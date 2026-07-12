"""Teste e2e de isolamento cross-tenant da DRE no Postgres REAL (Story 5.3, IV2).

"A DRE do tenant A não inclui lançamentos do tenant B." Exercita o SERVIÇO REAL (`dre_report`)
sob RLS, rodando como o papel NÃO-superusuário `e1p_app` (superusuários fazem BYPASS de RLS —
por isso a app nunca usa esse papel). Diferente do teste SQLite (que não exerce RLS), aqui a
agregação `GROUP BY` roda no Postgres com a GUC de tenant fixada na sessão, sem nenhum filtro
manual de `tenant_id` (Regra de Ouro nº 1).

Mesmo padrão/bootstrap de test_chart_of_accounts_rls.py. Módulo marcado `rls_e2e`: NÃO roda no
`pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI ou manualmente com Docker
(`pytest -m rls_e2e`).
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


def _seed_tenant(app_url: str, tenant_id: str, *, receita: int, despesa: int) -> None:
    """Cria, para um tenant (com a GUC setada ANTES dos INSERTs), uma conta de RECEITA + uma de
    DESPESA e um lançamento em cada (via ORM, para herdar os defaults das colunas)."""
    from app.modules.chart_of_accounts.models import ChartAccount
    from app.modules.payables.models import Payable
    from app.modules.receivables.models import Charge

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()  # fixa a GUC (escopo de sessão) e ENCERRA a txn: sem isso a Session
            # ligada a uma conexão já em transação usa join por SAVEPOINT e o session.commit()
            # só libera o savepoint — a txn externa (com o seed) é revertida no close. Mesmo
            # padrão da produção em app/db/session.py::tenant_session.
            session = Session(bind=conn)
            rec = ChartAccount(tenant_id=tenant_id, grupo_dre="RECEITA", categoria="Consultoria")
            desp = ChartAccount(tenant_id=tenant_id, grupo_dre="DESPESA_FIXA", categoria="Aluguel")
            session.add_all([rec, desp])
            session.flush()
            session.add(
                Charge(
                    tenant_id=tenant_id, kind="service", method="pix", amount_cents=receita,
                    due_date=date(2026, 7, 10), competence_date=date(2026, 7, 10),
                    chart_account_id=rec.id,
                )
            )
            session.add(
                Payable(
                    tenant_id=tenant_id, description="aluguel", amount_cents=despesa,
                    due_date=date(2026, 7, 5), competence_date=date(2026, 7, 5),
                    chart_account_id=desp.id,
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()


def _resultado(app_url: str, tenant_id: str | None) -> int:
    """Roda a DRE REAL sob a ótica de `tenant_id` (None = sem GUC → RLS fail-closed)."""
    from app.modules.financial_intelligence.dre import dre_report

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            report = dre_report(session, start=START, end=END)
            session.close()
            return report.resultado_cents
    finally:
        engine.dispose()


def _receita_consultoria(app_url: str, tenant_id: str) -> int:
    from app.modules.financial_intelligence.dre import dre_report

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()  # fixa a GUC (escopo de sessão) e ENCERRA a txn: sem isso a Session
            # ligada a uma conexão já em transação usa join por SAVEPOINT e o session.commit()
            # só libera o savepoint — a txn externa (com o seed) é revertida no close. Mesmo
            # padrão da produção em app/db/session.py::tenant_session.
            session = Session(bind=conn)
            report = dre_report(session, start=START, end=END)
            session.close()
            receita = next(g for g in report.groups if g.grupo_dre == "RECEITA")
            return receita.total_cents
    finally:
        engine.dispose()


def test_dre_cross_tenant_a_nao_ve_b() -> None:
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
        # A: receita 100000, despesa 40000 → resultado 60000
        _seed_tenant(app_url, tenant_a, receita=100000, despesa=40000)
        # B: receita 777777, despesa 7777 → resultado 770000 (não pode vazar para A)
        _seed_tenant(app_url, tenant_b, receita=777777, despesa=7777)

        assert _resultado(app_url, tenant_a) == 60000, "RLS falhou: DRE do A somou dados do B"
        assert _resultado(app_url, tenant_b) == 770000, "RLS falhou: DRE do B somou dados do A"

        # A receita do A é só a dele (não 100000 + 777777).
        assert _receita_consultoria(app_url, tenant_a) == 100000, (
            "RLS falhou: a receita da Consultoria do A incluiu a cobrança do B"
        )

        # Fail-closed: sem GUC de tenant, a agregação enxerga ZERO linhas → resultado 0.
        assert _resultado(app_url, None) == 0, (
            "RLS não é fail-closed: sem tenant setado a DRE deveria somar zero"
        )
