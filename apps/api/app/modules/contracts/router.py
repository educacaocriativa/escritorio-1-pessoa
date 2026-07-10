"""Rotas do Construtor de Contratos (privadas) + assinatura pública (sem login)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_db, get_tenant_session_factory
from app.modules.contracts import service
from app.modules.contracts.models import Contract
from app.modules.contracts.schemas import (
    ContractCreate,
    ContractOut,
    ContractsSummary,
    ContractUpdate,
    PublicContract,
    SignRequest,
    TemplateCreate,
    TemplateOut,
)
from app.modules.crm.models import Client

router = APIRouter(prefix="/contracts", tags=["contracts"])
public_router = APIRouter(prefix="/public/contracts", tags=["contracts-public"])

_guard = require_module("contracts")


def _out(c: Contract, db: Session) -> ContractOut:
    client = db.get(Client, c.client_id) if c.client_id else None
    return ContractOut(
        id=c.id,
        tenant_id=c.tenant_id,
        client_id=c.client_id,
        client_name=client.name if client else None,
        quote_id=c.quote_id,
        title=c.title,
        clauses=c.clauses,
        status=c.status,
        public_slug=c.public_slug,
        signer_name=c.signer_name,
        signer_document=c.signer_document,
        signed_at=c.signed_at,
        created_at=c.created_at,
    )


def _err(e: service.ContractError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/summary", response_model=ContractsSummary)
def summary(
    _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> ContractsSummary:
    return ContractsSummary(**service.summary(db))


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> list[TemplateOut]:
    return [
        TemplateOut(id=t.id, name=t.name, clauses=t.clauses, created_at=t.created_at)
        for t in service.list_templates(db, user.tenant_id)
    ]


@router.post("/templates", response_model=TemplateOut, status_code=201)
def create_template(
    data: TemplateCreate, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> TemplateOut:
    t = service.create_template(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    return TemplateOut(id=t.id, name=t.name, clauses=t.clauses, created_at=t.created_at)


@router.get("", response_model=list[ContractOut])
def list_contracts(
    status: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ContractOut]:
    return [_out(c, db) for c in service.list_contracts(db, status=status, client_id=client_id)]


@router.post("", response_model=ContractOut, status_code=201)
def create_contract(
    data: ContractCreate, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> ContractOut:
    c = service.create_contract(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    return _out(c, db)


@router.get("/{contract_id}", response_model=ContractOut)
def get_contract(
    contract_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> ContractOut:
    try:
        return _out(service.get_contract(db, contract_id), db)
    except service.ContractError as e:
        raise _err(e) from e


@router.patch("/{contract_id}", response_model=ContractOut)
def update_contract(
    contract_id: str,
    data: ContractUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ContractOut:
    try:
        c = service.update_contract(
            db, contract_id=contract_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.ContractError as e:
        raise _err(e) from e
    return _out(c, db)


def _transition(fn, contract_id, user, db) -> ContractOut:
    try:
        c = fn(db, contract_id=contract_id, tenant_id=user.tenant_id, actor=user.user_id)
    except service.ContractError as e:
        raise _err(e) from e
    return _out(c, db)


@router.post("/{contract_id}/send", response_model=ContractOut)
def send_contract(
    contract_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    return _transition(service.send_contract, contract_id, user, db)


@router.post("/{contract_id}/cancel", response_model=ContractOut)
def cancel_contract(
    contract_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
):
    return _transition(service.cancel_contract, contract_id, user, db)


# ── Público (sem login) ─────────────────────────────────────────────────────
@public_router.get("/{slug}", response_model=PublicContract)
def public_view(slug: str, db: Session = Depends(get_db)) -> PublicContract:
    """Uso LEGÍTIMO de `get_db` (sem tenant): rota pública lê `published_contracts`, um snapshot
    GLOBAL sem RLS. NÃO toca `users` nem tabelas de negócio por tenant — seguro por design
    (guarda explícita exigida pela Story 1.2, AC1)."""
    try:
        return PublicContract(**service.public_view(db, slug=slug))
    except service.ContractError as e:
        raise _err(e) from e


@public_router.post("/{slug}/sign")
def public_sign(
    slug: str,
    data: SignRequest,
    request: Request,
    db: Session = Depends(get_db),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    if not data.accept:
        raise HTTPException(status_code=400, detail="É necessário aceitar para assinar")
    ip = request.client.host if request.client else ""
    try:
        signed_at = service.public_sign(
            db, slug=slug, name=data.name, document=data.document, ip=ip,
            session_factory=session_factory,
        )
    except service.ContractError as e:
        raise _err(e) from e
    return {"status": "signed", "signed_at": signed_at.isoformat()}
