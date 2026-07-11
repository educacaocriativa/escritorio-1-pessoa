"""Schemas de Contas a Pagar."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.payables.models import ALL_RECURRENCES, RECUR_NONE


class PayableCreate(BaseModel):
    description: str = ""
    category: str = "Geral"
    supplier: str = ""
    amount_cents: int = Field(gt=0)
    due_date: date
    # Classificação DRE (Story 5.2, opcionais). competence_date omitida → service usa due_date
    # como fallback. chart_account_id validado contra o plano de contas do tenant se informado.
    competence_date: date | None = None
    chart_account_id: str | None = None
    # Story 5.4: vínculo opcional ao Contract (eixo "projeto"). Validado se informado (404 se
    # apontar p/ contrato inexistente/de outro tenant). NULL = bucket "Empresa" (overhead).
    contract_id: str | None = None
    # Story 5.5: vínculo opcional ao centro de custo (2ª dimensão). Validado se informado (404 se
    # apontar p/ centro de custo inexistente/de outro tenant). NULL = "Não atribuído".
    cost_center_id: str | None = None
    recurrence: str = RECUR_NONE
    recurrence_count: int = Field(default=1, ge=1, le=60)  # quantas vezes repete
    payment_code: str = ""  # linha digitável do boleto OU Pix copia-e-cola
    attachment_url: str = Field(default="", max_length=1024)  # URL do boleto anexado

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str) -> str:
        if v not in ALL_RECURRENCES:
            raise ValueError(f"recorrência inválida: {v}")
        return v


class PayableUpdate(BaseModel):
    description: str | None = None
    category: str | None = None
    supplier: str | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    due_date: date | None = None
    # Story 5.2: reclassificar (competência/conta do plano de contas).
    competence_date: date | None = None
    chart_account_id: str | None = None
    # Story 5.4: (re)vincular a um contrato. None no PATCH = "não altera"; para DESvincular,
    # use "" (string vazia) → cai no bucket "Empresa" (ver update_payable).
    contract_id: str | None = None
    # Story 5.5: (re)vincular a um centro de custo. None no PATCH = "não altera"; "" desvincula
    # (→ "Não atribuído"). Mesmo padrão de contract_id.
    cost_center_id: str | None = None
    recurrence: str | None = None
    payment_code: str | None = None
    attachment_url: str | None = Field(default=None, max_length=1024)

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str | None) -> str | None:
        if v is not None and v not in ALL_RECURRENCES:
            raise ValueError(f"recorrência inválida: {v}")
        return v


class PayableOut(BaseModel):
    id: str
    tenant_id: str
    description: str
    category: str
    supplier: str
    amount_cents: int
    due_date: date
    # Story 5.2: competência (DRE) e vínculo de conta do plano de contas.
    competence_date: date | None
    chart_account_id: str | None
    # Story 5.4: vínculo ao contrato (eixo "projeto"); None = bucket "Empresa".
    contract_id: str | None
    # Story 5.5: vínculo ao centro de custo (2ª dimensão); None = "Não atribuído".
    cost_center_id: str | None
    status: str
    is_overdue: bool
    paid_at: datetime | None
    recurrence: str
    recurrence_count: int
    recurrence_group: str | None
    payment_code: str
    attachment_url: str
    created_at: datetime


class PayablesSummary(BaseModel):
    open_cents: int  # a pagar (a vencer)
    overdue_cents: int  # vencido e não pago
    week_cents: int  # vence nesta semana
    month_cents: int  # total do mês (não cancelado)
    paid_month_cents: int  # já pago no mês


# ── Story 5.9: Fila de Pagamentos ──────────────────────────────────────────────────────────────
# Visão nova sobre dados existentes (Payable) — sem tabela/coluna nova. O agrupamento por janela de
# vencimento é calculado NA LEITURA (nunca gravado), então o balde de um item nunca "envelhece".
class PaymentQueueSummary(BaseModel):
    """Contagem e soma (centavos) por balde — mesmo padrão de PayablesSummary, sem os itens."""

    atrasados_count: int
    atrasados_cents: int
    hoje_count: int
    hoje_cents: int
    proximos_7_dias_count: int
    proximos_7_dias_cents: int
    proximos_30_dias_count: int
    proximos_30_dias_cents: int


class PaymentQueueOut(BaseModel):
    """Fila agrupada em 4 baldes de PayableOut (reaproveitado) + o resumo por balde."""

    atrasados: list[PayableOut]  # due_date < hoje
    hoje: list[PayableOut]  # due_date == hoje
    proximos_7_dias: list[PayableOut]  # hoje < due_date <= hoje+7
    proximos_30_dias: list[PayableOut]  # hoje+7 < due_date <= hoje+30
    summary: PaymentQueueSummary
