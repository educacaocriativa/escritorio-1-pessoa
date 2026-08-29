"""Isolamento cross-tenant de `vima/tools.executar` no Postgres REAL (Regra de Ouro nº 1).

`consultar_cliente` é a ferramenta que mais convida a vazar: ela recebe um NOME livre digitado
pela Claude, e é exatamente esse tipo de busca por texto que testaria o filtro errado (um
`ilike` sem `tenant_id` explícito) se alguém "otimizasse" a query por engano. A garantia real é
a mesma RLS de sempre — este teste prova que a ferramenta não abre uma segunda porta.

Mesmo bootstrap dos demais `*_rls.py`: engine SQLAlchemy cru da URL do container, migrations
aplicadas com `alembic upgrade head` como `e1p_app`. Módulo marcado `rls_e2e`: NÃO roda no
`pytest -q` (suíte SQLite), só no job dedicado do CI (`cross-tenant-rls`) ou manualmente com
Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
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
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_id},
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


def _criar_cliente(app_url: str, *, tenant_id: str, nome: str) -> str:
    from app.modules.crm.models import Client

    with _tenant_session(app_url, tenant_id) as session:
        cliente = Client(tenant_id=tenant_id, name=nome, source="manual")
        session.add(cliente)
        session.commit()
        return cliente.id


def _consultar_cliente(app_url: str, *, tenant_id: str, nome: str) -> dict:
    import json

    from app.core.tenancy import CurrentUser
    from app.modules.vima import tools

    usuario = CurrentUser(user_id="u1", tenant_id=tenant_id, role="owner", allowed_modules=[])
    with _tenant_session(app_url, tenant_id) as session:
        resultado = tools.executar(session, usuario, "consultar_cliente", {"nome": nome})
        return json.loads(resultado)


def test_consultar_cliente_isola_por_tenant() -> None:
    with PostgresContainer(
        "postgres:16-alpine", username=_ROOT_USER, password=_ROOT_PASS, dbname=_DB_NAME,
        driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        _criar_cliente(app_url, tenant_id=tenant_a, nome="Maria Fernandes")
        _criar_cliente(app_url, tenant_id=tenant_b, nome="Maria Fernandes")

        # Cada tenant pede pelo MESMO nome — se a RLS falhar, um veria o cliente do outro.
        resultado_a = _consultar_cliente(app_url, tenant_id=tenant_a, nome="Maria")
        resultado_b = _consultar_cliente(app_url, tenant_id=tenant_b, nome="Maria")

        assert len(resultado_a["clientes"]) == 1, "RLS falhou: A viu 0 ou >1 clientes"
        assert len(resultado_b["clientes"]) == 1, "RLS falhou: B viu 0 ou >1 clientes"
        assert resultado_a["clientes"][0]["id"] != resultado_b["clientes"][0]["id"], (
            "RLS falhou: os dois tenants viram o MESMO cliente"
        )
        # Controle positivo: cada tenant realmente encontra o PRÓPRIO cliente — não é lista
        # vazia dos dois lados escondendo uma RLS aberta demais.
        assert resultado_a["clientes"][0]["nome"] == "Maria Fernandes"
        assert resultado_b["clientes"][0]["nome"] == "Maria Fernandes"
