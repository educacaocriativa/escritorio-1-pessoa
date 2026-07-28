"""Bandeja de comprovantes: staging de arquivo antes de saber a qual conta ele pertence.

Um comprovante recém-chegado é um `Attachment` normal (RLS, storage S3/Postgres já resolvidos
por `attachments.service`) com `owner_type=OWNER_INBOX` e `owner_id=<user_id>`. Vincular à conta
depois é só trocar essas duas colunas — os bytes NUNCA se movem, porque a chave do storage
(`storage.build_key`) é `tenants/{tenant_id}/attachments/{id}/{filename}` e não carrega o dono.

Por isso a bandeja não tem tabela própria: qualquer porta de entrada nova (WhatsApp, e-mail)
só precisa gravar um Attachment com esse owner_type.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.attachments import service as attachments_service
from app.modules.attachments.models import Attachment
from app.modules.payables.models import STATUS_CANCELED, STATUS_OPEN, STATUS_PAID, Payable

# owner_type do anexo enquanto ele está em staging (ainda sem conta definida).
OWNER_INBOX = "receipt_inbox"
# owner_type do anexo depois de vinculado a uma conta a pagar.
OWNER_PAYABLE = "payable"
LABEL_COMPROVANTE = "comprovante"

# Mais restrito que ALLOWED_TYPES (que aceita áudio/vídeo por causa da mídia do WhatsApp):
# comprovante de banco é PDF ou foto.
RECEIPT_TYPES = {"application/pdf", "image/jpeg", "image/png"}

# Teto de itens em staging por usuário. Existe para limitar o dano de um token de dispositivo
# vazado (ver core/receipt_auth.py): o pior caso vira "enche a bandeja", não "enche o storage".
INBOX_MAX_ITEMS = 30


class ReceiptError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _inbox_count(db: Session, *, user_id: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Attachment)
        .where(Attachment.owner_type == OWNER_INBOX, Attachment.owner_id == user_id)
    ) or 0


def stage_receipt(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    actor: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> Attachment:
    """Guarda o arquivo na bandeja do usuário. Valida o tipo ANTES de tocar no storage."""
    if content_type not in RECEIPT_TYPES:
        raise ReceiptError("Envie o comprovante em PDF, JPEG ou PNG.", 415)
    if _inbox_count(db, user_id=user_id) >= INBOX_MAX_ITEMS:
        raise ReceiptError(
            f"Bandeja cheia ({INBOX_MAX_ITEMS} comprovantes). "
            "Vincule ou descarte os pendentes antes de enviar outro.",
            409,
        )
    # create_attachment cuida de tamanho/vazio (413/422), storage S3 vs Postgres, e auditoria.
    return attachments_service.create_attachment(
        db,
        tenant_id=tenant_id,
        actor=actor,
        owner_type=OWNER_INBOX,
        owner_id=user_id,
        label=LABEL_COMPROVANTE,
        filename=filename,
        content_type=content_type,
        data=data,
    )


def list_inbox(db: Session, *, user_id: str) -> list[Attachment]:
    """Comprovantes do usuário ainda não vinculados, mais recentes primeiro."""
    stmt = (
        select(Attachment)
        .where(Attachment.owner_type == OWNER_INBOX, Attachment.owner_id == user_id)
        .order_by(Attachment.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def get_staged(db: Session, *, attachment_id: str, user_id: str) -> Attachment:
    """Resolve um anexo que DEVE estar na bandeja do usuário.

    Distingue os dois "não encontrado" de propósito: já vinculado é 409 (o usuário fez algo
    válido, só que duas vezes); de outro usuário é 404 (não existe, do ponto de vista dele).
    """
    att = db.get(Attachment, attachment_id)
    if att is None:
        raise ReceiptError("Comprovante não encontrado", 404)
    if att.owner_type != OWNER_INBOX:
        raise ReceiptError("Este comprovante já foi anexado a uma conta", 409)
    if att.owner_id != user_id:
        raise ReceiptError("Comprovante não encontrado", 404)
    return att


def discard(db: Session, *, attachment_id: str, user_id: str, tenant_id: str, actor: str) -> None:
    get_staged(db, attachment_id=attachment_id, user_id=user_id)
    attachments_service.delete_attachment(
        db, attachment_id=attachment_id, tenant_id=tenant_id, actor=actor
    )


def list_candidates(db: Session, *, q: str = "", paid_window_days: int = 30) -> list[Payable]:
    """Lista curta para escolher no celular: abertas primeiro (por vencimento, então as
    vencidas caem naturalmente no topo), depois as pagas recentes — o caso de quem já deu
    baixa e só faltava o comprovante. Canceladas nunca aparecem.

    A ordenação é feita em duas queries, não num ORDER BY composto, porque os dois grupos
    ordenam por colunas diferentes (due_date crescente vs paid_at decrescente).
    """
    term = q.strip().lower()

    def _match(stmt):
        if not term:
            return stmt
        like = f"%{term}%"
        return stmt.where(
            func.lower(Payable.description).like(like) | func.lower(Payable.supplier).like(like)
        )

    abertas = list(
        db.scalars(
            _match(select(Payable).where(Payable.status == STATUS_OPEN))
            .order_by(Payable.due_date)
            .limit(100)
        ).all()
    )
    cutoff = datetime.now(UTC) - timedelta(days=paid_window_days)
    pagas = list(
        db.scalars(
            _match(
                select(Payable).where(Payable.status == STATUS_PAID, Payable.paid_at >= cutoff)
            )
            .order_by(Payable.paid_at.desc())
            .limit(100)
        ).all()
    )
    # Contas canceladas nunca entram: nenhum dos dois filtros (status aberta ou status paga)
    # as inclui, portanto não precisamos de um `.where(status != cancelada)` explícito.
    return (abertas + pagas)[:100]


def _attach_and_commit(
    db: Session,
    att: Attachment,
    p: Payable,
    *,
    tenant_id: str,
    actor: str,
    mark_paid: bool,
) -> Payable:
    """Move o anexo da bandeja para a conta e fecha a transação (com baixa, se pedido).

    Extraído porque `link_receipt` (conta existente) e `new_bill_from_receipt` (conta nova)
    terminam exatamente igual — só a origem da conta difere.
    """
    from app.core import audit
    from app.modules.payables import service as payables_service

    att.owner_type = OWNER_PAYABLE
    att.owner_id = p.id
    att.label = LABEL_COMPROVANTE

    # Conta já paga não é re-datada; `apply_paid` não commita, então a baixa e o vínculo
    # caem na MESMA transação.
    if mark_paid and p.status == STATUS_OPEN:
        payables_service.apply_paid(db, payable_id=p.id, tenant_id=tenant_id, actor=actor)

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="payable.receipt_linked", target=p.id
    )
    db.commit()
    db.refresh(p)
    return p


def link_receipt(
    db: Session,
    *,
    attachment_id: str,
    user_id: str,
    tenant_id: str,
    actor: str,
    bill_id: str,
    mark_paid: bool,
) -> Payable:
    """Vincula o comprovante a uma conta existente e, se pedido, dá a baixa.

    Vincular é trocar owner_type/owner_id do Attachment: os bytes ficam onde estão.
    """
    att = get_staged(db, attachment_id=attachment_id, user_id=user_id)

    p = db.get(Payable, bill_id)
    if p is None:
        raise ReceiptError("Conta não encontrada", 404)
    if p.status == STATUS_CANCELED:
        raise ReceiptError("Conta cancelada não recebe comprovante", 409)

    return _attach_and_commit(
        db, att, p, tenant_id=tenant_id, actor=actor, mark_paid=mark_paid
    )
