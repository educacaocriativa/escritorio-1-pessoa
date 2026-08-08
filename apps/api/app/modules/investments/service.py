"""Regras da conta de investimento (Story 5.6): CRUD + registrar rendimento + rentabilidade.

Isolamento por RLS (nenhuma query filtra tenant manualmente — Regra de Ouro nº 1). Mesmo padrão
CRUD simples de `chart_accounts`/`cost_centers`.

═══════════════════════════════════════════════════════════════════════════════════════════════
DECISÃO TÉCNICA CENTRAL (Task 3 / AC2 / IV1) — LEIA ANTES DE ALTERAR `register_yield`:
═══════════════════════════════════════════════════════════════════════════════════════════════
O rendimento (juro) vira um "lançamento de receita no grupo FINANCEIRO" reusando a tabela `charges`
(Contas a Receber — "o caminho de lançamento existente" da IV1), MAS construído DIRETAMENTE já
baixado (`status=paid`), sem NUNCA chamar `receivables.mark_paid`/`wallet.build_transaction`.

  Por quê assim: no e1p o ÚNICO ponto que cria uma `Transaction` na Carteira (com split 40/30/20 e
  `PlatformEarning`) é `wallet_service.build_transaction`, chamado só por `receivables.mark_paid`.
  Basta NÃO chamar esse caminho para garantir a IV1 ("receita financeira, não venda com split").
  Como a Charge JÁ nasce `status=paid`, um `mark_paid`/webhook sobre ela é no-op idempotente
  (guarda `if status == PAID: return`) — o split não é acionado nem por engano. Coberto por teste
  explícito (test_investments.py): registrar rendimento NÃO cria Transaction/PlatformEarning.

  Diferenças deliberadas da Charge de rendimento vs. uma cobrança normal de cliente:
   - `external_ref = "investment:<account_id>"` — MARCA a origem (rendimento, não cobrança de
     cliente nenhum) e correlaciona à conta de investimento (sem FK dura, padrão do projeto).
   - NÃO cria evento na Agenda (construção direta; não passa por `build_charge`) — não polui a
     agenda com um "vencimento" de algo que já está realizado.
   - `client_id = None` (não é de cliente nenhum).

  ⚠️ VISIBILIDADE / RECONCILIAÇÃO (ponto reservado à decisão do fundador + @architect, quality_gate
  desta story): como é uma `Charge status=paid`, este lançamento HOJE também é somado por
  `receivables.summary().paid_cents` (o "Recebido" da tela Cobranças) e listado por `list_charges`.
  Isso NÃO move dinheiro (sem Transaction/saque), mas mistura rendimento de investimento com
  recebimento de clientes nesse total. A story pedia explicitamente "aparece em Contas a Receber";
  a missão do fundador pediu para NÃO poluir as telas de cobrança normal. Como as duas orientações
  divergem e o assunto é dinheiro/reconciliação, NÃO alterei `receivables` por conta própria — está
  documentado no Dev Agent Record da story para decisão (mitigação pronta: filtrar
  `external_ref LIKE 'investment:%'` em `list_charges`/`summary`; ou a alternativa do @sm de uma
  tabela de lançamentos financeiros dedicada). A DRE (5.3) já inclui este lançamento corretamente,
  pois agrega `charges` por `chart_account_id`+competência direto (não via `list_charges`).
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.bank import service as bank_service
from app.modules.bank.models import KIND_INVESTMENT
from app.modules.chart_of_accounts import service as chart_service
from app.modules.chart_of_accounts.models import GRUPO_FINANCEIRO
from app.modules.investments.models import InvestmentAccount, external_ref_for
from app.modules.investments.schemas import (
    InvestmentAccountCreate,
    InvestmentAccountUpdate,
)
from app.modules.receivables.models import STATUS_PAID, Charge

# Valores INERTES nos campos que só teriam efeito no split (kind/method) — nunca são usados porque
# a Charge de rendimento não passa por mark_paid/build_transaction. Mantidos válidos por serem
# colunas NOT NULL. Ver docstring do módulo.
_YIELD_CHARGE_KIND = "service"
_YIELD_CHARGE_METHOD = "pix"


class InvestmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def get_account(db: Session, account_id: str) -> InvestmentAccount:
    acc = db.get(InvestmentAccount, account_id)
    if acc is None:
        # Cross-tenant também cai aqui: a RLS esconde a linha → db.get None → 404 (fail-closed).
        raise InvestmentError("Conta de investimento não encontrada", 404)
    return acc


def create_account(
    db: Session, *, tenant_id: str, actor: str, data: InvestmentAccountCreate
) -> InvestmentAccount:
    if data.bank_account_id:
        _validate_bank_account(db, data.bank_account_id)
    acc = InvestmentAccount(
        tenant_id=tenant_id,
        name=data.name,
        kind=data.kind,
        index_rate_label=data.index_rate_label,
        principal_cents=data.principal_cents,
        accrued_yield_cents=0,
        opened_at=data.opened_at,
        bank_account_id=data.bank_account_id,
    )
    db.add(acc)
    audit.record(db, tenant_id=tenant_id, actor=actor, action="investment.create", target=acc.id)
    db.commit()
    db.refresh(acc)
    return acc


def update_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str, data: InvestmentAccountUpdate
) -> InvestmentAccount:
    """Edita principal/indexador/tipo/nome. NÃO mexe em `accrued_yield_cents` (esse só muda via
    register_yield, que também gera o lançamento de receita — manter as duas coisas juntas)."""
    acc = get_account(db, account_id)
    if data.name is not None:
        acc.name = data.name
    if data.kind is not None:
        acc.kind = data.kind
    if data.index_rate_label is not None:
        acc.index_rate_label = data.index_rate_label
    if data.principal_cents is not None:
        acc.principal_cents = data.principal_cents
    if data.bank_account_id is not None:
        # Onda 2b-i: é por aqui que a aplicação LEGADA é vinculada — ato do dono, não backfill.
        _validate_bank_account(db, data.bank_account_id)
        acc.bank_account_id = data.bank_account_id
    audit.record(db, tenant_id=tenant_id, actor=actor, action="investment.update", target=acc.id)
    db.commit()
    db.refresh(acc)
    return acc


def list_accounts(db: Session) -> list[InvestmentAccount]:
    return list(db.scalars(select(InvestmentAccount).order_by(InvestmentAccount.name)).all())


def _validate_financeiro_account(db: Session, chart_account_id: str) -> None:
    """A conta do plano de contas informada existe (RLS) E pertence ao grupo FINANCEIRO? (AC2)

    404 se inexistente/de outro tenant (a RLS esconde a linha); 422 se existir mas estiver em outro
    grupo DRE — "preservar a coerência do regime de competência" (AC2) implica preservar a coerência
    do grupo: rendimento de aplicação é receita FINANCEIRA, não pode ser classificado noutro grupo.
    """
    try:
        account = chart_service.get_account(db, chart_account_id)  # 404 se não visível
    except chart_service.ChartAccountError as e:
        # Converte o erro do plano de contas no erro deste módulo (mantém o status 404 fail-closed).
        raise InvestmentError("Conta do plano de contas não encontrada", e.status_code) from e
    if account.grupo_dre != GRUPO_FINANCEIRO:
        raise InvestmentError(
            "A conta do plano de contas do rendimento deve pertencer ao grupo FINANCEIRO", 422
        )


_CONTA_NAO_E_APLICACAO_MSG = (
    "A conta bancária de uma aplicação precisa ser do tipo 'aplicação'. Se o dinheiro está numa "
    "conta corrente, ele não está aplicado — e o rendimento cairia na conta errada, fazendo os "
    "dois saldos derivados mentirem juntos."
)

# ⚠️ Duplicada em substância de `payables.service._CONTA_ARQUIVADA_MSG` DE PROPÓSITO. Aquela
# constante é privada do módulo de Contas a Pagar, e importar um símbolo `_` entre dois módulos de
# negócio seria acoplamento gratuito — o mesmo motivo pelo qual `receivables` duplica
# `ACAO_CADASTRAR_CONTA` em vez de importá-la. O que NÃO é duplicado é o `acao` do 409, porque
# aquele é contrato com a UI e tem teste de sincronia.
_CONTA_ARQUIVADA_MSG = (
    "A conta bancária escolhida está arquivada e não recebe lançamentos novos. Escolha outra "
    "conta ou cadastre a conta que você usa hoje — com o saldo de abertura do dia."
)


def _validate_bank_account(db: Session, bank_account_id: str) -> None:
    """A conta bancária do vínculo existe (RLS), é aplicação e está ativa? (Onda 2b-i)

    **404 se inexistente ou de outro tenant** — `bank_service.get_account` é fail-closed e a RLS
    esconde a linha alheia. Nunca 409 nesse caso: 409 confirmaria a existência da linha, que é
    vazamento de existência com cara de validação (critério já fixado no módulo `bank`).

    **422 se a conta não for `kind='investment'`.** A faceta de produto fala de UMA aplicação; se
    ela apontasse para uma conta corrente, o rendimento creditaria onde o dinheiro não está.
    """
    try:
        acc = bank_service.get_account(db, bank_account_id)
    except bank_service.BankError as e:
        raise InvestmentError("Conta bancária não encontrada", e.status_code) from e
    if acc.kind != KIND_INVESTMENT:
        raise InvestmentError(_CONTA_NAO_E_APLICACAO_MSG, 422)
    if acc.archived_at is not None:
        raise InvestmentError(_CONTA_ARQUIVADA_MSG, 409)


def register_yield(
    db: Session,
    *,
    account_id: str,
    tenant_id: str,
    actor: str,
    amount_cents: int,
    date: date,  # noqa: A002 (nome de domínio; é a data de competência do rendimento)
    chart_account_id: str | None,
) -> InvestmentAccount:
    """Registra o rendimento (juro) do período: soma ao `accrued_yield_cents` da conta E, na MESMA
    transação, cria a `Charge` de receita financeira JÁ baixada (Task 3) — SEM tocar Carteira/split.

    Ver a docstring do módulo para a decisão técnica completa (IV1). O sinal do lançamento vem da
    tabela de origem (`Charge` = +1), nunca do grupo_dre (convenção canônica ratificada na 5.3).
    """
    acc = get_account(db, account_id)
    if chart_account_id:
        _validate_financeiro_account(db, chart_account_id)

    acc.accrued_yield_cents += amount_cents

    # Charge sintética "já baixada": construída DIRETAMENTE (não via build_charge), NUNCA por
    # mark_paid/build_transaction → não gera Transaction/PlatformEarning (IV1). status=paid a torna
    # inclusive imune a um mark_paid/webhook posterior (guarda de idempotência).
    now = datetime.now(UTC)
    charge = Charge(
        tenant_id=tenant_id,
        client_id=None,  # rendimento não é de cliente nenhum
        description=f"Rendimento de aplicação: {acc.name}",
        kind=_YIELD_CHARGE_KIND,  # inerte (só afetaria o split, que não é acionado)
        method=_YIELD_CHARGE_METHOD,  # inerte
        amount_cents=amount_cents,
        due_date=date,
        competence_date=date,  # regime de competência (DRE, 5.3) — período do rendimento
        paid_at=now,  # regime de caixa: já realizado
        status=STATUS_PAID,
        chart_account_id=chart_account_id,  # grupo FINANCEIRO (validado acima quando informado)
        external_ref=external_ref_for(account_id),  # MARCA a origem (rendimento) + correlação
    )
    db.add(charge)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="investment.register_yield", target=acc.id
    )
    db.commit()
    db.refresh(acc)
    return acc


def _pct(numerator: int, principal_cents: int) -> float | None:
    """Rentabilidade (fração) protegendo divisão por zero: principal 0 → None (AC3)."""
    if principal_cents == 0:
        return None
    return numerator / principal_cents


def rentability(
    db: Session, *, account_id: str, start: date | None = None, end: date | None = None
) -> dict:
    """Rentabilidade da conta (AC3): total (rendimento acumulado / principal) e do período (soma dos
    rendimentos com competência no intervalo / principal). Divisão por zero (principal 0) → None.

    O rendimento do período é somado no BANCO (SUM) sobre as `Charge` marcadas
    `external_ref='investment:<account_id>'`, filtradas por `competence_date` (regime de
    competência, coerente com a DRE 5.3)."""
    acc = get_account(db, account_id)

    stmt = select(func.coalesce(func.sum(Charge.amount_cents), 0)).where(
        Charge.external_ref == external_ref_for(account_id)
    )
    if start is not None:
        stmt = stmt.where(Charge.competence_date >= start)
    if end is not None:
        stmt = stmt.where(Charge.competence_date <= end)
    period_yield = int(db.scalar(stmt) or 0)

    return {
        "account_id": acc.id,
        "principal_cents": acc.principal_cents,
        "accrued_yield_cents": acc.accrued_yield_cents,
        "total_rentability_pct": _pct(acc.accrued_yield_cents, acc.principal_cents),
        "period_rentability_pct": _pct(period_yield, acc.principal_cents),
        "period_yield_cents": period_yield,
        "start": start,
        "end": end,
    }
