"""Testes do auto-enroll: assinante `crm.client.created` -> `engine.enroll` no funil padrão
do tenant (ver `app/modules/funnels/automation.py`).
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.auth.models import Tenant, User
from app.modules.crm.models import Client
from app.modules.funnels import automation
from app.modules.funnels.models import Funnel, FunnelRun
from app.modules.settings.models import TenantProfile


def _seed_tenant(db: Session, *, slug: str, document: str) -> Tenant:
    tenant = Tenant(slug=slug, legal_name="Auto SA", document=document)
    db.add(tenant)
    db.flush()
    db.add(User(
        tenant_id=tenant.id, email=f"{slug}@example.com", name="Dono",
        password_hash=hash_password("senha-bem-grande"), role="owner",
    ))
    db.commit()
    return tenant


def _seed_funnel(db: Session, tenant_id: str) -> Funnel:
    f = Funnel(tenant_id=tenant_id, name="Entrada", nodes=[{"id": "n1"}], edges=[])
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


@pytest.fixture()
def _fake_session(db: Session, monkeypatch):
    @contextmanager
    def _factory(_tenant_id):
        yield db

    monkeypatch.setattr(automation, "tenant_session", _factory)


def _run_for(db: Session, client_id: str) -> FunnelRun | None:
    return db.scalar(select(FunnelRun).where(FunnelRun.client_id == client_id))


def test_auto_enrolls_landing_lead_when_funnel_configured(db: Session, _fake_session):
    tenant = _seed_tenant(db, slug="auto1", document="00000000000101")
    funnel = _seed_funnel(db, tenant.id)
    db.add(TenantProfile(tenant_id=tenant.id, default_entry_funnel_id=funnel.id))
    client = Client(tenant_id=tenant.id, name="Lead Externo", source="landing")
    db.add(client)
    db.commit()

    automation.on_client_created(tenant_id=tenant.id, client_id=client.id, source="landing")

    run = _run_for(db, client.id)
    assert run is not None
    assert run.funnel_id == funnel.id


def test_auto_enrolls_api_lead_when_funnel_configured(db: Session, _fake_session):
    tenant = _seed_tenant(db, slug="auto2", document="00000000000102")
    funnel = _seed_funnel(db, tenant.id)
    db.add(TenantProfile(tenant_id=tenant.id, default_entry_funnel_id=funnel.id))
    client = Client(tenant_id=tenant.id, name="Lead API", source="api")
    db.add(client)
    db.commit()

    automation.on_client_created(tenant_id=tenant.id, client_id=client.id, source="api")

    assert _run_for(db, client.id) is not None


def test_no_enroll_when_no_default_funnel_configured(db: Session, _fake_session):
    tenant = _seed_tenant(db, slug="auto3", document="00000000000103")
    client = Client(tenant_id=tenant.id, name="Lead Sem Funil", source="landing")
    db.add(client)
    db.commit()

    automation.on_client_created(tenant_id=tenant.id, client_id=client.id, source="landing")

    assert _run_for(db, client.id) is None


@pytest.mark.parametrize("source", ["manual", "import", "ai"])
def test_no_enroll_for_non_automated_sources(db: Session, _fake_session, source):
    tenant = _seed_tenant(db, slug=f"auto-{source}", document=f"0000000000020{source[0]}")
    funnel = _seed_funnel(db, tenant.id)
    db.add(TenantProfile(tenant_id=tenant.id, default_entry_funnel_id=funnel.id))
    client = Client(tenant_id=tenant.id, name="X", source=source)
    db.add(client)
    db.commit()

    automation.on_client_created(tenant_id=tenant.id, client_id=client.id, source=source)

    assert _run_for(db, client.id) is None


def test_deleted_or_invalid_funnel_does_not_raise(db: Session, _fake_session):
    tenant = _seed_tenant(db, slug="auto4", document="00000000000104")
    db.add(TenantProfile(tenant_id=tenant.id, default_entry_funnel_id="nao-existe"))
    client = Client(tenant_id=tenant.id, name="X", source="api")
    db.add(client)
    db.commit()

    # não deve levantar FunnelError — só loga e segue (não pode derrubar quem criou o lead)
    automation.on_client_created(tenant_id=tenant.id, client_id=client.id, source="api")

    assert _run_for(db, client.id) is None
