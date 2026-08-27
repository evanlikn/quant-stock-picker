"""Symmetric encryption for user-supplied credentials (SMTP password, WPUSH key).

Secrets live in the database because each user configures their own push
channels, so they cannot sit in a shared ``.env``. They are encrypted at rest
with Fernet using ``QUANT_PICKER_SECRET_KEY``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from quant_picker.config import load_env, project_root

logger = logging.getLogger(__name__)

_ENV_KEY = "QUANT_PICKER_SECRET_KEY"


class SecretKeyMissing(RuntimeError):
    pass


class SecretUndecryptable(RuntimeError):
    """Stored ciphertext cannot be read with the active key.

    Almost always means QUANT_PICKER_SECRET_KEY was lost or replaced while the
    database was kept. The credential is unrecoverable and must be re-entered.
    """


def _derive_fernet_key(raw: str) -> bytes:
    """Accept either a real Fernet key or any passphrase."""
    candidate = raw.strip()
    try:
        if len(base64.urlsafe_b64decode(candidate.encode())) == 32:
            return candidate.encode()
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(candidate.encode()).digest())


def _env_file() -> Path:
    root = project_root()
    for candidate in (root / ".env", root / "config" / ".env"):
        if candidate.exists():
            return candidate
    return root / "config" / ".env"


def ensure_secret_key() -> str:
    """Return the secret key, generating and persisting one on first run."""
    load_env()
    existing = os.getenv(_ENV_KEY, "").strip()
    if existing:
        return existing

    generated = Fernet.generate_key().decode()
    path = _env_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n# 用户推送凭据加密密钥，丢失后已保存的密码/APIKEY 将无法解密\n")
        f.write(f"{_ENV_KEY}={generated}\n")
    os.environ[_ENV_KEY] = generated
    logger.warning("已生成 %s 并写入 %s，请妥善备份", _ENV_KEY, path)
    return generated


def _fernet() -> Fernet:
    load_env()
    raw = os.getenv(_ENV_KEY, "").strip()
    if not raw:
        raise SecretKeyMissing(
            f"缺少 {_ENV_KEY}，无法加解密推送凭据。请在 config/.env 中配置该密钥。"
        )
    return Fernet(_derive_fernet_key(raw))


def encrypt_secret(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str | None) -> str | None:
    """Return the plaintext, or ``None`` when nothing was stored.

    Raises ``SecretUndecryptable`` when a value *is* stored but the active key
    cannot read it. Callers must not treat that as "unconfigured": doing so
    silently falls back to the shared .env credentials and pushes one user's
    alerts to whatever mailbox that file happens to point at.
    """
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, SecretKeyMissing) as exc:
        raise SecretUndecryptable(
            f"推送凭据无法解密，{_ENV_KEY} 可能已变更或丢失，需要重新填写凭据"
        ) from exc


def key_fingerprint(raw: str | None = None) -> str:
    """Short identifier for the active key, safe to store next to ciphertext.

    Deliberately *not* plain sha256 of the key: ``_derive_fernet_key`` uses
    exactly that to build the Fernet key from a passphrase, so an unsalted
    digest in the database would be the encryption key itself.
    """
    if raw is None:
        load_env()
        raw = os.getenv(_ENV_KEY, "")
    raw = raw.strip()
    if not raw:
        return ""
    return hashlib.sha256(f"fingerprint:{raw}".encode()).hexdigest()[:16]


def mask_secret(plaintext: str | None) -> str:
    if not plaintext:
        return ""
    if len(plaintext) <= 8:
        return "*" * len(plaintext)
    return f"{plaintext[:4]}{'*' * 6}{plaintext[-4:]}"


def random_password(length: int = 12) -> str:
    return secrets.token_urlsafe(length)[:length]
