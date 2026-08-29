# Vima: canal WhatsApp (self-chat, Evolution) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the tenant's owner ask Vima a question by messaging their own connected WhatsApp
number (self-chat, Evolution/Baileys only) and get an answer back over the same channel — reusing
`vima/pergunta.responder` (the engine built for the web chat) unchanged.

**Architecture:** Inside `whatsapp_inbox/service.py::ingest_webhook_payload`, a new early branch
detects self-chat by combining two signals that already exist but were never combined for content
routing: `msg.from_me` (Baileys-only — the message was typed on the linked device) and
`_e_telefone_da_equipe(...)` (the counterparty phone is a registered user of the tenant). When both
are true and the message is text, it's routed to a new `vima/whatsapp_conversa.py` module instead
of the normal CRM inbox path — no `Client`/`WhatsappChat`/`WhatsappMessage` row is ever written for
it. That module resolves the matching `User`, builds a short-lived in-process context (for
follow-up questions) and dedup cache (webhook retries), calls `vima/pergunta.responder` exactly as
the web endpoint does, and sends the answer back via the same `core/whatsapp.send_text` dispatcher
that already delivers the daily briefing.

**Tech Stack:** FastAPI + SQLAlchemy (Python 3.13), same stack as the rest of `apps/api`. No
frontend changes — this feature has no UI surface.

**Spec:** `docs/superpowers/specs/2026-08-28-vima-canal-whatsapp-design.md`

## Global Constraints

- Evolution-only, by construction — `msg.from_me` is structurally always `False` on the Meta
  transport (confirmed in `core/whatsapp/inbound.py`'s `InboundMessage.from_me` docstring), so no
  explicit "is this tenant on Evolution?" guard is added; a comment at the call site says why one
  isn't needed, so a future reader doesn't take its absence for an oversight.
- Self-chat conversation NEVER touches `whatsapp_chats`/`whatsapp_messages`/`clients`/`facts` — it
  is fully out-of-band from the CRM inbox, matching the "zero persistence" decision already made
  for the web chat (PR #266).
- Every message in the self-chat is treated as a question — no activation keyword.
- Context between messages and webhook-retry deduplication both live in a short-TTL, in-process
  cache (no new table, no new Redis dependency) — a known, documented limitation for the current
  single-process scale (see spec).
- The new routing branch never lets a failure go silent: on any error it still attempts to send
  a short apology back over WhatsApp, unlike the rest of `whatsapp_inbox`'s broad
  `except Exception` (a pre-existing, separately-tracked debt this feature does not inherit).
- No commit happens inside the new `vima/whatsapp_conversa.responder` function — it runs inside
  `ingest_webhook_payload`'s existing per-message transaction, which commits it explicitly, mirroring
  the precedent `vima/scheduler.responder_optin` already set ("não commita — roda dentro da
  transação-por-mensagem do ingest").
- Reuses `vima/pergunta.responder`, `vima/tools.py`, and `core/ai.complete_with_tools` completely
  unchanged — this feature adds a new caller, not a new engine.

---

## Task 1: Promote `_usuarios_ativos`/`_como_ator` to public in `vima/scheduler.py`

**Files:**
- Modify: `apps/api/app/modules/vima/scheduler.py`

**Interfaces:**
- Produces: `scheduler.usuarios_ativos(db: Session, tenant_id: str) -> list[User]` and
  `scheduler.como_ator(user: User) -> CurrentUser` (renamed from the private
  `_usuarios_ativos`/`_como_ator` — identical bodies, identical behavior) — consumed by Task 3.

Both functions already exist and already do exactly what this feature needs (resolve active users
of a tenant; convert a `User` row into a `CurrentUser`) — `vima/scheduler.py::tick` and
`responder_optin` already use them internally. They're private (`_`-prefixed) today because they
had exactly one consumer (this module). This feature is the second consumer, which is this
codebase's own documented threshold for promoting a helper to public instead of a second module
reaching into another's private internals (see `settings/service.py::hoje_do_tenant`'s docstring
for the same principle stated explicitly: "um símbolo com `_` importado de fora é a costura
frouxa"). No test file references the private names directly (verified by grep), so this is a
pure rename with no test-file changes needed — the existing scheduler/briefing tests are the
regression guard.

- [ ] **Step 1: Confirm the pre-refactor baseline passes**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q tests/test_vima_scheduler.py tests/test_vima_whatsapp_meta.py tests/test_vima_briefing.py -v`
Expected: PASS (establishes the baseline this rename must not break).

- [ ] **Step 2: Rename the two functions and their call sites**

Edit `apps/api/app/modules/vima/scheduler.py`:

```python
def usuarios_ativos(db: Session, tenant_id: str) -> list[User]:
    """⚠️ `users` é tabela GLOBAL, SEM RLS — o filtro por `tenant_id` aqui é explícito e
    obrigatório. É a exceção documentada da Regra de Ouro nº 1, a mesma de
    `whatsapp_inbox.service._e_telefone_da_equipe`.

    Pública porque tem dois consumidores desde a fatia do canal WhatsApp da Vima
    (`vima/whatsapp_conversa.py`) — antes disso, só este módulo a usava."""
    return list(
        db.scalars(
            select(User)
            .where(User.tenant_id == tenant_id)
            .where(User.is_active.is_(True))
            .order_by(User.created_at, User.id)
        ).all()
    )


def como_ator(user: User) -> CurrentUser:
    """O `CurrentUser` que o serviço espera. O `allowed_modules` vem do BANCO, não de um token:
    é ele que recorta quais fatos entram no briefing deste usuário (`vima/permissions.py`), e um
    token não existe num job.

    Pública pelo mesmo motivo de `usuarios_ativos` acima."""
    return CurrentUser(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        allowed_modules=list(user.allowed_modules or []),
        is_platform_admin=user.is_platform_admin,
    )
```

Update the three call sites in the same file:
- Line ~69: `for user in _usuarios_ativos(db, tenant_id):` → `for user in usuarios_ativos(db, tenant_id):`
- Line ~79: `service.gerar_ou_ler(db, user=_como_ator(user), hoje=hoje)` → `service.gerar_ou_ler(db, user=como_ator(user), hoje=hoje)`
- Line ~225 (inside `responder_optin`): `for u in _usuarios_ativos(db, tenant_id)` → `for u in usuarios_ativos(db, tenant_id)`

- [ ] **Step 3: Run the same baseline tests to verify nothing broke**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q tests/test_vima_scheduler.py tests/test_vima_whatsapp_meta.py tests/test_vima_briefing.py -v`
Expected: PASS, same test count as Step 1.

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/modules/vima/scheduler.py
git commit -m "refactor: usuarios_ativos/como_ator viram públicas em vima/scheduler.py

Ganham um segundo consumidor (vima/whatsapp_conversa.py, próxima tarefa) — mesmo
critério já documentado em settings/service.hoje_do_tenant para promover um símbolo
privado em vez de outro módulo reimplementar ou importar o underscore."
```

---

## Task 2: `vima/whatsapp_conversa.py` — context and dedup caches

**Files:**
- Create: `apps/api/app/modules/vima/whatsapp_conversa.py`
- Test: `apps/api/tests/test_vima_whatsapp_conversa.py`

**Interfaces:**
- Consumes: `scheduler.usuarios_ativos(db, tenant_id) -> list[User]` (Task 1).
- Produces (module-private, tested directly since the module has no `__all__` boundary in this
  codebase's convention — see how `vima/tools.py`'s `_consultar_*` functions are tested directly):
  `_ja_processada(wa_message_id: str) -> bool`, `_marcar_processada(wa_message_id: str) -> None`,
  `_historico(chave: str) -> list[pergunta.Turno]`, `_guardar_turno(chave: str, papel: str, texto: str) -> None`,
  `_chave(tenant_id: str, phone: str) -> str`, `_usuario_do_telefone(db, tenant_id: str, phone: str) -> User | None`
  — all consumed by Task 3's `responder()` in the same module.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_vima_whatsapp_conversa.py`:

```python
"""Os dois caches de `vima/whatsapp_conversa.py`: dedup de reentrega de webhook e contexto
curto entre perguntas — os dois em processo, com TTL, sem tabela nova (decisão da spec)."""
import time

from sqlalchemy.orm import Session

from app.modules.auth.models import User
from app.modules.vima import whatsapp_conversa as vc

TENANT = "t1"


def setup_function():
    # Os caches são módulo-level (dict global) — cada teste começa limpo, senão o TTL de um
    # teste vazaria pro próximo e a ordem de execução passaria a importar.
    vc._VISTAS.clear()
    vc._HISTORICO.clear()


# ── Dedup de reentrega ──────────────────────────────────────────────────────────────────────


def test_mensagem_nunca_vista_nao_esta_processada():
    assert vc._ja_processada("wamid.novo") is False


def test_mensagem_marcada_fica_processada():
    vc._marcar_processada("wamid.x")
    assert vc._ja_processada("wamid.x") is True


def test_marca_expira_apos_o_ttl(monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(vc.time, "monotonic", lambda: agora[0])
    vc._marcar_processada("wamid.y")
    assert vc._ja_processada("wamid.y") is True
    agora[0] += vc.TTL_DEDUP_SEGUNDOS + 1
    assert vc._ja_processada("wamid.y") is False


# ── Contexto entre perguntas ─────────────────────────────────────────────────────────────────


def test_chave_sem_historico_devolve_lista_vazia():
    assert vc._historico("t1:5511999998888") == []


def test_turno_guardado_aparece_no_historico():
    chave = vc._chave(TENANT, "5511999998888")
    vc._guardar_turno(chave, "usuario", "quanto tenho a receber?")
    vc._guardar_turno(chave, "vima", "R$ 500,00")
    historico = vc._historico(chave)
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "quanto tenho a receber?"), ("vima", "R$ 500,00"),
    ]


def test_turno_expirado_some_do_historico(monkeypatch):
    agora = [2000.0]
    monkeypatch.setattr(vc.time, "monotonic", lambda: agora[0])
    chave = vc._chave(TENANT, "5511999997777")
    vc._guardar_turno(chave, "usuario", "pergunta antiga")
    agora[0] += vc.TTL_CONTEXTO_SEGUNDOS + 1
    assert vc._historico(chave) == []


def test_chave_normaliza_o_telefone():
    # "(11) 99999-8888" e "5511999998888" são o MESMO telefone — a chave do cache não pode
    # tratá-los como duas conversas diferentes, ou o contexto se perde a cada formatação distinta
    # do mesmo número que o provider entregar.
    assert vc._chave(TENANT, "11999998888") == vc._chave(TENANT, "(11) 99999-8888")


# ── Resolução do usuário pelo telefone ──────────────────────────────────────────────────────


def test_usuario_do_telefone_encontra_por_numero_normalizado(db: Session):
    user = User(
        tenant_id=TENANT, email="dono@example.com", name="Dono", password_hash="x",
        phone="(11) 99999-8888",
    )
    db.add(user)
    db.commit()
    encontrado = vc._usuario_do_telefone(db, TENANT, "5511999998888")
    assert encontrado is not None
    assert encontrado.id == user.id


def test_usuario_do_telefone_ignora_usuario_inativo(db: Session):
    user = User(
        tenant_id=TENANT, email="inativo@example.com", name="Ex", password_hash="x",
        phone="5511988887777", is_active=False,
    )
    db.add(user)
    db.commit()
    assert vc._usuario_do_telefone(db, TENANT, "5511988887777") is None


def test_usuario_do_telefone_sem_match_devolve_none(db: Session):
    assert vc._usuario_do_telefone(db, TENANT, "5511900000000") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_whatsapp_conversa.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.vima.whatsapp_conversa'`.

- [ ] **Step 3: Implement the module (caches + user lookup only — `responder()` comes in Task 3)**

Create `apps/api/app/modules/vima/whatsapp_conversa.py`:

```python
"""Vima por WhatsApp: quando o dono manda mensagem pro PRÓPRIO número conectado (self-chat,
Evolution), essa mensagem vira pergunta à Vima em vez de virar mensagem de CRM.

Ver docs/superpowers/specs/2026-08-28-vima-canal-whatsapp-design.md.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.core.phone import normalize_br
from app.modules.auth.models import User
from app.modules.vima import pergunta as pergunta_service
from app.modules.vima import scheduler

logger = logging.getLogger("e1p.vima")

# Poucos minutos — o suficiente para uma sequência natural de perguntas, curto o bastante para
# nunca virar "histórico permanente" (decisão da spec: zero persistência).
TTL_CONTEXTO_SEGUNDOS = 5 * 60
TTL_DEDUP_SEGUNDOS = 5 * 60

# Em processo — não sobrevive a reiniciar, não é compartilhado entre réplicas. Aceito para a
# escala atual (ver spec); Redis é o próximo passo se um dia isso incomodar de verdade.
_HISTORICO: dict[str, list[tuple[float, pergunta_service.Turno]]] = {}
_VISTAS: dict[str, float] = {}


def _chave(tenant_id: str, phone: str) -> str:
    return f"{tenant_id}:{normalize_br(phone) or phone}"


def _ja_processada(wa_message_id: str) -> bool:
    expira = _VISTAS.get(wa_message_id)
    return expira is not None and expira > time.monotonic()


def _marcar_processada(wa_message_id: str) -> None:
    _VISTAS[wa_message_id] = time.monotonic() + TTL_DEDUP_SEGUNDOS
    if len(_VISTAS) > 1000:  # limpeza oportunista — sem isso o dict cresce sem limite
        agora = time.monotonic()
        for chave in [k for k, exp in _VISTAS.items() if exp <= agora]:
            del _VISTAS[chave]


def _historico(chave: str) -> list[pergunta_service.Turno]:
    agora = time.monotonic()
    vivos = [(exp, t) for exp, t in _HISTORICO.get(chave, []) if exp > agora]
    _HISTORICO[chave] = vivos
    return [t for _, t in vivos]


def _guardar_turno(chave: str, papel: str, texto: str) -> None:
    expira = time.monotonic() + TTL_CONTEXTO_SEGUNDOS
    _HISTORICO.setdefault(chave, []).append(
        (expira, pergunta_service.Turno(papel=papel, texto=texto))
    )


def _usuario_do_telefone(db: Session, tenant_id: str, phone: str) -> User | None:
    """O mesmo casamento por telefone normalizado que `vima.scheduler.responder_optin` já faz
    para o toque no botão do briefing — reusa `scheduler.usuarios_ativos` (pública desde a
    tarefa anterior) em vez de reescrever a consulta pela terceira vez (a primeira é
    `whatsapp_inbox.service._e_telefone_da_equipe`, que fica como está: devolve só `bool` e
    não precisa da linha inteira)."""
    chave = normalize_br(phone)
    if chave is None:
        return None
    return next(
        (
            u for u in scheduler.usuarios_ativos(db, tenant_id)
            if u.phone and normalize_br(u.phone) == chave
        ),
        None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_whatsapp_conversa.py -v`
Expected: PASS, 11 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/whatsapp_conversa.py apps/api/tests/test_vima_whatsapp_conversa.py
git commit -m "feat: vima/whatsapp_conversa — cache de contexto e dedup, em processo

TTL curto (5min) para os dois: contexto entre perguntas de acompanhamento e
deduplicação de reentrega de webhook. Sem tabela nova, sem Redis — decisão da spec
para a escala atual; limite conhecido e documentado."
```

---

## Task 3: `vima/whatsapp_conversa.responder` — the orchestration function

**Files:**
- Modify: `apps/api/app/modules/vima/whatsapp_conversa.py`
- Modify: `apps/api/tests/test_vima_whatsapp_conversa.py`

**Interfaces:**
- Consumes: `pergunta.responder` (existing), `core.whatsapp.send_text` (existing),
  `scheduler.como_ator(user) -> CurrentUser` (Task 1),
  `_usuario_do_telefone`/`_historico`/`_guardar_turno`/`_chave`/`_ja_processada`/`_marcar_processada`
  (Task 2, same module).
- Produces: `whatsapp_conversa.responder(db: Session, *, tenant_id: str, phone: str,
  wa_message_id: str, texto: str, profile) -> None` — consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_vima_whatsapp_conversa.py`:

```python
# ── responder() — a orquestração ────────────────────────────────────────────────────────────


def test_responder_chama_pergunta_e_manda_a_resposta_por_whatsapp(db: Session, monkeypatch):
    user = User(
        tenant_id=TENANT, email="dono2@example.com", name="Dono", password_hash="x",
        phone="5511999991111",
    )
    db.add(user)
    db.commit()

    capturado = {}

    def _fake_pergunta_responder(db, *, user, pergunta, historico):
        from app.modules.vima.pergunta import Resposta
        capturado["user_id"] = user.user_id
        capturado["pergunta"] = pergunta
        capturado["historico"] = historico
        return Resposta(texto="Você tem R$ 500,00 a receber.", por_ia=True)

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["enviado_para"] = to
        capturado["texto_enviado"] = text
        return "sent"

    monkeypatch.setattr(vc.pergunta_service, "responder", _fake_pergunta_responder)
    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder(
        db, tenant_id=TENANT, phone="5511999991111", wa_message_id="wamid.1",
        texto="quanto tenho a receber?", profile=None,
    )

    assert capturado["user_id"] == user.id
    assert capturado["pergunta"] == "quanto tenho a receber?"
    assert capturado["historico"] == []
    assert capturado["enviado_para"] == "5511999991111"
    assert capturado["texto_enviado"] == "Você tem R$ 500,00 a receber."


def test_responder_guarda_o_turno_para_a_proxima_pergunta(db: Session, monkeypatch):
    user = User(
        tenant_id=TENANT, email="dono3@example.com", name="Dono", password_hash="x",
        phone="5511999992222",
    )
    db.add(user)
    db.commit()

    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda db, *, user, pergunta, historico: __import__(
            "app.modules.vima.pergunta", fromlist=["Resposta"]
        ).Resposta(texto="R$ 500,00", por_ia=True),
    )
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    vc.responder(
        db, tenant_id=TENANT, phone="5511999992222", wa_message_id="wamid.2",
        texto="quanto tenho a receber?", profile=None,
    )

    historico = vc._historico(vc._chave(TENANT, "5511999992222"))
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "quanto tenho a receber?"), ("vima", "R$ 500,00"),
    ]


def test_responder_ignora_reentrega_do_mesmo_wa_message_id(db: Session, monkeypatch):
    user = User(
        tenant_id=TENANT, email="dono4@example.com", name="Dono", password_hash="x",
        phone="5511999993333",
    )
    db.add(user)
    db.commit()

    chamadas = {"n": 0}

    def _fake_pergunta_responder(db, *, user, pergunta, historico):
        from app.modules.vima.pergunta import Resposta
        chamadas["n"] += 1
        return Resposta(texto="ok", por_ia=True)

    monkeypatch.setattr(vc.pergunta_service, "responder", _fake_pergunta_responder)
    monkeypatch.setattr(vc.whatsapp, "send_text", lambda **_kw: "sent")

    for _ in range(2):
        vc.responder(
            db, tenant_id=TENANT, phone="5511999993333", wa_message_id="wamid.dup",
            texto="oi", profile=None,
        )
    assert chamadas["n"] == 1


def test_responder_sem_usuario_correspondente_nao_estoura(db: Session, monkeypatch):
    # Defensivo: o chamador já checou `_e_telefone_da_equipe`, mas nada garante atomicidade
    # entre a checagem e aqui — não pode estourar se o telefone não bater com ninguém.
    chamado = {"n": 0}
    monkeypatch.setattr(
        vc.pergunta_service, "responder",
        lambda *a, **kw: chamado.update(n=chamado["n"] + 1),
    )
    vc.responder(
        db, tenant_id=TENANT, phone="5511900009999", wa_message_id="wamid.semuser",
        texto="oi", profile=None,
    )
    assert chamado["n"] == 0  # nunca chegou a chamar pergunta.responder


def test_responder_falha_no_meio_manda_desculpa_em_vez_de_estourar(db: Session, monkeypatch):
    user = User(
        tenant_id=TENANT, email="dono5@example.com", name="Dono", password_hash="x",
        phone="5511999994444",
    )
    db.add(user)
    db.commit()

    def _explode(db, *, user, pergunta, historico):
        raise RuntimeError("Claude indisponível")

    capturado = {}

    def _fake_send_text(*, to, text, profile=None, **_kw):
        capturado["texto"] = text
        return "sent"

    monkeypatch.setattr(vc.pergunta_service, "responder", _explode)
    monkeypatch.setattr(vc.whatsapp, "send_text", _fake_send_text)

    vc.responder(  # não pode levantar
        db, tenant_id=TENANT, phone="5511999994444", wa_message_id="wamid.falha",
        texto="oi", profile=None,
    )
    assert "não consegui" in capturado["texto"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_whatsapp_conversa.py -v -k responder`
Expected: FAIL — `AttributeError: module 'app.modules.vima.whatsapp_conversa' has no attribute 'responder'`.

- [ ] **Step 3: Implement `responder()`**

Edit `apps/api/app/modules/vima/whatsapp_conversa.py`. Add this import at the top, alongside the
existing `pergunta_service`/`scheduler` imports from Task 2:

```python
from app.core import whatsapp
```

Then append at the end of the file:

```python
def responder(
    db: Session, *, tenant_id: str, phone: str, wa_message_id: str, texto: str, profile,
) -> None:
    """O dono perguntou algo na self-chat — responde pelo MESMO canal.

    Chamado por `whatsapp_inbox.service.ingest_webhook_payload` quando reconhece a self-chat
    (`msg.from_me and da_equipe and msg.kind == KIND_TEXT` — só existe no Evolution, porque só
    lá `from_me` existe). NÃO grava nada em `whatsapp_chats`/`whatsapp_messages`/CRM — decisão
    da spec, mesma disciplina de "zero persistência" do chat web (PR #266). NÃO commita — roda
    dentro da transação-por-mensagem do `ingest`, que decide quando commitar (mesmo padrão de
    `vima.scheduler.responder_optin`).

    Nunca deixa uma falha muda: qualquer erro no meio do caminho ainda tenta mandar uma resposta
    de desculpa pelo mesmo canal — `whatsapp.send_text` nunca levanta (fire-and-forget por
    contrato), então essa tentativa é sempre segura.
    """
    if _ja_processada(wa_message_id):
        return  # reentrega do webhook — já respondida
    _marcar_processada(wa_message_id)

    user = _usuario_do_telefone(db, tenant_id, phone)
    if user is None:
        # Defensivo: o chamador já confirmou que o telefone é de um usuário ativo
        # (`_e_telefone_da_equipe`), mas não há garantia atômica entre a checagem e aqui —
        # melhor desistir em silêncio do que estourar.
        logger.warning("[vima] self-chat sem usuário correspondente: tenant=%s", tenant_id)
        return

    chave = _chave(tenant_id, phone)

    try:
        resultado = pergunta_service.responder(
            db, user=scheduler.como_ator(user), pergunta=texto, historico=_historico(chave),
        )
    except Exception:  # noqa: BLE001 — falha nunca fica muda (ver docstring)
        logger.exception("[vima] falha ao responder pergunta via WhatsApp self-chat")
        db.rollback()
        whatsapp.send_text(
            to=phone, text="Não consegui responder agora — tenta de novo em instantes.",
            profile=profile,
        )
        return

    _guardar_turno(chave, "usuario", texto)
    _guardar_turno(chave, "vima", resultado.texto)
    whatsapp.send_text(to=phone, text=resultado.texto, profile=profile)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_whatsapp_conversa.py -v`
Expected: PASS, 16 tests total (11 from Task 2 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/whatsapp_conversa.py apps/api/tests/test_vima_whatsapp_conversa.py
git commit -m "feat: vima/whatsapp_conversa.responder — orquestra a pergunta via self-chat

Resolve o usuário pelo telefone, reusa pergunta.responder e core.whatsapp.send_text
sem nenhuma peça nova de motor. Dedup por wa_message_id, contexto por turno salvo
após o sucesso, e uma desculpa enviada de volta em qualquer falha no meio."
```

---

## Task 4: Wire the routing branch into `ingest_webhook_payload`

**Files:**
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py`
- Test: `apps/api/tests/test_whatsapp_inbox_self_chat.py`

**Interfaces:**
- Consumes: `whatsapp_conversa.responder` (Task 3).

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_whatsapp_inbox_self_chat.py`:

```python
"""A self-chat da Vima roteia para `vima/whatsapp_conversa`, não para o inbox normal — e as
outras três formas de `from_me`/`da_equipe` continuam se comportando como antes (regressão)."""
from sqlalchemy import select

from app.core.whatsapp.inbound import InboundMessage
from app.modules.auth.models import User
from app.modules.crm.models import Client
from app.modules.vima import whatsapp_conversa as vc
from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import WhatsappChat, WhatsappMessage

TENANT_ID = "22222222-2222-2222-2222-222222222222"


def _self_chat_msg(**over) -> InboundMessage:
    base = dict(
        wa_message_id="self.1", from_phone="5511988889999", kind="text",
        text_body="quanto tenho a receber?", media_ref=None, push_name="Dono",
        from_me=True, chat_jid="5511988889999@s.whatsapp.net",
    )
    base.update(over)
    return InboundMessage(**base)


def test_self_chat_roteia_para_vima_sem_gravar_no_crm(db, monkeypatch):
    user = User(
        tenant_id=TENANT_ID, email="dono@example.com", name="Dono", password_hash="x",
        phone="5511988889999",
    )
    db.add(user)
    db.commit()

    chamada = {}

    def _fake_responder(db, *, tenant_id, phone, wa_message_id, texto, profile):
        chamada.update(
            tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=texto,
        )

    monkeypatch.setattr(vc, "responder", _fake_responder)

    inbox_service.ingest_webhook_payload(db, tenant_id=TENANT_ID, messages=[_self_chat_msg()])

    assert chamada == {
        "tenant_id": TENANT_ID, "phone": "5511988889999",
        "wa_message_id": "self.1", "texto": "quanto tenho a receber?",
    }
    assert db.scalar(select(WhatsappMessage)) is None
    assert db.scalar(select(WhatsappChat)) is None
    assert db.scalar(select(Client)) is None


def test_midia_na_self_chat_cai_no_caminho_normal_sem_erro(db, monkeypatch):
    # Ponto de extensão da fatia de voz: hoje só TEXTO vira pergunta. Áudio/imagem no mesmo
    # self-chat segue o comportamento JÁ EXISTENTE (grava mensagem, sem virar lead — a mesma
    # guarda de `_e_telefone_da_equipe` que já protegia isso antes desta feature).
    user = User(
        tenant_id=TENANT_ID, email="dono2@example.com", name="Dono", password_hash="x",
        phone="5511988880001",
    )
    db.add(user)
    db.commit()

    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.audio", kind="audio", text_body="",
            from_phone="5511988880001", chat_jid="5511988880001@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0  # não roteou para a Vima
    row = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "self.audio"))
    assert row is not None  # gravou normalmente, como antes desta feature
    assert db.scalar(select(Client)) is None  # mas não virou lead — guarda pré-existente


def test_dono_respondendo_cliente_pelo_proprio_celular_nao_e_self_chat(db, monkeypatch):
    # from_me=True, mas a CONTRAPARTE é um cliente, não um usuário do tenant — não é self-chat.
    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))

    existing = Client(
        tenant_id=TENANT_ID, name="Cliente", phone="5511977776666", source="manual",
    )
    db.add(existing)
    db.commit()

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="reply.cliente", from_phone="5511977776666", text_body="já te retorno",
            chat_jid="5511977776666@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0
    row = db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "reply.cliente")
    )
    assert row is not None
    assert row.direction == "out"  # comportamento pré-existente, inalterado


def test_cliente_comum_nao_aciona_a_vima(db, monkeypatch):
    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="cliente.1", from_phone="5511966665555", from_me=False,
            text_body="oi, quero saber do produto", chat_jid="5511966665555@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0
    client = db.scalar(select(Client).where(Client.phone == "5511966665555"))
    assert client is not None  # vira lead normalmente, como sempre
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_inbox_self_chat.py -v`
Expected: FAIL — `test_self_chat_roteia_para_vima_sem_gravar_no_crm` fails because `chamada` stays
empty (no routing branch exists yet) and a `WhatsappMessage` row gets created instead.

- [ ] **Step 3: Wire the branch**

Edit `apps/api/app/modules/whatsapp_inbox/service.py`. Add the import alongside the existing
`vima_scheduler` import:

```python
from app.modules.vima import scheduler as vima_scheduler
from app.modules.vima import whatsapp_conversa as vima_whatsapp
```

Then edit the per-message loop — insert the new branch right after `da_equipe` is computed,
before the existing `if msg.from_phone is None or da_equipe:` block:

```python
            da_equipe = _e_telefone_da_equipe(db, tenant_id, msg.from_phone)

            # Self-chat: o dono perguntando à Vima pelo próprio número conectado. Só existe no
            # Evolution — `from_me` é exclusivo daquele transporte (a Meta nunca entrega mensagem
            # própria no webhook, ver `core/whatsapp/inbound.py`) —, então não há guarda extra de
            # "é Evolution?" aqui: a condição já é estruturalmente inalcançável na Meta. Mídia no
            # mesmo self-chat cai no comportamento normal abaixo — ponto de extensão da fatia de
            # voz (ver a spec).
            if msg.from_me and da_equipe and msg.kind == KIND_TEXT:
                vima_whatsapp.responder(
                    db, tenant_id=tenant_id, phone=msg.from_phone,
                    wa_message_id=msg.wa_message_id, texto=msg.text_body, profile=profile,
                )
                db.commit()
                continue

            if msg.from_phone is None or da_equipe:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_whatsapp_inbox_self_chat.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Run the full whatsapp_inbox + vima test files to check for regressions**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q tests/test_whatsapp_inbox_service.py tests/test_whatsapp_inbox_evolution_webhook.py tests/test_whatsapp_inbox_groups.py tests/test_whatsapp_inbox_media_worker.py tests/test_whatsapp_inbox_nao_lidas.py tests/test_whatsapp_inbox_reply.py tests/test_whatsapp_inbox_unidentified.py tests/test_whatsapp_inbox_webhook.py tests/test_vima_whatsapp_meta.py tests/test_vima_whatsapp_evolution.py tests/test_vima_scheduler.py -v`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/whatsapp_inbox/service.py apps/api/tests/test_whatsapp_inbox_self_chat.py
git commit -m "feat: self-chat do WhatsApp vira pergunta à Vima em vez de mensagem de CRM

from_me AND da_equipe AND kind==text isola a self-chat — as duas peças já
existiam, nunca combinadas para roteamento de conteúdo. Mídia na mesma self-chat
segue o caminho normal (ponto de extensão da fatia de voz). Sem grep de
require_module nem migration — reusa vima/pergunta.responder por inteiro."
```

---

## Final check: full suite, lint, docs, PR

- [ ] **Step 1: Run the full backend fast suite**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q`
Expected: PASS, no regressions against the pre-existing count.

- [ ] **Step 2: Run ruff**

Run: `cd apps/api && .venv/Scripts/python -m ruff check .`
Expected: clean.

- [ ] **Step 3: Update `CLAUDE.md`**

Per this repository's own rule (§5, step 4), add a short entry — place it as a subsection right
after (or folded into) the existing `## Vima: pergunte e receba resposta (2026-08-28)` section,
since this is the same feature's second channel, not a separate feature. Summarize: what exists
now (self-chat over Evolution routes to the same `pergunta.responder`), the
`from_me AND da_equipe` detection mechanism and why it needed no new data, the "zero persistence,
short in-process cache" decision and its known multi-process limitation, and the declared
Evolution-only scope.

- [ ] **Step 4: Commit the CLAUDE.md entry**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md registra o canal WhatsApp da Vima (self-chat, Evolution)"
```
