"""Rotas de Anexos: upload (multipart), listar, baixar, remover."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.db.session import get_db
from app.modules.attachments import service
from app.modules.attachments.models import Attachment
from app.modules.attachments.schemas import AttachmentOut, PublicImageOut

router = APIRouter(prefix="/attachments", tags=["attachments"])
# Leitura PÚBLICA (sem login) de imagens intencionalmente públicas — mesmo desenho de
# quotes.public_router / pages.public_router (snapshot global sem RLS).
public_router = APIRouter(prefix="/public-images", tags=["attachments-public"])

_guard = require_module("attachments")


def _out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=a.id, owner_type=a.owner_type, owner_id=a.owner_id, label=a.label,
        filename=a.filename, content_type=a.content_type, size=a.size, created_at=a.created_at,
    )


def _err(e: service.AttachmentError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.get("", response_model=list[AttachmentOut])
def list_attachments(
    owner_type: str = Query(...),
    owner_id: str = Query(...),
    _u: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[AttachmentOut]:
    return [_out(a) for a in service.list_for(db, owner_type=owner_type, owner_id=owner_id)]


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    owner_type: str = Form(...),
    owner_id: str = Form(...),
    label: str = Form("outro"),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> AttachmentOut:
    data = await file.read()
    try:
        att = service.create_attachment(
            db, tenant_id=user.tenant_id, actor=user.user_id,
            owner_type=owner_type, owner_id=owner_id, label=label,
            filename=file.filename or "arquivo", content_type=file.content_type or "", data=data,
        )
    except service.AttachmentError as e:
        raise _err(e) from e
    return _out(att)


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: str, _u: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> Response:
    try:
        att, data = service.get_attachment_bytes(db, attachment_id)
    except service.AttachmentError as e:
        raise _err(e) from e
    return Response(
        content=data,
        media_type=att.content_type,
        headers={"Content-Disposition": f'inline; filename="{att.filename}"'},
    )


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: str, user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> Response:
    try:
        service.delete_attachment(
            db, attachment_id=attachment_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.AttachmentError as e:
        raise _err(e) from e
    return Response(status_code=204)


# ── Imagens públicas ─────────────────────────────────────────────────────────
@router.post("/public-images", response_model=PublicImageOut, status_code=201)
async def upload_public_image(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PublicImageOut:
    """Upload autenticado de imagem intencionalmente pública (logo/foto). A leitura depois é
    pública (ver `serve_public_image`). Devolve o caminho da rota de leitura no backend; o
    frontend prefixa o proxy `/api` para obter a URL renderável em `<img src>`."""
    data = await file.read()
    try:
        img = service.create_public_image(
            db, tenant_id=user.tenant_id, actor=user.user_id,
            content_type=file.content_type or "", data=data,
        )
    except service.AttachmentError as e:
        raise _err(e) from e
    return PublicImageOut(id=img.id, url=f"/public-images/{img.id}")


@public_router.get("/{image_id}")
def serve_public_image(image_id: str, db: Session = Depends(get_db)) -> Response:
    """Uso LEGÍTIMO de `get_db` (sem tenant): rota pública lê `public_images`, tabela GLOBAL
    sem RLS. NÃO toca `users` nem tabelas de negócio por tenant — seguro por design. Serve os
    bytes inline (sem `Content-Disposition: attachment`) para renderizar como `<img>`."""
    try:
        img = service.get_public_image(db, image_id)
    except service.AttachmentError as e:
        raise _err(e) from e
    return Response(content=img.data, media_type=img.content_type)
