"""vínculo propósito→template do WhatsApp + colunas de template em notifications

Revision ID: 0053
Revises: 0052
Create Date: 2026-07-18

Fecha a lacuna deixada pela Story anterior (0052): os outros 5 pontos do produto que mandam
WhatsApp business-initiated (lembrete de cobrança, envio de contrato, envio de orçamento,
convite de staff, aviso interno de card movido) ainda usavam texto livre. A Meta exige template
pré-aprovado pra todos — mas cada um desses fluxos tem um "propósito" fixo (não é livre escolha
do usuário como no nó do funil), então o tenant só precisa VINCULAR um template já aprovado a
cada propósito, uma vez, em vez de escolher a cada envio.

1. `tenant_profiles.whatsapp_template_bindings` (JSON, dict propósito→template_id). Vazio/sem a
   chave = propósito ainda não vinculado — o fluxo correspondente cai no comportamento antigo
   (texto livre via `send_text`, agora ciente das credenciais do tenant), sem quebrar nada.
2. `notifications` ganha 3 colunas nullable pra suportar o caminho ASSÍNCRONO (fila do worker,
   usado hoje só por `on_client_moved`): o propósito é resolvido no ENFILEIRAMENTO (dentro da
   request), mas o ENVIO real acontece depois no worker (`process_pending`) — por isso o nome/
   idioma/variáveis do template precisam ficar guardados na própria notificação enfileirada.
   `whatsapp_template_name`, `whatsapp_template_language`, `whatsapp_template_variables` (JSON).
   NULL nas 3 = mesmo comportamento antigo (texto livre) nesse envio.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles",
        sa.Column("whatsapp_template_bindings", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "notifications", sa.Column("whatsapp_template_name", sa.String(512), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("whatsapp_template_language", sa.String(10), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("whatsapp_template_variables", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notifications", "whatsapp_template_variables")
    op.drop_column("notifications", "whatsapp_template_language")
    op.drop_column("notifications", "whatsapp_template_name")
    op.drop_column("tenant_profiles", "whatsapp_template_bindings")
