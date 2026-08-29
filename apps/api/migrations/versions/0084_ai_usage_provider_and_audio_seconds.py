"""ai_usage ganha provider e audio_seconds — a Groq entra como segundo provedor de IA

Revision ID: 0084
Revises: 0083
Create Date: 2026-08-29

Por quê: a fatia de voz da Vima (docs/superpowers/specs/2026-08-29-vima-voz-entrada-design.md)
introduz a Groq (transcrição de áudio) como segundo provedor de IA do repositório — hoje
`ai_usage` assume implicitamente um único provedor (Anthropic): não existe coluna `provider`, e
`input_tokens`/`output_tokens`/`cache_*` são conceitos de cobrança da Anthropic que não fazem
sentido para a Groq (que cobra por SEGUNDO de áudio, não por token).

`provider` nasce com `server_default='anthropic'` PERMANENTE — ao contrário de
`opening_balance_is_known` (0074), aqui o default NÃO é removido depois: `ai_usage.record()`
continua chamado por dezenas de call sites Anthropic existentes que não vão declarar `provider`,
e forçar todos a mudar seria puro churn sem ganho — só o caminho novo (Groq) passa o valor
explícito. Sem UPDATE: DDL puro (`ADD COLUMN` com `server_default`), a mesma disciplina segura
das migrations 0074/0075/0077 contra a armadilha do backfill sob FORCE RLS (a RLS não alcança
DDL, só DML).

`audio_seconds` é nullable, sem default: preenchido SÓ em linhas de transcrição (provider='groq');
toda linha Anthropic tem `audio_seconds IS NULL` para sempre. Os dois nunca coexistem numa linha.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_usage"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("provider", sa.String(32), nullable=False, server_default="anthropic"),
    )
    op.add_column(_TABLE, sa.Column("audio_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column(_TABLE, "audio_seconds")
    op.drop_column(_TABLE, "provider")
