"""Rotas de autenticação e onboarding de tenant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_access_token
from app.core.tenancy import CurrentUser, get_current_user
from app.db.session import get_db
from app.modules.auth.models import Tenant, User
from app.modules.auth.schemas import (
    AuthToken,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionInfo,
    TenantOut,
    UserOut,
)
from app.modules.auth.service import (
    AuthError,
    authenticate,
    register_tenant,
    request_password_reset,
    reset_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_token(tenant: Tenant, user: User) -> AuthToken:
    access = create_access_token(
        {
            "sub": user.id,
            "tenant_id": tenant.id,
            "role": user.role,
            "allowed_modules": user.allowed_modules,
            "is_platform_admin": user.is_platform_admin,
        }
    )
    return AuthToken(
        access_token=access,
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant),
    )


@router.post("/register", response_model=AuthToken, status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)) -> AuthToken:
    try:
        tenant, owner = register_tenant(db, data)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return _build_token(tenant, owner)


@router.post("/login", response_model=AuthToken)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> AuthToken:
    try:
        tenant, user = authenticate(db, str(data.email), data.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return _build_token(tenant, user)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    raw = request_password_reset(db, str(data.email))
    # Resposta sempre genérica — não revela se o e-mail existe.
    resp: dict = {"message": "Se o e-mail existir, enviaremos instruções de redefinição."}
    # DEV: ainda não há provedor de e-mail. Em desenvolvimento devolvemos o token para
    # permitir testar o fluxo. NUNCA em produção (lá vai por e-mail/WhatsApp).
    if raw and not settings.is_production:
        resp["dev_reset_token"] = raw
    return resp


@router.post("/reset-password")
def reset_password_route(data: ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    try:
        reset_password(db, data.token, data.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return {"message": "Senha redefinida com sucesso."}


@router.get("/me", response_model=SessionInfo)
def me(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionInfo:
    # Relê do banco e revalida estado — token desatualizado/usuário desativado não passa.
    user = db.get(User, current.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Sessão inválida")
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    return SessionInfo(user=UserOut.model_validate(user), tenant=TenantOut.model_validate(tenant))
