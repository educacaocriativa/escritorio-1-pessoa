"""Rotas de onboarding do WhatsApp por Evolution API (QR Code)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.whatsapp_session import service

router = APIRouter(prefix="/whatsapp-session", tags=["whatsapp-session"])

_guard = require_module("settings")


def _err(e: service.WhatsappSessionError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/connect")
def connect(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    try:
        return service.connect(db, tenant_id=user.tenant_id)
    except service.WhatsappSessionError as e:
        raise _err(e) from e


@router.get("/status")
def get_status(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    return {"status": service.get_status(db, tenant_id=user.tenant_id)}


@router.post("/confirm")
def confirm(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    return {"status": service.confirm(db, tenant_id=user.tenant_id)}


@router.post("/refresh-qr")
def refresh_qr(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    try:
        return {"qr_base64": service.refresh_qr(db, tenant_id=user.tenant_id)}
    except service.WhatsappSessionError as e:
        raise _err(e) from e


@router.delete("", status_code=204)
def disconnect(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    service.disconnect(db, tenant_id=user.tenant_id)
