"""Regras do CRM: estágios do funil, clientes (cards), movimentação e board.

Sessão já isolada por tenant (RLS). tenant_id só carimba novas linhas.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, events
from app.modules.crm.models import DEFAULT_STAGES, Client, PipelineStage
from app.modules.crm.schemas import ClientCreate, ClientUpdate, StageCreate, StageUpdate

EVENT_CLIENT_MOVED = "crm.client.moved"


class CrmError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ── Estágios ───────────────────────────────────────────


def _ordered_stages(db: Session) -> list[PipelineStage]:
    # Apenas etapas ativas (não arquivadas). Desempate por id garante ordem estável.
    return list(
        db.scalars(
            select(PipelineStage)
            .where(PipelineStage.is_archived.is_(False))
            .order_by(PipelineStage.position, PipelineStage.id)
        ).all()
    )


def ensure_stages(db: Session, tenant_id: str) -> list[PipelineStage]:
    """Retorna os estágios do tenant; semeia os padrões no primeiro acesso.

    A unicidade (tenant_id, name) protege contra seed duplicado em corrida: se outra request
    semeou ao mesmo tempo, o INSERT falha e nós apenas relemos.
    """
    stages = _ordered_stages(db)
    if stages:
        return stages
    try:
        for pos, spec in enumerate(DEFAULT_STAGES):
            db.add(PipelineStage(tenant_id=tenant_id, position=pos, **spec))
        db.commit()
    except IntegrityError:
        db.rollback()
    return _ordered_stages(db)


def create_stage(db: Session, *, tenant_id: str, actor: str, data: StageCreate) -> PipelineStage:
    if data.position is None:
        max_pos = db.scalar(select(func.max(PipelineStage.position)))
        position = 0 if max_pos is None else max_pos + 1
    else:
        position = data.position
    stage = PipelineStage(
        tenant_id=tenant_id,
        name=data.name,
        position=position,
        is_won=data.is_won,
        is_lost=data.is_lost,
    )
    db.add(stage)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.stage.create", target=stage.id)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise CrmError("Já existe um estágio com esse nome", 409) from e
    db.refresh(stage)
    return stage


def get_stage(db: Session, stage_id: str) -> PipelineStage:
    stage = db.get(PipelineStage, stage_id)
    if stage is None:
        raise CrmError("Estágio não encontrado", 404)
    return stage


def update_stage(
    db: Session, *, stage_id: str, tenant_id: str, actor: str, data: StageUpdate
) -> PipelineStage:
    stage = get_stage(db, stage_id)
    if data.name is not None:
        stage.name = data.name
    if data.position is not None:
        stage.position = data.position
    audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.stage.update", target=stage.id)
    db.commit()
    db.refresh(stage)
    return stage


def archive_stage(db: Session, *, stage_id: str, tenant_id: str, actor: str) -> None:
    """Arquiva uma etapa (some do board). Move os clientes dela para a primeira etapa ativa."""
    stage = get_stage(db, stage_id)
    if stage.is_archived:
        return
    others = [s for s in _ordered_stages(db) if s.id != stage_id]
    has_clients = db.scalar(select(func.count(Client.id)).where(Client.stage_id == stage_id))
    if has_clients:
        if not others:
            raise CrmError("Crie outra etapa antes de arquivar esta (há clientes nela)", 409)
        db.query(Client).filter(Client.stage_id == stage_id).update(
            {Client.stage_id: others[0].id}, synchronize_session=False
        )
    stage.is_archived = True
    audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.stage.archive", target=stage_id)
    db.commit()


def delete_stage(db: Session, *, stage_id: str, tenant_id: str, actor: str) -> None:
    stage = get_stage(db, stage_id)
    count = db.scalar(select(func.count(Client.id)).where(Client.stage_id == stage_id))
    if count:
        raise CrmError("Não é possível excluir um estágio com clientes; mova-os antes", 409)
    db.delete(stage)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.stage.delete", target=stage_id)
    db.commit()


# ── Clientes ───────────────────────────────────────────


def create_client(db: Session, *, tenant_id: str, actor: str, data: ClientCreate) -> Client:
    stages = ensure_stages(db, tenant_id)
    if data.stage_id is not None:
        stage = db.get(PipelineStage, data.stage_id)
        if stage is None:
            raise CrmError("Estágio informado não existe", 404)
        stage_id = stage.id
    else:
        stage_id = stages[0].id  # primeira coluna (Entrada)

    client = Client(
        tenant_id=tenant_id,
        name=data.name,
        email=str(data.email) if data.email else None,
        phone=data.phone,
        document=data.document,
        gender=data.gender,
        birthdate=data.birthdate,
        notes=data.notes,
        tags=data.tags,
        source=data.source,
        stage_id=stage_id,
    )
    db.add(client)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.client.create", target=client.id)
    db.commit()
    db.refresh(client)
    return client


def list_clients(
    db: Session,
    *,
    stage_id: str | None = None,
    tag: str | None = None,
    gender: str | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Client]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    stmt = select(Client).order_by(Client.name, Client.id)
    if stage_id is not None:
        stmt = stmt.where(Client.stage_id == stage_id)
    if gender is not None:
        stmt = stmt.where(Client.gender == gender)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Client.name.ilike(like))
    if tag is not None:
        # Filtro por tag em Python (portável entre SQLite/Postgres). stmt já vem ORDENADO,
        # então a paginação sobre o resultado é determinística. TODO: usar operador JSON
        # do Postgres (tags @> [tag]) para empurrar o filtro ao banco em escala.
        rows = list(db.scalars(stmt).all())
        filtered = [c for c in rows if tag in (c.tags or [])]
        return filtered[offset : offset + limit]
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def get_client(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise CrmError("Cliente não encontrado", 404)
    return client


def update_client(
    db: Session, *, client_id: str, tenant_id: str, actor: str, data: ClientUpdate
) -> Client:
    client = get_client(db, client_id)
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        if key == "email" and value is not None:
            value = str(value)
        setattr(client, key, value)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="crm.client.update", target=client.id
    )
    db.commit()
    db.refresh(client)
    return client


def move_client(
    db: Session, *, client_id: str, tenant_id: str, actor: str, by_ai: bool, stage_id: str
) -> Client:
    client = get_client(db, client_id)
    target = db.get(PipelineStage, stage_id)
    if target is None:
        raise CrmError("Estágio de destino não existe", 404)
    from_stage = client.stage_id
    client.stage_id = target.id
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="crm.client.move",
        target=client.id, is_ai=by_ai,
    )
    db.commit()
    db.refresh(client)
    # Gatilho do Kanban: outros módulos podem reagir (ex.: gerar cobrança ao entrar em 'Ganho').
    events.emit(
        EVENT_CLIENT_MOVED,
        tenant_id=tenant_id,
        client_id=client.id,
        from_stage=from_stage,
        to_stage=target.id,
        is_won=target.is_won,
        is_lost=target.is_lost,
    )
    return client


def build_board(db: Session, tenant_id: str) -> list[tuple[PipelineStage, list[Client]]]:
    stages = ensure_stages(db, tenant_id)
    clients = list(db.scalars(select(Client).order_by(Client.name)).all())
    by_stage: dict[str | None, list[Client]] = {}
    for c in clients:
        by_stage.setdefault(c.stage_id, []).append(c)
    return [(stage, by_stage.get(stage.id, [])) for stage in stages]
