"""Teste e2e de isolamento cross-tenant da DRE por contrato no Postgres REAL (Story 5.4, IV3).

"A DRE do contrato do tenant A não inclui lançamentos do tenant B, e o contrato de B é invisível
para A." Exercita o SERVIÇO REAL (`profitability.contract_dre`) sob RLS, rodando como o papel
NÃO-superusuário `e1p_app` (superusuários fazem BYPASS de RLS). Herda o RLS de
`contracts`/`payables`/`charges` — não há tabela nova a testar isoladamente (o vínculo é
`contract_id` nas tabelas já existentes).

Mesmo padrão/bootstrap de test_financial_intelligence_dre_rls.py. Módulo marcado `rls_e2e`: NÃO
roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI ou manualmente
com Docker (`pytest -m rls_e2e`).
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


def _seed_tenant(app_url: str, tenant_id: str, *, receita: int, custo: int) -> str:
    """Cria, para um tenant (GUC setada ANTES dos INSERTs), um Contract + contas RECEITA/CUSTO e
    um lançamento de cada vinculado ao contrato. Retorna o id do contrato."""
    from app.modules.chart_of_accounts.models import ChartAccount
    from app.modules.contracts.models import Contract
    from app.modules.payables.models import Payable
    from app.modules.receivables.models import Charge

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            contract = Contract(tenant_id=tenant_id, title="Projeto", clauses=[])
            rec = ChartAccount(tenant_id=tenant_id, grupo_dre="RECEITA", categoria="Consultoria")
            cst = ChartAccount(tenant_id=tenant_id, grupo_dre="CUSTO_DIRETO", categoria="Insumos")
            session.add_all([contract, rec, cst])
            session.flush()
            session.add(
                Charge(
                    tenant_id=tenant_id, kind="service", method="pix", amount_cents=receita,
                    due_date=date(2026, 7, 10), competence_date=date(2026, 7, 10),
                    chart_account_id=rec.id, contract_id=contract.id,
                )
            )
            session.add(
                Payable(
                    tenant_id=tenant_id, description="insumo", amount_cents=custo,
                    due_date=date(2026, 7, 5), competence_date=date(2026, 7, 5),
                    chart_account_id=cst.id, contract_id=contract.id,
                )
            )
            session.commit()
            contract_id = contract.id
            session.close()
            return contract_id
    finally:
        engine.dispose()


def _margem(app_url: str, tenant_id: str, contract_id: str) -> int:
    """Roda a DRE do contrato REAL sob a ótica de `tenant_id`."""
    from app.modules.contracts.models import Contract
    from app.modules.financial_intelligence.profitability import contract_dre

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            contract = session.get(Contract, contract_id)
            assert contract is not None
            report = contract_dre(session, contract=contract, start=START, end=END)
            session.close()
            return report.margem_contribuicao_cents
    finally:
        engine.dispose()


def _contract_visible(app_url: str, tenant_id: str, contract_id: str) -> bool:
    from app.modules.contracts.models import Contract

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            session = Session(bind=conn)
            visible = session.get(Contract, contract_id) is not None
            session.close()
            return visible
    finally:
        engine.dispose()


def test_contract_dre_cross_tenant_a_nao_ve_b() -> None:
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
        # A: receita 100000, custo 40000 → margem 60000
        contract_a = _seed_tenant(app_url, tenant_a, receita=100000, custo=40000)
        # B: receita 777777, custo 7777 → margem 770000 (não pode vazar para A)
        contract_b = _seed_tenant(app_url, tenant_b, receita=777777, custo=7777)

        assert _margem(app_url, tenant_a, contract_a) == 60000, (
            "RLS falhou: DRE do contrato de A somou dados do B"
        )
        assert _margem(app_url, tenant_b, contract_b) == 770000, (
            "RLS falhou: DRE do contrato de B somou dados do A"
        )

        # O contrato de B é INVISÍVEL para A (RLS esconde a linha → 404 na camada HTTP).
        assert not _contract_visible(app_url, tenant_a, contract_b), (
            "RLS falhou: A enxergou o contrato de B"
        )
