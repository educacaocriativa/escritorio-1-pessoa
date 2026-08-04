"""Testes de POST /internal/whatsapp/evolution/webhook/{webhook_secret} (Onda 3 §6)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.crm.models import Client
from app.modules.settings import service as settings_service
from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import WhatsappChat, WhatsappMessage
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


# ── Autoria: `key.fromMe` distingue quem escreveu ────────────────────────────
# O Baileys espelha no MESMO evento `messages.upsert` tanto o que o contato mandou quanto o que
# o dono digitou no WhatsApp do celular dele. O ingest fixava `direction="in"` para tudo, então
# a tela de Conversas mostrava as duas pontas como se fossem do cliente.

def _instancia(db, secret: str) -> None:
    settings_service.get_profile(db, TENANT_ID)
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret=secret,
        last_status="connected",
    ))
    db.commit()


def _fromme_payload(msg_id: str, text: str) -> dict:
    return {
        "data": {
            "key": {"id": msg_id, "remoteJid": "5511988887777@s.whatsapp.net", "fromMe": True},
            "pushName": "Nome Do Dono",
            "message": {"conversation": text},
        }
    }


def test_webhook_from_me_message_is_stored_as_outbound(client: TestClient, db) -> None:
    _instancia(db, "segredo-fromme")

    assert client.post(
        "/internal/whatsapp/evolution/webhook/segredo-fromme",
        json=_fromme_payload("3EB0MINE", "Ok, fechado"),
    ).status_code == 200

    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "3EB0MINE"))
    assert msg is not None
    assert msg.direction == "out"
    assert msg.text_body == "Ok, fechado"


def test_webhook_from_me_does_not_name_client_after_the_owner(client: TestClient, db) -> None:
    """`pushName` numa mensagem espelhada é o do PRÓPRIO DONO — não pode virar o nome do
    cliente recém-criado (o contato ainda é desconhecido nesta primeira mensagem)."""
    _instancia(db, "segredo-nome")

    assert client.post(
        "/internal/whatsapp/evolution/webhook/segredo-nome",
        json=_fromme_payload("3EB0NOME", "Oi, tudo bem?"),
    ).status_code == 200

    contato = db.scalar(select(Client).where(Client.phone == "5511988887777"))
    assert contato is not None
    assert contato.name != "Nome Do Dono"
    assert contato.name == "5511988887777"  # cai no telefone enquanto não sabemos o nome


def test_webhook_from_me_does_not_open_the_24h_window(client: TestClient, db) -> None:
    """A janela de 24h é reaberta pelo CLIENTE, nunca por nós: com o ingest antigo, uma
    mensagem que o dono mandou do celular reabria a janela e liberava resposta livre onde a
    Meta exigiria template."""
    _instancia(db, "segredo-janela")

    assert client.post(
        "/internal/whatsapp/evolution/webhook/segredo-janela",
        json=_fromme_payload("3EB0JANELA", "Alguma novidade?"),
    ).status_code == 200

    chat = db.scalar(
        select(WhatsappChat).where(WhatsappChat.chat_jid == "5511988887777@s.whatsapp.net")
    )
    assert chat is not None
    assert inbox_service.is_within_session_window(db, chat_id=chat.id) is False
