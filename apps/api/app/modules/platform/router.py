"""Rotas do Super Admin (Master). Todas exigem is_platform_admin."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, require_platform_admin
from app.db.session import get_db
from app.modules.auth.schemas import TenantOut, UserOut
from app.modules.auth.service import AuthError
from app.modules.platform import service
from app.modules.platform.schemas import (
    AccountOut,
    CreateAccountRequest,
    UpdateAccountRequest,
)

router = APIRouter(prefix="/admin", tags=["platform-admin"])


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[AccountOut]:
    return [
        AccountOut(
            tenant=TenantOut.model_validate(t),
            owner=UserOut.model_validate(owner) if owner else None,
        )
        for t, owner in service.list_accounts(db)
        if owner is not None
    ]


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(
    data: CreateAccountRequest,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> AccountOut:
    try:
        tenant, owner = service.create_account(db, data)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return AccountOut(tenant=TenantOut.model_validate(tenant), owner=UserOut.model_validate(owner))


@router.patch("/accounts/{user_id}", response_model=UserOut)
def update_account(
    user_id: str,
    data: UpdateAccountRequest,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    try:
        user = service.update_account(db, user_id, data)
    except service.PlatformError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return UserOut.model_validate(user)


@router.delete("/accounts/{tenant_id}", status_code=204)
def delete_account(
    tenant_id: str,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    from fastapi import Response

    try:
        service.delete_account(db, tenant_id)
    except service.PlatformError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return Response(status_code=204)
