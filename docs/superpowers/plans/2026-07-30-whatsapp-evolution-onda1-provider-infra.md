# WhatsApp Evolution — Onda 1 (Provider Evolution + Infra) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar `app/core/whatsapp/providers/evolution.py` (envio de texto/mídia via
Evolution API) e a infra dos 3 `docker-compose*.yml` (container Evolution + Redis, com teto de
memória e role de Postgres própria), sem tornar nenhum tenant alcançável por este transporte
ainda — a Onda 2 é quem liga o fio (`TenantProfile.whatsapp_provider`).

**Architecture:** `providers/evolution.py` implementa o mesmo formato de retorno do provider
Meta (`"sent" | "logged" | "failed"`, nunca propaga exceção nas de envio) contra a REST API real
da Evolution (`atendai/evolution-api`), documentada e validada no estudo do Orbitask
(`docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md` §3). Diferente do
Meta (credenciais por tenant), a API key da Evolution é **global** (`settings.evolution_api_key`)
— só o **nome da instância** (`e1p-{tenant_id}`, calculado, nunca guardado) varia por tenant.
Funções que a Evolution não suporta (`capabilities.EVOLUTION`: `templates=False`) levantam erro
claro em vez de fingir sucesso — um consumidor real só chega lá se `capabilities.py` tiver sido
ignorado, e isso é bug, não caminho feliz.

**Tech Stack:** Python 3.13, httpx (já em requirements.txt — nenhuma dependência nova), pytest.
Docker Compose v2 (`atendai/evolution-api`, `redis:7-alpine`).

## Global Constraints

- **`providers/evolution.py` NÃO é chamado por nenhum código de produção nesta onda.** O
  despachante (`app/core/whatsapp/__init__.py::_resolve`) continua hardcoded em `meta` — não
  editar `_resolve` nesta onda (isso é Onda 2, junto com o campo `whatsapp_provider`). Nenhum
  tenant muda de comportamento.
- **Contrato de retorno idêntico ao Meta**: `send_text`/`send_media` devolvem
  `"sent" | "logged" | "failed"`, nunca propagam exceção. `upload_media` é local (não bate rede —
  ver Task 2) e pode levantar `WhatsappApiError`-equivalente só se os bytes forem inválidos
  (não deveria acontecer em uso normal).
- **Funções fora de `capabilities.EVOLUTION`** (`send_template`, `create_template`,
  `fetch_template_status`, `delete_template`, `verify_webhook_signature`, `fetch_media_url`,
  `download_media`) levantam `EvolutionUnsupportedError` — nunca "logged" silencioso. Ver Task 3.
- **`ruff check .` limpo** e `python -m pytest -q -m "not rls_e2e"` verde, rodados de
  `apps/api/` (mesmo comando do CI).
- **Evolution mockada via httpx** nos testes automatizados desta onda — validação contra uma
  instância Evolution real fica para o checklist manual, na VPS (decisão do usuário: mock agora,
  real depois).
- **Nenhuma porta nova publicada** nos composes de dev/prod/traefik para o serviço `evolution`
  — só a rede interna (mesma decisão da spec §5: o manager web da Evolution não existe pra fora).
- Ambiente: `apps/api/.venv/Scripts/python.exe` (reaproveitado do checkout principal; ver nota
  de ambiente no plano da Onda 0). Rodar pytest com esse interpretador.

---

## File Structure

```
apps/api/app/core/whatsapp/providers/evolution.py  → NOVO
apps/api/app/config.py                             → MODIFICADO (2 settings novas)
apps/api/tests/test_whatsapp_evolution_provider.py → NOVO

.env.example                                       → MODIFICADO (2 linhas)
infra/.env.prod.example                            → MODIFICADO (2 linhas)
infra/docker-compose.yml                           → MODIFICADO (2 serviços novos: evolution, redis)
infra/docker-compose.prod.yml                       → MODIFICADO (idem, rede `internal`)
infra/docker-compose.traefik.yml                    → MODIFICADO (idem, rede `db_internal`)
```

---

### Task 1: `app/config.py` — 2 settings novas

**Files:**
- Modify: `apps/api/app/config.py:31-33`
- Test: `apps/api/tests/test_settings.py` (só leitura, sem edição — ver Step 3)

**Interfaces:**
- Produces: `settings.evolution_api_url: str` (default `"http://evolution:8080"` — nome de
  serviço do Docker Compose, resolvido internamente), `settings.evolution_api_key: str`
  (default `""` — vazio = Evolution desligada, mesmo espírito de `whatsapp_token`).

- [ ] **Step 1: Adicionar as 2 settings**

Em `apps/api/app/config.py`, logo após `whatsapp_phone_id: str = ""`:

```python
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    # Evolution API (WhatsApp não-oficial, Baileys) — transporte alternativo ao Meta Cloud API
    # (ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md). A API
    # key é GLOBAL (controla a instância de TODOS os tenants) — diferente do Meta, cujas
    # credenciais são por tenant. Vazio = Evolution desligada (graceful degradation, mesmo
    # espírito de whatsapp_token/phone_id).
    evolution_api_url: str = "http://evolution:8080"
    evolution_api_key: str = ""
```

- [ ] **Step 2: Rodar a suíte de settings pra confirmar que nada quebrou (nenhuma edição de
  teste esperada — é campo aditivo com default)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_settings.py -q`
Expected: mesmo total de antes, sem edição.

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/config.py
git commit -m "feat: settings evolution_api_url/evolution_api_key (Evolution desligada por padrão)"
```

---

### Task 2: `providers/evolution.py` — `send_text`

**Files:**
- Create: `apps/api/app/core/whatsapp/providers/evolution.py`
- Test: `apps/api/tests/test_whatsapp_evolution_provider.py`

**Interfaces:**
- Produces: `send_text(*, to: str, text: str, instance: str) -> str` — `"sent" | "logged" |
  "failed"`. Lê `settings.evolution_api_url`/`evolution_api_key` (globais — não recebe
  credencial por parâmetro, ao contrário do provider Meta, porque não HÁ credencial por tenant
  na Evolution).

- [ ] **Step 1: Escrever o teste do caminho "logged" (sem API key configurada)**

```python
"""Testes do provider Evolution API (WhatsApp não-oficial/Baileys) — Onda 1 da feature de
WhatsApp por Evolution (ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md).

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
```

- [ ] **Step 2: Rodar para confirmar que falha (módulo ainda não existe)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_evolution_provider.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named '...providers.evolution'`.

- [ ] **Step 3: Criar `evolution.py` com `send_text`**

```python
"""Envio de WhatsApp via Evolution API (Baileys, não-oficial) — transporte alternativo ao Meta
Cloud API (`providers/meta.py`). Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md.

Diferente do Meta: a API key é GLOBAL (`settings.evolution_api_key`), não por tenant — só o
NOME DA INSTÂNCIA (`e1p-{tenant_id}`, calculado pelo chamador; ver Onda 2) varia por tenant.
Sem API key configurada (Evolution desligada), NÃO falha: registra como "logged", mesmo
contrato do provider Meta.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("e1p.whatsapp.evolution")


class EvolutionUnsupportedError(Exception):
    """Levantado por operações que a Evolution API não suporta (ver `capabilities.EVOLUTION`:
    templates=False). Um consumidor real só chega aqui se ignorou `capabilities.py` — é bug de
    quem chama, não caso de "logged" gracioso."""


def send_text(*, to: str, text: str, instance: str) -> str:
    """Retorna 'sent' | 'logged' | 'failed'. Mesmo contrato do provider Meta: NUNCA propaga
    exceção (fire-and-forget, degradação graciosa)."""
    if not settings.evolution_api_key:
        logger.info("[whatsapp.evolution:logged] instancia=%s para=%s msg=%s", instance, to, text)
        return "logged"
    try:
        resp = httpx.post(
            f"{settings.evolution_api_url}/message/sendText/{instance}",
            headers={"apikey": settings.evolution_api_key},
            json={"number": to, "text": text, "delay": 1000},
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp.evolution:failed] instancia=%s para=%s", instance, to)
        return "failed"
```

- [ ] **Step 4: Rodar de novo — deve passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_evolution_provider.py -v`
Expected: 1 teste, PASS.

- [ ] **Step 5: Escrever + rodar os testes dos caminhos "sent" e "failed"**

Acrescentar ao arquivo de teste:

```python
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
```

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_evolution_provider.py -v`
Expected: 4 testes, todos PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/whatsapp/providers/evolution.py apps/api/tests/test_whatsapp_evolution_provider.py
git commit -m "feat: providers/evolution.py::send_text (Evolution API, não-oficial)"
```

---

### Task 3: `providers/evolution.py` — mídia (`upload_media`/`send_media`) e não-suportadas

**Files:**
- Modify: `apps/api/app/core/whatsapp/providers/evolution.py`
- Modify: `apps/api/tests/test_whatsapp_evolution_provider.py`

**Interfaces:**
- Consumes: `base64` (stdlib).
- Produces: `upload_media(*, file_bytes: bytes, filename: str, mime_type: str) -> str` — **local,
  sem chamada de rede** (devolve o base64 dos bytes como referência opaca; ver justificativa no
  docstring). `send_media(*, to: str, instance: str, kind: str, media_id: str, caption: str = "")
  -> str` — decodifica `media_id` (o base64 devolvido por `upload_media`) e envia inline.
  `send_template`, `create_template`, `fetch_template_status`, `delete_template`,
  `verify_webhook_signature`, `fetch_media_url`, `download_media` — todas levantam
  `EvolutionUnsupportedError`.

- [ ] **Step 1: Escrever os testes de mídia + não-suportadas**

Acrescentar ao arquivo de teste:

```python
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
```

- [ ] **Step 2: Rodar para confirmar que falha (funções ainda não existem)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_evolution_provider.py -v`
Expected: os 4 testes da Task 2 continuam passando; os novos falham com `AttributeError` (função
ainda não existe no módulo).

- [ ] **Step 3: Implementar `upload_media`, `send_media` e as não-suportadas**

Acrescentar ao final de `apps/api/app/core/whatsapp/providers/evolution.py`:

```python
def upload_media(*, file_bytes: bytes, filename: str, mime_type: str) -> str:
    """A Evolution API NÃO tem endpoint de upload separado (diferente do Meta) — a mídia vai
    inline (base64) no próprio POST de envio. Esta função é só uma conveniência LOCAL, sem
    chamada de rede, que devolve os bytes em base64 como referência opaca — mantém o mesmo
    padrão de 2 passos (`upload_media` → `send_media(media_id=...)`) que o despachante já usa
    para o Meta, sem precisar de nenhuma mudança nos call sites do domínio quando a Onda 2 ligar
    o fio. `filename`/`mime_type` não são usados aqui (Evolution não precisa deles no upload,
    só no envio — ver `send_media`); mantidos na assinatura por simetria com o provider Meta."""
    return base64.b64encode(file_bytes).decode("ascii")


def send_media(
    *, to: str, instance: str, kind: str, media_id: str, caption: str = ""
) -> str:
    """`media_id` aqui é o base64 devolvido por `upload_media` (não um ID remoto — ver docstring
    de `upload_media`). Retorna 'sent' | 'logged' | 'failed'. Mesmo contrato de send_text: NUNCA
    propaga exceção."""
    if not settings.evolution_api_key:
        logger.info("[whatsapp.evolution:logged] mídia instancia=%s para=%s kind=%s",
                     instance, to, kind)
        return "logged"
    body: dict = {"number": to, "mediatype": kind, "media": media_id}
    if caption:
        body["caption"] = caption
    try:
        resp = httpx.post(
            f"{settings.evolution_api_url}/message/sendMedia/{instance}",
            headers={"apikey": settings.evolution_api_key},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp.evolution:failed] mídia instancia=%s para=%s", instance, to)
        return "failed"


def send_template(**_kwargs: object) -> str:
    raise EvolutionUnsupportedError(
        "Evolution API não suporta templates aprovados (capabilities.EVOLUTION.templates=False)"
    )


def create_template(**_kwargs: object) -> dict:
    raise EvolutionUnsupportedError("Evolution API não suporta templates aprovados")


def fetch_template_status(**_kwargs: object) -> dict:
    raise EvolutionUnsupportedError("Evolution API não suporta templates aprovados")


def delete_template(**_kwargs: object) -> None:
    raise EvolutionUnsupportedError("Evolution API não suporta templates aprovados")


def verify_webhook_signature(**_kwargs: object) -> bool:
    raise EvolutionUnsupportedError(
        "Evolution API não usa HMAC de webhook — autenticação é por isolamento de rede + "
        "segredo por tenant (ver Onda 3 da spec)"
    )


def fetch_media_url(**_kwargs: object) -> str:
    raise EvolutionUnsupportedError(
        "Evolution API entrega mídia inline no payload do webhook, sem endpoint de resolução "
        "separado (ver Onda 3 da spec)"
    )


def download_media(**_kwargs: object) -> bytes:
    raise EvolutionUnsupportedError(
        "Evolution API entrega mídia inline no payload do webhook, sem endpoint de download "
        "separado (ver Onda 3 da spec)"
    )
```

Adicionar o import de `base64` no topo do arquivo (junto de `logging`).

- [ ] **Step 4: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_evolution_provider.py -v`
Expected: 11 testes (4 da Task 2 + 7 desta task, sendo 5 parametrizados de
`test_unsupported_operations_raise_clear_error`), todos PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/whatsapp/providers/evolution.py apps/api/tests/test_whatsapp_evolution_provider.py
git commit -m "feat: providers/evolution.py::upload_media/send_media + operações não suportadas"
```

---

### Task 4: Gate AST — confirmar que `evolution.py` também respeita o despachante

**Files:**
- Modify: `apps/api/tests/test_whatsapp_dispatcher.py` (nenhuma edição de lógica — só reaproveita
  o teste já existente, que varre `app/` inteiro; nenhuma mudança é necessária aqui, este passo é
  só de VERIFICAÇÃO)

- [ ] **Step 1: Rodar o gate AST já escrito na Onda 0 — ele já cobre `providers/evolution.py`
  automaticamente, por varrer `app/core/whatsapp/providers/` inteiro**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_dispatcher.py::test_no_direct_provider_imports -v`
Expected: PASS (nenhum módulo fora do pacote `whatsapp` importa `providers.evolution` — porque
nada importa ainda, é exatamente o estado esperado nesta onda).

- [ ] **Step 2: Nenhum commit nesta task** (é só confirmação; sem mudança de arquivo).

---

### Task 5: Infra — `docker-compose.yml` (dev)

**Files:**
- Modify: `infra/docker-compose.yml`
- Modify: `.env.example`

**Interfaces:** nenhuma (infra).

- [ ] **Step 1: Acrescentar os serviços `evolution` e `redis` a `infra/docker-compose.yml`**

Logo após o serviço `postgres` (antes de `api`), acrescentar:

```yaml
  redis:
    # Exclusivo da Evolution API (sessões Baileys) — o worker do e1p continua fazendo polling
    # no Postgres, não ganha dependência nova. Ver docs/superpowers/specs/
    # 2026-07-30-whatsapp-evolution-multi-tenant-design.md §8.
    image: redis:7-alpine
    restart: unless-stopped
    mem_limit: 128m
    command: redis-server --maxmemory 96mb --maxmemory-policy allkeys-lru
    volumes:
      - evolution_redis_data:/data

  evolution:
    # WhatsApp por Evolution API (Baileys, não-oficial) — transporte alternativo ao Meta Cloud
    # API. SEM `ports:` — nada publicado, nada no Traefik (o manager web da Evolution não existe
    # pra fora). mem_limit RÍGIDO: se uma sessão Baileys inchar, o OOM killer mata a Evolution,
    # não o Postgres (o WhatsApp cai, o produto continua de pé). Versão FIXADA, nunca `:latest`.
    image: atendai/evolution-api:v2.2.3
    restart: unless-stopped
    mem_limit: 1g
    environment:
      AUTHENTICATION_API_KEY: ${EVOLUTION_API_KEY:-dev-evolution-key-troque-em-producao}
      DATABASE_PROVIDER: postgresql
      # Role e banco PRÓPRIOS (e1p_evolution/evolution_db) — a Evolution é software de
      # terceiro rodando ao lado do banco do e1p; não tem por que enxergar tabelas com RLS.
      DATABASE_CONNECTION_URI: postgresql://e1p_evolution:e1p-evolution-pass@postgres:5432/evolution_db
      REDIS_URI: redis://redis:6379/0
      DEL_INSTANCE: 'false'
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - evolution_instances:/evolution/instances
```

E no final do arquivo, acrescentar aos `volumes:` do topo:

```yaml
volumes:
  postgres_data:
  evolution_instances:
  evolution_redis_data:
```

- [ ] **Step 2: Acrescentar `EVOLUTION_API_KEY` ao `.env.example`**

Em `.env.example`, na seção "Integrações", logo após o bloco de WhatsApp Cloud API:

```bash
# ── WhatsApp Evolution API (não-oficial, Baileys) — alternativa ao Meta Cloud API ──
# Vazio em dev = usa o default local "dev-evolution-key-troque-em-producao" (só serve pro
# container local, sem risco real). Em produção, gere uma chave forte
# (ex.: `openssl rand -hex 32`) e NUNCA reuse o default.
# EVOLUTION_API_KEY=
```

- [ ] **Step 3: Validar que o compose sobe sem erro de sintaxe (sem subir de verdade — sem
  Docker daemon garantido no ambiente de CI/dev)**

Run: `docker compose -f infra/docker-compose.yml config --quiet`
Expected: sem saída (comando silencioso = YAML válido). Se `docker` não estiver disponível no
ambiente de execução, pular este passo é aceitável — o `docker compose config` só valida
sintaxe, não sobe nada.

- [ ] **Step 4: Commit**

```bash
git add infra/docker-compose.yml .env.example
git commit -m "feat: infra dev — container Evolution API + Redis (mem_limit, sem porta publicada)"
```

---

### Task 6: Infra — `docker-compose.prod.yml` e `docker-compose.traefik.yml`

**Files:**
- Modify: `infra/docker-compose.prod.yml`
- Modify: `infra/docker-compose.traefik.yml`
- Modify: `infra/.env.prod.example`

**Interfaces:** nenhuma (infra).

- [ ] **Step 1: `docker-compose.prod.yml` — mesmo bloco da Task 5, na rede `internal`**

Acrescentar, na mesma posição relativa (após `postgres`, antes de `api`):

```yaml
  redis:
    image: redis:7-alpine
    restart: always
    mem_limit: 128m
    command: redis-server --maxmemory 96mb --maxmemory-policy allkeys-lru
    volumes:
      - evolution_redis_data:/data
    networks: [internal]

  evolution:
    image: atendai/evolution-api:v2.2.3
    restart: always
    mem_limit: 1g
    environment:
      AUTHENTICATION_API_KEY: ${EVOLUTION_API_KEY:?defina no .env.prod}
      DATABASE_PROVIDER: postgresql
      DATABASE_CONNECTION_URI: postgresql://e1p_evolution:${EVOLUTION_DB_PASSWORD:?defina no .env.prod}@postgres:5432/evolution_db
      REDIS_URI: redis://redis:6379/0
      DEL_INSTANCE: 'false'
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - evolution_instances:/evolution/instances
    networks: [internal]
```

E nos `volumes:` do topo do arquivo:

```yaml
volumes:
  postgres_data:
  uploads_data:
  generated_data:
  evolution_instances:
  evolution_redis_data:
```

(Preservar as entradas já existentes — só acrescentar as 2 novas.)

- [ ] **Step 2: `docker-compose.traefik.yml` — mesmo bloco, na rede `db_internal`**

Mesmo conteúdo do Step 1, trocando `networks: [internal]` por `networks: [db_internal]` em
ambos os serviços (mesma rede que o `postgres` já usa neste arquivo — Evolution/Redis não
precisam da rede `edge`, não são HTTP-facing).

- [ ] **Step 3: Acrescentar `EVOLUTION_API_KEY` e `EVOLUTION_DB_PASSWORD` a
  `infra/.env.prod.example`**

Na seção "Integrações", logo após `WHATSAPP_PHONE_ID=`:

```bash
# WhatsApp Evolution API (não-oficial) — obrigatório se o produto for oferecer esse transporte
# em produção. Gere com `openssl rand -hex 32`. Sem isso preenchido, o serviço `evolution` no
# compose recusa subir (guard `:?defina no .env.prod`).
EVOLUTION_API_KEY=
# Senha do role e1p_evolution no Postgres (banco evolution_db, separado do e1pdb da app) —
# gere com `openssl rand -base64 32`. Nunca reutilize a senha do e1p_app/e1p_root.
EVOLUTION_DB_PASSWORD=
```

- [ ] **Step 4: Validar sintaxe dos 2 composes**

Run: `docker compose -f infra/docker-compose.prod.yml config --quiet` (é esperado que falhe
por variáveis obrigatórias ausentes — `${EVOLUTION_API_KEY:?...}` sem `.env.prod` presente; isso
É o comportamento correto/esperado, mesma guarda que `POSTGRES_ROOT_PASSWORD` já usa. Confirmar
que a mensagem de erro é sobre a variável faltando, não sobre sintaxe YAML quebrada.)

- [ ] **Step 5: Commit**

```bash
git add infra/docker-compose.prod.yml infra/docker-compose.traefik.yml infra/.env.prod.example
git commit -m "feat: infra prod/traefik — container Evolution API + Redis (mesma topologia do dev)"
```

---

### Task 7: Documentar o backup do volume `evolution_instances`

**Files:**
- Modify: `docs/RUNBOOK-BACKUP-RESTORE.md`

**Interfaces:** nenhuma (documentação).

- [ ] **Step 1: Entender por que este volume é item de segurança, não só de dado**

`evolution_instances` guarda as credenciais de sessão do WhatsApp de TODOS os tenants
conectados por Evolution — quem tem esse volume fala pelo WhatsApp de todos eles (spec §8).
Perdê-lo sem backup significa todo tenant reescaneando QR — incidente de suporte multiplicado
por N. O runbook atual (`docs/RUNBOOK-BACKUP-RESTORE.md`) só cobre `pg_dump` do Postgres; este
volume é um **bind/named volume do Docker**, backup diferente (tar do diretório, não dump SQL).

- [ ] **Step 2: Acrescentar uma seção nova ao runbook, após a seção 1 (Pré-requisitos)**

```markdown
## 1.2 Volume `evolution_instances` — credenciais de sessão do WhatsApp (todos os tenants)

**Sensibilidade:** este volume guarda as credenciais de sessão do WhatsApp de TODOS os tenants
conectados por Evolution API — trate como segredo, não como cache. Backup ausente = todo tenant
reescaneando QR quando o volume se perder (incidente de suporte multiplicado por N).

**Backup manual/ad-hoc** (adicionar ao cron do `backup.sh` é dívida — ver nota abaixo):

```bash
# A partir da VPS, com a stack de pé:
docker run --rm \
  -v e1p_evolution_instances:/data:ro \
  -v /opt/e1p-backups:/backup \
  alpine tar czf /backup/evolution-instances-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .
```

(O nome exato do volume — `e1p_evolution_instances` ou `infra_evolution_instances` — depende do
`project name` do Compose; confirme com `docker volume ls | grep evolution`.)

**Restore:**

```bash
docker run --rm \
  -v e1p_evolution_instances:/data \
  -v /opt/e1p-backups:/backup \
  alpine sh -c "cd /data && tar xzf /backup/evolution-instances-<timestamp>.tar.gz"
```

**Dívida registrada:** este backup NÃO está automatizado no cron/`backup.sh` ainda — é passo
manual. Automatizar exige decidir frequência (sessões mudam com uso, não só 1x/dia) e se entra
no mesmo offsite (rclone) do dump do Postgres. Fora de escopo desta onda (infra base); tratar
antes de conectar o primeiro tenant real em produção.
```

- [ ] **Step 3: Commit**

```bash
git add docs/RUNBOOK-BACKUP-RESTORE.md
git commit -m "docs: backup do volume evolution_instances (credenciais de sessão, todos os tenants)"
```

---

### Task 8: Gate final — suíte completa + ruff

**Files:** nenhum novo. Task de verificação.

- [ ] **Step 1: Rodar ruff + suíte completa**

Run (a partir de `apps/api/`):
```bash
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m pytest -q -m "not rls_e2e"
```
Expected: `ruff check .` sem erro; pytest verde, total de passes = o da Onda 0 (836) + os novos
testes desta onda (1 em `test_settings.py` sem mudança de contagem + 11 em
`test_whatsapp_evolution_provider.py`) = 847 passed (mais ou menos, conferir o número real).

- [ ] **Step 2: Confirmar que nenhum teste PRÉ-EXISTENTE precisou de edição nesta onda**

Run: `git diff --stat <tip-da-Onda-0> -- apps/api/tests/ ':!apps/api/tests/test_whatsapp_evolution_provider.py'`
Expected: saída vazia — diferente da Onda 0, esta onda não deveria exigir NENHUM ajuste em teste
existente (nada chama o provider Evolution ainda).

- [ ] **Step 3: Commit final se `ruff` reformatar algo (normalmente não deveria)**

Se o Step 1 não gerar mudança nenhuma, pule para a Task 8.

---

### Task 9: Abrir o Pull Request

**Files:** nenhum (git/GitHub).

- [ ] **Step 1: Push**

```bash
git push -u origin docs/whatsapp-evolution-multi-tenant
```

(mesma branch da Onda 0 — Onda 1 continua na mesma branch/PR se o PR da Onda 0 ainda não tiver
sido mesclado; se JÁ tiver sido mesclado, criar uma branch nova a partir da `main` atualizada
com o mesmo nome de branch, ou um sufixo `-onda1`, e abrir um PR novo seguindo o mesmo formato
do PR #62.)

- [ ] **Step 2: Abrir o PR (ou atualizar o existente, se ainda aberto)**

```bash
gh pr create --title "feat: provider Evolution API + infra (Onda 1 — Evolution API)" --body "$(cat <<'EOF'
## Resumo

Onda 1 do design em `docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md`:
implementa `app/core/whatsapp/providers/evolution.py` (envio de texto/mídia via Evolution API,
não-oficial) e a infra dos 3 docker-compose (container Evolution + Redis, com teto de memória e
role de Postgres própria) — sem tornar nenhum tenant alcançável por este transporte ainda (o
despachante continua hardcoded em `meta`; a Onda 2 é quem liga o fio via
`TenantProfile.whatsapp_provider`).

- `providers/evolution.py`: `send_text`, `upload_media` (local, base64 — a Evolution não tem
  endpoint de upload separado), `send_media`; as operações fora de `capabilities.EVOLUTION`
  (templates, HMAC de webhook, fetch/download de mídia) levantam `EvolutionUnsupportedError`
  em vez de fingir sucesso.
- Infra: `evolution` + `redis` nos 3 composes (dev/prod/traefik), sem porta publicada, com
  `mem_limit` (o OOM killer mata a Evolution antes do Postgres), role/DB próprios
  (`e1p_evolution`/`evolution_db`), versão da imagem FIXADA (nunca `:latest`).

## Test plan
- [x] `ruff check .` limpo
- [x] `pytest -q -m "not rls_e2e"` verde
- [x] Nenhum teste pré-existente precisou de edição (o provider não é chamado por ninguém ainda)
- [x] `docker compose config` valida a sintaxe dos 3 composes
- [ ] Validação contra uma instância Evolution real — fica para o checklist manual, na VPS
      (decisão do usuário: mock agora, real depois)

🤖 Gerado com [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verificar os checks**

Run: `gh pr checks --watch`
Expected: os 4 checks obrigatórios verdes. Corrigir e re-push se algum falhar, nunca pular hook.
