"""Conversa sem contato identificado.

Até a Onda 3 isto era um BALDE ÚNICO sintetizado por `list_conversations`: toda mensagem com
`client_id=None` (grupo, `@lid`) virava uma linha chamada "Não identificados" com
`client_id: None` — que a tela NEM CONSEGUIA ABRIR, porque usava esse id nulo como chave de
rota. E todos os grupos do tenant caíam ali juntos, misturados.

Na Onda 4 o balde deixou de existir como conceito: cada conversa tem identidade própria
(`whatsapp_chats.chat_jid`), inclusive as que não resolvem contato. O que sobrou de "não
identificado" é só o RÓTULO — a conversa existe, abre, lê e responde como qualquer outra.
"""
from __future__ import annotations

from sqlalchemy import select

from app.modules.whatsapp_inbox import service
from app.modules.whatsapp_inbox.models import (
    DIRECTION_IN,
    LEGACY_CHAT_JID,
    WhatsappChat,
    WhatsappMessage,
)

TENANT_ID = "55555555-5555-5555-5555-555555555555"


def _chat(db, *, chat_jid: str, kind: str = "direct", title: str | None = None) -> WhatsappChat:
    chat = WhatsappChat(tenant_id=TENANT_ID, chat_jid=chat_jid, kind=kind, title=title)
    db.add(chat)
    db.flush()
    return chat


def test_lid_conversation_has_its_own_row_and_an_honest_label(db) -> None:
    """`@lid` sem `remoteJidAlt`: o WhatsApp não revelou o telefone, então não há contato — mas
    a conversa existe e é sua. O rótulo diz que não sabemos; não inventa nome nem finge que o
    `@lid` é um número de telefone."""
    chat = _chat(db, chat_jid="999999@lid")
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=None, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text", text_body="oi, sou eu", wa_message_id="wa-1",
    ))
    db.commit()

    conversations = service.list_conversations(db, TENANT_ID)
    assert len(conversations) == 1
    assert conversations[0]["chat_id"] == chat.id
    assert conversations[0]["client_id"] is None
    assert conversations[0]["title"] == "Contato não identificado"
    assert conversations[0]["phone"] is None


def test_lid_conversation_opens(db) -> None:
    """O defeito que o usuário reportou: a linha aparecia na lista e clicar nela não abria nada.
    Agora a conversa tem id próprio e a timeline responde."""
    chat = _chat(db, chat_jid="999999@lid")
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=None, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text", text_body="preciso de ajuda", wa_message_id="wa-2",
    ))
    db.commit()

    timeline = service.get_timeline(db, chat_id=chat.id)
    assert [e["text_body"] for e in timeline] == ["preciso de ajuda"]


def test_legacy_bucket_keeps_its_label(db) -> None:
    """As mensagens anteriores à 0066 não guardaram JID nenhum e foram recolhidas num chat
    sintético pelo backfill. Elas continuam juntas (não há como separá-las), mas agora ABREM."""
    chat = _chat(db, chat_jid=LEGACY_CHAT_JID)
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=None, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text", text_body="mensagem antiga", wa_message_id="wa-3",
    ))
    db.commit()

    conversations = service.list_conversations(db, TENANT_ID)
    assert conversations[0]["title"] == "Não identificados"


def test_list_conversations_empty_when_no_messages(db) -> None:
    assert service.list_conversations(db, TENANT_ID) == []


def test_chat_without_messages_is_not_listed(db) -> None:
    """Conversa criada mas ainda sem mensagem não polui a lista — o critério continua sendo
    "tem pelo menos uma mensagem", como antes."""
    _chat(db, chat_jid="5511900000000@s.whatsapp.net")
    db.commit()
    assert service.list_conversations(db, TENANT_ID) == []
    assert db.scalar(select(WhatsappChat)) is not None
