# Jornada única do contato — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um card por pessoa e um histórico por pessoa — o lead que volta complementa o contato que já existe (com data e texto novos) em vez de abrir um card paralelo, e a história inteira dele aparece ao lado da conversa.

**Architecture:** Deduplicação na entrada por telefone normalizado (`core/phone.py` → `clients.phone_key`), unificando as três portas que hoje criam contato (página pública, API de integração, WhatsApp). Uma tabela nova `client_events` guarda só os fatos **narrativos**; os fatos financeiros continuam sendo lidos de `quotes`/`charges` e são mesclados na leitura. Um componente React `<ClientTimeline>` serve a ficha 360° e o painel novo da tela de Conversas.

**Tech Stack:** FastAPI (Python 3.13), SQLAlchemy 2 + Alembic, PostgreSQL 16 (RLS `FORCE`), pytest (+ testcontainers para os testes `rls_e2e`), React 18 + Vite + TypeScript + Tailwind, vitest.

**Spec:** `docs/superpowers/specs/2026-08-04-crm-jornada-unica-do-contato-design.md`

## Global Constraints

- **Idioma:** produto, comentários de domínio e mensagens de erro em **PT-BR**; identificadores em inglês (CLAUDE.md §8).
- **Isolamento de tenant:** toda tabela de negócio nova carrega `tenant_id` (via `TenantMixin`) e recebe `ENABLE` + `FORCE ROW LEVEL SECURITY` + política `tenant_isolation` na migration. **Nunca** adicionar filtro manual de `tenant_id` em query — a RLS é a única garantia (Regra de Ouro nº 1).
- **Migrations são autocontidas:** nenhuma migration do repo importa de `app.` (verificado: 0 ocorrências). Código que a migration precisa é inlinado nela.
- **Backfill sob RLS:** qualquer `UPDATE`/`INSERT`/`SELECT` de backfill sobre tabela com `FORCE ROW LEVEL SECURITY` roda como `e1p_app` sem GUC de tenant e afeta **zero linhas, em silêncio**. Desabilitar a RLS só na janela do backfill e restaurar (`ENABLE` + `FORCE`) logo depois — molde da `0066_whatsapp_chats.py`.
- **`audit.record` precisa de `db.flush()` antes** quando a entidade acabou de ser criada: `client.id` ainda é `None` logo após `db.add()` (dívida MNT-001 do CLAUDE.md). Código novo faz `flush` antes de registrar trilha.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`), em PT-BR, na branch `docs/crm-jornada-unica-do-contato` (ou uma branch de feature criada a partir dela). `main` é protegida — não fazer push direto.
- **Rodar os testes de backend:** `cd apps/api && pytest <caminho> -v`. A suíte padrão usa SQLite e **não** exercita RLS; os testes marcados `rls_e2e` (`pytest -m rls_e2e`) sobem Postgres real via testcontainers e não rodam no `pytest -q`.
- **Rodar os testes de frontend:** `pnpm --filter @e1p/web test -- <arquivo>`.
- **Vocabulário fechado de `kind`** em `client_events`, exatamente estes seis: `lead_created`, `lead_return`, `stage_move`, `reopened`, `note`, `funnel`.

---

## File Structure

**Backend — criar:**

| Arquivo | Responsabilidade |
|---|---|
| `apps/api/app/core/phone.py` | `normalize_br` — normalização de telefone BR. Puro, sem I/O, irmão de `validators.py`. |
| `apps/api/app/modules/crm/timeline.py` | Read model: mescla `client_events` (persistido) com `quotes`/`charges` (derivado). Fica fora de `service.py` porque é leitura cross-módulo, com responsabilidade distinta das regras de escrita do CRM. |
| `apps/api/migrations/versions/0067_client_events_and_phone_key.py` | Tabela `client_events` + coluna `clients.phone_key` + backfill. |
| `apps/api/tests/test_phone.py` | Tabela de casos de `normalize_br`. |
| `apps/api/tests/test_lead_absorb.py` | `absorb_lead`: dedup, complemento, reabertura, desempate. |
| `apps/api/tests/test_client_timeline.py` | Endpoints de timeline e nota. |
| `apps/api/tests/test_crm_events_rls.py` | `rls_e2e`: backfill não é no-op + isolamento de `client_events`. |

**Backend — modificar:**

| Arquivo | Mudança |
|---|---|
| `apps/api/app/modules/crm/models.py` | `ClientEvent`, `Client.phone_key`, constantes de `kind`. |
| `apps/api/app/modules/crm/service.py` | `record_event`, `absorb_lead`, `last_interaction_map`; ganchos em `create_client`/`move_client`; `EVENT_CLIENT_RETURNED`. |
| `apps/api/app/modules/crm/schemas.py` | `ClientTimelineEntry`, `ClientTimelineOut`, `NoteCreate`, `BoardClient`. |
| `apps/api/app/modules/crm/router.py` | `GET /crm/clients/{id}/timeline`, `POST /crm/clients/{id}/notes`, board com `last_interaction_at`. |
| `apps/api/app/modules/pages/service.py` | `public_submit` chama `absorb_lead`. |
| `apps/api/app/modules/integrations/service.py` | `capture_lead` chama `absorb_lead`. |
| `apps/api/app/modules/whatsapp_inbox/service.py` | `_get_or_create_client` casa por `phone_key`. |
| `apps/api/app/modules/funnels/automation.py` | Assina `crm.client.returned` com guarda de jornada ativa. |

**Frontend — criar:**

| Arquivo | Responsabilidade |
|---|---|
| `apps/web/src/features/crm/ClientTimeline.tsx` | Componente compartilhado da linha do tempo (busca, renderiza, grava nota). |
| `apps/web/src/features/crm/ClientTimeline.test.tsx` | Ordem da mescla, `truncated`, gravar nota. |

**Frontend — modificar:**

| Arquivo | Mudança |
|---|---|
| `packages/shared-types/src/index.ts` | `ClientTimelineEntry`, `ClientTimelineOut`, `BoardClient`. |
| `apps/web/src/features/crm/ClientDetailPage.tsx` | `<ClientTimeline>` como primeira `<Section>`. |
| `apps/web/src/features/crm/CrmPage.tsx` | Card mostra "última interação". |
| `apps/web/src/features/conversas/ConversasPage.tsx` | Painel direito (coluna em `lg+`, gaveta abaixo). |
| `apps/web/src/features/conversas/ConversasPage.test.tsx` | Casos do painel. |

**Correção de vocabulário em relação à spec:** a ficha 360° (`ClientDetailPage.tsx`) **não usa abas** — usa blocos `<Section>` empilhados (linhas 108–200). Onde a spec diz "primeira aba", leia "primeira `<Section>`, antes de Cobranças". A intenção (histórico em primeiro lugar) é a mesma.

---

### Task 1: `core/phone.py` — normalização de telefone

**Files:**
- Create: `apps/api/app/core/phone.py`
- Test: `apps/api/tests/test_phone.py`

**Interfaces:**
- Consumes: nada (módulo puro, primeira tarefa).
- Produces: `normalize_br(raw: str | None) -> str | None` — devolve `"55" + DDD + local` ou `None` quando a entrada não encaixa em formato brasileiro.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_phone.py`:

```python
"""Normalização de telefone brasileiro (chave de deduplicação de contato)."""
import pytest

from app.core.phone import normalize_br


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        # celular moderno (9 dígitos), em todas as formas que um formulário produz
        ("(11) 99999-8888", "5511999998888"),
        ("11999998888", "5511999998888"),
        ("5511999998888", "5511999998888"),
        ("+55 (11) 99999-8888", "5511999998888"),
        # celular no formato pré-2016 (8 dígitos): ganha o 9 e casa com o moderno
        ("(11) 9999-8888", "5511999998888"),
        # fixo (8 dígitos começando em 2-5): NÃO ganha o 9
        ("(11) 3333-4444", "551133334444"),
        ("1133334444", "551133334444"),
        # outros DDDs
        ("(61) 98888-7777", "5561988887777"),
        # entradas que não normalizam
        ("", None),
        (None, None),
        ("99998888", None),          # sem DDD
        ("011999998888", None),      # DDD com zero à esquerda
        ("123", None),
    ],
)
def test_normalize_br(entrada, esperado):
    assert normalize_br(entrada) == esperado


def test_fixo_e_celular_com_mesmos_8_digitos_nao_colidem():
    """O caso que justifica a regra do 9º dígito.

    A alternativa óbvia — "compara os últimos 8 dígitos" — casaria estes dois números,
    e duas pessoas diferentes virariam um card só.
    """
    fixo = normalize_br("(11) 3333-4444")
    celular = normalize_br("(11) 93333-4444")
    assert fixo is not None
    assert celular is not None
    assert fixo != celular


def test_resultado_cabe_na_coluna():
    """`clients.phone_key` é String(16). O maior resultado possível tem 13 caracteres."""
    assert len(normalize_br("+55 (11) 99999-8888")) <= 16
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_phone.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.phone'`

- [ ] **Step 3: Write minimal implementation**

Create `apps/api/app/core/phone.py`:

```python
"""Normalização de telefone brasileiro para COMPARAÇÃO (dedup de contato).

Módulo utilitário do núcleo, mesma convenção de `validators.py`: sem I/O, pura
normalização, chamável de qualquer serviço ou schema.

O resultado NÃO substitui o telefone que a pessoa digitou — ele vive ao lado, em
`clients.phone_key`. `clients.phone` continua guardando `"(11) 99999-8888"` (evidência do
que chegou) e `phone_key` guarda `"5511999998888"` (a forma comparável). Mesmo par
`raw_description`/`user_description` de `bank_transactions`.

LIMITE CONHECIDO: o produto é BR-only, então um número estrangeiro de 10-11 dígitos é
normalizado como se fosse brasileiro. Não há campo de país para desambiguar, e inventar uma
heurística seria pior que o erro que ela evitaria.
"""
from __future__ import annotations

import re

_NON_DIGITS = re.compile(r"\D")

# Primeiro dígito do número LOCAL (depois do DDD): 6-9 é celular, 2-5 é fixo. É a faixa da
# Anatel, e é o que permite inserir o 9º dígito só onde ele de fato existe — sem isso, um
# fixo "11 3333-4444" e um celular "11 93333-4444" colapsariam na mesma chave.
_MOBILE_FIRST_DIGITS = "6789"


def normalize_br(raw: str | None) -> str | None:
    """`"(11) 9999-8888"` -> `"5511999998888"`. `None` quando não encaixa em formato BR."""
    digits = _NON_DIGITS.sub("", raw or "")
    if not digits:
        return None

    # Código de país presente? Só tira o "55" se o que sobra for um número BR plausível —
    # senão um fixo de DDD 55 (Pelotas/RS) perderia o próprio DDD.
    if digits.startswith("55") and len(digits) - 2 in (10, 11):
        digits = digits[2:]

    if len(digits) not in (10, 11):
        return None

    ddd, local = digits[:2], digits[2:]
    if ddd[0] == "0":
        # "011 99999-8888": o zero de operadora não faz parte do DDD, e adivinhar qual
        # dígito sobra seria chute. Não deduplica por telefone.
        return None

    if len(local) == 8 and local[0] in _MOBILE_FIRST_DIGITS:
        local = "9" + local  # celular pré-2016 — ganha o 9º dígito

    return "55" + ddd + local
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_phone.py -v`
Expected: PASS — 15 casos parametrizados + 2 testes nomeados.

- [ ] **Step 5: Lint**

Run: `cd apps/api && ruff check app/core/phone.py tests/test_phone.py`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/core/phone.py apps/api/tests/test_phone.py
git commit -m "feat: normalizacao de telefone BR para dedup de contato"
```

---

### Task 2: Modelo `ClientEvent` e coluna `clients.phone_key`

**Files:**
- Modify: `apps/api/app/modules/crm/models.py`
- Test: `apps/api/tests/test_crm_models.py` (create)

**Interfaces:**
- Consumes: `normalize_br` (Task 1) — ainda não é chamado aqui, mas define o formato de `phone_key`.
- Produces:
  - `ClientEvent` (tabela `client_events`) com campos `id, tenant_id, client_id, kind, title, body, actor, is_ai, created_at, updated_at`.
  - `Client.phone_key: str | None`.
  - Constantes: `KIND_LEAD_CREATED = "lead_created"`, `KIND_LEAD_RETURN = "lead_return"`, `KIND_STAGE_MOVE = "stage_move"`, `KIND_REOPENED = "reopened"`, `KIND_NOTE = "note"`, `KIND_FUNNEL = "funnel"`, e a tupla `EVENT_KINDS` com os seis.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_crm_models.py`:

```python
"""Estrutura das tabelas do CRM que a timeline depende."""
from app.modules.crm.models import EVENT_KINDS, Client, ClientEvent


def test_client_events_tem_as_colunas_do_contrato():
    cols = {c.name for c in ClientEvent.__table__.columns}
    assert cols == {
        "id", "tenant_id", "client_id", "kind", "title", "body", "actor", "is_ai",
        "created_at", "updated_at",
    }


def test_client_event_nao_tem_gancho_generico():
    """Sem `meta` JSON e sem `ref_type`/`ref_id`: seriam o depósito de qualquer coisa.

    Decisão da spec §"Modelo de dados". Se um caso concreto exigir, entra com nome próprio.
    """
    cols = {c.name for c in ClientEvent.__table__.columns}
    assert "meta" not in cols
    assert "ref_type" not in cols
    assert "ref_id" not in cols


def test_client_id_e_obrigatorio_e_cascateia():
    col = ClientEvent.__table__.c.client_id
    assert col.nullable is False
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "clients"
    assert fk.ondelete == "CASCADE"


def test_vocabulario_de_kind_fechado_em_seis():
    assert EVENT_KINDS == (
        "lead_created", "lead_return", "stage_move", "reopened", "note", "funnel",
    )


def test_client_ganhou_phone_key_indexada_e_sem_unique():
    col = Client.__table__.c.phone_key
    assert col.nullable is True
    assert col.index is True
    assert col.unique is not True  # dedup é busca, não invariante do banco
    assert col.type.length == 16
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_crm_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'EVENT_KINDS'`

- [ ] **Step 3: Write minimal implementation**

In `apps/api/app/modules/crm/models.py`, adicionar `Boolean` ao import de `sqlalchemy` (já está lá) e acrescentar, depois da definição de `Client`:

```python
# ── Linha do tempo do contato ──────────────────────────

# Vocabulário FECHADO. Cada valor vira um ícone e uma cor na tela; um valor novo sem
# tratamento no front apareceria sem identidade visual.
KIND_LEAD_CREATED = "lead_created"   # o contato nasceu
KIND_LEAD_RETURN = "lead_return"     # contato conhecido voltou pelo formulário/API
KIND_STAGE_MOVE = "stage_move"       # card mudou de coluna (inclusive drag-and-drop)
KIND_REOPENED = "reopened"           # retorno reabriu card que estava em coluna terminal
KIND_NOTE = "note"                   # decisão escrita pelo dono
KIND_FUNNEL = "funnel"               # contato inscrito numa jornada do funil

EVENT_KINDS = (
    KIND_LEAD_CREATED, KIND_LEAD_RETURN, KIND_STAGE_MOVE,
    KIND_REOPENED, KIND_NOTE, KIND_FUNNEL,
)


class ClientEvent(Base, TenantMixin, TimestampMixin):
    """Um fato NARRATIVO na história de um contato.

    O que mora aqui: como chegou, quando voltou e com que texto, para onde foi no Kanban,
    o que foi decidido.

    O que NÃO mora aqui: dinheiro. Orçamento, cobrança e pagamento continuam vivendo só em
    `quotes`/`charges` e são lidos de lá (ver `crm/timeline.py`). Copiar `amount_cents` para
    cá criaria uma segunda versão da verdade sobre dinheiro — a forma exata do bug que a
    Onda 0 do Epic 8 gastou uma onda inteira desfazendo.

    `title` e `body` são TEXTO CONGELADO, não referências: um movimento gravado hoje diz
    "Movido de Em contato → Proposta" como texto, e continua dizendo isso mesmo depois de a
    coluna ser renomeada ou arquivada. É o princípio do `raw_description` de
    `bank_transactions` — o registro é evidência, e evidência não se reescreve sozinha.
    """

    __tablename__ = "client_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # CASCADE: a história de um contato não sobrevive ao contato. Diferente do RESTRICT de
    # `stage_id`, que existe para impedir card órfão sumindo do board.
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    # Regra de Ouro nº 3: toda ação da IA deixa rastro identificável.
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

E dentro da classe `Client`, logo abaixo de `phone`:

```python
    # Forma COMPARÁVEL do telefone (ver `core/phone.normalize_br`). `phone` guarda o que a
    # pessoa digitou; esta guarda "5511999998888". Indexada porque é o caminho de busca do
    # `absorb_lead`. SEM unique: marido e mulher compartilham telefone, e uma constraint
    # quebraria a criação manual legítima de dois contatos com o mesmo número.
    phone_key: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_crm_models.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Verify the existing CRM suite still passes**

Run: `cd apps/api && pytest tests/test_crm.py -v`
Expected: PASS — o modelo novo não muda comportamento nenhum ainda.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/crm/models.py apps/api/tests/test_crm_models.py
git commit -m "feat: modelo client_events e coluna clients.phone_key"
```

---

### Task 3: Migration 0067 — tabela, coluna e backfill sob RLS

**Files:**
- Create: `apps/api/migrations/versions/0067_client_events_and_phone_key.py`
- Test: `apps/api/tests/test_migration_0067_phone_key.py` (create)

**Interfaces:**
- Consumes: `ClientEvent` e `Client.phone_key` (Task 2); `normalize_br` (Task 1) como referência de comportamento.
- Produces: revisão alembic `"0067"` com `down_revision = "0066"`; função inline `_normalize_br_frozen(raw)` dentro do módulo da migration (cópia congelada da regra).

**Por que uma cópia congelada em vez de importar `app.core.phone`:** nenhuma das 66 migrations do repo importa de `app.` (convenção verificada). Migration é um registro histórico — se ela importasse `normalize_br` e a regra mudasse daqui a um ano, rodar as migrations do zero produziria um backfill diferente do que a produção recebeu. O preço é a duplicação, e o Step 1 abaixo compra um teste que impede as duas de divergirem silenciosamente **hoje**.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_migration_0067_phone_key.py`:

```python
"""A cópia congelada da normalização dentro da migration 0067 concorda com `core/phone`.

A migration não pode importar de `app.` (convenção do repo: 0 de 66 fazem isso), então a
regra existe em dois lugares. Este teste é o que impede as duas de divergirem sem ninguém
notar — uma divergência aqui significaria backfill gerando chaves que o `absorb_lead` nunca
encontraria, e a dedup falharia em silêncio para todo contato que já existe.
"""
import importlib.util
from pathlib import Path

import pytest

from app.core.phone import normalize_br

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "0067_client_events_and_phone_key.py"
)

CASOS = [
    "(11) 99999-8888", "11999998888", "5511999998888", "+55 (11) 99999-8888",
    "(11) 9999-8888", "(11) 3333-4444", "1133334444", "(61) 98888-7777",
    "", "99998888", "011999998888", "123",
]


@pytest.fixture(scope="module")
def migration_module():
    spec = importlib.util.spec_from_file_location("migracao_0067", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("entrada", CASOS)
def test_copia_congelada_concorda_com_core_phone(migration_module, entrada):
    assert migration_module._normalize_br_frozen(entrada) == normalize_br(entrada)


def test_revisao_encadeia_na_0066(migration_module):
    assert migration_module.revision == "0067"
    assert migration_module.down_revision == "0066"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_migration_0067_phone_key.py -v`
Expected: FAIL — `FileNotFoundError` / `spec_from_file_location` devolve `None` porque o arquivo da migration não existe.

- [ ] **Step 3: Write the migration**

Create `apps/api/migrations/versions/0067_client_events_and_phone_key.py`:

```python
"""Linha do tempo do contato + chave de deduplicação de telefone

Revision ID: 0067
Revises: 0066
Create Date: 2026-08-04

O mesmo contato virava vários cards no Kanban: `pages/service.py::public_submit` e
`integrations/service.py::capture_lead` chamavam `create_client` incondicionalmente, sem
procurar se aquela pessoa já existia. Esta migration cria as duas estruturas que faltavam:

- **`client_events`** — a linha do tempo NARRATIVA do contato (como chegou, quando voltou,
  para onde foi no Kanban, o que foi decidido). Dinheiro NÃO entra aqui: orçamento, cobrança
  e pagamento continuam sendo lidos de `quotes`/`charges`.
- **`clients.phone_key`** — a forma comparável do telefone (`"5511999998888"`), ao lado do
  `phone` cru, que continua guardando o que a pessoa digitou.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL de `clients.phone_key`. Ela
roda como o papel dono NÃO-superusuário `e1p_app`, **sem** a GUC `app.current_tenant_id`. Sob
`FORCE ROW LEVEL SECURITY`, o `UPDATE` seria filtrado a **ZERO LINHAS, em silêncio** — e o
sintoma em produção não seria um erro, seria "continua duplicando contato". Por isso a RLS de
`clients` é desabilitada SÓ na janela do backfill e restaurada (ENABLE + FORCE) logo depois —
mesmo padrão da `0046_ledger_classification` e da `0066_whatsapp_chats`. DDL é transacional no
Postgres e a migration roda offline, então não há janela de exposição.

**A normalização está DUPLICADA de propósito.** `_normalize_br_frozen` abaixo é uma cópia
congelada de `app.core.phone.normalize_br` nesta revisão. Nenhuma migration do repo importa de
`app.` — migration é registro histórico, e importar código vivo faria "rodar as migrations do
zero" produzir um resultado diferente do que a produção recebeu se a regra mudasse depois. O
teste `tests/test_migration_0067_phone_key.py` prova que as duas concordam hoje.

**O backfill é aditivo e não-destrutivo:** preenche uma coluna nova, não altera `phone` e não
mescla card nenhum. Os cards duplicados que já existem CONTINUAM duplicados (decisão do
fundador: a correção vale daqui para frente) — eles passam a compartilhar `phone_key`, e o
desempate de qual deles recebe um retorno futuro é o "mais antigo primeiro" de
`crm/service.py::absorb_lead`.
"""
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_DIGITS = re.compile(r"\D")
_MOBILE_FIRST_DIGITS = "6789"


def _normalize_br_frozen(raw: str | None) -> str | None:
    """Cópia CONGELADA de `app.core.phone.normalize_br` na revisão 0067.

    Não editar para "acompanhar" mudanças futuras da regra: o backfill que a produção
    recebeu foi este. Uma regra nova pede uma migration nova.
    """
    digits = _NON_DIGITS.sub("", raw or "")
    if not digits:
        return None
    if digits.startswith("55") and len(digits) - 2 in (10, 11):
        digits = digits[2:]
    if len(digits) not in (10, 11):
        return None
    ddd, local = digits[:2], digits[2:]
    if ddd[0] == "0":
        return None
    if len(local) == 8 and local[0] in _MOBILE_FIRST_DIGITS:
        local = "9" + local
    return "55" + ddd + local


def upgrade() -> None:
    op.create_table(
        "client_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("is_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"],
            name="fk_client_events_client", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_client_events_client_id", "client_events", ["client_id"])
    # A timeline sempre lê "os N mais recentes deste contato" — o índice composto serve
    # exatamente essa consulta.
    op.create_index(
        "ix_client_events_client_created", "client_events", ["client_id", "created_at"]
    )

    op.execute("ALTER TABLE client_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE client_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON client_events
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.add_column("clients", sa.Column("phone_key", sa.String(length=16), nullable=True))
    op.create_index("ix_clients_phone_key", "clients", ["phone_key"])

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo abaixo é no-op) ---
    op.execute("ALTER TABLE clients DISABLE ROW LEVEL SECURITY")

    bind = op.get_bind()
    linhas = bind.execute(
        sa.text("SELECT id, phone FROM clients WHERE phone IS NOT NULL AND phone <> ''")
    ).fetchall()
    for linha in linhas:
        chave = _normalize_br_frozen(linha.phone)
        if chave is None:
            continue  # telefone que não normaliza fica sem chave; não se adivinha
        bind.execute(
            sa.text("UPDATE clients SET phone_key = :chave WHERE id = :id"),
            {"chave": chave, "id": linha.id},
        )

    op.execute("ALTER TABLE clients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clients FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_clients_phone_key", table_name="clients")
    op.drop_column("clients", "phone_key")
    op.drop_index("ix_client_events_client_created", table_name="client_events")
    op.drop_index("ix_client_events_client_id", table_name="client_events")
    op.drop_table("client_events")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_migration_0067_phone_key.py -v`
Expected: PASS (12 casos parametrizados + 1 teste de encadeamento)

- [ ] **Step 5: Lint**

Run: `cd apps/api && ruff check migrations/versions/0067_client_events_and_phone_key.py tests/test_migration_0067_phone_key.py`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add apps/api/migrations/versions/0067_client_events_and_phone_key.py apps/api/tests/test_migration_0067_phone_key.py
git commit -m "feat: migration 0067 - client_events e backfill de phone_key"
```

---

### Task 4: Validação da migration contra Postgres real (`rls_e2e`)

**Files:**
- Create: `apps/api/tests/test_crm_events_rls.py`

**Interfaces:**
- Consumes: migration `0067` (Task 3).
- Produces: nada consumido por tarefas seguintes. É o gate que prova que o backfill não é no-op.

**Por que uma tarefa própria:** é o risco número um da spec, tem ciclo de teste distinto (testcontainers, Postgres real, alguns minutos) e um revisor pode legitimamente aprovar a migration e rejeitar a validação dela — ou o contrário.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_crm_events_rls.py`, no mesmo molde de `tests/test_receipts_rls.py`:

```python
"""Migration 0067 e `client_events` sob RLS REAL (papel não-superusuário `e1p_app`).

Dois fatos que a suíte SQLite é estruturalmente incapaz de provar:

1. **O backfill de `phone_key` NÃO é no-op.** `clients` tem FORCE ROW LEVEL SECURITY. Se a
   migration esquecesse de desabilitar a RLS na janela do backfill, o UPDATE afetaria zero
   linhas SEM ERRO NENHUM — e o sintoma em produção seria "continua duplicando contato", meses
   depois. Semeamos `clients` ANTES de `alembic upgrade head` e conferimos as chaves depois.
2. **`client_events` é fail-closed cross-tenant.** Sessão do tenant A não enxerga evento do
   tenant B; sessão SEM GUC não enxerga nada.

Cada caso negativo vem com controle positivo (mesma operação sob a ótica do dono) para provar
que a asserção falha pelo motivo certo, e não por id errado.

Marcado `rls_e2e`: NÃO roda no `pytest -q`/`scripts/check.sh`. Roda no job `cross-tenant-rls`
do CI ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"

_API_DIR = Path(__file__).resolve().parents[1]

TENANT_A = str(uuid4())
TENANT_B = str(uuid4())
```

Copie de `tests/test_receipts_rls.py` os helpers de bootstrap **sem alterar**:
`_bootstrap_rls_role`, o helper de URL do papel `e1p_app` e o helper que roda
`alembic upgrade` — eles já existem e são idênticos para qualquer teste `rls_e2e`. Em seguida,
acrescente as fixtures e casos específicos desta tarefa:

```python
@pytest.fixture(scope="module")
def pg_url():
    """Sobe Postgres, cria o papel `e1p_app`, SEMEIA `clients` e SÓ ENTÃO migra até a head.

    A ordem importa: as linhas precisam existir ANTES do backfill, senão o teste passaria
    com a migration errada (backfill de tabela vazia é indistinguível de backfill no-op).
    """
    with PostgresContainer("postgres:16", username=_ROOT_USER, password=_ROOT_PASS,
                           dbname=_DB_NAME) as pg:
        super_url = pg.get_connection_url()
        _bootstrap_rls_role(super_url)

        # migra até 0066 (o estado ANTES desta feature) como e1p_app
        _alembic_upgrade(_app_url(super_url), revision="0066")

        # semeia dois tenants com telefones em formatos diferentes
        engine = create_engine(_app_url(super_url), poolclass=NullPool)
        with engine.begin() as conn:
            conn.execute(text("SET app.current_tenant_id = :t"), {"t": TENANT_A})
            for nome, telefone in [
                ("Flavio Moderno", "(11) 99999-8888"),
                ("Flavio Antigo", "11 9999-8888"),
                ("Fixo do Escritorio", "(11) 3333-4444"),
                ("Sem Telefone", ""),
            ]:
                conn.execute(
                    text(
                        "INSERT INTO clients (id, tenant_id, name, phone, gender, notes, "
                        "tags, source, created_at, updated_at) VALUES "
                        "(:id, :t, :n, :p, 'unspecified', '', '[]'::json, 'landing', "
                        "now(), now())"
                    ),
                    {"id": str(uuid4()), "t": TENANT_A, "n": nome, "p": telefone},
                )
        engine.dispose()

        # AGORA aplica a 0067 — o backfill encontra linhas de verdade
        _alembic_upgrade(_app_url(super_url), revision="head")
        yield _app_url(super_url)


def test_backfill_de_phone_key_nao_foi_no_op(pg_url):
    """Se a migration esquecesse de abrir a janela de RLS, todos viriam NULL."""
    engine = create_engine(pg_url, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("SET app.current_tenant_id = :t"), {"t": TENANT_A})
        linhas = conn.execute(
            text("SELECT name, phone, phone_key FROM clients ORDER BY name")
        ).fetchall()
    engine.dispose()

    por_nome = {r.name: r.phone_key for r in linhas}
    assert por_nome["Flavio Moderno"] == "5511999998888"
    # o celular pré-2016 normaliza para A MESMA chave — é o que faz a dedup funcionar
    assert por_nome["Flavio Antigo"] == "5511999998888"
    # fixo NÃO colide com o celular
    assert por_nome["Fixo do Escritorio"] == "551133334444"
    assert por_nome["Sem Telefone"] is None


def test_phone_cru_nao_foi_alterado_pelo_backfill(pg_url):
    """`phone` é evidência do que a pessoa digitou; o backfill só preenche a coluna nova."""
    engine = create_engine(pg_url, poolclass=NullPool)
    with engine.begin() as conn:
        conn.execute(text("SET app.current_tenant_id = :t"), {"t": TENANT_A})
        phone = conn.scalar(
            text("SELECT phone FROM clients WHERE name = 'Flavio Moderno'")
        )
    engine.dispose()
    assert phone == "(11) 99999-8888"


def test_client_events_isolado_entre_tenants(pg_url):
    engine = create_engine(pg_url, poolclass=NullPool)
    evento_id = str(uuid4())
    with engine.begin() as conn:
        conn.execute(text("SET app.current_tenant_id = :t"), {"t": TENANT_A})
        client_id = conn.scalar(
            text("SELECT id FROM clients WHERE name = 'Flavio Moderno'")
        )
        conn.execute(
            text(
                "INSERT INTO client_events (id, tenant_id, client_id, kind, title, body, "
                "actor, is_ai, created_at, updated_at) VALUES "
                "(:id, :t, :c, 'note', 'Decisao', 'fechamos com 10%', 'ana@example.com', "
                "false, now(), now())"
            ),
            {"id": evento_id, "t": TENANT_A, "c": client_id},
        )

    # controle POSITIVO: o dono enxerga
    with engine.begin() as conn:
        conn.execute(text("SET app.current_tenant_id = :t"), {"t": TENANT_A})
        assert conn.scalar(
            text("SELECT count(*) FROM client_events WHERE id = :id"), {"id": evento_id}
        ) == 1

    # caso NEGATIVO: outro tenant não enxerga
    with engine.begin() as conn:
        conn.execute(text("SET app.current_tenant_id = :t"), {"t": TENANT_B})
        assert conn.scalar(
            text("SELECT count(*) FROM client_events WHERE id = :id"), {"id": evento_id}
        ) == 0

    # caso NEGATIVO: sessão sem GUC não enxerga nada (fail-closed)
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM client_events")) == 0
    engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_crm_events_rls.py -m rls_e2e -v`
Expected: FAIL — os helpers `_bootstrap_rls_role`, `_app_url` e `_alembic_upgrade` ainda não foram copiados de `test_receipts_rls.py`.

- [ ] **Step 3: Copy the bootstrap helpers**

Abra `apps/api/tests/test_receipts_rls.py`, copie **verbatim** as funções `_bootstrap_rls_role`, `_app_url` e a que executa `alembic upgrade` para dentro de `test_crm_events_rls.py`, ajustando apenas a assinatura da última para aceitar `revision` (`"0066"` / `"head"`) em vez de assumir `head`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_crm_events_rls.py -m rls_e2e -v`
Expected: PASS (4 testes). Requer Docker rodando; leva alguns minutos na primeira execução (baixa a imagem `postgres:16`).

- [ ] **Step 5: Sanity — prove que o teste pegaria o bug**

Comente temporariamente as duas linhas `ALTER TABLE clients DISABLE/ENABLE ROW LEVEL SECURITY` da migration 0067 e rode de novo.
Expected: `test_backfill_de_phone_key_nao_foi_no_op` FALHA com todos os `phone_key` em `None`.
**Descomente as linhas em seguida** e confirme que volta a passar. Sem este passo não há prova de que o teste detecta o que ele diz detectar.

- [ ] **Step 6: Commit**

```bash
git add apps/api/tests/test_crm_events_rls.py
git commit -m "test: valida backfill da 0067 e RLS de client_events em Postgres real"
```

---

### Task 5: `record_event` + eventos de criação e movimentação

**Files:**
- Modify: `apps/api/app/modules/crm/service.py`
- Test: `apps/api/tests/test_client_events.py` (create)

**Interfaces:**
- Consumes: `ClientEvent`, constantes `KIND_*` (Task 2).
- Produces:
  - `record_event(db, *, tenant_id, client_id, kind, title, actor, body="", is_ai=False) -> ClientEvent` — **não commita**, só faz `db.add`. Quem chama decide o momento do commit (mesmo padrão de `receivables.build_charge`).
  - `create_client` passa a gravar um `lead_created`; `move_client` passa a gravar um `stage_move`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_client_events.py`:

```python
"""Eventos narrativos gravados pelos caminhos que já existiam no CRM."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.crm.models import ClientEvent

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _eventos(db, client_id: str) -> list[ClientEvent]:
    return list(
        db.scalars(
            select(ClientEvent)
            .where(ClientEvent.client_id == client_id)
            .order_by(ClientEvent.created_at, ClientEvent.id)
        ).all()
    )


def test_criar_cliente_grava_lead_created(client: TestClient, headers, db):
    resp = client.post(
        "/crm/clients", json={"name": "Flavio Kato", "phone": "(11) 99999-8888"},
        headers=headers,
    )
    assert resp.status_code == 201
    eventos = _eventos(db, resp.json()["id"])
    assert [e.kind for e in eventos] == ["lead_created"]
    assert eventos[0].title  # tem frase, não fica em branco


def test_criar_cliente_preenche_phone_key(client: TestClient, headers, db):
    """Sem isto o backfill conserta o legado e o código novo volta a criar linha sem chave."""
    from app.modules.crm.models import Client

    resp = client.post(
        "/crm/clients", json={"name": "Flavio Kato", "phone": "(11) 9999-8888"},
        headers=headers,
    )
    c = db.get(Client, resp.json()["id"])
    assert c.phone_key == "5511999998888"


def test_mover_card_grava_stage_move_com_nomes_congelados(client: TestClient, headers, db):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")

    client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": proposta["id"]}, headers=headers
    )

    eventos = _eventos(db, criado["id"])
    assert [e.kind for e in eventos] == ["lead_created", "stage_move"]
    # o texto guarda os NOMES, não os ids — renomear a coluna depois não reescreve a história
    assert "Entrada" in eventos[1].title
    assert "Proposta" in eventos[1].title


def test_texto_do_evento_sobrevive_a_renomear_a_coluna(client: TestClient, headers, db):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")
    client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": proposta["id"]}, headers=headers
    )

    client.patch(
        f"/crm/stages/{proposta['id']}", json={"name": "Negociação"}, headers=headers
    )

    eventos = _eventos(db, criado["id"])
    assert "Proposta" in eventos[1].title  # congelado: conta o que aconteceu naquele dia
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_client_events.py -v`
Expected: FAIL — `test_criar_cliente_grava_lead_created` falha com lista vazia (`[] != ["lead_created"]`).

- [ ] **Step 3: Write minimal implementation**

Em `apps/api/app/modules/crm/service.py`:

Adicionar aos imports:

```python
from app.core.phone import normalize_br
from app.modules.crm.models import (
    DEFAULT_STAGES,
    KIND_LEAD_CREATED,
    KIND_STAGE_MOVE,
    Client,
    ClientEvent,
    PipelineStage,
)
```

Adicionar a constante de evento junto das que já existem:

```python
EVENT_CLIENT_RETURNED = "crm.client.returned"
```

Adicionar a função de gravação, antes da seção `# ── Clientes`:

```python
# ── Linha do tempo ─────────────────────────────────────


def record_event(
    db: Session,
    *,
    tenant_id: str,
    client_id: str,
    kind: str,
    title: str,
    actor: str,
    body: str = "",
    is_ai: bool = False,
) -> ClientEvent:
    """Grava um fato narrativo. **NÃO commita** — quem chama decide o momento.

    Mesmo padrão de `receivables.build_charge`: assim o evento entra na MESMA transação do
    fato que ele descreve, e não existe estado em que o card mudou de coluna mas a história
    não registrou (ou o contrário).
    """
    event = ClientEvent(
        tenant_id=tenant_id, client_id=client_id, kind=kind,
        title=title[:140], body=body, actor=actor, is_ai=is_ai,
    )
    db.add(event)
    return event
```

Em `create_client`, trocar o bloco de criação/commit por:

```python
    client = Client(
        tenant_id=tenant_id,
        name=data.name,
        email=str(data.email) if data.email else None,
        phone=data.phone,
        # Forma comparável do telefone — é o que `absorb_lead` procura. Preenchida em TODO
        # caminho de criação, senão o backfill conserta o legado e o código novo reintroduz
        # linhas sem chave.
        phone_key=normalize_br(data.phone),
        document=data.document,
        gender=data.gender,
        birthdate=data.birthdate,
        notes=data.notes,
        tags=data.tags,
        source=data.source,
        stage_id=stage_id,
    )
    db.add(client)
    # `client.id` só existe depois do flush (o default `_uuid` é aplicado na descarga). Sem
    # isto, tanto a trilha quanto o evento apontariam para lugar nenhum — é exatamente a
    # dívida MNT-001 registrada no CLAUDE.md.
    db.flush()
    record_event(
        db, tenant_id=tenant_id, client_id=client.id, kind=KIND_LEAD_CREATED,
        title=_titulo_de_chegada(client.source), actor=actor, body=data.notes,
    )
    audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.client.create", target=client.id)
    db.commit()
    db.refresh(client)
```

E acrescentar o helper de rótulo, junto de `record_event`:

```python
_ROTULO_DE_CHEGADA = {
    "landing": "Chegou pelo site",
    "api": "Chegou por integração",
    "whatsapp": "Chegou pelo WhatsApp",
    "import": "Veio de importação",
    "manual": "Cadastrado à mão",
}


def _titulo_de_chegada(source: str) -> str:
    """Um `source` novo (backend mais recente) cai num rótulo honesto em vez de sumir."""
    return _ROTULO_DE_CHEGADA.get(source, f"Chegou por “{source}”")
```

Em `move_client`, gravar o evento antes do commit — capturando os **nomes** dos estágios:

```python
def move_client(
    db: Session, *, client_id: str, tenant_id: str, actor: str, by_ai: bool, stage_id: str
) -> Client:
    client = get_client(db, client_id)
    target = db.get(PipelineStage, stage_id)
    if target is None:
        raise CrmError("Estágio de destino não existe", 404)
    from_stage = client.stage_id
    origem = db.get(PipelineStage, from_stage) if from_stage else None
    nome_origem = origem.name if origem is not None else "sem etapa"
    client.stage_id = target.id
    # Guarda os NOMES, não os ids: renomear ou arquivar a coluna depois não pode reescrever
    # o que aconteceu naquele dia (princípio do `raw_description` de bank_transactions).
    record_event(
        db, tenant_id=tenant_id, client_id=client.id, kind=KIND_STAGE_MOVE,
        title=f"Movido de {nome_origem} → {target.name}", actor=actor, is_ai=by_ai,
    )
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="crm.client.move",
        target=client.id, is_ai=by_ai,
    )
    db.commit()
    db.refresh(client)
    events.emit(
        EVENT_CLIENT_MOVED,
        tenant_id=tenant_id,
        client_id=client.id,
        from_stage=from_stage,
        to_stage=target.id,
        is_won=target.is_won,
        is_lost=target.is_lost,
    )
    return client
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_client_events.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Verify no regression**

Run: `cd apps/api && pytest tests/test_crm.py tests/test_cockpit.py tests/test_funnels.py -v`
Expected: PASS — `create_client`/`move_client` mantêm assinatura e comportamento externo.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/crm/service.py apps/api/tests/test_client_events.py
git commit -m "feat: grava lead_created e stage_move na linha do tempo do contato"
```

---

### Task 6: `absorb_lead` — reconhecer quem voltou

**Files:**
- Modify: `apps/api/app/modules/crm/service.py`
- Test: `apps/api/tests/test_lead_absorb.py` (create)

**Interfaces:**
- Consumes: `record_event`, `create_client`, `_ordered_stages` (Task 5); `normalize_br` (Task 1); `KIND_LEAD_RETURN`, `KIND_REOPENED` (Task 2).
- Produces: `absorb_lead(db, *, tenant_id, actor, data: ClientCreate) -> tuple[Client, bool]` — o `bool` é `is_new`. Emite `EVENT_CLIENT_RETURNED` (`"crm.client.returned"`) com `tenant_id`, `client_id`, `source`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_lead_absorb.py`:

```python
"""`absorb_lead`: o lead que volta complementa o contato, não abre um card novo."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.crm import service
from app.modules.crm.models import Client, ClientEvent, PipelineStage
from app.modules.crm.schemas import ClientCreate

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    resp = client.post("/auth/register", json=REGISTER)
    return resp.json()["tenant"]["id"]


def _absorve(db, tenant_id: str, **campos):
    return service.absorb_lead(
        db, tenant_id=tenant_id, actor="pagina:lead", data=ClientCreate(**campos)
    )


def _kinds(db, client_id: str) -> list[str]:
    return [
        e.kind
        for e in db.scalars(
            select(ClientEvent)
            .where(ClientEvent.client_id == client_id)
            .order_by(ClientEvent.created_at, ClientEvent.id)
        ).all()
    ]


def _stage(db, nome: str) -> PipelineStage:
    return db.scalar(select(PipelineStage).where(PipelineStage.name == nome))


def test_lead_desconhecido_cria_contato(db, tenant_id):
    contato, novo = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    assert novo is True
    assert _kinds(db, contato.id) == ["lead_created"]


def test_mesmo_telefone_em_formato_diferente_nao_cria_segundo_card(db, tenant_id):
    primeiro, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    segundo, novo = _absorve(
        db, tenant_id, name="Flavio Kato", phone="5511999998888", source="landing"
    )
    assert novo is False
    assert segundo.id == primeiro.id
    assert db.scalar(select(Client).where(Client.id != primeiro.id)) is None


def test_mesmo_email_sem_telefone_nao_cria_segundo_card(db, tenant_id):
    primeiro, _ = _absorve(
        db, tenant_id, name="Flavio Kato", email="flavio@example.com", source="landing"
    )
    segundo, novo = _absorve(
        db, tenant_id, name="Flavio K.", email="FLAVIO@EXAMPLE.COM", source="landing"
    )
    assert novo is False
    assert segundo.id == primeiro.id


def test_retorno_grava_lead_return_com_o_texto_desta_vez(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing",
        notes="Quero orçamento para 50 convidados",
    )
    eventos = list(
        db.scalars(
            select(ClientEvent)
            .where(ClientEvent.client_id == contato.id, ClientEvent.kind == "lead_return")
        ).all()
    )
    assert len(eventos) == 1
    assert "50 convidados" in eventos[0].body


def test_retorno_preenche_campo_vazio_mas_nao_sobrescreve(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888",
        email="antigo@example.com", source="landing",
    )
    _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888",
        email="novo@example.com", document="52998224725", source="landing",
    )
    db.refresh(contato)
    assert contato.email == "antigo@example.com"   # já tinha: não toca
    assert contato.document == "52998224725"       # estava vazio: preenche


def test_retorno_nao_apaga_as_observacoes_do_dono(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    contato.notes = "Cliente exigente, cobrar adiantado"
    db.commit()
    _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing",
        notes="texto novo do formulario",
    )
    db.refresh(contato)
    assert contato.notes == "Cliente exigente, cobrar adiantado"


def test_retorno_nao_move_card_de_coluna_do_meio(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    proposta = _stage(db, "Proposta")
    contato.stage_id = proposta.id
    db.commit()

    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")
    db.refresh(contato)
    assert contato.stage_id == proposta.id
    assert "reopened" not in _kinds(db, contato.id)


@pytest.mark.parametrize("coluna", ["Ganho", "Perda"])
def test_retorno_reabre_card_em_coluna_terminal(db, tenant_id, coluna):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    terminal = _stage(db, coluna)
    contato.stage_id = terminal.id
    db.commit()

    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")
    db.refresh(contato)
    entrada = _stage(db, "Entrada")
    assert contato.stage_id == entrada.id
    assert "reopened" in _kinds(db, contato.id)


def test_multiplos_candidatos_escolhe_o_mais_antigo(db, tenant_id):
    """Os duplicados legados não foram mesclados — o retorno precisa cair sempre no mesmo."""
    antigo = Client(
        tenant_id=tenant_id, name="Flavio 1", phone="(11) 99999-8888",
        phone_key="5511999998888", source="landing",
    )
    db.add(antigo)
    db.flush()
    novo = Client(
        tenant_id=tenant_id, name="Flavio 2", phone="(11) 99999-8888",
        phone_key="5511999998888", source="landing",
    )
    db.add(novo)
    db.commit()

    achado, criou = _absorve(
        db, tenant_id, name="Flavio", phone="(11) 99999-8888", source="landing"
    )
    assert criou is False
    assert achado.id == antigo.id


def test_retorno_emite_evento_no_barramento(db, tenant_id):
    from app.core import events

    recebidos = []
    events.subscribe(service.EVENT_CLIENT_RETURNED, lambda **kw: recebidos.append(kw))

    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")
    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")

    assert len(recebidos) == 1
    assert recebidos[0]["source"] == "landing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_lead_absorb.py -v`
Expected: FAIL — `AttributeError: module 'app.modules.crm.service' has no attribute 'absorb_lead'`

- [ ] **Step 3: Write minimal implementation**

Em `apps/api/app/modules/crm/service.py`, adicionar `func` ao import de `sqlalchemy` (já importado) e `KIND_LEAD_RETURN`, `KIND_REOPENED` ao import de models. Então acrescentar, depois de `create_client`:

```python
def _find_existing(db: Session, *, phone_key: str | None, email: str | None) -> Client | None:
    """Procura o contato por telefone normalizado e, em segundo lugar, por e-mail.

    Ordem `created_at, id` porque `phone_key` NÃO é único e não deve ser: marido e mulher
    compartilham telefone, e os cards duplicados que já existiam (não mesclados, por decisão
    do fundador) compartilham chave a partir do backfill da 0067. Sem um desempate
    determinístico, o próximo retorno cairia num card imprevisível e a história se partiria
    entre eles. O mais antigo é o que acumulou mais contexto.
    """
    if phone_key:
        achado = db.scalars(
            select(Client)
            .where(Client.phone_key == phone_key)
            .order_by(Client.created_at, Client.id)
        ).first()
        if achado is not None:
            return achado
    if email:
        return db.scalars(
            select(Client)
            .where(func.lower(Client.email) == email.strip().lower())
            .order_by(Client.created_at, Client.id)
        ).first()
    return None


def absorb_lead(
    db: Session, *, tenant_id: str, actor: str, data: ClientCreate
) -> tuple[Client, bool]:
    """Porta ÚNICA de entrada de lead. Devolve `(contato, é_novo)`.

    Quem já existe é complementado — data nova e texto novo na linha do tempo — em vez de
    ganhar um card paralelo. É o que os três caminhos de captura (página pública, API de
    integração, WhatsApp) passam a usar.
    """
    existente = _find_existing(
        db,
        phone_key=normalize_br(data.phone),
        email=str(data.email) if data.email else None,
    )
    if existente is None:
        return create_client(db, tenant_id=tenant_id, actor=actor, data=data), True

    # Preenche só o que estava VAZIO. Sobrescrever apagaria o que o dono já corrigiu à mão;
    # a divergência (chegou outro e-mail) fica registrada no corpo do evento.
    complementos: list[str] = []
    if not existente.email and data.email:
        existente.email = str(data.email)
        complementos.append(f"e-mail: {data.email}")
    elif data.email and existente.email != str(data.email):
        complementos.append(f"informou outro e-mail: {data.email}")
    if not existente.phone and data.phone:
        existente.phone = data.phone
        existente.phone_key = normalize_br(data.phone)
        complementos.append(f"telefone: {data.phone}")
    if not existente.document and data.document:
        existente.document = data.document
        complementos.append(f"documento: {data.document}")
    if not existente.phone_key and existente.phone:
        # Contato legado cujo telefone não normalizava na 0067 (ou nasceu antes dela).
        existente.phone_key = normalize_br(existente.phone)

    corpo = "\n".join(filter(None, [data.notes, *complementos]))
    record_event(
        db, tenant_id=tenant_id, client_id=existente.id, kind=KIND_LEAD_RETURN,
        title=_titulo_de_retorno(data.source), actor=actor, body=corpo,
    )

    # Coluna terminal (ganho OU perda) = a negociação anterior fechou. Quem volta sozinho
    # depois disso é oportunidade nova: perdido que voltou, ou cliente querendo comprar de
    # novo. Coluna do meio NÃO se move — puxar de volta apagaria trabalho em andamento.
    etapa = db.get(PipelineStage, existente.stage_id) if existente.stage_id else None
    if etapa is not None and (etapa.is_won or etapa.is_lost):
        ativas = _ordered_stages(db)
        if ativas:
            existente.stage_id = ativas[0].id
            record_event(
                db, tenant_id=tenant_id, client_id=existente.id, kind=KIND_REOPENED,
                title=f"Reaberto em {ativas[0].name} (estava em {etapa.name})", actor=actor,
            )

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="crm.client.return", target=existente.id
    )
    db.commit()
    db.refresh(existente)
    events.emit(
        EVENT_CLIENT_RETURNED,
        tenant_id=tenant_id,
        client_id=existente.id,
        source=data.source,
    )
    return existente, False


_ROTULO_DE_RETORNO = {
    "landing": "Voltou pelo site",
    "api": "Voltou por integração",
}


def _titulo_de_retorno(source: str) -> str:
    return _ROTULO_DE_RETORNO.get(source, f"Voltou por “{source}”")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_lead_absorb.py -v`
Expected: PASS (11 testes, contando os 2 parametrizados de coluna terminal)

- [ ] **Step 5: Lint**

Run: `cd apps/api && ruff check app/modules/crm/service.py tests/test_lead_absorb.py`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/crm/service.py apps/api/tests/test_lead_absorb.py
git commit -m "feat: absorb_lead reconhece o contato que volta em vez de duplicar"
```

---

### Task 7: Ligar as três portas de entrada

**Files:**
- Modify: `apps/api/app/modules/pages/service.py:201-225`
- Modify: `apps/api/app/modules/integrations/service.py:105-127`
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py:113-120`
- Test: `apps/api/tests/test_lead_portas.py` (create)

**Interfaces:**
- Consumes: `absorb_lead` (Task 6), `normalize_br` (Task 1).
- Produces: nada novo. As três portas passam a convergir no mesmo contato.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_lead_portas.py`:

```python
"""As três portas de entrada de contato convergem para o MESMO card."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.whatsapp_inbox import service as inbox_service

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    return client.post("/auth/register", json=REGISTER).json()["tenant"]["id"]


def test_site_depois_whatsapp_e_um_card_so(db, tenant_id):
    """O teste que amarra as duas portas.

    Sem a normalização compartilhada, o site guardaria "(11) 99999-8888", o WhatsApp
    guardaria "5511999998888", e a mesma pessoa continuaria virando dois cards — agora por
    um motivo mais difícil de enxergar do que o bug original.
    """
    from app.modules.crm import service as crm_service

    crm_service.absorb_lead(
        db, tenant_id=tenant_id, actor="pagina:lead",
        data=ClientCreate(name="Flavio Kato", phone="(11) 99999-8888", source="landing"),
    )
    inbox_service._get_or_create_client(
        db, tenant_id=tenant_id, phone="5511999998888", name="Flavio",
    )

    assert db.scalar(select(func.count(Client.id))) == 1


def test_whatsapp_depois_site_e_um_card_so(db, tenant_id):
    from app.modules.crm import service as crm_service

    inbox_service._get_or_create_client(
        db, tenant_id=tenant_id, phone="5511999998888", name="Flavio",
    )
    _, novo = crm_service.absorb_lead(
        db, tenant_id=tenant_id, actor="pagina:lead",
        data=ClientCreate(name="Flavio Kato", phone="(11) 99999-8888", source="landing"),
    )

    assert novo is False
    assert db.scalar(select(func.count(Client.id))) == 1


def test_whatsapp_grava_phone_key(db, tenant_id):
    contato = inbox_service._get_or_create_client(
        db, tenant_id=tenant_id, phone="5511999998888", name="Flavio",
    )
    assert contato.phone_key == "5511999998888"


@pytest.fixture()
def slug_publicado(client: TestClient) -> str:
    """Cria e publica uma página de captura, devolvendo o slug público.

    Contrato conferido em `tests/test_pages.py`: o corpo de criação usa `model` (não
    `template`), e o slug vem em `public_slug` na resposta da CRIAÇÃO — `publish` só torna
    a página visível.
    """
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    page = client.post(
        "/pages", json={"title": "Captura", "model": "captura"}, headers=h
    ).json()
    client.post(f"/pages/{page['id']}/publish", headers=h)
    return page["public_slug"]


def test_formulario_publico_repetido_nao_duplica(client: TestClient, slug_publicado, db):
    """Envio duplicado pelo formulário da landing page — o bug original da tela do fundador."""
    corpo = {"name": "Flavio Kato", "phone": "(11) 99999-8888", "email": "f@example.com"}
    assert client.post(f"/public/pages/{slug_publicado}/submit", json=corpo).status_code < 400
    assert client.post(f"/public/pages/{slug_publicado}/submit", json=corpo).status_code < 400

    assert db.scalar(select(func.count(Client.id))) == 1
```

**Nota sobre a fixture `tenant_id`:** os dois primeiros testes deste arquivo usam `tenant_id`
(que já registra um tenant) e o último usa `slug_publicado` (que registra o seu). Não misture
as duas no mesmo teste — o segundo `POST /auth/register` com o mesmo e-mail devolve 409.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_lead_portas.py -v`
Expected: FAIL — `test_site_depois_whatsapp_e_um_card_so` acha 2 clientes (o WhatsApp compara `Client.phone == "5511999998888"` cru, que não bate com `"(11) 99999-8888"`).

- [ ] **Step 3a: `pages/service.py`**

Substituir a chamada dentro de `public_submit` (linhas 218-225):

```python
    with session_factory(snap.tenant_id) as tdb:
        # `absorb_lead` (não `create_client`): quem já existe é complementado com a data e o
        # texto deste envio, em vez de ganhar um card paralelo no Kanban.
        crm_service.absorb_lead(
            tdb, tenant_id=snap.tenant_id, actor="pagina:lead",
            data=ClientCreate(
                name=name, email=email, phone=phone or None, source="landing",
                notes=_format_fields(fields),
            ),
        )
```

- [ ] **Step 3b: `integrations/service.py`**

Substituir a chamada dentro de `capture_lead` (linhas 117-127):

```python
    with session_factory(snap.tenant_id) as tdb:
        crm_service.absorb_lead(
            tdb, tenant_id=snap.tenant_id, actor="integracao:lead",
            data=ClientCreate(
                name=data.name,
                email=str(data.email) if data.email else None,
                phone=data.phone,
                notes=_format_notes(data.notes, data.fields),
                source="api",
            ),
        )
```

- [ ] **Step 3c: `whatsapp_inbox/service.py`**

Substituir `_get_or_create_client` (linhas 113-120):

```python
def _get_or_create_client(db: Session, *, tenant_id: str, phone: str, name: str) -> Client:
    """Resolve o contato pelo telefone NORMALIZADO — a mesma identidade que o site usa.

    Comparar `Client.phone` cru (como era até aqui) deixava o conserto pela metade: o
    formulário guarda "(11) 99999-8888" e o WhatsApp guarda "5511999998888", então a mesma
    pessoa continuaria virando dois cards.
    """
    chave = normalize_br(phone)
    if chave:
        client = db.scalars(
            select(Client).where(Client.phone_key == chave).order_by(Client.created_at, Client.id)
        ).first()
        if client is not None:
            return client
    # Fallback para contato legado cujo telefone nunca normalizou (e portanto não tem chave).
    client = db.scalar(select(Client).where(Client.phone == phone))
    if client is not None:
        return client
    return crm_service.create_client(
        db, tenant_id=tenant_id, actor="whatsapp:inbox",
        data=ClientCreate(name=name or phone, phone=phone, source="whatsapp"),
    )
```

Adicionar ao topo do arquivo: `from app.core.phone import normalize_br`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_lead_portas.py -v`
Expected: PASS (4 testes)

- [ ] **Step 5: Verify no regression across the three modules**

Run: `cd apps/api && pytest tests/test_pages.py tests/test_integrations.py tests/test_whatsapp_inbox_service.py tests/test_whatsapp_inbox_evolution_webhook.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/pages/service.py apps/api/app/modules/integrations/service.py apps/api/app/modules/whatsapp_inbox/service.py apps/api/tests/test_lead_portas.py
git commit -m "feat: site, integracao e WhatsApp convergem no mesmo contato"
```

---

### Task 8: Reinscrição no funil, com guarda de jornada ativa

**Files:**
- Modify: `apps/api/app/modules/funnels/automation.py`
- Test: `apps/api/tests/test_lead_auto_enroll.py:1-90` (modify — acrescentar casos)

**Interfaces:**
- Consumes: `EVENT_CLIENT_RETURNED` (Task 6), `record_event` e `KIND_FUNNEL` (Tasks 2 e 5).
- Produces: `on_client_returned(*, tenant_id, client_id, source, **_)` registrado no barramento.

- [ ] **Step 1: Write the failing test**

Acrescentar a `apps/api/tests/test_lead_auto_enroll.py`:

```python
def test_retorno_reinscreve_quando_a_jornada_anterior_terminou(db: Session, _fake_session):
    from app.modules.funnels.models import RUN_DONE, FunnelRun

    tenant = _seed_tenant(db, slug="auto4", document="00000000000104")
    funnel = _seed_funnel(db, tenant.id)
    db.add(TenantProfile(tenant_id=tenant.id, default_entry_funnel_id=funnel.id))
    client = Client(tenant_id=tenant.id, name="Lead Recorrente", source="landing")
    db.add(client)
    db.commit()

    automation.on_client_created(tenant_id=tenant.id, client_id=client.id, source="landing")
    primeira = _run_for(db, client.id)
    assert primeira is not None
    primeira.status = RUN_DONE
    db.commit()

    automation.on_client_returned(tenant_id=tenant.id, client_id=client.id, source="landing")

    runs = list(db.scalars(select(FunnelRun).where(FunnelRun.client_id == client.id)).all())
    assert len(runs) == 2


def test_retorno_nao_reinscreve_quem_ja_esta_andando(db: Session, _fake_session):
    """Preencher o formulário duas vezes não pode reiniciar a jornada do zero."""
    from app.modules.funnels.models import FunnelRun

    tenant = _seed_tenant(db, slug="auto5", document="00000000000105")
    funnel = _seed_funnel(db, tenant.id)
    db.add(TenantProfile(tenant_id=tenant.id, default_entry_funnel_id=funnel.id))
    client = Client(tenant_id=tenant.id, name="Lead Ansioso", source="landing")
    db.add(client)
    db.commit()

    automation.on_client_created(tenant_id=tenant.id, client_id=client.id, source="landing")
    automation.on_client_returned(tenant_id=tenant.id, client_id=client.id, source="landing")

    runs = list(db.scalars(select(FunnelRun).where(FunnelRun.client_id == client.id)).all())
    assert len(runs) == 1


def test_retorno_de_source_manual_nao_inscreve(db: Session, _fake_session):
    from app.modules.funnels.models import FunnelRun

    tenant = _seed_tenant(db, slug="auto6", document="00000000000106")
    funnel = _seed_funnel(db, tenant.id)
    db.add(TenantProfile(tenant_id=tenant.id, default_entry_funnel_id=funnel.id))
    client = Client(tenant_id=tenant.id, name="Lead Manual", source="manual")
    db.add(client)
    db.commit()

    automation.on_client_returned(tenant_id=tenant.id, client_id=client.id, source="manual")

    assert db.scalar(select(FunnelRun).where(FunnelRun.client_id == client.id)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_lead_auto_enroll.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'on_client_returned'`

- [ ] **Step 3: Write minimal implementation**

Em `apps/api/app/modules/funnels/automation.py`, acrescentar os imports e as funções:

```python
from sqlalchemy import select

from app.modules.crm.models import KIND_FUNNEL
from app.modules.crm.service import EVENT_CLIENT_CREATED, EVENT_CLIENT_RETURNED, record_event
from app.modules.funnels.models import RUN_RUNNING, RUN_WAITING, FunnelRun
```

```python
def _ja_esta_andando(db, *, funnel_id: str, client_id: str) -> bool:
    """Jornada viva (running/waiting) para este contato neste funil."""
    return db.scalar(
        select(FunnelRun.id).where(
            FunnelRun.funnel_id == funnel_id,
            FunnelRun.client_id == client_id,
            FunnelRun.status.in_((RUN_RUNNING, RUN_WAITING)),
        )
    ) is not None


def on_client_returned(*, tenant_id: str, client_id: str, source: str, **_: object) -> None:
    """Contato conhecido voltou pela captura: reinscreve, se a jornada anterior já acabou.

    A guarda de "já está andando" vive AQUI e não dentro de `engine.enroll`: inscrição manual
    pela tela do funil deve continuar fazendo exatamente o que o usuário mandar, sem recusar
    em silêncio. Só o caminho automático precisa dessa contenção — senão preencher o
    formulário duas vezes reiniciaria a jornada do zero.
    """
    if source not in AUTO_ENROLL_SOURCES:
        return
    with tenant_session(tenant_id) as db:
        profile = settings_service.get_profile(db, tenant_id)
        if not profile.default_entry_funnel_id:
            return
        if _ja_esta_andando(
            db, funnel_id=profile.default_entry_funnel_id, client_id=client_id
        ):
            return
        try:
            engine.enroll(
                db, tenant_id=tenant_id, actor="sistema:auto-enroll",
                funnel_id=profile.default_entry_funnel_id, client_id=client_id,
            )
        except service.FunnelError:
            logger.warning(
                "[funnels:on_client_returned] reinscrição falhou tenant=%s funil=%s cliente=%s",
                tenant_id, profile.default_entry_funnel_id, client_id,
            )
            return
        record_event(
            db, tenant_id=tenant_id, client_id=client_id, kind=KIND_FUNNEL,
            title="Reinscrito no funil de entrada", actor="sistema:auto-enroll",
        )
        db.commit()
```

E no `register()`:

```python
def register() -> None:
    """Liga os assinantes do barramento. Chamado uma vez no boot (app.main)."""
    events.subscribe(EVENT_CLIENT_CREATED, on_client_created)
    events.subscribe(EVENT_CLIENT_RETURNED, on_client_returned)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_lead_auto_enroll.py -v`
Expected: PASS (todos os casos antigos + os 3 novos)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/funnels/automation.py apps/api/tests/test_lead_auto_enroll.py
git commit -m "feat: retorno de lead reinscreve no funil sem duplicar jornada ativa"
```

---

### Task 9: Read model da timeline + endpoints

**Files:**
- Create: `apps/api/app/modules/crm/timeline.py`
- Modify: `apps/api/app/modules/crm/schemas.py`
- Modify: `apps/api/app/modules/crm/router.py`
- Test: `apps/api/tests/test_client_timeline.py` (create)

**Interfaces:**
- Consumes: `ClientEvent` (Task 2), `record_event`/`get_client` (Task 5).
- Produces:
  - `timeline.build(db, *, client_id: str, limit: int = 100) -> tuple[list[dict], bool]` — a lista já ordenada por `at` decrescente e o flag `truncated`. Cada `dict` tem as chaves `id, kind, title, body, actor, is_ai, at`.
  - Schemas `ClientTimelineEntry`, `ClientTimelineOut`, `NoteCreate`.
  - Rotas `GET /crm/clients/{client_id}/timeline` e `POST /crm/clients/{client_id}/notes`.

- [ ] **Step 1: Write the failing test**

Create `apps/api/tests/test_client_timeline.py`:

```python
"""Timeline do contato: mescla o narrativo (client_events) com o financeiro (charges/quotes)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def contato(client: TestClient, headers) -> str:
    return client.post(
        "/crm/clients", json={"name": "Flavio Kato", "phone": "(11) 99999-8888"},
        headers=headers,
    ).json()["id"]


def test_timeline_comeca_com_a_chegada(client: TestClient, headers, contato):
    resp = client.get(f"/crm/clients/{contato}/timeline", headers=headers)
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["truncated"] is False
    assert [e["kind"] for e in corpo["entries"]] == ["lead_created"]


def test_timeline_inclui_a_cobranca_sem_copiar_o_valor(client: TestClient, headers, contato, db):
    """O financeiro é LIDO de `charges`. Nenhuma linha de `client_events` guarda o valor.

    A cobrança é semeada direto no banco (e não pela rota) de propósito: o contrato de
    `POST /receivables/charges` não é definido por este plano, e o que está sendo provado
    aqui é o read model da timeline, não a criação de cobrança.
    """
    from sqlalchemy import select

    from app.modules.crm.models import Client, ClientEvent
    from app.modules.receivables.models import Charge

    tenant_id = db.scalar(select(Client.tenant_id).where(Client.id == contato))
    db.add(
        Charge(
            tenant_id=tenant_id, client_id=contato, description="Ensaio",
            kind="service", method="pix", amount_cents=120000,
            due_date=date(2026, 9, 10),
        )
    )
    db.commit()

    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    entrada = next(e for e in corpo["entries"] if e["kind"] == "charge")
    assert "1.200,00" in entrada["title"]

    # A fonte única do valor continua sendo `charges`: nenhum evento narrativo o copiou.
    eventos = list(
        db.scalars(select(ClientEvent).where(ClientEvent.client_id == contato)).all()
    )
    assert all("1.200,00" not in (e.title + e.body) for e in eventos)


def test_timeline_ordena_do_mais_recente_para_o_mais_antigo(client: TestClient, headers, contato):
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")
    client.post(f"/crm/clients/{contato}/move", json={"stage_id": proposta["id"]}, headers=headers)

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    ats = [e["at"] for e in entries]
    assert ats == sorted(ats, reverse=True)
    assert entries[-1]["kind"] == "lead_created"  # o mais antigo é a chegada


def test_gravar_nota_aparece_na_timeline(client: TestClient, headers, contato):
    resp = client.post(
        f"/crm/clients/{contato}/notes",
        json={"title": "Desconto aprovado", "body": "Cliente pediu 10%, fechamos em 10%"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "note"

    entries = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()["entries"]
    nota = next(e for e in entries if e["kind"] == "note")
    assert nota["title"] == "Desconto aprovado"
    assert "10%" in nota["body"]


def test_nota_sem_titulo_e_rejeitada(client: TestClient, headers, contato):
    resp = client.post(f"/crm/clients/{contato}/notes", json={"title": "  "}, headers=headers)
    assert resp.status_code == 422


def test_timeline_de_contato_inexistente_da_404(client: TestClient, headers):
    assert client.get("/crm/clients/nao-existe/timeline", headers=headers).status_code == 404


def test_truncated_quando_passa_do_teto(client: TestClient, headers, contato):
    for i in range(101):
        client.post(
            f"/crm/clients/{contato}/notes", json={"title": f"nota {i}"}, headers=headers
        )
    corpo = client.get(f"/crm/clients/{contato}/timeline", headers=headers).json()
    assert corpo["truncated"] is True
    assert len(corpo["entries"]) == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_client_timeline.py -v`
Expected: FAIL — `404` em `/crm/clients/{id}/timeline` (rota não existe).

- [ ] **Step 3a: Write the read model**

Create `apps/api/app/modules/crm/timeline.py`:

```python
"""Read model da linha do tempo do contato.

Mescla DUAS fontes com contratos diferentes:

- **Persistida** — `client_events`: os fatos narrativos (chegou, voltou, moveu, decidiu).
- **Derivada** — `quotes` e `charges`: os fatos financeiros, lidos na ORIGEM.

O financeiro não é copiado para `client_events` de propósito. Guardar `amount_cents` em
segundo lugar criaria uma segunda versão da verdade sobre dinheiro — a forma exata do bug que
a Onda 0 do Epic 8 gastou uma onda inteira desfazendo. Ler da origem também traz de graça o
histórico RETROATIVO: contatos que já existiam mostram as cobranças de meses atrás sem
nenhuma migration de dados.

Fica fora de `service.py` porque é leitura cross-módulo (toca `receivables` e `quotes`), com
responsabilidade distinta das regras de escrita do CRM.
"""
from __future__ import annotations

from datetime import UTC, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.crm.models import ClientEvent
from app.modules.quotes.models import Quote
from app.modules.receivables.models import Charge

# Teto POR FONTE. A resposta declara `truncated` quando qualquer fonte bate nele — a tela
# avisa em vez de fingir que aquilo é tudo.
LIMITE_POR_FONTE = 100


def _brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _instante(valor: object) -> datetime:
    """Normaliza para datetime AWARE em UTC.

    `charges.due_date` é `Date` (data de negócio) e `paid_at`/`created_at` são `timestamptz`.
    Ordenar os dois juntos exige um tipo só; a data vira meia-noite UTC, mesma convenção dos
    eventos all-day da Agenda.
    """
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    return datetime.combine(valor, time.min, tzinfo=UTC)


def build(db: Session, *, client_id: str, limit: int = LIMITE_POR_FONTE) -> tuple[list[dict], bool]:
    """Devolve `(entradas_ordenadas, truncated)`. Mais recente primeiro."""
    truncated = False
    entradas: list[dict] = []

    eventos = list(
        db.scalars(
            select(ClientEvent)
            .where(ClientEvent.client_id == client_id)
            .order_by(ClientEvent.created_at.desc(), ClientEvent.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(eventos) > limit:
        truncated = True
        eventos = eventos[:limit]
    for e in eventos:
        entradas.append({
            "id": e.id, "kind": e.kind, "title": e.title, "body": e.body,
            "actor": e.actor, "is_ai": e.is_ai, "at": _instante(e.created_at),
        })

    cobrancas = list(
        db.scalars(
            select(Charge)
            .where(Charge.client_id == client_id)
            .order_by(Charge.created_at.desc(), Charge.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(cobrancas) > limit:
        truncated = True
        cobrancas = cobrancas[:limit]
    for c in cobrancas:
        if c.paid_at is not None:
            entradas.append({
                "id": f"charge:{c.id}:paid", "kind": "payment",
                "title": f"Pagamento recebido — {_brl(c.amount_cents)}",
                "body": c.description, "actor": "sistema", "is_ai": False,
                "at": _instante(c.paid_at),
            })
        entradas.append({
            "id": f"charge:{c.id}", "kind": "charge",
            "title": f"Cobrança de {_brl(c.amount_cents)} — vence {c.due_date:%d/%m/%Y}",
            "body": c.description, "actor": "sistema", "is_ai": False,
            "at": _instante(c.created_at),
        })

    orcamentos = list(
        db.scalars(
            select(Quote)
            .where(Quote.client_id == client_id)
            .order_by(Quote.created_at.desc(), Quote.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(orcamentos) > limit:
        truncated = True
        orcamentos = orcamentos[:limit]
    for q in orcamentos:
        entradas.append({
            "id": f"quote:{q.id}", "kind": "quote",
            "title": f"Orçamento “{q.title}” — {_brl(q.total_cents)} ({q.status})",
            "body": q.notes, "actor": "sistema", "is_ai": False,
            "at": _instante(q.created_at),
        })

    entradas.sort(key=lambda e: e["at"], reverse=True)
    if len(entradas) > limit:
        truncated = True
        entradas = entradas[:limit]
    return entradas, truncated
```

- [ ] **Step 3b: Schemas**

Em `apps/api/app/modules/crm/schemas.py`, acrescentar ao fim:

```python
# ── Linha do tempo do contato ──────────────────────────


class ClientTimelineEntry(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    actor: str
    is_ai: bool
    # `at`, e não `created_at`: para a cobrança paga o instante do fato é o `paid_at`. Um
    # nome só, um significado só, para as duas fontes poderem ser ordenadas juntas.
    at: datetime


class ClientTimelineOut(BaseModel):
    entries: list[ClientTimelineEntry]
    # `True` quando alguma fonte bateu no teto de 100. A tela avisa em vez de fingir que
    # aquilo é o histórico inteiro.
    truncated: bool


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    body: str = Field(default="", max_length=5000)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("a nota precisa de um título")
        return v
```

- [ ] **Step 3c: Rotas**

Em `apps/api/app/modules/crm/router.py`, acrescentar os imports (`ClientTimelineEntry`, `ClientTimelineOut`, `NoteCreate`, `from app.modules.crm import timeline`, `from app.modules.crm.models import KIND_NOTE`) e as rotas ao fim:

```python
# ── Linha do tempo ─────────────────────────────────────


@router.get("/clients/{client_id}/timeline", response_model=ClientTimelineOut)
def get_timeline(
    client_id: str,
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientTimelineOut:
    try:
        service.get_client(db, client_id)  # 404 fail-closed antes de montar qualquer coisa
    except service.CrmError as e:
        raise _err(e) from e
    entries, truncated = timeline.build(db, client_id=client_id)
    return ClientTimelineOut(
        entries=[ClientTimelineEntry(**e) for e in entries], truncated=truncated
    )


@router.post("/clients/{client_id}/notes", response_model=ClientTimelineEntry, status_code=201)
def create_note(
    client_id: str,
    data: NoteCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ClientTimelineEntry:
    try:
        service.get_client(db, client_id)
    except service.CrmError as e:
        raise _err(e) from e
    event = service.record_event(
        db, tenant_id=user.tenant_id, client_id=client_id, kind=KIND_NOTE,
        title=data.title, body=data.body, actor=user.user_id, is_ai=user.is_ai,
    )
    db.commit()
    db.refresh(event)
    return ClientTimelineEntry(
        id=event.id, kind=event.kind, title=event.title, body=event.body,
        actor=event.actor, is_ai=event.is_ai, at=event.created_at,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && pytest tests/test_client_timeline.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Lint and full backend suite**

Run: `cd apps/api && ruff check app/modules/crm/ && pytest -q`
Expected: sem erros de lint; suíte inteira verde.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/crm/timeline.py apps/api/app/modules/crm/schemas.py apps/api/app/modules/crm/router.py apps/api/tests/test_client_timeline.py
git commit -m "feat: endpoint de timeline do contato e nota de decisao"
```

---

### Task 10: `last_interaction_at` no board

**Files:**
- Modify: `apps/api/app/modules/crm/service.py`
- Modify: `apps/api/app/modules/crm/schemas.py`
- Modify: `apps/api/app/modules/crm/router.py:33-47`
- Test: `apps/api/tests/test_client_events.py` (modify — acrescentar casos)

**Interfaces:**
- Consumes: `ClientEvent` (Task 2).
- Produces:
  - `last_interaction_map(db) -> dict[str, datetime]` em `crm/service.py`.
  - Schema `BoardClient(ClientOut)` com `last_interaction_at: datetime | None`.
  - `BoardColumn.clients` passa a ser `list[BoardClient]`.

- [ ] **Step 1: Write the failing test**

Acrescentar a `apps/api/tests/test_client_events.py`:

```python
def test_board_traz_a_data_da_ultima_interacao(client: TestClient, headers):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    cols = client.get("/crm/board", headers=headers).json()["columns"]
    card = next(
        c for col in cols for c in col["clients"] if c["id"] == criado["id"]
    )
    # já existe o lead_created, então a data nunca vem vazia para contato criado pelo app
    assert card["last_interaction_at"] is not None


def test_data_da_ultima_interacao_avanca_com_o_movimento(client: TestClient, headers):
    criado = client.post("/crm/clients", json={"name": "Flavio Kato"}, headers=headers).json()
    antes = next(
        c for col in client.get("/crm/board", headers=headers).json()["columns"]
        for c in col["clients"] if c["id"] == criado["id"]
    )["last_interaction_at"]

    cols = client.get("/crm/board", headers=headers).json()["columns"]
    proposta = next(c["stage"] for c in cols if c["stage"]["name"] == "Proposta")
    client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": proposta["id"]}, headers=headers
    )

    depois = next(
        c for col in client.get("/crm/board", headers=headers).json()["columns"]
        for c in col["clients"] if c["id"] == criado["id"]
    )["last_interaction_at"]
    assert depois >= antes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && pytest tests/test_client_events.py -k ultima_interacao -v`
Expected: FAIL — `KeyError: 'last_interaction_at'`

- [ ] **Step 3a: `service.last_interaction_map`**

Em `apps/api/app/modules/crm/service.py`, acrescentar:

```python
def last_interaction_map(db: Session) -> dict[str, datetime]:
    """Data da última interação por contato, para o card do Kanban.

    Duas consultas AGRUPADAS para o board inteiro, em vez de uma coluna
    `clients.last_interaction_at`. Coluna seria um valor derivado guardado — a forma exata do
    bug que a Onda 0 do Epic 8 corrigiu — e dessincronizaria no primeiro caminho de escrita
    que alguém esquecesse de atualizar. Assim é correto por construção.

    A sessão já está isolada por tenant (RLS): nada de filtro manual de `tenant_id`.
    """
    ultimo: dict[str, datetime] = {}
    for tabela, coluna in (
        (ClientEvent, ClientEvent.client_id),
        (WhatsappMessage, WhatsappMessage.client_id),
    ):
        linhas = db.execute(
            select(coluna, func.max(tabela.created_at))
            .where(coluna.is_not(None))
            .group_by(coluna)
        ).all()
        for client_id, quando in linhas:
            if quando is None:
                continue
            atual = ultimo.get(client_id)
            if atual is None or quando > atual:
                ultimo[client_id] = quando
    return ultimo
```

Adicionar aos imports do arquivo: `from datetime import datetime` e
`from app.modules.whatsapp_inbox.models import WhatsappMessage`.

**Atenção ao ciclo de import:** `whatsapp_inbox/service.py` já importa de `crm`. Importar
`whatsapp_inbox.models` (só o modelo, não o service) em `crm/service.py` não fecha ciclo —
`models.py` do inbox não importa nada de `crm`. Confirme rodando
`cd apps/api && python -c "import app.main"` no Step 4; se acusar ciclo, mova o import para
dentro da função.

- [ ] **Step 3b: Schema**

Em `apps/api/app/modules/crm/schemas.py`, logo depois de `ClientOut`:

```python
class BoardClient(ClientOut):
    """`ClientOut` + a data da última interação.

    Campo separado do `ClientOut` de propósito: só o board calcula isso (via duas consultas
    agrupadas). Se `last_interaction_at` vivesse em `ClientOut`, todo endpoint que devolve
    cliente passaria a afirmar `null` — e `null` significaria tanto "sem interação" quanto
    "não calculei", que são coisas diferentes.
    """

    last_interaction_at: datetime | None = None
```

E trocar `BoardColumn`:

```python
class BoardColumn(BaseModel):
    stage: StageOut
    clients: list[BoardClient]
```

- [ ] **Step 3c: Router**

Em `apps/api/app/modules/crm/router.py`, trocar `get_board`:

```python
@router.get("/board", response_model=Board)
def get_board(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Board:
    columns = service.build_board(db, user.tenant_id)
    ultimo = service.last_interaction_map(db)
    return Board(
        columns=[
            BoardColumn(
                stage=StageOut.model_validate(stage),
                clients=[
                    BoardClient(
                        **ClientOut.model_validate(c).model_dump(),
                        last_interaction_at=ultimo.get(c.id),
                    )
                    for c in clients
                ],
            )
            for stage, clients in columns
        ]
    )
```

Trocar o import de `BoardColumn` para incluir `BoardClient`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && python -c "import app.main" && pytest tests/test_client_events.py tests/test_crm.py -v`
Expected: import sem erro de ciclo; testes PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/crm/service.py apps/api/app/modules/crm/schemas.py apps/api/app/modules/crm/router.py apps/api/tests/test_client_events.py
git commit -m "feat: card do Kanban mostra a data da ultima interacao"
```

---

### Task 11: Tipos compartilhados + componente `<ClientTimeline>`

**Files:**
- Modify: `packages/shared-types/src/index.ts`
- Create: `apps/web/src/features/crm/ClientTimeline.tsx`
- Test: `apps/web/src/features/crm/ClientTimeline.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /crm/clients/{id}/timeline`, `POST /crm/clients/{id}/notes` (Task 9).
- Produces:
  - TS: `ClientTimelineEntry`, `ClientTimelineOut`, `BoardClient`.
  - React: `export default function ClientTimeline({ clientId }: { clientId: string })`.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/features/crm/ClientTimeline.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ClientTimeline from "./ClientTimeline";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

const ENTRADA = {
  id: "1", kind: "lead_created", title: "Chegou pelo site", body: "",
  actor: "pagina:lead", is_ai: false, at: "2026-07-01T10:00:00Z",
};
const RETORNO = {
  id: "2", kind: "lead_return", title: "Voltou pelo site",
  body: "Quero orcamento para 50 convidados",
  actor: "pagina:lead", is_ai: false, at: "2026-08-04T14:32:00Z",
};

describe("ClientTimeline", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mostra as entradas da mais recente para a mais antiga", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [RETORNO, ENTRADA], truncated: false },
    } as never);

    render(<ClientTimeline clientId="c1" />);

    const titulos = await screen.findAllByTestId("timeline-title");
    expect(titulos.map((t) => t.textContent)).toEqual([
      "Voltou pelo site", "Chegou pelo site",
    ]);
  });

  it("mostra o texto que a pessoa preencheu no retorno", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [RETORNO], truncated: false },
    } as never);

    render(<ClientTimeline clientId="c1" />);
    expect(await screen.findByText(/50 convidados/)).toBeInTheDocument();
  });

  it("avisa quando o historico foi cortado, em vez de fingir que aquilo e tudo", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [ENTRADA], truncated: true },
    } as never);

    render(<ClientTimeline clientId="c1" />);
    expect(await screen.findByText(/mais recentes/i)).toBeInTheDocument();
  });

  it("grava a nota e recarrega a timeline", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [ENTRADA], truncated: false },
    } as never);
    vi.mocked(api.post).mockResolvedValue({ data: { ...ENTRADA, id: "3" } } as never);

    render(<ClientTimeline clientId="c1" />);
    await screen.findAllByTestId("timeline-title");

    await userEvent.type(screen.getByPlaceholderText(/decis/i), "Fechamos com 10%");
    await userEvent.click(screen.getByRole("button", { name: /registrar/i }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/crm/clients/c1/notes", {
        title: "Fechamos com 10%",
        body: "",
      }),
    );
    expect(api.get).toHaveBeenCalledTimes(2);  // recarrega depois de gravar
  });

  it("estado vazio nao aparece como erro", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [], truncated: false },
    } as never);

    render(<ClientTimeline clientId="c1" />);
    expect(await screen.findByText(/nenhum registro/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @e1p/web test -- ClientTimeline`
Expected: FAIL — não resolve `./ClientTimeline`.

- [ ] **Step 3a: Tipos compartilhados**

Em `packages/shared-types/src/index.ts`, acrescentar perto de `Client`:

```ts
export interface ClientTimelineEntry {
  id: string;
  kind:
    | "lead_created" | "lead_return" | "stage_move" | "reopened" | "note" | "funnel"
    | "quote" | "charge" | "payment";
  title: string;
  body: string;
  actor: string;
  is_ai: boolean;
  /** O instante do fato: `created_at` do evento, ou `paid_at` da cobrança. */
  at: string;
}

export interface ClientTimelineOut {
  entries: ClientTimelineEntry[];
  /** `true` quando alguma fonte bateu no teto de 100 — a tela avisa. */
  truncated: boolean;
}

/** `Client` do board, com a data da última interação (só o board calcula isso). */
export interface BoardClient extends Client {
  last_interaction_at: string | null;
}
```

- [ ] **Step 3b: Componente**

Create `apps/web/src/features/crm/ClientTimeline.tsx`:

```tsx
import type { ClientTimelineEntry, ClientTimelineOut } from "@e1p/shared-types";
import {
  ArrowRightLeft, FileText, MessageSquarePlus, Receipt, RotateCcw,
  Sparkles, UserPlus, Workflow,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

/** Ícone e cor por tipo de fato. Um `kind` novo vindo de um backend mais recente cai no
 *  neutro em vez de sumir da tela. */
const APARENCIA: Record<string, { icon: JSX.Element; cor: string }> = {
  lead_created: { icon: <UserPlus size={14} />, cor: "bg-primary-50 text-primary-700" },
  lead_return: { icon: <RotateCcw size={14} />, cor: "bg-primary-50 text-primary-700" },
  stage_move: { icon: <ArrowRightLeft size={14} />, cor: "bg-neutral-100 text-neutral-600" },
  reopened: { icon: <RotateCcw size={14} />, cor: "bg-amber-50 text-amber-700" },
  note: { icon: <MessageSquarePlus size={14} />, cor: "bg-emerald-50 text-emerald-700" },
  funnel: { icon: <Workflow size={14} />, cor: "bg-neutral-100 text-neutral-600" },
  quote: { icon: <FileText size={14} />, cor: "bg-sky-50 text-sky-700" },
  charge: { icon: <Receipt size={14} />, cor: "bg-sky-50 text-sky-700" },
  payment: { icon: <Receipt size={14} />, cor: "bg-emerald-50 text-emerald-700" },
};

const NEUTRO = { icon: <Sparkles size={14} />, cor: "bg-neutral-100 text-neutral-600" };

/** `at` é um INSTANTE (timestamptz), não uma data de negócio — formata no fuso local, mesma
 *  convenção da ConversasPage (e o oposto da regra all-day da Agenda). */
const quando = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

export default function ClientTimeline({ clientId }: { clientId: string }) {
  const [entries, setEntries] = useState<ClientTimelineEntry[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [nota, setNota] = useState("");
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get<ClientTimelineOut>(`/crm/clients/${clientId}/timeline`);
    setEntries(data.entries);
    setTruncated(data.truncated);
  }, [clientId]);

  useEffect(() => {
    load();
  }, [load]);

  async function registrar() {
    const titulo = nota.trim();
    if (!titulo) return;
    setSalvando(true);
    setErro("");
    try {
      await api.post(`/crm/clients/${clientId}/notes`, { title: titulo, body: "" });
      setNota("");
      await load();
    } catch (e) {
      setErro(apiErrorMessage(e));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex gap-2">
        <input
          value={nota}
          onChange={(e) => setNota(e.target.value)}
          placeholder="Registrar uma decisão..."
          className="min-w-0 flex-1 rounded-xl border border-neutral-200 px-3 py-2 text-sm"
        />
        <button
          onClick={registrar}
          disabled={salvando || !nota.trim()}
          className="shrink-0 rounded-xl bg-primary-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          Registrar
        </button>
      </div>
      {erro && <p className="text-sm text-rose-600">{erro}</p>}

      {truncated && (
        <p className="text-[11px] text-neutral-400">
          Mostrando os 100 registros mais recentes.
        </p>
      )}

      {entries.length === 0 ? (
        <p className="text-sm text-neutral-400">Nenhum registro ainda.</p>
      ) : (
        <ol className="flex flex-col gap-3 overflow-y-auto">
          {entries.map((e) => {
            const look = APARENCIA[e.kind] ?? NEUTRO;
            return (
              <li key={e.id} className="flex gap-2">
                <span className={`mt-0.5 shrink-0 rounded-lg p-1.5 ${look.cor}`}>
                  {look.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <p
                    data-testid="timeline-title"
                    className="text-sm font-medium text-neutral-800"
                  >
                    {e.title}
                  </p>
                  {e.body && (
                    <p className="whitespace-pre-wrap text-sm text-neutral-600">{e.body}</p>
                  )}
                  <p className="text-[11px] text-neutral-400">
                    {quando(e.at)}
                    {e.is_ai && " · IA"}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter @e1p/web test -- ClientTimeline`
Expected: PASS (5 testes)

- [ ] **Step 5: Typecheck**

Run: `pnpm --filter @e1p/web typecheck`
Expected: sem erros.

- [ ] **Step 6: Commit**

```bash
git add packages/shared-types/src/index.ts apps/web/src/features/crm/ClientTimeline.tsx apps/web/src/features/crm/ClientTimeline.test.tsx
git commit -m "feat: componente da linha do tempo do contato"
```

---

### Task 12: Timeline na ficha 360° e data no card do Kanban

**Files:**
- Modify: `apps/web/src/features/crm/ClientDetailPage.tsx:107-108`
- Modify: `apps/web/src/features/crm/CrmPage.tsx:180-215`
- Test: `apps/web/src/features/crm/CrmPage.test.tsx` (modify)

**Interfaces:**
- Consumes: `<ClientTimeline>` (Task 11), `BoardClient.last_interaction_at` (Tasks 10 e 11).
- Produces: nada consumido adiante.

- [ ] **Step 1: Write the failing test**

Acrescentar a `apps/web/src/features/crm/CrmPage.test.tsx`, reaproveitando o helper `renderPage()` e o `vi.mock` de `../../lib/api` que já existem no arquivo (o `beforeEach` atual devolve `{ columns: [] }` para `/crm/board`; cada teste abaixo sobrescreve esse mock):

```tsx
/** Board com um card só, para exercitar a linha da última interação. */
function boardComCard(lastInteractionAt: string | null) {
  return {
    columns: [
      {
        stage: {
          id: "s1", name: "Entrada", position: 0,
          is_won: false, is_lost: false, is_archived: false,
        },
        clients: [
          {
            id: "c1", tenant_id: "t1", name: "Flavio Kato", email: null, phone: null,
            document: null, gender: "unspecified", birthdate: null, notes: "",
            tags: [], source: "landing", stage_id: "s1",
            created_at: "2026-07-01T10:00:00Z",
            last_interaction_at: lastInteractionAt,
          },
        ],
      },
    ],
  };
}

function mockarBoard(lastInteractionAt: string | null) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/crm/board") {
      return Promise.resolve({ data: boardComCard(lastInteractionAt) } as never);
    }
    return Promise.resolve({ data: [] } as never);
  });
}

describe("CrmPage — última interação no card", () => {
  it("mostra a data quando o contato já teve interação", async () => {
    mockarBoard("2026-08-04T14:32:00Z");
    renderPage();
    expect(await screen.findByText(/última interação: 04\/08/i)).toBeInTheDocument();
  });

  it("card sem interação nenhuma não mostra rótulo vazio", async () => {
    mockarBoard(null);
    renderPage();
    await screen.findByText("Flavio Kato");
    expect(screen.queryByText(/última interação/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @e1p/web test -- CrmPage`
Expected: FAIL — texto "última interação" não existe na tela.

- [ ] **Step 3a: Card do Kanban**

Em `apps/web/src/features/crm/CrmPage.tsx`, trocar o tipo do card e acrescentar a linha da data. A assinatura vira `function Card({ client, stageId }: { client: BoardClient; stageId: string })` (import de `BoardClient` em vez de `Client` onde o board é tipado), e dentro do `<div className="min-w-0 flex-1">`, logo depois das tags:

```tsx
        {client.last_interaction_at && (
          <p className="mt-1 text-[10px] text-neutral-400">
            última interação:{" "}
            {new Date(client.last_interaction_at).toLocaleDateString("pt-BR", {
              day: "2-digit",
              month: "2-digit",
            })}
          </p>
        )}
```

- [ ] **Step 3b: Ficha 360°**

Em `apps/web/src/features/crm/ClientDetailPage.tsx`, importar o componente e o ícone:

```tsx
import { History } from "lucide-react";
import ClientTimeline from "./ClientTimeline";
```

E inserir, **imediatamente antes** do bloco `{/* Cobranças */}` da linha 107:

```tsx
      {/* Histórico — primeiro bloco de propósito: é a história que dá sentido às seções
          operacionais abaixo (Cobranças, Contratos, Orçamentos). */}
      <Section icon={<History size={16} />} title="Histórico">
        <ClientTimeline clientId={id} />
      </Section>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter @e1p/web test -- CrmPage && pnpm --filter @e1p/web typecheck`
Expected: PASS; typecheck limpo.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/crm/CrmPage.tsx apps/web/src/features/crm/CrmPage.test.tsx apps/web/src/features/crm/ClientDetailPage.tsx
git commit -m "feat: historico na ficha 360 e data da ultima interacao no card"
```

---

### Task 13: Painel de histórico na tela de Conversas

**Files:**
- Modify: `apps/web/src/features/conversas/ConversasPage.tsx`
- Test: `apps/web/src/features/conversas/ConversasPage.test.tsx` (modify)

**Interfaces:**
- Consumes: `<ClientTimeline>` (Task 11); `ConversationSummary.client_id` e `.kind` (já existentes).
- Produces: nada consumido adiante. Última tarefa.

**Requisito responsivo (não é opcional):** abaixo do breakpoint `lg` o painel **não é coluna** — é uma gaveta sobreposta ao thread, aberta por um botão no cabeçalho da conversa e fechada ao trocar de conversa. Uma terceira coluna fixa de ~320px num aparelho de 360px repete o incidente do PR #56, em que o `AppShell` sem breakpoint escondeu o checkbox "marcar como paga" e uma conta real foi baixada sem o dono ver.

- [ ] **Step 1: Write the failing test**

Acrescentar a `apps/web/src/features/conversas/ConversasPage.test.tsx`, reaproveitando o `vi.mock` de `../../lib/api` que já existe no topo do arquivo. Acrescente `fireEvent` ao import de `@testing-library/react`:

```tsx
const CONVERSA_DIRETA = {
  chat_id: "c1", kind: "direct" as const, title: "Flavio Kato", phone: "5511999998888",
  client_id: "cli1", last_message_at: "2026-08-04T10:00:00Z",
  last_message_preview: "Oi", unread: false,
};

const GRUPO = {
  chat_id: "g1", kind: "group" as const, title: "Turma 2026", phone: null,
  client_id: null, last_message_at: "2026-08-04T10:00:00Z",
  last_message_preview: "Bom dia", unread: false,
};

const TIMELINE_DO_CRM = {
  entries: [
    {
      id: "e1", kind: "lead_created", title: "Chegou pelo site", body: "",
      actor: "pagina:lead", is_ai: false, at: "2026-07-01T10:00:00Z",
    },
  ],
  truncated: false,
};

function mockarConversas(conversas: unknown[]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/whatsapp-conversations") {
      return Promise.resolve({ data: conversas } as never);
    }
    if (url.startsWith("/crm/clients/")) {
      return Promise.resolve({ data: TIMELINE_DO_CRM } as never);
    }
    if (url.endsWith("/window")) {
      return Promise.resolve({ data: { within_session_window: true } } as never);
    }
    return Promise.resolve({ data: [] } as never);
  });
}

describe("ConversasPage — painel de histórico", () => {
  it("conversa direta com contato mostra o histórico do CRM", async () => {
    mockarConversas([CONVERSA_DIRETA]);
    render(<ConversasPage />);
    await userEvent.click(await screen.findByText("Flavio Kato"));

    expect(await screen.findByTestId("painel-historico")).toBeInTheDocument();
    expect(await screen.findByText("Chegou pelo site")).toBeInTheDocument();
  });

  it("conversa de grupo diz em TEXTO que não há contato ligado", async () => {
    mockarConversas([GRUPO]);
    render(<ConversasPage />);
    await userEvent.click(await screen.findByText("Turma 2026"));

    expect(
      await screen.findByText(/não está ligada a um contato do CRM/i),
    ).toBeInTheDocument();
  });

  it("o histórico NÃO entra no polling de 7s", async () => {
    // `fireEvent` em vez de `userEvent` aqui de propósito: userEvent com fake timers exige
    // configuração de `advanceTimers` e falha de forma confusa sem ela.
    vi.useFakeTimers();
    mockarConversas([CONVERSA_DIRETA]);
    render(<ConversasPage />);
    await vi.advanceTimersByTimeAsync(0);      // resolve a carga inicial das conversas
    fireEvent.click(screen.getByText("Flavio Kato"));
    await vi.advanceTimersByTimeAsync(0);      // resolve a carga da timeline

    const chamadasDeTimeline = () =>
      vi.mocked(api.get).mock.calls.filter(([u]) =>
        String(u).startsWith("/crm/clients/"),
      ).length;

    const antes = chamadasDeTimeline();
    expect(antes).toBeGreaterThan(0);          // controle positivo: carregou uma vez

    await vi.advanceTimersByTimeAsync(21_000); // 3 ciclos de POLL_MS
    expect(chamadasDeTimeline()).toBe(antes);
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @e1p/web test -- ConversasPage`
Expected: FAIL — `painel-historico` não existe.

- [ ] **Step 3: Write minimal implementation**

Em `apps/web/src/features/conversas/ConversasPage.tsx`:

Importar o componente e o ícone da gaveta:

```tsx
import { History, Paperclip, Send, Users, X } from "lucide-react";
import ClientTimeline from "../crm/ClientTimeline";
```

Acrescentar estado da gaveta ao componente:

```tsx
  const [historicoAberto, setHistoricoAberto] = useState(false);
```

Fechar a gaveta ao trocar de conversa — junto do `setSelected` de cada botão da lista:

```tsx
              onClick={() => {
                setSelected(c.chat_id);
                setHistoricoAberto(false);
              }}
```

Acrescentar, ao lado do thread, o painel. `conversaSelecionada` é o item de `conversations` cujo `chat_id === selected`:

```tsx
      {/* Histórico do contato.
          Em `lg+` é a terceira coluna. ABAIXO de `lg` é uma GAVETA sobreposta: uma coluna
          fixa de ~320px num aparelho de 360px repete o incidente do PR #56 (AppShell sem
          breakpoint escondeu o checkbox "marcar como paga" e uma conta real foi baixada sem
          o dono ver). */}
      {selected && (
        <>
          <button
            onClick={() => setHistoricoAberto(true)}
            className="fixed bottom-4 right-4 z-20 rounded-full bg-primary-600 p-3 text-white shadow-lg lg:hidden"
            aria-label="Abrir histórico do contato"
          >
            <History size={18} />
          </button>

          {historicoAberto && (
            <div
              className="fixed inset-0 z-20 bg-neutral-900/30 lg:hidden"
              onClick={() => setHistoricoAberto(false)}
            />
          )}

          <aside
            data-testid="painel-historico"
            className={`z-30 shrink-0 overflow-y-auto rounded-2xl bg-white p-4 shadow-sm ${
              historicoAberto
                ? "fixed inset-y-0 right-0 w-80 max-w-[85vw] lg:static lg:max-w-none"
                : "hidden lg:block lg:w-80"
            }`}
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-semibold text-neutral-800">Histórico</h2>
              <button
                onClick={() => setHistoricoAberto(false)}
                className="text-neutral-400 lg:hidden"
                aria-label="Fechar histórico"
              >
                <X size={16} />
              </button>
            </div>
            {conversaSelecionada?.client_id ? (
              <ClientTimeline clientId={conversaSelecionada.client_id} />
            ) : (
              // Grupo NÃO vira contato do CRM (decisão do fundador, 2026-08-04). Dizer isso
              // em TEXTO, em vez de aparecer vazio como se não houvesse nada.
              <p className="text-sm text-neutral-400">
                {conversaSelecionada?.kind === "group"
                  ? "Conversa de grupo — não está ligada a um contato do CRM."
                  : "Esta conversa não está ligada a um contato do CRM."}
              </p>
            )}
          </aside>
        </>
      )}
```

Derive `conversaSelecionada` logo antes do `return`:

```tsx
  const conversaSelecionada = conversations.find((c) => c.chat_id === selected) ?? null;
```

**O `<ClientTimeline>` já carrega sozinho** (`useEffect` no `clientId`) e **não** é chamado pelo `setInterval` de `POLL_MS` — o polling de 7s continua tocando só `loadConversations`. Não acrescente a timeline àquele ciclo.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter @e1p/web test -- ConversasPage && pnpm --filter @e1p/web typecheck`
Expected: PASS; typecheck limpo.

- [ ] **Step 5: Manual acceptance at ~360px**

Abra a app (`pnpm --filter @e1p/web dev`, http://127.0.0.1:5173), entre em Conversas, e no DevTools force uma largura de **360px**. Confirme:

1. O painel **não** aparece como terceira coluna espremendo o thread.
2. O botão flutuante de histórico está visível e alcançável.
3. A gaveta abre sobreposta, com o botão de fechar dentro da área visível.
4. Trocar de conversa fecha a gaveta.
5. Nenhum controle do thread (campo de mensagem, botão de enviar, anexo) fica fora da tela com a gaveta fechada.

Este passo é aceite obrigatório e não tem substituto automatizado — é exatamente onde o PR #56 doeu.

- [ ] **Step 6: Full suite**

Run: `cd apps/api && pytest -q` e `pnpm --filter @e1p/web test`
Expected: ambas verdes.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/conversas/ConversasPage.tsx apps/web/src/features/conversas/ConversasPage.test.tsx
git commit -m "feat: painel de historico do contato na tela de Conversas"
```

---

### Task 14: Registrar no CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: tudo que as Tasks 1–13 construíram.
- Produces: nada. É o fechamento exigido pela seção "Consequências para o CLAUDE.md" da spec.

- [ ] **Step 1: Write the section**

Acrescentar ao `CLAUDE.md`, depois da seção "WhatsApp Evolution: em produção de verdade":

```markdown
## CRM: a jornada única do contato (um card por pessoa)

> Spec: `docs/superpowers/specs/2026-08-04-crm-jornada-unica-do-contato-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-04-crm-jornada-unica-do-contato.md`

O mesmo contato virava vários cards no Kanban (quatro "Flavio Kato" na tela do fundador):
`pages/service.py::public_submit` e `integrations/service.py::capture_lead` chamavam
`create_client` incondicionalmente. O WhatsApp já deduplicava — por telefone cru —, então o
comportamento era incoerente por porta de entrada.

- [x] **Porta única `crm_service.absorb_lead`** — as três portas (página pública, API de
  integração, WhatsApp) convergem nela. Identidade: **telefone normalizado primeiro, e-mail em
  segundo**. Quem já existe é COMPLEMENTADO (campos vazios preenchidos, nunca sobrescritos) e
  ganha um `lead_return` com a data e o texto daquele envio. `notes` do dono não é tocado no
  retorno — era exatamente o que apagava o que ele tinha escrito.
- [x] **`core/phone.normalize_br` + `clients.phone_key`** (migration 0067) — `phone` guarda o
  que a pessoa digitou, `phone_key` a forma comparável. **A regra do 9º dígito por faixa da
  Anatel** (local de 8 dígitos começando em 6–9 é celular e ganha o 9; 2–5 é fixo e não ganha)
  é o que impede o fixo `11 3333-4444` de colidir com o celular `11 93333-4444` — a alternativa
  "compara os últimos 8 dígitos" juntaria duas pessoas num card só.
- [x] **`phone_key` NÃO é único, de propósito** — marido e mulher compartilham telefone, e os
  duplicados legados (não mesclados, decisão do fundador) compartilham chave depois do
  backfill. `absorb_lead` desempata pelo **mais antigo** (`created_at ASC, id`); sem isso o
  próximo retorno cairia num card imprevisível e a história se partiria.
- [x] **Reabertura** — retorno em coluna terminal (`is_won` **ou** `is_lost`) move o card para
  a primeira coluna ativa e grava `reopened`. Coluna do meio **não** se move (puxar de volta
  apagaria trabalho em andamento). Ganho reabre porque lead recorrente querendo comprar de
  novo é oportunidade nova (decisão do fundador).
- [x] **`client_events`** — a linha do tempo NARRATIVA (`lead_created`, `lead_return`,
  `stage_move`, `reopened`, `note`, `funnel`). **Dinheiro não entra aqui:** orçamento, cobrança
  e pagamento continuam sendo lidos de `quotes`/`charges` por `crm/timeline.py`. Copiar
  `amount_cents` criaria uma segunda versão da verdade sobre dinheiro — a forma exata do bug
  que a Onda 0 do Epic 8 desfez. Ler da origem também deu o histórico financeiro
  **retroativo** de graça. `title`/`body` são texto CONGELADO (renomear a coluna do Kanban não
  reescreve o passado), no princípio do `raw_description` de `bank_transactions`.
- [x] **Reinscrição no funil** — `crm.client.returned` reinscreve no funil de entrada, com
  guarda de jornada `running`/`waiting` em `automation.py` (não dentro de `engine.enroll`:
  inscrição manual pela tela continua fazendo o que o usuário mandar).
- [x] **Superfícies** — `<ClientTimeline>` na ficha 360° (primeira `<Section>`) e como painel
  direito de Conversas (**gaveta sobreposta abaixo de `lg`**, pela lição do PR #56). Card do
  Kanban mostra "última interação", calculada por **duas consultas agrupadas** no endpoint do
  board — nunca uma coluna `last_interaction_at`, que seria valor derivado guardado.
- **Grupo de WhatsApp não tem histórico de CRM** — `client_id` é nulo e o painel diz isso em
  texto, mantendo a decisão de 2026-08-04 de que grupo não vira contato.

**Dívida:** os cards duplicados que já existiam **não foram mesclados** (decisão do fundador:
a correção vale daqui para frente) — quem for mesclá-los depois precisa juntar `client_events`,
`charges`, `quotes`, `contracts` e `whatsapp_chats` do card absorvido, e não só apagar a linha.
Não há ferramenta de mescla na tela. Também não há "ligar conversa não identificada a um
contato" nem marcação de histórico como lido.
```

- [ ] **Step 2: Verify the whole suite one last time**

Run: `cd apps/api && pytest -q` e `pnpm --filter @e1p/web test` e `pnpm --filter @e1p/web typecheck`
Expected: tudo verde.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: registra a jornada unica do contato no CRM"
```

---

## Notas de execução

- **Ordem das tarefas é dependência real**, não preferência: 1 → 2 → 3 → 4 alimentam a base;
  5 → 6 → 7 → 8 constroem a escrita; 9 → 10 a leitura; 11 → 12 → 13 as telas; 14 fecha.
- **Task 4 exige Docker rodando** (testcontainers). Se não houver Docker no ambiente do
  executor, a tarefa deve ser marcada como bloqueada e **relatada explicitamente** — não
  pulada em silêncio. Ela é o único gate que prova que o backfill não é no-op.
- **Task 13 Step 5 é aceite manual** e também não pode ser pulado em silêncio.
- `main` é protegida (4 checks obrigatórios): abrir PR ao fim, não fazer push direto.
