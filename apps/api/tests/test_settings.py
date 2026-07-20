"""Testes de Configurações + Brand Kit."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

REGISTER = {
    "legal_name": "Brand SA",
    "document": "39393939000107",
    "slug": "brandsa",
    "email": "brand@example.com",
    "name": "Br",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_profile_created_with_defaults(client: TestClient, headers):
    resp = client.get("/settings/profile", headers=headers)
    assert resp.status_code == 200
    p = resp.json()
    assert p["display_name"] == "Brand SA"  # vem do legal_name
    assert p["document"] == "39393939000107"
    assert p["primary_color"] == "#5D44F8"
    assert p["font"] == "Inter"
    assert p["timezone"] == "America/Sao_Paulo"  # default de fuso (Story 4.5)


def test_update_timezone(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile", json={"timezone": "America/Manaus"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "America/Manaus"
    # persiste
    again = client.get("/settings/profile", headers=headers).json()
    assert again["timezone"] == "America/Manaus"


def test_update_brand_kit(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile",
        json={
            "display_name": "Minha Marca",
            "primary_color": "#FF0000",
            "font": "Poppins",
            "logo_url": "https://x.com/logo.png",
            "phone": "+5511999998888",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    p = resp.json()
    assert p["display_name"] == "Minha Marca"
    assert p["primary_color"] == "#FF0000"
    assert p["font"] == "Poppins"
    # persiste
    again = client.get("/settings/profile", headers=headers).json()
    assert again["logo_url"] == "https://x.com/logo.png"
    assert again["phone"] == "+5511999998888"


def test_update_logo_url_accepts_relative_path(client: TestClient, headers):
    # uploadPublicImage.ts devolve "/api/public-images/{id}" (caminho relativo via proxy) — o
    # brand kit precisa aceitar esse formato, não só http(s) absoluto.
    resp = client.patch(
        "/settings/profile",
        json={"logo_url": "/api/public-images/2e41b902-81b0-470e-a96d-7a9fd7964f82"},
        headers=headers,
    )
    assert resp.status_code == 200
    again = client.get("/settings/profile", headers=headers).json()
    assert again["logo_url"] == "/api/public-images/2e41b902-81b0-470e-a96d-7a9fd7964f82"


def test_update_invalid_logo_url_rejected(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile", json={"logo_url": "nao-e-uma-url"}, headers=headers
    )
    assert resp.status_code == 422


def test_profile_is_singleton(client: TestClient, headers):
    client.get("/settings/profile", headers=headers)
    client.patch("/settings/profile", json={"display_name": "A"}, headers=headers)
    client.patch("/settings/profile", json={"display_name": "B"}, headers=headers)
    assert client.get("/settings/profile", headers=headers).json()["display_name"] == "B"


def test_update_invalid_timezone_rejected(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile", json={"timezone": "Nao/Existe"}, headers=headers
    )
    assert resp.status_code == 422
    # não persistiu: segue o default
    again = client.get("/settings/profile", headers=headers).json()
    assert again["timezone"] == "America/Sao_Paulo"


def test_update_invalid_website_rejected(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile", json={"website": "nao-e-uma-url"}, headers=headers
    )
    assert resp.status_code == 422
    again = client.get("/settings/profile", headers=headers).json()
    assert again["website"] == ""  # default vazio, não persistiu o lixo


def test_update_invalid_color_rejected(client: TestClient, headers):
    # cor por nome (não hex)
    resp = client.patch(
        "/settings/profile", json={"primary_color": "vermelho"}, headers=headers
    )
    assert resp.status_code == 422
    # hex com dígitos inválidos
    resp2 = client.patch(
        "/settings/profile", json={"primary_color": "#ZZZZZZ"}, headers=headers
    )
    assert resp2.status_code == 422
    # não persistiu: segue o default
    again = client.get("/settings/profile", headers=headers).json()
    assert again["primary_color"] == "#5D44F8"


def test_default_entry_funnel_starts_unset(client: TestClient, headers):
    p = client.get("/settings/profile", headers=headers).json()
    assert p["default_entry_funnel_id"] is None


def test_set_and_clear_default_entry_funnel(client: TestClient, headers):
    f = client.post("/funnels", json={"name": "Entrada"}, headers=headers).json()
    resp = client.patch(
        "/settings/profile", json={"default_entry_funnel_id": f["id"]}, headers=headers
    )
    assert resp.json()["default_entry_funnel_id"] == f["id"]

    # "" desliga o auto-enroll (mesmo padrão de contract_id/cost_center_id em Charge/Payable)
    cleared = client.patch(
        "/settings/profile", json={"default_entry_funnel_id": ""}, headers=headers
    )
    assert cleared.json()["default_entry_funnel_id"] is None


def test_requires_auth(client: TestClient):
    assert client.get("/settings/profile").status_code == 401


def test_whatsapp_starts_unconfigured(client: TestClient, headers):
    resp = client.get("/settings/profile", headers=headers)
    assert resp.status_code == 200
    p = resp.json()
    assert p["whatsapp_configured"] is False
    assert p["whatsapp_phone_id"] == ""
    assert p["whatsapp_waba_id"] == ""
    assert "whatsapp_token" not in p


def test_whatsapp_full_config_marks_configured(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile",
        json={
            "whatsapp_token": "EAAG-fake-meta-token",
            "whatsapp_phone_id": "1234567890",
            "whatsapp_waba_id": "0987654321",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    p = resp.json()
    assert p["whatsapp_configured"] is True
    assert p["whatsapp_phone_id"] == "1234567890"
    assert p["whatsapp_waba_id"] == "0987654321"
    assert "whatsapp_token" not in p
    # persiste
    again = client.get("/settings/profile", headers=headers).json()
    assert again["whatsapp_configured"] is True
    assert again["whatsapp_phone_id"] == "1234567890"
    assert again["whatsapp_waba_id"] == "0987654321"


def test_whatsapp_partial_config_not_configured(client: TestClient, headers):
    resp = client.patch(
        "/settings/profile",
        json={
            "whatsapp_token": "EAAG-fake-meta-token",
            "whatsapp_phone_id": "1234567890",
            # whatsapp_waba_id omitido de propósito
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["whatsapp_configured"] is False


def test_whatsapp_clear_token_unconfigures(client: TestClient, headers):
    client.patch(
        "/settings/profile",
        json={
            "whatsapp_token": "EAAG-fake-meta-token",
            "whatsapp_phone_id": "1234567890",
            "whatsapp_waba_id": "0987654321",
        },
        headers=headers,
    )
    resp = client.patch(
        "/settings/profile", json={"whatsapp_token": ""}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["whatsapp_configured"] is False
    again = client.get("/settings/profile", headers=headers).json()
    assert again["whatsapp_configured"] is False
    # phone_id/waba_id não foram tocados (None = não altera), só o token foi limpo
    assert again["whatsapp_phone_id"] == "1234567890"
    assert again["whatsapp_waba_id"] == "0987654321"


def test_whatsapp_token_encrypted_at_rest(client: TestClient, headers, db: Session):
    from sqlalchemy import text

    plaintext = "EAAG-fake-meta-token-for-encryption-check"
    client.patch(
        "/settings/profile", json={"whatsapp_token": plaintext}, headers=headers
    )
    # Bypassa o TypeDecorator (SQL cru) para inspecionar o valor REALMENTE gravado no banco.
    stored_raw = db.execute(
        text("SELECT whatsapp_token FROM tenant_profiles LIMIT 1")
    ).scalar()
    assert stored_raw != plaintext
    assert stored_raw.startswith("enc:v1:")


def test_whatsapp_verify_token_generated_when_fully_configured(
    client: TestClient, headers, db: Session
) -> None:
    """Ao completar as 4 credenciais (token/phone_id/waba_id/app_secret), o backend gera
    sozinho o verify_token e cria o snapshot público."""
    from app.modules.whatsapp_inbox.models import PublicWhatsappAccount

    resp = client.patch(
        "/settings/profile",
        json={
            "whatsapp_token": "tok-abc", "whatsapp_phone_id": "phone-123",
            "whatsapp_waba_id": "waba-456", "whatsapp_app_secret": "secret-xyz",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["whatsapp_verify_token"]  # gerado, não vazio
    assert "whatsapp_app_secret" not in body  # nunca exposto em claro

    snap = db.get(PublicWhatsappAccount, "phone-123")
    assert snap is not None
    assert snap.app_secret == "secret-xyz"
    assert snap.verify_token == body["whatsapp_verify_token"]


def test_whatsapp_public_snapshot_removed_when_incomplete(
    client: TestClient, headers, db: Session
) -> None:
    """Se as credenciais ficam incompletas de novo (ex.: limpar o app_secret), o snapshot
    público é removido — o webhook não deve mais resolver esse phone_number_id."""
    from app.modules.whatsapp_inbox.models import PublicWhatsappAccount

    client.patch(
        "/settings/profile",
        json={
            "whatsapp_token": "tok", "whatsapp_phone_id": "phone-999",
            "whatsapp_waba_id": "waba", "whatsapp_app_secret": "secret",
        },
        headers=headers,
    )
    assert db.get(PublicWhatsappAccount, "phone-999") is not None

    client.patch("/settings/profile", json={"whatsapp_app_secret": ""}, headers=headers)
    assert db.get(PublicWhatsappAccount, "phone-999") is None


def test_whatsapp_public_snapshot_moves_when_phone_id_changes(
    client: TestClient, headers, db: Session
) -> None:
    """Trocar o phone_id remove o snapshot antigo e cria um novo na chave certa."""
    from app.modules.whatsapp_inbox.models import PublicWhatsappAccount

    client.patch(
        "/settings/profile",
        json={
            "whatsapp_token": "tok", "whatsapp_phone_id": "phone-old",
            "whatsapp_waba_id": "waba", "whatsapp_app_secret": "secret",
        },
        headers=headers,
    )
    client.patch("/settings/profile", json={"whatsapp_phone_id": "phone-new"}, headers=headers)
    assert db.get(PublicWhatsappAccount, "phone-old") is None
    assert db.get(PublicWhatsappAccount, "phone-new") is not None
