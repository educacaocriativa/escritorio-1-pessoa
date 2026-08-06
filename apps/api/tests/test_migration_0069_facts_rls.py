"""Migration 0069 (`facts` absorve `client_events`) sob RLS REAL.

O fato que a suíte SQLite é estruturalmente incapaz de provar: **a migração de dados não é
no-op.** O `INSERT ... SELECT` lê `client_events` e escreve em `facts`, ambas com FORCE ROW
LEVEL SECURITY, e a migration roda como o papel não-superusuário `e1p_app` sem GUC de tenant.
Se a janela de DISABLE/ENABLE sumisse, o SELECT devolveria zero linhas e o INSERT gravaria zero
— SEM ERRO NENHUM. O sintoma em produção não seria falha de deploy, seria "a linha do tempo de
todo contato está vazia", com a origem já dropada.

Semeamos `client_events` parando na 0068 e só então aplicamos a 0069: migração sobre tabela
vazia é indistinguível de migração no-op, que é o bug que este arquivo existe para pegar.

Marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job `cross-tenant-rls` do CI
ou manualmente com Docker (`pytest -m rls_e2e`).
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
    """Aplica migrations como `e1p_app`, parando na revisão pedida."""
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


# (kind antigo, created_at, kind esperado em `facts`)
SEMENTES = [
    ("lead_created", "2026-07-01", "crm.lead.criado"),
    ("stage_move", "2026-07-20", "crm.etapa.movida"),
    ("note", "2026-07-25", "crm.nota.criada"),
    # Um kind fora do de-para NÃO pode sumir: cai num rótulo honesto em vez de virar NULL.
    ("kind_desconhecido", "2026-07-28", "crm.evento.kind_desconhecido"),
]


@pytest.fixture(scope="module")
def ambiente():
    """Sobe Postgres, migra até 0068, SEMEIA `client_events`, e só então aplica a 0069."""
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
        _run_migrations_as_app(app_url, "0068")

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        engine = create_engine(app_url, poolclass=NullPool)
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_a}
            )
            client_id = str(uuid4())
            conn.execute(
                text(
                    "INSERT INTO clients (id, tenant_id, name, gender, notes, tags, "
                    "source, created_at, updated_at) VALUES "
                    "(:id, :t, 'Flavio Kato', 'unspecified', '', '[]'::json, 'landing', "
                    "'2026-07-01', '2026-07-01')"
                ),
                {"id": client_id, "t": tenant_a},
            )
            for kind, quando, _esperado in SEMENTES:
                conn.execute(
                    text(
                        "INSERT INTO client_events (id, tenant_id, client_id, kind, "
                        "title, body, actor, is_ai, created_at, updated_at) VALUES "
                        "(:id, :t, :c, :k, :titulo, '', 'teste', false, :quando, :quando)"
                    ),
                    {
                        "id": str(uuid4()), "t": tenant_a, "c": client_id,
                        "k": kind, "titulo": f"evento {kind}", "quando": quando,
                    },
                )
        engine.dispose()

        # AGORA a 0069 — a migração de dados encontra linhas de verdade.
        _run_migrations_as_app(app_url, "0069")

        yield {"url": app_url, "tenant_a": tenant_a, "tenant_b": tenant_b, "client": client_id}


def test_migracao_nao_foi_no_op(ambiente):
    """Se a janela de RLS sumisse, `facts` viria VAZIA — e o deploy não reclamaria."""
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            linhas = conn.execute(
                text("SELECT module, kind, occurred_at, origin, subject_type, client_id "
                     "FROM facts ORDER BY occurred_at")
            ).fetchall()

        assert len(linhas) == len(SEMENTES), f"migração foi no-op: {linhas}"
        assert [linha.kind for linha in linhas] == [esperado for _k, _q, esperado in SEMENTES]
        assert all(linha.module == "crm" for linha in linhas)
        assert all(linha.origin == "emitted" for linha in linhas)
        assert all(linha.subject_type == "client" for linha in linhas)
        assert all(linha.client_id == ambiente["client"] for linha in linhas)
        # `occurred_at` herdou o `created_at` do evento antigo — melhor sinal disponível para
        # um registro que nunca soube distinguir "aconteceu" de "foi gravado".
        assert all(linha.occurred_at is not None for linha in linhas)
    finally:
        engine.dispose()


def test_client_events_foi_dropada(ambiente):
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            existe = conn.execute(text("SELECT to_regclass('public.client_events')")).scalar()
        assert existe is None
    finally:
        engine.dispose()


def test_rls_fail_closed_sem_guc(ambiente):
    """Sem a GUC do tenant, `facts` não devolve linha nenhuma."""
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            total = conn.execute(text("SELECT count(*) FROM facts")).scalar()
        assert total == 0
    finally:
        engine.dispose()


def test_isolamento_cross_tenant(ambiente):
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_b"]},
            )
            total = conn.execute(text("SELECT count(*) FROM facts")).scalar()
        assert total == 0
    finally:
        engine.dispose()
