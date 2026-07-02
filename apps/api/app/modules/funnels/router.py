"""Rotas do Construtor de Funil de Vendas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.crm.models import Client
from app.modules.funnels import engine, service
from app.modules.funnels.models import Funnel, FunnelRun
from app.modules.funnels.schemas import (
    ComponentCategory,
    ComposeRequest,
    ComposeResult,
    EnrollRequest,
    FunnelCreate,
    FunnelOut,
    FunnelRunOut,
    FunnelRunSummary,
    FunnelSummary,
    FunnelUpdate,
    RunNodeRequest,
    RunNodeResult,
    TickResult,
)

router = APIRouter(prefix="/funnels", tags=["funnels"])

_guard = require_module("funnels")


def _out(f: Funnel) -> FunnelOut:
    return FunnelOut(
        id=f.id, tenant_id=f.tenant_id, name=f.name, nodes=f.nodes, edges=f.edges,
        created_at=f.created_at,
    )


def _err(e: service.FunnelError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/components", response_model=list[ComponentCategory])
def components(_u: CurrentUser = Depends(_guard)) -> list[ComponentCategory]:
    return [ComponentCategory(**c) for c in service.CATALOG]


@router.post("/ai-compose", response_model=ComposeResult)
def ai_compose(
    data: ComposeRequest,
    _u: CurrentUser = Depends(_guard),
    _db: Session = Depends(get_tenant_db),
) -> ComposeResult:
    return ComposeResult(**service.ai_compose(data.kind, data.prompt))


@router.post("/run-node", response_model=RunNodeResult)
def run_node(
    data: RunNodeRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> RunNodeResult:
    try:
        result = service.run_node(
            db, tenant_id=user.tenant_id, actor=user.user_id,
            action=data.action, client_id=data.client_id, params=data.params,
        )
    except service.FunnelError as e:
        raise _err(e) from e
    return RunNodeResult(**result)


# ── Automação: inscrever contato, jornadas e agendador ──────────────────────
# (declarado ANTES de /{funnel_id} para "runs" não ser capturado como funnel_id)
def _run_out(run: FunnelRun, db: Session) -> FunnelRunOut:
    client = db.get(Client, run.client_id) if run.client_id else None
    return FunnelRunOut(
        id=run.id, tenant_id=run.tenant_id, funnel_id=run.funnel_id, client_id=run.client_id,
        client_name=client.name if client else None, status=run.status,
        current_node_id=run.current_node_id, resume_at=run.resume_at, steps=run.steps,
        error=run.error, created_at=run.created_at, updated_at=run.updated_at,
    )


@router.post("/runs/tick", response_model=TickResult)
def tick(user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)) -> TickResult:
    """Retoma as jornadas com espera vencida. Idempotente — chamável por cron ou pela tela."""
    return TickResult(**engine.tick(db, tenant_id=user.tenant_id, actor=user.user_id))


@router.get("/runs", response_model=list[FunnelRunSummary])
def list_runs(
    client_id: str | None = None,
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[FunnelRunSummary]:
    runs = engine.list_runs(db, client_id=client_id)
    out = []
    for r in runs:
        client = db.get(Client, r.client_id) if r.client_id else None
        out.append(FunnelRunSummary(
            id=r.id, funnel_id=r.funnel_id, client_id=r.client_id,
            client_name=client.name if client else None, status=r.status,
            resume_at=r.resume_at, step_count=len(r.steps), created_at=r.created_at,
        ))
    return out


@router.get("/runs/{run_id}", response_model=FunnelRunOut)
def get_run(
    run_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> FunnelRunOut:
    try:
        return _run_out(engine.get_run(db, run_id), db)
    except service.FunnelError as e:
        raise _err(e) from e


@router.post("/runs/{run_id}/cancel", response_model=FunnelRunOut)
def cancel_run(
    run_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> FunnelRunOut:
    try:
        run = engine.cancel_run(db, run_id=run_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.FunnelError as e:
        raise _err(e) from e
    return _run_out(run, db)


@router.post("/{funnel_id}/enroll", response_model=FunnelRunOut, status_code=201)
def enroll(
    funnel_id: str,
    data: EnrollRequest,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> FunnelRunOut:
    try:
        run = engine.enroll(
            db, tenant_id=user.tenant_id, actor=user.user_id, funnel_id=funnel_id,
            client_id=data.client_id, start_node_id=data.start_node_id,
        )
    except service.FunnelError as e:
        raise _err(e) from e
    return _run_out(run, db)


@router.get("/{funnel_id}/runs", response_model=list[FunnelRunSummary])
def list_funnel_runs(
    funnel_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[FunnelRunSummary]:
    runs = engine.list_runs(db, funnel_id=funnel_id)
    out = []
    for r in runs:
        client = db.get(Client, r.client_id) if r.client_id else None
        out.append(FunnelRunSummary(
            id=r.id, funnel_id=r.funnel_id, client_id=r.client_id,
            client_name=client.name if client else None, status=r.status,
            resume_at=r.resume_at, step_count=len(r.steps), created_at=r.created_at,
        ))
    return out


@router.get("", response_model=list[FunnelSummary])
def list_funnels(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[FunnelSummary]:
    return [
        FunnelSummary(id=f.id, name=f.name, node_count=len(f.nodes), created_at=f.created_at)
        for f in service.list_funnels(db)
    ]


@router.post("", response_model=FunnelOut, status_code=201)
def create_funnel(
    data: FunnelCreate, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> FunnelOut:
    return _out(service.create_funnel(db, tenant_id=user.tenant_id, actor=user.user_id, data=data))


@router.get("/{funnel_id}", response_model=FunnelOut)
def get_funnel(
    funnel_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> FunnelOut:
    try:
        return _out(service.get_funnel(db, funnel_id))
    except service.FunnelError as e:
        raise _err(e) from e


@router.patch("/{funnel_id}", response_model=FunnelOut)
def update_funnel(
    funnel_id: str,
    data: FunnelUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> FunnelOut:
    try:
        f = service.update_funnel(
            db, funnel_id=funnel_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.FunnelError as e:
        raise _err(e) from e
    return _out(f)


@router.delete("/{funnel_id}", status_code=204)
def delete_funnel(
    funnel_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> Response:
    try:
        service.delete_funnel(db, funnel_id=funnel_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.FunnelError as e:
        raise _err(e) from e
    return Response(status_code=204)
