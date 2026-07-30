"""Testes do despachante `app/core/whatsapp/__init__.py` — a Onda 0 da feature de WhatsApp
por Evolution API (ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md).

`tests/test_whatsapp.py` já cobre o provider Meta em si (movido para `providers/meta.py` sem
mudança). Este arquivo cobre só a CAMADA NOVA: o parâmetro `profile=` e o gate anti-import-direto.
"""
from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from app.core import whatsapp


class _FakeProfile:
    """Dublê mínimo de TenantProfile — só os campos que o despachante lê. `whatsapp_provider`
    default None: estes testes (Onda 0) exercitam o caminho Meta via `profile=`, então o
    default precisa continuar resolvendo pra `meta` depois que `_resolve` (Onda 2) passou a
    ler esse campo de verdade."""

    def __init__(
        self, token: str | None, phone_id: str | None, whatsapp_provider: str | None = None
    ) -> None:
        self.whatsapp_token = token
        self.whatsapp_phone_id = phone_id
        self.whatsapp_provider = whatsapp_provider


def test_send_text_with_profile_equivalent_to_explicit_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    def _fake_post(url: str, **kwargs: object) -> _Resp:
        captured.append({"url": url, "headers": kwargs.get("headers")})
        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)

    profile = _FakeProfile(token="tok-via-profile", phone_id="999")
    status = whatsapp.send_text(to="5511999999999", text="oi", profile=profile)

    assert status == "sent"
    assert captured[0]["url"] == "https://graph.facebook.com/v21.0/999/messages"
    assert captured[0]["headers"] == {"Authorization": "Bearer tok-via-profile"}


def test_send_text_without_profile_falls_back_to_explicit_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover
        raise AssertionError("não deveria chamar httpx sem credenciais")

    monkeypatch.setattr(httpx, "post", _boom)
    # Nem profile, nem token/phone_id: cai no "logged" — mesmo comportamento de hoje.
    assert whatsapp.send_text(to="5511999999999", text="oi") == "logged"


def test_send_text_profile_with_empty_credentials_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: object, **_k: object) -> None:  # pragma: no cover
        raise AssertionError("não deveria chamar httpx sem credenciais")

    monkeypatch.setattr(httpx, "post", _boom)
    profile = _FakeProfile(token=None, phone_id=None)
    assert whatsapp.send_text(to="5511999999999", text="oi", profile=profile) == "logged"


def test_send_template_with_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    def _fake_post(url: str, **kwargs: object) -> _Resp:
        captured.append({"url": url})
        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)
    profile = _FakeProfile(token="tok", phone_id="123")
    status = whatsapp.send_template(
        to="5511988887777", profile=profile, template_name="boas_vindas",
        language="pt_BR", variables=["Maria"],
    )
    assert status == "sent"
    assert captured[0]["url"] == "https://graph.facebook.com/v21.0/123/messages"


def test_upload_media_with_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"id": "media-abc"}

    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: _Resp())
    profile = _FakeProfile(token="tok", phone_id="123")
    media_id = whatsapp.upload_media(
        profile=profile, file_bytes=b"bytes", filename="a.pdf", mime_type="application/pdf",
    )
    assert media_id == "media-abc"


def test_fetch_media_url_and_download_media_with_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _GetResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"url": "https://example.com/f"}

        @property
        def content(self) -> bytes:
            return b"file-bytes"

    monkeypatch.setattr(httpx, "get", lambda *_a, **_k: _GetResp())
    profile = _FakeProfile(token="tok", phone_id=None)
    url = whatsapp.fetch_media_url(profile=profile, media_id="media-1")
    assert url == "https://example.com/f"
    data = whatsapp.download_media(profile=profile, url=url)
    assert data == b"file-bytes"


def test_resolve_picks_evolution_when_profile_provider_is_evolution() -> None:
    from app.core.whatsapp.providers import evolution

    class _P:
        whatsapp_provider = "evolution"

    assert whatsapp._resolve(_P()) is evolution


def test_resolve_picks_meta_when_profile_provider_is_meta_or_none() -> None:
    from app.core.whatsapp.providers import meta

    class _Meta:
        whatsapp_provider = "meta"

    class _None:
        whatsapp_provider = None

    assert whatsapp._resolve(_Meta()) is meta
    assert whatsapp._resolve(_None()) is meta
    assert whatsapp._resolve(None) is meta


def test_no_direct_provider_imports() -> None:
    """Gate estrutural: nenhum arquivo fora de `app/core/whatsapp/` pode importar
    `app.core.whatsapp.providers` diretamente — todo consumidor passa pelo despachante
    (`from app.core import whatsapp`). Mesmo idioma de `test_tenancy_guard.py`/
    `test_money_planes.py`. Sem isto, a Onda 1/2 (branch por `whatsapp_provider`) pode degenerar
    em `if` espalhado pelos módulos de domínio."""
    app_root = Path(__file__).resolve().parent.parent / "app"
    whatsapp_pkg_dir = app_root / "core" / "whatsapp"
    offenders: list[str] = []

    for path in app_root.rglob("*.py"):
        if whatsapp_pkg_dir in path.parents or path.parent == whatsapp_pkg_dir:
            continue  # o próprio pacote pode importar seus providers
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - não esperado no código do projeto
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("app.core.whatsapp.providers"):
                    offenders.append(str(path.relative_to(app_root)))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.core.whatsapp.providers"):
                        offenders.append(str(path.relative_to(app_root)))

    assert not offenders, (
        "Import direto de provider fora do despachante em: "
        f"{offenders} — use `from app.core import whatsapp` e passe `profile=`."
    )
