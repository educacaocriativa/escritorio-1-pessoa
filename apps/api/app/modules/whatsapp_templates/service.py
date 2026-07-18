"""Templates de WhatsApp (Meta Cloud API) — CRUD local + sincronização com a Graph API.

Todo envio business-initiated (fora da janela de 24h) exige um template pré-aprovado pela Meta
(ver `app/modules/whatsapp_templates/models.py`). Este service propõe o template (`create_template`,
que chama `core/whatsapp.create_template`), consulta o status de aprovação (`sync_template`) e
remove tanto localmente quanto na Meta (`delete_template`, best-effort do lado da Meta).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, whatsapp
from app.modules.settings.service import get_profile
from app.modules.whatsapp_templates.models import STATUS_PENDING, WhatsappTemplate
from app.modules.whatsapp_templates.schemas import TemplateCreate

logger = logging.getLogger("e1p.whatsapp_templates")

_PLACEHOLDER_RE = re.compile(r"\{\{(\d+)\}\}")


class WhatsappTemplateError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _validate_variables(body_text: str, variable_examples: list[str]) -> int:
    """Extrai os placeholders {{n}} do corpo e garante que formam o conjunto contíguo {1..N},
    sem lacunas nem duplicatas, e que há exatamente N exemplos (a Meta exige exemplo por
    variável). Retorna N. Levanta WhatsappTemplateError (422) se algo não bater."""
    numbers = [int(m.group(1)) for m in _PLACEHOLDER_RE.finditer(body_text)]
    unique = set(numbers)
    n = len(unique)
    if n == 0:
        if variable_examples:
            raise WhatsappTemplateError(
                "O corpo não usa variáveis ({{1}}, {{2}}, ...) mas foram informados exemplos", 422
            )
        return 0
    if unique != set(range(1, n + 1)):
        raise WhatsappTemplateError(
            "As variáveis do corpo devem ser contíguas e começar em 1 ({{1}}, {{2}}, ...), "
            "sem lacunas nem repetição de número diferente", 422
        )
    if len(variable_examples) != n:
        found = len(variable_examples)
        raise WhatsappTemplateError(
            f"Informe exatamente {n} exemplo(s) de variável (encontrado(s) {found})", 422
        )
    return n


def create_template(
    db: Session, *, tenant_id: str, actor: str, data: TemplateCreate
) -> WhatsappTemplate:
    profile = get_profile(db, tenant_id)
    if not profile.whatsapp_waba_id or not profile.whatsapp_token:
        raise WhatsappTemplateError(
            "Configure as credenciais do WhatsApp (Configurações → Integrações) antes de "
            "criar um template",
            422,
        )
    variable_count = _validate_variables(data.body_text, data.variable_examples)

    try:
        resp = whatsapp.create_template(
            waba_id=profile.whatsapp_waba_id,
            token=profile.whatsapp_token,
            name=data.name,
            language=data.language,
            category=data.category,
            body_text=data.body_text,
            variable_examples=data.variable_examples,
        )
    except whatsapp.WhatsappApiError as e:
        raise WhatsappTemplateError(str(e), 422) from e

    template = WhatsappTemplate(
        tenant_id=tenant_id,
        name=data.name,
        language=data.language,
        category_requested=data.category,
        category_approved=resp.get("category"),
        status=resp.get("status") or STATUS_PENDING,
        meta_template_id=resp.get("id"),
        body_text=data.body_text,
        variable_count=variable_count,
        variable_examples=data.variable_examples,
    )
    db.add(template)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_template.create", target=template.id
    )
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise WhatsappTemplateError("Já existe um template com esse nome e idioma", 409) from e
    db.refresh(template)
    return template


def list_templates(
    db: Session, tenant_id: str, *, status: str | None = None
) -> list[WhatsappTemplate]:
    # NÃO filtra por tenant_id manualmente — RLS já isola (Regra de Ouro nº 1).
    stmt = select(WhatsappTemplate)
    if status:
        stmt = stmt.where(WhatsappTemplate.status == status)
    stmt = stmt.order_by(WhatsappTemplate.created_at.desc())
    return list(db.scalars(stmt).all())


def _get(db: Session, template_id: str) -> WhatsappTemplate:
    template = db.get(WhatsappTemplate, template_id)
    if template is None:
        raise WhatsappTemplateError("Template não encontrado", 404)
    return template


def sync_template(db: Session, *, tenant_id: str, template_id: str) -> WhatsappTemplate:
    template = _get(db, template_id)
    if template.meta_template_id is None:
        raise WhatsappTemplateError("Template ainda não foi submetido à Meta", 422)
    profile = get_profile(db, tenant_id)
    try:
        resp = whatsapp.fetch_template_status(
            token=profile.whatsapp_token, meta_template_id=template.meta_template_id
        )
    except whatsapp.WhatsappApiError as e:
        raise WhatsappTemplateError(str(e), 422) from e

    if resp.get("status"):
        template.status = resp["status"]
    template.category_approved = resp.get("category")
    template.rejected_reason = resp.get("rejected_reason")
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, *, tenant_id: str, actor: str, template_id: str) -> None:
    template = _get(db, template_id)
    profile = get_profile(db, tenant_id)
    try:
        whatsapp.delete_template(
            waba_id=profile.whatsapp_waba_id, token=profile.whatsapp_token, name=template.name
        )
    except whatsapp.WhatsappApiError:
        logger.warning(
            "[whatsapp_template:delete] falha ao excluir na Meta (mantendo exclusão local) "
            "template_id=%s name=%s", template_id, template.name,
        )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="whatsapp_template.delete", target=template.id
    )
    db.delete(template)
    db.commit()
