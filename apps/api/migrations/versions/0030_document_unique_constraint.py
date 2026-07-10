"""users: unicidade de CPF/CNPJ (document) por tenant

Constraint COMPOSTA UNIQUE(tenant_id, document) — nunca `document` sozinho, porque `users` é
tabela GLOBAL sem RLS e tenants distintos podem legitimamente ter o mesmo documento. NULLs são
distintos no Postgres, então owners de /register (document=None) e o admin de plataforma não
colidem. Não é um CHECK de formato — a validação de dígito verificador vive na camada Pydantic,
para não quebrar o seed do tenant interno `platform` (document sentinela).

NOTA (stories paralelas): a Story 1.2 também cria uma migration em paralelo (provavelmente 0031).
Se ambas forem mescladas junto, pode ser necessário um rebase da cadeia `down_revision` no merge
— isso é esperado, não é erro.

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-10
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_user_tenant_document", "users", ["tenant_id", "document"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_user_tenant_document", "users", type_="unique")
