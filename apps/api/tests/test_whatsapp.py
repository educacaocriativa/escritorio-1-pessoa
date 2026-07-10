"""Testes do provedor de WhatsApp (WhatsApp Cloud API / Meta).

Cobre os 3 status possíveis de `send_text`:
- "logged": sem WHATSAPP_TOKEN/PHONE_ID → não tenta a chamada (graceful degradation).
- "sent":   com credenciais + resposta 200 da Graph API.
- "failed": com credenciais mas o provedor levanta exceção (não propaga — IV3).

A chamada real (`httpx.post`) é sempre mockada — este ambiente não tem credenciais reais.
"""
import httpx
import pytest

from app.config import settings
from app.core import whatsapp


class _FakeResponse:
    """Resposta mínima com o contrato usado por send_text (raise_for_status)."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "erro", request=httpx.Request("POST", "https://x"), response=self
            )


@pytest.fixture()
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ativa o branch de envio real com credenciais fake."""
    monkeypatch.setattr(settings, "whatsapp_token", "fake-token")
    monkeypatch.setattr(settings, "whatsapp_phone_id", "123456789")


def test_logged_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    # Sem credenciais, não deve nem chamar httpx.post.
    monkeypatch.setattr(settings, "whatsapp_token", "")
    monkeypatch.setattr(settings, "whatsapp_phone_id", "")

    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover - não deve ser chamado
        raise AssertionError("httpx.post não deveria ser chamado no caminho 'logged'")

    monkeypatch.setattr(httpx, "post", _boom)
    assert whatsapp.send_text(to="5511999999999", text="oi") == "logged"


def test_sent_when_provider_returns_200(
    monkeypatch: pytest.MonkeyPatch, _configured: None
) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200)

    monkeypatch.setattr(httpx, "post", _fake_post)
    assert whatsapp.send_text(to="5511988887777", text="Olá") == "sent"
    # Confere que o payload da Graph API foi montado corretamente.
    assert captured["url"] == "https://graph.facebook.com/v21.0/123456789/messages"
    assert captured["headers"] == {"Authorization": "Bearer fake-token"}
    assert captured["json"] == {
        "messaging_product": "whatsapp",
        "to": "5511988887777",
        "type": "text",
        "text": {"body": "Olá"},
    }


def test_failed_when_provider_raises(
    monkeypatch: pytest.MonkeyPatch, _configured: None
) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)
    # Falha do provedor não propaga (IV3): retorna "failed".
    assert whatsapp.send_text(to="5511988887777", text="Olá") == "failed"


def test_failed_when_provider_returns_error_status(
    monkeypatch: pytest.MonkeyPatch, _configured: None
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: _FakeResponse(401))
    # HTTPStatusError (via raise_for_status) também é capturado → "failed".
    assert whatsapp.send_text(to="5511988887777", text="Olá") == "failed"
