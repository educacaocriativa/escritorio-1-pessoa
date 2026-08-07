"""Preferências de briefing por usuário

Revision ID: 0072
Revises: 0071
Create Date: 2026-08-06

⚠️ **O plano da Onda 4 dizia "migration 0071" — o número já estava tomado** pelo `ai_usage`, de
uma frente paralela que mergeou primeiro. Escrever a 0071 de novo produziria duas revisions com o
mesmo id e o `alembic upgrade head` escolheria uma delas em silêncio. Ao abrir uma branch longa,
reconfira o head a cada merge de `main`, não só na hora de escrever.

⚠️ `users` é tabela GLOBAL, SEM RLS (login por e-mail é global). Não há janela de RLS a abrir aqui
— e é justamente por isso que toda consulta a `users` precisa de filtro explícito por `tenant_id`,
que é a exceção documentada da Regra de Ouro nº 1.

Só DDL com `server_default`: as linhas existentes recebem o padrão sem `UPDATE`, então a armadilha
do backfill sob RLS (ver 0046/0066/0067/0068/0069) não se aplica.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "briefing_whatsapp_enabled", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    # `String(5)`, não `Time`: é a hora do RELÓGIO DE PAREDE do dono ("às 7h"), não um instante.
    # Um `Time` convidaria a comparar com `datetime.now().time()` em UTC — exatamente o bug que a
    # correção de fuso de 2026-08-05 eliminou. O scheduler compara "07:00" com a hora local do
    # tenant, e a string deixa isso explícito.
    op.add_column(
        "users",
        sa.Column(
            "briefing_hour", sa.String(length=5), nullable=False, server_default="07:00",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "briefing_hour")
    op.drop_column("users", "briefing_whatsapp_enabled")
