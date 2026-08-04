"""Testes da validade por propósito em notifications.service::enqueue (Onda 3 — fila com
validade). Ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §7."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.notifications import service
from app.modules.settings import service as settings_service

TENANT_ID = "33333333-3333-3333-3333-333333333333"


def test_enqueue_without_purpose_never_expires(db) -> None:
    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="oi",
    )
    db.commit()
    assert n.expires_at is None


def test_enqueue_money_purpose_expires_end_of_tenant_day(db) -> None:
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.timezone = "America/Sao_Paulo"
    db.commit()

    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="cobranca",
        purpose="charge_reminder",
    )
    db.commit()
    assert n.expires_at is not None
    # 23:59:59 em America/Sao_Paulo (UTC-3) = 02:59:59 do dia seguinte em UTC.
    assert n.expires_at.hour == 2
    assert n.expires_at.minute == 59
    assert n.expires_at.tzinfo is not None


def test_enqueue_operational_purpose_expires_in_one_hour(db) -> None:
    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="card movido",
        purpose="client_moved",
    )
    db.commit()
    now = datetime.now(UTC)
    assert n.expires_at is not None
    delta = n.expires_at - now
    assert timedelta(minutes=55) < delta < timedelta(minutes=65)


def test_enqueue_funnel_node_purpose_expires_in_one_hour(db) -> None:
    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="promo",
        purpose="funnel_node",
    )
    db.commit()
    now = datetime.now(UTC)
    delta = n.expires_at - now
    assert timedelta(minutes=55) < delta < timedelta(minutes=65)
