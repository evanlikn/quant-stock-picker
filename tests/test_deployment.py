"""Regressions for a from-scratch server deployment (fresh DB, .env driven config)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from quant_picker import config
from quant_picker.auth.passwords import verify_password
from quant_picker.auth.service import get_user, list_users
from quant_picker.storage import models


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """A database that has never been touched, initialised through init_db()."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(models, "_persist_bootstrap_password", lambda *_: None)
    models._engine = None
    models._Session = None
    yield
    if models._engine is not None:
        models._engine.dispose()
    models._engine = None
    models._Session = None


def test_fresh_install_creates_admin(fresh_db, monkeypatch):
    """Without this the server boots with zero users and nobody can log in."""
    monkeypatch.setenv("QUANT_PICKER_ADMIN_USERNAME", "root")
    monkeypatch.setenv("QUANT_PICKER_ADMIN_PASSWORD", "s3cret-pass")

    models.init_db()

    with models.get_session_factory()() as session:
        users = list_users(session)
        assert len(users) == 1
        admin = get_user(session, "root")
        assert admin is not None
        assert admin.is_admin and admin.is_active
        assert verify_password("s3cret-pass", admin.password_hash)


def test_init_db_is_idempotent(fresh_db, monkeypatch):
    monkeypatch.setenv("QUANT_PICKER_ADMIN_PASSWORD", "s3cret-pass")

    models.init_db()
    models.init_db()

    with models.get_session_factory()() as session:
        assert len(list_users(session)) == 1


def test_generated_admin_password_is_persisted(fresh_db, monkeypatch):
    monkeypatch.delenv("QUANT_PICKER_ADMIN_PASSWORD", raising=False)
    written: dict[str, str] = {}
    monkeypatch.setattr(
        models,
        "_persist_bootstrap_password",
        lambda username, password: written.update(user=username, pwd=password),
    )

    models.init_db()

    assert written["user"] == os.getenv("QUANT_PICKER_ADMIN_USERNAME", "admin")
    with models.get_session_factory()() as session:
        admin = get_user(session, written["user"])
        assert verify_password(written["pwd"], admin.password_hash)


def test_sqlite_uses_wal(fresh_db, monkeypatch):
    """web and scheduler both write; the default journal makes refreshes fail."""
    monkeypatch.setenv("QUANT_PICKER_ADMIN_PASSWORD", "s3cret-pass")
    models.init_db()

    with models.get_engine().connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() >= 30_000


def test_sqlite_survives_a_concurrent_writer(fresh_db, monkeypatch):
    monkeypatch.setenv("QUANT_PICKER_ADMIN_PASSWORD", "s3cret-pass")
    models.init_db()
    factory = models.get_session_factory()

    # scheduler holds an open write transaction while the web app reads
    with factory() as writer, factory() as reader:
        writer.execute(
            text(
                "INSERT INTO users (username, display_name, password_hash, "
                "is_admin, is_active, created_at) "
                "VALUES ('w', 'w', 'x', 0, 1, '2026-01-01 00:00:00')"
            )
        )
        assert reader.execute(text("SELECT COUNT(*) FROM users")).scalar() == 1
        writer.commit()
        reader.rollback()
        assert reader.execute(text("SELECT COUNT(*) FROM users")).scalar() == 2


def test_concurrent_first_start_is_serialised(fresh_db, monkeypatch, tmp_path):
    """systemd starts web and scheduler together; both run init_db() at once."""
    import threading

    monkeypatch.setenv("QUANT_PICKER_ADMIN_PASSWORD", "s3cret-pass")
    models.get_engine()  # build the engine once, as separate processes would

    errors: list[BaseException] = []
    barrier = threading.Barrier(4)

    def worker():
        barrier.wait()
        try:
            models.init_db()
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with models.get_session_factory()() as session:
        assert len(list_users(session)) == 1


_LEGACY_WATCHLIST_DDL = """
CREATE TABLE watchlist_items (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(32) NOT NULL,
    display_name VARCHAR(128),
    market VARCHAR(8) NOT NULL,
    interval VARCHAR(8) NOT NULL,
    enabled BOOLEAN,
    notify_enabled BOOLEAN,
    wfo_status VARCHAR(16),
    last_optimized_at DATETIME,
    last_optimized_bar_time DATETIME,
    bars_since_optimization INTEGER,
    retrain_cycle_bars INTEGER,
    retrain_cycle_source VARCHAR(16),
    last_bar_time DATETIME,
    last_run_at DATETIME,
    added_at DATETIME,
    history_days INTEGER,
    position_manual_override BOOLEAN DEFAULT 0,
    position_entry_price FLOAT DEFAULT 0,
    position_entry_shares INTEGER DEFAULT 0,
    position_entry_atr FLOAT,
    position_entry_bar_time DATETIME,
    position_trailing_stop FLOAT,
    CONSTRAINT uq_watch UNIQUE (symbol, market, interval)
)
"""


@pytest.fixture
def legacy_sqlite_db(tmp_path, monkeypatch):
    """A SQLite file written by the single-user version, before user_id existed."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setenv("QUANT_PICKER_ADMIN_PASSWORD", "s3cret-pass")
    monkeypatch.setattr(models, "_persist_bootstrap_password", lambda *_: None)
    models._engine = None
    models._Session = None

    with models.get_engine().begin() as conn:
        conn.execute(text(_LEGACY_WATCHLIST_DDL))
        conn.execute(text("CREATE INDEX ix_watchlist_user ON watchlist_items (symbol)"))
        conn.execute(
            text(
                "INSERT INTO watchlist_items (symbol, market, interval, enabled, added_at) "
                "VALUES ('600519', 'cn', '1d', 1, '2026-01-01 00:00:00')"
            )
        )
    yield
    if models._engine is not None:
        models._engine.dispose()
    models._engine = None
    models._Session = None


def _add_watch(session, user_id, symbol="600519"):
    from quant_picker.storage.models import WatchlistItem

    item = WatchlistItem(user_id=user_id, symbol=symbol, market="cn", interval="1d")
    session.add(item)
    session.commit()
    return item


def test_legacy_sqlite_lets_two_users_hold_the_same_symbol(legacy_sqlite_db):
    """The old table made (symbol, market, interval) unique, so the second user
    to add 600519 was rejected. SQLite has no DROP CONSTRAINT, so the migration
    has to rebuild the table."""
    from quant_picker.auth import service

    models.init_db()

    with models.get_session_factory()() as session:
        constraints = {
            c["name"]
            for c in models.inspect(models.get_engine()).get_unique_constraints(
                "watchlist_items"
            )
        }
        assert "uq_watch" not in constraints
        assert "uq_watch_user" in constraints

        admin = get_user(session, os.getenv("QUANT_PICKER_ADMIN_USERNAME", "admin"))
        bob = service.create_user(session, username="bob", password="pwd")
        _add_watch(session, bob.id)

        owners = session.execute(
            text("SELECT user_id FROM watchlist_items WHERE symbol = '600519' ORDER BY user_id")
        ).scalars()
        assert list(owners) == sorted([admin.id, bob.id])


def test_legacy_rows_keep_their_data_and_go_to_the_admin(legacy_sqlite_db):
    models.init_db()

    with models.get_session_factory()() as session:
        admin = get_user(session, os.getenv("QUANT_PICKER_ADMIN_USERNAME", "admin"))
        row = session.execute(
            text("SELECT user_id, symbol, market, interval, enabled FROM watchlist_items")
        ).one()
        assert row.user_id == admin.id
        assert (row.symbol, row.market, row.interval) == ("600519", "cn", "1d")
        assert row.enabled


def test_legacy_migration_is_idempotent(legacy_sqlite_db):
    models.init_db()
    models.init_db()

    with models.get_session_factory()() as session:
        assert session.execute(text("SELECT COUNT(*) FROM watchlist_items")).scalar() == 1
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '%legacy%'")
            ).scalar()
            == 0
        )


def test_duplicate_symbol_for_one_user_is_still_rejected(legacy_sqlite_db):
    """The rebuild must not lose uniqueness altogether, only re-scope it."""
    from sqlalchemy.exc import IntegrityError

    from quant_picker.auth import service

    models.init_db()
    with models.get_session_factory()() as session:
        bob = service.create_user(session, username="bob", password="pwd")
        _add_watch(session, bob.id)
        with pytest.raises(IntegrityError):
            _add_watch(session, bob.id)


class TestEnvDrivenConfig:
    def test_database_url_switches_to_postgres(self, monkeypatch):
        url = "postgresql+psycopg://u:p@127.0.0.1:5432/quant_picker"
        monkeypatch.setenv("DATABASE_URL", url)
        assert config.database_url() == url
        assert config.uses_postgresql() is True

    def test_defaults_to_sqlite_file_when_url_absent(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("QUANT_PICKER_DB_PATH", str(tmp_path / "sub" / "app.db"))
        assert config.database_url() == f"sqlite:///{tmp_path / 'sub' / 'app.db'}"
        assert config.uses_postgresql() is False
        assert (tmp_path / "sub").is_dir()

    def test_relative_db_path_resolves_under_project_root(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("QUANT_PICKER_DB_PATH", "data/quant_picker.db")
        assert config.db_path() == config.project_root() / "data" / "quant_picker.db"

    def test_schema_timezone_and_intervals_come_from_env(self, monkeypatch):
        monkeypatch.setenv("QUANT_PICKER_DB_SCHEMA", "custom_schema")
        monkeypatch.setenv("QUANT_PICKER_TIMEZONE", "UTC")
        monkeypatch.setenv("QUANT_PICKER_AUTO_SYNC_INTERVALS", "1d, 1h")
        assert config.database_schema() == "custom_schema"
        assert config.scheduler_timezone() == "UTC"
        assert config.auto_sync_intervals() == ["1d", "1h"]

    def test_web_endpoint_comes_from_env(self, monkeypatch):
        monkeypatch.setenv("QUANT_PICKER_WEB_HOST", "0.0.0.0")
        monkeypatch.setenv("QUANT_PICKER_WEB_PORT", "8765")
        assert config.web_host() == "0.0.0.0"
        assert config.web_port() == 8765

    def test_invalid_web_port_is_rejected(self, monkeypatch):
        for value in ("bad", "0", "65536"):
            monkeypatch.setenv("QUANT_PICKER_WEB_PORT", value)
            with pytest.raises(RuntimeError, match="QUANT_PICKER_WEB_PORT"):
                config.web_port()

    def test_settings_yaml_remains_the_fallback(self, monkeypatch):
        for key in (
            "QUANT_PICKER_DB_SCHEMA",
            "QUANT_PICKER_TIMEZONE",
            "QUANT_PICKER_AUTO_SYNC_INTERVALS",
        ):
            monkeypatch.delenv(key, raising=False)
        assert config.database_schema() == "quant_picker"
        assert config.scheduler_timezone() == "Asia/Shanghai"
        assert config.auto_sync_intervals() == ["1d"]

    def test_busy_timeout_falls_back_on_garbage(self, monkeypatch):
        monkeypatch.setenv("QUANT_PICKER_SQLITE_TIMEOUT", "not-a-number")
        assert config.sqlite_busy_timeout() == 30.0
        monkeypatch.setenv("QUANT_PICKER_SQLITE_TIMEOUT", "5")
        assert config.sqlite_busy_timeout() == 5.0
