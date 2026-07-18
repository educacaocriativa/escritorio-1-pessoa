"""Templates de mensagem do WhatsApp Cloud API (Meta) — um por tenant, RLS.

A Meta exige que toda mensagem business-initiated (fora da janela de 24h de atendimento) use um
template pré-aprovado (categoria Marketing/Utility/Authentication). Esta tabela espelha o que a
Meta controla do lado dela: o tenant propõe (`category_requested`, `body_text`), a Meta aprova
(`status`, `category_approved` — pode divergir do solicitado — e `meta_template_id`) ou rejeita
(`rejected_reason`). Ver `app/core/whatsapp.py` para as chamadas à Graph API.
"""
from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Status espelhando o retorno da Graph API (`GET /{waba_id}/message_templates`).
STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_PAUSED = "PAUSED"
STATUS_DISABLED = "DISABLED"

# Categorias aceitas pela Meta (o que pedimos — a aprovada pode vir diferente).
CATEGORIES = ("MARKETING", "UTILITY", "AUTHENTICATION")

# ── Vínculo propósito→template (fluxos de sistema, NÃO o nó livre do funil) ──
#
# Diferente do nó de WhatsApp do Funil de Vendas (onde o usuário escolhe QUALQUER template
# aprovado e monta as variáveis livremente), estes 5 pontos do produto disparam WhatsApp de
# forma fixa/automática — o tenant só precisa vincular UM template aprovado por propósito
# (uma vez, em Configurações), e o sistema preenche as variáveis sozinho a cada envio.
#
# `PURPOSE_VARIABLE_SPECS` documenta, pra cada propósito, o rótulo de cada variável NA ORDEM
# em que o sistema vai preenchê-las ({{1}}, {{2}}, ...) — usado tanto para orientar o tenant ao
# escrever o corpo do template quanto para VALIDAR o vínculo (o template escolhido precisa ter
# exatamente `len(spec)` variáveis, ou o vínculo é rejeitado).
PURPOSE_CHARGE_REMINDER = "charge_reminder"
PURPOSE_CONTRACT_SEND = "contract_send"
PURPOSE_QUOTE_SEND = "quote_send"
PURPOSE_STAFF_INVITE = "staff_invite"
PURPOSE_CLIENT_MOVED = "client_moved"

PURPOSE_VARIABLE_SPECS: dict[str, list[str]] = {
    PURPOSE_CHARGE_REMINDER: [
        "Nome do cliente", "Frase de cobrança (a IA sugere uma; pode editar)",
        "Valor", "Vencimento",
    ],
    PURPOSE_CONTRACT_SEND: ["Nome do cliente", "Título do contrato", "Link de assinatura"],
    PURPOSE_QUOTE_SEND: ["Nome do cliente", "Título do orçamento", "Valor", "Link da proposta"],
    PURPOSE_STAFF_INVITE: ["Nome", "Empresa", "E-mail de login", "Senha temporária"],
    PURPOSE_CLIENT_MOVED: ["Nome do cliente", "Nome da nova etapa"],
}

PURPOSE_LABELS: dict[str, str] = {
    PURPOSE_CHARGE_REMINDER: "Lembrete de cobrança (Cobrar com IA)",
    PURPOSE_CONTRACT_SEND: "Envio de contrato",
    PURPOSE_QUOTE_SEND: "Envio de orçamento/proposta",
    PURPOSE_STAFF_INVITE: "Convite de funcionário (senha temporária)",
    PURPOSE_CLIENT_MOVED: "Aviso interno: cliente mudou de etapa no CRM",
}


class WhatsappTemplate(Base, TenantMixin, TimestampMixin):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", "language", name="uq_whatsapp_templates_tenant_name_lang"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="pt_BR", nullable=False)
    category_requested: Mapped[str] = mapped_column(String(20), nullable=False)
    # None até a Meta responder. Pode divergir de category_requested (a Meta recategoriza).
    category_approved: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, nullable=False)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Corpo com variáveis posicionais no formato Meta: {{1}}, {{2}}, ...
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    variable_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Exemplos obrigatórios por variável (a Meta rejeita submissão sem exemplo).
    variable_examples: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
