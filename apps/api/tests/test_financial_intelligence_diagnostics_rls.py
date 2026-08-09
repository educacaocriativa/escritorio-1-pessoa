"""Teste e2e de isolamento cross-tenant do DIAGNÓSTICO no Postgres REAL (Story 5.8, IV3).

"O diagnóstico do tenant A não vê dados (investimentos/contratos/caixa) do tenant B." Exercita a
orquestração REAL (`diagnostics.compute_signals`, que por baixo chama projeção 5.7, lucratividade
5.4 e rentabilidade 5.6 — todas RLS-scoped) rodando como o papel NÃO-superusuário `e1p_app`. A RLS
é a ÚNICA garantia de isolamento (Regra de Ouro nº 1); aqui provamos que os sinais de A citam só a
aplicação de A e nunca a de B.

Mesmo padrão/bootstrap de test_financial_intelligence_projection_rls.py. Marcado `rls_e2e`: NÃO roda
no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI ou `pytest -m rls_e2e`.
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


def _seed_investment(app_url: str, tenant_id: str, *, name: str, principal: int) -> None:
    """Uma aplicação com principal > 0 e sem rendimento → gera o sinal 🟡 'sem rendimento no
    período', cuja explicação cita o NOME da aplicação (o vetor de vazamento que testamos).

    ⚠️ **Onda 2b-ii: o principal vem da CONTA BANCÁRIA vinculada**, então esta fixture semeia as
    duas linhas — a `bank_account` `kind='investment'` com `opening_balance_cents = principal`, e a
    `investment_accounts` apontando para ela. Semear só a segunda deixaria o principal derivado em
    `None`, `period_rentability_pct` em `None`, e a regra 4 do motor não avaliaria nada: o teste
    ficaria **verde por vacuidade**, sem nenhum sinal citando nome de aplicação — ou seja, sem o
    vetor de vazamento que ele existe para exercitar. A coluna `principal_cents` continua sendo
    escrita aqui **de propósito**: é o valor congelado, e o teste prova que ele NÃO é o que aparece.
    """
    from app.modules.bank.models import KIND_INVESTMENT, BankAccount
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
            conta = BankAccount(
                tenant_id=tenant_id,
                name=f"{name} (conta)",
                kind=KIND_INVESTMENT,
                opening_balance_cents=principal,
                opening_balance_is_known=True,
                opening_date=date(2026, 6, 1),
            )
            session.add(conta)
            session.flush()  # o id tem default Python-side; sem isto o vínculo nasceria vazio
            session.add(
                InvestmentAccount(
                    tenant_id=tenant_id, name=name, principal_cents=principal,
                    opened_at=date(2026, 6, 1), bank_account_id=conta.id,
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()


def _seed_bank_account(
    app_url: str, tenant_id: str, *, name: str, opening: int, declarado: int
) -> None:
    """Uma conta bancária com saldo declarado divergente → sinal 🔴 de completude (Story 8.6),
    cuja explicação cita o NOME DA CONTA — o vetor de vazamento novo que esta story introduz.

    O nome da conta é PII pelo mesmo critério de `MarginTrend.project_name`: ele viaja na
    explicação do sinal e só é anonimizado pelo narrador na saída para o Claude. Se a RLS falhar,
    o sintoma não é "vi uma linha do vizinho" — é o diagnóstico de A **acusando um furo** medido
    contra a verdade externa de B."""
    from app.modules.bank.models import (
        KIND_CHECKING,
        ORIGIN_MANUAL,
        BankAccount,
        BankBalanceCheckpoint,
    )

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()  # ver a nota de `_seed_investment`: fixa a GUC e encerra a txn.
            session = Session(bind=conn)
            account = BankAccount(
                tenant_id=tenant_id,
                name=name,
                kind=KIND_CHECKING,
                opening_balance_cents=opening,
                opening_balance_is_known=True,
                opening_date=START,
            )
            session.add(account)
            session.flush()
            session.add(
                BankBalanceCheckpoint(
                    tenant_id=tenant_id,
                    bank_account_id=account.id,
                    reference_date=date(2026, 7, 20),
                    balance_cents=declarado,
                    origin=ORIGIN_MANUAL,
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()


def _diagnose(app_url: str, tenant_id: str | None) -> list[tuple[str, str]]:
    """Roda o diagnóstico REAL sob a ótica de `tenant_id` (None = sem GUC → RLS fail-closed).
    Retorna [(level, explanation), ...]."""
    from app.modules.financial_intelligence import diagnostics

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            signals = diagnostics.compute_signals(session, start=START, end=END)
            session.close()
            return [(s.level, s.explanation) for s in signals]
    finally:
        engine.dispose()


def test_diagnostics_cross_tenant_a_nao_ve_b() -> None:
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
        _seed_investment(app_url, tenant_a, name="Aplicacao-DO-A", principal=100000)
        _seed_investment(app_url, tenant_b, name="Aplicacao-DO-B", principal=200000)

        a_signals = _diagnose(app_url, tenant_a)
        a_text = " ".join(exp for _lvl, exp in a_signals)
        assert "Aplicacao-DO-A" in a_text, "diagnóstico de A deveria citar a aplicação de A"
        assert "Aplicacao-DO-B" not in a_text, "RLS falhou: A viu a aplicação do B"

        b_signals = _diagnose(app_url, tenant_b)
        b_text = " ".join(exp for _lvl, exp in b_signals)
        assert "Aplicacao-DO-B" in b_text
        assert "Aplicacao-DO-A" not in b_text, "RLS falhou: B viu a aplicação do A"

        # Fail-closed: sem GUC de tenant, o motor não recebe dado de negócio nenhum. O único sinal
        # possível é o 🟡 de completude "nenhuma conta bancária cadastrada" (Story 8.6) — que é o
        # comportamento correto: sem tenant o sistema não vê conta nenhuma e DIZ que não sabe.
        sem_tenant = _diagnose(app_url, None)
        assert all(lvl == "amarelo" for lvl, _exp in sem_tenant), sem_tenant
        assert all("Nenhuma conta bancária cadastrada" in exp for _lvl, exp in sem_tenant), (
            f"RLS não é fail-closed: sem tenant vazou algum dado de negócio: {sem_tenant}"
        )


def test_diagnostics_completude_cross_tenant_nao_vaza_nome_de_conta() -> None:
    """Story 8.6 / IV5 — o sinal de completude de A não cita a conta bancária de B.

    A completude é o primeiro sinal do diagnóstico a nomear uma entidade do módulo `bank`. Como o
    isolamento é RLS e só RLS (Regra de Ouro nº 1 — nenhum filtro manual de `tenant_id` em
    `reconciliation_report` nem em `diagnostics._completeness`), um vazamento aqui apareceria como
    um 🔴 acusando um furo de R$ X medido contra o saldo declarado do vizinho.
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
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        # Divergência de R$ 1.200 em A e de R$ 900 em B — as duas MUITO acima da banda (R$ 50).
        _seed_bank_account(
            app_url, tenant_a, name="Conta-DO-A", opening=1_000_000, declarado=1_120_000
        )
        _seed_bank_account(
            app_url, tenant_b, name="Conta-DO-B", opening=1_000_000, declarado=910_000
        )

        a_signals = _diagnose(app_url, tenant_a)
        a_text = " ".join(exp for _lvl, exp in a_signals)
        assert "Conta-DO-A" in a_text, "o diagnóstico de A deveria nomear a conta de A"
        assert "R$ 1.200,00" in a_text
        assert "Conta-DO-B" not in a_text, "RLS falhou: A viu a conta bancária do B"
        assert "R$ 900,00" not in a_text, "RLS falhou: A viu a divergência do B"

        b_signals = _diagnose(app_url, tenant_b)
        b_text = " ".join(exp for _lvl, exp in b_signals)
        assert "Conta-DO-B" in b_text and "R$ 900,00" in b_text
        assert "Conta-DO-A" not in b_text, "RLS falhou: B viu a conta bancária do A"


def _seed_onda2(
    app_url: str,
    tenant_id: str,
    *,
    conta: str,
    fornecedor: str,
    valor: int,
    declarado_a_mais: int,
) -> None:
    """Story 8.16 (IV6) — o cenário das DUAS regras novas, com PII dos dois lados.

    Monta, para um tenant:
      - uma conta bancária com um débito de `valor` já lançado (o movimento existe, e portanto o
        saldo derivado já o subtraiu);
      - um `Payable` pago do mesmo tamanho, com o **nome do fornecedor** (PII) e a conta informada;
      - um checkpoint declarando o saldo `valor` ACIMA do derivado → `divergencia = +valor`, que é
        exatamente o que o débito suspeito explica;
      - uma `Charge` recebida **direto na conta do dono**, que alimenta o *"N dos M"*.

    Os dois vetores de vazamento desta story são o **nome do fornecedor** (na explicação do débito
    suspeito) e o **nome da conta**. Se a RLS falhar, o sintoma não é "vi uma linha do vizinho": é o
    diagnóstico de A **nomeando um débito de B** como suspeito de um furo medido contra a verdade
    externa de B.

    ⚠️ A baixa e o recebimento passam pelos **serviços reais** (`payables.mark_paid` e
    `receivables.settle_off_rail`), e não por `INSERT` à mão: é assim que o `bank_transaction`
    nasce com o `dedup_hash`/`source`/`origin_id` corretos, e é o caminho que a produção percorre.
    Um seed que monta a linha do plano 3 na mão testaria um estado que o produto não produz.
    """
    from app.modules.bank.models import (
        KIND_CHECKING,
        ORIGIN_MANUAL,
        BankAccount,
        BankBalanceCheckpoint,
    )
    from app.modules.crm.models import Client
    from app.modules.payables import service as payables_service
    from app.modules.payables.models import Payable
    from app.modules.receivables import service as receivables_service
    from app.modules.receivables.models import Charge

    debito_em = date(2026, 7, 10)
    ator = f"dono-{tenant_id[:8]}@example.com"
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_id},
            )
            conn.commit()  # ver a nota de `_seed_investment`: fixa a GUC e encerra a txn.
            session = Session(bind=conn)
            account = BankAccount(
                tenant_id=tenant_id,
                name=conta,
                kind=KIND_CHECKING,
                opening_balance_cents=1_000_000,
                opening_balance_is_known=True,
                opening_date=START,
            )
            cliente = Client(tenant_id=tenant_id, name="Cliente Pix")
            payable = Payable(
                tenant_id=tenant_id,
                description="Despesa do mes",
                category="operacional",
                supplier=fornecedor,
                amount_cents=valor,
                due_date=debito_em,
            )
            session.add_all([account, cliente, payable])
            session.flush()
            charge = Charge(
                tenant_id=tenant_id,
                client_id=cliente.id,
                description="Consultoria",
                amount_cents=140_000,
                due_date=debito_em,
                method="pix",
                kind="service",
            )
            session.add(charge)
            session.commit()

            # O caminho REAL: a baixa gera o movimento bancário (Regra da Origem, Story 8.9/8.12) e
            # o recebimento fora da cobrança do e1p também (Story 8.15).
            payables_service.mark_paid(
                session,
                payable_id=payable.id,
                tenant_id=tenant_id,
                actor=ator,
                bank_account_id=account.id,
                paid_on=debito_em,
            )
            receivables_service.settle_off_rail(
                session,
                charge_id=charge.id,
                tenant_id=tenant_id,
                actor=ator,
                bank_account_id=account.id,
                received_on=debito_em,
            )

            session.add(
                BankBalanceCheckpoint(
                    tenant_id=tenant_id,
                    bank_account_id=account.id,
                    reference_date=date(2026, 7, 20),
                    # O banco ainda nao executou o debito ⇒ o dono declara o saldo `valor` acima do
                    # que o e1p calculou, e é isso que o débito suspeito explica.
                    balance_cents=1_000_000 - valor + 140_000 + declarado_a_mais,
                    origin=ORIGIN_MANUAL,
                )
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()


def test_iv6_debito_suspeito_e_recebimento_externo_nao_vazam_entre_tenants() -> None:
    """Story 8.16 / IV6 — as duas regras novas, cross-tenant, no Postgres REAL.

    O isolamento e RLS e so RLS (Regra de Ouro no 1): nem `diagnostics._debitos_suspeitos` nem
    `diagnostics._off_rail` filtram `tenant_id` a mao. Este teste e o que prova que isso basta —
    e o que pega o vazamento de PII pela porta nova: o **nome do fornecedor** viaja na explicacao
    do sinal, exatamente como `MarginTrend.project_name` sempre viajou.
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
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        _seed_onda2(
            app_url, tenant_a, conta="Conta-DO-A", fornecedor="Fornecedor-DO-A",
            valor=500_000, declarado_a_mais=500_000,
        )
        _seed_onda2(
            app_url, tenant_b, conta="Conta-DO-B", fornecedor="Fornecedor-DO-B",
            valor=300_000, declarado_a_mais=300_000,
        )

        a_signals = _diagnose(app_url, tenant_a)
        a_text = " ".join(exp for _lvl, exp in a_signals)
        assert "Fornecedor-DO-A" in a_text, "o debito de A deveria nomear o fornecedor de A"
        assert "pode nao ter saido" in a_text.replace("ã", "a").replace("í", "i")
        assert "Fornecedor-DO-B" not in a_text, "RLS falhou: A viu o fornecedor do B"
        assert "Conta-DO-B" not in a_text, "RLS falhou: A viu a conta bancaria do B"
        assert "R$ 3.000,00" not in a_text, "RLS falhou: A viu a divergencia do B"
        # E o "N dos M" de A conta so os recebimentos de A (1 de 1), nunca os dois tenants.
        assert "1 dos 1 recebimentos" in a_text

        b_signals = _diagnose(app_url, tenant_b)
        b_text = " ".join(exp for _lvl, exp in b_signals)
        assert "Fornecedor-DO-B" in b_text and "Conta-DO-B" in b_text
        assert "Fornecedor-DO-A" not in b_text, "RLS falhou: B viu o fornecedor do A"
        assert "R$ 5.000,00" not in b_text, "RLS falhou: B viu a divergencia do A"
        assert "1 dos 1 recebimentos" in b_text
