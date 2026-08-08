"""Testes da conta de investimento — rendimento e rentabilidade (Story 5.6).

Cobre (Tasks 1-5 / AC1-3 / IV1-3):
- CRUD da conta de investimento (criar/listar/editar principal/indexador/tipo);
- registrar rendimento incrementa `accrued_yield_cents` E cria uma `Charge` PAGA com
  `chart_account_id` no grupo FINANCEIRO, marcada `external_ref='investment:<id>'`;
- **IV1 (teste MAIS importante da story):** registrar rendimento NÃO cria nenhuma `Transaction` na
  Carteira nem `PlatformEarning` (split de vendas intocado) — assert de contagem antes/depois;
- o rendimento NÃO cria evento na Agenda (construção direta, não passa por build_charge);
- rentabilidade total e por período; divisão por zero (principal 0) → None;
- `chart_account_id` fora do grupo FINANCEIRO → 422; inexistente → 404;
- IV3: a `Charge` do rendimento aparece na DRE (5.3) somada ao grupo FINANCEIRO no período.

RLS/isolamento cross-tenant é validado à parte no Postgres real (test_investments_rls.py,
`rls_e2e`) — aqui a suíte roda em SQLite (ver conftest).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.agenda.models import AgendaEvent
from app.modules.financial_intelligence import dre as dre_service
from app.modules.receivables.models import STATUS_PAID, Charge
from app.modules.wallet.models import PlatformEarning, Transaction

REGISTER = {
    "legal_name": "Investe Consultoria",
    "document": "11444777000161",
    "slug": "investe",
    "email": "investe@example.com",
    "name": "Ivo",
    "password": "uma-senha-bem-grande",
}

START = "2026-07-01"
END = "2026-07-31"
D_START = date(2026, 7, 1)
D_END = date(2026, 7, 31)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account(client: TestClient, headers, grupo: str, categoria: str) -> str:
    r = client.post(
        "/chart-of-accounts", json={"grupo_dre": grupo, "categoria": categoria}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _conta_bancaria(
    client: TestClient, headers, *, name="CDB Itaú", kind="investment", opening_date="2026-01-01"
) -> dict:
    """A `bank_account` ONDE O DINHEIRO DA APLICAÇÃO ESTÁ (Onda 2b-i).

    `kind='investment'` funciona desde a Onda 1 — o que a 2b-i acrescenta é a ligação 1:1 com a
    faceta de PRODUTO (`investment_accounts`), que é quem sabe rentabilidade e indexador.
    """
    r = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": kind,
            "number": "",
            "opening_balance_cents": 0,
            "opening_balance_is_known": True,
            "opening_date": opening_date,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _investment(
    client: TestClient,
    headers,
    *,
    name="CDB Banco X",
    principal=1_000_000,
    opened="2026-01-10",
    bank_account_id: str | None = "auto",
) -> dict:
    """A aplicação **nasce vinculada por padrão** (Onda 2b-i), e isso não é conveniência de teste.

    Depois do 409 de `register_yield`, aplicação sem vínculo é um estado de transição — o dono
    passa por ele uma vez e sai. Fazer o helper refletir o estado NORMAL é o que mantém os treze
    call sites de rendimento exercitando o caminho real. Quem quer o estado de transição pede
    `bank_account_id=None`, explicitamente, e há exatamente um teste que o faz.

    Cada aplicação ganha a SUA conta: o índice único `(tenant_id, bank_account_id)` é 1:1.
    """
    if bank_account_id == "auto":
        bank_account_id = _conta_bancaria(client, headers, name=f"Conta {name}")["id"]
    r = client.post(
        "/investments",
        json={
            "name": name,
            "kind": "CDB",
            "index_rate_label": "CDI 110%",
            "principal_cents": principal,
            "opened_at": opened,
            "bank_account_id": bank_account_id,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── CRUD (AC1) ──────────────────────────────────────────────────────────────
def test_requires_auth(client: TestClient):
    assert client.get("/investments").status_code == 401


def test_crud_investment_account(client: TestClient, headers):
    acc = _investment(client, headers, name="Tesouro Selic", principal=500_000)
    assert acc["name"] == "Tesouro Selic"
    assert acc["kind"] == "CDB"
    assert acc["index_rate_label"] == "CDI 110%"
    assert acc["principal_cents"] == 500_000
    assert acc["accrued_yield_cents"] == 0

    lst = client.get("/investments", headers=headers).json()
    assert [a["name"] for a in lst] == ["Tesouro Selic"]

    # editar principal/indexador/tipo/nome
    r = client.patch(
        f"/investments/{acc['id']}",
        json={"name": "Tesouro IPCA", "index_rate_label": "IPCA+6%", "principal_cents": 700_000},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Tesouro IPCA"
    assert r.json()["index_rate_label"] == "IPCA+6%"
    assert r.json()["principal_cents"] == 700_000
    # editar NÃO mexe no rendimento acumulado
    assert r.json()["accrued_yield_cents"] == 0


def test_empty_name_rejected(client: TestClient, headers):
    assert client.post(
        "/investments", json={"name": "  ", "opened_at": "2026-01-10"}, headers=headers
    ).status_code == 422


def test_update_missing_account_is_404(client: TestClient, headers):
    r = client.patch("/investments/nao-existe", json={"name": "X"}, headers=headers)
    assert r.status_code == 404


# ── Registrar rendimento (AC2) ──────────────────────────────────────────────
def test_register_yield_increments_and_creates_financeiro_charge(
    client: TestClient, headers, db: Session
):
    rend = _account(client, headers, "FINANCEIRO", "Rendimento de aplicação")
    acc = _investment(client, headers, principal=1_000_000)

    r = client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 12_000, "date": "2026-07-05", "chart_account_id": rend},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["accrued_yield_cents"] == 12_000

    # rendendo de novo acumula
    r2 = client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 3_000, "date": "2026-07-20", "chart_account_id": rend},
        headers=headers,
    )
    assert r2.json()["accrued_yield_cents"] == 15_000

    # criou DUAS Charges pagas, no grupo FINANCEIRO, marcadas como rendimento
    charges = list(db.scalars(select(Charge)).all())
    assert len(charges) == 2
    for c in charges:
        assert c.status == STATUS_PAID
        assert c.paid_at is not None
        assert c.chart_account_id == rend
        assert c.external_ref == f"investment:{acc['id']}"
        assert c.client_id is None
        assert c.transaction_id is None  # nunca ligada à carteira


# ── IV1: NÃO aciona Carteira/split (o teste mais importante) ─────────────────
def test_register_yield_creates_no_transaction_nor_platform_earning(
    client: TestClient, headers, db: Session
):
    """IV1: registrar rendimento NÃO cria Transaction na Carteira nem PlatformEarning — é receita
    financeira, não venda com split de plataforma. Assert de contagem antes/depois = 0 novas."""
    rend = _account(client, headers, "FINANCEIRO", "Rendimento de aplicação")
    acc = _investment(client, headers, principal=2_000_000)

    tx_before = len(list(db.scalars(select(Transaction)).all()))
    pe_before = len(list(db.scalars(select(PlatformEarning)).all()))

    client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 50_000, "date": "2026-07-10", "chart_account_id": rend},
        headers=headers,
    )

    db.expire_all()
    tx_after = list(db.scalars(select(Transaction)).all())
    pe_after = list(db.scalars(select(PlatformEarning)).all())
    assert len(tx_after) == tx_before, "IV1 violado: rendimento criou Transaction na Carteira"
    assert len(pe_after) == pe_before, "IV1 violado: rendimento criou PlatformEarning (split)"


def test_register_yield_creates_no_agenda_event(client: TestClient, headers, db: Session):
    """Construção direta (não via build_charge) → nenhum evento de vencimento na Agenda."""
    rend = _account(client, headers, "FINANCEIRO", "Rendimento de aplicação")
    acc = _investment(client, headers)
    before = len(list(db.scalars(select(AgendaEvent)).all()))
    client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 1_000, "date": "2026-07-10", "chart_account_id": rend},
        headers=headers,
    )
    db.expire_all()
    assert len(list(db.scalars(select(AgendaEvent)).all())) == before


# ── Validação de grupo (AC2) ────────────────────────────────────────────────
def test_yield_chart_account_outside_financeiro_is_422(client: TestClient, headers):
    receita = _account(client, headers, "RECEITA", "Consultoria")
    acc = _investment(client, headers)
    r = client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 1_000, "date": "2026-07-10", "chart_account_id": receita},
        headers=headers,
    )
    assert r.status_code == 422, r.text


def test_yield_missing_chart_account_is_404(client: TestClient, headers):
    acc = _investment(client, headers)
    r = client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 1_000, "date": "2026-07-10", "chart_account_id": "nao-existe"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_yield_without_chart_account_is_allowed(client: TestClient, headers, db: Session):
    """chart_account_id é opcional (assinatura da Task 2): sem ele, o lançamento é criado sem
    classificação (cai em SEM_CATEGORIA na DRE). A validação de grupo só roda quando informado."""
    acc = _investment(client, headers)
    r = client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 1_000, "date": "2026-07-10"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["accrued_yield_cents"] == 1_000
    charge = db.scalars(select(Charge)).one()
    assert charge.chart_account_id is None


def test_yield_amount_must_be_positive(client: TestClient, headers):
    acc = _investment(client, headers)
    r = client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 0, "date": "2026-07-10"},
        headers=headers,
    )
    assert r.status_code == 422


# ── Story 5.6 quality gate (Aria): rendimento NÃO polui as telas de Contas a Receber ──────
def test_yield_charge_excluded_from_receivables_surfaces(client: TestClient, headers):
    """Decisão de arquitetura (Aria, quality_gate) — Opção A: a Charge sintética de rendimento é um
    lançamento de receita financeira JÁ baixado, NÃO uma cobrança de cliente. Deve entrar na DRE
    (testado em test_yield_appears_in_dre_financeiro_group) mas NÃO poluir Contas a Receber: some da
    lista de cobranças E do "Recebido"/`paid_cents` do resumo (superfície de reconciliação de
    recebíveis de cliente). Uma cobrança REAL de cliente, paga pelo caminho normal, CONTINUA
    aparecendo — o filtro não quebra o comportamento normal."""
    rend = _account(client, headers, "FINANCEIRO", "Rendimento de aplicação")
    acc = _investment(client, headers, principal=1_000_000)

    # rendimento de investimento → Charge sintética paga (external_ref='investment:<id>')
    client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 12_000, "date": "2026-07-05", "chart_account_id": rend},
        headers=headers,
    )

    # cobrança REAL de cliente, paga pelo caminho normal (mark_paid/split)
    cl = client.post("/crm/clients", json={"name": "Cliente Real"}, headers=headers).json()
    ch = client.post(
        "/receivables/charges",
        json={
            "client_id": cl["id"],
            "description": "Consultoria",
            "kind": "service",
            "method": "pix",
            "amount_cents": 40_000,
            "due_date": "2026-07-10",
        },
        headers=headers,
    ).json()
    client.post(f"/receivables/charges/{ch['id']}/pay", headers=headers)

    # a lista de Cobranças mostra SÓ a cobrança real; o rendimento foi filtrado
    charges = client.get("/receivables/charges", headers=headers).json()
    assert [c["id"] for c in charges] == [ch["id"]]

    # "Recebido" do resumo = só a cobrança real (40_000), sem os 12_000 de rendimento
    summary = client.get("/receivables/summary", headers=headers).json()
    assert summary["paid_cents"] == 40_000


def test_yield_with_null_external_ref_charges_still_listed(client: TestClient, headers):
    """Regressão do footgun de lógica ternária SQL: cobranças normais têm `external_ref=NULL`. O
    filtro usa `coalesce(external_ref,'') NOT LIKE 'investment:%'` justamente para NÃO excluí-las
    (um `NOT LIKE` puro sobre NULL as sumiria). Sem nenhum rendimento, a cobrança normal aparece."""
    ch = client.post(
        "/receivables/charges",
        json={
            "description": "Mensalidade",
            "kind": "service",
            "method": "pix",
            "amount_cents": 10_000,
            "due_date": "2026-08-10",
        },
        headers=headers,
    ).json()
    charges = client.get("/receivables/charges", headers=headers).json()
    assert [c["id"] for c in charges] == [ch["id"]]


# ── Rentabilidade (AC3) ─────────────────────────────────────────────────────
def test_rentability_total_and_period(client: TestClient, headers):
    rend = _account(client, headers, "FINANCEIRO", "Rendimento de aplicação")
    acc = _investment(client, headers, principal=1_000_000)
    # dois rendimentos em julho + um em agosto (fora do período consultado)
    for amount, d in [(20_000, "2026-07-05"), (30_000, "2026-07-25"), (5_000, "2026-08-10")]:
        client.post(
            f"/investments/{acc['id']}/yield",
            json={"amount_cents": amount, "date": d, "chart_account_id": rend},
            headers=headers,
        )

    # total: 55000 / 1000000 = 0.055
    full = client.get(f"/investments/{acc['id']}/rentability", headers=headers).json()
    assert full["accrued_yield_cents"] == 55_000
    assert full["total_rentability_pct"] == pytest.approx(0.055)
    # período aberto: soma tudo
    assert full["period_yield_cents"] == 55_000

    # período de julho: só 20000 + 30000 = 50000 → 0.05
    jul = client.get(
        f"/investments/{acc['id']}/rentability",
        params={"start": START, "end": END},
        headers=headers,
    ).json()
    assert jul["period_yield_cents"] == 50_000
    assert jul["period_rentability_pct"] == pytest.approx(0.05)
    # total não muda com o filtro de período
    assert jul["total_rentability_pct"] == pytest.approx(0.055)


def test_rentability_zero_principal_does_not_divide_by_zero(client: TestClient, headers):
    rend = _account(client, headers, "FINANCEIRO", "Rendimento de aplicação")
    acc = _investment(client, headers, principal=0)
    client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 1_000, "date": "2026-07-10", "chart_account_id": rend},
        headers=headers,
    )
    r = client.get(f"/investments/{acc['id']}/rentability", headers=headers).json()
    assert r["principal_cents"] == 0
    assert r["total_rentability_pct"] is None
    assert r["period_rentability_pct"] is None
    assert r["period_yield_cents"] == 1_000  # o rendimento acumulado ainda é reportado


def test_rentability_missing_account_is_404(client: TestClient, headers):
    assert client.get("/investments/nao-existe/rentability", headers=headers).status_code == 404


# ── IV3: o rendimento entra na DRE (5.3) no grupo FINANCEIRO ─────────────────
def test_yield_appears_in_dre_financeiro_group(client: TestClient, headers, db: Session):
    """IV3: a Charge do rendimento aparece na DRE somada ao grupo FINANCEIRO, no período de
    competência correto (integração investments + financial_intelligence.dre)."""
    rend = _account(client, headers, "FINANCEIRO", "Rendimento de aplicação")
    acc = _investment(client, headers, principal=1_000_000)
    client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 18_000, "date": "2026-07-15", "chart_account_id": rend},
        headers=headers,
    )
    # rendimento em agosto NÃO deve entrar no período de julho
    client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 9_000, "date": "2026-08-15", "chart_account_id": rend},
        headers=headers,
    )

    report = dre_service.dre_report(db, start=D_START, end=D_END)
    financeiro = next(g for g in report.groups if g.grupo_dre == "FINANCEIRO")
    # sinal +1 (origem Charge), só o rendimento de julho
    assert financeiro.total_cents == 18_000
    cats = {c.categoria: c.amount_cents for c in financeiro.categorias}
    assert cats["Rendimento de aplicação"] == 18_000
    # e conta no resultado operacional (FINANCEIRO ∈ RESULT_GROUPS)
    assert report.resultado_cents == 18_000


# ── Onda 2b-i — o vínculo 1:1 com a conta bancária da aplicação ──────────────────────────────


def test_vincular_a_aplicacao_a_conta_bancaria_dela(client: TestClient, headers):
    """O caminho feliz do vínculo, pelo PATCH — é assim que a aplicação LEGADA é vinculada.

    O vínculo é ato do dono, na tela: por isso a migration 0075 não faz backfill nenhum, e é
    justamente o backfill ausente que a mantém fora da armadilha do `FORCE ROW LEVEL SECURITY`.
    """
    conta = _conta_bancaria(client, headers)
    acc = _investment(client, headers, bank_account_id=None)  # o estado LEGADO, pré-2b-i
    assert acc["bank_account_id"] is None

    r = client.patch(
        f"/investments/{acc['id']}", json={"bank_account_id": conta["id"]}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["bank_account_id"] == conta["id"]


def test_vincular_ja_na_criacao(client: TestClient, headers):
    """A aplicação NOVA nasce vinculada — senão o dono cadastra e leva um 409 no primeiro
    rendimento, que é o beco que o 409 acionável existe para evitar."""
    conta = _conta_bancaria(client, headers)
    acc = _investment(client, headers, bank_account_id=conta["id"])
    assert acc["bank_account_id"] == conta["id"]


def test_a_conta_vinculada_precisa_ser_do_tipo_aplicacao(client: TestClient, headers):
    """Vincular a aplicação a uma conta CORRENTE creditaria o rendimento no lugar errado — e os
    dois saldos derivados passariam a mentir juntos."""
    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    acc = _investment(client, headers)

    r = client.patch(
        f"/investments/{acc['id']}", json={"bank_account_id": corrente["id"]}, headers=headers
    )
    assert r.status_code == 422, r.text
    assert "aplicação" in r.json()["detail"]


def test_conta_bancaria_inexistente_da_404_e_NUNCA_409(client: TestClient, headers):
    """404 fail-closed. **409 confirmaria a existência da linha** — e conta de outro tenant chega
    aqui exatamente assim, escondida pela RLS. O equivalente cross-tenant real mora em
    `test_investments_rls.py` (`rls_e2e`): no SQLite desta suíte a RLS não existe."""
    acc = _investment(client, headers)
    r = client.patch(
        f"/investments/{acc['id']}",
        json={"bank_account_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert r.status_code == 404, r.text


def test_conta_bancaria_arquivada_e_recusada(client: TestClient, headers):
    """Conta arquivada não recebe lançamento novo — vinculá-la produziria um rendimento que o
    dono não consegue mais ver movimentar."""
    conta = _conta_bancaria(client, headers)
    assert client.post(f"/bank/accounts/{conta['id']}/archive", headers=headers).status_code == 200
    acc = _investment(client, headers)

    r = client.patch(
        f"/investments/{acc['id']}", json={"bank_account_id": conta["id"]}, headers=headers
    )
    assert r.status_code == 409, r.text
    assert "arquivada" in r.json()["detail"]


def test_a_acao_do_409_e_a_MESMA_string_de_payables_e_receivables():
    """**O contrato do 409 acionável é UM, com três constantes — e o teste é a sincronia.**

    A string é duplicada de propósito: fazer `investments` importar `payables` só por uma palavra
    seria acoplamento gratuito entre módulos de negócio (mesmo motivo pelo qual `receivables` já a
    duplica). O que garante que as três não divirjam é **este teste**, não um comentário — a UI
    reconhece a situação por `acao`, e um segundo valor faria a tela deixar de oferecer o vínculo
    **sem erro nenhum**, só sem funcionar.
    """
    from app.modules.investments import service as investments_service
    from app.modules.payables import service as payables_service
    from app.modules.receivables import service as receivables_service

    assert (
        investments_service.ACAO_CADASTRAR_CONTA
        == payables_service.ACAO_CADASTRAR_CONTA
        == receivables_service.ACAO_CADASTRAR_CONTA
    )


def test_registrar_rendimento_sem_vinculo_da_409_ACIONAVEL(client: TestClient, headers):
    """**É este 409 que põe P3 em zero POR CONSTRUÇÃO** — o mesmo mecanismo pelo qual a 8.12 zerou
    P1 ao tornar a coluna obrigatória: a população esvazia sozinha e não depende de o dono lembrar
    de vincular.

    A degradação graciosa da Onda 3 (*"nada acontece, nada quebra"*) é certa LÁ e errada AQUI, e a
    diferença é quem está na sala: o payout é disparado pelo sistema, sem humano na tela a quem
    perguntar; o rendimento é o dono digitando um valor agora.

    **Mutante que este teste mata:** remover a guarda — o rendimento volta a ser criável sem perna,
    e P3 deixa de ser zero por construção.
    """
    acc = _investment(client, headers, bank_account_id=None)
    r = client.post(
        f"/investments/{acc['id']}/yield",
        json={"amount_cents": 48_000, "date": "2026-07-14"},
        headers=headers,
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["acao"] == "cadastrar_conta", "a UI reconhece a situação por este campo"
    assert "Vincule esta aplicação" in detail["mensagem"]


def test_erro_comum_de_investments_continua_sendo_string(client: TestClient, headers):
    """Controle negativo do `detail` estruturado: **só** o erro acionável o preenche. Se todo erro
    virasse dict, a tela quebraria em toda mensagem que ela hoje lê como texto."""
    r = client.patch("/investments/nao-existe", json={"name": "X"}, headers=headers)
    assert r.status_code == 404
    assert isinstance(r.json()["detail"], str)
