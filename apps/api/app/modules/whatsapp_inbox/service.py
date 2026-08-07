# apps/api/app/modules/whatsapp_inbox/service.py
"""Inbox de WhatsApp: ingestão do webhook, lead automático, linha do tempo unificada, janela
de 24h e envio de resposta (texto/mídia/template).

Ver docs/superpowers/specs/2026-07-19-whatsapp-inbox-design.md para o desenho completo.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, facts, whatsapp
from app.core.facts import COM_MENSAGEM_RECEBIDA
from app.core.phone import normalize_br
from app.core.whatsapp import capabilities as whatsapp_capabilities
from app.core.whatsapp.inbound import InboundMessage
from app.modules.attachments import service as attachments_service
from app.modules.attachments.models import ALLOWED_TYPES, MAX_BYTES
from app.modules.attachments.service import AttachmentError
from app.modules.auth.models import User
from app.modules.crm import service as crm_service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service
from app.modules.vima import scheduler as vima_scheduler
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_GROUP,
    DIRECTION_IN,
    DIRECTION_OUT,
    KIND_TEXT,
    LEGACY_CHAT_JID,
    MEDIA_STATUS_DOWNLOADED,
    MEDIA_STATUS_FAILED,
    MEDIA_STATUS_NONE,
    MEDIA_STATUS_PENDING,
    PublicWhatsappAccount,
    WhatsappChat,
    WhatsappMessage,
)
from app.modules.whatsapp_templates.models import (
    PAYLOAD_BOTAO_BRIEFING,
    STATUS_APPROVED,
    WhatsappTemplate,
)

logger = logging.getLogger("e1p.whatsapp_inbox")

SESSION_WINDOW = timedelta(hours=24)

# Intervalo mínimo entre duas tentativas de descobrir o nome de um grupo (ver
# `_resolve_group_title`). 6h é folgado de propósito: o nome de um grupo quase nunca muda, e o
# custo de errar para mais é só um grupo continuar sem nome por meio dia.
_TITLE_RETRY = timedelta(hours=6)

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
    """Resolve o contato pelo telefone NORMALIZADO — a mesma identidade que o site usa.

    Comparar `Client.phone` cru (como era até aqui) deixava o conserto pela metade: o
    formulário guarda "(11) 99999-8888" e o WhatsApp guarda "5511999998888", então a mesma
    pessoa continuaria virando dois cards.
    """
    chave = normalize_br(phone)
    if chave:
        client = db.scalars(
            select(Client).where(Client.phone_key == chave).order_by(Client.created_at, Client.id)
        ).first()
        if client is not None:
            return client
    # Fallback para contato legado cujo telefone nunca normalizou (e portanto não tem chave).
    client = db.scalar(select(Client).where(Client.phone == phone))
    if client is not None:
        return client
    return crm_service.create_client(
        db, tenant_id=tenant_id, actor="whatsapp:inbox",
        data=ClientCreate(name=name or phone, phone=phone, source="whatsapp"),
    )


def _resolve_group_title(profile, chat: WhatsappChat) -> None:
    """Preenche `chat.title` com o assunto do grupo, no máximo uma tentativa por `_TITLE_RETRY`.

    O assunto não vem no payload da mensagem (só o JID do grupo), então descobrir exige uma
    chamada à Evolution. Sem o carimbo `title_checked_at`, as duas saídas possíveis seriam
    ruins: consultar a cada mensagem recebida (rede no caminho do webhook, num laço que já
    processa lote) ou desistir na primeira falha e deixar o grupo anônimo para sempre.

    `fetch_group_subject` nunca levanta exceção e devolve `None` quando não sabe — e `None`
    permanece `None`: a tela mostra um rótulo honesto, nunca um nome inventado."""
    now = datetime.now(UTC)
    checked = chat.title_checked_at
    if checked is not None:
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)  # SQLite guarda naive
        if now - checked < _TITLE_RETRY:
            return
    chat.title_checked_at = now
    subject = whatsapp.fetch_group_subject(profile=profile, group_jid=chat.chat_jid)
    if subject:
        chat.title = subject


def _find_direct_chat_by_phone(db: Session, *, chat_jid: str) -> WhatsappChat | None:
    """A conversa direta cujo telefone NORMALIZA para o mesmo valor deste JID.

    A comparação é feita em Python, e não em SQL, porque a forma comparável do telefone não é
    coluna em `whatsapp_chats` (é em `clients.phone_key`) — e criar a coluna aqui exigiria
    migration num momento de frentes paralelas. O custo é aceitável porque só roda no MISS: o
    caminho normal (JID idêntico) resolve na primeira consulta, e este só varre as conversas
    diretas do tenant quando uma grafia nova aparece, que é raro por definição.

    Devolve `None` quando o JID não carrega telefone (`@lid`, sintéticos do backfill): sem
    telefone não há o que comparar, e adivinhar seria pior que abrir conversa nova."""
    alvo = normalize_br(chat_jid.split("@", 1)[0]) if "@" in chat_jid else None
    if alvo is None:
        return None
    for candidata in db.scalars(
        select(WhatsappChat).where(WhatsappChat.kind != CHAT_KIND_GROUP)
    ).all():
        if "@" not in candidata.chat_jid:
            continue  # `legacy:`/`client:` do backfill da 0066 — não são endereço de ninguém
        if normalize_br(candidata.chat_jid.split("@", 1)[0]) == alvo:
            return candidata
    return None


def _get_or_create_chat(
    db: Session, *, tenant_id: str, chat_jid: str, kind: str, client: Client | None, profile,
) -> WhatsappChat:
    """A conversa, criada sob demanda a partir do JID que o WhatsApp entregou.

    `client` é ENRIQUECIMENTO, não chave: uma conversa direta cujo contato só foi identificado
    depois (`@lid` que passou a vir com `remoteJidAlt`) ganha o vínculo aqui, sem trocar de
    identidade nem partir o histórico.

    **O 9º dígito é a segunda forma de o histórico se partir.** O JID que o WhatsApp usa para um
    celular pré-2016 pode não ter o 9 (`554384074017@s.whatsapp.net` — caso real do tenant do
    fundador), enquanto tudo que o produto envia passa por `normalize_br`, que o ACRESCENTA
    (`5543984074017`). Duas grafias do mesmo telefone, e a busca por igualdade de string cria
    duas conversas para a mesma pessoa — a mesma classe de bug que `chat_jid` canônico resolveu
    para `@lid` × `@s.whatsapp.net`.

    Por isso a conversa direta tem um segundo critério de busca: telefone NORMALIZADO. Só entra
    no caminho de miss (quando não há JID idêntico), então não custa nada no fluxo normal, e
    nunca se aplica a grupo (JID de grupo não é telefone)."""
    chat = db.scalar(select(WhatsappChat).where(WhatsappChat.chat_jid == chat_jid))
    if chat is None and kind != CHAT_KIND_GROUP:
        chat = _find_direct_chat_by_phone(db, chat_jid=chat_jid)
    if chat is None:
        chat = WhatsappChat(
            tenant_id=tenant_id, chat_jid=chat_jid, kind=kind,
            client_id=client.id if client is not None else None,
            title=client.name if client is not None else None,
        )
        db.add(chat)
        db.flush()  # materializa chat.id — usado como FK lógica na mensagem, na mesma transação
    else:
        if chat.client_id is None and client is not None:
            chat.client_id = client.id
        if not chat.title and client is not None:
            chat.title = client.name
    if kind == CHAT_KIND_GROUP and not chat.title:
        _resolve_group_title(profile, chat)
    return chat



def _e_telefone_da_equipe(db: Session, tenant_id: str, phone: str | None) -> bool:
    """O telefone é de um usuário ATIVO deste tenant (dono ou funcionário)?

    Mensagem vinda do próprio time não é lead: pelo caminho normal ela criaria um contato no
    CRM, e o dono apareceria no próprio funil de vendas e no painel de inadimplência. Hoje isso
    só acontece se alguém escrever para o próprio número; com o opt-in do briefing por botão na
    Meta (Onda 4) passa a acontecer todo dia.

    ⚠️ `users` é tabela GLOBAL, SEM RLS (o login por e-mail é global) — o filtro por
    `tenant_id` aqui é explícito e obrigatório. É a exceção documentada da Regra de Ouro nº 1.
    """
    chave = normalize_br(phone) if phone else None
    if chave is None:
        return False
    fones = db.scalars(
        select(User.phone)
        .where(User.tenant_id == tenant_id)
        .where(User.is_active.is_(True))
        .where(User.phone.is_not(None))
    ).all()
    return any(normalize_br(f) == chave for f in fones)


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
    # Carregado UMA vez, fora do laço: só é usado para descobrir o nome de grupo novo
    # (`_resolve_group_title`), e `get_profile` faz commit próprio — chamá-lo por mensagem
    # atravessaria a transação-por-mensagem que o comentário acima constrói.
    profile = settings_service.get_profile(db, tenant_id)
    for msg in messages:
        try:
            if msg.wa_message_id and db.scalar(
                select(WhatsappMessage).where(WhatsappMessage.wa_message_id == msg.wa_message_id)
            ):
                continue  # duplicata — ignora

            da_equipe = _e_telefone_da_equipe(db, tenant_id, msg.from_phone)
            if msg.from_phone is None or da_equipe:
                # Sem telefone (`@lid`) OU telefone do próprio time: a mensagem é
                # gravada, mas NÃO vira contato do CRM.
                client_id = None
                client = None
            else:
                # `push_name` só nomeia o cliente quando o CONTATO escreveu: em mensagem
                # espelhada do aparelho do dono (`from_me`), o `pushName` que a Evolution manda
                # é o do PRÓPRIO DONO — usá-lo criaria (ou renomearia) o cliente com o nome do
                # dono na primeira mensagem espelhada de um contato ainda desconhecido.
                # `_get_or_create_client` cai no telefone quando o nome vem vazio.
                client = _get_or_create_client(
                    db, tenant_id=tenant_id, phone=msg.from_phone,
                    name="" if msg.from_me else msg.push_name,
                )
                client_id = client.id

            # A CONVERSA. Sem `chat_jid` (só o provider Meta, que não expõe JID quando nem o
            # telefone veio) não há como agrupar — a mensagem entra sem conversa e o backfill
            # legado da 0066 é quem a recolhe.
            chat = (
                _get_or_create_chat(
                    db, tenant_id=tenant_id, chat_jid=msg.chat_jid, kind=msg.chat_kind,
                    client=client, profile=profile,
                )
                if msg.chat_jid
                else None
            )

            # A autoria vem do provider (`key.fromMe` da Evolution), nunca é assumida: espelhar
            # como `in` uma mensagem que o dono escreveu no celular apaga o autor na tela de
            # Conversas E abre indevidamente a janela de 24h (`is_within_session_window` conta
            # só `DIRECTION_IN` — a janela é reaberta pelo CLIENTE, não por nós).
            direction = DIRECTION_OUT if msg.from_me else DIRECTION_IN
            msg_row = WhatsappMessage(
                tenant_id=tenant_id, client_id=client_id, direction=direction, kind=msg.kind,
                text_body=msg.text_body, media_status=MEDIA_STATUS_NONE,
                wa_message_id=msg.wa_message_id, status="sent",
                chat_id=chat.id if chat is not None else None,
                sender_phone=msg.sender_phone, sender_name=msg.sender_name,
            )
            db.add(msg_row)
            # `default=_uuid` da coluna só materializa `msg_row.id` no FLUSH (não ao construir o
            # objeto Python) — precisa disso ANTES de usar como owner_id do Attachment.
            db.flush()

            # Só mensagem RECEBIDA DE FORA vira fato. As duas exclusões são coisas que o
            # próprio time fez, e reportá-las de volta no briefing seria eco, não notícia:
            # a espelhada do aparelho do dono (`from_me`, que o Baileys manda no mesmo evento)
            # e a vinda do telefone de um usuário do tenant (`da_equipe` — ex.: o toque no
            # botão do briefing na Meta, Onda 4).
            #
            # ⚠️ DÍVIDA: `occurred_at` cai no default (agora), não no instante real da
            # mensagem — `InboundMessage` não carrega o `messageTimestamp` do payload, e
            # propagá-lo é mudança na camada de provider (os dois parsers). O efeito é uma
            # janela de segundos: uma mensagem recebida 23h59 e processada 00h01 entra no
            # briefing do dia seguinte em vez do dia dela. Fecha adicionando o campo ao
            # `InboundMessage` e preenchendo em `evolution.parse_inbound`/`meta`.
            if direction == DIRECTION_IN and not da_equipe:
                quem = (msg.sender_name or msg.push_name or msg.from_phone
                        or "contato não identificado")
                facts.record(
                    db, tenant_id=tenant_id, module="comercial",
                    kind=COM_MENSAGEM_RECEBIDA,
                    title=f"{quem} escreveu no WhatsApp", actor="client",
                    client_id=client_id,
                    subject_type="whatsapp_chat",
                    subject_id=chat.id if chat is not None else None,
                )

            # O toque no botão do aviso do briefing (Vima, Onda 4). Fica DEPOIS do registro da
            # mensagem (a conversa mostra o toque como qualquer outra) e DENTRO do mesmo `try` —
            # a mesma transação-por-mensagem commita as duas coisas juntas.
            #
            # ⚠️ **Precisa vir aqui, e não junto do bloco de `facts` acima**: aquele bloco é
            # pulado quando `da_equipe` é verdadeiro, e o toque no botão do briefing vem
            # SEMPRE do telefone de um usuário do tenant. Colocado lá dentro, o opt-in seria
            # descartado junto com as demais mensagens do time e o briefing nunca sairia.
            if msg.button_payload == PAYLOAD_BOTAO_BRIEFING and da_equipe:
                vima_scheduler.responder_optin(db, tenant_id=tenant_id, phone=msg.from_phone)

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
                # Ação distinta para a mensagem espelhada do aparelho do dono: "received" numa
                # mensagem que o próprio dono escreveu é trilha de auditoria que mente.
                action=(
                    "whatsapp_inbox.message.mirrored" if msg.from_me
                    else "whatsapp_inbox.message.received"
                ),
                target=client_id or "unidentified",
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


def _display_title(chat: WhatsappChat) -> str:
    """O nome que a tela mostra. Nunca inventa: quando não sabemos, DIZEMOS que não sabemos."""
    if chat.title:
        return chat.title
    if chat.kind == CHAT_KIND_GROUP:
        return "Grupo sem nome"
    if chat.chat_jid == LEGACY_CHAT_JID:
        return "Não identificados"
    if chat.chat_jid.endswith("@s.whatsapp.net"):
        return chat.chat_jid.split("@", 1)[0]  # o telefone é melhor rótulo que "desconhecido"
    return "Contato não identificado"  # `@lid`: o que temos não é telefone, e não fingimos que é


def _chat_phone(chat: WhatsappChat) -> str | None:
    if chat.kind == CHAT_KIND_GROUP or not chat.chat_jid.endswith("@s.whatsapp.net"):
        return None
    return chat.chat_jid.split("@", 1)[0]


def _preview(msg: WhatsappMessage, chat: WhatsappChat) -> str:
    body = msg.text_body or f"[{msg.kind}]"
    # Em grupo, "quem falou" é metade da informação — sem isso a lista vira uma pilha de frases
    # soltas sem dono. Em conversa direta seria ruído: só existem duas pessoas ali.
    if chat.kind == CHAT_KIND_GROUP and msg.direction == DIRECTION_IN and msg.sender_name:
        return f"{msg.sender_name}: {body}"
    return body


def list_conversations(db: Session, tenant_id: str) -> list[dict]:
    """Uma linha por CONVERSA com pelo menos 1 mensagem, ordenada pela mais recente.

    Indexado por `whatsapp_chats`, não mais por cliente do CRM — é o que permite grupo existir
    aqui (grupo não é cliente). Mensagem sem `chat_id` (legado que o backfill da 0066 não
    alcançou) fica de fora: sem conversa não há o que abrir.

    `tenant_id` não filtra a query explicitamente: a sessão já chega escopada por RLS (mesma
    convenção de `crm_service.build_board`), é mantido no parâmetro por simetria com o resto do
    módulo (e uso futuro, ex.: auditoria)."""
    chats = {c.id: c for c in db.scalars(select(WhatsappChat)).all()}
    last_msgs: dict[str, WhatsappMessage] = {}
    for msg in db.scalars(
        select(WhatsappMessage).order_by(WhatsappMessage.created_at)
    ).all():
        if msg.chat_id is not None:
            last_msgs[msg.chat_id] = msg  # a última iteração (ordem crescente) vence

    out = []
    for chat_id, last_msg in last_msgs.items():
        chat = chats.get(chat_id)
        if chat is None:
            continue
        unread = (
            last_msg.direction == DIRECTION_IN
            and (chat.last_read_at is None or last_msg.created_at > chat.last_read_at)
        )
        out.append({
            "chat_id": chat.id,
            "kind": chat.kind,
            "title": _display_title(chat),
            "phone": _chat_phone(chat),
            # Conversa direta já identificada aponta pro contato do CRM; grupo NUNCA aponta
            # (decisão do fundador: grupo não entra no funil).
            "client_id": chat.client_id,
            "last_message_at": last_msg.created_at,
            "last_message_preview": _preview(last_msg, chat),
            "unread": unread,
        })
    out.sort(key=lambda c: c["last_message_at"], reverse=True)
    return out


def get_chat(db: Session, *, chat_id: str) -> WhatsappChat:
    chat = db.get(WhatsappChat, chat_id)
    if chat is None:
        raise WhatsappInboxError("Conversa não encontrada", 404)
    return chat


def get_timeline(db: Session, *, chat_id: str) -> list[dict]:
    """Mescla WhatsappMessage (a conversa) + Notification(channel=whatsapp) do cliente vinculado
    (avisos automáticos já existentes: cobrança, contrato, etc.) — leitura combinada, SEM
    migrar nenhum dado antigo (ver design doc §2).

    Os avisos automáticos só entram quando a conversa tem cliente: eles são endereçados a um
    contato do CRM, e grupo não tem um."""
    chat = get_chat(db, chat_id=chat_id)
    entries: list[dict] = []
    for msg in db.scalars(
        select(WhatsappMessage)
        .where(WhatsappMessage.chat_id == chat_id)
        .order_by(WhatsappMessage.created_at)
    ).all():
        entries.append({
            "source": "conversation",
            "direction": msg.direction,
            "kind": msg.kind,
            "text_body": msg.text_body,
            "media_attachment_id": msg.media_attachment_id,
            "purpose_label": None,
            # Quem falou — a tela usa isto para rotular a bolha em grupo. `None` em conversa
            # direta (seria ruído: só há duas pessoas) e em mensagem nossa (a tela diz "Você").
            "sender_name": (
                msg.sender_name
                if chat.kind == CHAT_KIND_GROUP and msg.direction == DIRECTION_IN
                else None
            ),
            "created_at": msg.created_at,
        })
    if chat.client_id:
        for notif in db.scalars(
            select(Notification)
            .where(Notification.client_id == chat.client_id, Notification.channel == "whatsapp")
            .order_by(Notification.created_at)
        ).all():
            entries.append({
                "source": "automated",
                "direction": "out",
                "kind": "text",
                "text_body": notif.message,
                "media_attachment_id": None,
                "purpose_label": AUTOMATED_PURPOSE_LABEL,
                "sender_name": None,
                "created_at": notif.created_at,
            })
    entries.sort(key=lambda e: e["created_at"])
    return entries


def is_within_session_window(db: Session, *, chat_id: str) -> bool:
    """A janela de 24h é uma regra da Meta (Cloud API): fora dela só template aprovado passa.

    **Não se aplica a grupo** — a API oficial da Meta nem tem grupos, então a regra não existe
    para eles; exigi-la ali só tornaria o grupo mudo por engano. Grupo responde sempre.

    **Nem ao transporte Evolution** (Baileys), que não tem janela nenhuma. Aqui não é só rigor
    desnecessário: fora da janela a ÚNICA saída que o produto oferece é template aprovado, e um
    tenant conectado por QR code não tem nenhum e não consegue criar (a Evolution recusa
    templates por design). A conversa ficaria muda para sempre 24h depois da última mensagem do
    contato. Ver app/core/whatsapp/capabilities.py."""
    chat = db.get(WhatsappChat, chat_id)
    if chat is not None and chat.kind == CHAT_KIND_GROUP:
        return True
    if chat is not None:
        profile = settings_service.get_profile(db, chat.tenant_id)
        if not whatsapp_capabilities.for_profile(profile).session_window:
            return True
    last_inbound = db.scalar(
        select(WhatsappMessage)
        .where(WhatsappMessage.chat_id == chat_id, WhatsappMessage.direction == DIRECTION_IN)
        .order_by(WhatsappMessage.created_at.desc())
        .limit(1)
    )
    if last_inbound is None:
        return False
    created_at = last_inbound.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)  # SQLite guarda naive; normaliza p/ comparar
    return datetime.now(UTC) - created_at < SESSION_WINDOW


def mark_read(db: Session, *, tenant_id: str, chat_id: str) -> None:
    """Marca a conversa como lida (`last_read_at = agora`).

    O estado de leitura vive na PRÓPRIA conversa desde a Onda 4. Antes vivia numa tabela à
    parte (`whatsapp_conversation_states`) chaveada por `client_id` — que não consegue
    representar leitura de grupo, pois grupo não tem cliente.

    Isso também dissolveu uma corrida que existia aqui: a tabela antiga precisava de
    CHECK-THEN-ACT com recuperação de `IntegrityError`, porque clicar numa conversa dispara
    `/read` de mais de um lugar quase ao mesmo tempo (a lista E a thread) e as duas requests
    tentavam INSERIR a mesma linha. Agora não há INSERT nenhum: a linha do chat já existe (foi
    criada no ingest), e duas requests concorrentes fazem dois UPDATEs do mesmo campo com
    valores quase idênticos — a última vence, e vencer é o resultado correto."""
    chat = get_chat(db, chat_id=chat_id)
    chat.last_read_at = datetime.now(UTC)
    audit.record(
        db, tenant_id=tenant_id, actor="whatsapp:inbox",
        action="whatsapp_inbox.conversation.mark_read", target=chat_id,
    )
    db.commit()


# ── Envio de resposta ────────────────────────────────────────────────────────


def _destination(db: Session, chat: WhatsappChat) -> str:
    """O endereço de volta da conversa.

    Grupo responde no PRÓPRIO JID (`...@g.us`) — a Evolution aceita o JID inteiro no campo
    `number`, mesmo caminho de um telefone. Conversa direta responde no telefone do contato
    quando ele é conhecido; quando não é (`@lid`), o JID é o único endereço que temos.

    Nunca devolve string vazia sem dizer por quê: um `to=""` viraria um envio silenciosamente
    perdido, que é o pior desfecho possível para quem clicou em "enviar"."""
    if chat.kind == CHAT_KIND_GROUP:
        return chat.chat_jid
    if chat.client_id:
        client = db.get(Client, chat.client_id)
        if client is not None and client.phone:
            return client.phone
    phone = _chat_phone(chat)
    if phone:
        return phone
    if chat.chat_jid.startswith("legacy:") or chat.chat_jid.startswith("client:"):
        # JIDs sintéticos criados pelo backfill da 0066 — não são endereço de nada.
        raise WhatsappInboxError(
            "Esta conversa não tem um destinatário conhecido (histórico antigo, sem telefone). "
            "Responda pelo contato no CRM.", 422,
        )
    return chat.chat_jid


def send_reply_text(
    db: Session, *, tenant_id: str, actor: str, chat_id: str, text: str
) -> WhatsappMessage:
    chat = get_chat(db, chat_id=chat_id)
    if not is_within_session_window(db, chat_id=chat_id):
        raise WhatsappInboxError(
            "Fora da janela de 24h — use um template aprovado para responder", 422
        )
    to = _destination(db, chat)
    profile = settings_service.get_profile(db, tenant_id)
    status = whatsapp.send_text(to=to, text=text, profile=profile)
    msg = WhatsappMessage(
        tenant_id=tenant_id, client_id=chat.client_id, chat_id=chat.id,
        direction=DIRECTION_OUT, kind=KIND_TEXT, text_body=text, status=status,
    )
    db.add(msg)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_inbox.reply.text", target=chat_id
    )
    db.commit()
    db.refresh(msg)
    return msg


def send_reply_media(
    db: Session, *, tenant_id: str, actor: str, chat_id: str, file_bytes: bytes,
    filename: str, mime_type: str, caption: str = "",
) -> WhatsappMessage:
    chat = get_chat(db, chat_id=chat_id)
    if not is_within_session_window(db, chat_id=chat_id):
        raise WhatsappInboxError(
            "Fora da janela de 24h — use um template aprovado para responder", 422
        )
    to = _destination(db, chat)
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
        to=to, profile=profile, kind=kind, media_id=media_id, caption=caption,
    )
    msg = WhatsappMessage(
        tenant_id=tenant_id, client_id=chat.client_id, chat_id=chat.id,
        direction=DIRECTION_OUT, kind=kind, text_body=caption, status=status,
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
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_inbox.reply.media", target=chat_id
    )
    db.commit()
    db.refresh(msg)
    return msg


def send_reply_template(
    db: Session, *, tenant_id: str, actor: str, chat_id: str, template_id: str,
    variables: list[str],
) -> WhatsappMessage:
    chat = get_chat(db, chat_id=chat_id)
    if chat.kind == CHAT_KIND_GROUP:
        # Template aprovado é um artefato da Cloud API da Meta, que não tem grupos. Grupo nunca
        # precisa dele (a janela de 24h não se aplica) e nunca conseguiria usá-lo.
        raise WhatsappInboxError("Grupo não usa template — responda com uma mensagem", 422)
    to = _destination(db, chat)
    template = db.get(WhatsappTemplate, template_id)
    if template is None or template.status != STATUS_APPROVED:
        raise WhatsappInboxError("Template não encontrado ou ainda não aprovado pela Meta", 422)
    profile = settings_service.get_profile(db, tenant_id)
    status = whatsapp.send_template(
        to=to, profile=profile, template_name=template.name,
        language=template.language, variables=variables,
    )
    rendered = template.body_text
    for i, value in enumerate(variables, start=1):
        rendered = rendered.replace(f"{{{{{i}}}}}", value)
    msg = WhatsappMessage(
        tenant_id=tenant_id, client_id=chat.client_id, chat_id=chat.id,
        direction=DIRECTION_OUT, kind=KIND_TEXT, text_body=rendered, status=status,
    )
    db.add(msg)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_inbox.reply.template",
        target=chat_id,
    )
    db.commit()
    db.refresh(msg)
    return msg
