"""Testes do Super Admin (Master). Delete real (purga) é coberto no e2e Docker (usa Postgres)."""
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import whatsapp
from app.core.audit import PlatformAuditEntry
from app.core.security import hash_password
from app.modules.agenda.models import AgendaEvent
from app.modules.auth.models import Tenant, User
from app.modules.crm.models import Client
from app.modules.platform import service as platform_service
from app.modules.settings.models import TenantProfile
from app.modules.whatsapp_templates.models import (
    PURPOSE_STAFF_INVITE,
    STATUS_APPROVED,
    STATUS_PENDING,
    WhatsappTemplate,
)

ADMIN_EMAIL = "master@e1p.com"
ADMIN_PASS = "senha-do-master-123"


@pytest.fixture()
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    t = Tenant(slug="platform", legal_name="Plataforma", document="00000000000")
    db.add(t)
    db.flush()
    db.add(
        User(
            tenant_id=t.id,
            email=ADMIN_EMAIL,
            name="Master",
            password_hash=hash_password(ADMIN_PASS),
            role="owner",
            allowed_modules=[],
            is_platform_admin=True,
        )
    )
    db.commit()
    token = client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account_payload(**over):
    base = {
        "legal_name": "Cliente Pagante",
        "document": "12345678000195",
        "slug": "clientepagante",
        "email": "cliente@example.com",
        "name": "Cliente",
        "password": "senha-bem-grande",  # usado no /auth/register; ignorado no /admin/accounts
        "address": "Av. Central, 500 - Centro",
        "phone": "27988887777",
    }
    return {**base, **over}


def test_non_admin_forbidden(client: TestClient):
    # usuário comum não acessa /admin
    token = client.post(
        "/auth/register",
        json=_account_payload(slug="comum", email="comum@example.com"),
    ).json()["access_token"]
    resp = client.get("/admin/accounts", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_unauthenticated_forbidden(client: TestClient):
    assert client.get("/admin/accounts").status_code == 401


def test_admin_creates_and_lists_account(client: TestClient, admin_headers):
    resp = client.post("/admin/accounts", json=_account_payload(), headers=admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["owner"]["email"] == "cliente@example.com"
    # conta criada por convite: dono com cadastro completo + senha temporária + troca no 1º acesso
    assert body["owner"]["phone"] == "27988887777"
    assert body["owner"]["address"] == "Av. Central, 500 - Centro"
    assert body["owner"]["must_reset_password"] is True
    assert body["temp_password"] and body["delivery_status"] in ("sent", "logged")
    # aparece na listagem de contas; a conta do próprio Master NÃO aparece
    accounts = client.get("/admin/accounts", headers=admin_headers).json()
    emails = [a["owner"]["email"] for a in accounts]
    assert "cliente@example.com" in emails and "master@e1p.com" not in emails


def test_account_owner_first_access(client: TestClient, admin_headers):
    inv = client.post(
        "/admin/accounts",
        json=_account_payload(slug="ownerfa", email="ownerfa@example.com"),
        headers=admin_headers,
    ).json()
    login = client.post(
        "/auth/login", json={"email": "ownerfa@example.com", "password": inv["temp_password"]}
    )
    assert login.status_code == 200 and login.json()["user"]["must_reset_password"] is True


def test_list_platform_customers(client: TestClient, admin_headers):
    tid, oh = _owner_headers(client, admin_headers, slug="lojinha", email="lojinha@example.com",
                             legal_name="Lojinha do Zé")
    prod = client.post(
        "/products", json={"name": "Mentoria", "kind": "digital", "price_cents": 50000}, headers=oh
    ).json()
    client.post(
        f"/products/{prod['id']}/sell",
        json={"name": "Cliente Comprador", "email": "comprou@x.com", "method": "pix"},
        headers=oh,
    )
    customers = client.get("/admin/customers", headers=admin_headers).json()
    mine = [c for c in customers if c["tenant_id"] == tid]
    assert len(mine) == 1
    assert mine[0]["name"] == "Cliente Comprador" and mine[0]["tenant_name"] == "Lojinha do Zé"


def test_admin_deactivates_account(client: TestClient, admin_headers):
    created = client.post("/admin/accounts", json=_account_payload(), headers=admin_headers).json()
    uid = created["owner"]["id"]
    resp = client.patch(f"/admin/accounts/{uid}", json={"is_active": False}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    # usuário desativado não consegue logar (mesmo com a senha temporária correta)
    login = client.post(
        "/auth/login", json={"email": "cliente@example.com", "password": created["temp_password"]}
    )
    assert login.status_code == 403


def test_cannot_edit_platform_admin(client: TestClient, admin_headers, db: Session):
    admin = db.query(User).filter(User.is_platform_admin.is_(True)).first()
    resp = client.patch(
        f"/admin/accounts/{admin.id}", json={"is_active": False}, headers=admin_headers
    )
    assert resp.status_code == 400


# ── Hierarquia de usuários (Super Admin vê/edita/exclui todos) ───────────────
def _tenant_id(client, admin_headers, **over) -> str:
    return client.post(
        "/admin/accounts", json=_account_payload(**over), headers=admin_headers
    ).json()["tenant"]["id"]


def test_list_users_hierarchy_excludes_platform(client: TestClient, admin_headers):
    _tenant_id(client, admin_headers, slug="esc1", email="esc1@example.com")
    data = client.get("/admin/users", headers=admin_headers).json()
    # só o escritório criado (a conta interna da plataforma é omitida)
    assert len(data) == 1
    node = data[0]
    assert node["admin"]["role"] == "owner"
    assert node["staff"] == [] and node["staff_count"] == 0
    assert node["customers"] == [] and node["customer_count"] == 0


def _staff_body(**over):
    base = {
        "name": "Contadora Completa",
        "email": "conta@esc2.com",
        "document": "11122233396",
        "address": "Rua das Flores, 100 - Centro",
        "phone": "27999990000",
        "allowed_modules": ["wallet"],
        "delivery": "email",
    }
    return {**base, **over}


def test_create_edit_delete_staff(client: TestClient, admin_headers):
    tid = _tenant_id(client, admin_headers, slug="esc2", email="esc2@example.com")
    # cria funcionário com cadastro completo; senha temporária é gerada e "enviada"
    invite = client.post(
        f"/admin/accounts/{tid}/users", json=_staff_body(), headers=admin_headers
    ).json()
    assert invite["temp_password"] and invite["delivery"] == "email"
    assert invite["delivery_status"] in ("sent", "logged")
    staff = invite["user"]
    assert staff["role"] == "sub_user" and staff["allowed_modules"] == ["wallet"]
    assert staff["document"] == "11122233396" and staff["phone"] == "27999990000"
    assert staff["must_reset_password"] is True  # deve trocar no 1º acesso
    # aparece na hierarquia
    node = next(n for n in client.get("/admin/users", headers=admin_headers).json()
                if n["tenant"]["id"] == tid)
    assert node["staff_count"] == 1
    # edita (suspende + troca módulos)
    upd = client.patch(
        f"/admin/users/{staff['id']}",
        json={"is_active": False, "allowed_modules": ["crm", "agenda"]},
        headers=admin_headers,
    ).json()
    assert upd["is_active"] is False and upd["allowed_modules"] == ["crm", "agenda"]
    # exclui
    assert client.delete(f"/admin/users/{staff['id']}", headers=admin_headers).status_code == 204
    node = next(n for n in client.get("/admin/users", headers=admin_headers).json()
                if n["tenant"]["id"] == tid)
    assert node["staff_count"] == 0


def test_staff_whatsapp_delivery(client: TestClient, admin_headers, _tenant_session_to_test_db):
    tid = _tenant_id(client, admin_headers, slug="escw", email="escw@example.com")
    invite = client.post(
        f"/admin/accounts/{tid}/users",
        json=_staff_body(email="zap@escw.com", delivery="whatsapp"),
        headers=admin_headers,
    ).json()
    assert invite["delivery"] == "whatsapp" and invite["delivery_status"] in ("sent", "logged")


# ── WhatsApp por template (staff_invite) — Story convite via template ───────────────────────
def test_staff_whatsapp_no_binding_uses_tenant_credentials(
    client: TestClient, admin_headers, db: Session, _tenant_session_to_test_db, monkeypatch
):
    """Sem template vinculado: mantém o texto livre, mas usando as credenciais do TENANT."""
    tid = _tenant_id(client, admin_headers, slug="escwcred", email="escwcred@example.com")
    db.add(TenantProfile(tenant_id=tid, whatsapp_token="tok-123", whatsapp_phone_id="phone-456"))
    db.commit()

    captured = {}

    def _fake_send_text(*, to, text, token=None, phone_id=None):
        captured.update(to=to, token=token, phone_id=phone_id)
        return "sent"

    monkeypatch.setattr(whatsapp, "send_text", _fake_send_text)

    invite = client.post(
        f"/admin/accounts/{tid}/users",
        json=_staff_body(email="credzap@escwcred.com", delivery="whatsapp"),
        headers=admin_headers,
    ).json()
    assert invite["delivery_status"] == "sent"
    assert captured["token"] == "tok-123" and captured["phone_id"] == "phone-456"


def test_staff_whatsapp_bound_approved_template_sends_variables_in_order(
    client: TestClient, admin_headers, db: Session, _tenant_session_to_test_db, monkeypatch
):
    """Template vinculado + aprovado: usa send_template com as variáveis na ordem do spec
    (Nome, Empresa, E-mail de login, Senha temporária)."""
    tid = _tenant_id(client, admin_headers, slug="esctpl", email="esctpl@example.com")
    tpl = WhatsappTemplate(
        tenant_id=tid,
        name="convite_funcionario",
        language="pt_BR",
        category_requested="UTILITY",
        status=STATUS_APPROVED,
        body_text="Olá {{1}}, bem-vindo à {{2}}. Login: {{3}} Senha: {{4}}",
        variable_count=4,
        variable_examples=["Ana", "Empresa X", "ana@x.com", "abc123"],
    )
    db.add(tpl)
    db.flush()
    db.add(TenantProfile(
        tenant_id=tid,
        whatsapp_token="tok-1",
        whatsapp_phone_id="phone-1",
        whatsapp_template_bindings={PURPOSE_STAFF_INVITE: tpl.id},
    ))
    db.commit()

    captured = {}

    def _fake_send_template(*, to, token, phone_id, template_name, language, variables):
        captured.update(
            to=to, token=token, phone_id=phone_id, template_name=template_name,
            language=language, variables=variables,
        )
        return "sent"

    monkeypatch.setattr(whatsapp, "send_template", _fake_send_template)

    body = _staff_body(email="tplzap@esctpl.com", delivery="whatsapp", name="Contadora Nova")
    invite = client.post(f"/admin/accounts/{tid}/users", json=body, headers=admin_headers).json()

    assert invite["delivery_status"] == "sent"
    assert captured["template_name"] == "convite_funcionario"
    assert captured["language"] == "pt_BR"
    assert captured["token"] == "tok-1" and captured["phone_id"] == "phone-1"
    assert captured["variables"] == [
        "Contadora Nova", "Cliente Pagante", "tplzap@esctpl.com", invite["temp_password"],
    ]


def test_staff_whatsapp_bound_unapproved_template_falls_back_to_text(
    client: TestClient, admin_headers, db: Session, _tenant_session_to_test_db, monkeypatch
):
    """Template vinculado mas ainda não aprovado pela Meta: cai no texto livre (send_text)."""
    tid = _tenant_id(client, admin_headers, slug="esctplpend", email="esctplpend@example.com")
    tpl = WhatsappTemplate(
        tenant_id=tid,
        name="convite_pendente",
        language="pt_BR",
        category_requested="UTILITY",
        status=STATUS_PENDING,
        body_text="Olá {{1}}, bem-vindo à {{2}}. Login: {{3}} Senha: {{4}}",
        variable_count=4,
        variable_examples=[],
    )
    db.add(tpl)
    db.flush()
    db.add(TenantProfile(
        tenant_id=tid,
        whatsapp_token="tok-2",
        whatsapp_phone_id="phone-2",
        whatsapp_template_bindings={PURPOSE_STAFF_INVITE: tpl.id},
    ))
    db.commit()

    calls = {"template": False, "text": False}

    def _fake_send_template(**kwargs):
        calls["template"] = True
        return "sent"

    def _fake_send_text(*, to, text, token=None, phone_id=None):
        calls["text"] = True
        return "sent"

    monkeypatch.setattr(whatsapp, "send_template", _fake_send_template)
    monkeypatch.setattr(whatsapp, "send_text", _fake_send_text)

    body = _staff_body(email="pendzap@esctplpend.com", delivery="whatsapp")
    invite = client.post(f"/admin/accounts/{tid}/users", json=body, headers=admin_headers).json()

    assert invite["delivery_status"] == "sent"
    assert calls["text"] is True and calls["template"] is False


def test_first_access_password_change(client: TestClient, admin_headers):
    tid = _tenant_id(client, admin_headers, slug="escfa", email="escfa@example.com")
    invite = client.post(
        f"/admin/accounts/{tid}/users",
        json=_staff_body(email="novo@escfa.com"), headers=admin_headers,
    ).json()
    temp = invite["temp_password"]
    # loga com a senha temporária
    login = client.post("/auth/login", json={"email": "novo@escfa.com", "password": temp})
    assert login.status_code == 200
    body = login.json()
    assert body["user"]["must_reset_password"] is True
    h = {"Authorization": f"Bearer {body['access_token']}"}
    # troca a senha no 1º acesso → limpa o flag
    new = "minha-nova-senha"
    changed = client.post("/auth/change-password", json={"new_password": new}, headers=h)
    assert changed.status_code == 200
    assert changed.json()["user"]["must_reset_password"] is False
    # senha antiga não vale mais; a nova vale
    old = client.post("/auth/login", json={"email": "novo@escfa.com", "password": temp})
    assert old.status_code == 401
    relog = client.post("/auth/login", json={"email": "novo@escfa.com", "password": new})
    assert relog.status_code == 200 and relog.json()["user"]["must_reset_password"] is False


def test_staff_duplicate_email_409(client: TestClient, admin_headers):
    tid = _tenant_id(client, admin_headers, slug="esc3", email="esc3@example.com")
    body = _staff_body(email="dup@esc3.com")
    url = f"/admin/accounts/{tid}/users"
    assert client.post(url, json=body, headers=admin_headers).status_code == 201
    assert client.post(url, json=body, headers=admin_headers).status_code == 409


def test_staff_duplicate_document_409(client: TestClient, admin_headers):
    # Story 1.1 AC3: UNIQUE(tenant_id, document) — mesmo CPF no mesmo escritório -> 409.
    tid = _tenant_id(client, admin_headers, slug="escdup", email="escdup@example.com")
    url = f"/admin/accounts/{tid}/users"
    assert client.post(
        url, json=_staff_body(email="a@escdup.com"), headers=admin_headers
    ).status_code == 201
    # e-mail diferente, MESMO documento -> rejeitado pela unicidade por tenant
    resp = client.post(url, json=_staff_body(email="b@escdup.com"), headers=admin_headers)
    assert resp.status_code == 409


def test_staff_invalid_document_422(client: TestClient, admin_headers):
    # Story 1.1 AC2: CPF com dígito verificador inválido -> 422.
    tid = _tenant_id(client, admin_headers, slug="escinv", email="escinv@example.com")
    resp = client.post(
        f"/admin/accounts/{tid}/users",
        json=_staff_body(email="inv@escinv.com", document="11122233344"),
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_cannot_delete_owner_via_users(client: TestClient, admin_headers):
    tid = _tenant_id(client, admin_headers, slug="esc4", email="esc4@example.com")
    node = next(n for n in client.get("/admin/users", headers=admin_headers).json()
                if n["tenant"]["id"] == tid)
    owner_id = node["admin"]["id"]
    resp = client.delete(f"/admin/users/{owner_id}", headers=admin_headers)
    assert resp.status_code == 400  # dono só sai com a conta inteira


def _owner_headers(client, admin_headers, **over) -> tuple[str, dict]:
    """Cria uma conta via convite e devolve (tenant_id, headers do dono logado c/ senha temp)."""
    inv = client.post(
        "/admin/accounts", json=_account_payload(**over), headers=admin_headers
    ).json()
    token = client.post(
        "/auth/login", json={"email": inv["owner"]["email"], "password": inv["temp_password"]}
    ).json()["access_token"]
    return inv["tenant"]["id"], {"Authorization": f"Bearer {token}"}


def test_customers_appear_from_enrollments(client: TestClient, admin_headers):
    # cria escritório e loga como o dono (senha temporária) para vender um produto
    _tid, oh = _owner_headers(client, admin_headers, slug="esc5", email="esc5@example.com")
    prod = client.post(
        "/products", json={"name": "Curso", "kind": "membership", "price_cents": 9900}, headers=oh
    ).json()
    prod = client.post(
        "/products", json={"name": "Curso", "kind": "membership", "price_cents": 9900}, headers=oh
    ).json()
    client.post(
        f"/products/{prod['id']}/sell",
        json={"name": "Aluna Compradora", "email": "aluna@x.com", "method": "pix"},
        headers=oh,
    )
    tid = prod["tenant_id"]
    node = next(n for n in client.get("/admin/users", headers=admin_headers).json()
                if n["tenant"]["id"] == tid)
    assert node["customer_count"] == 1
    assert node["customers"][0]["name"] == "Aluna Compradora"


def test_users_requires_admin(client: TestClient):
    token = client.post(
        "/auth/register", json=_account_payload(slug="naoadm", email="naoadm@example.com")
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/admin/users", headers=h).status_code == 403
    assert client.get("/admin/users").status_code == 401


# ── Gating de temp_password em produção (Story 2.1 AC3) ──────────────────────
def test_temp_password_hidden_in_production_account(client: TestClient, admin_headers, monkeypatch):
    """Em produção, POST /admin/accounts NÃO retorna a senha no corpo (vai por e-mail)."""
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    resp = client.post(
        "/admin/accounts",
        json=_account_payload(slug="prodacc", email="prodacc@example.com"),
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["temp_password"] is None  # AC3: não vaza no corpo em produção
    # o envio continua acontecendo (delivery_status) e a conta é criada normalmente
    assert body["delivery_status"] in ("sent", "logged", "failed")
    assert body["owner"]["must_reset_password"] is True


def test_temp_password_hidden_in_production_staff(client: TestClient, admin_headers, monkeypatch):
    """Em produção, POST /admin/accounts/{tid}/users NÃO retorna a senha temporária no corpo."""
    from app.config import settings

    tid = _tenant_id(client, admin_headers, slug="prodstaff", email="prodstaff@example.com")
    monkeypatch.setattr(settings, "environment", "production")
    resp = client.post(
        f"/admin/accounts/{tid}/users",
        json=_staff_body(email="staffprod@example.com"),
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["temp_password"] is None  # AC3: não vaza no corpo em produção
    assert body["delivery_status"] in ("sent", "logged", "failed")


# ── Exclusão de conta: purga atômica + log de plataforma sobrevivente (Story 1.2) ────
# Baseline de regressão criada ANTES da mudança de comportamento (a story constatou que não
# havia NENHUM teste automatizado para DELETE /admin/accounts/{tenant_id}). O delete real chama
# `tenant_session` (Postgres, RLS) — em teste (SQLite) apontamos para a sessão compartilhada.


@pytest.fixture()
def _tenant_session_to_test_db(db: Session, monkeypatch):
    """`delete_account` abre `tenant_session` (conexão Postgres dedicada) direto no service.

    Em teste (SQLite, sem RLS) redirecionamos para a MESMA sessão compartilhada, exercitando a
    purga + a gravação do log de plataforma sem precisar de Postgres real (RLS é validada no e2e).
    """

    @contextmanager
    def _fake_tenant_session(_tenant_id: str):
        yield db

    monkeypatch.setattr(platform_service, "tenant_session", _fake_tenant_session)


def _seed_business_data(db: Session, tenant_id: str) -> None:
    """Dados em 2 módulos de negócio distintos, para provar que a purga por tenant funciona."""
    db.add(Client(tenant_id=tenant_id, name="Lead a Purgar"))
    db.add(
        AgendaEvent(
            tenant_id=tenant_id,
            title="Reunião a Purgar",
            kind="reuniao",
            starts_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
            ends_at=datetime(2026, 7, 10, 11, 0, tzinfo=UTC),
        )
    )
    db.commit()


def test_delete_account_purges_and_writes_platform_log(
    client: TestClient, admin_headers, db: Session, _tenant_session_to_test_db
):
    created = client.post("/admin/accounts", json=_account_payload(), headers=admin_headers).json()
    tid = created["tenant"]["id"]
    _seed_business_data(db, tid)
    assert db.query(Client).filter(Client.tenant_id == tid).count() == 1
    assert db.query(AgendaEvent).filter(AgendaEvent.tenant_id == tid).count() == 1

    resp = client.delete(f"/admin/accounts/{tid}", headers=admin_headers)
    assert resp.status_code == 204, resp.text

    # IV1 — purga: tabelas de negócio do tenant ficam vazias; tenant e usuários removidos
    assert db.query(Client).filter(Client.tenant_id == tid).count() == 0
    assert db.query(AgendaEvent).filter(AgendaEvent.tenant_id == tid).count() == 0
    assert db.query(Tenant).filter(Tenant.id == tid).first() is None
    assert db.query(User).filter(User.tenant_id == tid).count() == 0

    # AC2 — log de plataforma criado com ator + snapshot do tenant corretos
    master = db.query(User).filter(User.is_platform_admin.is_(True)).first()
    logs = (
        db.query(PlatformAuditEntry)
        .filter(PlatformAuditEntry.target_tenant_id == tid)
        .all()
    )
    assert len(logs) == 1
    log = logs[0]
    assert log.action == "account_deleted"
    assert log.target_tenant_slug == "clientepagante"
    assert log.actor_user_id == master.id
    assert log.actor_email == ADMIN_EMAIL

    # IV3 — o log SOBREVIVE à exclusão: continua consultável mesmo sem o tenant/users
    assert db.query(PlatformAuditEntry).filter(
        PlatformAuditEntry.target_tenant_id == tid
    ).count() == 1


def test_delete_account_blocks_tenant_with_platform_admin(
    client: TestClient, admin_headers, db: Session, _tenant_session_to_test_db
):
    master = db.query(User).filter(User.is_platform_admin.is_(True)).first()
    resp = client.delete(f"/admin/accounts/{master.tenant_id}", headers=admin_headers)
    assert resp.status_code == 400
    # exclusão bloqueada não gera log de exclusão
    assert db.query(PlatformAuditEntry).count() == 0


def test_delete_account_404_for_unknown_tenant(
    client: TestClient, admin_headers, db: Session, _tenant_session_to_test_db
):
    resp = client.delete("/admin/accounts/tenant-inexistente-1234", headers=admin_headers)
    assert resp.status_code == 404
    assert db.query(PlatformAuditEntry).count() == 0
