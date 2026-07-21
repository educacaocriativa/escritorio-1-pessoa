"""Schemas da camada de inteligência financeira (Story 5.3 — DRE por categoria)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DreCategoryOut(BaseModel):
    categoria: str
    amount_cents: int  # sinal natural (Receber=+, Pagar=−)
    count: int


class DreGroupOut(BaseModel):
    grupo_dre: str
    total_cents: int
    categorias: list[DreCategoryOut]


class DreReportOut(BaseModel):
    """DRE hierárquica do período (grupo DRE → categoria), em regime de competência.

    `groups` traz sempre os 6 grupos na ordem canônica (mesmo vazios). `sem_categoria` é o bucket
    dos lançamentos não classificados (fora do `resultado_cents`). `notes` documenta as exclusões
    (INVESTIMENTO / sem categoria) e o regime — não silenciosamente.
    """

    start: date
    end: date
    groups: list[DreGroupOut]
    sem_categoria: DreGroupOut
    resultado_cents: int
    notes: list[str]


# ── Lucratividade por contrato (Story 5.4) ──────────────────────────────────
class ContractDreOut(BaseModel):
    """DRE de margem de contribuição de UM contrato (Story 5.4), em regime de competência.

    Sinal canônico (herdado da 5.3): totais já ASSINADOS (Receber=+, Pagar=−). `custo_direto_cents`
    normalmente é NEGATIVO; a margem é a SOMA `receita_cents + custo_direto_cents` (não subtração).
    `margem_contribuicao_pct` é a RAZÃO MC/Receita (fração, ex.: 0.6 = 60%; multiplique por 100 para
    exibir %), ou None quando não há receita (proteção contra divisão por zero). `break_even_cents`
    é a receita necessária para empatar os custos fixos; None + `break_even_reachable=false` quando
    a margem não-positiva impede o break-even (estado explícito, nunca erro 500).
    `overhead_allocated_cents` só é != 0 quando o rateio é solicitado (`include_overhead=true`) —
    calculado na leitura, JAMAIS gravado no lançamento (AC3/IV2).

    `outros_resultado_cents` é a soma assinada dos lançamentos do contrato em grupos de resultado
    ALÉM da margem (Despesa Fixa/Tributos/Financeiro): NÃO entra na margem de contribuição, mas
    COMPÕE o resultado (`resultado = margem + outros_resultado − custos fixos − overhead`).
    INVESTIMENTO e lançamentos sem categoria ficam fora do resultado (sinalizados em `notes`).
    """

    contract_id: str
    start: date
    end: date
    receita: DreGroupOut
    custo_direto: DreGroupOut
    receita_cents: int
    custo_direto_cents: int
    margem_contribuicao_cents: int
    margem_contribuicao_pct: float | None
    outros_resultado_cents: int
    fixed_costs_allocated_cents: int
    overhead_allocated_cents: int
    resultado_cents: int
    break_even_cents: int | None
    break_even_reachable: bool
    notes: list[str]


class ContractDreSummaryOut(BaseModel):
    """Uma linha do ranking de lucratividade (Story 5.12) — mesmos campos-chave do `ContractDreOut`
    de um contrato só, sem o detalhe de categorias (a lista completa é obtida via `/ledger`)."""

    contract_id: str
    title: str
    client_name: str | None
    receita_cents: int
    custo_direto_cents: int
    margem_contribuicao_cents: int
    margem_contribuicao_pct: float | None
    overhead_allocated_cents: int
    resultado_cents: int


# ── Projeção de fluxo de caixa 30/60/90 + runway (Story 5.7) ────────────────
class ProjectionWindowOut(BaseModel):
    """Saldo de caixa projetado para uma janela (dias a partir de hoje), em regime de CAIXA.

    `saldo_projetado_cents` é CUMULATIVO: saldo inicial da Carteira + entradas abertas − saídas
    abertas cujo vencimento cai até o fim da janela. `alert=True` quando o saldo fica NEGATIVO nessa
    janela — sinal explícito que a Story 5.8 consome como indicador 🔴 sem recalcular."""

    days: int
    saldo_projetado_cents: int
    alert: bool


class RunwayOut(BaseModel):
    """Runway: fôlego de caixa no ritmo de queima atual.

    `days` = dias até o saldo inicial zerar na queima líquida diária (saídas − entradas da maior
    janela / dias), ou `None` quando não há queima (caixa crescendo/estável) — "sem risco", sem
    divisão por zero. `burn_rate_cents_per_day` é a queima diária (0 quando não há queima)."""

    days: int | None
    burn_rate_cents_per_day: int


class ProjectionOut(BaseModel):
    """Projeção de fluxo de caixa 30/60/90 dias + runway (Story 5.7), em regime de CAIXA.

    OPOSTO da DRE (que usa competência): aqui a data é a de PAGAMENTO PREVISTO (vencimento dos itens
    em aberto), nunca `competence_date`. `saldo_inicial_cents` é o disponível da Carteira (mesmo
    número do Cockpit). `windows` traz uma janela por horizonte pedido (default 30/60/90), com o
    saldo projetado e o sinal `alert`. `notes` documenta o regime e as exclusões — não em silêncio.

    `overdue_inflow_cents`/`overdue_outflow_cents`: parcela de itens em aberto JÁ VENCIDOS
    (`due_date < hoje`) que a projeção conta como caixa esperado imediato — já embutida em todas as
    `windows`, exposta à parte para o consumidor risk-ajustar (vencidos podem não se concretizar).
    """

    today: date
    saldo_inicial_cents: int
    overdue_inflow_cents: int
    overdue_outflow_cents: int
    windows: list[ProjectionWindowOut]
    runway: RunwayOut
    notes: list[str]


# ── Cruzamento por centro de custo (Story 5.5) ──────────────────────────────
class CostCenterBucketOut(BaseModel):
    """Resultado do período agregado por um centro de custo (2ª dimensão). `cost_center_id=None` e
    `name='Não atribuído'` é o bucket sintético dos lançamentos sem centro de custo (AC3).
    `resultado_cents` usa a MESMA fórmula/exclusões da DRE (Story 5.3)."""

    cost_center_id: str | None
    name: str
    kind: str | None
    receita_cents: int
    resultado_cents: int
    lancamentos: int


class CostCenterReportOut(BaseModel):
    """Comparação lado a lado do resultado por centro de custo no período (Story 5.5, AC2).

    `buckets` traz um item por centro de custo do tenant (mesmo os sem movimento, para comparar
    sócios/áreas) mais o bucket 'Não atribuído' (quando há lançamentos sem a 2ª dimensão). `notes`
    documenta o regime e as exclusões — não silenciosamente.
    """

    start: date
    end: date
    buckets: list[CostCenterBucketOut]
    notes: list[str]


# ── Diagnóstico determinístico + narrativa por IA (Story 5.8) ───────────────
class SignalOut(BaseModel):
    """Um sinal de diagnóstico calculado pelo motor PURO (Story 5.8). `level` é verde/amarelo/
    vermelho; `explanation` SEMPRE traz o número que o justifica; `source` identifica a origem
    (lucratividade 5.4 / projecao 5.7 / investimento 5.6)."""

    level: str
    title: str
    explanation: str
    source: str


class DiagnosticsOut(BaseModel):
    """Resposta do diagnóstico (Story 5.8). `signals` é o resultado DETERMINÍSTICO do motor —
    existe e está correto INDEPENDENTEMENTE da IA (AC2/IV3). `narrative` é a leitura em linguagem
    natural: quando a IA está disponível, é gerada por ela (após anonimização — Regra de Ouro nº 2);
    senão, é um fallback por template a partir dos MESMOS sinais. `narrative_source` diz qual foi
    ('ai' | 'template') — a UI deixa claro ao usuário que os números vêm primeiro."""

    start: date
    end: date
    signals: list[SignalOut]
    narrative: str
    narrative_source: str  # "ai" | "template"


# ── DRE em matriz mensal (Story 5.11) ───────────────────────────────────────
class DreMatrixRowOut(BaseModel):
    label: str
    kind: str  # "result" | "informational" | "uncategorized"
    monthly_cents: list[int]
    total_cents: int


class DreMatrixGroupOut(BaseModel):
    key: str
    label: str | None
    rows: list[DreMatrixRowOut]
    subtotal_cents: list[int]
    subtotal_total: int


class DreMatrixReportOut(BaseModel):
    """Matriz mês x categoria (Story 5.11). `groups` é a hierarquia grupo/centro-de-custo ->
    categoria; cada linha carrega seu próprio `kind` (ver docstring de `dre_matrix_report`).
    `grand_total_cents` soma só as linhas `kind="result"` de todos os grupos, mês a mês."""

    months: list[str]
    groups: list[DreMatrixGroupOut]
    grand_total_cents: list[int]
    grand_total: int
    notes: list[str]
