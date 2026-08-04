"""Testes de POST /internal/whatsapp/evolution/webhook/{webhook_secret} (Onda 3 §6)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.modules.settings import service as settings_service
from app.modules.whatsapp_session.models import PublicWhatsappInstance

TENANT_ID = "66666666-6666-6666-6666-666666666666"

EVOLUTION_PAYLOAD = {
    "data": {
        "key": {"id": "3EB0XYZ", "remoteJid": "5511988887777@s.whatsapp.net"},
        "pushName": "Cliente Teste",
        "message": {"conversation": "Oi, preciso de ajuda"},
    }
}


def test_webhook_creates_lead_and_message(client: TestClient, db) -> None:
    settings_service.get_profile(db, TENANT_ID)
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="segredo-123",
        last_status="connected",
    ))
    db.commit()

    resp = client.post(
        "/internal/whatsapp/evolution/webhook/segredo-123", json=EVOLUTION_PAYLOAD,
    )
    assert resp.status_code == 200


def test_webhook_unknown_secret_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/internal/whatsapp/evolution/webhook/segredo-que-nao-existe", json=EVOLUTION_PAYLOAD,
    )
    assert resp.status_code == 404


def test_webhook_lid_message_lands_in_unidentified_bucket(client: TestClient, db) -> None:
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="segredo-456",
        last_status="connected",
    ))
    db.commit()
    lid_payload = {
        "data": {
            "key": {"id": "3EB0LID", "remoteJid": "999999@lid"},
            "pushName": "Sem Numero",
            "message": {"conversation": "Oi"},
        }
    }
    resp = client.post(
        "/internal/whatsapp/evolution/webhook/segredo-456", json=lid_payload,
    )
    assert resp.status_code == 200
