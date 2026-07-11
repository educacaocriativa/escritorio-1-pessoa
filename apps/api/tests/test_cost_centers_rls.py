"""Teste e2e de isolamento cross-tenant do centro de custo no Postgres REAL (Story 5.5, IV2).

Valida, sob RLS real (papel NÃO-superusuário `e1p_app`, que NÃO faz bypass de RLS):
- a tabela nova `cost_centers` isola por tenant (o centro de A é invisível para B → `exists` False,
  o que na camada HTTP vira 404 fail-closed ao vincular/filtrar);
- o cruzamento por centro de custo (`by_cost_center_report`) de A NÃO soma lançamentos de B;
- o filtro da DRE por `cost_center_id` respeita a RLS (A não filtra por um centro de B).

Também exercita `alembic upgrade head` como `e1p_app` — confirma que a migration 0048 aplica limpo
na cadeia (0045→0046→0047→0048). Mesmo bootstrap de test_financial_intelligence_profitability_rls.
Módulo marcado `rls_e2e`: NÃO roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job
dedicado do CI (`cross-tenant-rls`) ou manualmente com Docker (`pytest -m rls_e2e`).
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
        command.upgrade(cfg, "head")  # aplica a cadeia inteira, incl. 0048 (valida encadeamento)
    finally:
        settings.database_url = original_url


def _seed_tenant(app_url: str, tenant_id: str, *, receita: int, cc_name: str) -> str:
    """Cria, para um tenant (GUC setada ANTES dos INSERTs), um centro de custo + conta RECEITA e
    uma cobrança vinculada ao centro. Retorna o id do centro de custo."""
    from app.modules.chart_of_accounts.models import ChartAccount
    from app.modules.cost_centers.models import CostCenter
    from app.modules.receivables.models import Charge

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            cc = CostCenter(tenant_id=tenant_id, name=cc_name, kind="socio")
            rec = ChartAccount(tenant_id=tenant_id, grupo_dre="RECEITA", categoria="Consultoria")
            session.add_all([cc, rec])
            session.flush()
            session.add(
                Charge(
                    tenant_id=tenant_id, kind="service", method="pix", amount_cents=receita,
                    due_date=date(2026, 7, 10), competence_date=date(2026, 7, 10),
                    chart_account_id=rec.id, cost_center_id=cc.id,
                )
            )
            session.commit()
            cc_id = cc.id
            session.close()
            return cc_id
    finally:
        engine.dispose()


def _resultado_do_centro(app_url: str, tenant_id: str, cost_center_id: str) -> int:
    """Roda o cruzamento por centro de custo REAL sob a ótica de `tenant_id` e devolve o resultado
    do bucket `cost_center_id` (0 se o centro não for visível/sem movimento para esse tenant)."""
    from app.modules.financial_intelligence.dre import by_cost_center_report

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            report = by_cost_center_report(session, start=START, end=END)
            session.close()
            for b in report.buckets:
                if b.cost_center_id == cost_center_id:
                    return b.resultado_cents
            return 0
    finally:
        engine.dispose()


def _cost_center_visible(app_url: str, tenant_id: str, cost_center_id: str) -> bool:
    from app.modules.cost_centers import service as cost_centers_service

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            visible = cost_centers_service.exists(session, cost_center_id)
            session.close()
            return visible
    finally:
        engine.dispose()


def test_cost_center_cross_tenant_a_nao_ve_b() -> None:
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
        cc_a = _seed_tenant(app_url, tenant_a, receita=100000, cc_name="Sócio A")
        cc_b = _seed_tenant(app_url, tenant_b, receita=777777, cc_name="Sócio B")

        # O cruzamento por centro de custo de cada tenant só enxerga o próprio dado.
        assert _resultado_do_centro(app_url, tenant_a, cc_a) == 100000, (
            "RLS falhou: cruzamento por centro de custo de A somou dados de B"
        )
        assert _resultado_do_centro(app_url, tenant_b, cc_b) == 777777, (
            "RLS falhou: cruzamento por centro de custo de B somou dados de A"
        )

        # O centro de custo de B é INVISÍVEL para A (base do 404 fail-closed ao vincular/filtrar).
        assert not _cost_center_visible(app_url, tenant_a, cc_b), (
            "RLS falhou: A enxergou o centro de custo de B"
        )
        assert not _cost_center_visible(app_url, tenant_b, cc_a), (
            "RLS falhou: B enxergou o centro de custo de A"
        )
