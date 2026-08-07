"""Saldo inicial MISTO na Projeção de Caixa (Story 8.8, Onda 1 do Epic 8) — o fecho da 8.1.

O que este arquivo prova, em ordem de valor:

1. **A transição de estado nos DOIS sentidos** (AC4) — o teste mais valioso da story. Sem conta
   bancária, o comportamento da Story 8.1 está **intacto** (origem `plataforma`, `runway.days`
   suprimido, `alert` suprimido): é fallback, não regressão. Com conta ativa, a origem vira `misto`
   e os dois sinais voltam **por construção** — a condição de supressão é a **origem**, e nada na
   lógica de runway, de alerta ou do motor de diagnóstico foi tocado. Arquivando a conta, tudo
   volta ao fallback.
2. **A invariante `total == banco + plataforma`** (AC2), em todos os caminhos — a garantia mecânica
   de que a composição nunca fica escondida. Somar plano 3 + plano 1 é a única soma que o design
   autoriza (§6.1), e só acompanhada de origem declarada e das duas parcelas em campos próprios.
3. **Os snapshots de DRE / Cockpit / Carteira** (IV1–IV3) — esta story mexe num endpoint que já
   está em produção, e o repo tem histórico de regressão só visível em Postgres real.
4. **AC8** — fora da semente, a projeção não mudou em nada: mesma fórmula de `burn_rate`, mesmas
   janelas cumulativas, mesmo tratamento de vencidos.

⚠️ Os testes da 5.7/8.1 em `test_financial_intelligence_projection.py` seguem verdes **sem edição
nenhuma** (IV4): eles rodam em tenant sem conta bancária, ou seja, no fallback. Os dois testes de
`test_bank_accounts.py` que afirmavam "cadastrar conta NÃO altera a projeção" **mudaram de
expectativa** — eles próprios nomeavam a Story 8.8 como a autorizada a mudá-los; ver o bloco de
comentário lá.

RLS/isolamento cross-tenant é validado à parte no Postgres real
(`test_financial_intelligence_projection_rls.py`, marcado `rls_e2e`) — aqui a suíte roda em SQLite
e a RLS não é exercida (ver `conftest.py`).
"""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money_planes import (
    ORIGEM_INDISPONIVEL,
    ORIGEM_MISTO,
    ORIGEM_PLATAFORMA,
    ORIGENS,
)
from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today
from app.modules.bank import service as bank_service
from app.modules.bank.models import (
    KIND_CHECKING,
    KIND_INVESTMENT,
    KIND_SAVINGS,
    BankAccount,
    BankBalanceCheckpoint,
    BankTransaction,
)
from app.modules.cockpit import service as cockpit_service
from app.modules.financial_intelligence import diagnostics as diagnostics_service
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import projection as projection_service
from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import Transaction

REGISTER = {
    "legal_name": "Caixa Misto ME",
    "document": "22333444000181",
    "slug": "caixamisto",
    "email": "misto@example.com",
    "name": "Marta",
    "password": "uma-senha-bem-grande",
}

TODAY = tenant_today(DEFAULT_TENANT_TIMEZONE)
# Abertura bem no passado: dá espaço para lançar movimento em qualquer data recente sem esbarrar na
# guarda `posted_at > opening_date` do service (Story 8.3).
OPENING = (TODAY - timedelta(days=60)).isoformat()


def _d(days: int) -> str:
    """Data ISO de hoje + `days` (âncora UTC, a mesma que o serviço usa)."""
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Helpers (todos pela rota HTTP — é a superfície que o front consome) ───────────────────────


def _conta(
    client: TestClient,
    headers,
    *,
    nome: str = "Itaú PJ",
    kind: str = KIND_CHECKING,
    opening: int = 0,
    number: str = "",
) -> dict:
    r = client.post(
        "/bank/accounts",
        json={
            "name": nome,
            "kind": kind,
            "number": number,
            "opening_balance_cents": opening,
            "opening_balance_is_known": True,
            "opening_date": OPENING,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _movimento(client: TestClient, headers, conta_id: str, *, cents: int, dias: int = -1) -> dict:
    r = client.post(
        f"/bank/accounts/{conta_id}/transactions",
        json={
            "posted_at": _d(dias),
            "amount_cents": cents,
            "description": "movimento de teste",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _arquivar(client: TestClient, headers, conta_id: str) -> None:
    r = client.post(f"/bank/accounts/{conta_id}/archive", headers=headers)
    assert r.status_code == 200, r.text


def _charge(client, headers, *, amount: int, due: str) -> dict:
    r = client.post(
        "/receivables/charges",
        json={"kind": "service", "method": "pix", "amount_cents": amount, "due_date": due},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _payable(client, headers, *, amount: int, due: str) -> dict:
    r = client.post(
        "/payables/bills",
        json={"description": "conta", "amount_cents": amount, "due_date": due},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _seed_available(client, headers, *, gross: int) -> int:
    """Semeia saldo DISPONÍVEL na Carteira via uma venda pix. Retorna o líquido (gross − split)."""
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "pix", "gross_cents": gross},
        headers=headers,
    ).json()
    assert tx["status"] == "available"
    return tx["net_cents"]


def _projection(client, headers) -> dict:
    r = client.get("/financial-intelligence/projection", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _window(body: dict, days: int) -> dict:
    return next(w for w in body["windows"] if w["days"] == days)


def _tem_nota(body: dict, trecho: str) -> bool:
    return any(trecho in n for n in body["notes"])


# ── AC1/AC2 — precedência e as duas parcelas ─────────────────────────────────────────────────


def test_sem_conta_bancaria_mantem_o_fallback_da_8_1(client: TestClient, headers):
    """**[AC1 caso 2 / AC4]** É o estado de TODO tenant hoje — e ele não pode ter mudado."""
    _seed_available(client, headers, gross=150_000)  # disponível 90000
    body = _projection(client, headers)

    assert body["saldo_inicial_origem"] == ORIGEM_PLATAFORMA
    assert body["saldo_inicial_cents"] == 90_000
    assert body["saldo_inicial_banco_cents"] == 0
    assert body["saldo_inicial_plataforma_cents"] == 90_000
    # A nota da 8.1 continua; a de composição da 8.8 NÃO aparece (seria mentira aqui).
    assert _tem_nota(body, "não da sua conta bancária")
    assert not _tem_nota(body, "soma DUAS parcelas")


def test_com_conta_corrente_a_origem_vira_misto_e_soma_as_duas_parcelas(
    client: TestClient, headers, db: Session
):
    """**[AC1 caso 1 / AC2 / AC7]** A parcela bancária é EXATAMENTE o saldo derivado da Story 8.2 —
    não uma soma recalculada aqui (a Regra dos Planos §1.3a só é auditável com UMA implementação).
    """
    _seed_available(client, headers, gross=150_000)  # plataforma 90000
    conta = _conta(client, headers, opening=1_000_000)
    _movimento(client, headers, conta["id"], cents=-250_000)  # saldo derivado 750000

    body = _projection(client, headers)

    assert body["saldo_inicial_origem"] == ORIGEM_MISTO
    assert body["saldo_inicial_banco_cents"] == 750_000
    assert body["saldo_inicial_plataforma_cents"] == 90_000
    assert body["saldo_inicial_cents"] == 840_000
    # A parcela bancária é o número do `bank.service`, não um cálculo paralelo.
    assert body["saldo_inicial_banco_cents"] == bank_service.active_balance_total(db, until=TODAY)
    # ...e a de plataforma é o número do `wallet_service`, também sem recálculo.
    assert (
        body["saldo_inicial_plataforma_cents"]
        == wallet_service.wallet_summary(db)["available_cents"]
    )
    assert _tem_nota(body, "soma DUAS parcelas")


def test_a_soma_das_parcelas_e_o_total_em_TODOS_os_caminhos(client: TestClient, headers):
    """**[AC2 — a invariante]** `total == banco + plataforma` em cada estado por que o tenant passa.

    Percorre a vida inteira do cadastro numa requisição por etapa: nada, só Carteira, conta zerada,
    conta com saldo, conta negativa, aplicação, arquivamento. Se a soma escapar em qualquer ponto,
    a composição deixou de ser confiável — e é a composição que autoriza a soma entre planos.
    """

    def _conferir(rotulo: str) -> dict:
        body = _projection(client, headers)
        assert body["saldo_inicial_cents"] == (
            body["saldo_inicial_banco_cents"] + body["saldo_inicial_plataforma_cents"]
        ), f"invariante quebrada em: {rotulo}"
        assert body["saldo_inicial_origem"] in ORIGENS
        return body

    _conferir("tenant vazio")
    _seed_available(client, headers, gross=150_000)
    _conferir("só Carteira")

    conta = _conta(client, headers, nome="Zerada", opening=0, number="1-1")
    _conferir("conta ativa com saldo zero")

    _movimento(client, headers, conta["id"], cents=500_000)
    _conferir("conta com saldo positivo")

    _movimento(client, headers, conta["id"], cents=-900_000)
    _conferir("conta em cheque especial (saldo negativo)")

    _conta(client, headers, nome="CDB", kind=KIND_INVESTMENT, opening=9_000_000, number="2-2")
    _conferir("com conta de aplicação")

    _arquivar(client, headers, conta["id"])
    _conferir("depois de arquivar a conta corrente")


def test_conta_nova_sem_saldo_ja_conta_como_misto(client: TestClient, headers):
    """**[AC1, o edge case da Task 2]** A decisão é pela EXISTÊNCIA da conta, nunca pelo valor.

    Conta recém-cadastrada com saldo de abertura 0 dá `misto` com parcela bancária 0 — o usuário já
    declarou onde o dinheiro dele mora, e a projeção passa a ter lastro. Decidir por `total != 0`
    faria o produto oscilar entre "sei" e "não sei" conforme o saldo cruzasse o zero.
    """
    _conta(client, headers, opening=0)
    body = _projection(client, headers)

    assert body["saldo_inicial_origem"] == ORIGEM_MISTO
    assert body["saldo_inicial_banco_cents"] == 0
    assert body["saldo_inicial_cents"] == 0


def test_saldo_bancario_negativo_soma_com_sinal(client: TestClient, headers):
    """Cheque especial é saldo legítimo e entra NEGATIVO — não é clampado em zero.

    Clampar esconderia a única situação em que o dono precisa mesmo saber quanto tem: a projeção
    partiria de um caixa maior do que o real, exatamente quando ele está apertado.
    """
    _seed_available(client, headers, gross=150_000)  # plataforma 90000
    conta = _conta(client, headers, opening=100_000)
    _movimento(client, headers, conta["id"], cents=-350_000)  # derivado −250000

    body = _projection(client, headers)
    assert body["saldo_inicial_banco_cents"] == -250_000
    assert body["saldo_inicial_cents"] == -160_000
    assert body["saldo_inicial_origem"] == ORIGEM_MISTO


def test_carteira_zerada_com_banco_cheio_ainda_expoe_as_duas_parcelas(
    client: TestClient, headers
):
    """**[AC2]** Parcela zerada continua sendo parcela: o campo não some quando o valor é 0.

    É o caso do usuário que saca tudo. Se a parcela de plataforma sumisse aqui, a UI teria dois
    formatos de resposta para tratar e o "esconder a composição" voltaria pela porta dos fundos.
    """
    conta = _conta(client, headers, opening=2_000_000)
    body = _projection(client, headers)

    assert body["saldo_inicial_plataforma_cents"] == 0
    assert body["saldo_inicial_banco_cents"] == 2_000_000
    assert body["saldo_inicial_cents"] == 2_000_000
    assert body["saldo_inicial_origem"] == ORIGEM_MISTO
    assert "saldo_inicial_plataforma_cents" in body, "a parcela zerada não pode sumir do payload"
    assert conta["id"]


# ── AC3 — aplicações e contas arquivadas ficam fora ──────────────────────────────────────────


def test_conta_de_aplicacao_nao_entra_no_saldo_inicial_e_a_nota_diz_isso(
    client: TestClient, headers
):
    """**[AC3]** Dinheiro aplicado não é caixa para pagar a conta de amanhã (design §6.1).

    A exclusão vem do `exclude_kinds` de `active_balance_total` (Story 8.2) — não de um filtro
    reimplementado aqui.
    """
    corrente = _conta(client, headers, nome="Corrente", opening=300_000, number="1-1")
    _conta(client, headers, nome="CDB", kind=KIND_INVESTMENT, opening=9_000_000, number="2-2")

    body = _projection(client, headers)
    assert body["saldo_inicial_banco_cents"] == 300_000, "a aplicação entrou no caixa"
    assert _tem_nota(body, "contas de aplicação NÃO entram")
    assert corrente["id"]


def test_poupanca_entra_no_caixa_mas_aplicacao_nao(client: TestClient, headers):
    """A exclusão é de `investment` e SÓ dela: poupança é resgatável e conta como caixa.

    Guarda contra um "endurecimento" futuro que exclua `savings` junto por parecer parecido — o
    dono conta com a poupança para pagar a conta de amanhã, e com o CDB não.
    """
    _conta(client, headers, nome="Poupança", kind=KIND_SAVINGS, opening=400_000, number="1-1")
    _conta(client, headers, nome="CDB", kind=KIND_INVESTMENT, opening=9_000_000, number="2-2")

    body = _projection(client, headers)
    assert body["saldo_inicial_banco_cents"] == 400_000
    assert body["saldo_inicial_origem"] == ORIGEM_MISTO


def test_so_conta_de_aplicacao_cai_no_fallback_mas_a_nota_explica(client: TestClient, headers):
    """O tenant que cadastrou **só** uma aplicação não tem caixa bancário — e precisa saber por quê.

    ⚠️ Aqui a nota da 8.1 (*"enquanto você não cadastrar sua conta…"*) sozinha seria confusa: ele
    ACABOU de cadastrar uma. É por isso que a nota do AC3 é emitida sempre que existe aplicação
    ativa, e não só sob `misto` (desvio declarado da Task 2, registrado nas Completion Notes).
    """
    _conta(client, headers, nome="CDB", kind=KIND_INVESTMENT, opening=9_000_000)

    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] == ORIGEM_PLATAFORMA
    assert body["saldo_inicial_banco_cents"] == 0
    assert _tem_nota(body, "contas de aplicação NÃO entram"), (
        "sem esta nota o produto pareceria não ter visto o cadastro que o usuário acabou de fazer"
    )


def test_conta_arquivada_nao_conta_nem_para_o_saldo_nem_para_a_origem(
    client: TestClient, headers
):
    """Conta encerrada some das superfícies do dia a dia (Story 8.2) — inclusive desta."""
    _seed_available(client, headers, gross=150_000)
    conta = _conta(client, headers, opening=800_000)
    assert _projection(client, headers)["saldo_inicial_origem"] == ORIGEM_MISTO

    _arquivar(client, headers, conta["id"])

    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] == ORIGEM_PLATAFORMA
    assert body["saldo_inicial_banco_cents"] == 0
    assert body["saldo_inicial_cents"] == 90_000


def test_movimento_ignorado_sai_do_saldo_inicial(client: TestClient, headers):
    """O filtro `status <> 'ignored'` mora DENTRO do saldo derivado (Story 8.3) — quem consome não
    refiltra, e este teste prova que a projeção herda o comportamento em vez de reimplementá-lo."""
    conta = _conta(client, headers, opening=1_000_000)
    mov = _movimento(client, headers, conta["id"], cents=-400_000)
    assert _projection(client, headers)["saldo_inicial_banco_cents"] == 600_000

    r = client.post(f"/bank/transactions/{mov['id']}/ignore", headers=headers)
    assert r.status_code == 200, r.text

    assert _projection(client, headers)["saldo_inicial_banco_cents"] == 1_000_000


# ── AC4 — a transição de estado, nos DOIS sentidos (o teste mais valioso da story) ────────────


def test_transicao_sem_conta_para_com_conta_restaura_o_runway(client: TestClient, headers):
    """**[AC4]** A MESMA requisição, antes e depois de cadastrar a primeira conta.

    A restauração é **por construção**: a condição de supressão da 8.1 é `origem ==
    ORIGEM_PLATAFORMA`, então trocar a origem devolve os dias sem que uma linha da lógica de runway
    tenha sido tocada. `burn_rate_cents_per_day` — que nunca esteve contaminado — fica IDÊNTICO.
    """
    _seed_available(client, headers, gross=150_000)  # plataforma 90000
    _payable(client, headers, amount=90_000, due=_d(10))  # queima 90000/90d = 1000/dia

    antes = _projection(client, headers)
    assert antes["saldo_inicial_origem"] == ORIGEM_PLATAFORMA
    assert antes["runway"]["days"] is None
    assert antes["runway"]["days_suprimido"] is True
    assert antes["runway"]["burn_rate_cents_per_day"] == 1000
    assert _tem_nota(antes, "não da sua conta bancária")
    assert _tem_nota(antes, "fôlego de caixa em dias não é exibido")

    _conta(client, headers, opening=810_000)  # banco 810000 + plataforma 90000 = 900000

    depois = _projection(client, headers)
    assert depois["saldo_inicial_origem"] == ORIGEM_MISTO
    assert depois["runway"]["days_suprimido"] is False
    assert depois["runway"]["days"] == 900, "900000 / 1000 por dia"
    assert depois["runway"]["burn_rate_cents_per_day"] == 1000, "a queima NÃO muda com o saldo"
    # As duas notas da 8.1 somem; a de composição entra.
    assert not _tem_nota(depois, "não da sua conta bancária")
    assert not _tem_nota(depois, "fôlego de caixa em dias não é exibido")
    assert _tem_nota(depois, "soma DUAS parcelas")


def test_transicao_com_conta_para_sem_conta_volta_a_suprimir(client: TestClient, headers):
    """**[AC4, o sentido de volta]** Arquivar a última conta devolve o tenant ao fallback da 8.1.

    O comportamento da 8.1 **não foi removido** — se ele tivesse sido, este caminho voltaria com um
    runway calculado sobre saldo sem lastro, que é o bug original de novo.
    """
    _seed_available(client, headers, gross=150_000)
    _payable(client, headers, amount=90_000, due=_d(10))
    conta = _conta(client, headers, opening=810_000)

    com_conta = _projection(client, headers)
    assert com_conta["runway"]["days"] == 900
    assert com_conta["runway"]["days_suprimido"] is False

    _arquivar(client, headers, conta["id"])

    sem_conta = _projection(client, headers)
    assert sem_conta["saldo_inicial_origem"] == ORIGEM_PLATAFORMA
    assert sem_conta["runway"]["days"] is None
    assert sem_conta["runway"]["days_suprimido"] is True
    assert sem_conta["runway"]["burn_rate_cents_per_day"] == 1000
    assert _tem_nota(sem_conta, "fôlego de caixa em dias não é exibido")


def test_transicao_restaura_tambem_o_alerta_de_janela(client: TestClient, headers):
    """**[AC4, ratificação D-5]** São DOIS sinais a restaurar, não um.

    O `alert` é suprimido **sem** a condição de queima (é por janela). Trocar a origem devolve o
    veredito pela mesma mecânica — e o `saldo_projetado_cents`, que nunca foi suprimido, fica
    idêntico exceto pela semente.
    """
    _payable(client, headers, amount=100_000, due=_d(10))  # janelas negativas

    antes = _projection(client, headers)
    for dias in (30, 60, 90):
        w = _window(antes, dias)
        assert w["saldo_projetado_cents"] == -100_000
        assert w["alert"] is False
        assert w["alert_suprimido"] is True
    assert _tem_nota(antes, "não afirma se o seu caixa fica negativo")

    _conta(client, headers, opening=0)  # conta ativa, saldo 0 → origem `misto`

    depois = _projection(client, headers)
    for dias in (30, 60, 90):
        w = _window(depois, dias)
        assert w["saldo_projetado_cents"] == -100_000, "o número nunca foi suprimido"
        assert w["alert"] is True, "o veredito volta — agora com lastro"
        assert w["alert_suprimido"] is False
    assert not _tem_nota(depois, "não afirma se o seu caixa fica negativo")


def test_misto_nao_transforma_sem_risco_em_numero(client: TestClient, headers):
    """**[AC4, o AC4 da 8.1 que continua valendo]** "Sem risco" e "não sei" nunca se confundem.

    Com origem `misto` e SEM queima, `runway.days` continua `None` — mas com `days_suprimido =
    False` e a nota de "sem risco". A story restaura o que estava calado; **não** inventa um número
    onde nunca houve um.
    """
    _seed_available(client, headers, gross=100_000)  # plataforma 60000
    _conta(client, headers, opening=500_000)
    _charge(client, headers, amount=80_000, due=_d(10))  # entrada líquida → caixa cresce

    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] == ORIGEM_MISTO
    assert body["runway"]["burn_rate_cents_per_day"] == 0
    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is False
    assert _tem_nota(body, "sem risco de runway")


def test_invariantes_de_supressao_continuam_valendo_sob_misto(client: TestClient, headers):
    """`days_suprimido ⇒ days is None` e `alert_suprimido ⇒ alert is False`, agora também no
    caminho novo. Nenhum consumidor deve precisar tratar "suprimido, mas com veredito"."""
    _seed_available(client, headers, gross=150_000)
    _conta(client, headers, opening=10_000)
    _payable(client, headers, amount=900_000, due=_d(10))
    _charge(client, headers, amount=5_000, due=_d(-1))

    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] == ORIGEM_MISTO
    if body["runway"]["days_suprimido"]:
        assert body["runway"]["days"] is None
    for w in body["windows"]:
        if w["alert_suprimido"]:
            assert w["alert"] is False


def test_o_sinal_de_projecao_reaparece_no_diagnostico(client: TestClient, headers, db: Session):
    """**[AC4 — o efeito colateral desejado, a prova de que o ciclo fechou de ponta a ponta]**

    A Story 8.1 fez os sinais de `source="projecao"` **desaparecerem** do `/financeiro/diagnostico`
    e registrou isso como silêncio temporário. Com o saldo de partida com lastro, eles voltam —
    **sem editar `engine.py` nem `diagnostics.py`**: `collect_engine_input` repassa
    `proj.runway.days` (agora um número) e `w.alert` (agora `True`), e o motor faz o resto.
    """
    _seed_available(client, headers, gross=150_000)  # plataforma 90000
    _payable(client, headers, amount=300_000, due=_d(10))  # janelas negativas + queima
    _conta(client, headers, opening=100_000)
    db.commit()

    entrada = diagnostics_service.collect_engine_input(db, start=TODAY, end=TODAY)
    assert entrada.runway_days is not None, "o motor voltou a receber dias — agora com lastro"
    assert any(w.alert for w in entrada.projection_windows)

    sinais = diagnostics_service.compute_signals(db, start=TODAY, end=TODAY)
    da_projecao = [s for s in sinais if s.source == "projecao"]
    assert da_projecao, "o diagnóstico deveria voltar a afirmar algo sobre a projeção"
    assert any("Projeção de caixa negativa" in s.title for s in da_projecao)
    assert any("unway" in s.title for s in da_projecao), "o sinal de runway também volta"


# ── AC8 — fora da semente, nada mudou ────────────────────────────────────────────────────────


def test_a_formula_do_burn_nao_depende_do_saldo_inicial(client: TestClient, headers, db: Session):
    """**[AC8]** Variando APENAS o saldo inicial, `burn_rate_cents_per_day` fica idêntico e
    `runway.days` muda só na proporção do saldo. A story mexeu na semente, não na fórmula."""
    _payable(client, headers, amount=180_000, due=_d(10))  # queima 180000/90 = 2000/dia
    conta = _conta(client, headers, opening=200_000)

    primeiro = _projection(client, headers)
    assert primeiro["runway"]["burn_rate_cents_per_day"] == 2000
    assert primeiro["runway"]["days"] == 100  # 200000 / 2000

    _movimento(client, headers, conta["id"], cents=200_000)  # dobra SÓ o saldo inicial

    segundo = _projection(client, headers)
    assert segundo["saldo_inicial_cents"] == 400_000
    assert segundo["runway"]["burn_rate_cents_per_day"] == 2000, "a queima não pode ter mudado"
    assert segundo["runway"]["days"] == 200, "o dobro do saldo, o dobro dos dias"
    # As janelas andaram exatamente o delta do saldo, e nada mais.
    for w1, w2 in zip(primeiro["windows"], segundo["windows"], strict=True):
        assert w2["saldo_projetado_cents"] == w1["saldo_projetado_cents"] + 200_000
    assert db  # o `db` fixture garante o schema criado; nada é lido dele aqui


def test_vencidos_e_regime_de_caixa_seguem_iguais_sob_misto(client: TestClient, headers):
    """**[AC8]** Vencidos-em-aberto continuam entrando em TODAS as janelas e expostos à parte; o
    regime continua sendo `due_date`. A origem `misto` não toca em nada disso."""
    _conta(client, headers, opening=50_000)
    _charge(client, headers, amount=40_000, due=_d(-5))
    _payable(client, headers, amount=10_000, due=_d(-3))
    _charge(client, headers, amount=5_000, due=_d(20))

    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] == ORIGEM_MISTO
    for dias in (30, 60, 90):
        assert _window(body, dias)["saldo_projetado_cents"] == 50_000 + 35_000
    assert body["overdue_inflow_cents"] == 40_000
    assert body["overdue_outflow_cents"] == 10_000
    assert _tem_nota(body, "VENCIDOS")


# ── AC7 / Regra dos Planos ───────────────────────────────────────────────────────────────────

_SALDO_FIELD = re.compile(r"^saldo_(?P<base>.+)_cents$")

# ⚠️ **Allowlist com justificativa escrita** (mesmo padrão de `test_tenancy_guard.py` e de
# `test_money_planes.test_bank_nao_referencia_transaction`): estes dois campos NÃO recebem um irmão
# `*_origem` próprio, e não é esquecimento.
#
# Eles não são dois saldos independentes que precisam se identificar — são **a decomposição
# declarada** de `saldo_inicial_cents`, cuja origem é `saldo_inicial_origem = "misto"`. E `misto` é,
# por definição (`app.core.money_planes`), *"a soma rotulada dos planos 3 + 1"*: o nome de cada
# parcela **é** o valor de `ORIGENS` a que ela pertence (`banco`, `plataforma`), sem espaço para
# outra leitura. Um `saldo_inicial_banco_origem="banco"` constante não poderia carregar informação
# nenhuma; o que precisa ser aferido no lugar dele é que a decomposição usa o vocabulário canônico e
# que a soma fecha — e é isso que `test_todo_saldo_da_projecao_declara_origem` faz abaixo.
#
# Se o @architect preferir os irmãos redundantes no gate, a mudança é aditiva e cabe em duas linhas
# no schema; registrado nas Completion Notes da Story 8.8.
_PARCELAS_DE_SALDO_INICIAL = frozenset(
    {"saldo_inicial_banco_cents", "saldo_inicial_plataforma_cents"}
)


def _campos_de_saldo_sem_origem(payload: dict) -> list[str]:
    """Campos `saldo_*_cents` sem o irmão `*_origem` no MESMO objeto (Regra dos Planos §1.3c).

    Varredura **por instância**, no payload real da rota — o mesmo tratamento que as Stories
    8.2–8.5 deram à regra. O gate GLOBAL (`test_todo_saldo_declara_origem`, varrendo todo schema de
    saída do projeto) foi atribuído à Story 8.1 e nunca criado; criá-lo é decisão de @po/@architect,
    não desta story. Registrado em Completion Notes.
    """
    return [
        chave
        for chave in payload
        if (m := _SALDO_FIELD.match(chave))
        and chave not in _PARCELAS_DE_SALDO_INICIAL
        and f"saldo_{m.group('base')}_origem" not in payload
    ]


def test_todo_saldo_da_projecao_declara_origem(client: TestClient, headers):
    """**[AC7 / §1.3c]** Nenhum saldo trafega sem procedência — nos dois estados da story."""
    for rotulo in ("fallback", "misto"):
        body = _projection(client, headers)
        assert _campos_de_saldo_sem_origem(body) == [], (
            f"campo de saldo sem o irmão *_origem em {rotulo}: "
            f"{_campos_de_saldo_sem_origem(body)}"
        )
        assert body["saldo_inicial_origem"] in ORIGENS
        # A decomposição usa o vocabulário canônico do eixo A, e a soma fecha — é o que substitui
        # o irmão `*_origem` de cada parcela (ver a allowlist acima).
        assert {"banco", "plataforma"} <= ORIGENS
        assert body["saldo_inicial_cents"] == (
            body["saldo_inicial_banco_cents"] + body["saldo_inicial_plataforma_cents"]
        )
        # ...e `misto` aparece exatamente quando a parcela bancária tem lastro para existir.
        if body["saldo_inicial_origem"] == ORIGEM_MISTO:
            assert "saldo_inicial_banco_cents" in body
        else:
            assert body["saldo_inicial_banco_cents"] == 0
        if rotulo == "fallback":
            _conta(client, headers, opening=123_456)


def test_a_projecao_nao_reimplementa_o_saldo_bancario(client: TestClient, headers):
    """**[AC7]** A parcela bancária vem de `bank.service` — nada de somar conta por conta aqui.

    Varredura estática no espírito de `test_money_planes.py`: o módulo da projeção não pode tocar
    nos MODELOS do banco (`BankAccount`/`BankTransaction`), só no service. Tocar no modelo é o
    primeiro passo para reescrever a fórmula do design §3.1 uma segunda vez — e uma segunda
    implementação torna a Regra dos Planos §1.3a inauditável.
    """
    import ast
    import pathlib

    # ⚠️ AST, **nunca** `grep` — mesma razão documentada em `test_money_planes._imported_modules`:
    # a prosa da docstring deste módulo PRECISA poder citar `bank_transactions` e os modelos por
    # nome (é onde a Regra dos Planos está explicada). Um teste por texto cru reprovaria justamente
    # a documentação que existe para impedir a violação.
    fonte = pathlib.Path(projection_service.__file__).read_text(encoding="utf-8")
    tree = ast.parse(fonte)
    proibidos = {"BankAccount", "BankTransaction", "BankBalanceCheckpoint"}
    achados = [
        f"{type(node).__name__}:{nome}"
        for node in ast.walk(tree)
        if (
            (isinstance(node, ast.Name) and (nome := node.id) in proibidos)
            or (isinstance(node, ast.Attribute) and (nome := node.attr) in proibidos)
            or (isinstance(node, ast.alias) and (nome := node.name.split(".")[-1]) in proibidos)
        )
    ]
    assert not achados, (
        f"projection.py referencia modelos do banco: {achados}. A parcela 'no banco' deve vir "
        "inteira de `bank.service.active_balance_total` (Story 8.2) — uma segunda implementação da "
        "fórmula do design §3.1 torna a Regra dos Planos §1.3a inauditável."
    )
    assert client and headers  # fixtures mantidas para simetria com o resto do arquivo


# ── IV1–IV3 — as outras superfícies financeiras não se mexeram ───────────────────────────────


def _seed_movimento_financeiro(client: TestClient, headers) -> None:
    _seed_available(client, headers, gross=150_000)
    _charge(client, headers, amount=300_000, due=_d(5))
    _payable(client, headers, amount=120_000, due=_d(7))


def test_movimento_bancario_nao_altera_dre(client: TestClient, headers, db: Session):
    """**[IV1]** `dre.py` agrega `charges` + `payables` + `transactions`. Nenhuma tabela do módulo
    `bank` é uma delas, nem agora nem nunca (design §3.5/§6.4). Snapshot campo a campo, com conta,
    movimento **e** checkpoint existindo — o cenário completo da Onda 1."""
    _seed_movimento_financeiro(client, headers)
    inicio, fim = TODAY - timedelta(days=90), TODAY + timedelta(days=90)
    antes_dre = asdict(dre_service.dre_report(db, start=inicio, end=fim))

    conta = _conta(client, headers, opening=5_000_000)
    _movimento(client, headers, conta["id"], cents=-777_000)
    r = client.post(
        f"/bank/accounts/{conta['id']}/checkpoints",
        json={
            "reference_date": _d(0),
            "balance_cents": 4_000_000,
            "origin": "manual",
        },
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text

    depois_dre = asdict(dre_service.dre_report(db, start=inicio, end=fim))
    assert depois_dre == antes_dre, (
        "A DRE mudou depois de existirem conta/movimento/checkpoint bancários. Saldo de conta não "
        "é receita nem despesa de competência — se entrou na DRE, entrou como número inventado."
    )


def test_dre_e_lucratividade_nao_importam_o_modulo_bank(client: TestClient, headers):
    """**[IV1, a versão permanente]** O impacto zero da DRE e da Lucratividade é *por construção*.

    O snapshot acima prova o estado de hoje; esta varredura estática prova a **regra**: `dre.py`
    agrega exatamente `charges` + `payables` + `transactions`, e `profitability.py` deriva da DRE.
    Nenhuma tabela do módulo `bank` é uma delas — *"nem agora nem nunca"* (design §3.5/§6.4). Só a
    **projeção** ganhou o direito de ler o plano 3 nesta story; se amanhã a DRE também ganhar, que
    seja por uma decisão escrita, não por um import que passou despercebido numa PR.

    Mesmo estilo (AST, nunca `grep`) de `test_money_planes.py`: a prosa das docstrings precisa poder
    citar o módulo sem reprovar o teste.
    """
    import ast
    import pathlib

    from app.modules.financial_intelligence import profitability as profitability_service

    for modulo in (dre_service, profitability_service):
        caminho = pathlib.Path(modulo.__file__)
        tree = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
        importados: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                importados.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                # ⚠️ O alias entra no caminho (`app.modules` + `bank` → `app.modules.bank`).
                # Sem isso, `from app.modules import bank` dentro de `dre.py` produzia só
                # `"app.modules"`, que não casa com o `startswith` abaixo — e o gate ficava verde
                # com a DRE importando o plano 3. Verificado por mutação no re-gate do Epic 8
                # (2026-07-30); mesma correção já aplicada em `test_money_planes.py`,
                # `test_financial_intelligence_completeness.py` e
                # `test_bank_reconciliation_report.py`. Note que o OUTRO coletor deste arquivo
                # (`test_a_projecao_nao_reimplementa_o_saldo_bancario`) nunca teve o furo, porque
                # varre `ast.alias` — foi o que fez este passar despercebido na primeira rodada.
                base = f"{'.' * node.level}{node.module or ''}"
                importados.append(base)
                sep = "" if base.endswith(".") else "."
                importados.extend(f"{base}{sep}{a.name}" for a in node.names)
        ofensores = [m for m in importados if m.startswith("app.modules.bank")]
        assert not ofensores, (
            f"{caminho.name} passou a importar o módulo `bank`: {ofensores}. Saldo de conta não é "
            "receita nem despesa de competência — se entrou na DRE, entrou como número inventado."
        )
    assert client and headers


def test_cockpit_e_carteira_intactos(client: TestClient, headers, db: Session):
    """**[IV2 / IV3]** `cockpit.finance_summary` (faturamento líquido) e `wallet_summary` devolvem
    EXATAMENTE os mesmos números depois de existir saldo bancário. Esta story só LÊ a Carteira; o
    card "Em conta" do Cockpit é Onda 6 e está fora daqui."""
    _seed_movimento_financeiro(client, headers)
    antes_cockpit = cockpit_service.finance_summary(db)
    antes_wallet = wallet_service.wallet_summary(db)

    conta = _conta(client, headers, opening=5_000_000)
    _movimento(client, headers, conta["id"], cents=-777_000)

    assert cockpit_service.finance_summary(db) == antes_cockpit
    depois_wallet = wallet_service.wallet_summary(db)
    assert depois_wallet == antes_wallet
    for campo in (
        "available_cents",
        "pending_cents",
        "withdrawn_cents",
        "gross_total_cents",
        "fees_total_cents",
    ):
        assert depois_wallet[campo] == antes_wallet[campo], f"campo contaminado: {campo}"


# ── IV5 — read-only, agora incluindo as tabelas do `bank` ────────────────────────────────────


def _snapshot(db: Session) -> dict:
    """Fotografia do estado que a projeção JAMAIS pode alterar (IV5).

    Extensão do `test_projection_is_read_only` da 5.7 com as tabelas do módulo `bank`: a partir
    desta story a projeção LÊ o plano 3, e ler é a porta de entrada para escrever sem querer (um
    `db.add` de "ajuste", um saldo materializado "para ir mais rápido"). O design §3.1 é explícito:
    o saldo é DERIVADO e não se materializa em lugar nenhum.
    """
    db.expire_all()
    return {
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
        "bank_accounts": {
            a.id: (a.kind, a.opening_balance_cents, a.opening_date, a.archived_at, a.is_primary)
            for a in db.scalars(select(BankAccount)).all()
        },
        "bank_transactions": {
            t.id: (t.posted_at, t.amount_cents, t.status, t.bank_account_id)
            for t in db.scalars(select(BankTransaction)).all()
        },
        "bank_checkpoints": {
            c.id: (c.reference_date, c.balance_cents, c.origin)
            for c in db.scalars(select(BankBalanceCheckpoint)).all()
        },
    }


def test_projection_com_banco_continua_read_only(client: TestClient, headers, db: Session):
    _seed_movimento_financeiro(client, headers)
    conta = _conta(client, headers, opening=1_000_000)
    _movimento(client, headers, conta["id"], cents=-250_000)

    before = _snapshot(db)
    _projection(client, headers)
    _projection(client, headers)
    after = _snapshot(db)

    assert after == before, "a projeção escreveu/alterou dados — viola IV5 (read-only)"


# ── Story 8.21 — "tenho a conta e NÃO sei o saldo" ────────────────────────────────────────────
#
# O gate desta story: a coluna `opening_balance_is_known` não pode existir sem o consumidor
# provado. `core/whatsapp/capabilities.py` existiu desde a Onda 0 com ZERO call sites em produção
# e uma docstring que AFIRMAVA três consumidores inexistentes — foi essa afirmação que impediu
# alguém de notar a lacuna. Regra derivada: capacidade nova nasce com o consumidor no mesmo passo.


def _conta_sem_saldo(client, headers, *, nome: str, number: str = "") -> dict:
    """Conta cadastrada por quem NÃO sabe o saldo — o cenário inteiro da Story 8.21."""
    r = client.post(
        "/bank/accounts",
        json={
            "name": nome,
            "kind": KIND_CHECKING,
            "number": number,
            "opening_balance_is_known": False,
            "opening_date": OPENING,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_conta_sem_saldo_declarado_cala_a_projecao(client: TestClient, headers):
    """AC4 + AC9 — o gate do consumidor, e o teste de MAIOR VALOR da story.

    Sem ele a coluna vira documentação em vez de comportamento: o dado existe, ninguém o lê, e o
    produto continua afirmando runway sobre um saldo que ninguém informou.
    """
    _conta_sem_saldo(client, headers, nome="C6 PJ")
    # Queima real, senão `days_suprimido` seria trivialmente falso (ele exige `burn_rate > 0`) e o
    # teste passaria sem provar nada.
    _payable(client, headers, amount=600_00, due=_d(10))

    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] == ORIGEM_INDISPONIVEL
    assert body["saldo_inicial_origem"] in ORIGENS
    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is True
    for w in body["windows"]:
        assert w["alert"] is False
        assert w["alert_suprimido"] is True


def test_uma_conhecida_e_uma_NAO_conhecida_calam_a_projecao_inteira(client: TestClient, headers):
    """AC4, o caso MISTO — decidido pela @architect e o mais provável na prática.

    ⚠️ **É este teste que prova que a regra é "QUALQUER desconhecida", e não "todas".** Sem ele,
    a implementação `if not conhecidas:` passa no teste anterior e mente em produção.

    Por que suprimir tudo em vez de somar só as conhecidas: `opening_balance_cents` **pode ser
    negativo** (cheque especial), então a parcela que falta tanto subestima quanto superestima o
    caixa — e nada na tela diria em qual direção. Subestimar dispara alerta sem motivo;
    superestimar CALA o alerta que deveria soar, para quem tem cheque especial.
    """
    _conta(client, headers, nome="Itaú PJ", opening=10_000_00, number="1")
    _conta_sem_saldo(client, headers, nome="C6 PJ", number="2")
    _payable(client, headers, amount=600_00, due=_d(10))

    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] == ORIGEM_INDISPONIVEL
    assert body["runway"]["days"] is None
    assert all(w["alert_suprimido"] for w in body["windows"])


def test_todas_conhecidas_seguem_misto(client: TestClient, headers):
    """O NÃO-MEMBRO do AC4. Sem ele, "sempre indisponível" passaria no teste acima."""
    _conta(client, headers, nome="Itaú PJ", opening=10_000_00, number="1")
    _conta(client, headers, nome="Nubank PJ", opening=5_000_00, number="2")
    assert _projection(client, headers)["saldo_inicial_origem"] == ORIGEM_MISTO


def test_o_numero_sobrevive_a_supressao_e_a_nota_NOMEIA_a_saida(client: TestClient, headers):
    """AC4 (a) e (b) — as duas obrigações que a @architect anexou à supressão.

    Sem (a) a story violaria o princípio da Onda 0 (*suprimir a afirmação, nunca o número*); sem
    (b) o dono vê o runway sumir e não descobre o que fazer — o beco sem saída do WhatsApp
    item 12(b), em que a única saída oferecida era um template que não existia.
    """
    _conta(client, headers, nome="Itaú PJ", opening=10_000_00, number="1")
    _conta_sem_saldo(client, headers, nome="C6 PJ", number="2")

    body = _projection(client, headers)
    # (a) o número continua lá, e a composição continua fechando.
    assert body["saldo_inicial_cents"] == (
        body["saldo_inicial_banco_cents"] + body["saldo_inicial_plataforma_cents"]
    )
    assert body["saldo_inicial_banco_cents"] == 10_000_00
    # (b) a nota diz QUAL conta falta — asserção sobre a presença e sobre o NOME, nunca sobre a
    # frase inteira (a redação muda; o nome da conta é o que torna a nota acionável).
    assert _tem_nota(body, "C6 PJ")
