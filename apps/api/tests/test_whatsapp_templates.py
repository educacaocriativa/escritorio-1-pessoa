"""Testes do módulo de Templates de WhatsApp (Meta Cloud API).

Cobre: exigência de credenciais configuradas antes de criar (422), criação com sucesso (as
chamadas à Graph API são sempre mockadas — `core/whatsapp.create_template` etc.), validação de
variáveis do corpo ({{1}}, {{2}}, ...) vs. exemplos informados, duplicidade nome+idioma (409),
listagem, sincronização de status com a Meta e exclusão.

RLS/isolamento cross-tenant é validado à parte no Postgres real
(`test_whatsapp_templates_rls.py`, marcador `rls_e2e`) — mesmo padrão de
`test_cost_centers.py`/`test_cost_centers_rls.py`. Aqui a suíte roda em SQLite, que não exerce
RLS de verdade.

Nota sobre o fixture `client`: o router deste módulo é deliberadamente NÃO registrado em
`app/main.py`/`app/modules/__init__.py` ainda (outro agente, em paralelo, faz essa fiação depois
que todos os módulos concorrentes terminarem — ver instruções da tarefa). Por isso este arquivo
define seu PRÓPRIO fixture `client` (sombreando o de `conftest.py` só para este módulo de teste),
montando uma app FastAPI mínima com `auth` (para register/me) + `whatsapp_templates`, com os
mesmos overrides de sessão do fixture global.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import whatsapp as core_whatsapp
from app.core.tenancy import get_tenant_db
from app.db.session import get_db, get_tenant_session_factory
from app.modules.auth.router import router as auth_router
from app.modules.settings.service import get_profile
from app.modules.whatsapp_templates.models import WhatsappTemplate
from app.modules.whatsapp_templates.router import router as whatsapp_templates_router

REGISTER_A = {
    "legal_name": "Templates SA",
    "document": "61616161000107",
    "slug": "templatesa",
    "email": "templates@example.com",
    "name": "Tia",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    test_app = FastAPI()
    test_app.include_router(auth_router)
    test_app.include_router(whatsapp_templates_router)

    def _override_get_db() -> Iterator[Session]:
        yield db

    def _override_factory():
        @contextmanager
        def _factory(_tenant_id: str) -> Iterator[Session]:
            yield db

        return _factory

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_tenant_db] = _override_get_db
    test_app.dependency_overrides[get_tenant_session_factory] = _override_factory
    with TestClient(test_app) as c:
        yield c


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER_A).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _configure_credentials(db: Session, tenant_id: str) -> None:
    """Simula o dono já tendo configurado as credenciais do WhatsApp em Configurações
    (o schema/router de `/settings/profile` para esses campos é responsabilidade de outro
    agente em paralelo — aqui escrevemos direto no `TenantProfile` para não depender disso)."""
    profile = get_profile(db, tenant_id)
    profile.whatsapp_token = "fake-token"
    profile.whatsapp_phone_id = "123456789"
    profile.whatsapp_waba_id = "waba-1"
    db.commit()


BODY = "Olá {{1}}, seu pedido {{2}} foi confirmado!"


def _create_payload(**overrides) -> dict:
    payload = {
        "name": "confirmacao_pedido",
        "language": "pt_BR",
        "category": "UTILITY",
        "body_text": BODY,
        "variable_examples": ["Maria", "#123"],
    }
    payload.update(overrides)
    return payload


def _fake_create_ok(**_kwargs) -> dict:
    return {"id": "meta-tpl-1", "status": "PENDING"}


def test_create_without_credentials_is_422(client: TestClient, headers):
    resp = client.post("/whatsapp-templates", json=_create_payload(), headers=headers)
    assert resp.status_code == 422
    assert "Configure as credenciais" in resp.json()["detail"]


def test_create_with_credentials_returns_201(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    captured: dict[str, object] = {}

    def _fake_create(**kwargs) -> dict:
        captured.update(kwargs)
        return {"id": "meta-tpl-1", "status": "PENDING", "category": "UTILITY"}

    monkeypatch.setattr(core_whatsapp, "create_template", _fake_create)

    resp = client.post("/whatsapp-templates", json=_create_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "confirmacao_pedido"
    assert body["meta_template_id"] == "meta-tpl-1"
    assert body["status"] == "PENDING"
    assert body["category_approved"] == "UTILITY"
    assert body["category_requested"] == "UTILITY"
    assert body["variable_count"] == 2
    assert body["variable_examples"] == ["Maria", "#123"]
    # Credenciais do tenant propagadas corretamente pro core/whatsapp.
    assert captured["waba_id"] == "waba-1"
    assert captured["token"] == "fake-token"
    assert captured["name"] == "confirmacao_pedido"


def test_create_defaults_status_pending_when_meta_omits_it(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: {"id": "meta-x"})
    resp = client.post("/whatsapp-templates", json=_create_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "PENDING"
    assert resp.json()["category_approved"] is None


def test_create_variable_mismatch_is_422(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())

    # corpo usa {{1}} e {{2}} mas só 1 exemplo informado
    resp = client.post(
        "/whatsapp-templates",
        json=_create_payload(variable_examples=["Maria"]),
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_variable_gap_is_422(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())

    # {{1}} e {{3}} — não é contíguo (falta {{2}})
    resp = client.post(
        "/whatsapp-templates",
        json=_create_payload(body_text="Olá {{1}}, código {{3}}", variable_examples=["a", "b"]),
        headers=headers,
    )
    assert resp.status_code == 422


def test_create_meta_error_becomes_422(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)

    def _raise(**_k):
        raise core_whatsapp.WhatsappApiError("Graph API retornou erro 400: nome inválido")

    monkeypatch.setattr(core_whatsapp, "create_template", _raise)
    resp = client.post("/whatsapp-templates", json=_create_payload(), headers=headers)
    assert resp.status_code == 422
    assert "nome inválido" in resp.json()["detail"]


def test_duplicate_name_and_language_is_409(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())

    first = client.post("/whatsapp-templates", json=_create_payload(), headers=headers)
    assert first.status_code == 201, first.text
    dup = client.post("/whatsapp-templates", json=_create_payload(), headers=headers)
    assert dup.status_code == 409


def test_same_name_different_language_is_allowed(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())

    first = client.post("/whatsapp-templates", json=_create_payload(), headers=headers)
    assert first.status_code == 201
    other_lang = client.post(
        "/whatsapp-templates", json=_create_payload(language="en_US"), headers=headers
    )
    assert other_lang.status_code == 201


def test_invalid_name_format_is_422(client: TestClient, headers, db: Session, tenant_id: str):
    _configure_credentials(db, tenant_id)
    resp = client.post(
        "/whatsapp-templates", json=_create_payload(name="Boas Vindas!"), headers=headers
    )
    assert resp.status_code == 422


def test_list_templates(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())
    client.post("/whatsapp-templates", json=_create_payload(), headers=headers)

    listed = client.get("/whatsapp-templates", headers=headers).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "confirmacao_pedido"

    filtered = client.get(
        "/whatsapp-templates", params={"status": "REJECTED"}, headers=headers
    ).json()
    assert filtered == []


def test_sync_template_updates_status(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())
    created = client.post("/whatsapp-templates", json=_create_payload(), headers=headers).json()

    monkeypatch.setattr(
        core_whatsapp,
        "fetch_template_status",
        lambda **_k: {"status": "APPROVED", "category": "UTILITY", "rejected_reason": None},
    )
    resp = client.post(f"/whatsapp-templates/{created['id']}/sync", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "APPROVED"
    assert resp.json()["category_approved"] == "UTILITY"


def test_sync_template_rejected(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())
    created = client.post("/whatsapp-templates", json=_create_payload(), headers=headers).json()

    monkeypatch.setattr(
        core_whatsapp,
        "fetch_template_status",
        lambda **_k: {
            "status": "REJECTED", "category": "UTILITY", "rejected_reason": "INVALID_FORMAT",
        },
    )
    resp = client.post(f"/whatsapp-templates/{created['id']}/sync", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"
    assert resp.json()["rejected_reason"] == "INVALID_FORMAT"


def test_sync_template_not_submitted_yet_is_422(client: TestClient, headers, db: Session):
    """Um template sem meta_template_id (não deveria acontecer via API normal, mas cobre a
    guarda) não pode ser sincronizado."""
    tpl = WhatsappTemplate(
        tenant_id=client.get("/auth/me", headers=headers).json()["user"]["tenant_id"],
        name="sem_meta", language="pt_BR", category_requested="UTILITY",
        body_text="Olá", variable_count=0, variable_examples=[],
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    resp = client.post(f"/whatsapp-templates/{tpl.id}/sync", headers=headers)
    assert resp.status_code == 422


def test_sync_template_not_found_is_404(client: TestClient, headers):
    resp = client.post("/whatsapp-templates/nao-existe/sync", headers=headers)
    assert resp.status_code == 404


def test_sync_meta_error_becomes_422(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())
    created = client.post("/whatsapp-templates", json=_create_payload(), headers=headers).json()

    def _raise(**_k):
        raise core_whatsapp.WhatsappApiError("Graph API retornou erro 404: not found")

    monkeypatch.setattr(core_whatsapp, "fetch_template_status", _raise)
    resp = client.post(f"/whatsapp-templates/{created['id']}/sync", headers=headers)
    assert resp.status_code == 422


def test_delete_template(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())
    created = client.post("/whatsapp-templates", json=_create_payload(), headers=headers).json()

    monkeypatch.setattr(core_whatsapp, "delete_template", lambda **_k: None)
    resp = client.delete(f"/whatsapp-templates/{created['id']}", headers=headers)
    assert resp.status_code == 204
    assert client.get("/whatsapp-templates", headers=headers).json() == []


def test_delete_template_survives_meta_side_failure(
    client: TestClient, headers, db: Session, tenant_id: str, monkeypatch: pytest.MonkeyPatch
):
    """Exclusão local NUNCA é bloqueada por falha do lado da Meta (best-effort)."""
    _configure_credentials(db, tenant_id)
    monkeypatch.setattr(core_whatsapp, "create_template", lambda **_k: _fake_create_ok())
    created = client.post("/whatsapp-templates", json=_create_payload(), headers=headers).json()

    def _raise(**_k):
        raise core_whatsapp.WhatsappApiError("falhou do lado da Meta")

    monkeypatch.setattr(core_whatsapp, "delete_template", _raise)
    resp = client.delete(f"/whatsapp-templates/{created['id']}", headers=headers)
    assert resp.status_code == 204
    assert client.get("/whatsapp-templates", headers=headers).json() == []


def test_delete_template_not_found_is_404(client: TestClient, headers):
    resp = client.delete("/whatsapp-templates/nao-existe", headers=headers)
    assert resp.status_code == 404


def test_requires_auth(client: TestClient):
    assert client.get("/whatsapp-templates").status_code == 401
    assert client.post("/whatsapp-templates", json=_create_payload()).status_code == 401


# ── Isolamento por tenant ────────────────────────────────────────────────────
# Nota: RLS é Postgres-only e NÃO é exercida pela suíte SQLite deste arquivo (mesmo racional de
# test_cost_centers.py). `get_profile`/`list_templates`/`db.get` aqui não filtram manualmente
# por tenant_id (Regra de Ouro nº 1 — a app confia na RLS); tentar simular "tenant A não vê
# tenant B" registrando dois tenants no MESMO SQLite in-memory não provaria nada de real, porque
# sem RLS as queries sem filtro (ex.: `get_profile`) veriam as linhas de ambos os tenants —
# um falso-positivo (ou falso-negativo) que não reflete o comportamento em produção. O
# isolamento cross-tenant de verdade (tenant A não vê/sincroniza/exclui template de tenant B) é
# validado no Postgres real com RLS FORCE em `test_whatsapp_templates_rls.py` (marcador
# `rls_e2e`, mesmo padrão de `test_cost_centers_rls.py`/`test_rls_isolation.py`).
