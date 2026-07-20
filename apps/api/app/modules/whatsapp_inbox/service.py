# apps/api/app/modules/whatsapp_inbox/service.py
"""Inbox de WhatsApp: ingestão do webhook, lead automático, linha do tempo unificada, janela
de 24h e envio de resposta (texto/mídia/template).

Ver docs/superpowers/specs/2026-07-19-whatsapp-inbox-design.md para o desenho completo.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, whatsapp
from app.modules.attachments import service as attachments_service
from app.modules.attachments.models import ALLOWED_TYPES, MAX_BYTES
from app.modules.attachments.service import AttachmentError
from app.modules.crm import service as crm_service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service
from app.modules.whatsapp_inbox.models import (
    DIRECTION_IN,
    DIRECTION_OUT,
    KIND_TEXT,
    MEDIA_STATUS_NONE,
    MEDIA_STATUS_PENDING,
    PublicWhatsappAccount,
    WhatsappConversationState,
    WhatsappMessage,
)
from app.modules.whatsapp_templates.models import STATUS_APPROVED, WhatsappTemplate

SESSION_WINDOW = timedelta(hours=24)

# Rótulo genérico para avisos automáticos na timeline (ver `get_timeline`): `Notification` hoje
# não guarda o propósito explicitamente, então todo aviso automático cai neste rótulo único.
# Refinamento (guardar o propósito na própria Notification) fica para depois — não bloqueia
# esta feature.
AUTOMATED_PURPOSE_LABEL = "Aviso automático"

# Mapeia o mime_type recebido em `send_reply_media` para o `type` que a Graph API espera.
_MEDIA_KIND_BY_MIME = {
    "image/jpeg": "image",
    "image/png": "image",
    "application/pdf": "document",
    "audio/mpeg": "audio",
    "audio/ogg": "audio",
    "video/mp4": "video",
}


class WhatsappInboxError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


# ── Resolução de tenant (pré-autenticação do webhook) ───────────────────────


def resolve_account(db: Session, *, phone_number_id: str) -> PublicWhatsappAccount | None:
    """Resolve tenant/app_secret pelo `phone_number_id` — chamado numa sessão SEM tenant
    (`get_db`), ANTES de qualquer autenticação, mesmo padrão de `PublicIntegrationKey`."""
    return db.get(PublicWhatsappAccount, phone_number_id)


def resolve_by_verify_token(db: Session, *, verify_token: str) -> PublicWhatsappAccount | None:
    """Usado só no handshake GET — confere se o token bate com ALGUM tenant cadastrado."""
    return db.scalar(
        select(PublicWhatsappAccount).where(
            PublicWhatsappAccount.verify_token == verify_token
        )
    )


# ── Ingestão (webhook) ──────────────────────────────────────────────────────


def _extract_messages(payload: dict) -> list[tuple[dict, str]]:
    """Devolve [(mensagem, nome_do_contato)] achatando o formato aninhado do payload da Meta.
    O `tenant_id` já vem resolvido e validado pelo chamador (ver `ingest_webhook_payload`) — não
    precisamos extrair `phone_number_id` aqui.

    Este método é chamado DEPOIS que a assinatura do webhook já foi verificada (ver router), mas
    o CONTEÚDO do payload continua não confiável — a Meta não garante o shape interno. Em vez de
    `isinstance` a cada nível aninhado (mesmo histórico de gaps do router — ver
    `router._extract_phone_number_id`), captura a classe inteira de erro de shape inesperado de
    uma vez: `AttributeError` (`.get()` em algo que não é dict), `TypeError` (iterar algo
    não-iterável), `KeyError` (defensivo, ex.: `contacts[0]["profile"]` sem essas chaves)."""
    out: list[tuple[dict, str]] = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = value.get("contacts", [])
                name = contacts[0]["profile"]["name"] if contacts else "Cliente"
                for msg in value.get("messages", []):
                    out.append((msg, name))
    except (AttributeError, TypeError, KeyError) as exc:
        raise WhatsappInboxError("Payload inválido", 400) from exc
    return out


def _get_or_create_client(db: Session, *, tenant_id: str, phone: str, name: str) -> Client:
    client = db.scalar(select(Client).where(Client.phone == phone))
    if client is not None:
        return client
    return crm_service.create_client(
        db, tenant_id=tenant_id, actor="whatsapp:inbox",
        data=ClientCreate(name=name or phone, phone=phone, source="whatsapp"),
    )


def ingest_webhook_payload(db: Session, *, tenant_id: str, payload: dict) -> None:
    """Processa UM payload de webhook para um tenant já resolvido/validado pelo chamador. O
    router do webhook resolve o `tenant_id` via `PublicWhatsappAccount` (pelo `phone_number_id`)
    ANTES de chamar esta função, pois precisa do `app_secret` daquele tenant para validar a
    assinatura do webhook — reaproveitamos aqui o mesmo `tenant_id` já validado, sem resolvê-lo
    de novo. Idempotente: mensagens com `wa_message_id` já visto são ignoradas (a Meta reentrega
    o mesmo evento às vezes)."""
    for msg, contact_name in _extract_messages(payload):
        wa_message_id = msg.get("id")
        if wa_message_id and db.scalar(
            select(WhatsappMessage).where(WhatsappMessage.wa_message_id == wa_message_id)
        ):
            continue  # duplicata — ignora

        from_number = msg.get("from", "")
        kind = msg.get("type", "text")
        text_body = ""
        media_status = MEDIA_STATUS_NONE

        if kind == "text":
            text_body = msg.get("text", {}).get("body", "")
        elif kind in ("image", "audio", "document", "video"):
            media_obj = msg.get(kind, {})
            text_body = media_obj.get("caption", "")
            media_status = MEDIA_STATUS_PENDING
        else:
            kind = "text"
            text_body = "[tipo de mensagem não suportado]"

        client = _get_or_create_client(
            db, tenant_id=tenant_id, phone=from_number, name=contact_name
        )
        db.add(WhatsappMessage(
            tenant_id=tenant_id, client_id=client.id, direction=DIRECTION_IN, kind=kind,
            text_body=text_body, media_status=media_status, wa_message_id=wa_message_id,
            status="sent",
        ))
        audit.record(
            db, tenant_id=tenant_id, actor="whatsapp:inbox",
            action="whatsapp_inbox.message.received", target=client.id,
        )
    db.commit()


# ── Timeline unificada + janela de 24h ──────────────────────────────────────


def list_conversations(db: Session, tenant_id: str) -> list[dict]:
    """Uma linha por cliente com pelo menos 1 WhatsappMessage, ordenada pela mais recente.

    `tenant_id` não filtra a query explicitamente: a sessão já chega escopada por RLS (mesma
    convenção de `crm_service.build_board`), é mantido no parâmetro por simetria com o resto do
    módulo (e uso futuro, ex.: auditoria)."""
    last_msgs: dict[str, WhatsappMessage] = {}
    for msg in db.scalars(
        select(WhatsappMessage).order_by(WhatsappMessage.created_at)
    ).all():
        last_msgs[msg.client_id] = msg  # a última iteração (ordem crescente) vence

    states = {
        s.client_id: s
        for s in db.scalars(select(WhatsappConversationState)).all()
    }

    out = []
    for client_id, last_msg in last_msgs.items():
        client = db.get(Client, client_id)
        if client is None:
            continue
        state = states.get(client_id)
        unread = (
            last_msg.direction == DIRECTION_IN
            and (
                state is None
                or state.last_read_at is None
                or last_msg.created_at > state.last_read_at
            )
        )
        out.append({
            "client_id": client_id,
            "client_name": client.name,
            "client_phone": client.phone,
            "last_message_at": last_msg.created_at,
            "last_message_preview": last_msg.text_body or f"[{last_msg.kind}]",
            "unread": unread,
        })
    out.sort(key=lambda c: c["last_message_at"], reverse=True)
    return out


def get_timeline(db: Session, *, client_id: str) -> list[dict]:
    """Mescla WhatsappMessage (conversa) + Notification(channel=whatsapp) do mesmo cliente
    (avisos automáticos já existentes: cobrança, contrato, etc.) — leitura combinada, SEM
    migrar nenhum dado antigo (ver design doc §2)."""
    entries: list[dict] = []
    for msg in db.scalars(
        select(WhatsappMessage)
        .where(WhatsappMessage.client_id == client_id)
        .order_by(WhatsappMessage.created_at)
    ).all():
        entries.append({
            "source": "conversation",
            "direction": msg.direction,
            "kind": msg.kind,
            "text_body": msg.text_body,
            "media_attachment_id": msg.media_attachment_id,
            "purpose_label": None,
            "created_at": msg.created_at,
        })
    for notif in db.scalars(
        select(Notification)
        .where(Notification.client_id == client_id, Notification.channel == "whatsapp")
        .order_by(Notification.created_at)
    ).all():
        entries.append({
            "source": "automated",
            "direction": "out",
            "kind": "text",
            "text_body": notif.message,
            "media_attachment_id": None,
            "purpose_label": AUTOMATED_PURPOSE_LABEL,
            "created_at": notif.created_at,
        })
    entries.sort(key=lambda e: e["created_at"])
    return entries


def is_within_session_window(db: Session, *, client_id: str) -> bool:
    last_inbound = db.scalar(
        select(WhatsappMessage)
        .where(WhatsappMessage.client_id == client_id, WhatsappMessage.direction == DIRECTION_IN)
        .order_by(WhatsappMessage.created_at.desc())
        .limit(1)
    )
    if last_inbound is None:
        return False
    created_at = last_inbound.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)  # SQLite guarda naive; normaliza p/ comparar
    return datetime.now(UTC) - created_at < SESSION_WINDOW


def mark_read(db: Session, *, tenant_id: str, client_id: str) -> None:
    state = db.scalar(
        select(WhatsappConversationState).where(
            WhatsappConversationState.client_id == client_id
        )
    )
    if state is None:
        state = WhatsappConversationState(tenant_id=tenant_id, client_id=client_id)
        db.add(state)
    state.last_read_at = datetime.now(UTC)
    audit.record(
        db, tenant_id=tenant_id, actor="whatsapp:inbox",
        action="whatsapp_inbox.conversation.mark_read", target=client_id,
    )
    db.commit()


# ── Envio de resposta ────────────────────────────────────────────────────────


def send_reply_text(
    db: Session, *, tenant_id: str, actor: str, client_id: str, text: str
) -> WhatsappMessage:
    if not is_within_session_window(db, client_id=client_id):
        raise WhatsappInboxError(
            "Fora da janela de 24h — use um template aprovado para responder", 422
        )
    client = db.get(Client, client_id)
    if client is None:
        raise WhatsappInboxError("Cliente não encontrado", 404)
    profile = settings_service.get_profile(db, tenant_id)
    status = whatsapp.send_text(
        to=client.phone or "", text=text, token=profile.whatsapp_token,
        phone_id=profile.whatsapp_phone_id,
    )
    msg = WhatsappMessage(
        tenant_id=tenant_id, client_id=client_id, direction=DIRECTION_OUT, kind=KIND_TEXT,
        text_body=text, status=status,
    )
    db.add(msg)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_inbox.reply.text", target=client_id
    )
    db.commit()
    db.refresh(msg)
    return msg


def send_reply_media(
    db: Session, *, tenant_id: str, actor: str, client_id: str, file_bytes: bytes,
    filename: str, mime_type: str, caption: str = "",
) -> WhatsappMessage:
    if not is_within_session_window(db, client_id=client_id):
        raise WhatsappInboxError(
            "Fora da janela de 24h — use um template aprovado para responder", 422
        )
    client = db.get(Client, client_id)
    if client is None:
        raise WhatsappInboxError("Cliente não encontrado", 404)
    if mime_type not in ALLOWED_TYPES:
        raise WhatsappInboxError("Tipo de arquivo não permitido para envio", 415)
    if not file_bytes:
        raise WhatsappInboxError("Arquivo vazio", 422)
    if len(file_bytes) > MAX_BYTES:
        raise WhatsappInboxError("Arquivo acima de 10 MB", 413)
    kind = _MEDIA_KIND_BY_MIME.get(mime_type, "document")
    profile = settings_service.get_profile(db, tenant_id)
    try:
        media_id = whatsapp.upload_media(
            phone_id=profile.whatsapp_phone_id or "", token=profile.whatsapp_token or "",
            file_bytes=file_bytes, filename=filename, mime_type=mime_type,
        )
    except whatsapp.WhatsappApiError as exc:
        raise WhatsappInboxError(f"Falha ao subir mídia: {exc}", 502) from exc
    status = whatsapp.send_media(
        to=client.phone or "", token=profile.whatsapp_token or "",
        phone_id=profile.whatsapp_phone_id or "", kind=kind, media_id=media_id, caption=caption,
    )
    msg = WhatsappMessage(
        tenant_id=tenant_id, client_id=client_id, direction=DIRECTION_OUT, kind=kind,
        text_body=caption, status=status,
    )
    db.add(msg)
    db.flush()  # materializa msg.id na mesma transação, sem commitar — nada é durável ainda
    try:
        attachment = attachments_service.create_attachment(
            db, tenant_id=tenant_id, actor=actor, owner_type="whatsapp_message",
            owner_id=msg.id, label="outro", filename=filename, content_type=mime_type,
            data=file_bytes,
        )
    except AttachmentError as exc:
        raise WhatsappInboxError(str(exc), exc.status_code) from exc
    except Exception as exc:  # noqa: BLE001 — falha de storage (S3/rede) vira erro de domínio
        raise WhatsappInboxError(f"Falha ao salvar anexo: {exc}", 502) from exc
    msg.media_attachment_id = attachment.id
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_inbox.reply.media", target=client_id
    )
    db.commit()
    db.refresh(msg)
    return msg


def send_reply_template(
    db: Session, *, tenant_id: str, actor: str, client_id: str, template_id: str,
    variables: list[str],
) -> WhatsappMessage:
    client = db.get(Client, client_id)
    if client is None:
        raise WhatsappInboxError("Cliente não encontrado", 404)
    template = db.get(WhatsappTemplate, template_id)
    if template is None or template.status != STATUS_APPROVED:
        raise WhatsappInboxError("Template não encontrado ou ainda não aprovado pela Meta", 422)
    profile = settings_service.get_profile(db, tenant_id)
    status = whatsapp.send_template(
        to=client.phone or "", token=profile.whatsapp_token or "",
        phone_id=profile.whatsapp_phone_id or "", template_name=template.name,
        language=template.language, variables=variables,
    )
    rendered = template.body_text
    for i, value in enumerate(variables, start=1):
        rendered = rendered.replace(f"{{{{{i}}}}}", value)
    msg = WhatsappMessage(
        tenant_id=tenant_id, client_id=client_id, direction=DIRECTION_OUT, kind=KIND_TEXT,
        text_body=rendered, status=status,
    )
    db.add(msg)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_inbox.reply.template",
        target=client_id,
    )
    db.commit()
    db.refresh(msg)
    return msg
