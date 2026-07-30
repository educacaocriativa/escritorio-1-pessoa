# WhatsApp Evolution — Onda 2 (Onboarding por QR Code) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deixar o tenant conectar o WhatsApp escaneando um QR Code — sem tocar na Meta, sem
colar credencial nenhuma. Isto liga o fio que a Onda 0 deixou pronto (a resolução do
despachante ganha o segundo ramo real) e fecha o ciclo: conectar → confirmar → cair → avisar.

**Architecture:** Módulo novo `app/modules/whatsapp_session/` gerencia o ciclo de vida da
instância Evolution (criar, configurar webhook, obter QR, checar status, desconectar) via HTTP
direto (`httpx` contra `settings.evolution_api_url`), separado de `providers/evolution.py` (que
só cobre ENVIO de mensagem — gerenciar instância é outro contrato). Uma tabela global nova
(`public_whatsapp_instances`) guarda o segredo do webhook por tenant, no mesmo padrão de
`public_whatsapp_accounts`. **Decisão de design deliberada:** `GET /whatsapp-session/status` é
PURAMENTE de leitura (sem escrever no banco) — o próprio projeto já corrigiu antes um bug de GET
com efeito colateral (Cockpit, ver CLAUDE.md §6.0: "removido efeito colateral de escrita — GET
não semeia mais estágios"). A transição real (`whatsapp_provider = "evolution"`) acontece em
`POST /whatsapp-session/confirm`, chamado pelo frontend assim que o polling vê "connected" pela
primeira vez — e, como rede de segurança, também no sweep do worker (4ª etapa), para o caso da
aba ter sido fechada antes da confirmação.

**Tech Stack:** Python 3.13, httpx, Alembic, React 18 + TypeScript, vitest + testing-library
(já presentes — nenhuma dependência nova).

## Global Constraints

- **`GET /whatsapp-session/status` NUNCA escreve no banco.** Só `POST /whatsapp-session/confirm`
  e o worker (4ª etapa) podem setar `whatsapp_provider`. Ver nota de arquitetura acima.
- **Nome da instância: sempre `e1p-{tenant_id}`**, nunca o slug (slug muda, tenant_id não).
- **A Evolution mockada via httpx** nos testes automatizados — validação contra uma instância
  real fica para o checklist manual, na VPS (mesma decisão da Onda 1).
- **`_resolve` do despachante** (`app/core/whatsapp/__init__.py`) passa a checar
  `profile.whatsapp_provider` — é o ÚNICO lugar do domínio que sabe dessa distinção; nenhum
  outro módulo (incluindo `whatsapp_session`) decide isso de novo.
- **`ruff check .` limpo** no backend; `pnpm --filter @e1p/web typecheck` e
  `pnpm --filter @e1p/web test` limpos no frontend.
- Ambiente: `apps/api/.venv/Scripts/python.exe` (mesmo interpretador reaproveitado das ondas
  anteriores).

---

## File Structure

```
apps/api/migrations/versions/0058_whatsapp_provider_session.py  → NOVO
apps/api/app/config.py                                          → MODIFICADO (1 setting nova)
apps/api/app/modules/settings/models.py                          → MODIFICADO (whatsapp_provider ORM)
apps/api/app/modules/whatsapp_session/__init__.py                → NOVO (vazio)
apps/api/app/modules/whatsapp_session/models.py                  → NOVO
apps/api/app/modules/whatsapp_session/service.py                 → NOVO
apps/api/app/modules/whatsapp_session/router.py                  → NOVO
apps/api/app/modules/__init__.py                                 → MODIFICADO (registra o router)
apps/api/app/core/whatsapp/__init__.py                           → MODIFICADO (_resolve real)
apps/api/app/worker.py                                           → MODIFICADO (4ª etapa)
apps/api/app/modules/settings/schemas.py                         → MODIFICADO (whatsapp_provider em ProfileOut)
apps/api/app/modules/settings/router.py                          → MODIFICADO (idem)
apps/api/tests/test_whatsapp_session_service.py                  → NOVO
apps/api/tests/test_whatsapp_session_router.py                   → NOVO
apps/api/tests/test_whatsapp_dispatcher.py                       → MODIFICADO (cobre o branch real)
apps/api/tests/test_worker.py                                    → MODIFICADO (4ª etapa)

apps/web/src/features/config/WhatsappSection.tsx                → MODIFICADO (card de QR Code)
apps/web/src/features/config/WhatsappSection.test.tsx           → MODIFICADO
packages/shared-types/src/index.ts                                → MODIFICADO (whatsapp_provider)
```

---

### Task 1: Migration 0058 — `whatsapp_provider` + `public_whatsapp_instances`

**Files:**
- Create: `apps/api/migrations/versions/0058_whatsapp_provider_session.py`

**Interfaces:**
- Produces: coluna `tenant_profiles.whatsapp_provider` (`String(16)`, nullable, sem default —
  `None` é "nenhum transporte ativo", o estado de hoje). Tabela `public_whatsapp_instances`
  (global, sem RLS): `instance_name` (PK), `tenant_id`, `webhook_secret` (cifrado), `last_status`
  (`String(16)`, default `"connecting"`), `created_at`/`updated_at`.

- [ ] **Step 1: Escrever a migration**

```python
"""tenant_profiles.whatsapp_provider + public_whatsapp_instances (Onda 2 — onboarding por QR)

Revision ID: 0058
Revises: 0057
Create Date: 2026-07-30

- `tenant_profiles.whatsapp_provider`: "meta" | "evolution" | None. None = nenhum transporte
  ativo (estado de hoje — nenhum tenant existente muda de comportamento).
- `public_whatsapp_instances` (GLOBAL, sem RLS): resolve `instance_name -> tenant_id` +
  `webhook_secret` ANTES de qualquer autenticação (mesmo padrão de `public_whatsapp_accounts`,
  chave natural distinta: nome de instância, não phone_number_id da Meta).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_profiles", sa.Column("whatsapp_provider", sa.String(16), nullable=True)
    )
    op.create_table(
        "public_whatsapp_instances",
        sa.Column("instance_name", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("webhook_secret", sa.Text(), nullable=False),
        sa.Column("last_status", sa.String(16), nullable=False, server_default="connecting"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_public_whatsapp_instances_tenant_id", "public_whatsapp_instances", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_public_whatsapp_instances_tenant_id", table_name="public_whatsapp_instances"
    )
    op.drop_table("public_whatsapp_instances")
    op.drop_column("tenant_profiles", "whatsapp_provider")
```

- [ ] **Step 2: Rodar as migrations contra o SQLite de teste (a suíte usa `Base.metadata.create_all`,
  não Alembic — mas confirmar que a migration roda limpa contra Postgres real fica pro
  checklist manual/CI `test-in-prod-image`, que já roda `alembic upgrade head`)**

Run (verificação de sintaxe apenas — não exige Postgres de pé):
```bash
./.venv/Scripts/python.exe -c "import importlib; importlib.import_module('migrations.versions.0058_whatsapp_provider_session')"
```
Expected: sem erro de import/sintaxe.

- [ ] **Step 3: Commit**

```bash
git add apps/api/migrations/versions/0058_whatsapp_provider_session.py
git commit -m "feat: migration 0058 — tenant_profiles.whatsapp_provider + public_whatsapp_instances"
```

---

### Task 2: `settings.internal_api_base_url` + `TenantProfile.whatsapp_provider` (ORM) + modelo `PublicWhatsappInstance`

**Files:**
- Modify: `apps/api/app/config.py`
- Modify: `apps/api/app/modules/settings/models.py`
- Create: `apps/api/app/modules/whatsapp_session/__init__.py`
- Create: `apps/api/app/modules/whatsapp_session/models.py`

**Interfaces:**
- Produces: `settings.internal_api_base_url: str` (default `"http://api:8000"` — nome do serviço
  Docker, usado para montar a URL do webhook que a Evolution vai chamar).
  `TenantProfile.whatsapp_provider: str | None` (campo ORM — a migration da Task 1 só cria a
  COLUNA no banco; sem este campo no modelo, `profile.whatsapp_provider` nunca resolveria, e os
  testes com SQLite/`Base.metadata.create_all` — que não rodam a migration Alembic — nem
  criariam a coluna). `PublicWhatsappInstance` (SQLAlchemy `Base` + `TimestampMixin`, SEM
  `TenantMixin` — tabela global).

- [ ] **Step 1: Settings nova**

Em `apps/api/app/config.py`, logo após `evolution_api_key: str = ""`:

```python
    evolution_api_key: str = ""
    # URL pela qual a PRÓPRIA API é alcançável de DENTRO da rede Docker — usada para configurar
    # o webhook da Evolution (que aponta pra cá). Nome de serviço do compose, não localhost.
    internal_api_base_url: str = "http://api:8000"
```

- [ ] **Step 2: `TenantProfile.whatsapp_provider` (campo ORM)**

Em `apps/api/app/modules/settings/models.py`, dentro da classe `TenantProfile`, logo após o
campo `whatsapp_template_bindings` (o último campo relacionado a WhatsApp já existente):

```python
    whatsapp_template_bindings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Transporte ativo: "meta" | "evolution" | None. None = nenhum transporte ativo (estado de
    # hoje — nenhum tenant existente muda de comportamento). Só muda via
    # POST /whatsapp-session/connect+confirm (QR) ou credenciais Meta completas — nunca
    # setável direto por PATCH /settings/profile (ver ProfileUpdate, Task 5).
    whatsapp_provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

- [ ] **Step 3: `whatsapp_session/__init__.py` (vazio)**

```python
"""Onboarding e ciclo de vida da sessão WhatsApp por Evolution API (QR Code) — Onda 2 da
feature de WhatsApp por Evolution. Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §5.
"""
```

- [ ] **Step 4: `whatsapp_session/models.py`**

```python
"""Snapshot GLOBAL (sem RLS, SEM TenantMixin) da instância Evolution de cada tenant — resolve
`instance_name -> tenant_id` + `webhook_secret` ANTES de qualquer autenticação. Mesmo padrão de
`PublicWhatsappAccount` (whatsapp_inbox), chave natural distinta (nome de instância, não
phone_number_id da Meta) — por isso é tabela própria, não a mesma.
"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.token_crypto import EncryptedToken
from app.db.base import Base, TimestampMixin

STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"


class PublicWhatsappInstance(Base, TimestampMixin):
    __tablename__ = "public_whatsapp_instances"

    instance_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Cifrado em repouso (mesmo padrão de `PublicWhatsappAccount.app_secret`) — usado como
    # segmento de path no webhook interno (Onda 3), defesa em profundidade além do isolamento
    # de rede (a Evolution só existe na rede interna do Docker).
    webhook_secret: Mapped[str] = mapped_column(EncryptedToken, nullable=False)
    last_status: Mapped[str] = mapped_column(
        String(16), default=STATUS_CONNECTING, nullable=False
    )
```

- [ ] **Step 5: Rodar a suíte de settings (baseline — nada deveria quebrar, é campo aditivo)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_settings.py -q`
Expected: mesmo total de antes.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/config.py apps/api/app/modules/settings/models.py apps/api/app/modules/whatsapp_session/__init__.py apps/api/app/modules/whatsapp_session/models.py
git commit -m "feat: settings.internal_api_base_url + TenantProfile.whatsapp_provider (ORM) + modelo PublicWhatsappInstance"
```

---

### Task 3: `whatsapp_session/service.py` — `connect`

**Files:**
- Create: `apps/api/app/modules/whatsapp_session/service.py`
- Create: `apps/api/tests/test_whatsapp_session_service.py`

**Interfaces:**
- Consumes: `PublicWhatsappInstance` (Task 2), `settings.evolution_api_url/api_key/
  internal_api_base_url`, `app.modules.settings.service.get_profile`.
- Produces: `connect(db: Session, *, tenant_id: str) -> dict` — devolve
  `{"qr_base64": str, "status": "connecting"}`. `WhatsappSessionError(Exception)` com
  `status_code`.

- [ ] **Step 1: Escrever o teste de `connect` (instância nova)**

```python
"""Testes de app/modules/whatsapp_session/service.py — ciclo de vida da sessão Evolution
(Onda 2 da feature de WhatsApp por Evolution). httpx sempre mockado — sem instância real."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.modules.settings import service as settings_service
from app.modules.settings.models import TenantProfile
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
```

- [ ] **Step 2: Rodar para confirmar que falha (módulo ainda não existe)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_session_service.py -v`
Expected: FAIL com `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `connect`**

```python
"""Ciclo de vida da sessão WhatsApp por Evolution API (QR Code). Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §5.

Separado de `core/whatsapp/providers/evolution.py` (que só cobre ENVIO de mensagem) — gerenciar
a instância (criar, webhook, QR, status, logout) é um contrato de API diferente da Evolution,
com credencial GLOBAL igual, mas endpoints e ciclo de vida próprios.
"""
from __future__ import annotations

import secrets

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.settings import service as settings_service
from app.modules.whatsapp_session.models import (
    STATUS_CONNECTING,
    PublicWhatsappInstance,
)


class WhatsappSessionError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _instance_name(tenant_id: str) -> str:
    return f"e1p-{tenant_id}"


def _headers() -> dict[str, str]:
    return {"apikey": settings.evolution_api_key}


def _require_configured() -> None:
    if not settings.evolution_api_key:
        raise WhatsappSessionError(
            "Evolution API não configurada nesta instalação (EVOLUTION_API_KEY ausente)", 503
        )


def connect(db: Session, *, tenant_id: str) -> dict:
    """Idempotente: cria a instância na Evolution se não existir, configura o webhook (aponta
    para a rota interna que a Onda 3 implementa) e devolve o QR em base64.

    NÃO altera `TenantProfile.whatsapp_provider` — essa transição só acontece em `confirm()`,
    depois que o QR é escaneado de verdade (ver Global Constraints do plano)."""
    _require_configured()
    instance = _instance_name(tenant_id)
    settings_service.get_profile(db, tenant_id)  # garante que o profile existe

    try:
        resp = httpx.post(
            f"{settings.evolution_api_url}/instance/create",
            headers=_headers(),
            json={"instanceName": instance, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            timeout=15,
        )
        # A Evolution devolve erro se a instância já existir — idempotente: ignoramos esse
        # caso específico (detectado pelo texto da resposta) e seguimos pro resto do fluxo.
        if resp.status_code >= 400 and "already" not in resp.text.lower():
            raise WhatsappSessionError(
                f"Falha ao criar instância na Evolution: {resp.text}", 502
            )
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao criar instância: {exc}", 502) from exc

    existing = db.get(PublicWhatsappInstance, instance)
    webhook_secret = existing.webhook_secret if existing else secrets.token_urlsafe(32)

    try:
        httpx.post(
            f"{settings.evolution_api_url}/webhook/set/{instance}",
            headers=_headers(),
            json={
                "url": (
                    f"{settings.internal_api_base_url}"
                    f"/internal/whatsapp/evolution/webhook/{webhook_secret}"
                ),
                "webhook_by_events": False,
                "events": ["MESSAGES_UPSERT"],
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao configurar webhook: {exc}", 502) from exc

    if existing is None:
        db.add(
            PublicWhatsappInstance(
                instance_name=instance, tenant_id=tenant_id,
                webhook_secret=webhook_secret, last_status=STATUS_CONNECTING,
            )
        )
    else:
        existing.last_status = STATUS_CONNECTING
    db.commit()

    try:
        resp = httpx.get(
            f"{settings.evolution_api_url}/instance/connect/{instance}",
            headers=_headers(), timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao obter QR: {exc}", 502) from exc

    data = resp.json()
    return {"qr_base64": data.get("base64", ""), "status": STATUS_CONNECTING}
```

- [ ] **Step 4: Rodar de novo — deve passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_session_service.py -v`
Expected: 2 testes, PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/whatsapp_session/service.py apps/api/tests/test_whatsapp_session_service.py
git commit -m "feat: whatsapp_session.service::connect (cria instância + webhook + QR)"
```

---

### Task 4: `whatsapp_session/service.py` — `get_status`, `confirm`, `refresh_qr`, `disconnect`

**Files:**
- Modify: `apps/api/app/modules/whatsapp_session/service.py`
- Modify: `apps/api/tests/test_whatsapp_session_service.py`

**Interfaces:**
- Produces: `get_status(db, *, tenant_id) -> str` (`"never"|"connecting"|"connected"|
  "disconnected"`, PURAMENTE leitura). `confirm(db, *, tenant_id) -> str` (reverifica com a
  Evolution; se `"open"`, seta `whatsapp_provider="evolution"` e devolve `"connected"`; senão
  devolve o status real sem alterar nada). `refresh_qr(db, *, tenant_id) -> str` (novo QR
  base64). `disconnect(db, *, tenant_id) -> None` (logout na Evolution + limpa
  `whatsapp_provider`).

- [ ] **Step 1: Escrever os testes**

Acrescentar a `test_whatsapp_session_service.py`:

```python
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
```

- [ ] **Step 2: Rodar para confirmar que falha (funções ainda não existem)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_session_service.py -v`
Expected: os 2 testes da Task 3 continuam passando; os novos falham com `AttributeError`.

- [ ] **Step 3: Implementar as 4 funções**

Acrescentar ao final de `apps/api/app/modules/whatsapp_session/service.py`:

```python
def _fetch_evolution_status(instance: str) -> str | None:
    """Consulta a Evolution pelo status bruto da instância. Devolve o `status` da Evolution
    ("open", "connecting", etc.) ou None se a instância não aparecer/a chamada falhar."""
    try:
        resp = httpx.get(
            f"{settings.evolution_api_url}/instance/fetchInstances",
            headers=_headers(), params={"instanceName": instance}, timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    data = resp.json()
    items = data if isinstance(data, list) else []
    for item in items:
        inst = item.get("instance", item)
        if inst.get("instanceName") == instance:
            return inst.get("status")
    return None


def get_status(db: Session, *, tenant_id: str) -> str:
    """PURAMENTE leitura — nunca escreve no banco (ver Global Constraints do plano). Devolve
    'never' (nunca conectou), 'connecting', 'connected' ou 'disconnected'."""
    instance = _instance_name(tenant_id)
    row = db.get(PublicWhatsappInstance, instance)
    if row is None:
        return "never"
    evo_status = _fetch_evolution_status(instance)
    if evo_status == "open":
        return "connected"
    if evo_status is None:
        return "disconnected"
    return "connecting"


def confirm(db: Session, *, tenant_id: str) -> str:
    """Reverifica com a Evolution (nunca confia no client) e, se realmente 'open', É QUEM
    seta `whatsapp_provider='evolution'` — a única escrita de transição-pra-conectado deste
    módulo. Chamado pelo frontend ao ver 'connected' pela primeira vez; o worker (Onda 2,
    4ª etapa) é a rede de segurança caso a aba feche antes disso."""
    instance = _instance_name(tenant_id)
    row = db.get(PublicWhatsappInstance, instance)
    if row is None:
        return "never"
    evo_status = _fetch_evolution_status(instance)
    if evo_status != "open":
        return "connecting" if evo_status is not None else "disconnected"
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_provider = "evolution"
    row.last_status = STATUS_CONNECTED
    db.commit()
    return "connected"


def refresh_qr(db: Session, *, tenant_id: str) -> str:
    """QR expira em ~60s do lado da Evolution — pede um novo."""
    _require_configured()
    instance = _instance_name(tenant_id)
    try:
        resp = httpx.get(
            f"{settings.evolution_api_url}/instance/connect/{instance}",
            headers=_headers(), timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao renovar o QR: {exc}", 502) from exc
    return resp.json().get("base64", "")


def disconnect(db: Session, *, tenant_id: str) -> None:
    """Logout na Evolution + limpa `whatsapp_provider` (usado pra trocar de número/transporte).
    Não propaga falha de rede do logout — o produto ainda deve conseguir "esquecer" a conexão
    localmente mesmo se a Evolution estiver fora do ar."""
    instance = _instance_name(tenant_id)
    try:
        httpx.delete(
            f"{settings.evolution_api_url}/instance/logout/{instance}",
            headers=_headers(), timeout=15,
        )
    except httpx.HTTPError:
        pass
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_provider = None
    row = db.get(PublicWhatsappInstance, instance)
    if row is not None:
        row.last_status = STATUS_DISCONNECTED
    db.commit()
```

Adicionar `STATUS_CONNECTED`, `STATUS_DISCONNECTED` ao import de
`app.modules.whatsapp_session.models` no topo do arquivo (`STATUS_CONNECTING` já está
importado).

- [ ] **Step 4: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_session_service.py -v`
Expected: 8 testes, todos PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/whatsapp_session/service.py apps/api/tests/test_whatsapp_session_service.py
git commit -m "feat: whatsapp_session.service — get_status (read-only), confirm, refresh_qr, disconnect"
```

---

### Task 5: Router + registro + `ProfileOut.whatsapp_provider`

**Files:**
- Create: `apps/api/app/modules/whatsapp_session/router.py`
- Create: `apps/api/tests/test_whatsapp_session_router.py`
- Modify: `apps/api/app/modules/__init__.py`
- Modify: `apps/api/app/modules/settings/schemas.py`
- Modify: `apps/api/app/modules/settings/router.py`

**Interfaces:**
- Consumes: `app.modules.whatsapp_session.service` (Tasks 3-4).
- Produces: `POST /whatsapp-session/connect`, `GET /whatsapp-session/status`,
  `POST /whatsapp-session/confirm`, `POST /whatsapp-session/refresh-qr`,
  `DELETE /whatsapp-session`.

- [ ] **Step 1: Escrever `router.py`**

```python
"""Rotas de onboarding do WhatsApp por Evolution API (QR Code)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.whatsapp_session import service

router = APIRouter(prefix="/whatsapp-session", tags=["whatsapp-session"])

_guard = require_module("settings")


def _err(e: service.WhatsappSessionError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/connect")
def connect(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    try:
        return service.connect(db, tenant_id=user.tenant_id)
    except service.WhatsappSessionError as e:
        raise _err(e) from e


@router.get("/status")
def get_status(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    return {"status": service.get_status(db, tenant_id=user.tenant_id)}


@router.post("/confirm")
def confirm(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    return {"status": service.confirm(db, tenant_id=user.tenant_id)}


@router.post("/refresh-qr")
def refresh_qr(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> dict:
    try:
        return {"qr_base64": service.refresh_qr(db, tenant_id=user.tenant_id)}
    except service.WhatsappSessionError as e:
        raise _err(e) from e


@router.delete("", status_code=204)
def disconnect(
    user: CurrentUser = Depends(_guard), db: Session = Depends(get_tenant_db)
) -> None:
    service.disconnect(db, tenant_id=user.tenant_id)
```

- [ ] **Step 2: Registrar em `app/modules/__init__.py`**

Seguir o mesmo padrão de `whatsapp_inbox_router`: acrescentar
`from app.modules.whatsapp_session.router import router as whatsapp_session_router` nos
imports, e `whatsapp_session_router` na lista `ALL_ROUTERS`.

- [ ] **Step 3: `ProfileOut.whatsapp_provider` (read-only — não entra em `ProfileUpdate`)**

Em `apps/api/app/modules/settings/schemas.py`, em `ProfileOut`, logo após
`whatsapp_configured: bool`:

```python
    whatsapp_configured: bool
    # "meta" | "evolution" | None — só muda via POST /whatsapp-session/connect+confirm ou
    # PATCH /settings/profile (credenciais Meta completas). NUNCA exposto em ProfileUpdate:
    # setar isso direto seria "declarar conectado" sem ter conectado de verdade.
    whatsapp_provider: str | None
```

Em `apps/api/app/modules/settings/router.py`, na função `_out`, acrescentar
`whatsapp_provider=p.whatsapp_provider,` à construção de `ProfileOut(...)`.

- [ ] **Step 4: Escrever os testes do router**

```python
"""Testes das rotas de app/modules/whatsapp_session/router.py."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings

REGISTER = {
    "legal_name": "Sessao WA", "document": "39393939000107", "slug": "sessaowa",
    "email": "sessaowa@example.com", "name": "S", "password": "senha-bem-comprida",
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
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: type("R", (), {"status_code": 201, "text": ""})())
    monkeypatch.setattr(
        httpx, "get",
        lambda *_a, **_k: type("R", (), {
            "status_code": 200, "raise_for_status": lambda self: None,
            "json": lambda self: {"base64": "QR"},
        })(),
    )
    client.post("/whatsapp-session/connect", headers=headers)

    def _fake_get_open(url: str, **_k: object) -> object:
        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": url.rsplit("/", 1)[-1] or "x", "status": "open"}}]

        return _R()

    # fetchInstances usa query param, não path — reforça com um fake dedicado que devolve o
    # instanceName certo via params capturados
    def _fake_get_status(url: str, **kwargs: object) -> object:
        params = kwargs.get("params") or {}

        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": params.get("instanceName"), "status": "open"}}]

        return _R()

    monkeypatch.setattr(httpx, "get", _fake_get_status)
    resp = client.post("/whatsapp-session/confirm", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "connected"}

    profile = client.get("/settings/profile", headers=headers).json()
    assert profile["whatsapp_provider"] == "evolution"


def test_disconnect_clears_provider(client: TestClient, headers, monkeypatch) -> None:
    monkeypatch.setattr(httpx, "delete", lambda *_a, **_k: type("R", (), {"status_code": 200})())
    resp = client.delete("/whatsapp-session", headers=headers)
    assert resp.status_code == 204
```

- [ ] **Step 5: Rodar tudo**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_session_router.py tests/test_settings.py -v`
Expected: todos PASS (a suíte de settings continua verde — `whatsapp_provider` é campo aditivo).

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/whatsapp_session/router.py apps/api/app/modules/__init__.py apps/api/app/modules/settings/schemas.py apps/api/app/modules/settings/router.py apps/api/tests/test_whatsapp_session_router.py
git commit -m "feat: rotas /whatsapp-session (connect/status/confirm/refresh-qr/disconnect) + ProfileOut.whatsapp_provider"
```

---

### Task 6: Ligar o despachante de verdade (`_resolve`)

**Files:**
- Modify: `apps/api/app/core/whatsapp/__init__.py`
- Modify: `apps/api/tests/test_whatsapp_dispatcher.py`

**Interfaces:**
- Consumes: `app.core.whatsapp.providers.evolution` (Onda 1).

- [ ] **Step 1: Escrever o teste do branch real**

Acrescentar a `test_whatsapp_dispatcher.py`:

```python
def test_resolve_picks_evolution_when_profile_provider_is_evolution() -> None:
    from app.core.whatsapp.providers import evolution, meta

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
```

- [ ] **Step 2: Rodar para confirmar que falha (ainda hardcoded em `meta`)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_dispatcher.py -k resolve -v`
Expected: `test_resolve_picks_evolution_when_profile_provider_is_evolution` FALHA (devolve
`meta`, não `evolution`); o outro já passa (coincidência do hardcode atual).

- [ ] **Step 3: Implementar o branch real**

Em `apps/api/app/core/whatsapp/__init__.py`, trocar:

```python
def _resolve(profile: TenantProfile | None):
    """Escolhe o provider pelo transporte do tenant.

    PONTO DE EXTENSÃO (Onda 2): quando `TenantProfile.whatsapp_provider` existir, este função
    passa a ser `meta if profile is None or profile.whatsapp_provider != "evolution" else
    evolution`. Até lá só `meta` existe — não há branch para escrever."""
    return meta
```

por:

```python
def _resolve(profile: TenantProfile | None):
    """Escolhe o provider pelo transporte do tenant. `None` (perfil ausente) ou qualquer valor
    diferente de "evolution" cai em `meta` — inclusive `None`/"meta" (estado de hoje, ou tenant
    que nunca conectou por QR)."""
    if profile is not None and profile.whatsapp_provider == "evolution":
        return evolution
    return meta
```

E acrescentar o import no topo do arquivo:

```python
from app.core.whatsapp.providers import evolution, meta
```

(troca a linha `from app.core.whatsapp.providers import meta` existente).

- [ ] **Step 4: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_dispatcher.py -v`
Expected: todos PASS (os 7 da Onda 0 + os 2 novos).

- [ ] **Step 5: Rodar a suíte de WhatsApp inteira (Meta) — nenhum tenant existente tem
  `whatsapp_provider="evolution"`, então nada deveria mudar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp.py tests/test_whatsapp_inbox_service.py tests/test_notifications_queue.py tests/test_receivables.py -q`
Expected: mesmo total de antes desta task.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/whatsapp/__init__.py apps/api/tests/test_whatsapp_dispatcher.py
git commit -m "feat: despachante escolhe evolution quando TenantProfile.whatsapp_provider == 'evolution'"
```

---

### Task 7: Worker — 4ª etapa (monitorar quedas de sessão) + e-mail de aviso

**Files:**
- Modify: `apps/api/app/modules/whatsapp_session/service.py`
- Modify: `apps/api/app/worker.py`
- Modify: `apps/api/tests/test_whatsapp_session_service.py`
- Modify: `apps/api/tests/test_worker.py`

**Interfaces:**
- Produces: `whatsapp_session.service::check_connections(db, *, tenant_id) -> int` (quantas
  quedas detectou e avisou).

- [ ] **Step 1: Escrever o teste de `check_connections`**

Acrescentar a `test_whatsapp_session_service.py`:

```python
def test_check_connections_emails_owner_on_drop(db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import email as email_module

    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_provider = "evolution"
    profile.email = "dono@example.com"
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connected",
    ))
    db.commit()

    def _fake_get(url: str, **kwargs: object) -> object:
        params = kwargs.get("params") or {}

        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": params.get("instanceName"), "status": "close"}}]

        return _R()

    monkeypatch.setattr(httpx, "get", _fake_get)
    sent: list[dict] = []
    monkeypatch.setattr(
        email_module, "send_email",
        lambda **kw: sent.append(kw) or "sent",
    )

    dropped = session_service.check_connections(db, tenant_id=TENANT_ID)
    assert dropped == 1
    assert sent[0]["to"] == "dono@example.com"
    db.expire_all()
    row = db.get(PublicWhatsappInstance, "e1p-" + TENANT_ID)
    assert row.last_status == "disconnected"


def test_check_connections_noop_when_still_connected(db, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import email as email_module

    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_provider = "evolution"
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connected",
    ))
    db.commit()

    def _fake_get(url: str, **kwargs: object) -> object:
        params = kwargs.get("params") or {}

        class _R:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> list:
                return [{"instance": {"instanceName": params.get("instanceName"), "status": "open"}}]

        return _R()

    monkeypatch.setattr(httpx, "get", _fake_get)
    sent: list[dict] = []
    monkeypatch.setattr(email_module, "send_email", lambda **kw: sent.append(kw) or "sent")

    dropped = session_service.check_connections(db, tenant_id=TENANT_ID)
    assert dropped == 0
    assert sent == []


def test_check_connections_ignores_tenants_not_on_evolution(db) -> None:
    # profile.whatsapp_provider != "evolution" (nunca conectou) — nada a checar.
    assert session_service.check_connections(db, tenant_id=TENANT_ID) == 0
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_session_service.py -k check_connections -v`
Expected: FAIL (`AttributeError` — função ainda não existe).

- [ ] **Step 3: Implementar `check_connections`**

Acrescentar ao final de `apps/api/app/modules/whatsapp_session/service.py`:

```python
def check_connections(db: Session, *, tenant_id: str) -> int:
    """Chamado pelo worker (4ª etapa do sweep). Para tenants JÁ conectados por Evolution
    (`whatsapp_provider == "evolution"`), confere se a sessão caiu (Evolution não reporta mais
    "open") e, se sim, avisa o dono por e-mail (canal que não depende do que acabou de quebrar)
    e marca `last_status`. NÃO cuida da transição connecting->connected (isso é `confirm()`,
    chamado pelo frontend) — só monitora quedas de quem já estava de pé. Devolve quantas quedas
    detectou (0 ou 1, já que é por-tenant; o worker soma entre tenants)."""
    from app.core.email import send_email

    profile = settings_service.get_profile(db, tenant_id)
    if profile.whatsapp_provider != "evolution":
        return 0
    instance = _instance_name(tenant_id)
    row = db.get(PublicWhatsappInstance, instance)
    if row is None or row.last_status != STATUS_CONNECTED:
        return 0
    evo_status = _fetch_evolution_status(instance)
    if evo_status == "open":
        return 0
    row.last_status = STATUS_DISCONNECTED
    db.commit()
    if profile.email:
        send_email(
            to=profile.email,
            subject="WhatsApp desconectado no e1p",
            body=(
                "O WhatsApp da sua conta caiu e precisa ser reconectado. "
                "Acesse Configurações > WhatsApp e escaneie o QR Code novamente."
            ),
        )
    return 1
```

- [ ] **Step 4: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_session_service.py -v`
Expected: 11 testes (8 das Tasks 3-4 + 3 desta task), todos PASS.

- [ ] **Step 5: Escrever o teste do worker (4ª etapa)**

Em `apps/api/tests/test_worker.py`, acrescentar (reaproveitando `_cm_factory`/`_make_tenant`
já definidos no topo do arquivo):

```python
def test_run_sweep_checks_whatsapp_connections(db, monkeypatch):
    """4ª etapa: chama whatsapp_session.service.check_connections por tenant, em sessão
    separada das outras 3 — mesmo padrão de isolamento de falha (IV2) já testado acima."""
    tenant = _make_tenant(db, slug="wa-check")
    db.commit()

    calls: list[str] = []
    monkeypatch.setattr(
        worker.whatsapp_session_service, "check_connections",
        lambda db, *, tenant_id: calls.append(tenant_id) or 0,
    )

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert calls == [tenant.id]
    assert result["whatsapp_connections_dropped"] == 0
    assert result["errors"] == []


def test_run_sweep_isolates_whatsapp_stage_failure(db, monkeypatch):
    # A checagem de conexão lança para o tenant, mas a fila (etapa 2, sessão separada) já
    # tinha rodado antes — o erro da etapa 4 fica isolado em `errors`, sem derrubar o sweep.
    tenant = _make_tenant(db, slug="wa-falha")
    notif_service.enqueue(
        db, tenant_id=tenant.id, channel="whatsapp", recipient="d@e.com", message="oi"
    )
    db.commit()

    def _boom(_db, *, tenant_id):
        raise RuntimeError("checagem de conexão explodiu")

    monkeypatch.setattr(worker.whatsapp_session_service, "check_connections", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["notifications_processed"] == 1  # etapa 2 rodou normalmente
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "whatsapp_connections"
    assert result["errors"][0]["tenant_id"] == tenant.id
```

- [ ] **Step 6: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_worker.py -v`
Expected: o teste novo falha (a 4ª etapa ainda não existe em `run_sweep`); os demais continuam
passando.

- [ ] **Step 7: Implementar a 4ª etapa em `app/worker.py`**

Em `apps/api/app/worker.py`, acrescentar ao dicionário `result` inicial:
`"whatsapp_connections_dropped": 0,`. E, após a "Etapa 3 — mídia pendente" (antes do
`logger.info` final), acrescentar:

```python
        # Etapa 4 — monitora quedas de sessão Evolution (sessão SEPARADA das outras três).
        try:
            with tenant_session_factory(tenant_id) as db:
                dropped = whatsapp_session_service.check_connections(db, tenant_id=tenant_id)
            result["whatsapp_connections_dropped"] += dropped
        except Exception as exc:  # noqa: BLE001 — idem: isola a falha por tenant (IV2)
            logger.exception("[worker] checagem de conexão whatsapp falhou tenant=%s", tenant_id)
            result["errors"].append(
                {"tenant_id": tenant_id, "stage": "whatsapp_connections", "error": str(exc)}
            )
```

E o import no topo: `from app.modules.whatsapp_session import service as whatsapp_session_service`.
Também acrescentar `whatsapp_connections_dropped=%s` ao `logger.info` final (mesmo padrão das
outras 3 métricas).

- [ ] **Step 8: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_worker.py -v`
Expected: todos PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/modules/whatsapp_session/service.py apps/api/app/worker.py apps/api/tests/test_whatsapp_session_service.py apps/api/tests/test_worker.py
git commit -m "feat: worker monitora quedas de sessão Evolution (4ª etapa) + e-mail de aviso"
```

---

### Task 8: Frontend — cartão "Conectar por QR Code" em Configurações

**Files:**
- Modify: `packages/shared-types/src/index.ts`
- Modify: `apps/web/src/features/config/WhatsappSection.tsx`
- Modify: `apps/web/src/features/config/WhatsappSection.test.tsx`

**Interfaces:**
- Consumes: `POST /whatsapp-session/connect`, `GET /whatsapp-session/status`,
  `POST /whatsapp-session/confirm`, `POST /whatsapp-session/refresh-qr`,
  `DELETE /whatsapp-session` (Task 5).

- [ ] **Step 1: `TenantProfile.whatsapp_provider` em shared-types**

Em `packages/shared-types/src/index.ts`, na `interface TenantProfile`, logo após
`whatsapp_configured: boolean;`:

```typescript
  whatsapp_configured: boolean;
  /** "meta" | "evolution" | null — qual transporte está ativo. Só muda via
   * POST /whatsapp-session/connect+confirm (QR) ou credenciais Meta completas. */
  whatsapp_provider: "meta" | "evolution" | null;
```

- [ ] **Step 2: Escrever os testes do novo cartão**

Ler `apps/web/src/features/config/WhatsappSection.test.tsx` primeiro (já lido durante o
planejamento — reaproveita o mock de `../../lib/api` e o helper `profile(overrides)`). Ajustar
o helper `profile()` para incluir `whatsapp_provider: null` no objeto default. Acrescentar:

```typescript
describe("EvolutionQrCard", () => {
  it("mostra o botão de conectar quando whatsapp_provider é null", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: profile({ whatsapp_provider: null }) });
    render(<WhatsappSection />);
    expect(await screen.findByText(/conectar por qr code/i)).toBeInTheDocument();
  });

  it("pede o QR e mostra a imagem ao clicar em conectar", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: profile({ whatsapp_provider: null }) });
    vi.mocked(api.post).mockImplementation(async (url: string) => {
      if (url === "/whatsapp-session/connect") {
        return { data: { qr_base64: "data:image/png;base64,FAKE" } };
      }
      throw new Error(`unexpected POST ${url}`);
    });
    render(<WhatsappSection />);
    const btn = await screen.findByText(/conectar por qr code/i);
    await userEvent.click(btn);
    const img = await screen.findByAltText(/qr code/i);
    expect(img).toHaveAttribute("src", "data:image/png;base64,FAKE");
  });

  it("mostra 'Conectado' quando whatsapp_provider é evolution", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: profile({ whatsapp_provider: "evolution" }),
    });
    render(<WhatsappSection />);
    expect(await screen.findByText(/conectado/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Rodar para confirmar que falha**

Run: `pnpm --filter @e1p/web test -- WhatsappSection`
Expected: os 3 testes novos falham (o cartão ainda não existe).

- [ ] **Step 4: Implementar o cartão `EvolutionQrCard` em `WhatsappSection.tsx`**

Acrescentar ao arquivo (logo após a função `WhatsappSection` principal, antes de
`CredentialsCard`), e incluir `<EvolutionQrCard />` na lista de cartões renderizados por
`WhatsappSection`:

```tsx
/** Card "Conectar por QR Code" — onboarding pela Evolution API. Alternativa ao Meta Cloud API
 * (ver CredentialsCard acima): o tenant escaneia o QR, sem colar credencial nenhuma. */
function EvolutionQrCard() {
  const [provider, setProvider] = useState<TenantProfile["whatsapp_provider"]>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProfile = useCallback(async () => {
    const { data } = await api.get<TenantProfile>("/settings/profile");
    setProvider(data.whatsapp_provider);
  }, []);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    if (!qr) return;
    const interval = setInterval(async () => {
      const { data } = await api.get<{ status: string }>("/whatsapp-session/status");
      if (data.status === "connected") {
        await api.post("/whatsapp-session/confirm");
        setQr(null);
        setConnecting(false);
        await loadProfile();
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [qr, loadProfile]);

  async function connect() {
    setConnecting(true);
    setError(null);
    try {
      const { data } = await api.post<{ qr_base64: string }>("/whatsapp-session/connect");
      setQr(data.qr_base64);
    } catch (err) {
      setError(apiErrorMessage(err));
      setConnecting(false);
    }
  }

  async function disconnect() {
    await api.delete("/whatsapp-session");
    setQr(null);
    setConnecting(false);
    await loadProfile();
  }

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="font-semibold text-neutral-800">WhatsApp por QR Code (Evolution)</h2>
        {provider === "evolution" && (
          <span className="flex items-center gap-1 rounded-pill bg-green-50 px-3 py-1 text-xs font-semibold text-green-700">
            <Check size={12} /> Conectado
          </span>
        )}
      </div>
      <p className="mb-4 text-xs text-neutral-400">
        Alternativa ao WhatsApp Business (Meta) acima — escaneie um QR Code com o WhatsApp do
        seu negócio, sem precisar de conta na Meta.
      </p>

      {error && (
        <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>
      )}

      {provider === "evolution" ? (
        <button
          onClick={disconnect}
          className="rounded-pill border border-neutral-200 px-4 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-50"
        >
          Desconectar
        </button>
      ) : qr ? (
        <div className="flex flex-col items-center gap-3">
          <img src={qr} alt="QR Code do WhatsApp" className="h-56 w-56" />
          <p className="text-xs text-neutral-400">Escaneie com o WhatsApp do seu negócio</p>
        </div>
      ) : (
        <button
          onClick={connect}
          disabled={connecting}
          className="rounded-pill bg-primary-600 px-5 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {connecting ? "Conectando..." : "Conectar por QR Code"}
        </button>
      )}
    </div>
  );
}
```

E na função `WhatsappSection`, incluir o novo cartão:

```tsx
export default function WhatsappSection() {
  return (
    <div className="space-y-6">
      <CredentialsCard />
      <EvolutionQrCard />
      <TemplatesCard />
      <BindingsCard />
    </div>
  );
}
```

- [ ] **Step 5: Rodar de novo — todos devem passar**

Run: `pnpm --filter @e1p/web test -- WhatsappSection`
Expected: todos PASS.

- [ ] **Step 6: Typecheck**

Run: `pnpm --filter @e1p/web typecheck`
Expected: sem erro.

- [ ] **Step 7: Commit**

```bash
git add packages/shared-types/src/index.ts apps/web/src/features/config/WhatsappSection.tsx apps/web/src/features/config/WhatsappSection.test.tsx
git commit -m "feat: cartão de onboarding por QR Code (Evolution) em Configurações > WhatsApp"
```

---

### Task 9: Gate final — suíte completa (backend + frontend) + ruff + typecheck

**Files:** nenhum novo. Task de verificação.

- [ ] **Step 1: Backend**

Run (a partir de `apps/api/`):
```bash
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m pytest -q -m "not rls_e2e"
```
Expected: `ruff check .` limpo; pytest verde, total = 850 (Onda 1) + novos desta onda
(2 Task 3 + 6 Task 4 + ~5 Task 5 + 2 Task 6 + 3 Task 7 service + 1 Task 7 worker ≈ 19) ≈ 869
passed (conferir o número real no output).

- [ ] **Step 2: Frontend**

Run (a partir da raiz do monorepo):
```bash
pnpm --filter @e1p/web typecheck
pnpm --filter @e1p/web test
```
Expected: ambos limpos.

- [ ] **Step 3: Confirmar zero edição em teste de backend fora do previsto**

Run: `git diff --stat <tip-da-Onda-1> -- apps/api/tests/`
Expected: só os arquivos desta onda (`test_whatsapp_session_service.py`,
`test_whatsapp_session_router.py`, `test_whatsapp_dispatcher.py`, `test_worker.py`,
`test_settings.py` se tocado). Nenhum outro arquivo de teste de onda anterior deveria aparecer.

---

### Task 10: Push + PR/checks

**Files:** nenhum (git/GitHub).

- [ ] **Step 1: Push (mesma branch/PR das Ondas 0-1, se ainda não mesclado)**

```bash
git push
```

- [ ] **Step 2: Atualizar a descrição do PR** acrescentando a seção "Onda 2 — Onboarding por
QR Code" com o mesmo formato das seções anteriores (resumo + test plan).

- [ ] **Step 3: Verificar os checks**

Run: `gh pr checks --watch`
Expected: os 4 checks obrigatórios verdes.
