"""Rotas de Integrações: CRUD de chaves (privado) + captura de lead (pública, sem login)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_db, get_tenant_session_factory
from app.modules.integrations import service
from app.modules.integrations.models import IntegrationKey
from app.modules.integrations.schemas import (
    IntegrationKeyCreate,
    IntegrationKeyCreated,
    IntegrationKeyOut,
    LeadCapture,
)

router = APIRouter(prefix="/integrations/leads", tags=["integrations-leads"])
public_router = APIRouter(prefix="/public/leads", tags=["integrations-leads-public"])

_guard = require_module("settings")


def _out(k: IntegrationKey) -> IntegrationKeyOut:
    return IntegrationKeyOut(
        id=k.id, label=k.label, key_prefix=k.key_prefix, revoked_at=k.revoked_at,
        created_at=k.created_at,
    )


def _err(e: service.IntegrationError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/keys", response_model=list[IntegrationKeyOut])
def list_keys(_u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)):
    return [_out(k) for k in service.list_keys(db)]


@router.post("/keys", response_model=IntegrationKeyCreated, status_code=201)
def create_key(
    data: IntegrationKeyCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> IntegrationKeyCreated:
    key, raw_key = service.create_key(
        db, tenant_id=user.tenant_id, actor=user.user_id, label=data.label
    )
    return IntegrationKeyCreated(**_out(key).model_dump(), raw_key=raw_key)


@router.post("/keys/{key_id}/revoke", response_model=IntegrationKeyOut)
def revoke_key(
    key_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> IntegrationKeyOut:
    try:
        key = service.revoke_key(db, key_id=key_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.IntegrationError as e:
        raise _err(e) from e
    return _out(key)


# ── Público (sem login) — chamado pelo site externo do cliente ─────────────
@public_router.post("/{key}")
def capture_lead(
    key: str,
    data: LeadCapture,
    db: Session = Depends(get_db),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    """Uso LEGÍTIMO de `get_db` (sem tenant): resolve `public_integration_keys`, snapshot
    GLOBAL sem RLS, pelo hash da chave. Nunca toca tabela de negócio por aqui — a escrita
    real acontece dentro de `session_factory(tenant_id)` (ver service.capture_lead)."""
    try:
        service.capture_lead(db, raw_key=key, data=data, session_factory=session_factory)
    except service.IntegrationError as e:
        raise _err(e) from e
    return {"status": "ok"}
