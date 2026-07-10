"""Idle timeout LGPD (Story 1.3): expiração por inatividade + reemissão via /auth/refresh.

O JWT ganha duas camadas: ``exp`` = janela de inatividade (30 min, deslizada por atividade) e
``abs_exp`` = teto absoluto de 7 dias (preserva a garantia atual do JWT). Sem estado no banco.
"""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    refresh_access_token,
)

VALID = {
    "legal_name": "João Silva Advocacia",
    "document": "12345678000195",
    "slug": "joaosilva",
    "email": "joao@example.com",
    "name": "João Silva",
    "password": "senha-super-secreta",
}


def _register(client: TestClient):
    return client.post("/auth/register", json=VALID)


# ── Unidade: estrutura do token (AC1, AC3) ───────────────────────────────────
def test_token_has_idle_and_absolute_layers():
    token = create_access_token({"sub": "u1", "tenant_id": "t1"})
    payload = decode_access_token(token)
    assert payload is not None
    # A janela de inatividade (exp) é bem menor que o teto absoluto (abs_exp = 7 dias).
    assert payload["exp"] < payload["abs_exp"]
    idle_seconds = payload["exp"] - payload["iat"]
    assert idle_seconds <= settings.session_idle_timeout_minutes * 60 + 5
    # O teto absoluto continua sendo os 7 dias do JWT (AC3 — não afrouxado).
    ceiling_seconds = payload["abs_exp"] - payload["iat"]
    assert ceiling_seconds >= settings.jwt_expire_minutes * 60 - 5


def test_refresh_slides_idle_window_preserving_ceiling():
    original = create_access_token({"sub": "u1", "tenant_id": "t1", "role": "owner"})
    payload = decode_access_token(original)
    new_token = refresh_access_token(payload)
    assert new_token is not None
    new_payload = decode_access_token(new_token)
    assert new_payload is not None
    # Teto absoluto e identidade preservados na reemissão.
    assert new_payload["abs_exp"] == payload["abs_exp"]
    assert new_payload["sub"] == "u1"
    assert new_payload["role"] == "owner"


def test_refresh_returns_none_without_abs_exp():
    # Token legado (pré-Story 1.3, sem abs_exp) não pode ser deslizado → fail-closed.
    assert refresh_access_token({"sub": "u1", "tenant_id": "t1"}) is None


def test_refresh_returns_none_after_absolute_cap():
    past = datetime.now(UTC) - timedelta(seconds=1)
    payload = {"sub": "u1", "tenant_id": "t1", "abs_exp": int(past.timestamp())}
    assert refresh_access_token(payload) is None


def test_refresh_caps_new_window_at_ceiling():
    # Se o teto está logo ali (20s) e o idle é 30 min, a nova janela não passa do teto.
    ceiling = datetime.now(UTC) + timedelta(seconds=20)
    payload = {"sub": "u1", "tenant_id": "t1", "abs_exp": int(ceiling.timestamp())}
    new_token = refresh_access_token(payload)
    assert new_token is not None
    new_payload = decode_access_token(new_token)
    assert new_payload is not None
    assert new_payload["exp"] <= new_payload["abs_exp"]


# ── Integração: endpoint /auth/refresh (AC1, IV1, IV3) ───────────────────────
def test_refresh_endpoint_returns_working_token(client: TestClient):
    token = _register(client).json()["access_token"]
    r = client.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]
    assert new_token
    # O token renovado funciona numa rota protegida.
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me.status_code == 200


def test_refresh_without_token_rejected(client: TestClient):
    assert client.post("/auth/refresh").status_code == 401


# ── Integração: expiração por inatividade é fail-closed (AC1) ─────────────────
def test_idle_expired_token_is_rejected(client: TestClient, monkeypatch):
    body = _register(client).json()
    user, tenant = body["user"], body["tenant"]
    # Simula 'última atividade' há muito tempo: idle negativo => token nasce expirado.
    monkeypatch.setattr(settings, "session_idle_timeout_minutes", -1)
    stale = create_access_token(
        {
            "sub": user["id"],
            "tenant_id": tenant["id"],
            "role": user["role"],
            "allowed_modules": user["allowed_modules"],
            "is_platform_admin": user["is_platform_admin"],
        }
    )
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {stale}"})
    assert r.status_code == 401


def test_idle_expired_token_cannot_refresh(client: TestClient, monkeypatch):
    body = _register(client).json()
    user, tenant = body["user"], body["tenant"]
    monkeypatch.setattr(settings, "session_idle_timeout_minutes", -1)
    stale = create_access_token({"sub": user["id"], "tenant_id": tenant["id"]})
    # Token já expirado por inatividade não desliza a própria sessão (fail-closed).
    r = client.post("/auth/refresh", headers={"Authorization": f"Bearer {stale}"})
    assert r.status_code == 401


# ── IV2: rotas públicas não são afetadas ─────────────────────────────────────
def test_public_route_not_gated_by_idle(client: TestClient):
    # Rota pública (sem login) NÃO passa por get_current_user → nunca 401 por sessão/inatividade.
    r = client.get("/public/pages/inexistente-slug")
    assert r.status_code != 401
