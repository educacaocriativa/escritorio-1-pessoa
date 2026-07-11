"""Teste e2e de isolamento cross-tenant do plano de contas no Postgres REAL (Story 5.1, IV2/AC).

"João não vê o plano de contas da Maria." Valida a Regra de Ouro nº 1 (CLAUDE.md#3) sobre a
tabela nova `chart_accounts`, rodando como o papel NÃO-superusuário `e1p_app` (superusuários
fazem BYPASS de RLS, mesmo com FORCE — por isso a app nunca usa esse papel).

Mesmo padrão de test_rls_isolation.py: engine SQLAlchemy "crua" da URL do container (sem reusar o
`tenant_session` module-level, que está preso a settings.database_url no import). Módulo inteiro
marcado `rls_e2e`: NÃO roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado
`cross-tenant-rls` do CI ou manualmente com Docker (`pytest -m rls_e2e`).
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


def _insert_account(app_url: str, tenant_id: str, grupo: str, categoria: str) -> str:
    """Insere uma categoria do plano de contas para um tenant, com a GUC de sessão setada ANTES
    do INSERT (mesmo padrão de tenant_session: set_config is_local=false). NullPool = backend
    limpo por conexão (sem GUC vazando). Retorna o id gerado."""
    acc_id = str(uuid4())
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_id},
            )
            conn.execute(
                text(
                    "INSERT INTO chart_accounts (id, tenant_id, grupo_dre, categoria) "
                    "VALUES (:id, :tid, :grupo, :categoria)"
                ),
                {"id": acc_id, "tid": tenant_id, "grupo": grupo, "categoria": categoria},
            )
            conn.commit()
    finally:
        engine.dispose()
    return acc_id


def _categorias_visible(app_url: str, tenant_id: str | None) -> list[str]:
    """Lista categorias visíveis pela ótica de e1p_app. tenant_id=None → NÃO seta a GUC (a RLS
    deve devolver zero linhas, fail-closed)."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            rows = conn.execute(text("SELECT categoria FROM chart_accounts")).scalars().all()
            return sorted(rows)
    finally:
        engine.dispose()


def _account_visible_by_id(app_url: str, tenant_id: str, acc_id: str) -> bool:
    """Simula o acesso direto por id (rota PATCH/archive → db.get): com a GUC do tenant B, a linha
    do tenant A não deve ser encontrada (→ 404 fail-closed, não 403)."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_id},
            )
            row = conn.execute(
                text("SELECT id FROM chart_accounts WHERE id = :id"), {"id": acc_id}
            ).first()
            return row is not None
    finally:
        engine.dispose()


def test_cross_tenant_chart_accounts_joao_nao_ve_maria() -> None:
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

        joao_tenant = str(uuid4())
        maria_tenant = str(uuid4())
        # João cria "Consultoria" em RECEITA; Maria cria "Aluguel" em DESPESA_FIXA.
        joao_acc = _insert_account(app_url, joao_tenant, "RECEITA", "Consultoria")
        _insert_account(app_url, maria_tenant, "DESPESA_FIXA", "Aluguel")

        # Cada tenant só vê a sua própria categoria (list — GET /chart-of-accounts).
        assert _categorias_visible(app_url, joao_tenant) == ["Consultoria"], (
            "RLS falhou: com o tenant do João, o plano de contas da Maria vazou"
        )
        assert _categorias_visible(app_url, maria_tenant) == ["Aluguel"], (
            "RLS falhou: com o tenant da Maria, o plano de contas do João vazou"
        )

        # Acesso direto por id: Maria NÃO acha a "Consultoria" do João (→ 404 fail-closed).
        assert _account_visible_by_id(app_url, maria_tenant, joao_acc) is False, (
            "RLS falhou: Maria acessou a categoria do João por id direto"
        )
        # ...mas o próprio João acha (sanidade: a RLS não bloqueia o dono).
        assert _account_visible_by_id(app_url, joao_tenant, joao_acc) is True

        # Fail-closed: sem GUC setada, a query retorna ZERO linhas (não todas).
        assert _categorias_visible(app_url, None) == [], (
            "RLS não é fail-closed: sem tenant setado deveria retornar zero linhas"
        )
