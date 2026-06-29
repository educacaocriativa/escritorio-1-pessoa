"""Rotas de notificações (histórico do que o sistema enviou)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.notifications import service
from app.modules.notifications.schemas import NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])

_guard = require_module("notifications")


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[NotificationOut]:
    return [NotificationOut.model_validate(n) for n in service.list_notifications(db, limit=limit)]
