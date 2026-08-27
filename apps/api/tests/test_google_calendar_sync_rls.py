"""Confirma o índice único da migration 0081 contra Postgres REAL — SQLite não distingue um
índice parcial mal escrito (`sqlite_where` por engano em vez de `postgresql_where`) de um
correto; os dois passam no `db` fixture em memória e só o Postgres real prova a sintaxe.

Mesmo bootstrap de test_receipts_rls.py: engine "cru" da URL do container, migrations aplicadas
com `alembic upgrade head` como `e1p_app`. Marcado `rls_e2e`: NÃO roda no `pytest -q`, só no job
`cross-tenant-rls` do CI ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
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


def _run_migrations_as_app(app_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original_url


@contextmanager
def _tenant_session(app_url: str, tenant_id: str):
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


def test_google_event_id_unique_index_enforced_on_real_postgres() -> None:
    from app.modules.agenda.models import AgendaEvent

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
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        with _tenant_session(app_url, tenant_a) as session:
            session.add(
                AgendaEvent(
                    tenant_id=tenant_a,
                    title="Um",
                    kind="google",
                    starts_at=datetime(2026, 9, 10, 10, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 9, 10, 11, 0, tzinfo=UTC),
                    google_event_id="pg-dup",
                )
            )
            session.commit()

            session.add(
                AgendaEvent(
                    tenant_id=tenant_a,
                    title="Dois",
                    kind="google",
                    starts_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
                    ends_at=datetime(2026, 9, 11, 11, 0, tzinfo=UTC),
                    google_event_id="pg-dup",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
