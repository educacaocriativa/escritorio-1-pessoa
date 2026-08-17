"""O backfill da 0079 e a aplicação do status, sob Postgres real com FORCE ROW LEVEL SECURITY.

Dois enganos que a suíte SQLite deixa passar inteiros:

1. O backfill da 0079 lê `tenant_profiles` (RLS). Sem a janela DISABLE/ENABLE+FORCE, o UPDATE
   é filtrado a ZERO LINHAS em silêncio — todo tenant já configurado ficaria de fora do
   roteamento por WABA e o webhook responderia 404 pra sempre, sem erro em lugar nenhum.
2. `apply_status_events` não filtra por tenant_id (Regra de Ouro nº 1). Se a RLS não estiver
   isolando de fato, um evento aprovaria o template homônimo de OUTRO tenant.

Cada asserção vem com o controle positivo ao lado, pelo mesmo motivo do
`test_auth_timezone_rls.py`: provar que ela falha pelo motivo certo, e não porque o dado nem
chegou a ser gravado.

O teste do backfill roda as migrations em DUAS etapas (`0078`, depois `0079`) — sem isso não
existiria linha nenhuma no momento do backfill, e ele passaria mesmo com a janela removida.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

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


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _migrar_ate(app_url: str, revision: str) -> None:
    """Roda as migrations como `e1p_app` — o papel NÃO-superusuário, SEM a GUC de tenant. É
    exatamente assim que elas rodam em produção, e é por isso que a janela de RLS importa."""
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, revision)
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
    """Sessão SEM tenant — exatamente o que o webhook público usa (`get_db`)."""
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


@contextmanager
def _container_migrado_ate(revision: str):
    with PostgresContainer("postgres:16-alpine", dbname=_DB_NAME) as pg:
        super_url = pg.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+psycopg://"
        )
        _bootstrap_rls_role(super_url)
        host = super_url.split("@", 1)[1]
        url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}"
        _migrar_ate(url, revision)
        yield url


@pytest.fixture(scope="module")
def app_url():
    """Banco no head — para o teste de isolamento."""
    with _container_migrado_ate("head") as url:
        yield url


def _criar_tenant(session: Session, tenant_id: str, slug: str) -> None:
    from app.modules.auth.models import Tenant

    session.add(Tenant(
        id=tenant_id, slug=slug, legal_name=f"Empresa {slug}", document="61616161000107",
    ))
    session.commit()


def _criar_template(db: Session, *, tenant_id: str, meta_template_id: str) -> str:
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    tpl = WhatsappTemplate(
        tenant_id=tenant_id, name="lembrete", language="pt_BR", category_requested="UTILITY",
        body_text="Olá {{1}}", variable_count=1, variable_examples=["Maria"],
        status="PENDING", meta_template_id=meta_template_id,
    )
    db.add(tpl)
    db.commit()
    return tpl.id


def test_backfill_da_0079_preenche_waba_id_de_quem_ja_estava_configurado():
    """Container PRÓPRIO, parado na 0078: precisa existir linha ANTES do backfill rodar.

    É esta asserção que morre se alguém remover a janela de RLS da migration — e ela morre do
    jeito certo: `waba_id` volta NULL, sem erro nenhum, exatamente como aconteceria em
    produção.
    """
    from app.modules.settings.models import TenantProfile

    with _container_migrado_ate("0078") as url:
        # `tenants` não tem RLS; `tenant_profiles` tem — por isso o perfil é criado numa sessão
        # COM a GUC, pelo mesmo caminho que a aplicação usa.
        with _raw_session(url) as raw:
            _criar_tenant(raw, "t-backfill", "backfill")

        with _tenant_session(url, "t-backfill") as tdb:
            tdb.add(TenantProfile(
                tenant_id="t-backfill",
                whatsapp_token="tok", whatsapp_phone_id="phone-1",
                whatsapp_waba_id="waba-real", whatsapp_app_secret="segredo",
                whatsapp_verify_token="verify-1",
            ))
            tdb.commit()

        # O snapshot global existe desde a 0054 — mas SEM a coluna `waba_id`, que só nasce na
        # 0079. Por isso ele é inserido aqui via SQL crua, com as colunas de então.
        with _raw_session(url) as raw:
            raw.execute(text(
                "INSERT INTO public_whatsapp_accounts "
                "(phone_number_id, tenant_id, app_secret, verify_token) "
                "VALUES ('phone-1', 't-backfill', 'segredo', 'verify-1')"
            ))
            raw.commit()

        _migrar_ate(url, "0079")

        # Sessão CRUA de propósito: é como o webhook lê essa tabela, sem tenant nenhum. Leitura
        # por SQL (e não pelo ORM) para não passar `app_secret` pelo decifrador — o INSERT
        # acima gravou texto puro, e o que está sob teste aqui é o backfill, não a cifra.
        with _raw_session(url) as raw:
            waba = raw.execute(text(
                "SELECT waba_id FROM public_whatsapp_accounts WHERE phone_number_id='phone-1'"
            )).scalar()
            assert waba == "waba-real", (
                "o backfill não enxergou `tenant_profiles` — a janela de RLS da 0079 sumiu"
            )


def test_evento_nao_aprova_template_de_outro_tenant(app_url):
    """`apply_status_events` NÃO filtra por tenant_id — quem isola é a RLS. Se a policy não
    estiver valendo, o evento do tenant A aprova o template homônimo do tenant B: a Meta não
    garante `meta_template_id` único entre WABAs diferentes."""
    from app.core.whatsapp.providers.meta import TemplateStatusEvent
    from app.modules.whatsapp_templates import service
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    with _raw_session(app_url) as raw:
        _criar_tenant(raw, "t-A", "tenant-a")
        _criar_tenant(raw, "t-B", "tenant-b")

    with _tenant_session(app_url, "t-A") as db_a:
        id_a = _criar_template(db_a, tenant_id="t-A", meta_template_id="777")
    with _tenant_session(app_url, "t-B") as db_b:
        id_b = _criar_template(db_b, tenant_id="t-B", meta_template_id="777")

    with _tenant_session(app_url, "t-A") as db_a:
        aplicados = service.apply_status_events(
            db_a, tenant_id="t-A",
            events=[TemplateStatusEvent(
                meta_template_id="777", status="APPROVED", rejected_reason=None,
                category="UTILITY",
            )],
        )
        assert aplicados == 1

    # Controle positivo: em A mudou de fato (senão o assert de B abaixo passaria por nada ter
    # acontecido, e não por isolamento).
    with _tenant_session(app_url, "t-A") as db_a:
        assert db_a.get(WhatsappTemplate, id_a).status == "APPROVED"

    with _tenant_session(app_url, "t-B") as db_b:
        assert db_b.get(WhatsappTemplate, id_b).status == "PENDING", (
            "o evento do tenant A tocou o template do tenant B — a RLS não isolou"
        )
