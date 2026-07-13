"""Testes da integração Google (Meet/Calendar OAuth) — Story 4.1.

Todas as chamadas HTTP ao Google são MOCKADAS (não batemos na API real). A validação
ponta-a-ponta com um Google Cloud project real é manual, pós-deploy (ver Dev Agent Record).
"""
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.modules.google_calendar import service
from app.modules.google_calendar.models import DEFAULT_SCOPE

REGISTER = {
    "legal_name": "Clínica Maria",
    "document": "98765432000198",
    "slug": "clinicamaria",
    "email": "maria@example.com",
    "name": "Maria",
    "password": "uma-senha-bem-forte",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def configured(monkeypatch) -> None:
    """Simula o app OAuth global da plataforma configurado."""
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(
        settings,
        "google_oauth_redirect_uri",
        "https://api.e1p.com/integrations/google/callback",
    )


class FakeResp:
    def __init__(self, data: dict):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


def _mock_google(monkeypatch, *, revoke_raises: bool = False) -> None:
    def fake_post(url: str, **kw):
        if "revoke" in url:
            if revoke_raises:
                raise httpx.ConnectError("boom")
            return FakeResp({})
        # token exchange / refresh
        return FakeResp(
            {
                "access_token": "ya29.fake-access",
                "refresh_token": "1//fake-refresh",
                "expires_in": 3600,
                "scope": DEFAULT_SCOPE,
            }
        )

    def fake_get(url: str, **kw):
        return FakeResp({"email": "owner@gmail.com"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)


def test_status_unconfigured(client: TestClient, headers):
    resp = client.get("/integrations/google/status", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"configured": False, "connected": False, "email": None}


def test_connect_409_without_config(client: TestClient, headers):
    resp = client.get("/integrations/google/connect", headers=headers)
    assert resp.status_code == 409
    assert "não configurada" in resp.json()["detail"]


def test_connect_builds_authorize_url(client: TestClient, headers, configured):
    resp = client.get("/integrations/google/connect", headers=headers)
    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert q["client_id"] == ["test-client-id"]
    assert q["scope"] == [DEFAULT_SCOPE]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    # state assinado presente e válido (decodifica para um tenant_id)
    from app.core.security import verify_oauth_state

    assert verify_oauth_state(q["state"][0]) is not None


def test_callback_invalid_state(client: TestClient, headers, configured):
    resp = client.get(
        "/integrations/google/callback",
        params={"code": "abc", "state": "not-a-valid-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/config?google=error")


def test_callback_missing_code(client: TestClient, headers, configured):
    # state válido mas sem code → erro
    url = client.get("/integrations/google/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get(
        "/integrations/google/callback",
        params={"state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/config?google=error")


def test_callback_happy_connects_account(client: TestClient, headers, configured, monkeypatch):
    _mock_google(monkeypatch)
    url = client.get("/integrations/google/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]

    resp = client.get(
        "/integrations/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/config?google=connected")

    # status agora reflete conectado + e-mail (mas NUNCA os tokens — IV3)
    status = client.get("/integrations/google/status", headers=headers).json()
    assert status == {"configured": True, "connected": True, "email": "owner@gmail.com"}


def test_callback_userinfo_failure_still_connects(
    client: TestClient, headers, configured, monkeypatch
):
    """Achado em produção (2026-07-12): o userinfo é só para exibição ("conectado como ...");
    uma falha nele (rede, escopo insuficiente) NUNCA deve descartar tokens já obtidos com
    sucesso — mesmo princípio de robustez do módulo (ver docstring de handle_callback)."""

    def fake_post(url: str, **kw):
        return FakeResp(
            {"access_token": "ya29.fake-access", "refresh_token": "1//fake-refresh",
             "expires_in": 3600, "scope": DEFAULT_SCOPE}
        )

    def fake_get_raises(url: str, **kw):
        raise httpx.HTTPStatusError("401", request=None, response=None)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get_raises)

    url = client.get("/integrations/google/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = client.get(
        "/integrations/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"].endswith("/config?google=connected")

    # Conectado mesmo sem e-mail (userinfo falhou) — tokens não foram descartados.
    status = client.get("/integrations/google/status", headers=headers).json()
    assert status == {"configured": True, "connected": True, "email": ""}


def test_callback_reconnect_updates_same_credential(
    client: TestClient, headers, configured, monkeypatch
):
    _mock_google(monkeypatch)
    url = client.get("/integrations/google/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get(
        "/integrations/google/callback",
        params={"code": "c1", "state": state},
        follow_redirects=False,
    )
    client.get(
        "/integrations/google/callback",
        params={"code": "c2", "state": state},
        follow_redirects=False,
    )
    # Ainda uma única credencial (upsert, não duplica)
    from app.modules.google_calendar.models import GoogleCredential
    from tests.conftest import TestSession

    with TestSession() as s:
        assert s.query(GoogleCredential).count() == 1


def test_disconnect_removes_even_if_revoke_fails(
    client: TestClient, headers, configured, monkeypatch
):
    _mock_google(monkeypatch)
    url = client.get("/integrations/google/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get(
        "/integrations/google/callback",
        params={"code": "c", "state": state},
        follow_redirects=False,
    )
    # revogação falha, mas o disconnect deve remover a credencial localmente mesmo assim
    _mock_google(monkeypatch, revoke_raises=True)
    resp = client.post("/integrations/google/disconnect", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"

    status = client.get("/integrations/google/status", headers=headers).json()
    assert status["connected"] is False
    assert status["email"] is None


def test_disconnect_when_not_connected(client: TestClient, headers, configured):
    resp = client.post("/integrations/google/disconnect", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_connected"


def test_create_meet_event_noop_without_credential(client: TestClient, headers, db):
    """create_meet_event é no-op (None) quando o tenant não conectou o Google (AC3/IV1)."""

    class _Ev:
        title = "Reunião"
        description = ""
        starts_at = None
        ends_at = None
        guests: list = []

    assert service.create_meet_event(db, tenant_id="t" * 12, event=_Ev()) is None
