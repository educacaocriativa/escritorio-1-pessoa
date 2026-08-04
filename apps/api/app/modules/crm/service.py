"""Regras do CRM: estágios do funil, clientes (cards), movimentação e board.

Sessão já isolada por tenant (RLS). tenant_id só carimba novas linhas.

Nota sobre o import de `whatsapp_inbox.models`: é o MODELO, nunca o service. O
`whatsapp_inbox/service.py` importa de `crm`, então importar o service dele aqui fecharia
ciclo; `whatsapp_inbox/models.py` não importa nada de `crm`. Usado por
`last_interaction_map`, que precisa da data da última mensagem para o card do Kanban.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.phone import normalize_br
from app.modules.crm.models import (
    DEFAULT_STAGES,
    KIND_LEAD_CREATED,
    KIND_LEAD_RETURN,
    KIND_REOPENED,
    KIND_STAGE_MOVE,
    Client,
    ClientEvent,
    PipelineStage,
)
from app.modules.crm.schemas import ClientCreate, ClientUpdate, StageCreate, StageUpdate
from app.modules.whatsapp_inbox.models import WhatsappMessage

EVENT_CLIENT_MOVED = "crm.client.moved"
EVENT_CLIENT_CREATED = "crm.client.created"
EVENT_CLIENT_RETURNED = "crm.client.returned"


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
    active = _ordered_stages(db)
    if data.after_stage_id is not None:
        try:
            after_index = next(
                i for i, s in enumerate(active) if s.id == data.after_stage_id
            )
        except StopIteration as e:
            raise CrmError("Etapa de referência não encontrada", 422) from e
        insert_index = after_index + 1
    else:
        insert_index = len(active)

    stage = PipelineStage(
        tenant_id=tenant_id,
        name=data.name,
        is_won=data.is_won,
        is_lost=data.is_lost,
    )
    ordered = active[:insert_index] + [stage] + active[insert_index:]
    for index, s in enumerate(ordered):
        s.position = index

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


# ── Linha do tempo ─────────────────────────────────────


def record_event(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    kind: str,
    title: str,
    actor: str,
    body: str = "",
    is_ai: bool = False,
) -> ClientEvent:
    """Grava um fato narrativo. **NÃO commita** — quem chama decide o momento.

    Mesmo padrão de `receivables.build_charge`: assim o evento entra na MESMA transação do
    fato que ele descreve, e não existe estado em que o card mudou de coluna mas a história
    não registrou (ou o contrário).
    """
    event = ClientEvent(
        tenant_id=tenant_id, client_id=client_id, kind=kind,
        title=title[:140], body=body, actor=actor, is_ai=is_ai,
    )
    db.add(event)
    return event


_ROTULO_DE_CHEGADA = {
    "landing": "Chegou pelo site",
    "api": "Chegou por integração",
    "whatsapp": "Chegou pelo WhatsApp",
    "import": "Veio de importação",
    "manual": "Cadastrado à mão",
}


def _titulo_de_chegada(source: str) -> str:
    """Um `source` novo (backend mais recente) cai num rótulo honesto em vez de sumir."""
    return _ROTULO_DE_CHEGADA.get(source, f"Chegou por “{source}”")


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
        # Forma comparável do telefone — é o que `absorb_lead` procura. Preenchida em TODO
        # caminho de criação, senão o backfill conserta o legado e o código novo reintroduz
        # linhas sem chave.
        phone_key=normalize_br(data.phone),
        document=data.document,
        gender=data.gender,
        birthdate=data.birthdate,
        notes=data.notes,
        tags=data.tags,
        source=data.source,
        stage_id=stage_id,
    )
    db.add(client)
    # `client.id` só existe depois do flush (o default `_uuid` é aplicado na descarga). Sem
    # isto, tanto a trilha quanto o evento apontariam para lugar nenhum — é exatamente a
    # dívida MNT-001 registrada no CLAUDE.md.
    db.flush()
    record_event(
        db, tenant_id=tenant_id, client_id=client.id, kind=KIND_LEAD_CREATED,
        title=_titulo_de_chegada(client.source), actor=actor, body=data.notes,
    )
    audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.client.create", target=client.id)
    db.commit()
    db.refresh(client)
    # Gatilho de automação: outros módulos podem reagir (ex.: auto-enroll no funil de entrada
    # padrão do tenant, ver funnels/automation.py).
    events.emit(
        EVENT_CLIENT_CREATED, tenant_id=tenant_id, client_id=client.id, source=client.source
    )
    return client


def _find_existing(db: Session, *, phone_key: str | None, email: str | None) -> Client | None:
    """Procura o contato por telefone normalizado e, em segundo lugar, por e-mail.

    Ordem `created_at, id` porque `phone_key` NÃO é único e não deve ser: marido e mulher
    compartilham telefone, e os cards duplicados que já existiam (não mesclados, por decisão
    do fundador) compartilham chave a partir do backfill da 0067. Sem um desempate
    determinístico, o próximo retorno cairia num card imprevisível e a história se partiria
    entre eles. O mais antigo é o que acumulou mais contexto.
    """
    if phone_key:
        achado = db.scalars(
            select(Client)
            .where(Client.phone_key == phone_key)
            .order_by(Client.created_at, Client.id)
        ).first()
        if achado is not None:
            return achado
    if email:
        return db.scalars(
            select(Client)
            .where(func.lower(Client.email) == email.strip().lower())
            .order_by(Client.created_at, Client.id)
        ).first()
    return None


_ROTULO_DE_RETORNO = {
    "landing": "Voltou pelo site",
    "api": "Voltou por integração",
}


def _titulo_de_retorno(source: str) -> str:
    return _ROTULO_DE_RETORNO.get(source, f"Voltou por “{source}”")


def absorb_lead(
    db: Session, *, tenant_id: str, actor: str, data: ClientCreate
) -> tuple[Client, bool]:
    """Porta ÚNICA de entrada de lead. Devolve `(contato, é_novo)`.

    Quem já existe é complementado — data nova e texto novo na linha do tempo — em vez de
    ganhar um card paralelo. É o que os três caminhos de captura (página pública, API de
    integração, WhatsApp) passam a usar.
    """
    existente = _find_existing(
        db,
        phone_key=normalize_br(data.phone),
        email=str(data.email) if data.email else None,
    )
    if existente is None:
        return create_client(db, tenant_id=tenant_id, actor=actor, data=data), True

    # Preenche só o que estava VAZIO. Sobrescrever apagaria o que o dono já corrigiu à mão;
    # a divergência (chegou outro e-mail) fica registrada no corpo do evento.
    complementos: list[str] = []
    if not existente.email and data.email:
        existente.email = str(data.email)
        complementos.append(f"e-mail: {data.email}")
    elif data.email and existente.email != str(data.email):
        complementos.append(f"informou outro e-mail: {data.email}")
    if not existente.phone and data.phone:
        existente.phone = data.phone
        existente.phone_key = normalize_br(data.phone)
        complementos.append(f"telefone: {data.phone}")
    if not existente.document and data.document:
        existente.document = data.document
        complementos.append(f"documento: {data.document}")
    if not existente.phone_key and existente.phone:
        # Contato legado cujo telefone não normalizava na 0067 (ou nasceu antes dela).
        existente.phone_key = normalize_br(existente.phone)

    corpo = "\n".join(filter(None, [data.notes, *complementos]))
    record_event(
        db, tenant_id=tenant_id, client_id=existente.id, kind=KIND_LEAD_RETURN,
        title=_titulo_de_retorno(data.source), actor=actor, body=corpo,
    )

    # Coluna terminal (ganho OU perda) = a negociação anterior fechou. Quem volta sozinho
    # depois disso é oportunidade nova: perdido que voltou, ou cliente querendo comprar de
    # novo. Coluna do meio NÃO se move — puxar de volta apagaria trabalho em andamento.
    etapa = db.get(PipelineStage, existente.stage_id) if existente.stage_id else None
    if etapa is not None and (etapa.is_won or etapa.is_lost):
        ativas = _ordered_stages(db)
        if ativas:
            existente.stage_id = ativas[0].id
            record_event(
                db, tenant_id=tenant_id, client_id=existente.id, kind=KIND_REOPENED,
                title=f"Reaberto em {ativas[0].name} (estava em {etapa.name})", actor=actor,
            )

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="crm.client.return", target=existente.id
    )
    db.commit()
    db.refresh(existente)
    events.emit(
        EVENT_CLIENT_RETURNED,
        tenant_id=tenant_id,
        client_id=existente.id,
        source=data.source,
    )
    return existente, False


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
    origem = db.get(PipelineStage, from_stage) if from_stage else None
    nome_origem = origem.name if origem is not None else "sem etapa"
    client.stage_id = target.id
    # Guarda os NOMES, não os ids: renomear ou arquivar a coluna depois não pode reescrever
    # o que aconteceu naquele dia (princípio do `raw_description` de bank_transactions).
    record_event(
        db, tenant_id=tenant_id, client_id=client.id, kind=KIND_STAGE_MOVE,
        title=f"Movido de {nome_origem} → {target.name}", actor=actor, is_ai=by_ai,
    )
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


def last_interaction_map(db: Session) -> dict[str, datetime]:
    """Data da última interação por contato, para o card do Kanban.

    Duas consultas AGRUPADAS para o board inteiro, em vez de uma coluna
    `clients.last_interaction_at`. Coluna seria um valor derivado guardado — a forma exata do
    bug que a Onda 0 do Epic 8 corrigiu — e dessincronizaria no primeiro caminho de escrita
    que alguém esquecesse de atualizar. Assim é correto por construção.

    A sessão já está isolada por tenant (RLS): nada de filtro manual de `tenant_id`.
    """
    ultimo: dict[str, datetime] = {}
    for tabela, coluna in (
        (ClientEvent, ClientEvent.client_id),
        (WhatsappMessage, WhatsappMessage.client_id),
    ):
        linhas = db.execute(
            select(coluna, func.max(tabela.created_at))
            .where(coluna.is_not(None))
            .group_by(coluna)
        ).all()
        for client_id, quando in linhas:
            if quando is None:
                continue
            atual = ultimo.get(client_id)
            if atual is None or quando > atual:
                ultimo[client_id] = quando
    return ultimo


def build_board(db: Session, tenant_id: str) -> list[tuple[PipelineStage, list[Client]]]:
    stages = ensure_stages(db, tenant_id)
    clients = list(db.scalars(select(Client).order_by(Client.name)).all())
    by_stage: dict[str | None, list[Client]] = {}
    for c in clients:
        by_stage.setdefault(c.stage_id, []).append(c)
    return [(stage, by_stage.get(stage.id, [])) for stage in stages]
