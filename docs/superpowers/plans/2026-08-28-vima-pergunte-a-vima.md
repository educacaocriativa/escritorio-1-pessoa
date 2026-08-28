# Vima: perguntar e receber resposta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `POST /vima/pergunta` (a Claude tool-use loop over existing read services) and a
`/vima/perguntas` chat screen, so the owner can ask Vima a question in text and get an answer
grounded in real Financeiro/Agenda/CRM data — the first slice of the path toward a voice-driven,
self-sufficient assistant.

**Architecture:** A new `complete_with_tools` function in `core/ai.py` runs the Anthropic
tool-use loop generically (it doesn't know what a tool does); `vima/tools.py` defines five
read-only tools, each a thin wrapper over an existing deterministic service, filtered by
`allowed_modules` before Claude ever sees them; `vima/pergunta.py` wires the anonymizer, the
loop, and the audit trail together; `vima/router.py` exposes it as `POST /vima/pergunta`. The
frontend is a plain chat screen with no server-side history — each request resends the
session's transcript.

**Tech Stack:** FastAPI + SQLAlchemy (Python 3.13) on the backend, Anthropic SDK's tool-use
API; React + TypeScript + Tailwind on the frontend; pytest (+ `testcontainers` for the RLS
proof) and Vitest + Playwright for tests.

**Spec:** `docs/superpowers/specs/2026-08-28-vima-pergunte-design.md`

## Global Constraints

- No persistence between sessions — conversation history lives only in the frontend's React
  state; the backend never stores a transcript.
- The initial question (+ resent history) is masked via `core/anonymizer` before reaching
  Claude, same as every other AI call in this codebase (Regra de Ouro nº 2). Tool *results*
  are **not** masked — this extends the founder's 2026-07-11 accepted-risk decision for the
  Diagnóstico Financeiro module to this new flow (documented, not silent).
- No number is ever computed by Claude — every figure returned to the model comes from an
  existing deterministic service function. A tool failure is reported to Claude as "couldn't
  fetch this," never guessed (Article IV — No Invention).
- Tool visibility is filtered by `vima/permissions.pode_ver(user, module)` **before** the list
  reaches Claude — same principle the briefing already uses ("o filtro decide quais REGRAS
  RODAM, não quais resultados aparecem").
- New task key `vima.pergunta` routes to `claude-sonnet-5` in `MODELO_POR_TAREFA` (tool
  selection errors cost more than narration errors — same criterion the rest of the file uses).
- Golden Rule #1 (RLS is the only tenant guard) applies to every tool — no manual `tenant_id`
  filter is ever written in a tool body; the RLS-scoped `db` session already scopes everything.
- The `/vima/pergunta` route and its nav entry carry **no** `require_module`/`<Modulo>` guard,
  mirroring `/vima/briefing`'s existing decision — permission recorte happens per-tool, not at
  the route.
- The new frontend route ships with 360px e2e coverage from the same commit that adds the
  route (project convention, no exceptions).

---

## Task 1: `core/ai.complete_with_tools` — the generic tool-use loop

**Files:**
- Modify: `apps/api/app/core/ai.py`
- Test: `apps/api/tests/test_ai_complete_with_tools.py`

**Interfaces:**
- Consumes: `app.core.ai_usage.record` (existing, unchanged), `app.core.ai._get_client` /
  `modelo_da_tarefa` (existing, unchanged).
- Produces: `ai.ToolCallLoopResult` (dataclass: `text: str`, `input_tokens: int`,
  `output_tokens: int`, `cache_read_tokens: int = 0`, `cache_creation_tokens: int = 0`,
  `turnos_usados: int = 0`, `parou_no_teto: bool = False`) and
  `ai.complete_with_tools(*, db, tenant_id, task, system, user_message, tools,
  executar_ferramenta, max_tokens=1500, max_tool_turns=6, model=None, user_id=None) ->
  ToolCallLoopResult` — both consumed by Task 3.

- [ ] **Step 1: Add `"vima.pergunta"` to `MODELO_POR_TAREFA`**

Edit `apps/api/app/core/ai.py`, inside the `MODELO_POR_TAREFA` dict (right after the
`"vima.briefing": "claude-haiku-4-5",` line):

```python
    "vima.briefing": "claude-haiku-4-5",
    "vima.pergunta": "claude-sonnet-5",  # escolhe QUAL ferramenta chamar — erro de escolha
    # custa mais do que texto mal-narrado, mesmo critério de quotes/funnels/marketing.
```

- [ ] **Step 2: Write the failing tests for the loop**

Create `apps/api/tests/test_ai_complete_with_tools.py`:

```python
"""Testes do loop de tool-use (`core/ai.complete_with_tools`).

Esta é a PRIMEIRA consumidora da API de tool-use da Anthropic neste repositório — nenhum outro
módulo tinha `tools=`/`tool_use` antes desta função existir. Mesma disciplina do resto de
`core/ai.py`: mockar `_get_client`, nunca chamar a API de verdade.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.core import ai
from app.core.ai_usage import AIUsage

TENANT = "t1"


class _FakeMessagesQueue:
    """Devolve uma resposta por chamada, na ordem — o loop faz várias chamadas."""

    def __init__(self, respostas: list):
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        return self.respostas.pop(0)


class _FakeClient:
    def __init__(self, messages: _FakeMessagesQueue):
        self.messages = messages


def _bloco_texto(texto: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=texto)


def _bloco_tool_use(nome: str, entrada: dict, tool_id: str = "tu_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=nome, input=entrada)


def _resposta(blocos: list, *, stop_reason: str, input_tokens=10, output_tokens=5) -> SimpleNamespace:
    return SimpleNamespace(
        content=blocos,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
    )


def _install_fake(monkeypatch, respostas: list) -> _FakeMessagesQueue:
    fila = _FakeMessagesQueue(respostas)
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient(fila))
    return fila


def _loop(db, **over):
    kwargs = {
        "db": db, "tenant_id": TENANT, "task": "vima.pergunta",
        "system": "S", "user_message": "quanto eu tenho a receber?",
        "tools": [{"name": "consultar_recebiveis", "description": "d",
                   "input_schema": {"type": "object", "properties": {}}}],
        "executar_ferramenta": lambda nome, entrada: "{}",
    }
    kwargs.update(over)
    return ai.complete_with_tools(**kwargs)


def test_para_direto_quando_a_primeira_rodada_nao_pede_ferramenta(db: Session, monkeypatch):
    fila = _install_fake(monkeypatch, [_resposta([_bloco_texto("R$ 0,00")], stop_reason="end_turn")])
    resultado = _loop(db)
    assert resultado.text == "R$ 0,00"
    assert resultado.turnos_usados == 1
    assert resultado.parou_no_teto is False
    assert len(fila.chamadas) == 1


def test_chama_a_ferramenta_com_o_nome_e_o_input_pedidos_pela_claude(db: Session, monkeypatch):
    _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {"foo": "bar"})], stop_reason="tool_use"),
        _resposta([_bloco_texto("resposta final")], stop_reason="end_turn"),
    ])
    chamadas_da_ferramenta = []

    def _executar(nome, entrada):
        chamadas_da_ferramenta.append((nome, entrada))
        return '{"open_cents": 100}'

    resultado = _loop(db, executar_ferramenta=_executar)
    assert chamadas_da_ferramenta == [("consultar_recebiveis", {"foo": "bar"})]
    assert resultado.text == "resposta final"


def test_o_resultado_da_ferramenta_volta_para_a_claude_como_tool_result(db: Session, monkeypatch):
    fila = _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {}, tool_id="tu_9")], stop_reason="tool_use"),
        _resposta([_bloco_texto("ok")], stop_reason="end_turn"),
    ])
    _loop(db, executar_ferramenta=lambda nome, entrada: '{"open_cents": 500}')

    segunda_chamada = fila.chamadas[1]
    ultima_mensagem = segunda_chamada["messages"][-1]
    assert ultima_mensagem["role"] == "user"
    assert ultima_mensagem["content"] == [
        {"type": "tool_result", "tool_use_id": "tu_9", "content": '{"open_cents": 500}'}
    ]


def test_grava_uma_linha_de_ledger_por_rodada_de_api(db: Session, monkeypatch):
    _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use",
                   input_tokens=10, output_tokens=5),
        _resposta([_bloco_texto("ok")], stop_reason="end_turn", input_tokens=20, output_tokens=8),
    ])
    _loop(db, executar_ferramenta=lambda nome, entrada: "{}", user_id="u1")
    db.commit()

    linhas = db.query(AIUsage).order_by(AIUsage.input_tokens).all()
    assert len(linhas) == 2
    assert [linha.input_tokens for linha in linhas] == [10, 20]
    assert all(linha.task == "vima.pergunta" and linha.model == "claude-sonnet-5" for linha in linhas)
    assert all(linha.user_id == "u1" for linha in linhas)


def test_estoura_o_teto_de_rodadas_e_forca_uma_resposta_final_sem_ferramentas(db: Session, monkeypatch):
    fila = _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use"),
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use"),
        _resposta([_bloco_texto("melhor resposta possível")], stop_reason="end_turn"),
    ])
    resultado = _loop(db, executar_ferramenta=lambda nome, entrada: "{}", max_tool_turns=2)

    assert resultado.parou_no_teto is True
    assert resultado.turnos_usados == 3
    assert resultado.text == "melhor resposta possível"
    # a chamada de wrap-up NÃO oferece ferramentas — é isso que força um texto final
    assert "tools" not in fila.chamadas[-1]


def test_soma_os_tokens_de_todas_as_rodadas_no_resultado(db: Session, monkeypatch):
    _install_fake(monkeypatch, [
        _resposta([_bloco_tool_use("consultar_recebiveis", {})], stop_reason="tool_use",
                   input_tokens=10, output_tokens=5),
        _resposta([_bloco_texto("ok")], stop_reason="end_turn", input_tokens=20, output_tokens=8),
    ])
    resultado = _loop(db, executar_ferramenta=lambda nome, entrada: "{}")
    assert (resultado.input_tokens, resultado.output_tokens) == (30, 13)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_ai_complete_with_tools.py -v`
Expected: FAIL — `AttributeError: module 'app.core.ai' has no attribute 'complete_with_tools'`
(and no `ToolCallLoopResult`).

- [ ] **Step 4: Implement `complete_with_tools`**

Edit `apps/api/app/core/ai.py`. Add `Callable` to the `typing` import at the top
(`from typing import Any, Callable`), then append after the existing `complete()` function:

```python
@dataclass
class ToolCallLoopResult:
    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    turnos_usados: int = 0
    # `True` só quando `max_tool_turns` estourou e a última rodada foi um wrap-up forçado sem
    # ferramentas — nunca truncamento silencioso (ver docstring abaixo).
    parou_no_teto: bool = False


def complete_with_tools(
    *,
    db: Session,
    tenant_id: str,
    task: str,
    system: str,
    user_message: str,
    tools: list[dict[str, Any]],
    executar_ferramenta: Callable[[str, dict[str, Any]], str],
    max_tokens: int = 1500,
    max_tool_turns: int = 6,
    model: str | None = None,
    user_id: str | None = None,
) -> ToolCallLoopResult:
    """Completude com tool-use: a Claude escolhe ferramentas, o CHAMADOR as executa.

    Esta camada continua sem conhecer dados reais (item 1 do docstring do módulo) — quem sabe o
    que uma ferramenta faz é `executar_ferramenta`, fornecida pelo chamador. `user_message` deve
    chegar já anonimizado; o resultado de CADA ferramenta NÃO passa por anonimização aqui — é
    responsabilidade do chamador, se precisar (ver `vima/pergunta.py`).

    Cada rodada de `messages.create` grava sua PRÓPRIA linha no ledger `ai_usage`: é uma chamada
    de API por rodada, e cada uma custa dinheiro no instante em que acontece — resumir só no fim
    esconderia o custo real de um loop que deu muitas voltas.

    Estourar `max_tool_turns` sem uma resposta final não trunca em silêncio: uma última chamada
    SEM `tools` força um texto de fechamento com o que já foi apurado (`parou_no_teto=True`).
    """
    modelo = model or modelo_da_tarefa(task)
    client = _get_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    total_input = total_output = total_cache_read = total_cache_creation = 0

    def _grava(resp: Any) -> None:
        nonlocal total_input, total_output, total_cache_read, total_cache_creation
        cache_read = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
        cache_creation = getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
        total_input += resp.usage.input_tokens
        total_output += resp.usage.output_tokens
        total_cache_read += cache_read
        total_cache_creation += cache_creation
        ai_usage.record(
            db, tenant_id=tenant_id, task=task, model=modelo,
            input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
            cache_read_tokens=cache_read, cache_creation_tokens=cache_creation,
            user_id=user_id,
        )

    def _texto(resp: Any) -> str:
        return "".join(bloco.text for bloco in resp.content if bloco.type == "text")

    turnos = 0
    while turnos < max_tool_turns:
        turnos += 1
        resp = client.messages.create(
            model=modelo, max_tokens=max_tokens, system=system, tools=tools, messages=messages,
        )
        _grava(resp)
        if resp.stop_reason != "tool_use":
            return ToolCallLoopResult(
                text=_texto(resp), input_tokens=total_input, output_tokens=total_output,
                cache_read_tokens=total_cache_read, cache_creation_tokens=total_cache_creation,
                turnos_usados=turnos,
            )
        messages.append({"role": "assistant", "content": resp.content})
        resultados = [
            {
                "type": "tool_result",
                "tool_use_id": bloco.id,
                "content": executar_ferramenta(bloco.name, bloco.input),
            }
            for bloco in resp.content
            if bloco.type == "tool_use"
        ]
        messages.append({"role": "user", "content": resultados})

    resp_final = client.messages.create(
        model=modelo, max_tokens=max_tokens, system=system, messages=messages,
    )
    _grava(resp_final)
    return ToolCallLoopResult(
        text=_texto(resp_final), input_tokens=total_input, output_tokens=total_output,
        cache_read_tokens=total_cache_read, cache_creation_tokens=total_cache_creation,
        turnos_usados=turnos + 1, parou_no_teto=True,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_ai_complete_with_tools.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 6: Run the full backend fast suite to check for regressions**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q`
Expected: PASS (unchanged count + the 7 new tests).

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/core/ai.py apps/api/tests/test_ai_complete_with_tools.py
git commit -m "feat: ai.complete_with_tools — loop de tool-use, primeira consumidora no repo

Camada genérica: não conhece dado real, só orquestra rodadas de messages.create e
delega a execução de cada ferramenta ao chamador. Contabiliza uma linha de ai_usage
por rodada de API. vima.pergunta roteia para claude-sonnet-5 em MODELO_POR_TAREFA."
```

---

## Task 2: `vima/tools.py` — the five read-only tools

**Files:**
- Create: `apps/api/app/modules/vima/tools.py`
- Test: `apps/api/tests/test_vima_tools.py`

**Interfaces:**
- Consumes: `receivables.service.summary(db) -> dict`, `payables.service.summary(db) -> dict`,
  `financial_intelligence.projection.cash_projection(db) -> CashProjection` (dataclass),
  `agenda.service.list_events(db, *, start, end, exclude_cancelled, limit) -> list[AgendaEvent]`,
  `crm.service.list_clients(db, *, search, limit) -> list[Client]`,
  `crm.timeline.build(db, *, client_id, limit) -> tuple[list[dict], bool]`,
  `settings.service.tenant_timezone(db) -> str`, `core.tz.day_window_utc(day, tz_name) ->
  tuple[datetime, datetime]`, `vima.permissions.pode_ver(user, module) -> bool`.
- Produces: `tools.Ferramenta` (dataclass: `nome: str`, `modulo: str`, `definicao: dict`,
  `executar: Callable`), `tools.FERRAMENTAS: list[Ferramenta]`,
  `tools.ferramentas_disponiveis(user: CurrentUser) -> list[Ferramenta]`,
  `tools.executar(db: Session, user: CurrentUser, nome: str, entrada: dict) -> str` — all
  consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_vima_tools.py`:

```python
"""As cinco ferramentas de leitura que a Vima oferece à Claude — permissão, delegação e o
contrato "nunca deixa exceção subir crua" (o loop de tool-use precisa de um tool_result sempre).
"""
import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.crm.models import Client
from app.modules.receivables.models import METHOD_PIX, STATUS_OPEN, Charge
from app.modules.vima import tools
from app.modules.wallet.models import KIND_SERVICE

TENANT = "t1"


def _usuario(role: str = "owner", modulos: list[str] | None = None) -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id=TENANT, role=role,
        allowed_modules=modulos or [], is_platform_admin=False,
    )


# ── Catálogo e permissão ────────────────────────────────────────────────────────────────────


def test_owner_ve_as_cinco_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente",
    }


def test_sub_usuario_so_de_crm_so_ve_a_ferramenta_de_cliente():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("sub_user", ["crm"]))}
    assert nomes == {"consultar_cliente"}


def test_toda_ferramenta_declara_um_input_schema_valido():
    """Instanciação obrigatória do catálogo — uma ferramenta sem `input_schema` quebraria a
    chamada à Anthropic só na primeira vez que a Claude tentasse usá-la."""
    for f in tools.FERRAMENTAS:
        assert f.definicao["name"] == f.nome
        assert f.definicao["input_schema"]["type"] == "object"


def test_executar_recusa_ferramenta_fora_da_lista_permitida(db: Session):
    resultado = json.loads(
        tools.executar(db, _usuario("sub_user", ["crm"]), "consultar_recebiveis", {})
    )
    assert "erro" in resultado


# ── consultar_recebiveis / consultar_pagaveis ──────────────────────────────────────────────


def test_consultar_recebiveis_delega_para_o_resumo_real(db: Session):
    db.add(Charge(
        tenant_id=TENANT, description="Consultoria", kind=KIND_SERVICE, method=METHOD_PIX,
        amount_cents=50_000, due_date=date(2026, 9, 1), status=STATUS_OPEN,
    ))
    db.commit()
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_recebiveis", {}))
    assert resultado["open_cents"] == 50_000
    assert resultado["open_count"] == 1


def test_consultar_pagaveis_devolve_o_resumo_de_pagaveis(db: Session):
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_pagaveis", {}))
    assert "open_cents" in resultado and "overdue_cents" in resultado


# ── consultar_projecao_caixa ────────────────────────────────────────────────────────────────


def test_consultar_projecao_caixa_devolve_janelas_e_runway(db: Session):
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_projecao_caixa", {}))
    assert "windows" in resultado
    assert "runway" in resultado
    assert resultado["saldo_inicial_origem"] in {"plataforma", "banco", "misto", "indisponivel"}


# ── consultar_agenda ─────────────────────────────────────────────────────────────────────────


def test_consultar_agenda_devolve_eventos_do_dia_pedido(db: Session):
    from app.modules.agenda.models import AgendaEvent

    db.add(AgendaEvent(
        tenant_id=TENANT, title="Reunião com cliente", kind="meeting",
        starts_at=datetime(2026, 9, 10, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 10, 15, 0, tzinfo=UTC),
    ))
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "consultar_agenda", {"data_inicio": "2026-09-10"}
    ))
    assert len(resultado["eventos"]) == 1
    assert resultado["eventos"][0]["titulo"] == "Reunião com cliente"


def test_consultar_agenda_sem_evento_devolve_lista_vazia_nao_erro(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "consultar_agenda", {"data_inicio": "2026-01-01"}
    ))
    assert resultado["eventos"] == []


# ── consultar_cliente ────────────────────────────────────────────────────────────────────────


def test_consultar_cliente_encontra_por_nome_parcial(db: Session):
    db.add(Client(tenant_id=TENANT, name="João da Silva", phone="11999998888", source="manual"))
    db.commit()
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_cliente", {"nome": "João"}))
    assert len(resultado["clientes"]) == 1
    assert resultado["clientes"][0]["nome"] == "João da Silva"
    assert resultado["clientes"][0]["ultima_interacao"] is None


def test_consultar_cliente_sem_match_devolve_lista_vazia(db: Session):
    resultado = json.loads(tools.executar(db, _usuario(), "consultar_cliente", {"nome": "Ninguém"}))
    assert resultado["clientes"] == []


# ── Falha nunca sobe crua ───────────────────────────────────────────────────────────────────


def test_ferramenta_com_entrada_invalida_devolve_erro_em_vez_de_estourar(db: Session):
    resultado = json.loads(
        tools.executar(db, _usuario(), "consultar_agenda", {"data_inicio": "não é uma data"})
    )
    assert "erro" in resultado
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.vima.tools'`.

- [ ] **Step 3: Implement `vima/tools.py`**

Create `apps/api/app/modules/vima/tools.py`:

```python
"""Ferramentas de leitura que a Vima oferece à Claude no loop de `POST /vima/pergunta`.

Cada ferramenta é um wrapper fino sobre um serviço determinístico que já existe — a Claude
escolhe QUAL consultar, nunca calcula o número ela mesma (mesma disciplina de
`vima/absences.py`: "a IA só NARRA, nunca origina número"). O filtro de permissão decide quais
ferramentas a Claude sequer VÊ, não quais respostas aparecem depois de já vistas — mesmo
princípio de `vima/service.gerar_ou_ler` para o briefing.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.core.tz import day_window_utc
from app.modules.agenda import service as agenda_service
from app.modules.crm import service as crm_service
from app.modules.crm import timeline as crm_timeline
from app.modules.financial_intelligence import projection as projection_service
from app.modules.payables import service as payables_service
from app.modules.receivables import service as receivables_service
from app.modules.settings.service import tenant_timezone
from app.modules.vima.permissions import pode_ver


def _consultar_recebiveis(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:
    return receivables_service.summary(db)


def _consultar_pagaveis(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:
    return payables_service.summary(db)


def _consultar_projecao_caixa(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:
    return asdict(projection_service.cash_projection(db))


def _consultar_agenda(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:
    tz = tenant_timezone(db)
    inicio = date.fromisoformat(entrada["data_inicio"])
    fim = date.fromisoformat(entrada.get("data_fim") or entrada["data_inicio"])
    janela_inicio, _ = day_window_utc(inicio, tz)
    _, janela_fim = day_window_utc(fim, tz)
    eventos = agenda_service.list_events(
        db, start=janela_inicio, end=janela_fim, exclude_cancelled=True, limit=50,
    )
    return {
        "eventos": [
            {
                "titulo": e.title,
                "inicio": e.starts_at.isoformat(),
                "fim": e.ends_at.isoformat(),
                "dia_inteiro": e.all_day,
                "status": e.status,
                "tipo": e.kind,
            }
            for e in eventos
        ]
    }


def _consultar_cliente(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:
    nome = entrada["nome"]
    clientes = crm_service.list_clients(db, search=nome, limit=5)
    resultado = []
    for cliente in clientes:
        entradas, _ = crm_timeline.build(db, client_id=cliente.id, limit=1)
        ultima = entradas[0] if entradas else None
        resultado.append({
            "id": cliente.id,
            "nome": cliente.name,
            "telefone": cliente.phone,
            "tags": cliente.tags,
            "origem": cliente.source,
            "ultima_interacao": (
                {"titulo": ultima["title"], "quando": ultima["at"].isoformat()}
                if ultima else None
            ),
        })
    return {"clientes": resultado}


@dataclass
class Ferramenta:
    nome: str
    # Nome de módulo em `User.allowed_modules` — decide se a Claude VÊ esta ferramenta.
    modulo: str
    # Schema no formato de tool-use da Anthropic (`name`/`description`/`input_schema`).
    definicao: dict[str, Any]
    executar: Callable[[Session, dict[str, Any]], dict[str, Any]]


FERRAMENTAS: list[Ferramenta] = [
    Ferramenta(
        nome="consultar_recebiveis",
        modulo="receivables",
        definicao={
            "name": "consultar_recebiveis",
            "description": (
                "Resumo do que o dono tem a RECEBER de clientes: total em aberto, vencido, já "
                "recebido, e as contagens de cada um. Use para perguntas sobre dinheiro a "
                "receber."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_recebiveis,
    ),
    Ferramenta(
        nome="consultar_pagaveis",
        modulo="payables",
        definicao={
            "name": "consultar_pagaveis",
            "description": (
                "Resumo do que o dono tem a PAGAR: total em aberto, vencido, da semana, do mês, "
                "já pago no mês. Use para perguntas sobre dinheiro a pagar ou despesas."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_pagaveis,
    ),
    Ferramenta(
        nome="consultar_projecao_caixa",
        modulo="financial_intelligence",
        definicao={
            "name": "consultar_projecao_caixa",
            "description": (
                "Projeção de caixa em 30/60/90 dias e o runway (quantos dias o caixa aguenta no "
                "ritmo atual de gasto). Use para perguntas sobre quanto tempo o caixa aguenta ou "
                "como vai ficar o saldo."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        executar=_consultar_projecao_caixa,
    ),
    Ferramenta(
        nome="consultar_agenda",
        modulo="agenda",
        definicao={
            "name": "consultar_agenda",
            "description": (
                "Compromissos da agenda entre duas datas (inclusive). Use para perguntas sobre "
                "o que o dono tem marcado num dia ou período."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "data_inicio": {
                        "type": "string",
                        "description": "Data no formato AAAA-MM-DD.",
                    },
                    "data_fim": {
                        "type": "string",
                        "description": (
                            "Data final no formato AAAA-MM-DD. Se omitida, usa a mesma de "
                            "data_inicio."
                        ),
                    },
                },
                "required": ["data_inicio"],
            },
        },
        executar=_consultar_agenda,
    ),
    Ferramenta(
        nome="consultar_cliente",
        modulo="crm",
        definicao={
            "name": "consultar_cliente",
            "description": (
                "Busca cliente(s) pelo nome (ou parte dele) e devolve contato, tags, origem e a "
                "última interação registrada. Use para perguntas sobre um cliente específico."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string", "description": "Nome ou parte do nome do cliente."},
                },
                "required": ["nome"],
            },
        },
        executar=_consultar_cliente,
    ),
]


def ferramentas_disponiveis(user: CurrentUser) -> list[Ferramenta]:
    """As ferramentas que este usuário PODE VER — o filtro decide o que a Claude enxerga, não o
    que ela esconde depois de já ter visto."""
    return [f for f in FERRAMENTAS if pode_ver(user, f.modulo)]


def executar(db: Session, user: CurrentUser, nome: str, entrada: dict[str, Any]) -> str:
    """Executa uma ferramenta pelo nome, respeitando a MESMA lista que foi oferecida à Claude.

    Nunca deixa uma exceção subir crua: o loop de tool-use precisa de um `tool_result` sempre,
    mesmo quando a consulta falha — a Claude é instruída (ver `vima/pergunta.py`) a dizer que
    não conseguiu, nunca a inventar (Artigo IV, No Invention).
    """
    disponiveis = {f.nome: f for f in ferramentas_disponiveis(user)}
    ferramenta = disponiveis.get(nome)
    if ferramenta is None:
        return json.dumps({"erro": "ferramenta indisponível para este usuário"})
    try:
        resultado = ferramenta.executar(db, entrada)
    except Exception:  # noqa: BLE001 — tool_result sempre existe; a Claude decide o que dizer.
        return json.dumps({"erro": "não foi possível consultar isso agora"})
    return json.dumps(resultado, default=str, ensure_ascii=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_tools.py -v`
Expected: PASS, 13 tests. If `test_consultar_recebiveis_delega_para_o_resumo_real` or the
agenda test fail on an attribute name, open `apps/api/app/modules/receivables/models.py` /
`apps/api/app/modules/agenda/models.py` and match the tool's field access to the real model
attribute names — the ORM attribute names must equal the ones already used in each module's own
`EventOut`/`ChargesSummary` mapping code (already confirmed in the spec's research, but re-check
if a test disagrees).

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/tools.py apps/api/tests/test_vima_tools.py
git commit -m "feat: vima/tools — cinco ferramentas de leitura sobre financeiro, agenda e CRM

Wrappers finos de receivables.summary, payables.summary, cash_projection,
agenda.list_events e crm.list_clients+timeline. Filtro de permissão decide o que a
Claude VÊ; toda falha vira {erro: ...} em vez de subir crua."
```

---

## Task 3: `vima/pergunta.py` — orchestration (anonymize, loop, audit)

**Files:**
- Create: `apps/api/app/modules/vima/pergunta.py`
- Test: `apps/api/tests/test_vima_pergunta_service.py`

**Interfaces:**
- Consumes: `ai.complete_with_tools` (Task 1), `tools.ferramentas_disponiveis` /
  `tools.executar` (Task 2), `anonymizer.mask`/`unmask` (existing), `audit.record` (existing).
- Produces: `pergunta.Turno` (dataclass: `papel: str`, `texto: str`), `pergunta.Resposta`
  (dataclass: `texto: str`, `por_ia: bool`), `pergunta.responder(db, *, user, pergunta,
  historico: list[Turno]) -> Resposta` — consumed by Task 4.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_vima_pergunta_service.py`:

```python
"""`vima.pergunta.responder` — mascara antes de mandar, desmascara a resposta, registra rastro
de IA, e degrada graciosamente sem chave configurada."""
from sqlalchemy.orm import Session

from app.core.audit import AuditEntry
from app.core.tenancy import CurrentUser
from app.modules.vima import pergunta

TENANT = "t1"


def _usuario() -> CurrentUser:
    return CurrentUser(user_id="u1", tenant_id=TENANT, role="owner", allowed_modules=[])


def test_sem_chave_de_api_degrada_sem_quebrar(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")
    resultado = pergunta.responder(db, user=_usuario(), pergunta="oi", historico=[])
    assert resultado.por_ia is False
    assert resultado.texto


def test_manda_a_pergunta_mascarada_e_desmascara_a_resposta(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    capturado = {}

    def _fake_loop(*, db, tenant_id, task, system, user_message, tools, executar_ferramenta,
                    user_id=None, **_kw):
        capturado["user_message"] = user_message
        capturado["task"] = task
        capturado["tenant_id"] = tenant_id
        # eco do e-mail mascarado, como a Claude faria ao citar o dado de volta
        texto = f"o contato é {user_message.split()[-1]}"
        return type("R", (), {"text": texto})()

    monkeypatch.setattr(pergunta.ai, "complete_with_tools", _fake_loop)

    resultado = pergunta.responder(
        db, user=_usuario(), pergunta="qual o e-mail do cliente joao@example.com", historico=[]
    )

    assert "joao@example.com" not in capturado["user_message"]
    assert capturado["task"] == "vima.pergunta"
    assert capturado["tenant_id"] == TENANT
    assert resultado.texto == "o contato é joao@example.com"
    assert resultado.por_ia is True


def test_registra_rastro_de_ia_quando_a_ia_de_fato_respondeu(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    monkeypatch.setattr(
        pergunta.ai, "complete_with_tools",
        lambda **_kw: type("R", (), {"text": "resposta"})(),
    )
    pergunta.responder(db, user=_usuario(), pergunta="e ai", historico=[])
    db.commit()
    assert db.query(AuditEntry).filter_by(action="vima.pergunta.respondida").count() == 1


def test_historico_entra_no_texto_mandado_a_claude(db: Session, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    capturado = {}

    def _fake_loop(*, user_message, **_kw):
        capturado["user_message"] = user_message
        return type("R", (), {"text": "ok"})()

    monkeypatch.setattr(pergunta.ai, "complete_with_tools", _fake_loop)
    pergunta.responder(
        db, user=_usuario(), pergunta="e essa semana?",
        historico=[pergunta.Turno(papel="usuario", texto="quanto tenho a receber?"),
                    pergunta.Turno(papel="vima", texto="R$ 1.000,00")],
    )
    assert "quanto tenho a receber?" in capturado["user_message"]
    assert "R$ 1.000,00" in capturado["user_message"]
    assert "e essa semana?" in capturado["user_message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_pergunta_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.vima.pergunta'`.

- [ ] **Step 3: Implement `vima/pergunta.py`**

Create `apps/api/app/modules/vima/pergunta.py`:

```python
"""Orquestra o loop de pergunta-e-resposta da Vima (`POST /vima/pergunta`).

Sem persistência: o histórico da conversa vive só no que o front reenvia a cada pergunta (ver
spec `docs/superpowers/specs/2026-08-28-vima-pergunte-design.md`). A pergunta do dono e os
resultados das ferramentas chegam à Claude SEM anonimização de nome — extensão explícita do
risco aceito pelo fundador em 2026-07-11 para o Diagnóstico Financeiro (CLAUDE.md §6.1). PII
ESTRUTURAL (CPF/CNPJ/e-mail/telefone) continua mascarada, como em qualquer outra chamada de IA
(Regra de Ouro nº 2) — só o texto INICIAL passa pelo anonimizador; os resultados de ferramenta
não são mascarados (decisão da spec).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.core import ai, audit
from app.core.anonymizer import anonymizer
from app.core.tenancy import CurrentUser
from app.modules.vima import tools

_SYSTEM = (
    "Você é a Vima, a assistente do dono deste negócio dentro do e1p. Responda perguntas sobre "
    "o negócio SOMENTE com base no que as ferramentas devolverem — nunca invente um número, uma "
    "data ou um nome. Se não tiver uma ferramenta que responda a pergunta, diga isso claramente "
    "em vez de adivinhar. Responda em português do Brasil, direto e sem rodeios."
)


@dataclass
class Turno:
    papel: str  # "usuario" | "vima"
    texto: str


@dataclass
class Resposta:
    texto: str
    por_ia: bool


def responder(db: Session, *, user: CurrentUser, pergunta: str, historico: list[Turno]) -> Resposta:
    if not settings.anthropic_api_key:
        return Resposta(
            texto="A Vima está sem acesso à IA agora — pergunte de novo mais tarde.",
            por_ia=False,
        )

    definicoes = [f.definicao for f in tools.ferramentas_disponiveis(user)]
    seguro, mapa = anonymizer.mask(_com_historico(pergunta, historico))

    def _executar(nome: str, entrada: dict) -> str:
        return tools.executar(db, user, nome, entrada)

    resultado = ai.complete_with_tools(
        db=db, tenant_id=user.tenant_id, task="vima.pergunta", system=_SYSTEM,
        user_message=seguro, tools=definicoes, executar_ferramenta=_executar,
        user_id=user.user_id,
    )
    texto = anonymizer.unmask(resultado.text, mapa)
    audit.record(
        db, tenant_id=user.tenant_id, actor="ai", action="vima.pergunta.respondida",
        target="", is_ai=True,
    )
    return Resposta(texto=texto, por_ia=True)


def _com_historico(pergunta: str, historico: list[Turno]) -> str:
    if not historico:
        return pergunta
    linhas = [f"{'Dono' if t.papel == 'usuario' else 'Vima'}: {t.texto}" for t in historico]
    linhas.append(f"Dono: {pergunta}")
    return "\n".join(linhas)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_pergunta_service.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Run the full backend fast suite**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/vima/pergunta.py apps/api/tests/test_vima_pergunta_service.py
git commit -m "feat: vima/pergunta.responder — orquestra mascaramento, loop e rastro de IA

Mascara a pergunta+histórico antes de mandar (Regra de Ouro nº 2), roda
complete_with_tools com as ferramentas visíveis para o usuário, desmascara a
resposta final e grava vima.pergunta.respondida no audit quando a IA respondeu."
```

---

## Task 4: `POST /vima/pergunta` — the HTTP endpoint

**Files:**
- Modify: `apps/api/app/modules/vima/schemas.py`
- Modify: `apps/api/app/modules/vima/router.py`
- Test: `apps/api/tests/test_vima_pergunta_endpoint.py`

**Interfaces:**
- Consumes: `pergunta.responder`, `pergunta.Turno` (Task 3).
- Produces: HTTP `POST /vima/pergunta` — request `{texto: str, historico: [{papel, texto}]}`,
  response `{resposta: str, por_ia: bool}`.

- [ ] **Step 1: Write the failing tests**

Create `apps/api/tests/test_vima_pergunta_endpoint.py`:

```python
"""`POST /vima/pergunta` — o contrato HTTP em cima de `pergunta.responder`."""
import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token

REGISTER = {
    "legal_name": "Pergunta ME", "document": "11444777000161", "slug": "perguntame",
    "email": "pergunta@example.com", "name": "Flávio", "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def test_pergunta_sem_chave_de_api_responde_sem_ia(client: TestClient, headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "")
    resp = client.post("/vima/pergunta", json={"texto": "oi", "historico": []}, headers=headers)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["por_ia"] is False
    assert corpo["resposta"]


def test_pergunta_chama_o_servico_e_devolve_a_resposta(client: TestClient, headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")

    def _fake(db, *, user, pergunta, historico):
        from app.modules.vima.pergunta import Resposta
        assert pergunta == "quanto tenho a receber?"
        assert historico == []
        return Resposta(texto="R$ 500,00", por_ia=True)

    monkeypatch.setattr("app.modules.vima.pergunta.responder", _fake)
    resp = client.post(
        "/vima/pergunta", json={"texto": "quanto tenho a receber?", "historico": []},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"resposta": "R$ 500,00", "por_ia": True}


def test_pergunta_repassa_o_historico_para_o_servico(client: TestClient, headers, monkeypatch):
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "sk-fake")
    capturado = {}

    def _fake(db, *, user, pergunta, historico):
        from app.modules.vima.pergunta import Resposta
        capturado["historico"] = historico
        return Resposta(texto="ok", por_ia=True)

    monkeypatch.setattr("app.modules.vima.pergunta.responder", _fake)
    client.post(
        "/vima/pergunta",
        json={
            "texto": "e essa semana?",
            "historico": [{"papel": "usuario", "texto": "quanto tenho a receber?"},
                          {"papel": "vima", "texto": "R$ 500,00"}],
        },
        headers=headers,
    )
    historico = capturado["historico"]
    assert [(t.papel, t.texto) for t in historico] == [
        ("usuario", "quanto tenho a receber?"), ("vima", "R$ 500,00"),
    ]


def test_pergunta_sem_autenticacao_e_rejeitada(client: TestClient):
    resp = client.post("/vima/pergunta", json={"texto": "oi", "historico": []})
    assert resp.status_code in (401, 403)


def test_pergunta_vazia_e_rejeitada_pela_validacao(client: TestClient, headers):
    resp = client.post("/vima/pergunta", json={"texto": "", "historico": []}, headers=headers)
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_pergunta_endpoint.py -v`
Expected: FAIL — `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the schemas**

Edit `apps/api/app/modules/vima/schemas.py`. Add `Literal` to the `pydantic`-adjacent imports
(`from typing import Literal` under the existing `import json` / `from datetime import ...`
block), then append at the end of the file:

```python
class TurnoIn(BaseModel):
    papel: Literal["usuario", "vima"]
    texto: str


class PerguntaIn(BaseModel):
    texto: str = Field(min_length=1)
    historico: list[TurnoIn] = []


class PerguntaOut(BaseModel):
    resposta: str
    por_ia: bool
```

Add `Field` to the existing `from pydantic import BaseModel, ConfigDict` import line, turning it
into `from pydantic import BaseModel, ConfigDict, Field`.

- [ ] **Step 4: Wire the route**

Edit `apps/api/app/modules/vima/router.py`. Change the imports block to:

```python
from app.core.tenancy import CurrentUser, get_current_user, get_tenant_db
from app.modules.vima import pergunta as pergunta_service
from app.modules.vima import service
from app.modules.vima.schemas import BriefingOut, PerguntaIn, PerguntaOut, to_out
```

Then append at the end of the file:

```python
@router.post("/pergunta", response_model=PerguntaOut)
def perguntar(
    corpo: PerguntaIn,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> PerguntaOut:
    """O dono pergunta, a Vima responde consultando os dados reais. Sem persistência: o
    histórico vem do front a cada chamada (ver spec 2026-08-28)."""
    historico = [
        pergunta_service.Turno(papel=t.papel, texto=t.texto) for t in corpo.historico
    ]
    resultado = pergunta_service.responder(
        db, user=user, pergunta=corpo.texto, historico=historico
    )
    return PerguntaOut(resposta=resultado.texto, por_ia=resultado.por_ia)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_vima_pergunta_endpoint.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Run the full backend fast suite + gates**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q`
Expected: PASS.
Run: `bash scripts/check.sh` (from repo root)
Expected: lint + types + tests all pass.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/vima/schemas.py apps/api/app/modules/vima/router.py \
  apps/api/tests/test_vima_pergunta_endpoint.py
git commit -m "feat: POST /vima/pergunta — endpoint HTTP do loop de pergunta-e-resposta

Sem require_module, mesma decisão de /vima/briefing: o recorte de permissão
acontece por ferramenta dentro da resposta, não na rota. Sem persistência —
historico vem do corpo da requisição a cada chamada."
```

---

## Task 5: RLS proof — a tool never leaks across tenants

**Files:**
- Create: `apps/api/tests/test_vima_tools_rls.py`

**Interfaces:**
- Consumes: `tools.executar` (Task 2), the same Postgres-testcontainer bootstrap pattern as
  `apps/api/tests/test_ai_usage_rls.py`.
- Produces: nothing new — this is a pure verification task.

- [ ] **Step 1: Write the RLS test**

Create `apps/api/tests/test_vima_tools_rls.py`:

```python
"""Isolamento cross-tenant de `vima/tools.executar` no Postgres REAL (Regra de Ouro nº 1).

`consultar_cliente` é a ferramenta que mais convida a vazar: ela recebe um NOME livre digitado
pela Claude, e é exatamente esse tipo de busca por texto que testaria o filtro errado (um
`ilike` sem `tenant_id` explícito) se alguém "otimizasse" a query por engano. A garantia real é
a mesma RLS de sempre — este teste prova que a ferramenta não abre uma segunda porta.

Mesmo bootstrap dos demais `*_rls.py`: engine SQLAlchemy cru da URL do container, migrations
aplicadas com `alembic upgrade head` como `e1p_app`. Módulo marcado `rls_e2e`: NÃO roda no
`pytest -q` (suíte SQLite), só no job dedicado do CI (`cross-tenant-rls`) ou manualmente com
Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"

_API_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _run_migrations_as_app(app_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original_url


@contextmanager
def _tenant_session(app_url: str, tenant_id: str):
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_id},
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


def _criar_cliente(app_url: str, *, tenant_id: str, nome: str) -> str:
    from app.modules.crm.models import Client

    with _tenant_session(app_url, tenant_id) as session:
        cliente = Client(tenant_id=tenant_id, name=nome, source="manual")
        session.add(cliente)
        session.commit()
        return cliente.id


def _consultar_cliente(app_url: str, *, tenant_id: str, nome: str) -> dict:
    import json

    from app.core.tenancy import CurrentUser
    from app.modules.vima import tools

    usuario = CurrentUser(user_id="u1", tenant_id=tenant_id, role="owner", allowed_modules=[])
    with _tenant_session(app_url, tenant_id) as session:
        resultado = tools.executar(session, usuario, "consultar_cliente", {"nome": nome})
        return json.loads(resultado)


def test_consultar_cliente_isola_por_tenant() -> None:
    with PostgresContainer(
        "postgres:16-alpine", username=_ROOT_USER, password=_ROOT_PASS, dbname=_DB_NAME,
        driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        _criar_cliente(app_url, tenant_id=tenant_a, nome="Maria Fernandes")
        _criar_cliente(app_url, tenant_id=tenant_b, nome="Maria Fernandes")

        # Cada tenant pede pelo MESMO nome — se a RLS falhar, um veria o cliente do outro.
        resultado_a = _consultar_cliente(app_url, tenant_id=tenant_a, nome="Maria")
        resultado_b = _consultar_cliente(app_url, tenant_id=tenant_b, nome="Maria")

        assert len(resultado_a["clientes"]) == 1, "RLS falhou: A viu 0 ou >1 clientes"
        assert len(resultado_b["clientes"]) == 1, "RLS falhou: B viu 0 ou >1 clientes"
        assert resultado_a["clientes"][0]["id"] != resultado_b["clientes"][0]["id"], (
            "RLS falhou: os dois tenants viram o MESMO cliente"
        )
        # Controle positivo: cada tenant realmente encontra o PRÓPRIO cliente — não é lista
        # vazia dos dois lados escondendo uma RLS aberta demais.
        assert resultado_a["clientes"][0]["nome"] == "Maria Fernandes"
        assert resultado_b["clientes"][0]["nome"] == "Maria Fernandes"
```

- [ ] **Step 2: Run it (requires Docker)**

Run: `cd apps/api && .venv/Scripts/python -m pytest -m rls_e2e tests/test_vima_tools_rls.py -v`
Expected: PASS, 1 test. If Docker isn't running locally, this step is verified instead by the
CI job `cross-tenant-rls` after the PR is opened — do not skip writing/committing the test on
that basis.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_vima_tools_rls.py
git commit -m "test: prova RLS de vima/tools.executar (consultar_cliente) sob Postgres real

Dois tenants cadastram um cliente com o MESMO nome; cada consulta só encontra o
próprio. Mesmo bootstrap de test_ai_usage_rls.py — roda no job cross-tenant-rls."
```

---

## Task 6: shared-types — request/response contracts

**Files:**
- Modify: `packages/shared-types/src/index.ts`

**Interfaces:**
- Produces: `Turno`, `PerguntaRequest`, `PerguntaResposta` (TypeScript interfaces) — consumed
  by Task 7.

- [ ] **Step 1: Add the types**

Edit `packages/shared-types/src/index.ts`. Find the existing Vima section (it starts with the
comment `// ── Vima: briefing do dia (Onda 4) ──` and contains the `Briefing`/`BriefingLinha`
interfaces). Immediately after the closing brace of the `Briefing` interface, insert:

```typescript

// ── Vima: pergunte à Vima (chat em texto) ────────────────────────────────────

export interface Turno {
  papel: "usuario" | "vima";
  texto: string;
}

export interface PerguntaRequest {
  texto: string;
  historico: Turno[];
}

export interface PerguntaResposta {
  resposta: string;
  por_ia: boolean;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd packages/shared-types && pnpm build` (or, from repo root, `pnpm --filter
@e1p/shared-types build`, matching whichever script exists in this package's `package.json` —
check `packages/shared-types/package.json` scripts if `build` doesn't exist; `tsc --noEmit` is
the fallback).
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add packages/shared-types/src/index.ts
git commit -m "feat(types): PerguntaRequest/PerguntaResposta/Turno para o chat da Vima"
```

---

## Task 7: `PerguntePage.tsx` — the chat screen

**Files:**
- Create: `apps/web/src/features/vima/PerguntePage.tsx`
- Test: `apps/web/src/features/vima/PerguntePage.test.tsx`

**Interfaces:**
- Consumes: `api`/`apiErrorMessage` from `../../lib/api`, `PerguntaRequest`/`PerguntaResposta`
  from `@e1p/shared-types`.
- Produces: default export `PerguntePage` — consumed by Task 8.

- [ ] **Step 1: Write the failing component test**

Create `apps/web/src/features/vima/PerguntePage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import PerguntePage from "./PerguntePage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    "Erro inesperado",
}));

beforeEach(() => {
  vi.mocked(api.post).mockReset();
});

describe("PerguntePage", () => {
  it("mostra uma dica quando não há mensagem nenhuma ainda", () => {
    render(<PerguntePage />);
    expect(screen.getByText(/pergunte sobre/i)).toBeInTheDocument();
  });

  it("envia a pergunta e mostra a resposta da Vima", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { resposta: "Você tem R$ 500,00 a receber.", por_ia: true },
    });
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(
      screen.getByPlaceholderText(/digite sua pergunta/i),
      "quanto tenho a receber?{enter}",
    );

    expect(await screen.findByText("quanto tenho a receber?")).toBeInTheDocument();
    expect(await screen.findByText("Você tem R$ 500,00 a receber.")).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("/vima/pergunta", {
      texto: "quanto tenho a receber?",
      historico: [],
    });
  });

  it("a segunda pergunta reenvia o histórico da primeira", async () => {
    vi.mocked(api.post)
      .mockResolvedValueOnce({ data: { resposta: "R$ 500,00", por_ia: true } })
      .mockResolvedValueOnce({ data: { resposta: "R$ 100,00 essa semana", por_ia: true } });
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(
      screen.getByPlaceholderText(/digite sua pergunta/i),
      "quanto tenho a receber?{enter}",
    );
    await screen.findByText("R$ 500,00");
    await usuario.type(screen.getByPlaceholderText(/digite sua pergunta/i), "e essa semana?{enter}");
    await screen.findByText("R$ 100,00 essa semana");

    expect(api.post).toHaveBeenLastCalledWith("/vima/pergunta", {
      texto: "e essa semana?",
      historico: [
        { papel: "usuario", texto: "quanto tenho a receber?" },
        { papel: "vima", texto: "R$ 500,00" },
      ],
    });
  });

  it("mostra o erro sem derrubar a tela quando a requisição falha", async () => {
    vi.mocked(api.post).mockRejectedValue({ response: { data: { detail: "IA indisponível" } } });
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(screen.getByPlaceholderText(/digite sua pergunta/i), "oi{enter}");
    expect(await screen.findByText("IA indisponível")).toBeInTheDocument();
  });

  it("não envia pergunta vazia", async () => {
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(screen.getByPlaceholderText(/digite sua pergunta/i), "   {enter}");
    await waitFor(() => expect(api.post).not.toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && pnpm vitest run src/features/vima/PerguntePage.test.tsx`
Expected: FAIL — module `./PerguntePage` not found.

- [ ] **Step 3: Implement `PerguntePage.tsx`**

Create `apps/web/src/features/vima/PerguntePage.tsx`:

```tsx
import { Send } from "lucide-react";
import { useState } from "react";
import type { PerguntaResposta, Turno } from "@e1p/shared-types";
import { api, apiErrorMessage } from "../../lib/api";

interface Mensagem {
  papel: "usuario" | "vima";
  texto: string;
}

export default function PerguntePage() {
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [texto, setTexto] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function enviar() {
    const pergunta = texto.trim();
    if (!pergunta || carregando) return;

    const historico: Turno[] = mensagens.map((m) => ({ papel: m.papel, texto: m.texto }));
    setTexto("");
    setErro(null);
    setMensagens((atual) => [...atual, { papel: "usuario", texto: pergunta }]);
    setCarregando(true);
    try {
      const { data } = await api.post<PerguntaResposta>("/vima/pergunta", {
        texto: pergunta,
        historico,
      });
      setMensagens((atual) => [...atual, { papel: "vima", texto: data.resposta }]);
    } catch (err) {
      setErro(apiErrorMessage(err));
    } finally {
      setCarregando(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <h1 className="mb-3 shrink-0 text-lg font-semibold text-neutral-900">Pergunte à Vima</h1>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-lg border border-neutral-200 bg-white p-3">
        {mensagens.length === 0 && (
          <p className="text-sm text-neutral-400">
            Pergunte sobre o que você tem a receber, a pagar, sua agenda ou um cliente.
          </p>
        )}
        {mensagens.map((m, i) => (
          <div
            key={i}
            className={`max-w-[85%] min-w-0 break-words rounded-xl px-3 py-2 text-sm ${
              m.papel === "usuario"
                ? "ml-auto bg-primary-600 text-white"
                : "mr-auto bg-neutral-100 text-neutral-800"
            }`}
          >
            <p className="whitespace-pre-wrap">{m.texto}</p>
          </div>
        ))}
        {carregando && (
          <div className="mr-auto max-w-[85%] rounded-xl bg-neutral-100 px-3 py-2 text-sm text-neutral-400">
            Consultando...
          </div>
        )}
      </div>
      {erro && <p className="mt-2 shrink-0 text-sm text-red-600">{erro}</p>}
      <div className="mt-3 flex shrink-0 gap-2">
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && enviar()}
          placeholder="Digite sua pergunta..."
          className="min-h-[44px] min-w-0 flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
        />
        <button
          onClick={enviar}
          disabled={carregando}
          className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-pill bg-primary-600 p-2 text-white hover:bg-primary-700 disabled:opacity-50"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && pnpm vitest run src/features/vima/PerguntePage.test.tsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/vima/PerguntePage.tsx apps/web/src/features/vima/PerguntePage.test.tsx
git commit -m "feat(web): PerguntePage — chat da Vima, histórico só no estado do React

Sem persistência: cada envio reenvia o histórico da sessão atual. Alvos de 44px
nos controles, break-words nas bolhas (nome/valor digitado pode não ter espaço)."
```

---

## Task 8: routing + nav entry

**Files:**
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/app/navigation.ts`
- Modify: `apps/web/src/app/navigation.test.ts`

**Interfaces:**
- Consumes: `PerguntePage` (Task 7).
- Produces: route `/vima/perguntas` reachable inside `ProtectedLayout`, with a sidebar entry.

- [ ] **Step 1: Add the route**

Edit `apps/web/src/app/App.tsx`. Add the import near the other `vima` import:

```tsx
import BriefingPage from "../features/vima/BriefingPage";
import PerguntePage from "../features/vima/PerguntePage";
```

Then, inside the `<Route element={<ProtectedLayout />}>` block, add the new route right after
the `/conversas` entry:

```tsx
<Route path="/conversas" element={<Modulo m="crm"><ConversasPage /></Modulo>} />
<Route path="/vima/perguntas" element={<PerguntePage />} />
```

No `<Modulo>` wrapper — same decision as `/vima/briefing`: any authenticated user can open the
chat, and permission recorte happens per-tool inside the response, not at the route.

- [ ] **Step 2: Add the nav entry**

Edit `apps/web/src/app/navigation.ts`. Add `Sparkles` to the `lucide-react` import (it's not
used by any other nav entry, so it stays visually distinct from "Conversas"'s `MessageCircle`):

```typescript
import { MessageCircle, Sparkles, /* ...resto da lista já existente... */ } from "lucide-react";
```

Then, right after the `"Conversas"` entry, add:

```typescript
{ label: "Conversas", to: "/conversas", icon: MessageCircle, ready: true, module: "crm" },
// Sem `module`, de propósito — mesma decisão de /vima/briefing: qualquer usuário abre; o
// recorte de permissão acontece por FERRAMENTA dentro da resposta, não na visibilidade do menu.
{ label: "Pergunte à Vima", to: "/vima/perguntas", icon: Sparkles, ready: true },
```

- [ ] **Step 3: Update `navigation.test.ts` for the new item**

Edit `apps/web/src/app/navigation.test.ts`. Change the "esta story acrescentou exatamente UM
item" test (around line 81) to account for this second addition since Story 8.7:

```typescript
  it("acrescentou DOIS itens desde a 8.7 (Contas & Saldos + Pergunte à Vima)", () => {
    expect(itens).toHaveLength(ROTAS_PRE_8_7.length + 2);
  });
```

And update the now-stale comment on the "nenhum item de menu tem module" test (around line
103-107), since `"Pergunte à Vima"` is now the first item without one:

```typescript
  it("sub-usuário sem nenhum módulo não vê NENHUM item de negócio — só 'Pergunte à Vima' sobra", () => {
    const secoes = visibleNavSections(() => false);
    const visiveis = secoes.flatMap((s) => s.items);
    // "Pergunte à Vima" é o único item sem `module` hoje — mesma razão de /vima/briefing não
    // ter require_module: o recorte acontece por ferramenta, não por rota/menu.
    expect(visiveis.every((i) => !i.module)).toBe(true);
    expect(visiveis.map((i) => i.to)).toContain("/vima/perguntas");
  });
```

- [ ] **Step 4: Run the frontend tests**

Run: `cd apps/web && pnpm vitest run src/app/navigation.test.ts`
Expected: PASS.

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/App.tsx apps/web/src/app/navigation.ts apps/web/src/app/navigation.test.ts
git commit -m "feat(web): rota /vima/perguntas + item de menu 'Pergunte à Vima'

Sem <Modulo>/module — mesma decisão do /vima/briefing: o recorte de permissão
acontece por ferramenta na resposta, não na visibilidade da rota/menu."
```

---

## Task 9: 360px e2e coverage for `/vima/perguntas`

**Files:**
- Modify: `apps/web/e2e/support/rotas.ts`

**Interfaces:**
- Consumes: the shared `Caso` catalog loop in `rotas-360.spec.ts` and `alcance-360.spec.ts`
  (no new spec file — those two generic specs iterate `CASOS` automatically).

- [ ] **Step 1: Add the worst-case fixture and the `Caso` entry**

Edit `apps/web/e2e/support/rotas.ts`. Near the file's existing worst-case fixtures (alongside
`BRIEFING`, using the same `LONGO` constant for an unbroken-token worst case — a client name or
answer text typed without spaces), add:

```typescript
export const PERGUNTA_RESPOSTA = {
  resposta: `A última interação com ${LONGO} foi ${LONGO} atrás, e ela tem ${LONGO} a receber.`,
  por_ia: true,
};
```

Then, in the `CASOS` array, add an entry (the `marca` must be text visible in the EMPTY state,
since the page loads with no messages and nothing is fetched on mount):

```typescript
{
  rota: "/vima/perguntas",
  marca: "Pergunte à Vima",
  mocks: { "/vima/pergunta": PERGUNTA_RESPOSTA },
},
```

- [ ] **Step 2: Run the two generic 360px specs**

Run: `cd apps/web && E2E_PORT=5373 pnpm e2e -- rotas-360.spec.ts alcance-360.spec.ts` (custom
port avoids colliding with another worktree's Vite dev server on 5273, per this repo's own
convention).
Expected: PASS — including a new `/vima/perguntas não faz o documento rolar de lado em 360px`
case and its `alcance-360` counterpart. If either fails, the failure is real: this page renders
with `main.overflow-x-hidden` from the normal `AppShell` (unlike the bare-layout Vima screens),
so a long unbroken word in a chat bubble would be CLIPPED, not push the page — check that
`break-words` and `min-w-0` are present on the bubble `div` from Task 7 before assuming the
fixture is wrong.

- [ ] **Step 3: Commit**

```bash
git add apps/web/e2e/support/rotas.ts
git commit -m "test(e2e): /vima/perguntas entra no catálogo de 360px (rotas-360 + alcance-360)

Fixture de pior caso com LONGO na resposta — a marca é o cabeçalho da tela, visível
mesmo sem nenhuma mensagem ainda (o mount não busca nada)."
```

---

## Final check: full gate before opening a PR

- [ ] **Step 1: Run the complete local gate**

Run (from repo root): `bash scripts/gates.sh`
Expected: `check.sh` (lint + types + fast tests) → `pytest -m rls_e2e` → `pnpm e2e`, all green,
run in series (never in parallel with another heavy suite on the same machine — §5.5 of
`CLAUDE.md`).

- [ ] **Step 2: Update `CLAUDE.md`**

Per this repository's own rule (§5, step 4 — "a lição mora nas Completion Notes, escrita a
partir do código que subiu"), add a short entry under a new `## Vima: pergunte e receba
resposta` heading (place it right after the existing `## Vima: o Registro de Fatos e o
briefing` section) summarizing: what now exists (`POST /vima/pergunta`, the five tools, the
tool-use loop as the first Anthropic tool-use consumer in the repo), the PII decision extending
the 2026-07-11 accepted risk, and the declared debt (WhatsApp channel, voice, persisted
history — all still open, per the spec's "Fora de escopo" section).

- [ ] **Step 3: Commit the CLAUDE.md entry**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md registra o pergunte-e-receba da Vima e a dívida que sobra"
```
