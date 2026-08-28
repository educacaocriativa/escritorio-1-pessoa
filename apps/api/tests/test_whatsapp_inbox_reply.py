"""Testes dos endpoints autenticados de resposta da inbox (texto/mídia/template).

Nota sobre autenticação: ao contrário do rascunho original do Task 6 (que escrevia direto num
`TENANT_ID` fixo sem passar `Authorization`), o fixture `client` global (`conftest.py`) só
sobrescreve `get_tenant_db`/`get_db` — o `user: CurrentUser = Depends(_guard)` das novas rotas
continua resolvendo `get_current_user` de verdade (token JWT real), mesmo padrão já usado em
`test_crm.py`/`test_settings.py`. Por isso aqui registramos um tenant de verdade via
`/auth/register` e usamos o `tenant_id`/token devolvidos, em vez de um UUID inventado.
"""
import pytest
from fastapi.testclient import TestClient

from app.core import whatsapp
from app.modules.crm.models import Client
from app.modules.settings import service as settings_service
from app.modules.whatsapp_inbox.models import DIRECTION_IN, WhatsappChat, WhatsappMessage
from app.modules.whatsapp_templates.models import STATUS_APPROVED, WhatsappTemplate

REGISTER = {
    "legal_name": "Inbox SA",
    "document": "11222333000181",
    "slug": "inboxsa",
    "email": "inbox@example.com",
    "name": "In",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def auth(client: TestClient) -> tuple[dict[str, str], str]:
    resp = client.post("/auth/register", json=REGISTER).json()
    headers = {"Authorization": f"Bearer {resp['access_token']}"}
    return headers, resp["tenant"]["id"]


def _configure(db, tenant_id):
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_token = "tok"
    profile.whatsapp_phone_id = "phone-1"
    profile.whatsapp_waba_id = "waba"
    db.commit()



def _chat(db, tenant_id: str, c: Client) -> WhatsappChat:
    """A conversa direta do contato — criada explicitamente porque estes testes inserem as
    linhas na mão, sem passar pelo webhook (que a criaria sozinho a partir do `remoteJid`)."""
    chat = WhatsappChat(
        tenant_id=tenant_id, chat_jid=f"{c.phone}@s.whatsapp.net", kind="direct",
        title=c.name, client_id=c.id,
    )
    db.add(chat)
    db.flush()
    return chat

def test_reply_text_endpoint_requires_open_window(client, db, monkeypatch, auth):
    headers, tenant_id = auth
    _configure(db, tenant_id)
    c = Client(tenant_id=tenant_id, name="Cliente", phone="5511900000001", source="manual")
    db.add(c)
    db.flush()
    chat = _chat(db, tenant_id, c)
    db.commit()
    resp = client.post(
        f"/whatsapp-conversations/{chat.id}/messages/text", json={"text": "oi"}, headers=headers
    )
    assert resp.status_code == 422


def test_reply_text_endpoint_success_within_window(client, db, monkeypatch, auth):
    headers, tenant_id = auth
    _configure(db, tenant_id)
    c = Client(tenant_id=tenant_id, name="Cliente", phone="5511900000002", source="manual")
    db.add(c)
    db.flush()
    chat = _chat(db, tenant_id, c)
    db.add(WhatsappMessage(
        tenant_id=tenant_id, client_id=c.id, chat_id=chat.id, direction=DIRECTION_IN,
        kind="text", text_body="oi",
    ))
    db.commit()
    monkeypatch.setattr(whatsapp, "send_text", lambda **_kw: "sent")
    resp = client.post(
        f"/whatsapp-conversations/{chat.id}/messages/text",
        json={"text": "Olá, tudo bem?"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"


def test_start_conversation_endpoint_evolution_success(client, db, monkeypatch, auth):
    headers, tenant_id = auth
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_provider = "evolution"
    db.commit()
    c = Client(tenant_id=tenant_id, name="Cliente", phone="5511900000004", source="manual")
    db.add(c)
    db.commit()
    monkeypatch.setattr(whatsapp, "send_text", lambda **_kw: "sent")
    resp = client.post(
        "/whatsapp-conversations/start",
        json={"client_id": c.id, "text": "Oi! Bem-vindo."},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "sent"
    assert body["chat_id"]


def test_start_conversation_endpoint_rejects_meta(client, db, monkeypatch, auth):
    headers, tenant_id = auth
    _configure(db, tenant_id)
    c = Client(tenant_id=tenant_id, name="Cliente", phone="5511900000005", source="manual")
    db.add(c)
    db.commit()
    resp = client.post(
        "/whatsapp-conversations/start",
        json={"client_id": c.id, "text": "Oi!"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_reply_template_endpoint_success(client, db, monkeypatch, auth):
    headers, tenant_id = auth
    _configure(db, tenant_id)
    c = Client(tenant_id=tenant_id, name="Cliente", phone="5511900000003", source="manual")
    tpl = WhatsappTemplate(
        tenant_id=tenant_id, name="cardapio", language="pt_BR", category_requested="UTILITY",
        status=STATUS_APPROVED, body_text="Olá {{1}}, segue nosso cardápio!", variable_count=1,
        variable_examples=["Nome"],
    )
    db.add(c)
    db.add(tpl)
    db.flush()
    chat = _chat(db, tenant_id, c)
    db.commit()
    monkeypatch.setattr(whatsapp, "send_template", lambda **_kw: "sent")
    resp = client.post(
        f"/whatsapp-conversations/{chat.id}/messages/template",
        json={"template_id": tpl.id, "variables": ["Fulano"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "Fulano" in resp.json()["text_body"]
