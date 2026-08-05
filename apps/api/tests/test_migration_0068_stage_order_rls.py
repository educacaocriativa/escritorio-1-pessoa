"""Migration 0068 (backfill de `stage_entered_at`) sob RLS REAL.

O fato que a suíte SQLite é estruturalmente incapaz de provar: **o backfill não é no-op.**
`clients` tem FORCE ROW LEVEL SECURITY e a migration roda como o papel não-superusuário
`e1p_app` sem GUC de tenant. Se a janela de DISABLE/ENABLE sumisse, o UPDATE afetaria zero
linhas SEM ERRO NENHUM — e o sintoma em produção não seria uma falha de deploy, seria "a
fila do Kanban continua fora de ordem", meses depois.

Semeamos `clients` e `client_events` parando na 0067 e só então aplicamos a 0068: backfill
sobre tabela vazia é indistinguível de backfill no-op, que é o bug que este arquivo existe
para pegar.

Marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job `cross-tenant-rls` do
CI ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

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

    O teste precisa parar em `0067`, semear e só então aplicar a `0068` — senão o backfill
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


# (nome, created_at do cliente, kind do evento ou None, created_at do evento, data esperada)
SEMENTES = [
    ("Sem Evento", "2026-07-01", None, None, "2026-07-01"),
    ("Com Move", "2026-07-01", "stage_move", "2026-07-20", "2026-07-20"),
    ("Com Reopen", "2026-07-02", "reopened", "2026-07-25", "2026-07-25"),
    # `lead_created` NÃO é troca de etapa: tem que cair em `created_at`, não no evento.
    ("So Lead Created", "2026-07-03", "lead_created", "2026-07-28", "2026-07-03"),
]


@pytest.fixture(scope="module")
def ambiente():
    """Sobe Postgres, migra até 0067, SEMEIA, e só então aplica a 0068."""
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
        _run_migrations_as_app(app_url, "0067")

        tenant_a = str(uuid4())
        engine = create_engine(app_url, poolclass=NullPool)
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_a}
            )
            for nome, criado_em, kind, evento_em, _esperado in SEMENTES:
                client_id = str(uuid4())
                conn.execute(
                    text(
                        "INSERT INTO clients (id, tenant_id, name, gender, notes, tags, "
                        "source, created_at, updated_at) VALUES "
                        "(:id, :t, :n, 'unspecified', '', '[]'::json, 'landing', "
                        ":criado, :criado)"
                    ),
                    {"id": client_id, "t": tenant_a, "n": nome, "criado": criado_em},
                )
                if kind is not None:
                    conn.execute(
                        text(
                            "INSERT INTO client_events (id, tenant_id, client_id, kind, "
                            "title, body, actor, is_ai, created_at, updated_at) VALUES "
                            "(:id, :t, :c, :k, 'x', '', 'teste', false, :quando, :quando)"
                        ),
                        {
                            "id": str(uuid4()), "t": tenant_a, "c": client_id,
                            "k": kind, "quando": evento_em,
                        },
                    )
        engine.dispose()

        # AGORA a 0068 — o backfill encontra linhas de verdade.
        _run_migrations_as_app(app_url, "0068")

        yield {"url": app_url, "tenant_a": tenant_a}


def test_backfill_nao_foi_no_op(ambiente):
    """Se a janela de RLS sumisse, TODAS viriam NULL — e o deploy não reclamaria."""
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            linhas = conn.execute(
                text("SELECT name, stage_entered_at FROM clients ORDER BY name")
            ).fetchall()

        obtido = {linha.name: linha.stage_entered_at for linha in linhas}
        assert len(obtido) == len(SEMENTES)
        assert all(v is not None for v in obtido.values()), f"backfill foi no-op: {obtido}"

        for nome, _criado, _kind, _quando, esperado in SEMENTES:
            assert obtido[nome].strftime("%Y-%m-%d") == esperado, (
                f"{nome}: esperado {esperado}, veio {obtido[nome]}"
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("tabela", ["clients", "client_events"])
def test_rls_foi_restaurada(ambiente, tabela):
    """A janela do backfill DESLIGA a RLS das DUAS tabelas. Esquecer de religar abre uma
    delas em produção.

    Sem esta asserção, uma 0068 que abrisse as tabelas e não fechasse passaria feliz no
    teste acima — o backfill teria funcionado, e o vazamento seria invisível.

    `client_events` entra aqui porque é a FONTE da subconsulta do backfill: ela precisa ser
    aberta junto (a RLS filtra SELECT), e portanto precisa ser fechada junto.
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
        assert linha.relrowsecurity is True, f"RLS de `{tabela}` ficou DESLIGADA após a 0068"
        assert linha.relforcerowsecurity is True, f"FORCE de `{tabela}` não foi restaurado"
    finally:
        engine.dispose()
