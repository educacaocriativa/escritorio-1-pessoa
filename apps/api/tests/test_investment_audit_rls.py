"""O script de auditoria do principal, no Postgres REAL e sob RLS (Onda 2b-ii).

**Por que este teste existe, e por que ele não podia ser em SQLite.** A Onda 2b-ii trocou o backfill
do design-mãe §6.2 — o único `UPDATE` sobre dado existente do épico — por *auditoria + ato do dono*.
Trocar escrita por leitura só é seguro se a leitura de fato **enxergar**: uma consulta em tabela com
`FORCE ROW LEVEL SECURITY` **sem** a GUC de tenant devolve **zero linhas, sem erro**, e o silêncio
fica indistinguível de "está tudo certo". Foi assim que a sondagem de `phone_key` em produção quase
virou um "está tudo limpo" falso.

Os testes SQLite de `auditar()` (em `test_investments_principal.py`) provam a aritmética da
comparação e nada mais — **RLS não é exercida lá** (ver `conftest.py`). O que se prova aqui é a
outra metade, que é a que pode falhar em silêncio:

1. `_tenant_ids()` enxerga a tabela GLOBAL `tenants` (ela não tem RLS — mesma exceção de `users`);
2. `auditar()` dentro de `tenant_session` vê as aplicações **daquele** tenant;
3. e **não** vê as do outro (se visse, o script reportaria divergência de terceiro);
4. sem GUC, a leitura é **fail-closed** — zero linhas, que é exatamente o resultado que o script
   nunca pode confundir com aprovação, e por isso `main()` imprime a contagem de tenants varridos.

Módulo marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job `cross-tenant-rls` do CI
ou manualmente com Docker (`pytest -m rls_e2e`).
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
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original_url


def _seed(app_url: str, *, slug: str, aplicacao: str, abertura: int, coluna: int) -> str:
    """Um tenant com uma aplicação vinculada a uma conta de aplicação. Devolve o `tenant_id`.

    `abertura` vira o principal DERIVADO (é o saldo de abertura da conta); `coluna` é gravado em
    `principal_cents`, a coluna congelada. Os dois são diferentes de propósito: é a divergência que
    o script existe para reportar.
    """
    from app.modules.auth.models import Tenant
    from app.modules.bank.models import KIND_INVESTMENT, BankAccount
    from app.modules.investments.models import InvestmentAccount

    tenant_id = str(uuid4())
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()  # fixa a GUC (escopo de sessão) e encerra a txn — ver a nota do
            # test_financial_intelligence_diagnostics_rls sobre o SAVEPOINT.
            session = Session(bind=conn)
            session.add(
                Tenant(id=tenant_id, slug=slug, legal_name=slug, document=f"{slug}-doc")
            )
            conta = BankAccount(
                tenant_id=tenant_id,
                name=f"{aplicacao} (conta)",
                kind=KIND_INVESTMENT,
                opening_balance_cents=abertura,
                opening_balance_is_known=True,
                opening_date=date(2026, 1, 1),
            )
            session.add(conta)
            session.flush()  # o id tem default Python-side
            session.add(
                InvestmentAccount(
                    tenant_id=tenant_id,
                    name=aplicacao,
                    principal_cents=coluna,
                    opened_at=date(2026, 1, 1),
                    bank_account_id=conta.id,
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()
    return tenant_id


def _auditar_como(app_url: str, tenant_id: str | None) -> list[dict]:
    from app.scripts.investment_audit import auditar

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            linhas = auditar(session)
            session.close()
            return linhas
    finally:
        engine.dispose()


def test_a_auditoria_enxerga_o_proprio_tenant_e_nao_o_vizinho() -> None:
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

        a = _seed(app_url, slug="tenant-a", aplicacao="CDB-DO-A", abertura=10_000_00, coluna=777_77)
        b = _seed(app_url, slug="tenant-b", aplicacao="CDB-DO-B", abertura=20_000_00, coluna=0)

        # (1) e (2) — o tenant A vê a aplicação dele, com a divergência real
        linhas_a = _auditar_como(app_url, a)
        assert [linha["name"] for linha in linhas_a] == ["CDB-DO-A"]
        assert linhas_a[0]["coluna_cents"] == 777_77
        assert linhas_a[0]["derivado_cents"] == 10_000_00, (
            "o principal derivado veio do saldo de abertura da conta, sob RLS real"
        )
        assert linhas_a[0]["diverge"] is True

        # (3) — e não vê a do vizinho. Se visse, o script mandaria o dono de A caçar um lançamento
        # que é de B, que é o modo de falha que o épico chama de "pior do que ficar calado".
        assert "CDB-DO-B" not in {linha["name"] for linha in linhas_a}

        linhas_b = _auditar_como(app_url, b)
        assert [linha["name"] for linha in linhas_b] == ["CDB-DO-B"]
        assert "CDB-DO-A" not in {linha["name"] for linha in linhas_b}

        # (4) — sem GUC: ZERO linhas, sem erro. **É este silêncio que o `main()` do script não pode
        # confundir com aprovação**, e é por isso que ele imprime a contagem de tenants varridos.
        assert _auditar_como(app_url, None) == []
