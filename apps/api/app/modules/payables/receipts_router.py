"""Rotas da bandeja de comprovantes (`/payables/receipts`).

Separado de `payables/router.py` porque é um fluxo próprio (entrada pelo celular) com
autenticação própria a partir da Task 6 — misturar os dois deixaria o router de contas
difícil de ler.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.receipt_auth import get_receipt_db, receipt_uploader
from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.attachments.models import Attachment
from app.modules.payables import receipts
from app.modules.payables import service as payables_service
from app.modules.payables.receipts_schemas import ReceiptLinkIn, ReceiptNewBillIn, ReceiptOut
from app.modules.payables.schemas import PayableCreate, PayableOut
from app.modules.settings.service import hoje_do_tenant

router = APIRouter(prefix="/payables/receipts", tags=["payables-receipts"])

_guard = require_module("payables")


def _out(a: Attachment) -> ReceiptOut:
    return ReceiptOut(
        id=a.id, filename=a.filename, content_type=a.content_type,
        size=a.size, created_at=a.created_at,
    )


def _err(e: Exception, status_code: int) -> HTTPException:
    """`detail` estruturado quando o erro é ACIONÁVEL; string em todo o resto.

    A bandeja é a **mesma** superfície de baixa do `POST /bills/{id}/pay`, então ela devolve o
    **mesmo** 409 `{"acao": "cadastrar_conta", "mensagem": ...}` (Story 8.12 AC2/AC10) quando o
    tenant não tem conta primária. Dois formatos de erro para a mesma situação obrigariam a UI da
    8.13 a tratar cada porta de um jeito.
    """
    return HTTPException(status_code=status_code, detail=getattr(e, "detail", None) or str(e))


@router.post("", response_model=ReceiptOut, status_code=201)
async def upload_receipt(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(receipt_uploader),
    db: Session = Depends(get_receipt_db),
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


# IMPORTANT: Literal path "/candidates" must stay declared before parameterized "/{attachment_id}"
# to ensure GET /candidates resolves correctly. Although today no GET /{attachment_id} exists
# (only DELETE), if one were added in the future, it would silently swallow this route.
# Keep this ordering defensive.
@router.get("/candidates", response_model=list[PayableOut])
def list_candidates(
    q: str = Query(default=""),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[PayableOut]:
    """Contas que podem receber o comprovante. Reusa PayableOut para o front não precisar de
    um tipo novo (o cartão mostra descrição, fornecedor, valor, vencimento e is_overdue)."""
    hoje = hoje_do_tenant(db)  # uma leitura de fuso para a lista inteira, não uma por linha
    return [payables_service.payable_out(p, hoje) for p in receipts.list_candidates(db, q=q)]


@router.post("/{attachment_id}/link", response_model=PayableOut)
def link_receipt(
    attachment_id: str,
    data: ReceiptLinkIn,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = receipts.link_receipt(
            db, attachment_id=attachment_id, user_id=user.user_id, tenant_id=user.tenant_id,
            actor=user.user_id, bill_id=data.bill_id, mark_paid=data.mark_paid,
            # Story 8.13: a conta e a data vêm da tela — o backend não elege mais a primária.
            bank_account_id=data.bank_account_id, paid_on=data.paid_on,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    except payables_service.PayableError as e:
        raise _err(e, e.status_code) from e
    return payables_service.payable_out(p, hoje_do_tenant(db))


@router.post("/{attachment_id}/new-bill", response_model=PayableOut, status_code=201)
def new_bill_from_receipt(
    attachment_id: str,
    data: ReceiptNewBillIn,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    create = PayableCreate(
        description=data.description, category=data.category, supplier=data.supplier,
        amount_cents=data.amount_cents, due_date=data.due_date,
    )
    try:
        p = receipts.new_bill_from_receipt(
            db, attachment_id=attachment_id, user_id=user.user_id, tenant_id=user.tenant_id,
            actor=user.user_id, data=create, mark_paid=data.mark_paid,
            # Story 8.13: idem `link` — os dois campos atravessam até `apply_paid`.
            bank_account_id=data.bank_account_id, paid_on=data.paid_on,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    except payables_service.PayableError as e:
        raise _err(e, e.status_code) from e
    return payables_service.payable_out(p, hoje_do_tenant(db))


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
