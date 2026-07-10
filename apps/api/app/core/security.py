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


# Claims de identidade preservados ao reemitir (deslizar) a sessão. NÃO inclui exp/iat/abs_exp,
# que são recalculados a cada reemissão.
_SESSION_IDENTITY_CLAIMS = ("sub", "tenant_id", "role", "allowed_modules", "is_platform_admin")


def create_access_token(
    claims: dict[str, Any],
    *,
    absolute_expiry: datetime | None = None,
) -> str:
    """Emite um token de sessão com DUAS camadas de expiração (idle timeout LGPD — Story 1.3).

    - ``exp``: janela de INATIVIDADE (``session_idle_timeout_minutes``, ex. 30 min). É o que o
      JWT valida automaticamente: passou disso sem atividade, o token morre (fail-closed). É
      deslizado a cada atividade real do usuário via ``POST /auth/refresh``.
    - ``abs_exp``: teto ABSOLUTO da sessão (``jwt_expire_minutes``, 7 dias). Preserva a garantia
      de 7 dias do JWT como LIMITE MÁXIMO — a sessão nunca vive além disso, mesmo com atividade
      contínua. Reduzir a janela de idle NÃO afrouxa os 7 dias (AC3): eles seguem como teto.

    ``absolute_expiry`` é passado na reemissão para preservar o teto original do login.
    """
    now = datetime.now(UTC)
    ceiling = absolute_expiry or (now + timedelta(minutes=settings.jwt_expire_minutes))
    idle_expire = now + timedelta(minutes=settings.session_idle_timeout_minutes)
    # A janela de inatividade nunca ultrapassa o teto absoluto da sessão.
    expire = min(idle_expire, ceiling)
    to_encode = claims.copy()
    to_encode.update({"exp": expire, "iat": now, "abs_exp": int(ceiling.timestamp())})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def refresh_access_token(payload: dict[str, Any]) -> str | None:
    """Desliza a janela de inatividade de uma sessão, respeitando o teto absoluto de 7 dias.

    Recebe o ``payload`` de um token AINDA VÁLIDO (quem chama já garantiu, via
    ``decode_access_token``, que ele não expirou por inatividade). Retorna um novo token com a
    janela de idle renovada, ou ``None`` se:
    - o teto absoluto (``abs_exp``) já passou → a sessão atingiu o máximo de 7 dias; ou
    - o token não carrega ``abs_exp`` legível (ex.: token legado pré-Story 1.3).

    Fail-closed: na dúvida, recusa a reemissão (o usuário reloga). Não toca o banco.
    """
    abs_exp = payload.get("abs_exp")
    if abs_exp is None:
        return None
    try:
        ceiling_ts = float(abs_exp)
    except (TypeError, ValueError):
        return None
    if datetime.now(UTC).timestamp() >= ceiling_ts:
        return None
    identity = {k: payload[k] for k in _SESSION_IDENTITY_CLAIMS if k in payload}
    ceiling = datetime.fromtimestamp(ceiling_ts, tz=UTC)
    return create_access_token(identity, absolute_expiry=ceiling)


def generate_reset_token() -> tuple[str, str]:
    """Retorna (token_cru, hash). Só o hash é persistido; o cru vai ao usuário (e-mail/link)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    # sha256 (determinístico) p/ permitir lookup; o token tem entropia alta o bastante.
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
