# Onda 1 — Conversa na ficha do contato: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ficha do contato (`/crm/clients/:id`) passa a mostrar a conversa de WhatsApp daquele contato, o card do Kanban ganha um ponto quando há mensagem esperando resposta, e uma conversa passa a ter URL própria.

**Architecture:** Cada módulo continua dono do seu dado. O `whatsapp_inbox` ganha um filtro por `client_id` na lista de conversas e uma função agregada `unread_client_ids` para o board; o CRM consome as duas sem saber formatar conversa. Nenhuma migration — o vínculo `whatsapp_chats.client_id` já existe.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend, Python 3.12); React + TypeScript + Vite + Tailwind (frontend); pytest (API), Vitest + Testing Library (web), Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-08-16-crm-conversa-e-agenda-na-ficha-design.md`

## Global Constraints

- **Diretório de trabalho:** `f:\Projetos\e1p\escritorio-1-pessoa`. Todos os caminhos deste plano são relativos a ele.
- **Nunca commitar em `main`.** `main` é protegida (rejeita push direto, GH006). Trabalhe em branch e abra PR.
- **`git push` e `gh pr create` são exclusivos do @devops.** Não faça push. Commite localmente e reporte.
- **Rodar os testes em primeiro plano**, nunca em background.
- **Fuso:** todo instante exibido usa o fuso do TENANT — `useFuso()` + `lib/datetime` no front, `hoje_do_tenant(db)` no back. Formatar com `toLocaleString` sem `timeZone` é regressão conhecida neste repo.
- **Rede sempre mockada em teste de web** (`vi.mock("../../lib/api", ...)`). Nenhum teste bate em API real.
- **Comentário em português**, explicando o *porquê* e não o *o quê* — é a convenção do repo inteiro.
- **Testes de API rodam em SQLite em memória**; RLS não é exercida ali (ver `apps/api/tests/conftest.py`).

**Comandos:**

```bash
# API (do diretório apps/api)
.venv/Scripts/python.exe -m pytest tests/test_arquivo.py -v
# ⚠️ OBRIGATÓRIO em toda tarefa que toca Python. O CI roda
# `ruff check . && pytest` DENTRO da imagem (.github/workflows/ci.yml:47) — um E501
# derruba o build antes de qualquer teste rodar. Limite: 100 colunas.
.venv/Scripts/python.exe -m ruff check .

# Web (da raiz do repo)
pnpm --filter @e1p/web test
pnpm --filter @e1p/web typecheck
pnpm --filter @e1p/web lint
```

**Antes de começar:** crie a branch de trabalho **a partir de `spec/crm-conversa-e-agenda-na-ficha`**, não de `main`. A spec e este plano vivem lá e ainda não foram mesclados (`main` é protegida e exige PR até para mudança só de documentação).

```bash
git checkout spec/crm-conversa-e-agenda-na-ficha
git checkout -b feat/onda-1-conversa-na-ficha
git log --oneline -2   # confirme que a spec e o plano estão no histórico
```

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `apps/api/app/modules/whatsapp_inbox/service.py` | `unread_client_ids()` e o filtro `client_id` em `list_conversations()` — o módulo dono da regra de "não lida" | Modificar |
| `apps/api/app/modules/whatsapp_inbox/router.py` | Query param `client_id` no `GET ""` | Modificar |
| `apps/api/app/modules/crm/schemas.py` | `BoardClient.unread` | Modificar |
| `apps/api/app/modules/crm/router.py` | O board consome `unread_client_ids` | Modificar |
| `apps/api/tests/test_whatsapp_inbox_nao_lidas.py` | Paridade entre as duas definições de "não lida" + filtro | Criar |
| `apps/api/tests/test_crm_board_nao_lida.py` | O board devolve `unread` | Criar |
| `packages/shared-types/src/index.ts` | `BoardClient.unread` | Modificar |
| `apps/web/src/features/crm/BlocoDaConversa.tsx` | O bloco de conversa da ficha — arquivo próprio porque `ClientDetailPage` já tem 426 linhas | Criar |
| `apps/web/src/features/crm/BlocoDaConversa.test.tsx` | Testes do bloco | Criar |
| `apps/web/src/features/crm/ClientDetailPage.tsx` | Hospeda o bloco novo | Modificar |
| `apps/web/src/features/crm/CrmPage.tsx` | O ponto no card | Modificar |
| `apps/web/src/features/conversas/ConversasPage.tsx` | Seleção vem da URL | Modificar |
| `apps/web/src/app/App.tsx` | Rota `/conversas/:chatId` | Modificar |

**Ordem:** Tarefas 1→2 são backend (o contrato), 3 é o tipo compartilhado, 4→6 são frontend. Cada tarefa termina com commit e é revisável sozinha.

---

### Task 1: `unread_client_ids` — a mesma definição de "não lida", em forma agregada

O card do Kanban precisa saber quais contatos têm mensagem esperando resposta. Não dá para reusar `list_conversations` para isso: ela carrega **todas** as mensagens do tenant em memória para achar a última de cada chat (`select(WhatsappMessage).order_by(created_at)`, linha ~547). A tela de Conversas tolera; o board, aberto a cada navegação, não.

O risco é criar uma **segunda definição de "não lida"** que diverge da primeira em silêncio — o card diria "esperando resposta" com a caixa de entrada limpa. Por isso a função nova mora no mesmo módulo, colada na antiga, e um teste afirma que as duas concordam.

**Files:**
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py` (adicionar após `list_conversations`, que termina por volta da linha 576)
- Test: `apps/api/tests/test_whatsapp_inbox_nao_lidas.py` (criar)

**Interfaces:**
- Consumes: `WhatsappChat`, `WhatsappMessage`, `DIRECTION_IN` de `app.modules.whatsapp_inbox.models`; `list_conversations(db, tenant_id) -> list[dict]` já existente.
- Produces: `unread_client_ids(db: Session) -> set[str]` — ids de `clients` com mensagem esperando resposta. Consumido pela Task 2.

- [ ] **Step 1: Escrever o teste de paridade (vai falhar)**

Crie `apps/api/tests/test_whatsapp_inbox_nao_lidas.py`:

```python
# apps/api/tests/test_whatsapp_inbox_nao_lidas.py
"""`unread_client_ids` — o agregado que alimenta o ponto do card do Kanban.

O teste central aqui é o de PARIDADE. A regra de "não lida" vive inline dentro de
`list_conversations`; este agregado é uma segunda expressão da mesma regra, escrita porque
`list_conversations` carrega todas as mensagens do tenant em memória e o board não pode pagar
isso. Duas expressões da mesma regra divergem em silêncio — o card diria "esperando resposta"
com a caixa de entrada limpa. O teste de paridade é o que impede isso.
"""
from datetime import UTC, datetime, timedelta

from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_DIRECT,
    CHAT_KIND_GROUP,
    DIRECTION_IN,
    DIRECTION_OUT,
    WhatsappChat,
    WhatsappMessage,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"
BASE = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _chat(db, *, jid: str, client_id: str | None, kind: str = CHAT_KIND_DIRECT,
          last_read_at: datetime | None = None) -> WhatsappChat:
    chat = WhatsappChat(
        tenant_id=TENANT_ID, chat_jid=jid, kind=kind, title=jid,
        client_id=client_id, last_read_at=last_read_at,
    )
    db.add(chat)
    db.commit()
    return chat


def _msg(db, *, chat: WhatsappChat, direction: str, minutos: int, texto: str = "oi") -> None:
    db.add(WhatsappMessage(
        tenant_id=TENANT_ID, chat_id=chat.id, client_id=chat.client_id,
        direction=direction, text_body=texto,
        created_at=BASE + timedelta(minutes=minutos),
    ))
    db.commit()


def _cenario_completo(db) -> None:
    """As cinco situações que a regra precisa distinguir."""
    # 1. Nunca lida, última é do contato → ESPERANDO RESPOSTA.
    c1 = _chat(db, jid="5511900000001@s.whatsapp.net", client_id="cli-1")
    _msg(db, chat=c1, direction=DIRECTION_IN, minutos=10)

    # 2. Lida DEPOIS da última mensagem → em dia.
    c2 = _chat(db, jid="5511900000002@s.whatsapp.net", client_id="cli-2",
               last_read_at=BASE + timedelta(minutes=99))
    _msg(db, chat=c2, direction=DIRECTION_IN, minutos=10)

    # 3. Última mensagem é NOSSA → em dia, mesmo sem nunca ter sido "lida".
    c3 = _chat(db, jid="5511900000003@s.whatsapp.net", client_id="cli-3")
    _msg(db, chat=c3, direction=DIRECTION_IN, minutos=10)
    _msg(db, chat=c3, direction=DIRECTION_OUT, minutos=20)

    # 4. GRUPO com mensagem nova → nunca conta: grupo não é contato do CRM.
    g = _chat(db, jid="120363000000000000@g.us", client_id=None, kind=CHAT_KIND_GROUP)
    _msg(db, chat=g, direction=DIRECTION_IN, minutos=10)

    # 5. DOIS chats para o MESMO contato (o caso `@lid` + telefone). Um em dia, outro não —
    #    o contato aparece uma vez só, porque o conjunto é de CONTATOS, não de conversas.
    c5a = _chat(db, jid="5511900000005@s.whatsapp.net", client_id="cli-5",
                last_read_at=BASE + timedelta(minutes=99))
    _msg(db, chat=c5a, direction=DIRECTION_IN, minutos=10)
    c5b = _chat(db, jid="99995@lid", client_id="cli-5")
    _msg(db, chat=c5b, direction=DIRECTION_IN, minutos=30)


def test_unread_client_ids_distingue_as_cinco_situacoes(db):
    _cenario_completo(db)
    assert inbox_service.unread_client_ids(db) == {"cli-1", "cli-5"}


def test_unread_client_ids_concorda_com_list_conversations(db):
    """PARIDADE — a guarda contra as duas definições divergirem.

    Se alguém ajustar a regra em um dos dois lugares e esquecer o outro, este teste cai.
    """
    _cenario_completo(db)
    pela_caixa_de_entrada = {
        c["client_id"]
        for c in inbox_service.list_conversations(db, TENANT_ID)
        if c["unread"] and c["client_id"]
    }
    assert inbox_service.unread_client_ids(db) == pela_caixa_de_entrada


def test_unread_client_ids_vazio_sem_mensagem(db):
    _chat(db, jid="5511900000009@s.whatsapp.net", client_id="cli-9")
    assert inbox_service.unread_client_ids(db) == set()
```

- [ ] **Step 2: Rodar e confirmar que falha**

```bash
cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_nao_lidas.py -v
```

Esperado: FAIL com `AttributeError: module 'app.modules.whatsapp_inbox.service' has no attribute 'unread_client_ids'`.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/whatsapp_inbox/service.py`, **logo depois** de `list_conversations` (a proximidade física é parte da guarda — quem edita uma vê a outra):

> ⚠️ **Não amarre a consulta ao dialeto.** A tentação aqui é desempatar mensagens do mesmo instante com `func.strftime` (SQLite) ou `func.to_char` (Postgres) num `if`. Não faça: os testes rodam em SQLite e produção é Postgres, então o ramo do Postgres não seria exercido por teste nenhum. A versão abaixo é dialeto-agnóstica porque não precisa saber *qual* é a última mensagem — só se a conversa terminou com o contato falando.

```python
def unread_client_ids(db: Session) -> set[str]:
    """Contatos com mensagem esperando resposta, para o ponto no card do Kanban.

    ⚠️ ESTA É A MESMA REGRA de `list_conversations` acima ("a última mensagem da conversa é do
    contato e chegou depois do `last_read_at`"), escrita uma segunda vez. Mexeu em uma, mexa na
    outra — `test_whatsapp_inbox_nao_lidas.py::test_unread_client_ids_concorda_com_list_conversations`
    existe exatamente para pegar quem esquecer.

    A duplicação é deliberada: `list_conversations` materializa TODAS as mensagens do tenant
    para achar a última de cada chat. A tela de Conversas paga esse preço uma vez a cada 7s
    para um usuário; o board não pode pagá-lo a cada navegação. Aqui é uma consulta agregada,
    de custo independente do volume de mensagens.

    Devolve CONTATOS, não conversas: o mesmo contato pode ter dois chats (`@lid` + telefone) e
    o card é um só. Grupo nunca entra — `client_id` é nulo nele por decisão de produto.

    A sessão já chega escopada por RLS (mesma convenção de `list_conversations`).
    """
    # Últimas mensagens: uma linha por chat, obtida por max(created_at) agrupado. Empate de
    # instante (duas mensagens no mesmo commit) resolve-se pegando qualquer uma das empatadas
    # e checando se ALGUMA delas é `in` — que é a pergunta que interessa. Não precisamos saber
    # qual é "a" última, só se a conversa terminou com o contato falando.
    max_por_chat = (
        select(
            WhatsappMessage.chat_id.label("chat_id"),
            func.max(WhatsappMessage.created_at).label("ultima_em"),
        )
        .where(WhatsappMessage.chat_id.is_not(None))
        .group_by(WhatsappMessage.chat_id)
        .subquery()
    )
    linhas = db.execute(
        select(WhatsappChat.client_id)
        .join(max_por_chat, max_por_chat.c.chat_id == WhatsappChat.id)
        .join(
            WhatsappMessage,
            (WhatsappMessage.chat_id == WhatsappChat.id)
            & (WhatsappMessage.created_at == max_por_chat.c.ultima_em),
        )
        .where(
            WhatsappChat.client_id.is_not(None),
            WhatsappMessage.direction == DIRECTION_IN,
            (WhatsappChat.last_read_at.is_(None))
            | (max_por_chat.c.ultima_em > WhatsappChat.last_read_at),
        )
    ).all()
    return {client_id for (client_id,) in linhas}
```

Confirme que o topo do arquivo já importa `func` de `sqlalchemy` e `select`; se `func` faltar, adicione ao import existente.

- [ ] **Step 4: Rodar e confirmar que passa**

```bash
cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_nao_lidas.py -v
```

Esperado: 3 passed.

- [ ] **Step 5: Rodar a suíte do inbox inteira (nada pode ter quebrado)**

```bash
cd apps/api && .venv/Scripts/python.exe -m pytest tests/ -k "whatsapp" -v
```

Esperado: tudo verde. Se algo falhar, é regressão sua — conserte antes de commitar.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/whatsapp_inbox/service.py apps/api/tests/test_whatsapp_inbox_nao_lidas.py
git commit -m "feat: unread_client_ids, o agregado de 'esperando resposta' para o board"
```

---

### Task 2: O filtro `client_id` na lista de conversas, e o board devolvendo `unread`

**Files:**
- Modify: `apps/api/app/modules/whatsapp_inbox/service.py` (assinatura de `list_conversations`)
- Modify: `apps/api/app/modules/whatsapp_inbox/router.py:153-157`
- Modify: `apps/api/app/modules/crm/schemas.py:169-178`
- Modify: `apps/api/app/modules/crm/router.py:38-59`
- Test: `apps/api/tests/test_whatsapp_inbox_nao_lidas.py` (acrescentar), `apps/api/tests/test_crm_board_nao_lida.py` (criar)

**Interfaces:**
- Consumes: `unread_client_ids(db) -> set[str]` da Task 1.
- Produces: `GET /whatsapp-conversations?client_id=<id>` devolvendo só as conversas daquele contato; `BoardClient.unread: bool` no `GET /crm/board`. Consumidos pelas Tasks 4 e 5.

- [ ] **Step 1: Escrever os testes (vão falhar)**

Acrescente ao fim de `apps/api/tests/test_whatsapp_inbox_nao_lidas.py`:

```python
def test_list_conversations_filtra_por_client_id(db):
    _cenario_completo(db)
    do_contato = inbox_service.list_conversations(db, TENANT_ID, client_id="cli-5")
    assert len(do_contato) == 2  # o caso `@lid` + telefone: duas conversas, um contato
    assert {c["client_id"] for c in do_contato} == {"cli-5"}


def test_list_conversations_sem_filtro_continua_trazendo_grupo(db):
    """O filtro é OPCIONAL e não pode mudar o comportamento da tela de Conversas."""
    _cenario_completo(db)
    todas = inbox_service.list_conversations(db, TENANT_ID)
    assert any(c["kind"] == "group" for c in todas)


def test_list_conversations_filtrado_nunca_traz_grupo(db):
    """Grupo tem `client_id` nulo — filtrar por contato jamais pode trazê-lo."""
    _cenario_completo(db)
    for cid in ("cli-1", "cli-5"):
        assert all(c["kind"] != "group" for c in inbox_service.list_conversations(
            db, TENANT_ID, client_id=cid))
```

Crie `apps/api/tests/test_crm_board_nao_lida.py`:

```python
# apps/api/tests/test_crm_board_nao_lida.py
"""O board do Kanban devolve `unread` por card — o ponto de 'esperando resposta'."""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.modules.crm.models import Client
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_DIRECT,
    DIRECTION_IN,
    WhatsappChat,
    WhatsappMessage,
)

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
    """`/crm/board` é rota autenticada — sem isto tudo aqui é 401. Mesmo padrão de
    `test_crm.py`."""
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _contato(client: TestClient, headers: dict[str, str], nome: str) -> str:
    """Cria pela API, e não montando o modelo à mão.

    O contato precisa nascer no tenant AUTENTICADO e na primeira etapa do funil — `POST
    /crm/clients` faz as duas coisas (`create_client` chama `ensure_stages`). Um `Client(...)`
    direto no banco com `tenant_id` inventado passaria em SQLite, onde não há RLS, e mediria
    uma situação que não existe em produção.
    """
    resp = client.post("/crm/clients", json={"name": nome}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _conversa_esperando(db, client_id: str) -> None:
    """Uma mensagem do contato, nunca lida. O `tenant_id` vem do próprio contato."""
    contato = db.get(Client, client_id)
    chat = WhatsappChat(
        tenant_id=contato.tenant_id, chat_jid=f"5511{client_id[:9]}@s.whatsapp.net",
        kind=CHAT_KIND_DIRECT, client_id=client_id,
    )
    db.add(chat)
    db.commit()
    db.add(WhatsappMessage(
        tenant_id=contato.tenant_id, chat_id=chat.id, client_id=client_id,
        direction=DIRECTION_IN, text_body="oi, tudo bem?",
        created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    ))
    db.commit()


def _cards(payload: dict) -> dict[str, dict]:
    return {c["id"]: c for col in payload["columns"] for c in col["clients"]}


def test_board_marca_unread_so_em_quem_espera_resposta(client, db, headers):
    esperando = _contato(client, headers, "Quem escreveu")
    quieto = _contato(client, headers, "Quem nao escreveu")
    _conversa_esperando(db, esperando)

    resp = client.get("/crm/board", headers=headers)
    assert resp.status_code == 200
    cards = _cards(resp.json())
    assert cards[esperando]["unread"] is True
    assert cards[quieto]["unread"] is False


def test_board_unread_e_sempre_booleano(client, db, headers):
    """Nunca `null`: o card decide mostrar o ponto ou não, e não tem terceiro estado."""
    _contato(client, headers, "Sem conversa nenhuma")
    cards = _cards(client.get("/crm/board", headers=headers).json())
    assert cards, "o board veio sem card nenhum — o teste não mediu nada"
    assert all(isinstance(c["unread"], bool) for c in cards.values())


def _consultas_do_board(client, headers, engine) -> int:
    """Quantas consultas SQL um GET /crm/board dispara."""
    from sqlalchemy import event

    contador = []

    def _antes(_conn, _cursor, statement, _params, _context, _many):
        contador.append(statement)

    event.listen(engine, "before_cursor_execute", _antes)
    try:
        assert client.get("/crm/board", headers=headers).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _antes)
    return len(contador)


def test_board_nao_faz_uma_consulta_por_card(client, db, headers):
    """Dobrar os cards não pode dobrar as consultas.

    O jeito errado de implementar `unread` é perguntar por contato, dentro do laço que monta
    as colunas. Funciona no teste de duas linhas e derruba o board de quem tem 200 leads no
    funil — e a falha é invisível em qualquer teste que só olhe o JSON de resposta.

    Este é o mesmo motivo pelo qual `last_interaction_map` existe como consulta agrupada.
    """
    engine = db.get_bind()
    for i in range(2):
        _conversa_esperando(db, _contato(client, headers, f"Contato {i}"))
    com_2 = _consultas_do_board(client, headers, engine)

    for i in range(2, 8):
        _conversa_esperando(db, _contato(client, headers, f"Contato {i}"))
    com_8 = _consultas_do_board(client, headers, engine)

    assert com_8 == com_2, (
        f"{com_2} consultas com 2 cards e {com_8} com 8 — o custo está crescendo com os cards"
    )
```

- [ ] **Step 2: Rodar e confirmar que falham**

```bash
cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_nao_lidas.py tests/test_crm_board_nao_lida.py -v
```

Esperado: os 3 novos do primeiro arquivo falham com `TypeError: list_conversations() got an unexpected keyword argument 'client_id'`; os 3 do segundo falham com `KeyError: 'unread'` (o de contagem de consultas passa desde já, e é isso mesmo — ele é uma trava contra a implementação errada, não um teste de funcionalidade nova).

- [ ] **Step 3: Implementar o filtro no service**

Em `apps/api/app/modules/whatsapp_inbox/service.py`, mude a assinatura de `list_conversations`:

```python
def list_conversations(
    db: Session, tenant_id: str, *, client_id: str | None = None
) -> list[dict]:
```

Acrescente ao fim da docstring existente:

```
    `client_id` filtra as conversas de UM contato (a ficha 360° usa isso). Grupo tem
    `client_id` nulo e portanto nunca aparece filtrado — que é o correto: grupo não é contato
    do CRM. Um contato pode ter MAIS DE UMA conversa (`@lid` + telefone), então a lista
    filtrada não tem tamanho garantido de 1.
```

E filtre a carga de chats logo na primeira linha do corpo:

```python
    consulta_chats = select(WhatsappChat)
    if client_id is not None:
        consulta_chats = consulta_chats.where(WhatsappChat.client_id == client_id)
    chats = {c.id: c for c in db.scalars(consulta_chats).all()}
```

(substituindo o `chats = {c.id: c for c in db.scalars(select(WhatsappChat)).all()}` que está lá). O resto da função já ignora mensagem cujo `chat_id` não está em `chats`, então nada mais muda.

- [ ] **Step 4: Implementar o query param no router**

Em `apps/api/app/modules/whatsapp_inbox/router.py`, troque o handler da linha 153:

```python
@router.get("")
def list_conversations(
    client_id: str | None = Query(default=None),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[dict]:
    return service.list_conversations(db, user.tenant_id, client_id=client_id)
```

Confirme que `Query` está importado de `fastapi` no topo do arquivo; se não, adicione ao import existente.

- [ ] **Step 5: Implementar `unread` no board**

Em `apps/api/app/modules/crm/schemas.py`, na classe `BoardClient` (linha 169):

```python
class BoardClient(ClientOut):
    """`ClientOut` + os sinais que só o board calcula.

    Campos separados do `ClientOut` de propósito: só o board calcula isso (via consultas
    agrupadas). Se vivessem em `ClientOut`, todo endpoint que devolve cliente passaria a
    afirmar `null` — e `null` significaria tanto "sem interação" quanto "não calculei", que
    são coisas diferentes.
    """

    last_interaction_at: datetime | None = None
    # Tem mensagem do contato esperando resposta. Booleano e não contador: o card não tem
    # espaço para número, e "quantas" é pergunta da tela de Conversas.
    unread: bool = False
```

Em `apps/api/app/modules/crm/router.py`, no `get_board` (linha 38):

```python
@router.get("/board", response_model=Board)
def get_board(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> Board:
    columns = service.build_board(db, user.tenant_id)
    ultimo = service.last_interaction_map(db)
    # Consulta agregada, uma para o board inteiro — o custo não cresce com a quantidade de
    # cards. Lida do módulo DONO da regra de "não lida" em vez de reimplementada aqui.
    esperando = inbox_service.unread_client_ids(db)
    return Board(
        columns=[
            BoardColumn(
                stage=StageOut.model_validate(stage),
                clients=[
                    BoardClient(
                        **ClientOut.model_validate(c).model_dump(),
                        last_interaction_at=ultimo.get(c.id),
                        unread=c.id in esperando,
                    )
                    for c in clients
                ],
            )
            for stage, clients in columns
        ]
    )
```

Adicione o import no topo de `crm/router.py`:

```python
from app.modules.whatsapp_inbox import service as inbox_service
```

> ⚠️ Se esse import causar ciclo (o `whatsapp_inbox` importar `crm`), **não** resolva movendo a função: importe dentro da função `get_board`, com um comentário explicando. Rode `.venv/Scripts/python.exe -c "import app.main"` para checar.

- [ ] **Step 6: Rodar e confirmar que passam**

```bash
cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_whatsapp_inbox_nao_lidas.py tests/test_crm_board_nao_lida.py -v
```

Esperado: 9 passed.

- [ ] **Step 7: Rodar a suíte de API inteira**

```bash
cd apps/api && .venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: tudo verde. `list_conversations` mudou de assinatura (parâmetro novo tem default, então chamadas antigas seguem válidas) e o board ganhou campo — nenhum teste existente deveria quebrar. Se quebrar, é regressão sua.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/whatsapp_inbox/service.py apps/api/app/modules/whatsapp_inbox/router.py apps/api/app/modules/crm/schemas.py apps/api/app/modules/crm/router.py apps/api/tests/test_whatsapp_inbox_nao_lidas.py apps/api/tests/test_crm_board_nao_lida.py
git commit -m "feat: conversas filtram por contato e o board diz quem espera resposta"
```

---

### Task 3: O tipo compartilhado

**Files:**
- Modify: `packages/shared-types/src/index.ts:257-259`

**Interfaces:**
- Produces: `BoardClient.unread: boolean` para o front. Consumido pela Task 5.

- [ ] **Step 1: Editar o tipo**

Em `packages/shared-types/src/index.ts`, na interface `BoardClient` (linha 258):

```typescript
/** `Client` do board, com os sinais que só o board calcula. */
export interface BoardClient extends Client {
  last_interaction_at: string | null;
  /** Tem mensagem do contato esperando resposta. */
  unread: boolean;
}
```

- [ ] **Step 2: Verificar que o typecheck passa**

```bash
pnpm --filter @e1p/web typecheck
```

Esperado: sem erro. (`CrmPage.tsx` ainda não usa `unread`; adicionar campo obrigatório a uma interface não quebra quem só lê os outros. Se algum **mock de teste** construir um `BoardClient` literal, o typecheck acusa — conserte os mocks acrescentando `unread: false`.)

- [ ] **Step 3: Commit**

```bash
git add packages/shared-types/src/index.ts
git commit -m "feat: BoardClient carrega o sinal de mensagem esperando resposta"
```

---

### Task 4: A conversa ganha URL própria (`/conversas/:chatId`)

Hoje `ConversasPage` guarda a conversa selecionada em `useState` — não há como apontar para uma conversa de fora, que é justamente o que a ficha vai precisar fazer. Ganho colateral: o botão voltar do navegador passa a funcionar nessa tela.

**Files:**
- Modify: `apps/web/src/app/App.tsx:80`
- Modify: `apps/web/src/features/conversas/ConversasPage.tsx:46-50,86-90`
- Test: `apps/web/src/features/conversas/ConversasPage.test.tsx` (acrescentar)

**Interfaces:**
- Produces: rota `/conversas/:chatId`. Consumida pela Task 6.

- [ ] **Step 1: Escrever os testes (vão falhar)**

⚠️ `ConversasPage.test.tsx` hoje renderiza `<ConversasPage />` **sem router nenhum** e monta o mock de `api.get` dentro de cada `it`. Depois desta task a página passa a usar `useParams`/`useNavigate`, então **todos** os testes existentes precisam de um router em volta. Isso é parte da task, não um extra.

Acrescente ao fim de `apps/web/src/features/conversas/ConversasPage.test.tsx`:

```tsx
// ── Conversa com URL própria ────────────────────────────────────────────────

/** Duas conversas, para que "abriu a certa" seja uma afirmação com conteúdo. */
function mockarDuasConversas() {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/whatsapp-conversations") {
      return Promise.resolve({
        data: [
          {
            chat_id: "c1", kind: "direct" as const, title: "Doro Eventos",
            phone: "5511999999999", client_id: "cli-1",
            last_message_at: "2026-07-19T10:00:00Z",
            last_message_preview: "Oi, quero o cardápio", unread: true,
          },
          {
            chat_id: "c2", kind: "direct" as const, title: "Murilo Moreschi",
            phone: "5511977776666", client_id: "cli-2",
            last_message_at: "2026-07-20T11:00:00Z",
            last_message_preview: "Ok", unread: false,
          },
        ],
      });
    }
    if (url.endsWith("/timeline")) {
      return Promise.resolve({
        data: [{
          source: "conversation", direction: "in", kind: "text",
          text_body: "Oi, quero o cardápio", media_attachment_id: null,
          purpose_label: null, sender_name: null, created_at: "2026-07-19T10:00:00Z",
        }],
      });
    }
    if (url.endsWith("/window")) {
      return Promise.resolve({ data: { within_session_window: true } });
    }
    if (url === "/whatsapp-templates") return Promise.resolve({ data: [] });
    return Promise.resolve({ data: [] });
  });
  // Abrir uma conversa dispara POST /{id}/read. Sem isto o `await` recebe undefined e o
  // teste passa por acidente — melhor mockar do que depender disso.
  vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
}

function renderNaRota(rota: string) {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/conversas" element={<ConversasPage />} />
        <Route path="/conversas/:chatId" element={<ConversasPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConversasPage — a conversa tem URL própria", () => {
  it("com /conversas/:chatId, abre aquela conversa direto", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas/c2");
    // O campo de digitar só existe quando uma conversa está aberta.
    expect(await screen.findByPlaceholderText(/mensagem/i)).toBeInTheDocument();
    // E abriu a CERTA: a prova é qual timeline foi buscada, não o título na tela — título
    // aparece na lista também, e a asserção ficaria verde com a conversa errada aberta.
    expect(api.get).toHaveBeenCalledWith("/whatsapp-conversations/c2/timeline");
    expect(api.get).not.toHaveBeenCalledWith("/whatsapp-conversations/c1/timeline");
  });

  it("com /conversas, mostra a lista sem nenhuma conversa aberta", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas");
    expect(await screen.findByText("Doro Eventos")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/mensagem/i)).not.toBeInTheDocument();
  });

  it("clicar numa conversa muda a URL", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas");
    await userEvent.click(await screen.findByText("Doro Eventos"));
    expect(await screen.findByPlaceholderText(/mensagem/i)).toBeInTheDocument();
  });

  it("chatId que não existe cai na lista com aviso, e não em tela branca", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas/nao-existe");
    expect(await screen.findByText(/conversa não encontrada/i)).toBeInTheDocument();
    expect(screen.getByText("Doro Eventos")).toBeInTheDocument();
  });
});
```

Troque a linha 4 do arquivo para importar os três do router:

```tsx
import { MemoryRouter, Route, Routes } from "react-router-dom";
```

E envolva as duas chamadas `render(<ConversasPage />)` dos testes que já existem (procure por `render(<ConversasPage />)`) em `renderNaRota("/conversas")` — mova a função `renderNaRota` para cima do primeiro `describe` para que fique visível a todos.

- [ ] **Step 2: Rodar e confirmar que falham**

```bash
pnpm --filter @e1p/web test -- ConversasPage
```

Esperado: os 3 novos falham (a página ignora a URL hoje).

- [ ] **Step 3: Adicionar a rota**

Em `apps/web/src/app/App.tsx`, logo abaixo da linha 80:

```tsx
<Route path="/conversas" element={<ConversasPage />} />
{/* A conversa tem URL própria desde a Onda 1: é assim que a ficha 360° aponta para ela, e
    de quebra o botão voltar do navegador passa a funcionar nesta tela. */}
<Route path="/conversas/:chatId" element={<ConversasPage />} />
```

- [ ] **Step 4: A seleção passa a vir da URL**

Em `apps/web/src/features/conversas/ConversasPage.tsx`:

Importe os hooks do router:

```tsx
import { useNavigate, useParams } from "react-router-dom";
```

Troque o `useState` da seleção (linha ~47) por leitura da URL:

```tsx
  // A conversa aberta é a da URL, não estado local. Isso é o que permite a ficha 360° apontar
  // para uma conversa específica — e faz o botão voltar do navegador funcionar aqui.
  const { chatId } = useParams();
  const navigate = useNavigate();
  const selected = chatId ?? null;
```

Troque o `onClick` de cada item da lista (linha ~87) para navegar:

```tsx
              onClick={() => {
                navigate(`/conversas/${c.chat_id}`);
                setHistoricoAberto(false);
              }}
```

O botão de voltar (o `ChevronLeft` do modo celular) deve chamar `navigate("/conversas")` no lugar de `setSelected(null)`. Procure por `setSelected` no arquivo e troque **todas** as ocorrências restantes.

Trate o id inexistente logo abaixo do `conversaSelecionada`:

```tsx
  const conversaSelecionada = conversations.find((c) => c.chat_id === selected) ?? null;
  // Id que não existe (link velho, conversa apagada) não pode virar tela branca: a lista já
  // carregou, então mostramos ela com um aviso. `conversations.length > 0` evita o falso aviso
  // no primeiro render, antes de a lista chegar.
  const naoEncontrada = selected !== null && conversaSelecionada === null
    && conversations.length > 0;
```

E renderize o aviso acima da lista:

```tsx
        {naoEncontrada && (
          <p className="border-b border-amber-100 bg-amber-50 p-3 text-xs text-amber-700">
            Conversa não encontrada. Escolha uma da lista.
          </p>
        )}
```

Quando `naoEncontrada` for `true`, a lista precisa aparecer no celular — ajuste a classe do container da lista para tratar isso: onde hoje está `selected ? "hidden lg:block" : "block"`, use `selected && !naoEncontrada ? "hidden lg:block" : "block"`.

- [ ] **Step 5: Rodar e confirmar que passam**

```bash
pnpm --filter @e1p/web test -- ConversasPage
```

Esperado: todos verdes, incluindo os que já existiam. Se um teste antigo quebrar porque renderizava `<ConversasPage />` sem `Routes`, envolva-o como nos testes novos.

- [ ] **Step 6: Typecheck e lint**

```bash
pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
```

Esperado: ambos limpos. Se o lint reclamar de `setSelected` não usado, é porque sobrou uma ocorrência — remova o `useState`.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/app/App.tsx apps/web/src/features/conversas/ConversasPage.tsx apps/web/src/features/conversas/ConversasPage.test.tsx
git commit -m "feat: a conversa tem URL propria, e o botao voltar funciona em Conversas"
```

---

### Task 5: O ponto no card do Kanban

**Files:**
- Modify: `apps/web/src/features/crm/CrmPage.tsx:187-240`
- Test: `apps/web/src/features/crm/CrmPage.test.tsx` (acrescentar)

**Interfaces:**
- Consumes: `BoardClient.unread` da Task 3.

- [ ] **Step 1: Escrever os testes (vão falhar)**

Acrescente a `apps/web/src/features/crm/CrmPage.test.tsx`. Monte o board mockado no formato que o `beforeEach` do arquivo já usa para `/crm/board`:

```tsx
describe("CrmPage — ponto de mensagem esperando resposta", () => {
  const boardCom = (unread: boolean) => ({
    columns: [{
      stage: { id: "s1", name: "Entrada", position: 0, is_won: false, is_lost: false },
      clients: [{
        id: "c1", name: "Ju", email: null, phone: null, document: null,
        notes: "", tags: [], source: "whatsapp", stage_id: "s1",
        stage_entered_at: "2026-08-15T12:00:00Z", last_interaction_at: null,
        unread,
      }],
    }],
  });

  it("mostra o ponto quando o contato está esperando resposta", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: boardCom(true) } as never);
    renderPage();
    expect(await screen.findByLabelText("Mensagem esperando resposta")).toBeInTheDocument();
  });

  it("não mostra o ponto quando não há nada esperando", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: boardCom(false) } as never);
    renderPage();
    expect(await screen.findByText("Ju")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mensagem esperando resposta")).not.toBeInTheDocument();
  });
});
```

Se o objeto de cliente acima não bater com o tipo `BoardClient` (campos a mais ou a menos), ajuste pelos campos reais de `Client` em `packages/shared-types/src/index.ts` — o typecheck vai dizer.

- [ ] **Step 2: Rodar e confirmar que falham**

```bash
pnpm --filter @e1p/web test -- CrmPage
```

Esperado: os 2 novos falham com "Unable to find a label with the text of: Mensagem esperando resposta".

- [ ] **Step 3: Implementar**

Em `apps/web/src/features/crm/CrmPage.tsx`, dentro de `Card`, na linha do nome (linha 202):

```tsx
        {/* Nome e sinal na MESMA linha: o ponto é a única coisa que compete com o nome em
            urgência, e ele não pode custar altura — o card já tem cinco linhas de conteúdo.
            Mesma linguagem visual da lista de Conversas, para o dono não ter que aprender dois
            vocabulários para o mesmo fato. */}
        <p className="flex items-center gap-1.5 font-medium text-neutral-800">
          <span className="truncate">{client.name}</span>
          {client.unread && (
            <span
              aria-label="Mensagem esperando resposta"
              title="Mensagem esperando resposta"
              className="h-2 w-2 shrink-0 rounded-full bg-primary-600"
            />
          )}
        </p>
```

- [ ] **Step 4: Rodar e confirmar que passam**

```bash
pnpm --filter @e1p/web test -- CrmPage
```

Esperado: todos verdes.

- [ ] **Step 5: Typecheck e lint**

```bash
pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/crm/CrmPage.tsx apps/web/src/features/crm/CrmPage.test.tsx
git commit -m "feat: o card do Kanban avisa quando tem mensagem esperando resposta"
```

---

### Task 6: O bloco de Conversa na ficha

Arquivo próprio: `ClientDetailPage.tsx` já tem 426 linhas e cinco seções inline. Um sexto bloco com carregamento, estado vazio, tratamento de erro e multi-conversa dentro dele deixaria o arquivo inadministrável.

**Files:**
- Create: `apps/web/src/features/crm/BlocoDaConversa.tsx`
- Create: `apps/web/src/features/crm/BlocoDaConversa.test.tsx`
- Modify: `apps/web/src/features/crm/ClientDetailPage.tsx:9-11,116-118`

**Interfaces:**
- Consumes: `GET /whatsapp-conversations?client_id=` (Task 2), `GET /whatsapp-conversations/{chat_id}/timeline` (já existe, devolve `TimelineEntry[]`), rota `/conversas/:chatId` (Task 4).
- Produces: `<BlocoDaConversa clientId={string} />`.

- [ ] **Step 1: Escrever os testes (vão falhar)**

Crie `apps/web/src/features/crm/BlocoDaConversa.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api } from "../../lib/api";
import BlocoDaConversa from "./BlocoDaConversa";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

vi.mock("../../store/auth", () => ({ useFuso: () => "America/Sao_Paulo" }));

const conversa = (chat_id: string, title: string) => ({
  chat_id, kind: "direct", title, phone: "5511999998888",
  client_id: "cli-1", last_message_at: "2026-08-15T23:10:00Z",
  last_message_preview: "Boa noite", unread: false,
});

const mensagens = [
  {
    source: "conversation", direction: "in", kind: "text",
    text_body: "Boa noite", media_attachment_id: null, purpose_label: null,
    sender_name: null, created_at: "2026-08-15T23:10:00Z",
  },
  {
    source: "conversation", direction: "out", kind: "text",
    text_body: "Oi Ju, tudo bem?", media_attachment_id: null, purpose_label: null,
    sender_name: null, created_at: "2026-08-15T23:16:00Z",
  },
];

function mockar(conversas: unknown[], timeline: unknown[] = mensagens) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url.startsWith("/whatsapp-conversations?")) {
      return Promise.resolve({ data: conversas } as never);
    }
    if (url.includes("/timeline")) return Promise.resolve({ data: timeline } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

const renderBloco = () =>
  render(
    <MemoryRouter>
      <BlocoDaConversa clientId="cli-1" />
    </MemoryRouter>,
  );

beforeEach(() => vi.mocked(api.get).mockReset());

describe("BlocoDaConversa", () => {
  it("mostra as últimas mensagens da conversa", async () => {
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();
    expect(await screen.findByText("Boa noite")).toBeInTheDocument();
    expect(screen.getByText("Oi Ju, tudo bem?")).toBeInTheDocument();
  });

  it("leva para a conversa com o link certo", async () => {
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();
    const link = await screen.findByRole("link", { name: /abrir conversa/i });
    expect(link).toHaveAttribute("href", "/conversas/chat-1");
  });

  it("sem conversa, diz isso e NÃO oferece iniciar uma", async () => {
    mockar([]);
    renderBloco();
    expect(await screen.findByText(/nenhuma conversa no whatsapp/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /iniciar/i })).not.toBeInTheDocument();
  });

  it("com duas conversas, mostra a mais recente e avisa da outra", async () => {
    // Fora de ordem de propósito: o bloco escolhe pela data, não pela posição na lista.
    mockar([
      { ...conversa("chat-antigo", "Ju"), last_message_at: "2026-08-01T10:00:00Z" },
      { ...conversa("chat-novo", "Ju"), last_message_at: "2026-08-15T23:10:00Z" },
    ]);
    renderBloco();
    expect(await screen.findByRole("link", { name: /abrir conversa/i }))
      .toHaveAttribute("href", "/conversas/chat-novo");
    expect(screen.getByText(/\+1 outra conversa/i)).toBeInTheDocument();
  });

  it("falha de rede vira aviso, não derruba a ficha", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("caiu"));
    renderBloco();
    expect(await screen.findByText(/não foi possível carregar a conversa/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falham**

```bash
pnpm --filter @e1p/web test -- BlocoDaConversa
```

Esperado: FAIL — `Failed to resolve import "./BlocoDaConversa"`.

- [ ] **Step 3: Implementar o componente**

Crie `apps/web/src/features/crm/BlocoDaConversa.tsx`:

```tsx
import type { ConversationSummary, TimelineEntry } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { formatTime } from "../../lib/datetime";
import { useFuso } from "../../store/auth";

/** Quantas falas cabem sem a ficha virar uma segunda tela de Conversas. */
const ULTIMAS = 5;

/**
 * O teor da conversa na ficha 360° — uma JANELA, não um posto de trabalho.
 *
 * Mostra e leva para lá; responder continua sendo trabalho da tela de Conversas. A regra da
 * janela de 24h da Meta e a escolha de template vivem lá, e duplicá-las aqui criaria um
 * segundo lugar para o envio falhar de um jeito diferente.
 *
 * Não confundir com o `ClientTimeline` logo acima na ficha: aquele é a NARRATIVA do
 * relacionamento (chegou, moveu, pagou, escreveu); este é o TEOR, o que foi dito.
 */
export default function BlocoDaConversa({ clientId }: { clientId: string }) {
  const fuso = useFuso();
  const [conversas, setConversas] = useState<ConversationSummary[]>([]);
  const [mensagens, setMensagens] = useState<TimelineEntry[]>([]);
  const [erro, setErro] = useState(false);
  const [carregando, setCarregando] = useState(true);

  const load = useCallback(async () => {
    // Falha aqui NÃO pode derrubar a ficha — mesma postura do `ClientTimeline`, que degrada
    // para um aviso em vez de levar junto cobranças, contratos e o resto da tela.
    try {
      const { data } = await api.get<ConversationSummary[]>(
        `/whatsapp-conversations?client_id=${encodeURIComponent(clientId)}`,
      );
      const lista = Array.isArray(data) ? data : [];
      setConversas(lista);
      const recente = maisRecente(lista);
      if (recente) {
        const t = await api.get<TimelineEntry[]>(
          `/whatsapp-conversations/${recente.chat_id}/timeline`,
        );
        setMensagens(Array.isArray(t.data) ? t.data.slice(-ULTIMAS) : []);
      } else {
        setMensagens([]);
      }
      setErro(false);
    } catch {
      setErro(true);
      setConversas([]);
      setMensagens([]);
    } finally {
      setCarregando(false);
    }
  }, [clientId]);

  useEffect(() => {
    load();
  }, [load]);

  if (carregando) return <p className="py-4 text-sm text-neutral-400">Carregando conversa...</p>;
  if (erro) {
    return (
      <p className="py-4 text-sm text-amber-700">
        Não foi possível carregar a conversa.
      </p>
    );
  }

  const recente = maisRecente(conversas);
  if (!recente) {
    // Sem botão de "iniciar conversa": a janela de 24h da Meta não permite abrir conversa do
    // nada, e um botão que sempre falha é pior que nenhum.
    return <p className="py-4 text-center text-sm text-neutral-400">Nenhuma conversa no WhatsApp.</p>;
  }

  const outras = conversas.length - 1;

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-1.5">
        {mensagens.length === 0 ? (
          <p className="text-sm text-neutral-400">Conversa ainda sem mensagens.</p>
        ) : (
          mensagens.map((m, i) => (
            <div
              key={`${m.created_at}-${i}`}
              className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${
                m.direction === "out"
                  ? "self-end bg-primary-50 text-neutral-800"
                  : "self-start bg-neutral-100 text-neutral-700"
              }`}
            >
              <p className="whitespace-pre-wrap">{m.text_body || `[${m.kind}]`}</p>
              <p className="mt-0.5 text-[10px] text-neutral-400">{formatTime(m.created_at, fuso)}</p>
            </div>
          ))
        )}
      </div>

      <div className="flex items-center justify-between gap-2">
        <Link
          to={`/conversas/${recente.chat_id}`}
          className="text-sm font-medium text-primary-600 hover:text-primary-700"
        >
          Abrir conversa
        </Link>
        {/* Um contato pode ter MAIS DE UMA conversa (`@lid` + telefone — ver o comentário em
            whatsapp_inbox/models.py). Mostrar só a mais recente sem dizer que há outra
            esconderia mensagem do dono. */}
        {outras > 0 && (
          <Link to="/conversas" className="text-xs text-neutral-400 hover:text-neutral-600">
            +{outras} outra conversa
          </Link>
        )}
      </div>
    </div>
  );
}

/** A conversa mais recente do contato — por data, não pela ordem em que a API devolveu. */
function maisRecente(lista: ConversationSummary[]): ConversationSummary | null {
  return lista.reduce<ConversationSummary | null>((melhor, c) => {
    if (!melhor) return c;
    if (!c.last_message_at) return melhor;
    if (!melhor.last_message_at) return c;
    return c.last_message_at > melhor.last_message_at ? c : melhor;
  }, null);
}
```

- [ ] **Step 4: Rodar e confirmar que passam**

```bash
pnpm --filter @e1p/web test -- BlocoDaConversa
```

Esperado: 5 passed. Se o texto "+1 outra conversa" falhar por causa da pluralização, ajuste a asserção do teste ou o texto — mas mantenha os dois batendo.

- [ ] **Step 5: Pendurar o bloco na ficha**

Em `apps/web/src/features/crm/ClientDetailPage.tsx`:

Adicione `MessageCircle` ao import de `lucide-react` (linha 10) e importe o bloco junto dos outros imports locais:

```tsx
import BlocoDaConversa from "./BlocoDaConversa";
```

E insira a seção **logo depois** do bloco de Histórico (depois da linha 118), antes de Cobranças:

```tsx
      {/* Conversa vem depois do Histórico e antes do financeiro: o Histórico conta O QUE
          aconteceu, a Conversa mostra O QUE FOI DITO, e só então vêm as seções operacionais.
          O bloco carrega sozinho — não entra no `load()` da página, para que uma falha do
          WhatsApp não segure a ficha inteira. */}
      <Section icon={<MessageCircle size={16} />} title="Conversa">
        <BlocoDaConversa clientId={id} />
      </Section>
```

- [ ] **Step 6: Rodar a suíte de web inteira**

```bash
pnpm --filter @e1p/web test
```

Esperado: tudo verde.

- [ ] **Step 7: Typecheck e lint**

```bash
pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
```

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/crm/BlocoDaConversa.tsx apps/web/src/features/crm/BlocoDaConversa.test.tsx apps/web/src/features/crm/ClientDetailPage.tsx
git commit -m "feat: a ficha do contato mostra a conversa de WhatsApp"
```

---

### Task 7: Fechamento — suíte inteira e a régua de 360px

O card ganhou conteúdo na linha do nome e a ficha ganhou uma seção. A régua de 360px existe neste repo justamente porque teste estrutural (`toContain("flex-wrap")`) já deixou passar tela quebrada por duas sessões — layout só se prova medindo.

**Files:**
- Modify: `apps/web/e2e/crm-360.spec.ts` (se necessário, após verificar)

- [ ] **Step 1: Rodar a suíte de API inteira, com `TZ=UTC`**

```bash
cd apps/api && TZ=UTC .venv/Scripts/python.exe -m pytest tests/ -q
```

Esperado: tudo verde. `TZ=UTC` porque a suíte deste repo já quebrou de madrugada três vezes por depender do relógio da máquina.

- [ ] **Step 2: Rodar a suíte de web inteira**

```bash
pnpm --filter @e1p/web test && pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web lint
```

- [ ] **Step 3: Atualizar a fixture do board**

`apps/web/e2e/fixtures/crm.json` tem dois cards em `/crm/board`. Os objetos de cliente ali precisam do campo novo — e a fixture do repo é de **pior caso plausível**, então o card mais cheio (o `c2`, "Maria Aparecida Gonçalves de Souza", com duas tags) é o que ganha o ponto:

- em `c1`, acrescente `"unread": false`
- em `c2`, acrescente `"unread": true`

- [ ] **Step 4: Medir o card com o ponto**

Acrescente a `apps/web/e2e/crm-360.spec.ts`:

```ts
test("o ponto de mensagem esperando resposta não empurra o nome para fora", async ({ page }) => {
  await page.goto("/crm");

  // O ponto está no card MAIS CHEIO da fixture: nome longo + duas tags + alça de arrastar +
  // botão de ficha. A linha do nome já era a mais disputada do card antes de ganhar inquilino.
  const ponto = page.getByLabel("Mensagem esperando resposta");
  await expect(ponto).toBeVisible();
  await expect(ponto).toBeInViewport();

  // O ponto tem `shrink-0`; quem cede é o nome, via `truncate`. A prova de que a divisão
  // funciona é o ponto estar INTEIRO dentro do card — 8px de largura, não 3 amassados.
  const caixaDoPonto = await ponto.boundingBox();
  expect(caixaDoPonto?.width).toBeGreaterThanOrEqual(7);

  // E nada da primeira coluna saiu da tela. Mesmo recorte `.w-72` e mesmo controle positivo
  // do primeiro teste deste arquivo — sem o controle, um seletor que deixasse de casar
  // aprovaria a tela para sempre.
  expect(await textoForaDaTela(page, ".w-72")).toEqual([]);
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});
```

- [ ] **Step 5: Medir o bloco de Conversa na ficha**

Crie `apps/web/e2e/ficha-conversa-360.spec.ts` (arquivo próprio: a fixture é de outra tela e misturar as duas no `crm-360` obrigaria os testes de card a carregar mocks de conversa):

```ts
import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O bloco de Conversa da ficha 360° em 360px.
 *
 * O caso que estoura uma bolha de chat não é texto longo — é texto longo SEM ESPAÇO, que não
 * tem onde quebrar. `max-w-[85%]` limita a caixa e não o conteúdo: sem `break-words` o texto
 * transborda a bolha e leva a página junto. É por isso que a fixture abaixo tem uma URL
 * gigante e uma sequência sem espaço, e não um lorem ipsum.
 */
const CONVERSA = {
  chat_id: "chat-1",
  kind: "direct",
  title: "Ju",
  phone: "554384035398",
  client_id: "c1",
  last_message_at: "2026-08-15T23:16:00Z",
  last_message_preview: "Boa noite",
  unread: false,
};

const fixtures = {
  "/crm/clients/c1": {
    id: "c1", tenant_id: "t1", name: "Ju", email: null, phone: "554384035398",
    document: null, gender: "unspecified", birthdate: null, notes: "", tags: [],
    source: "whatsapp", stage_id: "s1", stage_entered_at: "2026-08-15T12:00:00Z",
    created_at: "2026-08-15T12:00:00Z",
  },
  "/whatsapp-conversations/chat-1/timeline": [
    {
      source: "conversation", direction: "in", kind: "text",
      text_body: "https://exemplo.com.br/orcamento/casamento-12-12-2026/detalhamento-completo-com-tudo",
      media_attachment_id: null, purpose_label: null, sender_name: null,
      created_at: "2026-08-15T23:10:00Z",
    },
    {
      source: "conversation", direction: "out", kind: "text",
      text_body: "Oi Ju! Aqui é do Doro Eventos. Recebemos seu contato e vamos te chamar pelo nosso número oficial.",
      media_attachment_id: null, purpose_label: null, sender_name: null,
      created_at: "2026-08-15T23:16:00Z",
    },
  ],
  "/whatsapp-conversations": [CONVERSA],
  // Mapeado de propósito: sem esta chave, o prefixo mais longo que casa é `/crm/clients/c1` e
  // o `ClientTimeline` receberia o OBJETO do cliente onde espera `{entries, truncated}`. Ele
  // degrada em vez de quebrar (`Array.isArray(data?.entries)`), mas o teste estaria medindo
  // uma ficha sem Histórico — ou seja, uma tela mais curta que a real.
  "/crm/clients/c1/timeline": { entries: [], truncated: false },
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, fixtures);
});

test("a conversa na ficha cabe em 360px, mesmo com texto sem espaço", async ({ page }) => {
  await page.goto("/crm/clients/c1");

  await expect(page.getByRole("link", { name: "Abrir conversa" })).toBeVisible();

  // A PÁGINA não rola de lado. A ficha é uma coluna só — aqui, ao contrário do board, rolagem
  // horizontal é defeito e não recurso.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);

  // Varredura escopada à seção da conversa, com o controle positivo de sempre.
  expect(await textoForaDaTela(page, "section, .rounded-2xl")).toEqual([]);
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);
});
```

⚠️ O seletor `"section, .rounded-2xl"` é um **chute** — ajuste-o para o que a ficha realmente usa depois de rodar (o `<Section>` de `ClientDetailPage` renderiza `div.rounded-2xl.bg-white`). O que **não** pode mudar é o par: varredura escopada **mais** o controle positivo. Um sem o outro não mede nada.

- [ ] **Step 6: Rodar o e2e**

```bash
pnpm --filter @e1p/web e2e -- crm-360 ficha-conversa-360
```

Esperado: verde. Se o texto sem espaço estourar, o conserto é `break-words` na bolha de `BlocoDaConversa.tsx` — **não** afrouxe a medição.

- [ ] **Step 7: Commit**

```bash
git add apps/web/e2e/crm-360.spec.ts apps/web/e2e/ficha-conversa-360.spec.ts apps/web/e2e/fixtures/crm.json
git commit -m "test: a regua de 360px mede o ponto no card e a conversa na ficha"
```

- [ ] **Step 8: Reportar**

Rode `git log --oneline main..HEAD` e reporte ao dono:
- os commits da onda;
- a saída real das suítes (número de testes, não "passou");
- que o push e o PR são do @devops — **não faça push**.

---

## Definição de pronto

- [ ] `GET /whatsapp-conversations?client_id=X` devolve só as conversas daquele contato, e nunca grupo.
- [ ] O teste de paridade entre `unread_client_ids` e `list_conversations` está verde.
- [ ] `GET /crm/board` devolve `unread` booleano em todo card.
- [ ] `/conversas/:chatId` abre a conversa; `/conversas` mostra a lista; id inválido avisa sem tela branca.
- [ ] O card mostra o ponto quando há mensagem esperando resposta.
- [ ] A ficha mostra as últimas mensagens, o link para a conversa, o aviso de conversa extra, o estado vazio honesto e degrada em falha de rede.
- [ ] Suítes de API e web verdes; typecheck e lint limpos; régua de 360px verde.
- [ ] Nenhum commit em `main`; nenhum push.
