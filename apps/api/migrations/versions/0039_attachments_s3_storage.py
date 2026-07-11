"""attachments: storage S3-compatível (storage_key + data nullable) — Story 3.5

Migração ESTRUTURAL apenas (sem I/O de rede): adiciona `storage_key` e afrouxa `data` para
NULL, permitindo que os bytes morem no object storage S3 (ver app/core/storage.py) em vez do
Postgres. O backfill dos anexos legados é um script operacional SEPARADO
(`app.scripts.migrate_attachments_to_s3`), rodado manualmente — nunca acoplar chamada de S3
aqui, pois esta migration roda no boot do container (`alembic upgrade head`) e quebraria o boot
de ambientes sem bucket configurado.

A política RLS `tenant_isolation` (migration 0025) permanece válida sem alteração: filtra por
`tenant_id`, não pelas colunas de conteúdo (IV2 preservado).

Revision ID: 0039
Revises: 0031
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Número 0039 RESERVADO exclusivamente para esta story (evita colisão com stories em paralelo).
revision: str = "0039"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("storage_key", sa.String(512), nullable=True))
    # `data` era NOT NULL (migration 0025); afrouxa p/ NULL — anexos no S3 têm data=None.
    op.alter_column("attachments", "data", existing_type=sa.LargeBinary(), nullable=True)


def downgrade() -> None:
    # Best-effort / estrutural apenas. Removemos a coluna storage_key, mas NÃO revertemos `data`
    # para NOT NULL: se já houver linhas migradas para o S3 (`data IS NULL`), reimpor a
    # constraint quebraria. O downgrade NÃO reidrata os bytes do S3 de volta ao Postgres —
    # isso exigiria o caminho inverso do script de backfill, fora do escopo de uma migration.
    op.drop_column("attachments", "storage_key")
