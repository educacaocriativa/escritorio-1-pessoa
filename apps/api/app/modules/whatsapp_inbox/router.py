# apps/api/app/modules/whatsapp_inbox/router.py
"""Webhook público de WhatsApp (recebimento de mensagens) + rotas autenticadas da inbox."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core import whatsapp
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_db, get_tenant_session_factory
from app.modules.whatsapp_inbox import service
from app.modules.whatsapp_inbox.schemas import SendTemplateRequest, SendTextRequest
from app.modules.whatsapp_session import service as whatsapp_session_service
from app.modules.whatsapp_templates import service as whatsapp_templates_service

public_router = APIRouter(prefix="/public/whatsapp", tags=["whatsapp-inbox-public"])
router = APIRouter(prefix="/whatsapp-conversations", tags=["whatsapp-inbox"])
# Alcançável SÓ de dentro da rede interna do Docker — a Evolution não tem rota publicada pelo
# Traefik/Caddy (ver infra da Onda 1). O segredo no path é defesa em profundidade, não a
# garantia primária (que é o isolamento de rede).
internal_router = APIRouter(prefix="/internal/whatsapp", tags=["whatsapp-internal"])

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


def _extract_phone_number_id(payload: dict) -> str | None:
    """Extrai o `phone_number_id` do payload da Meta. Levanta `HTTPException(400)` para
    QUALQUER formato inesperado dentro de um JSON sintaticamente válido (o payload vem de uma
    fonte não confiável — este endpoint é público): não tenta adivinhar `isinstance` a cada
    nível aninhado (histórico: rounds 1-2 de review já encontraram gaps assim duas vezes,
    sempre um nível mais fundo); captura toda a classe de erro de indexação inesperada de uma
    vez só (`AttributeError` de `.get()` em algo que não é dict, `TypeError` de iterar algo
    não-iterável, `KeyError` defensivo)."""
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id")
                if phone_number_id:
                    return phone_number_id
    except (AttributeError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="Payload inválido") from exc
    return None


def _exigir_assinatura(*, app_secret: str, body: bytes, signature_header: str | None) -> None:
    """Levanta 403 se a assinatura não bater. Extraído porque os DOIS ramos do webhook
    (mensagem e status de template) precisam da mesma checagem com o `app_secret` da conta já
    resolvida — duas cópias divergiriam na primeira mudança."""
    if not whatsapp.verify_webhook_signature(
        app_secret=app_secret, body=body, signature_header=signature_header
    ):
        raise HTTPException(status_code=403, detail="Assinatura inválida")


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
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON inválido")

    # ── Ramo 1: aprovação/rejeição de template (issue #36) ──────────────────
    # Roda ANTES do caminho de mensagem porque é ele que sabe se este payload é de template.
    # `parse_template_status` nunca levanta (ver docstring lá): payload de mensagem, ou
    # qualquer payload deformado, devolve [] e o fluxo cai no caminho antigo — que segue
    # respondendo os mesmos 400 de sempre, com os mesmos testes.
    #
    # O roteamento aqui é por WABA, não por telefone: o evento de template NÃO tem
    # `metadata.phone_number_id` (era assim que ele morria em 404 antes da issue #36).
    template_events = whatsapp.meta.parse_template_status(payload)
    if template_events:
        waba_id = whatsapp.meta.extract_waba_id(payload)
        if not waba_id:
            raise HTTPException(status_code=404, detail="WABA não encontrada no payload")
        account = service.resolve_by_waba_id(db, waba_id=waba_id)
        if account is None:
            raise HTTPException(
                status_code=404, detail="Conta não configurada nesta plataforma"
            )
        _exigir_assinatura(
            app_secret=account.app_secret,
            body=body,
            signature_header=request.headers.get("x-hub-signature-256"),
        )
        with session_factory(account.tenant_id) as tdb:
            whatsapp_templates_service.apply_status_events(
                tdb, tenant_id=account.tenant_id, events=template_events
            )
        return {"status": "ok"}

    # ── Ramo 2: mensagem recebida (o caminho original) ──────────────────────
    phone_number_id = _extract_phone_number_id(payload)
    if phone_number_id is not None and not isinstance(phone_number_id, str):
        # Presente mas com tipo errado (dict/list) — passaria direto pro `if not phone_number_id`
        # abaixo (valores truthy) e quebraria `resolve_account`'s `db.get()` com
        # `sqlalchemy.exc.InvalidRequestError`. Barra aqui, antes de chegar no service.
        raise HTTPException(status_code=400, detail="Payload inválido")
    if not phone_number_id:
        raise HTTPException(status_code=404, detail="phone_number_id não encontrado no payload")

    account = service.resolve_account(db, phone_number_id=phone_number_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Número não configurado nesta plataforma")

    _exigir_assinatura(
        app_secret=account.app_secret,
        body=body,
        signature_header=request.headers.get("x-hub-signature-256"),
    )

    try:
        messages = whatsapp.meta.parse_inbound(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with session_factory(account.tenant_id) as tdb:
        service.ingest_webhook_payload(tdb, tenant_id=account.tenant_id, messages=messages)

    return {"status": "ok"}


@internal_router.post("/evolution/webhook/{webhook_secret}")
async def receive_evolution_webhook(
    webhook_secret: str,
    request: Request,
    db: Session = Depends(get_db),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    """Webhook da Evolution API — só alcançável de dentro da rede Docker (ver docstring de
    `internal_router` acima). Resolve o tenant via `PublicWhatsappInstance.webhook_secret`
    (Onda 2), não por assinatura HMAC (a Evolution não suporta — ver
    `providers.evolution.verify_webhook_signature`, que existe só pra levantar
    `EvolutionUnsupportedError` de propósito)."""
    instance = whatsapp_session_service.resolve_by_webhook_secret(
        db, webhook_secret=webhook_secret
    )
    if instance is None:
        raise HTTPException(status_code=404, detail="Instância não encontrada")

    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON inválido")

    messages = whatsapp.evolution.parse_inbound(payload)
    with session_factory(instance.tenant_id) as tdb:
        service.ingest_webhook_payload(tdb, tenant_id=instance.tenant_id, messages=messages)

    return {"status": "ok"}


# ── Rotas autenticadas (tela de Conversas) ──────────────────────────────────


def _err(e: service.WhatsappInboxError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("")
def list_conversations(
    client_id: str | None = Query(default=None),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[dict]:
    return service.list_conversations(db, user.tenant_id, client_id=client_id)


@router.get("/{chat_id}/timeline")
def get_timeline(
    chat_id: str,
    # `None` por padrão preserva o comportamento de hoje (histórico inteiro) para a tela de
    # Conversas, que é a mesma rota. Só a ficha 360° manda `limit` (ver BlocoDaConversa.tsx).
    limit: int | None = Query(default=None, gt=0),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[dict]:
    # Conversa inexistente vira 404 explícito (o service levanta): antes o id era de cliente e
    # um id desconhecido devolvia 200 com lista vazia — indistinguível de "conversa sem
    # mensagem" e péssimo pra diagnosticar.
    try:
        return service.get_timeline(db, chat_id=chat_id, limit=limit)
    except service.WhatsappInboxError as e:
        raise _err(e) from e


@router.get("/{chat_id}/window")
def get_window(
    chat_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    return {"within_session_window": service.is_within_session_window(db, chat_id=chat_id)}


@router.post("/{chat_id}/read", status_code=204)
def mark_read(
    chat_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    try:
        service.mark_read(db, tenant_id=user.tenant_id, chat_id=chat_id)
    except service.WhatsappInboxError as e:
        raise _err(e) from e


def _msg_out(msg) -> dict:
    return {
        "id": msg.id, "direction": msg.direction, "kind": msg.kind,
        "text_body": msg.text_body, "status": msg.status, "created_at": msg.created_at,
    }


@router.post("/{chat_id}/messages/text")
def send_text_reply(
    chat_id: str, data: SendTextRequest,
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db),
) -> dict:
    try:
        msg = service.send_reply_text(
            db, tenant_id=user.tenant_id, actor=user.user_id, chat_id=chat_id, text=data.text,
        )
    except service.WhatsappInboxError as e:
        raise _err(e) from e
    return _msg_out(msg)


@router.post("/{chat_id}/messages/media")
async def send_media_reply(
    chat_id: str, caption: str = Form(""), file: UploadFile = File(...),
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db),
) -> dict:
    data = await file.read()
    try:
        msg = service.send_reply_media(
            db, tenant_id=user.tenant_id, actor=user.user_id, chat_id=chat_id,
            file_bytes=data, filename=file.filename or "arquivo",
            mime_type=file.content_type or "application/octet-stream", caption=caption,
        )
    except service.WhatsappInboxError as e:
        raise _err(e) from e
    return _msg_out(msg)


@router.post("/{chat_id}/messages/template")
def send_template_reply(
    chat_id: str, data: SendTemplateRequest,
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db),
) -> dict:
    try:
        msg = service.send_reply_template(
            db, tenant_id=user.tenant_id, actor=user.user_id, chat_id=chat_id,
            template_id=data.template_id, variables=data.variables,
        )
    except service.WhatsappInboxError as e:
        raise _err(e) from e
    return _msg_out(msg)
