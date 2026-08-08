"""Teste e2e de isolamento cross-tenant da conta de investimento no Postgres REAL (Story 5.6, IV2).

Valida, sob RLS real (papel NÃO-superusuário `e1p_app`, que NÃO faz bypass de RLS):
- a tabela nova `investment_accounts` isola por tenant (a conta de A é invisível para B → `get`
  None, o que na camada HTTP vira 404 fail-closed);
- a rentabilidade calculada sob a ótica de cada tenant só enxerga os rendimentos do próprio tenant
  (os lançamentos `Charge external_ref='investment:<id>'` de B não vazam para A).

Também exercita `alembic upgrade head` como `e1p_app` — confirma que a migration 0049 aplica limpo
na cadeia (0045→…→0048→0049). Mesmo bootstrap de test_cost_centers_rls.
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
        command.upgrade(cfg, "head")  # aplica a cadeia inteira, incl. 0049 (valida encadeamento)
    finally:
        settings.database_url = original_url


def _seed_tenant(app_url: str, tenant_id: str, *, principal: int, yield_cents: int) -> str:
    """Cria, para um tenant (GUC setada ANTES dos INSERTs), uma conta FINANCEIRO + uma conta de
    investimento e registra um rendimento (via o service real). Retorna o id da conta de
    investimento."""
    from app.modules.chart_of_accounts.models import ChartAccount
    from app.modules.investments import service as inv_service
    from app.modules.investments.models import InvestmentAccount

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
            rend = ChartAccount(
                tenant_id=tenant_id, grupo_dre="FINANCEIRO", categoria="Rendimento de aplicação"
            )
            acc = InvestmentAccount(
                tenant_id=tenant_id, name="CDB", kind="CDB", index_rate_label="CDI",
                principal_cents=principal, accrued_yield_cents=0, opened_at=date(2026, 1, 10),
            )
            session.add_all([rend, acc])
            session.flush()
            inv_service.register_yield(
                session, account_id=acc.id, tenant_id=tenant_id, actor="seed",
                amount_cents=yield_cents, date=date(2026, 7, 10), chart_account_id=rend.id,
            )
            acc_id = acc.id
            session.close()
            return acc_id
    finally:
        engine.dispose()


def _rentability_under(app_url: str, tenant_id: str, account_id: str) -> dict | None:
    """Roda `rentability` REAL sob a ótica de `tenant_id`. Devolve None se a conta não for visível
    (RLS esconde → get None → InvestmentError 404)."""
    from app.modules.investments import service as inv_service

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
            try:
                return inv_service.rentability(session, account_id=account_id)
            except inv_service.InvestmentError:
                return None
            finally:
                session.close()
    finally:
        engine.dispose()


def _bank_account_for(app_url: str, tenant_id: str) -> str:
    """Cria uma `bank_account` `kind='investment'` para o tenant. Devolve o id."""
    from app.modules.bank.models import BankAccount

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            acc = BankAccount(
                tenant_id=tenant_id, name="CDB Itaú", kind="investment", number="",
                opening_balance_cents=0, opening_balance_is_known=True,
                opening_date=date(2026, 1, 1),
            )
            session.add(acc)
            session.commit()
            acc_id = acc.id
            session.close()
            return acc_id
    finally:
        engine.dispose()


def _tentar_vincular(app_url: str, tenant_id: str, inv_id: str, bank_id: str) -> int | None:
    """Tenta vincular sob a ótica de `tenant_id`. Devolve o `status_code` do erro, ou None se
    o vínculo foi aceito."""
    from app.modules.investments import service as inv_service
    from app.modules.investments.schemas import InvestmentAccountUpdate

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                inv_service.update_account(
                    session, account_id=inv_id, tenant_id=tenant_id, actor="teste",
                    data=InvestmentAccountUpdate(bank_account_id=bank_id),
                )
                return None
            except inv_service.InvestmentError as e:
                return e.status_code
            finally:
                session.close()
    finally:
        engine.dispose()


def test_vincular_a_conta_bancaria_de_OUTRO_tenant_da_404_e_NUNCA_409() -> None:
    """A conta existe — no tenant B. Para o tenant A ela **não existe**, e a resposta é 404.

    **409 aqui confirmaria a existência da linha alheia**: seria vazamento de existência com cara
    de validação. É o mesmo critério já fixado em `bank_service.get_account`, e o que a 8.2 pagou
    para aprender.

    ⚠️ **Só o Postgres reproduz.** No SQLite da suíte unitária a linha do tenant B é visível, o
    vínculo seria ACEITO, e o teste equivalente lá (`test_conta_bancaria_inexistente_da_404...`)
    passa por outro motivo — ele usa um id que não existe em lugar nenhum.
    """
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
        _run_migrations_as_app(app_url)  # aplica a cadeia inteira, incl. a 0075

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        inv_a = _seed_tenant(app_url, tenant_a, principal=1_000_000, yield_cents=10_000)
        bank_b = _bank_account_for(app_url, tenant_b)

        # CONTROLE POSITIVO: a própria conta de A é aceita — sem isto, um 404 universal
        # (por bug na validação) passaria como se fosse isolamento funcionando.
        bank_a = _bank_account_for(app_url, tenant_a)
        assert _tentar_vincular(app_url, tenant_a, inv_a, bank_a) is None, (
            "a conta do PRÓPRIO tenant tem de ser aceita — senão o 404 abaixo não prova nada"
        )

        assert _tentar_vincular(app_url, tenant_a, inv_a, bank_b) == 404, (
            "RLS falhou, ou o erro virou 409: A não pode nem saber que a conta de B existe"
        )


def test_investment_cross_tenant_a_nao_ve_b() -> None:
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
        acc_a = _seed_tenant(app_url, tenant_a, principal=1_000_000, yield_cents=10_000)
        acc_b = _seed_tenant(app_url, tenant_b, principal=2_000_000, yield_cents=77_000)

        # Cada tenant só enxerga o próprio rendimento.
        ra = _rentability_under(app_url, tenant_a, acc_a)
        rb = _rentability_under(app_url, tenant_b, acc_b)
        assert ra is not None and ra["accrued_yield_cents"] == 10_000, (
            "RLS falhou: rentabilidade de A não bateu (vazou de B?)"
        )
        assert rb is not None and rb["accrued_yield_cents"] == 77_000, (
            "RLS falhou: rentabilidade de B não bateu (vazou de A?)"
        )

        # A conta de investimento de B é INVISÍVEL para A (base do 404 fail-closed).
        assert _rentability_under(app_url, tenant_a, acc_b) is None, (
            "RLS falhou: A enxergou a conta de investimento de B"
        )
        assert _rentability_under(app_url, tenant_b, acc_a) is None, (
            "RLS falhou: B enxergou a conta de investimento de A"
        )
