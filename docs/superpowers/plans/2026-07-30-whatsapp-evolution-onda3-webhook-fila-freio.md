# WhatsApp Evolution — Onda 3 (Webhook + Fila com Validade + Freio Anti-Ban) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar o ciclo do transporte Evolution: (A) migrar os 5 fluxos que hoje enviam
WhatsApp **na hora** (síncrono) para a fila assíncrona — pré-requisito para o freio valer para
os dois fluxos que mais geram volume; (B) dar à fila validade por propósito + retry com
backoff; (C) o freio anti-ban com aquecimento; (D) o webhook interno da Evolution (inbound) com
a bandeja "Não identificados" para o caso `@lid`.

**Architecture:** `Notification` ganha `purpose`, `expires_at`, `next_attempt_at`. Os 5 pontos
de chamada que hoje fazem `whatsapp.send_*(...)` direto na request passam a chamar
`notifications_service.enqueue(purpose=..., ...)` — a entrega real (e o freio) acontecem só no
worker (`process_pending`), fora da request. O webhook interno da Evolution resolve o tenant via
`PublicWhatsappInstance.webhook_secret` (no path, defesa em profundidade — a rota só é alcançável
de dentro da rede Docker) e reaproveita o domínio do inbox (Onda 0 do inbox, já existente) trocando
só o parser do payload.

**Tech Stack:** Python 3.13, SQLAlchemy/Alembic, pytest. Nenhuma dependência nova.

## Global Constraints

- **Correção de framing:** a decisão do usuário foi "migrar os 4 fluxos síncronos para a fila"
  (cobrança/contrato/orçamento/convite). Ao levantar os call sites reais, existe um **5º**:
  o nó de WhatsApp do Funil de Vendas (`funnels/service.py::run_node`, ação `send_message`) —
  também síncrono, e é um dos DOIS fluxos citados como motivação original do freio (o outro é a
  régua de cobrança). Ele entra nesta onda pelo mesmo motivo que os outros 4: sem isso, o freio
  não cobre metade do que foi desenhado para cobrir.
- **`GET /whatsapp-session/status` continua leitura pura** (invariante da Onda 2 — não mexer).
- **O freio vive só no caminho da fila** (`process_pending`), nunca no envio síncrono do inbox
  (responder quem escreveu primeiro não passa pelo freio — decisão já registrada na spec §7).
- **A migration desta onda começa em `0062`** (a Onda 2 fechou em `0061`, já mesclada).
- **`ruff check .` limpo**; suíte completa (`pytest -q -m "not rls_e2e"`) verde a cada task.
- Ambiente: `apps/api/.venv/Scripts/python.exe` (reaproveitado, mesma convenção das ondas
  anteriores).

---

## File Structure

```
apps/api/migrations/versions/0062_notification_purpose_expiry.py  → NOVO
apps/api/migrations/versions/0063_whatsapp_message_client_nullable.py → NOVO
apps/api/migrations/versions/0064_public_whatsapp_instances_secret_index.py → NOVO (índice p/ lookup do webhook por secret)

apps/api/app/modules/notifications/models.py     → MODIFICADO (purpose/expires_at/next_attempt_at)
apps/api/app/modules/notifications/service.py    → MODIFICADO (enqueue com purpose; process_pending com validade/retry/freio)
apps/api/app/modules/receivables/service.py      → MODIFICADO (2 call sites → enqueue)
apps/api/app/modules/contracts/service.py        → MODIFICADO (1 call site → enqueue)
apps/api/app/modules/quotes/service.py           → MODIFICADO (1 call site → enqueue)
apps/api/app/modules/platform/service.py         → MODIFICADO (1 call site → enqueue)
apps/api/app/modules/funnels/service.py          → MODIFICADO (1 call site → enqueue)

apps/api/app/core/whatsapp/providers/evolution.py → MODIFICADO (parse_inbound)
apps/api/app/core/whatsapp/providers/meta.py      → MODIFICADO (parse_inbound, movido de whatsapp_inbox/service.py)
apps/api/app/modules/whatsapp_inbox/models.py     → MODIFICADO (client_id nullable)
apps/api/app/modules/whatsapp_inbox/service.py    → MODIFICADO (ingest genérico por InboundMessage; bandeja não identificados)
apps/api/app/modules/whatsapp_inbox/router.py     → MODIFICADO (rota interna da Evolution)
apps/api/app/modules/whatsapp_inbox/schemas.py    → MODIFICADO (se necessário, ver Task 10)

apps/web/src/features/config/ConversasPage.tsx (ou onde a lista de conversas vive) → MODIFICADO (bandeja "Não identificados")

apps/api/tests/test_notifications_purpose_expiry.py → NOVO
apps/api/tests/test_notifications_throttle.py        → NOVO
apps/api/tests/test_whatsapp_inbox_unidentified.py    → NOVO
```

---

## Fase A — Migrar os 5 fluxos síncronos para a fila

### Task 1: Migration 0062 — `Notification.purpose`/`expires_at`/`next_attempt_at`

**Files:**
- Create: `apps/api/migrations/versions/0062_notification_purpose_expiry.py`
- Modify: `apps/api/app/modules/notifications/models.py`

**Interfaces:**
- Produces: `Notification.purpose: str | None`, `Notification.expires_at: datetime | None`,
  `Notification.next_attempt_at: datetime | None` (ORM + coluna).

- [ ] **Step 1: Migration**

```python
"""notifications ganha purpose/expires_at/next_attempt_at (Onda 3 — fila com validade)

Revision ID: 0062
Revises: 0061
Create Date: 2026-07-30

- `purpose`: propósito do envio (ex.: "charge_reminder", "funnel_node") — usado para resolver a
  validade (Onda 3 §Fase B). None = compatibilidade com linhas antigas (nunca expiram sozinhas).
- `expires_at`: calculado no enfileiramento; passado disso, `process_pending` marca "expired"
  em vez de tentar entregar.
- `next_attempt_at`: retry com backoff exponencial, limitado pela validade (nunca agenda
  tentativa depois de expirar).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("purpose", sa.String(32), nullable=True))
    op.add_column(
        "notifications", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("notifications", "next_attempt_at")
    op.drop_column("notifications", "expires_at")
    op.drop_column("notifications", "purpose")
```

- [ ] **Step 2: Campos ORM**

Em `apps/api/app/modules/notifications/models.py`, acrescentar à classe `Notification` (após
`whatsapp_template_variables`):

```python
    whatsapp_template_variables: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Propósito do envio (Onda 3) — resolve a validade em notifications/service.py. None =
    # notificação antiga (pré-Onda 3), nunca expira sozinha.
    purpose: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped["datetime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped["datetime | None"] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Acrescentar `DateTime` ao import de `sqlalchemy` e `from datetime import datetime` (ou
`from __future__ import annotations` já cobre, mas o arquivo precisa do import de `datetime`
para o `TYPE_CHECKING`-free type hint funcionar em runtime do SQLAlchemy — usar
`Mapped[datetime | None]` direto, sem aspas, já que `from __future__ import annotations` está
no topo do arquivo).

- [ ] **Step 3: Rodar a suíte de notificações (baseline aditivo)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications.py tests/test_notifications_queue.py -q`
Expected: mesmo total de antes (campos com default None, nada quebra).

- [ ] **Step 4: Commit**

```bash
git add apps/api/migrations/versions/0062_notification_purpose_expiry.py apps/api/app/modules/notifications/models.py
git commit -m "feat: migration 0062 — Notification.purpose/expires_at/next_attempt_at"
```

---

### Task 2: `enqueue()` calcula validade por propósito

**Files:**
- Modify: `apps/api/app/modules/notifications/service.py`
- Create: `apps/api/tests/test_notifications_purpose_expiry.py`

**Interfaces:**
- Produces: `enqueue(..., purpose: str | None = None) -> Notification` — quando `purpose` é um
  dos conhecidos, calcula `expires_at` (fim do dia no fuso do tenant, para propósitos de
  dinheiro; +1h para operacionais). `purpose=None` (compat) não seta `expires_at` (nunca expira
  — comportamento de hoje, preservado para não quebrar `on_client_moved`, que já enfileira sem
  propósito explícito ainda nesta task).

- [ ] **Step 1: Escrever os testes de validade**

```python
"""Testes da validade por propósito em notifications.service::enqueue (Onda 3 — fila com
validade). Ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §7."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.notifications import service
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service

TENANT_ID = "33333333-3333-3333-3333-333333333333"


def test_enqueue_without_purpose_never_expires(db) -> None:
    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="oi",
    )
    db.commit()
    assert n.expires_at is None


def test_enqueue_money_purpose_expires_end_of_tenant_day(db) -> None:
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.timezone = "America/Sao_Paulo"
    db.commit()

    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="cobranca",
        purpose="charge_reminder",
    )
    db.commit()
    assert n.expires_at is not None
    # Fim do dia em America/Sao_Paulo (UTC-3) = 03:00 do dia seguinte em UTC.
    assert n.expires_at.hour == 3
    assert n.expires_at.tzinfo is not None


def test_enqueue_operational_purpose_expires_in_one_hour(db) -> None:
    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="card movido",
        purpose="client_moved",
    )
    db.commit()
    now = datetime.now(UTC)
    assert n.expires_at is not None
    delta = n.expires_at - now
    assert timedelta(minutes=55) < delta < timedelta(minutes=65)


def test_enqueue_funnel_node_purpose_expires_in_one_hour(db) -> None:
    n = service.enqueue(
        db, tenant_id=TENANT_ID, channel="whatsapp", recipient="d@e.com", message="promo",
        purpose="funnel_node",
    )
    db.commit()
    now = datetime.now(UTC)
    delta = n.expires_at - now
    assert timedelta(minutes=55) < delta < timedelta(minutes=65)
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_purpose_expiry.py -v`
Expected: FAIL (`enqueue()` ainda não aceita `purpose=`, `TypeError`).

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/notifications/service.py`, acrescentar antes de `enqueue`:

```python
# Validade por propósito (spec §7): dinheiro-com-data expira no fim do dia do tenant;
# operacional expira em 1h. Ausente da tabela (ou purpose=None) = nunca expira (compat).
_MONEY_PURPOSES = frozenset({"charge_reminder", "contract_send", "quote_send"})
_ONE_HOUR_PURPOSES = frozenset({"client_moved", "staff_invite", "funnel_node"})


def _compute_expires_at(db: Session, *, tenant_id: str, purpose: str | None) -> "datetime | None":
    if purpose is None:
        return None
    now = datetime.now(UTC)
    if purpose in _ONE_HOUR_PURPOSES:
        return now + timedelta(hours=1)
    if purpose in _MONEY_PURPOSES:
        profile = settings_service.get_profile(db, tenant_id)
        try:
            tz = ZoneInfo(profile.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("America/Sao_Paulo")
        local_now = now.astimezone(tz)
        end_of_day_local = local_now.replace(hour=23, minute=59, second=59, microsecond=0)
        return end_of_day_local.astimezone(UTC)
    return None  # propósito desconhecido — não inventa validade
```

Adicionar aos imports do topo: `from datetime import UTC, datetime, timedelta` e
`from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`.

Modificar a assinatura e o corpo de `enqueue`:

```python
def enqueue(
    db: Session,
    *,
    tenant_id: str,
    channel: str,
    recipient: str,
    message: str,
    client_id: str | None = None,
    purpose: str | None = None,
    whatsapp_template_name: str | None = None,
    whatsapp_template_language: str | None = None,
    whatsapp_template_variables: list | None = None,
) -> Notification:
    """..."""  # (docstring existente + acrescentar nota sobre purpose= abaixo)
    if not recipient or not recipient.strip():
        raise NotificationError("destinatário (recipient) vazio ou inválido")
    notification = Notification(
        tenant_id=tenant_id,
        channel=channel,
        recipient=recipient,
        message=message,
        client_id=client_id,
        status="pending",
        attempts=0,
        purpose=purpose,
        expires_at=_compute_expires_at(db, tenant_id=tenant_id, purpose=purpose),
        whatsapp_template_name=whatsapp_template_name,
        whatsapp_template_language=whatsapp_template_language,
        whatsapp_template_variables=whatsapp_template_variables,
    )
    db.add(notification)
    db.flush()
    return notification
```

- [ ] **Step 4: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_purpose_expiry.py -v`
Expected: 4 testes, PASS.

- [ ] **Step 5: Rodar a suíte de notificações inteira (sem edição esperada)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications.py tests/test_notifications_queue.py -q`
Expected: mesmo total de antes (chamadores existentes não passam `purpose=`, continuam
`expires_at=None`, comportamento idêntico).

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/notifications/service.py apps/api/tests/test_notifications_purpose_expiry.py
git commit -m "feat: enqueue() calcula expires_at por propósito (dinheiro=fim do dia, operacional=1h)"
```

---

### Task 3: Migrar `receivables.collect_with_ai` e `receivables.send_message` para a fila

**Files:**
- Modify: `apps/api/app/modules/receivables/service.py`
- Modify: `apps/api/tests/test_receivables.py`

**Interfaces:**
- Consumes: `notifications_service.enqueue(purpose=...)` (Task 2).
- Produces: os 2 pontos passam a devolver `status="queued"` em vez do status real de envio.

- [ ] **Step 1: Baseline**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_receivables.py -q`
Expected: anotar o total atual.

- [ ] **Step 2: Migrar `collect_with_ai`**

Em `apps/api/app/modules/receivables/service.py`, trocar:

```python
    if template is not None and template.status == STATUS_APPROVED:
        valor = _money(charge.amount_cents)
        venc = charge.due_date.strftime("%d/%m/%Y")
        phrase = _compose_dunning_phrase(
            name, charge.amount_cents, charge.due_date, charge.description
        )
        variables = [name, phrase, valor, venc]
        status = whatsapp.send_template(
            to=client.phone if client and client.phone else "",
            profile=profile,
            template_name=template.name, language=template.language, variables=variables,
        )
        message = _render_template_preview(template.body_text, variables)
    else:
        message = _compose_dunning(name, charge.amount_cents, charge.due_date, charge.description)
        status = whatsapp.send_text(to=recipient, text=message, profile=profile)

    db.add(
        Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=message, status=status,
        )
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.collect.ai",
        target=charge.id, is_ai=True,
    )
    db.commit()
    return {"message": message, "status": status}
```

por:

```python
    if template is not None and template.status == STATUS_APPROVED:
        valor = _money(charge.amount_cents)
        venc = charge.due_date.strftime("%d/%m/%Y")
        phrase = _compose_dunning_phrase(
            name, charge.amount_cents, charge.due_date, charge.description
        )
        variables = [name, phrase, valor, venc]
        message = _render_template_preview(template.body_text, variables)
        notifications_service.enqueue(
            db, tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=message, purpose=PURPOSE_CHARGE_REMINDER,
            whatsapp_template_name=template.name, whatsapp_template_language=template.language,
            whatsapp_template_variables=variables,
        )
    else:
        message = _compose_dunning(name, charge.amount_cents, charge.due_date, charge.description)
        notifications_service.enqueue(
            db, tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=message, purpose=PURPOSE_CHARGE_REMINDER,
        )

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.collect.ai",
        target=charge.id, is_ai=True,
    )
    db.commit()
    return {"message": message, "status": "queued"}
```

Adicionar `from app.modules.notifications import service as notifications_service` ao topo do
arquivo (import de módulo, não de função — mesmo padrão do resto do arquivo). O import de
`Notification` (model) pode ser removido deste ponto SE não for mais usado em nenhum outro lugar
do arquivo — checar com `grep -n "Notification(" app/modules/receivables/service.py` antes de
remover o import (o `send_message`, migrado no próximo Step, também usa `Notification` hoje —
só remover o import depois que AMBOS os pontos estiverem migrados).

- [ ] **Step 3: Migrar `send_message` (mensagem manual)**

Trocar:

```python
    profile = settings_service.get_profile(db, tenant_id)
    status = whatsapp.send_text(to=recipient, text=text, profile=profile)
    db.add(
        Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=charge.client_id, message=text, status=status,
        )
    )
```

por:

```python
    notifications_service.enqueue(
        db, tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
        client_id=charge.client_id, message=text, purpose=PURPOSE_CHARGE_REMINDER,
    )
```

(Reaproveita o mesmo propósito `charge_reminder` — é a mesma cobrança, só que texto manual em
vez de gerado por IA; a distinção IA-vs-manual já está em `actor`/`audit.record`, não precisa de
propósito próprio.)

Ver o restante da função (`db.add(Notification(...))` original tinha mais campos/retorno — abrir
o arquivo e ajustar o `return` para `{"status": "queued"}` mantendo o resto do corpo (validação
de texto vazio, `get_charge`, resolução de `recipient`) intocado.

Agora remover o import de `Notification` model (não usado mais neste arquivo) SE o `grep` do
Step 2 confirmar zero usos restantes.

- [ ] **Step 4: Ajustar os testes que checavam o status real de envio**

Em `apps/api/tests/test_receivables.py`, os testes que hoje fazem
`assert body["status"] == "logged"` (ou `"sent"`) para `/collect` e `/message` precisam virar
`assert body["status"] == "queued"`. Localizar com:
`grep -n "status.*collect\|/collect\|/message" tests/test_receivables.py` e ajustar cada
asserção de status encontrada nesses fluxos — preservando as asserções sobre `captured["profile"]`
(que passam a ler os kwargs de `enqueue`, não de `send_text`/`send_template` — os 2 testes
`test_collect_with_ai_without_binding_uses_free_text_with_tenant_credentials` e
`test_send_message_manual_uses_tenant_credentials`, que hoje mockam `whatsapp.send_text`
diretamente, devem passar a mockar `notifications_service.enqueue` e verificar que
`client_id`/`purpose="charge_reminder"` chegam corretos — os campos de credencial não fazem
mais sentido aqui, já que o envio real acontece só depois, no worker).

- [ ] **Step 5: Rodar a suíte de receivables**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_receivables.py -q`
Expected: mesmo total do Step 1, todos verdes.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/receivables/service.py apps/api/tests/test_receivables.py
git commit -m "refactor: receivables (collect_with_ai + send_message) enfileiram em vez de enviar na hora"
```

---

### Task 4: Migrar `contracts.send_contract`, `quotes` (envio), `platform._send_invite`, `funnels` (nó de WhatsApp)

**Files:**
- Modify: `apps/api/app/modules/contracts/service.py`
- Modify: `apps/api/app/modules/quotes/service.py`
- Modify: `apps/api/app/modules/platform/service.py`
- Modify: `apps/api/app/modules/funnels/service.py`
- Modify: `apps/api/tests/test_contracts.py`, `tests/test_quotes.py`, `tests/test_funnels.py`

**Interfaces:** idem Task 3 — cada call site troca `whatsapp.send_*` + `db.add(Notification(...))`
direto por `notifications_service.enqueue(purpose=...)`.

- [ ] **Step 1: Baseline dos 3 arquivos de teste**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_contracts.py tests/test_quotes.py tests/test_funnels.py tests/test_funnel_automation.py -q`
Expected: anotar o total.

- [ ] **Step 2: `contracts.send_contract`**

Mesmo padrão da Task 3: o `status = whatsapp.send_template(...)` / `send_text(...)` viram
`notifications_service.enqueue(purpose=PURPOSE_CONTRACT_SEND, ...)`; o `db.add(Notification(...))`
some (o `enqueue` já cria a linha). **Import a mais**: `PURPOSE_CONTRACT_SEND` já está importado
neste arquivo (usado na resolução do vínculo). O `c.status = STATUS_SENT` e o resto da função
(`_publish`, `return c`) **não mudam** — só o trecho de envio.

- [ ] **Step 3: `quotes` — envio**

Mesmo padrão, `purpose=PURPOSE_QUOTE_SEND` (já importado no arquivo).

- [ ] **Step 4: `platform._send_invite`**

Este call site é o único que passa `token=`/`phone_id=` explícitos em vez de `profile=`
(exceção documentada na Onda 0, Task 8 — instância `TenantProfile` já detached fora da
`tenant_session`). Migrar para `enqueue` exige repensar esse detalhe: `enqueue` precisa do
`tenant_id` (já disponível) e NÃO precisa de `profile`/`token`/`phone_id` — quem resolve
credencial agora é o worker, dentro da PRÓPRIA `tenant_session` dele. Isso na verdade
**resolve** a razão de ser da exceção original (o detachment só importava para o envio síncrono
que lia `profile` fora da sessão) — o `enqueue` só precisa de
`tenant_id`/`recipient`/`message`/`purpose`/template resolvido, todos valores já extraídos
como strings simples ANTES do `with tenant_session` fechar (o código já faz isso hoje pro
`template_id`/`token`/`phone_id`).

Trocar:

```python
        if template is not None and template.status == STATUS_APPROVED:
            return whatsapp.send_template(
                to=phone, token=token or "", phone_id=phone_id or "",
                template_name=template.name, language=template.language,
                variables=[name, company, email, temp],  # ordem = PURPOSE_VARIABLE_SPECS
            )
        return whatsapp.send_text(to=phone, text=msg, token=token, phone_id=phone_id)
```

por (dentro de uma NOVA `tenant_session(tenant_id)` — a função `_send_invite` já roda com uma
sessão de tenant aberta para resolver o perfil; reaproveitar essa MESMA sessão pro `enqueue`,
já que ela ainda está aberta neste ponto, evita abrir uma terceira):

```python
        if template is not None and template.status == STATUS_APPROVED:
            notifications_service.enqueue(
                tdb, tenant_id=tenant_id, channel="whatsapp", recipient=phone, message=msg,
                purpose=PURPOSE_STAFF_INVITE, whatsapp_template_name=template.name,
                whatsapp_template_language=template.language,
                variables=[name, company, email, temp],  # ordem = PURPOSE_VARIABLE_SPECS
            )
        else:
            notifications_service.enqueue(
                tdb, tenant_id=tenant_id, channel="whatsapp", recipient=phone, message=msg,
                purpose=PURPOSE_STAFF_INVITE,
            )
        tdb.commit()
        return "queued"
```

**Atenção**: isso exige mover o bloco de envio para DENTRO do `with tenant_session(tenant_id) as
tdb:` que hoje só resolve o perfil (linhas ~291-295 antes da Onda 0) — reestruturar a função
para que o `if template is not None...`/`else` fiquem dentro do `with`, e o `token, phone_id =
...` capturado antes seja removido (não é mais necessário). Ler a função inteira
(`_send_invite`) antes de editar, para não quebrar o `return send_email(...)` do ramo
`delivery == "email"` (que fica FORA do `with`, inalterado).

Adicionar `from app.modules.notifications import service as notifications_service` ao topo.
Remover o import de `from app.core import whatsapp` SE não for mais usado em nenhum outro lugar
deste arquivo (`grep -n "whatsapp\." app/modules/platform/service.py` para confirmar).

- [ ] **Step 5: `funnels/service.py` — nó de WhatsApp (`action == "send_message"`)**

Este é o 5º ponto (a correção de framing do topo do plano). Adicionar a constante nova
`PURPOSE_FUNNEL_NODE = "funnel_node"` — não existe em `whatsapp_templates/models.py` porque o
nó do funil não é um dos 5 propósitos fixos daquele módulo (é conteúdo livre configurado pelo
usuário no builder, não um vínculo fixo); definir a constante localmente em
`funnels/service.py` mesmo, junto de onde é usada.

Trocar:

```python
        status = whatsapp.send_template(
            to=to_phone, profile=profile,
            template_name=tpl.name, language=tpl.language, variables=resolved_vars,
        )
        rendered = _render_template_preview(tpl.body_text, resolved_vars)
        db.add(Notification(
            tenant_id=tenant_id, channel="whatsapp", recipient=recipient,
            client_id=c.id, message=rendered, status=status,
        ))
```

por:

```python
        rendered = _render_template_preview(tpl.body_text, resolved_vars)
        notifications_service.enqueue(
            db, tenant_id=tenant_id, channel="whatsapp", recipient=recipient, client_id=c.id,
            message=rendered, purpose="funnel_node", whatsapp_template_name=tpl.name,
            whatsapp_template_language=tpl.language, whatsapp_template_variables=resolved_vars,
        )
```

Adicionar `from app.modules.notifications import service as notifications_service` ao topo.

- [ ] **Step 6: Ajustar os testes dos 4 arquivos**

Mesmo espírito do Task 3 Step 4 — cada teste que hoje monkeypatcha `whatsapp.send_template`/
`send_text` diretamente para esses 4 fluxos passa a monkeypatchar `notifications_service.enqueue`
(ou verificar o resultado indireto: uma `Notification` `pending` foi criada com `purpose`
correto). Localizar com `grep -n "whatsapp.send_template\|whatsapp.send_text\|core_whatsapp"
tests/test_contracts.py tests/test_quotes.py tests/test_funnels.py` e ajustar cada um.

- [ ] **Step 7: Rodar os 4 arquivos de teste**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_contracts.py tests/test_quotes.py tests/test_funnels.py tests/test_funnel_automation.py tests/test_platform.py -q`
Expected: mesmo total do Step 1 (mais os testes de platform, que não estavam no baseline —
anotar separadamente), todos verdes.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/contracts/service.py apps/api/app/modules/quotes/service.py apps/api/app/modules/platform/service.py apps/api/app/modules/funnels/service.py apps/api/tests/test_contracts.py apps/api/tests/test_quotes.py apps/api/tests/test_funnels.py
git commit -m "refactor: contracts/quotes/platform/funnels enfileiram em vez de enviar na hora (5º fluxo: nó do Funil)"
```

---

### Task 5: `on_client_moved` ganha `purpose` explícito

**Files:**
- Modify: `apps/api/app/modules/notifications/service.py`

**Interfaces:** nenhuma nova — só passa a usar o parâmetro já existente desde a Task 2.

- [ ] **Step 1: Localizar e ajustar**

Em `on_client_moved` (mesmo arquivo), o `enqueue(...)` já existente ganha `purpose=
PURPOSE_CLIENT_MOVED` (constante já importada no topo do arquivo desde antes da Onda 0).

- [ ] **Step 2: Rodar a suíte de notificações**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications.py -q`
Expected: mesmo total de antes — nenhum teste checa `expires_at` neste arquivo ainda (isso é
coberto por `test_notifications_purpose_expiry.py`, Task 2).

- [ ] **Step 3: Commit**

```bash
git add apps/api/app/modules/notifications/service.py
git commit -m "feat: on_client_moved passa purpose=client_moved ao enfileirar"
```

---

## Fase B — Retry com backoff (limitado pela validade) + freio anti-ban

### Task 6: `process_pending` expira o vencido e não finge sucesso

**Files:**
- Modify: `apps/api/app/modules/notifications/service.py`
- Modify: `apps/api/tests/test_notifications_queue.py`

**Interfaces:**
- Produces: `process_pending` marca `status="expired"` (novo valor) para `pending` com
  `expires_at` no passado, sem tentar entregar.

- [ ] **Step 1: Escrever o teste**

Acrescentar a `test_notifications_queue.py`:

```python
def test_process_pending_expires_past_due_without_attempting_delivery(db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    n = _pending(db)
    n.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    def _boom(**_k):
        raise AssertionError("não deveria tentar entregar notificação vencida")

    monkeypatch.setattr(whatsapp, "send_text", _boom)
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 1  # "processada" = decidida (expirada), não necessariamente entregue
    assert db.scalar(select(Notification)).status == "expired"


def test_process_pending_delivers_when_not_yet_expired(db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    n = _pending(db)
    n.expires_at = datetime.now(UTC) + timedelta(hours=1)
    db.commit()
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    service.process_pending(db, tenant_id=TENANT)
    assert db.scalar(select(Notification)).status == "sent"
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_queue.py -k expires -v`
Expected: FAIL (hoje `process_pending` sempre tenta entregar, ignorando `expires_at`).

- [ ] **Step 3: Implementar**

Em `process_pending`, logo no início do loop `for notification in pending:` (antes do `try` de
envio existente):

```python
    for notification in pending:
        if notification.expires_at is not None and notification.expires_at < datetime.now(UTC):
            notification.status = "expired"
            notification.attempts += 1
            processed += 1
            continue
        try:
            # ... corpo existente (send_email/send_template/send_text) ...
```

Adicionar `from datetime import UTC, datetime` ao topo (se ainda não presente — já deve estar,
da Task 2).

- [ ] **Step 4: Rodar de novo**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_queue.py -v`
Expected: todos passam (os 2 novos + os já existentes).

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/notifications/service.py apps/api/tests/test_notifications_queue.py
git commit -m "feat: process_pending marca 'expired' notificações vencidas, sem tentar entregar"
```

---

### Task 7: Retry com backoff exponencial, limitado pela validade

**Files:**
- Modify: `apps/api/app/modules/notifications/service.py`
- Modify: `apps/api/tests/test_notifications_queue.py`

**Interfaces:**
- Produces: uma falha de entrega (`status="failed"` hoje é TERMINAL) passa a reagendar via
  `next_attempt_at` (backoff `2**attempts` minutos, capado em 60min), MAS nunca além de
  `expires_at`. `process_pending` só tenta `pending` cujo `next_attempt_at` já passou (ou é
  `None` — primeira tentativa).

- [ ] **Step 1: Escrever os testes**

```python
def test_failed_delivery_reschedules_with_backoff_within_validity(db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    n = _pending(db, message="boom")
    n.expires_at = datetime.now(UTC) + timedelta(hours=2)
    db.commit()

    def _flaky(*, to, text, profile=None, token=None, phone_id=None):
        raise RuntimeError("provedor caiu")

    monkeypatch.setattr(whatsapp, "send_text", _flaky)
    service.process_pending(db, tenant_id=TENANT)
    db.refresh(n)
    assert n.status == "pending"  # NÃO "failed" terminal — ainda dentro da validade
    assert n.attempts == 1
    assert n.next_attempt_at is not None
    assert n.next_attempt_at > datetime.now(UTC)


def test_process_pending_skips_notification_before_next_attempt_at(db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    n = _pending(db)
    n.next_attempt_at = datetime.now(UTC) + timedelta(minutes=10)
    db.commit()

    def _boom(**_k):
        raise AssertionError("não deveria tentar antes de next_attempt_at")

    monkeypatch.setattr(whatsapp, "send_text", _boom)
    processed = service.process_pending(db, tenant_id=TENANT)
    assert processed == 0
    db.refresh(n)
    assert n.status == "pending"


def test_backoff_never_schedules_past_expiry(db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    n = _pending(db, message="boom")
    n.expires_at = datetime.now(UTC) + timedelta(minutes=5)  # validade curta
    n.attempts = 5  # backoff 2**5=32min já estouraria a validade de 5min
    db.commit()

    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: (_ for _ in ()).throw(
            RuntimeError("falha")
        ),
    )
    service.process_pending(db, tenant_id=TENANT)
    db.refresh(n)
    # o backoff bateria além da validade — a notificação expira em vez de reagendar pra depois
    # do próprio prazo de validade.
    assert n.status == "expired"
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_queue.py -k "backoff or next_attempt" -v`
Expected: FAIL (campo `next_attempt_at` ainda não é lido/escrito por `process_pending`).

- [ ] **Step 3: Implementar**

Ajustar a query de seleção (topo de `process_pending`) para pular quem ainda não venceu o
próprio `next_attempt_at`:

```python
    now = datetime.now(UTC)
    pending = list(
        db.scalars(
            select(Notification)
            .where(
                Notification.status == "pending",
                (Notification.next_attempt_at.is_(None))
                | (Notification.next_attempt_at <= now),
            )
            .order_by(Notification.created_at)
            .limit(limit)
        ).all()
    )
```

E no bloco `except Exception as exc:` (falha de entrega), trocar:

```python
        except Exception as exc:  # noqa: BLE001 — isola a falha de UMA notificação (IV2)
            logger.exception(
                "[notifications:process_pending] falha ao enviar id=%s", notification.id
            )
            notification.status = "failed"
            notification.last_error = str(exc)[:500]
```

por:

```python
        except Exception as exc:  # noqa: BLE001 — isola a falha de UMA notificação (IV2)
            logger.exception(
                "[notifications:process_pending] falha ao enviar id=%s", notification.id
            )
            notification.last_error = str(exc)[:500]
            backoff_minutes = min(2 ** notification.attempts, 60)
            candidate_next = now + timedelta(minutes=backoff_minutes)
            if notification.expires_at is not None and candidate_next > notification.expires_at:
                notification.status = "expired"  # o backoff estouraria a validade — expira já
            else:
                notification.status = "pending"  # continua pending — process_pending tenta de novo
                notification.next_attempt_at = candidate_next
```

- [ ] **Step 4: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_queue.py -v`
Expected: todos PASS.

- [ ] **Step 5: Rodar a suíte de notificações inteira + worker (regressão)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications.py tests/test_notifications_queue.py tests/test_worker.py -q`
Expected: verde. **Atenção**: `test_failure_is_isolated_and_recorded` (já existente, Onda 0)
assumia `status == "failed"` como TERMINAL — como a mensagem "boom" nesse teste não seta
`expires_at`, ela cai no ramo `expires_at is None` → `candidate_next > None` é sempre falso em
Python (comparação com None lança `TypeError`) — **checar isso explicitamente**: a condição
`if notification.expires_at is not None and candidate_next > notification.expires_at` já
protege contra isso (curto-circuito do `and`), então `expires_at=None` cai direto no `else`
(vira `pending` de novo, não mais `failed` fixo). Isso MUDA o comportamento esperado por
`test_failure_is_isolated_and_recorded` — o teste precisa ser ajustado: onde antes esperava
`status == "failed"`, agora espera `status == "pending"` com `attempts == 1` e
`next_attempt_at` no futuro (retry agendado, não é mais terminal). Ajustar essa asserção.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/notifications/service.py apps/api/tests/test_notifications_queue.py
git commit -m "feat: retry com backoff exponencial (capado em 60min), nunca além da validade"
```

---

### Task 8: Freio anti-ban (espaçamento + teto diário + aquecimento) — só Evolution

**Files:**
- Modify: `apps/api/app/modules/notifications/service.py`
- Create: `apps/api/tests/test_notifications_throttle.py`

**Interfaces:**
- Produces: `process_pending` entrega no máximo 5 notificações Evolution por sweep por tenant,
  respeita um teto diário por tenant (20/50/150 conforme dias desde a conexão — spec §7), e as
  que excedem o teto ficam `pending` (não `failed`, não `expired` — só esperam o próximo dia).
  **Não se aplica** a `channel="email"` nem a tenants no transporte Meta.

- [ ] **Step 1: Escrever os testes**

```python
"""Testes do freio anti-ban (Onda 3 §7) — só para tenants no transporte Evolution. Resposta a
quem escreveu primeiro (inbox) não passa por aqui — o freio vive só em process_pending."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core import whatsapp
from app.modules.notifications import service
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service
from app.modules.whatsapp_session.models import PublicWhatsappInstance

TENANT_ID = "44444444-4444-4444-4444-444444444444"


def _evolution_tenant(db, *, connected_days_ago: int = 30):
    profile = settings_service.get_profile(db, TENANT_ID)
    profile.whatsapp_provider = "evolution"
    instance = PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="s",
        last_status="connected",
    )
    db.add(instance)
    db.commit()
    # `created_at` do TimestampMixin tem server_default=now() — sobrescreve pra simular
    # conexão antiga (aquecimento já passado).
    instance.created_at = datetime.now(UTC) - timedelta(days=connected_days_ago)
    db.commit()
    return profile, instance


def _enqueue_n(db, n: int, *, message_prefix="msg"):
    for i in range(n):
        service.enqueue(
            db, tenant_id=TENANT_ID, channel="whatsapp", recipient=f"55{i:011d}",
            message=f"{message_prefix}-{i}",
        )
    db.commit()


def test_evolution_tenant_respects_max_per_sweep(db, monkeypatch: pytest.MonkeyPatch) -> None:
    _evolution_tenant(db)
    _enqueue_n(db, 8)
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    processed = service.process_pending(db, tenant_id=TENANT_ID)
    assert processed <= 5  # teto por sweep, spec §7


def test_meta_tenant_is_not_throttled(db, monkeypatch: pytest.MonkeyPatch) -> None:
    # Sem instância Evolution — profile.whatsapp_provider permanece None/"meta". Sem freio.
    _enqueue_n(db, 8)
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    processed = service.process_pending(db, tenant_id=TENANT_ID)
    assert processed == 8  # nenhum teto — só Evolution é limitado


def test_evolution_tenant_respects_daily_cap_for_new_connection(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    _evolution_tenant(db, connected_days_ago=1)  # 1-3 dias = teto 20/dia (spec §7)
    _enqueue_n(db, 25)
    monkeypatch.setattr(
        whatsapp, "send_text",
        lambda *, to, text, profile=None, token=None, phone_id=None: "sent",
    )
    total_delivered = 0
    for _ in range(10):  # múltiplos sweeps — o teto é DIÁRIO, não por sweep
        total_delivered += service.process_pending(db, tenant_id=TENANT_ID)
    assert total_delivered <= 20


def test_inbox_reply_does_not_count_toward_daily_cap(db) -> None:
    """O freio vive só em process_pending — enviar pelo inbox (síncrono, resposta a quem
    escreveu primeiro) não incrementa o contador diário. Este teste apenas documenta a garantia
    estrutural: `send_reply_text` (whatsapp_inbox) não importa nem chama nada deste módulo de
    throttle — não há acoplamento a testar além de "o módulo de throttle não é importado lá"."""
    import ast
    from pathlib import Path

    inbox_service_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "modules" / "whatsapp_inbox" / "service.py"
    )
    tree = ast.parse(inbox_service_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "app.modules.notifications.service" not in imported_modules
```

- [ ] **Step 2: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_throttle.py -v`
Expected: `test_evolution_tenant_respects_max_per_sweep` e o teste de teto diário FALHAM (nenhum
freio implementado ainda); os outros 2 passam (já são verdade hoje, viram testes de
regressão/documentação).

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/notifications/service.py`, acrescentar antes de `process_pending`:

```python
# Freio anti-ban (spec §7) — só para o transporte Evolution. Fixo no código, não configurável
# pelo tenant (mesma razão da banda de conferência do Epic 8: quem ajusta o próprio limite
# ajusta até ele parar de proteger).
_EVOLUTION_MAX_PER_SWEEP = 5
_EVOLUTION_WARMUP_CAPS = [
    (3, 20),   # dias 1-3 desde a conexão: 20/dia
    (7, 50),   # dias 4-7: 50/dia
]
_EVOLUTION_STEADY_CAP = 150  # dia 8+


def _evolution_daily_cap(instance: "PublicWhatsappInstance") -> int:
    days_connected = (datetime.now(UTC) - instance.created_at).days
    for max_days, cap in _EVOLUTION_WARMUP_CAPS:
        if days_connected <= max_days:
            return cap
    return _EVOLUTION_STEADY_CAP


def _evolution_sent_today(db: Session, *, tenant_id: str) -> int:
    """Conta quantas notificações whatsapp JÁ FORAM entregues hoje (status != pending/expired)
    — usado só pro teto diário Evolution."""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.channel == "whatsapp",
            Notification.status.in_(("sent", "logged")),
            Notification.updated_at >= today_start,
        )
    ) or 0
```

Adicionar `from sqlalchemy import func, select` (ajustar import existente de `select`) e
importar `PublicWhatsappInstance` com `from app.modules.whatsapp_session.models import
PublicWhatsappInstance` (só sob `TYPE_CHECKING` se for usado apenas em type hint, ou import
direto no topo — `whatsapp_session` não importa `notifications`, então não há ciclo).

Modificar o início de `process_pending` para resolver o teto ANTES do loop:

```python
    profile = settings_service.get_profile(db, tenant_id)
    max_this_sweep = limit
    if profile.whatsapp_provider == "evolution":
        instance = db.get(PublicWhatsappInstance, f"e1p-{tenant_id}")
        if instance is not None:
            daily_cap = _evolution_daily_cap(instance)
            already_sent = _evolution_sent_today(db, tenant_id=tenant_id)
            remaining_today = max(0, daily_cap - already_sent)
            max_this_sweep = min(limit, _EVOLUTION_MAX_PER_SWEEP, remaining_today)
```

E trocar o `.limit(limit)` da query de seleção por `.limit(max_this_sweep)` — com
`max_this_sweep == 0`, a query devolve lista vazia (nenhuma tentativa, nem para contar contra
o teto de sweep seguinte).

- [ ] **Step 4: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications_throttle.py -v`
Expected: 4 testes, PASS.

- [ ] **Step 5: Rodar a suíte de notificações + worker inteira (regressão do freio em tenants Meta)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_notifications.py tests/test_notifications_queue.py tests/test_worker.py -q`
Expected: verde — nenhum teste pré-existente usa `whatsapp_provider="evolution"`, então
`max_this_sweep` continua igual a `limit` (comportamento de hoje) pra todos eles.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/notifications/service.py apps/api/tests/test_notifications_throttle.py
git commit -m "feat: freio anti-ban (5/sweep, teto diário com aquecimento 20/50/150) só p/ Evolution"
```

---

## Fase C — Webhook interno da Evolution + bandeja "Não identificados"

### Task 9: `client_id` nullable + bandeja "Não identificados"

**Files:**
- Create: `apps/api/migrations/versions/0063_whatsapp_message_client_nullable.py`
- Modify: `apps/api/app/modules/whatsapp_inbox/models.py`
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py` (`list_conversations`)
- Create: `apps/api/tests/test_whatsapp_inbox_unidentified.py`

**Interfaces:**
- Produces: `WhatsappMessage.client_id: str | None`. `list_conversations` devolve uma entrada
  extra `{"client_id": None, "client_name": "Não identificados", ...}` quando existem mensagens
  sem cliente resolvido.

- [ ] **Step 1: Migration**

```python
"""whatsapp_messages.client_id vira nullable (Onda 3 — bandeja "não identificados" p/ @lid)

Revision ID: 0063
Revises: 0062
Create Date: 2026-07-30

Quando o WhatsApp entrega `@lid` no lugar do telefone (esconde o número), não dá pra resolver
o cliente com confiança — em vez de adivinhar por heurística (erra em silêncio, ver estudo do
Orbitask na spec), a mensagem fica com client_id=NULL e cai numa bandeja "Não identificados" na
tela de Conversas; o atendente liga manualmente ao cliente certo com um clique.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("whatsapp_messages", "client_id", nullable=True)


def downgrade() -> None:
    # Nenhuma mensagem com client_id NULL deveria existir se o downgrade for aplicado
    # imediatamente após o upgrade sem uso real — mas um downgrade em produção com dados reais
    # exigiria decidir o que fazer com linhas NULL primeiro (fora de escopo: dívida documentada).
    op.alter_column("whatsapp_messages", "client_id", nullable=False)
```

- [ ] **Step 2: Campo ORM**

Em `apps/api/app/modules/whatsapp_inbox/models.py`, trocar:

```python
    client_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
```

por:

```python
    # None = não identificado (ex.: WhatsApp entregou @lid no lugar do telefone) — cai na
    # bandeja "Não identificados" em vez de adivinhar por heurística (ver Onda 3 da spec).
    client_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
```

- [ ] **Step 3: Escrever o teste da bandeja**

```python
"""Testes da bandeja "Não identificados" — mensagens sem client_id resolvido (Onda 3, ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §6)."""
from __future__ import annotations

from app.modules.whatsapp_inbox import service
from app.modules.whatsapp_inbox.models import DIRECTION_IN, WhatsappMessage

TENANT_ID = "55555555-5555-5555-5555-555555555555"


def test_list_conversations_includes_unidentified_bucket_when_present(db) -> None:
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, client_id=None, direction=DIRECTION_IN, kind="text",
        text_body="oi, sou eu", wa_message_id="wa-1",
    ))
    db.commit()
    conversations = service.list_conversations(db, TENANT_ID)
    unidentified = [c for c in conversations if c["client_id"] is None]
    assert len(unidentified) == 1
    assert unidentified[0]["client_name"] == "Não identificados"


def test_list_conversations_omits_unidentified_bucket_when_absent(db) -> None:
    conversations = service.list_conversations(db, TENANT_ID)
    assert all(c["client_id"] is not None for c in conversations)
```

- [ ] **Step 4: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_unidentified.py -v`
Expected: FAIL (o modelo ainda tem `client_id` NOT NULL — a inserção do teste já quebraria; ou,
se a migration/ORM Step 2 já tiver sido aplicada primeiro, falha por `list_conversations` ainda
não tratar `client_id=None` como bucket próprio, e sim tentar `db.get(Client, None)` que devolve
`None` e hoje faz o `continue` — a mensagem simplesmente some da lista).

- [ ] **Step 5: Implementar em `list_conversations`**

Em `apps/api/app/modules/whatsapp_inbox/service.py`, dentro de `list_conversations`, o trecho:

```python
    for client_id, last_msg in last_msgs.items():
        client = db.get(Client, client_id)
        if client is None:
            continue
```

precisa tratar `client_id is None` como o bucket "Não identificados" em vez de descartar:

```python
    for client_id, last_msg in last_msgs.items():
        if client_id is None:
            out.append({
                "client_id": None,
                "client_name": "Não identificados",
                "client_phone": "",
                "last_message_at": last_msg.created_at,
                "last_message_preview": last_msg.text_body or f"[{last_msg.kind}]",
                "unread": last_msg.direction == DIRECTION_IN,
            })
            continue
        client = db.get(Client, client_id)
        if client is None:
            continue
```

- [ ] **Step 6: Rodar de novo**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_unidentified.py -v`
Expected: 2 testes, PASS.

- [ ] **Step 7: Rodar a suíte inteira do inbox (regressão)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_service.py tests/test_whatsapp_inbox_reply.py tests/test_whatsapp_inbox_webhook.py tests/test_whatsapp_inbox_models.py tests/test_whatsapp_inbox_media_worker.py -q`
Expected: mesmo total de antes, verde.

- [ ] **Step 8: Commit**

```bash
git add apps/api/migrations/versions/0063_whatsapp_message_client_nullable.py apps/api/app/modules/whatsapp_inbox/models.py apps/api/app/modules/whatsapp_inbox/service.py apps/api/tests/test_whatsapp_inbox_unidentified.py
git commit -m "feat: client_id nullable + bandeja 'Não identificados' (ao invés de heurística de @lid)"
```

---

### Task 10: `InboundMessage` — parser genérico (Meta + Evolution)

**Files:**
- Modify: `apps/api/app/core/whatsapp/providers/meta.py`
- Modify: `apps/api/app/core/whatsapp/providers/evolution.py`
- Create: `apps/api/tests/test_whatsapp_inbound_parsing.py`

**Interfaces:**
- Produces: `InboundMessage` (dataclass congelado, definido em `providers/meta.py` e
  reexportado — ou num módulo `app/core/whatsapp/inbound.py` novo, para não acoplar
  `evolution.py` a importar de `meta.py`): `wa_message_id: str`, `from_phone: str | None`,
  `kind: str`, `text_body: str`, `media_ref: str | None`, `push_name: str`.
  `meta.parse_inbound(payload: dict) -> list[InboundMessage]`,
  `evolution.parse_inbound(payload: dict) -> list[InboundMessage]`.

- [ ] **Step 1: Criar `app/core/whatsapp/inbound.py` com o dataclass**

```python
"""Formato normalizado de mensagem recebida — o que sobra depois que cada provider (Meta,
Evolution) traduz o próprio formato de payload. De `whatsapp_inbox/service.py` pra dentro
(resolver cliente, criar lead, deduplicar, enfileirar mídia pendente) nada sabe qual provider
originou a mensagem — só enxerga isto. Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §6.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    wa_message_id: str
    from_phone: str | None  # só dígitos, sem "+". None quando o provider não entrega o número
    kind: str  # text | image | audio | document | video
    text_body: str
    media_ref: str | None  # referência de mídia opaca (meta_media_id, ou base64 da Evolution)
    push_name: str
```

- [ ] **Step 2: Escrever os testes de parsing (Meta + Evolution)**

```python
"""Testes de parse_inbound — normaliza o payload de cada provider em InboundMessage (Onda 3).
Payloads de exemplo reais/realistas de cada provider."""
from __future__ import annotations

from app.core.whatsapp.inbound import InboundMessage
from app.core.whatsapp.providers import evolution, meta

META_TEXT_PAYLOAD = {
    "entry": [{
        "changes": [{
            "value": {
                "contacts": [{"profile": {"name": "Maria Cliente"}}],
                "messages": [{
                    "id": "wamid.123", "from": "5511988887777", "type": "text",
                    "text": {"body": "Olá, tudo bem?"},
                }],
            }
        }]
    }]
}

EVOLUTION_TEXT_PAYLOAD = {
    "data": {
        "key": {"id": "3EB0ABC123", "remoteJid": "5511988887777@s.whatsapp.net"},
        "pushName": "Maria Cliente",
        "message": {"conversation": "Olá, tudo bem?"},
    }
}

EVOLUTION_LID_PAYLOAD = {
    "data": {
        "key": {"id": "3EB0DEF456", "remoteJid": "123456789@lid"},
        "pushName": "Cliente Sem Numero",
        "message": {"conversation": "Oi"},
    }
}


def test_meta_parse_inbound_text() -> None:
    messages = meta.parse_inbound(META_TEXT_PAYLOAD)
    assert messages == [InboundMessage(
        wa_message_id="wamid.123", from_phone="5511988887777", kind="text",
        text_body="Olá, tudo bem?", media_ref=None, push_name="Maria Cliente",
    )]


def test_evolution_parse_inbound_text_with_phone() -> None:
    messages = evolution.parse_inbound(EVOLUTION_TEXT_PAYLOAD)
    assert messages == [InboundMessage(
        wa_message_id="3EB0ABC123", from_phone="5511988887777", kind="text",
        text_body="Olá, tudo bem?", media_ref=None, push_name="Maria Cliente",
    )]


def test_evolution_parse_inbound_lid_has_no_phone() -> None:
    """@lid esconde o telefone — from_phone=None, NUNCA adivinhado (ver Task 9, bandeja
    "Não identificados")."""
    messages = evolution.parse_inbound(EVOLUTION_LID_PAYLOAD)
    assert messages[0].from_phone is None
    assert messages[0].wa_message_id == "3EB0DEF456"
    assert messages[0].push_name == "Cliente Sem Numero"


def test_evolution_parse_inbound_malformed_payload_returns_empty() -> None:
    assert evolution.parse_inbound({"unexpected": "shape"}) == []
    assert evolution.parse_inbound({}) == []
```

- [ ] **Step 3: Rodar para confirmar que falha**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbound_parsing.py -v`
Expected: FAIL (`ModuleNotFoundError`/`AttributeError` — nada disso existe ainda).

- [ ] **Step 4: Implementar `meta.parse_inbound`**

Em `apps/api/app/core/whatsapp/providers/meta.py`, acrescentar (reaproveitando a MESMA lógica
de extração hoje em `whatsapp_inbox/service.py::_extract_messages`, mas devolvendo
`InboundMessage` em vez de tuplas cruas):

```python
from app.core.whatsapp.inbound import InboundMessage


def parse_inbound(payload: dict) -> list[InboundMessage]:
    """Extrai as mensagens do formato aninhado do payload da Meta. Payload não confiável (a
    Meta não garante o shape interno) — captura a classe inteira de erro de shape inesperado."""
    out: list[InboundMessage] = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                contacts = value.get("contacts", [])
                push_name = contacts[0]["profile"]["name"] if contacts else ""
                for msg in value.get("messages", []):
                    if not isinstance(msg, dict):
                        continue
                    wa_message_id = msg.get("id", "")
                    from_phone = msg.get("from") or None
                    kind = msg.get("type", "text")
                    text_body = ""
                    media_ref = None
                    if kind == "text":
                        text_body = msg.get("text", {}).get("body", "")
                    elif kind in ("image", "audio", "document", "video"):
                        media_obj = msg.get(kind, {})
                        text_body = media_obj.get("caption", "")
                        media_ref = media_obj.get("id")
                    else:
                        kind = "text"
                        text_body = "[tipo de mensagem não suportado]"
                    out.append(InboundMessage(
                        wa_message_id=wa_message_id, from_phone=from_phone, kind=kind,
                        text_body=text_body, media_ref=media_ref, push_name=push_name,
                    ))
    except (AttributeError, TypeError, KeyError):
        return []
    return out
```

- [ ] **Step 5: Implementar `evolution.parse_inbound`**

Em `apps/api/app/core/whatsapp/providers/evolution.py`:

```python
from app.core.whatsapp.inbound import InboundMessage


def parse_inbound(payload: dict) -> list[InboundMessage]:
    """Extrai a mensagem do formato da Evolution API (evento `messages.upsert`). `@lid` no
    lugar do telefone → `from_phone=None` — NUNCA adivinhado por heurística (ver bandeja "Não
    identificados", Onda 3 Task 9)."""
    try:
        data = payload.get("data", payload)
        key = data.get("key", {})
        remote_jid = key.get("remoteJid", "")
        wa_message_id = key.get("id", "")
        if not wa_message_id:
            return []
        from_phone = None
        if remote_jid.endswith("@s.whatsapp.net"):
            from_phone = remote_jid.split("@")[0]
        push_name = data.get("pushName", "")
        message = data.get("message", {})
        text_body = message.get("conversation", "") or message.get(
            "extendedTextMessage", {}
        ).get("text", "")
        return [InboundMessage(
            wa_message_id=wa_message_id, from_phone=from_phone, kind="text",
            text_body=text_body, media_ref=None, push_name=push_name,
        )]
    except (AttributeError, TypeError, KeyError):
        return []
```

*(Mídia inbound da Evolution — payload real de imagem/áudio/documento — fica como dívida
registrada no Task 12: o formato exato varia por tipo e exigiria payloads de exemplo de uma
instância real para não adivinhar o shape; texto cobre o caminho principal desta onda.)*

- [ ] **Step 6: Rodar de novo — todos devem passar**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbound_parsing.py -v`
Expected: 5 testes, PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/core/whatsapp/inbound.py apps/api/app/core/whatsapp/providers/meta.py apps/api/app/core/whatsapp/providers/evolution.py apps/api/tests/test_whatsapp_inbound_parsing.py
git commit -m "feat: InboundMessage — parse_inbound normalizado (Meta + Evolution)"
```

---

### Task 11: Rota interna do webhook Evolution + `ingest_webhook_payload` genérico

**Files:**
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py`
- Modify: `apps/api/app/modules/whatsapp_inbox/router.py`
- Modify: `apps/api/app/modules/whatsapp_session/service.py` (resolver por `webhook_secret`)
- Create: `apps/api/tests/test_whatsapp_inbox_evolution_webhook.py`

**Interfaces:**
- Produces: `POST /internal/whatsapp/evolution/webhook/{webhook_secret}` — resolve
  `PublicWhatsappInstance` pelo secret (path, não query), reaproveita
  `ingest_webhook_payload` (agora genérico, recebendo `list[InboundMessage]` já parseada em vez
  do payload cru + provider).
- `whatsapp_session.service.resolve_by_webhook_secret(db, *, webhook_secret) ->
  PublicWhatsappInstance | None`.

- [ ] **Step 1: Refatorar `ingest_webhook_payload` para receber `list[InboundMessage]`**

Em `apps/api/app/modules/whatsapp_inbox/service.py`, trocar a assinatura de
`ingest_webhook_payload(db, *, tenant_id, payload: dict)` por
`ingest_webhook_payload(db, *, tenant_id, messages: list[InboundMessage])` — o corpo do loop
(`for msg, contact_name in _extract_messages(payload):`) vira
`for msg in messages:`, e os acessos `msg.get("id")`/`msg.get("from", "")`/etc. viram
`msg.wa_message_id`/`msg.from_phone`/`msg.kind`/`msg.text_body`/`msg.media_ref`/`msg.push_name`.

**Ponto crítico — o `@lid` sem telefone**: onde hoje `_get_or_create_client(db, tenant_id=...,
phone=from_number, name=contact_name)` sempre resolve/cria um `Client`, a versão nova precisa
tratar `msg.from_phone is None`: **não chama `_get_or_create_client`**, grava
`WhatsappMessage(client_id=None, ...)` direto (a Task 9 já tornou a coluna nullable e a bandeja
"Não identificados" já existe pra isso).

```python
            if msg.from_phone is None:
                client_id = None
            else:
                client = _get_or_create_client(
                    db, tenant_id=tenant_id, phone=msg.from_phone, name=msg.push_name
                )
                client_id = client.id
            db.add(WhatsappMessage(
                tenant_id=tenant_id, client_id=client_id, direction=DIRECTION_IN, kind=msg.kind,
                text_body=msg.text_body,
                media_status=MEDIA_STATUS_PENDING if msg.media_ref else MEDIA_STATUS_NONE,
                wa_message_id=msg.wa_message_id,
                meta_media_id=msg.media_ref if msg.kind != "text" else None,
                status="sent",
            ))
            audit.record(
                db, tenant_id=tenant_id, actor="whatsapp:inbox",
                action="whatsapp_inbox.message.received", target=client_id or "unidentified",
            )
```

O resto da função (dedupe por `wa_message_id`, isolamento de falha por mensagem, commit por
mensagem) **não muda** — só a fonte dos campos.

O router da Meta (`receive_webhook`) precisa ser ajustado para chamar `meta.parse_inbound(payload)`
e passar `messages=` em vez de `payload=` — ver Step 3.

- [ ] **Step 2: `resolve_by_webhook_secret` em `whatsapp_session/service.py`**

```python
def resolve_by_webhook_secret(db: Session, *, webhook_secret: str) -> PublicWhatsappInstance | None:
    """Resolve a instância pelo segredo do webhook — chamado numa sessão SEM tenant (`get_db`),
    ANTES de qualquer autenticação, mesmo padrão de `whatsapp_inbox.resolve_account`. Percorre
    todas as instâncias comparando o valor DECIFRADO (o segredo não é indexável cifrado) — custo
    aceitável pelo volume esperado (uma linha por tenant conectado, não por mensagem)."""
    for instance in db.scalars(select(PublicWhatsappInstance)).all():
        if instance.webhook_secret == webhook_secret:
            return instance
    return None
```

Adicionar `from sqlalchemy import select` ao topo se ainda não importado.

- [ ] **Step 3: Rota interna no router**

Em `apps/api/app/modules/whatsapp_inbox/router.py`, ajustar o import de `service` da Meta
(`receive_webhook` já existente) para usar `meta.parse_inbound` em vez de passar o payload cru:

```python
    with session_factory(account.tenant_id) as tdb:
        try:
            messages = meta.parse_inbound(payload)
            service.ingest_webhook_payload(tdb, tenant_id=account.tenant_id, messages=messages)
        except service.WhatsappInboxError as e:
            raise _err(e) from e
```

(Import `from app.core.whatsapp.providers import meta` no topo do router.)

E acrescentar a rota nova, na mesma `public_router` (ou um `internal_router` próprio — usar um
`APIRouter` novo, `internal_router = APIRouter(prefix="/internal/whatsapp", tags=
["whatsapp-internal"])`, já que **não** deve aparecer listado como rota pública-facing de
propósito, ainda que tecnicamente acessível pelo mesmo `app.include_router`):

```python
@internal_router.post("/evolution/webhook/{webhook_secret}")
async def receive_evolution_webhook(
    webhook_secret: str,
    request: Request,
    db: Session = Depends(get_db),
    session_factory=Depends(get_tenant_session_factory),
) -> dict:
    """Só alcançável de DENTRO da rede Docker (a Evolution não tem rota publicada pelo
    Traefik/Caddy — ver infra da Onda 1). O segredo no path é defesa em profundidade, não a
    garantia primária (que é o isolamento de rede)."""
    instance = whatsapp_session_service.resolve_by_webhook_secret(
        db, webhook_secret=webhook_secret
    )
    if instance is None:
        raise HTTPException(status_code=404, detail="Instância não encontrada")
    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON inválido")

    messages = evolution.parse_inbound(payload)
    with session_factory(instance.tenant_id) as tdb:
        service.ingest_webhook_payload(tdb, tenant_id=instance.tenant_id, messages=messages)
    return {"status": "ok"}
```

Adicionar os imports: `from app.core.whatsapp.providers import evolution` e
`from app.modules.whatsapp_session import service as whatsapp_session_service`. Registrar
`internal_router` em `app/modules/__init__.py` (mesmo padrão dos outros `_public_router`).

- [ ] **Step 4: Escrever os testes do webhook interno**

```python
"""Testes de POST /internal/whatsapp/evolution/webhook/{webhook_secret} (Onda 3 §6)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.modules.settings import service as settings_service
from app.modules.whatsapp_session.models import PublicWhatsappInstance

TENANT_ID = "66666666-6666-6666-6666-666666666666"

EVOLUTION_PAYLOAD = {
    "data": {
        "key": {"id": "3EB0XYZ", "remoteJid": "5511988887777@s.whatsapp.net"},
        "pushName": "Cliente Teste",
        "message": {"conversation": "Oi, preciso de ajuda"},
    }
}


def test_webhook_creates_lead_and_message(client: TestClient, db) -> None:
    settings_service.get_profile(db, TENANT_ID)
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="segredo-123",
        last_status="connected",
    ))
    db.commit()

    resp = client.post(
        "/internal/whatsapp/evolution/webhook/segredo-123", json=EVOLUTION_PAYLOAD,
    )
    assert resp.status_code == 200


def test_webhook_unknown_secret_returns_404(client: TestClient) -> None:
    resp = client.post(
        "/internal/whatsapp/evolution/webhook/segredo-que-nao-existe", json=EVOLUTION_PAYLOAD,
    )
    assert resp.status_code == 404


def test_webhook_lid_message_lands_in_unidentified_bucket(client: TestClient, db) -> None:
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret="segredo-456",
        last_status="connected",
    ))
    db.commit()
    lid_payload = {
        "data": {
            "key": {"id": "3EB0LID", "remoteJid": "999999@lid"},
            "pushName": "Sem Numero",
            "message": {"conversation": "Oi"},
        }
    }
    resp = client.post(
        "/internal/whatsapp/evolution/webhook/segredo-456", json=lid_payload,
    )
    assert resp.status_code == 200
```

- [ ] **Step 5: Rodar para confirmar que falha, depois implementar e rodar de novo**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_evolution_webhook.py -v`
Expected primeiro FAIL (rota/função ainda não existem), depois PASS após os Steps 1-3.

- [ ] **Step 6: Rodar a suíte inteira do inbox + webhook Meta (regressão)**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_service.py tests/test_whatsapp_inbox_webhook.py tests/test_whatsapp_inbox_reply.py tests/test_whatsapp_inbox_models.py tests/test_whatsapp_inbox_media_worker.py tests/test_whatsapp_inbox_unidentified.py tests/test_whatsapp_inbound_parsing.py -q`
Expected: verde. **Se algum teste de `test_whatsapp_inbox_webhook.py` quebrar** por chamar
`ingest_webhook_payload(db, tenant_id=..., payload=...)` diretamente (assinatura antiga) em vez
de passar por `receive_webhook`, ajustar essas chamadas para `messages=meta.parse_inbound(payload)`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/whatsapp_inbox/service.py apps/api/app/modules/whatsapp_inbox/router.py apps/api/app/modules/whatsapp_session/service.py apps/api/app/modules/__init__.py apps/api/tests/test_whatsapp_inbox_evolution_webhook.py
git commit -m "feat: webhook interno da Evolution (POST /internal/whatsapp/evolution/webhook/{secret})"
```

---

### Task 12: Gate final — suíte completa + ruff + registro de dívidas

**Files:** nenhum novo. Task de verificação + atualização de dívidas conhecidas na spec.

- [ ] **Step 1: Backend completo**

Run (a partir de `apps/api/`):
```bash
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m pytest -q -m "not rls_e2e"
```
Expected: `ruff check .` limpo; pytest verde, total = 1096 (fim da Onda 2, já mesclada com Epic
8) + os novos desta onda.

- [ ] **Step 2: `alembic heads` — uma única head**

Run: `./.venv/Scripts/python.exe -m alembic heads`
Expected: uma linha só, `0063 (head)` — encadeamento linear 0061→0062→0063 sem bifurcação.

- [ ] **Step 3: Confirmar zero edição em teste fora do previsto**

Run: `git diff --stat <tip-da-Onda-2> -- apps/api/tests/`
Expected: só os arquivos explicitamente listados nas tasks desta onda (Task 3/4 tocam
receivables/contracts/quotes/funnels/platform de propósito; os demais são todos novos).

- [ ] **Step 4: Atualizar a seção "Dívidas conhecidas" da spec**

Em `docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md`, seção 12,
acrescentar:

```markdown
- **Mídia inbound da Evolution** (imagem/áudio/documento) não tem parser ainda — só texto.
  Payload de exemplo real de uma instância viva é pré-requisito antes de implementar, para não
  adivinhar o shape (mesmo cuidado já tomado com o parser de texto).
- **`resolve_by_webhook_secret` é O(n) nas instâncias conectadas** (varre todas comparando o
  segredo decifrado) — aceitável pelo volume esperado (uma linha por tenant conectado, não por
  mensagem), mas não escala indefinidamente. Se o volume de tenants Evolution crescer muito,
  considerar um índice sobre um HASH do segredo (não o valor cifrado em si).
```

---

## Task 13: Push + PR/checks

**Files:** nenhum (git/GitHub).

- [ ] **Step 1: Push**

```bash
git push
```

- [ ] **Step 2: Atualizar a descrição do PR** com a seção "Onda 3 — Webhook + Fila com Validade
+ Freio Anti-Ban", registrando explicitamente a correção de framing (5 fluxos migrados, não 4)
e o achado de que contracts/quotes não tinham impacto de frontend (o `status` que a tela lê é o
workflow do documento, não o status de entrega).

- [ ] **Step 3: Verificar os checks**

Run: `gh pr checks --watch`
Expected: os 4 checks obrigatórios verdes. Corrigir e re-push se algo falhar — inclusive
re-verificar `alembic heads` contra a `main` mais recente (o mesmo tipo de colisão que ocorreu
entre a Onda 2 e o Epic 8 pode se repetir se outro branch mesclar migrations nesse meio-tempo).
