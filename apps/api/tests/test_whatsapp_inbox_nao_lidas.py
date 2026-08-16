# apps/api/tests/test_whatsapp_inbox_nao_lidas.py
"""`unread_client_ids` — o agregado que alimenta o ponto do card do Kanban.

O teste central aqui é o de PARIDADE. A regra de "não lida" vive inline dentro de
`list_conversations`; este agregado é uma segunda expressão da mesma regra, escrita porque
`list_conversations` carrega todas as mensagens do tenant em memória e o board não pode pagar
isso. Duas expressões da mesma regra divergem em silêncio — o card diria "esperando resposta"
com a caixa de entrada limpa. O teste de paridade é o que impede isso.
"""
from datetime import UTC, datetime, timedelta

from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_DIRECT,
    CHAT_KIND_GROUP,
    DIRECTION_IN,
    DIRECTION_OUT,
    WhatsappChat,
    WhatsappMessage,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"
BASE = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _chat(db, *, jid: str, client_id: str | None, kind: str = CHAT_KIND_DIRECT,
          last_read_at: datetime | None = None) -> WhatsappChat:
    chat = WhatsappChat(
        tenant_id=TENANT_ID, chat_jid=jid, kind=kind, title=jid,
        client_id=client_id, last_read_at=last_read_at,
    )
    db.add(chat)
    db.commit()
    return chat


def _msg(db, *, chat: WhatsappChat, direction: str, minutos: int, texto: str = "oi") -> None:
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, chat_id=chat.id, client_id=chat.client_id,
        direction=direction, text_body=texto,
        created_at=BASE + timedelta(minutes=minutos),
    ))
    db.commit()


def _cenario_completo(db) -> None:
    """As cinco situações que a regra precisa distinguir."""
    # 1. Nunca lida, última é do contato → ESPERANDO RESPOSTA.
    c1 = _chat(db, jid="5511900000001@s.whatsapp.net", client_id="cli-1")
    _msg(db, chat=c1, direction=DIRECTION_IN, minutos=10)

    # 2. Lida DEPOIS da última mensagem → em dia.
    c2 = _chat(db, jid="5511900000002@s.whatsapp.net", client_id="cli-2",
               last_read_at=BASE + timedelta(minutes=99))
    _msg(db, chat=c2, direction=DIRECTION_IN, minutos=10)

    # 3. Última mensagem é NOSSA → em dia, mesmo sem nunca ter sido "lida".
    c3 = _chat(db, jid="5511900000003@s.whatsapp.net", client_id="cli-3")
    _msg(db, chat=c3, direction=DIRECTION_IN, minutos=10)
    _msg(db, chat=c3, direction=DIRECTION_OUT, minutos=20)

    # 4. GRUPO com mensagem nova → nunca conta: grupo não é contato do CRM.
    g = _chat(db, jid="120363000000000000@g.us", client_id=None, kind=CHAT_KIND_GROUP)
    _msg(db, chat=g, direction=DIRECTION_IN, minutos=10)

    # 5. DOIS chats para o MESMO contato (o caso `@lid` + telefone). Um em dia, outro não —
    #    o contato aparece uma vez só, porque o conjunto é de CONTATOS, não de conversas.
    c5a = _chat(db, jid="5511900000005@s.whatsapp.net", client_id="cli-5",
                last_read_at=BASE + timedelta(minutes=99))
    _msg(db, chat=c5a, direction=DIRECTION_IN, minutos=10)
    c5b = _chat(db, jid="99995@lid", client_id="cli-5")
    _msg(db, chat=c5b, direction=DIRECTION_IN, minutos=30)


def test_unread_client_ids_distingue_as_cinco_situacoes(db):
    _cenario_completo(db)
    assert inbox_service.unread_client_ids(db) == {"cli-1", "cli-5"}


def test_unread_client_ids_concorda_com_list_conversations(db):
    """PARIDADE — a guarda contra as duas definições divergirem.

    Se alguém ajustar a regra em um dos dois lugares e esquecer o outro, este teste cai.
    """
    _cenario_completo(db)
    pela_caixa_de_entrada = {
        c["client_id"]
        for c in inbox_service.list_conversations(db, TENANT_ID)
        if c["unread"] and c["client_id"]
    }
    assert inbox_service.unread_client_ids(db) == pela_caixa_de_entrada


def test_unread_client_ids_vazio_sem_mensagem(db):
    _chat(db, jid="5511900000009@s.whatsapp.net", client_id="cli-9")
    assert inbox_service.unread_client_ids(db) == set()
