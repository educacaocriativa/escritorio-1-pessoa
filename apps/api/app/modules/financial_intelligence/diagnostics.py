"""Orquestração read-only do diagnóstico (Story 5.8, AC1, IV3).

Camada FINA de I/O que separa o mundo com efeito colateral (queries) do motor PURO (`engine.py`):
busca as saídas já calculadas das Stories 5.4 (lucratividade por contrato), 5.6 (rentabilidade de
investimento) e 5.7 (projeção + runway), ADAPTA para as entradas do motor e chama
`engine.compute_signals(...)`. Nada aqui decide um sinal — essa é a responsabilidade do engine puro.

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


def collect_engine_input(db: Session, *, start: date, end: date) -> engine.EngineInput:
    """Monta o snapshot de entrada do motor a partir das fontes já calculadas (5.4/5.6/5.7).
    Toda a leitura de banco acontece AQUI — o motor recebe só dados puros."""
    proj = projection_service.cash_projection(db)
    return engine.EngineInput(
        margins=_margin_trends(db, start=start, end=end),
        runway_days=proj.runway.days,
        projection_windows=[
            engine.ProjectionWindowInput(days=w.days, alert=w.alert) for w in proj.windows
        ],
        investments=_investment_returns(db, start=start, end=end),
    )


def compute_signals(db: Session, *, start: date, end: date) -> list[engine.Signal]:
    """Busca os dados (I/O) e delega ao motor puro. Ponto único de orquestração dos sinais."""
    return engine.compute_signals(collect_engine_input(db, start=start, end=end))
