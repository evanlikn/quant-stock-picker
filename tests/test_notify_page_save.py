"""Saving a replacement WPUSH APIKEY through the 推送设置 form must persist it."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from quant_picker.auth import service
from quant_picker.auth.guard import CurrentUser
from quant_picker.security.crypto import decrypt_secret

PAGE = "src/quant_picker/web/pages/3_推送设置.py"


@pytest.fixture
def logged_in(monkeypatch, session):
    from quant_picker.auth import guard

    user = service.create_user(session, username="alice", password="pwd", is_admin=True)
    current = CurrentUser(
        id=user.id, username=user.username, display_name=user.username, is_admin=True
    )
    monkeypatch.setattr(guard, "require_login", lambda: current)
    monkeypatch.setattr(guard, "render_sidebar_account", lambda _u: None)
    monkeypatch.setattr(guard, "current_user_id", lambda: current.id)
    return current


def _stored_key(user_id):
    from quant_picker.storage.models import get_session_factory

    with get_session_factory()() as fresh:
        row = service.get_notification_setting(fresh, user_id)
        return decrypt_secret(row.wpush_apikey_enc) if row else None


def _apikey_input(app):
    return next(box for box in app.text_input if "APIKEY" in box.label)


def test_typing_a_new_key_over_an_existing_one_persists(logged_in, session):
    service.save_notification_setting(
        session,
        logged_in.id,
        email_enabled=False,
        wechat_enabled=True,
        trigger="daily_summary",
        intraday_trigger="signal_change",
        smtp_host=None,
        smtp_port=None,
        smtp_user=None,
        smtp_password=None,
        email_to=None,
        wpush_apikey="OLD-shared-key-from-env",
    )

    app = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not app.exception

    _apikey_input(app).set_value("WPUSHmybrandnewkey000000000000ab")
    app.button[0].click().run()
    assert not app.exception

    assert _stored_key(logged_in.id) == "WPUSHmybrandnewkey000000000000ab"


def test_key_is_stored_exactly_as_typed(logged_in, session):
    """The field used to be pre-filled with a '………' sentinel. Typing after it
    instead of replacing it saved '………<key>', which WPUSH rejects as a bad
    API key -- and a password field gives no way to see that."""
    service.save_notification_setting(
        session,
        logged_in.id,
        email_enabled=False,
        wechat_enabled=True,
        trigger="daily_summary",
        intraday_trigger="signal_change",
        smtp_host=None,
        smtp_port=None,
        smtp_user=None,
        smtp_password=None,
        email_to=None,
        wpush_apikey="OLD-key",
    )

    app = AppTest.from_file(PAGE, default_timeout=60).run()
    assert _apikey_input(app).value == "", "输入框不应预填任何占位内容"

    _apikey_input(app).set_value("  WPUSHpaddedkey0000000000000000  ")
    app.button[0].click().run()

    saved = _stored_key(logged_in.id)
    assert saved == "WPUSHpaddedkey0000000000000000"
    assert "…" not in saved


def test_untouched_placeholder_keeps_the_stored_key(logged_in, session):
    service.save_notification_setting(
        session,
        logged_in.id,
        email_enabled=False,
        wechat_enabled=True,
        trigger="daily_summary",
        intraday_trigger="signal_change",
        smtp_host=None,
        smtp_port=None,
        smtp_user=None,
        smtp_password=None,
        email_to=None,
        wpush_apikey="KEEP-this-key",
    )

    app = AppTest.from_file(PAGE, default_timeout=60).run()
    app.button[0].click().run()
    assert not app.exception

    assert _stored_key(logged_in.id) == "KEEP-this-key"


def test_first_time_key_is_saved(logged_in):
    app = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not app.exception

    _apikey_input(app).set_value("WPUSHfirsttimekey00000000000000c")
    app.button[0].click().run()
    assert not app.exception

    assert _stored_key(logged_in.id) == "WPUSHfirsttimekey00000000000000c"
