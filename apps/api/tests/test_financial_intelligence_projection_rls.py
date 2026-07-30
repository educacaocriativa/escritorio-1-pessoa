"""Teste e2e de isolamento cross-tenant da projeção de caixa no Postgres REAL (Story 5.7, IV3).

"A projeção do tenant A não inclui itens em aberto (nem saldo de Carteira) do tenant B." Exercita o
SERVIÇO REAL (`cash_projection`) sob RLS, rodando como o papel NÃO-superusuário `e1p_app`
(superusuários fazem BYPASS de RLS). Diferente do teste SQLite (que não exerce RLS), aqui a
agregação roda no Postgres com a GUC de tenant fixada na sessão, sem filtro manual de `tenant_id`
(Regra de Ouro nº 1).

**Story 8.8 (IV6) — extensão ADITIVA:** desde a Onda 1 o saldo inicial soma também a parcela
**bancária** (plano 3, `bank_accounts` + `bank_transactions`), o que traz uma superfície nova de
vazamento cross-tenant: a projeção do tenant A **nunca** pode somar saldo de conta do tenant B.
Cada tenant do teste passa a ter conta bancária com movimento, e as parcelas (`banco`/`plataforma`)
são conferidas separadamente — conferir só o total esconderia uma compensação entre as duas.

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
    app_url: str,
    tenant_id: str,
    *,
    available: int,
    inflow: int,
    outflow: int,
    bank_opening: int,
    bank_movement: int,
) -> None:
    """Para um tenant (GUC setada ANTES dos INSERTs): saldo disponível na Carteira + uma cobrança e
    uma conta a pagar EM ABERTO com vencimento em +10 dias (dentro de todas as janelas) + uma
    **conta bancária** com um movimento (Story 8.8 — a parcela do plano 3)."""
    from app.modules.bank.models import KIND_CHECKING, BankAccount, BankTransaction
    from app.modules.payables.models import Payable
    from app.modules.receivables.models import Charge
    from app.modules.wallet.models import Transaction

    due = TODAY + timedelta(days=10)
    abertura = TODAY - timedelta(days=30)
    conta_id = str(uuid4())
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
            # Story 8.8 — a parcela BANCÁRIA (plano 3). Conta corrente (não é `investment`, senão
            # ficaria fora do caixa por design) com um movimento posterior à abertura.
            session.add(
                BankAccount(
                    id=conta_id, tenant_id=tenant_id, name="Conta do tenant",
                    kind=KIND_CHECKING, opening_balance_cents=bank_opening,
                    opening_date=abertura,
                )
            )
            session.add(
                BankTransaction(
                    tenant_id=tenant_id, bank_account_id=conta_id,
                    posted_at=TODAY - timedelta(days=1), amount_cents=bank_movement,
                    raw_description="movimento", dedup_hash=str(uuid4()), source="manual",
                    status="unmatched",
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
                # Story 8.8: as parcelas são conferidas SEPARADAS. Só o total esconderia uma
                # compensação entre os dois planos (banco vazado a mais, plataforma a menos).
                "banco": result.saldo_inicial_banco_cents,
                "plataforma": result.saldo_inicial_plataforma_cents,
                "origem": result.saldo_inicial_origem,
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
        # A: disponível 100000, entrada 50000, saída 30000, banco 200000 + 5000 → w30 = 325000
        _seed_tenant(
            app_url, tenant_a, available=100000, inflow=50000, outflow=30000,
            bank_opening=200000, bank_movement=5000,
        )
        # B: valores bem diferentes em TODOS os planos — não podem vazar para A
        _seed_tenant(
            app_url, tenant_b, available=777777, inflow=1, outflow=999999,
            bank_opening=888888, bank_movement=-333,
        )

        a = _project(app_url, tenant_a)
        assert a["plataforma"] == 100000, "RLS falhou: parcela de Carteira do A somou a do B"
        assert a["banco"] == 205000, "RLS falhou: parcela BANCÁRIA do A somou conta do B"
        assert a["saldo_inicial_cents"] == 305000
        assert a["origem"] == "misto", "com conta bancária a origem é `misto` (Story 8.8)"
        assert a["w30"] == 305000 + 50000 - 30000, "RLS falhou: projeção do A incluiu itens do B"

        b = _project(app_url, tenant_b)
        assert b["plataforma"] == 777777, "RLS falhou: parcela de Carteira do B somou a do A"
        assert b["banco"] == 888555, "RLS falhou: parcela BANCÁRIA do B somou conta do A"
        assert b["saldo_inicial_cents"] == 777777 + 888555
        assert b["w30"] == 777777 + 888555 + 1 - 999999

        # Fail-closed: sem GUC de tenant, a agregação enxerga ZERO linhas — inclusive as contas
        # bancárias, então a projeção cai no fallback `plataforma` em vez de somar o banco de
        # alguém. Uma RLS que falhasse aberta aqui daria origem `misto` com saldo de outro tenant.
        blind = _project(app_url, None)
        assert blind["saldo_inicial_cents"] == 0 and blind["w30"] == 0, (
            "RLS não é fail-closed: sem tenant setado a projeção deveria ver zero"
        )
        assert blind["banco"] == 0 and blind["plataforma"] == 0
        assert blind["origem"] == "plataforma", (
            "sem tenant a projeção não pode enxergar conta bancária nenhuma — se a origem virou "
            "`misto`, a RLS deixou uma `bank_accounts` de algum tenant visível"
        )
