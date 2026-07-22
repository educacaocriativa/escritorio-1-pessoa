"""Rotas da inteligência financeira (Story 5.3 — DRE por categoria). SOMENTE LEITURA."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.contracts import service as contracts_service
from app.modules.cost_centers import service as cost_centers_service
from app.modules.financial_intelligence import ai_narrator
from app.modules.financial_intelligence import diagnostics as diagnostics_service
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import profitability as profitability_service
from app.modules.financial_intelligence import projection as projection_service
from app.modules.financial_intelligence.dre import CostCenterReport, DreGroup, DreReport
from app.modules.financial_intelligence.profitability import ContractDre, ContractDreGroup
from app.modules.financial_intelligence.projection import CashProjection
from app.modules.financial_intelligence.schemas import (
    ContractDreOut,
    ContractDreSummaryOut,
    CostCenterBucketOut,
    CostCenterReportOut,
    DiagnosticsOut,
    DreCategoryOut,
    DreGroupOut,
    DreMatrixGroupOut,
    DreMatrixReportOut,
    DreMatrixRowOut,
    DreReportOut,
    LedgerEntryOut,
    ProjectionOut,
    ProjectionWindowOut,
    RunwayOut,
    SignalOut,
)

router = APIRouter(prefix="/financial-intelligence", tags=["financial_intelligence"])

_guard = require_module("financial_intelligence")


def _require_cost_center(db: Session, cost_center_id: str | None) -> None:
    """Story 5.5: valida o filtro opcional por centro de custo. Um id inexistente OU de outro
    tenant → 404 fail-closed (a RLS esconde a linha → exists False), mesmo padrão do contrato
    (IV2: tenant A não filtra por centro de custo de tenant B)."""
    if cost_center_id and not cost_centers_service.exists(db, cost_center_id):
        raise HTTPException(status_code=404, detail="Centro de custo não encontrado")


def _group_out(g: DreGroup) -> DreGroupOut:
    return DreGroupOut(
        grupo_dre=g.grupo_dre,
        total_cents=g.total_cents,
        categorias=[
            DreCategoryOut(categoria=c.categoria, amount_cents=c.amount_cents, count=c.count)
            for c in g.categorias
        ],
    )


def _report_out(r: DreReport) -> DreReportOut:
    return DreReportOut(
        start=r.start,
        end=r.end,
        groups=[_group_out(g) for g in r.groups],
        sem_categoria=_group_out(r.sem_categoria),
        resultado_cents=r.resultado_cents,
        notes=r.notes,
    )


@router.get("/dre", response_model=DreReportOut)
def dre(
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    cost_center_id: str | None = Query(
        default=None,
        description="Story 5.5: filtra a DRE por centro de custo (2ª dimensão). Omitir = tudo.",
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DreReportOut:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    # `?cost_center_id=` (string vazia) == "Todos": normaliza p/ None para NÃO virar filtro que casa
    # zero lançamentos — "filtro nulo mostra tudo" (IV3), mantendo a visão da 5.3 idêntica.
    cost_center_id = cost_center_id or None
    _require_cost_center(db, cost_center_id)
    report = dre_service.dre_report(db, start=start, end=end, cost_center_id=cost_center_id)
    return _report_out(report)


def _matrix_row_out(r: dre_service.DreMatrixRow) -> DreMatrixRowOut:
    return DreMatrixRowOut(
        label=r.label, kind=r.kind, monthly_cents=r.monthly_cents, total_cents=r.total_cents,
    )


def _matrix_group_out(g: dre_service.DreMatrixGroup) -> DreMatrixGroupOut:
    return DreMatrixGroupOut(
        key=g.key, label=g.label, rows=[_matrix_row_out(r) for r in g.rows],
        subtotal_cents=g.subtotal_cents, subtotal_total=g.subtotal_total,
    )


def _matrix_report_out(r: dre_service.DreMatrixReport) -> DreMatrixReportOut:
    return DreMatrixReportOut(
        months=r.months, groups=[_matrix_group_out(g) for g in r.groups],
        grand_total_cents=r.grand_total_cents, grand_total=r.grand_total, notes=r.notes,
    )


@router.get("/dre/matrix", response_model=DreMatrixReportOut)
def dre_matrix(
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    group_by: str = Query(
        default="dre",
        pattern="^(dre|cost_center)$",
        description="Story 5.11: 'dre' (grupo DRE, padrão) ou 'cost_center' (centro de custo).",
    ),
    cost_center_id: str | None = Query(
        default=None,
        description="Filtra por centro de custo — só se aplica quando group_by='dre'.",
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DreMatrixReportOut:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    cost_center_id = cost_center_id or None
    _require_cost_center(db, cost_center_id)
    report = dre_service.dre_matrix_report(
        db, start=start, end=end, group_by=group_by, cost_center_id=cost_center_id,
    )
    return _matrix_report_out(report)


def _cost_center_bucket_out(b: dre_service.CostCenterBucket) -> CostCenterBucketOut:
    return CostCenterBucketOut(
        cost_center_id=b.cost_center_id,
        name=b.name,
        kind=b.kind,
        receita_cents=b.receita_cents,
        resultado_cents=b.resultado_cents,
        lancamentos=b.lancamentos,
    )


def _cost_center_report_out(r: CostCenterReport) -> CostCenterReportOut:
    return CostCenterReportOut(
        start=r.start,
        end=r.end,
        buckets=[_cost_center_bucket_out(b) for b in r.buckets],
        notes=r.notes,
    )


@router.get("/by-cost-center", response_model=CostCenterReportOut)
def by_cost_center(
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> CostCenterReportOut:
    """Cruza o resultado do período por centro de custo (2ª dimensão), incluindo o bucket 'Não
    atribuído' — comparação lado a lado de sócios/áreas/unidades (Story 5.5, AC2/AC3)."""
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    report = dre_service.by_cost_center_report(db, start=start, end=end)
    return _cost_center_report_out(report)


def _projection_out(r: CashProjection) -> ProjectionOut:
    return ProjectionOut(
        today=r.today,
        saldo_inicial_cents=r.saldo_inicial_cents,
        overdue_inflow_cents=r.overdue_inflow_cents,
        overdue_outflow_cents=r.overdue_outflow_cents,
        windows=[
            ProjectionWindowOut(
                days=w.days, saldo_projetado_cents=w.saldo_projetado_cents, alert=w.alert
            )
            for w in r.windows
        ],
        runway=RunwayOut(
            days=r.runway.days, burn_rate_cents_per_day=r.runway.burn_rate_cents_per_day
        ),
        notes=r.notes,
    )


@router.get("/projection", response_model=ProjectionOut)
def projection(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ProjectionOut:
    """Projeta o saldo de caixa para 30/60/90 dias e o runway (Story 5.7), em regime de CAIXA.

    SOMENTE LEITURA: usa a data de pagamento prevista (vencimento dos itens em aberto), nunca a de
    competência — não escreve nem cria contas (IV1/IV2)."""
    report = projection_service.cash_projection(db)
    return _projection_out(report)


def _contract_group_out(g: ContractDreGroup) -> DreGroupOut:
    return DreGroupOut(
        grupo_dre=g.grupo_dre,
        total_cents=g.total_cents,
        categorias=[
            DreCategoryOut(categoria=c.categoria, amount_cents=c.amount_cents, count=c.count)
            for c in g.categorias
        ],
    )


def _contract_dre_out(r: ContractDre) -> ContractDreOut:
    return ContractDreOut(
        contract_id=r.contract_id,
        start=r.start,
        end=r.end,
        receita=_contract_group_out(r.receita),
        custo_direto=_contract_group_out(r.custo_direto),
        receita_cents=r.receita_cents,
        custo_direto_cents=r.custo_direto_cents,
        margem_contribuicao_cents=r.margem_contribuicao_cents,
        margem_contribuicao_pct=r.margem_contribuicao_pct,
        outros_resultado_cents=r.outros_resultado_cents,
        fixed_costs_allocated_cents=r.fixed_costs_allocated_cents,
        overhead_allocated_cents=r.overhead_allocated_cents,
        resultado_cents=r.resultado_cents,
        break_even_cents=r.break_even_cents,
        break_even_reachable=r.break_even_reachable,
        notes=r.notes,
    )


@router.get("/contracts/{contract_id}/dre", response_model=ContractDreOut)
def contract_dre(
    contract_id: str,
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    include_overhead: bool = Query(
        default=False,
        description="Inclui o rateio de overhead do bucket 'Empresa' (só na visão analítica).",
    ),
    cost_center_id: str | None = Query(
        default=None,
        description="Story 5.5: filtra a DRE do contrato por centro de custo (2ª dimensão).",
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ContractDreOut:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    # Contrato inexistente OU de outro tenant → RLS esconde a linha → 404 fail-closed (IV3).
    try:
        contract = contracts_service.get_contract(db, contract_id)
    except contracts_service.ContractError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    # `?cost_center_id=` (vazio) == "Todos" → None (não vira filtro que casa zero — IV3).
    cost_center_id = cost_center_id or None
    _require_cost_center(db, cost_center_id)
    report = profitability_service.contract_dre(
        db, contract=contract, start=start, end=end, include_overhead=include_overhead,
        cost_center_id=cost_center_id,
    )
    return _contract_dre_out(report)


def _contract_dre_summary_out(s: profitability_service.ContractDreSummary) -> ContractDreSummaryOut:
    return ContractDreSummaryOut(
        contract_id=s.contract_id, title=s.title, client_name=s.client_name,
        receita_cents=s.receita_cents, custo_direto_cents=s.custo_direto_cents,
        margem_contribuicao_cents=s.margem_contribuicao_cents,
        margem_contribuicao_pct=s.margem_contribuicao_pct,
        overhead_allocated_cents=s.overhead_allocated_cents, resultado_cents=s.resultado_cents,
    )


@router.get("/contracts-dre", response_model=list[ContractDreSummaryOut])
def contracts_dre(
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    include_overhead: bool = Query(
        default=False, description="Inclui o rateio de overhead em todas as linhas do ranking.",
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ContractDreSummaryOut]:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    summaries = profitability_service.contracts_dre_report(
        db, start=start, end=end, include_overhead=include_overhead,
    )
    return [_contract_dre_summary_out(s) for s in summaries]


def _ledger_entry_out(e: profitability_service.LedgerEntry) -> LedgerEntryOut:
    return LedgerEntryOut(
        id=e.id, source=e.source, date=e.date, description=e.description,
        categoria=e.categoria, status=e.status, amount_cents=e.amount_cents,
    )


@router.get("/contracts/{contract_id}/ledger", response_model=list[LedgerEntryOut])
def contract_ledger_route(
    contract_id: str,
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[LedgerEntryOut]:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    try:
        contract = contracts_service.get_contract(db, contract_id)
    except contracts_service.ContractError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    entries = profitability_service.contract_ledger(db, contract=contract, start=start, end=end)
    return [_ledger_entry_out(e) for e in entries]


@router.get("/diagnostics", response_model=DiagnosticsOut)
def diagnostics(
    start: date = Query(..., description="Início do período (competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (competência), YYYY-MM-DD"),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DiagnosticsOut:
    """Diagnóstico financeiro (Story 5.8): sinais determinísticos 🟢🟡🔴 (motor PURO) + narrativa.

    O motor SEMPRE calcula e retorna os sinais, mesmo sem `ANTHROPIC_API_KEY` (AC2/IV3): a narrativa
    da IA é isolada e cai num fallback por template em qualquer erro/chave ausente — nunca derruba o
    endpoint. Quando a IA narra de fato, o texto passa pelo anonimizador ANTES do Claude (Regra de
    Ouro nº 2) e grava rastro "Ação executada pela IA" (Regra de Ouro nº 3)."""
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    signals = diagnostics_service.compute_signals(db, start=start, end=end)
    narrative, narrative_source = ai_narrator.narrate_with_source(
        signals, db=db, tenant_id=user.tenant_id, actor=user.user_id,
        target=f"{start.isoformat()}..{end.isoformat()}",
    )
    return DiagnosticsOut(
        start=start,
        end=end,
        signals=[
            SignalOut(level=s.level, title=s.title, explanation=s.explanation, source=s.source)
            for s in signals
        ],
        narrative=narrative,
        narrative_source=narrative_source,
    )
