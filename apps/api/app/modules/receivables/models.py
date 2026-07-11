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
ALL_STATUSES = {STATUS_OPEN, STATUS_PAID, STATUS_CANCELED}


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
