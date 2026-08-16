"""Task 2 da Onda 2: a Agenda passa a falar de contato.

Cobre três coisas: (1) `client_id` trafega em EventCreate/EventUpdate/EventOut e filtra
`GET /agenda/events`; (2) uma cobrança criada em `receivables` já nasce com o evento LIGADO ao
contato (não só o passado, que a Task 1 fez via backfill); (3) `next_event_map`, o agregado que
vai alimentar a linha "próximo compromisso" do card do Kanban.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tz import DEFAULT_TENANT_TIMEZONE, day_window_utc, tenant_today
from app.modules.agenda import service as agenda_service
from app.modules.agenda.models import STATUS_CANCELLED, AgendaEvent

REGISTER = {
    "legal_name": "Agenda por Contato ME",
    "document": "55666777000181",
    "slug": "agendaporcontato",
    "email": "dona@example.com",
    "name": "Dona",
    "password": "uma-senha-bem-forte",
}

TENANT_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _event(**over):
    base = {
        "title": "Atendimento João",
        "kind": "atendimento",
        "starts_at": "2026-07-01T10:00:00+00:00",
        "ends_at": "2026-07-01T11:00:00+00:00",
    }
    return {**base, **over}


def _row(db: Session, *, client_id: str | None, starts_at: datetime, ends_at: datetime,
         status: str = "scheduled", all_day: bool = False,
         event_id: str | None = None) -> AgendaEvent:
    """Cria um `AgendaEvent` direto pelo model (sem passar por `create_event`) — os testes de
    `next_event_map` abaixo não precisam da checagem de conflito nem do vínculo com Google/Meet,
    só de linhas na tabela com os campos que a consulta agregada lê."""
    kwargs = dict(
        tenant_id=TENANT_ID, title="Compromisso", kind="atendimento", status=status,
        client_id=client_id, starts_at=starts_at, ends_at=ends_at, all_day=all_day,
    )
    if event_id is not None:
        kwargs["id"] = event_id
    row = AgendaEvent(**kwargs)
    db.add(row)
    db.commit()
    return row


# ── client_id em EventCreate/EventUpdate/EventOut e no filtro do GET ────────────────────────


def test_cria_evento_com_client_id_e_le_de_volta(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Agenda"}, headers=headers).json()
    resp = client.post("/agenda/events", json=_event(client_id=cl["id"]), headers=headers)
    assert resp.status_code == 201, resp.text
    created = resp.json()["event"]
    assert created["client_id"] == cl["id"]

    fetched = client.get(f"/agenda/events/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["client_id"] == cl["id"]


def test_filtro_por_client_id_traz_so_os_daquele_contato(client: TestClient, headers):
    a = client.post("/crm/clients", json={"name": "Contato A"}, headers=headers).json()
    b = client.post("/crm/clients", json={"name": "Contato B"}, headers=headers).json()
    client.post("/agenda/events", json=_event(client_id=a["id"]), headers=headers)
    client.post(
        "/agenda/events",
        json=_event(
            title="Evento B", client_id=b["id"],
            starts_at="2026-07-02T10:00:00+00:00", ends_at="2026-07-02T11:00:00+00:00",
        ),
        headers=headers,
    )

    resp = client.get("/agenda/events", params={"client_id": a["id"]}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["client_id"] == a["id"]


def test_evento_sem_client_id_nao_aparece_no_filtro(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Contato C"}, headers=headers).json()
    client.post("/agenda/events", json=_event(client_id=cl["id"]), headers=headers)
    client.post(
        "/agenda/events",
        json=_event(
            title="Bloqueio sem contato", kind="bloqueio",
            starts_at="2026-07-02T10:00:00+00:00", ends_at="2026-07-02T11:00:00+00:00",
        ),
        headers=headers,
    )

    resp = client.get("/agenda/events", params={"client_id": cl["id"]}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["client_id"] == cl["id"]


# ── receivables grava o vínculo no evento que ela cria ──────────────────────────────────────


def test_cobranca_criada_ja_nasce_com_client_id_no_evento(client: TestClient, db: Session, headers):
    """`receivables` cria o evento da Agenda; ele tem que nascer ligado, não só o passado."""
    cl = client.post("/crm/clients", json={"name": "Pagador Agenda"}, headers=headers).json()
    due_date = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    charge = client.post(
        "/receivables/charges",
        json={
            "kind": "service", "method": "pix", "amount_cents": 5000,
            "due_date": due_date, "description": "Mensalidade", "client_id": cl["id"],
        },
        headers=headers,
    ).json()

    event = db.scalars(
        select(AgendaEvent).where(AgendaEvent.external_ref == charge["id"])
    ).first()
    assert event is not None
    assert event.client_id == cl["id"]


# ── next_event_map: o agregado que alimenta a linha "próximo compromisso" do card ───────────


def test_next_event_map_traz_o_mais_proximo_por_contato(db: Session):
    agora = datetime.now(UTC)
    perto = _row(
        db, client_id="cli-1",
        starts_at=agora + timedelta(hours=1), ends_at=agora + timedelta(hours=2),
    )
    _row(
        db, client_id="cli-1",
        starts_at=agora + timedelta(days=3), ends_at=agora + timedelta(days=3, hours=1),
    )

    mapa = agenda_service.next_event_map(db)
    assert mapa["cli-1"].id == perto.id


def test_next_event_map_ignora_cancelado(db: Session):
    agora = datetime.now(UTC)
    _row(
        db, client_id="cli-2",
        starts_at=agora + timedelta(hours=1), ends_at=agora + timedelta(hours=2),
        status=STATUS_CANCELLED,
    )
    depois = _row(
        db, client_id="cli-2",
        starts_at=agora + timedelta(days=1), ends_at=agora + timedelta(days=1, hours=1),
    )

    mapa = agenda_service.next_event_map(db)
    # O cancelado é o mais perto — se contasse, o mapa apontaria pra ele, não pro `depois`.
    assert mapa["cli-2"].id == depois.id


def test_next_event_map_inclui_evento_de_dia_inteiro_de_hoje(db: Session):
    """⚠️ O caso que uma implementação ingênua erra.

    Evento de dia inteiro é ancorado na meia-noite REAL do fuso do tenant (ver
    `agenda/service.create_event`). Às 15h, o `starts_at` dele já passou — filtrar por
    `starts_at >= agora` esconderia o compromisso de HOJE, que é justamente o mais
    relevante que o card poderia mostrar. O critério é `ends_at >= agora`.
    """
    # Mesma conversão que `create_event` faz no ramo `all_day` (`day_window_utc` sobre o dia
    # calendário do tenant): a janela é [meia-noite local de HOJE, meia-noite local de AMANHÃ),
    # em UTC. Por construção, `tenant_today(...)` é o dia que CONTÉM o instante atual — logo
    # `starts_at` (a meia-noite de hoje) já ficou no passado assim que o dia começou, e
    # `ends_at` (a meia-noite de amanhã) só chega no futuro. Uma implementação que corta por
    # `starts_at >= agora` avaliaria essa condição como False e DESCARTARIA o evento; só o corte
    # por `ends_at >= agora` o inclui — é exatamente essa diferença que este teste prova.
    hoje = tenant_today(DEFAULT_TENANT_TIMEZONE)
    starts_at, ends_at = day_window_utc(hoje, DEFAULT_TENANT_TIMEZONE)
    evento = _row(db, client_id="cli-hoje", starts_at=starts_at, ends_at=ends_at, all_day=True)

    mapa = agenda_service.next_event_map(db)
    assert mapa["cli-hoje"].id == evento.id
