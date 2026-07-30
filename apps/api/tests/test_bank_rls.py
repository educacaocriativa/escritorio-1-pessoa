"""Isolamento cross-tenant de `bank_accounts` (8.2), `bank_transactions` (8.3),
`bank_balance_checkpoints` (8.4) e da **conferência** que compara os três (8.5) no Postgres REAL.

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
compartilham o mesmo bootstrap. A 8.3, a 8.4 e a 8.5 seguiram essa instrução (funções novas neste
arquivo, mesmo container de escopo de módulo).

> **[@dev 8.5] Desvio documentado das File Locations da Story 8.5.** A story previa um arquivo novo,
> `tests/test_bank_reconciliation_report_rls.py`. Ele exigiria um **segundo** `PostgresContainer`
> (a fixture `app_url` tem escopo de MÓDULO) e, com ele, um segundo `alembic upgrade head` — minutos
> de CI para exercitar exatamente as mesmas três tabelas já preparadas aqui. A instrução escrita
> neste arquivo pela 8.3 é a mais recente e a mais informada; seguimos o padrão real do repositório
> e registramos a divergência em Completion Notes.

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
from sqlalchemy.exc import IntegrityError, ProgrammingError  # noqa: E402
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


# ── Story 8.5 — a CONFERÊNCIA (IV4) ──────────────────────────────────────────────────────────


def test_conferencia_isolamento_cross_tenant(app_url: str) -> None:
    """O relatório de conferência de A nunca enxerga conta, movimento ou checkpoint de B.

    **É o teste de vazamento mais grave do módulo**, e o motivo é o modo de falha, não a tabela: um
    vazamento aqui não apareceria como "vi uma linha que não é minha". Apareceria como a **verdade
    externa do vizinho** (ou os movimentos dele) entrando na conta deste tenant — ou seja, como uma
    **divergência inventada**, plausível e silenciosa, no único número que este produto vende como
    confiável. Pior ainda: esse número é o gate de decisão do epic §3.1 sobre as Ondas 3 e 4.

    Os dois tenants são montados para que qualquer mistura produza divergência: A fecha **exato**
    (divergência 0, dentro da banda, nada fora) e B tem um furo enorme. Se o checkpoint de B vazar
    para A, o relatório de A deixa de fechar em zero; se o de A vazar para B, o furo de B some.
    """
    from app.modules.bank import reconciliation
    from app.modules.bank import service as bank_service

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    start, end, hoje = date(2026, 7, 1), date(2026, 7, 25), date(2026, 7, 28)
    dia = date(2026, 7, 20)

    acc_a = _seed_account(app_url, tenant_a, name="Conf A", opening=100_000, number="4444-1")
    acc_b = _seed_account(app_url, tenant_b, name="Conf B", opening=100_000, number="4444-2")

    # A: +R$ 500 lançado; o banco confirma exatamente o que o e1p calculou → divergência ZERO.
    _lancar(app_url, tenant_a, acc_a, amount_cents=50_000, posted_at=date(2026, 7, 10))
    _declarar(app_url, tenant_a, acc_a, balance_cents=150_000, reference_date=dia)
    # B: −R$ 800 lançado e um saldo declarado gigante → furo enorme, impossível de confundir.
    _lancar(app_url, tenant_b, acc_b, amount_cents=-80_000, posted_at=date(2026, 7, 10))
    _declarar(app_url, tenant_b, acc_b, balance_cents=9_999_999, reference_date=dia)

    with _session_for(app_url, tenant_a) as sa:
        report = reconciliation.reconciliation_report(sa, start=start, end=end, today=hoje)
        assert [c.bank_account_id for c in report.contas] == [acc_a], (
            f"RLS falhou: a conferência de A enxergou contas alheias — {report.contas}"
        )
        conta = report.contas[0]
        assert conta.saldo_banco_cents == 150_000, "o saldo declarado de B vazou para o de A"
        assert conta.saldo_sistema_cents == 150_000, "um movimento de B entrou no saldo de A"
        assert conta.divergencia_cents == 0, (
            "a conferência de A deixou de fechar em zero — é EXATAMENTE assim que um vazamento de "
            "RLS apareceria aqui: como uma divergência inventada, não como uma linha estranha"
        )
        assert conta.dentro_da_tolerancia is True
        assert report.total_divergencia_cents == 0
        assert report.contas_fora_da_banda == []
        assert report.contas_avaliadas == 1 and report.contas_sem_checkpoint == 0

        # Pedir a conta de B é 404 fail-closed (a linha não existe para A), nunca um relatório.
        with pytest.raises(bank_service.BankError) as exc:
            reconciliation.reconciliation_report(
                sa, start=start, end=end, bank_account_id=acc_b, today=hoje
            )
        assert exc.value.status_code == 404

    with _session_for(app_url, tenant_b) as sb:
        report_b = reconciliation.reconciliation_report(sb, start=start, end=end, today=hoje)
        assert [c.bank_account_id for c in report_b.contas] == [acc_b]
        conta_b = report_b.contas[0]
        assert conta_b.saldo_sistema_cents == 20_000
        assert conta_b.divergencia_cents == 9_999_999 - 20_000, (
            "o furo de B mudou de tamanho — dado de A entrou no cálculo de B"
        )
        assert conta_b.dentro_da_tolerancia is False
        assert [f.bank_account_id for f in report_b.contas_fora_da_banda] == [acc_b]

    # ── Sem GUC: fail-closed. Zero contas, e NUNCA um total fabricado ────────────────────────
    with _session_for(app_url, None) as sn:
        vazio = reconciliation.reconciliation_report(sn, start=start, end=end, today=hoje)
        assert vazio.contas == [], (
            "FAIL-CLOSED falhou: sem `app.current_tenant_id` a conferência devolveu contas. O "
            "estado seguro é não ver nada."
        )
        assert vazio.total_divergencia_cents is None, (
            "sem tenant, o total precisa ser `None` (não sei) — um `0` afirmaria que está tudo "
            "batendo"
        )
        assert vazio.contas_avaliadas == 0 and vazio.contas_fora_da_banda == []


# ── Story 8.11 — a guarda do recuo e o agregado do aviso, sob RLS real ────────────────────────


def test_recuo_do_opening_date_sob_rls(app_url: str) -> None:
    """Os **+2 casos do design §4.3** no Postgres real: recuo com saldo → 200; sem saldo → 422.

    Vale rodar aqui, e não só no SQLite, por dois motivos: a guarda compara uma coluna `DATE` do
    Postgres (que volta como `datetime.date`, e não como texto) e o caminho de escrita passa pelo
    `commit`/`refresh` sob RLS — onde um `db.refresh()` sem a GUC já derrubou o produto inteiro
    antes (`CLAUDE.md` §6.0, o bug do refresh pós-commit).
    """
    from app.modules.bank import service as bank_service
    from app.modules.bank.schemas import BankAccountUpdate

    tenant = str(uuid4())
    acc = _seed_account(app_url, tenant, name="Recuo", opening=100_000, number="9911-1")

    # (a) Recuo SEM redeclarar o saldo → 422, e nada é gravado (nem a data).
    with _session_for(app_url, tenant) as s:
        with pytest.raises(bank_service.BankError) as exc:
            bank_service.update_account(
                s, account_id=acc, tenant_id=tenant, actor="dono",
                data=BankAccountUpdate(opening_date=date(2026, 6, 1)),
            )
        assert exc.value.status_code == 422
        assert "2026-07-01" in str(exc.value) and "2026-06-01" in str(exc.value)

    with _session_for(app_url, tenant) as s:
        conta = bank_service.get_account(s, acc)
        assert conta.opening_date == date(2026, 7, 1), "o 422 gravou a data pela metade"
        assert conta.opening_balance_cents == 100_000

    # (b) Recuo COM o saldo daquele dia → 200, e o saldo derivado parte do valor REDECLARADO.
    with _session_for(app_url, tenant) as s:
        atualizada = bank_service.update_account(
            s, account_id=acc, tenant_id=tenant, actor="dono",
            data=BankAccountUpdate(opening_date=date(2026, 6, 1), opening_balance_cents=340_000),
        )
        assert atualizada.opening_date == date(2026, 6, 1)
        assert atualizada.opening_balance_cents == 340_000
        assert bank_service.derived_balance(s, bank_account_id=acc) == 340_000


def test_paid_before_isolamento_cross_tenant(app_url: str) -> None:
    """`GET /payables/bills/paid-before` (Story 8.11): A nunca conta as contas pagas de B.

    O modo de falha aqui é **o aviso do vizinho**: o cadastro da conta bancária de A diria "você
    tem N contas pagas entre X e Y" com dados que não são dele — e a data sugerida, que ele vai
    usar como `opening_date` real, viria do histórico de outro escritório. Vazamento de PII de
    negócio **e** um número errado no exato campo que a Regra 5 protege.

    Também exercita o fail-closed: sem a GUC, o agregado é zero e as datas são `None` — nunca a
    soma de todo mundo. Um agregado que vaze não devolve "uma linha estranha", devolve um TOTAL —
    a forma mais silenciosa possível de vazamento.
    """
    from datetime import datetime

    from app.modules.payables import service as payables_service
    from app.modules.payables.models import STATUS_PAID, Payable

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())

    def _pagar(tenant_id: str, *, amount: int, dia: str) -> None:
        with _session_for(app_url, tenant_id) as s:
            s.add(
                Payable(
                    tenant_id=tenant_id,
                    description="conta",
                    category="Geral",
                    supplier="Fornecedor",
                    amount_cents=amount,
                    due_date=date.fromisoformat(dia),
                    status=STATUS_PAID,
                    paid_at=datetime.fromisoformat(f"{dia}T12:00:00+00:00"),
                )
            )
            s.commit()

    _pagar(tenant_a, amount=120_000, dia="2026-05-03")
    _pagar(tenant_a, amount=80_000, dia="2026-06-20")
    _pagar(tenant_b, amount=999_999, dia="2026-01-09")

    corte = date(2026, 7, 30)

    with _session_for(app_url, tenant_a) as sa:
        agregado = payables_service.paid_before(sa, date_=corte)
        assert agregado["count"] == 2, f"A contou conta paga de B: {agregado}"
        assert agregado["total_cents"] == 200_000, "o valor pago de B entrou no total de A"
        assert agregado["oldest_paid_on"] == date(2026, 5, 3), (
            "a data mais antiga veio do histórico de OUTRO tenant — é ela que o dono usaria como "
            "`opening_date` da conta bancária dele"
        )
        assert agregado["newest_paid_on"] == date(2026, 6, 20)

    with _session_for(app_url, tenant_b) as sb:
        assert payables_service.paid_before(sb, date_=corte) == {
            "count": 1,
            "total_cents": 999_999,
            "oldest_paid_on": date(2026, 1, 9),
            "newest_paid_on": date(2026, 1, 9),
        }

    # ── Sem GUC: fail-closed. Zero, e NUNCA a soma de todos os tenants ───────────────────────
    with _session_for(app_url, None) as sn:
        assert payables_service.paid_before(sn, date_=corte) == {
            "count": 0,
            "total_cents": 0,
            "oldest_paid_on": None,
            "newest_paid_on": None,
        }, (
            "FAIL-CLOSED falhou: sem `app.current_tenant_id` o agregado devolveu números. Num "
            "agregado o vazamento não aparece como linha estranha — aparece como um TOTAL."
        )


# ── Story 8.10 — o corte de data sob RLS ─────────────────────────────────────────────────────


def test_corte_de_data_sob_rls_cross_tenant(app_url: str) -> None:
    """O corte de `until=None` → **hoje** (Story 8.10) vale no Postgres real, e não vaza.

    Vale rodar aqui, e não só no SQLite, por dois motivos concretos:

    1. **A mudança altera a cláusula `WHERE` efetiva de uma query que roda sob RLS.** Uma condição a
       mais no `WHERE` de uma policy `FORCE` é exatamente o tipo de coisa que passa no SQLite e cai
       no Postgres — e o sintoma seria um saldo errado, não um erro.
    2. **`SEM_CORTE` é `date.max`.** No SQLite a comparação de `DATE` é textual (`'9999-12-31'`
       ordena bem por acidente do formato ISO); no Postgres é uma comparação de `date` de verdade,
       no limite superior do tipo. Se `date.max` estourasse o binding em algum dialeto, seria aqui.

    O cenário é montado **direto pelo model** porque `_validate_posted_at` recusa `posted_at` futuro
    pela porta manual — e continua recusando (quem afrouxa isso para o caminho de ORIGEM é a
    8.12/8.14). Ver a mesma justificativa em `tests/test_bank_corte_de_data.py`.
    """
    from datetime import timedelta

    from app.modules.bank import service as bank_service
    from app.modules.bank.models import BankTransaction

    hoje = bank_service._today()
    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    acc_a = _seed_account(app_url, tenant_a, name="A corte", opening=100_000, number="7710-1")
    acc_b = _seed_account(app_url, tenant_b, name="B corte", opening=500_000, number="7710-2")

    # Movimento PASSADO em cada um (pela porta normal) + um AGENDADO só no tenant A.
    _lancar(app_url, tenant_a, acc_a, amount_cents=20_000, posted_at=hoje - timedelta(days=2))
    _lancar(app_url, tenant_b, acc_b, amount_cents=-5_000, posted_at=hoje - timedelta(days=2))

    with _session_for(app_url, tenant_a) as sa:
        sa.add(
            BankTransaction(
                tenant_id=tenant_a,
                bank_account_id=acc_a,
                posted_at=hoje + timedelta(days=10),
                amount_cents=-90_000,
                raw_description="Agendado (como a 8.14 fara)",
                dedup_hash=f"agendado-{acc_a}",
                source="manual",
                status="unmatched",
            )
        )
        sa.commit()

    # ── A: o agendado existe, e NÃO entra no saldo corrente ──────────────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        assert len(bank_service.list_transactions(sa)) == 2, (
            "o movimento agendado sumiu da LISTA — ele tem de continuar visível; o que a 8.10 faz "
            "é tirá-lo do SALDO, não escondê-lo"
        )
        assert bank_service.derived_balance(sa, bank_account_id=acc_a) == 120_000
        assert bank_service.derived_balances_as_of(sa) == {acc_a: 120_000}
        # E a saída de emergência funciona no limite superior do tipo `date` do Postgres.
        assert (
            bank_service.derived_balance(
                sa, bank_account_id=acc_a, until=bank_service.SEM_CORTE
            )
            == 30_000
        )
        assert bank_service.derived_balances_as_of(sa, as_of=bank_service.SEM_CORTE) == {
            acc_a: 30_000
        }

    # ── B: nada do agendado de A o alcança, por nenhum dos dois cortes ───────────────────────
    with _session_for(app_url, tenant_b) as sb:
        assert bank_service.derived_balance(sb, bank_account_id=acc_b) == 495_000
        assert bank_service.derived_balances_as_of(sb) == {acc_b: 495_000}
        assert bank_service.derived_balances_as_of(sb, as_of=bank_service.SEM_CORTE) == {
            acc_b: 495_000
        }, (
            "o movimento AGENDADO do tenant A entrou no histórico de B. `SEM_CORTE` amplia a "
            "janela de DATAS, nunca o escopo de tenant — se ampliou, a RLS foi contornada pela "
            "condição nova do WHERE"
        )

    # ── Sem GUC: fail-closed, inclusive com o corte mais permissivo que existe ───────────────
    with _session_for(app_url, None) as sn:
        assert bank_service.derived_balances_as_of(sn) == {}
        assert bank_service.derived_balances_as_of(sn, as_of=bank_service.SEM_CORTE) == {}, (
            "FAIL-CLOSED falhou: sem `app.current_tenant_id`, pedir o histórico inteiro devolveu "
            "saldo. O estado seguro é 'não vejo nada', nunca 'vejo tudo'."
        )


# ── Story 8.9 — a REGRA DA ORIGEM (AC2, AC11) ────────────────────────────────────────────────
#
# > **[@dev 8.9] Desvio documentado das File Locations da Story 8.9.** A story previa um arquivo
# > novo, `tests/test_bank_origin_rls.py`. Ele exigiria um **segundo** `PostgresContainer` (a
# > fixture `app_url` tem escopo de MÓDULO) e, com ele, um segundo `alembic upgrade head` — minutos
# > de CI para exercitar exatamente as mesmas tabelas já preparadas aqui. **A instrução escrita no
# > topo deste arquivo pela 8.3 é explícita** (*"acrescente casos AQUI em vez de criar mais um
# > arquivo de testcontainer"*), a 8.5 seguiu-a e registrou o mesmo desvio, e a 8.9 é a terceira a
# > chegar. Seguimos o padrão real do repositório; registrado em Completion Notes.
#
# A fixture `app_url` passa a exercitar também a migration **0061** (a coluna `origin_id`, as duas
# colunas de `payables` e de `charges` e os dois índices novos) na cadeia …→0059→0060→**0061**.


def _sync_origem(app_url: str, tenant_id: str, **over) -> str | None:
    """`sync_origin_movement` numa sessão com a GUC do tenant fixada. Commita ao sair."""
    from app.modules.bank.models import SOURCE_PAYABLE
    from app.modules.bank.origin import sync_origin_movement

    kwargs = {
        "tenant_id": tenant_id,
        "actor": "dono",
        "source": SOURCE_PAYABLE,
        "origin_id": str(uuid4()),
        "bank_account_id": None,
        "posted_at": date(2026, 7, 10),
        "amount_cents": -120_00,
        "description": "Aluguel",
    }
    kwargs.update(over)
    with _session_for(app_url, tenant_id) as session:
        movimento = sync_origin_movement(session, **kwargs)
        movimento_id = movimento.id if movimento is not None else None
        session.commit()
        return movimento_id


def test_indice_unico_de_origem_no_postgres_real(app_url: str) -> None:
    """**AC2 — as duas metades do índice único PARCIAL, no banco que a produção roda.**

    Esta é a prova autoritativa: é aqui que a migration 0061 cria o índice de verdade, com o
    `WHERE origin_id IS NOT NULL` do dialeto Postgres. O SQLite dos unitários exercita um
    equivalente (`sqlite_where`), mas quem decide em produção é este.

    ⚠️ **A idempotência da Onda 2 inteira é este índice, não o `dedup_hash`.** Um retry de request,
    um reprocessamento de baixa ou um segundo caminho de escrita aberto por engano param aqui —
    fail-closed, no espírito da RLS.
    """
    from app.modules.bank.models import SOURCE_PAYABLE, STATUS_MATCHED, BankTransaction

    tenant = str(uuid4())
    acc = _seed_account(app_url, tenant, name="Origem", opening=100_000, number="6111-1")
    origin_id = str(uuid4())

    assert _sync_origem(app_url, tenant, origin_id=origin_id, bank_account_id=acc) is not None

    # (a) mesma `(tenant, source, origin_id)` → o BANCO recusa a segunda linha. Escrito
    #     CONTORNANDO o sincronizador de propósito: o que precisa estar provado é que a garantia
    #     sobrevive a um segundo caminho de escrita, não que a função tem um `if`.
    with _session_for(app_url, tenant) as s:
        s.add(
            BankTransaction(
                tenant_id=tenant,
                bank_account_id=acc,
                posted_at=date(2026, 7, 11),
                amount_cents=-1,
                raw_description="a mesma origem, de novo",
                dedup_hash="hash-diferente-de-proposito",
                source=SOURCE_PAYABLE,
                origin_id=origin_id,
                status=STATUS_MATCHED,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()

    # (b) duas linhas com `origin_id IS NULL` na mesma conta → **ambas passam**.
    for i in (1, 2):
        _lancar(
            app_url, tenant, acc, amount_cents=-50_00, posted_at=date(2026, 7, 12),
            description=f"Pix manual {i}",
        )

    with _session_for(app_url, tenant) as s:
        assert s.query(BankTransaction).filter(BankTransaction.origin_id.is_(None)).count() == 2


def test_indice_de_origem_nao_vaza_entre_tenants(app_url: str) -> None:
    """`uq_bank_transactions_origin` é GLOBAL — `tenant_id` na frente é o que salva.

    Dois tenants com a **mesma** `(source, origin_id)` precisam conviver. Sem `tenant_id` como
    primeira coluna, o segundo levaria um erro de integridade causado por um dado que ele **não
    pode nem ver**: bug **e** vazamento de existência — a mesma lição que
    `uq_bank_accounts_tenant_ident` (8.2) e `uq_bank_transactions_dedup` (8.3) já pagaram.
    """
    from app.modules.bank.models import BankTransaction

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    acc_a = _seed_account(app_url, tenant_a, name="Org A", opening=100_000, number="6222-1")
    acc_b = _seed_account(app_url, tenant_b, name="Org B", opening=100_000, number="6222-2")
    mesmo_origin_id = str(uuid4())  # a MESMA chave de origem nos dois lados, de propósito

    assert _sync_origem(app_url, tenant_a, origin_id=mesmo_origin_id, bank_account_id=acc_a)
    assert _sync_origem(app_url, tenant_b, origin_id=mesmo_origin_id, bank_account_id=acc_b)

    with _session_for(app_url, tenant_b) as sb:
        assert (
            sb.query(BankTransaction)
            .filter(BankTransaction.origin_id == mesmo_origin_id)
            .count()
            == 1
        ), "B enxergou o movimento de origem de A (ou o próprio em duplicidade)"


def test_sync_origin_movement_isolamento_cross_tenant(app_url: str) -> None:
    """**AC11 — A nunca alcança o movimento, o `payable` nem a `charge` de B.**

    O modo de falha desta função é o mais grave do módulo, porque ela **escreve** no razão
    bancário. Um vazamento aqui não apareceria como "vi uma linha que não é minha" — apareceria
    como **dinheiro do vizinho entrando no meu extrato** (ou sumindo do dele), e portanto como uma
    divergência inventada no único número que este produto vende como confiável.
    """
    from datetime import datetime

    from app.modules.bank import service as bank_service
    from app.modules.bank.models import SOURCE_PAYABLE, BankTransaction
    from app.modules.bank.origin import sync_origin_movement
    from app.modules.payables.models import STATUS_PAID, Payable
    from app.modules.receivables.models import Charge

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    _seed_account(app_url, tenant_a, name="Sync A", opening=100_000, number="6333-1")
    acc_b = _seed_account(app_url, tenant_b, name="Sync B", opening=100_000, number="6333-2")

    origin_b = str(uuid4())
    mov_b = _sync_origem(app_url, tenant_b, origin_id=origin_b, bank_account_id=acc_b)
    assert mov_b is not None

    # ── (1) A não escreve na conta de B: `get_account` é 404 fail-closed ─────────────────────
    with _session_for(app_url, tenant_a) as sa:
        with pytest.raises(bank_service.BankError) as exc:
            sync_origin_movement(
                sa, tenant_id=tenant_a, actor="a", source=SOURCE_PAYABLE,
                origin_id=str(uuid4()), bank_account_id=acc_b,
                posted_at=date(2026, 7, 10), amount_cents=-1_000, description="invasão",
            )
        assert exc.value.status_code == 404, "cross-tenant deve ser 404 fail-closed, não 403"

    # ── (2) A "estorna" a origem de B: não acha nada, não apaga nada ─────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        assert (
            sync_origin_movement(
                sa, tenant_id=tenant_a, actor="a", source=SOURCE_PAYABLE, origin_id=origin_b,
                bank_account_id=None, posted_at=None, amount_cents=None, description="",
            )
            is None
        )
        sa.commit()

    with _session_for(app_url, tenant_b) as sb:
        sobrevivente = sb.get(BankTransaction, mov_b)
        assert sobrevivente is not None, (
            "RLS falhou: A apagou o movimento de origem de B — o extrato do vizinho perdeu uma "
            "linha, e o saldo dele mudou sem que nada no sistema DELE tivesse acontecido"
        )
        assert sobrevivente.origin_id == origin_b
        assert (
            bank_service.derived_balance(sb, bank_account_id=acc_b, until=date(2026, 7, 31))
            == 100_000 - 120_00
        )

    # ── (3) As COLUNAS NOVAS de payables/charges também não vazam (migration 0061) ───────────
    with _session_for(app_url, tenant_b) as sb:
        p_b = Payable(
            tenant_id=tenant_b, description="conta de B", category="Geral", supplier="Forn",
            amount_cents=120_00, due_date=date(2026, 7, 10), status=STATUS_PAID,
            paid_at=datetime.fromisoformat("2026-07-10T12:00:00+00:00"),
            bank_account_id=acc_b, bank_transaction_id=mov_b,
        )
        c_b = Charge(
            tenant_id=tenant_b, description="cobrança de B", kind="service", method="pix",
            amount_cents=300_00, due_date=date(2026, 7, 10), bank_account_id=acc_b,
        )
        sb.add_all([p_b, c_b])
        sb.commit()
        payable_b, charge_b = p_b.id, c_b.id

    with _session_for(app_url, tenant_a) as sa:
        assert sa.get(Payable, payable_b) is None, "A leu a conta a pagar de B"
        assert sa.get(Charge, charge_b) is None, "A leu a cobrança de B"

    # ── (4) Escrita com `tenant_id` alheio: barrada pelo WITH CHECK ──────────────────────────
    with _session_for(app_url, tenant_a) as sa:
        sa.add(
            BankTransaction(
                tenant_id=tenant_b,  # ← o ataque: plantar um movimento de origem no vizinho
                bank_account_id=acc_b,
                posted_at=date(2026, 7, 13),
                amount_cents=999_999,
                raw_description="Plantado por A",
                dedup_hash="hash-plantado-origem",
                source=SOURCE_PAYABLE,
                origin_id=str(uuid4()),
                status="matched",
            )
        )
        with pytest.raises(ProgrammingError):
            sa.commit()
        sa.rollback()

    # ── (5) Sem GUC: fail-closed. A busca da origem não acha, e nada é apagado ───────────────
    with _session_for(app_url, None) as sn:
        assert (
            sync_origin_movement(
                sn, tenant_id=tenant_b, actor="ninguem", source=SOURCE_PAYABLE,
                origin_id=origin_b, bank_account_id=None, posted_at=None, amount_cents=None,
                description="",
            )
            is None
        )
        sn.commit()

    with _session_for(app_url, tenant_b) as sb:
        assert sb.get(BankTransaction, mov_b) is not None, (
            "FAIL-CLOSED falhou: sem `app.current_tenant_id` o sincronizador alcançou (e apagou) "
            "o movimento de um tenant. O estado seguro é não ver nada."
        )
