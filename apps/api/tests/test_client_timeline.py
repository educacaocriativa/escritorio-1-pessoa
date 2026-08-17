"""Timeline do contato: mescla o narrativo (`facts`) com o financeiro (charges/quotes) e,
desde a Task 4 da Onda 2, o compromisso já realizado (agenda_events)."""
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.facts import Fact

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
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def contato(client: TestClient, headers) -> str:
    return client.post(
        "/crm/clients", json={"name": "Flavio Kato", "phone": "(11) 99999-8888"},
        headers=headers,
    ).json()["id"]


def test_timeline_comeca_com_a_chegada(client: TestClient, headers, contato):
    resp = client.get(f"/crm/clients/{contato}/timeline", headers=headers)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["truncated"] is False
    assert [e["kind"] for e in corpo["entries"]] == ["crm.lead.criado"]


def test_timeline_inclui_a_cobranca_sem_copiar_o_valor(client: TestClient, headers, contato, db):
    """O financeiro é LIDO de `charges`. Nenhuma linha de `facts` guarda o valor.

    A cobrança é semeada direto no banco (e não pela rota) de propósito: o contrato de
    `POST /receivables/charges` não é definido por este plano, e o que está sendo provado
    aqui é o read model da timeline, não a criação de cobrança.
    """
    from sqlalchemy import select

    from app.modules.crm.models import Client
    from app.modules.receivables.models import Charge

    tenant_id = db.scalar(select(Client.tenant_id).where(Client.id == contato))
    db.add(
        Charge(
            tenant_id=tenant_id, client_id=contato, description="Ensaio",
            kind="service", method="pix", amount_cents=120000,
            due_date=date(2026, 9, 10),
        )
    )
    db.commit()

    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    entrada = next(e for e in corpo["entries"] if e["kind"] == "charge")
    assert "1.200,00" in entrada["title"]

    # A fonte única do valor continua sendo `charges`: nenhum evento narrativo o copiou.
    eventos = list(
        db.scalars(select(Fact).where(Fact.client_id == contato)).all()
    )
    assert all("1.200,00" not in (e.title + e.body) for e in eventos)


def test_timeline_ordena_do_mais_recente_para_o_mais_antigo(client: TestClient, headers, contato):
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")
    client.post(f"/crm/clients/{contato}/move", json={"stage_id": proposta["id"]}, headers=headers)

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    ats = [e["at"] for e in entries]
    assert ats == sorted(ats, reverse=True)
    assert entries[-1]["kind"] == "crm.lead.criado"  # o mais antigo é a chegada


def test_gravar_nota_aparece_na_timeline(client: TestClient, headers, contato):
    resp = client.post(
        f"/crm/clients/{contato}/notes",
        json={"title": "Desconto aprovado", "body": "Cliente pediu 10%, fechamos em 10%"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "crm.nota.criada"

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    nota = next(e for e in entries if e["kind"] == "crm.nota.criada")
    assert nota["title"] == "Desconto aprovado"
    assert "10%" in nota["body"]


def test_nota_sem_titulo_e_rejeitada(client: TestClient, headers, contato):
    resp = client.post(f"/crm/clients/{contato}/notes", json={"title": "  "}, headers=headers)
    assert resp.status_code == 422


def test_timeline_de_contato_inexistente_da_404(client: TestClient, headers):
    assert client.get("/crm/clients/nao-existe/timeline", headers=headers).status_code == 404


def test_truncated_quando_passa_do_teto(client: TestClient, headers, contato):
    for i in range(101):
        client.post(
            f"/crm/clients/{contato}/notes", json={"title": f"nota {i}"}, headers=headers
        )
    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    assert corpo["truncated"] is True
    assert len(corpo["entries"]) == 100


# ── Task 4 da Onda 2: a 4ª fonte — compromisso REALIZADO, lido de `agenda_events` ───────────


def test_timeline_inclui_compromisso_realizado(client: TestClient, headers, contato):
    """Compromisso que já aconteceu é fato do relacionamento — vive no Histórico, não no bloco."""
    resp = client.post(
        "/agenda/events",
        json={
            "title": "Sessão de fotos", "kind": "atendimento",
            "starts_at": "2026-01-10T13:00:00+00:00", "ends_at": "2026-01-10T14:00:00+00:00",
            "client_id": contato,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    entrada = next(e for e in entries if e["kind"] == "agenda")
    assert entrada["title"] == "Compromisso: Sessão de fotos"
    assert entrada["actor"] == "sistema"


def test_timeline_nao_inclui_compromisso_futuro(client: TestClient, headers, contato):
    """O futuro é assunto do bloco de Agenda. Duas telas, duas perguntas."""
    futuro = datetime.now(UTC) + timedelta(days=30)
    resp = client.post(
        "/agenda/events",
        json={
            "title": "Reunião ainda por vir", "kind": "reuniao",
            "starts_at": futuro.isoformat(),
            "ends_at": (futuro + timedelta(hours=1)).isoformat(),
            "client_id": contato,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    assert all(e["kind"] != "agenda" for e in entries)


def test_timeline_nao_inclui_compromisso_cancelado(client: TestClient, headers, contato):
    """Cancelado não é fato: a timeline não pode dizer "você se encontrou" de um encontro
    que não houve.

    O evento é criado no PASSADO de propósito — `ends_at < agora` já seria motivo suficiente
    para incluí-lo, então só o filtro de `status` pode estar segurando este teste. Um evento
    cancelado no FUTURO não provaria nada: o filtro de data já bastaria para escondê-lo.
    """
    resp = client.post(
        "/agenda/events",
        json={
            "title": "Consulta cancelada", "kind": "atendimento",
            "starts_at": "2026-01-10T13:00:00+00:00", "ends_at": "2026-01-10T14:00:00+00:00",
            "client_id": contato,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    event_id = resp.json()["event"]["id"]

    cancel_resp = client.post(f"/agenda/events/{event_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200, cancel_resp.text

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    assert all(e["kind"] != "agenda" for e in entries)


# ── Achado da revisão final da Onda 2: cobrança NÃO pode duplicar como compromisso fantasma ─


def test_cobranca_via_api_nao_duplica_como_compromisso_na_timeline(
    client: TestClient, headers, contato,
):
    """Vai pela rota real (`POST /receivables/charges`), não por um `Charge(...)` cru no banco.

    `test_timeline_inclui_a_cobranca_sem_copiar_o_valor` semeia a `Charge` direto no banco —
    isso NUNCA passa por `receivables.service.build_charge`, então o `AgendaEvent` gêmeo (que
    `build_charge` cria, com o MESMO `client_id`) nunca chega a existir, e o teste não conseguia
    enxergar o bug: a cobrança tinha que nascer pela rota de verdade para o evento fantasma
    também nascer.

    O vencimento é no PASSADO de propósito: só um evento com `ends_at < agora` entra nesta
    timeline (é o corte de "já realizado"). Uma cobrança com vencimento futuro não provaria nada
    — o filtro de data já a esconderia, kind ou não.
    """
    due_date = (datetime.now(UTC).date() - timedelta(days=5)).isoformat()
    resp = client.post(
        "/receivables/charges",
        json={
            "kind": "service", "method": "pix", "amount_cents": 30000,
            "due_date": due_date, "description": "Consulta", "client_id": contato,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]

    cobrancas = [e for e in entries if e["kind"] == "charge"]
    assert len(cobrancas) == 1

    # A trava real deste teste: NENHUM "Compromisso: A receber: ..." fantasma — a mesma
    # cobrança não pode aparecer também como `kind == "agenda"`.
    fantasmas = [e for e in entries if e["kind"] == "agenda"]
    assert fantasmas == [], f"compromisso fantasma vazando na timeline: {fantasmas}"


def test_timeline_de_agenda_respeita_o_limite_por_fonte(client: TestClient, headers, contato):
    """Mesma regra das outras três fontes: `LIMITE_POR_FONTE` e `truncated`."""
    base = datetime.now(UTC) - timedelta(days=365)
    for i in range(101):
        inicio = base + timedelta(hours=i)
        resp = client.post(
            "/agenda/events",
            json={
                "title": f"Atendimento {i}", "kind": "atendimento",
                "starts_at": inicio.isoformat(),
                "ends_at": (inicio + timedelta(minutes=30)).isoformat(),
                "client_id": contato,
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    assert corpo["truncated"] is True
    # A fonte por si só já corta em 100 (LIMITE_POR_FONTE); o corte global da timeline, que
    # mescla com o fato "crm.lead.criado" do próprio contato, pode tirar mais uma — por isso o
    # intervalo, em vez de um número fixo: o que este teste prova é que a Agenda nunca aparece
    # acima do teto, não a aritmética exata da mescla final.
    agenda_entries = [e for e in corpo["entries"] if e["kind"] == "agenda"]
    assert 99 <= len(agenda_entries) <= 100
