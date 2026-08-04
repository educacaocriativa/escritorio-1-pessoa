# WhatsApp Evolution — Onda 0 (Costura do `core/whatsapp`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar `app/core/whatsapp.py` (arquivo único, só Meta Cloud API) num pacote com
despachante de transporte, sem mudar nenhum comportamento externo, para que a Onda 1 (provider
Evolution) e as ondas seguintes possam adicionar um segundo transporte sem tocar de novo nos 9
pontos de chamada do domínio.

**Architecture:** `app/core/whatsapp/providers/meta.py` recebe o conteúdo de hoje, verbatim.
`app/core/whatsapp/__init__.py` vira o despachante: reexporta tudo que já existe (mesmo nome,
mesma assinatura) e acrescenta um parâmetro opcional `profile=` a cada função de envio/mídia, que
extrai `token`/`phone_id` do `TenantProfile` antes de delegar para `providers.meta`. Como nenhum
outro provider existe ainda, a resolução é sempre `meta` — a forma já fica pronta, o
comportamento não muda.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, pytest. Sem dependência nova nesta onda.

## Global Constraints

- **A suíte de testes atual passa SEM NENHUMA EDIÇÃO.** Nenhum arquivo em `apps/api/tests/`
  muda nesta onda — é o critério de pronto da Onda 0 (spec §13).
- **Contrato de envio inalterado:** `send_text`/`send_template`/`send_media` devolvem
  `"sent" | "logged" | "failed"` e **nunca propagam exceção**. As administrativas
  (`create_template`, `fetch_template_status`, `delete_template`, `upload_media`,
  `fetch_media_url`, `download_media`) **propagam** `WhatsappApiError` (spec §4).
- **Nenhum módulo importa `app.core.whatsapp.providers.*` diretamente.** Todo consumidor passa
  pelo despachante (`from app.core import whatsapp`) — gate de varredura AST obrigatório
  (spec §9, mesmo idioma de `test_money_planes.py`/`test_tenancy_guard.py`).
  Referência: `apps/api/tests/test_tenancy_guard.py` (padrão de varredura de arquivos já usado
  no projeto).
- **Sem campo `TenantProfile.whatsapp_provider` nesta onda** — ele chega na Onda 2. A resolução
  de provider é hardcoded para `meta` (com comentário explícito marcando o ponto de extensão).
- **`ruff check .` limpo** e `python -m pytest -q -m "not rls_e2e"` verde, rodados de dentro de
  `apps/api/` (mesmo comando do CI e de `scripts/check.sh`).
- Ambiente: `apps/api/.venv/Scripts/python.exe` (Windows, venv já criado). Rodar pytest com esse
  interpretador, não com `python` do PATH.

---

## File Structure

```
apps/api/app/core/whatsapp.py                    → REMOVIDO (movido)
apps/api/app/core/whatsapp/__init__.py           → NOVO — despachante
apps/api/app/core/whatsapp/capabilities.py       → NOVO — Capabilities (META/EVOLUTION)
apps/api/app/core/whatsapp/providers/__init__.py → NOVO — vazio
apps/api/app/core/whatsapp/providers/meta.py     → NOVO — conteúdo de whatsapp.py, verbatim

apps/api/app/modules/notifications/service.py    → MODIFICADO (2 call sites)
apps/api/app/modules/receivables/service.py      → MODIFICADO (3 call sites)
apps/api/app/modules/contracts/service.py        → MODIFICADO (2 call sites)
apps/api/app/modules/quotes/service.py           → MODIFICADO (2 call sites)
apps/api/app/modules/funnels/service.py          → MODIFICADO (1 call site)
apps/api/app/modules/whatsapp_inbox/service.py   → MODIFICADO (6 call sites)
apps/api/app/modules/platform/service.py         → NÃO MODIFICADO (ver Task 7 — exceção deliberada)

apps/api/tests/test_whatsapp_capabilities.py     → NOVO — testes do Capabilities
apps/api/tests/test_whatsapp_dispatcher.py       → NOVO — testes do despachante + gate AST
```

---

### Task 1: Mover o provider Meta para `providers/meta.py`

**Files:**
- Create: `apps/api/app/core/whatsapp/providers/__init__.py`
- Create: `apps/api/app/core/whatsapp/providers/meta.py`
- Delete (nesta task, criar como cópia — remoção do arquivo antigo acontece na Task 3): nenhuma
  ainda — `app/core/whatsapp.py` continua existindo até a Task 3 trocar por pacote.

**Interfaces:**
- Produces: `app.core.whatsapp.providers.meta` expõe, com a MESMA assinatura de hoje:
  `send_text(*, to, text, token=None, phone_id=None) -> str`,
  `send_template(*, to, token, phone_id, template_name, language, variables) -> str`,
  `send_media(*, to, token, phone_id, kind, media_id, caption="") -> str`,
  `upload_media(*, phone_id, token, file_bytes, filename, mime_type) -> str`,
  `fetch_media_url(*, token, media_id) -> str`,
  `download_media(*, token, url) -> bytes`,
  `verify_webhook_signature(*, app_secret, body, signature_header) -> bool`,
  `create_template(*, waba_id, token, name, language, category, body_text, variable_examples) -> dict`,
  `fetch_template_status(*, token, meta_template_id) -> dict`,
  `delete_template(*, waba_id, token, name) -> None`,
  classe `WhatsappApiError(Exception)`.

- [ ] **Step 1: Criar o diretório de providers com `__init__.py` vazio**

Conteúdo de `apps/api/app/core/whatsapp/providers/__init__.py`:

```python
"""Providers de transporte WhatsApp: meta.py (Cloud API oficial) e, a partir da Onda 1,
evolution.py (Evolution API/Baileys, não-oficial). Nenhum módulo fora de
`app/core/whatsapp/__init__.py` deve importar daqui diretamente — ver
`tests/test_whatsapp_dispatcher.py::test_no_direct_provider_imports`.
"""
```

- [ ] **Step 2: Copiar o conteúdo de `app/core/whatsapp.py` para `providers/meta.py`, sem
  alterar uma linha de lógica**

Leia o arquivo atual (`apps/api/app/core/whatsapp.py`) e copie seu conteúdo integral para
`apps/api/app/core/whatsapp/providers/meta.py`. Apenas o **docstring do módulo** ganha uma linha
de contexto no topo (nada de lógica muda):

```python
"""Envio de WhatsApp via WhatsApp Cloud API (Meta).

Provider oficial. Movido para cá na Onda 0 (costura do despachante) sem qualquer mudança de
comportamento — ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md.

Sem credenciais configuradas (caso atual), NÃO falha: apenas registra o envio como "logged"
para que o fluxo do produto funcione. Quando `whatsapp_token` + `whatsapp_phone_id` existirem,
entrega de verdade pela Graph API.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from app.config import settings

logger = logging.getLogger("e1p.whatsapp")


def send_text(
    *, to: str, text: str, token: str | None = None, phone_id: str | None = None
) -> str:
    """Retorna o status: 'sent' | 'logged' | 'failed'.

    `token`/`phone_id` são as credenciais do TENANT (ver `TenantProfile`) — passe-as sempre que
    o chamador já tiver o perfil do tenant em mãos. Quando omitidos (None, o default), cai na
    env global `settings.whatsapp_token`/`whatsapp_phone_id` — mantido só por retrocompatibilidade
    com testes/chamadas antigas; em produção essa env NUNCA está configurada (a integração é
    100% por tenant), então omitir os parâmetros equivale, na prática, a 'logged' sempre.
    """
    tok = token if token is not None else settings.whatsapp_token
    pid = phone_id if phone_id is not None else settings.whatsapp_phone_id
    if not tok or not pid:
        logger.info("[whatsapp:logged] para=%s msg=%s", to, text)
        return "logged"
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{pid}/messages",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp:failed] para=%s", to)
        return "failed"


class WhatsappApiError(Exception):
    """Erro ao chamar a Graph API para gerenciamento de templates (create/sync/delete).

    Diferente de send_text/send_template (fire-and-forget, nunca propagam exceção), estas são
    ações administrativas explícitas e DEVEM propagar erro pro service tratar.
    """


def _raise_for_error(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise WhatsappApiError(f"Graph API retornou erro {resp.status_code}: {detail}")


def create_template(
    *,
    waba_id: str,
    token: str,
    name: str,
    language: str,
    category: str,
    body_text: str,
    variable_examples: list[str],
) -> dict:
    """POST /{waba_id}/message_templates. Envia o template pra aprovação da Meta.

    Retorna o JSON de resposta (contém pelo menos 'id' e 'status'; a Meta às vezes já devolve
    'category' também). Levanta WhatsappApiError em qualquer falha (rede ou status >=400).
    """
    body_component: dict = {"type": "BODY", "text": body_text}
    if variable_examples:
        body_component["example"] = {"body_text": [variable_examples]}
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": name,
                "language": language,
                "category": category,
                "components": [body_component],
            },
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao criar template: {exc}") from exc
    _raise_for_error(resp)
    return resp.json()


def fetch_template_status(*, token: str, meta_template_id: str) -> dict:
    """GET /{meta_template_id}?fields=status,category,rejected_reason.

    Retorna {"status": ..., "category": ..., "rejected_reason": ...|None}.
    Levanta WhatsappApiError em qualquer falha.
    """
    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v21.0/{meta_template_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "status,category,rejected_reason"},
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao consultar template: {exc}") from exc
    _raise_for_error(resp)
    data = resp.json()
    return {
        "status": data.get("status"),
        "category": data.get("category"),
        "rejected_reason": data.get("rejected_reason"),
    }


def delete_template(*, waba_id: str, token: str, name: str) -> None:
    """DELETE /{waba_id}/message_templates?name={name}.

    Levanta WhatsappApiError em qualquer falha.
    """
    try:
        resp = httpx.delete(
            f"https://graph.facebook.com/v21.0/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {token}"},
            params={"name": name},
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao excluir template: {exc}") from exc
    _raise_for_error(resp)


def send_template(
    *, to: str, token: str, phone_id: str, template_name: str, language: str, variables: list[str]
) -> str:
    """Retorna 'sent' | 'logged' | 'failed'.

    MESMO contrato/invariante de send_text: NUNCA propaga exceção (fire-and-forget, graceful
    degradation) — 'logged' quando token ou phone_id vier vazio; 'failed' se a chamada falhar;
    'sent' em 200 OK.
    """
    if not token or not phone_id:
        logger.info("[whatsapp:logged] template para=%s nome=%s", to, template_name)
        return "logged"
    components = (
        [{"type": "body", "parameters": [{"type": "text", "text": v} for v in variables]}]
        if variables
        else []
    )
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language},
                    "components": components,
                },
            },
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp:failed] template para=%s nome=%s", to, template_name)
        return "failed"


def verify_webhook_signature(
    *, app_secret: str, body: bytes, signature_header: str | None
) -> bool:
    """Valida `X-Hub-Signature-256` (HMAC-SHA256 do corpo CRU do webhook). Comparação de tempo
    constante — nunca comparar segredos com `==`."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def upload_media(
    *, phone_id: str, token: str, file_bytes: bytes, filename: str, mime_type: str
) -> str:
    """POST /{phone_id}/media (multipart). Retorna o `media_id` temporário da Meta.
    Levanta WhatsappApiError em qualquer falha."""
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{phone_id}/media",
            headers={"Authorization": f"Bearer {token}"},
            data={"messaging_product": "whatsapp"},
            files={"file": (filename, file_bytes, mime_type)},
            timeout=30,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao subir mídia: {exc}") from exc
    _raise_for_error(resp)
    return resp.json()["id"]


def fetch_media_url(*, token: str, media_id: str) -> str:
    """GET /{media_id}. Retorna a URL temporária de download. Levanta WhatsappApiError."""
    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v21.0/{media_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao resolver mídia: {exc}") from exc
    _raise_for_error(resp)
    return resp.json()["url"]


def download_media(*, token: str, url: str) -> bytes:
    """Baixa os bytes da URL temporária (a Meta exige o Bearer token também neste GET).
    Levanta WhatsappApiError."""
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao baixar mídia: {exc}") from exc
    _raise_for_error(resp)
    return resp.content


def send_media(
    *, to: str, token: str, phone_id: str, kind: str, media_id: str, caption: str = ""
) -> str:
    """Retorna 'sent' | 'logged' | 'failed'. Mesmo contrato de send_text/send_template: NUNCA
    propaga exceção."""
    if not token or not phone_id:
        logger.info("[whatsapp:logged] mídia para=%s kind=%s", to, kind)
        return "logged"
    media_obj: dict[str, str] = {"id": media_id}
    if caption:
        media_obj["caption"] = caption
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp", "to": to, "type": kind, kind: media_obj,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp:failed] mídia para=%s kind=%s", to, kind)
        return "failed"
```

- [ ] **Step 3: Verificar que o arquivo antigo e o novo são idênticos em lógica**

Run: `diff <(tail -n +1 apps/api/app/core/whatsapp.py) <(tail -n +1 apps/api/app/core/whatsapp/providers/meta.py)`

Expected: só a diferença no docstring do topo (as linhas acrescentadas no Step 2). Nenhuma
diferença em código executável.

- [ ] **Step 4: Commit (arquivo antigo ainda intacto — ele só sai na Task 3)**

```bash
git add apps/api/app/core/whatsapp/providers/__init__.py apps/api/app/core/whatsapp/providers/meta.py
git commit -m "refactor: extrai provider Meta para app/core/whatsapp/providers/meta.py"
```

---

### Task 2: Criar o despachante (`app/core/whatsapp/__init__.py`)

**Files:**
- Create: `apps/api/app/core/whatsapp/__init__.py`

**Interfaces:**
- Consumes: `app.core.whatsapp.providers.meta` (Task 1) — todas as funções listadas ali.
- Produces: o pacote `app.core.whatsapp` expõe, para `from app.core import whatsapp`, EXATAMENTE
  os mesmos nomes de hoje (`send_text`, `send_template`, `send_media`, `upload_media`,
  `fetch_media_url`, `download_media`, `verify_webhook_signature`, `create_template`,
  `fetch_template_status`, `delete_template`, `WhatsappApiError`), cada função de
  envio/mídia/administrativa aceitando adicionalmente um parâmetro nomeado opcional `profile`
  (tipo `TenantProfile | None`, importado só sob `TYPE_CHECKING` para não criar dependência em
  tempo de execução de `app.core` sobre `app.modules`).

- [ ] **Step 1: Escrever o despachante**

Conteúdo de `apps/api/app/core/whatsapp/__init__.py`:

```python
"""Despachante de transporte WhatsApp.

Onda 0 (esta): só o provider Meta existe (`providers/meta.py`). Este módulo já aceita `profile=`
em toda função de envio/mídia — extrai `token`/`phone_id` do `TenantProfile` antes de delegar —
para que os 9 pontos de chamada do domínio parem de manusear credenciais cruas. A RESOLUÇÃO,
porém, é sempre `providers.meta`: não existe outro provider nem o campo
`TenantProfile.whatsapp_provider` ainda (chega na Onda 2, junto com `providers/evolution.py` na
Onda 1). Ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md.

Contrato preservado (idêntico ao módulo único que este pacote substitui):
- `send_text`/`send_template`/`send_media` devolvem "sent" | "logged" | "failed" e NUNCA
  propagam exceção (fire-and-forget, degradação graciosa).
- As administrativas (`create_template`, `fetch_template_status`, `delete_template`,
  `upload_media`, `fetch_media_url`, `download_media`) PROPAGAM `WhatsappApiError`.

Retrocompatibilidade: `token=`/`phone_id=` continuam aceitos diretamente (sem `profile`) — tanto
para a suíte de testes existente (`tests/test_whatsapp.py`, que testa o provider Meta via este
despachante sem nunca passar `profile`) quanto para chamadores que já têm as credenciais soltas
por razão própria (ver `platform/service.py::_send_invite`, que extrai token/phone_id DENTRO de
uma `tenant_session` fechada antes de enviar, evitando acessar atributo de um `TenantProfile`
SQLAlchemy já detached — ver nota nesse arquivo).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.whatsapp.providers import meta
from app.core.whatsapp.providers.meta import WhatsappApiError

if TYPE_CHECKING:
    from app.modules.settings.models import TenantProfile

__all__ = [
    "WhatsappApiError",
    "send_text",
    "send_template",
    "send_media",
    "upload_media",
    "fetch_media_url",
    "download_media",
    "verify_webhook_signature",
    "create_template",
    "fetch_template_status",
    "delete_template",
]


def _resolve(profile: "TenantProfile | None"):
    """Escolhe o provider pelo transporte do tenant.

    PONTO DE EXTENSÃO (Onda 2): quando `TenantProfile.whatsapp_provider` existir, este função
    passa a ser `meta if profile is None or profile.whatsapp_provider != "evolution" else
    evolution`. Até lá só `meta` existe — não há branch para escrever."""
    return meta


def send_text(
    *,
    to: str,
    text: str,
    profile: "TenantProfile | None" = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token
        phone_id = profile.whatsapp_phone_id
    return provider.send_text(to=to, text=text, token=token, phone_id=phone_id)


def send_template(
    *,
    to: str,
    template_name: str,
    language: str,
    variables: list[str],
    profile: "TenantProfile | None" = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
        phone_id = profile.whatsapp_phone_id or ""
    return provider.send_template(
        to=to,
        token=token or "",
        phone_id=phone_id or "",
        template_name=template_name,
        language=language,
        variables=variables,
    )


def send_media(
    *,
    to: str,
    kind: str,
    media_id: str,
    caption: str = "",
    profile: "TenantProfile | None" = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
        phone_id = profile.whatsapp_phone_id or ""
    return provider.send_media(
        to=to,
        token=token or "",
        phone_id=phone_id or "",
        kind=kind,
        media_id=media_id,
        caption=caption,
    )


def upload_media(
    *,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    profile: "TenantProfile | None" = None,
    token: str | None = None,
    phone_id: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
        phone_id = profile.whatsapp_phone_id or ""
    return provider.upload_media(
        phone_id=phone_id or "",
        token=token or "",
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
    )


def fetch_media_url(
    *,
    media_id: str,
    profile: "TenantProfile | None" = None,
    token: str | None = None,
) -> str:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
    return provider.fetch_media_url(token=token or "", media_id=media_id)


def download_media(
    *,
    url: str,
    profile: "TenantProfile | None" = None,
    token: str | None = None,
) -> bytes:
    provider = _resolve(profile)
    if profile is not None:
        token = profile.whatsapp_token or ""
    return provider.download_media(token=token or "", url=url)


def verify_webhook_signature(
    *, app_secret: str, body: bytes, signature_header: str | None
) -> bool:
    """Sem variante `profile=`: quem chama já tem `app_secret` resolvido de
    `PublicWhatsappAccount` (tabela global, pré-autenticação), não de `TenantProfile`."""
    return meta.verify_webhook_signature(
        app_secret=app_secret, body=body, signature_header=signature_header
    )


def create_template(
    *,
    waba_id: str,
    token: str,
    name: str,
    language: str,
    category: str,
    body_text: str,
    variable_examples: list[str],
) -> dict:
    return meta.create_template(
        waba_id=waba_id,
        token=token,
        name=name,
        language=language,
        category=category,
        body_text=body_text,
        variable_examples=variable_examples,
    )


def fetch_template_status(*, token: str, meta_template_id: str) -> dict:
    return meta.fetch_template_status(token=token, meta_template_id=meta_template_id)


def delete_template(*, waba_id: str, token: str, name: str) -> None:
    meta.delete_template(waba_id=waba_id, token=token, name=name)
```

- [ ] **Step 2: Remover o arquivo `app/core/whatsapp.py` antigo**

Agora que `app/core/whatsapp/__init__.py` existe, o arquivo `app/core/whatsapp.py` (módulo) e o
diretório `app/core/whatsapp/` (pacote) colidem — Python não permite os dois. Delete o arquivo
antigo:

```bash
git rm apps/api/app/core/whatsapp.py
```

- [ ] **Step 3: Rodar a suíte inteira de WhatsApp para confirmar zero edição necessária**

Run (a partir de `apps/api/`):
```bash
./.venv/Scripts/python.exe -m pytest tests/test_whatsapp.py tests/test_whatsapp_inbox_service.py tests/test_whatsapp_inbox_webhook.py tests/test_whatsapp_inbox_reply.py tests/test_whatsapp_inbox_models.py tests/test_whatsapp_inbox_media_worker.py tests/test_whatsapp_templates.py -q
```
Expected: `64 passed` (mesmo total da Task 0 de verificação) mais os arquivos adicionais, **todos
verdes, nenhum arquivo de teste tocado**.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/core/whatsapp/__init__.py
git commit -m "refactor: despachante WhatsApp com profile= opcional (só provider Meta ativo)"
```

---

### Task 3: Criar `capabilities.py` (o que cada transporte sabe fazer)

**Files:**
- Create: `apps/api/app/core/whatsapp/capabilities.py`
- Test: `apps/api/tests/test_whatsapp_capabilities.py`

**Interfaces:**
- Produces: `Capabilities` (dataclass congelado com `templates: bool`, `session_window: bool`,
  `media: bool`, `provisioning: str`), e as constantes `META` e `EVOLUTION` — ambas definidas
  agora, mesmo que só `META` seja alcançável nesta onda (`EVOLUTION` não tem provider nenhum
  atrás dela ainda; é dado puro, sem import de `providers.evolution`, então não cria dependência
  em código que só chega na Onda 1). Consumida pelos 3 pontos citados na spec §4
  (`notifications.enqueue`, caixa de resposta do inbox, tela de Configurações) — a partir da
  Onda 2, quando `TenantProfile.whatsapp_provider` existir para eles consultarem.

- [ ] **Step 1: Escrever o teste do dado (antes do dado existir)**

```python
"""Testes de app/core/whatsapp/capabilities.py — o que cada transporte sabe fazer, como DADO,
não como `if` espalhado pelos consumidores (ver spec §4)."""
from __future__ import annotations

from app.core.whatsapp.capabilities import EVOLUTION, META, Capabilities


def test_meta_capabilities() -> None:
    assert META == Capabilities(
        templates=True, session_window=True, media=True, provisioning="credentials",
    )


def test_evolution_capabilities() -> None:
    assert EVOLUTION == Capabilities(
        templates=False, session_window=False, media=True, provisioning="qrcode",
    )


def test_capabilities_is_frozen() -> None:
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        META.templates = False  # type: ignore[misc]
```

- [ ] **Step 2: Rodar para confirmar que falha (o módulo ainda não existe)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_capabilities.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.core.whatsapp.capabilities'`.

- [ ] **Step 3: Criar `capabilities.py`**

```python
"""O que cada transporte de WhatsApp sabe fazer — como DADO, não como `if` espalhado.

A Meta Cloud API exige template aprovado fora da janela de 24h; a Evolution (Baileys) não
conhece nenhum dos dois conceitos. Em vez de cada consumidor checar
`profile.whatsapp_provider == "meta"` (fácil de esquecer num consumidor novo), os 3 pontos que
precisam saber disso (fila de notificações ao resolver vínculo propósito→template, caixa de
resposta do inbox ao decidir entre texto livre e seletor de template, tela de Configurações ao
mostrar/esconder os cards de Templates e Vínculos) consultam este objeto — um transporte novo
sem entrada aqui quebra explicitamente em vez de falhar em silêncio.

Ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §4.

Nesta onda (Onda 0), `EVOLUTION` é dado sem provider atrás — `providers/evolution.py` chega na
Onda 1, e nenhum consumidor consegue alcançar `EVOLUTION` de fato até `TenantProfile
.whatsapp_provider` existir (Onda 2).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capabilities:
    templates: bool
    session_window: bool
    media: bool
    provisioning: str  # "credentials" (Meta: cola token/phone_id) | "qrcode" (Evolution)


META = Capabilities(templates=True, session_window=True, media=True, provisioning="credentials")
EVOLUTION = Capabilities(
    templates=False, session_window=False, media=True, provisioning="qrcode"
)
```

- [ ] **Step 4: Rodar de novo — deve passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_capabilities.py -v`
Expected: 3 testes, todos PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/core/whatsapp/capabilities.py apps/api/tests/test_whatsapp_capabilities.py
git commit -m "feat: Capabilities (templates/janela-24h/mídia/provisionamento) por transporte"
```

---

### Task 4: Testes do despachante + gate AST anti-`if` espalhado

**Files:**
- Create: `apps/api/tests/test_whatsapp_dispatcher.py`

**Interfaces:**
- Consumes: `app.core.whatsapp` (Task 2), `app.core.whatsapp.providers.meta` (Task 1).

- [ ] **Step 1: Escrever o teste que prova que `profile=` produz o mesmo resultado que
  `token=`/`phone_id=` explícitos**

```python
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
    """Dublê mínimo de TenantProfile — só os 2 campos que o despachante lê."""

    def __init__(self, token: str | None, phone_id: str | None) -> None:
        self.whatsapp_token = token
        self.whatsapp_phone_id = phone_id


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
```

- [ ] **Step 2: Rodar o novo arquivo de testes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_dispatcher.py -v`
Expected: todos os 7 testes passam (o gate AST passa porque nenhum call site ainda foi migrado
para `profile=`, mas também nenhum importa `providers` diretamente hoje).

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_whatsapp_dispatcher.py
git commit -m "test: cobertura do despachante WhatsApp (profile=) + gate anti-import-direto"
```

---

### Task 5: Migrar `notifications/service.py` para `profile=`

**Files:**
- Modify: `apps/api/app/modules/notifications/service.py:149-164`

**Interfaces:**
- Consumes: `whatsapp.send_template(*, to, template_name, language, variables, profile=...)`,
  `whatsapp.send_text(*, to, text, profile=...)` (Task 2).

- [ ] **Step 1: Confirmar o teste existente que cobre este trecho ainda passa antes da mudança**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications.py tests/test_notifications_queue.py -q`
Expected: todos passam (baseline antes da mudança).

- [ ] **Step 2: Trocar `token=`/`phone_id=` por `profile=`**

Em `apps/api/app/modules/notifications/service.py`, dentro de `process_pending`, troque:

```python
            elif notification.whatsapp_template_name:
                status = whatsapp.send_template(
                    to=notification.recipient,
                    token=profile.whatsapp_token or "",
                    phone_id=profile.whatsapp_phone_id or "",
                    template_name=notification.whatsapp_template_name,
                    language=notification.whatsapp_template_language or "pt_BR",
                    variables=notification.whatsapp_template_variables or [],
                )
            else:
                status = whatsapp.send_text(
                    to=notification.recipient,
                    text=notification.message,
                    token=profile.whatsapp_token,
                    phone_id=profile.whatsapp_phone_id,
                )
```

por:

```python
            elif notification.whatsapp_template_name:
                status = whatsapp.send_template(
                    to=notification.recipient,
                    profile=profile,
                    template_name=notification.whatsapp_template_name,
                    language=notification.whatsapp_template_language or "pt_BR",
                    variables=notification.whatsapp_template_variables or [],
                )
            else:
                status = whatsapp.send_text(
                    to=notification.recipient,
                    text=notification.message,
                    profile=profile,
                )
```

- [ ] **Step 3: Rodar os testes de novo (mesmo comando do Step 1) — mesmo resultado, zero edição
  de teste**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications.py tests/test_notifications_queue.py -q`
Expected: mesmos testes passam, sem tocar em nenhum arquivo `tests/test_notifications*.py`.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/modules/notifications/service.py
git commit -m "refactor: notifications usa whatsapp.send_*(profile=...) em vez de token/phone_id"
```

---

### Task 6: Migrar `receivables/service.py`, `contracts/service.py`, `quotes/service.py`, `funnels/service.py`

**Files:**
- Modify: `apps/api/app/modules/receivables/service.py:604-619,652-658`
- Modify: `apps/api/app/modules/contracts/service.py:287-301`
- Modify: `apps/api/app/modules/quotes/service.py:214-229`
- Modify: `apps/api/app/modules/funnels/service.py:453-458`

**Interfaces:**
- Consumes: mesmas assinaturas do despachante da Task 2.

- [ ] **Step 1: Baseline — rodar os 4 arquivos de teste correspondentes antes de mudar nada**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_receivables.py tests/test_contracts.py tests/test_quotes.py tests/test_funnels.py tests/test_funnel_automation.py -q`
Expected: todos passam (anote o total — vai comparar depois).

- [ ] **Step 2: `receivables/service.py` — cobrança com IA (linhas ~604-619)**

Troque:

```python
        status = whatsapp.send_template(
            to=client.phone if client and client.phone else "",
            token=profile.whatsapp_token or "", phone_id=profile.whatsapp_phone_id or "",
            template_name=template.name, language=template.language, variables=variables,
        )
        message = _render_template_preview(template.body_text, variables)
    else:
        message = _compose_dunning(name, charge.amount_cents, charge.due_date, charge.description)
        status = whatsapp.send_text(
            to=recipient, text=message,
            token=profile.whatsapp_token, phone_id=profile.whatsapp_phone_id,
        )
```

por:

```python
        status = whatsapp.send_template(
            to=client.phone if client and client.phone else "",
            profile=profile,
            template_name=template.name, language=template.language, variables=variables,
        )
        message = _render_template_preview(template.body_text, variables)
    else:
        message = _compose_dunning(name, charge.amount_cents, charge.due_date, charge.description)
        status = whatsapp.send_text(to=recipient, text=message, profile=profile)
```

- [ ] **Step 3: `receivables/service.py` — mensagem manual (`send_message`, linhas ~656-658)**

Troque:

```python
    status = whatsapp.send_text(
        to=recipient, text=text, token=profile.whatsapp_token, phone_id=profile.whatsapp_phone_id,
    )
```

por:

```python
    status = whatsapp.send_text(to=recipient, text=text, profile=profile)
```

- [ ] **Step 4: `contracts/service.py` — `send_contract` (linhas ~290-301)**

Troque:

```python
        status = whatsapp.send_template(
            to=client.phone if client and client.phone else "",
            token=profile.whatsapp_token or "", phone_id=profile.whatsapp_phone_id or "",
            template_name=template.name, language=template.language, variables=variables,
        )
        msg = _render_template_preview(template.body_text, variables)
    else:
        msg = f"Olá! Segue o contrato '{c.title}' para sua assinatura: {link}".strip()
        status = whatsapp.send_text(
            to=recipient, text=msg,
            token=profile.whatsapp_token, phone_id=profile.whatsapp_phone_id,
        )
```

por:

```python
        status = whatsapp.send_template(
            to=client.phone if client and client.phone else "",
            profile=profile,
            template_name=template.name, language=template.language, variables=variables,
        )
        msg = _render_template_preview(template.body_text, variables)
    else:
        msg = f"Olá! Segue o contrato '{c.title}' para sua assinatura: {link}".strip()
        status = whatsapp.send_text(to=recipient, text=msg, profile=profile)
```

- [ ] **Step 5: `quotes/service.py` — envio de orçamento (linhas ~218-229)**

Troque:

```python
        status = whatsapp.send_template(
            to=phone_to, token=profile.whatsapp_token or "",
            phone_id=profile.whatsapp_phone_id or "",
            template_name=template.name, language=template.language, variables=variables,
        )
        msg = _render_template_preview(template.body_text, variables)
    else:
        msg = f"Olá! Segue sua proposta de {q.title}: {valor}. Veja em: {link}".strip()
        status = whatsapp.send_text(
            to=recipient, text=msg,
            token=profile.whatsapp_token, phone_id=profile.whatsapp_phone_id,
        )
```

por:

```python
        status = whatsapp.send_template(
            to=phone_to, profile=profile,
            template_name=template.name, language=template.language, variables=variables,
        )
        msg = _render_template_preview(template.body_text, variables)
    else:
        msg = f"Olá! Segue sua proposta de {q.title}: {valor}. Veja em: {link}".strip()
        status = whatsapp.send_text(to=recipient, text=msg, profile=profile)
```

- [ ] **Step 6: `funnels/service.py` — nó de WhatsApp do funil (linhas ~454-458)**

Troque:

```python
        status = whatsapp.send_template(
            to=to_phone, token=profile.whatsapp_token or "",
            phone_id=profile.whatsapp_phone_id or "",
            template_name=tpl.name, language=tpl.language, variables=resolved_vars,
        )
```

por:

```python
        status = whatsapp.send_template(
            to=to_phone, profile=profile,
            template_name=tpl.name, language=tpl.language, variables=resolved_vars,
        )
```

- [ ] **Step 7: Rodar os mesmos 5 arquivos de teste do Step 1 de novo**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_receivables.py tests/test_contracts.py tests/test_quotes.py tests/test_funnels.py tests/test_funnel_automation.py -q`
Expected: mesmo total de passes do Step 1, **zero arquivo de teste editado**.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/receivables/service.py apps/api/app/modules/contracts/service.py apps/api/app/modules/quotes/service.py apps/api/app/modules/funnels/service.py
git commit -m "refactor: receivables/contracts/quotes/funnels usam whatsapp.send_*(profile=...)"
```

---

### Task 7: Migrar `whatsapp_inbox/service.py` (5 call sites)

**Files:**
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py:276-279,472-475,509-518,555-559`

**Interfaces:**
- Consumes: `whatsapp.fetch_media_url(*, media_id, profile=...)`,
  `whatsapp.download_media(*, url, profile=...)`, `whatsapp.send_text(*, to, text, profile=...)`,
  `whatsapp.upload_media(*, file_bytes, filename, mime_type, profile=...)`,
  `whatsapp.send_media(*, to, kind, media_id, caption="", profile=...)`,
  `whatsapp.send_template(*, to, template_name, language, variables, profile=...)`.

- [ ] **Step 1: Baseline — rodar a suíte do inbox antes de mudar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_service.py tests/test_whatsapp_inbox_reply.py tests/test_whatsapp_inbox_media_worker.py tests/test_whatsapp_inbox_webhook.py tests/test_whatsapp_inbox_models.py -q`
Expected: todos passam (anote o total).

- [ ] **Step 2: `process_pending_media` — mídia recebida (linhas ~276-279)**

Troque:

```python
            url = whatsapp.fetch_media_url(
                token=profile.whatsapp_token or "", media_id=msg.meta_media_id or ""
            )
            data = whatsapp.download_media(token=profile.whatsapp_token or "", url=url)
```

por:

```python
            url = whatsapp.fetch_media_url(profile=profile, media_id=msg.meta_media_id or "")
            data = whatsapp.download_media(profile=profile, url=url)
```

- [ ] **Step 3: `send_reply_text` (linhas ~472-475)**

Troque:

```python
    status = whatsapp.send_text(
        to=client.phone or "", text=text, token=profile.whatsapp_token,
        phone_id=profile.whatsapp_phone_id,
    )
```

por:

```python
    status = whatsapp.send_text(to=client.phone or "", text=text, profile=profile)
```

- [ ] **Step 4: `send_reply_media` — upload + envio (linhas ~509-518)**

Troque:

```python
    try:
        media_id = whatsapp.upload_media(
            phone_id=profile.whatsapp_phone_id or "", token=profile.whatsapp_token or "",
            file_bytes=file_bytes, filename=filename, mime_type=mime_type,
        )
    except whatsapp.WhatsappApiError as exc:
        raise WhatsappInboxError(f"Falha ao subir mídia: {exc}", 502) from exc
    status = whatsapp.send_media(
        to=client.phone or "", token=profile.whatsapp_token or "",
        phone_id=profile.whatsapp_phone_id or "", kind=kind, media_id=media_id, caption=caption,
    )
```

por:

```python
    try:
        media_id = whatsapp.upload_media(
            profile=profile, file_bytes=file_bytes, filename=filename, mime_type=mime_type,
        )
    except whatsapp.WhatsappApiError as exc:
        raise WhatsappInboxError(f"Falha ao subir mídia: {exc}", 502) from exc
    status = whatsapp.send_media(
        to=client.phone or "", profile=profile, kind=kind, media_id=media_id, caption=caption,
    )
```

- [ ] **Step 5: `send_reply_template` (linhas ~555-559)**

Troque:

```python
    status = whatsapp.send_template(
        to=client.phone or "", token=profile.whatsapp_token or "",
        phone_id=profile.whatsapp_phone_id or "", template_name=template.name,
        language=template.language, variables=variables,
    )
```

por:

```python
    status = whatsapp.send_template(
        to=client.phone or "", profile=profile, template_name=template.name,
        language=template.language, variables=variables,
    )
```

- [ ] **Step 6: Rodar os mesmos 5 arquivos de teste do Step 1 de novo**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_service.py tests/test_whatsapp_inbox_reply.py tests/test_whatsapp_inbox_media_worker.py tests/test_whatsapp_inbox_webhook.py tests/test_whatsapp_inbox_models.py -q`
Expected: mesmo total de passes do Step 1, **zero arquivo de teste editado**.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/whatsapp_inbox/service.py
git commit -m "refactor: whatsapp_inbox usa whatsapp.*(profile=...) em todos os 5 call sites"
```

---

### Task 8: `platform/service.py` — exceção deliberada, documentar e não migrar

**Files:**
- Modify: `apps/api/app/modules/platform/service.py:262-303` (comentário apenas — nenhuma
  mudança de lógica)

**Interfaces:**
- Consumes: nenhuma nova — este call site continua em `token=`/`phone_id=` explícitos.

- [ ] **Step 1: Entender por que este call site fica de fora**

Em `_send_invite`, o `profile` é lido **dentro** de `with tenant_session(tenant_id) as tdb:` e
`token, phone_id = profile.whatsapp_token, profile.whatsapp_phone_id` são extraídos como strings
ANTES do bloco `with` fechar — o código evita deliberadamente usar `profile` depois que a sessão
fecha (instância SQLAlchemy detached, risco de `DetachedInstanceError` num atributo não
carregado). Passar `profile=profile` para o despachante `send_template`/`send_text` **fora**
desse bloco reintroduziria esse risco. Migrar este call site não é seguro sem mudar também o
formato da função — fora de escopo desta onda (é refactor de outro comportamento, não só de
transporte).

- [ ] **Step 2: Acrescentar o comentário que registra a decisão (sem tocar em lógica)**

Em `apps/api/app/modules/platform/service.py`, imediatamente antes da linha
`token, phone_id = profile.whatsapp_token, profile.whatsapp_phone_id`, acrescente:

```python
            # Exceção deliberada (Onda 0 da spec de WhatsApp/Evolution): este call site NÃO
            # migra para `whatsapp.send_template(profile=...)`/`send_text(profile=...)` como os
            # outros 8 pontos do domínio. `profile` só existe DENTRO deste bloco `with
            # tenant_session`; extrair token/phone_id como strings simples ANTES do bloco fechar
            # é o que evita usar um `TenantProfile` (instância SQLAlchemy) já detached fora dele.
            # O despachante aceita token=/phone_id= diretamente por causa exatamente deste caso.
            token, phone_id = profile.whatsapp_token, profile.whatsapp_phone_id
```

(A linha de código em si — `token, phone_id = profile.whatsapp_token, profile.whatsapp_phone_id`
— permanece idêntica; só o comentário acima dela é novo.)

- [ ] **Step 3: Rodar a suíte de platform para confirmar que nada mudou**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_platform.py -q`
Expected: mesmo resultado de antes (nenhuma lógica mudou, só comentário).

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/modules/platform/service.py
git commit -m "docs: registra por que platform/service.py fica fora da migração para profile="
```

---

### Task 9: Gate final — suíte completa + ruff + confirmação de zero edição em testes

**Files:**
- Nenhum arquivo novo. Task de verificação.

- [ ] **Step 1: Rodar TODA a suíte (menos `rls_e2e`, que exige Docker/testcontainers)**

Run (a partir de `apps/api/`):
```bash
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m pytest -q -m "not rls_e2e"
```
Expected: `ruff check .` sem nenhum erro; pytest 100% verde.

- [ ] **Step 2: Confirmar que nenhum arquivo de teste foi tocado nesta onda**

Run: `git diff --stat main -- apps/api/tests/`

Expected: **saída vazia** — nenhuma linha. O único arquivo novo em `tests/` é
`test_whatsapp_dispatcher.py` (adicionado, não editado); `git diff --stat` compara conteúdo de
arquivos JÁ existentes em `main`, então um arquivo novo não aparece aqui — confirme
separadamente com `git status --porcelain apps/api/tests/` que `test_whatsapp_dispatcher.py` é o
ÚNICO item novo e nenhum outro arquivo de teste tem `M` (modificado).

- [ ] **Step 3: Rodar o gate AST isoladamente uma última vez, para deixar explícito no log da
  tarefa**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_dispatcher.py::test_no_direct_provider_imports -v`
Expected: PASS.

- [ ] **Step 4: Commit final (se `ruff` tiver reformatado algo — normalmente não deveria, já que
  o código novo já segue o estilo do projeto)**

Se o Step 1 não gerar nenhuma mudança de arquivo, não há o que commitar aqui — pule para a Task
9. Se `ruff check .` apontar algo (não deveria, mas confira), corrija e:

```bash
git add -A apps/api
git commit -m "fix: ajustes de lint pós-refactor do despachante WhatsApp"
```

---

### Task 10: Abrir o Pull Request

**Files:** nenhum (operação de git/GitHub).

- [ ] **Step 1: Push da branch**

```bash
git push -u origin docs/whatsapp-evolution-multi-tenant
```

- [ ] **Step 2: Abrir o PR via `gh`**

```bash
gh pr create --title "refactor: despachante de transporte WhatsApp (Onda 0 — Evolution API)" --body "$(cat <<'EOF'
## Resumo

Onda 0 do design em `docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md`:
transforma `app/core/whatsapp.py` num pacote com despachante de transporte, preparando o terreno
para o provider Evolution API (Onda 1) sem adiantar nenhuma funcionalidade nova.

- `app/core/whatsapp/providers/meta.py` — código de hoje, movido sem alteração de lógica.
- `app/core/whatsapp/__init__.py` — despachante; aceita `profile=` opcional em toda função de
  envio/mídia, com fallback total para `token=`/`phone_id=` explícitos.
- 8 dos 9 pontos de chamada do domínio migrados para `profile=` (notifications, receivables,
  contracts, quotes, funnels, whatsapp_inbox).
- `platform/service.py` fica de fora deliberadamente (instância `TenantProfile` já detached fora
  da `tenant_session` — documentado no código).
- Gate de varredura AST: nenhum módulo pode importar `app.core.whatsapp.providers.*` diretamente.

## Test plan
- [x] `ruff check .` limpo
- [x] `pytest -q -m "not rls_e2e"` 100% verde
- [x] Nenhum arquivo em `apps/api/tests/` foi editado (só `test_whatsapp_dispatcher.py`, novo)
- [x] `test_no_direct_provider_imports` prova o gate de import direto

🤖 Gerado com [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verificar os checks do CI**

Run: `gh pr checks --watch`

Expected: os 4 checks (`test-in-prod-image`, `cross-tenant-rls`, `secret-scan`, `sast-semgrep`)
terminam verdes. Se algum falhar, leia o log (`gh run view --log-failed`), corrija na branch, e
repita a partir do Step 1 desta task (novo commit, push, aguardar checks de novo) — nunca force
push nem pule hook.

- [ ] **Step 4: Reportar ao usuário**

Com os 4 checks verdes, o PR está pronto para o merge (botão do usuário, ou peça a ele /
`@devops` para mesclar — push direto em `main` é exclusivo do agente DevOps neste projeto).
