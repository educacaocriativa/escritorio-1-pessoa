"""Isolamento cross-tenant do ledger de uso de IA no Postgres REAL (Regra de Ouro nº 1).

O ledger é uma tabela de custo: se ela vazasse entre tenants, um cliente veria quanto outro
gasta com IA e em quais funcionalidades — perfil de uso do negócio alheio. Vale a mesma RLS
`FORCE` de qualquer tabela de negócio, e este teste é o que a prova sob o papel NÃO-superusuário
`e1p_app` (que não faz bypass).

Cobre:
- `ai_usage.record` grava sob a ótica de cada tenant e **nenhum enxerga a linha do outro**;
- a mesma leitura vista pelo tenant DONO devolve a linha — o controle positivo que prova que a
  asserção negativa falha pelo motivo certo, e não por dado ausente/id errado;
- sem a GUC de tenant a tabela é **fail-closed** (zero linhas), não aberta.

Mesmo bootstrap dos demais `*_rls.py`: engine SQLAlchemy cru da URL do container, migrations
aplicadas com `alembic upgrade head` como `e1p_app` — o que também exercita a migration 0071 de
fato. Módulo marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job dedicado do CI
(`cross-tenant-rls`) ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, select, text  # noqa: E402
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
def _tenant_session(app_url: str, tenant_id: str | None):
    """Sessão com a GUC de tenant fixada antes de qualquer query. `tenant_id=None` abre a sessão
    SEM a GUC — é assim que se testa o fail-closed."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
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


def _record(app_url: str, *, tenant_id: str, task: str, model: str) -> str:
    """Grava um uso de IA pelo caminho REAL (`ai_usage.record`), sob a ótica do tenant dono."""
    from app.core import ai_usage

    with _tenant_session(app_url, tenant_id) as session:
        uso = ai_usage.record(
            session, tenant_id=tenant_id, task=task, model=model,
            input_tokens=100, output_tokens=200,
        )
        assert uso is not None, "record() devolveu None — falhou ao gravar sob o tenant dono"
        session.commit()
        return uso.id


def _tasks_visiveis(app_url: str, tenant_id: str | None) -> list[str]:
    from app.core.ai_usage import AIUsage

    with _tenant_session(app_url, tenant_id) as session:
        return list(session.scalars(select(AIUsage.task).order_by(AIUsage.task)).all())


def _consegue_ler_por_id(app_url: str, *, viewer_tenant_id: str, usage_id: str) -> bool:
    from app.core.ai_usage import AIUsage

    with _tenant_session(app_url, viewer_tenant_id) as session:
        return session.get(AIUsage, usage_id) is not None


def test_ai_usage_cross_tenant_isolation() -> None:
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
        tenant_b = str(uuid4())

        uso_a = _record(app_url, tenant_id=tenant_a, task="juridico.documento",
                        model="claude-opus-5")
        uso_b = _record(app_url, tenant_id=tenant_b, task="vima.briefing",
                        model="claude-haiku-4-5")

        # ── Caso 1: cada tenant vê só o próprio consumo ───────────────────────────────────────
        assert _tasks_visiveis(app_url, tenant_a) == ["juridico.documento"], (
            "RLS falhou: A enxergou consumo de IA que não é dele"
        )
        assert _tasks_visiveis(app_url, tenant_b) == ["vima.briefing"], (
            "RLS falhou: B enxergou consumo de IA que não é dele"
        )

        # ── Caso 2: leitura direta por id também é barrada ────────────────────────────────────
        # O controle POSITIVO (o dono lê o próprio) é o que prova que a asserção negativa não
        # está passando por id errado ou linha inexistente.
        assert _consegue_ler_por_id(app_url, viewer_tenant_id=tenant_a, usage_id=uso_a) is True
        assert _consegue_ler_por_id(app_url, viewer_tenant_id=tenant_b, usage_id=uso_b) is True
        assert _consegue_ler_por_id(app_url, viewer_tenant_id=tenant_a, usage_id=uso_b) is False, (
            "RLS falhou: A leu por id a linha de consumo de B"
        )
        assert _consegue_ler_por_id(app_url, viewer_tenant_id=tenant_b, usage_id=uso_a) is False, (
            "RLS falhou: B leu por id a linha de consumo de A"
        )

        # ── Caso 3: sem GUC de tenant, fail-closed (zero linhas, não a tabela toda) ───────────
        assert _tasks_visiveis(app_url, None) == [], (
            "RLS não é fail-closed: sessão sem tenant enxergou o ledger"
        )
