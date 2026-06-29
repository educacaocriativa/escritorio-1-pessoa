"""Construtor de Contratos: templates, preenchimento de variáveis, status e assinatura pública."""
from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import audit, whatsapp
from app.modules.auth.models import Tenant
from app.modules.contracts.models import (
    STATUS_CANCELLED,
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_SIGNED,
    Contract,
    ContractTemplate,
    PublishedContract,
)
from app.modules.contracts.schemas import Clause, ContractCreate, ContractUpdate, TemplateCreate
from app.modules.crm.models import Client
from app.modules.notifications.models import Notification

# Templates oferecidos a todo tenant na primeira vez (cláusulas com variáveis [CHAVE]).
DEFAULT_TEMPLATES: list[dict] = [
    {
        "name": "Prestação de serviços",
        "clauses": [
            {"title": "Partes", "text": "Contratante: [CLIENTE], inscrito sob [DOCUMENTO]. "
             "Contratada: [EMPRESA]."},
            {"title": "Objeto", "text": "A Contratada prestará os serviços de [OBJETO]."},
            {"title": "Valor", "text": "Pelos serviços, a Contratante pagará [VALOR]."},
            {"title": "Prazo", "text": "O contrato vigora a partir de [DATA] pelo prazo acordado."},
            {"title": "Foro", "text": "Fica eleito o foro da comarca da Contratada."},
        ],
    },
    {
        "name": "Confidencialidade (NDA)",
        "clauses": [
            {"title": "Partes",
             "text": "[EMPRESA] e [CLIENTE] firmam o presente acordo em [DATA]."},
            {"title": "Confidencialidade", "text": "As partes manterão sigilo sobre toda "
             "informação trocada, não a divulgando a terceiros."},
            {"title": "Vigência", "text": "A obrigação de sigilo perdura por 5 anos."},
        ],
    },
]


class ContractError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:40] or "contrato").strip("-")


def _gen_slug(title: str) -> str:
    return f"{_slugify(title)}-{secrets.token_urlsafe(12)}"


def _company_name(db: Session, tenant_id: str) -> str:
    t = db.get(Tenant, tenant_id)
    return t.legal_name if t else ""


def _fill(clauses: list[Clause], variables: dict[str, str]) -> list[dict]:
    """Substitui [CHAVE] pelo valor; variáveis explícitas têm prioridade sobre as automáticas."""
    out = []
    for c in clauses:
        text = c.text
        for key, val in variables.items():
            text = text.replace(f"[{key}]", val)
        out.append({"title": c.title, "text": text})
    return out


# ── Templates ───────────────────────────────────────────────────────────────
def ensure_default_templates(db: Session, tenant_id: str) -> None:
    has = db.scalar(select(func.count(ContractTemplate.id)))
    if has:
        return
    for tpl in DEFAULT_TEMPLATES:
        db.add(ContractTemplate(tenant_id=tenant_id, name=tpl["name"], clauses=tpl["clauses"]))
    db.commit()


def list_templates(db: Session, tenant_id: str) -> list[ContractTemplate]:
    ensure_default_templates(db, tenant_id)
    return list(db.scalars(select(ContractTemplate).order_by(ContractTemplate.name)).all())


def create_template(
    db: Session, *, tenant_id: str, actor: str, data: TemplateCreate
) -> ContractTemplate:
    tpl = ContractTemplate(
        tenant_id=tenant_id, name=data.name, clauses=[c.model_dump() for c in data.clauses]
    )
    db.add(tpl)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="contract.template.create", target=tpl.id
    )
    db.commit()
    db.refresh(tpl)
    return tpl


# ── Snapshot público ────────────────────────────────────────────────────────
def _snapshot(contract: Contract) -> dict:
    return {
        "title": contract.title,
        "clauses": contract.clauses,
        "status": contract.status,
        "signer_name": contract.signer_name,
        "signed_at": contract.signed_at.isoformat() if contract.signed_at else None,
    }


def _publish(db: Session, contract: Contract, company_name: str) -> None:
    if not contract.public_slug:
        return
    snap = db.get(PublishedContract, contract.public_slug)
    if snap is None:
        snap = PublishedContract(slug=contract.public_slug)
        db.add(snap)
    snap.tenant_id = contract.tenant_id
    snap.contract_id = contract.id
    snap.company_name = company_name
    snap.data = _snapshot(contract)


# ── Contratos ───────────────────────────────────────────────────────────────
def _auto_vars(db: Session, tenant_id: str, client_id: str | None, company: str) -> dict[str, str]:
    today = datetime.now(UTC).strftime("%d/%m/%Y")
    auto = {"DATA": today, "EMPRESA": company}
    if client_id:
        client = db.get(Client, client_id)
        if client:
            auto["CLIENTE"] = client.name
    return auto


def create_contract(db: Session, *, tenant_id: str, actor: str, data: ContractCreate) -> Contract:
    company = _company_name(db, tenant_id)
    variables = {**_auto_vars(db, tenant_id, data.client_id, company), **data.variables}
    contract = Contract(
        tenant_id=tenant_id,
        client_id=data.client_id,
        quote_id=data.quote_id,
        title=data.title,
        clauses=_fill(data.clauses, variables),
        public_slug=_gen_slug(data.title),
    )
    db.add(contract)
    db.flush()
    _publish(db, contract, company)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="contract.create", target=contract.id)
    db.commit()
    db.refresh(contract)
    return contract


def get_contract(db: Session, contract_id: str) -> Contract:
    c = db.get(Contract, contract_id)
    if c is None:
        raise ContractError("Contrato não encontrado", 404)
    return c


def list_contracts(db: Session, *, status: str | None = None) -> list[Contract]:
    stmt = select(Contract).order_by(Contract.created_at.desc())
    if status:
        stmt = stmt.where(Contract.status == status)
    return list(db.scalars(stmt).all())


def update_contract(
    db: Session, *, contract_id: str, tenant_id: str, actor: str, data: ContractUpdate
) -> Contract:
    c = get_contract(db, contract_id)
    if c.status != STATUS_DRAFT:
        raise ContractError("Só contratos em rascunho podem ser editados", 409)
    if data.title is not None:
        c.title = data.title
    if data.client_id is not None:
        c.client_id = data.client_id
    if data.clauses is not None:
        c.clauses = [cl.model_dump() for cl in data.clauses]
    _publish(db, c, _company_name(db, tenant_id))
    audit.record(db, tenant_id=tenant_id, actor=actor, action="contract.update", target=c.id)
    db.commit()
    db.refresh(c)
    return c


def send_contract(db: Session, *, contract_id: str, tenant_id: str, actor: str) -> Contract:
    c = get_contract(db, contract_id)
    if c.status not in (STATUS_DRAFT, STATUS_SENT):
        raise ContractError("Contrato já encerrado", 409)
    client = db.get(Client, c.client_id) if c.client_id else None
    recipient = (client.phone if client and client.phone else None) or (
        client.name if client else "cliente"
    )
    link = (
        f"{settings.frontend_url.rstrip('/')}/contrato/{c.public_slug}" if c.public_slug else ""
    )
    msg = f"Olá! Segue o contrato '{c.title}' para sua assinatura: {link}".strip()
    status = whatsapp.send_text(to=recipient, text=msg)
    db.add(
        Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=c.client_id, message=msg, status=status,
        )
    )
    c.status = STATUS_SENT
    _publish(db, c, _company_name(db, tenant_id))
    audit.record(db, tenant_id=tenant_id, actor=actor, action="contract.send", target=c.id)
    db.commit()
    db.refresh(c)
    return c


def cancel_contract(db: Session, *, contract_id: str, tenant_id: str, actor: str) -> Contract:
    c = get_contract(db, contract_id)
    if c.status == STATUS_SIGNED:
        raise ContractError("Contrato assinado não pode ser cancelado", 409)
    c.status = STATUS_CANCELLED
    _publish(db, c, _company_name(db, tenant_id))
    audit.record(db, tenant_id=tenant_id, actor=actor, action="contract.cancel", target=c.id)
    db.commit()
    db.refresh(c)
    return c


def summary(db: Session) -> dict:
    def count(st: str) -> int:
        return db.scalar(select(func.count(Contract.id)).where(Contract.status == st)) or 0

    return {
        "draft_count": count(STATUS_DRAFT),
        "sent_count": count(STATUS_SENT),
        "signed_count": count(STATUS_SIGNED),
    }


# ── Assinatura pública (sem login; lê o snapshot global) ────────────────────
def public_view(db: Session, *, slug: str) -> dict:
    snap = db.get(PublishedContract, slug)
    if snap is None:
        raise ContractError("Contrato não encontrado", 404)
    return {**snap.data, "company_name": snap.company_name}


def public_sign(
    db: Session, *, slug: str, name: str, document: str, ip: str, session_factory
) -> datetime:
    """Assinatura do cliente -> registra KYC (nome+documento+IP+data) e marca assinado."""
    snap = db.get(PublishedContract, slug)
    if snap is None:
        raise ContractError("Contrato não encontrado", 404)
    with session_factory(snap.tenant_id) as tdb:
        c = tdb.scalar(
            select(Contract).where(Contract.id == snap.contract_id).with_for_update()
        )
        if c is None:
            raise ContractError("Contrato não encontrado", 404)
        if c.status == STATUS_SIGNED:
            raise ContractError("Contrato já assinado", 409)
        if c.status == STATUS_CANCELLED:
            raise ContractError("Contrato cancelado", 409)
        c.signer_name = name
        c.signer_document = document
        c.signer_ip = ip
        c.signed_at = datetime.now(UTC)
        c.status = STATUS_SIGNED
        _publish(tdb, c, snap.company_name)
        audit.record(
            tdb, tenant_id=snap.tenant_id, actor=f"assinatura:{document}",
            action="contract.sign", target=c.id,
        )
        signed_at = c.signed_at
    return signed_at
