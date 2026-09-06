"""audit_entries ganha `detail` — o SNAPSHOT que o `target` não recupera depois

Revision ID: 0087
Revises: 0086
Create Date: 2026-09-05

Por quê (issue #307): os três `audit.record()` do Google Calendar
(`google_calendar/service.py`) gravavam só `target=cred.id` — e os DOIS caminhos de saída
apagam a `GoogleCredential` na MESMA transação (`disconnect` faz `db.delete(cred)`;
`_descartar_credencial_revogada` idem). O id sobrevive apontando para uma linha que não existe
mais, então QUAL conta Google entrou ou saiu não era recuperável por nenhum join. A 0086 tinha
deixado a procedência em `agenda_events.google_account_email`, mas a própria invalidação de
reconexão ZERA essa coluna — o último rastro morria exatamente no evento que se queria auditar.

É o mesmo raciocínio que `platform_audit_entries` já aplica (`actor_email`,
`target_tenant_slug`): guardar SNAPSHOT quando o alvo é apagado logo em seguida.

`String(255)` + `NOT NULL` + `server_default=""`: a coluna cabe um e-mail inteiro (254, RFC
5321), que NÃO caberia composto no `target` (`String(255)` já ocupado por um UUID de 36).

O `server_default=""` é o que BACKFILLA as linhas existentes — e é DDL puro, sem `UPDATE`,
mantendo a disciplina das 0084/0085/0086: um `UPDATE` aqui rodaria sob FORCE RLS sem
`app.current_tenant_id`, seria filtrado a ZERO linhas e "passaria" em silêncio. Aqui o valor
das linhas antigas é `""` e isso é CORRETO, não uma lacuna: aquelas ações não tinham detalhe.

Diferente da 0086, `NULL` NÃO tem significado semântico nesta coluna — "sem detalhe" é `""`,
não "detalhe desconhecido". Por isso `NOT NULL`, espelhando o irmão `target`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_entries",
        sa.Column("detail", sa.String(255), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("audit_entries", "detail")
