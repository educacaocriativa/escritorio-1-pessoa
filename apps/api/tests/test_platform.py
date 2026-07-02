"""Testes do Super Admin (Master). Delete real (purga) é coberto no e2e Docker (usa Postgres)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.auth.models import Tenant, User

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
        "document": "12345678000190",
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
        "document": "11122233344",
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
    assert staff["document"] == "11122233344" and staff["phone"] == "27999990000"
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


def test_staff_whatsapp_delivery(client: TestClient, admin_headers):
    tid = _tenant_id(client, admin_headers, slug="escw", email="escw@example.com")
    invite = client.post(
        f"/admin/accounts/{tid}/users",
        json=_staff_body(email="zap@escw.com", delivery="whatsapp"),
        headers=admin_headers,
    ).json()
    assert invite["delivery"] == "whatsapp" and invite["delivery_status"] in ("sent", "logged")


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
