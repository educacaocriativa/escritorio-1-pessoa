"""Rotas de autenticação e onboarding de tenant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_access_token, decode_access_token, refresh_access_token
from app.core.tenancy import CurrentUser, get_current_user
from app.db.session import get_db
from app.modules.auth.models import Tenant, User
from app.modules.auth.schemas import (
    AuthToken,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshedToken,
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
    set_own_password,
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


@router.post("/refresh", response_model=RefreshedToken)
def refresh(
    _current: CurrentUser = Depends(get_current_user),
    authorization: str | None = Header(default=None),
) -> RefreshedToken:
    """Desliza a janela de inatividade da sessão (idle timeout LGPD — Story 1.3).

    Depende de ``get_current_user``: um token já expirado por inatividade (>30 min sem chamar
    /refresh) falha aqui com 401 (fail-closed), forçando novo login. O front chama isto enquanto
    há atividade real do usuário. Não consulta o banco → leve, sem regressão de performance (IV3).
    """
    # get_current_user já validou header presente + token não expirado; decodificamos de novo
    # apenas para ler ``abs_exp`` (não carregado em CurrentUser) e reemitir preservando o teto.
    token = (authorization or "").split(" ", 1)[1]
    payload = decode_access_token(token)
    new_token = refresh_access_token(payload) if payload else None
    if new_token is None:
        raise HTTPException(status_code=401, detail="Sessão expirada — faça login novamente")
    return RefreshedToken(access_token=new_token)


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    raw = request_password_reset(db, str(data.email))
    # Resposta sempre genérica — não revela se o e-mail existe.
    resp: dict = {"message": "Se o e-mail existir, enviaremos instruções de redefinição."}
    if raw:
        # Entrega real por e-mail (graceful degradation: sem SMTP configurado vira log).
        # Import tardio — mesmo padrão de platform/service.py::_send_invite.
        from app.core.email import send_email

        body = (
            "Você solicitou a redefinição da sua senha na plataforma.\n\n"
            f"Código de redefinição: {raw}\n\n"
            'Abra a tela "Esqueci minha senha" > "Definir nova senha" no app, cole este '
            "código no campo indicado e escolha uma nova senha. O código expira em 1 hora.\n\n"
            "Se você não fez esta solicitação, ignore este e-mail."
        )
        send_email(to=str(data.email), subject="Redefinição de senha", body=body)
        # DEV: devolvemos o token na resposta para permitir testar o fluxo sem provedor real.
        # NUNCA em produção (lá o usuário recebe apenas pelo e-mail acima).
        if not settings.is_production:
            resp["dev_reset_token"] = raw
    return resp


@router.post("/reset-password")
def reset_password_route(data: ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    try:
        reset_password(db, data.token, data.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return {"message": "Senha redefinida com sucesso."}


@router.post("/change-password", response_model=SessionInfo)
def change_password(
    data: ChangePasswordRequest,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionInfo:
    """Troca a própria senha (usado no 1º acesso, com senha temporária). Limpa o flag."""
    try:
        user = set_own_password(db, current.user_id, data.new_password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    tenant = db.get(Tenant, user.tenant_id)
    return SessionInfo(user=UserOut.model_validate(user), tenant=TenantOut.model_validate(tenant))


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
