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
    documento: str = Field(default="", max_length=64)  # nº do documento (nota fiscal, recibo...)
    observacoes: str = ""  # nota livre do dono sobre a conta

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
    documento: str | None = Field(default=None, max_length=64)
    observacoes: str | None = None

    @field_validator("recurrence")
    @classmethod
    def _recur(cls, v: str | None) -> str | None:
        if v is not None and v not in ALL_RECURRENCES:
            raise ValueError(f"recorrência inválida: {v}")
        return v


class PayablePayIn(BaseModel):
    """Corpo **obrigatório** de `POST /payables/bills/{id}/pay` (Story 8.12, AC11).

    ⚠️ **É uma quebra de contrato deliberada e declarada.** A rota aceitava chamada sem corpo; a
    partir daqui uma chamada sem ele responde **422** do FastAPI. Os **dois** consumidores de
    frontend hoje em produção — `PagarPage.tsx` e `FilaPagamentosPage.tsx` — são consertados na
    Story **8.13**. **8.12 e 8.13 formam um par de release:** mergear esta e soltar para produção
    sem aquela deixa as duas telas quebradas.

    `bank_account_id` **sem `min_length`**, de propósito: com um mínimo, um tenant sem conta
    nenhuma receberia o 422 do Pydantic antes de o service poder devolver o **409 acionável** do
    AC2 — e é o 409 que diz à UI o que fazer.
    """

    bank_account_id: str
    # `None` ⇒ `due_date` (AC3, fundador F10). Teto em hoje **nesta story** — ver
    # `service._valida_data_de_baixa`.
    paid_on: date | None = None


class PayablePaymentUpdate(BaseModel):
    """Corpo de `PATCH /payables/bills/{id}/payment` — corrigir conta e/ou data do pagamento (AC7).

    Schema **novo**, rota **nova**: `PayableUpdate` não ganha campo nenhum (ver a nota em
    `service.update_payment`). Os dois campos são opcionais e `None` significa *"não altera"* —
    mesmo contrato de PATCH do resto do módulo.
    """

    bank_account_id: str | None = None
    paid_on: date | None = None


class PayablesPaidBeforeOut(BaseModel):
    """Agregado read-only: "quantas contas eu já paguei ANTES deste dia?" (Story 8.11, AC5/AC6).

    Serve ao aviso pró-ativo do cadastro de conta bancária: antes de escolher a data de abertura,
    o dono vê quantas contas pagas ficariam **fora** do extrato do e1p com aquela escolha (o saldo
    derivado só soma `posted_at > opening_date`, e `_validate_posted_at` recusa o resto com 422).

    ⚠️ **`total_cents` é o total PAGO, e nunca um saldo** (AC4 / `CLAUDE.md` Regra 5). O saldo de
    abertura é um fato **sobre o banco**, que o sistema por definição não conhece; derivá-lo do
    histórico de `payables` seria somar o que o sistema sabe e chamar de "o que o banco diz" — a
    circularidade que faria a divergência ir a zero por construção no dia um, matando a métrica
    primária do épico. **O e1p não inventa o número: ele diz qual número ir buscar.** Nenhum campo
    daqui pode ser oferecido, sugerido ou pré-preenchido como `opening_balance_cents`.

    ⚠️ **Mora em `payables`, e não em `bank`, por restrição normativa** (epic §4.1d): a dependência
    é de negócio para banco, **nunca a volta**. `app.modules.bank` não importa `payables`.
    """

    count: int
    total_cents: int
    # Datas de CAIXA (`paid_at::date`), nunca de competência nem de vencimento. `None` quando
    # `count == 0` — "não há", jamais uma data fabricada.
    oldest_paid_on: date | None
    newest_paid_on: date | None


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
    documento: str
    observacoes: str
    # Story 8.12 AC12 — o vínculo com o razão bancário. `bank_account_id` é a decisão AUTORITATIVA
    # do usuário ("de qual conta saiu?"); `bank_transaction_id` é **cache de leitura** do movimento
    # gerado. Divergiram? Quem manda é o `origin_id` do movimento (`payables/models.py`).
    # Nascem `None` em toda conta não paga — e em toda conta paga antes desta story.
    bank_account_id: str | None = None
    bank_transaction_id: str | None = None
    created_at: datetime


class PayablesSummary(BaseModel):
    open_cents: int  # a pagar (a vencer)
    overdue_cents: int  # vencido e não pago
    week_cents: int  # vence nesta semana
    month_cents: int  # total do mês (não cancelado)
    paid_month_cents: int  # já pago no mês
    # Story 8.14 (AC8) — Σ das contas em `scheduled` (débito agendado, data futura).
    #
    # ⚠️ **Não se mistura com nada.** Fora de `open_cents` (agendada não é "a pagar") e fora de
    # `paid_month_cents` (não saiu). Os cinco campos acima **não mudaram de definição** — inclusive
    # `month_cents`, que já filtrava `status != canceled` e portanto continua contando a agendada
    # por VENCIMENTO, de propósito (é o total do mês por competência de vencimento, não por caixa).
    #
    # Default `0` para que um cliente antigo (ou um teste que construa o schema à mão) não quebre
    # ao ganhar um campo — o serviço sempre o preenche.
    scheduled_cents: int = 0


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
    # Story 8.14 (AC7) — o quinto balde. Não é balde de VENCIMENTO: é o que já foi agendado, com o
    # débito marcado para uma data futura. Default `0` pelo mesmo motivo de `scheduled_cents`.
    agendadas_count: int = 0
    agendadas_cents: int = 0


class PaymentQueueOut(BaseModel):
    """Fila agrupada em 5 baldes de PayableOut (reaproveitado) + o resumo por balde."""

    atrasados: list[PayableOut]  # due_date < hoje
    hoje: list[PayableOut]  # due_date == hoje
    proximos_7_dias: list[PayableOut]  # hoje < due_date <= hoje+7
    proximos_30_dias: list[PayableOut]  # hoje+7 < due_date <= hoje+30
    # Story 8.14 — `status == 'scheduled'`, ordenadas pela DATA DO DÉBITO (`paid_at`), não por
    # `due_date`: a pergunta deste balde é *quando o dinheiro sai*, e numa agendada as duas datas
    # são diferentes por construção. Sem janela de 30 dias — um compromisso assumido para daqui a
    # 60 dias continua sendo um compromisso, e escondê-lo é a omissão que o AC7 combate.
    agendadas: list[PayableOut] = []
    summary: PaymentQueueSummary


class PayablesPageOut(BaseModel):
    """Uma página da listagem de contas a pagar — `items` + o `total` REAL do recorte.

    O `total` não é enfeite: sem ele a tela não consegue dizer "mostrando 50 de 213", e o
    truncamento volta a ser silencioso — que foi exatamente o defeito que esta spec corrigiu.
    Ele conta o recorte inteiro, ignorando `limit`/`offset`.
    """

    items: list[PayableOut]
    total: int
