"""Testes do seed de dados SINTÉTICOS de staging (Story 3.1).

Cobre:
- gate seguro: com `SEED_SYNTHETIC_DATA=false` (default) NADA é criado (no-op);
- com a flag True, o tenant `staging-demo` + owner + registros mínimos de negócio existem;
- idempotência: rodar 2x não duplica nada.

Mesmo padrão de `test_seed.py`: SQLite em memória (StaticPool) plugado no `SessionLocal` do
módulo. Como `seed_staging` também usa `tenant_session` (RLS no Postgres real) para as tabelas
de negócio, monkeypatchamos esse helper por um contexto que devolve a MESMA sessão de teste —
o SQLite não tem RLS, então uma sessão simples basta para exercitar a lógica de seed.
"""
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.seed_staging as seed_staging
from app.config import settings
from app.db.registry import Base
from app.modules.agenda.models import AgendaEvent
from app.modules.auth.models import Tenant, User
from app.modules.crm.models import Client, PipelineStage
from app.modules.receivables.models import Charge


@pytest.fixture()
def staging_session(monkeypatch):
    """SQLite em memória compartilhado, plugado no SessionLocal E no tenant_session do módulo."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(seed_staging, "SessionLocal", TestSession)

    @contextmanager
    def fake_tenant_session(_tenant_id):
        db = TestSession()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    monkeypatch.setattr(seed_staging, "tenant_session", fake_tenant_session)
    try:
        yield TestSession
    finally:
        Base.metadata.drop_all(engine)


def _counts(session_factory) -> dict[str, int]:
    with session_factory() as db:
        return {
            "tenants": len(
                db.scalars(
                    select(Tenant).where(Tenant.slug == seed_staging.STAGING_TENANT_SLUG)
                ).all()
            ),
            "owners": len(
                db.scalars(select(User).where(User.email == seed_staging.STAGING_OWNER_EMAIL)).all()
            ),
            "clients": len(
                db.scalars(
                    select(Client).where(Client.email == seed_staging.STAGING_CLIENT_EMAIL)
                ).all()
            ),
            "events": len(
                db.scalars(
                    select(AgendaEvent).where(
                        AgendaEvent.external_ref == seed_staging.STAGING_EVENT_REF
                    )
                ).all()
            ),
            "charges": len(
                db.scalars(
                    select(Charge).where(Charge.external_ref == seed_staging.STAGING_CHARGE_REF)
                ).all()
            ),
        }


def test_noop_when_flag_disabled(staging_session, monkeypatch):
    # Default seguro: sem a flag, o boot de produção NÃO cria nada sintético.
    monkeypatch.setattr(settings, "seed_synthetic_data", False)
    seed_staging.seed_synthetic_data()

    counts = _counts(staging_session)
    assert counts == {"tenants": 0, "owners": 0, "clients": 0, "events": 0, "charges": 0}


def test_creates_synthetic_data_when_enabled(staging_session, monkeypatch):
    monkeypatch.setattr(settings, "seed_synthetic_data", True)
    seed_staging.seed_synthetic_data()

    counts = _counts(staging_session)
    assert counts == {"tenants": 1, "owners": 1, "clients": 1, "events": 1, "charges": 1}

    with staging_session() as db:
        # O funil padrão do CRM foi semeado e o cliente entra na 1ª etapa (aparece no board).
        stages = db.scalars(select(PipelineStage)).all()
        assert len(stages) >= 1
        client = db.scalar(select(Client).where(Client.email == seed_staging.STAGING_CLIENT_EMAIL))
        assert client is not None
        assert client.stage_id is not None
        # A cobrança sintética nasce ligada ao cliente e em aberto (aparece em Contas a Receber).
        charge = db.scalar(
            select(Charge).where(Charge.external_ref == seed_staging.STAGING_CHARGE_REF)
        )
        assert charge is not None
        assert charge.client_id == client.id
        assert charge.status == "open"
        # O owner sintético NÃO força troca de senha (login direto no smoke test).
        owner = db.scalar(select(User).where(User.email == seed_staging.STAGING_OWNER_EMAIL))
        assert owner is not None
        assert owner.must_reset_password is False


def test_is_idempotent(staging_session, monkeypatch):
    monkeypatch.setattr(settings, "seed_synthetic_data", True)
    seed_staging.seed_synthetic_data()
    seed_staging.seed_synthetic_data()  # segunda passada não pode duplicar nem falhar

    counts = _counts(staging_session)
    assert counts == {"tenants": 1, "owners": 1, "clients": 1, "events": 1, "charges": 1}
