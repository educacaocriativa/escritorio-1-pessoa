"""Integrações: CRUD de chaves + captura pública de lead (site externo → CRM)."""
from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.integrations.models import IntegrationKey, PublicIntegrationKey
from app.modules.integrations.schemas import LeadCapture

# Limite simples em memória (não sobrevive a múltiplas réplicas — aceitável no estágio atual,
# mesmo racional de custo do Golden Rule #4). Protege contra uma chave vazada/reaproveitada
# gerando spam de leads (e, por tabela, disparando ações reais do funil de auto-enroll).
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 30
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


class IntegrationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _rate_limited(key_hash: str) -> bool:
    now = time.monotonic()
    bucket = _rate_buckets[key_hash]
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_MAX_REQUESTS:
        return True
    bucket.append(now)
    return False


def _format_notes(notes: str | None, fields: dict[str, str] | None) -> str:
    parts = [notes.strip()] if notes and notes.strip() else []
    if fields:
        lines = "\n".join(f"{k}: {v}" for k, v in fields.items() if v)
        if lines:
            parts.append(f"Campos do formulário externo:\n{lines}")
    return "\n\n".join(parts)


# ── CRUD autenticado ────────────────────────────────────


def create_key(
    db: Session, *, tenant_id: str, actor: str, label: str
) -> tuple[IntegrationKey, str]:
    raw_key = secrets.token_urlsafe(32)
    key_hash = _hash(raw_key)
    key = IntegrationKey(
        tenant_id=tenant_id, label=label, key_prefix=raw_key[:8], key_hash=key_hash
    )
    db.add(key)
    db.add(PublicIntegrationKey(key_hash=key_hash, tenant_id=tenant_id))
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="integration_key.create", target=key.id
    )
    db.commit()
    db.refresh(key)
    return key, raw_key


def list_keys(db: Session) -> list[IntegrationKey]:
    return list(db.scalars(select(IntegrationKey).order_by(IntegrationKey.created_at.desc())).all())


def get_key(db: Session, key_id: str) -> IntegrationKey:
    key = db.get(IntegrationKey, key_id)
    if key is None:
        raise IntegrationError("Chave não encontrada", 404)
    return key


def revoke_key(db: Session, *, key_id: str, tenant_id: str, actor: str) -> IntegrationKey:
    key = get_key(db, key_id)
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        snap = db.get(PublicIntegrationKey, key.key_hash)
        if snap is not None:
            db.delete(snap)
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="integration_key.revoke", target=key.id
        )
        db.commit()
        db.refresh(key)
    return key


# ── Público (sem login) ─────────────────────────────────


def capture_lead(db: Session, *, raw_key: str, data: LeadCapture, session_factory) -> None:
    """Formulário externo → cria um LEAD no CRM do tenant dono da chave (source="api")."""
    key_hash = _hash(raw_key)
    if _rate_limited(key_hash):
        raise IntegrationError("Muitas requisições — tente novamente em instantes", 429)
    snap = db.get(PublicIntegrationKey, key_hash)
    if snap is None:
        raise IntegrationError("Chave inválida ou revogada", 401)

    from app.modules.crm import service as crm_service
    from app.modules.crm.schemas import ClientCreate

    with session_factory(snap.tenant_id) as tdb:
        crm_service.create_client(
            tdb, tenant_id=snap.tenant_id, actor="integracao:lead",
            data=ClientCreate(
                name=data.name,
                email=str(data.email) if data.email else None,
                phone=data.phone,
                notes=_format_notes(data.notes, data.fields),
                source="api",
            ),
        )
