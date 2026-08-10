"""Onda 3 sob Postgres REAL — a migration 0077, o isolamento e a ordem cronológica.

⚠️ **O que só este teste pega.** O SQLite da suíte unitária não tem RLS: um vazamento cross-tenant
no histórico de saques ou no crédito do extrato passaria **verde** lá. E a `0077` só é exercitada
de verdade aqui, rodando `alembic upgrade head` como o papel NÃO-superusuário `e1p_app` — o mesmo
caminho da produção.

Três coisas são validadas, e a terceira não cabe na suíte SQLite:

1. **Isolamento do histórico** — o saque de A não aparece para B, nos dois sentidos;
2. **Isolamento do razão** — o crédito `source='payout'` de A não aparece no extrato de B;
3. **A ordem cronológica de verdade** — `created_at` tem resolução de microssegundo no Postgres, e
   dois saques consecutivos ordenam corretamente. No SQLite a resolução é de segundo, então lá o
   teste afirma apenas **estabilidade** (`test_historico_tem_ordem_ESTAVEL_entre_chamadas_identicas`).

⚠️ **Os DOIS tenants sacam de verdade**, e isso não é simetria decorativa: se só A sacasse, B não
teria histórico nenhum para vazar e o teste passaria **verde por vacuidade** — sem exercitar o vetor
que ele existe para exercitar. Foi exatamente essa a armadilha do `rls_e2e` de PII da Onda 2b-ii.

Mesmo bootstrap de `test_receipts_rls.py`. Módulo marcado `rls_e2e`: NÃO roda no `pytest -q`, só no
job `cross-tenant-rls` do CI ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
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

_ABERTURA = date(2026, 1, 1)


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
def _tenant_session(app_url: str, tenant_id: str):
    """Sessão com a GUC de tenant fixada ANTES de qualquer query. Mesmo padrão do
    `test_receipts_rls.py`: `set_config(..., is_local=false)` + `commit()` para encerrar a txn."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


def _conta_principal(app_url: str, *, tenant_id: str, nome: str) -> str:
    """Cria a conta bancária do tenant. A PRIMEIRA do tenant nasce principal."""
    from app.modules.bank.models import BankAccount

    with _tenant_session(app_url, tenant_id) as session:
        acc = BankAccount(
            tenant_id=tenant_id,
            name=nome,
            kind="checking",
            opening_balance_cents=0,
            opening_balance_is_known=True,
            opening_date=_ABERTURA,
            is_primary=True,
        )
        session.add(acc)
        session.commit()
        return acc.id


def _venda(app_url: str, *, tenant_id: str, gross: int) -> None:
    """Uma venda disponível para saque, escrita direto no model (o split já aplicado)."""
    from app.modules.wallet.models import STATUS_AVAILABLE, Transaction

    with _tenant_session(app_url, tenant_id) as session:
        session.add(
            Transaction(
                tenant_id=tenant_id,
                kind="service",
                method="pix",
                description="Consulta",
                gross_cents=gross,
                platform_fee_cents=gross * 30 // 100,
                net_cents=gross - gross * 30 // 100,
                status=STATUS_AVAILABLE,
            )
        )
        session.commit()


def _saca(app_url: str, *, tenant_id: str) -> str:
    from app.modules.wallet import service as wallet_service

    with _tenant_session(app_url, tenant_id) as session:
        return wallet_service.request_payout(session, tenant_id=tenant_id, actor="u")["payout_id"]


def _historico(app_url: str, *, viewer_tenant_id: str) -> list[str]:
    from app.modules.wallet import service as wallet_service

    with _tenant_session(app_url, viewer_tenant_id) as session:
        return [p.id for p in wallet_service.list_payouts(session)]


def _movimentos_de_payout(app_url: str, *, viewer_tenant_id: str) -> list[int]:
    from app.modules.bank.models import SOURCE_PAYOUT, BankTransaction

    with _tenant_session(app_url, viewer_tenant_id) as session:
        stmt = select(BankTransaction).where(BankTransaction.source == SOURCE_PAYOUT)
        return [m.amount_cents for m in session.scalars(stmt).all()]


def test_payout_cross_tenant_isolation_e_ordem() -> None:
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
        # É AQUI que a 0077 é exercitada de verdade: como `e1p_app`, non-superuser, contra Postgres.
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())

        # Os DOIS têm conta e sacam — senão B não teria o que vazar e o teste passaria por vacuidade.
        _conta_principal(app_url, tenant_id=tenant_a, nome="Itaú de A")
        _conta_principal(app_url, tenant_id=tenant_b, nome="Nubank de B")

        _venda(app_url, tenant_id=tenant_a, gross=1_000_00)
        payout_a1 = _saca(app_url, tenant_id=tenant_a)
        _venda(app_url, tenant_id=tenant_a, gross=2_000_00)
        payout_a2 = _saca(app_url, tenant_id=tenant_a)

        _venda(app_url, tenant_id=tenant_b, gross=500_00)
        payout_b = _saca(app_url, tenant_id=tenant_b)

        # ── Caso 1: o histórico de A não contém o saque de B, e vice-versa ───────────────────
        hist_a = _historico(app_url, viewer_tenant_id=tenant_a)
        hist_b = _historico(app_url, viewer_tenant_id=tenant_b)

        assert set(hist_a) == {payout_a1, payout_a2}, (
            f"RLS falhou no histórico de saques: A enxergou {set(hist_a) - {payout_a1, payout_a2}}"
        )
        assert set(hist_b) == {payout_b}, (
            f"RLS falhou no histórico de saques: B enxergou {set(hist_b) - {payout_b}}"
        )

        # ── Caso 2: a ORDEM cronológica, que o SQLite não consegue afirmar ───────────────────
        # `created_at` tem resolução de microssegundo aqui, então dois saques consecutivos são
        # genuinamente distinguíveis no tempo — o mais novo primeiro.
        assert hist_a == [payout_a2, payout_a1], (
            "o histórico deveria vir do mais novo para o mais velho no Postgres, onde os "
            f"timestamps são distinguíveis: {hist_a}"
        )

        # ── Caso 3: o crédito no razão bancário também é isolado ─────────────────────────────
        # 30% de taxa: R$ 1.000 → R$ 700 e R$ 2.000 → R$ 1.400 em A; R$ 500 → R$ 350 em B.
        assert sorted(_movimentos_de_payout(app_url, viewer_tenant_id=tenant_a)) == [700_00, 1400_00]
        assert _movimentos_de_payout(app_url, viewer_tenant_id=tenant_b) == [350_00]
