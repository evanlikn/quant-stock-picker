"""User accounts and per-user notification settings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_picker.auth.passwords import hash_password, verify_password
from quant_picker.config import load_settings
from quant_picker.notifications.credentials import (
    WPUSH_CHANNEL,
    EmailCredentials,
    WPushCredentials,
    email_credentials_from_env,
    wpush_credentials_from_env,
)
from quant_picker.security.crypto import (
    SecretUndecryptable,
    decrypt_secret,
    encrypt_secret,
    key_fingerprint,
)
from quant_picker.storage.models import User, UserNotificationSetting

logger = logging.getLogger(__name__)


class UsernameTaken(ValueError):
    pass


@dataclass(frozen=True)
class UserNotifyConfig:
    """Resolved push configuration for one user."""

    email_enabled: bool
    wechat_enabled: bool
    trigger: str
    intraday_trigger: str
    email: EmailCredentials
    wpush: WPushCredentials
    # A stored credential the active key cannot read. The channel is forced off
    # rather than falling back to .env, which would send this user's alerts to
    # the shared mailbox.
    email_unreadable: bool = False
    wpush_unreadable: bool = False

    @property
    def needs_recredential(self) -> bool:
        return self.email_unreadable or self.wpush_unreadable


# --- Users ---
def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


def get_user(session: Session, username: str) -> User | None:
    return session.scalar(
        select(User).where(func.lower(User.username) == username.strip().lower())
    )


def get_user_by_id(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def create_user(
    session: Session,
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    email: str | None = None,
    is_admin: bool = False,
) -> User:
    username = username.strip()
    if not username or not password:
        raise ValueError("用户名和密码不能为空")
    if get_user(session, username):
        raise UsernameTaken(f"用户名 {username} 已存在")
    user = User(
        username=username,
        display_name=(display_name or username).strip(),
        email=(email or "").strip() or None,
        password_hash=hash_password(password),
        is_admin=is_admin,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def set_password(session: Session, user_id: int, password: str) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("用户不存在")
    user.password_hash = hash_password(password)
    session.commit()


def change_password(
    session: Session, user_id: int, current_password: str, new_password: str
) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("用户不存在")
    if not verify_password(current_password, user.password_hash):
        raise ValueError("当前密码不正确")
    if len(new_password) < 6:
        raise ValueError("新密码至少 6 位")
    user.password_hash = hash_password(new_password)
    session.commit()


def set_active(session: Session, user_id: int, active: bool) -> None:
    user = session.get(User, user_id)
    if user is None:
        return
    user.is_active = active
    session.commit()


def touch_login(session: Session, user_id: int) -> None:
    user = session.get(User, user_id)
    if user is None:
        return
    user.last_login_at = datetime.utcnow()
    session.commit()


def build_credentials(session: Session) -> dict[str, Any]:
    """Shape active accounts into the dict streamlit-authenticator expects."""
    usernames: dict[str, Any] = {}
    for user in list_users(session):
        if not user.is_active:
            continue
        usernames[user.username] = {
            "name": user.display_name or user.username,
            "email": user.email or "",
            "password": user.password_hash,
            "logged_in": False,
        }
    return {"usernames": usernames}


# --- Notification settings ---
def get_notification_setting(
    session: Session, user_id: int
) -> UserNotificationSetting | None:
    return session.scalar(
        select(UserNotificationSetting).where(
            UserNotificationSetting.user_id == user_id
        )
    )


def get_or_create_notification_setting(
    session: Session, user_id: int
) -> UserNotificationSetting:
    """Fetch the user's row, seeding it from the shared .env on first access.

    Before the multi-user split everyone shared one set of credentials in
    ``.env``. Creating an empty row here would silently switch a working
    deployment's notifications off, so the first row inherits whatever the
    global config already had.
    """
    row = get_notification_setting(session, user_id)
    if row is not None:
        return row

    defaults = load_settings().get("notifications", {}) or {}
    env_email = email_credentials_from_env()
    env_wpush = wpush_credentials_from_env()
    row = UserNotificationSetting(
        user_id=user_id,
        email_enabled=bool(defaults.get("email_enabled", False)) and env_email.configured,
        wechat_enabled=bool(defaults.get("wechat_enabled", False)) and env_wpush.configured,
        trigger=str(defaults.get("trigger", "daily_summary")),
        intraday_trigger=str(defaults.get("intraday_trigger", "signal_change")),
        smtp_host=env_email.host,
        smtp_port=env_email.port,
        smtp_user=env_email.user,
        smtp_password_enc=encrypt_secret(env_email.password),
        email_to=env_email.to_addr,
        wpush_apikey_enc=encrypt_secret(env_wpush.apikey if env_wpush.configured else None),
        wpush_channel=env_wpush.channel,
        key_fingerprint=key_fingerprint(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def save_notification_setting(
    session: Session,
    user_id: int,
    *,
    email_enabled: bool,
    wechat_enabled: bool,
    trigger: str,
    intraday_trigger: str,
    smtp_host: str | None,
    smtp_port: int | None,
    smtp_user: str | None,
    smtp_password: str | None,
    email_to: str | None,
    wpush_apikey: str | None,
) -> UserNotificationSetting:
    """Persist a user's push config; ``None`` secrets keep the stored value."""
    row = get_or_create_notification_setting(session, user_id)
    row.email_enabled = email_enabled
    row.wechat_enabled = wechat_enabled
    row.trigger = trigger
    row.intraday_trigger = intraday_trigger
    row.smtp_host = (smtp_host or "").strip() or None
    row.smtp_port = int(smtp_port) if smtp_port else None
    row.smtp_user = (smtp_user or "").strip() or None
    row.email_to = (email_to or "").strip() or None
    row.wpush_channel = WPUSH_CHANNEL
    if smtp_password is not None:
        row.smtp_password_enc = encrypt_secret(smtp_password.strip()) or None
    if wpush_apikey is not None:
        row.wpush_apikey_enc = encrypt_secret(wpush_apikey.strip()) or None

    # Only claim the current key once every stored ciphertext was written with
    # it. Editing just the SMTP host must not stamp a fresh fingerprint onto a
    # password that an older key encrypted, which would hide the mismatch.
    rewrote_smtp = smtp_password is not None or row.smtp_password_enc is None
    rewrote_wpush = wpush_apikey is not None or row.wpush_apikey_enc is None
    if rewrote_smtp and rewrote_wpush:
        row.key_fingerprint = key_fingerprint()
    row.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(row)
    return row


def resolve_notify_config(
    session: Session, user_id: int, defaults: dict[str, Any] | None = None
) -> UserNotifyConfig:
    """Merge the user's row with settings.yaml defaults and the shared .env.

    The ``.env`` fallback keeps the single-user deployment working after the
    migration: whoever has not filled in the form yet still sends through the
    credentials that used to be global.
    """
    defaults = defaults or {}
    default_trigger = str(defaults.get("trigger", "daily_summary"))
    default_intraday = str(defaults.get("intraday_trigger", "signal_change"))
    env_email = email_credentials_from_env()
    env_wpush = wpush_credentials_from_env()

    row = get_notification_setting(session, user_id)
    if row is None:
        return UserNotifyConfig(
            email_enabled=bool(defaults.get("email_enabled", False))
            and env_email.configured,
            wechat_enabled=bool(defaults.get("wechat_enabled", False))
            and env_wpush.configured,
            trigger=default_trigger,
            intraday_trigger=default_intraday,
            email=env_email,
            wpush=env_wpush,
        )

    try:
        smtp_password = decrypt_secret(row.smtp_password_enc)
        email_unreadable = False
    except SecretUndecryptable:
        smtp_password, email_unreadable = None, True
    try:
        wpush_apikey = decrypt_secret(row.wpush_apikey_enc)
        wpush_unreadable = False
    except SecretUndecryptable:
        wpush_apikey, wpush_unreadable = None, True

    if email_unreadable or wpush_unreadable:
        logger.error(
            "用户 %s 的推送凭据无法解密（密钥指纹 %s，当前 %s），已停用相关通道，"
            "请在「推送设置」页重新填写",
            user_id,
            row.key_fingerprint or "未记录",
            key_fingerprint() or "未配置",
        )

    email = EmailCredentials(
        host=row.smtp_host,
        port=int(row.smtp_port or 465),
        user=row.smtp_user,
        password=smtp_password,
        to_addr=row.email_to,
    )
    wpush = WPushCredentials(apikey=wpush_apikey)
    return UserNotifyConfig(
        email_enabled=bool(row.email_enabled) and not email_unreadable,
        wechat_enabled=bool(row.wechat_enabled) and not wpush_unreadable,
        trigger=row.trigger or default_trigger,
        intraday_trigger=row.intraday_trigger or default_intraday,
        # The .env fallback only covers users who never configured a channel.
        # An unreadable secret means they did configure one, so falling back
        # would push their alerts to the shared mailbox.
        email=email if email.configured or email_unreadable else env_email,
        wpush=wpush if wpush.configured or wpush_unreadable else env_wpush,
        email_unreadable=email_unreadable,
        wpush_unreadable=wpush_unreadable,
    )


def audit_credential_keys(session: Session) -> list[str]:
    """Return the usernames whose stored credentials the active key cannot read.

    Checked by actually attempting a decryption rather than trusting the
    recorded fingerprint, so rows written before the fingerprint column existed
    are still covered.
    """
    broken: list[str] = []
    rows = session.scalars(select(UserNotificationSetting)).all()
    for row in rows:
        if not (row.smtp_password_enc or row.wpush_apikey_enc):
            continue
        try:
            decrypt_secret(row.smtp_password_enc)
            decrypt_secret(row.wpush_apikey_enc)
        except SecretUndecryptable:
            user = session.get(User, row.user_id)
            broken.append(user.username if user else f"user_id={row.user_id}")
    return broken


def warn_on_credential_key_change(session: Session) -> list[str]:
    """Log a startup banner when a replaced key orphaned stored credentials."""
    broken = audit_credential_keys(session)
    if broken:
        logger.error(
            "QUANT_PICKER_SECRET_KEY 与数据库中的推送凭据不匹配，"
            "以下用户的推送已停用，需要重新填写凭据：%s",
            "、".join(broken),
        )
    return broken
