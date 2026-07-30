"""Testes da conta bancária — fundação do plano 3 do dinheiro (Story 8.2).

Cobre (Tasks 3-5,7 / AC1-7 / IV1,IV5):
- CRUD: criar (saldo derivado == saldo de abertura), listar, editar, arquivar (lógico, idempotente);
- **N contas por tenant** (decisão do fundador F3): corrente + poupança + aplicação, bancos
  diferentes, dois `kind` iguais — tudo aceito; `DELETE` não existe;
- `kind` VALIDADO (ao contrário dos outros `kind` do projeto) → 422 fora de `KINDS`, e
  `platform_wallet` recusado com mensagem própria (Regra dos Planos §1.3a);
- identidade bancária única por tenant (409), com conta sem número nunca colidindo (índice PARCIAL);
- `is_primary` no máximo UMA por tenant, mantido pelo service; arquivar a primária deixa o tenant
  **sem** primária (nenhuma sucessora eleita em silêncio);
- saldo derivado: `derived_balance`, `derived_balances_as_of` (data comum) e `active_balance_total`
  (exclui `investment`);
- todo saldo exposto declara `saldo_derivado_origem == ORIGEM_BANCO` (AC6);
- **IV1** DRE intacta depois de cadastrar conta com saldo (verdade permanente: `bank_*` nunca entra
  na DRE) e **IV5** Projeção de Caixa — ⚠️ **atualizado pela Story 8.8**: cadastrar conta agora
  MUDA a projeção (origem `misto` + parcela bancária), e o que se afere é que ela muda **só na
  semente**. Ver o bloco de comentário acima daqueles dois testes.

RLS/isolamento cross-tenant NÃO é exercido aqui (SQLite — ver `conftest.py`): é validado no
Postgres real em `test_bank_rls.py` (`rls_e2e`). A Regra dos Planos tem arquivo próprio:
`test_money_planes.py`.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO, ORIGEM_MISTO, ORIGEM_PLATAFORMA, ORIGENS
from app.modules.bank import service
from app.modules.bank.models import (
    KIND_CASH,
    KIND_CHECKING,
    KIND_INVESTMENT,
    KIND_PLATFORM_WALLET,
    KIND_SAVINGS,
    KINDS,
    BankAccount,
)
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import projection as projection_service

REGISTER = {
    "legal_name": "Banco Fundacao ME",
    "document": "11444777000161",
    "slug": "bancofundacao",
    "email": "banco@example.com",
    "name": "Bruna",
    "password": "uma-senha-bem-grande",
}

OPENING = "2026-07-01"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _payload(**over) -> dict:
    base = {
        "name": "Itaú PJ",
        "kind": KIND_CHECKING,
        "institution": "Itaú Unibanco",
        "institution_code": "341",
        "branch": "1234",
        "number": "56789-0",
        "holder_document": "11.444.777/0001-61",
        "pix_key": "banco@example.com",
        "opening_balance_cents": 1_500_00,
        "opening_date": OPENING,
    }
    base.update(over)
    return base


def _create(client: TestClient, headers, **over) -> dict:
    resp = client.post("/bank/accounts", json=_payload(**over), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── AC1/AC5/AC6 — criar e ler ─────────────────────────────────────────────────────────────────


def test_requires_auth(client: TestClient):
    assert client.get("/bank/accounts").status_code == 401


def test_criar_conta_devolve_saldo_derivado_igual_ao_saldo_de_abertura(client: TestClient, headers):
    """AC5: sem movimentos (Story 8.3), o derivado É o saldo de abertura — e nunca uma coluna."""
    acc = _create(client, headers)
    assert acc["saldo_derivado_cents"] == 1_500_00 == acc["opening_balance_cents"]
    assert acc["saldo_derivado_origem"] == ORIGEM_BANCO
    assert acc["is_primary"] is True  # primeira conta do tenant nasce primária (AC7)
    assert acc["archived_at"] is None
    # holder_document normalizado para só-dígitos.
    assert acc["holder_document"] == "11444777000161"


def test_saldo_derivado_nao_e_coluna_no_modelo():
    """AC5, dito de forma que uma story futura não consiga contornar sem ver o teste falhar."""
    columns = set(BankAccount.__table__.columns.keys())
    assert "opening_balance_cents" in columns
    proibidas = {c for c in columns if "balance" in c and c != "opening_balance_cents"}
    assert not proibidas, (
        f"Coluna de saldo apareceu em bank_accounts: {proibidas}. O saldo é DERIVADO (design "
        "§3.1) — materializá-lo troca a única propriedade que este produto vende (que o número é "
        "conferível) por um O(1) que ninguém pediu."
    )


def test_todas_as_superficies_de_saldo_declaram_a_origem(client: TestClient, headers):
    """AC6: nenhum saldo trafega sem procedência — asserção sobre a CONSTANTE, não sobre a
    string literal."""
    acc = _create(client, headers)
    for body in (
        acc,
        client.get(f"/bank/accounts/{acc['id']}", headers=headers).json(),
        client.get("/bank/accounts", headers=headers).json()[0],
        client.get(f"/bank/accounts/{acc['id']}/balance", headers=headers).json(),
        client.patch(
            f"/bank/accounts/{acc['id']}", json={"name": "Itaú PJ (matriz)"}, headers=headers
        ).json(),
        client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers).json(),
    ):
        assert body["saldo_derivado_origem"] == ORIGEM_BANCO
        assert body["saldo_derivado_origem"] in ORIGENS


def test_balance_devolve_a_data_de_corte(client: TestClient, headers):
    acc = _create(client, headers)
    sem_corte = client.get(f"/bank/accounts/{acc['id']}/balance", headers=headers).json()
    assert sem_corte["until"] is None

    com_corte = client.get(
        f"/bank/accounts/{acc['id']}/balance", params={"until": "2026-07-15"}, headers=headers
    ).json()
    assert com_corte["until"] == "2026-07-15"
    # Sem movimentos, o corte não muda o número — mas a data precisa voltar mesmo assim: saldo sem
    # a data em que foi apurado é um número que não dá para conferir.
    assert com_corte["saldo_derivado_cents"] == sem_corte["saldo_derivado_cents"]


def test_conta_inexistente_404(client: TestClient, headers):
    assert client.get("/bank/accounts/nao-existe", headers=headers).status_code == 404
    assert client.get("/bank/accounts/nao-existe/balance", headers=headers).status_code == 404
    assert client.patch(
        "/bank/accounts/nao-existe", json={"name": "x"}, headers=headers
    ).status_code == 404


def test_nao_existe_rota_de_delete(client: TestClient, headers):
    """AC2: a remoção é LÓGICA. Conta encerrada não pode levar o histórico de movimentos junto."""
    acc = _create(client, headers)
    assert client.delete(f"/bank/accounts/{acc['id']}", headers=headers).status_code == 405


# ── AC2 — N contas por tenant (decisão do fundador F3) ────────────────────────────────────────


def test_n_contas_no_mesmo_tenant_inclusive_do_mesmo_kind(client: TestClient, headers):
    """Corrente + poupança + aplicação, bancos diferentes, e duas correntes. Tudo legítimo."""
    _create(client, headers, name="Itaú PJ", kind=KIND_CHECKING, institution_code="341",
            number="1111-1")
    _create(client, headers, name="Itaú Poupança", kind=KIND_SAVINGS, institution_code="341",
            number="2222-2")
    _create(client, headers, name="BB Aplicação", kind=KIND_INVESTMENT, institution_code="001",
            number="3333-3")
    _create(client, headers, name="Nubank PJ", kind=KIND_CHECKING, institution_code="260",
            number="4444-4")

    contas = client.get("/bank/accounts", headers=headers).json()
    assert len(contas) == 4
    assert [c["name"] for c in contas] == sorted(c["name"] for c in contas), "ordena por nome"
    assert sum(c["is_primary"] for c in contas) == 1, "só a primeira nasce primária"


# ── AC4 — `kind` validado ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["corrente", "CHECKING", "", "poupanca", "wallet"])
def test_kind_invalido_422(client: TestClient, headers, kind: str):
    resp = client.post("/bank/accounts", json=_payload(kind=kind), headers=headers)
    assert resp.status_code == 422, resp.text


def test_platform_wallet_e_explicitamente_recusado(client: TestClient, headers):
    """AC4: o valor existe no vocabulário (reservado) mas a API recusa — a Regra dos Planos em
    forma de validação. Se um dia isto virar 201, a Carteira vira uma conta bancária e somar
    plano 1 com plano 3 passa a ser um `SUM` distraído."""
    assert KIND_PLATFORM_WALLET not in KINDS
    resp = client.post("/bank/accounts", json=_payload(kind=KIND_PLATFORM_WALLET), headers=headers)
    assert resp.status_code == 422, resp.text
    assert "Carteira" in resp.json()["detail"], "a mensagem precisa explicar o PORQUÊ ao usuário"


@pytest.mark.parametrize("kind", KINDS)
def test_os_quatro_kinds_aceitos(client: TestClient, headers, kind: str):
    acc = _create(client, headers, kind=kind, number=f"conta-{kind}")
    assert acc["kind"] == kind


def test_kind_invalido_no_patch_tambem_422(client: TestClient, headers):
    acc = _create(client, headers)
    resp = client.patch(
        f"/bank/accounts/{acc['id']}", json={"kind": KIND_PLATFORM_WALLET}, headers=headers
    )
    assert resp.status_code == 422, resp.text


# ── AC1 — validações de saldo de abertura e data ──────────────────────────────────────────────


def test_opening_date_futura_422(client: TestClient, headers):
    futuro = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    resp = client.post("/bank/accounts", json=_payload(opening_date=futuro), headers=headers)
    assert resp.status_code == 422, resp.text


def test_opening_balance_negativo_e_aceito(client: TestClient, headers):
    """Conta no limite / cheque especial é saldo de partida legítimo — recusá-lo obrigaria o
    usuário a mentir um número, que é o oposto do que a conferência precisa."""
    acc = _create(client, headers, opening_balance_cents=-42_000)
    assert acc["opening_balance_cents"] == -42_000
    assert acc["saldo_derivado_cents"] == -42_000


def test_nome_vazio_422(client: TestClient, headers):
    resp = client.post("/bank/accounts", json=_payload(name="   "), headers=headers)
    assert resp.status_code == 422, resp.text


def test_holder_document_invalido_422(client: TestClient, headers):
    resp = client.post(
        "/bank/accounts", json=_payload(holder_document="12345678901"), headers=headers
    )
    assert resp.status_code == 422, resp.text


# ── AC3 — identidade bancária única, sem vazar existência ─────────────────────────────────────


def test_duplicidade_de_identidade_bancaria_409(client: TestClient, headers):
    _create(client, headers, institution_code="341", branch="1234", number="56789-0")
    resp = client.post(
        "/bank/accounts",
        json=_payload(name="Itaú PJ (de novo)", institution_code="341", branch="1234",
                      number="56789-0"),
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert "agência" in resp.json()["detail"], "mensagem precisa ser acionável"


def test_contas_sem_numero_nunca_colidem(client: TestClient, headers):
    """Índice único PARCIAL (`WHERE number <> ''`): "Caixinha" pode existir N vezes.

    ⚠️ Este teste só é honesto porque o modelo declara `sqlite_where` junto do `postgresql_where`
    (ver `models.py`): sem ele, o índice nasceria TOTAL no SQLite e este teste falharia aqui e
    passaria em produção — ou o contrário, dependendo de qual dialeto ficou de fora.
    """
    for i in range(3):
        _create(client, headers, name=f"Caixinha {i}", kind=KIND_CASH, institution_code="",
                branch="", number="")
    assert len(client.get("/bank/accounts", headers=headers).json()) == 3


def test_mesma_agencia_e_numero_em_bancos_diferentes_convivem(client: TestClient, headers):
    _create(client, headers, name="A", institution_code="341", branch="1", number="9")
    acc = _create(client, headers, name="B", institution_code="001", branch="1", number="9")
    assert acc["institution_code"] == "001"


def test_patch_que_criaria_duplicidade_409(client: TestClient, headers):
    _create(client, headers, name="A", institution_code="341", branch="1", number="9")
    b = _create(client, headers, name="B", institution_code="341", branch="1", number="8")
    resp = client.patch(f"/bank/accounts/{b['id']}", json={"number": "9"}, headers=headers)
    assert resp.status_code == 409, resp.text


# ── AC2 — arquivar (nunca deletar) ────────────────────────────────────────────────────────────


def test_arquivar_sai_da_listagem_default_e_e_idempotente(client: TestClient, headers):
    acc = _create(client, headers)
    arquivada = client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers).json()
    assert arquivada["archived_at"] is not None

    assert client.get("/bank/accounts", headers=headers).json() == []
    incluindo = client.get(
        "/bank/accounts", params={"include_archived": True}, headers=headers
    ).json()
    assert [c["id"] for c in incluindo] == [acc["id"]]

    de_novo = client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers).json()
    assert de_novo["archived_at"] == arquivada["archived_at"], "rearquivar mantém o carimbo"


def test_conta_arquivada_continua_legivel_e_com_saldo(client: TestClient, headers):
    """A linha não some: o histórico de movimentos da 8.3 depende dela."""
    acc = _create(client, headers)
    client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers)
    lida = client.get(f"/bank/accounts/{acc['id']}", headers=headers).json()
    assert lida["saldo_derivado_cents"] == 1_500_00


# ── AC7 — no máximo uma conta primária ────────────────────────────────────────────────────────


def test_marcar_outra_como_primaria_desmarca_a_anterior(client: TestClient, headers, db: Session):
    a = _create(client, headers, name="A", number="1")
    b = _create(client, headers, name="B", number="2")
    assert a["is_primary"] is True and b["is_primary"] is False

    promovida = client.patch(
        f"/bank/accounts/{b['id']}", json={"is_primary": True}, headers=headers
    ).json()
    assert promovida["is_primary"] is True
    assert client.get(f"/bank/accounts/{a['id']}", headers=headers).json()["is_primary"] is False
    assert service.primary_account(db).id == b["id"]


def test_arquivar_a_primaria_deixa_o_tenant_sem_primaria(client: TestClient, headers, db: Session):
    """Nenhuma sucessora é eleita em silêncio: escolher a conta de destino do dinheiro do usuário
    sem ele pedir é o tipo de ajuda que só se descobre quando o dinheiro foi para o lugar errado."""
    a = _create(client, headers, name="A", number="1")
    _create(client, headers, name="B", number="2")

    client.post(f"/bank/accounts/{a['id']}/archive", headers=headers)
    assert service.primary_account(db) is None
    assert all(not c["is_primary"] for c in client.get("/bank/accounts", headers=headers).json())


def test_conta_criada_apos_arquivar_a_primaria_assume(client: TestClient, headers, db: Session):
    a = _create(client, headers, name="A", number="1")
    client.post(f"/bank/accounts/{a['id']}/archive", headers=headers)
    nova = _create(client, headers, name="C", number="3")
    assert nova["is_primary"] is True
    assert service.primary_account(db).id == nova["id"]


def test_conta_arquivada_nao_pode_ser_primaria(client: TestClient, headers):
    a = _create(client, headers, name="A", number="1")
    _create(client, headers, name="B", number="2")
    client.post(f"/bank/accounts/{a['id']}/archive", headers=headers)
    resp = client.patch(f"/bank/accounts/{a['id']}", json={"is_primary": True}, headers=headers)
    assert resp.status_code == 422, resp.text


def test_set_primary_service_troca_num_commit_so(client: TestClient, headers, db: Session):
    """`set_primary` existe para a Story 8.7 chamar direto (sem passar pelo PATCH)."""
    a = _create(client, headers, name="A", number="1")
    b = _create(client, headers, name="B", number="2")
    tenant_id = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]

    service.set_primary(db, account_id=b["id"], tenant_id=tenant_id, actor="teste")
    assert service.primary_account(db).id == b["id"]
    assert db.get(BankAccount, a["id"]).is_primary is False


# ── AC5 — as três funções de saldo ────────────────────────────────────────────────────────────


def test_derived_balances_as_of_traz_todas_as_contas_numa_data_comum(
    client: TestClient, headers, db: Session
):
    a = _create(client, headers, name="A", number="1", opening_balance_cents=10_000)
    b = _create(client, headers, name="B", number="2", opening_balance_cents=-2_500)
    arq = _create(client, headers, name="Z", number="3", opening_balance_cents=777)
    client.post(f"/bank/accounts/{arq['id']}/archive", headers=headers)

    saldos = service.derived_balances_as_of(db, as_of=date(2026, 7, 31))
    assert saldos == {a["id"]: 10_000, b["id"]: -2_500}, "arquivada fica de fora por default"

    com_arquivadas = service.derived_balances_as_of(db, as_of=None, include_archived=True)
    assert com_arquivadas[arq["id"]] == 777


def test_active_balance_total_exclui_investimento_por_default(
    client: TestClient, headers, db: Session
):
    """A Story 8.8 soma esta parcela ao `available_cents` sob `ORIGEM_MISTO`. Dinheiro aplicado
    não é caixa disponível para pagar a conta de amanhã (design §6.1)."""
    _create(client, headers, name="Corrente", kind=KIND_CHECKING, number="1",
            opening_balance_cents=100_000)
    _create(client, headers, name="Poupança", kind=KIND_SAVINGS, number="2",
            opening_balance_cents=50_000)
    _create(client, headers, name="CDB", kind=KIND_INVESTMENT, number="3",
            opening_balance_cents=900_000)

    assert service.active_balance_total(db) == 150_000
    assert service.active_balance_total(db, exclude_kinds=()) == 1_050_000
    so_corrente = service.active_balance_total(db, exclude_kinds=(KIND_SAVINGS, KIND_INVESTMENT))
    assert so_corrente == 100_000


def test_active_balance_total_ignora_arquivadas(client: TestClient, headers, db: Session):
    a = _create(client, headers, name="A", number="1", opening_balance_cents=100_000)
    _create(client, headers, name="B", number="2", opening_balance_cents=1)
    client.post(f"/bank/accounts/{a['id']}/archive", headers=headers)
    assert service.active_balance_total(db) == 1


def test_derived_balance_de_conta_inexistente_levanta_404(db: Session, client: TestClient, headers):
    _create(client, headers)
    with pytest.raises(service.BankError) as exc:
        service.derived_balance(db, bank_account_id="nao-existe")
    assert exc.value.status_code == 404


def test_derived_balances_as_of_vazio_para_tenant_sem_conta(client: TestClient, headers,
                                                            db: Session):
    assert service.derived_balances_as_of(db) == {}
    assert service.active_balance_total(db) == 0


# ── Edição ────────────────────────────────────────────────────────────────────────────────────


def test_patch_edita_os_campos_da_conta(client: TestClient, headers):
    acc = _create(client, headers)
    resp = client.patch(
        f"/bank/accounts/{acc['id']}",
        json={
            "name": "Itaú PJ (matriz)",
            "kind": KIND_SAVINGS,
            "institution": "Itaú",
            "branch": "4321",
            "pix_key": "novo@example.com",
            "opening_balance_cents": 2_000_00,
            "opening_date": "2026-06-01",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Itaú PJ (matriz)"
    assert body["kind"] == KIND_SAVINGS
    assert body["branch"] == "4321"
    assert body["opening_balance_cents"] == 2_000_00
    assert body["opening_date"] == "2026-06-01"
    # O saldo derivado acompanha o novo ponto de partida — porque ele é derivado, não guardado.
    assert body["saldo_derivado_cents"] == 2_000_00


def test_patch_nao_arquiva(client: TestClient, headers):
    """`archived_at` não é editável pelo PATCH (AC2): arquivar tem rota e auditoria próprias."""
    acc = _create(client, headers)
    resp = client.patch(
        f"/bank/accounts/{acc['id']}", json={"archived_at": "2026-07-10T00:00:00Z"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archived_at"] is None


def test_patch_opening_date_futura_422(client: TestClient, headers):
    acc = _create(client, headers)
    futuro = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    resp = client.patch(
        f"/bank/accounts/{acc['id']}", json={"opening_date": futuro}, headers=headers
    )
    assert resp.status_code == 422, resp.text


# ── Auditoria ─────────────────────────────────────────────────────────────────────────────────


def test_operacoes_deixam_rastro_de_auditoria(client: TestClient, headers, db: Session):
    from app.core.audit import AuditEntry

    acc = _create(client, headers)
    client.patch(f"/bank/accounts/{acc['id']}", json={"name": "Outro"}, headers=headers)
    client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers)

    acoes = {e.action for e in db.query(AuditEntry).filter(AuditEntry.target == acc["id"]).all()}
    assert acoes == {"bank.account.create", "bank.account.update", "bank.account.archive"}


# ── IV1 — DRE e Lucratividade intactas ────────────────────────────────────────────────────────


def _seed_movimento_financeiro(client: TestClient, headers) -> None:
    """Uma cobrança e uma conta a pagar, para que a DRE do período NÃO seja trivialmente vazia."""
    assert client.post(
        "/receivables/charges",
        json={"description": "Consultoria", "kind": "service", "method": "pix",
              "amount_cents": 300_000, "due_date": "2026-07-10"},
        headers=headers,
    ).status_code == 201
    assert client.post(
        "/payables/bills",
        json={"description": "Aluguel", "category": "Aluguel", "amount_cents": 120_000,
              "due_date": "2026-07-05"},
        headers=headers,
    ).status_code == 201


def test_conta_bancaria_nao_altera_dre(client: TestClient, headers, db: Session):
    """IV1: a DRE agrega `charges` + `payables` + `transactions`. `bank_accounts` não é nenhuma
    delas — e nunca será adicionada (design §3.5, §6.4). Snapshot campo a campo."""
    _seed_movimento_financeiro(client, headers)
    antes = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))

    _create(client, headers, opening_balance_cents=987_654_321)

    depois = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))
    assert depois == antes, (
        "A DRE mudou depois de cadastrar uma conta bancária. Saldo de conta não é receita nem "
        "despesa de competência — se ele entrou na DRE, entrou como número inventado."
    )


# ── IV5 — Projeção de Caixa: a mudança é da Story 8.8, e SÓ na semente ────────────────────────
#
# ⚠️ **[Story 8.8 — @dev] Estes dois testes MUDARAM DE EXPECTATIVA, e isso é a CORREÇÃO, não uma
# regressão.** Enquanto valia só a Story 8.2, eles afirmavam que cadastrar conta bancária **não**
# alterava a Projeção — a guarda contra o acoplamento acidental, com a própria docstring nomeando a
# Story 8.8 como a autorizada a mudar isso ("*não pode acontecer por efeito colateral de um
# cadastro*"). A 8.8 chegou: agora o cadastro **deve** mudar a projeção, e o que estes testes
# passam a guardar é que ele muda **exatamente na semente e em nada mais** (AC8) — mesmo padrão com
# que a Story 8.1 atualizou os testes de runway da 5.7. Se algum dia o cadastro voltar a ser
# inócuo, é a 8.8 que quebrou.


def test_conta_bancaria_muda_a_projecao_so_na_semente(client: TestClient, headers, db: Session):
    """**[Story 8.8, AC1/AC8]** Cadastrar conta troca a origem para `misto` e soma a parcela
    bancária ao saldo inicial — e **nada mais** se move.

    O valor deste teste está no `assert` de campo a campo: `overdue_*`, `burn_rate` e o formato das
    janelas ficam idênticos, e cada `saldo_projetado_cents` anda **exatamente** o valor da parcela
    bancária. É a prova de que a story mexeu na semente, não na fórmula.
    """
    _seed_movimento_financeiro(client, headers)
    hoje = date(2026, 7, 20)
    antes = asdict(projection_service.cash_projection(db, today=hoje))
    assert antes["saldo_inicial_origem"] == ORIGEM_PLATAFORMA, "pré-condição: sem conta ainda"
    assert antes["saldo_inicial_banco_cents"] == 0

    _create(client, headers, opening_balance_cents=5_000_000)

    depois = asdict(projection_service.cash_projection(db, today=hoje))
    assert depois["saldo_inicial_origem"] == ORIGEM_MISTO
    assert depois["saldo_inicial_banco_cents"] == 5_000_000
    # A parcela de plataforma é a MESMA de antes (o cadastro não toca no plano 1)...
    assert depois["saldo_inicial_plataforma_cents"] == antes["saldo_inicial_plataforma_cents"]
    # ...e a invariante da soma vale nos dois estados.
    for estado in (antes, depois):
        assert estado["saldo_inicial_cents"] == (
            estado["saldo_inicial_banco_cents"] + estado["saldo_inicial_plataforma_cents"]
        )

    # AC8 — fora da semente, a projeção não mudou em NADA.
    assert depois["overdue_inflow_cents"] == antes["overdue_inflow_cents"]
    assert depois["overdue_outflow_cents"] == antes["overdue_outflow_cents"]
    assert (
        depois["runway"]["burn_rate_cents_per_day"] == antes["runway"]["burn_rate_cents_per_day"]
    ), "a fórmula de queima deriva de contas em aberto, não do saldo inicial — não pode ter mudado"
    for w_antes, w_depois in zip(antes["windows"], depois["windows"], strict=True):
        assert w_depois["days"] == w_antes["days"]
        assert w_depois["saldo_projetado_cents"] == w_antes["saldo_projetado_cents"] + 5_000_000, (
            "cada janela deve andar EXATAMENTE a parcela bancária — se andou outro valor, a story "
            "mexeu na fórmula e não só na semente"
        )


def test_projecao_pela_rota_tambem_muda(client: TestClient, headers):
    """O mesmo, pela superfície HTTP que o front consome (a 8.1 e a 8.8 mexeram justamente aqui).

    Também é o teste de **compatibilidade** do endpoint em produção (8.8 IV4): a resposta ganhou
    dois campos e nenhum dos anteriores desapareceu.
    """
    antes = client.get("/financial-intelligence/projection", headers=headers).json()
    assert antes["saldo_inicial_origem"] == ORIGEM_PLATAFORMA

    _create(client, headers, opening_balance_cents=5_000_000)

    depois = client.get("/financial-intelligence/projection", headers=headers).json()
    assert depois["saldo_inicial_origem"] == ORIGEM_MISTO
    assert depois["saldo_inicial_cents"] == antes["saldo_inicial_cents"] + 5_000_000
    # IV4 — mudança estritamente ADITIVA: todo campo que existia antes continua existindo.
    assert set(antes) <= set(depois)
    assert {"saldo_inicial_banco_cents", "saldo_inicial_plataforma_cents"} <= set(depois)
