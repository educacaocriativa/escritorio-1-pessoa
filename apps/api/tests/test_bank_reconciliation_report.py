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
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO, ORIGEM_INDISPONIVEL, ORIGENS
from app.modules.bank import reconciliation
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
    assert c.dias_desde_ultima_conferencia is None, "nunca declarado ≠ declarado hoje"

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
    """`reference_date == start` está DENTRO da janela (as duas pontas são inclusivas)."""
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000, reference_date=START)

    c = _so_conta(_report(db))
    assert c.saldo_banco_data == START
    assert c.divergencia_cents == 0


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
            importados.append(node.module or "")

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
