"""Ciclo de vida da credencial de máquina: emitir, resolver, listar, revogar."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_reset_token, hash_token
from app.modules.machine_tokens.models import SCOPES, MachineToken


class MachineTokenError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def create_token(
    db: Session, *, tenant_id: str, name: str, scope: str
) -> tuple[MachineToken, str]:
    """Emite e devolve `(linha, token_cru)`. O cru é mostrado UMA vez e nunca mais."""
    if scope not in SCOPES:
        raise MachineTokenError(f"Escopo desconhecido: {scope}", 422)
    raw, hashed = generate_reset_token()  # mesmo par sha256 do reset de senha e do Atalho
    token = MachineToken(
        tenant_id=tenant_id, name=name.strip() or "Integração", token_hash=hashed, scope=scope
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw


def resolve(db: Session, *, raw: str, scope: str) -> MachineToken:
    """Resolve o token cru. Desconhecido, revogado ou de outro escopo → 401, sem distinguir.

    Diferente de `device_tokens.resolve`, que separa 401 de 403: o contrato da ingestão
    (spec §6.1) só conhece 401 para credencial, e dizer a quem não se autenticou que "o token
    existe, só não serve aqui" é informação de graça para quem testa um token vazado.

    Marca `last_used_at` para quem administra enxergar credencial abandonada.
    """
    token = db.scalar(select(MachineToken).where(MachineToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None or token.scope != scope:
        raise MachineTokenError("Credencial inválida", 401)
    token.last_used_at = datetime.now(UTC)
    db.commit()
    return token


def list_tokens(db: Session, *, tenant_id: str) -> list[MachineToken]:
    """Ativas E revogadas, mais nova primeiro — é a visão de quem administra, não de quem usa.

    Filtro explícito por `tenant_id`: a tabela é global (sem RLS), mesma exceção documentada
    de `users` na Regra de Ouro nº 1.
    """
    stmt = (
        select(MachineToken)
        .where(MachineToken.tenant_id == tenant_id)
        .order_by(MachineToken.created_at.desc(), MachineToken.id.desc())
    )
    return list(db.scalars(stmt).all())


def revoke(db: Session, *, token_id: str) -> MachineToken:
    """Revoga. Revogar de novo não reescreve a data: ela é a evidência de QUANDO parou."""
    token = db.get(MachineToken, token_id)
    if token is None:
        raise MachineTokenError("Credencial não encontrada", 404)
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
        db.commit()
    return token
