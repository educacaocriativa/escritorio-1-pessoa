"""Teste e2e de isolamento cross-tenant no Postgres REAL (Story 3.2, AC2).

Fecha a dívida técnica do CLAUDE.md#6.1 ("RLS é Postgres-only; os testes unitários usam
SQLite e não a exercem... TODO: automatizar com testcontainers no CI") e valida a Regra de
Ouro nº 1 (CLAUDE.md#3): "João não vê dados da Maria".

Por que este teste roda como `e1p_app` (papel NÃO-superusuário) e NÃO como o superuser do
container: superusuários IGNORAM Row-Level Security (mesmo com FORCE). Se o teste rodasse as
migrations/queries como superuser, ele "passaria" sem validar nada de real — um falso-positivo
perigoso, o oposto do que a IV3 pede. Por isso `e1p_app` é o DONO das tabelas (roda as
migrations), exatamente como em produção (infra/docker-compose.prod.yml → serviço api conecta
como `postgresql+psycopg://e1p_app:...`).

Marcado inteiro com `rls_e2e`: NÃO roda no `pytest -q` padrão (a suíte SQLite in-memory), só no
job dedicado `cross-tenant-rls` do CI (.github/workflows/ci.yml) ou manualmente com Docker.

[AUTO-DECISION] Usa engine SQLAlchemy "crua" (criada da URL do container) em vez de reusar
`app.db.session.tenant_session`: o `tenant_session` está ligado a um engine module-level preso
a `settings.database_url` no import — reapontá-lo para a URL efêmera do container exigiria
monkeypatch de estado global compartilhado, arriscando vazar para outros testes do mesmo
processo. Uma engine local ao teste é mais segura e auditável (é teste, não código de produção).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

# Se testcontainers não estiver instalado (ex.: coleta no job test-in-prod-image, onde este
# teste é deselecionado por marker), pula o módulo em vez de quebrar a coleta. No job
# cross-tenant-rls o pacote está em requirements.txt, então o import prossegue normalmente.
pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

# Credenciais efêmeras do container de teste (não são segredos de produção).
_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"

_API_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_rls_role(super_url: str) -> None:
    """Replica infra/docker/initdb/01-rls-enforce.sql: cria o papel e1p_app NÃO-superusuário
    e concede privilégios. Roda como o superuser do container (bootstrap único, como em prod)."""
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER")
            )
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _run_migrations_as_app(app_url: str) -> None:
    """Roda `alembic upgrade head` com a connection string do papel e1p_app — assim e1p_app
    vira DONO das tabelas (fiel a produção). env.py lê `settings.database_url`, então apontamos
    o singleton para a URL do container antes de invocar o comando."""
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        # script_location absoluto: alembic resolve o relativo pela cwd, que varia entre runners.
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original_url


def _insert_audit(app_url: str, tenant_id: str, actor: str) -> None:
    """Insere uma linha em audit_entries (tabela com RLS) para um tenant, setando a GUC de
    sessão ANTES do INSERT — mesmo padrão de app.db.session.tenant_session (set_config,
    is_local=false). NullPool garante backend novo/limpo por conexão (sem GUC vazando)."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_id},
            )
            conn.execute(
                text(
                    "INSERT INTO audit_entries (id, tenant_id, actor, action) "
                    "VALUES (:id, :tid, :actor, 'created')"
                ),
                {"id": str(uuid4()), "tid": tenant_id, "actor": actor},
            )
            conn.commit()
    finally:
        engine.dispose()


def _actors_visible(app_url: str, tenant_id: str | None) -> list[str]:
    """Lê audit_entries pela ótica de e1p_app. Se tenant_id for None, NÃO seta a GUC (simula
    sessão sem tenant → a RLS deve retornar zero linhas, fail-closed). NullPool = backend novo,
    portanto a GUC começa genuinamente não-setada."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            rows = conn.execute(text("SELECT actor FROM audit_entries")).scalars().all()
            return sorted(rows)
    finally:
        engine.dispose()


def _actors_as_superuser(super_url: str) -> list[str]:
    """Lê audit_entries como o superuser do container — superusuários fazem BYPASS de RLS
    (mesmo com FORCE), então enxergam as linhas de TODOS os tenants. É exatamente por isso que
    a app NUNCA pode usar esse papel (Regra de Ouro nº 1)."""
    engine = create_engine(super_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT actor FROM audit_entries")).scalars().all()
            return sorted(rows)
    finally:
        engine.dispose()


def test_cross_tenant_isolation_joao_nao_ve_maria() -> None:
    """João não vê dados da Maria — no Postgres real, com RLS FORCE, rodando como e1p_app."""
    with PostgresContainer(
        "postgres:16-alpine",
        username=_ROOT_USER,
        password=_ROOT_PASS,
        dbname=_DB_NAME,
        driver="psycopg",  # casa com psycopg[binary] do requirements (não psycopg2)
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        # Bootstrap idêntico a produção: papel NÃO-superusuário + migrations rodadas por ele.
        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url)

        # Dois tenants sintéticos, uma linha de audit cada (gravada com a GUC do próprio tenant).
        joao_tenant = str(uuid4())
        maria_tenant = str(uuid4())
        _insert_audit(app_url, joao_tenant, "joao")
        _insert_audit(app_url, maria_tenant, "maria")

        # Assert 1 — cenário nomeado: com a GUC do João, só a linha do João aparece.
        assert _actors_visible(app_url, joao_tenant) == ["joao"], (
            "RLS falhou: com o tenant do João setado, dados da Maria vazaram"
        )
        # E o simétrico, para não passar por acaso.
        assert _actors_visible(app_url, maria_tenant) == ["maria"], (
            "RLS falhou: com o tenant da Maria setado, dados do João vazaram"
        )

        # Assert 2 — fail-closed: sem GUC setada, a query retorna ZERO linhas (não todas).
        # (current_setting('app.current_tenant_id', true) => NULL => nenhuma linha visível.)
        assert _actors_visible(app_url, None) == [], (
            "RLS não é fail-closed: sem tenant setado deveria retornar zero linhas"
        )

        # Assert 3 — o superuser do container faz BYPASS de RLS e vê AS DUAS linhas. Documenta
        # por que a app precisa rodar como e1p_app (non-superuser), nunca como o superuser.
        assert _actors_as_superuser(super_url) == ["joao", "maria"], (
            "superuser deveria enxergar as duas linhas (bypass de RLS)"
        )
