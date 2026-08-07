"""O fuso que a SESSÃO entrega precisa ser o fuso do tenant — no Postgres real, sob RLS.

**Este bug é invisível para a suíte SQLite, e foi assim que ele passou.** `/auth/login`,
`/auth/register`, `/auth/me` e `/auth/change-password` rodam em sessão CRUA (`get_db`, sem a GUC
de tenant) e liam o fuso de `tenant_profiles`, que tem `FORCE ROW LEVEL SECURITY` desde a 0022.
Sem a GUC, a policy filtra **o SELECT inteiro** — o `WHERE tenant_id = ...` explícito não ajuda,
porque o problema nunca foi *qual* linha trazer, e sim *conseguir enxergar alguma*. O resultado
era o fallback silencioso para `America/Sao_Paulo` em todo tenant, e o `useFuso()` do frontend
inteiro sai desse valor.

É a mesma armadilha do backfill da 0068 ("a RLS filtra SELECT também"), do outro lado do produto.

Cada asserção vem com o CONTROLE POSITIVO ao lado (a mesma leitura com a GUC setada), para provar
que ela falha pelo motivo certo — e não porque o dado não foi gravado.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"
_API_DIR = Path(__file__).resolve().parents[1]

# Um fuso REAL e diferente do padrão: se fosse America/Sao_Paulo, o teste passaria pelo bug.
FUSO_DO_TENANT = "America/Manaus"


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

    original = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original


@contextmanager
def _tenant_session(app_url: str, tenant_id: str):
    """Sessão COM a GUC de tenant — o que as rotas de módulo de negócio usam."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


@contextmanager
def _raw_session(app_url: str):
    """Sessão SEM tenant — exatamente o que `get_db` entrega às rotas de `/auth`."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def app_url() -> str:
    with PostgresContainer("postgres:16-alpine", dbname=_DB_NAME) as pg:
        super_url = pg.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+psycopg://"
        )
        _bootstrap_rls_role(super_url)
        host = super_url.split("@", 1)[1]
        url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}"
        _run_migrations_as_app(url)
        yield url


@pytest.fixture()
def tenant_com_fuso(app_url: str) -> str:
    """Tenant que ESCOLHEU um fuso diferente do padrão, pelo caminho de produção."""
    from app.modules.auth.models import Tenant
    from app.modules.settings.models import TenantProfile

    tenant_id = str(uuid4())
    slug = f"manaus-{tenant_id[:8]}"
    with _raw_session(app_url) as s:  # `tenants` é tabela GLOBAL, sem RLS
        s.add(Tenant(id=tenant_id, slug=slug, legal_name="Manaus ME", document="11444777000161"))
        s.commit()
    with _tenant_session(app_url, tenant_id) as s:
        s.add(TenantProfile(tenant_id=tenant_id, display_name="Manaus ME"))
        s.commit()

    from app.modules.settings.schemas import ProfileUpdate
    from app.modules.settings.service import update_profile

    with _tenant_session(app_url, tenant_id) as s:
        update_profile(
            s, tenant_id=tenant_id, actor="teste", data=ProfileUpdate(timezone=FUSO_DO_TENANT)
        )
        s.commit()
    return tenant_id


def test_a_sessao_de_auth_entrega_o_fuso_do_tenant(app_url: str, tenant_com_fuso: str):
    """O caso que quebrava. `_tenant_out` roda em sessão crua — e precisa acertar mesmo assim."""
    from app.modules.settings.service import timezone_of

    with _raw_session(app_url) as s:
        assert timezone_of(s, tenant_com_fuso) == FUSO_DO_TENANT


def test_controle_positivo_a_sessao_de_tenant_tambem_acerta(app_url: str, tenant_com_fuso: str):
    """Prova que o teste acima falha por RLS, e não porque o fuso não foi gravado."""
    from app.modules.settings.service import tenant_timezone, timezone_of

    with _tenant_session(app_url, tenant_com_fuso) as s:
        assert timezone_of(s, tenant_com_fuso) == FUSO_DO_TENANT
        assert tenant_timezone(s) == FUSO_DO_TENANT


def test_tenant_sem_perfil_cai_no_padrao_sem_levantar(app_url: str):
    """Fail-safe preservado: fuso ausente NUNCA derruba uma request de login."""
    from app.core.tz import DEFAULT_TENANT_TIMEZONE
    from app.modules.auth.models import Tenant
    from app.modules.settings.service import timezone_of

    tenant_id = str(uuid4())
    with _raw_session(app_url) as s:
        s.add(
            Tenant(
                id=tenant_id, slug=f"sem-perfil-{tenant_id[:8]}",
                legal_name="Sem Perfil ME", document="11444777000161",
            )
        )
        s.commit()
        assert timezone_of(s, tenant_id) == DEFAULT_TENANT_TIMEZONE


def test_tenant_inexistente_cai_no_padrao(app_url: str):
    from app.core.tz import DEFAULT_TENANT_TIMEZONE
    from app.modules.settings.service import timezone_of

    with _raw_session(app_url) as s:
        assert timezone_of(s, str(uuid4())) == DEFAULT_TENANT_TIMEZONE


def test_o_fuso_NAO_atravessa_tenants(app_url: str, tenant_com_fuso: str):
    """`tenants` é global e sem RLS: a leitura por id precisa continuar sendo POR ID.

    Sem o filtro explícito, mover o fuso para uma tabela global trocaria um bug de fuso por um
    vazamento entre tenants — que é infinitamente pior."""
    from app.core.tz import DEFAULT_TENANT_TIMEZONE
    from app.modules.auth.models import Tenant
    from app.modules.settings.service import timezone_of

    outro = str(uuid4())
    with _raw_session(app_url) as s:
        s.add(
            Tenant(
                id=outro, slug=f"outro-{outro[:8]}",
                legal_name="Outro ME", document="11444777000161",
            )
        )
        s.commit()
        assert timezone_of(s, outro) == DEFAULT_TENANT_TIMEZONE
        assert timezone_of(s, tenant_com_fuso) == FUSO_DO_TENANT
