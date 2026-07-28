"""Rotas de gerenciamento dos tokens de dispositivo (`/settings/device-tokens`).

Usa `get_db` (sem tenant) de propósito: `device_tokens` é uma tabela GLOBAL sem RLS. O
isolamento aqui vem do filtro explícito por `user_id` vindo do JWT — não há acesso a nenhuma
tabela de negócio nestas rotas.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_current_user
from app.db.session import get_db
from app.modules.device_tokens import service
from app.modules.device_tokens.schemas import (
    DeviceTokenCreate,
    DeviceTokenCreated,
    DeviceTokenOut,
)

router = APIRouter(prefix="/settings/device-tokens", tags=["device-tokens"])


@router.get("", response_model=list[DeviceTokenOut])
def list_tokens(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeviceTokenOut]:
    return [
        DeviceTokenOut(
            id=t.id, name=t.name, created_at=t.created_at, last_used_at=t.last_used_at
        )
        for t in service.list_tokens(db, user_id=user.user_id)
    ]


@router.post("", response_model=DeviceTokenCreated, status_code=201)
def create_token(
    data: DeviceTokenCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeviceTokenCreated:
    token, raw = service.create_token(
        db, tenant_id=user.tenant_id, user_id=user.user_id, name=data.name
    )
    return DeviceTokenCreated(id=token.id, name=token.name, token=raw)


@router.delete("/{token_id}", status_code=204)
def revoke_token(
    token_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        service.revoke(db, token_id=token_id, user_id=user.user_id)
    except service.DeviceTokenError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return Response(status_code=204)
