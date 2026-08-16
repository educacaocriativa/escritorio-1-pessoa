# apps/api/tests/test_crm_board_nao_lida.py
"""O board do Kanban devolve `unread` por card — o ponto de 'esperando resposta'."""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.modules.crm.models import Client
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_DIRECT,
    DIRECTION_IN,
    WhatsappChat,
    WhatsappMessage,
)

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    """`/crm/board` é rota autenticada — sem isto tudo aqui é 401. Mesmo padrão de
    `test_crm.py`."""
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _contato(client: TestClient, headers: dict[str, str], nome: str) -> str:
    """Cria pela API, e não montando o modelo à mão.

    O contato precisa nascer no tenant AUTENTICADO e na primeira etapa do funil — `POST
    /crm/clients` faz as duas coisas (`create_client` chama `ensure_stages`). Um `Client(...)`
    direto no banco com `tenant_id` inventado passaria em SQLite, onde não há RLS, e mediria
    uma situação que não existe em produção.
    """
    resp = client.post("/crm/clients", json={"name": nome}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _conversa_esperando(db, client_id: str) -> None:
    """Uma mensagem do contato, nunca lida. O `tenant_id` vem do próprio contato."""
    contato = db.get(Client, client_id)
    chat = WhatsappChat(
        tenant_id=contato.tenant_id, chat_jid=f"5511{client_id[:9]}@s.whatsapp.net",
        kind=CHAT_KIND_DIRECT, client_id=client_id,
    )
    db.add(chat)
    db.commit()
    db.add(WhatsappMessage(
        tenant_id=contato.tenant_id, chat_id=chat.id, client_id=client_id,
        direction=DIRECTION_IN, text_body="oi, tudo bem?",
        created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    ))
    db.commit()


def _cards(payload: dict) -> dict[str, dict]:
    return {c["id"]: c for col in payload["columns"] for c in col["clients"]}


def test_board_marca_unread_so_em_quem_espera_resposta(client, db, headers):
    esperando = _contato(client, headers, "Quem escreveu")
    quieto = _contato(client, headers, "Quem nao escreveu")
    _conversa_esperando(db, esperando)

    resp = client.get("/crm/board", headers=headers)
    assert resp.status_code == 200
    cards = _cards(resp.json())
    assert cards[esperando]["unread"] is True
    assert cards[quieto]["unread"] is False


def test_board_unread_e_sempre_booleano(client, db, headers):
    """Nunca `null`: o card decide mostrar o ponto ou não, e não tem terceiro estado."""
    _contato(client, headers, "Sem conversa nenhuma")
    cards = _cards(client.get("/crm/board", headers=headers).json())
    assert cards, "o board veio sem card nenhum — o teste não mediu nada"
    assert all(isinstance(c["unread"], bool) for c in cards.values())


def _consultas_do_board(client, headers, engine) -> int:
    """Quantas consultas SQL um GET /crm/board dispara."""
    from sqlalchemy import event

    contador = []

    def _antes(_conn, _cursor, statement, _params, _context, _many):
        contador.append(statement)

    event.listen(engine, "before_cursor_execute", _antes)
    try:
        assert client.get("/crm/board", headers=headers).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _antes)
    return len(contador)


def test_board_nao_faz_uma_consulta_por_card(client, db, headers):
    """Dobrar os cards não pode dobrar as consultas.

    O jeito errado de implementar `unread` é perguntar por contato, dentro do laço que monta
    as colunas. Funciona no teste de duas linhas e derruba o board de quem tem 200 leads no
    funil — e a falha é invisível em qualquer teste que só olhe o JSON de resposta.

    Este é o mesmo motivo pelo qual `last_interaction_map` existe como consulta agrupada.
    """
    engine = db.get_bind()
    for i in range(2):
        _conversa_esperando(db, _contato(client, headers, f"Contato {i}"))
    com_2 = _consultas_do_board(client, headers, engine)

    for i in range(2, 8):
        _conversa_esperando(db, _contato(client, headers, f"Contato {i}"))
    com_8 = _consultas_do_board(client, headers, engine)

    assert com_8 == com_2, (
        f"{com_2} consultas com 2 cards e {com_8} com 8 — o custo está crescendo com os cards"
    )
