"""Migration 0078 (backfill de `agenda_events.client_id`) sob RLS REAL.

O fato que a suíte SQLite é estruturalmente incapaz de provar: **o backfill não é no-op.**
`agenda_events` e `charges` têm FORCE ROW LEVEL SECURITY e a migration roda como o papel
não-superusuário `e1p_app` sem GUC de tenant. Sem a janela de DISABLE/ENABLE o UPDATE
afetaria zero linhas SEM ERRO NENHUM — e o sintoma em produção não seria falha de deploy,
seria "a ficha do cliente não mostra compromisso nenhum", meses depois.

Semeamos parando na 0077 e só então aplicamos a 0078: backfill sobre tabela vazia é
indistinguível de backfill no-op, que é o bug que este arquivo existe para pegar.

Marcado `rls_e2e`: NÃO roda no `pytest -q`; roda no job `cross-tenant-rls` do CI e
localmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"

_API_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _run_migrations_as_app(app_url: str, revision: str) -> None:
    """Aplica migrations como `e1p_app`, parando na revisão pedida.

    O teste precisa parar em `0077`, semear e só então aplicar a `0078` — senão o backfill
    rodaria sobre tabela vazia, e backfill de tabela vazia é indistinguível de backfill
    no-op (que é exatamente o bug que este arquivo existe para pegar).
    """
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, revision)
    finally:
        settings.database_url = original_url


_AGORA = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def ambiente():
    """Sobe Postgres, migra até 0077, SEMEIA, e só então aplica a 0078.

    A semente cobre os três casos do backfill num único tenant:
      - `charge`: uma cobrança com `client_id` preenchido.
      - `evento_cobranca`: `kind='cobranca_receber'`, `external_ref` = id da `charge` acima —
        é o evento que o backfill DEVE ligar ao cliente.
      - `evento_bloqueio`: sem `external_ref` — não tem de onde herdar dono, fica órfão.
      - `payable`: uma conta a pagar cujo `id` é **deliberadamente igual ao `id` da charge**
        (tabelas diferentes, sem FK — não há conflito de PK). Isso testa a armadilha real: se o
        backfill não filtrasse por `kind`, a colisão de id ligaria `evento_pagar` ao cliente
        errado.
      - `evento_pagar`: `kind='cobranca_pagar'`, `external_ref` = esse id colidido — deve
        continuar órfão porque o filtro `kind='cobranca_receber'` o exclui da UPDATE.
    """
    with PostgresContainer(
        "postgres:16-alpine",
        username=_ROOT_USER,
        password=_ROOT_PASS,
        dbname=_DB_NAME,
        driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url, "0077")

        tenant_a = str(uuid4())
        client_id = str(uuid4())
        charge_id = str(uuid4())
        payable_id = charge_id  # colisão DELIBERADA entre tabelas diferentes (ver docstring)

        evento_cobranca_id = str(uuid4())
        evento_bloqueio_id = str(uuid4())
        evento_pagar_id = str(uuid4())

        engine = create_engine(app_url, poolclass=NullPool)
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_a}
            )

            # Cobrança com dono (client_id preenchido) — a FONTE do backfill.
            conn.execute(
                text(
                    "INSERT INTO charges (id, tenant_id, client_id, kind, method, "
                    "amount_cents, due_date) VALUES "
                    "(:id, :t, :c, 'service', 'pix', 15000, '2026-07-01')"
                ),
                {"id": charge_id, "t": tenant_a, "c": client_id},
            )

            # Conta a pagar cujo id colide com o da charge acima (ver docstring da fixture).
            conn.execute(
                text(
                    "INSERT INTO payables (id, tenant_id, amount_cents, due_date) VALUES "
                    "(:id, :t, 8000, '2026-07-05')"
                ),
                {"id": payable_id, "t": tenant_a},
            )

            # Evento de cobrança a receber — DEVE ganhar client_id no backfill.
            conn.execute(
                text(
                    "INSERT INTO agenda_events (id, tenant_id, title, kind, external_ref, "
                    "starts_at, ends_at) VALUES "
                    "(:id, :t, 'Vencimento', 'cobranca_receber', :ref, :ini, :fim)"
                ),
                {
                    "id": evento_cobranca_id, "t": tenant_a, "ref": charge_id,
                    "ini": _AGORA, "fim": _AGORA,
                },
            )

            # Bloqueio de horário, sem external_ref — não tem de onde herdar dono.
            conn.execute(
                text(
                    "INSERT INTO agenda_events (id, tenant_id, title, kind, "
                    "starts_at, ends_at) VALUES "
                    "(:id, :t, 'Fora do escritório', 'bloqueio', :ini, :fim)"
                ),
                {"id": evento_bloqueio_id, "t": tenant_a, "ini": _AGORA, "fim": _AGORA},
            )

            # Conta a pagar cujo external_ref colide com o id da charge — deve ficar órfão.
            conn.execute(
                text(
                    "INSERT INTO agenda_events (id, tenant_id, title, kind, external_ref, "
                    "starts_at, ends_at) VALUES "
                    "(:id, :t, 'Aluguel', 'cobranca_pagar', :ref, :ini, :fim)"
                ),
                {
                    "id": evento_pagar_id, "t": tenant_a, "ref": payable_id,
                    "ini": _AGORA, "fim": _AGORA,
                },
            )
        engine.dispose()

        # AGORA a 0078 — o backfill encontra linhas de verdade.
        _run_migrations_as_app(app_url, "0078")

        yield {
            "url": app_url,
            "tenant_a": tenant_a,
            "client_id": client_id,
            "evento_cobranca_id": evento_cobranca_id,
            "evento_bloqueio_id": evento_bloqueio_id,
            "evento_pagar_id": evento_pagar_id,
        }


def _client_id_de(ambiente: dict, evento_id: str) -> str | None:
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            linha = conn.execute(
                text("SELECT client_id FROM agenda_events WHERE id = :id"),
                {"id": evento_id},
            ).one()
        return linha.client_id
    finally:
        engine.dispose()


def test_backfill_liga_evento_de_cobranca_ao_cliente(ambiente):
    """O caso que o backfill existe para resolver: evento antigo ganha dono."""
    obtido = _client_id_de(ambiente, ambiente["evento_cobranca_id"])
    assert obtido == ambiente["client_id"], (
        f"evento de cobranca_receber deveria herdar client_id={ambiente['client_id']!r} "
        f"da charge, veio {obtido!r}"
    )


def test_backfill_nao_e_no_op(ambiente):
    """A asserção que só o Postgres com RLS pode fazer.

    Se alguém remover a janela de DISABLE ROW LEVEL SECURITY, o UPDATE roda, não falha, e
    afeta zero linhas. Este teste é a única coisa entre esse commit e a produção.
    """
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            total = conn.execute(
                text("SELECT COUNT(*) FROM agenda_events WHERE client_id IS NOT NULL")
            ).scalar_one()
        assert total >= 1, f"backfill foi no-op: {total} eventos com client_id não nulo"
    finally:
        engine.dispose()


def test_backfill_nao_inventa_dono(ambiente):
    """Evento sem cobrança e conta a PAGAR continuam órfãos — e devem."""
    bloqueio = _client_id_de(ambiente, ambiente["evento_bloqueio_id"])
    pagar = _client_id_de(ambiente, ambiente["evento_pagar_id"])
    assert bloqueio is None, f"bloqueio sem external_ref não deveria ter dono, veio {bloqueio!r}"
    assert pagar is None, (
        f"cobranca_pagar cujo external_ref colide com o id de uma charge não deveria herdar "
        f"dono (o filtro kind='cobranca_receber' deveria excluí-lo), veio {pagar!r}"
    )


@pytest.mark.parametrize("tabela", ["agenda_events", "charges"])
def test_rls_foi_restaurada(ambiente, tabela):
    """A janela do backfill DESLIGA a RLS das DUAS tabelas. Esquecer de religar abre uma
    delas em produção.

    `charges` entra aqui porque é a FONTE da subconsulta do backfill: ela precisa ser aberta
    junto (a RLS filtra SELECT), e portanto precisa ser fechada junto.
    """
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            linha = conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = :t"
                ),
                {"t": tabela},
            ).one()
        assert linha.relrowsecurity is True, f"RLS de `{tabela}` ficou DESLIGADA após a 0078"
        assert linha.relforcerowsecurity is True, f"FORCE de `{tabela}` não foi restaurado"
    finally:
        engine.dispose()
