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

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

STATUS_OPEN = "open"
# ── `scheduled` (Story 8.14) — o pagamento AGENDADO no app do banco ──────────────────────────
#
# *"Esta conta ainda vai sair da minha conta?"* com `scheduled` é `status == 'scheduled'`. Com a
# alternativa rejeitada (`paid` + `paid_at` futuro) seria `status == 'paid' AND paid_at > today` —
# um predicado que se lê **"pago no futuro"**, contradição em termos, que teria de ser replicado em
# CINCO lugares (`payment_queue`, `summary`, `projection._window_sums`, `receipts.list_candidates`
# e a regra do Diagnóstico da 8.16). *"Cinco cópias de um predicado autocontraditório é a definição
# de o modelo estar errado."*
#
# E o argumento que decidiu não foi de gosto, foi um **bug verificado**: com `paid`+futuro a conta
# sai dos fluxos de saída da Projeção (`projection.py` filtrava `status == 'open'`) **e** o
# movimento futuro não entra no `saldo_inicial` (`active_balance_total(until=today)`). Os R$ 5.000
# agendados **sumiriam** da Projeção — a máquina de falso negativo da Onda 0 ressuscitada, na mesma
# tela que a Onda 0 consertou.
#
# ⚠️ **CABE EM `String(12)` — e é por isso que esta story não tem migration.** `"scheduled"` tem 9
# caracteres (`test_scheduled_cabe_na_coluna` afere isso explicitamente, contra o `type.length` real
# da coluna). Quem quiser "melhorar" este vocabulário para uma string maior paga uma migration com
# `ALTER TYPE` sobre dado em produção, sob `FORCE RLS` — a armadilha da 0046 que o ADR 0003 nomeia.
STATUS_SCHEDULED = "scheduled"
STATUS_PAID = "paid"
STATUS_CANCELED = "canceled"
ALL_STATUSES = {STATUS_OPEN, STATUS_SCHEDULED, STATUS_PAID, STATUS_CANCELED}

# Recorrência (auto-geração de contas futuras fica como dívida — só armazenamos por ora).
RECUR_NONE = "none"
RECUR_WEEKLY = "weekly"
RECUR_MONTHLY = "monthly"
RECUR_YEARLY = "yearly"
ALL_RECURRENCES = {RECUR_NONE, RECUR_WEEKLY, RECUR_MONTHLY, RECUR_YEARLY}


class Payable(Base, TenantMixin, TimestampMixin):
    __tablename__ = "payables"

    # Índice de leitura da Regra da Origem (Story 8.9): *"o que saiu desta conta?"*. Declarado aqui
    # e não com `index=True` na coluna porque a migration 0064 o cria COMPOSTO com `tenant_id` na
    # frente — e schema declarado divergindo do schema migrado é como o SQLite dos unitários passa
    # a exercitar um banco que a produção não tem.
    __table_args__ = (
        Index("ix_payables_bank_account", "tenant_id", "bank_account_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(48), default="Geral", nullable=False)
    supplier: Mapped[str] = mapped_column(String(120), default="", nullable=False)  # fornecedor
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # `String(12)` — ver o comentário de `STATUS_SCHEDULED` acima: o valor novo da Story 8.14 cabe
    # aqui (9 < 12) e é por isso que aquela story não cria migration nenhuma.
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
    # Número/identificador do documento (nota fiscal, recibo...) — texto livre, sem validação de
    # formato. Observações: nota livre do dono sobre a conta. Ambos aplicam-se a TODAS as
    # ocorrências de uma recorrência (mesma disciplina de `description`/`supplier`), ao contrário
    # de `payment_code`/`attachment_url`, que são por ocorrência.
    documento: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    observacoes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    agenda_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── A Regra da Origem (Story 8.9, migration 0064, design Onda 2 §3.3) ────────────────────
    # As duas colunas nascem NULL e **nenhum caminho de produção as escreve nesta story**: a Story
    # 8.9 entrega o contrato, e a **8.12** liga `apply_paid` a ele. Sem FK dura (padrão do
    # projeto, igual a `cost_center_id`/`chart_account_id`): a integridade é validada no service,
    # sob RLS.
    #
    # **REGRA DE AUTORIDADE — não existem duas verdades, existe uma verdade e um cache:**
    #
    #   `bank_account_id`      → **DECISÃO DO USUÁRIO, AUTORITATIVA.** *"De qual conta este
    #                            pagamento saiu?"* Existe desde a baixa, **inclusive quando o
    #                            movimento ainda não pôde ser gerado**. É dela que
    #                            `bank_transactions.bank_account_id` é DERIVADA, pelo
    #                            sincronizador (`bank/origin.py::sync_origin_movement`) e por
    #                            nenhum outro caminho.
    #   `bank_transaction_id`  → **CACHE DE LEITURA.** Conveniência para responder *"qual é o
    #                            movimento desta conta paga?"* sem um segundo SELECT. Se divergir
    #                            do movimento cujo `origin_id = payable.id`, **quem manda é o
    #                            `origin_id`** — o cache está errado, o movimento não.
    #
    # ⚠️ Por que a regra de autoridade mora no código e não só no design: a divergência entre o
    # cache e o `origin_id` só é alcançável **por bug** (o sincronizador é o escritor único, devolve
    # a linha na mesma chamada e na mesma transação), e condição alcançável só por bug se prova com
    # **teste**, não com script — `test_cache_de_movimento_nunca_diverge_do_origin_id`
    # (`tests/test_bank_origin.py`), que a 8.12 estende para os caminhos reais de mutação.
    # `app/scripts/bank_audit.py` **não existe e não deve ser criado** aqui (ratificação §C-4); ele
    # volta a ser necessário na Onda 5, junto de `_refresh_status`.
    bank_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    bank_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
