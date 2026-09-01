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
    documento: str = Field(default="", max_length=64)  # nº do documento (nota fiscal, recibo...)
    observacoes: str = ""  # nota livre do dono sobre a cobrança

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
    documento: str
    observacoes: str
    transaction_id: str | None
    created_at: datetime
    # Gateway real (Asaas) — somente-leitura; None quando a cobrança foi gerada pelo stub.
    gateway_provider: str | None = None
    gateway_status_raw: str | None = None
    # ── A INVARIANTE DO TRILHO, exposta pelos DOIS PONTEIROS (Story 8.15, AC4) ────────────────
    #
    # `transaction_id` (acima) → **trilho**; `bank_account_id` → **fora do trilho**. Exatamente um
    # deles é não-nulo numa cobrança liquidada.
    #
    # ⚠️ **NÃO existe campo de rota aqui, e a ausência é a decisão.** A rota é **DERIVADA**
    # (`"trilho" if transaction_id else "banco"`) e a derivação mora no `.ts`
    # (`features/cobrancas/rota.ts`), onde ela é consumida. Um rótulo persistido — ou serializado
    # como se fosse fato — pode divergir dos ponteiros e vira a terceira fonte de verdade (D-3).
    #
    # ⚠️ Nenhuma superfície de `/admin/*` recebe estes campos (epic §2.1, decisão G-D7): não
    # existe agregado de plataforma sobre a conta bancária do dono.
    bank_account_id: str | None = None
    bank_transaction_id: str | None = None


class RescheduleRequest(BaseModel):
    due_date: date


class ChargeSettleOffRailIn(BaseModel):
    """Corpo de `POST /receivables/charges/{id}/settle-externally` (Story 8.15, AC1).

    `bank_account_id` **sem `min_length`**, de propósito e pelo mesmo motivo de `PayablePayIn`: com
    um mínimo, um tenant sem conta nenhuma receberia o 422 do Pydantic antes de o service poder
    devolver o **409 acionável** — e é o 409 que diz à UI o que fazer.

    **Não existe campo `status`.** O estado é derivado de `received_on` (`> hoje ⇒ scheduled`), e a
    API não oferece a escolha.
    """

    bank_account_id: str
    # `None` ⇒ **hoje** (o gesto é "caiu na minha conta", um fato observado agora). Sem teto: data
    # futura é agendamento, não erro (AC5).
    received_on: date | None = None


class ChargePaymentUpdate(BaseModel):
    """Corpo de `PATCH /receivables/charges/{id}/payment` — corrigir conta e/ou data (AC10).

    Schema **novo**, rota **nova**: `ChargeUpdate` não ganha campo nenhum (ver a nota em
    `service.update_off_rail_payment`). Os dois campos são opcionais e `None` significa *"não
    altera"* — mesmo contrato de PATCH do resto do módulo.
    """

    bank_account_id: str | None = None
    received_on: date | None = None


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
    documento: str | None = Field(default=None, max_length=64)
    observacoes: str | None = None


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
    # [Story 8.15, AC7] Recebimento fora do trilho com data FUTURA (`status='scheduled'`).
    # **Fora** de `open_cents` e **fora** de `paid_cents`: sem este campo a cobrança agendada
    # sumiria dos três buckets. Os cinco campos acima mantêm a definição byte a byte (há teste de
    # snapshot num cenário sem agendamento).
    scheduled_cents: int = 0
