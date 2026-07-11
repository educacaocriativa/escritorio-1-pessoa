"""Contas a Pagar — despesas (fixas e variáveis).

Cada conta tem vencimento (injetado na Agenda como cobranca_pagar) e alimenta o "Custos do Mês"
do Cockpit. NÃO mexe na Carteira (é saída, não receita). Tabela de NEGÓCIO (RLS).

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

STATUS_OPEN = "open"
STATUS_PAID = "paid"
STATUS_CANCELED = "canceled"
ALL_STATUSES = {STATUS_OPEN, STATUS_PAID, STATUS_CANCELED}

# Recorrência (auto-geração de contas futuras fica como dívida — só armazenamos por ora).
RECUR_NONE = "none"
RECUR_WEEKLY = "weekly"
RECUR_MONTHLY = "monthly"
RECUR_YEARLY = "yearly"
ALL_RECURRENCES = {RECUR_NONE, RECUR_WEEKLY, RECUR_MONTHLY, RECUR_YEARLY}


class Payable(Base, TenantMixin, TimestampMixin):
    __tablename__ = "payables"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(48), default="Geral", nullable=False)
    supplier: Mapped[str] = mapped_column(String(120), default="", nullable=False)  # fornecedor
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(String(12), default=STATUS_OPEN, nullable=False)
    # paid_at (regime de CAIXA) já existia (Fase 2) — setado em mark_paid.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Classificação DRE (Story 5.2, aditivas/nullable — migration 0046).
    # competence_date: regime de COMPETÊNCIA (DRE). Backfill de legados = due_date; se omitida na
    #   criação, o service usa due_date como fallback.
    # chart_account_id: vínculo OPCIONAL a uma conta do plano de contas (chart_accounts, Story 5.1);
    #   sem FK dura — RLS + validação no service garantem a integridade lógica.
    competence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    chart_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Vínculo OPCIONAL ao Contract como eixo financeiro "projeto" (Story 5.4). Mesmo padrão de
    # referência solta (sem FK dura) de Charge.client_id. NULL = bucket implícito "Empresa"
    # (overhead) — quem não usa não é obrigado; legado nasce vazio.
    contract_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # Vínculo OPCIONAL ao centro de custo como 2ª dimensão de análise (Story 5.5). Mesmo padrão de
    # referência solta (sem FK dura). NULL = "Não atribuído" — quem não usa a dimensão não é
    # obrigado; legado nasce vazio e a visão padrão dos relatórios (sem filtro) fica idêntica.
    cost_center_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    recurrence: Mapped[str] = mapped_column(String(8), default=RECUR_NONE, nullable=False)
    # nº de repetições geradas e o grupo que liga as ocorrências da mesma recorrência
    recurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    recurrence_group: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Boleto/Pix recebido: linha digitável do boleto OU código Pix copia-e-cola.
    payment_code: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Anexo do boleto recebido (URL do PDF/imagem).
    attachment_url: Mapped[str] = mapped_column(String(1024), default="", nullable=False)

    agenda_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
