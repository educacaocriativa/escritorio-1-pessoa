"""Testes do webhook público de WhatsApp: handshake de verificação + recebimento de mensagem."""
import hashlib
import hmac
import json

from sqlalchemy import select

from app.modules.whatsapp_inbox.models import PublicWhatsappAccount, WhatsappMessage


def _seed_account(db, *, phone_number_id="phone-123", tenant_id="t-1", app_secret="shh",
                   verify_token="verify-me"):
    db.add(PublicWhatsappAccount(
        phone_number_id=phone_number_id, tenant_id=tenant_id, app_secret=app_secret,
        verify_token=verify_token,
    ))
    db.commit()


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_verification_handshake_success(client, db):
    _seed_account(db)
    resp = client.get(
        "/public/whatsapp/webhook",
        params={
            "hub.mode": "subscribe", "hub.verify_token": "verify-me",
            "hub.challenge": "challenge-xyz",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "challenge-xyz"


def test_webhook_verification_handshake_wrong_token(client, db):
    _seed_account(db)
    resp = client.get(
        "/public/whatsapp/webhook",
        params={
            "hub.mode": "subscribe", "hub.verify_token": "token-errado",
            "hub.challenge": "challenge-xyz",
        },
    )
    assert resp.status_code == 403


def test_webhook_post_creates_message_with_valid_signature(client, db):
    _seed_account(db, phone_number_id="phone-abc", tenant_id="t-2", app_secret="segredo-2")
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "phone-abc"},
                    "contacts": [{"profile": {"name": "Cliente Teste"}, "wa_id": "5511900000000"}],
                    "messages": [{
                        "from": "5511900000000", "id": "wamid.test1", "type": "text",
                        "text": {"body": "Olá!"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode()
    sig = _sign(body, "segredo-2")
    resp = client.post(
        "/public/whatsapp/webhook", content=body,
        headers={"content-type": "application/json", "x-hub-signature-256": sig},
    )
    assert resp.status_code == 200
    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.test1"))
    assert msg is not None
    assert msg.text_body == "Olá!"


def test_webhook_post_rejects_invalid_signature(client, db):
    _seed_account(db, phone_number_id="phone-def", tenant_id="t-3", app_secret="segredo-3")
    payload = {"entry": []}
    body = json.dumps(payload).encode()
    resp = client.post(
        "/public/whatsapp/webhook", content=body,
        headers={"content-type": "application/json", "x-hub-signature-256": "sha256=invalido"},
    )
    assert resp.status_code == 403


def test_webhook_post_rejects_malformed_json(client, db):
    # JSON malformado falha no parse antes mesmo de extrair phone_number_id — não dá pra
    # resolver a conta nem calcular assinatura correta, então nem uma assinatura válida
    # evitaria o 400 aqui (a checagem de JSON acontece primeiro).
    resp = client.post(
        "/public/whatsapp/webhook", content=b"isto nao e json{{{",
        headers={"content-type": "application/json", "x-hub-signature-256": "sha256=irrelevante"},
    )
    assert resp.status_code == 400


def test_webhook_post_rejects_unknown_phone_number_id(client, db):
    payload = {
        "entry": [{
            "changes": [{
                "value": {"metadata": {"phone_number_id": "numero-desconhecido"}, "messages": []},
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode()
    resp = client.post(
        "/public/whatsapp/webhook", content=body,
        headers={"content-type": "application/json", "x-hub-signature-256": "sha256=irrelevante"},
    )
    assert resp.status_code == 404
