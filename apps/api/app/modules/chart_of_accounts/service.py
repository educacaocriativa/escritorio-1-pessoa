"""Regras do plano de contas: CRUD por tenant + seed opcional de categorias comuns.

Isolamento por RLS (nenhuma query filtra tenant manualmente — Regra de Ouro nº 1). Duplicidade de
`(tenant, grupo, categoria)` é barrada pela UniqueConstraint → 409. Arquivar NÃO deleta a linha.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.chart_of_accounts.models import (
    GROUP_ORDER,
    ChartAccount,
)
from app.modules.chart_of_accounts.schemas import ChartAccountCreate, ChartAccountUpdate

# Conjunto-semente opcional de categorias comuns por grupo (AC2). Usado só via POST /seed.
# FINANCEIRO → "Rendimento de aplicação" é o hook usado pela Story 5.6.
COMMON_CATEGORIES: dict[str, list[str]] = {
    "RECEITA": ["Vendas de produto", "Vendas de serviço", "Recorrência"],
    "CUSTO_DIRETO": ["Insumos", "Comissões"],
    "DESPESA_FIXA": ["Aluguel", "Assinaturas/SaaS", "Folha/Pró-labore"],
    "TRIBUTOS": ["Impostos sobre serviço", "Taxas"],
    "FINANCEIRO": ["Rendimento de aplicação", "Tarifas bancárias"],
    "INVESTIMENTO": ["Equipamentos"],
}


class ChartAccountError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def exists(db: Session, account_id: str) -> bool:
    """A conta existe E é visível pela RLS do tenant atual? Usada por Payables/Receivables
    (Story 5.2) para validar `chart_account_id` no cadastro/edição — uma conta inexistente OU de
    outro tenant devolve False (a RLS esconde a linha → db.get None), garantindo o isolamento
    (IV3) sem que os módulos financeiros filtrem tenant manualmente (Regra de Ouro nº 1)."""
    return db.get(ChartAccount, account_id) is not None


def get_account(db: Session, account_id: str) -> ChartAccount:
    acc = db.get(ChartAccount, account_id)
    if acc is None:
        # Cross-tenant também cai aqui: a RLS esconde a linha → db.get devolve None → 404
        # (fail-closed, mesmo padrão do resto do projeto: 404, não 403).
        raise ChartAccountError("Categoria não encontrada", 404)
    return acc


def create_account(
    db: Session, *, tenant_id: str, actor: str, data: ChartAccountCreate
) -> ChartAccount:
    acc = ChartAccount(
        tenant_id=tenant_id,
        grupo_dre=data.grupo_dre,
        categoria=data.categoria,
    )
    db.add(acc)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="chart_account.create", target=acc.id
    )
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ChartAccountError(
            "Já existe uma categoria com esse nome neste grupo", 409
        ) from e
    db.refresh(acc)
    return acc


def update_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str, data: ChartAccountUpdate
) -> ChartAccount:
    """Renomeia a categoria (o grupo DRE é fixo e não muda). Valida unicidade no grupo."""
    acc = get_account(db, account_id)
    if data.categoria is not None:
        acc.categoria = data.categoria
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="chart_account.update", target=acc.id
    )
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise ChartAccountError(
            "Já existe uma categoria com esse nome neste grupo", 409
        ) from e
    db.refresh(acc)
    return acc


def archive_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str
) -> ChartAccount:
    """Arquiva (lógico): seta archived_at, NÃO deleta a linha — preserva o histórico já
    classificado (AC2). Idempotente: rearquivar mantém o carimbo original."""
    acc = get_account(db, account_id)
    if acc.archived_at is None:
        acc.archived_at = datetime.now(UTC)
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="chart_account.archive", target=acc.id
        )
        db.commit()
        db.refresh(acc)
    return acc


def list_accounts(
    db: Session, *, grupo: str | None = None, include_archived: bool = False
) -> list[ChartAccount]:
    stmt = select(ChartAccount).order_by(ChartAccount.grupo_dre, ChartAccount.categoria)
    if grupo:
        stmt = stmt.where(ChartAccount.grupo_dre == grupo)
    if not include_archived:
        stmt = stmt.where(ChartAccount.archived_at.is_(None))
    return list(db.scalars(stmt).all())


def hierarchy(db: Session, *, include_archived: bool = False) -> list[dict]:
    """Hierarquia grupo → categorias (AC3). Sempre devolve os 6 grupos na ordem canônica, mesmo
    os vazios — assim o front renderiza a taxonomia completa."""
    accounts = list_accounts(db, include_archived=include_archived)
    by_group: dict[str, list[ChartAccount]] = {g: [] for g in GROUP_ORDER}
    for acc in accounts:
        by_group.setdefault(acc.grupo_dre, []).append(acc)
    return [{"grupo_dre": g, "categorias": by_group.get(g, [])} for g in GROUP_ORDER]


def seed_common_categories(db: Session, *, tenant_id: str, actor: str) -> list[ChartAccount]:
    """Semeia as categorias comuns (AC2) — OPCIONAL, chamada só pelo endpoint /seed (nunca
    automática no cadastro do tenant). Idempotente: rodar de novo não duplica (a categoria já
    existente é pulada; a UniqueConstraint é a rede de segurança em corrida)."""
    existing = {
        (acc.grupo_dre, acc.categoria)
        for acc in db.scalars(select(ChartAccount)).all()
    }
    created = 0
    for grupo, categorias in COMMON_CATEGORIES.items():
        for categoria in categorias:
            if (grupo, categoria) in existing:
                continue
            db.add(ChartAccount(tenant_id=tenant_id, grupo_dre=grupo, categoria=categoria))
            existing.add((grupo, categoria))
            created += 1
    if created:
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="chart_account.seed", target=tenant_id
        )
        try:
            db.commit()
        except IntegrityError:
            # Corrida: outra request semeou ao mesmo tempo. Relê o estado consistente.
            db.rollback()
    return list_accounts(db, include_archived=False)
