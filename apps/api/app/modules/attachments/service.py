"""Anexos: validação de tipo/tamanho, criação, listagem, download e remoção.

Story 3.5 — dual-write/dual-read: se o object storage S3 estiver configurado
(`storage.is_configured()`), os bytes vão para o bucket e a linha guarda só a `storage_key`;
senão, mantém o comportamento legado (bytes no Postgres, `data`). A leitura resolve a origem
automaticamente, então anexos antigos (pré-migração) continuam baixando normalmente (AC3).
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, storage
from app.modules.attachments.models import (
    ALLOWED_TYPES,
    MAX_BYTES,
    PUBLIC_IMAGE_TYPES,
    Attachment,
    PublicImage,
)

logger = logging.getLogger("e1p.attachments")


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
    safe_name = filename or "arquivo"
    # Instancia o ORM primeiro para materializar o `id` (default=_uuid roda ao construir o
    # objeto Python, antes do INSERT) — necessário para montar a storage_key antes do commit.
    att = Attachment(
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        label=label or "outro",
        filename=safe_name,
        content_type=content_type,
        size=len(data),
    )
    if storage.is_configured():
        # Storage S3 ligado: sobe os bytes e guarda só a chave (data fica None).
        key = storage.build_key(tenant_id, att.id, safe_name)
        storage.put_object(key, data, content_type)
        att.storage_key = key
        att.data = None
    else:
        # Fallback legado: bytes no Postgres (dev local / CI / staging sem bucket ainda).
        att.data = data
        att.storage_key = None
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


def get_attachment_bytes(db: Session, attachment_id: str) -> tuple[Attachment, bytes]:
    """Resolve os bytes do anexo, independente de onde moram (S3 ou Postgres).

    Se `storage_key` está setado, baixa do object storage; senão, usa `att.data` (fallback
    legado). Levanta AttachmentError 404 se o anexo não existir.
    """
    att = get_attachment(db, attachment_id)
    if att.storage_key:
        data = storage.get_object(att.storage_key)
    else:
        data = att.data or b""
    return att, data


def delete_attachment(db: Session, *, attachment_id: str, tenant_id: str, actor: str) -> None:
    att = get_attachment(db, attachment_id)
    # Best-effort: remove o objeto do storage antes de apagar o metadado. Uma falha no storage
    # (rede/objeto ausente) NÃO deve travar a remoção do metadado — só loga.
    if att.storage_key:
        try:
            storage.delete_object(att.storage_key)
        except Exception:  # noqa: BLE001 (best-effort: metadado é a fonte da verdade da remoção)
            logger.exception("[attachment:delete] falha ao remover objeto %s", att.storage_key)
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
