"""Testes da Central de Orçamentos — incluindo o efeito dominó (aprovar -> cobrança)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.settings import service as settings_service
from app.modules.whatsapp_templates.models import (
    PURPOSE_QUOTE_SEND,
    STATUS_APPROVED,
    STATUS_PENDING,
    WhatsappTemplate,
)

REGISTER = {
    "legal_name": "Orca Co",
    "document": "18181818000113",
    "slug": "orcaco",
    "email": "orca@example.com",
    "name": "Or",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _template(db: Session, tenant_id: str, *, status: str = STATUS_APPROVED, **overrides):
    tpl = WhatsappTemplate(
        tenant_id=tenant_id, name="orcamento_proposta", language="pt_BR",
        category_requested="UTILITY", category_approved="UTILITY", status=status,
        body_text="Olá {{1}}, segue sua proposta {{2}}: {{3}}. Veja em {{4}}",
        variable_count=4, variable_examples=["Maria", "Consultoria", "R$ 100", "https://x"],
    )
    for k, v in overrides.items():
        setattr(tpl, k, v)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def _quote(**over):
    base = {
        "title": "Consultoria",
        "items": [
            {"description": "Hora técnica", "quantity": 10, "unit_price_cents": 15000},
            {"description": "Relatório", "quantity": 1, "unit_price_cents": 50000},
        ],
        "discount_cents": 0,
    }
    return {**base, **over}


def test_create_computes_totals(client: TestClient, headers):
    resp = client.post("/quotes", json=_quote(), headers=headers)
    assert resp.status_code == 201, resp.text
    q = resp.json()
    assert q["subtotal_cents"] == 200000  # 10*15000 + 50000
    assert q["total_cents"] == 200000
    assert q["status"] == "draft"


def test_discount_applied(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(discount_cents=20000), headers=headers).json()
    assert q["total_cents"] == 180000


def test_requires_at_least_one_item(client: TestClient, headers):
    resp = client.post("/quotes", json=_quote(items=[]), headers=headers)
    assert resp.status_code == 422


def test_send_marks_sent_and_notifies(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Orca"}, headers=headers).json()
    q = client.post("/quotes", json=_quote(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/send", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"
    notifs = client.get("/notifications", headers=headers).json()
    assert any(n["channel"] == "whatsapp" for n in notifs)


def test_send_free_text_uses_tenant_credentials_when_no_template_bound(
    client: TestClient, headers, db: Session, tenant_id: str
):
    """Sem vínculo: texto livre ENFILEIRADO (Onda 3) — a resolução de credenciais do tenant via
    `profile=` acontece depois, na entrega real feita pelo worker."""
    from sqlalchemy import select

    from app.modules.notifications.models import Notification

    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_token = "tok-123"
    profile.whatsapp_phone_id = "phone-456"
    db.commit()

    cl = client.post(
        "/crm/clients", json={"name": "Cliente Orca", "phone": "5511977776666"}, headers=headers
    ).json()
    q = client.post("/quotes", json=_quote(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/send", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"  # status do ORÇAMENTO (workflow), não do envio

    notif = db.scalar(select(Notification).where(Notification.channel == "whatsapp"))
    assert notif is not None
    assert notif.status == "pending"
    assert notif.purpose == PURPOSE_QUOTE_SEND
    assert f"Segue sua proposta de {q['title']}" in notif.message


def test_send_uses_approved_bound_template(
    client: TestClient, headers, db: Session, tenant_id: str
):
    """Com vínculo aprovado, a notificação enfileirada carrega o template (não texto livre) —
    a entrega real (send_template) acontece depois, no worker (Onda 3)."""
    from sqlalchemy import select

    from app.modules.notifications.models import Notification

    tpl = _template(db, tenant_id)
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_token = "tok-abc"
    profile.whatsapp_phone_id = "phone-xyz"
    profile.whatsapp_template_bindings = {PURPOSE_QUOTE_SEND: tpl.id}
    db.commit()

    cl = client.post(
        "/crm/clients", json={"name": "Maria Cliente", "phone": "5511988887777"}, headers=headers
    ).json()
    q = client.post("/quotes", json=_quote(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/send", headers=headers)
    assert resp.status_code == 200

    valor = f"R$ {q['total_cents'] / 100:.2f}".replace(".", ",")
    notif = db.scalar(select(Notification).where(Notification.channel == "whatsapp"))
    assert notif is not None
    assert notif.purpose == PURPOSE_QUOTE_SEND
    assert notif.whatsapp_template_name == tpl.name
    assert notif.whatsapp_template_language == tpl.language
    assert notif.recipient == "5511988887777"
    link = notif.whatsapp_template_variables[3]
    assert notif.whatsapp_template_variables == ["Maria Cliente", q["title"], valor, link]

    expected_msg = f"Olá Maria Cliente, segue sua proposta {q['title']}: {valor}. Veja em {link}"
    assert "{{" not in expected_msg
    assert notif.message == expected_msg


def test_send_falls_back_to_free_text_when_bound_template_not_approved(
    client: TestClient, headers, db: Session, tenant_id: str
):
    from sqlalchemy import select

    from app.modules.notifications.models import Notification

    tpl = _template(db, tenant_id, status=STATUS_PENDING)
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_template_bindings = {PURPOSE_QUOTE_SEND: tpl.id}
    db.commit()

    q = client.post("/quotes", json=_quote(), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/send", headers=headers)
    assert resp.status_code == 200

    notif = db.scalar(select(Notification).where(Notification.channel == "whatsapp"))
    assert notif is not None
    assert notif.whatsapp_template_name is None  # não usou o template ainda pendente
    assert f"Segue sua proposta de {q['title']}" in notif.message


def test_approve_generates_charge(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Orca"}, headers=headers).json()
    q = client.post("/quotes", json=_quote(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/approve", headers=headers)
    assert resp.status_code == 200
    approved = resp.json()
    assert approved["status"] == "approved"
    assert approved["charge_id"]
    # a cobrança foi criada em Contas a Receber pelo valor total
    charges = client.get("/receivables/charges", headers=headers).json()
    assert any(c["amount_cents"] == 200000 for c in charges)


def test_approve_zero_total_rejected(client: TestClient, headers):
    q = client.post(
        "/quotes",
        json={
            "title": "Brinde",
            "items": [{"description": "X", "quantity": 1, "unit_price_cents": 0}],
        },
        headers=headers,
    ).json()
    resp = client.post(f"/quotes/{q['id']}/approve", headers=headers)
    assert resp.status_code == 409  # não 500


def test_reject(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(), headers=headers).json()
    resp = client.post(f"/quotes/{q['id']}/reject", headers=headers)
    assert resp.json()["status"] == "rejected"


def test_cannot_edit_after_sent(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(), headers=headers).json()
    client.post(f"/quotes/{q['id']}/send", headers=headers)
    resp = client.patch(f"/quotes/{q['id']}", json={"title": "Novo"}, headers=headers)
    assert resp.status_code == 409


def test_summary(client: TestClient, headers):
    q1 = client.post("/quotes", json=_quote(), headers=headers).json()
    client.post(f"/quotes/{q1['id']}/approve", headers=headers)
    client.post("/quotes", json=_quote(), headers=headers)  # draft
    s = client.get("/quotes/summary", headers=headers).json()
    assert s["approved_cents"] == 200000
    assert s["draft_count"] == 1


def test_requires_auth(client: TestClient):
    assert client.get("/quotes/summary").status_code == 401


# ── Construtor de proposta + link público ───────────────────────────────────
def test_create_generates_public_slug(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(), headers=headers).json()
    assert q["public_slug"]
    assert q["has_password"] is False


def test_builder_fields_persist(client: TestClient, headers):
    payload = _quote(
        client_name="Maria Cliente",
        payment_terms="50% entrada, 50% na entrega",
        show_schedule=True,
        schedule=[{"title": "Kickoff", "when": "Semana 1", "description": "Alinhamento"}],
        primary_color="#FF0000",
        items=[{"description": "Setup", "subtitle": "inclui suporte", "quantity": 1,
                "unit_price_cents": 100000}],
    )
    q = client.post("/quotes", json=payload, headers=headers).json()
    assert q["client_name"] == "Maria Cliente"
    assert q["payment_terms"].startswith("50%")
    assert q["show_schedule"] is True
    assert q["schedule"][0]["title"] == "Kickoff"
    assert q["primary_color"] == "#FF0000"
    assert q["items"][0]["subtitle"] == "inclui suporte"


def test_public_view(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(client_name="Zé"), headers=headers).json()
    resp = client.get(f"/public/proposals/{q['public_slug']}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["title"] == "Consultoria"
    assert data["total_cents"] == 200000
    assert data["client_name"] == "Zé"


def test_public_view_password_protected(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(link_password="segredo"), headers=headers).json()
    assert client.get(f"/public/proposals/{q['public_slug']}").status_code == 401
    ok = client.get(f"/public/proposals/{q['public_slug']}", params={"password": "segredo"})
    assert ok.status_code == 200


def test_public_view_not_found(client: TestClient):
    assert client.get("/public/proposals/inexistente-xyz").status_code == 404


def test_public_accept_approves_and_charges(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Final"}, headers=headers).json()
    q = client.post("/quotes", json=_quote(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/public/proposals/{q['public_slug']}/accept", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    # o orçamento ficou aprovado e gerou cobrança
    got = client.get(f"/quotes/{q['id']}", headers=headers).json()
    assert got["status"] == "approved"
    charges = client.get("/receivables/charges", headers=headers).json()
    assert any(c["amount_cents"] == 200000 for c in charges)


def test_approve_with_contract_generates_contract(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cliente Doc"}, headers=headers).json()
    payload = _quote(
        client_id=cl["id"],
        show_contract=True,
        contract_text="As partes acordam os termos a seguir.",
    )
    q = client.post("/quotes", json=payload, headers=headers).json()
    client.post(f"/quotes/{q['id']}/approve", headers=headers)
    # dominó completo: além da cobrança, nasce um contrato ligado ao orçamento
    contracts = client.get("/contracts", headers=headers).json()
    gen = [c for c in contracts if c["quote_id"] == q["id"]]
    assert len(gen) == 1
    assert gen[0]["title"] == "Contrato — Consultoria"
    assert gen[0]["status"] == "draft"


def test_approve_without_contract_flag_makes_no_contract(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(), headers=headers).json()
    client.post(f"/quotes/{q['id']}/approve", headers=headers)
    contracts = client.get("/contracts", headers=headers).json()
    assert all(c["quote_id"] != q["id"] for c in contracts)


def test_public_accept_wrong_password(client: TestClient, headers):
    q = client.post("/quotes", json=_quote(link_password="abc"), headers=headers).json()
    resp = client.post(f"/public/proposals/{q['public_slug']}/accept", json={"password": "errada"})
    assert resp.status_code == 401
