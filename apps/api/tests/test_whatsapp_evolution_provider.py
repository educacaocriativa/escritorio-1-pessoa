"""Testes do provider Evolution API (WhatsApp não-oficial/Baileys) — Onda 1 da feature de
WhatsApp por Evolution (ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md).

Mesma convenção de tests/test_whatsapp.py (provider Meta): a chamada real (`httpx.post`) é
sempre mockada — este ambiente não tem uma instância Evolution real. Validação contra uma
instância real fica para o checklist manual, na VPS.

Este provider NÃO é chamado por nenhum código de produção ainda (o despachante continua
hardcoded em `meta` até a Onda 2) — estes testes cobrem só o módulo isolado.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from app.config import settings
from app.core.whatsapp.providers import evolution


def test_send_text_logged_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "")

    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover
        raise AssertionError("httpx.post não deveria ser chamado sem api key")

    monkeypatch.setattr(httpx, "post", _boom)
    status = evolution.send_text(to="5511999999999", text="oi", instance="e1p-tenant-1")
    assert status == "logged"


def test_send_text_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "key-123")
    monkeypatch.setattr(settings, "evolution_api_url", "http://evolution:8080")
    captured: list[dict] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    def _fake_post(url: str, **kwargs: object) -> _Resp:
        captured.append({"url": url, "headers": kwargs.get("headers"), "json": kwargs.get("json")})
        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)
    status = evolution.send_text(to="5511988887777", text="oi", instance="e1p-tenant-1")

    assert status == "sent"
    assert captured[0]["url"] == "http://evolution:8080/message/sendText/e1p-tenant-1"
    assert captured[0]["headers"] == {"apikey": "key-123"}
    assert captured[0]["json"] == {"number": "5511988887777", "text": "oi", "delay": 1000}


def test_send_text_failed_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "key-123")

    def _raise(*_a: object, **_k: object) -> None:
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx, "post", _raise)
    status = evolution.send_text(to="5511988887777", text="oi", instance="e1p-tenant-1")
    assert status == "failed"


def test_send_text_failed_on_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "key-123")

    class _ErrResp:
        status_code = 500

        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError(
                "erro", request=httpx.Request("POST", "https://x"), response=self
            )

    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: _ErrResp())
    status = evolution.send_text(to="5511988887777", text="oi", instance="e1p-tenant-1")
    assert status == "failed"


def test_upload_media_is_local_base64_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Evolution API não tem endpoint de upload separado — envia mídia inline (base64) no
    próprio POST de envio. `upload_media` aqui é só uma conveniência LOCAL para manter o mesmo
    padrão de 2 passos (upload → send com media_id) que o despachante já usa para o Meta —
    ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md."""

    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover
        raise AssertionError("upload_media não deveria bater rede")

    monkeypatch.setattr(httpx, "post", _boom)
    monkeypatch.setattr(httpx, "get", _boom)
    ref = evolution.upload_media(
        file_bytes=b"conteudo-fake", filename="cardapio.pdf", mime_type="application/pdf",
    )
    assert base64.b64decode(ref) == b"conteudo-fake"


def test_send_media_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "key-123")
    monkeypatch.setattr(settings, "evolution_api_url", "http://evolution:8080")
    captured: list[dict] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    def _fake_post(url: str, **kwargs: object) -> _Resp:
        captured.append({"url": url, "json": kwargs.get("json")})
        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)
    media_ref = evolution.upload_media(
        file_bytes=b"cardapio-bytes", filename="cardapio.pdf", mime_type="application/pdf",
    )
    status = evolution.send_media(
        to="5511988887777", instance="e1p-tenant-1", kind="document",
        media_id=media_ref, caption="Segue o cardápio",
    )
    assert status == "sent"
    assert captured[0]["url"] == "http://evolution:8080/message/sendMedia/e1p-tenant-1"
    body = captured[0]["json"]
    assert body["number"] == "5511988887777"
    assert body["mediatype"] == "document"
    assert body["caption"] == "Segue o cardápio"
    assert base64.b64decode(body["media"]) == b"cardapio-bytes"


def test_send_media_logged_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "")

    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover
        raise AssertionError("não deveria bater rede sem api key")

    monkeypatch.setattr(httpx, "post", _boom)
    media_ref = evolution.upload_media(
        file_bytes=b"x", filename="a.pdf", mime_type="application/pdf",
    )
    status = evolution.send_media(
        to="5511988887777", instance="e1p-tenant-1", kind="document", media_id=media_ref,
    )
    assert status == "logged"


@pytest.mark.parametrize(
    "call",
    [
        lambda: evolution.send_template(
            to="x", instance="i", template_name="t", language="pt_BR", variables=[],
        ),
        lambda: evolution.create_template(
            waba_id="w", token="t", name="n", language="pt_BR", category="MARKETING",
            body_text="b", variable_examples=[],
        ),
        lambda: evolution.fetch_template_status(token="t", meta_template_id="m"),
        lambda: evolution.delete_template(waba_id="w", token="t", name="n"),
        lambda: evolution.verify_webhook_signature(
            app_secret="s", body=b"{}", signature_header=None,
        ),
        lambda: evolution.fetch_media_url(token="t", media_id="m"),
        lambda: evolution.download_media(token="t", url="https://x"),
    ],
)
def test_unsupported_operations_raise_clear_error(call) -> None:
    with pytest.raises(evolution.EvolutionUnsupportedError):
        call()
