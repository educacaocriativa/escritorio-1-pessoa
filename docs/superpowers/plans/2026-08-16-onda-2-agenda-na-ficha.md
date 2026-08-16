# Onda 2 — Agenda na ficha do contato: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um compromisso da Agenda passa a saber de que contato é. A ficha 360° mostra os próximos compromissos daquele contato e permite marcar um novo dali mesmo; o card do Kanban diz qual é o próximo passo — ou avisa que não há nenhum.

**Architecture:** Coluna nova `agenda_events.client_id` (nullable, indexada, sem FK) com backfill retroativo a partir das cobranças. Cada módulo continua dono do seu dado: a Agenda expõe filtro e agregado, o CRM consome. O modal de criação não é reescrito — é extraído do `AgendaPage` e passa a aceitar `clientId`, para a checagem de conflito continuar existindo em um lugar só.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Pydantic (Python 3.12); React + TypeScript + Vite + Tailwind; pytest (API, SQLite + testcontainers/Postgres para RLS), Vitest + Testing Library (web), Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-08-16-crm-conversa-e-agenda-na-ficha-design.md` — seção "Onda 2".

## Global Constraints

- **Worktree:** `F:/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/onda-2-agenda`, branch `feat/onda-2-agenda-na-ficha`. Existe um checkout irmão em `F:/Projetos/e1p/escritorio-1-pessoa` (sem `.claude/worktrees/...`) — **nunca** edite nem commite lá.
- **Nunca commitar em `main`; nunca `git push`; nunca `gh pr create`.** São exclusivos do @devops.
- **Rodar tudo em primeiro plano.** Nunca em background, nunca com monitor, nunca poll. Dois implementadores da Onda 1 perderam o turno assim.
- **Fuso:** todo instante exibido usa o fuso do TENANT — `useFuso()` + `lib/datetime` no front, `tenant_timezone(db)` no back. `toLocaleString` sem `timeZone` é regressão conhecida.
- **Dinheiro em centavos inteiros.** Nunca float.
- **Comentário em português**, explicando o *porquê*.
- **`ruff check .` é gate de CI** (`.github/workflows/ci.yml:47` roda `ruff check . && pytest` dentro da imagem) — lint quebrado derruba o build antes de qualquer teste. Limite de 100 colunas.
- Rede sempre mockada em teste de web.

**Comandos (verificados neste worktree):**

```bash
# API — cwd no apps/api DO WORKTREE, interpretador do checkout principal
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/onda-2-agenda/apps/api
/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .
TZ=UTC /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -q     # ~8min
# Testes de RLS/migration (Docker 29.6.1 disponível; roda em ~10s)
/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -m rls_e2e -q

# Web — da raiz do worktree
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/onda-2-agenda
pnpm --filter @e1p/web test && pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
pnpm --filter @e1p/web e2e
```

> ⚠️ `pytest -q` **exclui** o marcador `rls_e2e` no CI (`-m 'not rls_e2e'`) e o teste da migration vive nele. Rodar só `pytest -q` **não** exercita o backfill. Toda tarefa que toca a migration roda os dois.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `apps/api/migrations/versions/0078_agenda_event_client.py` | Coluna + backfill sob janela de RLS | Criar |
| `apps/api/tests/test_migration_0078_agenda_client_rls.py` | Prova que o backfill não é no-op | Criar |
| `apps/api/app/modules/agenda/models.py` | `client_id` | Modificar |
| `apps/api/app/modules/agenda/schemas.py` | `client_id` em Create/Update/Out | Modificar |
| `apps/api/app/modules/agenda/service.py` | Grava `client_id`; `next_event_map` | Modificar |
| `apps/api/app/modules/agenda/router.py` | Filtro `client_id`; limpeza do `_events_out` | Modificar |
| `apps/api/app/modules/receivables/service.py` | Passa a gravar `client_id` no evento | Modificar |
| `apps/api/app/modules/crm/timeline.py` | 4ª fonte: compromissos realizados | Modificar |
| `apps/api/app/modules/crm/router.py` | Board consome `next_event_map` | Modificar |
| `apps/api/app/modules/crm/schemas.py` | `next_event_at` / `next_event_title` | Modificar |
| `packages/shared-types/src/index.ts` | Espelho dos campos novos | Modificar |
| `apps/web/src/features/agenda/NewEventModal.tsx` | Modal extraído, aceita `clientId` | Criar |
| `apps/web/src/features/agenda/AgendaPage.tsx` | Passa a importar o modal | Modificar |
| `apps/web/src/features/crm/BlocoDaAgenda.tsx` | Próximos compromissos + "Marcar" | Criar |
| `apps/web/src/features/crm/ClientDetailPage.tsx` | Hospeda o bloco | Modificar |
| `apps/web/src/features/crm/ClientTimeline.tsx` | Fuso do tenant + `kind: agenda` | Modificar |
| `apps/web/src/features/crm/CrmPage.tsx` | Linha do próximo passo | Modificar |
| `apps/web/e2e/ficha-agenda-360.spec.ts` | Régua | Criar |

**Ordem e dependências:** T1 → T2 → T3 (a limpeza exige o backfill provado). T2 → T7, T8. T6 → T7. T4+T5 tocam os mesmos dois arquivos e vão juntas.

**Antes de começar:**

```bash
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/onda-2-agenda
git branch --show-current   # deve imprimir feat/onda-2-agenda-na-ficha
```

---

### Task 1: Migration 0078 — a coluna e o passado

**Files:**
- Create: `apps/api/migrations/versions/0078_agenda_event_client.py`
- Create: `apps/api/tests/test_migration_0078_agenda_client_rls.py`
- Modify: `apps/api/app/modules/agenda/models.py`

**Interfaces:**
- Produces: `AgendaEvent.client_id: str | None` (indexado, sem FK). Consumido por todas as tarefas seguintes.

- [ ] **Step 1: Escrever o teste da migration (vai falhar)**

Crie `apps/api/tests/test_migration_0078_agenda_client_rls.py`. Ele segue a estrutura de `test_migration_0068_stage_order_rls.py` — **leia aquele arquivo primeiro** e reuse os helpers `_bootstrap_rls_role` e `_run_migrations_as_app` copiando-os (são módulos de teste independentes; a duplicação é a convenção existente).

```python
"""Migration 0078 (backfill de `agenda_events.client_id`) sob RLS REAL.

O fato que a suíte SQLite é estruturalmente incapaz de provar: **o backfill não é no-op.**
`agenda_events` e `charges` têm FORCE ROW LEVEL SECURITY e a migration roda como o papel
não-superusuário `e1p_app` sem GUC de tenant. Sem a janela de DISABLE/ENABLE o UPDATE
afetaria zero linhas SEM ERRO NENHUM — e o sintoma em produção não seria falha de deploy,
seria "a ficha do cliente não mostra compromisso nenhum", meses depois.

Semeamos parando na 0077 e só então aplicamos a 0078: backfill sobre tabela vazia é
indistinguível de backfill no-op, que é o bug que este arquivo existe para pegar.

Marcado `rls_e2e`: NÃO roda no `pytest -q`; roda no job `cross-tenant-rls` do CI e
localmente com Docker (`pytest -m rls_e2e`).
"""
```

Três testes:

```python
def test_backfill_liga_evento_de_cobranca_ao_cliente(...):
    """O caso que o backfill existe para resolver: evento antigo ganha dono."""
    # Semeie parando na 0077: um tenant, um client, uma charge com client_id,
    # e um agenda_event kind='cobranca_receber' com external_ref = charge.id.
    # Aplique a 0078. Afirme que o evento agora tem client_id igual ao da charge.

def test_backfill_nao_e_no_op(...):
    """A asserção que só o Postgres com RLS pode fazer.

    Se alguém remover a janela de DISABLE ROW LEVEL SECURITY, o UPDATE roda, não falha, e
    afeta zero linhas. Este teste é a única coisa entre esse commit e a produção.
    """
    # Idem acima, mas afirme explicitamente COUNT(*) de eventos com client_id NÃO NULO >= 1.

def test_backfill_nao_inventa_dono(...):
    """Evento sem cobrança e conta a PAGAR continuam órfãos — e devem."""
    # Semeie um evento kind='bloqueio' sem external_ref e um kind='cobranca_pagar' cujo
    # external_ref aponta para um payable. Afirme que ambos ficam com client_id NULL.
```

> ⚠️ O terceiro teste importa mais do que parece: `_events_out` no router resolve **dois** vínculos — cliente (via `charges`) e **fornecedor** (via `payables`). Um backfill que casasse `external_ref` sem filtrar por `kind` ligaria um evento de conta a pagar ao id de uma cobrança que por acaso colidisse. Filtrar por `kind='cobranca_receber'` é obrigatório.

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_migration_0078_agenda_client_rls.py -m rls_e2e -v
```

Esperado: FAIL — a revisão 0078 não existe.

- [ ] **Step 3: Escrever a migration**

Crie `apps/api/migrations/versions/0078_agenda_event_client.py`. **Leia a 0068 primeiro** — ela é o modelo da janela de RLS e o docstring dela explica a armadilha.

```python
"""Vínculo do compromisso com o contato: agenda_events.client_id

Revision ID: 0078
Revises: 0077
Create Date: 2026-08-16

A Agenda não sabia de que contato era um compromisso. O nome que a tela mostrava era
DERIVADO da cobrança, por um caminho polimórfico via `external_ref` — que já está ocupado
apontando para cobrança e para conta a pagar, conforme o `kind`.

SEM FK, `String(36)`, seguindo o precedente de `whatsapp_chats.client_id`: a Agenda não deve
ganhar dependência dura da tabela do CRM. Nullable é o caso NORMAL — bloqueio de horário,
prazo interno e conta a pagar não têm cliente.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL. Ela roda como o papel dono
não-superusuário `e1p_app`, **sem** a GUC `app.current_tenant_id`. Sob `FORCE ROW LEVEL
SECURITY` o `UPDATE` seria filtrado a **ZERO LINHAS, EM SILÊNCIO** — e o sintoma em produção
não seria erro de deploy, seria "a ficha não mostra compromisso nenhum". Por isso a RLS é
desabilitada nas DUAS tabelas na janela do backfill (`agenda_events` porque é o ALVO,
`charges` porque é a FONTE da subconsulta — a RLS filtra SELECT também) e restaurada com
ENABLE + FORCE logo depois. Mesmo padrão da 0046, 0066, 0067 e 0068. DDL é transacional no
Postgres e a migration roda offline, então não há janela de exposição.

O backfill filtra por `kind='cobranca_receber'`. Sem esse filtro, um evento de conta a pagar
cujo `external_ref` colidisse com o id de uma cobrança ganharia um dono errado — `external_ref`
é ponteiro polimórfico, e o `kind` é o discriminador.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agenda_events", sa.Column("client_id", sa.String(36), nullable=True))
    op.create_index(
        "ix_agenda_events_client_id", "agenda_events", ["client_id"]
    )

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo abaixo é no-op) ---
    op.execute("ALTER TABLE agenda_events DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE charges DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        UPDATE agenda_events AS e
           SET client_id = c.client_id
          FROM charges AS c
         WHERE e.external_ref = c.id
           AND e.kind = 'cobranca_receber'
           AND c.client_id IS NOT NULL
           AND e.tenant_id = c.tenant_id
        """
    )

    op.execute("ALTER TABLE agenda_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agenda_events FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE charges ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE charges FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_agenda_events_client_id", table_name="agenda_events")
    op.drop_column("agenda_events", "client_id")
```

> ⚠️ Confirme o nome real da tabela de cobranças (`charges`) e da coluna de tenant lendo `apps/api/app/modules/receivables/models.py` antes de rodar. O `AND e.tenant_id = c.tenant_id` é cinto de segurança: com a RLS desligada, nada mais impede um cruzamento entre tenants se dois ids colidissem.

- [ ] **Step 4: Adicionar o campo ao modelo**

Em `apps/api/app/modules/agenda/models.py`, dentro de `AgendaEvent`, logo abaixo de `external_ref`:

```python
    # De QUEM é este compromisso. Nullable é o caso normal: bloqueio de horário, prazo
    # interno e conta a pagar não têm cliente. Sem FK e `String(36)`, como
    # `whatsapp_chats.client_id` — a Agenda não deve ganhar dependência dura da tabela do CRM.
    #
    # Não confundir com `external_ref`: aquele é ponteiro POLIMÓRFICO, lido conforme o `kind`
    # (id de cobrança, de conta a pagar...). Este é sempre um `clients.id`.
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
```

- [ ] **Step 5: Rodar o teste de migration**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_migration_0078_agenda_client_rls.py -m rls_e2e -v
```

Esperado: 3 passed.

- [ ] **Step 6: Provar que o teste discrimina**

Copie a migration (`cp`, **nunca** `git checkout`/`git stash` — há trabalho não commitado), remova as quatro linhas de `DISABLE`/`ENABLE`/`FORCE`, rode de novo e confirme que `test_backfill_nao_e_no_op` **FALHA**. Restaure e confirme que volta a passar. Reporte os dois resultados.

Se passar sem a janela, o teste não está medindo o que promete e precisa de outra construção.

- [ ] **Step 7: Suítes e lint**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .
cd apps/api && TZ=UTC /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -q
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -m rls_e2e -q
```

- [ ] **Step 8: Commit**

```bash
git add apps/api/migrations/versions/0078_agenda_event_client.py apps/api/tests/test_migration_0078_agenda_client_rls.py apps/api/app/modules/agenda/models.py
git commit -m "feat: o compromisso da Agenda sabe de que contato e (migration 0078)"
```

---

### Task 2: A API da Agenda passa a falar de contato

**Files:**
- Modify: `apps/api/app/modules/agenda/schemas.py`, `service.py`, `router.py`
- Modify: `apps/api/app/modules/receivables/service.py` (por volta da linha 257)
- Test: `apps/api/tests/test_agenda_por_contato.py` (criar)

**Interfaces:**
- Consumes: `AgendaEvent.client_id` da Task 1.
- Produces: `GET /agenda/events?client_id=<id>`; `client_id` em `EventCreate`/`EventUpdate`/`EventOut`; `next_event_map(db) -> dict[str, AgendaEvent]`.

- [ ] **Step 1: Escrever os testes (vão falhar)**

Crie `apps/api/tests/test_agenda_por_contato.py`. Use o padrão de fixture `headers` de `tests/test_agenda.py` — **leia aquele arquivo** para copiar a forma de autenticar e criar eventos pela API.

Cobrir:

```python
def test_cria_evento_com_client_id_e_le_de_volta(client, headers): ...
def test_filtro_por_client_id_traz_so_os_daquele_contato(client, headers): ...
def test_evento_sem_client_id_nao_aparece_no_filtro(client, headers): ...
def test_cobranca_criada_ja_nasce_com_client_id_no_evento(client, db, headers):
    """`receivables` cria o evento da Agenda; ele tem que nascer ligado, não só o passado."""

def test_next_event_map_traz_o_mais_proximo_por_contato(db): ...
def test_next_event_map_ignora_cancelado(db): ...
def test_next_event_map_inclui_evento_de_dia_inteiro_de_hoje(db):
    """⚠️ O caso que uma implementação ingênua erra.

    Evento de dia inteiro é ancorado na meia-noite REAL do fuso do tenant (ver
    `agenda/service.create_event`). Às 15h, o `starts_at` dele já passou — filtrar por
    `starts_at >= agora` esconderia o compromisso de HOJE, que é justamente o mais
    relevante para o card. O critério é `ends_at >= agora`.
    """
```

- [ ] **Step 2: Rodar e confirmar que falham**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_agenda_por_contato.py -v
```

- [ ] **Step 3: Schemas**

Em `apps/api/app/modules/agenda/schemas.py`, adicione `client_id: str | None = None` a `EventCreate`, a `EventUpdate` e a `EventOut` (esta última já tem `client_name`; o campo novo fica logo acima dele, com um comentário distinguindo os dois: `client_id` é o vínculo, `client_name` é o nome resolvido para o card).

- [ ] **Step 4: Service**

Em `create_event`, passe `client_id=data.client_id` ao construir o `AgendaEvent`. Em `update_event`, trate `client_id` como os demais campos opcionais (leia como o arquivo já faz com os outros antes de escrever).

Adicione, ao fim de `service.py`:

```python
def next_event_map(db: Session) -> dict[str, AgendaEvent]:
    """Próximo compromisso por contato, para a linha do card do Kanban.

    Consulta agregada, uma para o board inteiro — no molde de `crm_service.last_interaction_map`,
    que existe justamente porque valor derivado guardado dessincroniza. O custo não cresce com
    a quantidade de cards.

    ⚠️ O corte é `ends_at >= agora`, NÃO `starts_at >= agora`. Evento de dia inteiro é ancorado
    na meia-noite real do fuso do tenant (ver `create_event`), então às 15h o `starts_at` dele
    já passou — filtrar pelo início esconderia o compromisso de HOJE, que é o mais relevante
    que existe para o card. Pelo fim, ele aparece o dia todo e some quando acaba.

    Cancelado fica de fora: não é próximo passo nenhum.

    A sessão já chega escopada por RLS (mesma convenção de `list_events`).
    """
```

Implemente com `row_number()` particionado por `client_id`, ordenado por `(starts_at, id)`, ficando com `rn == 1` — mesmo padrão que a Onda 1 usou em `unread_client_ids`, e pelo mesmo motivo: sem desempate por `id`, dois eventos no mesmo instante fazem "o próximo" dançar entre chamadas. Sem SQL condicional por dialeto.

- [ ] **Step 5: Router — o filtro**

Em `list_events` (`router.py`), acrescente `client_id: str | None = Query(default=None)` e repasse ao service, que filtra na consulta.

- [ ] **Step 6: `receivables` grava o vínculo**

Em `apps/api/app/modules/receivables/service.py`, no `AgendaEvent(...)` por volta da linha 257, acrescente:

```python
        client_id=data.client_id,
```

com um comentário curto dizendo que sem isto só o passado (o backfill da 0078) ficaria ligado e todo evento novo nasceria órfão.

- [ ] **Step 7: Rodar, lint, commit**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_agenda_por_contato.py -v
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .
cd apps/api && TZ=UTC /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -q
```

```bash
git add apps/api/app/modules/agenda apps/api/app/modules/receivables/service.py apps/api/tests/test_agenda_por_contato.py
git commit -m "feat: eventos da Agenda filtram por contato e nascem ligados a ele"
```

---

### Task 3: A limpeza do `_events_out` — teste de paridade ANTES da remoção

`agenda/router.py::_events_out` reconstrói o nome do cliente por um caminho polimórfico: junta `external_ref` de dois `kind`s, busca cobranças, monta mapa. Com `client_id` populado, a metade das cobranças vira um join direto.

> ⚠️ **Só metade morre.** `_events_out` resolve DOIS vínculos: cliente (via `charges`) e **fornecedor** (via `payables`, `p.supplier`). Conta a pagar não tem cliente e nunca terá `client_id`. A derivação via `payables` **fica**. Remover as duas apagaria o nome do fornecedor da tela da Agenda.

**Files:**
- Modify: `apps/api/app/modules/agenda/router.py:25-49`
- Test: `apps/api/tests/test_agenda_por_contato.py` (acrescentar)

- [ ] **Step 1: Escrever o teste de paridade (deve passar JÁ, antes de qualquer mudança)**

```python
def test_client_name_do_evento_e_o_mesmo_pelos_dois_caminhos(client, db, headers):
    """A trava da limpeza: derivação antiga e join novo produzem o MESMO `client_name`.

    Roda ANTES da remoção do caminho velho. Se um backfill errasse uma linha, a Agenda
    perderia um nome que hoje mostra — e ninguém perceberia, porque nenhum teste afirmava
    que os dois caminhos concordam.
    """
    # Crie uma cobrança com cliente (o que gera o evento da Agenda com client_id e external_ref).
    # Calcule o nome pelos DOIS caminhos sobre a mesma base:
    #   antigo: external_ref -> Charge -> Client.name
    #   novo:   AgendaEvent.client_id -> Client.name
    # Afirme que são iguais, e que não são None.

def test_conta_a_pagar_continua_mostrando_o_fornecedor(client, db, headers):
    """A metade que NÃO morre. Conta a pagar não tem cliente; o nome vem de `payables.supplier`."""
```

- [ ] **Step 2: Rodar — os dois devem passar antes da mudança**

Se `test_client_name_..._dois_caminhos` já falhar aqui, **pare e reporte**: significa que o backfill ou o `receivables` não estão ligando corretamente, e a limpeza não pode prosseguir.

- [ ] **Step 3: Trocar a metade das cobranças por join direto**

Reescreva `_events_out` para resolver o nome do cliente por `AgendaEvent.client_id` (uma consulta a `Client` com os ids do lote), mantendo intacto o ramo `pagar_refs` → `Payable.supplier`. Atualize o docstring para dizer que os dois caminhos existem porque são coisas diferentes: cliente é vínculo direto, fornecedor é derivação e continua sendo.

- [ ] **Step 4: Rodar de novo — os mesmos testes, agora contra o código novo**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_agenda_por_contato.py tests/test_agenda.py -v
```

Ambos os testes de paridade continuam verdes; se o do fornecedor cair, você removeu a metade errada.

- [ ] **Step 5: Suíte inteira, lint, commit**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check . && TZ=UTC /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -q
git add apps/api/app/modules/agenda/router.py apps/api/tests/test_agenda_por_contato.py
git commit -m "refactor: o nome do cliente na Agenda vem do vinculo, nao da derivacao"
```

---

### Task 4: O compromisso realizado entra no Histórico — e o fuso do `ClientTimeline`

**Files:**
- Modify: `apps/api/app/modules/crm/timeline.py`
- Modify: `apps/web/src/features/crm/ClientTimeline.tsx`
- Test: `apps/api/tests/test_client_timeline.py` (acrescentar), `apps/web/src/features/crm/ClientTimeline.test.tsx` (acrescentar)

**Interfaces:**
- Produces: entradas com `kind: "agenda"` no `GET /crm/clients/{id}/timeline`.

- [ ] **Step 1: Escrever os testes (vão falhar)**

API — acrescente a `tests/test_client_timeline.py`:

```python
def test_timeline_inclui_compromisso_realizado(...):
    """Compromisso que já aconteceu é fato do relacionamento — vive no Histórico, não no bloco."""

def test_timeline_nao_inclui_compromisso_futuro(...):
    """O futuro é assunto do bloco de Agenda. Duas telas, duas perguntas."""

def test_timeline_de_agenda_respeita_o_limite_por_fonte(...):
    """Mesma regra das outras três fontes: `LIMITE_POR_FONTE` e `truncated`."""
```

Web — acrescente a `ClientTimeline.test.tsx`:

```tsx
it("formata no fuso do tenant, não no do navegador", async () => {
  // Uma entrada às 23:30 UTC deve aparecer como 20:30 em America/Sao_Paulo (UTC-3),
  // e a DATA deve ser a do dia anterior — que é o ponto: sem o fuso, a entrada aparece
  // no dia errado. Mocke `useFuso` para "America/Sao_Paulo".
});

it("compromisso realizado tem identidade visual própria, não o ícone neutro", async () => {
  // O vocabulário de `kind` é FECHADO: um `kind` sem entrada em APARENCIA cai no neutro.
});
```

- [ ] **Step 2: Rodar e confirmar que falham**

- [ ] **Step 3: A 4ª fonte no `timeline.py`**

Em `apps/api/app/modules/crm/timeline.py`, acrescente `AgendaEvent` ao lado de `Fact`, `Charge` e `Quote`, seguindo o padrão exato das outras três (mesmo `LIMITE_POR_FONTE`, mesma marcação de `truncated`, mesma normalização por `_instante`).

Só compromissos **já realizados** entram: filtre por `ends_at < agora` e por `status != 'cancelled'`. Título no formato do resto do arquivo — algo como `f"Compromisso: {e.title}"` —, `kind` = `"agenda"`, `actor` = `"sistema"`.

Atualize o docstring do módulo: hoje ele fala em DUAS fontes derivadas (`quotes` e `charges`); passam a ser três, e a razão é a mesma — ler na origem em vez de copiar para `facts`.

- [ ] **Step 4: A aparência do `kind` novo, e o conserto do fuso**

Em `apps/web/src/features/crm/ClientTimeline.tsx`:

Acrescente ao mapa `APARENCIA` uma entrada para `agenda`, com ícone `CalendarDays` do `lucide-react` e cor coerente com as demais fontes derivadas (`quote` e `charge` usam `bg-sky-50 text-sky-700`).

E conserte o fuso. A função `quando()` hoje é:

```tsx
const quando = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
```

Sem `timeZone`, isso formata no relógio do NAVEGADOR. O comentário acima dela diz "mesma convenção da ConversasPage" — mas a ConversasPage foi corrigida exatamente disso, e o comentário dela explica por quê: o mesmo histórico quebrava os dias em pontos diferentes conforme a máquina que abrisse a tela. Passe a usar `useFuso()` + `lib/datetime`, como o resto do sistema, e reescreva o comentário para dizer a verdade.

> Isto vira obrigatório agora, e não antes, porque esta tarefa coloca compromisso **com horário** nessa lista: "reunião às 14h" aparecendo às 11h para quem abrir de outro fuso é errado de um jeito que o dono percebe.

- [ ] **Step 5: Rodar, lint, commit**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/test_client_timeline.py -v && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/onda-2-agenda && pnpm --filter @e1p/web test -- ClientTimeline && pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
```

```bash
git add apps/api/app/modules/crm/timeline.py apps/api/tests/test_client_timeline.py apps/web/src/features/crm/ClientTimeline.tsx apps/web/src/features/crm/ClientTimeline.test.tsx
git commit -m "feat: compromisso realizado entra no Historico, e ele passa a usar o fuso do tenant"
```

---

### Task 5: Extrair o `NewEventModal`

`AgendaPage.tsx` tem 723 linhas e o modal ocupa ~175 delas (a partir da 547). Ele já resolve o aviso de conflito de horário; a ficha vai reusá-lo em vez de reimplementar.

**Files:**
- Create: `apps/web/src/features/agenda/NewEventModal.tsx`
- Modify: `apps/web/src/features/agenda/AgendaPage.tsx`
- Test: `apps/web/src/features/agenda/NewEventModal.test.tsx` (criar)

**Interfaces:**
- Produces: `<NewEventModal open initialDate onClose onCreated clientId? />`. Consumido pela Task 6.

- [ ] **Step 1: Escrever os testes (vão falhar)**

```tsx
it("envia client_id quando recebe um", async () => { /* afirma o corpo do POST /agenda/events */ });
it("não envia client_id quando não recebe", async () => { /* a Agenda continua criando evento solto */ });
it("mostra o aviso de conflito sem fechar o modal", async () => {
  // O comportamento que NÃO pode se perder na extração: com conflitos, avisa e mantém aberto.
});
```

- [ ] **Step 2: Rodar e confirmar que falham**

- [ ] **Step 3: Mover, não reescrever**

Recorte o componente `NewEventModal` de `AgendaPage.tsx` para `NewEventModal.tsx`, **sem alterar a lógica**. Leve junto o que ele usa e que hoje vive no escopo do arquivo (`KINDS`, `MEET_KINDS`, `ymd`, `getGoogleStatus`, `Field`, `Modal`) — importando de onde já vêm ou movendo o que for exclusivo dele. Se algum helper for compartilhado com o resto do `AgendaPage`, **não duplique**: exporte-o de um lado e importe do outro.

Acrescente a prop opcional:

```tsx
  /** Quando presente, o evento nasce ligado a este contato. A ficha 360° usa isto; a tela de
   *  Agenda não passa nada e segue criando evento solto. */
  clientId?: string;
```

e inclua `client_id: clientId ?? null` no corpo do `POST /agenda/events`.

- [ ] **Step 4: `AgendaPage` importa em vez de declarar**

Confirme que a página segue funcionando exatamente como antes — os testes existentes de `AgendaPage.test.tsx` são a rede.

- [ ] **Step 5: Rodar tudo, lint, commit**

```bash
pnpm --filter @e1p/web test && pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
```

Esperado: a suíte inteira verde, incluindo `AgendaPage`. Uma regressão ali significa que a extração levou junto algo que ficou faltando.

```bash
git add apps/web/src/features/agenda/
git commit -m "refactor: NewEventModal em arquivo proprio, aceitando clientId"
```

---

### Task 6: O bloco "Agenda" na ficha

**Files:**
- Create: `apps/web/src/features/crm/BlocoDaAgenda.tsx`, `BlocoDaAgenda.test.tsx`
- Modify: `apps/web/src/features/crm/ClientDetailPage.tsx`

**Interfaces:**
- Consumes: `GET /agenda/events?client_id=` (Task 2), `<NewEventModal clientId>` (Task 5).

O bloco é **ativo**: mostra os **próximos** compromissos e traz "Marcar com este cliente". O passado NÃO aparece aqui — ele vive no Histórico (Task 4). Duas telas, duas perguntas.

- [ ] **Step 1: Escrever os testes (vão falhar)**

```tsx
it("lista os próximos compromissos, do mais próximo para o mais distante", ...);
it("estado vazio diz que não há compromisso e oferece marcar", ...);
// ⚠️ Este é o estado MAIS IMPORTANTE do bloco: é ele que revela o contato que vai esfriar.
it("abre o modal de marcar e, ao criar, recarrega a lista", ...);
it("formata o horário no fuso do tenant", ...);
it("falha de rede vira aviso, não derruba a ficha", ...);
```

- [ ] **Step 2: Rodar e confirmar que falham**

- [ ] **Step 3: Implementar**

Arquivo próprio: `ClientDetailPage.tsx` já tem sete seções. Siga a postura do `BlocoDaConversa` (criado na Onda 1) — **leia-o**: carrega sozinho fora do `load()` da página, degrada para aviso em falha, e não derruba a ficha. Os dois devem parecer irmãos.

Estado vazio: "Nenhum compromisso marcado", com o botão logo abaixo.

- [ ] **Step 4: Pendurar na ficha**

Em `ClientDetailPage.tsx`, insira a seção logo **depois** de Conversa e antes de Cobranças — a ficha conta uma história: o que aconteceu (Histórico), o que foi dito (Conversa), o que está marcado (Agenda), e então o operacional. Use `<Section icon={<CalendarDays size={16} />} title="Agenda">`.

- [ ] **Step 5: Rodar tudo, lint, commit**

---

### Task 7: A linha do próximo passo no card

**Files:**
- Modify: `apps/api/app/modules/crm/schemas.py`, `apps/api/app/modules/crm/router.py`
- Modify: `packages/shared-types/src/index.ts`
- Modify: `apps/web/src/features/crm/CrmPage.tsx`
- Test: `apps/api/tests/test_crm_board_proximo_passo.py` (criar), `CrmPage.test.tsx` (acrescentar)

- [ ] **Step 1: Escrever os testes (vão falhar)**

API — no molde de `tests/test_crm_board_nao_lida.py` (criado na Onda 1; **leia-o**, inclusive o teste de contagem de consultas, que deve ganhar um irmão aqui):

```python
def test_board_traz_o_proximo_compromisso_do_contato(client, db, headers): ...
def test_board_nao_traz_compromisso_cancelado(client, db, headers): ...
def test_board_nao_faz_uma_consulta_por_card_com_proximo_passo(client, db, headers):
    """Mesma trava do `unread`: dobrar os cards não pode dobrar as consultas."""
```

Web:

```tsx
it("mostra o próximo compromisso quando existe", ...);
it("diz 'sem próximo passo' quando não existe", ...);
it("nunca mostra os dois ao mesmo tempo", ...);
```

- [ ] **Step 2: Rodar e confirmar que falham**

- [ ] **Step 3: Backend**

`BoardClient` ganha `next_event_at: datetime | None` e `next_event_title: str | None`, com o mesmo comentário de vizinhança que `unread` já tem (campos que só o board calcula). O `get_board` chama `next_event_map(db)` **uma vez**, ao lado de `last_interaction_map` e `unread_client_ids`.

Note a diferença de forma: `next_event_map` devolve `dict[str, AgendaEvent]` — o evento inteiro —, e o router extrai os dois campos ao montar cada `BoardClient` (`ev.starts_at` e `ev.title`, ou `None` quando o contato não está no mapa). Devolver o objeto, e não uma tupla já achatada, é o que permite o bloco da ficha e o card lerem coisas diferentes do mesmo agregado sem uma segunda consulta.

- [ ] **Step 4: Tipo compartilhado**

`packages/shared-types/src/index.ts`, em `BoardClient`: `next_event_at: string | null` e `next_event_title: string | null`.

- [ ] **Step 5: O card**

Em `CrmPage.tsx`, dentro de `Card`, **uma linha só** abaixo de "última interação":

```tsx
        {/* Próximo passo e a AUSÊNCIA dele são estados opostos da mesma pergunta e nunca
            aparecem juntos — por isso uma linha só, e não duas. O aviso de "sem próximo passo"
            é o mais acionável do card: mostra quem vai esfriar. */}
```

Renderize o título e a data no fuso do tenant (`useFuso()` + `formatDateShort`) quando houver; senão, o aviso em tom discreto.

- [ ] **Step 6: Rodar tudo (API + web), lint, typecheck, commit**

---

### Task 8: Fechamento — suítes completas e a régua de 360px

O card ganhou uma **terceira** linha de rodapé e a ficha uma oitava seção. A régua de 360px foi afiada na Onda 1 (`e2e/support/medidas.ts` passou a medir a tinta, não a caixa) — ela agora enxerga estouro que antes passava.

**Files:**
- Modify: `apps/web/e2e/crm-360.spec.ts`, `apps/web/e2e/fixtures/crm.json`
- Create: `apps/web/e2e/ficha-agenda-360.spec.ts`

- [ ] **Step 1: Todas as suítes, em primeiro plano**

```bash
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m ruff check .
cd apps/api && TZ=UTC /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -q
cd apps/api && /f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe -m pytest tests/ -m rls_e2e -q
cd /f/Projetos/e1p/escritorio-1-pessoa/.claude/worktrees/onda-2-agenda
pnpm --filter @e1p/web test && pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
pnpm --filter @e1p/web e2e
```

- [ ] **Step 2: A fixture ganha o próximo passo**

Em `apps/web/e2e/fixtures/crm.json`, acrescente `next_event_at` e `next_event_title` aos dois cards: o card mais cheio (`c2`) recebe um **título longo e plausível** de compromisso — "Reunião de alinhamento do casamento 12/12" —, e `c1` recebe `null` nos dois, exercitando o "sem próximo passo". Pior caso plausível, como manda a casa.

- [ ] **Step 3: Medir o card de três linhas**

Acrescente a `crm-360.spec.ts` uma medição no estilo do arquivo: o card com o título longo de compromisso não estoura a coluna, com varredura escopada em `.w-72` **e o controle positivo** (`.seletor-que-nao-existe`) — sem o par, a varredura vira um passe permanente que não mede nada.

- [ ] **Step 4: Medir o bloco de Agenda na ficha**

Crie `ficha-agenda-360.spec.ts` no molde de `ficha-conversa-360.spec.ts` (Onda 1). Dê à seção um `data-testid` próprio pelo mesmo motivo que a Conversa ganhou o dela: `querySelector` devolve só o primeiro casamento e as oito seções da ficha compartilham `.rounded-2xl.bg-white`, então um seletor de classe mediria o cabeçalho do cliente.

Inclua o caso que estoura de verdade: um compromisso com título longo **sem espaços**, e o botão "Marcar com este cliente" ao lado da lista.

Se algo estourar, o conserto é no CSS do componente — **nunca** afrouxar a medição.

- [ ] **Step 5: Commit e reportar**

Reporte ao dono os commits, a saída real de cada suíte (números, não "passou"), e que push e PR são do @devops.

---

## Definição de pronto

- [ ] `agenda_events.client_id` existe, indexada, e o backfill ligou o passado — provado sob Postgres real com RLS.
- [ ] O teste da migration falha quando a janela de RLS é removida (discriminação demonstrada).
- [ ] Evento novo de cobrança nasce ligado ao contato.
- [ ] `GET /agenda/events?client_id=` filtra; `next_event_map` ignora cancelado e inclui o dia-inteiro de hoje.
- [ ] O nome do cliente na Agenda vem do vínculo; o do fornecedor continua vindo da conta a pagar.
- [ ] Compromisso realizado aparece no Histórico; futuro não.
- [ ] `ClientTimeline` formata no fuso do tenant.
- [ ] `NewEventModal` mora em arquivo próprio, aceita `clientId`, e a tela de Agenda não regrediu.
- [ ] A ficha mostra os próximos compromissos e marca um novo dali.
- [ ] O card diz o próximo passo — ou avisa que não há.
- [ ] Todas as suítes verdes, incluindo `rls_e2e` e a régua de 360px.
- [ ] Nenhum commit em `main`; nenhum push.
