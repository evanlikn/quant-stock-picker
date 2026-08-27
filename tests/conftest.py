from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))
os.environ.setdefault("QUANT_PICKER_ROOT", str(_ROOT))
# Models bind their MetaData schema at import time; force SQLite before importing
# anything from quant_picker so tests never touch the real PostgreSQL database.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(scope="session", autouse=True)
def _secret_key():
    os.environ["QUANT_PICKER_SECRET_KEY"] = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _isolate_dotenv(monkeypatch):
    """Keep the developer's real config/.env out of tests.

    load_env() re-populates os.environ from that file, which would otherwise
    undo monkeypatch.delenv and point tests at the live PostgreSQL database.
    """
    monkeypatch.setattr("quant_picker.config.load_dotenv", lambda *a, **k: False)


@pytest.fixture(autouse=True)
def temp_database(tmp_path, _secret_key, _isolate_dotenv):
    """Point the shared engine at a throwaway SQLite file for each test."""
    from quant_picker.storage import models

    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    models._engine = None
    models._Session = None
    models.Base.metadata.create_all(models.get_engine())
    yield
    if models._engine is not None:
        models._engine.dispose()
    models._engine = None
    models._Session = None


@pytest.fixture
def session():
    from quant_picker.storage.models import get_session_factory

    with get_session_factory()() as s:
        yield s
