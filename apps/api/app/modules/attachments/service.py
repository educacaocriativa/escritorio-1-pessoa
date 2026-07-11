"""Anexos: validação de tipo/tamanho, criação, listagem, download e remoção."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.attachments.models import (
    ALLOWED_TYPES,
    MAX_BYTES,
    PUBLIC_IMAGE_TYPES,
    Attachment,
    PublicImage,
)


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


# ── Imagens públicas (logo/fotos renderizadas em <img> — ver PublicImage) ────────────────
def create_public_image(
    db: Session, *, tenant_id: str, actor: str, content_type: str, data: bytes
) -> PublicImage:
    """Cria uma imagem pública (escrita autenticada; leitura será pública). Mesmas regras de
    tamanho do módulo de Anexos (10 MB), mas restrito a imagem (JPEG/PNG — sem PDF)."""
    if content_type not in PUBLIC_IMAGE_TYPES:
        raise AttachmentError("Tipo não permitido. Envie uma imagem JPEG ou PNG.", 415)
    if not data:
        raise AttachmentError("Arquivo vazio", 422)
    if len(data) > MAX_BYTES:
        raise AttachmentError("Arquivo acima de 10 MB", 413)
    img = PublicImage(tenant_id=tenant_id, content_type=content_type, size=len(data), data=data)
    db.add(img)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="public_image.create", target=img.id)
    db.commit()
    db.refresh(img)
    return img


def get_public_image(db: Session, image_id: str) -> PublicImage:
    img = db.get(PublicImage, image_id)
    if img is None:
        raise AttachmentError("Imagem não encontrada", 404)
    return img
