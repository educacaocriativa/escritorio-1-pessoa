# Ordem de entrada na etapa (Kanban) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cada coluna do Funil de clientes passa a listar os cards por ordem de entrada naquela etapa — o mais antigo no topo, quem entra vai para o fim — para que o dono atenda em ordem de chegada.

**Architecture:** uma coluna nova `clients.stage_entered_at` carimbada nos três caminhos que escrevem `Client.stage_id`, um teste-portão AST que impede o quarto caminho de esquecer, e `build_board` ordenando por ela. Não é derivação em tempo de leitura porque o `client_events` não tem registro completo de troca de etapa (`archive_stage` não grava evento nenhum).

**Tech Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · pytest · React 18 + TypeScript + Vitest

**Spec:** `docs/superpowers/specs/2026-08-05-crm-ordem-de-entrada-na-etapa-design.md`

## Global Constraints

- **Checkout:** `f:\Projetos\e1p\e1p-whatsapp-evolution`, branch `feat/crm-ordem-de-entrada-na-etapa` (já criada, a partir de `origin/main` @ `ee52750`). **Não** trabalhar em `escritorio-1-pessoa` — está parado em outra branch com trabalho em andamento.
- **Python:** este checkout **não tem venv próprio**. Usar o do irmão: `/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe`.
- **Rodar testes no FOREGROUND**, nunca em background.
- **Idioma:** comentários e docstrings de domínio em **PT-BR**; identificadores em inglês.
- **Commits:** Conventional Commits. Terminar toda mensagem com `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`. Usar heredoc (`git commit -F - <<'EOF'`), **nunca** here-string do PowerShell no Bash.
- **`main` é protegida** (`GH006`): nada de push direto; a entrega é um PR com os 4 checks.
- **RLS é a única garantia de isolamento** — não adicionar filtro manual de `tenant_id` em query nenhuma.
- **Alembic head é `0067`.** Reconferir com `ls apps/api/migrations/versions/` antes de criar a `0068` e a cada merge de `main`.

### Comandos

```bash
PY=/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api

$PY -m pytest tests/test_crm.py -v            # suíte do módulo
$PY -m ruff check app tests                   # lint
cd /f/Projetos/e1p/e1p-whatsapp-evolution && pnpm --filter @e1p/web test   # vitest
```

---

### Task 1: Coluna `stage_entered_at` + migration 0068

**Files:**
- Modify: `apps/api/app/modules/crm/models.py` (classe `Client`)
- Create: `apps/api/migrations/versions/0068_client_stage_entered_at.py`
- Test: `apps/api/tests/test_crm_stage_order.py` (novo)

**Interfaces:**
- Consumes: nada.
- Produces: `Client.stage_entered_at: Mapped[datetime]` — não-nulo, default Python `datetime.now(UTC)`. Todas as tarefas seguintes dependem deste nome exato.

- [ ] **Step 1: Escrever o teste que falha**

Criar `apps/api/tests/test_crm_stage_order.py`:

```python
"""Ordem de entrada na etapa: a fila FIFO de cada coluna do Kanban.

Spec: docs/superpowers/specs/2026-08-05-crm-ordem-de-entrada-na-etapa-design.md
"""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

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


def test_cliente_novo_nasce_carimbado(client: TestClient, headers, db):
    """Todo card sabe desde quando está na etapa em que está."""
    from app.modules.crm.models import Client

    antes = datetime.now(UTC) - timedelta(seconds=5)
    resp = client.post("/crm/clients", json={"name": "João"}, headers=headers)
    assert resp.status_code == 201

    row = db.get(Client, resp.json()["id"])
    assert row.stage_entered_at is not None
    # SQLite devolve naive; comparamos em UTC consciente.
    carimbo = row.stage_entered_at
    if carimbo.tzinfo is None:
        carimbo = carimbo.replace(tzinfo=UTC)
    assert carimbo >= antes
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
PY=/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -m pytest tests/test_crm_stage_order.py -v
```

Esperado: FAIL com `AttributeError: 'Client' object has no attribute 'stage_entered_at'`.

- [ ] **Step 3: Adicionar a coluna ao modelo**

Em `apps/api/app/modules/crm/models.py`, dentro da classe `Client`, logo **depois** do campo `stage_id`:

```python
    # Desde quando este card está NESTA etapa. É a ordem da fila do Kanban: o mais antigo no
    # topo, quem entra vai para o fim, para que o dono atenda por ordem de chegada.
    #
    # Coluna, e não derivação de `client_events`, porque os três caminhos que escrevem
    # `stage_id` registram coisas diferentes — `move_client` grava `stage_move`, a reabertura
    # do `absorb_lead` grava `reopened`, e `archive_stage` remaneja em massa sem evento
    # nenhum. Não é valor derivado materializado (o caso que `last_interaction_map` recusa);
    # é fato primário que não tinha onde morar.
    #
    # Default do lado do PYTHON, sobrescrevendo o `server_default`: no Postgres `now()` é o
    # instante da TRANSAÇÃO, então dois carimbos no mesmo commit sairiam idênticos e o
    # desempate cairia no uuid. Mesma razão de `ClientEvent.created_at`.
    stage_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
```

`models.py` já importa `UTC`, `datetime`, `DateTime` e `func` (usados por `ClientEvent`) — nada a acrescentar nos imports.

- [ ] **Step 4: Rodar o teste e confirmar que passa**

```bash
$PY -m pytest tests/test_crm_stage_order.py -v
```

Esperado: PASS.

- [ ] **Step 5: Escrever a migration 0068**

Conferir primeiro que o head ainda é `0067`:

```bash
ls /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api/migrations/versions/ | tail -3
```

Criar `apps/api/migrations/versions/0068_client_stage_entered_at.py`:

```python
"""Ordem de entrada na etapa: clients.stage_entered_at

Revision ID: 0068
Revises: 0067
Create Date: 2026-08-05

O board do Kanban ordenava por `Client.name`. Como a maioria dos leads entra pelo WhatsApp sem
nome resolvido, o "nome" é o telefone e a coluna Entrada aparecia em ordem numérica de DDI. O
dono precisa atender por ordem de chegada, e "quando este card entrou nesta etapa" não estava
gravado em lugar nenhum.

⚠️ ARMADILHA QUE **SE APLICA** AQUI: esta migration FAZ BACKFILL de `clients`. Ela roda como o
papel dono NÃO-superusuário `e1p_app`, **sem** a GUC `app.current_tenant_id`. Sob `FORCE ROW
LEVEL SECURITY`, o `UPDATE` seria filtrado a **ZERO LINHAS, em silêncio** — e o sintoma em
produção não seria um erro de deploy, seria "a fila continua fora de ordem". Por isso a RLS de
`clients` é desabilitada SÓ na janela do backfill e restaurada (ENABLE + FORCE) logo depois —
mesmo padrão da `0046`, `0066` e `0067`. DDL é transacional no Postgres e a migration roda
offline, então não há janela de exposição.

A coluna é `NOT NULL` no destino mas **não pode nascer assim**: nascer com
`server_default=now()` carimbaria todo card existente com o instante do deploy, e o backfill
teria de desfazer isso. Ordem: nullable → backfill → NOT NULL + server_default.

O backfill usa o melhor sinal disponível por linha: o último `stage_move`/`reopened` daquele
contato, e `clients.created_at` quando não houver evento (card anterior à 0067, ou card que
nunca se moveu — que é o caso da maioria). Errado no detalhe para card movido antes da 0067,
mas monotônico e sem buraco.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clients", sa.Column("stage_entered_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- backfill (ver a ARMADILHA no docstring: sem esta janela, tudo abaixo é no-op) ---
    op.execute("ALTER TABLE clients DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        UPDATE clients SET stage_entered_at = COALESCE(
            (SELECT MAX(e.created_at) FROM client_events e
              WHERE e.client_id = clients.id AND e.kind IN ('stage_move', 'reopened')),
            clients.created_at
        )
        """
    )

    op.execute("ALTER TABLE clients ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE clients FORCE ROW LEVEL SECURITY")

    op.alter_column(
        "clients",
        "stage_entered_at",
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.drop_column("clients", "stage_entered_at")
```

- [ ] **Step 6: Conferir que a migration é sintaticamente válida e o head é único**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -c "import ast,pathlib; ast.parse(pathlib.Path('migrations/versions/0068_client_stage_entered_at.py').read_text(encoding='utf-8')); print('ok')"
$PY -m ruff check migrations/versions/0068_client_stage_entered_at.py app/modules/crm/models.py
```

Esperado: `ok` e ruff sem erros.

- [ ] **Step 7: Rodar a suíte do CRM inteira (regressão)**

```bash
$PY -m pytest tests/test_crm.py tests/test_crm_stage_order.py tests/test_lead_absorb.py -v
```

Esperado: tudo PASS. Se algo falhar aqui, é regressão desta tarefa — corrigir antes de commitar.

- [ ] **Step 8: Commit**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
git add apps/api/app/modules/crm/models.py apps/api/migrations/versions/0068_client_stage_entered_at.py apps/api/tests/test_crm_stage_order.py
git commit -F - <<'EOF'
feat: clients.stage_entered_at, o fato que faltava para a fila do Kanban

"Quando este card entrou nesta etapa" nao existia em lugar nenhum. Nao e
derivavel do client_events: move_client grava stage_move, a reabertura grava
reopened, e archive_stage remaneja em massa sem evento nenhum.

Backfill dentro de janela com RLS desabilitada — sem ela o UPDATE seria
filtrado a zero linhas em silencio (armadilha da 0046/0066/0067).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: Carimbar nos três caminhos de escrita (e preservar no arquivamento)

**Files:**
- Modify: `apps/api/app/modules/crm/service.py` — `create_client`, `move_client`, `absorb_lead`, `archive_stage`
- Test: `apps/api/tests/test_crm_stage_order.py`

**Interfaces:**
- Consumes: `Client.stage_entered_at` (Task 1).
- Produces: nenhuma assinatura nova — só comportamento. As funções mantêm exatamente as assinaturas atuais.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `apps/api/tests/test_crm_stage_order.py`:

```python
def _stage_ids(client: TestClient, headers) -> list[str]:
    return [s["id"] for s in client.get("/crm/stages", headers=headers).json()]


def test_mover_card_recarimba(client: TestClient, headers, db):
    """Mudar de coluna é entrar numa etapa nova: o card vai para o fim da fila de destino."""
    from app.modules.crm.models import Client

    stages = _stage_ids(client, headers)
    criado = client.post("/crm/clients", json={"name": "João"}, headers=headers).json()
    antes = db.get(Client, criado["id"]).stage_entered_at

    resp = client.post(
        f"/crm/clients/{criado['id']}/move", json={"stage_id": stages[1]}, headers=headers
    )
    assert resp.status_code == 200

    db.expire_all()
    depois = db.get(Client, criado["id"]).stage_entered_at
    assert depois >= antes
    assert db.get(Client, criado["id"]).stage_id == stages[1]


def test_arquivar_etapa_preserva_antiguidade(client: TestClient, headers, db):
    """Arquivar é ato administrativo do dono — não custa a vez de quem esperou mais.

    Se recarimbasse, todo card da coluna arquivada iria em bloco para o fim da fila de
    destino, e a fila que existe para atender por antiguidade puniria quem esperou mais.
    """
    from app.modules.crm.models import Client

    stages = _stage_ids(client, headers)
    criado = client.post(
        "/crm/clients", json={"name": "Antigo", "stage_id": stages[2]}, headers=headers
    ).json()
    antes = db.get(Client, criado["id"]).stage_entered_at

    # Arquivar é POST .../archive (204). `DELETE /crm/stages/{id}` é outra coisa: recusa com
    # 409 quando a etapa tem clientes, então não exercitaria o remanejamento nenhum.
    resp = client.post(f"/crm/stages/{stages[2]}/archive", headers=headers)
    assert resp.status_code == 204

    db.expire_all()
    movido = db.get(Client, criado["id"])
    assert movido.stage_id == stages[0]          # remanejado para a primeira ativa
    assert movido.stage_entered_at == antes       # e com a antiguidade INTACTA


def test_reabertura_recarimba(client: TestClient, headers, db):
    """Retorno em coluna terminal reabre o card — e reabrir é entrar numa etapa nova.

    A reabertura escreve `stage_id` por um caminho DIFERENTE do `move_client` e grava
    `reopened` em vez de `stage_move` — é exatamente por isso que a ordem não pode ser
    derivada de `client_events` filtrando um kind só.
    """
    from app.modules.crm import service
    from app.modules.crm.models import Client, PipelineStage
    from app.modules.crm.schemas import ClientCreate

    stages = _stage_ids(client, headers)
    tenant_id = db.scalars(select(PipelineStage)).first().tenant_id

    # Nasce direto na coluna terminal "Perda" (a última do seed padrão).
    perdido = client.post(
        "/crm/clients",
        json={"name": "Voltou", "phone": "11999998888", "stage_id": stages[-1]},
        headers=headers,
    ).json()
    antes = db.get(Client, perdido["id"]).stage_entered_at

    existente, novo = service.absorb_lead(
        db,
        tenant_id=tenant_id,
        actor="pagina:lead",
        data=ClientCreate(name="Voltou", phone="11999998888"),
    )
    assert novo is False                      # absorveu, não criou card paralelo
    assert existente.stage_id == stages[0]    # reaberto na primeira coluna ativa
    assert existente.stage_entered_at >= antes


def test_editar_cliente_nao_reordena(client: TestClient, headers, db):
    """`updated_at` muda em qualquer edição; o carimbo da fila não pode mudar junto."""
    from app.modules.crm.models import Client

    criado = client.post("/crm/clients", json={"name": "João"}, headers=headers).json()
    antes = db.get(Client, criado["id"]).stage_entered_at

    resp = client.patch(
        f"/crm/clients/{criado['id']}", json={"name": "João Editado"}, headers=headers
    )
    assert resp.status_code == 200

    db.expire_all()
    assert db.get(Client, criado["id"]).stage_entered_at == antes
```

- [ ] **Step 2: Rodar e confirmar quais falham**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -m pytest tests/test_crm_stage_order.py -v
```

Esperado: `test_mover_card_recarimba` e `test_reabertura_recarimba` FALHAM (nenhum dos dois caminhos recarimba ainda). `test_arquivar_etapa_preserva_antiguidade` e `test_editar_cliente_nao_reordena` provavelmente já passam — o default do modelo cobre a criação e nenhum dos dois caminhos toca a coluna. Isso é esperado e correto: eles são testes de **regressão**, que travam o comportamento certo antes de o arquivo ser mexido.

- [ ] **Step 3: Carimbar em `move_client`**

Em `apps/api/app/modules/crm/service.py`, na função `move_client`, substituir a linha:

```python
    client.stage_id = target.id
```

por:

```python
    client.stage_id = target.id
    # Entrou numa etapa nova agora: vai para o FIM da fila da coluna de destino.
    client.stage_entered_at = datetime.now(UTC)
```

- [ ] **Step 4: Carimbar na reabertura do `absorb_lead`**

Na mesma `service.py`, dentro de `absorb_lead`, no ramo da reabertura, substituir:

```python
            existente.stage_id = ativas[0].id
```

por:

```python
            existente.stage_id = ativas[0].id
            # Reabrir é entrar numa etapa nova: a negociação anterior fechou e esta é outra.
            existente.stage_entered_at = datetime.now(UTC)
```

- [ ] **Step 5: Documentar a exceção deliberada em `archive_stage`**

Na mesma `service.py`, em `archive_stage`, o `.update()` fica **como está** — só ganha o comentário que explica a ausência, para que o gate da Task 4 e qualquer leitor futuro saibam que é escolha e não esquecimento:

```python
        # `stage_entered_at` NÃO é recarimbado aqui, de propósito (allowlist do gate em
        # tests/test_crm_stage_order_gate.py). Arquivar uma etapa é ato administrativo do
        # dono, não mudança na situação do cliente: recarimbar jogaria todo card desta
        # coluna, em bloco, para o fim da fila de destino — e a fila existe justamente para
        # atender por antiguidade. O card muda de coluna; a antiguidade dele é dele.
        db.query(Client).filter(Client.stage_id == stage_id).update(
            {Client.stage_id: others[0].id}, synchronize_session=False
        )
```

- [ ] **Step 6: Garantir o import de `datetime`/`UTC` em `service.py`**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
grep -n "^from datetime import\|^import datetime" app/modules/crm/service.py
```

Se não houver `UTC` e `datetime`, acrescentar no bloco de imports do topo (logo abaixo de `from __future__ import annotations`):

```python
from datetime import UTC, datetime
```

- [ ] **Step 7: Rodar os testes e confirmar que passam**

```bash
$PY -m pytest tests/test_crm_stage_order.py -v
$PY -m pytest tests/test_crm.py tests/test_lead_absorb.py -v
$PY -m ruff check app/modules/crm/service.py tests/test_crm_stage_order.py
```

Esperado: tudo PASS, ruff limpo.

- [ ] **Step 8: Commit**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
git add apps/api/app/modules/crm/service.py apps/api/tests/test_crm_stage_order.py
git commit -F - <<'EOF'
feat: carimba stage_entered_at nos tres caminhos que escrevem stage_id

move_client e a reabertura do absorb_lead recarimbam (entraram numa etapa
nova agora). archive_stage PRESERVA de proposito: arquivar e ato
administrativo do dono, e recarimbar jogaria todo card da coluna em bloco
para o fim da fila de destino.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: `build_board` ordena pela fila

**Files:**
- Modify: `apps/api/app/modules/crm/service.py:489-494` (`build_board`)
- Test: `apps/api/tests/test_crm_stage_order.py`

**Interfaces:**
- Consumes: `Client.stage_entered_at` (Task 1), carimbado (Task 2).
- Produces: `build_board` devolve os clientes de cada coluna em ordem `stage_entered_at ASC, id ASC`. É o comportamento que o frontend da Task 6 assume — a tela **não** reordena.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `apps/api/tests/test_crm_stage_order.py`:

```python
def _entrada(board: dict) -> list[str]:
    """Nomes dos cards da primeira coluna, na ordem em que o board os devolveu."""
    return [c["name"] for c in board["columns"][0]["clients"]]


def test_board_ordena_por_entrada_e_nao_por_nome(client: TestClient, headers):
    """O que entra depois fica no fim — mesmo que o nome venha antes no alfabeto."""
    for nome in ("Zulmira", "Amanda", "Mauricio"):
        assert client.post("/crm/clients", json={"name": nome}, headers=headers).status_code == 201

    board = client.get("/crm/board", headers=headers).json()
    assert _entrada(board) == ["Zulmira", "Amanda", "Mauricio"]


def test_card_moido_vai_para_o_fim_da_coluna_destino(client: TestClient, headers):
    stages = _stage_ids(client, headers)
    primeiro = client.post("/crm/clients", json={"name": "Primeiro"}, headers=headers).json()
    client.post("/crm/clients", json={"name": "Segundo"}, headers=headers)

    # "Primeiro" sai para a coluna 2 e volta: tem que reaparecer no FIM da Entrada.
    client.post(
        f"/crm/clients/{primeiro['id']}/move", json={"stage_id": stages[1]}, headers=headers
    )
    client.post(
        f"/crm/clients/{primeiro['id']}/move", json={"stage_id": stages[0]}, headers=headers
    )

    board = client.get("/crm/board", headers=headers).json()
    assert _entrada(board) == ["Segundo", "Primeiro"]


def test_ordem_e_estavel_com_carimbos_iguais(client: TestClient, headers, db):
    """Empate de instante não pode fazer a fila dançar entre dois carregamentos.

    Acontece de verdade: no Postgres, cards criados na mesma transação compartilham o
    instante. Sem desempate determinístico o board devolveria ordens diferentes para o
    mesmo estado.
    """
    from datetime import datetime as _dt

    from app.modules.crm.models import Client

    for nome in ("Um", "Dois", "Tres"):
        client.post("/crm/clients", json={"name": nome}, headers=headers)

    mesmo_instante = _dt(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    for row in db.query(Client).all():
        row.stage_entered_at = mesmo_instante
    db.commit()

    primeira = _entrada(client.get("/crm/board", headers=headers).json())
    segunda = _entrada(client.get("/crm/board", headers=headers).json())
    assert primeira == segunda
```

- [ ] **Step 2: Rodar e confirmar que falham**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -m pytest tests/test_crm_stage_order.py -v -k "board or fim or estavel"
```

Esperado: `test_board_ordena_por_entrada_e_nao_por_nome` FALHA com `['Amanda', 'Mauricio', 'Zulmira'] != ['Zulmira', 'Amanda', 'Mauricio']` (ainda ordena por nome).

- [ ] **Step 3: Trocar a ordenação**

Em `apps/api/app/modules/crm/service.py`, na função `build_board`, substituir:

```python
    clients = list(db.scalars(select(Client).order_by(Client.name)).all())
```

por:

```python
    # A fila de cada coluna: quem entrou primeiro no topo, quem entra vai para o fim, para o
    # dono atender por ordem de chegada. Desempate por `id` porque no Postgres cards criados
    # na mesma transação compartilham o instante — sem ele a ordem dançaria entre chamadas
    # (mesmo padrão de `_ordered_stages` e `find_duplicate_groups`).
    clients = list(
        db.scalars(select(Client).order_by(Client.stage_entered_at, Client.id)).all()
    )
```

- [ ] **Step 4: Rodar e confirmar que passam**

```bash
$PY -m pytest tests/test_crm_stage_order.py -v
```

Esperado: todos PASS.

- [ ] **Step 5: Rodar a suíte inteira do backend (regressão real)**

```bash
$PY -m pytest -q
```

Esperado: tudo PASS. O ponto de atrito previsto na spec são asserções antigas que dependiam da ordem alfabética do board. Se alguma falhar, **ajustar a asserção** (a ordem nova é a correta), não reverter a mudança — e citar no commit qual teste mudou e por quê.

- [ ] **Step 6: Commit**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
git add apps/api/app/modules/crm/service.py apps/api/tests/
git commit -F - <<'EOF'
feat: o board ordena por entrada na etapa, nao por nome

Cada coluna do Funil vira uma fila FIFO: o mais antigo no topo, quem entra
vai para o fim. Desempate por id para ordem estavel quando o instante empata
(cards criados na mesma transacao no Postgres).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Teste-portão contra o quarto caminho de escrita

**Files:**
- Create: `apps/api/tests/test_crm_stage_order_gate.py`

**Interfaces:**
- Consumes: o código de `apps/api/app/modules/crm/` como texto (varredura AST) — nenhuma importação de runtime.
- Produces: nada consumido por outras tarefas.

**Por que existe:** o risco da coluna (contra a derivação) é o quinto caminho de escrita que alguém adicionar daqui a dois meses esquecer de carimbar. Esse esquecimento **não quebra teste nenhum**: nada estoura, a coluna só passa a mentir sobre a fila. É a mesma classe de problema que `test_tenancy_guard.py` e `test_money_planes.py` já cobrem — invariante sem consumidor mecânico não protesta.

- [ ] **Step 1: Escrever o gate (que já deve passar, dado o estado após a Task 2)**

Criar `apps/api/tests/test_crm_stage_order_gate.py`:

```python
"""Guarda ESTÁTICA da fila do Kanban: quem move card, carimba.

`clients.stage_entered_at` é a ordem da fila de cada coluna do Funil (spec
`2026-08-05-crm-ordem-de-entrada-na-etapa-design.md`). Existem hoje três caminhos que escrevem
`Client.stage_id`, e a spec escolheu uma COLUNA em vez de derivar de `client_events` porque
esse log não registra troca de etapa de forma completa.

O preço dessa escolha é este arquivo. Um quarto caminho que escreva `stage_id` sem carimbar
`stage_entered_at` **não quebra teste nenhum**: nada estoura, nenhuma rota falha, a coluna só
passa a devolver a fila fora de ordem — e o dono atende na ordem errada sem nada avisar.

Mesma família de `test_tenancy_guard.py` e `test_money_planes.py`: varredura barata, sem
ferramenta externa, contra a regressão que os testes de comportamento não alcançam.
"""
from __future__ import annotations

import ast
import pathlib

CRM_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "crm"

CAMPO_ETAPA = "stage_id"
CAMPO_CARIMBO = "stage_entered_at"

# Funções que escrevem `stage_id` e NÃO carimbam, por decisão registrada.
ALLOWLIST = {
    # Arquivar uma etapa é ato administrativo do dono, não mudança na situação do cliente.
    # Recarimbar jogaria todo card da coluna, em bloco, para o fim da fila de destino — e a
    # fila existe justamente para atender por antiguidade. Ver a seção 3 da spec.
    "archive_stage",
}


def _escreve_stage_id(no: ast.FunctionDef) -> bool:
    """A função atribui `stage_id`, por atributo ou dentro de um dict de `.update()`?"""
    for filho in ast.walk(no):
        # `algo.stage_id = ...`
        if isinstance(filho, ast.Assign):
            for alvo in filho.targets:
                if isinstance(alvo, ast.Attribute) and alvo.attr == CAMPO_ETAPA:
                    return True
        # `.update({Client.stage_id: ...})`
        if isinstance(filho, ast.Dict):
            for chave in filho.keys:
                if isinstance(chave, ast.Attribute) and chave.attr == CAMPO_ETAPA:
                    return True
    return False


def _carimba(no: ast.FunctionDef) -> bool:
    for filho in ast.walk(no):
        if isinstance(filho, ast.Assign):
            for alvo in filho.targets:
                if isinstance(alvo, ast.Attribute) and alvo.attr == CAMPO_CARIMBO:
                    return True
        if isinstance(filho, ast.Dict):
            for chave in filho.keys:
                if isinstance(chave, ast.Attribute) and chave.attr == CAMPO_CARIMBO:
                    return True
    return False


def _funcoes_do_crm() -> list[tuple[str, ast.FunctionDef]]:
    encontradas: list[tuple[str, ast.FunctionDef]] = []
    arquivos = sorted(p for p in CRM_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    assert arquivos, f"Nenhum .py encontrado em {CRM_DIR} — teste desatualizado?"
    for arquivo in arquivos:
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.FunctionDef):
                encontradas.append((f"{arquivo.name}::{no.name}", no))
    return encontradas


def test_quem_escreve_stage_id_carimba_stage_entered_at():
    infratores = [
        rotulo
        for rotulo, no in _funcoes_do_crm()
        if _escreve_stage_id(no) and not _carimba(no) and no.name not in ALLOWLIST
    ]
    assert not infratores, (
        f"Função(ões) que movem card entre etapas sem carimbar `{CAMPO_CARIMBO}`: "
        f"{sorted(infratores)}. A ordem das colunas do Kanban é a ordem de entrada na etapa; "
        "sem o carimbo o card entra na fila na posição errada e NADA falha. Carimbe "
        f"`client.{CAMPO_CARIMBO} = datetime.now(UTC)` junto com a troca de `{CAMPO_ETAPA}`, ou "
        "— se a função tiver motivo para preservar a antiguidade — adicione-a à ALLOWLIST "
        "deste arquivo COM o motivo escrito."
    )


def test_allowlist_nao_apodrece():
    """Nome na allowlist que não existe mais é allowlist mentindo sobre o código."""
    nomes = {no.name for _, no in _funcoes_do_crm()}
    fantasmas = sorted(ALLOWLIST - nomes)
    assert not fantasmas, f"ALLOWLIST cita função inexistente: {fantasmas}"
```

- [ ] **Step 2: Rodar e confirmar que passa**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -m pytest tests/test_crm_stage_order_gate.py -v
```

Esperado: 2 PASS.

- [ ] **Step 3: Provar o gate por MUTAÇÃO (senão ele não protege nada)**

Um gate que nunca reprovou é indistinguível de um gate quebrado. Provar que ele pega o defeito real.

⚠️ **Nunca reverter a mutação com `git checkout`** — este arquivo tem trabalho não commitado nas tarefas anteriores. Usar cópia de arquivo:

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
cp app/modules/crm/service.py /tmp/service.py.bak
```

Agora acrescentar ao fim de `app/modules/crm/service.py` uma função que move card sem carimbar:

```python
def mutacao_temporaria(db: Session, *, client_id: str, stage_id: str) -> None:
    cliente = get_client(db, client_id)
    cliente.stage_id = stage_id
```

```bash
$PY -m pytest tests/test_crm_stage_order_gate.py -v
```

Esperado: **FAIL**, citando `service.py::mutacao_temporaria`. Se PASSAR, o gate está cego — corrigir `_escreve_stage_id` antes de seguir.

Restaurar:

```bash
cp /tmp/service.py.bak app/modules/crm/service.py
rm /tmp/service.py.bak
$PY -m pytest tests/test_crm_stage_order_gate.py -v
```

Esperado: 2 PASS de novo.

- [ ] **Step 4: Commit**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
git add apps/api/tests/test_crm_stage_order_gate.py
git commit -F - <<'EOF'
test: gate AST — quem escreve stage_id carimba stage_entered_at

Um quarto caminho de escrita que esquecesse o carimbo nao quebraria teste
nenhum: a coluna so passaria a devolver a fila fora de ordem, em silencio.
Provado por mutacao (funcao que move card sem carimbar reprova o gate).

archive_stage esta na allowlist com o motivo escrito.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: Contrato — `ClientOut` e `shared-types`

**Files:**
- Modify: `apps/api/app/modules/crm/schemas.py` (`ClientOut`)
- Modify: `packages/shared-types/src/index.ts` (interface `Client`)
- Test: `apps/api/tests/test_crm_stage_order.py`

**Interfaces:**
- Consumes: `Client.stage_entered_at` (Task 1).
- Produces: campo `stage_entered_at: string` (ISO, nunca nulo) em toda resposta que devolve cliente — inclusive `BoardClient`, que herda de `ClientOut`. É o campo que a Task 6 lê.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar ao fim de `apps/api/tests/test_crm_stage_order.py`:

```python
def test_api_expoe_stage_entered_at(client: TestClient, headers):
    """Vai em `ClientOut`, não em `BoardClient`: é coluna, sempre conhecida.

    `last_interaction_at` mora em `BoardClient` porque só o board o calcula, e num
    endpoint que não calcula o `null` significaria "não sei" em vez de "não houve". Este
    campo não tem essa ambiguidade — todo card está em algum lugar desde algum instante.
    """
    criado = client.post("/crm/clients", json={"name": "João"}, headers=headers).json()
    assert criado["stage_entered_at"]  # já no POST, que devolve ClientOut

    board = client.get("/crm/board", headers=headers).json()
    card = board["columns"][0]["clients"][0]
    assert card["stage_entered_at"]
    assert card["stage_entered_at"] == criado["stage_entered_at"]
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -m pytest tests/test_crm_stage_order.py::test_api_expoe_stage_entered_at -v
```

Esperado: FAIL com `KeyError: 'stage_entered_at'`.

- [ ] **Step 3: Acrescentar ao schema**

Em `apps/api/app/modules/crm/schemas.py`, na classe `ClientOut`, logo **depois** de `stage_id`:

```python
    # Desde quando o card está nesta etapa — a ordem da fila do Kanban. Fica em `ClientOut`
    # (e não em `BoardClient`, como `last_interaction_at`) porque é coluna: sempre conhecida,
    # nunca "não calculei". Não há o `null` ambíguo que justificou separar o outro campo.
    stage_entered_at: datetime
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
$PY -m pytest tests/test_crm_stage_order.py -v
$PY -m pytest tests/test_crm.py -q
```

Esperado: PASS.

- [ ] **Step 5: Espelhar em `shared-types`**

Em `packages/shared-types/src/index.ts`, na interface `Client`, logo depois de `stage_id`:

```typescript
  /** Desde quando o card está nesta etapa — a ordem da fila no Kanban. ISO 8601, nunca nulo. */
  stage_entered_at: string;
```

(O `generated.ts` está defasado desde o PR #45 e é dívida conhecida — não é escopo desta mudança.)

- [ ] **Step 6: Conferir os tipos do frontend**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
pnpm --filter @e1p/web exec tsc --noEmit
```

Esperado: sem erros.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/crm/schemas.py apps/api/tests/test_crm_stage_order.py packages/shared-types/src/index.ts
git commit -F - <<'EOF'
feat: expoe stage_entered_at no contrato do CRM

Vai em ClientOut, e nao em BoardClient como last_interaction_at: e coluna,
sempre conhecida, entao nenhum endpoint precisa afirmar um null que
significaria "nao calculei".

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: O card mostra as duas datas

**Files:**
- Modify: `apps/web/src/lib/datetime.ts` (helper novo)
- Modify: `apps/web/src/lib/datetime.test.ts`
- Modify: `apps/web/src/features/crm/CrmPage.tsx` (componente `Card`, ~linhas 205-215)
- Modify: `apps/web/src/features/crm/CrmPage.test.tsx`

**Interfaces:**
- Consumes: `client.stage_entered_at` (Task 5), `useFuso()` de `store/auth`.
- Produces: `formatDateShort(iso: string | null | undefined, tz: string): string` → `"05/08"`.

- [ ] **Step 1: Escrever o teste do helper**

Acrescentar a `apps/web/src/lib/datetime.test.ts`:

```typescript
describe("formatDateShort", () => {
  it("devolve dia/mês no fuso do tenant", () => {
    // 2026-08-06T01:30Z é ainda 05/08 em São Paulo (UTC-3).
    expect(formatDateShort("2026-08-06T01:30:00Z", "America/Sao_Paulo")).toBe("05/08");
  });

  it("devolve string vazia para nulo", () => {
    expect(formatDateShort(null, "America/Sao_Paulo")).toBe("");
  });
});
```

Acrescentar `formatDateShort` ao `import` de `./datetime` no topo do arquivo.

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
pnpm --filter @e1p/web test -- datetime
```

Esperado: FAIL — `formatDateShort` não existe.

- [ ] **Step 3: Escrever o helper**

Em `apps/web/src/lib/datetime.ts`, logo depois de `formatDate`:

```typescript
/**
 * Instante → `05/08`. Sem o ano, para caber no card do Kanban.
 *
 * Existe para que o card não volte a chamar `toLocaleDateString` na mão: `lib/datetime.ts` é a
 * única porta de formatação, e a compactação é uma escolha de exibição, não um motivo para
 * sair por fora.
 */
export function formatDateShort(iso: string | null | undefined, tz: string): string {
  return iso ? fmt(iso, tz, { day: "2-digit", month: "2-digit" }) : "";
}
```

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
pnpm --filter @e1p/web test -- datetime
```

Esperado: PASS.

- [ ] **Step 5: Escrever o teste do card**

Em `apps/web/src/features/crm/CrmPage.test.tsx`, o helper `boardComCard(lastInteractionAt)` (~linha 85) monta o card. Acrescentar o campo novo ao objeto do cliente, logo depois de `created_at`:

```typescript
            created_at: "2026-07-01T10:00:00Z",
            stage_entered_at: "2026-07-28T12:00:00Z",
            last_interaction_at: lastInteractionAt,
```

E acrescentar o teste (as duas datas caem no mesmo dia em `America/Sao_Paulo`, que é o `FUSO_PADRAO` devolvido por `useFuso()` fora do provider — 12:00Z é 09:00 em SP, 13:00Z é 10:00):

```typescript
it("mostra as duas datas no card: posição na fila e temperatura da conversa", async () => {
  mockarBoard("2026-08-05T13:00:00Z");
  renderPage();

  expect(await screen.findByText("na etapa desde: 28/07")).toBeInTheDocument();
  expect(await screen.findByText("última interação: 05/08")).toBeInTheDocument();
});
```

- [ ] **Step 6: Rodar e confirmar que falha**

```bash
pnpm --filter @e1p/web test -- CrmPage
```

Esperado: FAIL — o texto "na etapa desde" ainda não é renderizado.

- [ ] **Step 7: Atualizar o `Card`**

Em `apps/web/src/features/crm/CrmPage.tsx`, substituir o bloco atual de `last_interaction_at`:

```tsx
        {client.last_interaction_at && (
          <p className="mt-1 text-[10px] text-neutral-400">
            última interação:{" "}
            {new Date(client.last_interaction_at).toLocaleDateString("pt-BR", {
              timeZone: fuso,
              day: "2-digit",
              month: "2-digit",
            })}
          </p>
        )}
```

por:

```tsx
        {/* As duas datas dizem coisas diferentes: a primeira explica a POSIÇÃO do card na
            fila (a coluna é ordenada por ela), a segunda, o quão fria está a conversa. */}
        <p className="mt-1 text-[10px] text-neutral-400">
          na etapa desde: {formatDateShort(client.stage_entered_at, fuso)}
        </p>
        {client.last_interaction_at && (
          <p className="text-[10px] text-neutral-400">
            última interação: {formatDateShort(client.last_interaction_at, fuso)}
          </p>
        )}
```

Acrescentar ao topo do arquivo:

```tsx
import { formatDateShort } from "../../lib/datetime";
```

Isto também corrige, de passagem, o `toLocaleDateString` na mão que existia ali — `lib/datetime.ts` é a única porta de formatação do projeto, e o card era uma exceção não intencional.

- [ ] **Step 8: Rodar e confirmar que passa**

```bash
pnpm --filter @e1p/web test -- CrmPage
pnpm --filter @e1p/web exec tsc --noEmit
```

Esperado: PASS e sem erro de tipo.

- [ ] **Step 9: Rodar o frontend inteiro (regressão)**

```bash
pnpm --filter @e1p/web test
```

Esperado: tudo PASS.

- [ ] **Step 10: Commit**

```bash
git add apps/web/src/lib/datetime.ts apps/web/src/lib/datetime.test.ts apps/web/src/features/crm/CrmPage.tsx apps/web/src/features/crm/CrmPage.test.tsx
git commit -F - <<'EOF'
feat: card do Kanban mostra "na etapa desde" e "ultima interacao"

A primeira data explica a POSICAO do card na fila (a coluna e ordenada por
ela); a segunda, o quao fria esta a conversa.

Corrige de passagem o toLocaleDateString na mao que existia no card:
lib/datetime.ts e a unica porta de formatacao, e o card era uma excecao nao
intencional. Helper novo formatDateShort (dia/mes, sem ano, para caber).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 7: Provar o backfill contra Postgres real

**Files:**
- Create: `apps/api/tests/test_migration_0068_stage_order_rls.py`

**Interfaces:**
- Consumes: a migration `0068` (Task 1).
- Produces: nada.

**Por que existe:** a suíte unitária monta o schema com `Base.metadata.create_all` — **alembic nunca roda ali**. O backfill da `0068` só é exercido contra Postgres, e o defeito que ele pode ter (no-op silencioso por `FORCE ROW LEVEL SECURITY`) é invisível em SQLite por construção. É exatamente o par de `test_crm_events_rls.py` para a `0067`.

- [ ] **Step 1: Escrever o teste**

Criar `apps/api/tests/test_migration_0068_stage_order_rls.py`. O bootstrap é copiado de `tests/test_crm_events_rls.py` (mesmo padrão de `test_receipts_rls.py`):

```python
"""Migration 0068 (backfill de `stage_entered_at`) sob RLS REAL.

O fato que a suíte SQLite é estruturalmente incapaz de provar: **o backfill não é no-op.**
`clients` tem FORCE ROW LEVEL SECURITY e a migration roda como o papel não-superusuário
`e1p_app` sem GUC de tenant. Se a janela de DISABLE/ENABLE sumisse, o UPDATE afetaria zero
linhas SEM ERRO NENHUM — e o sintoma em produção não seria uma falha de deploy, seria "a
fila do Kanban continua fora de ordem", meses depois.

Semeamos `clients` e `client_events` parando na 0067 e só então aplicamos a 0068: backfill
sobre tabela vazia é indistinguível de backfill no-op, que é o bug que este arquivo existe
para pegar.

Marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job `cross-tenant-rls` do
CI ou manualmente com Docker (`pytest -m rls_e2e`).
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


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _run_migrations_as_app(app_url: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, revision)
    finally:
        settings.database_url = original_url


# (nome, created_at do cliente, kind do evento ou None, created_at do evento, esperado)
SEMENTES = [
    ("Sem Evento", "2026-07-01", None, None, "2026-07-01"),
    ("Com Move", "2026-07-01", "stage_move", "2026-07-20", "2026-07-20"),
    ("Com Reopen", "2026-07-02", "reopened", "2026-07-25", "2026-07-25"),
    # `lead_created` NÃO é troca de etapa: tem que cair em `created_at`, não no evento.
    ("So Lead Created", "2026-07-03", "lead_created", "2026-07-28", "2026-07-03"),
]


@pytest.fixture(scope="module")
def ambiente():
    """Sobe Postgres, migra até 0067, SEMEIA, e só então aplica a 0068."""
    with PostgresContainer(
        "postgres:16-alpine",
        username=_ROOT_USER,
        password=_ROOT_PASS,
        dbname=_DB_NAME,
        driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url, "0067")

        tenant_a = str(uuid4())
        engine = create_engine(app_url, poolclass=NullPool)
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_a}
            )
            for nome, criado_em, kind, evento_em, _esperado in SEMENTES:
                client_id = str(uuid4())
                conn.execute(
                    text(
                        "INSERT INTO clients (id, tenant_id, name, gender, notes, tags, "
                        "source, created_at, updated_at) VALUES "
                        "(:id, :t, :n, 'unspecified', '', '[]'::json, 'landing', "
                        ":criado, :criado)"
                    ),
                    {"id": client_id, "t": tenant_a, "n": nome, "criado": criado_em},
                )
                if kind is not None:
                    conn.execute(
                        text(
                            "INSERT INTO client_events (id, tenant_id, client_id, kind, "
                            "title, body, actor, is_ai, created_at, updated_at) VALUES "
                            "(:id, :t, :c, :k, 'x', '', 'teste', false, :quando, :quando)"
                        ),
                        {
                            "id": str(uuid4()), "t": tenant_a, "c": client_id,
                            "k": kind, "quando": evento_em,
                        },
                    )
        engine.dispose()

        # AGORA a 0068 — o backfill encontra linhas de verdade.
        _run_migrations_as_app(app_url, "0068")

        yield {"url": app_url, "tenant_a": tenant_a}


def test_backfill_nao_foi_no_op(ambiente):
    """Se a janela de RLS sumisse, TODAS viriam NULL — e o deploy não reclamaria."""
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"),
                {"t": ambiente["tenant_a"]},
            )
            linhas = conn.execute(
                text("SELECT name, stage_entered_at FROM clients ORDER BY name")
            ).fetchall()

        obtido = {linha.name: linha.stage_entered_at for linha in linhas}
        assert len(obtido) == len(SEMENTES)
        assert all(v is not None for v in obtido.values()), f"backfill foi no-op: {obtido}"

        for nome, _criado, _kind, _quando, esperado in SEMENTES:
            assert obtido[nome].strftime("%Y-%m-%d") == esperado, (
                f"{nome}: esperado {esperado}, veio {obtido[nome]}"
            )
    finally:
        engine.dispose()


def test_rls_de_clients_foi_restaurada(ambiente):
    """A janela do backfill DESLIGA a RLS. Esquecer de religar abre a tabela em produção.

    Sem esta asserção, uma 0068 que abrisse `clients` e não fechasse passaria feliz no
    teste acima — o backfill teria funcionado, e o vazamento seria invisível.
    """
    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.begin() as conn:
            linha = conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'clients'"
                )
            ).one()
        assert linha.relrowsecurity is True, "RLS de `clients` ficou DESLIGADA após a 0068"
        assert linha.relforcerowsecurity is True, "FORCE de `clients` não foi restaurado"
    finally:
        engine.dispose()
```

- [ ] **Step 2: Rodar (exige Docker)**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -m pytest tests/test_migration_0068_stage_order_rls.py -m rls_e2e -v
```

Esperado: PASS. Se o Docker não estiver disponível, o `pytest.importorskip("testcontainers.postgres")` faz o arquivo ser pulado — **nesse caso, registrar no PR que a validação real não rodou localmente** e deixar o job `cross-tenant-rls` do CI ser a prova. Não afirmar que passou sem ter visto passar.

- [ ] **Step 3: Provar por mutação que o teste pega o defeito**

```bash
cp migrations/versions/0068_client_stage_entered_at.py /tmp/0068.bak
```

Comentar as duas linhas `ALTER TABLE clients DISABLE/ENABLE ROW LEVEL SECURITY` da migration e rodar de novo.

Esperado: **FAIL** (linhas com `stage_entered_at IS NULL`, ou o `alter_column` para `NOT NULL` estourando). Se passar, o teste não está provando nada — corrigir antes de seguir.

Restaurar:

```bash
cp /tmp/0068.bak migrations/versions/0068_client_stage_entered_at.py && rm /tmp/0068.bak
$PY -m pytest tests/test_migration_0068_stage_order_rls.py -m rls_e2e -v
```

- [ ] **Step 4: Commit**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
git add apps/api/tests/test_migration_0068_stage_order_rls.py
git commit -F - <<'EOF'
test: prova que o backfill da 0068 nao e no-op sob RLS real

clients tem FORCE ROW LEVEL SECURITY e a migration roda como e1p_app sem GUC
de tenant: sem a janela de DISABLE/ENABLE o UPDATE seria filtrado a zero
linhas em silencio. SQLite nao alcanca isso (create_all, sem alembic).

Confere tambem que a RLS foi RESTAURADA — sem essa asercao, esquecer o
ENABLE deixaria a tabela aberta e o teste passaria feliz.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 8: Fechamento — check completo, CLAUDE.md e PR

**Files:**
- Modify: `CLAUDE.md` (seção do CRM)

- [ ] **Step 1: Rodar as etapas de verificação individualmente**

`scripts/check.sh` mascara falha de frontend com `|| true` no vitest (dívida registrada no CLAUDE.md) — **não confiar nele**. Rodar separado:

```bash
PY=/f/Projetos/e1p/escritorio-1-pessoa/apps/api/.venv/Scripts/python.exe
cd /f/Projetos/e1p/e1p-whatsapp-evolution/apps/api
$PY -m ruff check app tests
$PY -m pytest -q

cd /f/Projetos/e1p/e1p-whatsapp-evolution
pnpm --filter @e1p/web exec tsc --noEmit
pnpm --filter @e1p/web test
```

Todas as quatro precisam passar. Colar a saída real no PR — não afirmar sucesso sem ter visto.

- [ ] **Step 2: Registrar no CLAUDE.md**

Na seção **"CRM: a jornada única do contato (um card por pessoa)"**, acrescentar um item na lista de superfícies:

```markdown
- [x] **A coluna do Kanban é uma FILA por ordem de entrada na etapa** (`clients.stage_entered_at`,
  migration 0068). Antes ordenava por `Client.name`, e como a maioria dos leads entra pelo
  WhatsApp sem nome resolvido o "nome" é o telefone — a Entrada aparecia em ordem numérica de
  DDI. Agora o mais antigo fica no topo e quem entra vai para o fim, para o dono atender por
  ordem de chegada. **É coluna e não derivação de `client_events`** (ao contrário de
  `last_interaction_at`, logo acima) porque o log não registra troca de etapa de forma
  completa: `move_client` grava `stage_move`, a reabertura do `absorb_lead` grava `reopened`,
  e **`archive_stage` remaneja em massa sem evento nenhum** — não é derivado materializado, é
  fato primário que não tinha onde morar. O preço da coluna é o gate AST
  (`tests/test_crm_stage_order_gate.py`): um quarto caminho de escrita que esquecesse o
  carimbo não quebraria teste nenhum, a fila só passaria a mentir. **`archive_stage` preserva
  a antiguidade de propósito** (allowlist do gate): arquivar é ato administrativo do dono, e
  recarimbar jogaria a coluna inteira, em bloco, para o fim da fila de destino.
```

- [ ] **Step 3: Commit e push da branch**

```bash
cd /f/Projetos/e1p/e1p-whatsapp-evolution
git add CLAUDE.md
git commit -F - <<'EOF'
docs: registra a fila por ordem de entrada na etapa no CLAUDE.md

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
git push -u origin feat/crm-ordem-de-entrada-na-etapa
```

⚠️ `git push` é operação **exclusiva de @devops** pela matriz de autoridade do AIOX, e `main` é protegida. Push da **branch** (não de `main`) é o caminho normal aqui, mas confirmar com o usuário antes de abrir o PR.

- [ ] **Step 4: Abrir o PR**

```bash
gh pr create --title "feat: a coluna do Kanban vira fila por ordem de entrada na etapa" --body "$(cat <<'EOF'
## O que muda

Cada coluna do Funil de clientes passa a listar os cards por **ordem de entrada naquela etapa** — o mais antigo no topo, quem entra vai para o fim — para atender em ordem de chegada.

Antes o board ordenava por `Client.name`. Como a maioria dos leads entra pelo WhatsApp sem nome resolvido, o "nome" é o telefone e a Entrada aparecia em ordem numérica de DDI.

## Por que uma coluna e não derivação de `client_events`

Os três caminhos que escrevem `Client.stage_id` registram coisas diferentes: `move_client` grava `stage_move`, a reabertura do `absorb_lead` grava `reopened`, e **`archive_stage` remaneja em massa sem evento nenhum**. O log também é mais novo que os cards (nasceu na 0067). Não é valor derivado materializado — é fato primário que não tinha onde morar.

O preço da coluna é o gate AST: um quarto caminho de escrita que esquecesse o carimbo não quebraria teste nenhum. Provado por mutação.

## Decisão de produto

**`archive_stage` preserva a antiguidade.** Arquivar uma etapa é ato administrativo do dono, não mudança na situação do cliente — recarimbar jogaria todo card da coluna, em bloco, para o fim da fila de destino.

## Migration 0068

Backfill dentro de janela com a RLS desabilitada. Sem ela o `UPDATE` seria filtrado a zero linhas **em silêncio** (armadilha da 0046/0066/0067), e o sintoma em produção seria "a fila continua fora de ordem", não uma falha de deploy. Coberto por `test_migration_0068_stage_order_rls.py` (`rls_e2e`).

## Spec e plano

- `docs/superpowers/specs/2026-08-05-crm-ordem-de-entrada-na-etapa-design.md`
- `docs/superpowers/plans/2026-08-05-crm-ordem-de-entrada-na-etapa.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Ordem de execução e dependências

```
Task 1 (coluna + migration)
  └─> Task 2 (carimbar) ──> Task 3 (ordenar) ──> Task 6 (card)
  └─> Task 5 (contrato) ──────────────────────────┘
  └─> Task 7 (backfill sob Postgres real)
Task 4 (gate) — depois da Task 2
Task 8 (fechamento) — por último
```

Tasks 4, 5 e 7 são independentes entre si depois das suas dependências e podem ir em paralelo.
