"""A limpeza de reconexão (issue #302) é um UPDATE EM MASSA — contra Postgres REAL, sob RLS.

Por que este teste é obrigatório e não pode viver na suíte SQLite: o `UPDATE agenda_events ...`
de `_invalidar_vinculos_de_outra_conta` não traz filtro de tenant no `WHERE` (Regra de Ouro
nº 1 — quem isola é a RLS). Se a política não permitisse a escrita, o Postgres NÃO levantaria
erro: filtraria a ZERO linhas e o commit "passaria". É o modo de falha silenciosa que já mordeu
este repo, e SQLite (que não tem RLS) aprovaria os dois casos igualmente.

Por isso as asserções são de CONTAGEM, não de ausência de exceção: provamos que N linhas
REALMENTE mudaram no tenant que reconectou, e que ZERO mudaram no tenant vizinho.

Mesmo bootstrap de test_google_calendar_sync_rls.py: engine "cru" da URL do container,
migrations aplicadas com `alembic upgrade head` como `e1p_app`. Marcado `rls_e2e`: NÃO roda no
`pytest -q`, só no job `cross-tenant-rls` do CI ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, func, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"
_API_DIR = Path(__file__).resolve().parents[1]

CONTA_ANTIGA = "antiga@gmail.com"
CONTA_NOVA = "nova@gmail.com"


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


def _semear(session: Session, tenant_id: str, *, prefixo: str) -> None:
    """Dois eventos com procedência da conta ANTIGA + um legado (procedência desconhecida)."""
    from app.modules.agenda.models import AgendaEvent

    for i in (1, 2):
        session.add(
            AgendaEvent(
                tenant_id=tenant_id,
                title=f"Reunião {prefixo}-{i}",
                kind="reuniao",
                starts_at=datetime(2026, 9, 10, 10, 0, tzinfo=UTC),
                ends_at=datetime(2026, 9, 10, 11, 0, tzinfo=UTC),
                google_event_id=f"{prefixo}-evt-{i}",
                google_account_email=CONTA_ANTIGA,
                meeting_url=f"https://meet.google.com/{prefixo}-{i}",
            )
        )
    session.add(
        AgendaEvent(
            tenant_id=tenant_id,
            title=f"Legado {prefixo}",
            kind="reuniao",
            starts_at=datetime(2026, 9, 11, 10, 0, tzinfo=UTC),
            ends_at=datetime(2026, 9, 11, 11, 0, tzinfo=UTC),
            google_event_id=f"{prefixo}-evt-legado",
            google_account_email=None,  # procedência desconhecida: imune por desenho
            meeting_url=f"https://meet.google.com/{prefixo}-legado",
        )
    )
    session.commit()


def _com_vinculo(session: Session) -> int:
    from app.modules.agenda.models import AgendaEvent

    return session.scalar(
        select(func.count()).select_from(AgendaEvent).where(
            AgendaEvent.google_event_id.is_not(None)
        )
    )


def test_limpeza_de_reconexao_atinge_o_proprio_tenant_e_nao_o_vizinho() -> None:
    from app.modules.google_calendar.service import (
        _invalidar_vinculos_de_outra_conta,
        upsert_credential,
    )

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
        with _tenant_session(app_url, tenant_a) as sa_:
            _semear(sa_, tenant_a, prefixo="a")
            assert _com_vinculo(sa_) == 3
        with _tenant_session(app_url, tenant_b) as sb:
            _semear(sb, tenant_b, prefixo="b")
            assert _com_vinculo(sb) == 3

        # (a) O UPDATE em massa AFETA as linhas do tenant que está reconectando. A contagem
        #     devolvida pelo próprio UPDATE é a prova contra o modo de falha silenciosa: uma
        #     política de RLS que barrasse a escrita devolveria 0 aqui, sem erro nenhum.
        with _tenant_session(app_url, tenant_a) as sa_:
            afetadas = _invalidar_vinculos_de_outra_conta(sa_, novo_email=CONTA_NOVA)
            assert afetadas == 2, (
                "o UPDATE em massa não alcançou as linhas do próprio tenant — sob FORCE RLS "
                "isso é falha SILENCIOSA (zero linhas, zero erro)"
            )
            sa_.commit()

        with _tenant_session(app_url, tenant_a) as sa_:
            from app.modules.agenda.models import AgendaEvent

            assert _com_vinculo(sa_) == 1  # sobra só o legado
            legado = sa_.scalars(
                select(AgendaEvent).where(AgendaEvent.google_event_id.is_not(None))
            ).one()
            assert legado.google_event_id == "a-evt-legado"
            assert legado.meeting_url == "https://meet.google.com/a-legado"
            assert legado.google_account_email is None
            # As duas invalidadas perderam id, link e procedência — as três colunas.
            limpas = sa_.scalars(
                select(AgendaEvent).where(AgendaEvent.google_event_id.is_(None))
            ).all()
            assert len(limpas) == 2
            assert all(e.meeting_url is None and e.google_account_email is None for e in limpas)

        # (b) O tenant vizinho NÃO foi tocado — as 3 linhas dele seguem intactas.
        with _tenant_session(app_url, tenant_b) as sb:
            from app.modules.agenda.models import AgendaEvent

            assert _com_vinculo(sb) == 3
            vizinhas = sb.scalars(select(AgendaEvent)).all()
            assert len(vizinhas) == 3
            assert all(e.meeting_url is not None for e in vizinhas)

        # (c) O caminho REAL (`upsert_credential`, com credencial + auditoria na mesma
        #     transação) também escreve de verdade sob FORCE RLS — não só a query isolada.
        with _tenant_session(app_url, tenant_b) as sb:
            upsert_credential(
                sb,
                tenant_id=tenant_b,
                email=CONTA_NOVA,
                token_data={"access_token": "a", "refresh_token": "r", "expires_in": 3600},
            )
        with _tenant_session(app_url, tenant_b) as sb:
            assert _com_vinculo(sb) == 1  # só o legado de B sobreviveu
