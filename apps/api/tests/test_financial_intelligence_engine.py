"""Testes UNITÁRIOS PUROS do motor de diagnóstico (Story 5.8, Task 4 — críticos p/ IV1/NFR3).

100% sem banco e sem rede: só `engine.compute_signals(...)` com inputs Python fabricados. Cada
regra determinística é testada isoladamente nos seus limiares, mais a priorização e — o teste
CENTRAL do IV1 — o determinismo byte-a-byte (a MESMA entrada produz SEMPRE a MESMA saída, provando
que nenhuma IA pode ter influenciado os sinais: a IA sequer é importável a partir daqui).
"""
from __future__ import annotations

from app.modules.financial_intelligence.engine import (
    AMARELO,
    VERDE,
    VERMELHO,
    EngineInput,
    InvestmentReturn,
    MarginTrend,
    ProjectionWindowInput,
    Signal,
    compute_signals,
)


def _input(
    *,
    margins: list[MarginTrend] | None = None,
    runway_days: int | None = None,
    windows: list[ProjectionWindowInput] | None = None,
    investments: list[InvestmentReturn] | None = None,
) -> EngineInput:
    return EngineInput(
        margins=margins or [],
        runway_days=runway_days,
        projection_windows=windows or [],
        investments=investments or [],
    )


# ── Regra 1: margem de projeto caindo ───────────────────────────────────────────────────────
def test_margin_drop_yellow_at_threshold() -> None:
    # queda de 8 p.p. (0.30 → 0.22) → 🟡
    m = MarginTrend("Alpha", 0.30, 0.22, "1 mês")
    signals = compute_signals(_input(margins=[m]))
    assert len(signals) == 1
    assert signals[0].level == AMARELO
    assert "30%→22%" in signals[0].explanation
    assert "Alpha" in signals[0].explanation


def test_margin_drop_red_above_15pp() -> None:
    # queda de 16 p.p. (0.40 → 0.24) → 🔴
    signals = compute_signals(_input(margins=[MarginTrend("Beta", 0.40, 0.24, "1 mês")]))
    assert signals[0].level == VERMELHO


def test_margin_negative_is_red_regardless_of_small_drop() -> None:
    # margem final negativa → 🔴 mesmo com queda pequena (5 p.p.)
    signals = compute_signals(_input(margins=[MarginTrend("Gamma", 0.03, -0.02, "1 mês")]))
    assert signals[0].level == VERMELHO
    assert "-2%" in signals[0].explanation


def test_margin_small_drop_no_signal() -> None:
    # queda de 3 p.p. (< 8) e margem positiva → nenhum sinal
    assert compute_signals(_input(margins=[MarginTrend("Delta", 0.30, 0.27, "1 mês")])) == []


def test_margin_none_period_skipped() -> None:
    # sem receita em algum período (pct None) → não há tendência a diagnosticar
    assert compute_signals(_input(margins=[MarginTrend("Eps", None, 0.10, "1 mês")])) == []
    assert compute_signals(_input(margins=[MarginTrend("Eps", 0.20, None, "1 mês")])) == []


# ── Regra 2: runway curto ───────────────────────────────────────────────────────────────────
def test_runway_red_below_60() -> None:
    s = compute_signals(_input(runway_days=45))
    assert s[0].level == VERMELHO and "60" in s[0].explanation


def test_runway_yellow_below_120() -> None:
    s = compute_signals(_input(runway_days=90))
    assert s[0].level == AMARELO and "120" in s[0].explanation


def test_runway_green_when_healthy() -> None:
    s = compute_signals(_input(runway_days=200))
    assert s[0].level == VERDE and "200" in s[0].explanation


def test_runway_none_no_signal() -> None:
    # None = caixa não está sendo queimado (estável) → nenhum sinal
    assert compute_signals(_input(runway_days=None)) == []


# ── Regra 3: janela de projeção negativa (reuso do campo `alert` da 5.7) ─────────────────────
def test_projection_window_alert_propagates_red_without_recompute() -> None:
    windows = [
        ProjectionWindowInput(30, False),
        ProjectionWindowInput(60, True),
        ProjectionWindowInput(90, True),
    ]
    signals = compute_signals(_input(windows=windows))
    reds = [s for s in signals if s.level == VERMELHO]
    assert len(reds) == 2
    assert "60 dias" in reds[0].explanation
    assert "90 dias" in reds[1].explanation


# ── Regra 4: investimento sem rendimento no período ─────────────────────────────────────────
def test_investment_zero_or_negative_yields_yellow() -> None:
    s = compute_signals(_input(investments=[InvestmentReturn("CDB X", -0.02)]))
    assert s[0].level == AMARELO and "-2.0%" in s[0].explanation
    s0 = compute_signals(_input(investments=[InvestmentReturn("CDB Y", 0.0)]))
    assert s0[0].level == AMARELO


def test_investment_positive_no_signal_and_none_skipped() -> None:
    assert compute_signals(_input(investments=[InvestmentReturn("CDB Z", 0.01)])) == []
    assert compute_signals(_input(investments=[InvestmentReturn("Sem principal", None)])) == []


# ── Priorização: vermelho > amarelo > verde ─────────────────────────────────────────────────
def test_priority_orders_red_first() -> None:
    data = _input(
        margins=[MarginTrend("Amarelo", 0.30, 0.22, "1 mês")],  # 🟡
        runway_days=200,  # 🟢
        windows=[ProjectionWindowInput(30, True)],  # 🔴
    )
    signals = compute_signals(data)
    levels = [s.level for s in signals]
    assert levels == [VERMELHO, AMARELO, VERDE]


# ── IV1 (teste CENTRAL): determinismo byte-a-byte ───────────────────────────────────────────
def test_iv1_same_input_same_output_deterministic() -> None:
    """O MESMO input (sem tocar em core.ai) produz a MESMA lista de sinais — prova que o motor é
    determinístico e que a IA não pode ter originado nenhum número. A arquitetura pura do engine já
    garante isso; este teste documenta e trava a garantia (regressão)."""
    data = _input(
        margins=[
            MarginTrend("Alpha", 0.40, 0.24, "1 mês"),
            MarginTrend("Beta", 0.30, 0.27, "1 mês"),  # sem sinal
        ],
        runway_days=45,
        windows=[ProjectionWindowInput(60, True)],
        investments=[InvestmentReturn("CDB", -0.01)],
    )
    first = compute_signals(data)
    second = compute_signals(data)
    # Igualdade por VALOR (dataclasses) — mesma ordem, mesmos campos.
    assert first == second
    # E são de fato `Signal` (não outra coisa que só "parece" igual).
    assert all(isinstance(s, Signal) for s in first)
    # Repetível quantas vezes for: nenhum estado global mutável.
    assert compute_signals(data) == first
