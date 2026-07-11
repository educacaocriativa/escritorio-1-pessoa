"""public_images: imagens deliberadamente públicas (logo/fotos) — tabela GLOBAL sem RLS

Story 4.2 (Upload real de logo e imagens). Tabela GLOBAL, deliberadamente SEM tenant_id como
controle de acesso e SEM RLS — mesmo padrão de `published_proposals` / `published_pages` /
`published_contracts`. A LEITURA é pública por design (a imagem é renderizada num `<img>` nas
páginas públicas sem login). O isolamento por tenant (Regra de Ouro nº 1) fica na ESCRITA
(`POST /attachments/public-images` exige usuário autenticado) — `tenant_id` é só rastreio.
É uma tabela SEPARADA de `attachments` (que guarda boletos/contratos e permanece 100% com RLS).

Revision ID: 0041
Revises: 0031
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "public_images",
        sa.Column("id", sa.String(36), primary_key=True),
        # tenant_id: coluna simples de rastreio/auditoria — NÃO controla acesso de leitura.
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_public_images_tenant_id", "public_images", ["tenant_id"])
    # SEM RLS por design: tabela GLOBAL de leitura pública (igual a published_*). O oposto de
    # `attachments` (que herda TenantMixin e é protegida por RLS). Ver models.PublicImage.


def downgrade() -> None:
    op.drop_table("public_images")
