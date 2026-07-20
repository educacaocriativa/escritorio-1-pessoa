"""public_whatsapp_accounts.app_secret cifrado em repouso (EncryptedToken)

Revision ID: 0056
Revises: 0055
Create Date: 2026-07-19

Achado da revisão final de branch: `PublicWhatsappAccount.app_secret` guardava o segredo do App
da Meta em TEXTO PLANO (`String(255)`), ao contrário de `TenantProfile.whatsapp_app_secret`
(mesmo segredo, mesma origem, já cifrado via `EncryptedToken`/Fernet — ver
`app/core/token_crypto.py`). Um vazamento de dump/backup do banco expunha o segredo em claro,
permitindo forjar a assinatura `X-Hub-Signature-256` do webhook e injetar mensagens/leads falsos
em qualquer tenant (`public_whatsapp_accounts` é uma tabela GLOBAL, sem RLS, por design — resolve
`phone_number_id -> tenant_id` ANTES de qualquer autenticação).

`EncryptedToken` (`app/core/token_crypto.py`) cifra/decifra de forma transparente no nível
Python — nenhum código que lê/escreve `account.app_secret` precisa mudar (confirmado:
`settings/service.py::_sync_whatsapp_webhook_snapshot` e
`whatsapp_inbox/router.py::receive_webhook` só manipulam a string em claro via o atributo do
ORM). Mas o tipo SQL subjacente do `TypeDecorator` é `TEXT`, não `VARCHAR(255)` — mesmo padrão
que `TenantProfile.whatsapp_app_secret` já usa (criada como `sa.Text()` direto na migration 0054,
por já nascer com o tipo certo). Como `public_whatsapp_accounts.app_secret` nasceu como
`String(255)` (migration 0054, tabela ainda sem `EncryptedToken` na época), aqui fazemos o
ALTER explícito de VARCHAR(255) -> TEXT para acomodar o ciphertext (mais longo que o segredo
original) e alinhar o tipo real da coluna ao `TypeDecorator`.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "public_whatsapp_accounts",
        "app_secret",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "public_whatsapp_accounts",
        "app_secret",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
    )
