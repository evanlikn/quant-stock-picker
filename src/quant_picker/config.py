from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

Interval = str  # "1d" | "1h" | "1m"
Market = str  # "cn" | "us" | "hk"
Action = str  # "buy" | "hold" | "sell"


def project_root() -> Path:
    env = os.environ.get("QUANT_PICKER_ROOT")
    if env:
        return Path(env)
    # src/quant_picker/config.py -> project root
    return Path(__file__).resolve().parents[2]


@lru_cache
def load_settings() -> dict[str, Any]:
    path = project_root() / "config" / "settings.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_strategies_config() -> dict[str, Any]:
    path = project_root() / "config" / "strategies.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_screener_config() -> dict[str, Any]:
    path = project_root() / "config" / "screener.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_env() -> None:
    """Layer deployment settings: real environment > .env > .env.example.

    load_dotenv never overrides an existing variable, so loading .env first and
    the example second makes the example a defaults layer. That matters because
    the secret key is appended to a freshly created .env: without the fallback,
    a one-line .env would silently drop every documented default.
    """
    root = project_root()
    for candidate in (root / ".env", root / "config" / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
            break
    load_dotenv(root / "config" / ".env.example")


def env(name: str, default: str = "") -> str:
    """Read a deployment setting from the .env file (or real environment)."""
    load_env()
    return os.getenv(name, "").strip() or default


def clear_settings_cache() -> None:
    load_settings.cache_clear()
    load_strategies_config.cache_clear()
    load_screener_config.cache_clear()


def db_path() -> Path:
    rel = env("QUANT_PICKER_DB_PATH") or load_settings().get("database", {}).get(
        "path", "data/quant_picker.db"
    )
    path = Path(rel)
    if not path.is_absolute():
        path = project_root() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    """Resolve SQLAlchemy URL: DATABASE_URL env > settings.database.url > SQLite file."""
    env_url = env("DATABASE_URL")
    if env_url:
        return env_url
    cfg_url = (load_settings().get("database", {}) or {}).get("url", "")
    if cfg_url:
        return str(cfg_url).strip()
    return f"sqlite:///{db_path()}"


def database_schema() -> str:
    """PostgreSQL schema for project tables; ignored for SQLite."""
    return env("QUANT_PICKER_DB_SCHEMA") or str(
        (load_settings().get("database", {}) or {}).get("schema", "quant_picker")
    )


def sqlite_busy_timeout() -> float:
    """Seconds a SQLite connection waits for a competing writer before failing."""
    try:
        return float(env("QUANT_PICKER_SQLITE_TIMEOUT", "30"))
    except ValueError:
        return 30.0


def pg_idle_transaction_timeout() -> float:
    """Seconds PostgreSQL keeps an idle-in-transaction connection; 0 disables."""
    try:
        return float(env("QUANT_PICKER_PG_IDLE_TX_TIMEOUT", "120"))
    except ValueError:
        return 120.0


def log_level() -> str:
    return env("QUANT_PICKER_LOG_LEVEL", "INFO").upper()


def longbridge_app_key() -> str:
    return env("LONGBRIDGE_APP_KEY")


def longbridge_app_secret() -> str:
    return env("LONGBRIDGE_APP_SECRET")


def longbridge_access_token() -> str:
    return env("LONGBRIDGE_ACCESS_TOKEN")


def longbridge_configured() -> bool:
    """True when OpenAPI key, secret and access token are all present."""
    return bool(
        longbridge_app_key() and longbridge_app_secret() and longbridge_access_token()
    )


def web_host() -> str:
    """Address Streamlit listens on."""
    host = env("QUANT_PICKER_WEB_HOST")
    if not host:
        raise RuntimeError("缺少 QUANT_PICKER_WEB_HOST，请在 config/.env 中配置")
    return host


def web_port() -> int:
    """Port Streamlit listens on."""
    raw = env("QUANT_PICKER_WEB_PORT")
    if not raw:
        raise RuntimeError("缺少 QUANT_PICKER_WEB_PORT，请在 config/.env 中配置")
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("QUANT_PICKER_WEB_PORT 必须是整数") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("QUANT_PICKER_WEB_PORT 必须在 1-65535 之间")
    return port


def scheduler_timezone() -> str:
    return env("QUANT_PICKER_TIMEZONE") or str(
        (load_settings().get("scheduler", {}) or {}).get("timezone", "Asia/Shanghai")
    )


def auto_sync_intervals() -> list[str]:
    """Intervals updated by background scheduler; default daily only."""
    override = env("QUANT_PICKER_AUTO_SYNC_INTERVALS")
    if override:
        return [x.strip() for x in override.split(",") if x.strip()]
    intervals = (load_settings().get("scheduler", {}) or {}).get("auto_sync_intervals")
    if intervals:
        return [str(x) for x in intervals]
    return ["1d"]


def market_daily_run_schedule() -> dict[str, dict[str, str]]:
    """Per-market post-close daily job time (Asia/Shanghai) and cron weekdays."""
    sched = (load_settings().get("scheduler", {}) or {})
    custom = sched.get("market_daily_run")
    if custom:
        return {str(k).lower(): dict(v) for k, v in custom.items()}
    legacy = sched.get("daily_run_time", "15:35")
    return {
        "cn": {"time": legacy, "days": "mon-fri"},
        "hk": {"time": "16:35", "days": "mon-fri"},
        "us": {"time": "09:00", "days": "mon-sat"},
    }


def uses_postgresql() -> bool:
    return database_url().startswith("postgresql")
