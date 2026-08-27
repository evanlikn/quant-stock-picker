"""bcrypt password hashing, kept free of model imports so migrations can use it."""

from __future__ import annotations

import bcrypt

_MAX_BCRYPT_BYTES = 72


def _truncate(password: str) -> bytes:
    """bcrypt rejects inputs longer than 72 bytes instead of silently trimming."""
    return password.encode("utf-8")[:_MAX_BCRYPT_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_truncate(password), password_hash.encode())
    except ValueError:
        return False
