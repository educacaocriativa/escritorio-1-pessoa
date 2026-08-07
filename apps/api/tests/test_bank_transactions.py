"""Testes do movimento bancário manual — o saldo do plano 3 passa a se mover (Story 8.3).

Cobre (Tasks 4-7 / AC2-8 / IV1,IV4,IV5):
- lançar: crédito SOBE o saldo derivado, débito DESCE (valores exatos em centavos);
- guardas de 422: valor zero, data anterior/igual à abertura, data futura, conta arquivada;
- 404 fail-closed para movimento e conta inexistentes;
- **AC3** `posted_at` é data de calendário: movimento em `until` entra, em `until + 1 dia` não —
  sem nenhuma aritmética de fuso no caminho;
- **AC4** `raw_description` é IMUTÁVEL: editar muda `user_description`, nunca o texto original, e
  mandar `raw_description` no corpo do PATCH não muda nada;
- **AC5** ignorar TIRA do saldo, `unignore` devolve, ambos idempotentes;
- **AC7** dois lançamentos idênticos no mesmo dia são DOIS movimentos, com `dedup_hash` distintos;
- **AC8** nasce `unmatched` e nenhum caminho de código desta onda escreve `partial`/`matched`;
- lista: filtros por conta/janela/status, ordenação e paginação obrigatória;
- **IV1** DRE intacta, **IV4** Contas a Pagar/Receber e Carteira intactas, **IV5** Projeção intacta.

RLS/isolamento cross-tenant NÃO é exercido aqui (SQLite — ver `conftest.py`): no banco dos testes
unitários todas as linhas são visíveis a todas as sessões, então "a conta é de outro tenant" é uma
afirmação que só o Postgres real pode provar. Ela vive em `test_bank_rls.py` (`rls_e2e`), que esta
story estendeu. A Regra dos Planos tem arquivo próprio: `test_money_planes.py`.
"""
from __future__ import annotations

import pathlib
from dataclasses import asdict
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_MISTO
from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.modules.bank import service
from app.modules.bank.models import (
    KIND_CHECKING,
    KIND_INVESTMENT,
    SOURCE_MANUAL,
    SOURCES_EXTERNA,
    SOURCES_SISTEMA,
    STATUS_IGNORED,
    STATUS_MATCHED,
    STATUS_PARTIAL,
    STATUS_UNMATCHED,
    BankTransaction,
)
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import projection as projection_service
from app.modules.payables import service as payables_service
from app.modules.receivables import service as receivables_service

REGISTER = {
    "legal_name": "Movimento Bancario ME",
    "document": "11444777000161",
    "slug": "movimentobancario",
    "email": "movimento@example.com",
    "name": "Marta",
    "password": "uma-senha-bem-grande",
}

# Toda data usada nos testes é do passado em relação ao "hoje" real: a guarda de data futura
# (`_validate_posted_at`) ancora em `_hoje()`, como o resto do projeto.
OPENING = date(2026, 7, 1)
OPENING_CENTS = 1_500_00



def _hoje() -> date:
    """A MESMA âncora do service (`service._today`) — fuso do tenant, nunca UTC solto."""
    return tenant_today(DEFAULT_TENANT_TIMEZONE)

@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account(
    client: TestClient, headers, *, opening: int = OPENING_CENTS, **over
) -> dict:
    payload = {
        "name": "Itaú PJ",
        "kind": KIND_CHECKING,
        "opening_balance_cents": opening,
        "opening_balance_is_known": True,
        "opening_date": OPENING.isoformat(),
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _lancar(
    client: TestClient,
    headers,
    account_id: str,
    *,
    amount_cents: int,
    posted_at: date | str = date(2026, 7, 10),
    description: str = "Pix recebido",
    expect: int = 201,
    **over,
) -> dict:
    body = {
        "posted_at": posted_at if isinstance(posted_at, str) else posted_at.isoformat(),
        "amount_cents": amount_cents,
        "description": description,
    }
    body.update(over)
    resp = client.post(
        f"/bank/accounts/{account_id}/transactions", json=body, headers=headers
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def _saldo(client: TestClient, headers, account_id: str, *, until: date | None = None) -> int:
    params = {"until": until.isoformat()} if until else None
    resp = client.get(
        f"/bank/accounts/{account_id}/balance", params=params, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["saldo_derivado_cents"]


# ── AC2/AC5 — o saldo se move de verdade ─────────────────────────────────────────────────────


def test_credito_sobe_e_debito_desce_o_saldo(client: TestClient, headers):
    """A promessa central da story, em centavos exatos: `+` sobe, `−` desce, o resto é SUM()."""
    acc = _account(client, headers)
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS

    _lancar(client, headers, acc["id"], amount_cents=100_00, description="Cliente pagou")
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS + 100_00

    _lancar(client, headers, acc["id"], amount_cents=-100_00, description="Aluguel")
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS, (
        "entrada de R$100 seguida de saída de R$100 tem que voltar ao saldo de abertura — se não "
        "voltou, o sinal não está sendo somado como sinal"
    )

    # E o débito sozinho pode levar o saldo abaixo de zero (conta no limite é estado legítimo).
    _lancar(client, headers, acc["id"], amount_cents=-(OPENING_CENTS + 1))
    assert _saldo(client, headers, acc["id"]) == -1


def test_saldo_derivado_bate_pelo_service_e_pela_rota(client: TestClient, headers, db: Session):
    """O número é o mesmo pelas duas superfícies — a fórmula tem uma implementação só (§3.1)."""
    acc = _account(client, headers)
    _lancar(client, headers, acc["id"], amount_cents=250_00)
    _lancar(client, headers, acc["id"], amount_cents=-75_50)

    esperado = OPENING_CENTS + 250_00 - 75_50
    assert service.derived_balance(db, bank_account_id=acc["id"]) == esperado
    assert _saldo(client, headers, acc["id"]) == esperado
    # A lista de contas usa a versão em LOTE — que precisa dar o mesmo número.
    listado = client.get("/bank/accounts", headers=headers).json()
    assert [a["saldo_derivado_cents"] for a in listado] == [esperado]


def test_derived_balances_as_of_e_active_balance_total_refletem_os_movimentos(
    client: TestClient, headers, db: Session
):
    """A versão em lote soma os movimentos de cada conta, e conta SEM movimento não some do dict.

    O `GROUP BY` sozinho omitiria a conta sem movimento (erro clássico) — e o saldo dela sumiria da
    tela de "Contas & Saldos" em vez de aparecer com o saldo de abertura.
    """
    corrente = _account(client, headers, opening=100_00, name="Corrente", number="1")
    parada = _account(client, headers, opening=50_00, name="Sem movimento", number="2")
    aplicacao = _account(
        client, headers, opening=900_00, name="CDB", number="3", kind=KIND_INVESTMENT
    )

    _lancar(client, headers, corrente["id"], amount_cents=30_00)
    _lancar(client, headers, aplicacao["id"], amount_cents=10_00)

    saldos = service.derived_balances_as_of(db)
    assert saldos == {corrente["id"]: 130_00, parada["id"]: 50_00, aplicacao["id"]: 910_00}

    # `active_balance_total` continua excluindo `investment` (dinheiro aplicado não é caixa) —
    # agora com movimentos no meio, que é quando um filtro mal escrito apareceria.
    assert service.active_balance_total(db) == 130_00 + 50_00
    assert service.active_balance_total(db, exclude_kinds=()) == 130_00 + 50_00 + 910_00


def test_movimento_anterior_a_abertura_e_recusado(client: TestClient, headers):
    """AC: `posted_at > opening_date`. Aceitar sem somar seria pior — linha existindo sem efeito.

    Inclui o caso de FRONTEIRA (`posted_at == opening_date`), que é o que a fórmula do design §3.1
    exclui com `>` e o que um `>=` mal escrito deixaria passar contando dinheiro duas vezes.
    """
    acc = _account(client, headers)
    for dia in (OPENING - timedelta(days=1), OPENING):
        erro = _lancar(client, headers, acc["id"], amount_cents=10_00, posted_at=dia, expect=422)
        assert "posterior" in erro["detail"]
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS


def test_valor_zero_e_recusado(client: TestClient, headers):
    acc = _account(client, headers)
    erro = _lancar(client, headers, acc["id"], amount_cents=0, expect=422)
    assert "zero" in erro["detail"]


def test_data_futura_e_recusada(client: TestClient, headers):
    """Extrato é fato passado. Data futura é erro de digitação (ano errado é o caso comum)."""
    acc = _account(client, headers)
    amanha = _hoje() + timedelta(days=1)
    erro = _lancar(client, headers, acc["id"], amount_cents=10_00, posted_at=amanha, expect=422)
    assert "futura" in erro["detail"]


def test_conta_arquivada_nao_recebe_lancamento(client: TestClient, headers):
    acc = _account(client, headers)
    assert client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers).status_code == 200
    erro = _lancar(client, headers, acc["id"], amount_cents=10_00, expect=422)
    assert "arquivada" in erro["detail"]


def test_conta_arquivada_ainda_permite_corrigir_movimento_antigo(client: TestClient, headers):
    """Assimetria DELIBERADA: arquivar impede história NOVA, não impede corrigir a que já existia.

    Se editar também travasse, um erro de digitação descoberto depois do encerramento da conta
    ficaria eternizado — e a única saída seria `ignore`, que muda o saldo em vez de corrigi-lo.
    """
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00)
    assert client.post(f"/bank/accounts/{acc['id']}/archive", headers=headers).status_code == 200

    resp = client.patch(
        f"/bank/transactions/{tx['id']}",
        json={"amount_cents": 11_00, "user_description": "valor certo"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount_cents"] == 11_00
    # E o saldo da conta arquivada acompanha a correção (ela some das listas, não do histórico).
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS + 11_00


def test_conta_e_movimento_inexistentes_sao_404(client: TestClient, headers):
    """404 fail-closed, nunca 403 — 403 confirmaria a existência da linha (padrão do projeto)."""
    _lancar(client, headers, "nao-existe", amount_cents=10_00, expect=404)
    assert client.get("/bank/transactions/nao-existe", headers=headers).status_code == 404
    assert (
        client.patch(
            "/bank/transactions/nao-existe", json={"amount_cents": 1}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post("/bank/transactions/nao-existe/ignore", headers=headers).status_code == 404
    )
    assert (
        client.post("/bank/transactions/nao-existe/unignore", headers=headers).status_code == 404
    )


# ── AC3 — `posted_at` é data de calendário, e ponto ───────────────────────────────────────────


def test_until_recorta_por_data_de_calendario(client: TestClient, headers):
    """Movimento em `until` ENTRA; em `until + 1 dia`, não. Sem fuso no caminho.

    É a lição do `CLAUDE.md` §6.0 (eventos all-day sumindo da Agenda por comparação em horário
    local) aplicada na ORIGEM: `posted_at` é `DATE`, então não existe conversão para converter
    errado. Um dia inteiro de diferença é justamente o que um bug de fuso produziria.
    """
    acc = _account(client, headers)
    corte = date(2026, 7, 15)
    _lancar(client, headers, acc["id"], amount_cents=40_00, posted_at=corte)
    _lancar(client, headers, acc["id"], amount_cents=7_00, posted_at=corte + timedelta(days=1))

    assert _saldo(client, headers, acc["id"], until=corte) == OPENING_CENTS + 40_00
    assert _saldo(client, headers, acc["id"], until=corte + timedelta(days=1)) == (
        OPENING_CENTS + 40_00 + 7_00
    )
    # `until=None` = sem limite superior: o saldo atual completo.
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS + 40_00 + 7_00


def test_posted_at_trafega_como_data_pura(client: TestClient, headers, db: Session):
    """`YYYY-MM-DD` na entrada, `YYYY-MM-DD` na saída, `date` no banco — nunca um datetime."""
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00, posted_at="2026-07-09")
    assert tx["posted_at"] == "2026-07-09"
    persistido = db.get(BankTransaction, tx["id"])
    assert isinstance(persistido.posted_at, date)
    assert not isinstance(persistido.posted_at, datetime)


# ── AC4 — `raw_description` é imutável ────────────────────────────────────────────────────────


def test_raw_description_nao_muda_na_edicao(client: TestClient, headers, db: Session):
    """Editar troca o RÓTULO (`user_description`), nunca a prova documental."""
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00, description="TED 0341 XPTO")
    assert tx["raw_description"] == "TED 0341 XPTO"
    assert tx["user_description"] == ""
    assert tx["description"] == "TED 0341 XPTO", "sem rótulo do usuário, exibe-se o texto cru"

    resp = client.patch(
        f"/bank/transactions/{tx['id']}",
        json={"user_description": "Honorários do João"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    editado = resp.json()
    assert editado["raw_description"] == "TED 0341 XPTO", (
        "AC4 VIOLADO: `raw_description` mudou. É a prova documental do que o banco disse — se ela "
        "pode ser reescrita, a auditoria (que é o produto) perde a fonte."
    )
    assert editado["user_description"] == "Honorários do João"
    assert editado["description"] == "Honorários do João", (
        "`description` é `user_description or raw_description`, derivada no backend para a UI da "
        "8.7 não reimplementar a regra"
    )
    assert db.get(BankTransaction, tx["id"]).raw_description == "TED 0341 XPTO"


def test_patch_com_raw_description_no_corpo_nao_altera_nada(
    client: TestClient, headers, db: Session
):
    """Segunda linha de defesa: o campo não existe no schema, então o corpo é ignorado.

    A guarda é dupla de propósito (schema + service): `update_transaction` toca nos três campos
    permitidos um a um, sem `setattr` genérico — assim acrescentar um campo ao schema não torna
    esse campo editável por acidente.
    """
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00, description="ORIGINAL")

    resp = client.patch(
        f"/bank/transactions/{tx['id']}",
        json={
            "raw_description": "FALSIFICADO",
            "source": "ofx",
            "status": STATUS_MATCHED,
            "dedup_hash": "x" * 64,
            "fitid": "123",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 422), resp.text

    persistido = db.get(BankTransaction, tx["id"])
    assert persistido.raw_description == "ORIGINAL"
    assert persistido.source == SOURCE_MANUAL
    assert persistido.status == STATUS_UNMATCHED
    assert persistido.fitid is None


def test_edicao_de_data_e_valor_revalida_as_guardas(client: TestClient, headers):
    """Corrigir um lançamento passa pelas MESMAS guardas de criar — senão a validação seria só
    uma formalidade da primeira gravação."""
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00)

    assert (
        client.patch(
            f"/bank/transactions/{tx['id']}", json={"amount_cents": 0}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/bank/transactions/{tx['id']}",
            json={"posted_at": OPENING.isoformat()},
            headers=headers,
        ).status_code
        == 422
    )
    amanha = (_hoje() + timedelta(days=1)).isoformat()
    assert (
        client.patch(
            f"/bank/transactions/{tx['id']}", json={"posted_at": amanha}, headers=headers
        ).status_code
        == 422
    )

    # A correção legítima passa — e move o saldo.
    resp = client.patch(
        f"/bank/transactions/{tx['id']}", json={"amount_cents": -25_00}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS - 25_00


# ── AC5 — ignorar tira do saldo, sem apagar nada ──────────────────────────────────────────────


def test_ignorar_remove_do_saldo_e_unignore_devolve(client: TestClient, headers):
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=80_00, description="Não é meu")
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS + 80_00

    resp = client.post(
        f"/bank/transactions/{tx['id']}/ignore",
        json={"reason": "Transferência entre contas minhas"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == STATUS_IGNORED
    assert resp.json()["ignored_reason"] == "Transferência entre contas minhas"
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS, (
        "AC5: ignorar TIRA o movimento do saldo — e o filtro mora DENTRO do saldo derivado, para "
        "que 8.5 e 8.7 não precisem refiltrar (dois lugares, um dia divergem)"
    )
    # Continua existindo e visível — o oposto de um DELETE.
    assert client.get(f"/bank/transactions/{tx['id']}", headers=headers).status_code == 200

    volta = client.post(f"/bank/transactions/{tx['id']}/unignore", headers=headers)
    assert volta.status_code == 200
    assert volta.json()["status"] == STATUS_UNMATCHED
    assert volta.json()["ignored_reason"] == ""
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS + 80_00


def test_ignore_e_unignore_sao_idempotentes(client: TestClient, headers, db: Session):
    """Clique duplo não pode produzir estado diferente do clique único."""
    from app.core.audit import AuditEntry

    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=80_00)

    primeiro = client.post(
        f"/bank/transactions/{tx['id']}/ignore", json={"reason": "motivo"}, headers=headers
    ).json()
    segundo = client.post(
        f"/bank/transactions/{tx['id']}/ignore", json={"reason": "outro"}, headers=headers
    ).json()
    assert segundo["status"] == STATUS_IGNORED
    assert segundo["ignored_reason"] == primeiro["ignored_reason"] == "motivo", (
        "no-op de verdade: o segundo ignore não re-grava o motivo"
    )
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS

    client.post(f"/bank/transactions/{tx['id']}/unignore", headers=headers)
    de_novo = client.post(f"/bank/transactions/{tx['id']}/unignore", headers=headers).json()
    assert de_novo["status"] == STATUS_UNMATCHED
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS + 80_00

    # O no-op também não polui a auditoria com um segundo rastro do que não aconteceu.
    acoes = [
        e.action
        for e in db.query(AuditEntry).filter(AuditEntry.target == tx["id"]).all()
    ]
    assert acoes.count("bank.transaction.ignore") == 1
    assert acoes.count("bank.transaction.unignore") == 1


def test_movimento_ignorado_pode_ser_editado(client: TestClient, headers):
    """Corrigir e depois reativar é o caminho normal de quem ignorou por engano."""
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=80_00)
    client.post(f"/bank/transactions/{tx['id']}/ignore", headers=headers)

    resp = client.patch(
        f"/bank/transactions/{tx['id']}", json={"amount_cents": 90_00}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == STATUS_IGNORED, "editar não reativa sozinho"
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS

    client.post(f"/bank/transactions/{tx['id']}/unignore", headers=headers)
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS + 90_00


# ── AC7 — dois lançamentos idênticos no mesmo dia são DOIS movimentos ─────────────────────────


def test_dois_lancamentos_identicos_no_mesmo_dia_sao_dois_movimentos(
    client: TestClient, headers, db: Session
):
    """O teste que impede o sistema de criar o próprio furo (design §4.4).

    Dois Pix de R$ 50 para a mesma pessoa no mesmo dia acontecem de verdade. A implementação mais
    provável de `dedup_hash` (hash sobre data+valor+descrição) colidiria e engoliria o segundo em
    silêncio — o saldo ficaria R$ 50 acima do extrato e ninguém saberia por quê. Por isso a variante
    manual é chaveada no próprio UUID da linha: única por construção.
    """
    acc = _account(client, headers)
    dia = date(2026, 7, 12)
    a = _lancar(
        client, headers, acc["id"], amount_cents=-50_00, posted_at=dia, description="Pix Maria"
    )
    b = _lancar(
        client, headers, acc["id"], amount_cents=-50_00, posted_at=dia, description="Pix Maria"
    )

    assert a["id"] != b["id"]
    persistidos = db.query(BankTransaction).all()
    assert len(persistidos) == 2, "o segundo lançamento idêntico foi engolido"
    assert len({t.dedup_hash for t in persistidos}) == 2, (
        "os dois `dedup_hash` colidiram — a constraint única teria barrado o segundo insert"
    )
    assert all(len(t.dedup_hash) == 64 for t in persistidos), "sha256 hex tem 64 caracteres"
    assert _saldo(client, headers, acc["id"]) == OPENING_CENTS - 100_00, (
        "o saldo tem que somar os DOIS movimentos"
    )


def test_dedup_hash_e_fitid_seguem_a_variante_manual(client: TestClient, headers, db: Session):
    """`sha256("{conta}|manual|{id}")`, `fitid` NULL (o manual não tem FITID)."""
    import hashlib

    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00)
    persistido = db.get(BankTransaction, tx["id"])

    esperado = hashlib.sha256(f"{acc['id']}|manual|{tx['id']}".encode()).hexdigest()
    assert persistido.dedup_hash == esperado
    assert persistido.fitid is None
    assert persistido.source == SOURCE_MANUAL


# ── AC8 — `status` nasce `unmatched` e ninguém mais escreve nele nesta onda ───────────────────


def test_movimento_nasce_unmatched(client: TestClient, headers):
    acc = _account(client, headers)
    assert _lancar(client, headers, acc["id"], amount_cents=10_00)["status"] == STATUS_UNMATCHED


def test_nenhuma_rota_produz_partial_ou_matched(client: TestClient, headers, db: Session):
    """Por comportamento: depois de exercitar TODAS as rotas, só existem `unmatched`/`ignored`."""
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00)
    client.patch(f"/bank/transactions/{tx['id']}", json={"amount_cents": 20_00}, headers=headers)
    client.post(f"/bank/transactions/{tx['id']}/ignore", headers=headers)
    client.post(f"/bank/transactions/{tx['id']}/unignore", headers=headers)
    client.get("/bank/transactions", headers=headers)

    estados = {t.status for t in db.query(BankTransaction).all()}
    assert estados <= {STATUS_UNMATCHED, STATUS_IGNORED}


def test_service_nao_escreve_partial_nem_matched(client: TestClient, headers):
    """E por varredura: `partial`/`matched` não são sequer MENCIONADOS pelo service desta onda.

    Mesmo estilo de gate estático de `test_money_planes.py`. `status` é a única materialização
    deliberada do design (§2.2) e o que a mantém correta é a disciplina de quem pode escrevê-la:
    `_refresh_status` da conciliação (Onda 4) é o dono de `partial`/`matched`. Quando essa story
    chegar, ela atualiza ESTE teste com justificativa escrita — nunca o apaga.
    """
    fonte = (
        pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "bank" / "service.py"
    ).read_text(encoding="utf-8")
    for proibido in ("STATUS_PARTIAL", "STATUS_MATCHED"):
        assert proibido not in fonte, (
            f"`{proibido}` apareceu em bank/service.py. Nesta onda só `ignore`/`unignore` escrevem "
            "`status` (invariante (d) do modelo). Se a conciliação chegou, atualize este teste com "
            "a justificativa."
        )
    # As constantes existem no vocabulário — o que não existe é escritor para elas.
    assert STATUS_PARTIAL == "partial" and STATUS_MATCHED == "matched"


# ── Lista: filtros, ordem e paginação ────────────────────────────────────────────────────────


def _lista(client: TestClient, headers, **params) -> list[dict]:
    resp = client.get("/bank/transactions", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_lista_filtra_por_conta_janela_e_status(client: TestClient, headers):
    a = _account(client, headers, name="Conta A", number="1")
    b = _account(client, headers, name="Conta B", number="2")

    # Datas distintas de propósito: assim a ordem esperada é única e a asserção não precisa
    # tolerar empate (o desempate por `created_at` tem granularidade de segundo no SQLite).
    t5 = _lancar(client, headers, a["id"], amount_cents=10_00, posted_at=date(2026, 7, 5))
    tb = _lancar(client, headers, b["id"], amount_cents=40_00, posted_at=date(2026, 7, 8))
    t10 = _lancar(client, headers, a["id"], amount_cents=20_00, posted_at=date(2026, 7, 10))
    t20 = _lancar(client, headers, a["id"], amount_cents=30_00, posted_at=date(2026, 7, 20))

    # Ordem: `posted_at` desc — do mais recente ao mais antigo, contas misturadas.
    assert [t["id"] for t in _lista(client, headers)] == [
        t20["id"], t10["id"], tb["id"], t5["id"]
    ]

    assert [t["id"] for t in _lista(client, headers, bank_account_id=b["id"])] == [tb["id"]]
    # Janela INCLUSIVA nas duas pontas.
    ids_janela = {
        t["id"] for t in _lista(client, headers, start="2026-07-05", end="2026-07-10")
    }
    assert ids_janela == {t5["id"], tb["id"], t10["id"]}

    client.post(f"/bank/transactions/{t20['id']}/ignore", headers=headers)
    assert [t["id"] for t in _lista(client, headers, status=STATUS_IGNORED)] == [t20["id"]]
    assert t20["id"] not in {t["id"] for t in _lista(client, headers, status=STATUS_UNMATCHED)}


def test_lista_aceita_varios_status_e_recusa_status_invalido(client: TestClient, headers):
    """A 8.5 pede `unmatched`+`partial` numa chamada só; um status inventado é 422, não silêncio."""
    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00)
    ignorado = _lancar(client, headers, acc["id"], amount_cents=20_00)
    client.post(f"/bank/transactions/{ignorado['id']}/ignore", headers=headers)

    combinado = _lista(client, headers, status=[STATUS_UNMATCHED, STATUS_PARTIAL])
    assert [t["id"] for t in combinado] == [tx["id"]]

    resp = client.get("/bank/transactions", params={"status": "conciliado"}, headers=headers)
    assert resp.status_code == 422, resp.text


def test_lista_pagina(client: TestClient, headers):
    """Paginação obrigatória (padrão do projeto desde a correção de QA da Agenda)."""
    acc = _account(client, headers)
    for dia in range(2, 8):
        _lancar(client, headers, acc["id"], amount_cents=dia * 100, posted_at=date(2026, 7, dia))

    pagina1 = _lista(client, headers, limit=2, offset=0)
    pagina2 = _lista(client, headers, limit=2, offset=2)
    assert len(pagina1) == len(pagina2) == 2
    assert {t["id"] for t in pagina1}.isdisjoint({t["id"] for t in pagina2})
    # Mais recente primeiro: 07/07 e 06/07 na primeira página.
    assert [t["posted_at"] for t in pagina1] == ["2026-07-07", "2026-07-06"]

    assert client.get(
        "/bank/transactions", params={"limit": 0}, headers=headers
    ).status_code == 422


def test_lancar_deixa_rastro_de_auditoria(client: TestClient, headers, db: Session):
    from app.core.audit import AuditEntry

    acc = _account(client, headers)
    tx = _lancar(client, headers, acc["id"], amount_cents=10_00)
    client.patch(f"/bank/transactions/{tx['id']}", json={"amount_cents": 20_00}, headers=headers)
    client.post(f"/bank/transactions/{tx['id']}/ignore", headers=headers)
    client.post(f"/bank/transactions/{tx['id']}/unignore", headers=headers)

    acoes = {e.action for e in db.query(AuditEntry).filter(AuditEntry.target == tx["id"]).all()}
    assert acoes == {
        "bank.transaction.create",
        "bank.transaction.update",
        "bank.transaction.ignore",
        "bank.transaction.unignore",
    }
    assert all(
        e.target for e in db.query(AuditEntry).filter(AuditEntry.target == tx["id"]).all()
    ), "auditoria com `target` vazio é rastro que não aponta para nada (ver `create_account`)"


def test_contraparte_opcional_e_validada(client: TestClient, headers):
    """Contraparte é opcional; quando informada à mão, o CPF/CNPJ passa pelo dígito verificador."""
    acc = _account(client, headers)
    tx = _lancar(
        client,
        headers,
        acc["id"],
        amount_cents=10_00,
        counterparty_name="João da Silva",
        counterparty_document="111.444.777-35",
        operation_nature="honorarios",
    )
    assert tx["counterparty_name"] == "João da Silva"
    assert tx["counterparty_document"] == "11144477735", "normalizado para só dígitos"
    assert tx["operation_nature"] == "honorarios"

    _lancar(
        client, headers, acc["id"], amount_cents=10_00, counterparty_document="123", expect=422
    )


# ── IV1 — DRE e Lucratividade intactas ───────────────────────────────────────────────────────


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


def test_movimento_bancario_nao_altera_dre(client: TestClient, headers, db: Session):
    """IV1 — a promessa central do desenho ("impacto zero por construção") virando teste.

    A DRE agrega exatamente três origens: `charges` + `payables` + `transactions` (`dre.py`).
    `bank_transactions` não é nenhuma delas e **nunca será adicionada** (design §3.5, §6.4) — o
    plano 3 descreve onde o dinheiro está, não o que foi receita ou despesa de competência.
    `profitability.py` deriva da DRE, então está coberto pelo mesmo snapshot.
    """
    _seed_movimento_financeiro(client, headers)
    acc = _account(client, headers)
    antes = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))

    _lancar(client, headers, acc["id"], amount_cents=987_654, description="Crédito arbitrário")
    _lancar(client, headers, acc["id"], amount_cents=-123_456, description="Débito arbitrário")

    depois = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))
    assert depois == antes, (
        "A DRE mudou depois de lançar movimentos bancários. Movimento de extrato não é receita nem "
        "despesa de competência — se entrou na DRE, entrou como número inventado."
    )


# ── IV4 — Contas a Pagar / Receber / Carteira intactas ───────────────────────────────────────


def test_movimento_bancario_nao_toca_payables_receivables_nem_carteira(
    client: TestClient, headers, db: Session
):
    """IV4: nenhum vínculo de conciliação existe nesta story (`bank_reconciliations` é da Onda 4).

    Um movimento bancário **não** cria, altera ou baixa `Payable`, `Charge` ou `Transaction`. Baixar
    cobrança a partir do extrato está bloqueada até a Onda 5 (o vínculo `platform_earnings →
    transaction` não existe — decisão do fundador F4).
    """
    from app.modules.wallet.models import PlatformEarning, Transaction

    _seed_movimento_financeiro(client, headers)
    acc = _account(client, headers)
    payables_antes = payables_service.summary(db)
    receivables_antes = receivables_service.summary(db)
    carteira_antes = client.get("/wallet/summary", headers=headers).json()

    # Um crédito do valor EXATO da cobrança em aberto — o caso em que uma "ajuda" automática
    # tentaria dar baixa sozinha.
    _lancar(client, headers, acc["id"], amount_cents=300_000, description="Consultoria")
    _lancar(client, headers, acc["id"], amount_cents=-120_000, description="Aluguel")

    assert payables_service.summary(db) == payables_antes
    assert receivables_service.summary(db) == receivables_antes
    assert client.get("/wallet/summary", headers=headers).json() == carteira_antes
    assert db.query(Transaction).count() == 0, "movimento bancário não cria Transaction (plano 1)"
    assert db.query(PlatformEarning).count() == 0


# ── IV5 — Projeção de Caixa: o movimento move a semente, e SÓ ela ────────────────────────────
#
# ⚠️ **[Story 8.8 — @dev] Este teste MUDOU DE EXPECTATIVA, e isso é a CORREÇÃO, não uma regressão.**
# Enquanto valia só a Story 8.3 ele afirmava que lançar movimento bancário **não** alterava a
# projeção, com a própria docstring nomeando a Story 8.8 como a autorizada a mudar isso. A 8.8
# chegou: o saldo derivado agora é a parcela "no banco" do saldo inicial, então o movimento
# **deve** movê-la. O que o teste passa a guardar é que ele move **exatamente isso** — a semente —
# e nada mais (AC8). Mesmo tratamento dado ao par equivalente em `test_bank_accounts.py`.


def test_movimento_bancario_move_a_projecao_so_pela_semente(
    client: TestClient, headers, db: Session
):
    """**[Story 8.8, AC1/AC8]** O movimento entra pelo saldo derivado, não por outra porta."""
    _seed_movimento_financeiro(client, headers)
    acc = _account(client, headers)
    hoje = date(2026, 7, 20)
    antes = asdict(projection_service.cash_projection(db, today=hoje))
    assert antes["saldo_inicial_origem"] == ORIGEM_MISTO, "pré-condição: a conta já existe"

    _lancar(client, headers, acc["id"], amount_cents=5_000_000, posted_at=date(2026, 7, 15))

    depois = asdict(projection_service.cash_projection(db, today=hoje))
    assert depois["saldo_inicial_banco_cents"] == antes["saldo_inicial_banco_cents"] + 5_000_000
    # O plano 1 não se mexeu: movimento bancário não cria `Transaction` (Regra dos Planos §1.3a).
    assert depois["saldo_inicial_plataforma_cents"] == antes["saldo_inicial_plataforma_cents"]
    assert depois["saldo_inicial_origem"] == ORIGEM_MISTO
    # AC8 — fora da semente, nada mudou.
    assert depois["overdue_inflow_cents"] == antes["overdue_inflow_cents"]
    assert depois["overdue_outflow_cents"] == antes["overdue_outflow_cents"]
    assert (
        depois["runway"]["burn_rate_cents_per_day"] == antes["runway"]["burn_rate_cents_per_day"]
    )
    for w_antes, w_depois in zip(antes["windows"], depois["windows"], strict=True):
        assert w_depois["saldo_projetado_cents"] == w_antes["saldo_projetado_cents"] + 5_000_000

    pela_rota = client.get("/financial-intelligence/projection", headers=headers).json()
    assert pela_rota["saldo_inicial_origem"] == ORIGEM_MISTO


# ── Story 8.14 (AC4) — a guarda de data futura passa a ser cortada por `source` ───────────────
#
# ⚠️ **A justificativa antiga da guarda descrevia TRANSCRIÇÃO, não origem.** *"Extrato bancário é
# fato passado; data futura é erro de digitação"* continua verdadeiro para o que o usuário
# **transcreve** (`SOURCES_EXTERNA`: manual, ofx, csv). Não é verdadeiro para o que o e1p
# **originou** (`SOURCES_SISTEMA`): um débito agendado para daqui a 15 dias é verdade registrada em
# primeira mão, não digitação errada. *"O e1p pode afirmar o futuro do que ele mesmo agendou; não
# pode afirmar o futuro do que outro atestou."*
#
# ⚠️ **O corte é por `source`, e por `source` APENAS** (ratificação §C-6.2). O booleano
# `permite_futuro` decidido pelo chamador está **rejeitado**: *"é o parâmetro que alguém passa
# `True` no caminho manual, um dia, por conveniência — e nenhum gate de AST o pega, porque não há
# import envolvido"*. Um eixo, uma pergunta.


def test_AC4_manual_continua_recusando_data_futura(client: TestClient, headers):
    """**O não-membro do conjunto isento.** `manual ∈ SOURCES_EXTERNA` → 422, mensagem inalterada.

    É a proteção real que a guarda dá hoje (erro de ano na digitação) e ela **não** foi afrouxada.
    Este teste é o par de `test_data_futura_e_recusada` acima, agora escrito contra o CONJUNTO.
    """
    from app.modules.bank.models import SOURCES_EXTERNA

    assert SOURCE_MANUAL in SOURCES_EXTERNA
    acc = _account(client, headers)
    amanha = _hoje() + timedelta(days=1)
    erro = _lancar(client, headers, acc["id"], amount_cents=10_00, posted_at=amanha, expect=422)
    assert "futura" in erro["detail"]


@pytest.mark.parametrize("source", SOURCES_SISTEMA)
def test_AC4_toda_origem_de_SISTEMA_aceita_data_futura(client: TestClient, headers, db, source):
    """**Os membros do conjunto isento — todos eles, um por um.**

    Parametrizado sobre a tupla inteira e não sobre `payable`: a regra é escrita contra
    `SOURCES_SISTEMA`, então acrescentar uma origem de sistema nova (a 8.18 acrescenta `transfer`,
    a Onda 2b `yield`, a Onda 3 `payout`) tem de herdar a isenção **sem** ninguém editar a guarda.
    Se um valor novo entrar na tupla e a guarda não o cobrir, este teste reprova sozinho.

    ⚠️ `transfer` é membro **aqui** e mesmo assim é recusado por `create_transfer` na Story 8.18,
    por outro motivo (a A-3 de lá). São guardas diferentes, em camadas diferentes.
    """
    acc = _account(client, headers)
    amanha = _hoje() + timedelta(days=1)
    assert (
        service._validate_posted_at(
            amanha, service.get_account(db, acc["id"]), _hoje(), source=source
        )
        == amanha
    )


@pytest.mark.parametrize("source", SOURCES_EXTERNA)
def test_AC4_toda_origem_EXTERNA_recusa_data_futura(client: TestClient, headers, db, source):
    """A outra metade da partição, também sobre a tupla inteira. `ofx` e `csv` ainda não têm
    caminho de escrita (Onda 4), e é justamente por isso que a regra é fixada agora: quando o
    parser chegar, ele herda a recusa em vez de a redescobrir."""
    acc = _account(client, headers)
    amanha = _hoje() + timedelta(days=1)
    with pytest.raises(service.BankError) as exc:
        service._validate_posted_at(
            amanha, service.get_account(db, acc["id"]), _hoje(), source=source
        )
    assert exc.value.status_code == 422
    assert "futura" in str(exc.value)


def test_AC4_source_desconhecido_e_422_e_nao_ganha_a_isencao(client: TestClient, headers, db):
    """**Fail-closed.** Um valor fora do vocabulário não herda a permissão do lado mais frouxo.

    A partição é escrita nas duas metades (`in SOURCES_SISTEMA` … `not in SOURCES_EXTERNA` → 422).
    Um `if source not in SOURCES_SISTEMA` sozinho faria valor novo herdar o teto sem ninguém
    decidir; um `if source in SOURCES_EXTERNA` sozinho o faria herdar a **isenção** — que é o lado
    caro, porque cria movimento futuro que só aparece semanas depois.
    """
    acc = _account(client, headers)
    amanha = _hoje() + timedelta(days=1)
    with pytest.raises(service.BankError) as exc:
        service._validate_posted_at(
            amanha, service.get_account(db, acc["id"]), _hoje(), source="origem_inventada"
        )
    assert exc.value.status_code == 422
    assert "inválida" in str(exc.value)


@pytest.mark.parametrize("source", SOURCES_EXTERNA + SOURCES_SISTEMA)
def test_AC4_o_PISO_vale_para_TODA_origem_sem_excecao(client: TestClient, headers, db, source):
    """O piso (`posted_at > opening_date`) **não** foi cortado por origem — e não deve ser.

    Ele protege a aritmética do saldo (o que veio antes da abertura já está dentro de
    `opening_balance_cents`), não a plausibilidade do dado. Um movimento de sistema anterior à
    abertura ficaria órfão do saldo exatamente como um manual.
    """
    acc = _account(client, headers)
    with pytest.raises(service.BankError) as exc:
        service._validate_posted_at(
            OPENING, service.get_account(db, acc["id"]), _hoje(), source=source
        )
    assert exc.value.status_code == 422
    assert "posterior" in str(exc.value)


# ── Story 8.18 (AC9) — a Regra da Origem (d), aplicada: movimento de SISTEMA não é editável ───
#
# ⚠️ **DESVIO DOCUMENTADO — a premissa da 8.18 AC9 era falsa.** O AC9 diz que as pernas da
# transferência *"herdam a guarda que a Story 8.9 implementa"*. Ao implementar a 8.18 verificou-se
# que a 8.9 **escreveu a regra na docstring de `bank/origin.py` e não a implementou**: nem
# `update_transaction` nem `ignore_transaction` olhavam para `tx.source`. Pior, o comentário dentro
# de `update_transaction` já afirmava que a edição *"é impedida antes, pela Regra da Origem (d)"* —
# uma afirmação sem código por trás, do tipo que só é descoberta quando alguém tenta usá-la.
#
# A guarda entrou em `service._recusa_se_origem_do_sistema`, escrita contra `SOURCES_SISTEMA` (nunca
# contra `'transfer'` solto): `payable` e `charge` a herdam do mesmo jeito, e é isso que se testa
# aqui. As pernas da transferência estão em `test_bank_transfers.py`.
#
# O caso do movimento MANUAL segue coberto pelos testes de edição/ignore acima — a guarda é sobre
# origem de sistema, não sobre "movimento bancário".


@pytest.mark.parametrize("source", SOURCES_SISTEMA)
def test_AC9_movimento_de_origem_de_sistema_recusa_edicao_de_data_e_valor(
    client: TestClient, headers, db, source
):
    """Parametrizado sobre a tupla inteira: acrescentar uma origem nova herda a guarda de graça.

    O que a guarda impede em cada origem: corrigir a data/valor da linha bancária **sem** corrigir o
    lançamento que a gerou deixa o cache e o razão contando histórias diferentes — e a Regra da
    Origem (c) promete o oposto (*"o movimento é ESPELHO do lançamento"*). Quem quer mudar mexe no
    lançamento, e o movimento acompanha.
    """
    from app.modules.bank.origin import sync_origin_movement
    from app.modules.bank.schemas import BankTransactionUpdate

    acc = _account(client, headers)
    tenant = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    tx = sync_origin_movement(
        db,
        tenant_id=tenant,
        actor="dono",
        source=source,
        origin_id=f"origem-{source}",
        bank_account_id=acc["id"],
        posted_at=date(2026, 7, 10),
        amount_cents=-100_00,
        description="lançamento do sistema",
    )
    db.commit()

    for corpo in (
        BankTransactionUpdate(posted_at=date(2026, 7, 11)),
        BankTransactionUpdate(amount_cents=-200_00),
    ):
        with pytest.raises(service.BankError) as exc:
            service.update_transaction(
                db, transaction_id=tx.id, tenant_id=tenant, actor="dono", data=corpo
            )
        assert exc.value.status_code == 422
        assert "lançamento" in str(exc.value)

    db.expire_all()
    intacto = db.get(BankTransaction, tx.id)
    assert intacto.posted_at == date(2026, 7, 10) and intacto.amount_cents == -100_00


@pytest.mark.parametrize("source", SOURCES_SISTEMA)
def test_AC9_movimento_de_origem_de_sistema_recusa_ignore(client: TestClient, headers, db, source):
    """`ignore` TIRA do saldo derivado. Ignorar um movimento que o e1p mesmo originou faria o saldo
    divergir do lançamento que o justifica — e a conferência acusaria um furo que o próprio clique
    criou. Divergência inventada é pior que divergência escondida."""
    from app.modules.bank.origin import sync_origin_movement

    acc = _account(client, headers)
    tenant = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    tx = sync_origin_movement(
        db,
        tenant_id=tenant,
        actor="dono",
        source=source,
        origin_id=f"origem-ignore-{source}",
        bank_account_id=acc["id"],
        posted_at=date(2026, 7, 10),
        amount_cents=-100_00,
        description="lançamento do sistema",
    )
    db.commit()

    resp = client.post(f"/bank/transactions/{tx.id}/ignore", headers=headers)
    assert resp.status_code == 422, resp.text
    db.expire_all()
    assert db.get(BankTransaction, tx.id).status == STATUS_MATCHED


@pytest.mark.parametrize("source", SOURCES_SISTEMA)
def test_AC9_a_EXCECAO_NOMEADA_e_user_description_e_so_ela(client: TestClient, headers, db, source):
    """*"A única exceção é `user_description`, que é rótulo, não fato."*

    Sem esta asserção ao lado, a guarda acima estaria satisfeita pela forma mais fácil e mais errada
    — recusar o PATCH inteiro —, e o dono perderia a única edição que ele legitimamente tem sobre um
    movimento de origem, sem que ninguém tivesse decidido tirar.
    """
    from app.modules.bank.origin import sync_origin_movement

    acc = _account(client, headers)
    tenant = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    tx = sync_origin_movement(
        db,
        tenant_id=tenant,
        actor="dono",
        source=source,
        origin_id=f"origem-rotulo-{source}",
        bank_account_id=acc["id"],
        posted_at=date(2026, 7, 10),
        amount_cents=-100_00,
        description="lançamento do sistema",
    )
    db.commit()

    resp = client.patch(
        f"/bank/transactions/{tx.id}", json={"user_description": "o meu rótulo"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_description"] == "o meu rótulo"
    assert resp.json()["raw_description"] == "lançamento do sistema"
