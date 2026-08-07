"""**Story 8.14 — o estado `scheduled`: agendar sem mentir na Projeção.**

O que esta story resolve, em uma frase: o dono **agenda o pagamento no app do banco** e precisa
registrar isso sem que o dinheiro suma de nenhuma das telas — nem do saldo (onde ele ainda está),
nem da Projeção (de onde ele vai sair), nem da Fila (onde ele já foi resolvido).

Cobre:

- **AC1** `STATUS_SCHEDULED` no vocabulário, cabendo em `String(12)` — **sem migration**;
- **AC2** o estado é **DERIVADO da data**, nas duas direções da invariante
  `status == 'scheduled' ⟺ paid_at.date() > hoje` (no momento da escrita), e a API **nunca** aceita
  `status` do cliente;
- **AC3** o teto de `paid_on` da 8.12 **saiu**; o **piso** contra a `opening_date` **ficou**, com a
  mensagem que nomeia as duas saídas;
- **AC7/AC8** o balde "Agendadas" e o `scheduled_cents`, sem contaminar nenhum campo antigo;
- **AC9** estorno de conta agendada (cancelar um agendamento **é** estornar);
- **AC10** `promote_scheduled` — só o que venceu, idempotente, sem re-datar, e **o saldo derivado
  correto com o worker DESLIGADO** (a prova do F-D11);
- **AC11** a bandeja de comprovantes enxerga a agendada;
- **AC14** `is_overdue` continua `False`, e nenhuma migration nasceu.

A dupla contagem do dia D (AC6) e a IV1 vivem em `test_financial_intelligence_projection.py`, junto
do resto da Projeção; a guarda de data por origem (AC4) vive em `test_bank_transactions.py`, junto
do resto da porta manual. Isolamento cross-tenant da promoção é `rls_e2e` (`test_bank_rls.py`).
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scheduling import status_por_data
from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.modules.bank import service as bank_service
from app.modules.bank.models import BankTransaction
from app.modules.payables import receipts as receipts_service
from app.modules.payables import service as payables_service
from app.modules.payables.models import (
    ALL_STATUSES,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SCHEDULED,
    Payable,
)
from app.modules.payables.schemas import (
    PayableCreate,
    PayablePayIn,
    PayablePaymentUpdate,
    PayableUpdate,
)

REGISTER = {
    "legal_name": "Agendamento ME",
    "document": "11444777000161",
    "slug": "agendamento",
    "email": "agenda@example.com",
    "name": "Selma",
    "password": "uma-senha-bem-grande",
}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _hoje() -> date:
    """A MESMA âncora do service, que desde o PR #78 é o FUSO DO TENANT — nunca UTC cru
    nem `date.today()` local. O tenant de teste fica com o fuso padrão."""
    return tenant_today(DEFAULT_TENANT_TIMEZONE)


# Abertura dois meses atrás: o piso fica longe o bastante para não interferir nos testes de data
# retroativa (`paid_on = hoje - 5`), e continua sendo alcançável pelos testes que o exercitam de
# propósito. **Ancorada em "hoje", nunca num dia fixo** — data fixa envelheceria junto com o
# repositório sem nunca quebrar, até quebrar por outro motivo (lição de `test_bank_corte_de_data`).
ABERTURA = _hoje() - timedelta(days=60)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _conta(client: TestClient, headers, **over) -> dict:
    payload = {
        "name": "Itaú PJ",
        "kind": "checking",
        "opening_balance_cents": 10_000_00,
        "opening_balance_is_known": True,
        "opening_date": ABERTURA.isoformat(),
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def conta(client: TestClient, headers) -> dict:
    return _conta(client, headers)


def _bill(client: TestClient, headers, **over) -> dict:
    payload = {
        "description": "Aluguel",
        "supplier": "Imobiliária Central",
        "amount_cents": 5_000_00,
        "due_date": _hoje().isoformat(),
    }
    payload.update(over)
    resp = client.post("/payables/bills", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _pay(client: TestClient, headers, bill_id: str, *, conta_id: str, paid_on: date | None = None):
    body: dict = {"bank_account_id": conta_id}
    if paid_on is not None:
        body["paid_on"] = paid_on.isoformat()
    return client.post(f"/payables/bills/{bill_id}/pay", json=body, headers=headers)


def _get(client: TestClient, headers, bill_id: str) -> dict:
    return client.get(f"/payables/bills/{bill_id}", headers=headers).json()


# ── AC1 — o vocabulário, e a coluna que não precisou de migration ────────────────────────────


def test_scheduled_entrou_no_vocabulario():
    assert STATUS_SCHEDULED == "scheduled"
    assert ALL_STATUSES == {"open", "scheduled", "paid", "canceled"}


def test_scheduled_cabe_na_coluna_e_por_isso_nao_ha_migration():
    """**AC1 verificado, não presumido** — e a asserção é contra a coluna REAL, não contra o `12`.

    Se alguém "melhorar" o vocabulário para uma string maior (`"agendado_banco"`, `"scheduled_at_
    bank"`), este teste reprova **antes** de a linha ser gravada truncada em produção. Ampliar a
    coluna é possível, mas custa uma migration com `ALTER TYPE` sobre dado existente sob
    `FORCE RLS` — a armadilha da 0046 que o ADR 0003 nomeia. O teste força quem quiser isso a
    tomar a decisão de propósito.
    """
    coluna = Payable.__table__.c.status
    assert len(STATUS_SCHEDULED) <= coluna.type.length
    # E todo o resto do vocabulário também — um valor novo não pode entrar pela porta de trás.
    assert all(len(s) <= coluna.type.length for s in ALL_STATUSES)


def test_a_story_nao_cria_migration():
    versions = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"
    assert not list(versions.glob("*8_14*")), "esta story não cria migration (AC1/AC14)"
    assert not list(versions.glob("*scheduled*"))


# ── AC2 — o estado é DERIVADO da data, nas DUAS direções ─────────────────────────────────────


def test_helper_de_derivacao_e_publico_e_neutro():
    """**Contrato criado por esta story e consumido pela 8.15** — o nome e o lugar são o contrato.

    A v0.1 da story declarava `_status_por_data`, **privado**, dentro de `payables/service.py`. O
    @po corrigiu: um símbolo com `_` importado por outro módulo é a costura frouxa que produz duas
    cópias no primeiro ajuste, e fazer `receivables` importar `payables` só por causa deste
    predicado seria acoplamento gratuito entre dois módulos de negócio.
    """
    assert not status_por_data.__name__.startswith("_")
    assert status_por_data.__module__ == "app.core.scheduling"
    assert "payables" not in status_por_data.__module__


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [
        (-30, STATUS_PAID),
        (-1, STATUS_PAID),
        (0, STATUS_PAID),  # ⚠️ A BORDA: hoje é PAGO, não agendado (é o que evita a dupla contagem)
        (1, STATUS_SCHEDULED),
        (30, STATUS_SCHEDULED),
    ],
)
def test_status_por_data_nas_duas_direcoes(dias: int, esperado: str):
    """A invariante em forma pura: **a borda `> hoje` é estrita, e é o ponto todo.**

    `paid_on == hoje` ⇒ `paid`, porque o movimento bancário correspondente já tem
    `posted_at <= hoje` e portanto já entra em `active_balance_total(until=today)`. Tratar hoje
    como agendado faria o mesmo dinheiro ser contado duas vezes na Projeção.
    """
    hoje = date(2026, 8, 4)
    assert (
        status_por_data(
            hoje + timedelta(days=dias),
            hoje,
            status_agendado=STATUS_SCHEDULED,
            status_pago=STATUS_PAID,
        )
        == esperado
    )


def test_payables_IMPORTA_o_helper_em_vez_de_reimplementar():
    """**Estrutural, não comportamental — e o mutante que ele mata é invisível de outra forma.**

    Um `payables/service.py` que reimplementasse `p.status = SCHEDULED if paid_on > hoje else PAID`
    inline passaria em **todos** os testes de comportamento deste arquivo, e a 8.15 nasceria com a
    segunda cópia da regra. O teste do AC comportamental não distingue os dois mundos; este
    distingue. (É o mesmo motivo pelo qual a Story 8.9 precisou de gates de import por AST.)
    """
    fonte = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app" / "modules" / "payables" / "service.py"
    )
    arvore = ast.parse(fonte.read_text(encoding="utf-8"))
    importado = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.core.scheduling"
        and any(a.name == "status_por_data" for a in node.names)
        for node in ast.walk(arvore)
    )
    assert importado, (
        "`payables/service.py` parou de importar `app.core.scheduling.status_por_data`. Se a regra "
        "foi reescrita inline, existem agora DUAS derivações do mesmo estado — e a Story 8.15 vai "
        "nascer com a terceira. Importar, nunca copiar."
    )
    chamadas = sum(
        1
        for node in ast.walk(arvore)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "status_por_data"
    )
    assert chamadas >= 2, (
        "a derivação é usada em MENOS de dois lugares. `apply_paid` e `update_payment` precisam "
        "das duas — a correção da data é justamente onde a fronteira `paid ⇄ scheduled` é "
        f"atravessada (encontradas: {chamadas})"
    )


def test_data_futura_vira_scheduled_e_data_de_hoje_vira_paid(client: TestClient, headers, conta):
    """A invariante pela API, nas duas direções, no mesmo cenário."""
    futura = _bill(client, headers, description="Agendada")
    amanha = _hoje() + timedelta(days=1)
    resp = _pay(client, headers, futura["id"], conta_id=conta["id"], paid_on=amanha)
    assert resp.status_code == 200, resp.text
    out_futura = _get(client, headers, futura["id"])
    assert out_futura["status"] == STATUS_SCHEDULED
    assert out_futura["paid_at"].startswith(amanha.isoformat())

    hoje_bill = _bill(client, headers, description="Paga hoje")
    assert _pay(
        client, headers, hoje_bill["id"], conta_id=conta["id"], paid_on=_hoje()
    ).status_code == 200
    assert _get(client, headers, hoje_bill["id"])["status"] == STATUS_PAID


def test_invariante_scheduled_sse_paid_at_futuro(client: TestClient, headers, conta, db: Session):
    """**`status == 'scheduled' ⟺ paid_at.date() > hoje`, no momento da escrita.**

    Escrita como varredura sobre TODAS as linhas do cenário (e não como asserção sobre uma), no
    estilo da Invariante da Origem da 8.9: uma invariante que só é aferida no caminho feliz não é
    invariante, é exemplo.
    """
    hoje = _hoje()
    for dias in (-5, -1, 0, 1, 5, 40):
        bill = _bill(client, headers, description=f"conta D{dias:+}")
        _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=hoje + timedelta(days=dias))

    linhas = list(db.scalars(select(Payable)).all())
    assert len(linhas) == 6
    for p in linhas:
        agendada = p.status == STATUS_SCHEDULED
        futura = p.paid_at.date() > hoje
        assert agendada == futura, (
            f"invariante quebrada: status={p.status} paid_at={p.paid_at} hoje={hoje}. "
            "`scheduled` e `paid_at > hoje` têm de ser a MESMA afirmação no momento da escrita."
        )


@pytest.mark.parametrize(
    "schema", [PayableCreate, PayableUpdate, PayablePayIn, PayablePaymentUpdate]
)
def test_nenhum_schema_de_entrada_aceita_status(schema):
    """**A API nunca aceita `status` do cliente** (AC2). Guarda estrutural, nos QUATRO schemas.

    O estado é derivado da data. Um campo `status` em qualquer um destes payloads tornaria a
    derivação uma sugestão — e bastaria um cliente mandar `status="paid"` com data futura para o
    dinheiro sumir da Projeção, que é exatamente o bug que a story existe para impedir.
    """
    assert "status" not in schema.model_fields


def test_mandar_status_no_payload_e_ignorado(client: TestClient, headers, conta):
    """A metade de comportamento da guarda acima: o campo extra não vira estado."""
    bill = client.post(
        "/payables/bills",
        json={
            "description": "Tentativa",
            "amount_cents": 100_00,
            "due_date": _hoje().isoformat(),
            "status": STATUS_SCHEDULED,
        },
        headers=headers,
    )
    assert bill.status_code == 201, bill.text
    assert bill.json()["status"] == STATUS_OPEN, "o cliente conseguiu escolher o estado"

    # E na baixa: `status` no corpo não muda a derivação pela data.
    resp = client.post(
        f"/payables/bills/{bill.json()['id']}/pay",
        json={
            "bank_account_id": conta["id"],
            "paid_on": _hoje().isoformat(),
            "status": STATUS_SCHEDULED,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == STATUS_PAID


# ── AC3 — o teto saiu, o piso ficou ──────────────────────────────────────────────────────────


def test_o_piso_contra_a_abertura_da_conta_CONTINUA_de_pe(client: TestClient, headers, conta):
    """A remoção do teto **não** removeu o piso — e a mensagem continua nomeando as DUAS saídas.

    ⚠️ O status sozinho não prova a guarda (achado por mutação na 8.12): `sync_origin_movement`
    também aplica o piso e devolveria 422 de todo jeito. O que distingue é a **mensagem** — só a
    guarda de `payables` diz ao usuário o que fazer.
    """
    antiga = ABERTURA - timedelta(days=1)
    bill = _bill(client, headers, due_date=antiga.isoformat())
    resp = _pay(client, headers, bill["id"], conta_id=conta["id"])
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert ABERTURA.isoformat() in detail
    assert "escolha outra conta" in detail
    assert "saldo daquele dia" in detail


def test_a_borda_do_piso(client: TestClient, headers, conta):
    """`paid_on == opening_date` → 422; `paid_on == opening_date + 1` → aceito. Estrito, como o
    saldo derivado, que soma `posted_at > opening_date`."""
    na_abertura = _bill(client, headers, due_date=ABERTURA.isoformat())
    assert _pay(client, headers, na_abertura["id"], conta_id=conta["id"]).status_code == 422

    depois = _bill(client, headers, due_date=(ABERTURA + timedelta(days=1)).isoformat())
    assert _pay(client, headers, depois["id"], conta_id=conta["id"]).status_code == 200


def test_data_muito_futura_e_aceita_sem_teto_nenhum(client: TestClient, headers, conta):
    """Não existe mais teto — nem em hoje, nem em +30, nem em +365. *"Sem teto superior"* (design
    §4.2). A guarda que sobrou é o piso, e ele não tem nada a ver com o futuro."""
    bill = _bill(client, headers)
    daqui_um_ano = _hoje() + timedelta(days=365)
    resp = _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=daqui_um_ano)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == STATUS_SCHEDULED


# ── O movimento bancário do agendamento ──────────────────────────────────────────────────────


def test_a_agendada_gera_UM_movimento_com_posted_at_no_futuro(
    client: TestClient, headers, conta, db: Session
):
    """A Regra da Origem vale igual: **um** movimento, nascido `matched`, com a data do débito.

    É esta linha — e não o worker — que faz o saldo se corrigir sozinho quando o dia chega.
    """
    bill = _bill(client, headers)
    dia_do_debito = _hoje() + timedelta(days=15)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=dia_do_debito)

    movimentos = list(db.scalars(select(BankTransaction)).all())
    assert len(movimentos) == 1
    tx = movimentos[0]
    assert tx.posted_at == dia_do_debito
    assert tx.amount_cents == -5_000_00, "saída é NEGATIVA (invariante (b) do modelo)"
    assert tx.origin_id == bill["id"]


def test_o_agendado_NAO_entra_no_saldo_corrente_e_entra_no_agendado_da_conta(
    client: TestClient, headers, conta, db: Session
):
    """**AC13 + o pré-requisito duro da 8.10, no mesmo cenário.**

    O saldo corrente (`until=None` = hoje, desde a 8.10) **não** vê o agendado — se visse, "Total
    em contas" mostraria R$ 5.000 que já têm destino marcado. E `agendado_saida_cents` é o
    **complemento exato**: os dois juntos cobrem o histórico inteiro, uma vez só.
    """
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=15))

    lista = client.get("/bank/accounts", headers=headers).json()
    assert lista[0]["saldo_derivado_cents"] == 10_000_00, (
        "o saldo corrente somou um débito que ainda não saiu da conta"
    )
    assert lista[0]["agendado_saida_cents"] == 5_000_00
    assert lista[0]["agendado_entrada_cents"] == 0, (
        "não existe entrada agendada até a Story 8.15 — se apareceu, algo produziu movimento "
        "positivo futuro por um caminho não previsto"
    )
    # Regra dos Planos §1.3c: nenhum saldo trafega sem procedência declarada.
    assert lista[0]["agendado_origem"] == "banco"

    # E o complemento é exato: corrente (até hoje) + agendado (depois de hoje) = histórico inteiro.
    historico = bank_service.derived_balance(
        db, bank_account_id=conta["id"], until=bank_service.SEM_CORTE
    )
    assert lista[0]["saldo_derivado_cents"] - lista[0]["agendado_saida_cents"] == historico


def test_A_BORDA_do_agendado_o_movimento_de_HOJE_conta_no_SALDO_e_NAO_no_agendado(
    client: TestClient, headers, conta, db: Session
):
    """⚠️ **ACHADO POR MUTAÇÃO (M6), e o buraco era real.**

    Trocar o `>` por `>=` no corte de `_movements_sums(since=...)` deixava **58 testes verdes** — e
    fazia o débito de HOJE contar nos DOIS lugares: dentro do saldo corrente (`posted_at <= hoje`,
    inclusivo) **e** dentro de "Agendado para sair" (`posted_at >= hoje`). O dono veria o mesmo
    dinheiro descontado do saldo *e* anunciado como "ainda vai sair".

    É **a mesma família de defeito do AC6**, pela terceira porta: lá a dobra é na Projeção, entre
    `saldo_inicial` e `_window_sums`; aqui é na tela de Contas & Saldos, entre o saldo e o agendado.
    Nenhum teste pegava, porque todos os cenários usavam data futura — a borda é o único lugar onde
    os dois recortes podem se sobrepor, e era justamente o lugar sem caso.

    **A invariante que este teste fixa:** os dois recortes **particionam** o eixo do tempo em
    `(…, hoje]` e `(hoje, …)` — nenhum movimento nos dois, nenhum fora dos dois.
    """
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje())

    lista = client.get("/bank/accounts", headers=headers).json()
    assert lista[0]["saldo_derivado_cents"] == 10_000_00 - 5_000_00, (
        "o débito de HOJE não entrou no saldo corrente — o corte `until` deixou de ser inclusivo"
    )
    assert lista[0]["agendado_saida_cents"] == 0, (
        "o débito de HOJE apareceu como AGENDADO **e** já estava descontado do saldo: o mesmo "
        "dinheiro contado duas vezes na mesma tela. O corte de `agendado_sums` tem de ser "
        "`> hoje`, "
        "estrito — `>= hoje` faz os dois recortes se sobreporem exatamente no dia de hoje."
    )

    # A partição, dita como soma: corrente (até hoje) + agendado (depois de hoje) = histórico.
    historico = bank_service.derived_balance(
        db, bank_account_id=conta["id"], until=bank_service.SEM_CORTE
    )
    assert lista[0]["saldo_derivado_cents"] - lista[0]["agendado_saida_cents"] == historico


def test_agendado_saida_e_em_MODULO_e_a_conta_sem_futuro_vem_zerada(
    client: TestClient, headers, conta
):
    """`agendado_saida_cents` é **absoluto**, e conta sem movimento futuro vem `0` — nunca ausente,
    nunca `None` ("não sei" seria uma terceira afirmação que este campo não faz)."""
    sozinha = client.get(f"/bank/accounts/{conta['id']}", headers=headers).json()
    assert sozinha["agendado_saida_cents"] == 0
    assert sozinha["agendado_entrada_cents"] == 0

    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=3))
    depois = client.get(f"/bank/accounts/{conta['id']}", headers=headers).json()
    assert depois["agendado_saida_cents"] == 5_000_00, "veio negativo (ou não veio)"


# ── AC2 (transição) — dar baixa numa agendada ────────────────────────────────────────────────


def test_scheduled_para_paid_pela_baixa_nao_duplica_o_movimento(
    client: TestClient, headers, conta, db: Session
):
    """A conta agendada **atravessa** a idempotência de `apply_paid` e re-deriva o estado.

    Cenário real: o dono agendou para o dia 20, o banco antecipou (ou ele pagou na mão antes) e ele
    volta na tela para informar o dia em que o dinheiro saiu de verdade. O movimento **move**, não
    duplica — `sync_origin_movement` é upsert sobre `(source, origin_id)`.
    """
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=20))
    assert _get(client, headers, bill["id"])["status"] == STATUS_SCHEDULED

    resp = _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje())
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == STATUS_PAID
    assert db.query(BankTransaction).count() == 1, "a baixa da agendada DUPLICOU o movimento"
    assert db.scalars(select(BankTransaction)).first().posted_at == _hoje()


def test_paga_continua_idempotente(client: TestClient, headers, conta):
    """A idempotência de `paid` **não** foi afrouxada junto: conta já paga volta inalterada."""
    bill = _bill(client, headers)
    primeira = _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje()).json()
    segunda = _pay(
        client, headers, bill["id"], conta_id=conta["id"],
        paid_on=_hoje() - timedelta(days=1),
    ).json()
    assert segunda["paid_at"] == primeira["paid_at"], "conta paga foi re-datada por um retry"


def test_patch_de_pagamento_move_o_estado_nas_DUAS_direcoes(client: TestClient, headers, conta):
    """`PATCH /bills/{id}/payment` atravessa a fronteira `paid ⇄ scheduled` — e o estado continua
    derivado da data, pela MESMA função (`test_payables_IMPORTA_o_helper...` prova a estrutura)."""
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje())
    assert _get(client, headers, bill["id"])["status"] == STATUS_PAID

    # paid → scheduled (o dono percebeu que na verdade tinha agendado)
    futuro = _hoje() + timedelta(days=10)
    r = client.patch(
        f"/payables/bills/{bill['id']}/payment",
        json={"paid_on": futuro.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == STATUS_SCHEDULED

    # scheduled → paid (antecipou)
    r2 = client.patch(
        f"/payables/bills/{bill['id']}/payment",
        json={"paid_on": _hoje().isoformat()},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == STATUS_PAID


def test_patch_de_pagamento_em_conta_ABERTA_continua_409(client: TestClient, headers, conta):
    """A ampliação foi só para `scheduled`. Conta aberta continua 409 — senão a rota vira um segundo
    caminho de baixa, nascido sem o 409 acionável e sem o piso."""
    bill = _bill(client, headers)
    r = client.patch(
        f"/payables/bills/{bill['id']}/payment",
        json={"paid_on": _hoje().isoformat()},
        headers=headers,
    )
    assert r.status_code == 409, r.text


# ── AC9 — cancelar um agendamento É estornar ─────────────────────────────────────────────────


def test_estornar_conta_agendada_volta_para_open_e_APAGA_o_movimento(
    client: TestClient, headers, conta, db: Session
):
    """**Nenhuma rota nova, nenhum verbo novo** — `reverse` já significa *"esta saída não vai
    acontecer"*, e serve igualmente para uma saída que ainda não aconteceu.

    A conta reaparece na Fila (agendamento cancelado = a conta voltou a ser problema) e o movimento
    futuro some: nada sobra no razão afirmando que aquele dinheiro vai sair.
    """
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=15))
    assert db.query(BankTransaction).count() == 1

    resp = client.post(f"/payables/bills/{bill['id']}/reverse", headers=headers)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == STATUS_OPEN
    assert out["paid_at"] is None
    assert out["bank_account_id"] is None and out["bank_transaction_id"] is None
    assert db.query(BankTransaction).count() == 0, "o movimento futuro sobreviveu ao estorno"

    # E a conta volta a aparecer na Fila, no balde de vencimento dela.
    fila = client.get("/payables/queue", headers=headers).json()
    assert [p["id"] for p in fila["hoje"]] == [bill["id"]]
    assert fila["agendadas"] == []


def test_estornar_conta_ABERTA_continua_409(client: TestClient, headers, conta):
    """A ampliação foi só para `scheduled`: conta em aberto não tem baixa a desfazer."""
    bill = _bill(client, headers)
    assert client.post(
        f"/payables/bills/{bill['id']}/reverse", headers=headers
    ).status_code == 409


# ── AC7/AC8 — a Fila e o resumo ──────────────────────────────────────────────────────────────


def test_a_agendada_sai_dos_baldes_de_vencimento_e_entra_no_proprio(
    client: TestClient, headers, conta
):
    """**Esconder é erro; misturar também.**

    A conta vence HOJE e foi agendada para daqui a 15 dias. Ela some do balde "hoje" (a pergunta da
    Fila é *"o que preciso pagar?"*, e ela já foi resolvida) e aparece em "agendadas".
    """
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=15))

    fila = client.get("/payables/queue", headers=headers).json()
    assert fila["hoje"] == [] and fila["atrasados"] == []
    assert fila["proximos_7_dias"] == [] and fila["proximos_30_dias"] == []
    assert [p["id"] for p in fila["agendadas"]] == [bill["id"]]
    assert fila["summary"]["agendadas_count"] == 1
    assert fila["summary"]["agendadas_cents"] == 5_000_00
    assert fila["summary"]["hoje_cents"] == 0


def test_agendadas_ordenam_pela_data_do_DEBITO_nao_pelo_vencimento(
    client: TestClient, headers, conta
):
    """A pergunta do balde é *quando o dinheiro sai* — e numa agendada as duas datas divergem por
    construção. A conta que vence DEPOIS foi agendada para ANTES, e é ela que vem primeiro."""
    vence_antes = _bill(client, headers, description="Vence antes", due_date=_hoje().isoformat())
    vence_depois = _bill(
        client, headers, description="Vence depois",
        due_date=(_hoje() + timedelta(days=20)).isoformat(),
    )
    _pay(client, headers, vence_antes["id"], conta_id=conta["id"],
         paid_on=_hoje() + timedelta(days=25))
    _pay(client, headers, vence_depois["id"], conta_id=conta["id"],
         paid_on=_hoje() + timedelta(days=5))

    fila = client.get("/payables/queue", headers=headers).json()
    assert [p["description"] for p in fila["agendadas"]] == ["Vence depois", "Vence antes"], (
        "o balde ordenou por `due_date` — a pergunta dele é a data do DÉBITO"
    )


def test_agendada_para_alem_de_30_dias_continua_visivel(client: TestClient, headers, conta):
    """Os baldes de vencimento cortam em 30 dias ("não é próximo"). O balde das agendadas **não**:
    um compromisso assumido para daqui a 60 dias continua sendo um compromisso."""
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=60))
    fila = client.get("/payables/queue", headers=headers).json()
    assert len(fila["agendadas"]) == 1


def test_summary_ganha_scheduled_cents_sem_contaminar_os_cinco_antigos(
    client: TestClient, headers, conta
):
    """**AC8 — snapshot dos 5 campos antigos, antes e depois de agendar.**

    `open_cents`, `overdue_cents`, `week_cents` e `paid_month_cents` **não** enxergam a agendada.
    `month_cents` enxerga — e isso é **preservado de propósito**: ele já filtrava
    `status != canceled` e é o total do mês por VENCIMENTO, não por caixa. A conta continua
    vencendo neste mês independentemente de quando o débito foi agendado.
    """
    bill = _bill(client, headers)
    antes = client.get("/payables/summary", headers=headers).json()
    assert antes["scheduled_cents"] == 0

    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=15))
    depois = client.get("/payables/summary", headers=headers).json()

    assert depois["scheduled_cents"] == 5_000_00
    assert depois["open_cents"] == 0, "agendada entrou em `open_cents` — ela não é 'a pagar'"
    assert depois["overdue_cents"] == 0
    assert depois["week_cents"] == 0
    assert depois["paid_month_cents"] == 0, "agendada entrou em `paid_month_cents` — não saiu ainda"
    assert depois["month_cents"] == antes["month_cents"], (
        "`month_cents` MUDOU de definição. Ele é o total do mês por vencimento e já filtrava "
        "`status != canceled` — a agendada continua contando ali, de propósito (AC8)."
    )


def test_snapshot_dos_cinco_campos_antigos_sem_agendamento_nenhum(client: TestClient, headers):
    """O contrato dos campos antigos num cenário **sem** agendamento: idêntico ao de antes da story
    (é o que a IV2 pede). `scheduled_cents` nasce `0`, nunca `None`."""
    _bill(client, headers, amount_cents=300_00, due_date=_hoje().isoformat())
    s = client.get("/payables/summary", headers=headers).json()
    assert s == {
        "open_cents": 300_00,
        "overdue_cents": 0,
        "week_cents": 300_00,
        "month_cents": 300_00,
        "paid_month_cents": 0,
        "scheduled_cents": 0,
    }


# ── AC14 — o que NÃO mudou ───────────────────────────────────────────────────────────────────


def test_agendada_nao_e_atrasada(client: TestClient, headers, conta):
    """`is_overdue` já exigia `STATUS_OPEN` — custo **zero**, verificado e não presumido.

    A conta vence hoje-30 (vencidíssima) e foi agendada: deixa de ser atrasada no instante em que
    ganha dia marcado, que é a leitura certa — o problema foi resolvido.
    """
    bill = _bill(client, headers, due_date=(_hoje() - timedelta(days=30)).isoformat())
    assert _get(client, headers, bill["id"])["is_overdue"] is True

    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=5))
    out = _get(client, headers, bill["id"])
    assert out["status"] == STATUS_SCHEDULED
    assert out["is_overdue"] is False
    assert payables_service.is_overdue(
        Payable(status=STATUS_SCHEDULED, due_date=_hoje() - timedelta(days=99)), _hoje()
    ) is False


# ── AC11 — a bandeja de comprovantes ─────────────────────────────────────────────────────────


def test_a_agendada_aparece_nos_candidatos_do_comprovante(
    client: TestClient, headers, conta, db: Session
):
    """*"O comprovante do agendamento existe e é o que o dono tem na mão."*

    O app do banco emite o comprovante do agendamento na hora. Sem este AC, o dono teria de esperar
    o dia do débito para anexar um arquivo que ele já tem — e, na prática, nunca anexaria.
    """
    agendada = _bill(client, headers, description="Agendada")
    paga = _bill(client, headers, description="Paga")
    _bill(client, headers, description="Aberta")
    cancelada = _bill(client, headers, description="Cancelada")

    _pay(client, headers, agendada["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=9))
    _pay(client, headers, paga["id"], conta_id=conta["id"], paid_on=_hoje())
    client.post(f"/payables/bills/{cancelada['id']}/cancel", headers=headers)

    nomes = {p.description for p in receipts_service.list_candidates(db)}
    assert "Agendada" in nomes
    assert {"Paga", "Aberta"} <= nomes
    assert "Cancelada" not in nomes, "conta cancelada nunca entra na bandeja"


def test_vincular_comprovante_a_uma_agendada_funciona(client: TestClient, headers, conta):
    """O caminho inteiro pelo celular: sobe o comprovante, escolhe a conta agendada, vincula."""
    bill = _bill(client, headers)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=_hoje() + timedelta(days=9))
    rid = client.post(
        "/payables/receipts",
        files={"file": ("comprovante.png", PNG, "image/png")},
        headers=headers,
    ).json()["id"]

    resp = client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": bill["id"], "mark_paid": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == STATUS_SCHEDULED, "vincular o comprovante mexeu no estado"


# ── AC10 — a promoção, e a prova de que o saldo NÃO depende dela ─────────────────────────────


def test_promote_scheduled_promove_so_o_que_venceu(
    client: TestClient, headers, conta, tenant_id, db: Session
):
    hoje = _hoje()
    ontem_bill = _bill(client, headers, description="débito de ontem")
    hoje_bill = _bill(client, headers, description="débito de hoje")
    amanha_bill = _bill(client, headers, description="débito de amanhã")

    # As três nascem `scheduled` porque a promoção é medida com `today` INJETADO três dias antes.
    _pay(client, headers, ontem_bill["id"], conta_id=conta["id"], paid_on=hoje + timedelta(days=1))
    _pay(client, headers, hoje_bill["id"], conta_id=conta["id"], paid_on=hoje + timedelta(days=2))
    _pay(client, headers, amanha_bill["id"], conta_id=conta["id"], paid_on=hoje + timedelta(days=3))

    # "Hoje" para a varredura = D+2: o de D+1 e o de D+2 venceram; o de D+3 não.
    promovidas = payables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="system:worker", today=hoje + timedelta(days=2)
    )
    assert promovidas == 2
    assert _get(client, headers, ontem_bill["id"])["status"] == STATUS_PAID
    assert _get(client, headers, hoje_bill["id"])["status"] == STATUS_PAID, (
        "a borda: `paid_at::date <= hoje` é INCLUSIVA — o débito DE HOJE já aconteceu"
    )
    assert _get(client, headers, amanha_bill["id"])["status"] == STATUS_SCHEDULED


def test_promote_scheduled_e_idempotente_e_nao_re_data(
    client: TestClient, headers, conta, tenant_id, db: Session
):
    """Rodar duas vezes promove zero na segunda; `paid_at` **não** é re-datado.

    Re-datar seria sobrescrever a data de caixa que o usuário informou por "hoje" — inventar o fato
    de caixa (Artigo IV) e, de quebra, mover o movimento bancário por baixo do saldo.
    """
    bill = _bill(client, headers)
    debito = _hoje() + timedelta(days=2)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=debito)

    depois = debito + timedelta(days=5)
    assert payables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="system:worker", today=depois
    ) == 1
    assert payables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="system:worker", today=depois
    ) == 0, "a segunda varredura promoveu de novo — não é idempotente"

    out = _get(client, headers, bill["id"])
    assert out["status"] == STATUS_PAID
    assert out["paid_at"].startswith(debito.isoformat()), "`paid_at` foi RE-DATADO pela promoção"
    assert out["bank_account_id"] == conta["id"], "a promoção mexeu no vínculo bancário"


def test_promote_scheduled_nao_toca_o_movimento_bancario(
    client: TestClient, headers, conta, tenant_id, db: Session
):
    bill = _bill(client, headers)
    debito = _hoje() + timedelta(days=2)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=debito)
    antes = db.scalars(select(BankTransaction)).one()
    snapshot = (antes.id, antes.posted_at, antes.amount_cents, antes.bank_account_id, antes.status)

    payables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="system:worker", today=debito + timedelta(days=1)
    )
    depois = db.scalars(select(BankTransaction)).one()
    assert (
        depois.id, depois.posted_at, depois.amount_cents, depois.bank_account_id, depois.status
    ) == snapshot


def test_O_SALDO_DERIVADO_NAO_DEPENDE_DO_WORKER(
    client: TestClient, headers, conta, db: Session
):
    """⚠️ **A prova do F-D11 — o teste mais importante do AC10.**

    Com o worker **desligado** (nunca chamado neste teste), o saldo derivado do dia do débito já
    contempla o movimento. O movimento nasceu com `posted_at` = a data agendada e o saldo é
    **função da data**: ele entra sozinho quando o dia chega.

    Se este teste um dia depender de `promote_scheduled` para passar, alguém transformou uma
    cosmética de status em componente crítico — e o saldo do dono passou a depender de um processo
    em background estar de pé.
    """
    bill = _bill(client, headers)
    dia_do_debito = _hoje() + timedelta(days=15)
    _pay(client, headers, bill["id"], conta_id=conta["id"], paid_on=dia_do_debito)

    # Hoje: o dinheiro ainda está lá.
    assert bank_service.derived_balance(db, bank_account_id=conta["id"]) == 10_000_00
    # No dia do débito (e sem worker nenhum): já saiu.
    assert bank_service.derived_balance(
        db, bank_account_id=conta["id"], until=dia_do_debito
    ) == 10_000_00 - 5_000_00
    # ...e o status continua `scheduled`, porque ninguém rodou a varredura. Os dois fatos convivem:
    # o saldo é função da data; o status é rótulo.
    assert _get(client, headers, bill["id"])["status"] == STATUS_SCHEDULED
