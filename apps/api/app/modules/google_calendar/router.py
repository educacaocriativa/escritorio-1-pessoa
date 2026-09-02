"""Rotas da integração Google (privadas) + callback público do OAuth (sem Bearer).

A integração é uma extensão da Agenda → usa `require_module("agenda")` como guarda. O callback
do Google NÃO carrega Bearer token (é o browser do usuário voltando do consent), então é uma
rota PÚBLICA que abre a sessão de tenant via `get_tenant_session_factory` — mesmo padrão de
pages/router.py. O tenant vem do `state` assinado (anti-CSRF), não de um token de sessão.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import verify_oauth_state
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_tenant_session_factory
from app.modules.google_calendar import service
from app.modules.google_calendar.schemas import GoogleConnectOut, GoogleStatusOut

router = APIRouter(prefix="/integrations/google", tags=["google-calendar"])
public_router = APIRouter(prefix="/integrations/google", tags=["google-calendar-public"])

logger = logging.getLogger("e1p.google_calendar")

_guard = require_module("agenda")


@router.get("/status", response_model=GoogleStatusOut)
def status(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> GoogleStatusOut:
    cred = service.get_credential(db)
    return GoogleStatusOut(
        configured=settings.google_oauth_configured,
        connected=cred is not None,
        email=cred.google_account_email if cred is not None else None,
    )


@router.get("/connect", response_model=GoogleConnectOut)
def connect(user: CurrentUser = Depends(_guard)) -> GoogleConnectOut:
    try:
        url = service.build_authorize_url(user.tenant_id)
    except service.GoogleNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return GoogleConnectOut(url=url)


@router.post("/disconnect")
def disconnect(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    removed = service.disconnect(db, tenant_id=user.tenant_id, actor=user.user_id)
    return {"status": "disconnected" if removed else "not_connected"}


# ── Público (sem login) — callback do Google ─────────────────────────────────
@public_router.get("/callback")
def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session_factory=Depends(get_tenant_session_factory),
) -> RedirectResponse:
    """O Google redireciona para cá após o consent. Valida o `state`, troca o `code` por tokens
    e persiste a credencial no tenant. Sempre redireciona de volta ao frontend.

    Todo caminho de falha cai no MESMO `?google=error` para o usuário — então cada um precisa
    deixar rastro no log, senão "recusou o consentimento", `redirect_uri_mismatch` e state
    expirado ficam indistinguíveis no suporte."""
    dest_ok = f"{settings.frontend_url}/config?google=connected"
    dest_err = f"{settings.frontend_url}/config?google=error"
    if error:
        # O Google devolve `error=access_denied` quando a pessoa cancela na tela de consentimento.
        # Rota PÚBLICA: `error` é entrada arbitrária, então vai truncado e sem quebra de linha
        # (senão dá para forjar linhas no log).
        logger.warning("[google:callback:denied] error=%s", " ".join(error[:60].split()))
        return RedirectResponse(dest_err, status_code=307)
    if not code or not state:
        logger.warning(
            "[google:callback:incompleto] code=%s state=%s", bool(code), bool(state)
        )
        return RedirectResponse(dest_err, status_code=307)
    tenant_id = verify_oauth_state(state)
    if not tenant_id:
        # State assinado inválido/expirado: CSRF ou aba parada tempo demais na tela do Google.
        logger.warning("[google:callback:state_invalido]")
        return RedirectResponse(dest_err, status_code=307)
    try:
        with session_factory(tenant_id) as tdb:
            service.handle_callback(tdb, tenant_id=tenant_id, code=code)
    except Exception:  # noqa: BLE001 — qualquer falha vira redirect de erro, nunca 500
        # O usuário só vê `?google=error` genérico: sem este log, `redirect_uri_mismatch`,
        # client_secret errado e token expirado ficam indistinguíveis no suporte.
        logger.exception("[google:callback:failed] tenant=%s", tenant_id)
        return RedirectResponse(dest_err, status_code=307)
    return RedirectResponse(dest_ok, status_code=307)
