"""Anexos: validação de tipo/tamanho, criação, listagem, download e remoção."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.attachments.models import ALLOWED_TYPES, MAX_BYTES, Attachment


class AttachmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def create_attachment(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    owner_type: str,
    owner_id: str,
    label: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> Attachment:
    if content_type not in ALLOWED_TYPES:
        raise AttachmentError("Tipo não permitido. Envie PDF, JPEG ou PNG.", 415)
    if not data:
        raise AttachmentError("Arquivo vazio", 422)
    if len(data) > MAX_BYTES:
        raise AttachmentError("Arquivo acima de 10 MB", 413)
    att = Attachment(
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        label=label or "outro",
        filename=filename or "arquivo",
        content_type=content_type,
        size=len(data),
        data=data,
    )
    db.add(att)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="attachment.create", target=att.id)
    db.commit()
    db.refresh(att)
    return att


def list_for(db: Session, *, owner_type: str, owner_id: str) -> list[Attachment]:
    stmt = (
        select(Attachment)
        .where(Attachment.owner_type == owner_type, Attachment.owner_id == owner_id)
        .order_by(Attachment.created_at)
    )
    return list(db.scalars(stmt).all())


def get_attachment(db: Session, attachment_id: str) -> Attachment:
    att = db.get(Attachment, attachment_id)
    if att is None:
        raise AttachmentError("Anexo não encontrado", 404)
    return att


def delete_attachment(db: Session, *, attachment_id: str, tenant_id: str, actor: str) -> None:
    att = get_attachment(db, attachment_id)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="attachment.delete", target=att.id)
    db.delete(att)
    db.commit()
