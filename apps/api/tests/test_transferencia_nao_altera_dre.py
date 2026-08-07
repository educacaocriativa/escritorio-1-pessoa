"""**A Regra da NEUTRALIDADE** — o teste que o design da Onda 2 nomeou (Story 8.18, AC6 / IV1).

> Transferência entre contas próprias é **exclusivamente** evento do plano 3: **nunca** cria, altera
> ou baixa `Charge`, `Payable` ou `Transaction`, e por isso **não aparece** na DRE, na Lucratividade
> nem na Projeção como entrada ou saída.

**Por que este arquivo existe se a propriedade é verdadeira POR CONSTRUÇÃO.** `dre.py` agrega
exatamente `charges` + `payables` + `transactions` (`dre.py:161`, `_sum_by_account` /
`_sum_transactions_by_account`); `bank_transfers` e `bank_transactions` não são nenhuma das três e
**nunca serão** — a Regra dos Planos proíbe. Então por que o teste?

Porque **a garantia é a invariante, não o nome**. O dia em que alguém "melhorar" a DRE para incluir
uma quarta fonte — e o candidato óbvio é justamente o razão bancário, que é a tabela mais completa
do produto —, este é o teste que avisa. É a mesma lógica dos gates estruturais de
`test_money_planes.py` e do gate de pureza do `engine.py`: *"sem o teste, o resto degrada por
acidente"* (epic §4.1c). O
risco correspondente no epic tem nome — **"Resgate de aplicação virando receita fantasma"** — e é
mitigado por *"duas defesas independentes"*: esta e a asserção de zero acoplamento com o produto
financeiro (`test_bank_transfers_nao_importa_investments`).

**Snapshot CAMPO A CAMPO, e não `==` de objeto.** Um `assert depois == antes` diria "mudou" sem
dizer **o quê** — e num relatório com dezenas de campos aninhados isso é a diferença entre um alarme
e um
enigma. Aqui a comparação é feita sobre `asdict(...)` (que preserva o aninhamento) **e** repetida
campo a campo nos totais, para que a mensagem de falha nomeie o número que se moveu.

⚠️ **Três transferências, e uma delas para conta de aplicação** — porque é a de aplicação que a
"melhoria" futura mais provavelmente trataria como receita/despesa (é ela que *parece*
investimento, e não é).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.modules.bank.models import (
    KIND_CHECKING,
    KIND_INVESTMENT,
    TRANSFER_KIND_INVESTMENT_IN,
    TRANSFER_KIND_OWN,
)
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import profitability as profitability_service
from app.modules.financial_intelligence import projection as projection_service

REGISTER = {
    "legal_name": "Neutralidade ME",
    "document": "11444777000161",
    "slug": "neutralidade",
    "email": "neutra@example.com",
    "name": "Nara",
    "password": "uma-senha-bem-grande",
}


def _hoje() -> date:
    return tenant_today(DEFAULT_TENANT_TIMEZONE)


ABERTURA = _hoje() - timedelta(days=90)
DIA = _hoje() - timedelta(days=5)
# A janela da DRE cobre a data das transferências E a dos lançamentos semeados abaixo.
INICIO = _hoje() - timedelta(days=60)
FIM = _hoje()


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conta(client: TestClient, headers, *, name: str, kind: str, opening: int, number: str) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": kind,
            "number": number,
            "opening_balance_cents": opening,
            "opening_balance_is_known": True,
            "opening_date": ABERTURA.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed_movimento_financeiro(client: TestClient, headers) -> None:
    """Uma cobrança e uma conta a pagar, para que a DRE do período **não** seja trivialmente vazia.

    Uma DRE toda zerada passaria neste teste sem provar nada: zero continua zero depois de qualquer
    coisa. É a mesma disciplina de `test_movimento_de_origem_nao_altera_a_dre` (Story 8.9).
    """
    assert (
        client.post(
            "/receivables/charges",
            json={
                "description": "Consultoria",
                "kind": "service",
                "method": "pix",
                "amount_cents": 300_000,
                "due_date": (INICIO + timedelta(days=5)).isoformat(),
            },
            headers=headers,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/payables/bills",
            json={
                "description": "Aluguel",
                "category": "Estrutura",
                "amount_cents": 120_000,
                "due_date": (INICIO + timedelta(days=3)).isoformat(),
            },
            headers=headers,
        ).status_code
        == 201
    )


def _transferir(client: TestClient, headers, *, from_id: str, to_id: str, kind: str, valor: int):
    resp = client.post(
        "/bank/transfers",
        json={
            "from_account_id": from_id,
            "to_account_id": to_id,
            "amount_cents": valor,
            "posted_at": DIA.isoformat(),
            "kind": kind,
            "description": "movimentação entre contas",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _snapshot_dre(db: Session) -> dict:
    return asdict(dre_service.dre_report(db, start=INICIO, end=FIM))


def _snapshot_lucratividade(db: Session) -> list[dict]:
    return [
        asdict(c)
        for c in profitability_service.contracts_dre_report(db, start=INICIO, end=FIM)
    ]


@pytest.fixture()
def cenario(client: TestClient, headers) -> dict:
    """Três contas (corrente, poupança, aplicação) + lançamentos de negócio no período."""
    _seed_movimento_financeiro(client, headers)
    return {
        "corrente": _conta(
            client, headers, name="Itaú PJ", kind=KIND_CHECKING, opening=10_000_00, number="1-1"
        ),
        "poupanca": _conta(
            client, headers, name="Poupança", kind="savings", opening=500_00, number="2-2"
        ),
        "aplicacao": _conta(
            client, headers, name="CDB", kind=KIND_INVESTMENT, opening=0, number="3-3"
        ),
    }


# ── IV1 — a DRE não se move ──────────────────────────────────────────────────────────────────


def test_transferencia_nao_altera_dre(client: TestClient, headers, cenario, db: Session):
    """**O teste que dá nome a este arquivo.** Snapshot da DRE **idêntico campo a campo**.

    Três transferências, incluindo `checking → investment`. Se qualquer número da DRE se mexer, uma
    transferência entrou como receita ou despesa — ou seja, como **número inventado**: o dinheiro
    não entrou nem saiu da empresa, só mudou de conta.
    """
    antes = _snapshot_dre(db)

    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["poupanca"]["id"],
        kind=TRANSFER_KIND_OWN, valor=1_000_00,
    )
    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["aplicacao"]["id"],
        kind=TRANSFER_KIND_INVESTMENT_IN, valor=2_500_00,
    )
    _transferir(
        client, headers,
        from_id=cenario["poupanca"]["id"], to_id=cenario["corrente"]["id"],
        kind=TRANSFER_KIND_OWN, valor=300_00,
    )

    depois = _snapshot_dre(db)

    # Campo a campo nos totais primeiro: a mensagem de falha nomeia QUAL número se moveu.
    for campo in antes:
        if isinstance(antes[campo], int | float) or antes[campo] is None:
            assert depois[campo] == antes[campo], (
                f"a DRE mudou no campo `{campo}` depois de 3 transferências entre contas próprias: "
                f"{antes[campo]} → {depois[campo]}. Transferência não é receita nem despesa — se "
                "entrou na DRE, entrou como número inventado."
            )
    # E o relatório inteiro, incluindo os grupos e as linhas aninhadas.
    assert depois == antes


def test_transferencia_nao_altera_a_lucratividade(
    client: TestClient, headers, cenario, db: Session
):
    """A Lucratividade **deriva** da DRE, logo estaria coberta — e mesmo assim é verificada.

    "Derivada, logo coberta" é uma inferência sobre o código de hoje. O snapshot é uma afirmação
    sobre o comportamento, e é ela que sobrevive a alguém acrescentar uma fonte própria ali.
    """
    antes = _snapshot_lucratividade(db)

    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["aplicacao"]["id"],
        kind=TRANSFER_KIND_INVESTMENT_IN, valor=2_500_00,
    )

    assert _snapshot_lucratividade(db) == antes


# ── IV1 — a Projeção: o total não muda; a composição, quando é aplicação, MUDA (e é correto) ──


def test_transferencia_entre_contas_ELEGIVEIS_nao_muda_a_projecao(
    client: TestClient, headers, cenario, db: Session
):
    """Corrente → poupança: o saldo **redistribui** e a Projeção não sente. Campo a campo.

    As duas contas entram em `active_balance_total` (só `investment` fica de fora), então a parcela
    bancária do `saldo_inicial` é a mesma soma de antes — e, com ela, todas as janelas e o runway.
    """
    hoje = _hoje()
    antes = asdict(projection_service.cash_projection(db, today=hoje))

    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["poupanca"]["id"],
        kind=TRANSFER_KIND_OWN, valor=1_000_00,
    )

    depois = asdict(projection_service.cash_projection(db, today=hoje))
    assert depois["saldo_inicial_cents"] == antes["saldo_inicial_cents"]
    assert depois["saldo_inicial_banco_cents"] == antes["saldo_inicial_banco_cents"]
    assert depois["saldo_inicial_plataforma_cents"] == antes["saldo_inicial_plataforma_cents"]
    assert depois["saldo_inicial_origem"] == antes["saldo_inicial_origem"]
    assert depois == antes


def test_transferencia_para_APLICACAO_derruba_o_caixa_da_projecao_e_isso_e_CORRETO(
    client: TestClient, headers, cenario, db: Session
):
    """**O risco residual que o @po marcou — fixado por teste em vez de deixado por acaso.**

    `active_balance_total` exclui `kind='investment'` por default (design §6.1: dinheiro aplicado
    não é caixa para pagar a conta de amanhã). Logo transferir para a aplicação **reduz** a parcela
    bancária do `saldo_inicial` — e é a primeira vez no produto que uma ação do dono encurta o
    runway **sem que nada tenha sido pago**. É verdade e é correto; por isso o aviso do AC10 é
    obrigatório
    na tela, não polimento.

    ⚠️ **O que continua imóvel é o que importa aqui:** a parcela da PLATAFORMA, a origem declarada e
    os fluxos (`overdue_inflow`/`overdue_outflow`) — nenhuma transferência os alcança. E as janelas
    caem exatamente pelo mesmo valor do saldo inicial, nunca por um valor próprio.
    """
    hoje = _hoje()
    antes = asdict(projection_service.cash_projection(db, today=hoje))
    valor = 2_500_00

    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["aplicacao"]["id"],
        kind=TRANSFER_KIND_INVESTMENT_IN, valor=valor,
    )

    depois = asdict(projection_service.cash_projection(db, today=hoje))
    assert depois["saldo_inicial_banco_cents"] == antes["saldo_inicial_banco_cents"] - valor
    assert depois["saldo_inicial_plataforma_cents"] == antes["saldo_inicial_plataforma_cents"]
    assert depois["saldo_inicial_origem"] == antes["saldo_inicial_origem"]
    assert depois["overdue_inflow_cents"] == antes["overdue_inflow_cents"]
    assert depois["overdue_outflow_cents"] == antes["overdue_outflow_cents"]
    for w_antes, w_depois in zip(antes["windows"], depois["windows"], strict=True):
        assert w_depois["saldo_projetado_cents"] == w_antes["saldo_projetado_cents"] - valor


def test_o_dinheiro_da_aplicacao_NAO_sumiu_do_total_em_contas(
    client: TestClient, headers, cenario, db: Session
):
    """A metade que impede o teste acima de ser lido como "aplicar destrói dinheiro".

    O *"Total em contas"* (o recorte que **inclui** aplicação) não se move. São dois recortes, dois
    rótulos, e a diferença entre eles é exatamente o que o dono precisa entender (lição UX-001).
    """
    from app.modules.bank import service as bank_service

    hoje = _hoje()
    total_antes = bank_service.active_balance_total(db, until=hoje, exclude_kinds=())

    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["aplicacao"]["id"],
        kind=TRANSFER_KIND_INVESTMENT_IN, valor=2_500_00,
    )

    assert bank_service.active_balance_total(db, until=hoje, exclude_kinds=()) == total_antes


# ── A Regra da Neutralidade em forma de contagem: nada de negócio foi tocado ──────────────────


def test_nenhuma_charge_payable_ou_transaction_e_criada_alterada_ou_baixada(
    client: TestClient, headers, cenario, db: Session
):
    """A afirmação normativa, verificada nas **três** tabelas do plano 1 e do plano 2.

    Snapshot de cada linha (id, status e valor) antes e depois — não só a contagem. Contagem sozinha
    não pegaria o modo de falha mais provável: uma transferência **baixando** uma cobrança existente
    (o número de linhas não mudaria, o status sim).
    """
    from sqlalchemy import select

    from app.modules.payables.models import Payable
    from app.modules.receivables.models import Charge
    from app.modules.wallet.models import Transaction

    def _foto() -> dict[str, list[tuple]]:
        return {
            "charges": [
                (c.id, c.status, c.amount_cents) for c in db.scalars(select(Charge)).all()
            ],
            "payables": [
                (p.id, p.status, p.amount_cents) for p in db.scalars(select(Payable)).all()
            ],
            "transactions": [
                (t.id, t.status, t.gross_cents) for t in db.scalars(select(Transaction)).all()
            ],
        }

    antes = _foto()
    assert antes["charges"] and antes["payables"], "pré-condição: o cenário não pode estar vazio"

    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["poupanca"]["id"],
        kind=TRANSFER_KIND_OWN, valor=1_000_00,
    )
    _transferir(
        client, headers,
        from_id=cenario["corrente"]["id"], to_id=cenario["aplicacao"]["id"],
        kind=TRANSFER_KIND_INVESTMENT_IN, valor=2_500_00,
    )
    db.expire_all()

    assert _foto() == antes, (
        "uma transferência tocou `charges`/`payables`/`transactions` — ela é evento do plano 3 e "
        "de mais nenhum (Regra da Neutralidade, epic §4.2)"
    )
