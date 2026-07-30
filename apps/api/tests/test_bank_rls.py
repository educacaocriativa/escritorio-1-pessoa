"""Isolamento cross-tenant de `bank_accounts` (8.2), `bank_transactions` (8.3) e
`bank_balance_checkpoints` (8.4) no Postgres REAL.

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

Também exercita `alembic upgrade head` como `e1p_app`, o que confirma que as migrations **0058**,
**0059** e **0060** aplicam limpo na cadeia (…→0057→0058→0059→0060) — incluindo os índices PARCIAIS
e os únicos (dedupe de movimento e dia do checkpoint), que o SQLite dos testes unitários cria com
outro dialeto.

⚠️ **Este arquivo é o ponto de extensão do módulo `bank`**: acrescente casos AQUI em vez de criar
mais um arquivo de testcontainer — cada boot de Postgres custa minutos de CI, e as três tabelas
compartilham o mesmo bootstrap. A 8.3 e a 8.4 seguiram essa instrução (funções novas neste arquivo,
mesmo container de escopo de módulo).

Módulo marcado `rls_e2e`: NÃO roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job
dedicado do CI (`cross-tenant-rls`) ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from collections.abc import Iterator
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


@pytest.fixture(scope="module")
def app_url() -> Iterator[str]:
    """UM Postgres para o módulo inteiro, com a cadeia de migrations já aplicada como `e1p_app`.

    Escopo de MÓDULO de propósito: a Story 8.3 acrescentou uma segunda função de teste aqui e cada
    boot de testcontainer custa minutos de CI. O bootstrap (papel não-superusuário + `alembic
    upgrade head`) é idêntico para as três tabelas do módulo `bank`, então compartilhá-lo é de
    graça — o que cada teste NÃO pode compartilhar é o tenant, e por isso todos usam `uuid4()`.
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
        url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        # Aplica a cadeia inteira (incl. 0058, 0059 e 0060) e, com isso, VALIDA o encadeamento: um
        # `down_revision` errado nesta onda apareceria aqui como "multiple heads".
        _run_migrations_as_app(url)
        yield url


def test_bank_account_isolamento_cross_tenant(app_url: str) -> None:
    from app.modules.bank import service as bank_service
    from app.modules.bank.models import BankAccount
    from app.modules.bank.schemas import BankAccountUpdate

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    # MESMA identidade bancária nos dois tenants: o índice único é GLOBAL e não respeita RLS,
    # então isto só passa porque `tenant_id` é a PRIMEIRA coluna da constraint (design §2.1).
    # Sem isso, B receberia um 409 inexplicável por causa de um dado de A — bug E vazamento
    # de existência.
    acc_a = _seed_account(app_url, tenant_a, name="A", opening=100_000, number="55555-5")
    acc_b = _seed_account(app_url, tenant_b, name="B", opening=777_000, number="55555-5")

    # ── Leitura: cada um só enxerga o próprio ────────────────────────────────────────────────
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

    # ── Edição/arquivamento: A não alcança a linha de B ──────────────────────────────────────
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

    # ── Escrita com tenant_id alheio: barrada pelo WITH CHECK ────────────────────────────────
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

    # ── Sem GUC: fail-closed (zero linhas, nunca todas) ──────────────────────────────────────
    with _session_for(app_url, None) as sn:
        assert bank_service.list_accounts(sn) == [], (
            "FAIL-CLOSED falhou: sem `app.current_tenant_id` a leitura devolveu linhas. O "
            "estado seguro é não ver nada."
        )
        assert sn.get(BankAccount, acc_a) is None


# ── Story 8.3 — os MOVIMENTOS (AC9) ──────────────────────────────────────────────────────────


def _lancar(
    app_url: str,
    tenant_id: str,
    account_id: str,
    *,
    amount_cents: int,
    posted_at: date,
    description: str = "movimento",
) -> str:
    from app.modules.bank import service as bank_service
    from app.modules.bank.schemas import BankTransactionCreate

    with _session_for(app_url, tenant_id) as session:
        tx = bank_service.create_transaction(
            session,
            bank_account_id=account_id,
            tenant_id=tenant_id,
            actor="quem-lancou",
            data=BankTransactionCreate(
                posted_at=posted_at, amount_cents=amount_cents, description=description
            ),
        )
        return tx.id


def test_bank_transaction_isolamento_cross_tenant(app_url: str) -> None:
    """O movimento de A é invisível e intocável para B — e o SALDO de A não vê o dinheiro de B.

    O último caso é o que só existe nesta story: com movimentos, um vazamento de RLS não apareceria
    como "vi uma linha que não é minha", e sim como um **saldo errado** — uma divergência
    inexplicável no relatório de conferência da 8.5, que é justamente o número que o produto vende
    como confiável.
    """
    from app.modules.bank import service as bank_service
    from app.modules.bank.models import BankTransaction
    from app.modules.bank.schemas import BankTransactionUpdate

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    acc_a = _seed_account(app_url, tenant_a, name="Mov A", opening=100_000, number="7777-1")
    acc_b = _seed_account(app_url, tenant_b, name="Mov B", opening=100_000, number="7777-2")

    tx_a = _lancar(
        app_url, tenant_a, acc_a, amount_cents=50_000, posted_at=date(2026, 7, 10),
        description="Entrada de A",
    )
    tx_b = _lancar(
        app_url, tenant_b, acc_b, amount_cents=-30_000, posted_at=date(2026, 7, 10),
        description="Saída de B",
    )

    # ── Leitura: A lista e lê só o dele ──────────────────────────────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        assert [t.id for t in bank_service.list_transactions(sa)] == [tx_a]
        assert sa.get(BankTransaction, tx_b) is None, "RLS falhou: A leu o movimento de B"
        with pytest.raises(bank_service.BankError) as exc:
            bank_service.get_transaction(sa, tx_b)
        assert exc.value.status_code == 404, "cross-tenant deve ser 404 fail-closed, não 403"
        # O saldo de A conta o movimento de A e SÓ ele.
        assert bank_service.derived_balance(sa, bank_account_id=acc_a) == 150_000

    with _session_for(app_url, tenant_b) as sb:
        assert [t.id for t in bank_service.list_transactions(sb)] == [tx_b]
        assert bank_service.derived_balance(sb, bank_account_id=acc_b) == 70_000

    # ── Edição/ignore: A não alcança o movimento de B ────────────────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        for call in (
            lambda: bank_service.update_transaction(
                sa, transaction_id=tx_b, tenant_id=tenant_a, actor="a",
                data=BankTransactionUpdate(amount_cents=1),
            ),
            lambda: bank_service.ignore_transaction(
                sa, transaction_id=tx_b, tenant_id=tenant_a, actor="a", reason="some daqui"
            ),
            lambda: bank_service.unignore_transaction(
                sa, transaction_id=tx_b, tenant_id=tenant_a, actor="a"
            ),
        ):
            with pytest.raises(bank_service.BankError) as exc:
                call()
            assert exc.value.status_code == 404

    with _session_for(app_url, tenant_b) as sb:
        mov_b = sb.get(BankTransaction, tx_b)
        assert mov_b.amount_cents == -30_000 and mov_b.status == "unmatched", (
            "RLS falhou: A conseguiu modificar o movimento de B"
        )
        assert bank_service.derived_balance(sb, bank_account_id=acc_b) == 70_000

    # ── Escrita com tenant_id alheio: barrada pelo WITH CHECK ────────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        sa.add(
            BankTransaction(
                tenant_id=tenant_b,  # ← o ataque: plantar um movimento no extrato do vizinho
                bank_account_id=acc_b,
                posted_at=date(2026, 7, 11),
                amount_cents=999_999,
                raw_description="Plantado por A",
                dedup_hash="hash-plantado",
                source="manual",
                status="unmatched",
            )
        )
        with pytest.raises(ProgrammingError):
            sa.commit()
        sa.rollback()

    # ── O saldo de B não se moveu — o teste que só esta story pode fazer ─────────────────────
    with _session_for(app_url, tenant_b) as sb:
        assert [t.id for t in bank_service.list_transactions(sb)] == [tx_b], (
            "WITH CHECK falhou: A plantou um movimento no tenant de B"
        )
        assert bank_service.derived_balance(sb, bank_account_id=acc_b) == 70_000, (
            "o saldo de B mudou por causa de uma escrita de A — é assim que um vazamento de RLS "
            "apareceria depois desta story: como um número errado, não como uma linha estranha"
        )

    # ── O saldo de A não enxerga movimento de B lançado na conta de B ────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        assert bank_service.derived_balance(sa, bank_account_id=acc_a) == 150_000
        assert bank_service.derived_balances_as_of(sa) == {acc_a: 150_000}
        # A conta de B nem existe para A: pedir o saldo dela é 404, não um número.
        with pytest.raises(bank_service.BankError) as exc:
            bank_service.derived_balance(sa, bank_account_id=acc_b)
        assert exc.value.status_code == 404

    # ── Sem GUC: fail-closed também nos movimentos ───────────────────────────────────────────
    with _session_for(app_url, None) as sn:
        assert bank_service.list_transactions(sn) == [], (
            "FAIL-CLOSED falhou: sem `app.current_tenant_id` a leitura de movimentos devolveu "
            "linhas. O estado seguro é não ver nada."
        )
        assert sn.get(BankTransaction, tx_a) is None


def test_dedupe_unique_index_nao_vaza_entre_tenants(app_url: str) -> None:
    """O índice único de dedupe é GLOBAL (não respeita RLS) — `tenant_id` na frente é o que salva.

    Dois tenants com o MESMO `dedup_hash` na MESMA `bank_account_id` precisam conviver. Sem
    `tenant_id` como primeira coluna da constraint, o segundo levaria um erro de integridade
    causado por um dado que ele não pode nem ver: bug **e** vazamento de existência. Este é o
    equivalente, para movimentos, do caso de identidade bancária repetida já coberto acima.
    """
    from app.modules.bank.models import BankTransaction

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    conta_compartilhada = str(uuid4())  # mesmo id de conta nos dois lados, de propósito
    mesmo_hash = "colisao-proposital-entre-tenants"

    for tenant_id in (tenant_a, tenant_b):
        with _session_for(app_url, tenant_id) as session:
            session.add(
                BankTransaction(
                    tenant_id=tenant_id,
                    bank_account_id=conta_compartilhada,
                    posted_at=date(2026, 7, 12),
                    amount_cents=1_000,
                    raw_description="mesmo hash, tenants diferentes",
                    dedup_hash=mesmo_hash,
                    source="manual",
                    status="unmatched",
                )
            )
            session.commit()  # o segundo NÃO pode estourar IntegrityError

    with _session_for(app_url, tenant_b) as sb:
        assert (
            sb.query(BankTransaction).filter(BankTransaction.dedup_hash == mesmo_hash).count() == 1
        ), "B enxergou o movimento de A (ou o próprio em duplicidade)"


# ── Story 8.4 — o SALDO DECLARADO (AC9) ──────────────────────────────────────────────────────


def _declarar(
    app_url: str,
    tenant_id: str,
    account_id: str,
    *,
    balance_cents: int,
    reference_date: date,
) -> str:
    from app.modules.bank import service as bank_service
    from app.modules.bank.schemas import CheckpointCreate

    with _session_for(app_url, tenant_id) as session:
        cp, criado = bank_service.declare_balance(
            session,
            bank_account_id=account_id,
            tenant_id=tenant_id,
            actor="quem-declarou",
            data=CheckpointCreate(
                reference_date=reference_date, balance_cents=balance_cents
            ),
        )
        assert criado is True
        return cp.id


def test_bank_checkpoint_isolamento_cross_tenant(app_url: str) -> None:
    """O saldo declarado de A é invisível e intocável para B — e `latest_checkpoint` não vaza.

    O último caso é o que só existe nesta story: `latest_checkpoint` é a função que a conferência
    (8.5) consome, e um vazamento ali não apareceria como "vi uma linha que não é minha", e sim
    como a **verdade externa do vizinho** sendo comparada com o saldo derivado deste tenant — uma
    divergência inventada, plausível e silenciosa, no relatório que o produto vende como confiável.
    """
    from app.modules.bank import service as bank_service
    from app.modules.bank.models import BankBalanceCheckpoint

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    acc_a = _seed_account(app_url, tenant_a, name="Saldo A", opening=100_000, number="8888-1")
    acc_b = _seed_account(app_url, tenant_b, name="Saldo B", opening=100_000, number="8888-2")

    dia = date(2026, 7, 15)
    cp_a = _declarar(app_url, tenant_a, acc_a, balance_cents=123_456, reference_date=dia)
    cp_b = _declarar(app_url, tenant_b, acc_b, balance_cents=999_999, reference_date=dia)

    # ── Leitura: A lista e lê só o dele ──────────────────────────────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        assert [c.id for c in bank_service.list_checkpoints(sa)] == [cp_a]
        assert sa.get(BankBalanceCheckpoint, cp_b) is None, "RLS falhou: A leu o checkpoint de B"
        with pytest.raises(bank_service.BankError) as exc:
            bank_service.get_checkpoint(sa, cp_b)
        assert exc.value.status_code == 404, "cross-tenant deve ser 404 fail-closed, não 403"

    with _session_for(app_url, tenant_b) as sb:
        assert [c.id for c in bank_service.list_checkpoints(sb)] == [cp_b]

    # ── `latest_checkpoint`: a verdade externa de A não é a de B ─────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        achado = bank_service.latest_checkpoint(sa, bank_account_id=acc_a, on_or_before=dia)
        assert achado is not None and achado.balance_cents == 123_456
        # A conta de B nem existe para A: o resultado honesto é `None` (= "não há verdade externa
        # aqui" → `ORIGEM_INDISPONIVEL` na 8.5), JAMAIS o checkpoint do vizinho.
        assert (
            bank_service.latest_checkpoint(sa, bank_account_id=acc_b, on_or_before=dia) is None
        ), (
            "RLS falhou: `latest_checkpoint` devolveu a verdade externa de outro tenant — a 8.5 "
            "compararia o saldo do banco do vizinho com o saldo derivado deste tenant"
        )
        # Idem para o contador de abandono: `None` (nunca declarado), não os dias de B.
        assert (
            bank_service.days_since_last_declared_balance(
                sa, bank_account_id=acc_b, today=date(2026, 7, 31)
            )
            is None
        )
        assert (
            bank_service.days_since_last_declared_balance(sa, today=date(2026, 7, 31)) == 16
        ), "o consolidado do tenant A contou o checkpoint de B"

    # ── Delete: A não alcança o checkpoint de B ──────────────────────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        with pytest.raises(bank_service.BankError) as exc:
            bank_service.delete_checkpoint(
                sa, checkpoint_id=cp_b, tenant_id=tenant_a, actor="a"
            )
        assert exc.value.status_code == 404

    with _session_for(app_url, tenant_b) as sb:
        sobrevivente = sb.get(BankBalanceCheckpoint, cp_b)
        assert sobrevivente is not None and sobrevivente.balance_cents == 999_999, (
            "RLS falhou: A conseguiu apagar o saldo declarado de B"
        )

    # ── Escrita com tenant_id alheio: barrada pelo WITH CHECK ────────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        sa.add(
            BankBalanceCheckpoint(
                tenant_id=tenant_b,  # ← o ataque: plantar uma "verdade externa" no vizinho
                bank_account_id=acc_b,
                reference_date=date(2026, 7, 16),
                balance_cents=1,
                origin="manual",
            )
        )
        with pytest.raises(ProgrammingError):
            sa.commit()
        sa.rollback()

    with _session_for(app_url, tenant_b) as sb:
        assert [c.id for c in bank_service.list_checkpoints(sb)] == [cp_b], (
            "WITH CHECK falhou: A plantou um saldo declarado no tenant de B"
        )

    # ── Sem GUC: fail-closed ─────────────────────────────────────────────────────────────────
    with _session_for(app_url, None) as sn:
        assert bank_service.list_checkpoints(sn) == [], (
            "FAIL-CLOSED falhou: sem `app.current_tenant_id` a leitura de saldos declarados "
            "devolveu linhas. O estado seguro é não ver nada."
        )
        assert sn.get(BankBalanceCheckpoint, cp_a) is None
        assert (
            bank_service.latest_checkpoint(sn, bank_account_id=acc_a, on_or_before=dia) is None
        )


def test_checkpoint_unique_do_dia_nao_vaza_entre_tenants(app_url: str) -> None:
    """`uq_bank_checkpoint_day` é GLOBAL (não respeita RLS) — `tenant_id` na frente é o que salva.

    Dois tenants declarando o saldo do MESMO dia, na MESMA `bank_account_id`, com a MESMA origem,
    precisam conviver. Sem `tenant_id` como primeira coluna da constraint, o segundo levaria um 409
    causado por um dado que ele não pode nem ver: bug **e** vazamento de existência.
    """
    from app.modules.bank.models import BankBalanceCheckpoint

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    conta_compartilhada = str(uuid4())  # mesmo id de conta nos dois lados, de propósito
    mesmo_dia = date(2026, 7, 20)

    for tenant_id in (tenant_a, tenant_b):
        with _session_for(app_url, tenant_id) as session:
            session.add(
                BankBalanceCheckpoint(
                    tenant_id=tenant_id,
                    bank_account_id=conta_compartilhada,
                    reference_date=mesmo_dia,
                    balance_cents=50_000,
                    origin="manual",
                )
            )
            session.commit()  # o segundo NÃO pode estourar IntegrityError

    with _session_for(app_url, tenant_b) as sb:
        assert (
            sb.query(BankBalanceCheckpoint)
            .filter(BankBalanceCheckpoint.reference_date == mesmo_dia)
            .count()
            == 1
        ), "B enxergou o checkpoint de A (ou o próprio em duplicidade)"


def test_redeclaracao_e_origin_convivem_no_postgres_real(app_url: str) -> None:
    """A constraint do dia no Postgres real: redeclarar CORRIGE; `manual` e `ofx` coexistem.

    O SQLite dos testes unitários cria o índice único com outro dialeto, então o comportamento de
    AC3/AC4 sob a constraint de verdade é confirmado aqui. A linha `ofx` é escrita direto pelo
    modelo — a API a recusa com 422 nesta onda.
    """
    from app.modules.bank import service as bank_service
    from app.modules.bank.models import BankBalanceCheckpoint
    from app.modules.bank.schemas import CheckpointCreate

    tenant = str(uuid4())
    acc = _seed_account(app_url, tenant, name="Redeclara", opening=10_000, number="6666-6")
    dia = date(2026, 7, 22)

    primeiro = _declarar(app_url, tenant, acc, balance_cents=1_234_00, reference_date=dia)

    with _session_for(app_url, tenant) as s:
        cp, criado = bank_service.declare_balance(
            s,
            bank_account_id=acc,
            tenant_id=tenant,
            actor="quem-corrigiu",
            data=CheckpointCreate(reference_date=dia, balance_cents=12_340_00),
        )
        assert criado is False and cp.id == primeiro
        assert cp.balance_cents == 12_340_00
        assert cp.created_by == "quem-corrigiu"

        # `origin` na chave única não é redundância: o mesmo dia aceita a outra porta de entrada.
        s.add(
            BankBalanceCheckpoint(
                tenant_id=tenant,
                bank_account_id=acc,
                reference_date=dia,
                balance_cents=12_340_00,
                origin="ofx",
            )
        )
        s.commit()

        assert s.query(BankBalanceCheckpoint).count() == 2
        # E o desempate do mesmo dia é pela REGRA (`ofx` na frente), não pela ordem de inserção.
        vencedor = bank_service.latest_checkpoint(s, bank_account_id=acc, on_or_before=dia)
        assert vencedor.origin == "ofx"
