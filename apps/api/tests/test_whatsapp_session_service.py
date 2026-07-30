"""Testes de app/modules/whatsapp_session/service.py — ciclo de vida da sessão Evolution
(Onda 2 da feature de WhatsApp por Evolution). httpx sempre mockado — sem instância real."""
from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.modules.settings import service as settings_service
from app.modules.whatsapp_session import service as session_service
from app.modules.whatsapp_session.models import PublicWhatsappInstance

TENANT_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _evolution_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "evolution_api_key", "global-key")
    monkeypatch.setattr(settings, "evolution_api_url", "http://evolution:8080")
    monkeypatch.setattr(settings, "internal_api_base_url", "http://api:8000")


def test_connect_creates_instance_configures_webhook_and_returns_qr(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def _fake_post(url: str, **kwargs: object) -> object:
        calls.append({"url": url, "json": kwargs.get("json")})

        class _Resp:
            status_code = 201
            text = ""

        return _Resp()

    def _fake_get(url: str, **kwargs: object) -> object:
        calls.append({"url": url})

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"base64": "data:image/png;base64,FAKE_QR"}

        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(httpx, "get", _fake_get)

    result = session_service.connect(db, tenant_id=TENANT_ID)

    assert result == {"qr_base64": "data:image/png;base64,FAKE_QR", "status": "connecting"}

    create_call = next(c for c in calls if "/instance/create" in c["url"])
    assert create_call["json"] == {
        "instanceName": "e1p-22222222-2222-2222-2222-222222222222",
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS",
    }

    webhook_call = next(c for c in calls if "/webhook/set/" in c["url"])
    assert webhook_call["url"].endswith(
        "/webhook/set/e1p-22222222-2222-2222-2222-222222222222"
    )
    assert webhook_call["json"]["webhook_by_events"] is False
    assert webhook_call["json"]["url"].startswith(
        "http://api:8000/internal/whatsapp/evolution/webhook/"
    )

    row = db.get(
        PublicWhatsappInstance, "e1p-22222222-2222-2222-2222-222222222222"
    )
    assert row is not None
    assert row.tenant_id == TENANT_ID
    assert row.last_status == "connecting"
    # o segredo do webhook usado na URL é o mesmo guardado na linha (cifrado em repouso, mas
    # o valor em texto plano lido de volta bate)
    assert row.webhook_secret in webhook_call["json"]["url"]


def test_connect_without_api_key_raises(db) -> None:
    from app.config import settings as cfg

    cfg.evolution_api_key = ""
    with pytest.raises(session_service.WhatsappSessionError):
        session_service.connect(db, tenant_id=TENANT_ID)
    cfg.evolution_api_key = "global-key"  # restaura p/ não vazar pro próximo teste


def test_get_status_never_without_instance_row(db) -> None:
    assert session_service.get_status(db, tenant_id=TENANT_ID) == "never"


def test_get_status_connecting_when_evolution_reports_non_open(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connecting",
    ))
    db.commit()

    def _fake_get(url: str, **kwargs: object) -> object:
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": "e1p-" + TENANT_ID, "status": "connecting"}}]

        return _Resp()

    monkeypatch.setattr(httpx, "get", _fake_get)
    assert session_service.get_status(db, tenant_id=TENANT_ID) == "connecting"


def test_get_status_does_not_write_to_db(db, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate de design: GET nunca escreve — ver Global Constraints do plano."""
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connecting",
    ))
    db.commit()

    def _fake_get(url: str, **kwargs: object) -> object:
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": "e1p-" + TENANT_ID, "status": "open"}}]

        return _Resp()

    monkeypatch.setattr(httpx, "get", _fake_get)
    profile_before = settings_service.get_profile(db, TENANT_ID).whatsapp_provider
    status = session_service.get_status(db, tenant_id=TENANT_ID)
    assert status == "connected"
    db.expire_all()
    profile_after = settings_service.get_profile(db, TENANT_ID).whatsapp_provider
    assert profile_before == profile_after  # nada mudou no banco


def test_confirm_sets_provider_when_evolution_reports_open(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connecting",
    ))
    db.commit()

    def _fake_get(url: str, **kwargs: object) -> object:
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": "e1p-" + TENANT_ID, "status": "open"}}]

        return _Resp()

    monkeypatch.setattr(httpx, "get", _fake_get)
    status = session_service.confirm(db, tenant_id=TENANT_ID)
    assert status == "connected"
    db.expire_all()
    profile = settings_service.get_profile(db, TENANT_ID)
    assert profile.whatsapp_provider == "evolution"
    row = db.get(PublicWhatsappInstance, "e1p-" + TENANT_ID)
    assert row.last_status == "connected"


def test_confirm_does_not_set_provider_when_not_open(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connecting",
    ))
    db.commit()

    def _fake_get(url: str, **kwargs: object) -> object:
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": "e1p-" + TENANT_ID, "status": "connecting"}}]

        return _Resp()

    monkeypatch.setattr(httpx, "get", _fake_get)
    status = session_service.confirm(db, tenant_id=TENANT_ID)
    assert status == "connecting"
    db.expire_all()
    assert settings_service.get_profile(db, TENANT_ID).whatsapp_provider is None


def test_refresh_qr_returns_new_qr(db, monkeypatch: pytest.MonkeyPatch) -> None:
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connecting",
    ))
    db.commit()

    def _fake_get(url: str, **kwargs: object) -> object:
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"base64": "data:image/png;base64,NOVO_QR"}

        return _Resp()

    monkeypatch.setattr(httpx, "get", _fake_get)
    qr = session_service.refresh_qr(db, tenant_id=TENANT_ID)
    assert qr == "data:image/png;base64,NOVO_QR"


def test_disconnect_logs_out_and_clears_provider(db, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_provider = "evolution"
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connected",
    ))
    db.commit()

    calls: list[str] = []
    monkeypatch.setattr(
        httpx, "delete", lambda url, **_k: calls.append(url) or type("R", (), {"status_code": 200})()
    )
    session_service.disconnect(db, tenant_id=TENANT_ID)
    assert any("/instance/logout/e1p-" + TENANT_ID in c for c in calls)
    db.expire_all()
    assert settings_service.get_profile(db, TENANT_ID).whatsapp_provider is None
