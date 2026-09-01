# Vima: ações de agenda — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar à Vima três ferramentas de escrita — `criar_compromisso`, `cancelar_compromisso`, `remarcar_compromisso` — no mesmo loop de tool-use que hoje só lê, fechando a dívida "Ações da Vima" do CLAUDE.md e a Regra de Ouro nº 3 (propagar `is_ai` nas escritas de agenda).

**Architecture:** Três wrappers finos em `vima/tools.py` sobre `agenda_service.create_event/cancel_event/reschedule_event`, que já aceitam `by_ai`. Nenhuma regra de negócio nova (conflito, RLS, espelho no Google já existem no serviço). Confirmação obrigatória via campo `confirmado: bool` + disciplina de prompt em `vima/pergunta.py`. Mesmo gate de permissão das ferramentas de leitura (`pode_ver(user, "agenda")`).

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, pytest (SQLite em memória para unitário, Postgres real via testcontainers para RLS).

**Spec:** `docs/superpowers/specs/2026-09-01-vima-acoes-de-agenda-design.md`

## Global Constraints

- Escrita só ocorre com `confirmado=true` explícito no payload da ferramenta — ausente ou `false` devolve `{"erro": "..."}` sem tocar o banco (spec, "Confirmação").
- Toda chamada de escrita passa `by_ai=True` e `actor=user.user_id` para os serviços de agenda (Regra de Ouro nº 3 do CLAUDE.md).
- Nenhuma query filtra tenant manualmente — a sessão já vem RLS-escopada (Regra de Ouro nº 1); só o `tenant_id` explícito é passado ao CRIAR uma linha nova, exatamente como `agenda_service.create_event` já exige.
- `criar_compromisso` só aceita `tipo` em `{atendimento, reuniao, audiencia, bloqueio, lembrete}` — os demais `ALL_KINDS` (`prazo`, `cobranca_receber`, `cobranca_pagar`, `google`) são derivados de outro módulo, nunca criados por chat.
- Duração padrão de 1h quando a hora de término é omitida, em `criar_compromisso` e `remarcar_compromisso`.
- Gate de visibilidade das 3 ferramentas novas é `pode_ver(user, "agenda")` — mesmo critério das ferramentas de leitura, nenhuma dimensão de permissão nova.
- Erros de domínio (`AgendaError`) e de formato (`ValueError`) chegam ao `tool_result` com a mensagem real, não a genérica — a Claude precisa saber SE foi "evento não encontrado" vs. "não consegui de jeito nenhum" para narrar direito (Artigo IV, No Invention: nunca dizer que deu certo quando não deu).

---

## File Structure

| Arquivo | Papel |
|---|---|
| `apps/api/app/modules/vima/tools.py` | Modificado: 3 ferramentas novas + `_evento_json` compartilhado + `Ferramenta.executar` ganha `user: CurrentUser` |
| `apps/api/tests/test_vima_tools.py` | Modificado: testes das 3 ferramentas novas + contagem do catálogo |
| `apps/api/app/modules/vima/pergunta.py` | Modificado: `_SYSTEM` ganha a disciplina de confirmação |
| `apps/api/tests/test_vima_pergunta_service.py` | Modificado: teste do novo trecho do prompt |
| `apps/api/tests/test_vima_tools_rls.py` | Modificado: prova de RLS cross-tenant para `cancelar_compromisso` |
| `CLAUDE.md` | Modificado: nova seção `## Vima: ações de agenda` |

Nenhum arquivo novo, nenhuma migration — tudo reaproveita `agenda/service.py`, `agenda/schemas.py` e `agenda/models.py` como já existem.

---

### Task 1: `criar_compromisso` (+ widen `Ferramenta.executar` para receber `user`)

**Files:**
- Modify: `apps/api/app/modules/vima/tools.py`
- Test: `apps/api/tests/test_vima_tools.py`

**Interfaces:**
- Consumes: `agenda_service.create_event(db, *, tenant_id, actor, by_ai, data: EventCreate) -> tuple[AgendaEvent, list[AgendaEvent]]`; `agenda_service.AgendaError`; `EventCreate` (`app.modules.agenda.schemas`); `crm_service.list_clients(db, search, limit) -> list[Client]`; `tenant_zone(tz_name) -> ZoneInfo` (`app.core.tz`, já existe, ainda não importado em `tools.py`); `tenant_timezone(db) -> str` (já importado).
- Produces: `_evento_json(e: AgendaEvent) -> dict[str, Any]` — serialização compartilhada, usada por `_consultar_agenda` e pelas 3 ferramentas de escrita (Tasks 2/3 dependem dela). `Ferramenta.executar` passa a ser `Callable[[Session, CurrentUser, dict[str, Any]], dict[str, Any]]` — Tasks 2/3 seguem essa assinatura.

Hoje `Ferramenta.executar` só recebe `(db, entrada)` porque as 9 ferramentas de leitura não precisam de identidade — a sessão já vem RLS-escopada. Escrever exige `tenant_id` (para carimbar a linha nova) e `actor` (para o rastro de auditoria), então esta task alarga a assinatura para TODAS as ferramentas — as de leitura passam a receber `user` e ignorá-lo (mesma convenção de parâmetro não usado que o arquivo já tem: `_entrada` quando o dado não é lido).

- [ ] **Step 1: Rodar a suíte atual para ter uma baseline verde**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py tests/test_vima_pergunta_service.py -v`
Expected: todos os testes existentes passam.

- [ ] **Step 2: Alargar a assinatura de `Ferramenta.executar` e o dispatch em `executar()`**

Em `apps/api/app/modules/vima/tools.py`, troque:

```python
@dataclass
class Ferramenta:
    nome: str
    # Nome de módulo em `User.allowed_modules` — decide se a Claude VÊ esta ferramenta.
    modulo: str
    # Schema no formato de tool-use da Anthropic (`name`/`description`/`input_schema`).
    definicao: dict[str, Any]
    executar: Callable[[Session, dict[str, Any]], dict[str, Any]]
```

por:

```python
@dataclass
class Ferramenta:
    nome: str
    # Nome de módulo em `User.allowed_modules` — decide se a Claude VÊ esta ferramenta.
    modulo: str
    # Schema no formato de tool-use da Anthropic (`name`/`description`/`input_schema`).
    definicao: dict[str, Any]
    # `user` existe para as ferramentas de ESCRITA carimbarem tenant_id/actor — as de leitura
    # ignoram (mesma convenção de parâmetro não usado do resto do arquivo: `_user`).
    executar: Callable[[Session, CurrentUser, dict[str, Any]], dict[str, Any]]
```

E troque o corpo de `executar()`:

```python
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

por:

```python
def executar(db: Session, user: CurrentUser, nome: str, entrada: dict[str, Any]) -> str:
    """Executa uma ferramenta pelo nome, respeitando a MESMA lista que foi oferecida à Claude.

    Nunca deixa uma exceção subir crua: o loop de tool-use precisa de um `tool_result` sempre,
    mesmo quando a consulta/escrita falha — a Claude é instruída (ver `vima/pergunta.py`) a
    dizer que não conseguiu, nunca a inventar (Artigo IV, No Invention). Erro de domínio
    (`AgendaError`) e de formato (`ValueError`) chegam com a mensagem REAL — a genérica é só
    para o que não se sabe explicar.
    """
    disponiveis = {f.nome: f for f in ferramentas_disponiveis(user)}
    ferramenta = disponiveis.get(nome)
    if ferramenta is None:
        return json.dumps({"erro": "ferramenta indisponível para este usuário"})
    try:
        resultado = ferramenta.executar(db, user, entrada)
    except (agenda_service.AgendaError, ValueError) as exc:
        return json.dumps({"erro": str(exc)})
    except Exception:  # noqa: BLE001 — tool_result sempre existe; a Claude decide o que dizer.
        return json.dumps({"erro": "não foi possível consultar isso agora"})
    return json.dumps(resultado, default=str, ensure_ascii=False)
```

Agora ajuste a assinatura das 9 funções de leitura (uma troca de linha cada, corpo inalterado):

| Função | Linha atual | Linha nova |
|---|---|---|
| `_consultar_recebiveis` | `def _consultar_recebiveis(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_recebiveis(db: Session, _user: CurrentUser, _entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_pagaveis` | `def _consultar_pagaveis(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_pagaveis(db: Session, _user: CurrentUser, _entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_projecao_caixa` | `def _consultar_projecao_caixa(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_projecao_caixa(db: Session, _user: CurrentUser, _entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_agenda` | `def _consultar_agenda(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_agenda(db: Session, _user: CurrentUser, entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_cliente` | `def _consultar_cliente(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_cliente(db: Session, _user: CurrentUser, entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_documentos_juridicos` | `def _consultar_documentos_juridicos(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_documentos_juridicos(db: Session, _user: CurrentUser, entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_campanhas_marketing` | `def _consultar_campanhas_marketing(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_campanhas_marketing(db: Session, _user: CurrentUser, entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_estoque_baixo` | `def _consultar_estoque_baixo(db: Session, _entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_estoque_baixo(db: Session, _user: CurrentUser, _entrada: dict[str, Any]) -> dict[str, Any]:` |
| `_consultar_item_estoque` | `def _consultar_item_estoque(db: Session, entrada: dict[str, Any]) -> dict[str, Any]:` | `def _consultar_item_estoque(db: Session, _user: CurrentUser, entrada: dict[str, Any]) -> dict[str, Any]:` |

Nenhuma outra linha dessas 9 funções muda.

- [ ] **Step 3: Rodar a suíte de novo — deve continuar 100% verde (refactor não muda comportamento)**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py -v`
Expected: mesmos testes de antes, todos PASS. Se algum quebrar, a assinatura foi trocada errado — pare e corrija antes de seguir.

- [ ] **Step 4: Commit do refactor isolado**

```bash
git add apps/api/app/modules/vima/tools.py
git commit -m "refactor(vima): Ferramenta.executar ganha CurrentUser, sem mudar comportamento"
```

- [ ] **Step 5: Escrever os testes (falhando) de `criar_compromisso`**

Adicione em `apps/api/tests/test_vima_tools.py`, numa seção nova `# ── criar_compromisso ──` (após a seção de `consultar_agenda`):

```python
def test_criar_compromisso_sem_confirmado_nao_escreve(db: Session):
    from app.modules.agenda.models import AgendaEvent

    resultado = json.loads(tools.executar(
        db, _usuario(), "criar_compromisso",
        {"titulo": "Falar com o Carlos", "tipo": "reuniao", "data": "2026-09-02",
         "hora_inicio": "10:30"},
    ))
    assert "erro" in resultado
    assert db.query(AgendaEvent).count() == 0


def test_criar_compromisso_confirmado_cria_com_duracao_padrao_de_1h(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "criar_compromisso",
        {"titulo": "Falar com o Carlos", "tipo": "reuniao", "data": "2026-09-02",
         "hora_inicio": "10:30", "confirmado": True},
    ))
    assert resultado["compromisso"]["titulo"] == "Falar com o Carlos"
    assert resultado["compromisso"]["inicio"] == "2026-09-02T13:30:00+00:00"
    assert resultado["compromisso"]["fim"] == "2026-09-02T14:30:00+00:00"
    assert resultado["conflitos"] == []


def test_criar_compromisso_respeita_hora_fim_explicita(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "criar_compromisso",
        {"titulo": "Audiência", "tipo": "audiencia", "data": "2026-09-02",
         "hora_inicio": "09:00", "hora_fim": "11:00", "confirmado": True},
    ))
    assert resultado["compromisso"]["inicio"] == "2026-09-02T12:00:00+00:00"
    assert resultado["compromisso"]["fim"] == "2026-09-02T14:00:00+00:00"


def test_criar_compromisso_tipo_nao_criavel_devolve_erro(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "criar_compromisso",
        {"titulo": "X", "tipo": "prazo", "data": "2026-09-02", "hora_inicio": "10:00",
         "confirmado": True},
    ))
    assert "erro" in resultado


def test_criar_compromisso_devolve_conflito_sem_bloquear(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, AgendaEvent

    db.add(AgendaEvent(
        tenant_id=TENANT, title="Já marcado", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 2, 13, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 14, 0, tzinfo=UTC),
    ))
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "criar_compromisso",
        {"titulo": "Novo", "tipo": "reuniao", "data": "2026-09-02", "hora_inicio": "10:30",
         "confirmado": True},
    ))
    assert resultado["compromisso"]["titulo"] == "Novo"
    assert len(resultado["conflitos"]) == 1
    assert resultado["conflitos"][0]["titulo"] == "Já marcado"


def test_criar_compromisso_vincula_cliente_encontrado_por_nome(db: Session):
    db.add(Client(tenant_id=TENANT, name="Carlos Souza", phone="11999990000", source="manual"))
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "criar_compromisso",
        {"titulo": "Reunião", "tipo": "reuniao", "data": "2026-09-02", "hora_inicio": "10:00",
         "cliente": "Carlos", "confirmado": True},
    ))
    assert "aviso" not in resultado


def test_criar_compromisso_cliente_nao_encontrado_avisa_mas_ainda_cria(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "criar_compromisso",
        {"titulo": "Reunião", "tipo": "reuniao", "data": "2026-09-02", "hora_inicio": "10:00",
         "cliente": "Ninguém", "confirmado": True},
    ))
    assert resultado["compromisso"]["titulo"] == "Reunião"
    assert "não encontrado" in resultado["aviso"]
```

- [ ] **Step 6: Rodar os testes novos e confirmar que falham por `ImportError`/`KeyError` de ferramenta inexistente**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py -k criar_compromisso -v`
Expected: FAIL — `criar_compromisso` ainda não está em `FERRAMENTAS`.

- [ ] **Step 7: Implementar `_evento_json`, o refactor de `_consultar_agenda` para usá-lo, e `_criar_compromisso`**

No topo de `apps/api/app/modules/vima/tools.py`, ajuste os imports:

```python
from datetime import UTC, date, datetime, timedelta
```
vira
```python
from datetime import UTC, date, datetime, time, timedelta
```

```python
from app.core.tz import day_window_utc
```
vira
```python
from app.core.tz import day_window_utc, tenant_zone
```

Adicione, junto aos outros imports de módulo:

```python
from app.modules.agenda.models import (
    KIND_ATENDIMENTO,
    KIND_AUDIENCIA,
    KIND_BLOQUEIO,
    KIND_LEMBRETE,
    KIND_REUNIAO,
    AgendaEvent,
)
from app.modules.agenda.schemas import EventCreate
```

Adicione, logo antes de `def _consultar_agenda(...)`:

```python
# Tipos que fazem sentido nascer de uma conversa — exclui prazo/cobranca_*/google, derivados
# de outro módulo ou de sync externo.
_TIPOS_CRIAVEIS_POR_CHAT = {
    KIND_ATENDIMENTO, KIND_REUNIAO, KIND_AUDIENCIA, KIND_BLOQUEIO, KIND_LEMBRETE,
}
_DURACAO_PADRAO = timedelta(hours=1)


def _evento_json(e: AgendaEvent) -> dict[str, Any]:
    """Serialização compartilhada entre `consultar_agenda` e as ferramentas de escrita — o `id`
    é o que permite à Claude referenciar de volta, numa chamada seguinte, um evento achado por
    consulta (`cancelar_compromisso`/`remarcar_compromisso` operam por `event_id`)."""
    return {
        "id": e.id,
        "titulo": e.title,
        "inicio": e.starts_at.isoformat(),
        "fim": e.ends_at.isoformat(),
        "dia_inteiro": e.all_day,
        "status": e.status,
        "tipo": e.kind,
    }


def _combinar_utc(dia: date, hora: time, tz_name: str) -> datetime:
    """Combina uma data-calendário e uma hora de parede NO FUSO do tenant, convertidas para
    UTC — mesma disciplina de `day_window_utc`, mas para um instante específico em vez da
    meia-noite do dia."""
    return datetime.combine(dia, hora, tzinfo=tenant_zone(tz_name)).astimezone(UTC)
```

Troque o corpo de `_consultar_agenda` (o `return` no final) de:

```python
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
```

por:

```python
    return {"eventos": [_evento_json(e) for e in eventos]}
```

Adicione, depois de `_consultar_agenda` (antes de `_consultar_cliente`):

```python
def _criar_compromisso(db: Session, user: CurrentUser, entrada: dict[str, Any]) -> dict[str, Any]:
    tipo = entrada["tipo"]
    if tipo not in _TIPOS_CRIAVEIS_POR_CHAT:
        raise ValueError(f"tipo inválido para criar por chat: {tipo}")
    if not entrada.get("confirmado"):
        return {
            "erro": (
                "peça a confirmação explícita do dono antes de chamar esta ferramenta de novo "
                "com confirmado=true"
            )
        }

    tz = tenant_timezone(db)
    dia = date.fromisoformat(entrada["data"])
    starts_at = _combinar_utc(dia, time.fromisoformat(entrada["hora_inicio"]), tz)
    if entrada.get("hora_fim"):
        ends_at = _combinar_utc(dia, time.fromisoformat(entrada["hora_fim"]), tz)
    else:
        ends_at = starts_at + _DURACAO_PADRAO
    if ends_at <= starts_at:
        raise ValueError("hora_fim deve ser depois de hora_inicio")

    client_id = None
    nome_cliente = entrada.get("cliente")
    cliente_nao_encontrado = False
    if nome_cliente:
        clientes = crm_service.list_clients(db, search=nome_cliente, limit=1)
        if clientes:
            client_id = clientes[0].id
        else:
            cliente_nao_encontrado = True

    evento, conflitos = agenda_service.create_event(
        db, tenant_id=user.tenant_id, actor=user.user_id, by_ai=True,
        data=EventCreate(
            title=entrada["titulo"], kind=tipo, starts_at=starts_at, ends_at=ends_at,
            location=entrada.get("local") or "", source="vima", client_id=client_id,
        ),
    )
    resultado: dict[str, Any] = {
        "compromisso": _evento_json(evento),
        "conflitos": [_evento_json(c) for c in conflitos],
    }
    if cliente_nao_encontrado:
        resultado["aviso"] = f"cliente '{nome_cliente}' não encontrado no cadastro; criado sem vínculo"
    return resultado
```

Por fim, adicione a `Ferramenta` na lista `FERRAMENTAS`, logo depois da entrada de `consultar_agenda`:

```python
    Ferramenta(
        nome="criar_compromisso",
        modulo="agenda",
        definicao={
            "name": "criar_compromisso",
            "description": (
                "Cria um novo compromisso na agenda. SÓ chame com confirmado=true depois que o "
                "dono confirmar explicitamente os detalhes numa mensagem anterior — antes "
                "disso, resuma o que você entendeu e peça a confirmação em texto."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Título do compromisso."},
                    "tipo": {
                        "type": "string",
                        "enum": ["atendimento", "reuniao", "audiencia", "bloqueio", "lembrete"],
                        "description": "Tipo do compromisso.",
                    },
                    "data": {"type": "string", "description": "Data no formato AAAA-MM-DD."},
                    "hora_inicio": {"type": "string", "description": "Hora de início, HH:MM."},
                    "hora_fim": {
                        "type": "string",
                        "description": "Hora de término, HH:MM. Se omitida, dura 1h.",
                    },
                    "cliente": {
                        "type": "string",
                        "description": "Nome ou parte do nome do cliente, se houver um vinculado.",
                    },
                    "local": {"type": "string", "description": "Local do compromisso, se houver."},
                    "confirmado": {
                        "type": "boolean",
                        "description": (
                            "true SOMENTE depois que o dono confirmou explicitamente numa "
                            "mensagem anterior."
                        ),
                    },
                },
                "required": ["titulo", "tipo", "data", "hora_inicio", "confirmado"],
            },
        },
        executar=_criar_compromisso,
    ),
```

- [ ] **Step 8: Atualizar o teste de contagem do catálogo**

Em `test_vima_tools.py`, troque:

```python
def test_owner_ve_as_nove_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente", "consultar_documentos_juridicos",
        "consultar_campanhas_marketing", "consultar_estoque_baixo", "consultar_item_estoque",
    }
```

por:

```python
def test_owner_ve_as_dez_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente", "consultar_documentos_juridicos",
        "consultar_campanhas_marketing", "consultar_estoque_baixo", "consultar_item_estoque",
        "criar_compromisso",
    }
```

- [ ] **Step 9: Rodar a suíte inteira do arquivo e confirmar verde**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py -v`
Expected: PASS em todos, incluindo os 7 testes novos de `criar_compromisso`.

- [ ] **Step 10: Commit**

```bash
git add apps/api/app/modules/vima/tools.py apps/api/tests/test_vima_tools.py
git commit -m "feat(vima): criar_compromisso — primeira ferramenta de escrita da Vima"
```

---

### Task 2: `cancelar_compromisso`

**Files:**
- Modify: `apps/api/app/modules/vima/tools.py`
- Test: `apps/api/tests/test_vima_tools.py`

**Interfaces:**
- Consumes: `agenda_service.cancel_event(db, *, event_id, tenant_id, actor, by_ai=False) -> AgendaEvent`; `agenda_service.get_event` (indireto, via `cancel_event`); `_evento_json` (Task 1).
- Produces: nada consumido por tasks seguintes além do padrão já estabelecido.

- [ ] **Step 1: Escrever os testes (falhando)**

Adicione em `test_vima_tools.py`, numa seção nova `# ── cancelar_compromisso ──`:

```python
def test_cancelar_compromisso_sem_confirmado_nao_escreve(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, STATUS_SCHEDULED, AgendaEvent

    evento = AgendaEvent(
        tenant_id=TENANT, title="Reunião", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
    )
    db.add(evento)
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "cancelar_compromisso", {"event_id": evento.id},
    ))
    assert "erro" in resultado
    db.refresh(evento)
    assert evento.status == STATUS_SCHEDULED


def test_cancelar_compromisso_confirmado_cancela(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, AgendaEvent

    evento = AgendaEvent(
        tenant_id=TENANT, title="Reunião", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
    )
    db.add(evento)
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "cancelar_compromisso", {"event_id": evento.id, "confirmado": True},
    ))
    assert resultado["compromisso"]["status"] == "cancelled"


def test_cancelar_compromisso_id_inexistente_devolve_erro(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "cancelar_compromisso", {"event_id": "não-existe", "confirmado": True},
    ))
    assert "erro" in resultado


def test_cancelar_compromisso_ja_cancelado_devolve_erro(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, STATUS_CANCELLED, AgendaEvent

    evento = AgendaEvent(
        tenant_id=TENANT, title="Reunião", kind=KIND_REUNIAO, status=STATUS_CANCELLED,
        starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
    )
    db.add(evento)
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "cancelar_compromisso", {"event_id": evento.id, "confirmado": True},
    ))
    assert "erro" in resultado
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py -k cancelar_compromisso -v`
Expected: FAIL — ferramenta ainda não existe.

- [ ] **Step 3: Implementar `_cancelar_compromisso` e registrar em `FERRAMENTAS`**

Em `apps/api/app/modules/vima/tools.py`, adicione depois de `_criar_compromisso`:

```python
def _cancelar_compromisso(
    db: Session, user: CurrentUser, entrada: dict[str, Any]
) -> dict[str, Any]:
    if not entrada.get("confirmado"):
        return {
            "erro": (
                "peça a confirmação explícita do dono antes de chamar esta ferramenta de novo "
                "com confirmado=true"
            )
        }
    evento = agenda_service.cancel_event(
        db, event_id=entrada["event_id"], tenant_id=user.tenant_id, actor=user.user_id,
        by_ai=True,
    )
    return {"compromisso": _evento_json(evento)}
```

E na lista `FERRAMENTAS`, logo depois da entrada de `criar_compromisso`:

```python
    Ferramenta(
        nome="cancelar_compromisso",
        modulo="agenda",
        definicao={
            "name": "cancelar_compromisso",
            "description": (
                "Cancela um compromisso existente. Use consultar_agenda primeiro para achar o "
                "event_id certo. SÓ chame com confirmado=true depois que o dono confirmar "
                "explicitamente qual compromisso cancelar numa mensagem anterior."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Id do compromisso, obtido via consultar_agenda.",
                    },
                    "confirmado": {
                        "type": "boolean",
                        "description": (
                            "true SOMENTE depois que o dono confirmou explicitamente numa "
                            "mensagem anterior."
                        ),
                    },
                },
                "required": ["event_id", "confirmado"],
            },
        },
        executar=_cancelar_compromisso,
    ),
```

- [ ] **Step 4: Atualizar a contagem do catálogo**

`FERRAMENTAS` agora tem 11 entradas — o teste de contagem da Task 1 (`test_owner_ve_as_dez_ferramentas`) quebraria sem este ajuste. Troque:

```python
def test_owner_ve_as_dez_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente", "consultar_documentos_juridicos",
        "consultar_campanhas_marketing", "consultar_estoque_baixo", "consultar_item_estoque",
        "criar_compromisso",
    }
```

por:

```python
def test_owner_ve_as_onze_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente", "consultar_documentos_juridicos",
        "consultar_campanhas_marketing", "consultar_estoque_baixo", "consultar_item_estoque",
        "criar_compromisso", "cancelar_compromisso",
    }
```

- [ ] **Step 5: Rodar os testes e confirmar verde**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py -v`
Expected: PASS em todos.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/vima/tools.py apps/api/tests/test_vima_tools.py
git commit -m "feat(vima): cancelar_compromisso"
```

---

### Task 3: `remarcar_compromisso` (+ testes de permissão por módulo)

**Files:**
- Modify: `apps/api/app/modules/vima/tools.py`
- Test: `apps/api/tests/test_vima_tools.py`

**Interfaces:**
- Consumes: `agenda_service.get_event(db, event_id) -> AgendaEvent`; `agenda_service.reschedule_event(db, *, event_id, tenant_id, actor, starts_at, ends_at, by_ai=False) -> tuple[AgendaEvent, list[AgendaEvent]]`; `_evento_json`, `_combinar_utc` (Task 1).
- Produces: catálogo final de 12 ferramentas — Task 5 (RLS) e Task 6 (docs) assumem esse estado final.

- [ ] **Step 1: Escrever os testes (falhando)**

Adicione em `test_vima_tools.py`, numa seção nova `# ── remarcar_compromisso ──`:

```python
def test_remarcar_compromisso_sem_confirmado_nao_escreve(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, AgendaEvent

    evento = AgendaEvent(
        tenant_id=TENANT, title="Reunião", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
    )
    db.add(evento)
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "remarcar_compromisso",
        {"event_id": evento.id, "nova_data": "2026-09-03", "nova_hora_inicio": "15:00"},
    ))
    assert "erro" in resultado
    db.refresh(evento)
    assert evento.starts_at == datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def test_remarcar_compromisso_confirmado_preserva_duracao_original(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, AgendaEvent

    evento = AgendaEvent(
        tenant_id=TENANT, title="Reunião", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 11, 30, tzinfo=UTC),  # 1h30 de duração
    )
    db.add(evento)
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "remarcar_compromisso",
        {"event_id": evento.id, "nova_data": "2026-09-03", "nova_hora_inicio": "15:00",
         "confirmado": True},
    ))
    assert resultado["compromisso"]["inicio"] == "2026-09-03T18:00:00+00:00"
    assert resultado["compromisso"]["fim"] == "2026-09-03T19:30:00+00:00"


def test_remarcar_compromisso_respeita_nova_hora_fim_explicita(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, AgendaEvent

    evento = AgendaEvent(
        tenant_id=TENANT, title="Reunião", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
    )
    db.add(evento)
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "remarcar_compromisso",
        {"event_id": evento.id, "nova_data": "2026-09-03", "nova_hora_inicio": "15:00",
         "nova_hora_fim": "16:00", "confirmado": True},
    ))
    assert resultado["compromisso"]["fim"] == "2026-09-03T19:00:00+00:00"


def test_remarcar_compromisso_devolve_conflito_sem_bloquear(db: Session):
    from app.modules.agenda.models import KIND_REUNIAO, AgendaEvent

    alvo = AgendaEvent(
        tenant_id=TENANT, title="Alvo", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 2, 11, 0, tzinfo=UTC),
    )
    # nova_hora_inicio "15:00" é hora LOCAL (America/Sao_Paulo, UTC-3) → vira 18:00 UTC. O
    # concorrente precisa sobrepor a JANELA CONVERTIDA, não o número "15:00" lido cru.
    outro = AgendaEvent(
        tenant_id=TENANT, title="Outro compromisso", kind=KIND_REUNIAO,
        starts_at=datetime(2026, 9, 3, 18, 30, tzinfo=UTC),
        ends_at=datetime(2026, 9, 3, 19, 30, tzinfo=UTC),
    )
    db.add_all([alvo, outro])
    db.commit()
    resultado = json.loads(tools.executar(
        db, _usuario(), "remarcar_compromisso",
        {"event_id": alvo.id, "nova_data": "2026-09-03", "nova_hora_inicio": "15:00",
         "confirmado": True},
    ))
    assert len(resultado["conflitos"]) == 1
    assert resultado["conflitos"][0]["titulo"] == "Outro compromisso"


def test_remarcar_compromisso_id_inexistente_devolve_erro(db: Session):
    resultado = json.loads(tools.executar(
        db, _usuario(), "remarcar_compromisso",
        {"event_id": "não-existe", "nova_data": "2026-09-03", "nova_hora_inicio": "15:00",
         "confirmado": True},
    ))
    assert "erro" in resultado
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py -k remarcar_compromisso -v`
Expected: FAIL — ferramenta ainda não existe.

- [ ] **Step 3: Implementar `_remarcar_compromisso` e registrar em `FERRAMENTAS`**

Adicione depois de `_cancelar_compromisso`:

```python
def _remarcar_compromisso(
    db: Session, user: CurrentUser, entrada: dict[str, Any]
) -> dict[str, Any]:
    if not entrada.get("confirmado"):
        return {
            "erro": (
                "peça a confirmação explícita do dono antes de chamar esta ferramenta de novo "
                "com confirmado=true"
            )
        }

    evento_atual = agenda_service.get_event(db, entrada["event_id"])
    duracao_original = evento_atual.ends_at - evento_atual.starts_at

    tz = tenant_timezone(db)
    dia = date.fromisoformat(entrada["nova_data"])
    novo_inicio = _combinar_utc(dia, time.fromisoformat(entrada["nova_hora_inicio"]), tz)
    if entrada.get("nova_hora_fim"):
        novo_fim = _combinar_utc(dia, time.fromisoformat(entrada["nova_hora_fim"]), tz)
    else:
        novo_fim = novo_inicio + duracao_original
    if novo_fim <= novo_inicio:
        raise ValueError("nova_hora_fim deve ser depois de nova_hora_inicio")

    evento, conflitos = agenda_service.reschedule_event(
        db, event_id=entrada["event_id"], tenant_id=user.tenant_id, actor=user.user_id,
        starts_at=novo_inicio, ends_at=novo_fim, by_ai=True,
    )
    return {
        "compromisso": _evento_json(evento),
        "conflitos": [_evento_json(c) for c in conflitos],
    }
```

E na lista `FERRAMENTAS`, logo depois da entrada de `cancelar_compromisso`:

```python
    Ferramenta(
        nome="remarcar_compromisso",
        modulo="agenda",
        definicao={
            "name": "remarcar_compromisso",
            "description": (
                "Muda a data/hora de um compromisso existente. Use consultar_agenda primeiro "
                "para achar o event_id certo. SÓ chame com confirmado=true depois que o dono "
                "confirmar explicitamente o novo horário numa mensagem anterior."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Id do compromisso, obtido via consultar_agenda.",
                    },
                    "nova_data": {"type": "string", "description": "Nova data, AAAA-MM-DD."},
                    "nova_hora_inicio": {
                        "type": "string", "description": "Nova hora de início, HH:MM.",
                    },
                    "nova_hora_fim": {
                        "type": "string",
                        "description": (
                            "Nova hora de término, HH:MM. Se omitida, preserva a duração "
                            "original."
                        ),
                    },
                    "confirmado": {
                        "type": "boolean",
                        "description": (
                            "true SOMENTE depois que o dono confirmou explicitamente numa "
                            "mensagem anterior."
                        ),
                    },
                },
                "required": ["event_id", "nova_data", "nova_hora_inicio", "confirmado"],
            },
        },
        executar=_remarcar_compromisso,
    ),
```

- [ ] **Step 4: Atualizar a contagem do catálogo e adicionar o teste de permissão por módulo `agenda`**

Troque (de novo) `test_owner_ve_as_onze_ferramentas` por:

```python
def test_owner_ve_as_doze_ferramentas():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("owner"))}
    assert nomes == {
        "consultar_recebiveis", "consultar_pagaveis", "consultar_projecao_caixa",
        "consultar_agenda", "consultar_cliente", "consultar_documentos_juridicos",
        "consultar_campanhas_marketing", "consultar_estoque_baixo", "consultar_item_estoque",
        "criar_compromisso", "cancelar_compromisso", "remarcar_compromisso",
    }
```

E adicione, na seção "Catálogo e permissão":

```python
def test_sub_usuario_so_de_agenda_ve_a_leitura_e_as_tres_ferramentas_de_escrita():
    nomes = {f.nome for f in tools.ferramentas_disponiveis(_usuario("sub_user", ["agenda"]))}
    assert nomes == {
        "consultar_agenda", "criar_compromisso", "cancelar_compromisso", "remarcar_compromisso",
    }
```

- [ ] **Step 5: Rodar a suíte inteira do arquivo e confirmar verde**

Run: `cd apps/api && python -m pytest tests/test_vima_tools.py -v`
Expected: PASS em todos — catálogo com 12 ferramentas, 17 testes novos desde o início do plano.

- [ ] **Step 6: Rodar a suíte completa da API para checar que nada mais quebrou**

Run: `cd apps/api && python -m pytest -q`
Expected: `... passed` (suíte SQLite; `rls_e2e` fica de fora, é a Task 5).

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/vima/tools.py apps/api/tests/test_vima_tools.py
git commit -m "feat(vima): remarcar_compromisso — fecha o trio de escrita da agenda"
```

---

### Task 4: Disciplina de confirmação no prompt-sistema

**Files:**
- Modify: `apps/api/app/modules/vima/pergunta.py`
- Test: `apps/api/tests/test_vima_pergunta_service.py`

**Interfaces:**
- Consumes: nada novo — só o texto de `_SYSTEM` já existente.
- Produces: nada consumido por outras tasks.

- [ ] **Step 1: Escrever o teste (falhando)**

Adicione em `test_vima_pergunta_service.py`:

```python
def test_system_prompt_exige_confirmacao_antes_de_escrever():
    assert "confirmado=true" in pergunta._SYSTEM
    assert "criar_compromisso" in pergunta._SYSTEM
    assert "cancelar_compromisso" in pergunta._SYSTEM
    assert "remarcar_compromisso" in pergunta._SYSTEM
    assert "consultar_agenda" in pergunta._SYSTEM
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd apps/api && python -m pytest tests/test_vima_pergunta_service.py -k system_prompt -v`
Expected: FAIL — `_SYSTEM` ainda não menciona nenhuma das ferramentas de escrita.

- [ ] **Step 3: Estender `_SYSTEM`**

Em `apps/api/app/modules/vima/pergunta.py`, troque:

```python
_SYSTEM = (
    "Você é a Vima, a assistente do dono deste negócio dentro do e1p. Responda perguntas sobre "
    "o negócio SOMENTE com base no que as ferramentas devolverem — nunca invente um número, uma "
    "data ou um nome. Se não tiver uma ferramenta que responda a pergunta, diga isso claramente "
    "em vez de adivinhar. Responda em português do Brasil, direto e sem rodeios."
)
```

por:

```python
_SYSTEM = (
    "Você é a Vima, a assistente do dono deste negócio dentro do e1p. Responda perguntas sobre "
    "o negócio SOMENTE com base no que as ferramentas devolverem — nunca invente um número, uma "
    "data ou um nome. Se não tiver uma ferramenta que responda a pergunta, diga isso claramente "
    "em vez de adivinhar. Responda em português do Brasil, direto e sem rodeios.\n\n"
    "Antes de criar, cancelar ou remarcar um compromisso na agenda, resuma em texto o que você "
    "entendeu (o quê, quando, com quem) e peça confirmação explícita do dono. SÓ chame "
    "criar_compromisso, cancelar_compromisso ou remarcar_compromisso com confirmado=true depois "
    "que o dono confirmar claramente numa mensagem seguinte — nunca no mesmo turno em que ele "
    "pediu. Para cancelar ou remarcar, use consultar_agenda primeiro para achar o compromisso "
    "certo; se houver mais de um compatível, pergunte qual antes de agir."
)
```

- [ ] **Step 4: Rodar os testes e confirmar verde**

Run: `cd apps/api && python -m pytest tests/test_vima_pergunta_service.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/vima/pergunta.py apps/api/tests/test_vima_pergunta_service.py
git commit -m "feat(vima): prompt-sistema exige confirmação explícita antes de escrever"
```

---

### Task 5: Prova de RLS cross-tenant para `cancelar_compromisso`

**Files:**
- Modify: `apps/api/tests/test_vima_tools_rls.py`

**Interfaces:**
- Consumes: `tools.executar` (já com a assinatura da Task 1), `_tenant_session`/`_bootstrap_rls_role`/`_run_migrations_as_app` (já existentes no arquivo).
- Produces: nada consumido por outras tasks — é o fim da cadeia de testes.

Mesmo raciocínio do `consultar_cliente` já provado neste arquivo: `cancelar_compromisso` recebe um `event_id` livre — é a ferramenta de escrita mais direta em "alcançar a linha de outro tenant pelo id", então é a prova representativa (mesmo padrão do arquivo: uma ferramenta por família, não as três).

- [ ] **Step 1: Adicionar os helpers e o teste**

Em `apps/api/tests/test_vima_tools_rls.py`, adicione depois de `_consultar_cliente`:

```python
def _criar_evento(app_url: str, *, tenant_id: str, titulo: str) -> str:
    from datetime import UTC, datetime

    from app.modules.agenda.models import KIND_REUNIAO, AgendaEvent

    with _tenant_session(app_url, tenant_id) as session:
        evento = AgendaEvent(
            tenant_id=tenant_id, title=titulo, kind=KIND_REUNIAO,
            starts_at=datetime(2026, 9, 10, 14, 0, tzinfo=UTC),
            ends_at=datetime(2026, 9, 10, 15, 0, tzinfo=UTC),
        )
        session.add(evento)
        session.commit()
        return evento.id


def _cancelar_compromisso(app_url: str, *, tenant_id: str, event_id: str) -> dict:
    import json

    from app.core.tenancy import CurrentUser
    from app.modules.vima import tools

    usuario = CurrentUser(user_id="u1", tenant_id=tenant_id, role="owner", allowed_modules=[])
    with _tenant_session(app_url, tenant_id) as session:
        resultado = tools.executar(
            session, usuario, "cancelar_compromisso",
            {"event_id": event_id, "confirmado": True},
        )
        return json.loads(resultado)


def test_cancelar_compromisso_nao_alcanca_evento_de_outro_tenant() -> None:
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
        evento_id = _criar_evento(app_url, tenant_id=tenant_a, titulo="Reunião do tenant A")

        # Tenant B tenta cancelar o evento de A pelo MESMO id — se a RLS falhar, ele consegue.
        resultado_b = _cancelar_compromisso(app_url, tenant_id=tenant_b, event_id=evento_id)
        assert "erro" in resultado_b, "RLS falhou: tenant B conseguiu alcançar o evento de A"

        # Controle positivo: o próprio dono (tenant A) cancela sem problema — não é RLS fechada
        # demais escondendo os dois lados.
        resultado_a = _cancelar_compromisso(app_url, tenant_id=tenant_a, event_id=evento_id)
        assert resultado_a["compromisso"]["status"] == "cancelled"
```

- [ ] **Step 2: Rodar (precisa de Docker rodando — testcontainers sobe um Postgres real)**

Run: `cd apps/api && python -m pytest tests/test_vima_tools_rls.py -m rls_e2e -v`
Expected: PASS nos dois testes do arquivo (`test_consultar_cliente_isola_por_tenant` + o novo).

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_vima_tools_rls.py
git commit -m "test(vima): prova de RLS cross-tenant para cancelar_compromisso"
```

---

### Task 6: Documentar a fatia no CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nada — só resume o que as Tasks 1-5 já fizeram.
- Produces: nada.

Mesmo padrão das duas seções anteriores da Vima (`## Vima: pergunte e receba resposta`, `## Vima: canal WhatsApp`) — procure por `## Vima: canal WhatsApp (self-chat, Evolution) (2026-08-28)` no `CLAUDE.md` e adicione a nova seção IMEDIATAMENTE ANTES dela (mantém a ordem cronológica das seções da Vima).

- [ ] **Step 1: Adicionar a seção**

```markdown
## Vima: ações de agenda (2026-09-01)

> Spec: `docs/superpowers/specs/2026-09-01-vima-acoes-de-agenda-design.md` ·
> Plano: `docs/superpowers/plans/2026-09-01-vima-acoes-de-agenda.md`

Terceira fatia do caminho até o Jarbes, e a primeira em que a Vima ESCREVE. Fecha a dívida
"Ações da Vima — hoje ela só LÊ" registrada nas duas fatias anteriores, e a Regra de Ouro nº 3
(propagar `is_ai` nas escritas de agenda) — `agenda/service.py` já aceitava `by_ai` desde
sempre, só nunca tinha sido chamado com `True`.

- [x] **Três ferramentas novas em `vima/tools.py`** — `criar_compromisso`, `cancelar_compromisso`,
  `remarcar_compromisso`, wrappers finos sobre `agenda_service.create_event/cancel_event/
  reschedule_event`. Nenhuma regra de negócio nova: conflito de horário, espelho no Google, RLS
  — tudo já existia no serviço.
- [x] **Confirmação obrigatória por campo, não por mecanismo persistido.** Cada ferramenta de
  escrita exige `confirmado: bool`; ausente/`false` devolve erro sem tocar o banco. O
  prompt-sistema (`vima/pergunta.py`) instrui a Vima a resumir e pedir confirmação em texto
  antes de chamar com `confirmado=true` — mesma disciplina (prompt + teste, não trava de
  código) que já sustenta "a IA só narra, nunca origina número" no resto da Vima. Um token de
  confirmação persistido entre chamadas HTTP foi considerado e rejeitado: contrariaria a
  decisão já tomada de "sem persistência de conversa entre sessões".
- [x] **`Ferramenta.executar` ganhou `CurrentUser`** — as 9 ferramentas de leitura não
  precisavam de identidade (a sessão já vem RLS-escopada); escrever precisa de `tenant_id`
  (carimbar a linha nova) e `actor` (auditoria). As 9 antigas ignoram o parâmetro
  (`_user`), refactor sem mudança de comportamento, provado pela suíte existente continuando
  verde.
- [x] **`consultar_agenda` passou a devolver `id`** — sem isso a Vima não tinha como referenciar
  de volta um evento achado por consulta numa chamada de `cancelar_compromisso`/
  `remarcar_compromisso`. Extraído `_evento_json`, compartilhado entre as quatro ferramentas de
  agenda.
- [x] **Erro de domínio chega com a mensagem real** — `tools.executar` ganhou um `except`
  específico para `AgendaError`/`ValueError` antes do genérico, para a Vima saber narrar "evento
  não encontrado" em vez de um "não consegui" apagado.
- [x] **Prova de RLS** (`test_vima_tools_rls.py`) — dois tenants, `cancelar_compromisso` por id:
  tenant B não alcança o evento de A, sob Postgres real.

**Fora de escopo, declarado:**
- Editar campos livres (título/local/descrição) via Vima — só criar, cancelar, remarcar.
- Ferramentas de escrita para outros módulos (Financeiro, CRM, Jurídico, Marketing, Estoque).
- Mecanismo de confirmação mais forte que prompt + campo obrigatório, caso o risco de
  auto-confirmação (a Claude chamar a ferramenta de escrita na mesma rodada em que propôs, sem
  o dono ver) se prove real em uso — hoje é decisão de custo/benefício, não lacuna desconhecida.

```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md registra a fatia de ações de agenda da Vima"
```
