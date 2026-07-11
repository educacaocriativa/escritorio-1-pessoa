"""Regras do centro de custo: CRUD por tenant (Story 5.5).

Isolamento por RLS (nenhuma query filtra tenant manualmente — Regra de Ouro nº 1). Duplicidade de
`(tenant, name)` é barrada pela UniqueConstraint → 409. Arquivar NÃO deleta a linha (preserva o
histórico já vinculado). Mesmo padrão CRUD simples de `chart_accounts` (Story 5.1).
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.cost_centers.models import CostCenter
from app.modules.cost_centers.schemas import CostCenterCreate, CostCenterUpdate


class CostCenterError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def exists(db: Session, cost_center_id: str) -> bool:
    """O centro de custo existe E é visível pela RLS do tenant atual? Usada por
    Payables/Receivables ao vincular um lançamento e pela camada analítica ao filtrar por centro de
    custo — um id inexistente OU de outro tenant devolve False (a RLS esconde a linha → db.get
    None), garantindo o isolamento (IV2) sem que os consumidores filtrem tenant manualmente."""
    return db.get(CostCenter, cost_center_id) is not None


def get_cost_center(db: Session, cost_center_id: str) -> CostCenter:
    cc = db.get(CostCenter, cost_center_id)
    if cc is None:
        # Cross-tenant também cai aqui: a RLS esconde a linha → db.get None → 404 (fail-closed).
        raise CostCenterError("Centro de custo não encontrado", 404)
    return cc


def create_cost_center(
    db: Session, *, tenant_id: str, actor: str, data: CostCenterCreate
) -> CostCenter:
    cc = CostCenter(tenant_id=tenant_id, name=data.name, kind=data.kind)
    db.add(cc)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="cost_center.create", target=cc.id)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise CostCenterError("Já existe um centro de custo com esse nome", 409) from e
    db.refresh(cc)
    return cc


def update_cost_center(
    db: Session, *, cost_center_id: str, tenant_id: str, actor: str, data: CostCenterUpdate
) -> CostCenter:
    cc = get_cost_center(db, cost_center_id)
    if data.name is not None:
        cc.name = data.name
    if data.kind is not None:
        cc.kind = data.kind
    audit.record(db, tenant_id=tenant_id, actor=actor, action="cost_center.update", target=cc.id)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise CostCenterError("Já existe um centro de custo com esse nome", 409) from e
    db.refresh(cc)
    return cc


def archive_cost_center(
    db: Session, *, cost_center_id: str, tenant_id: str, actor: str
) -> CostCenter:
    """Arquiva (lógico): seta archived_at, NÃO deleta a linha — preserva o histórico já vinculado.
    Idempotente: rearquivar mantém o carimbo original."""
    cc = get_cost_center(db, cost_center_id)
    if cc.archived_at is None:
        cc.archived_at = datetime.now(UTC)
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="cost_center.archive", target=cc.id
        )
        db.commit()
        db.refresh(cc)
    return cc


def list_cost_centers(db: Session, *, include_archived: bool = False) -> list[CostCenter]:
    stmt = select(CostCenter).order_by(CostCenter.name)
    if not include_archived:
        stmt = stmt.where(CostCenter.archived_at.is_(None))
    return list(db.scalars(stmt).all())
