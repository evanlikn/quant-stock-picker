from __future__ import annotations

import pytest

from quant_picker.auth import service
from quant_picker.notifications.credentials import WPUSH_CHANNEL
from quant_picker.security.crypto import (
    SecretUndecryptable,
    decrypt_secret,
    encrypt_secret,
    key_fingerprint,
)


def _save(session, user_id, **overrides):
    payload = dict(
        email_enabled=True,
        wechat_enabled=True,
        trigger="daily_summary",
        intraday_trigger="signal_change",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_user="me@example.com",
        smtp_password="app-token",
        email_to="me@example.com",
        wpush_apikey="wpush-secret-key",
    )
    payload.update(overrides)
    return service.save_notification_setting(session, user_id, **payload)


def test_secrets_are_encrypted_at_rest(session):
    user = service.create_user(session, username="alice", password="pwd")
    row = _save(session, user.id)

    assert row.smtp_password_enc != "app-token"
    assert decrypt_secret(row.smtp_password_enc) == "app-token"
    assert decrypt_secret(row.wpush_apikey_enc) == "wpush-secret-key"


def test_passing_none_keeps_the_stored_secret(session):
    user = service.create_user(session, username="alice", password="pwd")
    _save(session, user.id)
    row = _save(session, user.id, smtp_password=None, wpush_apikey=None, email_to="new@example.com")

    assert decrypt_secret(row.smtp_password_enc) == "app-token"
    assert row.email_to == "new@example.com"


def test_resolve_config_returns_user_credentials(session):
    alice = service.create_user(session, username="alice", password="pwd")
    bob = service.create_user(session, username="bob", password="pwd")
    _save(session, alice.id)
    _save(session, bob.id, smtp_user="bob@example.com", email_to="bob@example.com")

    alice_cfg = service.resolve_notify_config(session, alice.id)
    bob_cfg = service.resolve_notify_config(session, bob.id)

    assert alice_cfg.email.to_addr == "me@example.com"
    assert bob_cfg.email.to_addr == "bob@example.com"
    assert alice_cfg.email_enabled and alice_cfg.wechat_enabled


def test_wpush_channel_is_fixed(session):
    """WPUSH 只有 wechat 表示微信公众号，通道不对用户开放，也不可被写坏。"""
    user = service.create_user(session, username="alice", password="pwd")
    row = _save(session, user.id)
    assert row.wpush_channel == WPUSH_CHANNEL == "wechat"
    assert service.resolve_notify_config(session, user.id).wpush.channel == "wechat"


def test_user_without_settings_defaults_to_disabled(session):
    user = service.create_user(session, username="alice", password="pwd")
    config = service.resolve_notify_config(session, user.id)

    assert config.email_enabled is False
    assert config.wechat_enabled is False
    assert config.intraday_trigger == "signal_change"


def _rotate_key(monkeypatch):
    """Simulate restoring a database without its config/.env."""
    import os

    from cryptography.fernet import Fernet

    monkeypatch.setitem(os.environ, "QUANT_PICKER_SECRET_KEY", Fernet.generate_key().decode())


def test_undecryptable_secret_raises_instead_of_returning_none(session, monkeypatch):
    """Silently returning None here is what made a lost key look like 'not configured'."""
    ciphertext = encrypt_secret("app-token")
    _rotate_key(monkeypatch)

    with pytest.raises(SecretUndecryptable):
        decrypt_secret(ciphertext)


def test_empty_ciphertext_is_not_an_error(session):
    assert decrypt_secret(None) is None
    assert decrypt_secret("") is None


def test_lost_key_disables_channels_without_falling_back_to_env(session, monkeypatch):
    """A lost key must not reroute this user's alerts to the shared .env mailbox."""
    monkeypatch.setenv("SMTP_HOST", "smtp.shared.com")
    monkeypatch.setenv("SMTP_USER", "shared@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "shared-token")
    monkeypatch.setenv("EMAIL_TO", "shared@example.com")
    monkeypatch.setenv("WPUSH_APIKEY", "shared-wpush-key")

    user = service.create_user(session, username="alice", password="pwd")
    _save(session, user.id)
    _rotate_key(monkeypatch)
    session.expire_all()

    config = service.resolve_notify_config(session, user.id)

    assert config.email_unreadable and config.wpush_unreadable
    assert config.needs_recredential
    assert config.email_enabled is False
    assert config.wechat_enabled is False
    assert config.email.to_addr != "shared@example.com"
    assert config.wpush.apikey != "shared-wpush-key"


def test_audit_reports_users_whose_credentials_are_orphaned(session, monkeypatch):
    alice = service.create_user(session, username="alice", password="pwd")
    bob = service.create_user(session, username="bob", password="pwd")
    _save(session, alice.id)

    assert service.audit_credential_keys(session) == []

    _rotate_key(monkeypatch)
    session.expire_all()

    # bob never stored anything, so only alice needs to re-enter credentials
    assert service.audit_credential_keys(session) == ["alice"]
    assert service.get_notification_setting(session, bob.id) is None


def test_fingerprint_tracks_the_key_that_wrote_the_row(session, monkeypatch):
    user = service.create_user(session, username="alice", password="pwd")
    row = _save(session, user.id)

    assert row.key_fingerprint == key_fingerprint()

    _rotate_key(monkeypatch)
    session.expire_all()
    stale = service.get_notification_setting(session, user.id)
    assert stale.key_fingerprint != key_fingerprint()


def test_editing_other_fields_keeps_the_original_fingerprint(session, monkeypatch):
    """Stamping the current key onto secrets an older key wrote would hide the mismatch."""
    user = service.create_user(session, username="alice", password="pwd")
    original = _save(session, user.id).key_fingerprint

    _rotate_key(monkeypatch)
    session.expire_all()
    row = _save(session, user.id, smtp_password=None, wpush_apikey=None, email_to="new@example.com")

    assert row.key_fingerprint == original
    assert row.email_to == "new@example.com"


def test_fingerprint_is_not_the_encryption_key(monkeypatch):
    """A plain sha256 digest would *be* the derived Fernet key for a passphrase."""
    import base64
    import hashlib

    monkeypatch.setenv("QUANT_PICKER_SECRET_KEY", "a-plain-passphrase")
    derived = base64.urlsafe_b64encode(hashlib.sha256(b"a-plain-passphrase").digest()).decode()

    assert key_fingerprint() not in derived
    assert len(key_fingerprint()) == 16
