# Compartilhar comprovante do banco → Contas a Pagar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o comprovante de pagamento seja enviado direto do share sheet do celular (Android e iPhone) para dentro do e1p, anexado à conta certa em Contas a Pagar, com baixa opcional no mesmo gesto.

**Architecture:** Uma **bandeja de staging** (`Attachment` com `owner_type="receipt_inbox"`, `owner_id=<user_id>`) recebe o arquivo de qualquer porta de entrada. Vincular à conta é um `UPDATE` de `owner_type`/`owner_id` — os bytes nunca se movem. Duas portas: PWA Share Target (Android, via service worker sem cache) e app Atalhos (iOS, via token de dispositivo com escopo travado num único endpoint de escrita).

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL (RLS) · React 18 + Vite + TypeScript + Tailwind · pytest · vitest

**Spec:** `docs/superpowers/specs/2026-07-28-compartilhar-comprovante-celular-design.md`

**Branch:** `feat/comprovante-compartilhar-celular` (já criada, com a spec commitada)

## Global Constraints

- **Regra de Ouro nº 1 — isolamento por RLS.** Nenhuma query nova adiciona filtro manual de `tenant_id`. O isolamento vem da RLS via `get_tenant_db`/`tenant_session`. Consequência: testes de isolamento cross-tenant **não** rodam em SQLite; vão para o checklist manual do Postgres (Task 13).
- **Idioma:** produto e comentários de domínio em PT-BR; identificadores em inglês.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`).
- **Tamanho de arquivo:** máx. 10 MB por anexo (`MAX_BYTES` já existente).
- **Tipos aceitos no comprovante:** `application/pdf`, `image/jpeg`, `image/png` — **mais restrito** que o `ALLOWED_TYPES` global de `attachments/models.py` (que inclui áudio/vídeo por causa do WhatsApp).
- **Teto da bandeja:** 30 itens em staging por usuário.
- **`owner_type` e `label` são `String(24)`** — `"receipt_inbox"` (13) e `"comprovante"` (11) cabem; nenhuma migration em `attachments`.
- **Códigos HTTP herdados de `attachments.service`:** `415` tipo inválido, `413` acima de 10 MB, `422` arquivo vazio. As rotas novas devem propagá-los, nunca achatar em `400`.
- **Ordem das migrations:** a última é `0056`; a nova é `0057`.
- **Rodar a suíte:** `cd apps/api && source .venv/bin/activate && pytest` · `pnpm --filter @e1p/web test` · `bash scripts/check.sh` antes de fechar.
- **Todo modelo novo entra em `app/db/registry.py`**, senão `Base.metadata.create_all` dos testes não cria a tabela.

---

## File Structure

**Backend — criar:**

| Arquivo | Responsabilidade |
|---|---|
| `apps/api/app/modules/payables/receipts.py` | Serviço da bandeja: constantes, staging, listagem, candidatas, vinculação |
| `apps/api/app/modules/payables/receipts_router.py` | As 6 rotas `/payables/receipts*` (separadas de `router.py`, que já tem 151 linhas) |
| `apps/api/app/modules/payables/receipts_schemas.py` | Schemas de entrada/saída da bandeja |
| `apps/api/app/modules/device_tokens/__init__.py` | Módulo do token de dispositivo |
| `apps/api/app/modules/device_tokens/models.py` | `DeviceToken` (tabela GLOBAL, sem RLS) |
| `apps/api/app/modules/device_tokens/service.py` | Criar / resolver / listar / revogar |
| `apps/api/app/modules/device_tokens/router.py` | `/settings/device-tokens` |
| `apps/api/app/modules/device_tokens/schemas.py` | Schemas do token |
| `apps/api/app/core/receipt_auth.py` | Dependency que aceita JWT **ou** `X-E1P-Device-Token` |
| `apps/api/migrations/versions/0057_device_tokens.py` | Migration da tabela |
| `apps/api/tests/test_receipts.py` | Testes da bandeja |
| `apps/api/tests/test_device_tokens.py` | Testes do token |

**Backend — modificar:**

| Arquivo | Mudança |
|---|---|
| `apps/api/app/modules/payables/service.py` | Extrair `apply_paid` e `build_payable` (versões sem commit) |
| `apps/api/app/modules/__init__.py` | Registrar `receipts_router` e `device_tokens_router` |
| `apps/api/app/db/registry.py` | Importar `DeviceToken` |
| `apps/api/tests/conftest.py` | Override de `get_receipt_db` |

**Frontend — criar:**

| Arquivo | Responsabilidade |
|---|---|
| `apps/web/public/manifest.webmanifest` | PWA instalável + `share_target` |
| `apps/web/public/sw.js` | Service worker mínimo (só o POST do share target, zero cache) |
| `apps/web/public/icon-192.png`, `icon-512.png` | Ícones do PWA (maskable) |
| `apps/web/src/lib/shareInbox.ts` | Helper de IndexedDB (lado do app) |
| `apps/web/src/lib/shareInbox.test.ts` | Teste do helper |
| `apps/web/src/features/pagar/CompartilharPage.tsx` | Rota de trânsito `/compartilhar` |
| `apps/web/src/features/pagar/CompartilharPage.test.tsx` | Teste da rota de trânsito |
| `apps/web/src/features/pagar/ComprovantePage.tsx` | Tela `/comprovante/:id` |
| `apps/web/src/features/pagar/ComprovantePage.test.tsx` | Teste da tela |
| `apps/web/src/features/config/CelularSection.tsx` | Seção "Celular" (instruções + tokens) |
| `apps/web/src/features/config/CelularSection.test.tsx` | Teste da seção |

**Frontend — modificar:**

| Arquivo | Mudança |
|---|---|
| `apps/web/index.html` | `<link rel="manifest">` |
| `apps/web/src/main.tsx` | Registro do service worker |
| `apps/web/src/app/App.tsx` | Rotas `/compartilhar` e `/comprovante/:id` |
| `apps/web/src/features/pagar/PagarPage.tsx` | Slot `comprovante` + aviso da bandeja |
| `apps/web/src/features/config/ConfiguracoesPage.tsx` | Montar `CelularSection` |
| `apps/web/nginx.conf` | `sw.js` sem cache + MIME do manifest |
| `apps/web/package.json` | devDependency `fake-indexeddb` |
| `packages/shared-types/src/index.ts` | Tipos `ReceiptCandidate` e `DeviceTokenOut` |

**Docs:**

| Arquivo | Mudança |
|---|---|
| `docs/CHECKLIST-COMPROVANTE-MOBILE.md` | Validação manual (Android, iOS, Postgres/RLS) |
| `CLAUDE.md` | Registrar a entrega e a dívida |

---

## Task 1: Bandeja — staging, listagem e descarte

Cria o serviço e as três rotas mais simples. Autenticação por JWT apenas; o token de dispositivo entra na Task 6.

**Files:**
- Create: `apps/api/app/modules/payables/receipts.py`
- Create: `apps/api/app/modules/payables/receipts_schemas.py`
- Create: `apps/api/app/modules/payables/receipts_router.py`
- Create: `apps/api/tests/test_receipts.py`
- Modify: `apps/api/app/modules/__init__.py`

**Interfaces:**
- Consumes: `attachments.service.create_attachment`, `attachments.service.delete_attachment`, `attachments.models.Attachment`, `core.tenancy.get_tenant_db`, `core.tenancy.require_module`
- Produces:
  - `receipts.OWNER_INBOX: str = "receipt_inbox"`
  - `receipts.OWNER_PAYABLE: str = "payable"`
  - `receipts.LABEL_COMPROVANTE: str = "comprovante"`
  - `receipts.RECEIPT_TYPES: set[str]`
  - `receipts.INBOX_MAX_ITEMS: int = 30`
  - `receipts.ReceiptError(Exception)` com `.status_code`
  - `receipts.stage_receipt(db, *, tenant_id, user_id, actor, filename, content_type, data) -> Attachment`
  - `receipts.list_inbox(db, *, user_id) -> list[Attachment]`
  - `receipts.discard(db, *, attachment_id, user_id, tenant_id, actor) -> None`
  - `receipts_schemas.ReceiptOut` com campos `id, filename, content_type, size, created_at`

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_receipts.py`:

```python
"""Testes da bandeja de comprovantes (Contas a Pagar)."""
import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Recibo Co",
    "document": "20202020000188",
    "slug": "reciboco",
    "email": "recibo@example.com",
    "name": "Recibo",
    "password": "senha-bem-comprida",
}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client: TestClient, headers, *, name="comprovante.png", ctype="image/png", data=PNG):
    return client.post(
        "/payables/receipts",
        files={"file": (name, data, ctype)},
        headers=headers,
    )


def test_upload_cria_item_na_bandeja(client: TestClient, headers):
    resp = _upload(client, headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "comprovante.png"
    assert body["content_type"] == "image/png"
    assert body["size"] == len(PNG)

    bandeja = client.get("/payables/receipts", headers=headers).json()
    assert [i["id"] for i in bandeja] == [body["id"]]


def test_upload_recusa_tipo_nao_permitido(client: TestClient, headers):
    resp = _upload(client, headers, name="audio.ogg", ctype="audio/ogg", data=b"OggS____")
    assert resp.status_code == 415


def test_upload_recusa_arquivo_vazio(client: TestClient, headers):
    resp = _upload(client, headers, data=b"")
    assert resp.status_code == 422


def test_upload_recusa_acima_de_10mb(client: TestClient, headers):
    resp = _upload(client, headers, data=b"0" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 413


def test_bandeja_tem_teto_de_30(client: TestClient, headers):
    for _ in range(30):
        assert _upload(client, headers).status_code == 201
    resp = _upload(client, headers)
    assert resp.status_code == 409
    assert "bandeja" in resp.json()["detail"].lower()


def test_descartar_remove_da_bandeja(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    assert client.delete(f"/payables/receipts/{rid}", headers=headers).status_code == 204
    assert client.get("/payables/receipts", headers=headers).json() == []


def test_descartar_id_inexistente_da_404(client: TestClient, headers):
    assert client.delete("/payables/receipts/nao-existe", headers=headers).status_code == 404
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py -v`
Expected: FAIL — todas com `404 Not Found` (as rotas ainda não existem).

- [ ] **Step 3: Criar o serviço da bandeja**

Criar `apps/api/app/modules/payables/receipts.py`:

```python
"""Bandeja de comprovantes: staging de arquivo antes de saber a qual conta ele pertence.

Um comprovante recém-chegado é um `Attachment` normal (RLS, storage S3/Postgres já resolvidos
por `attachments.service`) com `owner_type=OWNER_INBOX` e `owner_id=<user_id>`. Vincular à conta
depois é só trocar essas duas colunas — os bytes NUNCA se movem, porque a chave do storage
(`storage.build_key`) é `tenants/{tenant_id}/attachments/{id}/{filename}` e não carrega o dono.

Por isso a bandeja não tem tabela própria: qualquer porta de entrada nova (WhatsApp, e-mail)
só precisa gravar um Attachment com esse owner_type.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.attachments import service as attachments_service
from app.modules.attachments.models import Attachment

# owner_type do anexo enquanto ele está em staging (ainda sem conta definida).
OWNER_INBOX = "receipt_inbox"
# owner_type do anexo depois de vinculado a uma conta a pagar.
OWNER_PAYABLE = "payable"
LABEL_COMPROVANTE = "comprovante"

# Mais restrito que ALLOWED_TYPES (que aceita áudio/vídeo por causa da mídia do WhatsApp):
# comprovante de banco é PDF ou foto.
RECEIPT_TYPES = {"application/pdf", "image/jpeg", "image/png"}

# Teto de itens em staging por usuário. Existe para limitar o dano de um token de dispositivo
# vazado (ver core/receipt_auth.py): o pior caso vira "enche a bandeja", não "enche o storage".
INBOX_MAX_ITEMS = 30


class ReceiptError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _inbox_count(db: Session, *, user_id: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Attachment)
        .where(Attachment.owner_type == OWNER_INBOX, Attachment.owner_id == user_id)
    ) or 0


def stage_receipt(
    db: Session,
    *,
    tenant_id: str,
    user_id: str,
    actor: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> Attachment:
    """Guarda o arquivo na bandeja do usuário. Valida o tipo ANTES de tocar no storage."""
    if content_type not in RECEIPT_TYPES:
        raise ReceiptError("Envie o comprovante em PDF, JPEG ou PNG.", 415)
    if _inbox_count(db, user_id=user_id) >= INBOX_MAX_ITEMS:
        raise ReceiptError(
            f"Bandeja cheia ({INBOX_MAX_ITEMS} comprovantes). "
            "Vincule ou descarte os pendentes antes de enviar outro.",
            409,
        )
    # create_attachment cuida de tamanho/vazio (413/422), storage S3 vs Postgres, e auditoria.
    return attachments_service.create_attachment(
        db,
        tenant_id=tenant_id,
        actor=actor,
        owner_type=OWNER_INBOX,
        owner_id=user_id,
        label=LABEL_COMPROVANTE,
        filename=filename,
        content_type=content_type,
        data=data,
    )


def list_inbox(db: Session, *, user_id: str) -> list[Attachment]:
    """Comprovantes do usuário ainda não vinculados, mais recentes primeiro."""
    stmt = (
        select(Attachment)
        .where(Attachment.owner_type == OWNER_INBOX, Attachment.owner_id == user_id)
        .order_by(Attachment.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def get_staged(db: Session, *, attachment_id: str, user_id: str) -> Attachment:
    """Resolve um anexo que DEVE estar na bandeja do usuário.

    Distingue os dois "não encontrado" de propósito: já vinculado é 409 (o usuário fez algo
    válido, só que duas vezes); de outro usuário é 404 (não existe, do ponto de vista dele).
    """
    att = db.get(Attachment, attachment_id)
    if att is None:
        raise ReceiptError("Comprovante não encontrado", 404)
    if att.owner_type != OWNER_INBOX:
        raise ReceiptError("Este comprovante já foi anexado a uma conta", 409)
    if att.owner_id != user_id:
        raise ReceiptError("Comprovante não encontrado", 404)
    return att


def discard(db: Session, *, attachment_id: str, user_id: str, tenant_id: str, actor: str) -> None:
    get_staged(db, attachment_id=attachment_id, user_id=user_id)
    attachments_service.delete_attachment(
        db, attachment_id=attachment_id, tenant_id=tenant_id, actor=actor
    )
```

- [ ] **Step 4: Criar os schemas**

Criar `apps/api/app/modules/payables/receipts_schemas.py`:

```python
"""Schemas da bandeja de comprovantes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReceiptOut(BaseModel):
    """Um comprovante em staging. Não expõe owner_type/owner_id — são detalhe interno."""

    id: str
    filename: str
    content_type: str
    size: int
    created_at: datetime
```

- [ ] **Step 5: Criar o router**

Criar `apps/api/app/modules/payables/receipts_router.py`:

```python
"""Rotas da bandeja de comprovantes (`/payables/receipts`).

Separado de `payables/router.py` porque é um fluxo próprio (entrada pelo celular) com
autenticação própria a partir da Task 6 — misturar os dois deixaria o router de contas
difícil de ler.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_tenant_db, require_module
from app.modules.attachments.models import Attachment
from app.modules.payables import receipts
from app.modules.payables.receipts_schemas import ReceiptOut

router = APIRouter(prefix="/payables/receipts", tags=["payables-receipts"])

_guard = require_module("payables")


def _out(a: Attachment) -> ReceiptOut:
    return ReceiptOut(
        id=a.id, filename=a.filename, content_type=a.content_type,
        size=a.size, created_at=a.created_at,
    )


def _err(e: Exception, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail=str(e))


@router.post("", response_model=ReceiptOut, status_code=201)
async def upload_receipt(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ReceiptOut:
    """Recebe o comprovante e guarda na bandeja. É a única rota que as portas de entrada
    (Share Target do Android, Atalho do iOS) conhecem."""
    from app.modules.attachments.service import AttachmentError

    data = await file.read()
    try:
        att = receipts.stage_receipt(
            db, tenant_id=user.tenant_id, user_id=user.user_id, actor=user.user_id,
            filename=file.filename or "comprovante",
            content_type=file.content_type or "", data=data,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    except AttachmentError as e:
        # Propaga 413/422 de create_attachment em vez de achatar em 400.
        raise _err(e, e.status_code) from e
    return _out(att)


@router.get("", response_model=list[ReceiptOut])
def list_receipts(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ReceiptOut]:
    return [_out(a) for a in receipts.list_inbox(db, user_id=user.user_id)]


@router.delete("/{attachment_id}", status_code=204)
def discard_receipt(
    attachment_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Response:
    try:
        receipts.discard(
            db, attachment_id=attachment_id, user_id=user.user_id,
            tenant_id=user.tenant_id, actor=user.user_id,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    return Response(status_code=204)
```

- [ ] **Step 6: Registrar o router**

Em `apps/api/app/modules/__init__.py`, adicionar o import ao lado do de `payables_router` (linha 29, ordem alfabética):

```python
from app.modules.payables.receipts_router import router as payables_receipts_router
```

E, na seção de `api_router.include_router(...)`, logo depois da linha do `payables_router`:

```python
api_router.include_router(payables_receipts_router)
```

- [ ] **Step 7: Rodar os testes**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py -v`
Expected: PASS (7 testes).

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/payables/receipts.py \
        apps/api/app/modules/payables/receipts_schemas.py \
        apps/api/app/modules/payables/receipts_router.py \
        apps/api/app/modules/__init__.py \
        apps/api/tests/test_receipts.py
git commit -m "feat: bandeja de comprovantes (staging, listagem, descarte)"
```

---

## Task 2: Lista curta de contas candidatas

**Files:**
- Modify: `apps/api/app/modules/payables/receipts.py`
- Modify: `apps/api/app/modules/payables/receipts_router.py`
- Modify: `apps/api/tests/test_receipts.py`

**Interfaces:**
- Consumes: `receipts.*` da Task 1; `payables.models.Payable`, `STATUS_OPEN`, `STATUS_PAID`, `STATUS_CANCELED`; `payables.service.payable_out`
- Produces: `receipts.list_candidates(db, *, q: str = "", paid_window_days: int = 30) -> list[Payable]`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `apps/api/tests/test_receipts.py`:

```python
def _bill(client: TestClient, headers, **over):
    base = {
        "description": "Energia",
        "category": "Estrutura",
        "supplier": "Copel",
        "amount_cents": 30000,
        "due_date": "2099-01-10",
    }
    return client.post("/payables/bills", json={**base, **over}, headers=headers).json()


def test_candidates_lista_abertas_por_vencimento(client: TestClient, headers):
    _bill(client, headers, description="Depois", due_date="2099-03-01")
    _bill(client, headers, description="Antes", due_date="2099-01-01")
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == ["Antes", "Depois"]


def test_candidates_inclui_pagas_recentes_depois_das_abertas(client: TestClient, headers):
    aberta = _bill(client, headers, description="Aberta", due_date="2099-02-02")
    paga = _bill(client, headers, description="Paga", due_date="2099-02-03")
    client.post(f"/payables/bills/{paga['id']}/pay", headers=headers)
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == ["Aberta", "Paga"]
    assert itens[0]["id"] == aberta["id"]


def test_candidates_nao_lista_canceladas(client: TestClient, headers):
    b = _bill(client, headers, description="Cancelada")
    client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == []


def test_candidates_busca_por_descricao_e_fornecedor(client: TestClient, headers):
    _bill(client, headers, description="Aluguel sala", supplier="Imobiliária X")
    _bill(client, headers, description="Energia", supplier="Copel")

    por_descricao = client.get("/payables/receipts/candidates?q=aluguel", headers=headers).json()
    assert [i["description"] for i in por_descricao] == ["Aluguel sala"]

    por_fornecedor = client.get("/payables/receipts/candidates?q=copel", headers=headers).json()
    assert [i["description"] for i in por_fornecedor] == ["Energia"]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py -k candidates -v`
Expected: FAIL — `404 Not Found` na rota `/payables/receipts/candidates`.

- [ ] **Step 3: Implementar `list_candidates`**

Acrescentar em `apps/api/app/modules/payables/receipts.py` (imports no topo do arquivo):

```python
from datetime import UTC, datetime, timedelta

from app.modules.payables.models import STATUS_OPEN, STATUS_PAID, Payable
```

Importe **apenas** o que esta task usa. `STATUS_CANCELED` só é usado por `link_receipt`, na Task 3 — importá-lo aqui deixa um símbolo sem uso e o `ruff` quebra com `F401` (o `select` em `apps/api/pyproject.toml` inclui `F`, e o `per-file-ignores` só isenta `tests/*`).

E a função ao fim do arquivo:

```python
def list_candidates(db: Session, *, q: str = "", paid_window_days: int = 30) -> list[Payable]:
    """Lista curta para escolher no celular: abertas primeiro (por vencimento, então as
    vencidas caem naturalmente no topo), depois as pagas recentes — o caso de quem já deu
    baixa e só faltava o comprovante. Canceladas nunca aparecem.

    A ordenação é feita em duas queries, não num ORDER BY composto, porque os dois grupos
    ordenam por colunas diferentes (due_date crescente vs paid_at decrescente).
    """
    term = q.strip().lower()

    def _match(stmt):
        if not term:
            return stmt
        like = f"%{term}%"
        return stmt.where(
            func.lower(Payable.description).like(like) | func.lower(Payable.supplier).like(like)
        )

    abertas = list(
        db.scalars(
            _match(select(Payable).where(Payable.status == STATUS_OPEN))
            .order_by(Payable.due_date)
            .limit(100)
        ).all()
    )
    cutoff = datetime.now(UTC) - timedelta(days=paid_window_days)
    pagas = list(
        db.scalars(
            _match(
                select(Payable).where(Payable.status == STATUS_PAID, Payable.paid_at >= cutoff)
            )
            .order_by(Payable.paid_at.desc())
            .limit(100)
        ).all()
    )
    # Conta cancelada nunca entra: nenhum dos dois filtros a inclui (por isso não há
    # `.where(status != canceled)` — seria redundante).
    return (abertas + pagas)[:100]
```

- [ ] **Step 4: Adicionar a rota**

Em `apps/api/app/modules/payables/receipts_router.py`, adicionar ao import do FastAPI o `Query`, importar `PayableOut` e `service`, e acrescentar a rota **antes** de `discard_receipt`:

```python
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from app.modules.payables import receipts, service as payables_service
from app.modules.payables.schemas import PayableOut
```

```python
@router.get("/candidates", response_model=list[PayableOut])
def list_candidates(
    q: str = Query(default=""),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[PayableOut]:
    """Contas que podem receber o comprovante. Reusa PayableOut para o front não precisar de
    um tipo novo (o cartão mostra descrição, fornecedor, valor, vencimento e is_overdue)."""
    return [payables_service.payable_out(p) for p in receipts.list_candidates(db, q=q)]
```

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py -v`
Expected: PASS (11 testes).

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/payables/receipts.py \
        apps/api/app/modules/payables/receipts_router.py \
        apps/api/tests/test_receipts.py
git commit -m "feat: lista curta de contas candidatas ao comprovante"
```

---

## Task 3: Vincular o comprovante à conta (com baixa opcional)

Precisa de uma versão de `mark_paid` **sem commit**, para que anexo e baixa aconteçam na mesma transação. O repositório já tem esse padrão (`receivables.build_charge` sem commit + `create_charge` como wrapper) — seguimos ele.

**Files:**
- Modify: `apps/api/app/modules/payables/service.py:234-251`
- Modify: `apps/api/app/modules/payables/receipts.py`
- Modify: `apps/api/app/modules/payables/receipts_schemas.py`
- Modify: `apps/api/app/modules/payables/receipts_router.py`
- Modify: `apps/api/tests/test_receipts.py`

**Interfaces:**
- Consumes: `receipts.get_staged`, `payables.service.payable_out`
- Produces:
  - `payables.service.apply_paid(db, *, payable_id, tenant_id, actor) -> Payable` (**sem commit**)
  - `receipts.link_receipt(db, *, attachment_id, user_id, tenant_id, actor, bill_id, mark_paid) -> Payable`
  - `receipts_schemas.ReceiptLinkIn` com campos `bill_id: str`, `mark_paid: bool = True`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `apps/api/tests/test_receipts.py`:

```python
def _link(client: TestClient, headers, rid: str, bill_id: str, mark_paid: bool = True):
    return client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": bill_id, "mark_paid": mark_paid},
        headers=headers,
    )


def test_link_anexa_e_da_baixa(client: TestClient, headers):
    b = _bill(client, headers)
    rid = _upload(client, headers).json()["id"]

    resp = _link(client, headers, rid, b["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"
    assert resp.json()["paid_at"] is not None

    # saiu da bandeja e virou anexo da conta, com o label certo
    assert client.get("/payables/receipts", headers=headers).json() == []
    anexos = client.get(
        f"/attachments?owner_type=payable&owner_id={b['id']}", headers=headers
    ).json()
    assert [a["label"] for a in anexos] == ["comprovante"]


def test_link_sem_mark_paid_nao_muda_status(client: TestClient, headers):
    b = _bill(client, headers)
    rid = _upload(client, headers).json()["id"]
    resp = _link(client, headers, rid, b["id"], mark_paid=False)
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"
    assert resp.json()["paid_at"] is None


def test_link_em_conta_ja_paga_nao_altera_paid_at(client: TestClient, headers):
    b = _bill(client, headers)
    paga = client.post(f"/payables/bills/{b['id']}/pay", headers=headers).json()
    rid = _upload(client, headers).json()["id"]

    resp = _link(client, headers, rid, b["id"], mark_paid=True)
    assert resp.status_code == 200
    assert resp.json()["paid_at"] == paga["paid_at"]  # baixa preservada, não re-datada


def test_link_em_conta_cancelada_falha_e_mantem_na_bandeja(client: TestClient, headers):
    b = _bill(client, headers)
    client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    rid = _upload(client, headers).json()["id"]

    resp = _link(client, headers, rid, b["id"])
    assert resp.status_code == 409
    # nada foi gravado: o comprovante continua na bandeja
    assert [i["id"] for i in client.get("/payables/receipts", headers=headers).json()] == [rid]


def test_link_duas_vezes_da_409(client: TestClient, headers):
    b = _bill(client, headers)
    rid = _upload(client, headers).json()["id"]
    assert _link(client, headers, rid, b["id"]).status_code == 200
    assert _link(client, headers, rid, b["id"]).status_code == 409


def test_link_em_conta_inexistente_da_404(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    assert _link(client, headers, rid, "nao-existe").status_code == 404


def test_mark_paid_continua_funcionando_apos_refactor(client: TestClient, headers):
    """Guarda de regressão do refactor apply_paid/mark_paid: a rota antiga não muda."""
    b = _bill(client, headers)
    paga = client.post(f"/payables/bills/{b['id']}/pay", headers=headers).json()
    assert paga["status"] == "paid" and paga["paid_at"] is not None
    eventos = [
        e for e in client.get("/agenda/events?limit=500", headers=headers).json()
        if e["external_ref"] == b["id"]
    ]
    assert [e["status"] for e in eventos] == ["done"]
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py -k link -v`
Expected: FAIL — `404` na rota `/payables/receipts/{id}/link`.

- [ ] **Step 3: Extrair `apply_paid` de `mark_paid`**

Substituir `mark_paid` em `apps/api/app/modules/payables/service.py` (linhas 234-251) por:

```python
def apply_paid(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    """Dá baixa na conta SEM commitar — reutilizável dentro de outra transação.

    Mesmo padrão de `receivables.build_charge`: a versão sem commit é a real, e a versão
    pública (`mark_paid`) é um wrapper que commita. Assim anexar o comprovante e dar a baixa
    acontecem numa transação só (ver payables/receipts.py::link_receipt).

    Idempotente: conta já paga volta inalterada (não re-data o paid_at).
    """
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    if p.status == STATUS_PAID:
        return p
    if p.status == STATUS_CANCELED:
        raise PayableError("Conta cancelada não pode ser paga", 409)
    p.status = STATUS_PAID
    p.paid_at = datetime.now(UTC)
    if p.agenda_event_id:
        ev = db.get(AgendaEvent, p.agenda_event_id)
        if ev is not None:
            ev.status = STATUS_DONE  # não fica "atrasado" na agenda
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.paid", target=p.id)
    return p


def mark_paid(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    p = apply_paid(db, payable_id=payable_id, tenant_id=tenant_id, actor=actor)
    db.commit()
    db.refresh(p)
    return p
```

- [ ] **Step 4: Rodar a suíte de payables para provar que o refactor não quebrou nada**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_payables.py -v`
Expected: PASS — todos os testes existentes continuam verdes.

- [ ] **Step 5: Implementar `link_receipt`**

Primeiro, acrescentar `STATUS_CANCELED` ao import de models no topo de `apps/api/app/modules/payables/receipts.py` (a Task 2 importou só `STATUS_OPEN`/`STATUS_PAID`/`Payable`, porque `STATUS_CANCELED` ainda não tinha uso e o `ruff` reprova import morto):

```python
from app.modules.payables.models import STATUS_CANCELED, STATUS_OPEN, STATUS_PAID, Payable
```

Depois, acrescentar ao fim do arquivo:

```python
def _attach_and_commit(
    db: Session,
    att: Attachment,
    p: Payable,
    *,
    tenant_id: str,
    actor: str,
    mark_paid: bool,
) -> Payable:
    """Move o anexo da bandeja para a conta e fecha a transação (com baixa, se pedido).

    Extraído porque `link_receipt` (conta existente) e `new_bill_from_receipt` (conta nova)
    terminam exatamente igual — só a origem da conta difere.
    """
    from app.core import audit
    from app.modules.payables import service as payables_service

    att.owner_type = OWNER_PAYABLE
    att.owner_id = p.id
    att.label = LABEL_COMPROVANTE

    # Conta já paga não é re-datada; `apply_paid` não commita, então a baixa e o vínculo
    # caem na MESMA transação.
    if mark_paid and p.status == STATUS_OPEN:
        payables_service.apply_paid(db, payable_id=p.id, tenant_id=tenant_id, actor=actor)

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="payable.receipt_linked", target=p.id
    )
    db.commit()
    db.refresh(p)
    return p


def link_receipt(
    db: Session,
    *,
    attachment_id: str,
    user_id: str,
    tenant_id: str,
    actor: str,
    bill_id: str,
    mark_paid: bool,
) -> Payable:
    """Vincula o comprovante a uma conta existente e, se pedido, dá a baixa.

    Vincular é trocar owner_type/owner_id do Attachment: os bytes ficam onde estão.
    """
    att = get_staged(db, attachment_id=attachment_id, user_id=user_id)

    p = db.get(Payable, bill_id)
    if p is None:
        raise ReceiptError("Conta não encontrada", 404)
    if p.status == STATUS_CANCELED:
        raise ReceiptError("Conta cancelada não recebe comprovante", 409)

    return _attach_and_commit(
        db, att, p, tenant_id=tenant_id, actor=actor, mark_paid=mark_paid
    )
```

- [ ] **Step 6: Adicionar o schema de entrada**

Acrescentar em `apps/api/app/modules/payables/receipts_schemas.py`:

```python
class ReceiptLinkIn(BaseModel):
    bill_id: str
    # Marcado por padrão: quem compartilha o comprovante acabou de pagar. A tela deixa desmarcar.
    mark_paid: bool = True
```

- [ ] **Step 7: Adicionar a rota**

Em `apps/api/app/modules/payables/receipts_router.py`, importar `ReceiptLinkIn` e acrescentar antes de `discard_receipt`:

```python
@router.post("/{attachment_id}/link", response_model=PayableOut)
def link_receipt(
    attachment_id: str,
    data: ReceiptLinkIn,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = receipts.link_receipt(
            db, attachment_id=attachment_id, user_id=user.user_id, tenant_id=user.tenant_id,
            actor=user.user_id, bill_id=data.bill_id, mark_paid=data.mark_paid,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    except payables_service.PayableError as e:
        raise _err(e, e.status_code) from e
    return payables_service.payable_out(p)
```

- [ ] **Step 8: Rodar os testes**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py tests/test_payables.py -v`
Expected: PASS (18 testes de receipts + toda a suíte de payables).

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/modules/payables/service.py \
        apps/api/app/modules/payables/receipts.py \
        apps/api/app/modules/payables/receipts_schemas.py \
        apps/api/app/modules/payables/receipts_router.py \
        apps/api/tests/test_receipts.py
git commit -m "feat: vincular comprovante a conta com baixa no mesmo commit"
```

---

## Task 4: Criar conta nova a partir do comprovante

Mesma técnica da Task 3, agora para `create_payable`.

**Files:**
- Modify: `apps/api/app/modules/payables/service.py:74-139`
- Modify: `apps/api/app/modules/payables/receipts.py`
- Modify: `apps/api/app/modules/payables/receipts_schemas.py`
- Modify: `apps/api/app/modules/payables/receipts_router.py`
- Modify: `apps/api/tests/test_receipts.py`

**Interfaces:**
- Consumes: `payables.schemas.PayableCreate`
- Produces:
  - `payables.service.build_payable(db, *, tenant_id, actor, data) -> Payable` (**sem commit**)
  - `receipts.new_bill_from_receipt(db, *, attachment_id, user_id, tenant_id, actor, data, mark_paid) -> Payable`
  - `receipts_schemas.ReceiptNewBillIn` com `description, category, supplier, amount_cents, due_date, mark_paid`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `apps/api/tests/test_receipts.py`:

```python
def _new_bill_payload(**over):
    base = {
        "description": "Estacionamento",
        "category": "Geral",
        "supplier": "Shopping",
        "amount_cents": 4500,
        "due_date": "2099-05-05",
        "mark_paid": True,
    }
    return {**base, **over}


def test_new_bill_cria_conta_paga_com_o_anexo(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    resp = client.post(
        f"/payables/receipts/{rid}/new-bill", json=_new_bill_payload(), headers=headers
    )
    assert resp.status_code == 201, resp.text
    b = resp.json()
    assert b["description"] == "Estacionamento"
    assert b["status"] == "paid"

    assert client.get("/payables/receipts", headers=headers).json() == []
    anexos = client.get(
        f"/attachments?owner_type=payable&owner_id={b['id']}", headers=headers
    ).json()
    assert [a["label"] for a in anexos] == ["comprovante"]


def test_new_bill_sem_mark_paid_nasce_aberta(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    b = client.post(
        f"/payables/receipts/{rid}/new-bill",
        json=_new_bill_payload(mark_paid=False),
        headers=headers,
    ).json()
    assert b["status"] == "open"


def test_new_bill_injeta_evento_na_agenda(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    b = client.post(
        f"/payables/receipts/{rid}/new-bill", json=_new_bill_payload(), headers=headers
    ).json()
    eventos = [
        e for e in client.get("/agenda/events?limit=500", headers=headers).json()
        if e["external_ref"] == b["id"]
    ]
    assert len(eventos) == 1
    assert eventos[0]["kind"] == "cobranca_pagar"


def test_new_bill_recusa_valor_zero(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    resp = client.post(
        f"/payables/receipts/{rid}/new-bill",
        json=_new_bill_payload(amount_cents=0),
        headers=headers,
    )
    assert resp.status_code == 422  # PayableCreate exige amount_cents > 0


def test_create_bill_continua_funcionando_apos_refactor(client: TestClient, headers):
    """Guarda de regressão do refactor build_payable/create_payable."""
    b = _bill(client, headers, due_date="2099-06-01", recurrence="monthly", recurrence_count=3)
    todas = client.get("/payables/bills", headers=headers).json()
    assert len([x for x in todas if x["recurrence_group"] == b["recurrence_group"]]) == 3
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py -k new_bill -v`
Expected: FAIL — `404` na rota `/payables/receipts/{id}/new-bill`.

- [ ] **Step 3: Extrair `build_payable` de `create_payable`**

Em `apps/api/app/modules/payables/service.py`, renomear a função existente `create_payable` para `build_payable`, remover as duas últimas linhas (`db.commit()` e `db.refresh(first)`), e criar o wrapper. O corpo fica assim (o miolo do laço é idêntico ao atual — só mudam o nome, o docstring e o final):

```python
def build_payable(db: Session, *, tenant_id: str, actor: str, data: PayableCreate) -> Payable:
    """Cria a conta SEM commitar — reutilizável dentro de outra transação (mesmo padrão de
    `receivables.build_charge`). Se recorrente, gera N ocorrências — cada uma com seu
    vencimento e seu evento na Agenda (assim cada repetição pode receber seu próprio boleto).
    """
    # Story 5.2: valida o vínculo opcional ao plano de contas (404 se apontar p/ conta
    # inexistente/de outro tenant — a RLS já esconde a linha cross-tenant).
    if data.chart_account_id and not chart_service.exists(db, data.chart_account_id):
        raise PayableError("Conta do plano de contas não encontrada", 404)
    # Story 5.4: valida o vínculo opcional ao contrato.
    if data.contract_id and not contracts_service.exists(db, data.contract_id):
        raise PayableError("Contrato não encontrado", 404)
    # Story 5.5: valida o vínculo opcional ao centro de custo (2ª dimensão).
    if data.cost_center_id and not cost_centers_service.exists(db, data.cost_center_id):
        raise PayableError("Centro de custo não encontrado", 404)
    n = occurrences(data.recurrence, data.recurrence_count)
    group = _uuid() if n > 1 else None
    title = f"A pagar: {data.supplier or data.description or 'conta'}"
    first: Payable | None = None
    for i in range(n):
        due = advance(data.due_date, data.recurrence, i)
        # competência (regime de competência/DRE): fallback = vencimento da ocorrência quando
        # omitida; se informada, avança em paralelo ao vencimento.
        competence = (
            advance(data.competence_date, data.recurrence, i)
            if data.competence_date is not None
            else due
        )
        payable = Payable(
            tenant_id=tenant_id,
            description=data.description,
            category=data.category,
            supplier=data.supplier,
            amount_cents=data.amount_cents,
            due_date=due,
            competence_date=competence,
            chart_account_id=data.chart_account_id,
            contract_id=data.contract_id,
            cost_center_id=data.cost_center_id,
            recurrence=data.recurrence,
            recurrence_count=n,
            recurrence_group=group,
            # boleto/anexo informados na criação só na 1ª ocorrência
            payment_code=data.payment_code if i == 0 else "",
            attachment_url=data.attachment_url if i == 0 else "",
            status=STATUS_OPEN,
        )
        db.add(payable)
        db.flush()
        day_start = datetime.combine(due, time.min, tzinfo=UTC)
        event = AgendaEvent(
            tenant_id=tenant_id, title=title, kind=KIND_COBRANCA_PAGAR, status=STATUS_SCHEDULED,
            priority=PRIORITY_NORMAL, source="payables", starts_at=day_start,
            ends_at=day_start.replace(hour=23, minute=59), all_day=True,
            amount_cents=data.amount_cents, external_ref=payable.id,
        )
        db.add(event)
        db.flush()
        payable.agenda_event_id = event.id
        if i == 0:
            first = payable

    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.create", target=first.id)
    return first


def create_payable(db: Session, *, tenant_id: str, actor: str, data: PayableCreate) -> Payable:
    p = build_payable(db, tenant_id=tenant_id, actor=actor, data=data)
    db.commit()
    db.refresh(p)
    return p
```

O corpo acima é o `create_payable` atual (linhas 74-139) sem as duas últimas linhas. Nenhum import muda — `chart_service`, `contracts_service`, `cost_centers_service`, `occurrences`, `advance`, `_uuid`, `time`, `AgendaEvent` e as constantes já estão no topo do arquivo.

- [ ] **Step 4: Rodar a suíte de payables para provar que o refactor não quebrou nada**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_payables.py -v`
Expected: PASS.

- [ ] **Step 5: Implementar `new_bill_from_receipt`**

Acrescentar em `apps/api/app/modules/payables/receipts.py`:

```python
def new_bill_from_receipt(
    db: Session,
    *,
    attachment_id: str,
    user_id: str,
    tenant_id: str,
    actor: str,
    data,  # PayableCreate
    mark_paid: bool,
) -> Payable:
    """Cria a conta a partir do comprovante e já vincula o anexo — num commit só.

    Para o caso de ter pago algo que ainda não estava cadastrado no sistema.
    """
    from app.modules.payables import service as payables_service

    att = get_staged(db, attachment_id=attachment_id, user_id=user_id)

    # build_payable não commita: a conta, o evento na Agenda, o vínculo do anexo e a baixa
    # entram todos na mesma transação.
    p = payables_service.build_payable(db, tenant_id=tenant_id, actor=actor, data=data)

    return _attach_and_commit(
        db, att, p, tenant_id=tenant_id, actor=actor, mark_paid=mark_paid
    )
```

A conta recém-criada nasce `STATUS_OPEN`, então a guarda `p.status == STATUS_OPEN` dentro de `_attach_and_commit` deixa a baixa passar normalmente.

- [ ] **Step 6: Adicionar o schema de entrada**

Acrescentar em `apps/api/app/modules/payables/receipts_schemas.py` (importar `date` de `datetime` e `Field` de `pydantic`):

```python
class ReceiptNewBillIn(BaseModel):
    """Formulário curto da tela do celular. Deliberadamente MENOR que PayableCreate: sem
    recorrência, sem classificação DRE, sem centro de custo — quem está no celular com o
    comprovante na mão quer registrar rápido e refinar depois no computador."""

    description: str = ""
    category: str = "Geral"
    supplier: str = ""
    amount_cents: int = Field(gt=0)
    due_date: date
    mark_paid: bool = True
```

- [ ] **Step 7: Adicionar a rota**

Em `apps/api/app/modules/payables/receipts_router.py`, importar `PayableCreate` e `ReceiptNewBillIn`, e acrescentar antes de `discard_receipt`:

```python
@router.post("/{attachment_id}/new-bill", response_model=PayableOut, status_code=201)
def new_bill_from_receipt(
    attachment_id: str,
    data: ReceiptNewBillIn,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    create = PayableCreate(
        description=data.description, category=data.category, supplier=data.supplier,
        amount_cents=data.amount_cents, due_date=data.due_date,
    )
    try:
        p = receipts.new_bill_from_receipt(
            db, attachment_id=attachment_id, user_id=user.user_id, tenant_id=user.tenant_id,
            actor=user.user_id, data=create, mark_paid=data.mark_paid,
        )
    except receipts.ReceiptError as e:
        raise _err(e, e.status_code) from e
    except payables_service.PayableError as e:
        raise _err(e, e.status_code) from e
    return payables_service.payable_out(p)
```

- [ ] **Step 8: Rodar os testes**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py tests/test_payables.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/modules/payables/service.py \
        apps/api/app/modules/payables/receipts.py \
        apps/api/app/modules/payables/receipts_schemas.py \
        apps/api/app/modules/payables/receipts_router.py \
        apps/api/tests/test_receipts.py
git commit -m "feat: criar conta a pagar a partir do comprovante"
```

---

## Task 5: Modelo e migration do token de dispositivo

**Files:**
- Create: `apps/api/app/modules/device_tokens/__init__.py`
- Create: `apps/api/app/modules/device_tokens/models.py`
- Create: `apps/api/app/modules/device_tokens/service.py`
- Create: `apps/api/migrations/versions/0057_device_tokens.py`
- Create: `apps/api/tests/test_device_tokens.py`
- Modify: `apps/api/app/db/registry.py`

**Interfaces:**
- Consumes: `core.security.generate_reset_token`, `core.security.hash_token`, `db.base.Base`, `db.base.TimestampMixin`, `db.base._uuid`
- Produces:
  - `device_tokens.models.DeviceToken` com colunas `id, tenant_id, user_id, name, token_hash, scope, last_used_at, revoked_at`
  - `device_tokens.models.SCOPE_RECEIPT_UPLOAD: str = "receipt_upload"`
  - `device_tokens.service.create_token(db, *, tenant_id, user_id, name) -> tuple[DeviceToken, str]` (token cru é o 2º item)
  - `device_tokens.service.resolve(db, *, raw: str, scope: str) -> DeviceToken` — levanta `DeviceTokenError`
  - `device_tokens.service.list_tokens(db, *, user_id) -> list[DeviceToken]`
  - `device_tokens.service.revoke(db, *, token_id, user_id) -> None`
  - `device_tokens.service.DeviceTokenError(Exception)` com `.status_code`

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_device_tokens.py`:

```python
"""Testes do token de dispositivo (credencial do Atalho do iOS)."""
import pytest
from sqlalchemy.orm import Session

from app.db.registry import Base  # noqa: F401 — garante o registro do modelo novo
from app.modules.device_tokens import service
from app.modules.device_tokens.models import SCOPE_RECEIPT_UPLOAD


@pytest.fixture()
def seeded(db: Session):
    return {"tenant_id": "t-1", "user_id": "u-1"}


def test_create_devolve_token_cru_e_guarda_so_o_hash(db: Session, seeded):
    token, raw = service.create_token(db, name="iPhone", **seeded)
    assert raw and len(raw) > 20
    assert token.token_hash != raw
    assert raw not in token.token_hash
    assert token.scope == SCOPE_RECEIPT_UPLOAD
    assert token.revoked_at is None


def test_resolve_encontra_pelo_token_cru_e_marca_uso(db: Session, seeded):
    _, raw = service.create_token(db, name="iPhone", **seeded)
    found = service.resolve(db, raw=raw, scope=SCOPE_RECEIPT_UPLOAD)
    assert found.user_id == "u-1"
    assert found.tenant_id == "t-1"
    assert found.last_used_at is not None


def test_resolve_recusa_token_desconhecido(db: Session, seeded):
    with pytest.raises(service.DeviceTokenError) as e:
        service.resolve(db, raw="nao-existe", scope=SCOPE_RECEIPT_UPLOAD)
    assert e.value.status_code == 401


def test_resolve_recusa_token_revogado(db: Session, seeded):
    token, raw = service.create_token(db, name="iPhone", **seeded)
    service.revoke(db, token_id=token.id, user_id="u-1")
    with pytest.raises(service.DeviceTokenError) as e:
        service.resolve(db, raw=raw, scope=SCOPE_RECEIPT_UPLOAD)
    assert e.value.status_code == 401


def test_resolve_recusa_escopo_diferente(db: Session, seeded):
    _, raw = service.create_token(db, name="iPhone", **seeded)
    with pytest.raises(service.DeviceTokenError) as e:
        service.resolve(db, raw=raw, scope="outro_escopo")
    assert e.value.status_code == 403


def test_revoke_de_outro_usuario_da_404(db: Session, seeded):
    token, _ = service.create_token(db, name="iPhone", **seeded)
    with pytest.raises(service.DeviceTokenError) as e:
        service.revoke(db, token_id=token.id, user_id="u-outro")
    assert e.value.status_code == 404


def test_list_traz_so_os_do_proprio_usuario(db: Session, seeded):
    service.create_token(db, name="iPhone", **seeded)
    service.create_token(db, tenant_id="t-1", user_id="u-2", name="Android")
    assert [t.name for t in service.list_tokens(db, user_id="u-1")] == ["iPhone"]


def test_list_omite_revogados(db: Session, seeded):
    token, _ = service.create_token(db, name="iPhone", **seeded)
    service.revoke(db, token_id=token.id, user_id="u-1")
    assert service.list_tokens(db, user_id="u-1") == []
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_device_tokens.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'app.modules.device_tokens'`.

- [ ] **Step 3: Criar o modelo**

Criar `apps/api/app/modules/device_tokens/__init__.py` (vazio) e `apps/api/app/modules/device_tokens/models.py`:

```python
"""Token de dispositivo: credencial de escopo único para o Atalho do iOS.

Tabela GLOBAL (sem `TenantMixin`, sem RLS) pela MESMA razão que `users` é: o tenant precisa
ser resolvido A PARTIR do token, antes de existir uma `tenant_session` para consultar. Guarda
apenas hash e metadado de credencial — nenhum dado de negócio. Vale aqui a mesma regra já
registrada no CLAUDE.md para `users`: nenhum módulo de negócio consulta esta tabela.

O desenho assume que o token VAI vazar um dia (ele vive em texto claro dentro do atalho, no
aparelho). Por isso o `scope` é travado: ele só autoriza `POST /payables/receipts`, uma
escrita que não devolve nenhum dado. Ver `app/core/receipt_auth.py`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, _uuid

# Único escopo existente. Autoriza SOMENTE o upload do comprovante para a bandeja.
SCOPE_RECEIPT_UPLOAD = "receipt_upload"


class DeviceToken(Base, TimestampMixin):
    __tablename__ = "device_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # tenant_id é coluna simples de resolução (não controla acesso por RLS — a tabela é global).
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # sha256 do token cru. O cru NUNCA é persistido — mesmo padrão do reset de senha.
    token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default=SCOPE_RECEIPT_UPLOAD)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Criar o serviço**

Criar `apps/api/app/modules/device_tokens/service.py`:

```python
"""Ciclo de vida do token de dispositivo: criar, resolver, listar, revogar."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_reset_token, hash_token
from app.modules.device_tokens.models import SCOPE_RECEIPT_UPLOAD, DeviceToken


class DeviceTokenError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def create_token(
    db: Session, *, tenant_id: str, user_id: str, name: str
) -> tuple[DeviceToken, str]:
    """Cria o token e devolve (linha, token_cru). O cru é mostrado UMA vez e nunca mais."""
    raw, hashed = generate_reset_token()  # reusa o par sha256 já validado do reset de senha
    token = DeviceToken(
        tenant_id=tenant_id, user_id=user_id, name=name.strip() or "Dispositivo",
        token_hash=hashed, scope=SCOPE_RECEIPT_UPLOAD,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw


def resolve(db: Session, *, raw: str, scope: str) -> DeviceToken:
    """Resolve o token cru. Fail-closed: qualquer dúvida vira 401/403, nunca acesso.

    Marca `last_used_at` para a tela de gerenciamento mostrar dispositivos abandonados.
    """
    token = db.scalar(select(DeviceToken).where(DeviceToken.token_hash == hash_token(raw)))
    if token is None or token.revoked_at is not None:
        raise DeviceTokenError("Token de dispositivo inválido", 401)
    if token.scope != scope:
        raise DeviceTokenError("Token sem permissão para esta operação", 403)
    token.last_used_at = datetime.now(UTC)
    db.commit()
    return token


def list_tokens(db: Session, *, user_id: str) -> list[DeviceToken]:
    stmt = (
        select(DeviceToken)
        .where(DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
        .order_by(DeviceToken.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def revoke(db: Session, *, token_id: str, user_id: str) -> None:
    token = db.get(DeviceToken, token_id)
    if token is None or token.user_id != user_id:
        raise DeviceTokenError("Token não encontrado", 404)
    token.revoked_at = datetime.now(UTC)
    db.commit()
```

- [ ] **Step 5: Registrar o modelo**

Em `apps/api/app/db/registry.py`, adicionar em ordem alfabética — logo **depois** de `crm` e antes de `funnels`:

```python
from app.modules.device_tokens.models import DeviceToken  # noqa: F401
```

- [ ] **Step 6: Criar a migration**

Criar `apps/api/migrations/versions/0057_device_tokens.py`:

```python
"""device_tokens: credencial de escopo único para o Atalho do iOS

Revision ID: 0057
Revises: 0056
Create Date: 2026-07-28

Tabela GLOBAL, deliberadamente SEM RLS: o tenant é resolvido A PARTIR do token (o cliente não
tem sessão), então nenhuma `tenant_session` existe no momento do lookup — mesma situação de
`users` e `public_whatsapp_accounts`. Guarda só hash de credencial e metadado.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="receipt_upload"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_device_tokens_tenant_id", "device_tokens", ["tenant_id"])
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    # Índice do lookup por hash (caminho quente de toda requisição do atalho).
    op.create_index("ix_device_tokens_token_hash", "device_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_table("device_tokens")
```

- [ ] **Step 7: Rodar os testes**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_device_tokens.py -v`
Expected: PASS (8 testes).

- [ ] **Step 8: Verificar a migration contra o Postgres real**

```bash
docker start infra-postgres-1 infra-api-1
docker compose --env-file .env -f infra/docker-compose.yml build api
docker compose --env-file .env -f infra/docker-compose.yml up -d api
docker logs infra-api-1 --tail 40
```
Expected: `alembic upgrade head` chega em `0057` sem erro; `/health` responde.

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/modules/device_tokens/ \
        apps/api/migrations/versions/0057_device_tokens.py \
        apps/api/app/db/registry.py \
        apps/api/tests/test_device_tokens.py
git commit -m "feat: token de dispositivo com escopo unico (migration 0057)"
```

---

## Task 6: Autenticar o upload por JWT **ou** token de dispositivo

**Files:**
- Create: `apps/api/app/core/receipt_auth.py`
- Modify: `apps/api/app/modules/payables/receipts_router.py`
- Modify: `apps/api/tests/conftest.py`
- Modify: `apps/api/tests/test_receipts.py`

**Interfaces:**
- Consumes: `device_tokens.service.resolve`, `core.tenancy.CurrentUser`, `core.tenancy.get_current_user`, `db.session.tenant_session`, `db.session.get_db`
- Produces:
  - `receipt_auth.receipt_uploader(...) -> CurrentUser`
  - `receipt_auth.get_receipt_db(...) -> Iterator[Session]`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `apps/api/tests/test_receipts.py`:

Acrescentar o import no topo do arquivo:

```python
from sqlalchemy.orm import Session
```

E os testes:

```python
def _device_token(db: Session, headers) -> tuple[str, str, str]:
    """Cria um token de dispositivo direto pelo serviço (a rota HTTP só vem na Task 7).

    Usa a fixture `db` — a MESMA sessão SQLite que a fixture `client` usa — em vez de abrir
    outra: o token precisa estar visível para a requisição que virá logo em seguida.

    Devolve (token_cru, user_id, tenant_id).
    """
    from app.modules.auth.models import User
    from app.modules.device_tokens import service as dt_service

    user = db.query(User).filter(User.email == REGISTER["email"]).one()
    _, raw = dt_service.create_token(
        db, tenant_id=user.tenant_id, user_id=user.id, name="iPhone de teste"
    )
    return raw, user.id, user.tenant_id


def test_upload_aceita_token_de_dispositivo(client: TestClient, db: Session, headers):
    raw, _, _ = _device_token(db, headers)
    resp = client.post(
        "/payables/receipts",
        files={"file": ("comp.png", PNG, "image/png")},
        headers={"X-E1P-Device-Token": raw},
    )
    assert resp.status_code == 201, resp.text
    # o arquivo caiu na bandeja do MESMO usuário, visível pela sessão web
    assert [i["id"] for i in client.get("/payables/receipts", headers=headers).json()] == [
        resp.json()["id"]
    ]


def test_upload_recusa_token_de_dispositivo_invalido(client: TestClient):
    resp = client.post(
        "/payables/receipts",
        files={"file": ("comp.png", PNG, "image/png")},
        headers={"X-E1P-Device-Token": "token-que-nao-existe"},
    )
    assert resp.status_code == 401


def test_upload_sem_credencial_nenhuma_da_401(client: TestClient):
    resp = client.post("/payables/receipts", files={"file": ("comp.png", PNG, "image/png")})
    assert resp.status_code == 401


def test_token_de_dispositivo_escreve_sempre_no_tenant_do_proprio_token(
    client: TestClient, db: Session, headers
):
    """O tenant_id do anexo vem do TOKEN, nunca do corpo da requisição — por isso um token de
    A não consegue escrever em B, mesmo forjando parâmetros. (O outro lado do isolamento — a
    LEITURA cross-tenant no `link` — depende de RLS e só é validável no Postgres: ver
    docs/CHECKLIST-COMPROVANTE-MOBILE.md.)"""
    from app.modules.attachments.models import Attachment

    raw, user_id, tenant_id = _device_token(db, headers)
    rid = client.post(
        "/payables/receipts",
        files={"file": ("comp.png", PNG, "image/png")},
        headers={"X-E1P-Device-Token": raw},
    ).json()["id"]

    att = db.get(Attachment, rid)
    assert att.tenant_id == tenant_id
    assert att.owner_id == user_id


def test_link_continua_exigindo_sessao_web(client: TestClient, db: Session, headers):
    """O token de dispositivo NÃO autoriza vincular — escopo travado no upload."""
    b = _bill(client, headers)
    raw, _, _ = _device_token(db, headers)
    rid = _upload(client, headers).json()["id"]
    resp = client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": b["id"], "mark_paid": True},
        headers={"X-E1P-Device-Token": raw},
    )
    assert resp.status_code == 401  # link exige Bearer, não conhece o header do dispositivo
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py -k device -v`
Expected: FAIL — o upload com `X-E1P-Device-Token` devolve `401` "Token ausente" (a rota só conhece Bearer).

- [ ] **Step 3: Criar a dependency**

Criar `apps/api/app/core/receipt_auth.py`:

```python
"""Autenticação do upload de comprovante: JWT (web/Android) OU token de dispositivo (iOS).

Duas portas de entrada, uma identidade. O resto do código recebe um `CurrentUser` normal e
não sabe qual credencial foi usada.

O token de dispositivo é DELIBERADAMENTE limitado a este único endpoint de escrita: ele vive
em texto claro dentro do Atalho, no aparelho, então o desenho assume vazamento. O pior caso é
alguém depositar arquivos na bandeja do dono — que ele vê e descarta. Nenhum dado sai.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.core.tenancy import CurrentUser
from app.db.session import get_db, tenant_session
from app.modules.device_tokens import service as device_tokens_service
from app.modules.device_tokens.models import SCOPE_RECEIPT_UPLOAD
from app.modules.device_tokens.service import DeviceTokenError


def receipt_uploader(
    authorization: str | None = Header(default=None),
    x_e1p_device_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Aceita `Authorization: Bearer <jwt>` OU `X-E1P-Device-Token: <raw>`.

    O JWT tem precedência: se a pessoa está logada no PWA, é a sessão dela que vale.
    """
    if authorization and authorization.lower().startswith("bearer "):
        payload = decode_access_token(authorization.split(" ", 1)[1])
        if not payload or "sub" not in payload or "tenant_id" not in payload:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
        return CurrentUser(
            user_id=payload["sub"],
            tenant_id=payload["tenant_id"],
            role=payload.get("role", "owner"),
            allowed_modules=payload.get("allowed_modules", []),
            is_platform_admin=bool(payload.get("is_platform_admin", False)),
        )

    if x_e1p_device_token:
        # Lookup pela sessão SEM tenant (`get_db`): `device_tokens` é global por design — o
        # tenant só é conhecido DEPOIS de resolver o token. Mesmo uso legítimo de `get_db` que
        # o login faz sobre `users`. Injetado por Depends (e não via SessionLocal direto) para
        # que os testes possam apontá-lo ao SQLite, como já fazem com o resto.
        try:
            token = device_tokens_service.resolve(
                db, raw=x_e1p_device_token, scope=SCOPE_RECEIPT_UPLOAD
            )
        except DeviceTokenError as e:
            raise HTTPException(e.status_code, str(e)) from e
        return CurrentUser(
            user_id=token.user_id,
            tenant_id=token.tenant_id,
            # O token não carrega papel/módulos; damos o mínimo viável para a rota de upload,
            # que não consulta RBAC além do módulo 'payables'.
            role="owner",
            allowed_modules=[],
        )

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credencial ausente")


def get_receipt_db(user: CurrentUser = Depends(receipt_uploader)) -> Iterator[Session]:
    """Sessão com RLS fixada no tenant resolvido pela credencial (JWT ou dispositivo)."""
    with tenant_session(user.tenant_id) as db:
        yield db
```

- [ ] **Step 4: Trocar a dependency da rota de upload**

Em `apps/api/app/modules/payables/receipts_router.py`, importar:

```python
from app.core.receipt_auth import get_receipt_db, receipt_uploader
```

E alterar **apenas** a assinatura de `upload_receipt` (as demais rotas continuam com `_guard`/`get_tenant_db` — é isso que trava o escopo do token):

```python
async def upload_receipt(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(receipt_uploader),
    db: Session = Depends(get_receipt_db),
) -> ReceiptOut:
```

- [ ] **Step 5: Adicionar o override no conftest**

Em `apps/api/tests/conftest.py`, importar e sobrescrever a sessão nova (senão a rota abriria conexão Postgres real):

```python
from app.core.receipt_auth import get_receipt_db
```

E, junto dos outros overrides dentro da fixture `client`:

```python
    # get_receipt_db também abre tenant_session (Postgres) — em teste, aponta para o SQLite
    # compartilhado, igual get_tenant_db. A resolução da CREDENCIAL (receipt_uploader) NÃO é
    # sobrescrita: é justamente o que os testes de token de dispositivo exercitam.
    app.dependency_overrides[get_receipt_db] = _override_get_db
```

- [ ] **Step 6: Rodar os testes**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_receipts.py tests/test_device_tokens.py -v`
Expected: PASS.

- [ ] **Step 7: Rodar a suíte inteira (o conftest mudou)**

Run: `cd apps/api && source .venv/bin/activate && pytest`
Expected: PASS — nenhuma regressão.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/core/receipt_auth.py \
        apps/api/app/modules/payables/receipts_router.py \
        apps/api/tests/conftest.py \
        apps/api/tests/test_receipts.py
git commit -m "feat: upload de comprovante aceita token de dispositivo (iOS)"
```

---

## Task 7: Rotas de gerenciamento dos tokens

**Files:**
- Create: `apps/api/app/modules/device_tokens/router.py`
- Create: `apps/api/app/modules/device_tokens/schemas.py`
- Modify: `apps/api/app/modules/__init__.py`
- Modify: `apps/api/tests/test_device_tokens.py`

**Interfaces:**
- Consumes: `device_tokens.service.*`, `core.tenancy.get_current_user`, `db.session.get_db`
- Produces:
  - `device_tokens.schemas.DeviceTokenOut` — `id, name, created_at, last_used_at`
  - `device_tokens.schemas.DeviceTokenCreated` — `id, name, token` (cru, uma vez só)
  - `device_tokens.schemas.DeviceTokenCreate` — `name: str`

- [ ] **Step 1: Escrever os testes que falham**

Mover o import novo para o topo de `apps/api/tests/test_device_tokens.py` (junto dos demais):

```python
from fastapi.testclient import TestClient
```

E acrescentar ao fim do arquivo:

```python
REGISTER = {
    "legal_name": "Token Co",
    "document": "30303030000199",
    "slug": "tokenco",
    "email": "token@example.com",
    "name": "Token",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_criar_token_mostra_o_cru_uma_vez(client: TestClient, headers):
    resp = client.post("/settings/device-tokens", json={"name": "iPhone"}, headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "iPhone"
    assert len(body["token"]) > 20

    # a listagem NUNCA devolve o token cru
    listagem = client.get("/settings/device-tokens", headers=headers).json()
    assert [t["name"] for t in listagem] == ["iPhone"]
    assert "token" not in listagem[0]


def test_revogar_some_da_listagem(client: TestClient, headers):
    tid = client.post(
        "/settings/device-tokens", json={"name": "iPhone"}, headers=headers
    ).json()["id"]
    assert client.delete(f"/settings/device-tokens/{tid}", headers=headers).status_code == 204
    assert client.get("/settings/device-tokens", headers=headers).json() == []


def test_rotas_exigem_login(client: TestClient):
    assert client.get("/settings/device-tokens").status_code == 401
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_device_tokens.py -k "criar_token or revogar or exigem" -v`
Expected: FAIL — `404` nas rotas.

- [ ] **Step 3: Criar os schemas**

Criar `apps/api/app/modules/device_tokens/schemas.py`:

```python
"""Schemas do token de dispositivo."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DeviceTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DeviceTokenOut(BaseModel):
    """Listagem — NUNCA carrega o token cru."""

    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None


class DeviceTokenCreated(BaseModel):
    """Resposta da criação — única vez em que o token cru sai do servidor."""

    id: str
    name: str
    token: str
```

- [ ] **Step 4: Criar o router**

Criar `apps/api/app/modules/device_tokens/router.py`:

```python
"""Rotas de gerenciamento dos tokens de dispositivo (`/settings/device-tokens`).

Usa `get_db` (sem tenant) de propósito: `device_tokens` é uma tabela GLOBAL sem RLS. O
isolamento aqui vem do filtro explícito por `user_id` vindo do JWT — não há acesso a nenhuma
tabela de negócio nestas rotas.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_current_user
from app.db.session import get_db
from app.modules.device_tokens import service
from app.modules.device_tokens.schemas import (
    DeviceTokenCreate,
    DeviceTokenCreated,
    DeviceTokenOut,
)

router = APIRouter(prefix="/settings/device-tokens", tags=["device-tokens"])


@router.get("", response_model=list[DeviceTokenOut])
def list_tokens(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeviceTokenOut]:
    return [
        DeviceTokenOut(
            id=t.id, name=t.name, created_at=t.created_at, last_used_at=t.last_used_at
        )
        for t in service.list_tokens(db, user_id=user.user_id)
    ]


@router.post("", response_model=DeviceTokenCreated, status_code=201)
def create_token(
    data: DeviceTokenCreate,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeviceTokenCreated:
    token, raw = service.create_token(
        db, tenant_id=user.tenant_id, user_id=user.user_id, name=data.name
    )
    return DeviceTokenCreated(id=token.id, name=token.name, token=raw)


@router.delete("/{token_id}", status_code=204)
def revoke_token(
    token_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    try:
        service.revoke(db, token_id=token_id, user_id=user.user_id)
    except service.DeviceTokenError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return Response(status_code=204)
```

- [ ] **Step 5: Registrar o router**

Em `apps/api/app/modules/__init__.py`, adicionar o import (ordem alfabética, depois de `crm_router`):

```python
from app.modules.device_tokens.router import router as device_tokens_router
```

E, na seção de includes:

```python
api_router.include_router(device_tokens_router)
```

- [ ] **Step 6: Rodar os testes**

Run: `cd apps/api && source .venv/bin/activate && pytest tests/test_device_tokens.py -v`
Expected: PASS (11 testes).

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/device_tokens/router.py \
        apps/api/app/modules/device_tokens/schemas.py \
        apps/api/app/modules/__init__.py \
        apps/api/tests/test_device_tokens.py
git commit -m "feat: rotas de gerenciamento dos tokens de dispositivo"
```

---

## Task 8: PWA — manifest, service worker e helper de IndexedDB

**Files:**
- Create: `apps/web/public/manifest.webmanifest`
- Create: `apps/web/public/sw.js`
- Create: `apps/web/public/icon-192.png`, `apps/web/public/icon-512.png`
- Create: `apps/web/src/lib/shareInbox.ts`
- Create: `apps/web/src/lib/shareInbox.test.ts`
- Modify: `apps/web/index.html`
- Modify: `apps/web/src/main.tsx`
- Modify: `apps/web/nginx.conf`
- Modify: `apps/web/package.json`

**Interfaces:**
- Produces:
  - `shareInbox.SHARE_DB_NAME: string = "e1p-share"`
  - `shareInbox.SHARE_STORE: string = "files"`
  - `shareInbox.takeSharedFile(key: string): Promise<File | null>` — lê e **apaga** a chave

- [ ] **Step 1: Instalar a dependência de teste**

```bash
cd apps/web && pnpm add -D fake-indexeddb
```
Expected: `fake-indexeddb` aparece em `devDependencies` no `package.json`.

- [ ] **Step 2: Escrever o teste que falha**

Criar `apps/web/src/lib/shareInbox.test.ts`:

```ts
import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import { SHARE_DB_NAME, SHARE_STORE, takeSharedFile } from "./shareInbox";

/** Grava direto no IndexedDB, imitando o que o service worker faz no POST do share target. */
async function seed(key: string, file: File): Promise<void> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(SHARE_DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(SHARE_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(SHARE_STORE, "readwrite");
    tx.objectStore(SHARE_STORE).put(file, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

describe("shareInbox", () => {
  it("devolve o arquivo gravado e apaga a chave depois de ler", async () => {
    const file = new File(["conteudo"], "comprovante.pdf", { type: "application/pdf" });
    await seed("k1", file);

    const lido = await takeSharedFile("k1");
    expect(lido?.name).toBe("comprovante.pdf");
    expect(lido?.type).toBe("application/pdf");

    // consumo único: a segunda leitura não encontra mais nada
    expect(await takeSharedFile("k1")).toBeNull();
  });

  it("devolve null para chave inexistente em vez de lançar", async () => {
    expect(await takeSharedFile("nao-existe")).toBeNull();
  });
});
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `cd apps/web && pnpm vitest run src/lib/shareInbox.test.ts`
Expected: FAIL — `Failed to resolve import "./shareInbox"`.

- [ ] **Step 4: Criar o helper**

Criar `apps/web/src/lib/shareInbox.ts`:

```ts
/**
 * Ponte entre o service worker e o app para o Web Share Target.
 *
 * O SW recebe o POST do share sheet do Android e guarda o arquivo aqui sob uma chave
 * aleatória; a rota /compartilhar lê e apaga. O IndexedDB é o único canal possível: o SW não
 * pode entregar um File por query string nem por postMessage confiável durante o redirect.
 *
 * Mantenha DB_NAME/STORE em sincronia com public/sw.js — são o mesmo banco.
 */
export const SHARE_DB_NAME = "e1p-share";
export const SHARE_STORE = "files";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(SHARE_DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(SHARE_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Lê o arquivo compartilhado e REMOVE a chave (consumo único). null se não existir. */
export async function takeSharedFile(key: string): Promise<File | null> {
  let db: IDBDatabase;
  try {
    db = await openDb();
  } catch {
    return null;
  }
  try {
    const file = await new Promise<File | null>((resolve, reject) => {
      const tx = db.transaction(SHARE_STORE, "readonly");
      const req = tx.objectStore(SHARE_STORE).get(key);
      req.onsuccess = () => resolve((req.result as File) ?? null);
      req.onerror = () => reject(req.error);
    });
    if (file) {
      await new Promise<void>((resolve) => {
        const tx = db.transaction(SHARE_STORE, "readwrite");
        tx.objectStore(SHARE_STORE).delete(key);
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve(); // apagar é best-effort; o arquivo já foi entregue
      });
    }
    return file;
  } finally {
    db.close();
  }
}
```

- [ ] **Step 5: Rodar o teste**

Run: `cd apps/web && pnpm vitest run src/lib/shareInbox.test.ts`
Expected: PASS (2 testes).

- [ ] **Step 6: Criar o manifest**

Criar `apps/web/public/manifest.webmanifest`:

```json
{
  "name": "e1p — Empresa de 1 Pessoa",
  "short_name": "e1p",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#5D44F8",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
  ],
  "share_target": {
    "action": "/compartilhar",
    "method": "POST",
    "enctype": "multipart/form-data",
    "params": {
      "files": [
        {
          "name": "file",
          "accept": ["image/jpeg", "image/png", "application/pdf"]
        }
      ]
    }
  }
}
```

- [ ] **Step 7: Criar os ícones**

Gerar `apps/web/public/icon-192.png` e `apps/web/public/icon-512.png`: fundo sólido `#5D44F8`, o "e1p" em branco centralizado, com ~20% de margem em volta (exigência do formato *maskable* — o Android recorta as bordas em círculo).

```bash
cd apps/web/public
python3 - <<'PY'
from PIL import Image, ImageDraw, ImageFont
for size in (192, 512):
    img = Image.new("RGB", (size, size), "#5D44F8")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(size * 0.32))
    except OSError:
        font = ImageFont.load_default()
    text = "e1p"
    box = d.textbbox((0, 0), text, font=font)
    d.text(
        ((size - box[2] + box[0]) / 2, (size - box[3] + box[1]) / 2),
        text, fill="white", font=font,
    )
    img.save(f"icon-{size}.png")
PY
```
Expected: os dois PNGs existem. Se `Pillow` não estiver disponível, produza os ícones por qualquer outro meio — o requisito é só serem PNG quadrados de 192 e 512 com margem de segurança.

- [ ] **Step 8: Criar o service worker**

Criar `apps/web/public/sw.js`:

```js
/**
 * Service worker MÍNIMO — existe por um motivo só: o share sheet do Android entrega o
 * arquivo via POST, e uma SPA não tem como receber um POST sem interceptá-lo aqui.
 *
 * NÃO faz cache de NADA. Sem precache, sem runtime caching, sem Workbox. Isso elimina por
 * construção a classe de bugs "deploy novo no ar, mas o celular mostra a versão velha" —
 * o principal risco de introduzir PWA num app servido estaticamente por nginx.
 *
 * DB_NAME/STORE devem casar com src/lib/shareInbox.ts.
 */
const DB_NAME = "e1p-share";
const STORE = "files";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function put(key, file) {
  const db = await openDb();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readwrite");
      tx.objectStore(STORE).put(file, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Só o POST do share target é interceptado. Todo o resto vai direto à rede.
  if (event.request.method !== "POST" || url.pathname !== "/compartilhar") return;

  event.respondWith(
    (async () => {
      try {
        const form = await event.request.formData();
        const file = form.get("file");
        if (!file) return Response.redirect("/compartilhar?erro=sem-arquivo", 303);
        const key = crypto.randomUUID();
        await put(key, file);
        return Response.redirect(`/compartilhar?k=${key}`, 303);
      } catch {
        return Response.redirect("/compartilhar?erro=falha", 303);
      }
    })(),
  );
});
```

- [ ] **Step 9: Ligar o manifest no HTML**

Em `apps/web/index.html`, dentro do `<head>`:

```html
    <link rel="manifest" href="/manifest.webmanifest" />
    <meta name="theme-color" content="#5D44F8" />
```

- [ ] **Step 10: Registrar o service worker**

Em `apps/web/src/main.tsx`, acrescentar antes do `ReactDOM.createRoot(...)`:

```tsx
// PWA: registra o service worker que recebe o POST do Web Share Target (Android).
// Ele não faz cache — ver public/sw.js. Falha silenciosa: navegador sem suporte
// (ou http sem TLS) apenas não vira destino de compartilhamento, o app segue normal.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
```

- [ ] **Step 11: Corrigir o cache do nginx**

`apps/web/nginx.conf` hoje casa `*.js` com `expires 30d; Cache-Control: immutable` — isso **congelaria o service worker por 30 dias** no aparelho. Substituir o arquivo inteiro por:

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Nginx não conhece o MIME do manifest por padrão.
    types {
        application/manifest+json  webmanifest;
    }

    # O service worker NUNCA pode ser cacheado: `location =` (match exato) tem precedência
    # sobre o regex de estáticos abaixo, senão o SW ficaria 30 dias congelado no aparelho.
    location = /sw.js {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        expires -1;
    }

    location = /manifest.webmanifest {
        add_header Cache-Control "no-cache";
        expires -1;
    }

    # SPA: todas as rotas caem no index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API é servida separadamente (proxy/ALB em prod); aqui só o estático.
    location ~* \.(js|css|png|jpg|jpeg|svg|woff2?)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

- [ ] **Step 12: Verificar o build e a suíte**

```bash
cd apps/web && pnpm build && pnpm test
```
Expected: build sem erro de tipos; todos os testes verdes. Conferir que `dist/sw.js`, `dist/manifest.webmanifest`, `dist/icon-192.png` e `dist/icon-512.png` existem.

- [ ] **Step 13: Commit**

```bash
git add apps/web/public/ apps/web/index.html apps/web/src/main.tsx \
        apps/web/src/lib/shareInbox.ts apps/web/src/lib/shareInbox.test.ts \
        apps/web/nginx.conf apps/web/package.json pnpm-lock.yaml
git commit -m "feat: PWA instalavel com share target (service worker sem cache)"
```

---

## Task 9: Rota de trânsito `/compartilhar`

**Files:**
- Create: `apps/web/src/features/pagar/CompartilharPage.tsx`
- Create: `apps/web/src/features/pagar/CompartilharPage.test.tsx`
- Modify: `apps/web/src/app/App.tsx`

**Interfaces:**
- Consumes: `shareInbox.takeSharedFile`, `lib/api.api`
- Produces: componente default `CompartilharPage`

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/web/src/features/pagar/CompartilharPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { takeSharedFile } from "../../lib/shareInbox";
import CompartilharPage from "./CompartilharPage";

vi.mock("../../lib/api", () => ({
  api: { post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));
vi.mock("../../lib/shareInbox", () => ({ takeSharedFile: vi.fn() }));

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/compartilhar" element={<CompartilharPage />} />
        <Route path="/comprovante/:id" element={<p>tela do comprovante</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CompartilharPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sobe o arquivo compartilhado e vai para a tela de vinculacao", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockResolvedValue({ data: { id: "r-1" } } as never);

    renderAt("/compartilhar?k=abc");

    await waitFor(() => screen.getByText("tela do comprovante"));
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/payables/receipts");
  });

  it("mostra recado tratado quando a chave nao existe mais", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(null);
    renderAt("/compartilhar?k=perdida");
    await waitFor(() => screen.getByText(/não encontramos o arquivo/i));
    expect(screen.getByRole("link", { name: /contas a pagar/i })).toBeTruthy();
  });

  it("mostra recado quando o service worker sinaliza erro", async () => {
    renderAt("/compartilhar?erro=falha");
    await waitFor(() => screen.getByText(/não conseguimos receber/i));
    expect(vi.mocked(takeSharedFile)).not.toHaveBeenCalled();
  });

  it("mostra o erro da API sem tela em branco quando o upload falha", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockRejectedValue(new Error("413"));
    renderAt("/compartilhar?k=abc");
    await waitFor(() => screen.getByText(/413/));
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/web && pnpm vitest run src/features/pagar/CompartilharPage.test.tsx`
Expected: FAIL — `Failed to resolve import "./CompartilharPage"`.

- [ ] **Step 3: Implementar a tela**

Criar `apps/web/src/features/pagar/CompartilharPage.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import { takeSharedFile } from "../../lib/shareInbox";

/**
 * Rota de trânsito do Web Share Target. Sem UI própria além do spinner: o service worker
 * redireciona para cá com `?k=<chave>`, nós pegamos o arquivo do IndexedDB, subimos para a
 * bandeja e seguimos para a tela de vinculação.
 *
 * Os dois caminhos de erro são tratados explicitamente — chave perdida (recarregou a página)
 * e falha do SW — porque a alternativa é uma tela em branco logo depois de um compartilhamento,
 * que parece bug do app.
 */
export default function CompartilharPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const key = params.get("k");
  const swError = params.get("erro");

  useEffect(() => {
    if (started.current) return; // StrictMode monta duas vezes; o consumo da chave é único
    started.current = true;

    if (swError) {
      setError("Não conseguimos receber o arquivo compartilhado. Tente de novo.");
      return;
    }
    if (!key) {
      setError("Não encontramos o arquivo compartilhado.");
      return;
    }

    (async () => {
      const file = await takeSharedFile(key);
      if (!file) {
        setError("Não encontramos o arquivo compartilhado. Ele pode já ter sido enviado.");
        return;
      }
      try {
        const fd = new FormData();
        fd.append("file", file);
        const { data } = await api.post<{ id: string }>("/payables/receipts", fd, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        navigate(`/comprovante/${data.id}`, { replace: true });
      } catch (err) {
        setError(apiErrorMessage(err));
      }
    })();
  }, [key, swError, navigate]);

  if (error) {
    return (
      <div className="mx-auto max-w-md space-y-3 p-6 text-center">
        <p className="text-sm text-neutral-600">{error}</p>
        <Link to="/pagar" className="inline-block text-sm font-semibold text-primary-600">
          Ir para Contas a pagar
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-64 items-center justify-center text-sm text-neutral-500">
      Enviando comprovante...
    </div>
  );
}
```

- [ ] **Step 4: Registrar a rota**

Em `apps/web/src/app/App.tsx`, importar e adicionar dentro de `<Route element={<ProtectedLayout />}>`, logo depois da linha do `/pagar`:

```tsx
import CompartilharPage from "../features/pagar/CompartilharPage";
```

```tsx
          <Route path="/compartilhar" element={<CompartilharPage />} />
```

Ficar dentro do `ProtectedLayout` é o que dá, de graça, o comportamento de "não logado → login e volta": o `ProtectedLayout` já redireciona para `/login`, e o arquivo continua guardado no IndexedDB sob a mesma chave até a volta.

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/web && pnpm vitest run src/features/pagar/CompartilharPage.test.tsx`
Expected: PASS (4 testes).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/pagar/CompartilharPage.tsx \
        apps/web/src/features/pagar/CompartilharPage.test.tsx \
        apps/web/src/app/App.tsx
git commit -m "feat: rota /compartilhar recebe o arquivo do share target"
```

---

## Task 10: Tela `/comprovante/:id`

**Files:**
- Create: `apps/web/src/features/pagar/ComprovantePage.tsx`
- Create: `apps/web/src/features/pagar/ComprovantePage.test.tsx`
- Modify: `apps/web/src/app/App.tsx`

**Interfaces:**
- Consumes: `lib/api.api`, tipo `Payable` de `@e1p/shared-types`
- Produces: componente default `ComprovantePage`

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/web/src/features/pagar/ComprovantePage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ComprovantePage from "./ComprovantePage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

const ABERTA = {
  id: "b-aberta", description: "Energia", supplier: "Copel", amount_cents: 30000,
  due_date: "2099-01-10", status: "open", is_overdue: false, paid_at: null,
};
const PAGA = {
  id: "b-paga", description: "Internet", supplier: "Vivo", amount_cents: 12000,
  due_date: "2099-01-05", status: "paid", is_overdue: false, paid_at: "2026-07-20T10:00:00Z",
};

function mockApi(candidates = [ABERTA, PAGA]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url.startsWith("/payables/receipts/candidates")) {
      return Promise.resolve({ data: candidates });
    }
    if (url === "/payables/receipts") {
      return Promise.resolve({
        data: [{ id: "r-1", filename: "comp.pdf", content_type: "application/pdf",
                 size: 1024, created_at: "2026-07-28T10:00:00Z" }],
      });
    }
    return Promise.resolve({ data: [] });
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/comprovante/r-1"]}>
      <Routes>
        <Route path="/comprovante/:id" element={<ComprovantePage />} />
        <Route path="/pagar" element={<p>contas a pagar</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ComprovantePage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lista as contas candidatas com nome, valor e status", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));
    expect(screen.getByText("Internet")).toBeTruthy();
    expect(screen.getByText("Pago")).toBeTruthy();
  });

  it("mostra o checkbox de baixa apenas para conta em aberto", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    const check = screen.getByRole("checkbox", { name: /marcar como paga/i }) as HTMLInputElement;
    expect(check.checked).toBe(true); // marcado por padrão

    await userEvent.click(screen.getByText("Internet"));
    expect(screen.queryByRole("checkbox", { name: /marcar como paga/i })).toBeNull();
  });

  it("vincula chamando link com o payload correto", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-aberta" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    await userEvent.click(screen.getByRole("button", { name: /^anexar$/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/payables/receipts/r-1/link");
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({
      bill_id: "b-aberta", mark_paid: true,
    });
  });

  it("envia mark_paid false quando o usuario desmarca", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-aberta" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    await userEvent.click(screen.getByRole("checkbox", { name: /marcar como paga/i }));
    await userEvent.click(screen.getByRole("button", { name: /^anexar$/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({
      bill_id: "b-aberta", mark_paid: false,
    });
  });

  it("busca refaz a consulta com o termo digitado", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.type(screen.getByPlaceholderText(/buscar conta/i), "copel");
    await waitFor(() =>
      expect(
        vi.mocked(api.get).mock.calls.some(([url]) =>
          String(url).includes("candidates?q=copel"),
        ),
      ).toBe(true),
    );
  });

  it("cria conta nova a partir do formulario curto", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-novo" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    await userEvent.type(screen.getByPlaceholderText(/descrição/i), "Estacionamento");
    await userEvent.type(screen.getByPlaceholderText(/valor/i), "45,00");
    await userEvent.click(screen.getByRole("button", { name: /criar e anexar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, payload] = vi.mocked(api.post).mock.calls[0];
    expect(url).toBe("/payables/receipts/r-1/new-bill");
    expect((payload as { amount_cents: number }).amount_cents).toBe(4500);
  });

  it("descartar remove o comprovante e volta para contas a pagar", async () => {
    mockApi();
    vi.mocked(api.delete).mockResolvedValue({ data: null } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /descartar/i }));
    await waitFor(() => screen.getByText("contas a pagar"));
    expect(api.delete).toHaveBeenCalledWith("/payables/receipts/r-1");
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/web && pnpm vitest run src/features/pagar/ComprovantePage.test.tsx`
Expected: FAIL — `Failed to resolve import "./ComprovantePage"`.

- [ ] **Step 3: Implementar a tela**

Criar `apps/web/src/features/pagar/ComprovantePage.tsx`:

```tsx
import type { Payable } from "@e1p/shared-types";
import { FileText, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const dia = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("pt-BR", { timeZone: "UTC" });

/** Converte "45,00" / "45.00" / "4500" em centavos. Vazio ou inválido → 0. */
function toCents(raw: string): number {
  const clean = raw.replace(/\s/g, "").replace(/\./g, "").replace(",", ".");
  const n = Number.parseFloat(clean);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

function chip(p: Payable): { label: string; cls: string } {
  if (p.status === "paid") return { label: "Pago", cls: "bg-accent-50 text-accent-700" };
  if (p.is_overdue) return { label: "Vencida", cls: "bg-red-50 text-danger" };
  return { label: "A vencer", cls: "bg-amber-50 text-amber-700" };
}

/**
 * Tela de vinculação do comprovante, dimensionada para o polegar: cartões altos, um alvo de
 * toque por conta, e a ação principal fixa no rodapé.
 */
export default function ComprovantePage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [candidates, setCandidates] = useState<Payable[]>([]);
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [markPaid, setMarkPaid] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<Payable[]>(
      `/payables/receipts/candidates?q=${encodeURIComponent(q)}`,
    );
    setCandidates(data);
  }, [q]);

  useEffect(() => {
    load().catch((err) => setError(apiErrorMessage(err)));
  }, [load]);

  const chosen = useMemo(
    () => candidates.find((c) => c.id === selected) ?? null,
    [candidates, selected],
  );

  async function link() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      await api.post(`/payables/receipts/${id}/link`, {
        bill_id: chosen.id,
        // conta já paga não mostra o checkbox — não faz sentido "dar baixa" de novo
        mark_paid: chosen.status === "open" ? markPaid : false,
      });
      navigate("/pagar", { replace: true });
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    setBusy(true);
    try {
      await api.delete(`/payables/receipts/${id}`);
      navigate("/pagar", { replace: true });
    } catch (err) {
      setError(apiErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg space-y-4 pb-28">
      <header className="flex items-center gap-3 rounded-2xl bg-white p-4 shadow-sm">
        <FileText size={22} className="shrink-0 text-neutral-400" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-neutral-700">Comprovante recebido</p>
          <p className="text-xs text-neutral-500">Escolha a conta a que ele pertence</p>
        </div>
        <button
          onClick={discard}
          disabled={busy}
          className="flex shrink-0 items-center gap-1 text-xs text-neutral-400 hover:text-danger"
        >
          <Trash2 size={14} /> Descartar
        </button>
      </header>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Buscar conta por nome ou fornecedor"
        className="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-primary-400"
      />

      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-danger">{error}</p>}

      <ul className="space-y-2">
        {candidates.map((c) => {
          const tag = chip(c);
          const active = c.id === selected;
          return (
            <li key={c.id}>
              <button
                onClick={() => setSelected(c.id)}
                className={`w-full rounded-2xl border p-4 text-left transition ${
                  active ? "border-primary-400 bg-primary-50" : "border-neutral-200 bg-white"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-neutral-800">
                      {c.description || c.supplier || "Conta"}
                    </p>
                    {c.supplier && c.description && (
                      <p className="truncate text-xs text-neutral-500">{c.supplier}</p>
                    )}
                    <p className="mt-1 text-xs text-neutral-500">Vence {dia(c.due_date)}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-bold text-neutral-800">{brl(c.amount_cents)}</p>
                    <span className={`rounded-pill px-2 py-0.5 text-[10px] font-semibold ${tag.cls}`}>
                      {tag.label}
                    </span>
                  </div>
                </div>
              </button>
            </li>
          );
        })}
        {candidates.length === 0 && (
          <li className="rounded-2xl bg-white p-6 text-center text-sm text-neutral-400">
            Nenhuma conta encontrada.
          </li>
        )}
      </ul>

      {chosen?.status === "open" && (
        <label className="flex items-center gap-2 rounded-2xl bg-white p-4 text-sm text-neutral-700 shadow-sm">
          <input
            type="checkbox"
            checked={markPaid}
            onChange={(e) => setMarkPaid(e.target.checked)}
            className="h-4 w-4"
          />
          Marcar como paga
        </label>
      )}

      {showNew ? (
        <NewBillForm receiptId={id} onError={setError} />
      ) : (
        <button
          onClick={() => setShowNew(true)}
          className="w-full text-center text-sm font-semibold text-primary-600"
        >
          Criar conta nova com este comprovante
        </button>
      )}

      <div className="fixed inset-x-0 bottom-0 border-t border-neutral-100 bg-white p-4">
        <button
          onClick={link}
          disabled={!chosen || busy}
          className="mx-auto block w-full max-w-lg rounded-pill bg-accent-400 py-3 font-semibold text-white hover:bg-accent-500 disabled:opacity-50"
        >
          {busy ? "Anexando..." : "Anexar"}
        </button>
      </div>
    </div>
  );
}

/** Formulário curto: o mínimo para registrar agora e refinar depois no computador. */
function NewBillForm({
  receiptId,
  onError,
}: {
  receiptId: string;
  onError: (m: string | null) => void;
}) {
  const navigate = useNavigate();
  const [description, setDescription] = useState("");
  const [supplier, setSupplier] = useState("");
  const [category, setCategory] = useState("Geral");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);

  async function submit() {
    const cents = toCents(amount);
    if (cents <= 0) {
      onError("Informe um valor maior que zero.");
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await api.post(`/payables/receipts/${receiptId}/new-bill`, {
        description, supplier, category, amount_cents: cents,
        due_date: dueDate, mark_paid: true,
      });
      navigate("/pagar", { replace: true });
    } catch (err) {
      onError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-primary-400";

  return (
    <div className="space-y-2 rounded-2xl bg-white p-4 shadow-sm">
      <p className="text-sm font-semibold text-neutral-700">Conta nova</p>
      <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Descrição" className={input} />
      <input value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Fornecedor" className={input} />
      <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Categoria" className={input} />
      <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Valor (ex.: 45,00)" inputMode="decimal" className={input} />
      <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className={input} />
      <button
        onClick={submit}
        disabled={busy}
        className="w-full rounded-pill bg-primary-500 py-2.5 font-semibold text-white hover:bg-primary-600 disabled:opacity-50"
      >
        {busy ? "Criando..." : "Criar e anexar"}
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Registrar a rota**

Em `apps/web/src/app/App.tsx`, importar e adicionar logo depois de `/compartilhar`:

```tsx
import ComprovantePage from "../features/pagar/ComprovantePage";
```

```tsx
          <Route path="/comprovante/:id" element={<ComprovantePage />} />
```

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/web && pnpm vitest run src/features/pagar/ComprovantePage.test.tsx`
Expected: PASS (7 testes).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/pagar/ComprovantePage.tsx \
        apps/web/src/features/pagar/ComprovantePage.test.tsx \
        apps/web/src/app/App.tsx
git commit -m "feat: tela de vinculacao do comprovante a conta"
```

---

## Task 11: Slot `comprovante` e aviso da bandeja em Contas a Pagar

Esta é a correção do problema original — hoje o comprovante vai parar no campo "Contrato" porque não existe campo próprio.

**Files:**
- Modify: `apps/web/src/features/pagar/PagarPage.tsx:361` (slots) e o topo da página (aviso)
- Create: `apps/web/src/features/pagar/PagarPage.test.tsx`

**Interfaces:**
- Consumes: `components/Attachments` (prop `slots`), `lib/api.api`

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/web/src/features/pagar/PagarPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import PagarPage from "./PagarPage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));
vi.mock("../../store/pageActions", () => ({ usePrimaryAction: () => undefined }));

const SUMMARY = {
  open_cents: 0, overdue_cents: 0, week_cents: 0, month_cents: 0, paid_month_cents: 0,
};

function mockApi(inbox: unknown[]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/payables/summary") return Promise.resolve({ data: SUMMARY });
    if (url === "/payables/receipts") return Promise.resolve({ data: inbox });
    return Promise.resolve({ data: [] });
  });
}

describe("PagarPage — bandeja de comprovantes", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mostra o aviso quando ha comprovantes aguardando", async () => {
    mockApi([
      { id: "r-1", filename: "a.pdf", content_type: "application/pdf", size: 1, created_at: "2026-07-28T10:00:00Z" },
      { id: "r-2", filename: "b.pdf", content_type: "application/pdf", size: 1, created_at: "2026-07-28T11:00:00Z" },
    ]);
    render(<MemoryRouter><PagarPage /></MemoryRouter>);
    await waitFor(() => screen.getByText(/2 comprovantes aguardando/i));
  });

  it("nao mostra o aviso com a bandeja vazia", async () => {
    mockApi([]);
    render(<MemoryRouter><PagarPage /></MemoryRouter>);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByText(/aguardando/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/web && pnpm vitest run src/features/pagar/PagarPage.test.tsx`
Expected: FAIL — o texto do aviso não existe.

- [ ] **Step 3: Adicionar o slot `comprovante`**

Em `apps/web/src/features/pagar/PagarPage.tsx`, na linha 361, trocar:

```tsx
            slots={[{ key: "boleto", label: "Boleto" }, { key: "contrato", label: "Contrato" }]}
```

por:

```tsx
            slots={[
              { key: "boleto", label: "Boleto" },
              { key: "contrato", label: "Contrato" },
              { key: "comprovante", label: "Comprovante" },
            ]}
```

- [ ] **Step 4: Adicionar o aviso da bandeja**

Três edições pontuais em `apps/web/src/features/pagar/PagarPage.tsx`.

**4a — import do `Link`**, no topo do arquivo, junto dos outros imports:

```tsx
import { Link } from "react-router-dom";
```

**4b — estado e busca.** Dentro do componente `PagarPage`, adicionar o estado ao lado dos existentes (`summary`, `bills`, ...):

```tsx
  // Comprovantes que chegaram pelo celular e ainda não foram vinculados a nenhuma conta.
  const [inbox, setInbox] = useState<{ id: string }[]>([]);
```

E, dentro do `useCallback` `load`, depois do `Promise.all` que já busca summary e bills:

```tsx
    // .catch: a bandeja é um extra da tela; se falhar, Contas a Pagar continua funcionando.
    const pend = await api
      .get<{ id: string }[]>("/payables/receipts")
      .catch(() => ({ data: [] as { id: string }[] }));
    setInbox(pend.data);
```

**4c — o aviso no JSX**, imediatamente acima dos cartões de resumo (`<Stat .../>`):

```tsx
      {inbox.length > 0 && (
        <Link
          to={`/comprovante/${inbox[0].id}`}
          className="block rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-medium text-amber-800 hover:bg-amber-100"
        >
          {inbox.length === 1
            ? "1 comprovante aguardando"
            : `${inbox.length} comprovantes aguardando`}{" "}
          — toque para escolher a conta.
        </Link>
      )}
```

O `Link` aponta para o comprovante mais recente (`list_inbox` já ordena por `created_at` decrescente); depois de vinculá-lo, o aviso reaparece apontando para o próximo.

- [ ] **Step 5: Rodar os testes**

Run: `cd apps/web && pnpm vitest run src/features/pagar/PagarPage.test.tsx`
Expected: PASS (2 testes).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/pagar/PagarPage.tsx \
        apps/web/src/features/pagar/PagarPage.test.tsx
git commit -m "feat: slot comprovante e aviso da bandeja em contas a pagar"
```

---

## Task 12: Seção "Celular" em Configurações

**Files:**
- Create: `apps/web/src/features/config/CelularSection.tsx`
- Create: `apps/web/src/features/config/CelularSection.test.tsx`
- Modify: `apps/web/src/features/config/ConfiguracoesPage.tsx`
- Modify: `packages/shared-types/src/index.ts`

**Interfaces:**
- Consumes: `lib/api.api`
- Produces:
  - `shared-types.DeviceToken` — `{ id: string; name: string; created_at: string; last_used_at: string | null }`
  - componente default `CelularSection`

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/web/src/features/config/CelularSection.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import CelularSection from "./CelularSection";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

describe("CelularSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lista os dispositivos com o ultimo uso", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "t-1", name: "iPhone do Flavio", created_at: "2026-07-01T10:00:00Z",
               last_used_at: "2026-07-27T09:00:00Z" }],
    } as never);
    render(<CelularSection />);
    await waitFor(() => screen.getByText("iPhone do Flavio"));
  });

  it("mostra o token cru UMA vez ao criar", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "t-2", name: "iPhone", token: "segredo-cru-do-token" },
    } as never);

    render(<CelularSection />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    await userEvent.type(screen.getByPlaceholderText(/nome do aparelho/i), "iPhone");
    await userEvent.click(screen.getByRole("button", { name: /gerar token/i }));

    await waitFor(() => screen.getByText("segredo-cru-do-token"));
    expect(screen.getByText(/só aparece uma vez/i)).toBeTruthy();
  });

  it("revoga o dispositivo", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "t-1", name: "iPhone", created_at: "2026-07-01T10:00:00Z", last_used_at: null }],
    } as never);
    vi.mocked(api.delete).mockResolvedValue({ data: null } as never);

    render(<CelularSection />);
    await waitFor(() => screen.getByText("iPhone"));
    await userEvent.click(screen.getByRole("button", { name: /revogar/i }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/settings/device-tokens/t-1"));
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/web && pnpm vitest run src/features/config/CelularSection.test.tsx`
Expected: FAIL — `Failed to resolve import "./CelularSection"`.

- [ ] **Step 3: Adicionar o tipo compartilhado**

Em `packages/shared-types/src/index.ts`, acrescentar:

```ts
/** Credencial do Atalho do iOS. O token cru só existe na resposta da criação. */
export interface DeviceToken {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}
```

- [ ] **Step 4: Implementar a seção**

Criar `apps/web/src/features/config/CelularSection.tsx`:

```tsx
import type { DeviceToken } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

/**
 * Configuração das duas portas de entrada do comprovante pelo celular.
 *
 * Android não precisa de token: o PWA instalado já vira destino do compartilhamento. iOS
 * precisa, porque o Atalho não tem sessão de navegador — e é por isso que esse token só
 * autoriza o upload do comprovante, nada mais.
 */
export default function CelularSection() {
  const [tokens, setTokens] = useState<DeviceToken[]>([]);
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<DeviceToken[]>("/settings/device-tokens");
    setTokens(data);
  }, []);

  useEffect(() => {
    load().catch((err) => setError(apiErrorMessage(err)));
  }, [load]);

  async function create() {
    setError(null);
    try {
      const { data } = await api.post<{ token: string }>("/settings/device-tokens", {
        name: name.trim() || "Meu iPhone",
      });
      setFresh(data.token);
      setName("");
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function revoke(id: string) {
    await api.delete(`/settings/device-tokens/${id}`);
    await load();
  }

  const origin = typeof window === "undefined" ? "" : window.location.origin;

  return (
    <section className="space-y-4 rounded-2xl bg-white p-5 shadow-sm">
      <div>
        <h2 className="font-semibold text-neutral-800">Celular — anexar comprovante</h2>
        <p className="text-sm text-neutral-500">
          Compartilhe o comprovante direto do app do banco para o e1p.
        </p>
      </div>

      <div className="rounded-xl bg-neutral-50 p-4 text-sm text-neutral-700">
        <p className="mb-1 font-semibold">Android</p>
        <p>
          Abra <code>{origin}</code> no Chrome, toque no menu e escolha{" "}
          <strong>Instalar app</strong>. Depois disso o e1p aparece na lista de compartilhamento
          do app do banco. Não precisa de token.
        </p>
      </div>

      <div className="rounded-xl bg-neutral-50 p-4 text-sm text-neutral-700">
        <p className="mb-1 font-semibold">iPhone</p>
        <p className="mb-2">
          Crie um atalho no app <strong>Atalhos</strong> com estes 4 passos e gere um token abaixo:
        </p>
        <ol className="list-decimal space-y-1 pl-5 text-xs">
          <li>Ação <strong>Receber</strong> imagens e PDFs da folha de compartilhamento.</li>
          <li>
            <strong>Obter conteúdo do URL</strong> — POST em{" "}
            <code>{origin}/api/payables/receipts</code>, corpo <code>Formulário</code> com o campo{" "}
            <code>file</code> = Entrada do Atalho, e cabeçalho{" "}
            <code>X-E1P-Device-Token</code> = seu token.
          </li>
          <li><strong>Obter valor do dicionário</strong> — chave <code>id</code>.</li>
          <li><strong>Abrir URL</strong> — <code>{origin}/comprovante/</code> + o valor do passo 3.</li>
        </ol>
      </div>

      {fresh && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-xs font-semibold text-amber-800">
            Copie agora — o token só aparece uma vez.
          </p>
          <p className="mt-1 break-all rounded bg-white p-2 font-mono text-xs">{fresh}</p>
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Nome do aparelho (ex.: meu iPhone)"
          className="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
        />
        <button
          onClick={create}
          className="shrink-0 rounded-pill bg-primary-500 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-600"
        >
          Gerar token
        </button>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {tokens.length > 0 && (
        <ul className="divide-y divide-neutral-100 rounded-lg border border-neutral-100">
          {tokens.map((t) => (
            <li key={t.id} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate text-neutral-700">{t.name}</span>
              <span className="shrink-0 text-xs text-neutral-400">
                {t.last_used_at
                  ? `usado em ${new Date(t.last_used_at).toLocaleDateString("pt-BR")}`
                  : "nunca usado"}
              </span>
              <button
                onClick={() => revoke(t.id)}
                className="shrink-0 text-xs font-semibold text-neutral-400 hover:text-danger"
              >
                Revogar
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Montar na página de configurações**

Em `apps/web/src/features/config/ConfiguracoesPage.tsx`, importar e renderizar a seção junto das existentes (ex.: logo depois de `WhatsappSection`):

```tsx
import CelularSection from "./CelularSection";
```

```tsx
      <CelularSection />
```

- [ ] **Step 6: Rodar os testes e o typecheck**

```bash
cd apps/web && pnpm vitest run src/features/config/CelularSection.test.tsx && pnpm typecheck
```
Expected: PASS (3 testes) e typecheck limpo.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/config/CelularSection.tsx \
        apps/web/src/features/config/CelularSection.test.tsx \
        apps/web/src/features/config/ConfiguracoesPage.tsx \
        packages/shared-types/src/index.ts
git commit -m "feat: secao Celular em configuracoes (PWA + atalho iOS + tokens)"
```

---

## Task 13: Checklist de validação manual e memória do projeto

Duas coisas **não** são automatizáveis e precisam ficar registradas em vez de fingir cobertura: o share sheet do Android (exige aparelho real com o PWA instalado) e o Atalho do iOS. O teste de isolamento cross-tenant do `link` também precisa de Postgres, porque a RLS não existe no SQLite dos testes.

**Files:**
- Create: `docs/CHECKLIST-COMPROVANTE-MOBILE.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Escrever o checklist**

Criar `docs/CHECKLIST-COMPROVANTE-MOBILE.md`:

```markdown
# Checklist manual — comprovante pelo celular

Rodar uma vez antes de considerar a entrega concluída. Nada aqui é automatizável: share sheets
de sistema operacional e RLS do Postgres não são exercitáveis por vitest/pytest.

## 1. Isolamento cross-tenant (Postgres real)

A RLS é Postgres-only; os testes unitários usam SQLite e não a exercem (mesma lacuna já
registrada no CLAUDE.md).

- [ ] Subir a stack: `docker compose --env-file .env -f infra/docker-compose.yml up -d --build`
- [ ] Criar dois tenants (A e B) via `/auth/register`.
- [ ] Em A, criar uma conta a pagar e anotar o `bill_id`.
- [ ] Em B, subir um comprovante (`POST /payables/receipts`) e anotar o `receipt_id`.
- [ ] Com o token de B, chamar `POST /payables/receipts/{receipt_id}/link` com o `bill_id` de A.
- [ ] **Esperado:** `404` — a RLS esconde a conta de A da sessão de B. Se vier `200`, a RLS não
      está ativa (checar se a app conecta como `e1p_app`, não superusuário).

## 2. Android — share sheet

- [ ] Abrir `https://<domínio>` no Chrome do Android.
- [ ] Menu → **Instalar app**. Confirmar que o ícone aparece na tela inicial.
- [ ] Abrir o app do banco, fazer/abrir um pagamento, tocar em **Compartilhar**.
- [ ] **Esperado:** "e1p" aparece na lista de destinos.
- [ ] Tocar em e1p → abre a tela de escolha da conta com o arquivo já enviado.
- [ ] Escolher uma conta em aberto, manter "marcar como paga", tocar em **Anexar**.
- [ ] **Esperado:** volta para Contas a pagar, a conta está "Pago" e tem o anexo `comprovante`.
- [ ] Repetir deslogado: deve cair no login e retomar sozinho depois de entrar.

## 3. Android — o service worker não serve versão velha

- [ ] Fazer um deploy novo com uma mudança visível.
- [ ] Abrir o PWA já instalado no aparelho, sem limpar dados.
- [ ] **Esperado:** a mudança aparece na primeira abertura. Se não aparecer, conferir o
      `Cache-Control` de `/sw.js` no nginx (deve ser `no-cache`).

## 4. iPhone — Atalho

- [ ] Em Configurações → Celular, gerar um token e copiar.
- [ ] Montar o atalho no app Atalhos seguindo os 4 passos da tela.
- [ ] Testar com um arquivo qualquer pela folha de compartilhamento.
- [ ] **Esperado:** o Safari abre em `/comprovante/<id>` com o arquivo já na bandeja.
- [ ] Publicar o atalho como link do iCloud (**manual, uma vez só** — não dá para gerar por
      código) e guardar o link para distribuir a quem for usar.
- [ ] Revogar o token em Configurações e repetir: **esperado** `401`.

## 5. Limites

- [ ] Compartilhar um arquivo acima de 10 MB → mensagem de erro clara, não tela branca.
- [ ] Compartilhar um tipo não suportado (ex.: `.docx`) → recusado com mensagem.
- [ ] Encher a bandeja com 30 itens e tentar o 31º → mensagem pedindo para vincular/descartar.
```

- [ ] **Step 2: Atualizar a memória do projeto**

Em `CLAUDE.md`, acrescentar na seção de Anexos:

```markdown
## Anexos: comprovante pelo share sheet do celular
- [x] **Compartilhar comprovante do app do banco → Contas a Pagar** — o comprovante entra pelo
  compartilhamento nativo do celular, sem salvar arquivo antes. **Bandeja de staging** sem tabela
  nova: `Attachment` com `owner_type="receipt_inbox"`, `owner_id=<user_id>`; vincular é só trocar
  `owner_type`/`owner_id` para `payable` (os bytes não se movem — a `storage.build_key` não
  carrega o dono). Rotas em `/payables/receipts` (upload, bandeja, `candidates`, `link`,
  `new-bill`, descarte). `link` anexa e dá baixa **num commit só**, o que exigiu extrair
  `apply_paid` e `build_payable` (versões sem commit) de `mark_paid`/`create_payable` — mesmo
  padrão do `receivables.build_charge`. **Android:** PWA instalável com `share_target`; o
  `public/sw.js` é um service worker que **não faz cache de nada** (só intercepta o POST do share
  target) — de propósito, para não introduzir a classe de bug "deploy novo, app velho em cache".
  ⚠️ `nginx.conf` ganhou `location = /sw.js` com `no-cache`: o regex de estáticos daria
  `immutable` 30d ao service worker. **iOS:** app Atalhos + `device_tokens` (migration 0057,
  tabela GLOBAL sem RLS pela mesma razão que `users`), com escopo travado em
  `POST /payables/receipts` — um token vazado só consegue depositar arquivo na bandeja do dono,
  nunca ler. Slot `comprovante` adicionado ao modal (antes o comprovante ia no campo "Contrato").
  - **Dívida:** Contas a Receber e anexos genéricos fora de escopo; WhatsApp como porta de entrada
    fica desenhado mas não construído (o `whatsapp_inbox` já cria `Attachment` — falta apontar o
    `owner_type` para a bandeja) e depende das credenciais da Meta; sem OCR/sugestão automática da
    conta; publicação do atalho do iOS é manual (limitação da plataforma).
  - **Validação manual obrigatória:** `docs/CHECKLIST-COMPROVANTE-MOBILE.md` — share sheet do
    Android, Atalho do iOS e isolamento cross-tenant do `link` (RLS é Postgres-only) não são
    cobertos pelos testes automatizados.
```

- [ ] **Step 3: Rodar a suíte completa**

```bash
bash scripts/check.sh
```
Expected: lint + typecheck + testes (backend e frontend) todos verdes.

- [ ] **Step 4: Commit**

```bash
git add docs/CHECKLIST-COMPROVANTE-MOBILE.md CLAUDE.md
git commit -m "docs: checklist manual do comprovante mobile e memoria do projeto"
```

---

## Cobertura da spec

| Requisito da spec | Task |
|---|---|
| Bandeja como `Attachment` com `owner_type="receipt_inbox"` | 1 |
| `POST /payables/receipts` restrito a PDF/JPEG/PNG | 1 |
| Teto de 30 itens em staging | 1 |
| `GET /payables/receipts` (bandeja) e descarte | 1 |
| `GET /payables/receipts/candidates` — abertas + pagas 30d, sem canceladas, com busca | 2 |
| `link` com baixa opcional, num commit | 3 |
| Conta cancelada → 409 sem gravar; já vinculado → 409; já paga → silencioso | 3 |
| `new-bill` criando conta + evento na Agenda + vínculo | 4 |
| Tabela `device_tokens` global, hash sha256, migration 0057 | 5 |
| Escopo travado; token vazado só deposita na bandeja | 5, 6 |
| Dependency que aceita JWT ou `X-E1P-Device-Token` | 6 |
| `/settings/device-tokens` (criar/listar/revogar), cru uma vez | 7, 12 |
| `manifest.webmanifest` com `share_target` | 8 |
| Service worker sem cache, `skipWaiting` + `clients.claim` | 8 |
| Ícones 192/512 maskable | 8 |
| `/compartilhar` com os dois caminhos de erro tratados | 9 |
| `/comprovante/:id` — cartões, chips, checkbox, busca, conta nova | 10 |
| Slot `comprovante` no modal | 11 |
| Aviso da bandeja em Contas a Pagar | 11 |
| Seção "Celular" com instruções Android/iOS | 12 |
| Validação manual declarada (Android, iOS, cross-tenant) | 13 |
