"""Migration 0067 e `client_events` sob RLS REAL (papel não-superusuário `e1p_app`).

Dois fatos que a suíte SQLite é estruturalmente incapaz de provar:

1. **O backfill de `phone_key` NÃO é no-op.** `clients` tem FORCE ROW LEVEL SECURITY. Se a
   migration esquecesse de desabilitar a RLS na janela do backfill, o UPDATE afetaria zero
   linhas SEM ERRO NENHUM — e o sintoma em produção seria "continua duplicando contato", meses
   depois. Semeamos `clients` ANTES de aplicar a 0067 e conferimos as chaves depois.
2. **`client_events` é fail-closed cross-tenant.** Sessão do tenant A não enxerga evento do
   tenant B; sessão SEM GUC não enxerga nada.

Cada caso negativo vem com controle positivo (mesma operação sob a ótica do dono) para provar
que a asserção falha pelo motivo certo, e não por id errado.

Mesmo bootstrap de test_receipts_rls.py: engine SQLAlchemy "cru" da URL do container (sem
reusar `tenant_session`, que fica preso a `settings.database_url` no import), migrations
aplicadas com `alembic upgrade` como `e1p_app`.

Marcado `rls_e2e`: NÃO roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job
dedicado do CI (`cross-tenant-rls`) ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"

_API_DIR = Path(__file__).resolve().parents[1]

# Telefones semeados ANTES da 0067, nos formatos que o mundo real produz.
SEMENTES = [
    ("Flavio Moderno", "(11) 99999-8888"),
    ("Flavio Antigo", "11 9999-8888"),
    ("Fixo do Escritorio", "(11) 3333-4444"),
    ("Sem Telefone", ""),
]


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _run_migrations_as_app(app_url: str, revision: str) -> None:
    """Igual ao helper de `test_receipts_rls.py`, mas com a revisão parametrizada.

    O teste precisa parar em `0066`, semear `clients` e só então aplicar a `0067` — senão o
    backfill rodaria sobre tabela vazia, e backfill de tabela vazia é indistinguível de
    backfill no-op (que é exatamente o bug que este arquivo existe para pegar).
    """
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, revision)
    finally:
        settings.database_url = original_url


@pytest.fixture(scope="module")
def ambiente():
    """Sobe Postgres, migra até 0066, SEMEIA `clients` e só então aplica a 0067."""
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
        _run_migrations_as_app(app_url, "0066")

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())

        engine = create_engine(app_url, poolclass=NullPool)
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_a}
            )
            for nome, telefone in SEMENTES:
                conn.execute(
                    text(
                        "INSERT INTO clients (id, tenant_id, name, phone, gender, notes, "
                        "tags, source, created_at, updated_at) VALUES "
                        "(:id, :t, :n, :p, 'unspecified', '', '[]'::json, 'landing', "
                        "now(), now())"
                    ),
                    {"id": str(uuid4()), "t": tenant_a, "n": nome, "p": telefone},
                )
        engine.dispose()

        # AGORA a 0067 — o backfill encontra linhas de verdade.
        _run_migrations_as_app(app_url, "head")

        yield {"url": app_url, "tenant_a": tenant_a, "tenant_b": tenant_b}


def test_backfill_de_phone_key_nao_foi_no_op(ambiente):
    """Se a migration esquecesse de abrir a janela de RLS, todos viriam NULL."""
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            linhas = conn.execute(
                text("SELECT name, phone, phone_key FROM clients ORDER BY name")
            ).fetchall()
    finally:
        engine.dispose()

    por_nome = {r.name: r.phone_key for r in linhas}
    assert por_nome["Flavio Moderno"] == "5511999998888"
    # o celular pré-2016 normaliza para A MESMA chave — é o que faz a dedup funcionar
    assert por_nome["Flavio Antigo"] == "5511999998888"
    # fixo NÃO colide com o celular
    assert por_nome["Fixo do Escritorio"] == "551133334444"
    assert por_nome["Sem Telefone"] is None


def test_phone_cru_nao_foi_alterado_pelo_backfill(ambiente):
    """`phone` é evidência do que a pessoa digitou; o backfill só preenche a coluna nova."""
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            phone = conn.scalar(
                text("SELECT phone FROM clients WHERE name = 'Flavio Moderno'")
            )
    finally:
        engine.dispose()
    assert phone == "(11) 99999-8888"


def test_facts_isolado_entre_tenants(ambiente):
    """A linha do tempo narrativa mudou de casa na 0069 (`client_events` → `facts`).

    A RLS precisa valer na tabela nova exatamente como valia na antiga — uma tabela que troca
    de nome sem levar a policy junto é vazamento silencioso.
    """
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    fato_id = str(uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            client_id = conn.scalar(
                text("SELECT id FROM clients WHERE name = 'Flavio Moderno'")
            )
            conn.execute(
                text(
                    "INSERT INTO facts (id, tenant_id, module, kind, title, body, client_id, "
                    "subject_type, subject_id, actor, is_ai, occurred_at, origin, "
                    "created_at, updated_at) VALUES "
                    "(:id, :t, 'crm', 'crm.nota.criada', 'Decisao', 'fechamos com 10%', :c, "
                    "'client', :c, 'ana@example.com', false, now(), 'emitted', now(), now())"
                ),
                {"id": fato_id, "t": ambiente["tenant_a"], "c": client_id},
            )

        # controle POSITIVO: o dono enxerga
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            assert conn.scalar(
                text("SELECT count(*) FROM facts WHERE id = :id"), {"id": fato_id}
            ) == 1

        # caso NEGATIVO: outro tenant não enxerga
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_b"]},
            )
            assert conn.scalar(
                text("SELECT count(*) FROM facts WHERE id = :id"), {"id": fato_id}
            ) == 0

        # caso NEGATIVO: sessão sem GUC não enxerga nada (fail-closed)
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT count(*) FROM facts")) == 0
    finally:
        engine.dispose()
