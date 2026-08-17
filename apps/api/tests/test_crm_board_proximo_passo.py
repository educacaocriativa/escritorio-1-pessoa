# apps/api/tests/test_crm_board_proximo_passo.py
"""O board do Kanban devolve `next_event_at`/`next_event_title` por card — o outro lado da

mesma pergunta que `unread` responde: o que está marcado com este contato, ou o aviso de que
não há nada (o sinal mais acionável, quem vai esfriar). Irmão direto de
`test_crm_board_nao_lida.py` — mesmo molde, inclusive o teste de contagem de consultas.
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.agenda.models import STATUS_CANCELLED, AgendaEvent
from app.modules.crm.models import Client

REGISTER = {
    "legal_name": "Estúdio Bia",
    "document": "22333444000181",
    "slug": "estudiobia",
    "email": "bia@example.com",
    "name": "Bia",
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


def _compromisso(
    db: Session, client_id: str, *, titulo: str = "Reunião de alinhamento",
    status: str = "scheduled", em: timedelta = timedelta(hours=1),
) -> AgendaEvent:
    """Um `AgendaEvent` ligado ao contato, direto pelo model — no molde de `_row` em
    `test_agenda_por_contato.py`. O `tenant_id` vem do próprio contato, como `_conversa_esperando`
    faz para a mensagem de WhatsApp."""
    contato = db.get(Client, client_id)
    agora = datetime.now(UTC)
    evento = AgendaEvent(
        tenant_id=contato.tenant_id, title=titulo, kind="atendimento", status=status,
        client_id=client_id, starts_at=agora + em, ends_at=agora + em + timedelta(hours=1),
    )
    db.add(evento)
    db.commit()
    return evento


def _cards(payload: dict) -> dict[str, dict]:
    return {c["id"]: c for col in payload["columns"] for c in col["clients"]}


def test_board_traz_o_proximo_compromisso_do_contato(client, db, headers):
    marcado = _contato(client, headers, "Tem compromisso")
    sem_nada = _contato(client, headers, "Sem compromisso")
    _compromisso(db, marcado, titulo="Reunião de alinhamento")

    resp = client.get("/crm/board", headers=headers)
    assert resp.status_code == 200
    cards = _cards(resp.json())

    assert cards[marcado]["next_event_title"] == "Reunião de alinhamento"
    assert cards[marcado]["next_event_at"] is not None
    assert cards[sem_nada]["next_event_at"] is None
    assert cards[sem_nada]["next_event_title"] is None


def test_board_nao_traz_compromisso_cancelado(client, db, headers):
    """Cancelado não é próximo passo nenhum — mesma regra que `next_event_map` já aplica."""
    contato = _contato(client, headers, "Só tem cancelado")
    _compromisso(db, contato, titulo="Cancelado", status=STATUS_CANCELLED)

    resp = client.get("/crm/board", headers=headers)
    assert resp.status_code == 200
    card = _cards(resp.json())[contato]

    assert card["next_event_at"] is None
    assert card["next_event_title"] is None


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


def test_board_nao_faz_uma_consulta_por_card_com_proximo_passo(client, db, headers):
    """Mesma trava do `unread`: dobrar os cards não pode dobrar as consultas.

    O jeito errado de implementar isto é perguntar pelo próximo evento por contato, dentro do
    laço que monta as colunas. `next_event_map` existe para custar UMA consulta agregada,
    igual `last_interaction_map` e `unread_client_ids` — e essa garantia só se prova medindo,
    não lendo o JSON de resposta.
    """
    engine = db.get_bind()
    for i in range(2):
        _compromisso(db, _contato(client, headers, f"Contato {i}"))
    com_2 = _consultas_do_board(client, headers, engine)

    for i in range(2, 8):
        _compromisso(db, _contato(client, headers, f"Contato {i}"))
    com_8 = _consultas_do_board(client, headers, engine)

    assert com_8 == com_2, (
        f"{com_2} consultas com 2 cards e {com_8} com 8 — o custo está crescendo com os cards"
    )
