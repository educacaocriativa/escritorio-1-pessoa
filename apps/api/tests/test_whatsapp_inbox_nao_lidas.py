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


def _msg(db, *, chat: WhatsappChat, direction: str, minutos: int, texto: str = "oi",
         msg_id: str | None = None) -> None:
    # `msg_id` só é passado quando o teste precisa CONTROLAR o desempate (duas mensagens no
    # mesmo `created_at`): o `id` é o critério de desempate depois de `created_at`, e o default
    # da coluna é um UUID aleatório — sem fixar o id, um teste de empate seria não-determinístico.
    kwargs = dict(
        tenant_id=TENANT_ID, chat_id=chat.id, client_id=chat.client_id,
        direction=direction, text_body=texto,
        created_at=BASE + timedelta(minutes=minutos),
    )
    if msg_id is not None:
        kwargs["id"] = msg_id
    db.add(WhatsappMessage(**kwargs))
    db.commit()


def _cenario_completo(db) -> None:
    """As seis situações que a regra precisa distinguir."""
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

    # 6. EMPATE: duas mensagens do MESMO chat no MESMO instante, uma `in` outra `out`, nunca
    #    lida. O desempate é (created_at, id) — aqui elege a de MAIOR id como "a última", e os
    #    ids abaixo são escolhidos de propósito para que seja a `out` ("id-c6-out" > "id-c6-in"
    #    na comparação de string). Contato EM DIA, portanto: a última mensagem de verdade é a
    #    `out`, mesmo com a `in` empatada no mesmo instante. Uma checagem EXISTENCIAL ("existe
    #    ALGUMA mensagem `in` empatada no topo?") erraria isso — acharia a `in` e marcaria como
    #    esperando resposta. É este chat que faz o teste de paridade abaixo discriminar as duas
    #    implementações: só a que pergunta "qual É a última" (não "existe alguma") concorda com
    #    `list_conversations` aqui.
    c6 = _chat(db, jid="5511900000006@s.whatsapp.net", client_id="cli-6")
    _msg(db, chat=c6, direction=DIRECTION_IN, minutos=40, msg_id="id-c6-in")
    _msg(db, chat=c6, direction=DIRECTION_OUT, minutos=40, msg_id="id-c6-out")


def test_unread_client_ids_distingue_as_seis_situacoes(db):
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


def test_list_conversations_filtra_por_client_id(db):
    _cenario_completo(db)
    do_contato = inbox_service.list_conversations(db, TENANT_ID, client_id="cli-5")
    assert len(do_contato) == 2  # o caso `@lid` + telefone: duas conversas, um contato
    assert {c["client_id"] for c in do_contato} == {"cli-5"}


def test_list_conversations_sem_filtro_continua_trazendo_grupo(db):
    """O filtro é OPCIONAL e não pode mudar o comportamento da tela de Conversas."""
    _cenario_completo(db)
    todas = inbox_service.list_conversations(db, TENANT_ID)
    assert any(c["kind"] == "group" for c in todas)


def test_list_conversations_filtrado_nunca_traz_grupo(db):
    """Grupo tem `client_id` nulo — filtrar por contato jamais pode trazê-lo."""
    _cenario_completo(db)
    for cid in ("cli-1", "cli-5"):
        assert all(c["kind"] != "group" for c in inbox_service.list_conversations(
            db, TENANT_ID, client_id=cid))
