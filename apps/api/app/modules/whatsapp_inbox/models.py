"""Conversa de WhatsApp (inbox): mensagens trocadas com o cliente (RLS) + resolução
pré-autenticação do webhook (tabela global, sem RLS).

Não confundir com `whatsapp_templates` (templates aprovados pela Meta) — aqui é a conversa de
verdade, ida-e-volta, entre o tenant e o cliente. Ver docs/superpowers/specs/
2026-07-19-whatsapp-inbox-design.md.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.token_crypto import EncryptedToken
from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

DIRECTION_IN = "in"
DIRECTION_OUT = "out"
DIRECTIONS = (DIRECTION_IN, DIRECTION_OUT)

KIND_TEXT = "text"
KIND_IMAGE = "image"
KIND_AUDIO = "audio"
KIND_DOCUMENT = "document"
KIND_VIDEO = "video"
KINDS = (KIND_TEXT, KIND_IMAGE, KIND_AUDIO, KIND_DOCUMENT, KIND_VIDEO)

MEDIA_STATUS_NONE = "none"
MEDIA_STATUS_PENDING = "pending"
MEDIA_STATUS_DOWNLOADED = "downloaded"
MEDIA_STATUS_FAILED = "failed"

CHAT_KIND_DIRECT = "direct"
CHAT_KIND_GROUP = "group"
CHAT_KINDS = (CHAT_KIND_DIRECT, CHAT_KIND_GROUP)

# Conversa legada: as mensagens que existiam antes de `whatsapp_chats` e nunca tiveram
# `client_id` resolvido (`@lid` sem `remoteJidAlt`). Elas não têm JID nenhum guardado — não dá
# pra reconstruir de qual conversa vieram —, então a migration 0066 junta todas num chat só por
# tenant com este JID sintético. Mensagem NOVA nunca cai aqui: hoje todo evento traz o
# `remoteJid`, então cada conversa (inclusive `@lid` não resolvido) ganha chat próprio.
LEGACY_CHAT_JID = "legacy:unidentified"


class WhatsappChat(Base, TenantMixin, TimestampMixin):
    """A CONVERSA — identidade própria, separada do cliente do CRM.

    Existe porque grupo não é cliente. Até a Onda 3 a caixa de entrada era indexada por
    `client_id`, e `client_id` é uma linha de `clients` (CRM/Kanban, funil de vendas, painel de
    inadimplência). Um grupo de WhatsApp não pertence a esse conjunto — mas é uma conversa
    legítima, que precisa de nome, histórico e resposta. Decisão do fundador (2026-08-04): grupo
    aparece em Conversas e NÃO vira contato do CRM.

    Consequência: `client_id` aqui é NULLABLE e é um enriquecimento da conversa direta ("esta
    conversa é com este cliente"), não a chave dela. A chave é `chat_jid`, que é o que o
    WhatsApp entrega (`key.remoteJid`) e o que a Evolution aceita de volta no envio.
    """

    __tablename__ = "whatsapp_chats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "chat_jid", name="uq_whatsapp_chats_tenant_jid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # `5511999999999@s.whatsapp.net` (direta), `1203...@g.us` (grupo) ou `9999@lid` (direta com
    # o telefone escondido pelo WhatsApp). Guardado CRU: é o endereço de volta no envio.
    chat_jid: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), default=CHAT_KIND_DIRECT, nullable=False)
    # Grupo: o assunto, que NÃO vem no payload da mensagem (só o JID) — é buscado à parte na
    # Evolution e cacheado aqui. Direta: o nome do contato. `None` = ainda não sabemos, e a tela
    # mostra um rótulo honesto em vez de inventar um nome.
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Só para conversa direta, e mesmo aí opcional (`@lid` sem telefone não resolve cliente).
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Quando tentamos descobrir o `title` pela última vez. Existe para fechar dois buracos que
    # um `title IS NULL` sozinho deixaria abertos: sem ele, ou consultamos o nome do grupo a
    # CADA mensagem recebida (chamada de rede no caminho do webhook), ou desistimos na primeira
    # falha e o grupo fica anônimo para sempre. Com ele, a tentativa é no máximo uma por
    # `_TITLE_RETRY` (ver service.py).
    title_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WhatsappMessage(Base, TenantMixin, TimestampMixin):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "wa_message_id", name="uq_whatsapp_messages_tenant_wa_id"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # None = não identificado (ex.: WhatsApp entregou @lid no lugar do telefone) — cai na
    # bandeja "Não identificados" em vez de adivinhar por heurística (ver Onda 3 da spec).
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # A CONVERSA a que a mensagem pertence (`whatsapp_chats.id`). É esta, e não `client_id`, a
    # chave de agrupamento da caixa de entrada desde a Onda 4 — `client_id` não consegue
    # representar grupo. Nullable só por causa do backfill; toda mensagem nova recebe um.
    chat_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # Quem escreveu, DENTRO da conversa. Em conversa direta é redundante com o próprio chat; em
    # GRUPO é a única forma de saber quem falou — sem isto, um grupo de 30 pessoas vira um muro
    # de balões anônimos. `sender_phone` vem de `key.participantAlt` (a Evolution manda o
    # telefone real mesmo quando `participant` está mascarado como `@lid`).
    sender_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default=KIND_TEXT, nullable=False)
    text_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Link pro módulo de Anexos já existente (reaproveita storage S3/Postgres).
    media_attachment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Só relevante pra mídia `in` (baixada de forma assíncrona pelo worker).
    media_status: Mapped[str] = mapped_column(
        String(16), default=MEDIA_STATUS_NONE, nullable=False
    )
    # ID da própria Meta — evita duplicar se o webhook reentregar a mesma mensagem.
    wa_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # ID de mídia da Meta (distinto de wa_message_id, que é o ID da MENSAGEM) — só setado
    # quando kind != "text" e ainda não baixamos os bytes.
    meta_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Só relevante pra `direction=out` ("sent"|"logged"|"failed", mesmo vocabulário de sempre).
    status: Mapped[str] = mapped_column(String(16), default="sent", nullable=False)


class WhatsappConversationState(Base, TenantMixin, TimestampMixin):
    """Uma linha por cliente com atividade — só guarda `last_read_at` (compartilhado entre toda
    a equipe do tenant: "lida por qualquer um" marca lida pra todos, sem granularidade por
    atendente, mesma decisão de 'inbox compartilhada' do brainstorming)."""

    __tablename__ = "whatsapp_conversation_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "client_id", name="uq_whatsapp_conv_state_tenant_client"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublicWhatsappAccount(Base, TimestampMixin):
    """Snapshot GLOBAL (sem RLS, SEM TenantMixin) — resolve `tenant_id` a partir do
    `phone_number_id` ANTES de qualquer autenticação. O webhook da Meta não manda tenant nenhum,
    só o `phone_number_id` que recebeu a mensagem; esta tabela é o único jeito de saber de quem é
    o evento e qual `app_secret` usar pra validar a assinatura. Mesmo padrão de
    `PublicIntegrationKey`/`published_pages`. Mantida em sincronia (dual-write) por
    `settings/service.py::update_profile` toda vez que o tenant salva/altera as credenciais.
    """

    __tablename__ = "public_whatsapp_accounts"

    phone_number_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Cifrado em repouso (mesmo padrão de `TenantProfile.whatsapp_app_secret`, ver
    # `core/token_crypto.py`) — vazamento de dump/backup não deve expor o segredo do App da Meta,
    # que forjaria a assinatura do webhook. Transparente: leitura/escrita seguem em texto plano
    # no nível Python (migration 0056 ajusta o tipo SQL subjacente p/ TEXT).
    app_secret: Mapped[str] = mapped_column(EncryptedToken, nullable=False)
    verify_token: Mapped[str] = mapped_column(String(64), nullable=False)
