"""Rotas de Contas a Pagar."""
from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.payables import service
from app.modules.payables.models import Payable
from app.modules.payables.schemas import (
    PayableCreate,
    PayableOut,
    PayablePayIn,
    PayablePaymentUpdate,
    PayablesPageOut,
    PayablesPaidBeforeOut,
    PayablesSummary,
    PayableUpdate,
    PaymentQueueOut,
)
from app.modules.settings.service import hoje_do_tenant

router = APIRouter(prefix="/payables", tags=["payables"])

_guard = require_module("payables")


def _out(db: Session, p: Payable) -> PayableOut:
    # Montagem canônica do PayableOut vive no service (reutilizada pela fila da Story 5.9).
    # `db` entra por causa de `is_overdue`: "atrasada" depende do dia de HOJE no fuso do tenant,
    # e o fuso vem do perfil. Sem isso o servidor (UTC) antecipava o vencimento em 3h.
    return service.payable_out(p, hoje_do_tenant(db))


def _err(e: service.PayableError) -> HTTPException:
    """`detail` estruturado quando o erro é ACIONÁVEL; string em todo o resto.

    O 409 `{"acao": "cadastrar_conta", "mensagem": ...}` é **contrato** (Story 8.12 AC2), consumido
    pela 8.13 para abrir o cadastro de conta embutido no fluxo de pagamento. Sem o `detail` em
    dicionário, a tela teria de reconhecer a situação por substring da mensagem.
    """
    return HTTPException(status_code=e.status_code, detail=e.detail or str(e))


@router.get("/summary", response_model=PayablesSummary)
def summary(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayablesSummary:
    return PayablesSummary(**service.summary(db))


@router.get("/queue", response_model=PaymentQueueOut)
def payment_queue(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PaymentQueueOut:
    """Story 5.9 — fila de pagamentos: Payables em aberto agrupados por janela de vencimento.
    Mesmo módulo/guard (`require_module('payables')`), sem autorização nova."""
    return service.payment_queue(db, tenant_id=user.tenant_id)


@router.get("/categories", response_model=list[str])
def categories(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[str]:
    return service.list_categories(db)


@router.get("/bills", response_model=PayablesPageOut)
def list_bills(
    status: list[str] | None = Query(default=None),
    # `from`/`to` são as palavras naturais na URL; `from` é reservada em Python, daí o alias.
    due_from: date_type | None = Query(default=None, alias="from"),
    due_to: date_type | None = Query(default=None, alias="to"),
    q: str | None = Query(default=None, max_length=120),
    cost_center_id: str | None = Query(default=None),
    chart_account_id: str | None = Query(default=None),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayablesPageOut:
    # Fuso resolvido UMA vez para a página inteira: `_out` por linha faria uma consulta de perfil
    # por conta (N+1). Mesmo cuidado da listagem de `receivables`.
    hoje = hoje_do_tenant(db)
    # O recorte vai como dict ÚNICO para buscar e contar: esquecer um argumento em uma das duas
    # chamadas reproduz, pela porta da rota, a divergência que `_filtros` existe para impedir.
    recorte = dict(
        status=status,
        due_from=due_from,
        due_to=due_to,
        q=q,
        cost_center_id=cost_center_id,
        chart_account_id=chart_account_id,
    )
    itens = service.list_payables(db, order=order, limit=limit, offset=offset, **recorte)
    return PayablesPageOut(
        items=[service.payable_out(p, hoje) for p in itens],
        total=service.count_payables(db, **recorte),
    )


@router.get("/bills/paid-before", response_model=PayablesPaidBeforeOut)
def bills_paid_before(
    date: date_type = Query(description="Data de corte (YYYY-MM-DD). A borda é `<`, estrita."),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayablesPaidBeforeOut:
    """Quantas contas eu já **paguei** antes deste dia? (Story 8.11, AC5/AC6)

    ⚠️ **A ordem de registro importa:** esta rota precisa vir ANTES de `GET /bills/{payable_id}`.
    O FastAPI casa na ordem de declaração — invertida, `paid-before` seria lido como um
    `payable_id` e esta rota nunca seria alcançada (404 "Conta não encontrada").

    Read-only, agregado (não devolve lista, então não tem paginação), isolado por RLS. Não escreve
    nada e **não produz saldo nenhum** — ver a nota da Regra 5 em `PayablesPaidBeforeOut`.
    """
    return PayablesPaidBeforeOut(**service.paid_before(db, date_=date))


@router.get("/bills/{payable_id}", response_model=PayableOut)
def get_bill(
    payable_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        return _out(db, service.get_payable(db, payable_id))
    except service.PayableError as e:
        raise _err(e) from e


@router.post("/bills", response_model=PayableOut, status_code=201)
def create_bill(
    data: PayableCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.create_payable(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)


@router.patch("/bills/{payable_id}", response_model=PayableOut)
def update_bill(
    payable_id: str,
    data: PayableUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.update_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id, data=data
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)


@router.post("/bills/{payable_id}/pay", response_model=PayableOut)
def pay_bill(
    payable_id: str,
    data: PayablePayIn,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    """Dá a baixa **e gera o movimento bancário**, num commit só (Story 8.12).

    ⚠️ O corpo passou a ser **obrigatório** (AC11): a conta bancária de onde o dinheiro saiu não
    tem default no service — *"opcional significa que alguém pula, e a conferência volta a medir o
    que você esqueceu de preencher"* (fundador F7). Quem pré-preenche pela conta primária é a UI da
    Story 8.13; **o que o pré-preenchimento evita é construir, não confirmar.**
    """
    try:
        p = service.mark_paid(
            db,
            payable_id=payable_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            bank_account_id=data.bank_account_id,
            paid_on=data.paid_on,
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)


@router.patch("/bills/{payable_id}/payment", response_model=PayableOut)
def update_bill_payment(
    payable_id: str,
    data: PayablePaymentUpdate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    """Corrige o **pagamento** (conta bancária e/ou data) de uma conta já paga (Story 8.12, AC7).

    Rota separada do `PATCH /bills/{id}` de propósito: aquele edita a **obrigação** (valor,
    vencimento, fornecedor) e é recusado em conta paga; este edita o **fato de caixa**, e só existe
    em conta paga. Trocar a conta **move** o movimento bancário — nunca duplica.

    Existe porque corrigir/reagendar é evento **normal**: sem ela, a alternativa seria estornar +
    repagar, com delete + recreate do movimento e o evento da Agenda indo e voltando.
    """
    try:
        p = service.update_payment(
            db,
            payable_id=payable_id,
            tenant_id=user.tenant_id,
            actor=user.user_id,
            bank_account_id=data.bank_account_id,
            paid_on=data.paid_on,
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)


@router.post("/bills/{payable_id}/cancel", response_model=PayableOut)
def cancel_bill(
    payable_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.cancel_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)


@router.post("/bills/{payable_id}/reactivate", response_model=PayableOut)
def reactivate_bill(
    payable_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    """Conta cancelada volta para 'A pagar'. Rota própria — ver `service.reactivate_payable`."""
    try:
        p = service.reactivate_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)


@router.post("/bills/{payable_id}/reverse", response_model=PayableOut)
def reverse_bill(
    payable_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.reverse_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)
