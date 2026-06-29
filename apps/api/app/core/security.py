"""Primitivas de segurança: hash de senha e tokens JWT."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# bcrypt opera sobre no máx. 72 bytes; truncamos explicitamente (comportamento documentado).
_BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(claims: dict[str, Any]) -> str:
    to_encode = claims.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire, "iat": datetime.now(UTC)})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def generate_reset_token() -> tuple[str, str]:
    """Retorna (token_cru, hash). Só o hash é persistido; o cru vai ao usuário (e-mail/link)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    # sha256 (determinístico) p/ permitir lookup; o token tem entropia alta o bastante.
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
