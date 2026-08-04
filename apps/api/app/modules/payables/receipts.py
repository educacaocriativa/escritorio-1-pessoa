"""Bandeja de comprovantes: staging de arquivo antes de saber a qual conta ele pertence.

Um comprovante recém-chegado é um `Attachment` normal (RLS, storage S3/Postgres já resolvidos
por `attachments.service`) com `owner_type=OWNER_INBOX` e `owner_id=<user_id>`. Vincular à conta
depois é só trocar essas duas colunas — os bytes NUNCA se movem, porque a chave do storage
(`storage.build_key`) é `tenants/{tenant_id}/attachments/{id}/{filename}` e não carrega o dono.

Por isso a bandeja não tem tabela própria: qualquer porta de entrada nova (WhatsApp, e-mail)
só precisa gravar um Attachment com esse owner_type.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.attachments import service as attachments_service
from app.modules.attachments.models import Attachment
from app.modules.payables.models import (
    STATUS_CANCELED,
    STATUS_OPEN,
    STATUS_PAID,
    STATUS_SCHEDULED,
    Payable,
)

# Os estados em que a baixa já aconteceu — o dinheiro saiu (`paid`) ou já tem dia marcado para sair
# (`scheduled`, Story 8.14). Nos dois o comprovante do banco **já existe e o dono o tem na mão**.
# `open` tem query própria (ordena por `due_date`); `canceled` nunca entra.
_ESTADOS_LIQUIDADOS: tuple[str, ...] = (STATUS_PAID, STATUS_SCHEDULED)

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

    ⚠️ **[Story 8.14] As AGENDADAS entram junto das pagas recentes** (AC11), pela mesma janela e a
    mesma ordenação. *"O comprovante do agendamento existe e é o que o dono tem na mão"* — o app do
    banco emite o comprovante do agendamento na hora, e é aquele PDF que ele compartilha pelo
    celular. Deixar a agendada de fora obrigaria o dono a esperar o dia do débito para anexar um
    arquivo que ele já tem — e, na prática, a nunca anexar.

    A janela de `paid_window_days` continua sendo aplicada sobre `paid_at`, que numa agendada é a
    data **futura** do débito: `paid_at >= cutoff` é verdadeiro para toda agendada, e isso está
    certo — nenhuma agendada é "antiga demais" para receber comprovante.
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
                select(Payable).where(
                    # [8.14] `IN (paid, scheduled)`, escrito contra a tupla e não contra dois
                    # `==` encadeados: quando a 8.15/8.16 precisarem do mesmo recorte, é uma
                    # entrada a mais e nenhuma regra muda.
                    Payable.status.in_(_ESTADOS_LIQUIDADOS),
                    Payable.paid_at >= cutoff,
                )
            )
            .order_by(Payable.paid_at.desc())
            .limit(100)
        ).all()
    )
    # Contas canceladas nunca entram: nenhum dos dois filtros (status aberta ou status
    # paga/agendada) as inclui, portanto não precisamos de um `.where(status != cancelada)`.
    return (abertas + pagas)[:100]


def _attach_and_commit(
    db: Session,
    att: Attachment,
    p: Payable,
    *,
    tenant_id: str,
    actor: str,
    mark_paid: bool,
    bank_account_id: str | None = None,
    paid_on: date | None = None,
) -> Payable:
    """Move o anexo da bandeja para a conta e fecha a transação (com baixa, se pedido).

    Extraído porque `link_receipt` (conta existente) e `new_bill_from_receipt` (conta nova)
    terminam exatamente igual — só a origem da conta difere. **É o único call site de `apply_paid`
    fora de `mark_paid`** (grep de 2026-07-30: o design da Onda 2 fala de três chamadores, mas a
    chamada das duas funções públicas foi extraída para cá — duas assinaturas mudam, um call site).

    A partir da Story 8.12 a baixa também **escreve o movimento bancário**, e por isso precisa dos
    dois parâmetros novos. Os dois só são resolvidos quando a baixa vai mesmo acontecer: vincular
    um comprovante **sem** dar baixa (`mark_paid=False`) continua não exigindo conta bancária
    nenhuma.

    ⚠️ **Story 8.13: os dois vêm do payload, sempre.** O substituto temporário da 8.12 (a conta
    primária, escolhida pelo backend sob `TODO(8.13)`) foi **removido** — pré-preencher é papel da
    tela, e a diferença importa: *"o que o pré-preenchimento evita é **construir**, não
    **confirmar**"*. `paid_on=None` cai no default de `apply_paid` (`due_date`); a tela da bandeja
    manda **hoje** explicitamente (ver `link_receipt`).
    """
    from app.core import audit
    from app.modules.payables import service as payables_service

    att.owner_type = OWNER_PAYABLE
    att.owner_id = p.id
    att.label = LABEL_COMPROVANTE

    # Conta já paga não é re-datada; `apply_paid` não commita, então a baixa, o vínculo do anexo e
    # o movimento bancário caem todos na MESMA transação.
    if mark_paid and p.status == STATUS_OPEN:
        if not bank_account_id:
            # **Segunda barreira, e não a primeira.** A primeira é o validador condicional de
            # `BaixaDoComprovante` (422 antes de tocar no banco). Esta existe porque
            # `_attach_and_commit` é o ÚNICO ponto por onde as duas portas da bandeja dão baixa: um
            # chamador interno futuro que esqueça a conta encontra um erro, não uma baixa sem
            # movimento bancário — que é exatamente o estado que a Onda 2 existe para tornar
            # impossível. Mesmo status da primeira barreira (422): o fato é o mesmo.
            raise ReceiptError(
                "Informe de qual conta bancária o dinheiro saiu para dar a baixa.", 422
            )
        payables_service.apply_paid(
            db,
            payable_id=p.id,
            tenant_id=tenant_id,
            actor=actor,
            bank_account_id=bank_account_id,
            paid_on=paid_on,
        )

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
    bank_account_id: str | None = None,
    paid_on: date | None = None,
) -> Payable:
    """Vincula o comprovante a uma conta existente e, se pedido, dá a baixa.

    Vincular é trocar owner_type/owner_id do Attachment: os bytes ficam onde estão.

    `bank_account_id`/`paid_on` são **repassados** para a baixa (Story 8.12) e vêm do payload
    (`ReceiptLinkIn`, Story 8.13) — sem substituto do backend.

    ⚠️ **A data que a TELA da bandeja manda é HOJE, e isso é decisão de produto, não default de
    função.** O comprovante chega pelo share sheet **no instante do pagamento** (*"a captura mais
    barata do produto inteiro, fisicamente no instante do pagamento"*), então a data de caixa
    honesta desta porta é o dia de hoje — e é também o que a bandeja já gravava antes da 8.13
    (IV1: a porta não muda de comportamento). Herdar o default `due_date` de `apply_paid` mudaria o
    fato de caixa em silêncio **e**, para conta com vencimento futuro — o caso mais comum na lista
    de candidatas, ordenada por vencimento —, esbarraria no teto de hoje com um 422 numa porta que
    hoje funciona. O que a 8.13 acrescenta é que esse "hoje" deixou de ser escolha invisível do
    backend: ele é um campo **visível e editável** na barra fixa, ao lado do botão que comete a
    ação. O usuário **confirma**, não constrói.
    """
    att = get_staged(db, attachment_id=attachment_id, user_id=user_id)

    p = db.get(Payable, bill_id)
    if p is None:
        raise ReceiptError("Conta não encontrada", 404)
    if p.status == STATUS_CANCELED:
        raise ReceiptError("Conta cancelada não recebe comprovante", 409)

    return _attach_and_commit(
        db, att, p, tenant_id=tenant_id, actor=actor, mark_paid=mark_paid,
        bank_account_id=bank_account_id, paid_on=paid_on,
    )


def new_bill_from_receipt(
    db: Session,
    *,
    attachment_id: str,
    user_id: str,
    tenant_id: str,
    actor: str,
    data,  # PayableCreate
    mark_paid: bool,
    bank_account_id: str | None = None,
    paid_on: date | None = None,
) -> Payable:
    """Cria a conta a partir do comprovante e já vincula o anexo — num commit só.

    Para o caso de ter pago algo que ainda não estava cadastrado no sistema.

    `bank_account_id`/`paid_on` são **repassados** para a baixa (Story 8.12/8.13) — ver
    `link_receipt`, inclusive a nota sobre a data que a tela manda.
    """
    from app.modules.payables import service as payables_service

    att = get_staged(db, attachment_id=attachment_id, user_id=user_id)

    # build_payable não commita: a conta, o evento na Agenda, o vínculo do anexo, a baixa e o
    # movimento bancário entram todos na mesma transação.
    p = payables_service.build_payable(db, tenant_id=tenant_id, actor=actor, data=data)

    return _attach_and_commit(
        db, att, p, tenant_id=tenant_id, actor=actor, mark_paid=mark_paid,
        bank_account_id=bank_account_id, paid_on=paid_on,
    )
