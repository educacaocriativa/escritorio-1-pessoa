# apps/api/app/modules/whatsapp_inbox/router.py
"""Webhook público de WhatsApp (recebimento de mensagens) + rotas autenticadas da inbox."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core import whatsapp
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_db, get_tenant_session_factory
from app.modules.whatsapp_inbox import service

public_router = APIRouter(prefix="/public/whatsapp", tags=["whatsapp-inbox-public"])
router = APIRouter(prefix="/whatsapp-conversations", tags=["whatsapp-inbox"])

_guard = require_module("crm")


@public_router.get("/webhook")
def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Handshake de verificação chamado 1x pela Meta quando o tenant configura o webhook no
    painel dele. Uso LEGÍTIMO de `get_db` (sem tenant): resolve `public_whatsapp_accounts`,
    tabela GLOBAL sem RLS, pelo verify_token — não toca tabela de negócio."""
    if hub_mode != "subscribe" or service.resolve_by_verify_token(
        db, verify_token=hub_verify_token
    ) is None:
        raise HTTPException(status_code=403, detail="Token de verificação inválido")
    return PlainTextResponse(content=hub_challenge)


@public_router.post("/webhook")
async def receive_webhook(
    request: Request,
    db: Session = Depends(get_db),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    """Recebe o evento da Meta. Descobre o tenant pelo `phone_number_id` do payload ANTES de
    validar a assinatura (a assinatura usa o `app_secret` DAQUELE tenant, então precisamos saber
    quem é primeiro). Se a assinatura não bater, rejeita sem processar nada."""
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON inválido")
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="JSON inválido")
    phone_number_id = None
    for entry in entries:
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail="JSON inválido")
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            raise HTTPException(status_code=400, detail="JSON inválido")
        for change in changes:
            if not isinstance(change, dict):
                raise HTTPException(status_code=400, detail="JSON inválido")
            phone_number_id = change.get("value", {}).get("metadata", {}).get("phone_number_id")
            if phone_number_id:
                break
        if phone_number_id:
            break

    if not phone_number_id:
        raise HTTPException(status_code=404, detail="phone_number_id não encontrado no payload")

    account = service.resolve_account(db, phone_number_id=phone_number_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Número não configurado nesta plataforma")

    signature = request.headers.get("x-hub-signature-256")
    if not whatsapp.verify_webhook_signature(
        app_secret=account.app_secret, body=body, signature_header=signature
    ):
        raise HTTPException(status_code=403, detail="Assinatura inválida")

    with session_factory(account.tenant_id) as tdb:
        service.ingest_webhook_payload(tdb, tenant_id=account.tenant_id, payload=payload)

    return {"status": "ok"}


# ── Rotas autenticadas (tela de Conversas) ──────────────────────────────────


def _err(e: service.WhatsappInboxError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("")
def list_conversations(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[dict]:
    return service.list_conversations(db, user.tenant_id)


@router.get("/{client_id}/timeline")
def get_timeline(
    client_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[dict]:
    return service.get_timeline(db, client_id=client_id)


@router.get("/{client_id}/window")
def get_window(
    client_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    return {"within_session_window": service.is_within_session_window(db, client_id=client_id)}


@router.post("/{client_id}/read", status_code=204)
def mark_read(
    client_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    service.mark_read(db, tenant_id=user.tenant_id, client_id=client_id)
