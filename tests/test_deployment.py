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
