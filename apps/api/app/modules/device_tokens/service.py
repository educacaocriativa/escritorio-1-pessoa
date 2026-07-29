"""Ciclo de vida do token de dispositivo: criar, resolver, listar, revogar."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_reset_token, hash_token
from app.modules.device_tokens.models import SCOPE_RECEIPT_UPLOAD, DeviceToken


class DeviceTokenError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def create_token(
    db: Session, *, tenant_id: str, user_id: str, name: str
) -> tuple[DeviceToken, str]:
    """Cria o token e devolve (linha, token_cru). O cru é mostrado UMA vez e nunca mais."""
    raw, hashed = generate_reset_token()  # reusa o par sha256 já validado do reset de senha
    token = DeviceToken(
        tenant_id=tenant_id, user_id=user_id, name=name.strip() or "Dispositivo",
        token_hash=hashed, scope=SCOPE_RECEIPT_UPLOAD,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw


def resolve(db: Session, *, raw: str, scope: str) -> DeviceToken:
    """Resolve o token cru. Fail-closed: qualquer dúvida vira 401/403, nunca acesso.

    Marca `last_used_at` para a tela de gerenciamento mostrar dispositivos abandonados.
    """
    token = db.scalar(select(DeviceToken).where(DeviceToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None:
        raise DeviceTokenError("Token de dispositivo inválido", 401)
    if token.scope != scope:
        raise DeviceTokenError("Token sem permissão para esta operação", 403)
    token.last_used_at = datetime.now(UTC)
    db.commit()
    return token


def list_tokens(db: Session, *, user_id: str) -> list[DeviceToken]:
    stmt = (
        select(DeviceToken)
        .where(DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
        .order_by(DeviceToken.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def revoke(db: Session, *, token_id: str, user_id: str) -> None:
    token = db.get(DeviceToken, token_id)
    if token is None or token.user_id != user_id:
        raise DeviceTokenError("Token não encontrado", 404)
    token.revoked_at = datetime.now(UTC)
    db.commit()
