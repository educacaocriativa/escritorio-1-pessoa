"""O fuso do tenant muda de `tenant_profiles` para `tenants`

Revision ID: 0073
Revises: 0072
Create Date: 2026-08-06

**Por quê.** `tenant_profiles` tem `FORCE ROW LEVEL SECURITY` desde a 0022, e as rotas de `/auth`
rodam em sessão CRUA (`get_db`, sem a GUC de tenant): a policy filtrava o SELECT inteiro e
`timezone_of` caía sempre no padrão. Todo tenant que escolheu outro fuso recebia
`America/Sao_Paulo` na sessão — e o `useFuso()` do frontend inteiro sai desse valor.

O fuso é **identidade do tenant**, não brand kit: mora em `tenants`, que é tabela GLOBAL sem RLS
e que as rotas de auth já leem naturalmente. Isso ELIMINA a classe do problema em vez de
contorná-la com uma sessão extra ou um bypass de RLS.

⚠️ **`tenants` não tem RLS — logo, toda leitura precisa de filtro explícito por id.** É a mesma
exceção documentada de `users` (Regra de Ouro nº 1). O gate está em
`tests/test_auth_timezone_rls.py::test_o_fuso_NAO_atravessa_tenants`: trocar um bug de fuso por um
vazamento entre tenants seria infinitamente pior.

⚠️ **O backfill lê `tenant_profiles`, que TEM RLS — e por isso a desabilita na sua janela.** Sem
isso o `UPDATE ... FROM` casaria zero linhas e completaria com sucesso aparente, deixando todo
mundo no default: exatamente a armadilha das 0046/0066/0067/0068/0069, que o SQLite dos testes não
pega. A RLS é reabilitada (com FORCE) logo depois, no mesmo `upgrade`.

⚠️ **`tenant_profiles.timezone` NÃO é dropada aqui**, de propósito: `DROP COLUMN` é irreversível e
vale manter um ciclo para conferência (mesmo critério de `whatsapp_conversation_states` na 0066).
Nada mais a lê — o gate `test_settings_timezone.py::test_ninguem_le_mais_o_fuso_do_perfil` reprova
quem voltar a ler. Dropar numa migration posterior.

Numeração: nasceu como `0072` numa branch paralela à `feat/vima-briefing-superficies`, que
escreveu a OUTRA `0072` (preferências de briefing) — as duas saíram da mesma `main`. Aquela
mergeou primeiro (PR #90), então esta virou `0073` e encadeia depois dela. É o custo conhecido de
duas frentes abertas ao mesmo tempo neste repositório.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PADRAO = "America/Sao_Paulo"


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default=_PADRAO),
    )

    # Janela de RLS aberta na TABELA DE ORIGEM (não na de destino: `tenants` não tem RLS).
    # Ver a nota no topo — é a fonte da leitura que precisa estar visível, não o alvo do UPDATE.
    op.execute("ALTER TABLE tenant_profiles DISABLE ROW LEVEL SECURITY")
    try:
        op.execute(
            """
            UPDATE tenants AS t
               SET timezone = p.timezone
              FROM tenant_profiles AS p
             WHERE p.tenant_id = t.id
               AND p.timezone IS NOT NULL
               AND p.timezone <> ''
            """
        )
    finally:
        op.execute("ALTER TABLE tenant_profiles ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE tenant_profiles FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # `tenant_profiles.timezone` nunca foi removida, então voltar é só descartar a coluna nova —
    # e o que tiver sido editado em `tenants` depois desta migration se perde. É o preço de
    # desfazer, e está registrado aqui em vez de descoberto no meio de um rollback.
    op.drop_column("tenants", "timezone")
