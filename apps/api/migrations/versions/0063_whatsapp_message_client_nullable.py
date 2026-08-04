"""whatsapp_messages.client_id vira nullable (Onda 3 — bandeja "não identificados" p/ @lid)

Revision ID: 0063
Revises: 0062
Create Date: 2026-07-30

Quando o WhatsApp entrega `@lid` no lugar do telefone (esconde o número), não dá pra resolver
o cliente com confiança — em vez de adivinhar por heurística (erra em silêncio, ver estudo do
Orbitask na spec), a mensagem fica com client_id=NULL e cai numa bandeja "Não identificados" na
tela de Conversas; o atendente liga manualmente ao cliente certo com um clique.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("whatsapp_messages", "client_id", nullable=True)


def downgrade() -> None:
    # Nenhuma mensagem com client_id NULL deveria existir se o downgrade for aplicado
    # imediatamente após o upgrade sem uso real — mas um downgrade em produção com dados reais
    # exigiria decidir o que fazer com linhas NULL primeiro (fora de escopo: dívida documentada).
    op.alter_column("whatsapp_messages", "client_id", nullable=False)
