"""Testes da **conferência bloco 1** (Story 8.5) — a divergência em uma frase, **por conta**.

Esta é a story que produz o número que justifica o Epic 8, e o número dela é o **gate de decisão**
sobre investir ou não nas Ondas 3 e 4. Um relatório que erra aqui não quebra: ele **mente**, e leva
a decisão de produto junto. Por isso a suíte é desenhada em torno dos modos de falha silenciosos:

- **AC4/AC4b — a comparação na MESMA data.**
  `test_movimento_posterior_a_referencia_nao_muda_a_divergencia` é **divergente por construção**: o
  cenário dá resultados diferentes se o código comparar em `end` em vez de na `reference_date` do
  checkpoint (mesmo estilo do `test_uses_due_date_not_competence_date` da 5.7). E
  `test_conferencia_nao_usa_derived_balances_as_of` é a varredura estática que impede a função em
  lote (uma data comum para todas as contas) de voltar por manutenção.
- **AC6 — o silêncio dentro da banda.** R$ 3,50 num saldo de R$ 25.000 é **verde e mudo**; e a borda
  `|divergência| == tolerância` é **dentro** (teste obrigatório, nos dois regimes da banda: piso e
  percentual).
- **AC3 — `None` não é zero.** Sem checkpoint na janela o relatório **diz que não sabe**; nenhum
  número de divergência é produzido, e a conta não entra em `contas_fora_da_banda`.
- **AC7 — o consolidado nunca vem sozinho.** O cenário do epic §3.2 (+R$ 1.200 / −R$ 900 / +R$ 40)
  soma +R$ 340 *e* devolve as três contas, com **duas** nomeadas fora da banda.
- **IV1/IV2/IV3/IV5** — read-only de verdade, DRE intacta, procedência em todo campo de saldo, zero
  IA e zero rede.

RLS/isolamento cross-tenant NÃO é exercido aqui (SQLite — ver `conftest.py`): "a conta é de outro
tenant" é afirmação que só o Postgres real prova, e ela vive em
`tests/test_bank_reconciliation_report_rls.py` (`rls_e2e`).
"""
from __future__ import annotations

import ast
import pathlib
import re
from dataclasses import asdict
from datetime import UTC, date, datetime, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO, ORIGEM_INDISPONIVEL, ORIGENS
from app.modules.bank import reconciliation
from app.modules.bank import service as bank_service
from app.modules.bank.models import (
    KIND_CHECKING,
    KIND_INVESTMENT,
    KIND_SAVINGS,
    ORIGIN_MANUAL,
    ORIGIN_OFX,
    BankAccount,
    BankBalanceCheckpoint,
    BankTransaction,
)
from app.modules.financial_intelligence import dre as dre_service
from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge
from app.modules.wallet.models import Transaction

REGISTER = {
    "legal_name": "Conferência ME",
    "document": "11444777000161",
    "slug": "conferencia",
    "email": "conferencia@example.com",
    "name": "Cora",
    "password": "uma-senha-bem-grande",
}

# Toda data de dado é do PASSADO real: as guardas de "data futura" de movimento e de checkpoint
# ancoram em `datetime.now(UTC).date()`. `END` é só a janela do relatório (não tem essa guarda),
# mas fica no passado também para que `min(end, today)` seja determinístico nos testes de rota,
# onde `today` não é injetável.
OPENING = date(2026, 7, 1)
START = date(2026, 7, 1)
END = date(2026, 7, 25)
TODAY = date(2026, 7, 28)
# A data de referência padrão dos checkpoints da suíte (dentro de [START, END] e no passado).
REF = date(2026, 7, 20)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _account(
    client: TestClient,
    headers,
    *,
    name: str = "Itaú PJ",
    opening: int = 1_000_000,
    opening_date: date = OPENING,
    kind: str = KIND_CHECKING,
    number: str = "",
) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": kind,
            "number": number,
            "opening_balance_cents": opening,
            "opening_date": opening_date.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _declarar(
    client: TestClient,
    headers,
    account_id: str,
    *,
    balance_cents: int,
    reference_date: date = REF,
) -> dict:
    resp = client.post(
        f"/bank/accounts/{account_id}/checkpoints",
        json={
            "reference_date": reference_date.isoformat(),
            "balance_cents": balance_cents,
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _lancar(
    client: TestClient,
    headers,
    account_id: str,
    *,
    amount_cents: int,
    posted_at: date,
    description: str = "movimento",
) -> dict:
    resp = client.post(
        f"/bank/accounts/{account_id}/transactions",
        json={
            "posted_at": posted_at.isoformat(),
            "amount_cents": amount_cents,
            "description": description,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _report(
    db: Session,
    *,
    start: date = START,
    end: date = END,
    bank_account_id: str | None = None,
    today: date = TODAY,
) -> reconciliation.ConferenciaReport:
    return reconciliation.reconciliation_report(
        db, start=start, end=end, bank_account_id=bank_account_id, today=today
    )


def _so_conta(report: reconciliation.ConferenciaReport) -> reconciliation.ConferenciaConta:
    """O relatório de UMA conta. Falha alto se houver mais de uma — não silencia com `[0]`."""
    assert len(report.contas) == 1, f"esperava 1 conta, veio {len(report.contas)}"
    return report.contas[0]


# ── AC6 — a banda de tolerância, como função pura ────────────────────────────────────────────


def test_tolerance_cents_e_pura_e_devolve_inteiro():
    """`max(R$ 50; 0,5%)`, sobre o valor ABSOLUTO, sempre em centavos inteiros."""
    assert reconciliation.TOLERANCE_FLOOR_CENTS == 5_000
    assert reconciliation.TOLERANCE_PCT == 0.005

    # Piso domina em conta pequena; percentual domina em conta grande.
    assert reconciliation.tolerance_cents(0) == 5_000
    assert reconciliation.tolerance_cents(100_000) == 5_000
    assert reconciliation.tolerance_cents(1_000_000) == 5_000, "o ponto exato de cruzamento"
    assert reconciliation.tolerance_cents(10_000_000) == 50_000
    # Saldo NEGATIVO (conta no limite) tem direito à mesma banda proporcional.
    assert reconciliation.tolerance_cents(-10_000_000) == 50_000

    # Dinheiro nunca sai float do cálculo.
    assert isinstance(reconciliation.tolerance_cents(2_500_000), int)

    # A "costura" da configurabilidade: os dois parâmetros são nomeados e a fórmula é uma só.
    assert reconciliation.tolerance_cents(1_000_000, floor_cents=0, pct=0.01) == 10_000
    assert reconciliation.tolerance_cents(1_000_000, floor_cents=99_999, pct=0.0) == 99_999


# ── AC2/AC4/AC5 — o caminho avaliável ────────────────────────────────────────────────────────


def test_conta_batendo_exato_fica_dentro_da_banda_e_em_silencio(
    client: TestClient, headers, db: Session
):
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)

    c = _so_conta(_report(db))
    assert c.bank_account_id == conta["id"]
    assert c.bank_account_name == "Itaú PJ"
    assert c.bank_account_kind == KIND_CHECKING
    assert c.saldo_banco_cents == 1_000_000
    assert c.saldo_sistema_cents == 1_000_000
    assert c.saldo_banco_data == date(2026, 7, 20)
    assert c.divergencia_cents == 0
    assert c.dentro_da_tolerancia is True
    assert c.notes == [], "bateu exato e o relatório ainda assim disse alguma coisa"

    # Eixo A dos dois lados: é por serem o MESMO plano que compará-los é legítimo.
    assert c.saldo_banco_origem == ORIGEM_BANCO
    assert c.saldo_sistema_origem == ORIGEM_BANCO
    # Eixo B: o valor CRU do checkpoint, sem tradução para o eixo A.
    assert c.saldo_banco_fonte == ORIGIN_MANUAL


def test_divergencia_negativa_acima_da_banda_e_o_achado_de_maior_valor(
    client: TestClient, headers, db: Session
):
    """REQ-14: o banco ABAIXO do sistema = provável **saída** não lançada (conta a pagar esquecida).

    É o achado que o épico existe para produzir: receber já tem três testemunhas independentes
    (gateway, webhook, split na Carteira); pagar não tem nenhuma.
    """
    conta = _account(client, headers, opening=1_000_000)
    # O banco tem R$ 3.000 a MENOS do que o e1p calculou.
    _declarar(client, headers, conta["id"], balance_cents=700_000)

    report = _report(db)
    c = _so_conta(report)
    assert c.divergencia_cents == -300_000, "sinal invertido: banco − sistema, nunca o contrário"
    assert c.dentro_da_tolerancia is False
    assert c.tolerancia_cents == 5_000

    assert report.total_divergencia_cents == -300_000
    assert report.contas_avaliadas == 1
    assert report.contas_sem_checkpoint == 0
    assert [f.bank_account_id for f in report.contas_fora_da_banda] == [conta["id"]]
    assert report.contas_fora_da_banda[0].bank_account_name == "Itaú PJ"
    assert report.contas_fora_da_banda[0].divergencia_cents == -300_000
    assert report.contas_fora_da_banda[0].tolerancia_cents == 5_000
    assert report.notes == [], "nenhuma conta ficou sem checkpoint — o total cobre tudo"


def test_divergencia_positiva_acima_da_banda(client: TestClient, headers, db: Session):
    """Banco ACIMA do sistema = provável **entrada** não lançada."""
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_250_000)

    c = _so_conta(_report(db))
    assert c.divergencia_cents == 250_000
    assert c.dentro_da_tolerancia is False


def test_tres_e_cinquenta_em_vinte_e_cinco_mil_e_silencio(
    client: TestClient, headers, db: Session
):
    """**O teste que protege a confiança no sinal** (AC6).

    *"O e1p não é ferramenta contábil; não precisa fechar em zero, e alertar sobre R$ 3,50 num mês
    de R$ 25.000 treina o usuário a ignorar o alerta."* Uma tela que grita por R$ 3 destrói a única
    coisa que o produto está vendendo.
    """
    conta = _account(client, headers, opening=2_499_650)
    _declarar(client, headers, conta["id"], balance_cents=2_500_000)

    report = _report(db)
    c = _so_conta(report)
    assert c.divergencia_cents == 350
    assert c.tolerancia_cents == 12_500, "0,5% de R$ 25.000"
    assert c.dentro_da_tolerancia is True
    assert c.notes == [], "R$ 3,50 gerou um alerta — é assim que o usuário aprende a ignorar a tela"
    assert report.contas_fora_da_banda == []
    # O número CONTINUA exposto: suprime-se a afirmação, nunca o número.
    assert report.total_divergencia_cents == 350


def test_borda_divergencia_exatamente_igual_a_banda_e_DENTRO_no_regime_do_piso(
    client: TestClient, headers, db: Session
):
    """`abs(divergência) == tolerância` → **dentro** (silêncio). Aqui a banda é o piso de R$ 50.

    A borda precisa de teste nos dois lugares que a avaliam (aqui e no motor da 8.6, design §5.3)
    justamente porque `<=` vira `<` numa manutenção distraída sem nada quebrar visivelmente.
    """
    conta = _account(client, headers, opening=100_000)
    _declarar(client, headers, conta["id"], balance_cents=105_000)

    c = _so_conta(_report(db))
    assert c.tolerancia_cents == 5_000, "piso (R$ 50) domina: 0,5% de R$ 1.050 são R$ 5,25"
    assert c.divergencia_cents == 5_000
    assert c.dentro_da_tolerancia is True, "a borda `==` é DENTRO da banda"
    assert c.notes == []


def test_borda_divergencia_exatamente_igual_a_banda_e_DENTRO_no_regime_do_percentual(
    client: TestClient, headers, db: Session
):
    """A mesma borda, com a banda dominada pelo percentual — e um centavo além dela, fora."""
    na_borda = _account(client, headers, name="Na borda", opening=3_980_000, number="1111-1")
    _declarar(client, headers, na_borda["id"], balance_cents=4_000_000)

    um_centavo_alem = _account(
        client, headers, name="Um centavo além", opening=3_979_999, number="2222-2"
    )
    _declarar(
        client, headers, um_centavo_alem["id"], balance_cents=4_000_000
    )

    por_id = {c.bank_account_id: c for c in _report(db).contas}

    borda = por_id[na_borda["id"]]
    assert borda.tolerancia_cents == 20_000, "0,5% de R$ 40.000"
    assert borda.divergencia_cents == 20_000
    assert borda.dentro_da_tolerancia is True

    alem = por_id[um_centavo_alem["id"]]
    assert alem.tolerancia_cents == 20_000
    assert alem.divergencia_cents == 20_001
    assert alem.dentro_da_tolerancia is False, "um centavo acima da banda já é fora"


def test_banda_dominada_pelo_piso_e_pelo_percentual_em_contas_diferentes(
    client: TestClient, headers, db: Session
):
    """A "Caixinha" de R$ 300 e a corrente de R$ 100.000 no mesmo relatório, cada uma com sua banda.

    É por o componente percentual adaptar a banda ao tamanho da conta que uma banda ÚNICA por tenant
    serve para as duas (design §5.1.1) — e é por isso que "banda por conta" foi rejeitada agora.
    """
    caixinha = _account(client, headers, name="Caixinha", opening=30_000, number="1111-1")
    _declarar(client, headers, caixinha["id"], balance_cents=30_000)

    corrente = _account(client, headers, name="Corrente", opening=10_000_000, number="2222-2")
    _declarar(
        client, headers, corrente["id"], balance_cents=10_000_000, reference_date=date(2026, 7, 20)
    )

    por_id = {c.bank_account_id: c for c in _report(db).contas}
    assert por_id[caixinha["id"]].tolerancia_cents == 5_000, "piso: 0,5% de R$ 300 são R$ 1,50"
    assert por_id[corrente["id"]].tolerancia_cents == 50_000, "percentual: 0,5% de R$ 100.000"


# ── AC4 — o teste divergente por construção ──────────────────────────────────────────────────


def test_movimento_posterior_a_referencia_nao_muda_a_divergencia(
    client: TestClient, headers, db: Session
):
    """**O teste mais valioso da story.** A comparação é na data do CHECKPOINT, não em `end`.

    Cenário desenhado para dar resultado DIFERENTE se o código comparasse em `end`:
      - saldo de abertura R$ 10.000 em 01/07;
      - +R$ 500 em 10/07  → saldo derivado em 15/07 = R$ 10.500;
      - checkpoint de 15/07 = R$ 10.500 → divergência **zero**;
      - −R$ 3.000 em 20/07 → saldo derivado em 25/07 (o `end`) = R$ 7.500.

    Comparar o saldo do banco de 15/07 com o saldo do sistema de 25/07 acusaria +R$ 3.000 de
    divergência — um furo inexistente, inventado pelo próprio relatório. Se este teste falhar com
    `divergencia_cents == 300_000`, é exatamente esse bug.
    """
    conta = _account(client, headers, opening=1_000_000)
    _lancar(client, headers, conta["id"], amount_cents=50_000, posted_at=date(2026, 7, 10))
    _declarar(
        client, headers, conta["id"], balance_cents=1_050_000, reference_date=date(2026, 7, 15)
    )
    _lancar(client, headers, conta["id"], amount_cents=-300_000, posted_at=date(2026, 7, 20))

    c = _so_conta(_report(db))
    assert c.saldo_banco_data == date(2026, 7, 15)
    assert c.saldo_sistema_cents == 1_050_000, (
        "o saldo do sistema não foi apurado na data do checkpoint — se veio 750_000, o código "
        "comparou em `end` e o relatório está inventando um furo de R$ 3.000"
    )
    assert c.divergencia_cents == 0
    assert c.dentro_da_tolerancia is True


def test_cada_conta_usa_a_SUA_data_de_referencia(client: TestClient, headers, db: Session):
    """AC4b em runtime: duas contas, dois checkpoints em dias diferentes, duas datas de apuração.

    Uma data comum (o que `derived_balances_as_of` faria) daria o saldo do sistema de uma conta
    numa data que não é a do checkpoint dela — e o furo apareceria só numa das duas.
    """
    cedo = _account(client, headers, name="Cedo", opening=1_000_000, number="1111-1")
    _lancar(client, headers, cedo["id"], amount_cents=-200_000, posted_at=date(2026, 7, 18))
    _declarar(
        client, headers, cedo["id"], balance_cents=1_000_000, reference_date=date(2026, 7, 10)
    )

    tarde = _account(client, headers, name="Tarde", opening=1_000_000, number="2222-2")
    _lancar(client, headers, tarde["id"], amount_cents=-200_000, posted_at=date(2026, 7, 18))
    _declarar(client, headers, tarde["id"], balance_cents=800_000)

    por_id = {c.bank_account_id: c for c in _report(db).contas}
    assert por_id[cedo["id"]].saldo_banco_data == date(2026, 7, 10)
    assert por_id[cedo["id"]].saldo_sistema_cents == 1_000_000, "o −R$ 2.000 é de DEPOIS de 10/07"
    assert por_id[cedo["id"]].divergencia_cents == 0

    assert por_id[tarde["id"]].saldo_banco_data == date(2026, 7, 20)
    assert por_id[tarde["id"]].saldo_sistema_cents == 800_000, "o −R$ 2.000 é de ANTES de 20/07"
    assert por_id[tarde["id"]].divergencia_cents == 0


def test_o_checkpoint_usado_e_o_MAIS_RECENTE_da_janela(client: TestClient, headers, db: Session):
    conta = _account(client, headers, opening=1_000_000)
    for dia, valor in ((5, 900_000), (12, 1_000_000), (22, 1_000_000)):
        _declarar(
            client, headers, conta["id"], balance_cents=valor, reference_date=date(2026, 7, dia)
        )

    assert _so_conta(_report(db, end=date(2026, 7, 25))).saldo_banco_data == date(2026, 7, 22)
    assert _so_conta(_report(db, end=date(2026, 7, 15))).saldo_banco_data == date(2026, 7, 12)
    # E o teto é INCLUSIVO, como `derived_balance(until=...)` — as duas janelas coincidem.
    assert _so_conta(_report(db, end=date(2026, 7, 12))).saldo_banco_data == date(2026, 7, 12)


# ── AC3 — sem checkpoint na janela, o relatório DIZ que não sabe ─────────────────────────────


def _assert_indisponivel(c: reconciliation.ConferenciaConta) -> None:
    assert c.saldo_banco_cents is None
    assert c.saldo_banco_origem == ORIGEM_INDISPONIVEL
    assert c.saldo_banco_fonte is None, "não houve porta de entrada — o eixo B não se aplica"
    assert c.saldo_banco_data is None
    assert c.saldo_sistema_cents is None
    assert c.saldo_sistema_origem == ORIGEM_BANCO, (
        "a procedência do saldo derivado não muda por não haver checkpoint — o que falta é o VALOR"
    )
    assert c.divergencia_cents is None, (
        "produziu um número de divergência sem verdade externa para comparar. `None` significa NÃO "
        "AVALIÁVEL; um `0` aqui afirmaria 'conferi e está batendo', e comparar contra zero "
        "inventaria uma divergência do tamanho do saldo inteiro"
    )
    assert c.dentro_da_tolerancia is None
    assert c.tolerancia_cents == 0
    assert c.notes, "o relatório precisa DIZER que não sabe, não apenas devolver campos nulos"


def test_conta_sem_checkpoint_nenhum_e_indisponivel(client: TestClient, headers, db: Session):
    conta = _account(client, headers, opening=1_000_000)
    _lancar(client, headers, conta["id"], amount_cents=-500_000, posted_at=date(2026, 7, 10))

    report = _report(db)
    c = _so_conta(report)
    _assert_indisponivel(c)
    # Story 8.19 — o bloco 4 cai para a DATA DE ABERTURA quando não há checkpoint nenhum. Antes
    # disto era `None`, e a tela traduzia `None` por "esta conta nunca teve saldo informado" — falso
    # para uma conta cujo saldo de partida o dono informou no cadastro. `min(END, TODAY)` manda o
    # END (25/07) → 25/07 − 01/07 = 24 dias. O bloco 1 acima segue INTACTO (`_assert_indisponivel`).
    assert c.dias_desde_ultima_conferencia == (min(END, TODAY) - OPENING).days == 24

    assert report.total_divergencia_cents is None, (
        "somou zero contas e devolveu 0 — um total de zero afirma que está tudo batendo justamente "
        "onde nada foi conferido"
    )
    assert report.contas_avaliadas == 0
    assert report.contas_sem_checkpoint == 1
    assert report.contas_fora_da_banda == [], (
        "uma conta NÃO AVALIÁVEL entrou na lista de fora-da-banda — é o bug do `not None is True`"
    )
    assert report.notes, "o total é parcial e o relatório não avisou"


def test_checkpoint_fora_da_janela_segue_indisponivel_mas_conta_os_dias(
    client: TestClient, headers, db: Session
):
    """O caso que separa o bloco 1 do bloco 4 (AC2 × AC8), e que justifica os dois critérios.

    Checkpoint de 20/06, relatório de 01/07 a 25/07: ele **não serve** para comparar (é de outro
    período), mas serve — e é o único que serve — para a frase honesta *"saldo não confirmado há
    35 dias"*. Fundir os dois critérios num só quebra exatamente um dos dois lados.
    """
    conta = _account(
        client, headers, opening=1_000_000, opening_date=date(2026, 6, 1)
    )
    _declarar(client, headers, conta["id"], balance_cents=999_999, reference_date=date(2026, 6, 20))

    c = _so_conta(_report(db))
    _assert_indisponivel(c)
    assert c.dias_desde_ultima_conferencia == 35, (
        "o bloco 4 perdeu o checkpoint antigo — sem ele o relatório não consegue dizer há quanto "
        "tempo o saldo não é confirmado, que é a frase honesta que ele existe para produzir"
    )


def test_dias_desde_ultima_conferencia_usa_min_entre_end_e_today(
    client: TestClient, headers, db: Session
):
    """Relatório de período passado não diz "há 200 dias" quando, no fim daquele período, fazia 5.

    E o contador é `0` no dia da declaração (`0` = "confirmado hoje" ≠ `None` = "nunca").
    """
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)

    # `end` (25/07) < `today` (28/07) → manda o `end`.
    assert _so_conta(_report(db)).dias_desde_ultima_conferencia == 5
    # `today` (22/07) < `end` (25/07) → manda o `today`.
    assert _so_conta(_report(db, today=date(2026, 7, 22))).dias_desde_ultima_conferencia == 2
    # No próprio dia: zero, e zero não é `None`.
    assert (
        _so_conta(
            _report(db, end=date(2026, 7, 20), today=date(2026, 7, 20))
        ).dias_desde_ultima_conferencia
        == 0
    )


def test_checkpoint_na_borda_do_start_serve(client: TestClient, headers, db: Session):
    """`reference_date == start` está DENTRO da janela (as duas pontas são inclusivas).

    ⚠️ A conta é aberta em 01/06, e **não** no `OPENING` default (01/07) — porque `START` também é
    01/07. Com a data de abertura no default, este cenário cairia por acidente na **comparação
    degenerada** da Story 8.20 (`reference_date == opening_date`, não avaliável) e o teste passaria
    a medir aquilo, e não a borda da janela que ele existe para medir. Não "simplifique" a data de
    volta: o afastamento é o que mantém as duas asserções abaixo falando da janela.
    """
    conta = _account(client, headers, opening=1_000_000, opening_date=date(2026, 6, 1))
    _declarar(client, headers, conta["id"], balance_cents=1_000_000, reference_date=START)

    c = _so_conta(_report(db))
    assert c.saldo_banco_data == START
    assert c.divergencia_cents == 0


# ── Story 8.19 — o saldo de ABERTURA é uma declaração: o bloco 4 conta a partir dele ─────────
#
# `opening_balance_cents` e `opening_date` são `NOT NULL`: **toda** conta nasce com um saldo de
# partida informado pelo dono, e `service._validate_opening_date` descreve a data como "o dia em que
# você conferiu o saldo no app do banco". Devolver `None` no bloco 4 fazia a tela dizer *"Esta conta
# nunca teve saldo informado."* a quem informou o saldo no cadastro — mandando o dono repetir um ato
# que ele já fez.
#
# ⚠️ **O que esta story NÃO faz: tocar o bloco 1.** Nenhum saldo de abertura é comparado com coisa
# alguma — ele entra só como DATA, no contador de dias. Sem checkpoint na janela, a
# `divergencia_cents` continua `None`, `derived_balance` continua não sendo chamada, e o 🟢 continua
# impossível. É exatamente por isso que ela não reabre a Story 8.20: o defeito de lá era a
# COMPARAÇÃO degenerada, e aqui não há comparação nenhuma. O teste do 🟢 (o modo de falha caro desta
# story) vive em `test_financial_intelligence_diagnostics_completude.py`, onde o motor está ligado.


def test_sem_checkpoint_o_bloco_4_conta_a_partir_da_data_de_abertura(
    client: TestClient, headers, db: Session
):
    """A conta recém-cadastrada, no dia do cadastro: **0 dias**, e `0` não é `None`.

    É o cenário do tenant do fundador — conta criada hoje, saldo de partida informado, zero
    checkpoint. O relatório continua **não avaliável** no bloco 1 (é a mesma conta que
    `_assert_indisponivel` descreve), mas para de afirmar que a conta nunca teve saldo informado.
    """
    _account(client, headers, opening=1_000_000, opening_date=OPENING)

    c = _so_conta(_report(db, start=OPENING, end=OPENING, today=OPENING))
    assert c.dias_desde_ultima_conferencia == 0, (
        "dia do cadastro: o saldo de partida foi informado HOJE — `0` é 'informado hoje' e `None` "
        "seria 'nunca informado', que é falso"
    )
    assert c.dias_desde_ultima_conferencia is not None
    # E o bloco 1 não se moveu por causa disso: sem checkpoint, nada é comparado.
    _assert_indisponivel(c)


def test_sem_checkpoint_o_bloco_4_usa_min_entre_end_e_today_e_a_guarda_do_zero(
    client: TestClient, headers, db: Session
):
    """As DUAS guardas do contador valem igual no ramo novo — elas não são do ramo do checkpoint.

    `min(end, today)`: um relatório de período passado não diz "há 200 dias" quando, no fim daquele
    período, fazia 24. `max(0, …)`: um relatório de um período **anterior** à abertura da conta não
    devolve dias negativos — o não-membro do conjunto, e a borda que some se alguém "simplificar" o
    `max`.
    """
    _account(client, headers, opening=1_000_000, opening_date=OPENING)

    # `end` (25/07) < `today` (28/07) → manda o `end`: 25/07 − 01/07 = 24.
    assert _so_conta(_report(db)).dias_desde_ultima_conferencia == 24
    # `today` (05/07) < `end` (25/07) → manda o `today`: 05/07 − 01/07 = 4.
    assert _so_conta(_report(db, today=date(2026, 7, 5))).dias_desde_ultima_conferencia == 4
    # Período INTEIRAMENTE anterior à abertura → `max(0, negativo)` = 0, nunca um número negativo.
    assert (
        _so_conta(
            _report(db, start=date(2026, 6, 1), end=date(2026, 6, 30), today=date(2026, 6, 30))
        ).dias_desde_ultima_conferencia
        == 0
    )


def test_sem_checkpoint_a_nota_reconhece_o_saldo_de_partida_e_nao_manda_repetir(
    client: TestClient, headers, db: Session
):
    """AC2 — a nota diz as DUAS coisas: existe saldo de partida; não houve saldo novo no período.

    E a frase *"nunca teve saldo informado"* não aparece em lugar nenhum do payload — era ela que a
    tela renderizava para quem já tinha informado.
    """
    _account(client, headers, opening=1_000_000, opening_date=OPENING)

    report = _report(db)
    c = _so_conta(report)
    nota = " ".join(c.notes)

    assert OPENING.isoformat() in nota, (
        "a nota precisa dizer QUANDO o saldo de partida foi informado"
    )
    assert "saldo de partida" in nota
    assert "nenhum saldo novo" in nota, (
        "a nota precisa separar 'existe saldo de partida' de 'não houve saldo novo neste "
        "período' — afirmar só o segundo é o que fazia a tela mandar o dono repetir o ato"
    )
    # UX-001 (8.7): o lado externo não usa o vocabulário locacional da Projeção.
    assert "no banco" not in nota

    payload = " ".join(str(v) for v in asdict(report).values())
    assert "nunca teve saldo informado" not in payload
    assert "Nenhum saldo informado para esta conta" not in payload, (
        "a redação antiga voltou — ela afirma que a conta não tem saldo informado, e toda conta tem"
    )


def test_conta_com_abertura_recuada_conta_mais_dias_sem_mudar_o_bloco_1(
    client: TestClient, headers, db: Session
):
    """O contador acompanha a `opening_date` de verdade — não é uma constante disfarçada.

    Duas contas idênticas, abertas em datas diferentes, produzem contadores diferentes; e nenhuma
    das duas ganha divergência por isso.
    """
    _account(client, headers, name="Aberta em julho", opening=1_000_000, opening_date=OPENING)
    _account(
        client, headers, name="Aberta em junho", opening=1_000_000, opening_date=date(2026, 6, 1)
    )

    report = _report(db)
    por_nome = {c.bank_account_name: c for c in report.contas}
    assert por_nome["Aberta em julho"].dias_desde_ultima_conferencia == 24
    assert por_nome["Aberta em junho"].dias_desde_ultima_conferencia == 54
    # IV2 — o bloco 1 das duas segue idêntico ao de antes desta story.
    assert report.contas_avaliadas == 0
    assert report.contas_sem_checkpoint == 2
    assert report.total_divergencia_cents is None
    assert report.contas_fora_da_banda == []


# ── Story 8.20 — a COMPARAÇÃO DEGENERADA (checkpoint na data de abertura) ────────────────────
#
# `derived_balance(until=opening_date) ≡ opening_balance_cents` para toda conta, sempre — o escopo
# de `service._movements_sums` é `posted_at > opening_date`, estrito. Comparar os dois lados nessa
# data é comparar DUAS DECLARAÇÕES DO MESMO DONO SOBRE O MESMO DIA, e o resultado é errado nos dois
# ramos possíveis: coincidindo, dá zero por construção e o Diagnóstico emite o 🟢 "está tudo
# batendo" sobre um razão bancário vazio; discordando, estoura a banda e o motor manda o dono caçar
# um lançamento que não existe. Por isso o remédio é "a comparação não vale", e NUNCA "se der zero,
# ignore" — este segundo passaria no ramo A e deixaria o ramo B vivo.


def _assert_degenerada(
    c: reconciliation.ConferenciaConta, *, reference_date: date
) -> None:
    """O estado do AC1: o mesmo de "sem checkpoint", com UM desvio — `saldo_banco_data`."""
    assert c.saldo_banco_cents is None
    assert c.saldo_banco_origem == ORIGEM_INDISPONIVEL
    assert c.saldo_banco_fonte is None
    assert c.saldo_sistema_cents is None, (
        "o saldo derivado foi apurado num caminho que não compara nada — `derived_balance` não "
        "deve ser chamada aqui"
    )
    assert c.saldo_sistema_origem == ORIGEM_BANCO
    assert c.divergencia_cents is None, (
        "o relatório produziu uma divergência a partir de uma comparação TAUTOLÓGICA: o saldo "
        "informado é da própria data de abertura, e ali o lado do e1p é o saldo de abertura por "
        "definição. Zero ali não é 'conferi e bateu' — é 'comparei um número com ele mesmo'"
    )
    assert c.dentro_da_tolerancia is None
    assert c.tolerancia_cents == 0
    # O desvio deliberado (AC3): houve DECLARAÇÃO; o que faltou foi a COMPARAÇÃO.
    assert c.saldo_banco_data == reference_date, (
        "sem este campo o payload não distingue 'você não me informou saldo nenhum' de 'você me "
        "informou, mas nesta data isso não decide nada' — e a tela mandaria o dono repetir o ato "
        "que ele acabou de fazer"
    )
    nota = " ".join(c.notes)
    assert reconciliation._note_sem_checkpoint(OPENING) not in c.notes, (
        "a nota de 'nenhum saldo novo informado no período' foi reusada numa conta que declarou "
        "dentro dele — trocar uma afirmação falsa por outra é o mesmo defeito uma camada acima"
    )
    assert reference_date.isoformat() in nota
    assert "mesmo dia em que a conta foi aberta" in nota
    assert "dia posterior" in nota, "a nota precisa dizer o que fazer, não só o que houve"
    # UX-001 (8.7): o vocabulário do lado externo não usa "no banco" (é a parcela da Projeção).
    assert "no banco" not in nota


def test_checkpoint_na_data_de_abertura_nao_e_conferencia(
    client: TestClient, headers, db: Session
):
    """**Ramo A — o comum, e o caro.** As duas declarações coincidem → hoje, 🟢 falso.

    Cenário real do tenant do fundador: conta cadastrada com saldo de abertura e, no mesmo dia, o
    dono informa no app o mesmo número que a UI já lhe mostrou. Antes desta correção o relatório
    devolvia `divergencia_cents == 0` e `dentro_da_tolerancia is True` — "está tudo batendo" para
    uma conta com **zero movimento** lançado. O sistema se auto-aprovava.
    """
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000, reference_date=OPENING)

    report = _report(db)
    c = _so_conta(report)
    _assert_degenerada(c, reference_date=OPENING)

    assert report.contas_avaliadas == 0
    assert report.contas_sem_checkpoint == 1
    assert report.total_divergencia_cents is None
    assert report.contas_fora_da_banda == []


def test_checkpoint_na_data_de_abertura_que_DISCORDA_nao_inventa_furo(
    client: TestClient, headers, db: Session
):
    """**Ramo B — o silencioso.** As duas declarações discordam → hoje, 🔴 falso.

    O dono corrigiu a memória (ou o saldo de abertura mudou depois, via `update_account`) e informa
    R$ 40.000 numa conta aberta com R$ 10.000, na data de abertura. A divergência de R$ 30.000
    estoura qualquer banda, a conta entra em `contas_fora_da_banda` e o motor escreve *"faltam
    R$ 30.000 em lançamentos — provavelmente faltam lançamentos de saída"*. **Não falta lançamento
    nenhum**: o dono se contradisse em duas declarações sobre o mesmo dia.

    Este é o teste que impede o remédio de degenerar em *"se der zero, ignore"* — essa variante
    passaria no ramo A e deixaria este diagnóstico falso vivo.
    """
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=4_000_000, reference_date=OPENING)

    report = _report(db)
    _assert_degenerada(_so_conta(report), reference_date=OPENING)
    assert report.contas_fora_da_banda == [], (
        "o relatório acusou um furo de R$ 30.000 numa comparação que não compara nada — a "
        "divergência é inventada pelo próprio relatório, o modo de falha que este módulo inteiro "
        "existe para impedir"
    )
    assert report.total_divergencia_cents is None


def test_checkpoint_na_data_de_abertura_CONTA_no_bloco_4(client: TestClient, headers, db: Session):
    """AC8 — o bloco 4 não é silenciado: o dono **declarou de fato**, e é isso que ele mede.

    O bloco 1 mede a **comparação**; o bloco 4 mede o **ato de declarar**. Colapsar os dois é o
    erro de fundo que esta correção desfaz — e `None` ali significaria *"nunca confirmado"*, que
    seria falso e faria a tela dizer "Esta conta nunca teve saldo informado."
    """
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000, reference_date=OPENING)

    # `end == today == opening_date`: o dia do cadastro. "Confirmado hoje" = 0, e 0 não é `None`.
    c = _so_conta(_report(db, end=OPENING, today=OPENING))
    assert c.dias_desde_ultima_conferencia == 0, (
        "o bloco 4 perdeu a declaração: `0` é 'confirmado hoje' e `None` é 'nunca confirmado' — "
        "não são a mesma coisa, e só um dos dois é verdade aqui"
    )
    assert c.dias_desde_ultima_conferencia is not None
    # E na janela cheia do relatório o contador anda normalmente (28/07 − 01/07 = 27 dias… mas
    # `min(end, today)` manda o `end` = 25/07 → 24 dias).
    assert _so_conta(_report(db)).dias_desde_ultima_conferencia == 24


def test_checkpoint_UM_DIA_depois_da_abertura_continua_avaliavel(
    client: TestClient, headers, db: Session
):
    """O NÃO-MEMBRO do conjunto degenerado — a guarda contra a correção virar bloqueio geral.

    Um dia depois da abertura o lado do e1p já carrega os movimentos daquele dia, e é exatamente
    por isso que a comparação decide alguma coisa. Aqui ela encontra o furo de R$ 5.000.
    """
    dia_seguinte = date(2026, 7, 2)
    conta = _account(client, headers, opening=1_000_000)
    _lancar(client, headers, conta["id"], amount_cents=-100_000, posted_at=dia_seguinte)
    _declarar(client, headers, conta["id"], balance_cents=400_000, reference_date=dia_seguinte)

    c = _so_conta(_report(db))
    assert c.saldo_banco_cents == 400_000
    assert c.saldo_banco_origem == ORIGEM_BANCO
    assert c.saldo_sistema_cents == 900_000
    assert c.divergencia_cents == -500_000
    assert c.dentro_da_tolerancia is False
    assert c.notes == []


def test_conta_com_checkpoint_degenerado_E_outro_posterior_usa_o_posterior(
    client: TestClient, headers, db: Session
):
    """A detecção olha o checkpoint **escolhido**, não "existe algum na data de abertura".

    Declarar na abertura e declarar de novo depois é o caminho normal do mutirão: o segundo saldo
    é comparável e é ele que o relatório usa. Se a guarda fosse "a conta tem checkpoint na data de
    abertura", a conta ficaria não avaliável para sempre.
    """
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000, reference_date=OPENING)
    _lancar(client, headers, conta["id"], amount_cents=-100_000, posted_at=date(2026, 7, 10))
    _declarar(client, headers, conta["id"], balance_cents=900_000, reference_date=REF)

    c = _so_conta(_report(db))
    assert c.saldo_banco_data == REF
    assert c.divergencia_cents == 0
    assert c.dentro_da_tolerancia is True


# ── AC7 — o consolidado nunca vem sem a decomposição ─────────────────────────────────────────


def test_consolidado_nunca_vem_sem_decomposicao(client: TestClient, headers, db: Session):
    """O cenário literal do epic §3.2 / decisão do fundador F3.

    Três contas divergindo +R$ 1.200, −R$ 900 e +R$ 40 somam **+R$ 340**, que *parece saudável* e
    **esconde dois problemas**. O relatório devolve o total, sim — mas sempre com as três contas ao
    lado e com as duas problemáticas **nomeadas**.
    """
    corrente = _account(client, headers, name="Corrente", opening=1_000_000, number="1111-1")
    _declarar(client, headers, corrente["id"], balance_cents=1_120_000)

    poupanca = _account(
        client, headers, name="Poupança", opening=2_000_000, kind=KIND_SAVINGS, number="2222-2"
    )
    _declarar(client, headers, poupanca["id"], balance_cents=1_910_000)

    aplicacao = _account(
        client, headers, name="Aplicação", opening=500_000, kind=KIND_INVESTMENT, number="3333-3"
    )
    _declarar(client, headers, aplicacao["id"], balance_cents=504_000)

    report = _report(db)

    assert report.total_divergencia_cents == 34_000, "+R$ 1.200 − R$ 900 + R$ 40 = +R$ 340"
    assert len(report.contas) == 3, (
        "o consolidado veio sem a decomposição — é literalmente o que o epic §3.2 proíbe"
    )
    assert report.contas_avaliadas == 3
    assert report.contas_sem_checkpoint == 0

    por_id = {c.bank_account_id: c for c in report.contas}
    assert por_id[corrente["id"]].divergencia_cents == 120_000
    assert por_id[poupanca["id"]].divergencia_cents == -90_000
    assert por_id[aplicacao["id"]].divergencia_cents == 4_000
    # A aplicação (kind='investment') **entra** na conferência: ela é excluída do "caixa disponível"
    # da 8.8, não da conferência — o extrato dela também pode ter furo.
    assert por_id[aplicacao["id"]].bank_account_kind == KIND_INVESTMENT

    fora = {f.bank_account_id: f for f in report.contas_fora_da_banda}
    assert set(fora) == {corrente["id"], poupanca["id"]}, (
        "as duas contas com problema precisam ser NOMEADAS — apontar qual conta está fora da banda "
        "é a razão de a conferência ser por conta"
    )
    assert fora[corrente["id"]].bank_account_name == "Corrente"
    assert fora[poupanca["id"]].divergencia_cents == -90_000
    # A de +R$ 40 está dentro da banda (piso de R$ 50): verde e silêncio.
    assert por_id[aplicacao["id"]].dentro_da_tolerancia is True
    assert por_id[aplicacao["id"]].notes == []


def test_total_parcial_avisa_que_nao_cobre_todas_as_contas(
    client: TestClient, headers, db: Session
):
    conferida = _account(client, headers, name="Conferida", opening=1_000_000, number="1111-1")
    _declarar(client, headers, conferida["id"], balance_cents=1_200_000)
    _account(client, headers, name="Nunca conferida", opening=5_000_000, number="2222-2")

    report = _report(db)
    assert report.total_divergencia_cents == 200_000
    assert report.contas_avaliadas == 1
    assert report.contas_sem_checkpoint == 1
    assert len(report.contas) == 2
    assert any("não cobre todas as contas" in n for n in report.notes), (
        f"total parcial sem ressalva — um número que mente por omissão. notes={report.notes}"
    )


def test_relatorio_sem_conta_nenhuma_e_vazio_e_honesto(client: TestClient, headers, db: Session):
    """Estado de todos os tenants hoje: nenhuma conta cadastrada. Zero contas, total `None`."""
    report = _report(db)
    assert report.contas == []
    assert report.total_divergencia_cents is None
    assert report.contas_avaliadas == 0
    assert report.contas_sem_checkpoint == 0
    assert report.contas_fora_da_banda == []
    assert report.start == START and report.end == END


# ── AC1 — escopo das contas ──────────────────────────────────────────────────────────────────


def test_conta_arquivada_fica_fora_do_relatorio(client: TestClient, headers, db: Session):
    ativa = _account(client, headers, name="Ativa", opening=1_000_000, number="1111-1")
    arquivada = _account(client, headers, name="Arquivada", opening=9_000_000, number="2222-2")
    _declarar(client, headers, arquivada["id"], balance_cents=1)
    assert (
        client.post(f"/bank/accounts/{arquivada['id']}/archive", headers=headers).status_code == 200
    )

    report = _report(db)
    assert [c.bank_account_id for c in report.contas] == [ativa["id"]]

    # Mas pedir a conta arquivada EXPLICITAMENTE responde (ela existe; 404 seria falso).
    so_ela = _so_conta(_report(db, bank_account_id=arquivada["id"]))
    assert so_ela.bank_account_id == arquivada["id"]


def test_filtro_por_conta_devolve_exatamente_uma(client: TestClient, headers, db: Session):
    a = _account(client, headers, name="A", opening=1_000_000, number="1111-1")
    _account(client, headers, name="B", opening=2_000_000, number="2222-2")
    _declarar(client, headers, a["id"], balance_cents=1_000_000)

    assert [c.bank_account_id for c in _report(db, bank_account_id=a["id"]).contas] == [a["id"]]


def test_conta_inexistente_estoura_bank_error_404(client: TestClient, headers, db: Session):
    from app.modules.bank import service

    with pytest.raises(service.BankError) as exc:
        _report(db, bank_account_id="conta-que-nao-existe")
    assert exc.value.status_code == 404


# ── AC8 — movimentos ignorados (transparência, não recálculo) ────────────────────────────────


def test_movimentos_ignorados_conta_apenas_os_da_janela(client: TestClient, headers, db: Session):
    conta = _account(client, headers, opening=1_000_000, opening_date=date(2026, 6, 1))
    dentro_1 = _lancar(
        client, headers, conta["id"], amount_cents=-10_000, posted_at=date(2026, 7, 5)
    )
    dentro_2 = _lancar(
        client, headers, conta["id"], amount_cents=-20_000, posted_at=date(2026, 7, 6)
    )
    fora = _lancar(client, headers, conta["id"], amount_cents=-30_000, posted_at=date(2026, 6, 15))
    _lancar(client, headers, conta["id"], amount_cents=-40_000, posted_at=date(2026, 7, 7))  # ativo

    for tx in (dentro_1, dentro_2, fora):
        assert (
            client.post(
                f"/bank/transactions/{tx['id']}/ignore",
                json={"reason": "não é meu"},
                headers=headers,
            ).status_code
            == 200
        )

    _declarar(client, headers, conta["id"], balance_cents=960_000)

    c = _so_conta(_report(db))
    assert c.movimentos_ignorados == 2, "contou movimento ignorado fora da janela do relatório"
    # E o saldo derivado JÁ exclui os ignorados — a conferência não refiltra (o filtro mora dentro
    # de `service._movements_sums`, e ter dois lugares é ter dois lugares para divergirem).
    assert c.saldo_sistema_cents == 960_000, "1.000.000 − 40.000 (o único movimento ativo)"
    assert c.divergencia_cents == 0


def test_movimentos_ignorados_nao_vazam_entre_contas(client: TestClient, headers, db: Session):
    a = _account(client, headers, name="A", opening=1_000_000, number="1111-1")
    b = _account(client, headers, name="B", opening=1_000_000, number="2222-2")
    tx = _lancar(client, headers, a["id"], amount_cents=-10_000, posted_at=date(2026, 7, 5))
    client.post(f"/bank/transactions/{tx['id']}/ignore", headers=headers)

    por_id = {c.bank_account_id: c for c in _report(db).contas}
    assert por_id[a["id"]].movimentos_ignorados == 1
    assert por_id[b["id"]].movimentos_ignorados == 0


# ── AC2 — eixo B cru, sem tradução ───────────────────────────────────────────────────────────


def test_saldo_banco_fonte_e_o_valor_cru_do_checkpoint(client: TestClient, headers, db: Session):
    """`ofx` chega ao relatório como `ofx` — os dois eixos NUNCA se traduzem um no outro (§1.3.1).

    A linha é escrita pelo modelo porque a API recusa `ofx` nesta onda (AC3 da 8.4). Na Onda 3
    isto é **zero mudança de vocabulário**: só se passa a escrever `ofx` pela porta da importação.
    """
    conta = _account(client, headers, opening=1_000_000)
    db.add(
        BankBalanceCheckpoint(
            tenant_id=_tenant_id(client, headers),
            bank_account_id=conta["id"],
            reference_date=date(2026, 7, 20),
            balance_cents=1_000_000,
            origin=ORIGIN_OFX,
        )
    )
    db.commit()

    c = _so_conta(_report(db))
    assert c.saldo_banco_fonte == ORIGIN_OFX
    assert c.saldo_banco_origem == ORIGEM_BANCO, (
        "o eixo B contaminou o eixo A — `ofx` é porta de entrada, não plano de dinheiro"
    )


# ── AC4b — a proibição como varredura estática ───────────────────────────────────────────────

_RECONCILIATION_PY = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "modules"
    / "bank"
    / "reconciliation.py"
)


def _chamadas(tree: ast.AST) -> list[str]:
    """Nomes de função efetivamente CHAMADOS (`f()` / `mod.f()`) — via AST, não por texto.

    AST em vez de `grep` pelo mesmo motivo do `test_money_planes.py`: a docstring deste módulo
    **precisa** poder citar a função proibida para explicar por que ela é proibida.
    """
    nomes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                nomes.append(func.attr)
            elif isinstance(func, ast.Name):
                nomes.append(func.id)
    return nomes


def test_conferencia_nao_usa_derived_balances_as_of():
    """**AC4b, contrato ratificado (D-4).** A função de data COMUM é proibida na conferência.

    Cada conta tem a sua própria data de referência; um `as_of` único compararia o saldo do banco de
    uma data com o saldo do sistema de outra — o erro que o design §5.1 manda recusar. O sintoma de
    errar seria **silencioso e plausível**: o relatório não quebra, ele mente um número. E a função
    certa difere da errada por um `s` (foi por isso que a errada virou `derived_balances_as_of`).

    A asserção positiva no fim impede o teste de virar vácuo: se um dia `derived_balance` sumir
    daqui, é porque alguém reimplementou a soma — e aí o problema é outro (§1.3a).
    """
    chamadas = _chamadas(ast.parse(_RECONCILIATION_PY.read_text(encoding="utf-8")))
    assert "derived_balances_as_of" not in chamadas, (
        "AC4b VIOLADO: a conferência chamou `derived_balances_as_of`, que apura TODAS as contas "
        "numa data comum. Cada conta aqui tem a data do SEU checkpoint. Use laço de "
        "`derived_balance` "
        "com o `until` de cada conta — ver a docstring da função em lote."
    )
    assert "derived_balances" not in chamadas, "idem, sob o nome antigo"
    assert "derived_balance" in chamadas, (
        "a conferência parou de usar `derived_balance` — se a soma foi reimplementada aqui, "
        "a Regra dos Planos §1.3a fica inauditável (deve existir UMA implementação de saldo "
        "bancário)"
    )


def test_conferencia_nao_importa_wallet_nem_le_transactions():
    """IV3 / Regra dos Planos §1.3a: o saldo comparado é o bancário dos DOIS lados.

    Complementa (não substitui) o `test_bank_nao_referencia_transaction` do `test_money_planes.py`,
    que varre o módulo `bank` inteiro: aqui a asserção é sobre **este** arquivo, que é o que expõe
    campos de saldo comparáveis e por isso é onde a tentação de "somar o disponível da Carteira"
    apareceria primeiro.
    """
    fonte = _RECONCILIATION_PY.read_text(encoding="utf-8")
    tree = ast.parse(fonte)
    importados: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            importados.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            # ⚠️ O alias entra no caminho: sem isso, `from app.modules import wallet` produzia só
            # `"app.modules"` e passava nas duas asserções abaixo (nem "wallet" nem "core.ai"
            # apareciam). Furo encontrado no quality gate do Epic 8 (2026-07-30), corrigido também
            # em `test_money_planes.py` e `test_financial_intelligence_completeness.py`.
            base = f"{'.' * node.level}{node.module or ''}"
            importados.append(base)
            sep = "" if base.endswith(".") else "."
            importados.extend(f"{base}{sep}{a.name}" for a in node.names)

    assert not [m for m in importados if "wallet" in m], (
        f"a conferência importou a Carteira (plano 1): {importados}"
    )
    assert not [m for m in importados if "core.ai" in m or "anonymizer" in m], (
        "IV5: esta story não chama IA nem precisa de anonimizador (bloco 1 só devolve números, "
        "datas e o nome da conta — PII de terceiro é da 8.7/Onda 4)"
    )


# ── IV3 — todo campo de saldo declara a procedência (por instância) ──────────────────────────

_SALDO_FIELD = re.compile(r"^saldo_(?P<base>.+)_cents$")


def _campos_de_saldo_sem_origem(payload: dict) -> list[str]:
    """Campos `saldo_*_cents` sem o irmão `*_origem` no MESMO objeto (Regra dos Planos §1.3c).

    Varredura **por instância**, no payload real da rota — o mesmo tratamento que as Stories 8.2,
    8.3 e 8.4 deram à regra. O gate GLOBAL (`test_todo_saldo_declara_origem`, varrendo todo schema
    de saída do projeto) foi atribuído à 8.1 e nunca criado; criá-lo é decisão de @po/@architect,
    não desta story. Registrado em Completion Notes.

    `divergencia_cents`/`tolerancia_cents`/`total_divergencia_cents` estão fora da regra de
    propósito: são uma diferença e um limiar, não saldos — §1.3c fala de campos que carregam saldo.
    """
    faltando = []
    for chave in payload:
        m = _SALDO_FIELD.match(chave)
        if m and f"saldo_{m.group('base')}_origem" not in payload:
            faltando.append(chave)
    return faltando


def test_todo_saldo_do_relatorio_declara_origem(client: TestClient, headers):
    conta = _account(client, headers, name="Com saldo", opening=1_000_000, number="1111-1")
    _declarar(client, headers, conta["id"], balance_cents=1_100_000)
    _account(client, headers, name="Sem saldo", opening=1_000_000, number="2222-2")

    payload = client.get(
        "/bank/reconciliation-report",
        params={"start": START.isoformat(), "end": END.isoformat()},
        headers=headers,
    ).json()

    assert len(payload["contas"]) == 2
    for c in payload["contas"]:
        assert _campos_de_saldo_sem_origem(c) == [], (
            f"campo de saldo sem o irmão *_origem em {c['bank_account_name']}: "
            f"{_campos_de_saldo_sem_origem(c)}"
        )
        assert c["saldo_banco_origem"] in ORIGENS
        assert c["saldo_sistema_origem"] in ORIGENS
        # Inclusive na conta NÃO avaliável: o que falta é o valor, não a origem.
        assert c["saldo_sistema_origem"] == ORIGEM_BANCO


# ── AC9 — a rota ─────────────────────────────────────────────────────────────────────────────


def _get(client: TestClient, headers, **params):
    return client.get(
        "/bank/reconciliation-report",
        params={"start": START.isoformat(), "end": END.isoformat(), **params},
        headers=headers,
    )


def test_rota_devolve_o_relatorio_completo(client: TestClient, headers):
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=700_000)

    resp = _get(client, headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["start"] == START.isoformat() and body["end"] == END.isoformat()
    assert body["total_divergencia_cents"] == -300_000
    assert body["contas_avaliadas"] == 1 and body["contas_sem_checkpoint"] == 0
    assert len(body["contas"]) == 1, "o consolidado nunca viaja sem a decomposição"
    assert body["contas_fora_da_banda"][0]["bank_account_name"] == "Itaú PJ"

    c = body["contas"][0]
    assert c["saldo_banco_cents"] == 700_000
    assert c["saldo_sistema_cents"] == 1_000_000
    assert c["saldo_banco_data"] == "2026-07-20"
    assert c["saldo_banco_fonte"] == ORIGIN_MANUAL
    assert c["dentro_da_tolerancia"] is False
    assert c["dias_desde_ultima_conferencia"] == 5, "min(end, hoje) − 20/07"
    assert c["movimentos_ignorados"] == 0


def test_rota_indisponivel_e_200_com_nulos_nao_erro(client: TestClient, headers):
    """`indisponivel` é resposta legítima. Um 404/500 aqui tornaria o caminho normal um erro."""
    _account(client, headers, opening=1_000_000)

    body = _get(client, headers).json()
    c = body["contas"][0]
    assert c["saldo_banco_origem"] == ORIGEM_INDISPONIVEL
    assert c["saldo_banco_cents"] is None and c["divergencia_cents"] is None
    assert c["notes"]
    assert body["total_divergencia_cents"] is None


def test_rota_filtra_por_conta_e_normaliza_string_vazia(client: TestClient, headers):
    a = _account(client, headers, name="A", opening=1_000_000, number="1111-1")
    _account(client, headers, name="B", opening=2_000_000, number="2222-2")

    assert len(_get(client, headers, bank_account_id=a["id"]).json()["contas"]) == 1
    # `?bank_account_id=` == "todas": não pode virar filtro que casa zero contas.
    assert len(_get(client, headers, bank_account_id="").json()["contas"]) == 2


def test_rota_end_antes_de_start_e_422(client: TestClient, headers):
    resp = client.get(
        "/bank/reconciliation-report",
        params={"start": "2026-07-25", "end": "2026-07-01"},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_rota_conta_inexistente_e_404_fail_closed(client: TestClient, headers):
    assert _get(client, headers, bank_account_id="fantasma").status_code == 404


def test_rota_exige_autenticacao(client: TestClient):
    resp = client.get(
        "/bank/reconciliation-report",
        params={"start": START.isoformat(), "end": END.isoformat()},
    )
    assert resp.status_code in (401, 403)


def test_rota_exige_start_e_end(client: TestClient, headers):
    assert client.get("/bank/reconciliation-report", headers=headers).status_code == 422


# ── IV1 — read-only de verdade ───────────────────────────────────────────────────────────────


def _snapshot(db: Session) -> dict:
    """Fotografia do estado que a conferência JAMAIS pode alterar (mesmo padrão da 5.7)."""
    db.expire_all()
    return {
        "bank_accounts": {
            a.id: (a.name, a.kind, a.opening_balance_cents, a.opening_date, a.archived_at)
            for a in db.scalars(select(BankAccount)).all()
        },
        "bank_transactions": {
            t.id: (t.posted_at, t.amount_cents, t.status, t.ignored_reason)
            for t in db.scalars(select(BankTransaction)).all()
        },
        "bank_balance_checkpoints": {
            c.id: (c.reference_date, c.balance_cents, c.origin, c.created_by)
            for c in db.scalars(select(BankBalanceCheckpoint)).all()
        },
        "charges": {
            c.id: (c.status, c.amount_cents, c.due_date, c.paid_at)
            for c in db.scalars(select(Charge)).all()
        },
        "payables": {
            p.id: (p.status, p.amount_cents, p.due_date, p.paid_at)
            for p in db.scalars(select(Payable)).all()
        },
        "transactions": {
            t.id: (t.status, t.net_cents) for t in db.scalars(select(Transaction)).all()
        },
    }


def test_reconciliation_report_is_read_only(client: TestClient, headers, db: Session):
    """IV1. Inclui o caso `indisponivel`, que é onde a "ajuda" mais provável apareceria: criar um
    checkpoint (ou um "movimento de ajuste") para que o relatório tenha o que comparar."""
    conferida = _account(client, headers, name="Conferida", opening=1_000_000, number="1111-1")
    _lancar(client, headers, conferida["id"], amount_cents=-70_000, posted_at=date(2026, 7, 10))
    _declarar(client, headers, conferida["id"], balance_cents=500_000)
    _account(client, headers, name="Sem checkpoint", opening=800_000, number="2222-2")

    before = _snapshot(db)
    _report(db)
    _report(db)
    _get(client, headers)
    after = _snapshot(db)

    assert after == before, "a conferência escreveu/alterou dados — viola IV1 (read-only)"
    for tabela in before:
        assert after[tabela] == before[tabela], f"tabela alterada pela conferência: {tabela}"


# ── IV2 — o eixo já em produção segue intacto ────────────────────────────────────────────────


def test_movimento_bancario_nao_altera_dre(client: TestClient, headers, db: Session):
    """IV2 (design §6.4). Conta, movimento e saldo declarado são **plano 3**; a DRE é plano 2.

    Snapshot campo a campo da DRE antes e depois de existir toda a matéria-prima da conferência —
    e depois de rodar a própria conferência.
    """
    antes = asdict(dre_service.dre_report(db, start=START, end=END))

    conta = _account(client, headers, opening=1_000_000)
    _lancar(client, headers, conta["id"], amount_cents=-250_000, posted_at=date(2026, 7, 10))
    _declarar(client, headers, conta["id"], balance_cents=400_000)
    _report(db)

    depois = asdict(dre_service.dre_report(db, start=START, end=END))
    assert depois == antes
    for campo in antes:
        assert depois[campo] == antes[campo], f"campo da DRE contaminado pelo plano 3: {campo}"


# ── Story 8.16 — os TERMOS DA PRÉ-CONDIÇÃO DO GATE: anota, nunca subtrai ─────────────────────
#
# O bloco 4 ("o sistema declara o que não sabe") passa a contar o que o e1p **sabe** que moveu
# dinheiro numa conta real e ainda não virou movimento bancário na janela. Quatro termos; três
# contados (P1+P2 juntos, P3 separado) e o P4 declarado e não contado.
#
# O teste que mais importa deste bloco é o **IV3**: a divergência tem de ficar IDÊNTICA com e sem
# esses lançamentos. Descontar o termo conhecido seria o checkpoint corrigindo o saldo derivado com
# outra roupa — a divergência iria a zero por construção sempre que o sistema soubesse explicar a
# diferença, e a métrica primária do épico morreria (Regra 5 do `CLAUDE.md`).


def _payable_legado(db: Session, tenant_id: str, *, valor: int, pago_em: date) -> Payable:
    """Uma baixa SEM conta bancária informada — uma das legadas, anteriores à Story 8.12 (P1)."""
    p = Payable(
        tenant_id=tenant_id,
        description="Fornecedor legado",
        category="operacional",
        amount_cents=valor,
        due_date=pago_em,
        status="paid",
        paid_at=datetime.combine(pago_em, time.min, tzinfo=UTC),
    )
    db.add(p)
    db.commit()
    return p


def _charge_sem_conta(db: Session, tenant_id: str, *, valor: int, pago_em: date) -> Charge:
    """Recebimento fora da cobrança do e1p, sem conta informada (P2)."""
    c = Charge(
        tenant_id=tenant_id,
        description="Pix antigo",
        amount_cents=valor,
        due_date=pago_em,
        method="pix",
        kind="service",
        status="paid",
        paid_at=datetime.combine(pago_em, time.min, tzinfo=UTC),
    )
    db.add(c)
    db.commit()
    return c


def _charge_de_rendimento(db: Session, tenant_id: str, *, valor: int, pago_em: date) -> Charge:
    """A `Charge` SINTÉTICA de rendimento de aplicação (P3) — o achado A-1.

    Ela nasce `paid`, `paid_at=now()`, **sem** `transaction_id` e **sem** `bank_account_id`: cai
    inteira na população de P2 se o predicado de exclusão não estiver lá. O `external_ref` é o
    discriminador, e o predicado que o lê mora em UM lugar só.
    """
    c = Charge(
        tenant_id=tenant_id,
        description="Rendimento CDB",
        amount_cents=valor,
        due_date=pago_em,
        method="pix",
        kind="service",
        status="paid",
        external_ref="investment:abc-123",
        paid_at=datetime.combine(pago_em, time.min, tzinfo=UTC),
    )
    db.add(c)
    db.commit()
    return c


def test_iv3_a_divergencia_nao_se_move_por_causa_da_nota(client: TestClient, headers, db: Session):
    """**IV3 — a verificação que esta story existe para não falhar.**

    Snapshot do relatório inteiro, campo a campo, com e sem lançamentos sem conta informada:
    `divergencia_cents`, `tolerancia_cents`, `dentro_da_tolerancia`, `total_divergencia_cents` e
    `contas_fora_da_banda` **idênticos**. Só `notes` e os contadores novos diferem.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, opening=1_000_000)
    _lancar(client, headers, conta["id"], amount_cents=-70_000, posted_at=date(2026, 7, 10))
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)

    antes = asdict(_report(db))
    assert antes["lancamentos_sem_conta_informada"] == 0
    assert antes["notes"] == []
    assert antes["contas"][0]["divergencia_cents"] == 70_000, (
        "o cenário precisa ter divergência REAL para o teste valer"
    )

    _payable_legado(db, tenant_id, valor=312_000, pago_em=date(2026, 7, 12))
    _charge_sem_conta(db, tenant_id, valor=45_000, pago_em=date(2026, 7, 14))
    depois = asdict(_report(db))

    # O que NÃO pode mudar — campo a campo, inclusive dentro de cada conta.
    for campo in ("total_divergencia_cents", "contas_avaliadas", "contas_sem_checkpoint",
                  "contas_fora_da_banda"):
        assert depois[campo] == antes[campo], f"a nota mexeu em {campo} — ANOTA, NUNCA SUBTRAI"
    for campo in ("divergencia_cents", "tolerancia_cents", "dentro_da_tolerancia",
                  "saldo_banco_cents", "saldo_sistema_cents"):
        assert depois["contas"][0][campo] == antes["contas"][0][campo], campo

    # O que MUDA: só a anotação.
    assert depois["lancamentos_sem_conta_informada"] == 2
    assert depois["valor_sem_conta_informada_cents"] == 357_000
    assert len(depois["notes"]) == 1
    assert "2 lançamentos deste período" in depois["notes"][0]
    assert "R$ 3.570,00" in depois["notes"][0]
    assert "Onda 2" in depois["notes"][0], "a nota tem de nomear a onda que fecha o termo"


def test_a1_o_rendimento_de_aplicacao_nao_entra_no_termo_de_conta_informada(
    client: TestClient, headers, db: Session
):
    """**O achado A-1, o bloqueio 3 da onda** — o teste dedicado que a story pediu.

    Cenário: **uma** `Charge` de rendimento na janela e **zero** outros pendentes.
      → P1+P2 = **0**, P3 = **1**, e a nota que sai é a do rendimento, nomeando a **Onda 2b**.

    **Mutante que este teste mata:** remover o `_not_investment_yield()` do P2. Com ele removido, o
    rendimento passa a contar em P1+P2 (e também em P3, ou seja, DUAS vezes), a nota de "lançamentos
    sem conta informada" aparece indevidamente — e **o gate nunca abriria para nenhum tenant que
    registre rendimento**, para sempre, até a Onda 2b. Verificado por mutação na implementação.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    _charge_de_rendimento(db, tenant_id, valor=48_000, pago_em=date(2026, 7, 14))

    r = _report(db)
    assert r.lancamentos_sem_conta_informada == 0, (
        "a Charge sintética de rendimento caiu em P1/P2 — é o achado A-1 de volta, e com ele o "
        "gate não abre para nenhum tenant que registre rendimento"
    )
    assert r.valor_sem_conta_informada_cents == 0
    assert r.rendimentos_sem_perna_bancaria == 1
    assert r.valor_rendimentos_sem_perna_cents == 48_000

    assert len(r.notes) == 1
    nota = r.notes[0]
    assert "1 rendimento de aplicação" in nota
    assert "R$ 480,00" in nota
    assert "Onda 2b" in nota, "o termo P3 NÃO fecha nesta onda — a nota tem de dizer isso"
    assert "não há o que corrigir à mão" in nota


def test_os_dois_termos_geram_duas_notas_com_ondas_diferentes(
    client: TestClient, headers, db: Session
):
    """Uma nota **por termo não-zero**, cada uma nomeando a sua onda (ratificação §C-1.5).

    A v0.1 tinha UMA nota e UM par de contadores, o que achatava P3 dentro de P1/P2. Prometer
    *"isso some quando você terminar o mutirão"* sobre um termo que só fecha na Onda 2b é a mesma
    classe de afirmação sem lastro que a Onda 0 removeu da Projeção.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    _payable_legado(db, tenant_id, valor=312_000, pago_em=date(2026, 7, 12))
    _charge_de_rendimento(db, tenant_id, valor=48_000, pago_em=date(2026, 7, 14))

    r = _report(db)
    assert r.lancamentos_sem_conta_informada == 1 and r.rendimentos_sem_perna_bancaria == 1
    assert len(r.notes) == 2
    assert "Onda 2:" in r.notes[0] and "Onda 2b" not in r.notes[0]
    assert "Onda 2b" in r.notes[1]


def test_zero_termo_nao_zero_e_zero_nota(client: TestClient, headers, db: Session):
    """Silêncio — e é exatamente esse silêncio que sinaliza *"agora o gate pode ser lido"*."""
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    r = _report(db)
    assert (r.lancamentos_sem_conta_informada, r.rendimentos_sem_perna_bancaria) == (0, 0)
    assert r.notes == []


def test_lancamento_fora_da_janela_nao_conta(client: TestClient, headers, db: Session):
    """A pré-condição é **por ciclo de conferência**: o que aconteceu fora da janela é de outro."""
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    _payable_legado(db, tenant_id, valor=312_000, pago_em=date(2026, 6, 20))  # antes de START

    assert _report(db).lancamentos_sem_conta_informada == 0
    # E a borda: `end` é INCLUSIVO nas duas pontas (datas de calendário).
    _payable_legado(db, tenant_id, valor=100_000, pago_em=END)
    assert _report(db).lancamentos_sem_conta_informada == 1


def test_baixa_com_conta_informada_nao_e_termo_nenhum(client: TestClient, headers, db: Session):
    """O não-membro por construção: o movimento bancário dela **existe**, então ela não é pendência.

    É a diferença entre P1 e o caminho normal do produto desde a Story 8.12 — se este teste cair,
    o termo passou a contar o que já está resolvido e a nota nunca iria a zero.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    p = _payable_legado(db, tenant_id, valor=312_000, pago_em=date(2026, 7, 12))
    p.bank_account_id = conta["id"]
    db.commit()

    assert _report(db).lancamentos_sem_conta_informada == 0


def test_iv5_os_contadores_novos_nao_escrevem_nada(client: TestClient, headers, db: Session):
    """**IV5** — a conferência continua read-only **com** o bloco 4 novo ligado.

    A contagem é `SELECT count(), sum()` e nada mais: nenhum lançamento é "corrigido", nenhuma conta
    é atribuída a nada, nenhum movimento nasce para fechar a diferença.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=900_000)
    _payable_legado(db, tenant_id, valor=312_000, pago_em=date(2026, 7, 12))
    _charge_de_rendimento(db, tenant_id, valor=48_000, pago_em=date(2026, 7, 14))

    before = _snapshot(db)
    _report(db)
    _get(client, headers)
    assert _snapshot(db) == before


def test_a_contagem_dos_termos_e_uma_porta_registrada():
    """O outro lado do fail-closed: a porta EXISTE e é ligada por composição, fora de `bank`.

    Sem esta asserção, os testes acima ficariam verdes do jeito mais fácil possível — devolvendo
    `TermosDoGate(0, 0, 0, 0)` fixo. E a inversão de dependência é o que mantém o gate estrutural
    `bank ↛ payables/receivables` verde **porque a dependência sumiu**, não porque foi escondida.
    """
    assert reconciliation.termos_do_gate_probe_registrado(), (
        "app/main.py deixou de ligar `register_termos_do_gate_probe`"
    )
    assert set(reconciliation.TermosDoGate.__dataclass_fields__) == {
        "lancamentos_sem_conta_informada",
        "valor_sem_conta_informada_cents",
        "rendimentos_sem_perna_bancaria",
        "valor_rendimentos_sem_perna_cents",
    }
    # E quem implementa a contagem vive do lado do NEGÓCIO, que pode importar `bank`.
    from app.modules.payables.service import contar_saidas_sem_conta_informada
    from app.modules.receivables.service import (
        contar_entradas_sem_conta_informada,
        contar_rendimentos_sem_perna_bancaria,
    )

    assert callable(contar_saidas_sem_conta_informada)
    assert callable(contar_entradas_sem_conta_informada)
    assert callable(contar_rendimentos_sem_perna_bancaria)


def test_sem_a_porta_registrada_o_relatorio_recusa_em_vez_de_zerar(
    client: TestClient, headers, db: Session, monkeypatch
):
    """**Fail-closed:** sem a contagem, o relatório levanta — nunca devolve zero por ausência.

    Zero por ausência de medição **não é zero**: as notas sumiriam em silêncio e a tela passaria a
    dizer, por omissão, *"nenhum termo pendente, o gate pode ser lido"*. É exatamente a leitura
    errada que custou uma decisão de produto neste épico.
    """
    _account(client, headers, opening=1_000_000)
    monkeypatch.setattr(reconciliation, "_termos_do_gate_probe", None)
    with pytest.raises(bank_service.BankError) as e:
        _report(db)
    assert e.value.status_code == 500
    assert "não está ligada" in str(e.value)
