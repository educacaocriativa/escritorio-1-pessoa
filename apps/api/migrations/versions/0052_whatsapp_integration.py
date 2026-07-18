"""credenciais WhatsApp por tenant + gerenciamento de templates

Revision ID: 0052
Revises: 0051
Create Date: 2026-07-18

Duas mudanças, mesma story (integração real de WhatsApp por tenant — hoje era um único
WHATSAPP_TOKEN/PHONE_ID global em env, errado pra um SaaS multi-tenant onde cada escritório
precisa da própria conta no WhatsApp Cloud API da Meta):

1. `tenant_profiles` ganha 3 colunas nullable (sem backfill — NULL = integração desligada, mesmo
   comportamento de graceful degradation que já existia com a env global):
   - `whatsapp_token` (texto cifrado em repouso via `EncryptedToken`/Fernet — mesmo padrão já
     usado pelos tokens OAuth do Google em `google_credentials`, ver `core/token_crypto.py`).
   - `whatsapp_phone_id` (Phone Number ID da Meta — não é segredo, é um ID de conta).
   - `whatsapp_waba_id` (WhatsApp Business Account ID — necessário para criar/consultar
     templates via Graph API, além de enviar mensagens).

2. `whatsapp_templates` (RLS) — um template de mensagem por linha, espelhando o que a Meta
   controla (nome, idioma, categoria solicitada x aprovada, status, motivo de rejeição, ID da
   Meta). A Meta EXIGE que toda mensagem business-initiated (fora da janela de 24h de
   atendimento) use um template pré-aprovado — não dá mais para disparar texto livre.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenant_profiles", sa.Column("whatsapp_token", sa.Text(), nullable=True))
    op.add_column(
        "tenant_profiles", sa.Column("whatsapp_phone_id", sa.String(64), nullable=True)
    )
    op.add_column(
        "tenant_profiles", sa.Column("whatsapp_waba_id", sa.String(64), nullable=True)
    )

    op.create_table(
        "whatsapp_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="pt_BR"),
        sa.Column("category_requested", sa.String(20), nullable=False),
        sa.Column("category_approved", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("meta_template_id", sa.String(64), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("variable_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("variable_examples", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "name", "language", name="uq_whatsapp_templates_tenant_name_lang"
        ),
    )
    op.create_index("ix_whatsapp_templates_tenant_id", "whatsapp_templates", ["tenant_id"])
    op.execute("ALTER TABLE whatsapp_templates ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE whatsapp_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON whatsapp_templates
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_templates_tenant_id", table_name="whatsapp_templates")
    op.drop_table("whatsapp_templates")
    op.drop_column("tenant_profiles", "whatsapp_waba_id")
    op.drop_column("tenant_profiles", "whatsapp_phone_id")
    op.drop_column("tenant_profiles", "whatsapp_token")
