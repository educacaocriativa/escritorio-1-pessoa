"""Isolamento cross-tenant de `bank_accounts` no Postgres REAL (Story 8.2, AC9).

Valida, sob RLS real (papel NÃO-superusuário `e1p_app` — superusuário faz bypass **mesmo com
FORCE**, `CLAUDE.md` Regra de Ouro nº 1):

- **leitura:** o tenant A não lista nem lê a conta do tenant B (`db.get` → None → 404 fail-closed);
- **escrita:** `INSERT` com `tenant_id` alheio é barrado pelo `WITH CHECK` da policy;
- **edição/arquivamento:** A não consegue editar nem arquivar a conta de B (a linha nem existe
  para ele);
- **fail-closed sem GUC:** sem `app.current_tenant_id` a leitura devolve ZERO linhas — o estado
  seguro é "não vejo nada", nunca "vejo tudo";
- **saldo derivado por conta:** o saldo que cada tenant apura é o dele (é o número que a Story 8.5
  vai comparar com o extrato — vazamento aqui seria uma divergência inexplicável no relatório).

Também exercita `alembic upgrade head` como `e1p_app`, o que confirma que a migration **0058**
aplica limpo na cadeia (…→0057→0058) — incluindo o índice único PARCIAL, que o SQLite dos testes
unitários cria com outro dialeto.

⚠️ **Este arquivo é o ponto de extensão das Stories 8.3 e 8.4** (`bank_transactions` e
`bank_balance_checkpoints`): acrescente casos AQUI em vez de criar mais um arquivo de
testcontainer — cada boot de Postgres custa minutos de CI, e as três tabelas compartilham o mesmo
bootstrap.

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
from sqlalchemy.exc import ProgrammingError  # noqa: E402
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
        command.upgrade(cfg, "head")  # aplica a cadeia inteira, incl. 0058 (valida encadeamento)
    finally:
        settings.database_url = original_url


def _session_for(app_url: str, tenant_id: str | None):
    """Contexto de sessão com (ou SEM) a GUC de tenant fixada — espelha `db/session.py`.

    `tenant_id=None` deixa a GUC ausente de propósito: é o cenário fail-closed.
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        engine = create_engine(app_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                if tenant_id is not None:
                    conn.execute(
                        text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                        {"tid": tenant_id},
                    )
                conn.commit()  # fixa a GUC (escopo de SESSÃO) e ENCERRA a txn: sem isso a Session
                # ligada a uma conexão já em transação usa join por SAVEPOINT e o session.commit()
                # só libera o savepoint — a txn externa é revertida no close. Mesmo padrão da
                # produção em app/db/session.py::tenant_session.
                session = Session(bind=conn)
                try:
                    yield session
                finally:
                    session.close()
        finally:
            engine.dispose()

    return _ctx()


def _seed_account(app_url: str, tenant_id: str, *, name: str, opening: int, number: str) -> str:
    from app.modules.bank.models import BankAccount

    with _session_for(app_url, tenant_id) as session:
        acc = BankAccount(
            tenant_id=tenant_id,
            name=name,
            kind="checking",
            institution="Banco Teste",
            institution_code="341",
            branch="0001",
            number=number,
            opening_balance_cents=opening,
            opening_date=date(2026, 7, 1),
            is_primary=True,
        )
        session.add(acc)
        session.commit()
        return acc.id


def test_bank_account_isolamento_cross_tenant() -> None:
    from app.modules.bank import service as bank_service
    from app.modules.bank.models import BankAccount
    from app.modules.bank.schemas import BankAccountUpdate

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
        # MESMA identidade bancária nos dois tenants: o índice único é GLOBAL e não respeita RLS,
        # então isto só passa porque `tenant_id` é a PRIMEIRA coluna da constraint (design §2.1).
        # Sem isso, B receberia um 409 inexplicável por causa de um dado de A — bug E vazamento
        # de existência.
        acc_a = _seed_account(app_url, tenant_a, name="A", opening=100_000, number="55555-5")
        acc_b = _seed_account(app_url, tenant_b, name="B", opening=777_000, number="55555-5")

        # ── Leitura: cada um só enxerga o próprio ────────────────────────────────────────────
        with _session_for(app_url, tenant_a) as sa:
            visiveis = [a.id for a in bank_service.list_accounts(sa)]
            assert visiveis == [acc_a], f"RLS falhou: A enxergou {visiveis}"
            assert sa.get(BankAccount, acc_b) is None, "RLS falhou: A leu a conta de B"
            with pytest.raises(bank_service.BankError) as exc:
                bank_service.get_account(sa, acc_b)
            assert exc.value.status_code == 404, "cross-tenant deve ser 404 fail-closed, não 403"
            # O saldo derivado apurado por A é o de A — é o número que a 8.5 vai conferir.
            assert bank_service.derived_balance(sa, bank_account_id=acc_a) == 100_000
            assert bank_service.derived_balances_as_of(sa) == {acc_a: 100_000}

        with _session_for(app_url, tenant_b) as sb:
            assert [a.id for a in bank_service.list_accounts(sb)] == [acc_b]
            assert bank_service.derived_balance(sb, bank_account_id=acc_b) == 777_000

        # ── Edição/arquivamento: A não alcança a linha de B ──────────────────────────────────
        with _session_for(app_url, tenant_a) as sa:
            for call in (
                lambda: bank_service.update_account(
                    sa, account_id=acc_b, tenant_id=tenant_a, actor="a",
                    data=BankAccountUpdate(name="invadida"),
                ),
                lambda: bank_service.archive_account(
                    sa, account_id=acc_b, tenant_id=tenant_a, actor="a"
                ),
            ):
                with pytest.raises(bank_service.BankError) as exc:
                    call()
                assert exc.value.status_code == 404

        with _session_for(app_url, tenant_b) as sb:
            conta_b = sb.get(BankAccount, acc_b)
            assert conta_b.name == "B" and conta_b.archived_at is None, (
                "RLS falhou: A conseguiu modificar a conta de B"
            )

        # ── Escrita com tenant_id alheio: barrada pelo WITH CHECK ────────────────────────────
        with _session_for(app_url, tenant_a) as sa:
            sa.add(
                BankAccount(
                    tenant_id=tenant_b,  # ← o ataque: gravar dentro do tenant do vizinho
                    name="Plantada por A",
                    kind="checking",
                    opening_balance_cents=1,
                    opening_date=date(2026, 7, 1),
                )
            )
            with pytest.raises(ProgrammingError):
                sa.commit()
            sa.rollback()

        with _session_for(app_url, tenant_b) as sb:
            assert [a.id for a in bank_service.list_accounts(sb)] == [acc_b], (
                "WITH CHECK falhou: A plantou uma conta no tenant de B"
            )

        # ── Sem GUC: fail-closed (zero linhas, nunca todas) ──────────────────────────────────
        with _session_for(app_url, None) as sn:
            assert bank_service.list_accounts(sn) == [], (
                "FAIL-CLOSED falhou: sem `app.current_tenant_id` a leitura devolveu linhas. O "
                "estado seguro é não ver nada."
            )
            assert sn.get(BankAccount, acc_a) is None
