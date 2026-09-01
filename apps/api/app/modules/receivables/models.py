"""Contas a Receber — cobranças (boleto/Pix/link).

Quando uma cobrança é paga, vira uma Transaction na Carteira (com o split aplicado) e o
vencimento é injetado na Agenda. Tabela de NEGÓCIO (RLS).

Regra determinística (Story 5.2): fluxo de caixa usa `paid_at` (regime de caixa);
DRE/lucratividade/relatórios analíticos usam `competence_date` (regime de competência).
Nunca inverter. As Stories 5.3 (DRE) e 5.7 (projeção) devem citar esta regra literalmente
ao escrever suas queries, para eliminar ambiguidade entre stories/sessões diferentes.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# kind = tipo da venda (define o split quando paga): product/service/recurring (igual à wallet).
METHOD_PIX = "pix"
METHOD_BOLETO = "boleto"
METHOD_CARD = "card"
ALL_METHODS = {METHOD_PIX, METHOD_BOLETO, METHOD_CARD}

STATUS_OPEN = "open"
STATUS_PAID = "paid"
STATUS_CANCELED = "canceled"
# ⚠️ **[Story 8.15] `scheduled` — o Pix que o cliente AGENDOU e ainda não caiu.** Espelho exato do
# `payables.STATUS_SCHEDULED` da 8.14: o estado é **derivado da data** (`received_on > hoje ⇒
# scheduled`) por `app.core.scheduling.status_por_data`, nunca escolhido — nenhum schema de entrada
# deste módulo tem campo `status`.
#
# **Cabe sem migration de tipo:** `charges.status` é `String(12)` e `"scheduled"` tem 9 caracteres
# (asserção estrutural em `tests/test_receivables_off_rail.py`). A story 8.15 não cria migration.
#
# ⚠️ Ele só nasce pelo caminho **fora do trilho** (`settle_off_rail`): o caminho do gateway
# (`mark_paid`/webhook) crava `paid_at = now()` e continua sem estado agendado — *"é fato externo,
# atestado por terceiro, e editá-lo transformaria uma testemunha em opinião"*. A assimetria com
# `payables` é a informação, não um esquecimento.
STATUS_SCHEDULED = "scheduled"
ALL_STATUSES = {STATUS_OPEN, STATUS_SCHEDULED, STATUS_PAID, STATUS_CANCELED}


class Charge(Base, TenantMixin, TimestampMixin):
    __tablename__ = "charges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # split quando paga: product/service/recurring
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(String(12), default=STATUS_OPEN, nullable=False)
    # Classificação DRE (Story 5.2, aditivas/nullable — migration 0046).
    # competence_date: regime de COMPETÊNCIA (DRE). Backfill de legados = due_date; se omitida na
    #   criação, o service usa due_date como fallback.
    # paid_at: regime de CAIXA (fluxo de caixa). Setada na baixa (mark_paid/webhook). NOVA aqui
    #   (Payable já tinha; Charge só rastreava status="paid"+updated_at, o que não é confiável).
    # chart_account_id: vínculo OPCIONAL a uma conta do plano de contas (chart_accounts, Story 5.1);
    #   sem FK dura (mesmo padrão de client_id) — RLS + validação no service garantem a integridade.
    competence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chart_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Vínculo OPCIONAL ao Contract como eixo financeiro "projeto" (Story 5.4). Mesmo padrão de
    # referência solta (sem FK dura) de client_id. NULL = bucket implícito "Empresa" (overhead).
    contract_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # Vínculo OPCIONAL ao centro de custo como 2ª dimensão de análise (Story 5.5). Mesmo padrão de
    # referência solta (sem FK dura). NULL = "Não atribuído" — quem não usa a dimensão não é
    # obrigado; legado nasce vazio e a visão padrão dos relatórios (sem filtro) fica idêntica.
    cost_center_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # Stub do gateway: Pix copia-e-cola / linha do boleto / link de pagamento.
    payment_code: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Número/identificador do documento (nota fiscal, recibo...) — texto livre. Observações: nota
    # livre do dono sobre a cobrança. Mesma disciplina de description: valem para TODAS as
    # ocorrências de uma recorrência.
    documento: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # tx da carteira
    # evento de vencimento na agenda
    agenda_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # quando protestada (cobrança vencida levada a protesto); None = não protestada
    protested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # recorrência: gera N cobranças (uma por vencimento) ligadas por recurrence_group
    recurrence: Mapped[str] = mapped_column(String(8), default="none", nullable=False)
    recurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    recurrence_group: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Gateway de pagamento real (Asaas). Nullable/aditivos (migration 0033): quando o gateway
    # está configurado, guardam qual provedor gerou a cobrança, o id dela no provedor (suporte)
    # e o último status bruto recebido pelo webhook (debug). None = cobrança via stub.
    gateway_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gateway_charge_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gateway_status_raw: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── A Regra da Origem (Story 8.9, migration 0064, design Onda 2 §3.4) ────────────────────
    # As duas colunas nascem NULL e **nenhum caminho de produção as escreve nesta story**: a Story
    # 8.9 entrega o contrato, e a **8.15** (recebimento fora do trilho, `settle_off_rail`) liga o
    # fluxo a ele. Sem FK dura (padrão do projeto, igual a `client_id`).
    #
    # **REGRA DE AUTORIDADE**, idêntica à de `Payable` (ver a docstring lá, que é a longa):
    #   `bank_account_id`     → **DECISÃO DO USUÁRIO, AUTORITATIVA** — em qual conta o Pix caiu.
    #   `bank_transaction_id` → **CACHE DE LEITURA.** Divergiu do movimento com
    #                           `origin_id = charge.id`? **Quem manda é o `origin_id`.**
    #
    # ⚠️ **Estes dois ponteiros são criados aqui, mas a INVARIANTE DO TRILHO não é implementada
    # nesta story** (design §3.4; é escopo da 8.15): *para toda `Charge` com `status='paid'`,
    # exatamente um de `transaction_id` e `bank_account_id` é não-nulo.* `transaction_id` ⇒ entrou
    # pelo **trilho** (plano 1: split, `PlatformEarning`, nenhum movimento bancário);
    # `bank_account_id` ⇒ entrou **fora do trilho** (plano 3: nenhuma `Transaction`, nenhum
    # `PlatformEarning`, um movimento de crédito). Hoje ela é insatisfazível por construção —
    # `settle_off_rail` não existe, logo não há charge fora do trilho para varrer.
    #
    # ⚠️ **NÃO existe (nem deve existir) coluna `payment_route`.** A rota é **DERIVADA** dos dois
    # ponteiros (`"trilho" if transaction_id else "banco"`); um rótulo separado pode divergir do
    # fato e vira a terceira fonte de verdade — o defeito D-3 pela terceira vez.
    bank_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bank_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
