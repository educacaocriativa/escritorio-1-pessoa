"""Motor de indicadores PURO e DETERMINÍSTICO (Story 5.8, AC1/AC2, IV1/NFR3).

Este módulo é o coração da Story 5.8 e o motivo de toda a iniciativa: **os sinais de
diagnóstico 🟢🟡🔴 são calculados aqui, por regras determinísticas, ANTES de qualquer IA.**
A IA (ver `ai_narrator.py`) só NARRA os sinais já calculados — nunca origina um número.

Regra de design (NÃO NEGOCIÁVEL — IV1/NFR3): este arquivo é ESTRITAMENTE PURO.
  - NÃO importa `Session`, NÃO faz query, NÃO chama `core.ai`, NÃO chama `core.anonymizer`.
  - Recebe estruturas Python já calculadas (dataclasses de entrada abaixo, alimentadas por
    `diagnostics.py` a partir das saídas das Stories 5.4/5.6/5.7) e devolve `list[Signal]`.
  - Puramente funcional, sem efeito colateral. É o que o torna "testável isoladamente": o teste
    (test_financial_intelligence_engine.py) não precisa de banco nem de rede.

[AUTO-DECISION] A Story cita como entrada `DreReportOut`/`ProjectionOut`/etc. Optamos por
dataclasses de entrada PRÓPRIAS e mínimas (definidas aqui) em vez de importar os schemas Pydantic
dos outros módulos. Motivo: manter o motor 100% desacoplado de qualquer outro módulo (o mais forte
possível para a garantia IV1 — o engine não pode nem "ver" a camada de I/O), e tornar o teste
unitário trivial de montar. A adaptação schema-Pydantic → entrada-do-engine vive em `diagnostics`.
Duas entradas (`MarginTrend`, `InvestmentReturn`) carregam o NOME do projeto/aplicação — que os
Out schemas não expõem (só id) mas as explicações numéricas do AC1 exigem (ex.: "Projeto X: ...").
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Níveis de sinal (🟢🟡🔴). Ordem de prioridade: vermelho > amarelo > verde. ──────────────
VERDE = "verde"
AMARELO = "amarelo"
VERMELHO = "vermelho"

# Rank determinístico para a priorização (AC1 "sinais priorizados"). Menor = mais urgente.
_LEVEL_RANK: dict[str, int] = {VERMELHO: 0, AMARELO: 1, VERDE: 2}

# ── Limiares determinísticos (documentados; extensíveis sem tocar na estrutura) ─────────────
# Margem de contribuição caindo (em pontos percentuais, p.p.):
_MARGIN_DROP_YELLOW_PP = 8.0   # queda ≥ 8 p.p. → 🟡
_MARGIN_DROP_RED_PP = 15.0     # queda ≥ 15 p.p. (ou margem final negativa) → 🔴
# Runway (dias de fôlego de caixa):
_RUNWAY_RED_DAYS = 60          # < 60 dias → 🔴
_RUNWAY_YELLOW_DAYS = 120      # < 120 dias → 🟡


@dataclass(frozen=True)
class Signal:
    """Um sinal de diagnóstico determinístico. `explanation` SEMPRE traz o número que o justifica
    (AC1 "explicação numérica"). `source` identifica a regra/origem (5.4/5.6/5.7) — a UI rotula."""

    level: str  # VERDE | AMARELO | VERMELHO
    title: str
    explanation: str
    source: str


# ── Entradas do motor (puras — montadas por diagnostics.py) ─────────────────────────────────
@dataclass(frozen=True)
class MarginTrend:
    """Margem de contribuição de UM projeto/contrato em dois períodos consecutivos (Story 5.4).

    `project_name` é o título do contrato (pode conter PII — anonimizado DEPOIS pelo narrador, nunca
    aqui). `margem_pct_antes`/`margem_pct_depois` são FRAÇÕES (ex.: 0.28 = 28%), como a 5.4 expõe
    (`margem_contribuicao_pct`), ou None quando não há receita no período (proteção div/0)."""

    project_name: str
    margem_pct_antes: float | None
    margem_pct_depois: float | None
    period_label: str  # ex.: "1 mês" — a janela de comparação (não é PII)


@dataclass(frozen=True)
class ProjectionWindowInput:
    """Uma janela da projeção de caixa (Story 5.7). `alert` já vem calculado pela 5.7 (saldo
    projetado negativo na janela) — o motor o CONSOME sem recalcular (reuso direto do campo)."""

    days: int
    alert: bool


@dataclass(frozen=True)
class InvestmentReturn:
    """Rentabilidade de UMA aplicação no período (Story 5.6). `name` pode conter PII (anonimizado
    depois). `period_rentability_pct` é FRAÇÃO (ex.: -0.02 = -2%) ou None quando principal == 0."""

    name: str
    period_rentability_pct: float | None


@dataclass(frozen=True)
class EngineInput:
    """Snapshot de entrada do motor. Tudo já calculado pelas Stories anteriores; o motor só decide
    os sinais. Campos são listas/valores simples → o teste unitário monta à mão, sem I/O."""

    margins: list[MarginTrend]
    runway_days: int | None
    projection_windows: list[ProjectionWindowInput]
    investments: list[InvestmentReturn]


def _pct_display(fraction: float) -> int:
    """Fração (0.28) → percentual inteiro para exibição (28). Determinístico."""
    return round(fraction * 100)


def _margin_signals(margins: list[MarginTrend]) -> list[Signal]:
    """Regra 1 — margem de projeto caindo (Story 5.4). Só avalia projetos com margem nos DOIS
    períodos (a explicação do AC1 exige o formato "{antes}%→{depois}%"). Escalonamento:
    queda ≥ 15 p.p. OU margem final negativa → 🔴; queda ≥ 8 p.p. → 🟡; senão nenhum sinal."""
    out: list[Signal] = []
    for m in margins:
        if m.margem_pct_antes is None or m.margem_pct_depois is None:
            continue  # sem receita em algum período → não há tendência a diagnosticar
        # round(6) neutraliza ruído de ponto flutuante (ex.: 0.30-0.22 = 7.999…) para que os
        # limiares (8/15 p.p.) sejam determinísticos e batam exatamente na borda.
        drop_pp = round((m.margem_pct_antes - m.margem_pct_depois) * 100.0, 6)
        antes = _pct_display(m.margem_pct_antes)
        depois = _pct_display(m.margem_pct_depois)
        explanation = (
            f"Projeto {m.project_name}: margem {antes}%→{depois}% em {m.period_label}"
        )
        if m.margem_pct_depois < 0 or drop_pp >= _MARGIN_DROP_RED_PP:
            out.append(Signal(VERMELHO, "Margem de contribuição em queda forte", explanation,
                              "lucratividade"))
        elif drop_pp >= _MARGIN_DROP_YELLOW_PP:
            out.append(Signal(AMARELO, "Margem de contribuição caindo", explanation,
                              "lucratividade"))
    return out


def _runway_signal(runway_days: int | None) -> list[Signal]:
    """Regra 2 — runway curto (Story 5.7, campo `runway.days` já calculado). None = caixa não está
    sendo queimado (estável) → nenhum sinal. < 60 → 🔴; < 120 → 🟡; senão 🟢."""
    if runway_days is None:
        return []
    if runway_days < _RUNWAY_RED_DAYS:
        return [Signal(VERMELHO, "Runway crítico", f"Runway < {_RUNWAY_RED_DAYS} dias", "projecao")]
    if runway_days < _RUNWAY_YELLOW_DAYS:
        return [Signal(AMARELO, "Runway curto", f"Runway < {_RUNWAY_YELLOW_DAYS} dias", "projecao")]
    return [Signal(VERDE, "Runway saudável", f"Runway de {runway_days} dias", "projecao")]


def _projection_window_signals(windows: list[ProjectionWindowInput]) -> list[Signal]:
    """Regra 3 — janela de projeção negativa (Story 5.7). Reuso DIRETO do campo `alert` por janela:
    qualquer janela com alert=True → 🔴, citando a janela. Não recalcula nada."""
    return [
        Signal(VERMELHO, "Projeção de caixa negativa",
               f"Projeção de caixa negativa em {w.days} dias", "projecao")
        for w in windows
        if w.alert
    ]


def _investment_signals(investments: list[InvestmentReturn]) -> list[Signal]:
    """Regra 4 — investimento sem rendimento no período (Story 5.6). [AUTO-DECISION] Sem benchmark
    de mercado real (fora de escopo, ver 5.6), o único critério objetivo é rentabilidade do período
    ≤ 0 → 🟡. Aplicações com principal 0 (pct None) não são avaliadas (não há base)."""
    out: list[Signal] = []
    for inv in investments:
        if inv.period_rentability_pct is None:
            continue
        if inv.period_rentability_pct <= 0:
            pct = round(inv.period_rentability_pct * 100, 1)
            out.append(Signal(
                AMARELO, "Investimento sem rendimento no período",
                f"{inv.name}: rentabilidade {pct}% no período", "investimento",
            ))
    return out


def compute_signals(data: EngineInput) -> list[Signal]:
    """Ponto de entrada PURO do motor. Avalia as 4 regras determinísticas na ordem documentada
    (margem → runway → janela → investimento), depois PRIORIZA por nível (vermelho > amarelo >
    verde), mantendo, dentro do mesmo nível, a ordem de avaliação (sort ESTÁVEL — critério simples e
    determinístico, sem heurística subjetiva de "importância" que o motor não teria como aferir).

    DETERMINISMO (IV1): para o MESMO `data`, retorna SEMPRE a MESMA lista (mesma ordem, mesmos
    valores). Nenhuma dependência de relógio, aleatoriedade, I/O ou IA. É esta pureza que garante
    que a IA (que só entra depois, em ai_narrator.py) não pode ter influenciado nenhum sinal."""
    signals: list[Signal] = []
    signals.extend(_margin_signals(data.margins))
    signals.extend(_runway_signal(data.runway_days))
    signals.extend(_projection_window_signals(data.projection_windows))
    signals.extend(_investment_signals(data.investments))
    # Sort estável por prioridade de nível: preserva a ordem de avaliação dentro de cada nível.
    signals.sort(key=lambda s: _LEVEL_RANK[s.level])
    return signals
