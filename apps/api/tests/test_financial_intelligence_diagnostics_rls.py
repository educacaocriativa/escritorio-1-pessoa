"""Teste e2e de isolamento cross-tenant do DIAGNÓSTICO no Postgres REAL (Story 5.8, IV3).

"O diagnóstico do tenant A não vê dados (investimentos/contratos/caixa) do tenant B." Exercita a
orquestração REAL (`diagnostics.compute_signals`, que por baixo chama projeção 5.7, lucratividade
5.4 e rentabilidade 5.6 — todas RLS-scoped) rodando como o papel NÃO-superusuário `e1p_app`. A RLS
é a ÚNICA garantia de isolamento (Regra de Ouro nº 1); aqui provamos que os sinais de A citam só a
aplicação de A e nunca a de B.

Mesmo padrão/bootstrap de test_financial_intelligence_projection_rls.py. Marcado `rls_e2e`: NÃO roda
no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI ou `pytest -m rls_e2e`.
"""
from __future__ import annotations

from datetime import date
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

START = date(2026, 7, 1)
END = date(2026, 7, 31)


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


def _seed_investment(app_url: str, tenant_id: str, *, name: str, principal: int) -> None:
    """Uma aplicação com principal > 0 e sem rendimento → gera o sinal 🟡 'sem rendimento no
    período', cuja explicação cita o NOME da aplicação (o vetor de vazamento que testamos)."""
    from app.modules.investments.models import InvestmentAccount

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            session.add(
                InvestmentAccount(
                    tenant_id=tenant_id, name=name, principal_cents=principal,
                    opened_at=date(2026, 6, 1),
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()


def _diagnose(app_url: str, tenant_id: str | None) -> list[tuple[str, str]]:
    """Roda o diagnóstico REAL sob a ótica de `tenant_id` (None = sem GUC → RLS fail-closed).
    Retorna [(level, explanation), ...]."""
    from app.modules.financial_intelligence import diagnostics

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            signals = diagnostics.compute_signals(session, start=START, end=END)
            session.close()
            return [(s.level, s.explanation) for s in signals]
    finally:
        engine.dispose()


def test_diagnostics_cross_tenant_a_nao_ve_b() -> None:
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
        _seed_investment(app_url, tenant_a, name="Aplicacao-DO-A", principal=100000)
        _seed_investment(app_url, tenant_b, name="Aplicacao-DO-B", principal=200000)

        a_signals = _diagnose(app_url, tenant_a)
        a_text = " ".join(exp for _lvl, exp in a_signals)
        assert "Aplicacao-DO-A" in a_text, "diagnóstico de A deveria citar a aplicação de A"
        assert "Aplicacao-DO-B" not in a_text, "RLS falhou: A viu a aplicação do B"

        b_signals = _diagnose(app_url, tenant_b)
        b_text = " ".join(exp for _lvl, exp in b_signals)
        assert "Aplicacao-DO-B" in b_text
        assert "Aplicacao-DO-A" not in b_text, "RLS falhou: B viu a aplicação do A"

        # Fail-closed: sem GUC de tenant, o motor não recebe nenhum dado → nenhum sinal.
        assert _diagnose(app_url, None) == [], "RLS não é fail-closed: sem tenant deveria ver zero"
