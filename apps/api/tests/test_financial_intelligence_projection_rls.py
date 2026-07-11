"""Teste e2e de isolamento cross-tenant da projeção de caixa no Postgres REAL (Story 5.7, IV3).

"A projeção do tenant A não inclui itens em aberto (nem saldo de Carteira) do tenant B." Exercita o
SERVIÇO REAL (`cash_projection`) sob RLS, rodando como o papel NÃO-superusuário `e1p_app`
(superusuários fazem BYPASS de RLS). Diferente do teste SQLite (que não exerce RLS), aqui a
agregação roda no Postgres com a GUC de tenant fixada na sessão, sem filtro manual de `tenant_id`
(Regra de Ouro nº 1).

Mesmo padrão/bootstrap de test_financial_intelligence_dre_rls.py. Módulo marcado `rls_e2e`: NÃO roda
no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI ou manualmente com Docker
(`pytest -m rls_e2e`).
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


def _seed_tenant(
    app_url: str, tenant_id: str, *, available: int, inflow: int, outflow: int
) -> None:
    """Para um tenant (GUC setada ANTES dos INSERTs): saldo disponível na Carteira + uma cobrança e
    uma conta a pagar EM ABERTO com vencimento em +10 dias (dentro de todas as janelas)."""
    from app.modules.payables.models import Payable
    from app.modules.receivables.models import Charge
    from app.modules.wallet.models import Transaction

    due = TODAY + timedelta(days=10)
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            session.add(
                Transaction(
                    tenant_id=tenant_id, kind="service", method="pix",
                    gross_cents=available, platform_fee_cents=0, net_cents=available,
                    status="available",
                )
            )
            session.add(
                Charge(
                    tenant_id=tenant_id, kind="service", method="pix", amount_cents=inflow,
                    due_date=due, status="open",
                )
            )
            session.add(
                Payable(
                    tenant_id=tenant_id, description="conta", amount_cents=outflow,
                    due_date=due, status="open",
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()


def _project(app_url: str, tenant_id: str | None) -> dict:
    """Roda a projeção REAL sob a ótica de `tenant_id` (None = sem GUC → RLS fail-closed)."""
    from app.modules.financial_intelligence.projection import cash_projection

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            result = cash_projection(session)
            session.close()
            return {
                "saldo_inicial_cents": result.saldo_inicial_cents,
                "w30": result.windows[0].saldo_projetado_cents,
            }
    finally:
        engine.dispose()


def test_projection_cross_tenant_a_nao_ve_b() -> None:
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
        # A: disponível 100000, entrada 50000, saída 30000 → w30 = 120000
        _seed_tenant(app_url, tenant_a, available=100000, inflow=50000, outflow=30000)
        # B: valores bem diferentes — não podem vazar para A
        _seed_tenant(app_url, tenant_b, available=777777, inflow=1, outflow=999999)

        a = _project(app_url, tenant_a)
        assert a["saldo_inicial_cents"] == 100000, "RLS falhou: saldo do A somou Carteira do B"
        assert a["w30"] == 120000, "RLS falhou: projeção do A incluiu itens do B"

        b = _project(app_url, tenant_b)
        assert b["saldo_inicial_cents"] == 777777, "RLS falhou: saldo do B somou Carteira do A"
        assert b["w30"] == 777777 + 1 - 999999

        # Fail-closed: sem GUC de tenant, a agregação enxerga ZERO linhas.
        blind = _project(app_url, None)
        assert blind["saldo_inicial_cents"] == 0 and blind["w30"] == 0, (
            "RLS não é fail-closed: sem tenant setado a projeção deveria ver zero"
        )
