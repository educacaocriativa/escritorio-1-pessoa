"""Testes do despachante (core/whatsapp/__init__.py) pro ramo Evolution — cobre um bug real
achado em produção: send_text/send_media/upload_media chamavam SEMPRE o provider com
token=/phone_id= (parâmetros da Meta), mesmo quando `_resolve` escolhia `evolution`, cujas
funções não aceitam esses kwargs (`TypeError`). Nunca foi pego porque, até essa mensagem real
em produção, nenhuma resposta tinha sido enviada de fato por um tenant conectado via Evolution
— toda a suíte anterior (test_whatsapp.py) só cobre o provider Meta."""
from __future__ import annotations

from app.core import whatsapp
from app.core.whatsapp.providers import evolution
from app.modules.settings.models import TenantProfile

TENANT_ID = "99999999-9999-9999-9999-999999999999"


def _evolution_profile() -> TenantProfile:
    return TenantProfile(tenant_id=TENANT_ID, whatsapp_provider="evolution")


def test_send_text_dispatches_to_evolution_with_instance_not_token(
    monkeypatch,
) -> None:
    calls: list[dict] = []

    def _fake_send_text(**kwargs: object) -> str:
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(evolution, "send_text", _fake_send_text)
    status = whatsapp.send_text(to="5511999999999", text="oi", profile=_evolution_profile())
    assert status == "sent"
    assert calls == [{
        "to": "5511999999999", "text": "oi", "instance": f"e1p-{TENANT_ID}",
    }]


def test_send_media_dispatches_to_evolution_with_instance_not_token(
    monkeypatch,
) -> None:
    calls: list[dict] = []

    def _fake_send_media(**kwargs: object) -> str:
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(evolution, "send_media", _fake_send_media)
    status = whatsapp.send_media(
        to="5511999999999", kind="image", media_id="base64ref", caption="legenda",
        profile=_evolution_profile(),
    )
    assert status == "sent"
    assert calls == [{
        "to": "5511999999999", "instance": f"e1p-{TENANT_ID}", "kind": "image",
        "media_id": "base64ref", "caption": "legenda",
    }]


def test_upload_media_dispatches_to_evolution_without_token_or_phone_id(
    monkeypatch,
) -> None:
    calls: list[dict] = []

    def _fake_upload_media(**kwargs: object) -> str:
        calls.append(kwargs)
        return "base64-ref"

    monkeypatch.setattr(evolution, "upload_media", _fake_upload_media)
    media_id = whatsapp.upload_media(
        file_bytes=b"bytes", filename="foto.jpg", mime_type="image/jpeg",
        profile=_evolution_profile(),
    )
    assert media_id == "base64-ref"
    assert calls == [{
        "file_bytes": b"bytes", "filename": "foto.jpg", "mime_type": "image/jpeg",
    }]


def test_send_text_without_profile_still_dispatches_to_meta() -> None:
    # Retrocompatibilidade preservada: sem profile, cai sempre em Meta (token=/phone_id= diretos).
    assert whatsapp._resolve(None) is whatsapp.meta
