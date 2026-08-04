"""Conversa como entidade própria: grupos de WhatsApp na caixa de entrada

Revision ID: 0066
Revises: 0065
Create Date: 2026-08-04

Até aqui a caixa de entrada era indexada por `whatsapp_messages.client_id` — uma linha de
`clients`, que é o CRM/Kanban. Grupo de WhatsApp não é cliente (decisão do fundador: grupo
aparece em Conversas e NÃO entra no funil de vendas), então grupo simplesmente não tinha onde
existir: `parse_inbound` só reconhecia `@s.whatsapp.net`, e todo `@g.us` virava `from_phone=None`
→ TODOS os grupos colapsavam num balde único "Não identificados", que a tela nem conseguia abrir
(`client_id` nulo → `setSelected(null)` → estado vazio).

Esta migration cria a identidade que faltava:

- **`whatsapp_chats`** — a conversa. Chave real = `chat_jid` (o `key.remoteJid` que o WhatsApp
  entrega e que a Evolution aceita de volta no envio). `client_id` vira ENRIQUECIMENTO opcional
  da conversa direta, não mais a chave.
- **`whatsapp_messages`** ganha `chat_id` (a conversa), `sender_phone` e `sender_name` (quem
  falou dentro do grupo — sem isso um grupo de 30 pessoas vira um muro de balões anônimos).

Estritamente ADITIVA: 1 `CREATE TABLE`, 3 `ADD COLUMN` nullable, 1 `CREATE INDEX`. Nenhuma
coluna é removida e nenhuma vira `NOT NULL` — `whatsapp_conversation_states` continua de pé
(ver nota de dívida no fim deste docstring).

⚠️ ARMADILHA QUE **SE APLICA** AQUI (ao contrário da 0064/0065, que não tocam em linha nenhuma):
esta migration FAZ BACKFILL. Ela roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC
`app.current_tenant_id`. Sob `FORCE ROW LEVEL SECURITY`, `SELECT`/`INSERT`/`UPDATE` numa tabela
de negócio é filtrado a **ZERO LINHAS, em silêncio** — o backfill viraria um no-op que só
apareceria em produção, como histórico sumido da tela. Por isso a RLS de `whatsapp_messages`,
`whatsapp_chats`, `whatsapp_conversation_states` e `clients` é desabilitada SÓ na janela do
backfill e restaurada (ENABLE + FORCE) logo depois — mesmo padrão da `0046_ledger_classification`,
que descobriu isso na validação e2e em Postgres real. DDL é transacional no Postgres e a
migration roda offline, então não há janela de exposição.

**O backfill preserva o histórico** (nada de conversa que "some" no deploy):

1. Um chat direto por (tenant, client_id) com mensagem — `chat_jid` derivado de `clients.phone`
   (`{phone}@s.whatsapp.net`, que é exatamente o JID que aquele contato produz) e `title` = nome
   do cliente. Cliente sem telefone cai num JID sintético `client:{id}` — não inventamos um
   número que não existe.
2. Um chat "legado" por tenant que tenha mensagem SEM `client_id`, com `chat_jid`
   `legacy:unidentified` (ver `models.LEGACY_CHAT_JID`). Essas mensagens não guardaram JID
   nenhum — não há como reconstruir de qual conversa vieram, então elas ficam juntas, e agora
   ao menos ABREM. Mensagem nova nunca cai aqui.
3. `last_read_at` migra de `whatsapp_conversation_states` para o chat correspondente, senão toda
   conversa já lida voltaria a aparecer como não-lida no dia do deploy.

**Dívida deixada de propósito:** `whatsapp_conversation_states` fica órfã depois deste passo (o
estado de leitura passa a viver em `whatsapp_chats.last_read_at`, que é o único que consegue
representar leitura de grupo). Não é dropada aqui porque `DROP TABLE` é irreversível e o valor
de mantê-la por um ciclo — poder comparar os dois lados se o backfill tiver errado — é maior que
o custo de uma tabela parada. Dropar numa migration posterior, depois de confirmado em produção.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RLS_TABLES = (
    "whatsapp_messages",
    "whatsapp_chats",
    "whatsapp_conversation_states",
    "clients",
)


def upgrade() -> None:
    op.create_table(
        "whatsapp_chats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("chat_jid", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False, server_default="direct"),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "chat_jid", name="uq_whatsapp_chats_tenant_jid"),
    )
    op.create_index("ix_whatsapp_chats_chat_jid", "whatsapp_chats", ["chat_jid"])
    op.create_index("ix_whatsapp_chats_client_id", "whatsapp_chats", ["client_id"])

    op.execute("ALTER TABLE whatsapp_chats ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE whatsapp_chats FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON whatsapp_chats
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.add_column(
        "whatsapp_messages", sa.Column("chat_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "whatsapp_messages", sa.Column("sender_phone", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "whatsapp_messages", sa.Column("sender_name", sa.String(length=128), nullable=True)
    )
    op.create_index("ix_whatsapp_messages_chat_id", "whatsapp_messages", ["chat_id"])

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo abaixo é no-op) ---
    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # 1. um chat direto por (tenant, cliente) que já tenha conversa
    op.execute(
        """
        INSERT INTO whatsapp_chats
            (id, tenant_id, chat_jid, kind, title, client_id, created_at, updated_at)
        SELECT gen_random_uuid()::text,
               m.tenant_id,
               CASE
                   WHEN c.phone IS NOT NULL AND c.phone <> ''
                       THEN c.phone || '@s.whatsapp.net'
                   ELSE 'client:' || c.id
               END,
               'direct',
               c.name,
               c.id,
               now(),
               now()
        FROM (SELECT DISTINCT tenant_id, client_id
                FROM whatsapp_messages
               WHERE client_id IS NOT NULL) m
        JOIN clients c ON c.id = m.client_id AND c.tenant_id = m.tenant_id
        ON CONFLICT (tenant_id, chat_jid) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE whatsapp_messages m
           SET chat_id = ch.id
          FROM whatsapp_chats ch
         WHERE ch.tenant_id = m.tenant_id
           AND ch.client_id = m.client_id
           AND m.client_id IS NOT NULL
           AND m.chat_id IS NULL
        """
    )

    # 2. o balde legado, por tenant — mensagens que nunca resolveram cliente E não guardaram JID
    op.execute(
        """
        INSERT INTO whatsapp_chats
            (id, tenant_id, chat_jid, kind, title, client_id, created_at, updated_at)
        SELECT gen_random_uuid()::text, t.tenant_id, 'legacy:unidentified', 'direct',
               'Não identificados', NULL, now(), now()
        FROM (SELECT DISTINCT tenant_id
                FROM whatsapp_messages
               WHERE client_id IS NULL) t
        ON CONFLICT (tenant_id, chat_jid) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE whatsapp_messages m
           SET chat_id = ch.id
          FROM whatsapp_chats ch
         WHERE ch.tenant_id = m.tenant_id
           AND ch.chat_jid = 'legacy:unidentified'
           AND m.client_id IS NULL
           AND m.chat_id IS NULL
        """
    )

    # 3. estado de leitura: sem isto, toda conversa já lida volta a piscar como não-lida
    op.execute(
        """
        UPDATE whatsapp_chats ch
           SET last_read_at = s.last_read_at
          FROM whatsapp_conversation_states s
         WHERE s.tenant_id = ch.tenant_id
           AND s.client_id = ch.client_id
           AND ch.client_id IS NOT NULL
        """
    )

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_whatsapp_messages_chat_id", table_name="whatsapp_messages")
    op.drop_column("whatsapp_messages", "sender_name")
    op.drop_column("whatsapp_messages", "sender_phone")
    op.drop_column("whatsapp_messages", "chat_id")
    op.drop_index("ix_whatsapp_chats_client_id", table_name="whatsapp_chats")
    op.drop_index("ix_whatsapp_chats_chat_jid", table_name="whatsapp_chats")
    op.drop_table("whatsapp_chats")
