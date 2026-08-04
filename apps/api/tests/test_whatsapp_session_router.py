"""Testes das rotas de app/modules/whatsapp_session/router.py."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings

REGISTER = {
    "legal_name": "Sessao WA", "document": "39393939000107", "slug": "sessaowa",
    "email": "sessaowa@example.com", "name": "Se", "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _evolution_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "key")
    monkeypatch.setattr(settings, "evolution_api_url", "http://evolution:8080")


def test_connect_endpoint_returns_qr(client: TestClient, headers, monkeypatch) -> None:
    def _fake_post(url: str, **_k: object) -> object:
        class _R:
            status_code = 201
            text = ""

        return _R()

    def _fake_get(url: str, **_k: object) -> object:
        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"base64": "QR"}

        return _R()

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(httpx, "get", _fake_get)
    resp = client.post("/whatsapp-session/connect", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"qr_base64": "QR", "status": "connecting"}


def test_connect_without_evolution_configured_returns_503(
    client: TestClient, headers, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "")
    resp = client.post("/whatsapp-session/connect", headers=headers)
    assert resp.status_code == 503


def test_status_before_any_connect_is_never(client: TestClient, headers) -> None:
    resp = client.get("/whatsapp-session/status", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "never"}


def test_confirm_then_profile_reflects_provider(client: TestClient, headers, monkeypatch) -> None:
    def _fake_post_create(url: str, **_k: object) -> object:
        class _R:
            status_code = 201
            text = ""

        return _R()

    def _fake_get_qr(url: str, **_k: object) -> object:
        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"base64": "QR"}

        return _R()

    monkeypatch.setattr(httpx, "post", _fake_post_create)
    monkeypatch.setattr(httpx, "get", _fake_get_qr)
    client.post("/whatsapp-session/connect", headers=headers)

    def _fake_get_status(url: str, **kwargs: object) -> object:
        params = kwargs.get("params") or {}

        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{
                    "instance": {"instanceName": params.get("instanceName"), "status": "open"}
                }]

        return _R()

    monkeypatch.setattr(httpx, "get", _fake_get_status)
    resp = client.post("/whatsapp-session/confirm", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "connected"}

    profile = client.get("/settings/profile", headers=headers).json()
    assert profile["whatsapp_provider"] == "evolution"


def test_disconnect_clears_provider(client: TestClient, headers, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx, "delete", lambda *_a, **_k: type("R", (), {"status_code": 200})()
    )
    resp = client.delete("/whatsapp-session", headers=headers)
    assert resp.status_code == 204
