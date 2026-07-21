"""Lucratividade por contrato (Story 5.4) — DRE do contrato, margem de contribuição, break-even
e rateio de overhead. Agregação SOMENTE-LEITURA, regime de COMPETÊNCIA.

Reusa o padrão da DRE por categoria (Story 5.3, `dre.py`): agregação `GROUP BY` no banco (nunca
carrega os lançamentos em memória para somar), regime de competência (`competence_date`, NUNCA
`paid_at`) e — o ponto mais crítico — a **CONVENÇÃO CANÔNICA DE SINAL ratificada pelo @architect**:

  O sinal de um lançamento vem EXCLUSIVAMENTE da sua TABELA DE ORIGEM, nunca do `grupo_dre`:
  `Charge` (a receber/entrada) = +1 ; `Payable` (a pagar/saída) = −1. O `grupo_dre` é só um
  rótulo de classificação. Os totais de grupo já vêm ASSINADOS (custos NEGATIVOS). Portanto:

    Margem de Contribuição = Receita(+) + CustoDireto(−)      ← SOMA de totais assinados,
                                                                NUNCA `receita − custo` (isso
                                                                seria dupla-negação: o footgun
                                                                que o @architect alertou na 5.3).

  Um reembolso ao cliente (Payable em RECEITA) reduz corretamente a receita; um crédito de
  fornecedor (Charge em CUSTO_DIRETO) reduz corretamente o custo — sem regra especial por grupo.

Eixo "projeto" = o `Contract` já existente (decisão do fundador — não há tabela nova).
Lançamentos com `contract_id IS NULL` caem no bucket implícito "Empresa" (overhead) e NÃO entram na
DRE de nenhum contrato específico.

Isolamento: nenhuma query filtra `tenant_id` manualmente — a RLS já fixou o tenant na sessão
(Regra de Ouro nº 1). Herda o RLS de `contracts`/`payables`/`charges`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.chart_of_accounts.models import (
    GROUP_ORDER,
    GRUPO_CUSTO_DIRETO,
    GRUPO_DESPESA_FIXA,
    GRUPO_INVESTIMENTO,
    GRUPO_RECEITA,
    ChartAccount,
)
from app.modules.contracts import service as contracts_service
from app.modules.contracts.models import STATUS_SIGNED, Contract
from app.modules.crm.models import Client
from app.modules.payables.models import STATUS_CANCELED as PAYABLE_CANCELED
from app.modules.payables.models import Payable
from app.modules.receivables.models import STATUS_CANCELED as CHARGE_CANCELED
from app.modules.receivables.models import Charge

# Critério(s) de rateio de overhead suportado(s). Um único critério nesta story (AC3 pede apenas
# "opcional, por critério configurável"); a assinatura aceita `criterio` para novos critérios
# depois, sem inventar uma matriz não pedida.
CRITERIO_RECEITA_PROPORCIONAL = "receita_proporcional"
ALL_CRITERIOS = frozenset({CRITERIO_RECEITA_PROPORCIONAL})

# ── Escopo do resultado do contrato (regra canônica ratificada pela Aria — @architect — na 5.4) ──
# A MARGEM DE CONTRIBUIÇÃO usa APENAS estes dois grupos (Receita + Custo Direto), conforme AC2.
_MARGIN_GROUPS = frozenset({GRUPO_RECEITA, GRUPO_CUSTO_DIRETO})
# O RESULTADO do contrato inclui TODOS os grupos de resultado (menos INVESTIMENTO, que é movimento
# de balanço, não de DRE — mesma exclusão da 5.3). Consistente com a regra geral "lucro = Σ Charges
# + Σ Payables do contrato". Os grupos ALÉM da margem (Despesa Fixa/Tributos/Financeiro) NÃO entram
# na margem de contribuição, mas COMPÕEM o resultado — um custo que o usuário atribuiu de fato ao
# contrato (ex.: taxa fixa mensal do projeto) JAMAIS pode sumir do resultado, só virar nota.
_RESULT_GROUPS = frozenset(GROUP_ORDER) - {GRUPO_INVESTIMENTO}
_OTHER_RESULT_GROUPS = _RESULT_GROUPS - _MARGIN_GROUPS  # {DESPESA_FIXA, TRIBUTOS, FINANCEIRO}

_NOTE_COMPETENCIA = "Regime de competência (data de competência), não de caixa."
_NOTE_MARGEM = (
    "Margem de Contribuição = Receita + Custo Direto (soma assinada, custo já negativo). "
    "Resultado = Margem + outros grupos de resultado atribuídos ao contrato (Despesa Fixa/"
    "Tributos/Financeiro) − custos fixos atribuídos − overhead rateado (quando solicitado)."
)
_NOTE_BREAK_EVEN_INATINGIVEL = (
    "Margem de contribuição não-positiva no período: no ritmo atual o contrato não atinge "
    "break-even (a receita não cobre o custo direto)."
)
_NOTE_OVERHEAD = (
    "Overhead rateado do bucket 'Empresa' (lançamentos sem contrato) por proporção de receita — "
    "cálculo APENAS na leitura; nunca gravado no lançamento original."
)
_NOTE_OUTROS_GRUPOS = (
    "Há lançamentos vinculados a este contrato em outros grupos de resultado (Despesa Fixa/"
    "Tributos/Financeiro): eles NÃO entram na margem de contribuição (que soma só Receita e Custo "
    "Direto), mas COMPÕEM o resultado do contrato — ver 'outros_resultado_cents'."
)
_NOTE_INVESTIMENTO = (
    "Há lançamentos de INVESTIMENTO vinculados a este contrato: ficam fora do resultado (movimento "
    "de balanço, não de DRE — mesma exclusão do resultado geral)."
)
_NOTE_SEM_CATEGORIA = (
    "Há lançamentos vinculados a este contrato sem categoria/conta resolvível: ficam fora da "
    "margem e do resultado. Classifique-os no plano de contas para vê-los no grupo correto."
)


@dataclass
class ContractDreCategory:
    categoria: str
    amount_cents: int  # sinal natural (Receber=+, Pagar=−)
    count: int


@dataclass
class ContractDreGroup:
    grupo_dre: str
    total_cents: int  # soma já-com-sinal dos lançamentos do grupo, para este contrato
    categorias: list[ContractDreCategory] = field(default_factory=list)


@dataclass
class ContractDre:
    contract_id: str
    start: date
    end: date
    receita: ContractDreGroup
    custo_direto: ContractDreGroup
    receita_cents: int
    custo_direto_cents: int
    margem_contribuicao_cents: int
    # razão MC/Receita (fração, ex.: 0.6 = 60%). None quando não há receita (proteção div/0).
    margem_contribuicao_pct: float | None
    # Soma assinada dos lançamentos do contrato em grupos de resultado ALÉM da margem
    # (Despesa Fixa/Tributos/Financeiro). Normalmente negativa (despesas). Entra no resultado,
    # não na margem. INVESTIMENTO e sem-categoria ficam de fora (notados).
    outros_resultado_cents: int
    fixed_costs_allocated_cents: int
    overhead_allocated_cents: int
    resultado_cents: int
    # Receita (em centavos) necessária para o contrato empatar os custos fixos atribuídos.
    # None quando não atingível (margem <= 0 e há custo fixo a cobrir).
    break_even_cents: int | None
    break_even_reachable: bool
    notes: list[str] = field(default_factory=list)


def _sum_group_by_account(
    db: Session,
    model: type[Payable | Charge],
    *,
    contract_id: str,
    start: date,
    end: date,
    canceled: str,
    sign: int,
    cost_center_id: str | None = None,
) -> list[tuple[str | None, int, int]]:
    """Soma por `chart_account_id` (GROUP BY no banco) dos lançamentos de UM contrato no período
    de COMPETÊNCIA. `COALESCE(competence_date, due_date)` como rede de segurança para legado com
    competência nula (`due_date` é NOT NULL — nenhuma linha é descartada). Cancelados fora.
    `sign` aplica o sinal NATURAL (Receber=+1, Pagar=−1). Retorna (chart_account_id, soma, cnt).

    Story 5.5: `cost_center_id` (2ª dimensão) filtra por centro de custo QUANDO informado. Quando
    `None` (default), NENHUM predicado extra entra na query — a DRE do contrato fica IDÊNTICA à da
    Story 5.4 (IV3)."""
    competence = func.coalesce(model.competence_date, model.due_date)
    stmt = select(
        model.chart_account_id,
        func.coalesce(func.sum(model.amount_cents), 0),
        func.count(model.id),
    ).where(
        model.contract_id == contract_id,
        competence >= start,
        competence <= end,
        model.status != canceled,
    )
    if cost_center_id is not None:
        stmt = stmt.where(model.cost_center_id == cost_center_id)
    stmt = stmt.group_by(model.chart_account_id)
    rows = db.execute(stmt).all()
    return [(acc_id, sign * int(total or 0), int(count)) for acc_id, total, count in rows]


def _account_map(db: Session) -> dict[str, tuple[str, str]]:
    """id da conta → (grupo, categoria). Inclui arquivadas (a classificação histórica de um
    lançamento deve resolver o grupo mesmo se a categoria foi arquivada depois)."""
    return {a.id: (a.grupo_dre, a.categoria) for a in db.scalars(select(ChartAccount)).all()}


def _group(grupo: str, cats: dict[str, list[int]]) -> ContractDreGroup:
    categorias = [
        ContractDreCategory(categoria=cat, amount_cents=amt, count=cnt)
        for cat, (amt, cnt) in sorted(cats.items())
    ]
    total = sum(c.amount_cents for c in categorias)
    return ContractDreGroup(grupo_dre=grupo, total_cents=total, categorias=categorias)


def contract_dre(
    db: Session,
    *,
    contract: Contract,
    start: date,
    end: date,
    include_overhead: bool = False,
    criterio: str = CRITERIO_RECEITA_PROPORCIONAL,
    cost_center_id: str | None = None,
) -> ContractDre:
    """Monta a DRE de margem de contribuição de UM contrato no período, em regime de competência.

    Story 5.5: `cost_center_id` (2ª dimensão, OPCIONAL) filtra os lançamentos do contrato por centro
    de custo quando informado. Omitir (`None`) produz resultado IDÊNTICO ao da Story 5.4 (IV3). O
    rateio de overhead permanece de nível-EMPRESA (não é filtrado por centro de custo — é uma
    alocação da empresa inteira, ortogonal à 2ª dimensão; documentado para não inventar um produto
    cartesiano não pedido).

    SOMENTE LEITURA: não escreve nada (nenhum efeito sobre payables/charges/contracts — IV2). O
    `contract` já vem resolvido pelo router (existe e é visível pela RLS do tenant)."""
    account_map = _account_map(db)

    # Agrega TODOS os lançamentos do contrato (Charge +, Payable −), por conta do plano de contas.
    aggregated = _sum_group_by_account(
        db, Charge, contract_id=contract.id, start=start, end=end,
        canceled=CHARGE_CANCELED, sign=1, cost_center_id=cost_center_id,
    ) + _sum_group_by_account(
        db, Payable, contract_id=contract.id, start=start, end=end,
        canceled=PAYABLE_CANCELED, sign=-1, cost_center_id=cost_center_id,
    )

    # grupo -> categoria -> [amount_cents, count]  (só os grupos da MARGEM: Receita/Custo Direto)
    by_group: dict[str, dict[str, list[int]]] = {}
    # Soma assinada dos demais grupos de resultado (Despesa Fixa/Tributos/Financeiro): entram no
    # RESULTADO, não na margem. INVESTIMENTO e sem-categoria ficam fora do resultado (só notados).
    outros_resultado_cents = 0
    has_outros = False
    has_investimento = False
    has_sem_categoria = False
    for acc_id, amount, count in aggregated:
        resolved = account_map.get(acc_id) if acc_id else None
        grupo = resolved[0] if resolved else None
        categoria = resolved[1] if resolved else "Sem categoria"
        if grupo in _MARGIN_GROUPS:
            bucket = by_group.setdefault(grupo, {})
            line = bucket.setdefault(categoria, [0, 0])
            line[0] += amount
            line[1] += count
        elif grupo in _OTHER_RESULT_GROUPS:
            # Custo/tributo/financeiro atribuído ao contrato: NÃO entra na margem de contribuição
            # (AC2: só Receita − Custo Direto), mas COMPÕE o resultado — um custo explicitamente
            # vinculado ao contrato jamais deve sumir do resultado (regra canônica da Aria, 5.4).
            outros_resultado_cents += amount
            has_outros = True
        elif grupo == GRUPO_INVESTIMENTO:
            # Movimento de balanço, não de DRE — fora do resultado (mesma exclusão da 5.3). Notado.
            has_investimento = True
        else:
            # Sem conta resolvível (chart_account_id NULL ou conta inexistente): fora do resultado.
            has_sem_categoria = True

    receita = _group(GRUPO_RECEITA, by_group.get(GRUPO_RECEITA, {}))
    custo_direto = _group(GRUPO_CUSTO_DIRETO, by_group.get(GRUPO_CUSTO_DIRETO, {}))

    receita_cents = receita.total_cents  # normalmente + (Charges)
    custo_direto_cents = custo_direto.total_cents  # normalmente − (Payables, já assinado)
    # Margem = SOMA de totais assinados (custo já é negativo) — NUNCA `receita − custo`.
    margem_contribuicao_cents = receita_cents + custo_direto_cents

    # Margem % = MC / Receita (fração). Proteção explícita contra divisão por zero: sem receita
    # no período, a razão é indefinida → None (o router devolve 200, nunca 500).
    margem_contribuicao_pct: float | None = (
        margem_contribuicao_cents / receita_cents if receita_cents != 0 else None
    )

    fixed_costs = contract.fixed_costs_allocated_cents or 0

    overhead_allocated = 0
    if include_overhead:
        overhead_allocated = allocate_overhead(
            db, contract=contract, start=start, end=end, criterio=criterio
        )

    # Resultado do contrato = margem + outros grupos de resultado atribuídos (Despesa Fixa/Tributos/
    # Financeiro, já assinados) − custos fixos manuais − overhead rateado (quando solicitado).
    resultado_cents = (
        margem_contribuicao_cents + outros_resultado_cents - fixed_costs - overhead_allocated
    )

    break_even_cents, break_even_reachable = _break_even(fixed_costs, margem_contribuicao_pct)

    notes = [_NOTE_COMPETENCIA, _NOTE_MARGEM]
    if not break_even_reachable:
        notes.append(_NOTE_BREAK_EVEN_INATINGIVEL)
    if include_overhead:
        notes.append(_NOTE_OVERHEAD)
    if has_outros:
        notes.append(_NOTE_OUTROS_GRUPOS)
    if has_investimento:
        notes.append(_NOTE_INVESTIMENTO)
    if has_sem_categoria:
        notes.append(_NOTE_SEM_CATEGORIA)

    return ContractDre(
        contract_id=contract.id,
        start=start,
        end=end,
        receita=receita,
        custo_direto=custo_direto,
        receita_cents=receita_cents,
        custo_direto_cents=custo_direto_cents,
        margem_contribuicao_cents=margem_contribuicao_cents,
        margem_contribuicao_pct=margem_contribuicao_pct,
        outros_resultado_cents=outros_resultado_cents,
        fixed_costs_allocated_cents=fixed_costs,
        overhead_allocated_cents=overhead_allocated,
        resultado_cents=resultado_cents,
        break_even_cents=break_even_cents,
        break_even_reachable=break_even_reachable,
        notes=notes,
    )


def _break_even(
    fixed_costs_cents: int, margem_pct: float | None
) -> tuple[int | None, bool]:
    """Break-even (AC2): receita (R$) necessária para a margem cobrir os custos fixos atribuídos.

    - Sem custo fixo a cobrir (<= 0): break-even trivial em 0, sempre atingível.
    - Com custo fixo e margem % > 0: `custo_fixo / margem_pct` (proteção div/0 embutida: só divide
      quando margem_pct é positiva e não-nula).
    - Margem % nula/None (sem receita) ou <= 0: NÃO atingível no ritmo atual — estado explícito
      (break_even_cents=None, reachable=False), consumível pela Story 5.8 (diagnóstico). Sem 500."""
    if fixed_costs_cents <= 0:
        return 0, True
    if margem_pct is not None and margem_pct > 0:
        return round(fixed_costs_cents / margem_pct), True
    return None, False


def _revenue_in_period(
    db: Session,
    *,
    contract_id: str | None,
    start: date,
    end: date,
    receita_account_ids: list[str],
) -> int:
    """Receita (Charges em contas do grupo RECEITA) no período de competência, para um contrato
    (ou, quando contract_id=None, para TODOS os contratos via `contract_id IS NOT NULL`).

    Só considera contas do grupo RECEITA (a base de rateio é a receita reconhecida). Cancelados
    fora. Retorna a soma (Charges → +). SOMENTE LEITURA."""
    if not receita_account_ids:
        return 0
    competence = func.coalesce(Charge.competence_date, Charge.due_date)
    stmt = (
        select(func.coalesce(func.sum(Charge.amount_cents), 0))
        .where(
            competence >= start,
            competence <= end,
            Charge.status != CHARGE_CANCELED,
            Charge.chart_account_id.in_(receita_account_ids),
        )
    )
    if contract_id is None:
        stmt = stmt.where(Charge.contract_id.is_not(None))
    else:
        stmt = stmt.where(Charge.contract_id == contract_id)
    return int(db.scalar(stmt) or 0)


def allocate_overhead(
    db: Session,
    *,
    contract: Contract,
    start: date,
    end: date,
    criterio: str = CRITERIO_RECEITA_PROPORCIONAL,
) -> int:
    """Rateia o overhead do bucket "Empresa" (lançamentos SEM contrato) a UM contrato (AC3).

    CRÍTICO (IV2): função ESTRITAMENTE de leitura — NUNCA escreve em payables/charges/contracts.
    O resultado só aparece no `ContractDre` retornado, opcional via `?include_overhead=true`.

    Critério `receita_proporcional` (único nesta story): proporção da receita do contrato sobre a
    receita total de TODOS os contratos ativos no período. Divisão por zero protegida: sem receita
    total de contratos, não há base de rateio → 0.

    Overhead pool = despesas fixas (grupo DESPESA_FIXA) do bucket "Empresa" (contract_id IS NULL)
    no período. Calculado pelo sinal natural (Payable − / Charge +) e convertido para magnitude
    positiva (`-signed`), robusto a estornos. Retorna centavos (>= 0 no caso normal)."""
    if criterio not in ALL_CRITERIOS:
        raise ValueError(f"critério de rateio inválido: {criterio}")

    # Contas do grupo RECEITA (base do rateio) e DESPESA_FIXA (pool de overhead).
    accounts = db.scalars(select(ChartAccount)).all()
    receita_ids = [a.id for a in accounts if a.grupo_dre == GRUPO_RECEITA]
    despesa_ids = [a.id for a in accounts if a.grupo_dre == GRUPO_DESPESA_FIXA]

    overhead_pool = _overhead_pool(db, start=start, end=end, despesa_account_ids=despesa_ids)
    if overhead_pool <= 0:
        return 0

    contract_revenue = _revenue_in_period(
        db, contract_id=contract.id, start=start, end=end, receita_account_ids=receita_ids
    )
    total_revenue = _revenue_in_period(
        db, contract_id=None, start=start, end=end, receita_account_ids=receita_ids
    )
    if total_revenue <= 0 or contract_revenue <= 0:
        return 0  # proteção div/0: sem base de receita, não há rateio proporcional
    return round(overhead_pool * (contract_revenue / total_revenue))


def _overhead_pool(
    db: Session, *, start: date, end: date, despesa_account_ids: list[str]
) -> int:
    """Pool de overhead: despesas fixas do bucket "Empresa" (contract_id IS NULL) no período.

    Sinal natural (Payable −, Charge +) → soma assinada é negativa (despesa); devolvemos a
    MAGNITUDE (`-signed`), robusta a estornos (um crédito reduz o pool). SOMENTE LEITURA."""
    if not despesa_account_ids:
        return 0
    signed = 0
    for model, sign, canceled in (
        (Charge, 1, CHARGE_CANCELED),
        (Payable, -1, PAYABLE_CANCELED),
    ):
        competence = func.coalesce(model.competence_date, model.due_date)
        total = db.scalar(
            select(func.coalesce(func.sum(model.amount_cents), 0)).where(
                model.contract_id.is_(None),
                competence >= start,
                competence <= end,
                model.status != canceled,
                model.chart_account_id.in_(despesa_account_ids),
            )
        )
        signed += sign * int(total or 0)
    return -signed  # despesa (negativa) → magnitude positiva


# ── Ranking de lucratividade de todos os contratos (Story 5.12) ────────────────────────────────
@dataclass
class ContractDreSummary:
    contract_id: str
    title: str
    client_name: str | None
    receita_cents: int
    custo_direto_cents: int
    margem_contribuicao_cents: int
    margem_contribuicao_pct: float | None
    overhead_allocated_cents: int
    resultado_cents: int


def contracts_dre_report(
    db: Session, *, start: date, end: date, include_overhead: bool = False,
) -> list[ContractDreSummary]:
    """Ranking de lucratividade de TODOS os contratos ASSINADOS do tenant (Story 5.12). Contrato
    signed sem lançamento no período aparece com tudo zerado (não é filtrado) — permite comparar
    quem está "parado" vs. em execução. SOMENTE LEITURA; reusa `contract_dre` por contrato (mesma
    convenção de sinal/competência já ratificada), sem alterar nenhuma linha.

    Custo conhecido, aceito de propósito: chama `contract_dre` (que recarrega o plano de contas
    inteiro a cada chamada) uma vez por contrato — com `include_overhead=True`, `allocate_overhead`
    ainda recalcula a receita total de TODOS os contratos a cada linha, tornando esse caminho O(N²)
    no nº de contratos assinados. Aceitável para o volume esperado por tenant nesta primeira versão
    (decisão registrada no spec da Lucratividade por Contrato); otimizar (account_map compartilhado
    entre chamadas, cache da receita total) só se o volume real justificar."""
    contracts = contracts_service.list_contracts(db, status=STATUS_SIGNED)
    summaries: list[ContractDreSummary] = []
    for contract in contracts:
        dre = contract_dre(
            db, contract=contract, start=start, end=end, include_overhead=include_overhead
        )
        client_name = None
        if contract.client_id:
            client = db.get(Client, contract.client_id)
            client_name = client.name if client else None
        summaries.append(
            ContractDreSummary(
                contract_id=contract.id,
                title=contract.title,
                client_name=client_name,
                receita_cents=dre.receita_cents,
                custo_direto_cents=dre.custo_direto_cents,
                margem_contribuicao_cents=dre.margem_contribuicao_cents,
                margem_contribuicao_pct=dre.margem_contribuicao_pct,
                overhead_allocated_cents=dre.overhead_allocated_cents,
                resultado_cents=dre.resultado_cents,
            )
        )
    return summaries
