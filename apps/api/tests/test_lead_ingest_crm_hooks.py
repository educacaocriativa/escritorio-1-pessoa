"""Ganchos que a ingestão usa no CRM: `find_lead`, `auto_enroll=False`, `jornada_viva`."""
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import events
from app.modules.crm import service as crm_service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.funnels import automation
from app.modules.funnels.models import RUN_WAITING, Funnel, FunnelRun
from app.modules.settings.models import TenantProfile

TENANT = "tenant-nexus-0001"


@pytest.fixture()
def emitidos():
    events.clear()
    capturados: list[tuple[str, dict]] = []
    for nome in (crm_service.EVENT_CLIENT_CREATED, crm_service.EVENT_CLIENT_RETURNED):
        events.subscribe(nome, lambda _nome=nome, **p: capturados.append((_nome, p)))
    yield capturados
    events.clear()


@pytest.fixture()
def _fake_session(db: Session, monkeypatch):
    @contextmanager
    def _factory(_tenant_id):
        yield db

    monkeypatch.setattr(automation, "tenant_session", _factory)


def _absorve(db: Session, **kw):
    return crm_service.absorb_lead(
        db, tenant_id=TENANT, actor="teste",
        data=ClientCreate(name="Maria", email="maria@exemplo.gov.br", source="api"), **kw,
    )


def _funil_padrao(db: Session) -> Funnel:
    funil = Funnel(tenant_id=TENANT, name="Entrada", nodes=[{"id": "n1"}], edges=[])
    db.add(funil)
    db.commit()
    db.add(TenantProfile(tenant_id=TENANT, default_entry_funnel_id=funil.id))
    db.commit()
    return funil


def test_padrao_continua_emitindo_auto_enroll_verdadeiro(db: Session, emitidos):
    _absorve(db)
    assert [nome for nome, _ in emitidos] == [crm_service.EVENT_CLIENT_CREATED]
    assert emitidos[0][1]["auto_enroll"] is True


def test_auto_enroll_falso_viaja_na_criacao_e_no_retorno(db: Session, emitidos):
    _absorve(db, auto_enroll=False)
    _absorve(db, auto_enroll=False)
    assert [(nome, p["auto_enroll"]) for nome, p in emitidos] == [
        (crm_service.EVENT_CLIENT_CREATED, False),
        (crm_service.EVENT_CLIENT_RETURNED, False),
    ]


def test_automacao_respeita_auto_enroll_falso(db: Session, _fake_session):
    _funil_padrao(db)
    contato = Client(tenant_id=TENANT, name="Lead API", source="api")
    db.add(contato)
    db.commit()
    automation.on_client_created(
        tenant_id=TENANT, client_id=contato.id, source="api", auto_enroll=False
    )
    automation.on_client_returned(
        tenant_id=TENANT, client_id=contato.id, source="api", auto_enroll=False
    )
    assert db.scalar(select(FunnelRun).where(FunnelRun.client_id == contato.id)) is None


def test_find_lead_acha_por_telefone_em_outro_formato_e_por_email_sem_caixa(db: Session):
    contato = Client(
        tenant_id=TENANT, name="Maria", email="Maria@Exemplo.gov.br",
        phone="(11) 99999-8888", phone_key="5511999998888", source="api",
    )
    db.add(contato)
    db.commit()
    assert crm_service.find_lead(db, phone="5511999998888", email=None).id == contato.id
    assert crm_service.find_lead(db, phone=None, email="maria@exemplo.gov.br").id == contato.id
    assert crm_service.find_lead(db, phone="(21) 98888-7777", email="outra@x.com") is None


def test_jornada_viva_e_publica_e_ve_espera(db: Session):
    run = FunnelRun(
        tenant_id=TENANT, funnel_id="f-1", client_id="c-1", status=RUN_WAITING, steps=[]
    )
    db.add(run)
    db.commit()
    assert automation.jornada_viva(db, funnel_id="f-1", client_id="c-1") is True
    assert automation.jornada_viva(db, funnel_id="f-1", client_id="c-2") is False
