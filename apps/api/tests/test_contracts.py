"""Testes do Construtor de Contratos + assinatura pública (KYC)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.settings import service as settings_service
from app.modules.whatsapp_templates.models import (
    PURPOSE_CONTRACT_SEND,
    STATUS_APPROVED,
    STATUS_PENDING,
    WhatsappTemplate,
)

REGISTER = {
    "legal_name": "Contratos SA",
    "document": "23232323000106",
    "slug": "contratosa",
    "email": "contr@example.com",
    "name": "Co",
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
        tenant_id=tenant_id, name="contrato_assinatura", language="pt_BR",
        category_requested="UTILITY", category_approved="UTILITY", status=status,
        body_text="Olá {{1}}, segue o contrato {{2}} para sua assinatura: {{3}}",
        variable_count=3, variable_examples=["Maria", "Prestação de serviços", "https://x"],
    )
    for k, v in overrides.items():
        setattr(tpl, k, v)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


def _contract(**over):
    base = {
        "title": "Prestação de serviços",
        "clauses": [
            {"title": "Objeto", "text": "Serviço para [CLIENTE] por [VALOR]."},
            {"title": "Empresa", "text": "Contratada: [EMPRESA] em [DATA]."},
        ],
    }
    return {**base, **over}


def test_default_templates_seeded(client: TestClient, headers):
    resp = client.get("/contracts/templates", headers=headers)
    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()]
    assert "Prestação de serviços" in names
    assert "Confidencialidade (NDA)" in names


def test_create_fills_variables(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Maria"}, headers=headers).json()
    payload = _contract(client_id=cl["id"], variables={"VALOR": "R$ 1.000"})
    c = client.post("/contracts", json=payload, headers=headers).json()
    texts = " ".join(cl_["text"] for cl_ in c["clauses"])
    assert "R$ 1.000" in texts  # [VALOR]
    assert "Maria" in texts  # [CLIENTE] automático
    assert "Contratos SA" in texts  # [EMPRESA] automático
    assert "[" not in texts  # nada de placeholder solto conhecido
    assert c["public_slug"]
    assert c["status"] == "draft"


def test_public_view_and_sign(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    slug = c["public_slug"]
    # visão pública
    pub = client.get(f"/public/contracts/{slug}")
    assert pub.status_code == 200
    assert pub.json()["company_name"] == "Contratos SA"
    # assinar (KYC: nome + documento)
    sign = client.post(
        f"/public/contracts/{slug}/sign",
        json={"name": "João Cliente", "document": "529.982.247-25", "accept": True},
    )
    assert sign.status_code == 200, sign.text
    assert sign.json()["status"] == "signed"
    # contrato ficou assinado com os dados do assinante
    got = client.get(f"/contracts/{c['id']}", headers=headers).json()
    assert got["status"] == "signed"
    assert got["signer_name"] == "João Cliente"
    # KYC: documento validado (CPF real) e gravado NORMALIZADO (só-dígitos).
    assert got["signer_document"] == "52998224725"
    assert got["signed_at"]


def test_cannot_sign_twice(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    slug = c["public_slug"]
    body = {"name": "A B", "document": "52998224725", "accept": True}
    assert client.post(f"/public/contracts/{slug}/sign", json=body).status_code == 200
    assert client.post(f"/public/contracts/{slug}/sign", json=body).status_code == 409


def test_sign_requires_accept(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    resp = client.post(
        f"/public/contracts/{c['public_slug']}/sign",
        json={"name": "A B", "document": "52998224725", "accept": False},
    )
    assert resp.status_code == 400


def test_send_marks_sent(client: TestClient, headers):
    cl = client.post("/crm/clients", json={"name": "Cli"}, headers=headers).json()
    c = client.post("/contracts", json=_contract(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/contracts/{c['id']}/send", headers=headers)
    assert resp.json()["status"] == "sent"


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
        "/crm/clients", json={"name": "Cli", "phone": "5511999998888"}, headers=headers
    ).json()
    c = client.post("/contracts", json=_contract(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/contracts/{c['id']}/send", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "sent"  # status do CONTRATO (workflow), não do envio

    notif = db.scalar(select(Notification).where(Notification.channel == "whatsapp"))
    assert notif is not None
    assert notif.status == "pending"
    assert notif.purpose == PURPOSE_CONTRACT_SEND
    assert f"Segue o contrato '{c['title']}'" in notif.message


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
    profile.whatsapp_template_bindings = {PURPOSE_CONTRACT_SEND: tpl.id}
    db.commit()

    cl = client.post(
        "/crm/clients", json={"name": "Maria Cliente", "phone": "5511988887777"}, headers=headers
    ).json()
    c = client.post("/contracts", json=_contract(client_id=cl["id"]), headers=headers).json()
    resp = client.post(f"/contracts/{c['id']}/send", headers=headers)
    assert resp.status_code == 200

    notif = db.scalar(select(Notification).where(Notification.channel == "whatsapp"))
    assert notif is not None
    assert notif.purpose == PURPOSE_CONTRACT_SEND
    assert notif.whatsapp_template_name == tpl.name
    assert notif.whatsapp_template_language == tpl.language
    assert notif.recipient == "5511988887777"
    link = notif.whatsapp_template_variables[2]
    assert notif.whatsapp_template_variables == ["Maria Cliente", c["title"], link]

    expected_msg = f"Olá Maria Cliente, segue o contrato {c['title']} para sua assinatura: {link}"
    assert "{{" not in expected_msg
    assert notif.message == expected_msg


def test_send_falls_back_to_free_text_when_bound_template_not_approved(
    client: TestClient, headers, db: Session, tenant_id: str
):
    from sqlalchemy import select

    from app.modules.notifications.models import Notification

    tpl = _template(db, tenant_id, status=STATUS_PENDING)
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_template_bindings = {PURPOSE_CONTRACT_SEND: tpl.id}
    db.commit()

    c = client.post("/contracts", json=_contract(), headers=headers).json()
    resp = client.post(f"/contracts/{c['id']}/send", headers=headers)
    assert resp.status_code == 200

    notif = db.scalar(select(Notification).where(Notification.channel == "whatsapp"))
    assert notif is not None
    assert notif.whatsapp_template_name is None  # não usou o template ainda pendente
    assert f"Segue o contrato '{c['title']}'" in notif.message


def test_cannot_edit_after_sent(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    client.post(f"/contracts/{c['id']}/send", headers=headers)
    resp = client.patch(f"/contracts/{c['id']}", json={"title": "Novo"}, headers=headers)
    assert resp.status_code == 409


def test_summary(client: TestClient, headers):
    c = client.post("/contracts", json=_contract(), headers=headers).json()
    client.post(f"/public/contracts/{c['public_slug']}/sign",
                json={"name": "X Y", "document": "52998224725", "accept": True})
    client.post("/contracts", json=_contract(), headers=headers)  # draft
    s = client.get("/contracts/summary", headers=headers).json()
    assert s["signed_count"] == 1
    assert s["draft_count"] == 1


def test_requires_auth(client: TestClient):
    assert client.get("/contracts/summary").status_code == 401