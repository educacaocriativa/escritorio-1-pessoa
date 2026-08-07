"""**A INVARIANTE DO TRILHO** (Story 8.15, AC3) — a defesa 1, estrutural.

> **Para toda `Charge` liquidada, exatamente UM de `transaction_id` e `bank_account_id` é
> não-nulo. Nunca os dois, nunca nenhum.**
>
> - `transaction_id IS NOT NULL` → **trilho** (plano 1): split 40/30/20, `PlatformEarning` criado,
>   **nenhum** `bank_transaction`. O dinheiro está na Carteira da e1p;
> - `bank_account_id IS NOT NULL` → **fora do trilho** (plano 3): **nenhuma** `Transaction`,
>   **nenhum** `PlatformEarning`, um `bank_transaction` de crédito. O dinheiro nunca passou pela
>   e1p.

Este arquivo monta um cenário **completo** — cobrança do trilho (via webhook), cobranças fora do
trilho (`paid` e `scheduled`), cobrança de rendimento de investimento, cobrança cancelada, cobrança
em aberto — e **varre todas as linhas liquidadas** exigindo exatamente-um-ponteiro, nos **dois
sentidos** (nem dois, nem nenhum), como o gate `bank_origin` já faz com a Regra da Origem.

⚠️ **A `Charge` sintética de rendimento (`external_ref='investment:<id>'`, Story 5.6) é EXCLUÍDA da
varredura, e a exclusão é explícita** (ratificada pela @architect, §C-1.5). Ela nasce `paid` e hoje
**não tem nenhum dos dois ponteiros**: é receita financeira do plano 2, que só ganha perna bancária
na Onda 2b (`register_yield` → `source='yield'`). Incluí-la faria a invariante nascer **vermelha
contra dado legítimo em produção**.

⚠️ **O predicado de exclusão é IMPORTADO de `receivables/service.py`, nunca reescrito** — *"duas
cópias divergem, e o parecer da ratificação é a prova de que já divergiram uma vez entre dois
@sm"*.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.modules.bank.models import BankTransaction
from app.modules.receivables.models import (
    STATUS_CANCELED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SCHEDULED,
    Charge,
)
from app.modules.receivables.service import _not_investment_yield
from app.modules.wallet.models import PlatformEarning, Transaction

REGISTER = {
    "legal_name": "Trilho e Fora do Trilho ME",
    "document": "11444777000161",
    "slug": "trilho",
    "email": "trilho@example.com",
    "name": "Teresa",
    "password": "uma-senha-bem-grande",
}

# Os estados em que uma cobrança já é uma afirmação sobre dinheiro que entrou (ou tem dia marcado
# para entrar) — e portanto os estados em que a invariante precisa valer. `open` e `canceled` ficam
# de fora: neles os DOIS ponteiros são legitimamente nulos, porque não houve liquidação nenhuma.
LIQUIDADAS = (STATUS_PAID, STATUS_SCHEDULED)


def _hoje() -> date:
    """A MESMA âncora do service, que desde o PR #78 é o FUSO DO TENANT — nunca UTC cru
    nem `date.today()` local. O tenant de teste fica com o fuso padrão."""
    return tenant_today(DEFAULT_TENANT_TIMEZONE)


ABERTURA = _hoje() - timedelta(days=60)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


@pytest.fixture()
def conta(client: TestClient, headers) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 10_000_00,
            "opening_balance_is_known": True,
            "opening_date": ABERTURA.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _charge(client: TestClient, headers, **over) -> dict:
    payload = {
        "kind": "service",
        "method": "pix",
        "amount_cents": 1_000_00,
        "due_date": _hoje().isoformat(),
        "description": "Consultoria",
    }
    payload.update(over)
    resp = client.post("/receivables/charges", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _settle_off_rail(client, headers, charge_id, *, conta_id, quando: date | None = None):
    body: dict = {"bank_account_id": conta_id}
    if quando is not None:
        body["received_on"] = quando.isoformat()
    return client.post(
        f"/receivables/charges/{charge_id}/settle-externally", json=body, headers=headers
    )


def _cenario_completo(client: TestClient, headers, tenant_id: str, conta: dict) -> dict:
    """As SEIS populações que a varredura precisa enxergar de uma vez.

    Um cenário com só uma população faria a invariante passar por vacuidade — e é exatamente assim
    que uma varredura vira enfeite: ela continua verde porque nunca teve o que reprovar.
    """
    # (1) Trilho: entra pelo WEBHOOK do gateway (caminho de produção), com split e PlatformEarning.
    do_trilho = _charge(client, headers, description="Pelo gateway")
    resp = client.post(
        "/receivables/webhook",
        json={"tenant_id": tenant_id, "charge_id": do_trilho["id"], "status": "paid"},
    )
    assert resp.json()["status"] == STATUS_PAID, resp.text

    # (2) Fora do trilho, já caiu (hoje) → `paid`.
    fora_hoje = _charge(client, headers, description="Pix direto")
    assert _settle_off_rail(
        client, headers, fora_hoje["id"], conta_id=conta["id"], quando=_hoje()
    ).status_code == 200

    # (3) Fora do trilho, agendado (amanhã) → `scheduled`.
    fora_agendado = _charge(client, headers, description="Pix agendado")
    assert _settle_off_rail(
        client,
        headers,
        fora_agendado["id"],
        conta_id=conta["id"],
        quando=_hoje() + timedelta(days=1),
    ).status_code == 200

    # (4) Cobrança em aberto — os DOIS ponteiros nulos, legitimamente.
    aberta = _charge(
        client,
        headers,
        description="Ainda em aberto",
        due_date=(_hoje() + timedelta(days=30)).isoformat(),
    )

    # (5) Cobrança cancelada — idem.
    cancelada = _charge(client, headers, description="Cancelada")
    assert client.post(
        f"/receivables/charges/{cancelada['id']}/cancel", headers=headers
    ).status_code == 200

    # (6) A `Charge` SINTÉTICA de rendimento de investimento (Story 5.6): nasce `paid`, **sem
    # nenhum dos dois ponteiros**. É ela que a varredura tem de excluir explicitamente.
    conta_dre = client.post(
        "/chart-of-accounts",
        json={"grupo_dre": "FINANCEIRO", "categoria": "Rendimento de aplicação"},
        headers=headers,
    )
    assert conta_dre.status_code == 201, conta_dre.text
    aplicacao = client.post(
        "/investments",
        json={
            "name": "CDB Banco X",
            "kind": "CDB",
            "principal_cents": 1_000_000,
            "opened_at": ABERTURA.isoformat(),
        },
        headers=headers,
    )
    assert aplicacao.status_code == 201, aplicacao.text
    rendimento = client.post(
        f"/investments/{aplicacao.json()['id']}/yield",
        json={
            "amount_cents": 12_000,
            "date": _hoje().isoformat(),
            "chart_account_id": conta_dre.json()["id"],
        },
        headers=headers,
    )
    assert rendimento.status_code == 200, rendimento.text

    return {
        "do_trilho": do_trilho["id"],
        "fora_hoje": fora_hoje["id"],
        "fora_agendado": fora_agendado["id"],
        "aberta": aberta["id"],
        "cancelada": cancelada["id"],
    }


# ── A varredura (AC3) ─────────────────────────────────────────────────────────────────────────


def test_A_INVARIANTE_DO_TRILHO_varre_todas_as_cobrancas_liquidadas(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """**A defesa 1.** Nem os dois ponteiros, nem nenhum — em TODA cobrança liquidada do cenário.

    Falha em qualquer linha que preencha os dois (dinheiro existindo nos dois planos) **ou** nenhum
    (dinheiro liquidado sem lastro em plano nenhum: some da Carteira e do extrato ao mesmo tempo).
    """
    ids = _cenario_completo(client, headers, tenant_id, conta)

    liquidadas = list(
        db.scalars(
            select(Charge).where(Charge.status.in_(LIQUIDADAS)).where(_not_investment_yield())
        ).all()
    )
    # Pré-condição: a varredura tem o que varrer (senão ela passaria por vacuidade).
    assert {c.id for c in liquidadas} == {ids["do_trilho"], ids["fora_hoje"], ids["fora_agendado"]}

    infratoras = [
        (c.id, c.description, c.status, c.transaction_id, c.bank_account_id)
        for c in liquidadas
        if (c.transaction_id is None) == (c.bank_account_id is None)
    ]
    assert not infratoras, (
        "INVARIANTE DO TRILHO VIOLADA — cobranças liquidadas com os DOIS ponteiros ou com NENHUM: "
        f"{infratoras}. `transaction_id` significa trilho (Carteira + split + PlatformEarning); "
        "`bank_account_id` significa fora do trilho (crédito no banco do dono, sem split). Os dois "
        "juntos fazem o mesmo dinheiro existir em dois planos; nenhum dos dois faz o dinheiro "
        "liquidado não existir em plano nenhum."
    )


def test_a_cobranca_do_TRILHO_tem_transaction_e_platform_earning_e_ZERO_movimento_bancario(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """A metade "trilho" da invariante, com as consequências que ela promete."""
    ids = _cenario_completo(client, headers, tenant_id, conta)
    charge = db.get(Charge, ids["do_trilho"])

    assert charge.transaction_id is not None
    assert charge.bank_account_id is None and charge.bank_transaction_id is None
    assert db.get(Transaction, charge.transaction_id) is not None
    # E nenhum movimento bancário aponta para ela: o dinheiro do trilho não encosta na conta do
    # dono até o payout (Onda 3).
    assert (
        db.scalars(
            select(BankTransaction).where(BankTransaction.origin_id == charge.id)
        ).first()
        is None
    )


def test_a_cobranca_FORA_DO_TRILHO_tem_conta_bancaria_e_ZERO_transaction(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """A metade "fora do trilho": crédito no banco, e **nada** no plano da plataforma."""
    ids = _cenario_completo(client, headers, tenant_id, conta)
    charge = db.get(Charge, ids["fora_hoje"])

    assert charge.transaction_id is None
    assert charge.bank_account_id == conta["id"]
    movimento = db.scalars(
        select(BankTransaction).where(BankTransaction.origin_id == charge.id)
    ).first()
    assert movimento is not None
    assert movimento.amount_cents == charge.amount_cents > 0, "crédito é POSITIVO"
    assert movimento.source == "charge"
    assert movimento.status == "matched", "movimento de origem nasce conciliado"
    # O cache nunca diverge do `origin_id` (contrato do sincronizador).
    assert charge.bank_transaction_id == movimento.id
    # Nenhuma `Transaction` nasceu por causa dela.
    assert (
        db.scalars(select(Transaction).where(Transaction.external_ref == charge.id)).first() is None
    )


def test_a_charge_de_RENDIMENTO_e_excluida_pelo_predicado_do_modulo_e_nao_por_copia(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """⚠️ **A exclusão precisa ser VISÍVEL, senão a invariante nasce vermelha em produção.**

    A `Charge` de rendimento (Story 5.6) é `paid` **sem nenhum dos dois ponteiros** — ela violaria
    a invariante por construção. Ela é receita financeira do plano 2 e ganha perna bancária só na
    Onda 2b; excluí-la aqui é decisão registrada, não conveniência.

    O teste prova **duas** coisas: (a) que ela existe e é de fato uma violadora se incluída — sem
    isso o `where` de exclusão seria decorativo; (b) que quem a exclui é o predicado **do módulo**
    (`_not_investment_yield`), e não uma segunda cópia do `LIKE 'investment:%'` escrita aqui.
    """
    _cenario_completo(client, headers, tenant_id, conta)

    rendimento = db.scalars(
        select(Charge).where(Charge.external_ref.like("investment:%"))
    ).first()
    assert rendimento is not None and rendimento.status == STATUS_PAID
    # (a) Sem a exclusão, ela seria uma infratora — este é o membro do conjunto "violaria".
    assert rendimento.transaction_id is None and rendimento.bank_account_id is None

    # (b) E o predicado do módulo é exatamente o que a tira da varredura.
    excluidas = db.scalars(
        select(Charge.id).where(Charge.status == STATUS_PAID).where(~_not_investment_yield())
    ).all()
    assert list(excluidas) == [rendimento.id]


def test_cobranca_ABERTA_e_CANCELADA_tem_os_dois_ponteiros_nulos_e_isso_esta_certo(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """**O não-membro do conjunto** (regra da instanciação obrigatória, `CLAUDE.md`).

    A invariante fala de cobrança **liquidada**. Em aberto e cancelada, os dois ponteiros nulos são
    o estado correto — e escrever isto impede que alguém "conserte" a invariante estendendo-a a
    toda `Charge` e passe a exigir conta bancária de uma cobrança que ninguém pagou.
    """
    ids = _cenario_completo(client, headers, tenant_id, conta)

    for chave, status in (("aberta", STATUS_OPEN), ("cancelada", STATUS_CANCELED)):
        charge = db.get(Charge, ids[chave])
        assert charge.status == status
        assert charge.transaction_id is None and charge.bank_account_id is None


def test_a_invariante_SOBREVIVE_a_promocao_do_worker(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """`scheduled → paid` não pode ser a porta por onde a invariante se rompe.

    A promoção move **só o status**. Se algum dia ela "aproveitasse" para criar a `Transaction` que
    a cobrança "deveria" ter, o dinheiro passaria a existir nos dois planos — e nenhum teste de
    comportamento do worker notaria, porque o status resultante seria o mesmo.
    """
    from app.modules.receivables import service as receivables_service

    ids = _cenario_completo(client, headers, tenant_id, conta)
    promovidas = receivables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="system:worker", today=_hoje() + timedelta(days=2)
    )
    assert promovidas == 1

    charge = db.get(Charge, ids["fora_agendado"])
    db.refresh(charge)
    assert charge.status == STATUS_PAID
    assert charge.transaction_id is None, "promover NÃO é entrar no trilho"
    assert charge.bank_account_id == conta["id"]
    assert (charge.transaction_id is None) != (charge.bank_account_id is None)


def test_nenhum_PlatformEarning_do_lado_de_fora_do_trilho(
    client: TestClient, headers, tenant_id, conta, db: Session
):
    """`platform_earnings` é ledger **GLOBAL, sem RLS** — um vazamento ali aparece no GMV de todos.

    O cenário tem **uma** cobrança do trilho e **duas** fora dele: o ledger tem de ter exatamente
    uma linha, a do trilho.
    """
    _cenario_completo(client, headers, tenant_id, conta)

    ganhos = list(db.scalars(select(PlatformEarning)).all())
    assert len(ganhos) == 1, (
        "o painel do Master ganhou (ou perdeu) linhas por causa do recebimento fora do trilho — "
        f"esperado exatamente 1 (a cobrança do trilho), veio {len(ganhos)}"
    )
    assert ganhos[0].gross_cents == 1_000_00
