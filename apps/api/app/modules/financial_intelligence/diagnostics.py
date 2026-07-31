"""Orquestração read-only do diagnóstico (Story 5.8, AC1, IV3).

Camada FINA de I/O que separa o mundo com efeito colateral (queries) do motor PURO (`engine.py`):
busca as saídas já calculadas das Stories 5.4 (lucratividade por contrato), 5.6 (rentabilidade de
investimento), 5.7 (projeção + runway) e 8.5 (conferência bancária, por conta), ADAPTA para as
entradas do motor e chama `engine.compute_signals(...)`. Nada aqui decide um sinal — essa é a
responsabilidade do engine puro.

⚠️ **Toda query desta story mora aqui** (Story 8.6, AC7). Se um dia parecer necessário buscar algo
"só o nome da conta", "só contar checkpoints" de dentro do `engine.py`, a resposta é sempre a
mesma: monta-se aqui e passa-se pronto. É essa fronteira que mantém o motor testável sem banco.

SOMENTE LEITURA: não escreve no banco. (O único write do módulo é o rastro de IA, feito pelo
`ai_narrator` quando a narrativa é gerada — ver router.)

[AUTO-DECISION] Comparação de margem período-a-período: usamos o período pedido `[start, end]` como
"depois" e a janela de MESMA duração imediatamente anterior como "antes" (a Story 5.4 já calcula a
DRE de um contrato para qualquer intervalo; aqui só a chamamos duas vezes por contrato). Só
contratos ASSINADOS entram (ativos) — rascunhos/cancelados não representam operação corrente.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.modules.bank import reconciliation as bank_reconciliation
from app.modules.contracts import service as contracts_service
from app.modules.contracts.models import STATUS_SIGNED
from app.modules.financial_intelligence import engine
from app.modules.financial_intelligence import profitability as profitability_service
from app.modules.financial_intelligence import projection as projection_service
from app.modules.investments import service as investments_service


def _previous_period(start: date, end: date) -> tuple[date, date]:
    """Janela anterior de MESMA duração, imediatamente antes de `[start, end]`. Determinística."""
    span = end - start
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - span
    return prev_start, prev_end


def _period_label(start: date, end: date) -> str:
    """Rótulo humano da janela de comparação (não é PII). Aproxima em meses de 30 dias; para janelas
    < 1 mês, usa dias — apenas exibição, o número canônico do sinal é a margem em si."""
    days = (end - start).days + 1
    months = round(days / 30)
    if months >= 1:
        return f"{months} {'mês' if months == 1 else 'meses'}"
    return f"{days} {'dia' if days == 1 else 'dias'}"


def _margin_trends(db: Session, *, start: date, end: date) -> list[engine.MarginTrend]:
    """Para cada contrato ASSINADO: margem de contribuição do período atual vs. do período anterior
    (Story 5.4, `margem_contribuicao_pct`). Alimenta a Regra 1 do motor."""
    prev_start, prev_end = _previous_period(start, end)
    label = _period_label(start, end)
    trends: list[engine.MarginTrend] = []
    for contract in contracts_service.list_contracts(db, status=STATUS_SIGNED):
        atual = profitability_service.contract_dre(db, contract=contract, start=start, end=end)
        anterior = profitability_service.contract_dre(
            db, contract=contract, start=prev_start, end=prev_end
        )
        trends.append(
            engine.MarginTrend(
                project_name=contract.title,
                margem_pct_antes=anterior.margem_contribuicao_pct,
                margem_pct_depois=atual.margem_contribuicao_pct,
                period_label=label,
            )
        )
    return trends


def _investment_returns(db: Session, *, start: date, end: date) -> list[engine.InvestmentReturn]:
    """Rentabilidade do período de cada aplicação (Story 5.6). Alimenta a Regra 4 do motor."""
    out: list[engine.InvestmentReturn] = []
    for acc in investments_service.list_accounts(db):
        rent = investments_service.rentability(db, account_id=acc.id, start=start, end=end)
        out.append(
            engine.InvestmentReturn(
                name=acc.name,
                period_rentability_pct=rent["period_rentability_pct"],
            )
        )
    return out


def _completeness(
    db: Session, *, start: date, end: date, today: date | None = None
) -> engine.CompletenessInput:
    """A completude dos lançamentos (Story 8.6, AC7) — **a única I/O nova desta story**.

    Chama a conferência da Story 8.5 (`bank.reconciliation.reconciliation_report`, read-only) e
    **adapta** o relatório para a entrada do motor: uma `CompletenessAccountInput` por
    `ConferenciaConta`, mapeada **1:1**, sem agregação nenhuma. Não existe `max()` de
    `dias_desde_ultima_conferencia` aqui: colapsar as contas perderia *qual* delas está
    desatualizada, que é exatamente o que a decisão do fundador F3 proíbe (ratificação D-2
    Ajuste 1). A 8.5 já entrega o valor por conta; esta camada só para de descartá-lo.

    Tenant sem conta bancária (o estado de **todos** os tenants no dia do deploy) → `contas=[]`, e
    é o motor que transforma isso no 🟡 "não sei se os seus lançamentos estão completos". Nenhum
    caminho aqui levanta exceção por ausência de conta — `reconciliation_report` sem
    `bank_account_id` lista as contas ativas e devolve relatório vazio quando não há nenhuma.

    **Direção da dependência:** `financial_intelligence` → `bank` é a permitida (a proibida, pela
    Regra dos Planos §1.3b, é `wallet` → `bank`, coberta por `test_money_planes.py`). `bank` não
    importa `financial_intelligence`, então não há ciclo.
    """
    report = bank_reconciliation.reconciliation_report(db, start=start, end=end, today=today)
    return engine.CompletenessInput(
        contas=[
            engine.CompletenessAccountInput(
                account_name=c.bank_account_name,
                divergencia_cents=c.divergencia_cents,
                tolerancia_cents=c.tolerancia_cents,
                dias_desde_ultima_conferencia=c.dias_desde_ultima_conferencia,
            )
            for c in report.contas
        ],
        # 0 LITERAL — a Onda 1 não tem conciliação (`bank_reconciliations` é da Onda 4), então
        # "movimento sem contrapartida" não é aferível. PROIBIDO aproximar por "movimentos
        # unmatched": na Onda 1 todos são, e esse número alimenta o gate do epic §3.1. A regra já
        # está escrita no motor e acorda na Onda 3 trocando este zero pela contagem real.
        movimentos_sem_contrapartida=0,
    )


def collect_engine_input(
    db: Session, *, start: date, end: date, today: date | None = None
) -> engine.EngineInput:
    """Monta o snapshot de entrada do motor a partir das fontes já calculadas (5.4/5.6/5.7) e da
    conferência bancária (8.5). Toda a leitura de banco acontece AQUI — o motor recebe só dados
    puros. `today` é injetável (default = hoje em UTC dentro da conferência) apenas para tornar o
    contador de "dias desde a última conferência" testável, como em `bank.reconciliation`."""
    proj = projection_service.cash_projection(db)
    return engine.EngineInput(
        margins=_margin_trends(db, start=start, end=end),
        runway_days=proj.runway.days,
        projection_windows=[
            engine.ProjectionWindowInput(days=w.days, alert=w.alert) for w in proj.windows
        ],
        investments=_investment_returns(db, start=start, end=end),
        completeness=_completeness(db, start=start, end=end, today=today),
    )


def compute_signals(
    db: Session, *, start: date, end: date, today: date | None = None
) -> list[engine.Signal]:
    """Busca os dados (I/O) e delega ao motor puro. Ponto único de orquestração dos sinais."""
    return engine.compute_signals(collect_engine_input(db, start=start, end=end, today=today))
