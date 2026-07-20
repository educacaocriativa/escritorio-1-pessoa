"""Testes do provedor de WhatsApp (WhatsApp Cloud API / Meta).

Cobre os 3 status possíveis de `send_text`:
- "logged": sem WHATSAPP_TOKEN/PHONE_ID → não tenta a chamada (graceful degradation).
- "sent":   com credenciais + resposta 200 da Graph API.
- "failed": com credenciais mas o provedor levanta exceção (não propaga — IV3).

A chamada real (`httpx.post`) é sempre mockada — este ambiente não tem credenciais reais.
"""
import hashlib
import hmac

import httpx
import pytest

from app.config import settings
from app.core import whatsapp


class _FakeResponse:
    """Resposta mínima com o contrato usado por send_text/send_template (raise_for_status) +
    .json()/.content pros novos testes de mídia."""

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self._json: dict = {}
        self._content: bytes = b""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "erro", request=httpx.Request("POST", "https://x"), response=self
            )

    def json(self) -> dict:
        return self._json

    @property
    def content(self) -> bytes:
        return self._content


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


# ── Templates (gerência administrativa — PROPAGA exceção, ver WhatsappApiError) ─────────


class _FakeJsonResponse:
    """Resposta mínima com o contrato usado pelas funções de template (status_code + .json())."""

    def __init__(self, status_code: int = 200, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self) -> dict:
        return self._payload


def test_create_template_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _FakeJsonResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _FakeJsonResponse(200, {"id": "meta-123", "status": "PENDING"})

    monkeypatch.setattr(httpx, "post", _fake_post)
    resp = whatsapp.create_template(
        waba_id="waba1", token="tok", name="boas_vindas", language="pt_BR",
        category="MARKETING", body_text="Olá {{1}}, bem-vindo!", variable_examples=["Maria"],
    )
    assert resp == {"id": "meta-123", "status": "PENDING"}
    assert captured["url"] == "https://graph.facebook.com/v21.0/waba1/message_templates"
    assert captured["headers"] == {"Authorization": "Bearer tok"}
    assert captured["json"] == {
        "name": "boas_vindas",
        "language": "pt_BR",
        "category": "MARKETING",
        "components": [
            {
                "type": "BODY",
                "text": "Olá {{1}}, bem-vindo!",
                "example": {"body_text": [["Maria"]]},
            }
        ],
    }


def test_create_template_without_variables_omits_example(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _FakeJsonResponse:
        captured["json"] = kwargs.get("json")
        return _FakeJsonResponse(200, {"id": "meta-1", "status": "PENDING"})

    monkeypatch.setattr(httpx, "post", _fake_post)
    whatsapp.create_template(
        waba_id="waba1", token="tok", name="sem_var", language="pt_BR",
        category="UTILITY", body_text="Olá!", variable_examples=[],
    )
    assert "example" not in captured["json"]["components"][0]


def test_create_template_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.create_template(
            waba_id="waba1", token="tok", name="x", language="pt_BR",
            category="MARKETING", body_text="Olá", variable_examples=[],
        )


def test_create_template_raises_on_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "post",
        lambda *_a, **_k: _FakeJsonResponse(400, {"error": {"message": "nome inválido"}}),
    )
    with pytest.raises(whatsapp.WhatsappApiError, match="nome inválido"):
        whatsapp.create_template(
            waba_id="waba1", token="tok", name="x", language="pt_BR",
            category="MARKETING", body_text="Olá", variable_examples=[],
        )


def test_fetch_template_status_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_get(url: str, **kwargs: object) -> _FakeJsonResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        captured["headers"] = kwargs.get("headers")
        return _FakeJsonResponse(
            200, {"status": "APPROVED", "category": "MARKETING", "rejected_reason": None}
        )

    monkeypatch.setattr(httpx, "get", _fake_get)
    resp = whatsapp.fetch_template_status(token="tok", meta_template_id="meta-123")
    assert resp == {"status": "APPROVED", "category": "MARKETING", "rejected_reason": None}
    assert captured["url"] == "https://graph.facebook.com/v21.0/meta-123"
    assert captured["params"] == {"fields": "status,category,rejected_reason"}


def test_fetch_template_status_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: _FakeJsonResponse(404, {}, "not found"))
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.fetch_template_status(token="tok", meta_template_id="meta-404")


def test_delete_template_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_delete(url: str, **kwargs: object) -> _FakeJsonResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _FakeJsonResponse(200, {"success": True})

    monkeypatch.setattr(httpx, "delete", _fake_delete)
    whatsapp.delete_template(waba_id="waba1", token="tok", name="boas_vindas")
    assert captured["url"] == "https://graph.facebook.com/v21.0/waba1/message_templates"
    assert captured["params"] == {"name": "boas_vindas"}


def test_delete_template_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "delete", lambda *_a, **_k: _FakeJsonResponse(400, {}, "erro"))
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.delete_template(waba_id="waba1", token="tok", name="x")


def test_send_template_logged_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover - não deve ser chamado
        raise AssertionError("httpx.post não deveria ser chamado no caminho 'logged'")

    monkeypatch.setattr(httpx, "post", _boom)
    assert whatsapp.send_template(
        to="5511999999999", token="", phone_id="", template_name="boas_vindas",
        language="pt_BR", variables=["Maria"],
    ) == "logged"
    # Sem phone_id, mesmo com token: também 'logged'.
    assert whatsapp.send_template(
        to="5511999999999", token="tok", phone_id="", template_name="boas_vindas",
        language="pt_BR", variables=[],
    ) == "logged"


def test_send_template_sent_with_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200)

    monkeypatch.setattr(httpx, "post", _fake_post)
    status = whatsapp.send_template(
        to="5511988887777", token="tok", phone_id="123456789", template_name="boas_vindas",
        language="pt_BR", variables=["Maria"],
    )
    assert status == "sent"
    assert captured["url"] == "https://graph.facebook.com/v21.0/123456789/messages"
    assert captured["headers"] == {"Authorization": "Bearer tok"}
    assert captured["json"] == {
        "messaging_product": "whatsapp",
        "to": "5511988887777",
        "type": "template",
        "template": {
            "name": "boas_vindas",
            "language": {"code": "pt_BR"},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": "Maria"}]}
            ],
        },
    }


def test_send_template_sent_without_variables_has_empty_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200)

    monkeypatch.setattr(httpx, "post", _fake_post)
    whatsapp.send_template(
        to="5511988887777", token="tok", phone_id="123456789", template_name="sem_var",
        language="pt_BR", variables=[],
    )
    assert captured["json"]["template"]["components"] == []


def test_send_template_failed_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)
    status = whatsapp.send_template(
        to="5511988887777", token="tok", phone_id="123456789", template_name="x",
        language="pt_BR", variables=[],
    )
    assert status == "failed"


def test_send_template_failed_on_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: _FakeResponse(500))
    status = whatsapp.send_template(
        to="5511988887777", token="tok", phone_id="123456789", template_name="x",
        language="pt_BR", variables=[],
    )
    assert status == "failed"


# ── Webhook, media upload/download/send ───────────────────────────────────────────────────


def test_verify_webhook_signature_valid():
    body = b'{"hello":"world"}'
    secret = "shh-its-a-secret"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert whatsapp.verify_webhook_signature(
        app_secret=secret, body=body, signature_header=sig
    ) is True


def test_verify_webhook_signature_invalid():
    assert whatsapp.verify_webhook_signature(
        app_secret="shh-its-a-secret", body=b'{"hello":"world"}',
        signature_header="sha256=deadbeef",
    ) is False


def test_verify_webhook_signature_missing_header():
    assert whatsapp.verify_webhook_signature(
        app_secret="shh-its-a-secret", body=b"{}", signature_header=None
    ) is False


def test_upload_media_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["url"] = url
        captured["files"] = kwargs.get("files")
        resp = _FakeResponse(200)
        resp._json = {"id": "media-123"}
        return resp

    monkeypatch.setattr(httpx, "post", _fake_post)
    media_id = whatsapp.upload_media(
        phone_id="123456789", token="fake-token", file_bytes=b"fake-bytes",
        filename="cardapio.pdf", mime_type="application/pdf",
    )
    assert media_id == "media-123"
    assert captured["url"] == "https://graph.facebook.com/v21.0/123456789/media"


def test_upload_media_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: _FakeResponse(500))
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.upload_media(
            phone_id="123", token="tok", file_bytes=b"x", filename="a.pdf",
            mime_type="application/pdf",
        )


def test_fetch_media_url_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_get(url: str, **_k: object) -> _FakeResponse:
        resp = _FakeResponse(200)
        resp._json = {"url": "https://lookaside.fbsbx.com/whatsapp_business/temp/abc"}
        return resp

    monkeypatch.setattr(httpx, "get", _fake_get)
    url = whatsapp.fetch_media_url(token="tok", media_id="media-123")
    assert url == "https://lookaside.fbsbx.com/whatsapp_business/temp/abc"


def test_download_media_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_get(url: str, **_k: object) -> _FakeResponse:
        resp = _FakeResponse(200)
        resp._content = b"file-bytes-here"
        return resp

    monkeypatch.setattr(httpx, "get", _fake_get)
    data = whatsapp.download_media(token="tok", url="https://example.com/f")
    assert data == b"file-bytes-here"


def test_send_media_logged_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("httpx.post não deveria ser chamado no caminho 'logged'")

    monkeypatch.setattr(httpx, "post", _boom)
    status = whatsapp.send_media(
        to="5511999999999", token="", phone_id="", kind="image", media_id="m1"
    )
    assert status == "logged"


def test_send_media_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_post(url: str, **kwargs: object) -> _FakeResponse:
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200)

    monkeypatch.setattr(httpx, "post", _fake_post)
    status = whatsapp.send_media(
        to="5511988887777", token="tok", phone_id="123", kind="document",
        media_id="media-123", caption="Cardápio",
    )
    assert status == "sent"
    assert captured["json"] == {
        "messaging_product": "whatsapp", "to": "5511988887777", "type": "document",
        "document": {"id": "media-123", "caption": "Cardápio"},
    }


def test_send_media_failed_when_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)
    # Falha do provedor não propaga (IV3): retorna "failed".
    assert whatsapp.send_media(
        to="5511988887777", token="tok", phone_id="123", kind="image", media_id="m1"
    ) == "failed"


def test_send_media_failed_when_provider_returns_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: _FakeResponse(500))
    # HTTPStatusError (via raise_for_status) também é capturado → "failed".
    assert whatsapp.send_media(
        to="5511988887777", token="tok", phone_id="123", kind="image", media_id="m1"
    ) == "failed"


def test_upload_media_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.upload_media(
            phone_id="123", token="tok", file_bytes=b"x", filename="a.pdf",
            mime_type="application/pdf",
        )


def test_fetch_media_url_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "get", _raise)
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.fetch_media_url(token="tok", media_id="media-123")


def test_fetch_media_url_raises_on_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: _FakeResponse(404))
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.fetch_media_url(token="tok", media_id="media-123")


def test_download_media_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "get", _raise)
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.download_media(token="tok", url="https://example.com/f")


def test_download_media_raises_on_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: _FakeResponse(500))
    with pytest.raises(whatsapp.WhatsappApiError):
        whatsapp.download_media(token="tok", url="https://example.com/f")
