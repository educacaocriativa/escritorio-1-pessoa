"""Teste e2e de isolamento cross-tenant do template de WhatsApp no Postgres REAL (IV2).

Valida, sob RLS real (papel NÃO-superusuário `e1p_app`, que NÃO faz bypass de RLS):
- o template de A é invisível para B (`db.get` sob a ótica de B → None → 404 fail-closed em
  sync/delete);
- `list_templates` de B nunca inclui o template de A.

Mesmo bootstrap/padrão de `test_cost_centers_rls.py`/`test_rls_isolation.py`. Módulo marcado
`rls_e2e`: NÃO roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI
(`cross-tenant-rls`) ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

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


def _seed_template(app_url: str, tenant_id: str, *, name: str) -> str:
    """Cria, sob a GUC do próprio tenant, um WhatsappTemplate. Retorna o id."""
    from app.modules.whatsapp_templates.models import WhatsappTemplate

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
            tpl = WhatsappTemplate(
                tenant_id=tenant_id, name=name, language="pt_BR", category_requested="UTILITY",
                status="APPROVED", meta_template_id=f"meta-{name}", body_text="Olá!",
                variable_count=0, variable_examples=[],
            )
            session.add(tpl)
            session.commit()
            tpl_id = tpl.id
            session.close()
            return tpl_id
    finally:
        engine.dispose()


def _visible_names(app_url: str, tenant_id: str) -> list[str]:
    """Lista os templates visíveis sob a ótica de `tenant_id` (equivalente a
    `service.list_templates`, sem filtro manual — a RLS é quem decide)."""
    from app.modules.whatsapp_templates import service

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            names = [t.name for t in service.list_templates(session, tenant_id)]
            session.close()
            return names
    finally:
        engine.dispose()


def _get_visible(app_url: str, tenant_id: str, template_id: str) -> bool:
    """True se `template_id` é visível (existe) sob a ótica de `tenant_id`."""
    from app.modules.whatsapp_templates.models import WhatsappTemplate

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            visible = session.get(WhatsappTemplate, template_id) is not None
            session.close()
            return visible
    finally:
        engine.dispose()


def test_whatsapp_template_cross_tenant_a_nao_ve_b() -> None:
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
        tpl_a = _seed_template(app_url, tenant_a, name="tpl_a")
        tpl_b = _seed_template(app_url, tenant_b, name="tpl_b")

        # Listagem: cada tenant só enxerga o próprio template.
        assert _visible_names(app_url, tenant_a) == ["tpl_a"], (
            "RLS falhou: listagem de A mostrou template de B"
        )
        assert _visible_names(app_url, tenant_b) == ["tpl_b"], (
            "RLS falhou: listagem de B mostrou template de A"
        )

        # Get direto por id: o template de B é INVISÍVEL para A (base do 404 fail-closed em
        # sync/delete) e vice-versa.
        assert not _get_visible(app_url, tenant_a, tpl_b), (
            "RLS falhou: A enxergou o template de B via get"
        )
        assert not _get_visible(app_url, tenant_b, tpl_a), (
            "RLS falhou: B enxergou o template de A via get"
        )
        # E cada um continua enxergando o próprio.
        assert _get_visible(app_url, tenant_a, tpl_a)
        assert _get_visible(app_url, tenant_b, tpl_b)
