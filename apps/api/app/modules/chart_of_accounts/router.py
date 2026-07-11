"""Rotas do plano de contas (grupo DRE → categorias)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.chart_of_accounts import service
from app.modules.chart_of_accounts.models import ChartAccount
from app.modules.chart_of_accounts.schemas import (
    ChartAccountCreate,
    ChartAccountOut,
    ChartAccountUpdate,
    ChartGroupOut,
)

router = APIRouter(prefix="/chart-of-accounts", tags=["chart_of_accounts"])

_guard = require_module("chart_of_accounts")


def _out(a: ChartAccount) -> ChartAccountOut:
    return ChartAccountOut(
        id=a.id,
        grupo_dre=a.grupo_dre,
        categoria=a.categoria,
        archived_at=a.archived_at,
        created_at=a.created_at,
    )


def _err(e: service.ChartAccountError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=list[ChartAccountOut])
def list_accounts(
    grupo: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ChartAccountOut]:
    accounts = service.list_accounts(db, grupo=grupo, include_archived=include_archived)
    return [_out(a) for a in accounts]


@router.get("/hierarchy", response_model=list[ChartGroupOut])
def hierarchy(
    include_archived: bool = Query(default=False),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ChartGroupOut]:
    groups = service.hierarchy(db, include_archived=include_archived)
    return [
        ChartGroupOut(
            grupo_dre=g["grupo_dre"],
            categorias=[_out(a) for a in g["categorias"]],
        )
        for g in groups
    ]


@router.post("", response_model=ChartAccountOut, status_code=201)
def create_account(
    data: ChartAccountCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChartAccountOut:
    try:
        acc = service.create_account(
            db, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.ChartAccountError as e:
        raise _err(e) from e
    return _out(acc)


@router.patch("/{account_id}", response_model=ChartAccountOut)
def update_account(
    account_id: str,
    data: ChartAccountUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChartAccountOut:
    try:
        acc = service.update_account(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.ChartAccountError as e:
        raise _err(e) from e
    return _out(acc)


@router.post("/{account_id}/archive", response_model=ChartAccountOut)
def archive_account(
    account_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChartAccountOut:
    try:
        acc = service.archive_account(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ChartAccountError as e:
        raise _err(e) from e
    return _out(acc)


@router.post("/seed", response_model=list[ChartAccountOut])
def seed(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ChartAccountOut]:
    accounts = service.seed_common_categories(
        db, tenant_id=user.tenant_id, actor=user.user_id
    )
    return [_out(a) for a in accounts]
