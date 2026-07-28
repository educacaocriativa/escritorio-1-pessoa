"""Rotas da bandeja de comprovantes (`/payables/receipts`).

Separado de `payables/router.py` porque é um fluxo próprio (entrada pelo celular) com
autenticação própria a partir da Task 6 — misturar os dois deixaria o router de contas
difícil de ler.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.attachments.models import Attachment
from app.modules.payables import receipts, service as payables_service
from app.modules.payables.receipts_schemas import ReceiptOut
from app.modules.payables.schemas import PayableOut

router = APIRouter(prefix="/payables/receipts", tags=["payables-receipts"])

_guard = require_module("payables")


def _out(a: Attachment) -> ReceiptOut:
    return ReceiptOut(
        id=a.id, filename=a.filename, content_type=a.content_type,
        size=a.size, created_at=a.created_at,
    )


def _err(e: Exception, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(e))


@router.post("", response_model=ReceiptOut, status_code=201)
async def upload_receipt(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ReceiptOut:
    """Recebe o comprovante e guarda na bandeja. É a única rota que as portas de entrada
    (Share Target do Android, Atalho do iOS) conhecem."""
    from app.modules.attachments.service import AttachmentError

    data = await file.read()
    try:
        att = receipts.stage_receipt(
            db, tenant_id=user.tenant_id, user_id=user.user_id, actor=user.user_id,
            filename=file.filename or "comprovante",
            content_type=file.content_type or "", data=data,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    except AttachmentError as e:
        # Propaga 413/422 de create_attachment em vez de achatar em 400.
        raise _err(e, e.status_code) from e
    return _out(att)


@router.get("", response_model=list[ReceiptOut])
def list_receipts(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ReceiptOut]:
    return [_out(a) for a in receipts.list_inbox(db, user_id=user.user_id)]


@router.get("/candidates", response_model=list[PayableOut])
def list_candidates(
    q: str = Query(default=""),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[PayableOut]:
    """Contas que podem receber o comprovante. Reusa PayableOut para o front não precisar de
    um tipo novo (o cartão mostra descrição, fornecedor, valor, vencimento e is_overdue)."""
    return [payables_service.payable_out(p) for p in receipts.list_candidates(db, q=q)]


@router.delete("/{attachment_id}", status_code=204)
def discard_receipt(
    attachment_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    try:
        receipts.discard(
            db, attachment_id=attachment_id, user_id=user.user_id,
            tenant_id=user.tenant_id, actor=user.user_id,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    return Response(status_code=204)
