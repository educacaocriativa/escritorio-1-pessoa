"""A preferência é DO USUÁRIO — não pode exigir o módulo `settings`.

`/settings/profile` é configuração de EMPRESA e exige o módulo. Escolher o próprio horário e
ligar o próprio WhatsApp é outra coisa: um sub-usuário sem `settings` precisa poder fazer as
duas. Por isso a preferência vive em `users` e as rotas não têm `require_module`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.modules.auth.models import User
from app.modules.settings.models import TenantProfile
from app.modules.whatsapp_templates.models import (
    PURPOSE_VIMA_BRIEFING,
    STATUS_APPROVED,
    WhatsappTemplate,
)

REGISTER = {
    "legal_name": "Vima ME",
    "document": "11444777000161",
    "slug": "vimame",
    "email": "vima@example.com",
    "name": "Flávio Kato",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    """O dono, ainda SEM telefone cadastrado (é como `/register` o cria)."""
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


@pytest.fixture()
def headers_sem_telefone(headers: dict[str, str]) -> dict[str, str]:
    return headers


@pytest.fixture()
def dono_com_telefone(db: Session, client: TestClient, headers: dict[str, str]) -> User:
    user_id = client.get("/auth/me", headers=headers).json()["user"]["id"]
    dono = db.get(User, user_id)
    dono.phone = "43984074017"
    db.commit()
    return dono


@pytest.fixture()
def tenant_evolution(db: Session, tenant_id: str) -> TenantProfile:
    perfil = TenantProfile(
        tenant_id=tenant_id, display_name="Vima ME", whatsapp_provider="evolution"
    )
    db.add(perfil)
    db.commit()
    return perfil


@pytest.fixture()
def headers_sub_crm(db: Session, client: TestClient, tenant_id: str) -> dict[str, str]:
    """Funcionário que só enxerga o CRM — sem o módulo `settings`, com telefone próprio."""
    sub = User(
        tenant_id=tenant_id, email="contador@example.com", name="Contador",
        password_hash="x", role="sub_user", allowed_modules=["crm"],
        phone="43999998888",
    )
    db.add(sub)
    db.commit()
    token = create_access_token(
        {
            "sub": sub.id, "tenant_id": tenant_id, "role": "sub_user",
            "allowed_modules": ["crm"], "is_platform_admin": False,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def test_default_e_desligado(client: TestClient, headers):
    """Ninguém ganha WhatsApp diário sem pedir."""
    p = client.get("/auth/me/preferences", headers=headers).json()
    assert p["briefing_whatsapp_enabled"] is False
    assert p["briefing_hour"] == "07:00"


def test_sub_usuario_sem_settings_configura_o_proprio_briefing(
    client: TestClient, headers_sub_crm, tenant_evolution
):
    """`/config` exige o módulo `settings`. Um sub-usuário sem ele precisa poder ligar o
    próprio WhatsApp e escolher o próprio horário — configurar a própria entrega não é
    configuração de empresa."""
    r = client.patch(
        "/auth/me/preferences",
        json={"briefing_whatsapp_enabled": True, "briefing_hour": "08:30"},
        headers=headers_sub_crm,
    )
    assert r.status_code == 200
    assert r.json()["briefing_hour"] == "08:30"
    assert r.json()["briefing_whatsapp_enabled"] is True


def test_sem_telefone_nao_pode_ligar(client: TestClient, headers_sem_telefone, tenant_evolution):
    """Ligar a entrega sem destinatário produziria uma fila de envios que falham calados."""
    r = client.patch(
        "/auth/me/preferences", json={"briefing_whatsapp_enabled": True},
        headers=headers_sem_telefone,
    )
    assert r.status_code == 422
    assert "WhatsApp" in r.json()["detail"]


def test_horario_invalido_e_recusado(client: TestClient, headers):
    r = client.patch("/auth/me/preferences", json={"briefing_hour": "25:00"}, headers=headers)
    assert r.status_code == 422


def test_horario_muda_sem_mexer_no_whatsapp(client: TestClient, headers):
    """Escolher o horário da TELA não exige telefone — só a entrega por WhatsApp exige."""
    r = client.patch("/auth/me/preferences", json={"briefing_hour": "09:15"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["briefing_hour"] == "09:15"
    assert r.json()["briefing_whatsapp_enabled"] is False


@pytest.fixture()
def tenant_meta_conectado(db: Session, tenant_id: str) -> TenantProfile:
    """Tenant na Cloud API COM credenciais — mas ainda sem o template do briefing aprovado."""
    perfil = TenantProfile(
        tenant_id=tenant_id, display_name="Vima ME", whatsapp_provider="meta",
        whatsapp_token="tok", whatsapp_phone_id="pid",
    )
    db.add(perfil)
    db.commit()
    return perfil


def test_tenant_meta_sem_template_diz_por_que_nao_da(
    client: TestClient, headers, dono_com_telefone, tenant_meta_conectado
):
    """A dependência é EXTERNA (aprovação da Meta) e fora do repositório. A tela precisa dizer
    o motivo em vez de oferecer um botão que não entrega nada."""
    p = client.get("/auth/me/preferences", headers=headers).json()
    assert p["briefing_whatsapp_disponivel"] is False
    assert "Meta" in p["briefing_whatsapp_indisponivel_motivo"]

    r = client.patch(
        "/auth/me/preferences", json={"briefing_whatsapp_enabled": True}, headers=headers
    )
    assert r.status_code == 422


def test_quem_nunca_conectou_whatsapp_le_o_motivo_CERTO(
    client: TestClient, headers, dono_com_telefone
):
    """Perfil ausente cai em Meta por definição (`for_profile(None)`), mas este tenant não está
    esperando a Meta aprovar nada — está esperando conectar. Dizer "a Meta ainda não aprovou"
    seria verdade e resposta errada: manda o dono esperar em vez de agir."""
    p = client.get("/auth/me/preferences", headers=headers).json()
    assert p["briefing_whatsapp_disponivel"] is False
    assert "não está conectado" in p["briefing_whatsapp_indisponivel_motivo"]
    assert "Meta" not in p["briefing_whatsapp_indisponivel_motivo"]


def test_tenant_evolution_pode_ligar_sem_template_nenhum(
    client: TestClient, headers, dono_com_telefone, tenant_evolution
):
    """A Evolution não conhece template: o briefing sai como texto livre, em um passo."""
    p = client.get("/auth/me/preferences", headers=headers).json()
    assert p["briefing_whatsapp_disponivel"] is True
    assert p["briefing_whatsapp_indisponivel_motivo"] is None

    r = client.patch(
        "/auth/me/preferences", json={"briefing_whatsapp_enabled": True}, headers=headers
    )
    assert r.status_code == 200


def test_tenant_meta_com_template_aprovado_pode_ligar(
    db: Session, client: TestClient, headers, tenant_id, dono_com_telefone
):
    tpl = WhatsappTemplate(
        tenant_id=tenant_id, name="vima_briefing", language="pt_BR",
        category_requested="UTILITY", status=STATUS_APPROVED,
        body_text="Bom dia, {{1}}. Seu resumo de hoje está pronto.", variable_count=1,
        variable_examples=["Flávio"],
    )
    db.add(tpl)
    db.flush()
    perfil = TenantProfile(
        tenant_id=tenant_id, display_name="Vima ME",
        whatsapp_token="tok", whatsapp_phone_id="pid",
        whatsapp_template_bindings={PURPOSE_VIMA_BRIEFING: tpl.id},
    )
    db.add(perfil)
    db.commit()

    p = client.get("/auth/me/preferences", headers=headers).json()
    assert p["briefing_whatsapp_disponivel"] is True

    r = client.patch(
        "/auth/me/preferences", json={"briefing_whatsapp_enabled": True}, headers=headers
    )
    assert r.status_code == 200


def test_desligar_nunca_e_bloqueado(client: TestClient, headers, dono_com_telefone):
    """Mesmo num tenant que não consegue entregar, DESLIGAR sempre passa — a guarda existe para
    impedir promessa vazia, não para prender ninguém numa preferência."""
    r = client.patch(
        "/auth/me/preferences", json={"briefing_whatsapp_enabled": False}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["briefing_whatsapp_enabled"] is False


def test_a_preferencia_e_de_cada_UM(client: TestClient, headers, headers_sub_crm, tenant_evolution):
    """Dois usuários do mesmo tenant, dois horários. Se morasse no perfil da empresa, um
    sobrescreveria o outro."""
    client.patch("/auth/me/preferences", json={"briefing_hour": "06:30"}, headers=headers)
    client.patch("/auth/me/preferences", json={"briefing_hour": "10:00"}, headers=headers_sub_crm)

    assert client.get("/auth/me/preferences", headers=headers).json()["briefing_hour"] == "06:30"
    assert (
        client.get("/auth/me/preferences", headers=headers_sub_crm).json()["briefing_hour"]
        == "10:00"
    )
