"""Testes do freio anti-ban (Onda 3 §7) — só para tenants no transporte Evolution. Resposta a
quem escreveu primeiro (inbox) não passa por aqui — o freio vive só em process_pending."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core import whatsapp
from app.modules.notifications import service
from app.modules.settings import service as settings_service
from app.modules.whatsapp_session.models import PublicWhatsappInstance

TENANT_ID = "44444444-4444-4444-4444-444444444444"


def _evolution_tenant(db, *, connected_days_ago: int = 30):
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_provider = "evolution"
    instance = PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connected",
    )
    db.add(instance)
    db.commit()
    # `created_at` do TimestampMixin tem server_default=now() — sobrescreve pra simular
    # conexão antiga (aquecimento já passado).
    instance.created_at = datetime.now(UTC) - timedelta(days=connected_days_ago)
    db.commit()
    return profile, instance


def _enqueue_n(db, n: int, *, message_prefix="msg"):
    for i in range(n):
        service.enqueue(
            db, tenant_id=TENANT_ID, channel="whatsapp", recipient=f"55{i:011d}",
            message=f"{message_prefix}-{i}",
        )
    db.commit()


def test_evolution_tenant_respects_max_per_sweep(db, monkeypatch: pytest.MonkeyPatch) -> None:
    _evolution_tenant(db)
    _enqueue_n(db, 8)
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    processed = service.process_pending(db, tenant_id=TENANT_ID)
    assert processed <= 5  # teto por sweep, spec §7


def test_meta_tenant_is_not_throttled(db, monkeypatch: pytest.MonkeyPatch) -> None:
    # Sem instância Evolution — profile.whatsapp_provider permanece None/"meta". Sem freio.
    _enqueue_n(db, 8)
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    processed = service.process_pending(db, tenant_id=TENANT_ID)
    assert processed == 8  # nenhum teto — só Evolution é limitado


def test_evolution_tenant_respects_daily_cap_for_new_connection(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _evolution_tenant(db, connected_days_ago=1)  # 1-3 dias = teto 20/dia (spec §7)
    _enqueue_n(db, 25)
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    total_delivered = 0
    for _ in range(10):  # múltiplos sweeps — o teto é DIÁRIO, não por sweep
        total_delivered += service.process_pending(db, tenant_id=TENANT_ID)
    assert total_delivered <= 20


def test_inbox_reply_does_not_count_toward_daily_cap(db) -> None:
    """O freio vive só em process_pending — enviar pelo inbox (síncrono, resposta a quem
    escreveu primeiro) não incrementa o contador diário. Este teste apenas documenta a garantia
    estrutural: `send_reply_text` (whatsapp_inbox) não importa nem chama nada deste módulo de
    throttle — não há acoplamento a testar além de "o módulo de throttle não é importado lá"."""
    import ast
    from pathlib import Path

    inbox_service_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "modules" / "whatsapp_inbox" / "service.py"
    )
    tree = ast.parse(inbox_service_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "app.modules.notifications.service" not in imported_modules
