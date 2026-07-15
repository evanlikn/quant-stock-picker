#!/usr/bin/env bash
# Initialize PostgreSQL for quant-stock-picker:
#   - create database (if missing)
#   - create project app user + dedicated schema
#   - write DATABASE_URL to config/.env (app user, not superuser)
#   - create application tables via init_db()
#
# Requires: psql, Python venv with project dependencies.
# Superuser credentials are only used for this one-time/ops script.
#
# Usage:
#   PG_SUPERUSER_PASSWORD=123456 ./scripts/init_postgres.sh
#
# Optional env:
#   PGHOST=127.0.0.1
#   PGPORT=5432
#   PG_SUPERUSER=postgres
#   PG_SUPERUSER_PASSWORD=...   (or PGPASSWORD)
#   PGDATABASE=quant_picker
#   APP_USER=quant_picker         (default: settings.yaml database.app_user)
#   APP_SCHEMA=quant_picker       (default: settings.yaml database.schema)
#   APP_PASSWORD=...              (default: random, written to config/.env)
#   SKIP_ENV=1                    (do not update config/.env)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export QUANT_PICKER_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PG_SUPERUSER="${PG_SUPERUSER:-postgres}"
PGDATABASE="${PGDATABASE:-quant_picker}"

if [[ -z "${PG_SUPERUSER_PASSWORD:-}" ]]; then
  PG_SUPERUSER_PASSWORD="${PGPASSWORD:-}"
fi
if [[ -z "${PG_SUPERUSER_PASSWORD:-}" ]]; then
  echo "Error: set PG_SUPERUSER_PASSWORD (or PGPASSWORD) for PostgreSQL superuser." >&2
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Error: .venv not found. Run: python -m venv .venv && pip install -e ." >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "Error: psql not found in PATH." >&2
  exit 1
fi

PYTHON="$ROOT/.venv/bin/python"

read -r APP_USER APP_SCHEMA <<< "$("$PYTHON" - <<'PY'
import yaml
from pathlib import Path
import os

root = Path(os.environ["QUANT_PICKER_ROOT"])
db = (yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}).get("database", {}) or {}
print(
    os.environ.get("APP_USER") or db.get("app_user", "quant_picker"),
    os.environ.get("APP_SCHEMA") or db.get("schema", "quant_picker"),
)
PY
)"

APP_USER="${APP_USER:-quant_picker}"
APP_SCHEMA="${APP_SCHEMA:-quant_picker}"

if [[ -z "${APP_PASSWORD:-}" ]]; then
  APP_PASSWORD="$("$PYTHON" -c "import secrets; print(secrets.token_urlsafe(24))")"
fi

# Escape single quotes for use inside SQL string literals
escape_sql_literal() {
  printf "%s" "$1" | sed "s/'/''/g"
}
APP_PASS_SQL="$(escape_sql_literal "$APP_PASSWORD")"

export PGPASSWORD="$PG_SUPERUSER_PASSWORD"
PSQL=(psql -h "$PGHOST" -p "$PGPORT" -U "$PG_SUPERUSER" -v ON_ERROR_STOP=1)

echo "==> Checking PostgreSQL connection (${PG_SUPERUSER}@${PGHOST}:${PGPORT})..."
"${PSQL[@]}" -d postgres -c "SELECT version();" >/dev/null

echo "==> Ensuring database '${PGDATABASE}' exists..."
DB_EXISTS="$("${PSQL[@]}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${PGDATABASE}'")"
if [[ "$DB_EXISTS" != "1" ]]; then
  createdb -h "$PGHOST" -p "$PGPORT" -U "$PG_SUPERUSER" "$PGDATABASE"
  echo "    created database ${PGDATABASE}"
else
  echo "    database already exists"
fi

echo "==> Ensuring app role '${APP_USER}' and schema '${APP_SCHEMA}'..."
"${PSQL[@]}" -d "$PGDATABASE" <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${APP_USER}') THEN
    CREATE ROLE ${APP_USER} LOGIN PASSWORD '${APP_PASS_SQL}';
  ELSE
    ALTER ROLE ${APP_USER} WITH LOGIN PASSWORD '${APP_PASS_SQL}';
  END IF;
END
\$\$;

CREATE SCHEMA IF NOT EXISTS ${APP_SCHEMA} AUTHORIZATION ${APP_USER};
ALTER ROLE ${APP_USER} SET search_path TO ${APP_SCHEMA};
REVOKE CREATE ON SCHEMA public FROM ${APP_USER};
GRANT CONNECT ON DATABASE ${PGDATABASE} TO ${APP_USER};
GRANT USAGE, CREATE ON SCHEMA ${APP_SCHEMA} TO ${APP_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA ${APP_SCHEMA} GRANT ALL ON TABLES TO ${APP_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA ${APP_SCHEMA} GRANT ALL ON SEQUENCES TO ${APP_USER};
SQL

if [[ "${SKIP_ENV:-}" != "1" ]]; then
  echo "==> Updating config/.env DATABASE_URL (app user, not superuser)..."
  ENV_FILE="$ROOT/config/.env"
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ROOT/config/.env.example" "$ENV_FILE"
  fi
  DATABASE_URL="postgresql+psycopg://${APP_USER}:${APP_PASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"
  "$PYTHON" - <<PY
import re
from pathlib import Path

env_path = Path("${ENV_FILE}")
text = env_path.read_text(encoding="utf-8")
url = """${DATABASE_URL}"""
if re.search(r"^DATABASE_URL=", text, flags=re.M):
    text = re.sub(r"^DATABASE_URL=.*$", f"DATABASE_URL={url}", text, flags=re.M)
else:
    text = text.rstrip() + (
        "\n\n# PostgreSQL（项目专用账号 ${APP_USER} / schema ${APP_SCHEMA}）\n"
        f"DATABASE_URL={url}\n"
    )
env_path.write_text(text, encoding="utf-8")
PY
else
  export DATABASE_URL="postgresql+psycopg://${APP_USER}:${APP_PASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"
  echo "==> SKIP_ENV=1, using DATABASE_URL from environment for init_db"
fi

echo "==> Creating application tables in schema '${APP_SCHEMA}'..."
cd "$ROOT"
source .venv/bin/activate
"$PYTHON" - <<'PY'
from quant_picker.config import clear_settings_cache, database_schema, uses_postgresql
from quant_picker.storage.db import get_engine, init_db
from sqlalchemy import text

clear_settings_cache()
if not uses_postgresql():
    raise SystemExit("DATABASE_URL is not PostgreSQL; check config/.env or SKIP_ENV setup.")

init_db()
schema = database_schema()
with get_engine().connect() as conn:
    rows = conn.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = :s ORDER BY tablename"),
        {"s": schema},
    ).fetchall()
print("    tables:", ", ".join(r[0] for r in rows) or "(none)")
PY

unset PGPASSWORD

echo
echo "Done."
echo "  Database : ${PGDATABASE} @ ${PGHOST}:${PGPORT}"
echo "  App user : ${APP_USER}"
echo "  Schema   : ${APP_SCHEMA}"
if [[ "${SKIP_ENV:-}" != "1" ]]; then
  echo "  Config   : config/.env (DATABASE_URL updated)"
fi
echo
echo "Start the app with:"
echo "  export QUANT_PICKER_ROOT=\$(pwd)"
echo "  ./scripts/run_web.sh"
