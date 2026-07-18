"""Rotas de Templates de WhatsApp (Meta Cloud API)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.whatsapp_templates import service
from app.modules.whatsapp_templates.models import WhatsappTemplate
from app.modules.whatsapp_templates.schemas import TemplateCreate, TemplateOut

router = APIRouter(prefix="/whatsapp-templates", tags=["whatsapp-templates"])

_guard = require_module("settings")


def _out(t: WhatsappTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id, name=t.name, language=t.language, category_requested=t.category_requested,
        category_approved=t.category_approved, status=t.status, rejected_reason=t.rejected_reason,
        meta_template_id=t.meta_template_id, body_text=t.body_text,
        variable_count=t.variable_count, variable_examples=t.variable_examples,
        created_at=t.created_at, updated_at=t.updated_at,
    )


def _err(e: service.WhatsappTemplateError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=list[TemplateOut])
def list_templates(
    status: str | None = None,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[TemplateOut]:
    return [_out(t) for t in service.list_templates(db, user.tenant_id, status=status)]


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(
    data: TemplateCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> TemplateOut:
    try:
        template = service.create_template(
            db, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.WhatsappTemplateError as e:
        raise _err(e) from e
    return _out(template)


@router.post("/{template_id}/sync", response_model=TemplateOut)
def sync_template(
    template_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> TemplateOut:
    try:
        template = service.sync_template(db, tenant_id=user.tenant_id, template_id=template_id)
    except service.WhatsappTemplateError as e:
        raise _err(e) from e
    return _out(template)


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    try:
        service.delete_template(
            db, tenant_id=user.tenant_id, actor=user.user_id, template_id=template_id
        )
    except service.WhatsappTemplateError as e:
        raise _err(e) from e
    return Response(status_code=204)
