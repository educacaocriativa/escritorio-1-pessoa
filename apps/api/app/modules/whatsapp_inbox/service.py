# apps/api/app/modules/whatsapp_inbox/service.py
"""Inbox de WhatsApp: ingestão do webhook, lead automático, linha do tempo unificada, janela
de 24h e envio de resposta (texto/mídia/template).

Ver docs/superpowers/specs/2026-07-19-whatsapp-inbox-design.md para o desenho completo.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, whatsapp
from app.core.whatsapp.inbound import InboundMessage
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
    MEDIA_STATUS_DOWNLOADED,
    MEDIA_STATUS_FAILED,
    MEDIA_STATUS_NONE,
    MEDIA_STATUS_PENDING,
    PublicWhatsappAccount,
    WhatsappConversationState,
    WhatsappMessage,
)
from app.modules.whatsapp_templates.models import STATUS_APPROVED, WhatsappTemplate

logger = logging.getLogger("e1p.whatsapp_inbox")

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


def _is_safe_identifier(value: str) -> bool:
    """Recusa NUL e qualquer string que não codifique em UTF-8 (ex.: surrogate solto) — ambos
    quebram o driver do Postgres na hora de fazer bind do parâmetro (psycopg.DataError /
    UnicodeEncodeError). Inofensivo pra maioria dos back-ends de teste, mas explode em
    produção. Ambos os identificadores vêm de entrada não confiável (payload público do
    webhook / query param do handshake), então validamos antes de qualquer lookup."""
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def resolve_account(db: Session, *, phone_number_id: str) -> PublicWhatsappAccount | None:
    """Resolve tenant/app_secret pelo `phone_number_id` — chamado numa sessão SEM tenant
    (`get_db`), ANTES de qualquer autenticação, mesmo padrão de `PublicIntegrationKey`."""
    if not _is_safe_identifier(phone_number_id):
        return None
    return db.get(PublicWhatsappAccount, phone_number_id)


def resolve_by_verify_token(db: Session, *, verify_token: str) -> PublicWhatsappAccount | None:
    """Usado só no handshake GET — confere se o token bate com ALGUM tenant cadastrado."""
    if not _is_safe_identifier(verify_token):
        return None
    return db.scalar(
        select(PublicWhatsappAccount).where(
            PublicWhatsappAccount.verify_token == verify_token
        )
    )


# ── Ingestão (webhook) ──────────────────────────────────────────────────────


def _get_or_create_client(db: Session, *, tenant_id: str, phone: str, name: str) -> Client:
    client = db.scalar(select(Client).where(Client.phone == phone))
    if client is not None:
        return client
    return crm_service.create_client(
        db, tenant_id=tenant_id, actor="whatsapp:inbox",
        data=ClientCreate(name=name or phone, phone=phone, source="whatsapp"),
    )


def ingest_webhook_payload(
    db: Session, *, tenant_id: str, messages: list[InboundMessage]
) -> None:
    """Processa mensagens JÁ PARSEADAS (Onda 3 — `InboundMessage`, normalizado por
    `provider.parse_inbound()`, chamado pelo router ANTES desta função) para um tenant já
    resolvido/validado pelo chamador. Genérico entre Meta e Evolution: nada aqui sabe de qual
    provider veio a mensagem. Idempotente: mensagens com `wa_message_id` já visto são ignoradas
    (o provider reentrega o mesmo evento às vezes).

    `from_phone is None` (ex.: `@lid` da Evolution, que esconde o telefone) vira mensagem SEM
    cliente resolvido (`client_id=None` — bandeja "Não identificados" na tela de Conversas) em
    vez de adivinhar por heurística (ver Onda 3 da spec)."""
    # Cada mensagem do lote é processada de forma ISOLADA e commitada individualmente: uma
    # falha em UMA mensagem (client_id não resolvido, `ClientCreate` com nome inválido, ou
    # qualquer outra) NUNCA derruba as demais do MESMO lote. Mesmo princípio de isolamento de
    # `notifications/service.py::process_pending`. A validação de SHAPE do lote (batch malformado)
    # já aconteceu em `provider.parse_inbound()`, antes desta função ser chamada — o router
    # converte essa falha em 400 antes de chegar aqui.
    #
    # CRÍTICO — commit POR MENSAGEM (não um único commit no fim do laço): o `db.add(...)` apenas
    # STAGE o insert; a falha real de PERSISTÊNCIA (ex.: `text_body`/caption com surrogate solto ou
    # NUL que o driver não consegue codificar — mesma classe de crash que rounds 6-8 blindaram em
    # `phone_number_id`/`verify_token`) só dispara no flush/commit. Se houvesse um único
    # `db.commit()` DEPOIS do laço, esse erro cairia FORA de todo try/except por mensagem e viraria
    # um 500 não tratado, quebrando a garantia de isolamento. E um `db.flush()` por mensagem com
    # commit único no fim também não serve: o `db.rollback()` de recuperação de uma mensagem
    # posterior desfaria TUDO desde o último commit — inclusive mensagens anteriores já flushadas e
    # válidas. Por isso cada mensagem é sua PRÓPRIA transação atômica: commita a si mesma no fim do
    # try; qualquer falha faz rollback só da sua própria transação e segue para a próxima. O
    # `db.rollback()` aqui NÃO limpa a GUC `app.current_tenant_id`: ela foi setada em
    # `tenant_session` com `set_config(..., is_local=false)` + `conn.commit()` no nível da CONEXÃO
    # (escopo de sessão), então o rollback ORM não a reverte e as mensagens seguintes continuam
    # corretamente escopadas por tenant.
    for msg in messages:
        try:
            if msg.wa_message_id and db.scalar(
                select(WhatsappMessage).where(WhatsappMessage.wa_message_id == msg.wa_message_id)
            ):
                continue  # duplicata — ignora

            if msg.from_phone is None:
                client_id = None
            else:
                client = _get_or_create_client(
                    db, tenant_id=tenant_id, phone=msg.from_phone, name=msg.push_name
                )
                client_id = client.id

            msg_row = WhatsappMessage(
                tenant_id=tenant_id, client_id=client_id, direction=DIRECTION_IN, kind=msg.kind,
                text_body=msg.text_body, media_status=MEDIA_STATUS_NONE,
                wa_message_id=msg.wa_message_id, status="sent",
            )
            db.add(msg_row)
            # `default=_uuid` da coluna só materializa `msg_row.id` no FLUSH (não ao construir o
            # objeto Python) — precisa disso ANTES de usar como owner_id do Attachment.
            db.flush()

            if msg.media_bytes:
                # Evolution: bytes já vieram decodificados no payload (webhookBase64) — cria o
                # Attachment NA HORA, sem depender do worker (que é Meta-only, ver
                # `providers/evolution.py::fetch_media_url`, que recusa por design).
                content_type = (
                    msg.media_mime_type
                    if msg.media_mime_type in ALLOWED_TYPES
                    else "application/octet-stream"
                )
                try:
                    attachment = attachments_service.create_attachment(
                        db, tenant_id=tenant_id, actor="whatsapp:inbox",
                        owner_type="whatsapp_message", owner_id=msg_row.id, label="outro",
                        filename=msg.media_filename or f"{msg.kind}-{msg_row.id}",
                        content_type=content_type, data=msg.media_bytes,
                    )
                    msg_row.media_attachment_id = attachment.id
                    msg_row.media_status = MEDIA_STATUS_DOWNLOADED
                except AttachmentError as exc:
                    # Mensagem ainda é registrada (com legenda, se houver) — só sem anexo. Mesmo
                    # princípio de isolamento do resto da função: um anexo problemático (tipo/
                    # tamanho) não pode derrubar o recebimento da mensagem em si.
                    logger.warning(
                        "[whatsapp_inbox] falha ao anexar mídia recebida, mensagem fica sem "
                        "anexo: wa_message_id=%s: %s", msg.wa_message_id, exc,
                    )
                    msg_row.media_status = MEDIA_STATUS_FAILED
            elif msg.media_ref:
                # Meta: só a referência opaca chegou — o worker resolve depois (assíncrono).
                msg_row.media_status = MEDIA_STATUS_PENDING
                msg_row.meta_media_id = msg.media_ref

            audit.record(
                db, tenant_id=tenant_id, actor="whatsapp:inbox",
                action="whatsapp_inbox.message.received", target=client_id or "unidentified",
            )
            db.commit()  # commita SÓ esta mensagem — transação atômica própria, isolada de
            # qualquer mensagem seguinte do mesmo lote que venha a falhar (ver nota no topo da
            # função sobre por que um único commit no fim do laço, ou flush+rollback parcial,
            # arriscaria desfazer mensagens anteriores já processadas com sucesso).
        except Exception as exc:  # noqa: BLE001 — isola a falha de UMA mensagem (inclui
            # pydantic.ValidationError de ClientCreate E falha de persistência do driver no commit,
            # ex.: text_body/caption com surrogate solto ou NUL); não trava o restante do lote
            # (mesmo princípio de process_pending)
            db.rollback()  # desfaz só a transação desta mensagem (não a GUC de tenant — ver nota)
            logger.warning(
                "[whatsapp_inbox] falha inesperada processando mensagem, ignorada: "
                "wa_message_id=%s: %s", msg.wa_message_id, exc,
            )
            continue
    # NENHUM db.commit() aqui: cada mensagem já commitou (ou fez rollback) a si mesma acima.


# ── Worker: download assíncrono de mídia recebida ───────────────────────────


def process_pending_media(db: Session, *, tenant_id: str) -> int:
    """Baixa mídia pendente de mensagens recebidas (chamado pelo worker, `run_sweep`).

    A sessão já chega escopada por RLS (`tenant_session`), então o `select` abaixo só enxerga
    mensagens deste tenant — mesma convenção do resto do módulo. Uma falha isolada (rede,
    credencial ausente/inválida, media_id inválido) NÃO trava as demais mensagens pendentes: a
    mensagem falha é marcada `MEDIA_STATUS_FAILED` e o loop segue (IV2, mesmo princípio de
    `ingest_webhook_payload`/`notifications.service.process_pending`).

    CRÍTICO — commit POR MENSAGEM (não um único commit no fim do laço): `create_attachment` já
    faz seu PRÓPRIO `db.commit()`/`db.refresh()` internamente, então a Session já sofre um commit
    real a cada iteração bem-sucedida — não existe "commit único no fim" de fato, só a ILUSÃO de
    um. Se o `create_attachment` de UMA mensagem falhar no meio (erro transitório de rede/storage,
    plausível para bytes de mídia reais de vários MB), o SQLAlchemy 2.0 deixa a Session "poisoned"
    (exige `db.rollback()` explícito antes de qualquer novo uso); sem esse rollback aqui, a
    PRÓXIMA mensagem do mesmo lote (ou o commit final) levantaria `PendingRollbackError` e
    contaminaria em cascata mensagens seguintes que seriam bem-sucedidas. Por isso, mesmo padrão de
    `ingest_webhook_payload`: cada mensagem commita a si mesma (sucesso OU falha) e o `except`
    chama `db.rollback()` ANTES de marcar `MEDIA_STATUS_FAILED`, para garantir que a Session volte
    a um estado limpo antes de seguir para a próxima."""
    profile = settings_service.get_profile(db, tenant_id)
    pending = db.scalars(
        select(WhatsappMessage)
        .where(WhatsappMessage.media_status == MEDIA_STATUS_PENDING)
        .limit(50)
    ).all()
    processed = 0
    for msg in pending:
        # `msg_id`/`msg_kind` capturados ANTES do try: se `create_attachment` falhar no meio do
        # seu próprio commit, a Session fica "poisoned" e QUALQUER acesso a atributo de `msg`
        # depois disso (inclusive para logar) levantaria PendingRollbackError de novo — capturar
        # antes garante que já temos os valores em mãos, sem tocar a Session no `except`.
        msg_id = msg.id
        try:
            url = whatsapp.fetch_media_url(profile=profile, media_id=msg.meta_media_id or "")
            data = whatsapp.download_media(profile=profile, url=url)
            mime_type = {
                "image": "image/jpeg", "audio": "audio/ogg",
                "document": "application/octet-stream", "video": "video/mp4",
            }.get(msg.kind, "application/octet-stream")
            attachment = attachments_service.create_attachment(
                db, tenant_id=tenant_id, actor="system:worker", owner_type="whatsapp_message",
                owner_id=msg_id, label="outro", filename=f"{msg.kind}-{msg_id}",
                content_type=mime_type, data=data,
            )
            msg.media_attachment_id = attachment.id
            msg.media_status = MEDIA_STATUS_DOWNLOADED
            db.commit()  # commita SÓ esta mensagem — transação isolada da próxima do lote.
        except Exception:  # noqa: BLE001 — isola a falha por mensagem (IV2)
            db.rollback()  # limpa a Session (possivelmente "poisoned" pelo create_attachment
            # que falhou no meio) ANTES de qualquer outro uso — senão o log abaixo, a marcação de
            # status ou o próximo db.add/commit (desta mensagem ou da seguinte) levantaria
            # PendingRollbackError.
            logger.exception("[whatsapp_inbox] falha ao baixar mídia msg=%s", msg_id)
            msg.media_status = MEDIA_STATUS_FAILED
            db.commit()  # commita só a marcação de falha desta mensagem.
        processed += 1
    return processed


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
        if client_id is None:
            out.append({
                "client_id": None,
                "client_name": "Não identificados",
                "client_phone": "",
                "last_message_at": last_msg.created_at,
                "last_message_preview": last_msg.text_body or f"[{last_msg.kind}]",
                "unread": last_msg.direction == DIRECTION_IN,
            })
            continue
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
    """Marca a conversa como lida (`last_read_at = agora`).

    CHECK-THEN-ACT contra `uq_whatsapp_conv_state_tenant_client` (achado em smoke test manual:
    clicar numa conversa dispara `/read` de mais de um lugar quase ao mesmo tempo — ex. a lista
    de conversas E a thread aberta — e ambas as requests chegam aqui antes de qualquer uma
    commitar). O SELECT abaixo pode devolver `None` para as duas; as duas tentam INSERIR a
    mesma linha (tenant_id, client_id) e a que commita por último esbarra num
    `IntegrityError` (UniqueViolation) não tratado, virando 500.

    Mesma classe de corrida já resolvida em `crm_service._ordered_stages` (não a de
    `create_stage`): a linha já existir NÃO é um conflito de negócio a rejeitar — só significa
    que outra request venceu a corrida e já criou o estado; a ação correta é recuperar (rollback
    + reconsultar) e atualizar essa linha, nunca deixar o IntegrityError escapar. Mesmo
    `db.rollback()`-antes-de-reusar já documentado em `ingest_webhook_payload`/
    `process_pending_media` acima: o commit que falhou deixa a Session "poisoned" e qualquer
    uso posterior (inclusive o SELECT de recuperação) precisa do rollback explícito primeiro.
    """
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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # desfaz nosso INSERT perdedor (e o audit.record da mesma transação) —
        # a linha vencedora da corrida já está commitada por quem chegou primeiro; sem este
        # rollback a Session fica poisoned e o SELECT de recuperação abaixo levantaria
        # PendingRollbackError em vez de simplesmente reconsultar.
        state = db.scalar(
            select(WhatsappConversationState).where(
                WhatsappConversationState.client_id == client_id
            )
        )
        if state is None:
            # Não deveria acontecer (o IntegrityError só dispara se a linha já existe pra
            # alguém ter vencido a corrida), mas não escondemos um bug diferente atrás de um
            # AttributeError em `state.last_read_at` — propaga o erro original.
            raise
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
    status = whatsapp.send_text(to=client.phone or "", text=text, profile=profile)
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
            profile=profile, file_bytes=file_bytes, filename=filename, mime_type=mime_type,
        )
    except whatsapp.WhatsappApiError as exc:
        raise WhatsappInboxError(f"Falha ao subir mídia: {exc}", 502) from exc
    status = whatsapp.send_media(
        to=client.phone or "", profile=profile, kind=kind, media_id=media_id, caption=caption,
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
        to=client.phone or "", profile=profile, template_name=template.name,
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
