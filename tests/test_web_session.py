"""The web layer must not leak a database connection per Streamlit rerun."""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from streamlit.testing.v1 import AppTest

from quant_picker.auth import service
from quant_picker.auth.guard import CurrentUser
from quant_picker.storage.models import get_engine


@pytest.fixture
def pool_counter():
    """Track connections checked out of, and returned to, the pool."""
    engine = get_engine()
    stats = {"out": 0, "in": 0}
    on_out = lambda *_: stats.__setitem__("out", stats["out"] + 1)  # noqa: E731
    on_in = lambda *_: stats.__setitem__("in", stats["in"] + 1)  # noqa: E731
    event.listen(engine, "checkout", on_out)
    event.listen(engine, "checkin", on_in)
    stats["held"] = lambda: stats["out"] - stats["in"]
    yield stats
    event.remove(engine, "checkout", on_out)
    event.remove(engine, "checkin", on_in)


@pytest.fixture
def logged_in(monkeypatch, session):
    from quant_picker.auth import guard

    user = service.create_user(session, username="alice", password="pwd", is_admin=True)
    current = CurrentUser(
        id=user.id, username=user.username, display_name=user.username, is_admin=True
    )
    monkeypatch.setattr(guard, "require_login", lambda: current)
    monkeypatch.setattr(guard, "render_sidebar_account", lambda _user: None)
    monkeypatch.setattr(guard, "current_user_id", lambda: current.id)
    return current


def test_reruns_do_not_accumulate_connections(logged_in, pool_counter):
    """One connection per browser session, however many times the script reruns."""
    app = AppTest.from_file("src/quant_picker/web/pages/2_建议历史.py", default_timeout=60)

    app.run()
    assert not app.exception
    after_first = pool_counter["held"]()

    for _ in range(5):
        app.run()
        assert not app.exception

    assert pool_counter["held"]() == after_first


class _StubAuthenticator:
    def login(self, **_kwargs):
        return None

    def logout(self, *_args, **_kwargs):
        return None


@pytest.fixture
def scoped_db():
    """db_session driven by a plain dict, so no Streamlit runtime is needed."""
    from quant_picker.web import db_session

    class _Stub:
        session_state: dict = {}

    original = db_session.st
    db_session.st = _Stub()
    try:
        yield db_session
    finally:
        db_session.release_web_session()
        db_session.st = original


class TestSessionScope:
    def test_the_same_session_is_reused(self, scoped_db):
        first = scoped_db.web_session()
        assert scoped_db.web_session() is first

    def test_release_returns_the_connection_but_keeps_the_session_usable(
        self, scoped_db, pool_counter
    ):
        session = scoped_db.web_session()
        session.execute(text("SELECT 1"))
        assert pool_counter["held"]() >= 1

        scoped_db.release_web_session()
        assert pool_counter["held"]() == 0

        # still usable: the next query just begins a fresh transaction
        assert session.execute(text("SELECT 1")).scalar() == 1
        assert scoped_db.web_session() is session

    def test_repeated_runs_hold_at_most_one_connection(self, scoped_db, pool_counter):
        for _ in range(10):
            scoped_db.release_web_session()  # what require_login does per rerun
            scoped_db.web_session().execute(text("SELECT 1"))
            assert pool_counter["held"]() == 1

    def test_release_is_safe_when_nothing_was_opened(self, scoped_db):
        scoped_db.release_web_session()
        scoped_db.release_web_session()

    def test_require_login_releases_the_previous_run(self, session, monkeypatch):
        """The wiring that makes the per-rerun release actually happen."""
        from quant_picker.auth import guard
        from quant_picker.web import db_session

        user = service.create_user(session, username="carol", password="pwd")
        released: list[bool] = []
        monkeypatch.setattr(
            db_session, "release_web_session", lambda: released.append(True)
        )
        monkeypatch.setattr(guard, "_bootstrap", lambda: True)
        monkeypatch.setattr(guard, "_build_authenticator", lambda: _StubAuthenticator())
        monkeypatch.setattr(
            guard.st, "session_state", {"authentication_status": True, "username": "carol"}
        )

        current = guard.require_login()

        assert current.id == user.id
        assert released == [True]

    def test_release_survives_a_broken_session(self, scoped_db, monkeypatch):
        session = scoped_db.web_session()
        monkeypatch.setattr(
            session, "close", lambda: (_ for _ in ()).throw(RuntimeError("connection gone"))
        )

        scoped_db.release_web_session()

        # the dead session was dropped, so the page gets a working one
        assert scoped_db.web_session() is not session
