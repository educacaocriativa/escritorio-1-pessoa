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
    AccountInviteOut,
    AccountOut,
    CreateAccountRequest,
    CreateStaffRequest,
    CustomerOut,
    PlatformCustomerOut,
    StaffInviteOut,
    TenantUsersOut,
    UpdateAccountRequest,
    UpdateUserRequest,
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


@router.post("/accounts", response_model=AccountInviteOut, status_code=201)
def create_account(
    data: CreateAccountRequest,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> AccountInviteOut:
    """Cria escritório + dono por convite (senha temporária enviada, trocada no 1º acesso)."""
    try:
        tenant, owner, temp, status = service.create_account(db, data)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return AccountInviteOut(
        tenant=TenantOut.model_validate(tenant), owner=UserOut.model_validate(owner),
        temp_password=temp, delivery=data.delivery, delivery_status=status,
    )


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


# ── Hierarquia de usuários: Super Admin vê/edita/exclui todos ────────────────
@router.get("/users", response_model=list[TenantUsersOut])
def list_users(
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[TenantUsersOut]:
    """Usuários da plataforma na hierarquia: escritório → Admin → funcionários + clientes."""
    return [
        TenantUsersOut(
            tenant=TenantOut.model_validate(node["tenant"]),
            admin=UserOut.model_validate(node["admin"]) if node["admin"] else None,
            staff=[UserOut.model_validate(u) for u in node["staff"]],
            customers=[CustomerOut(**c) for c in node["customers"]],
            staff_count=node["staff_count"],
            customer_count=node["customer_count"],
        )
        for node in service.list_tenant_users(db)
    ]


@router.get("/customers", response_model=list[PlatformCustomerOut])
def list_customers(
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> list[PlatformCustomerOut]:
    """Todos os clientes compradores da plataforma, com o escritório de origem."""
    return [PlatformCustomerOut(**c) for c in service.list_customers(db)]


@router.post("/accounts/{tenant_id}/users", response_model=StaffInviteOut, status_code=201)
def create_staff(
    tenant_id: str,
    data: CreateStaffRequest,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> StaffInviteOut:
    """O Master cadastra um funcionário (sub_user) com cadastro completo; a senha temporária é
    enviada por e-mail/WhatsApp e trocada no 1º acesso."""
    try:
        user, temp, status = service.create_staff(db, tenant_id, data)
    except (service.PlatformError, AuthError) as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return StaffInviteOut(
        user=UserOut.model_validate(user), temp_password=temp,
        delivery=data.delivery, delivery_status=status,
    )


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    data: UpdateUserRequest,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    try:
        user = service.update_user(db, user_id, data)
    except service.PlatformError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return UserOut.model_validate(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    _admin: CurrentUser = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    from fastapi import Response

    try:
        service.delete_user(db, user_id)
    except service.PlatformError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return Response(status_code=204)


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
