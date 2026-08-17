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
from app.modules.agenda.models import STATUS_CANCELLED, STATUS_DONE, AgendaEvent
from app.modules.receivables.models import Charge

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


# ── exclude_cancelled: achado da revisão do Task 6 ──────────────────────────────────────────
# Histórico (`crm/timeline.py`) e `next_event_map` já excluem cancelado; `list_events` era o
# único dos três que não tinha essa trava. `BlocoDaAgenda` (ficha 360°) pede `exclude_cancelled`
# explicitamente para não impersonar um cancelado como "próximo compromisso"; a Agenda continua
# sem passar o parâmetro, então o default tem que preservar o comportamento de hoje.


def test_exclude_cancelled_filtra_o_cancelado_do_filtro_por_contato(client: TestClient, headers):
    """A chamada que o `BlocoDaAgenda` faz: um evento futuro CANCELADO não pode aparecer."""
    cl = client.post("/crm/clients", json={"name": "Cliente Cancelado"}, headers=headers).json()
    created = client.post(
        "/agenda/events",
        json=_event(
            client_id=cl["id"],
            starts_at="2099-01-01T10:00:00+00:00", ends_at="2099-01-01T11:00:00+00:00",
        ),
        headers=headers,
    ).json()["event"]
    cancel = client.post(f"/agenda/events/{created['id']}/cancel", headers=headers)
    assert cancel.status_code == 200

    resp = client.get(
        "/agenda/events",
        params={"client_id": cl["id"], "exclude_cancelled": "true"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_exclude_cancelled_tambem_filtra_o_done_adiantado(client: TestClient, db: Session, headers):
    """Achado da revisão final da Onda 2: `TERMINAL_STATUSES` = {cancelled, done}, não só
    cancelado. Um compromisso marcado `done` ANTES da hora (o dono adianta o status) não pode
    continuar aparecendo no bloco de "próximos compromissos" da ficha 360° — já aconteceu, do
    ponto de vista de quem olha o card."""
    cl = client.post(
        "/crm/clients", json={"name": "Cliente Done Adiantado"}, headers=headers
    ).json()
    agora = datetime.now(UTC)
    db.add(
        AgendaEvent(
            tenant_id=cl["tenant_id"], title="Feito antes da hora", kind="atendimento",
            status=STATUS_DONE, client_id=cl["id"],
            starts_at=agora + timedelta(days=1), ends_at=agora + timedelta(days=1, hours=1),
        )
    )
    db.commit()

    resp = client.get(
        "/agenda/events",
        params={"client_id": cl["id"], "exclude_cancelled": "true"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_sem_exclude_cancelled_o_padrao_continua_devolvendo_o_cancelado(
    client: TestClient, headers,
):
    """Default `False` é escolha de COMPATIBILIDADE, não descuido — a tela de Agenda (que não
    manda o parâmetro) continua vendo todo evento, cancelado incluso, como sempre viu."""
    cl = client.post("/crm/clients", json={"name": "Cliente Cancelado 2"}, headers=headers).json()
    created = client.post(
        "/agenda/events",
        json=_event(
            client_id=cl["id"],
            starts_at="2099-01-01T10:00:00+00:00", ends_at="2099-01-01T11:00:00+00:00",
        ),
        headers=headers,
    ).json()["event"]
    client.post(f"/agenda/events/{created['id']}/cancel", headers=headers)

    resp = client.get("/agenda/events", params={"client_id": cl["id"]}, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["status"] == "cancelled"


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


def test_next_event_map_ignora_done_adiantado(db: Session):
    """Irmã de `test_next_event_map_ignora_cancelado`: `done` ANTES da hora também não é
    próximo passo. `TERMINAL_STATUSES = {cancelled, done}` — achado da revisão final da Onda 2,
    que a implementação original só cobria a metade `cancelled`."""
    agora = datetime.now(UTC)
    _row(
        db, client_id="cli-3",
        starts_at=agora + timedelta(hours=1), ends_at=agora + timedelta(hours=2),
        status=STATUS_DONE,
    )
    depois = _row(
        db, client_id="cli-3",
        starts_at=agora + timedelta(days=1), ends_at=agora + timedelta(days=1, hours=1),
    )

    mapa = agenda_service.next_event_map(db)
    # O `done` adiantado é o mais perto — se contasse, o mapa apontaria pra ele, não pro `depois`.
    assert mapa["cli-3"].id == depois.id


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


# ── Task 3: _events_out — join direto substitui a derivação por external_ref, MAS só a ──────
# ── metade das cobranças. A metade do fornecedor (payables) não tem client_id e fica. ───────


def test_cobranca_e_evento_concordam_no_client_id_ligado(client: TestClient, db: Session, headers):
    """Checagem de base, NÃO a trava da limpeza: prova só que Tasks 1/2 ligaram os ids certos.

    Faz dois lookups crus no banco (Charge.client_id e AgendaEvent.client_id) e afirma que
    concordam — nunca chama `_events_out` nem bate no endpoint, então não exercita o join que
    o router faz. `test_cobranca_criada_ja_nasce_com_client_id_no_evento` (acima) já cobre esse
    mesmo fato de forma mais direta; este teste fica como reforço de que o vínculo é o MESMO id
    dos dois lados, não como guarda da refatoração de `_events_out` — essa guarda é
    `test_client_name_no_get_events_vem_do_join_direto`, abaixo, que bate no endpoint real.
    """
    cl = client.post("/crm/clients", json={"name": "Cliente Paridade"}, headers=headers).json()
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

    charge_row = db.get(Charge, charge["id"])
    assert charge_row.client_id == event.client_id


def test_client_name_no_get_events_vem_do_join_direto(client: TestClient, headers):
    """A trava real da limpeza: `GET /agenda/events` devolve o nome do cliente pelo endpoint.

    Espelha `test_conta_a_pagar_continua_mostrando_o_fornecedor` (abaixo), mas para a metade
    que FOI trocada por join direto. Bate no endpoint de verdade (não em `Client`/`Charge` crus),
    então uma quebra em `_events_out` — por exemplo, um typo que troque `client_id` por
    `external_ref` no join — apareceria aqui, não só numa checagem de banco que nem passa pelo
    router.
    """
    cl = client.post("/crm/clients", json={"name": "Cliente Endpoint"}, headers=headers).json()
    due_date = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    client.post(
        "/receivables/charges",
        json={
            "kind": "service", "method": "pix", "amount_cents": 5000,
            "due_date": due_date, "description": "Mensalidade", "client_id": cl["id"],
        },
        headers=headers,
    )

    events = client.get("/agenda/events", headers=headers).json()
    receber = next(e for e in events if e["kind"] == "cobranca_receber")
    assert receber["client_name"] == "Cliente Endpoint"


def test_conta_a_pagar_continua_mostrando_o_fornecedor(client: TestClient, headers):
    """A metade que NÃO morre. Conta a pagar não tem cliente; o nome vem de `payables.supplier`."""
    resp = client.post(
        "/payables/bills",
        json={
            "description": "Aluguel", "category": "Estrutura", "supplier": "Imobiliária Paridade",
            "amount_cents": 250000, "due_date": "2099-08-05",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    events = client.get("/agenda/events", headers=headers).json()
    pagar = next(e for e in events if e["kind"] == "cobranca_pagar")
    assert pagar["client_name"] == "Imobiliária Paridade"
