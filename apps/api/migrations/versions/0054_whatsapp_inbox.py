"""inbox de whatsapp: mensagens, estado de leitura, resolução pré-auth do webhook

Revision ID: 0054
Revises: 0053
Create Date: 2026-07-19

Três peças novas pra suportar a conversa de ida-e-volta com clientes pelo WhatsApp (design em
docs/superpowers/specs/2026-07-19-whatsapp-inbox-design.md):

1. `tenant_profiles` ganha `whatsapp_app_secret` (cifrado, valida a assinatura do webhook) e
   `whatsapp_verify_token` (texto simples, handshake de verificação da Meta).
2. `whatsapp_messages` (RLS) — cada mensagem trocada (`in`/`out`), com mídia opcional.
3. `whatsapp_conversation_states` (RLS) — 1 linha por cliente com atividade, só pra "lida/não
   lida" (compartilhada, sem granularidade por atendente).
4. `public_whatsapp_accounts` (GLOBAL, sem RLS) — resolve `phone_number_id -> tenant_id` +
   `app_secret`/`verify_token` ANTES de qualquer autenticação, mesmo padrão de
   `public_integration_keys`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles", sa.Column("whatsapp_app_secret", sa.Text(), nullable=True)
    )
    op.add_column(
        "tenant_profiles", sa.Column("whatsapp_verify_token", sa.String(64), nullable=True)
    )

    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("direction", sa.String(4), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="text"),
        sa.Column("text_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_attachment_id", sa.String(36), nullable=True),
        sa.Column("media_status", sa.String(16), nullable=False, server_default="none"),
        sa.Column("wa_message_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="sent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "wa_message_id", name="uq_whatsapp_messages_tenant_wa_id"
        ),
    )
    op.create_index("ix_whatsapp_messages_tenant_id", "whatsapp_messages", ["tenant_id"])
    op.create_index("ix_whatsapp_messages_client_id", "whatsapp_messages", ["client_id"])
    op.execute("ALTER TABLE whatsapp_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE whatsapp_messages FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON whatsapp_messages
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.create_table(
        "whatsapp_conversation_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id", "client_id", name="uq_whatsapp_conv_state_tenant_client"
        ),
    )
    op.create_index(
        "ix_whatsapp_conversation_states_tenant_id",
        "whatsapp_conversation_states",
        ["tenant_id"],
    )
    op.create_index(
        "ix_whatsapp_conversation_states_client_id",
        "whatsapp_conversation_states",
        ["client_id"],
    )
    op.execute("ALTER TABLE whatsapp_conversation_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE whatsapp_conversation_states FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON whatsapp_conversation_states
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.create_table(
        "public_whatsapp_accounts",
        sa.Column("phone_number_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("app_secret", sa.String(255), nullable=False),
        sa.Column("verify_token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("public_whatsapp_accounts")
    op.drop_index(
        "ix_whatsapp_conversation_states_client_id",
        table_name="whatsapp_conversation_states",
    )
    op.drop_index(
        "ix_whatsapp_conversation_states_tenant_id", table_name="whatsapp_conversation_states"
    )
    op.drop_table("whatsapp_conversation_states")
    op.drop_index("ix_whatsapp_messages_client_id", table_name="whatsapp_messages")
    op.drop_index("ix_whatsapp_messages_tenant_id", table_name="whatsapp_messages")
    op.drop_table("whatsapp_messages")
    op.drop_column("tenant_profiles", "whatsapp_verify_token")
    op.drop_column("tenant_profiles", "whatsapp_app_secret")
