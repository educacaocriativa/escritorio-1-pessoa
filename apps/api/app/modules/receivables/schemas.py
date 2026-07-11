"""Schemas de Contas a Receber."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.receivables.models import ALL_METHODS
from app.modules.wallet.models import ALL_KINDS


class ChargeCreate(BaseModel):
    client_id: str | None = None
    description: str = ""
    kind: str  # product/service/recurring (define o split quando paga)
    method: str
    amount_cents: int = Field(gt=0)
    due_date: date
    # Classificação DRE (Story 5.2, opcionais). competence_date omitida → service usa due_date
    # como fallback (mesma regra do backfill). chart_account_id validado contra o plano de contas
    # do tenant só se informado (404 se apontar p/ conta inexistente/de outro tenant).
    competence_date: date | None = None
    chart_account_id: str | None = None
    # Story 5.4: vínculo opcional ao Contract (eixo "projeto"). Validado se informado (404 se
    # apontar p/ contrato inexistente/de outro tenant). NULL = bucket "Empresa" (overhead).
    contract_id: str | None = None
    # Story 5.5: vínculo opcional ao centro de custo (2ª dimensão). Validado se informado (404 se
    # apontar p/ centro de custo inexistente/de outro tenant). NULL = "Não atribuído".
    cost_center_id: str | None = None
    recurrence: str = "none"  # none/weekly/monthly/yearly
    recurrence_count: int = Field(default=1, ge=1, le=60)

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str) -> str:
        if v not in {"none", "weekly", "monthly", "yearly"}:
            raise ValueError(f"recorrência inválida: {v}")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ALL_KINDS:
            raise ValueError(f"kind inválido: {v}")
        return v

    @field_validator("method")
    @classmethod
    def _method(cls, v: str) -> str:
        if v not in ALL_METHODS:
            raise ValueError(f"method inválido: {v}")
        return v


class ChargeOut(BaseModel):
    id: str
    tenant_id: str
    client_id: str | None
    client_name: str | None
    description: str
    kind: str
    method: str
    amount_cents: int
    due_date: date
    # Story 5.2: competência (regime de competência/DRE) e pagamento (regime de caixa).
    competence_date: date | None
    paid_at: datetime | None
    chart_account_id: str | None
    # Story 5.4: vínculo ao contrato (eixo "projeto"); None = bucket "Empresa".
    contract_id: str | None
    # Story 5.5: vínculo ao centro de custo (2ª dimensão); None = "Não atribuído".
    cost_center_id: str | None
    status: str
    is_overdue: bool
    protested_at: datetime | None
    recurrence: str
    recurrence_group: str | None
    payment_code: str
    transaction_id: str | None
    created_at: datetime
    # Gateway real (Asaas) — somente-leitura; None quando a cobrança foi gerada pelo stub.
    gateway_provider: str | None = None
    gateway_status_raw: str | None = None


class RescheduleRequest(BaseModel):
    due_date: date


class ChargeUpdate(BaseModel):
    description: str | None = None
    amount_cents: int | None = Field(default=None, gt=0)
    due_date: date | None = None
    # Story 5.2: reclassificar uma cobrança em aberto (competência/conta do plano de contas).
    competence_date: date | None = None
    chart_account_id: str | None = None
    # Story 5.4: (re)vincular a um contrato. None no PATCH = "não altera"; "" desvincula (bucket
    # "Empresa"). Ver update_charge.
    contract_id: str | None = None
    # Story 5.5: (re)vincular a um centro de custo. None = "não altera"; "" desvincula ("Não
    # atribuído"). Mesmo padrão de contract_id.
    cost_center_id: str | None = None


class WebhookPayment(BaseModel):
    """Payload INTERNO de confirmação (dev/teste): o link 'simular pgto' e testes chamam o webhook
    com este corpo. Em produção o corpo real vem do provedor (ver AsaasWebhookPayload)."""
    tenant_id: str
    charge_id: str
    status: str = "paid"
    secret: str = ""


class AsaasWebhookPayment(BaseModel):
    """Sub-objeto `payment` do evento do Asaas (campos relevantes; o provedor envia mais)."""
    id: str | None = None
    externalReference: str | None = None  # noqa: N815 (nome do campo é ditado pela API do Asaas)
    status: str | None = None


class AsaasWebhookPayload(BaseModel):
    """Payload REAL do webhook do Asaas. `event` é o tipo (ex.: PAYMENT_RECEIVED/PAYMENT_CONFIRMED)
    e `payment.externalReference` carrega `tenant_id:charge_id` (setado ao criar a cobrança).

    Documentação/validação de contrato: os nomes de campos seguem a doc pública do Asaas e devem
    ser confirmados contra a doc vigente antes do go-live. O endpoint aceita o corpo cru (dict)
    e não exige este schema para não quebrar por campos extras do provedor — ele documenta o
    formato esperado."""
    event: str | None = None
    payment: AsaasWebhookPayment | None = None


class DunningResult(BaseModel):
    message: str
    status: str  # sent / logged / failed


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ChargesSummary(BaseModel):
    open_cents: int  # em aberto (a vencer)
    overdue_cents: int  # vencido e não pago
    paid_cents: int  # recebido
    open_count: int
    overdue_count: int
