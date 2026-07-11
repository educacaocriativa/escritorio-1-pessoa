"""Teste e2e de isolamento cross-tenant da Fila de Pagamentos no Postgres REAL (Story 5.9, IV2).

"A fila do tenant A não mostra Payables do tenant B." Exercita o SERVIÇO REAL (`payment_queue`)
sob RLS, rodando como o papel NÃO-superusuário `e1p_app` (superusuários fazem BYPASS de RLS).
Diferente do teste SQLite (que não exerce RLS), aqui a agregação roda no Postgres com a GUC de
tenant fixada na sessão, sem filtro manual de `tenant_id` (Regra de Ouro nº 1) — a fila não tem
tabela nova, herda a RLS de `payables`.

Mesmo padrão/bootstrap de test_financial_intelligence_projection_rls.py. Módulo marcado `rls_e2e`:
NÃO roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI ou manualmente
com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from datetime import date, timedelta
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

TODAY = date.today()


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


def _seed_open_payable(app_url: str, tenant_id: str, *, amount: int, days: int) -> None:
    """Conta a pagar EM ABERTO do tenant (GUC setada ANTES do INSERT), vencendo em +`days` dias."""
    from app.modules.payables.models import Payable

    due = TODAY + timedelta(days=days)
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            session.add(
                Payable(
                    tenant_id=tenant_id, description="conta", amount_cents=amount,
                    due_date=due, status="open",
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()


def _queue_amounts(app_url: str, tenant_id: str | None) -> list[int]:
    """Roda a fila REAL sob a ótica de `tenant_id` (None = sem GUC → RLS fail-closed) e devolve os
    valores (centavos) de TODOS os baldes, ordenados — para comparar sem depender do balde exato."""
    from app.modules.payables.service import payment_queue

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            q = payment_queue(session, tenant_id=tenant_id or "")
            session.close()
            items = [*q.atrasados, *q.hoje, *q.proximos_7_dias, *q.proximos_30_dias]
            return sorted(p.amount_cents for p in items)
    finally:
        engine.dispose()


def test_payment_queue_cross_tenant_a_nao_ve_b() -> None:
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
        # A: duas contas próprias (dentro das janelas da fila)
        _seed_open_payable(app_url, tenant_a, amount=11100, days=0)
        _seed_open_payable(app_url, tenant_a, amount=22200, days=5)
        # B: valores bem diferentes — não podem vazar para a fila do A
        _seed_open_payable(app_url, tenant_b, amount=99999, days=1)

        assert _queue_amounts(app_url, tenant_a) == [11100, 22200], (
            "RLS falhou: a fila do A incluiu Payables do B"
        )
        assert _queue_amounts(app_url, tenant_b) == [99999], (
            "RLS falhou: a fila do B incluiu Payables do A"
        )

        # Fail-closed: sem GUC de tenant, a fila enxerga ZERO linhas (não todas).
        assert _queue_amounts(app_url, None) == [], (
            "RLS não é fail-closed: sem tenant setado a fila deveria ver zero"
        )
