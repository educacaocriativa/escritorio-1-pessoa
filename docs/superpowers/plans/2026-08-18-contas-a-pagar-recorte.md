# Contas a Pagar — recorte da lista e reativar cancelada — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Contas a Pagar passa a abrir em "o que eu devo", com filtros no servidor, paginação que anuncia o que corta, e conta cancelada volta a ser reativável.

**Architecture:** `GET /payables/bills` ganha filtros por query string e passa a devolver `{items, total}` em vez de lista nua; buscar e contar compartilham um único construtor de predicado. Reativar é rota nova (`POST /bills/{id}/reactivate`), não reuso de `/reverse`. No front, o estado do filtro sai para um módulo puro (`filtros.ts`) e a barra para um componente próprio, porque `PagarPage.tsx` já tem 660 linhas e quatro modais.

**Tech Stack:** FastAPI + SQLAlchemy 2.x + Pydantic v2 (`apps/api`); React 18 + TypeScript + Tailwind + Vite (`apps/web`); pytest + TestClient; vitest + Testing Library; Playwright a 360px.

**Spec:** `docs/superpowers/specs/2026-08-18-contas-a-pagar-recorte-design.md`

## ⚠️ Antes da Task 1: isolamento

Em 18/08/2026 este checkout tinha **outra sessão trabalhando em Agenda**, com `CLAUDE.md`,
`AgendaPage.tsx`, `NewEventModal.tsx`, `BlocoDaAgenda.tsx` e `ClientDetailPage.tsx` modificados e
não commitados, na branch `feat/agenda-escolher-horario`. O repositório tem **um único checkout
git** — os diretórios irmãos não têm `.git`.

Antes de qualquer commit: use `superpowers:using-git-worktrees` para criar worktree isolada em
`.claude/worktrees/`, a partir de `main`. Não commite na branch de Agenda; não faça `checkout -b`
com o trabalho alheio na árvore.

Verifique `git status` e `git branch --show-current` **você mesmo** antes de cada commit — neste
repositório o estado já mudou no meio de uma sessão.

## Global Constraints

- **Fuso:** datas de "hoje" vêm de `hoje_do_tenant(db)` no back e de `useFuso()` + `today(fuso)` no front. `datetime.now(UTC).date()` e `new Date()` cru são regressão.
- **Import absoluto** no backend (`from app.modules...`), padrão do repositório.
- **Rede sempre mockada** nos testes de front (`vi.mock("../../lib/api", ...)`).
- **Medição de layout por `boundingBox`**, nunca `toContain` de classe CSS.
- **Verde exige três comandos:** `pytest -q`, `TZ=UTC pytest -q`, `pytest -m rls_e2e` (este exige Docker e fica fora do `-q` por padrão).
- **Commits convencionais:** `feat:`, `fix:`, `test:`, `docs:`.
- Rodar comandos de teste em **primeiro plano**, nunca em background.
- Backend roda de `apps/api` com o venv em `apps/api/.venv`. Front roda de `apps/web` com `pnpm`.

---

### Task 1: `GET /bills` devolve `{items, total}` e aceita `limit`/`offset`

Esta task sozinha mata o defeito mais grave: hoje a rota devolve as 200 contas mais antigas e o
resto desaparece sem aviso.

**Files:**
- Modify: `apps/api/app/modules/payables/schemas.py` (adicionar `PayablesPageOut` ao fim do arquivo)
- Modify: `apps/api/app/modules/payables/service.py:325-332` (`list_payables`) e acrescentar `_filtros` + `count_payables`
- Modify: `apps/api/app/modules/payables/router.py:72-84` (`list_bills`)
- Test: `apps/api/tests/test_payables_listagem.py` (novo)

**Interfaces:**
- Produces:
  - `schemas.PayablesPageOut(BaseModel)` com `items: list[PayableOut]` e `total: int`
  - `service._filtros(stmt, *, status: list[str] | None = None)` — recebe e devolve um `Select`
  - `service.count_payables(db: Session, *, status: list[str] | None = None) -> int`
  - `service.list_payables(db, *, status: list[str] | None = None, limit: int = 200, offset: int = 0) -> list[Payable]`
- Consumes: nada de tasks anteriores.

⚠️ `status` passa de `str | None` para `list[str] | None`. Os chamadores existentes passam `None`;
confira com `grep -rn "list_payables" apps/api` antes de terminar e ajuste quem passar string.

- [ ] **Step 1: Escrever o teste que reprova o código de hoje**

Criar `apps/api/tests/test_payables_listagem.py`:

```python
"""Listagem de Contas a Pagar: paginação honesta e filtros (spec 2026-08-18).

O teste `test_teto_de_200_nao_engole_o_futuro` REPROVA o código anterior a esta spec, e é
deliberado: `list_payables` tinha `limit=200` fixo e o router não expunha `limit`/`offset`, então
a partir da 201ª conta as linhas seguintes eram inalcançáveis pela rota, sem aviso nenhum.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

REGISTER = {
    "legal_name": "Lista Co",
    "document": "10101010000178",
    "slug": "listaco",
    "email": "lista@example.com",
    "name": "Lista",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _cria(client: TestClient, headers, **campos) -> dict:
    """Cria uma conta a pagar e devolve o corpo criado."""
    corpo = {
        "description": "Conta",
        "category": "Ferramentas",
        "supplier": "Fornecedor",
        "amount_cents": 10_000,
        "due_date": date(2027, 1, 10).isoformat(),
    }
    corpo.update(campos)
    resp = client.post("/payables/bills", json=corpo, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _cria_muitas(client: TestClient, headers, total: int) -> None:
    """Cria `total` contas usando recorrência mensal.

    `MAX_OCCURRENCES` (app/core/recurrence.py) e o schema limitam `recurrence_count` a 60, então
    250 contas saem em 5 POSTs de 50 em vez de 250 chamadas HTTP.
    """
    assert total % 50 == 0, "use múltiplos de 50"
    for lote in range(total // 50):
        _cria(
            client,
            headers,
            description=f"Serie {lote}",
            due_date=date(2027 + lote, 1, 10).isoformat(),
            recurrence="monthly",
            recurrence_count=50,
        )


def test_teto_de_200_nao_engole_o_futuro(client: TestClient, headers):
    _cria_muitas(client, headers, 250)

    primeira = client.get("/payables/bills?limit=50&offset=0", headers=headers)
    assert primeira.status_code == 200, primeira.text
    corpo = primeira.json()
    assert len(corpo["items"]) == 50
    assert corpo["total"] == 250, "o total tem de ser o real, não o tamanho da página"

    # A 201ª conta em diante era inalcançável pela rota antes desta spec.
    depois_do_teto = client.get("/payables/bills?limit=50&offset=200", headers=headers)
    assert depois_do_teto.status_code == 200, depois_do_teto.text
    assert len(depois_do_teto.json()["items"]) == 50
    assert depois_do_teto.json()["total"] == 250


def test_pagina_nao_repete_nem_pula_conta(client: TestClient, headers):
    _cria_muitas(client, headers, 100)
    vistos: list[str] = []
    for offset in (0, 50):
        pagina = client.get(f"/payables/bills?limit=50&offset={offset}", headers=headers).json()
        vistos.extend(item["id"] for item in pagina["items"])
    assert len(vistos) == 100
    assert len(set(vistos)) == 100, "offset repetiu conta entre páginas"
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
cd apps/api && .venv/Scripts/python -m pytest tests/test_payables_listagem.py -v
```

Esperado: FAIL. `corpo["items"]` levanta `TypeError: list indices must be integers` porque a rota
ainda devolve lista nua.

- [ ] **Step 3: Adicionar `PayablesPageOut` ao schema**

Ao fim de `apps/api/app/modules/payables/schemas.py`:

```python
class PayablesPageOut(BaseModel):
    """Uma página da listagem de contas a pagar — `items` + o `total` REAL do recorte.

    O `total` não é enfeite: sem ele a tela não consegue dizer "mostrando 50 de 213", e o
    truncamento volta a ser silencioso — que foi exatamente o defeito que esta spec corrigiu.
    Ele conta o recorte inteiro, ignorando `limit`/`offset`.
    """

    items: list[PayableOut]
    total: int
```

- [ ] **Step 4: `_filtros`, `count_payables` e `list_payables` no service**

Substituir `list_payables` (hoje em `apps/api/app/modules/payables/service.py:325-332`) por:

```python
def _filtros(stmt, *, status: list[str] | None = None):
    """Construtor ÚNICO do predicado da listagem — usado por `list_payables` E `count_payables`.

    ⚠️ **Não duplique este `where` do outro lado.** Dois blocos copiados divergem na primeira
    manutenção, e a partir daí a tela anuncia um `total` que a própria lista não confirma: nada
    quebra, o rodapé só passa a mentir. É um modo de falha discreto e caro de achar.
    """
    if status:
        stmt = stmt.where(Payable.status.in_(status))
    return stmt


def list_payables(
    db: Session,
    *,
    status: list[str] | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Payable]:
    limit = max(1, min(limit, 500))
    stmt = _filtros(select(Payable), status=status).order_by(Payable.due_date)
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def count_payables(db: Session, *, status: list[str] | None = None) -> int:
    """Quantas contas o recorte tem, ignorando `limit`/`offset`."""
    stmt = _filtros(select(func.count()).select_from(Payable), status=status)
    return int(db.scalar(stmt) or 0)
```

`func` e `select` já estão importados no topo do arquivo (linha 6).

- [ ] **Step 5: Ajustar a rota**

Em `apps/api/app/modules/payables/router.py`, trocar `PayableOut` por `PayablesPageOut` no import
vindo de `app.modules.payables.schemas` e substituir `list_bills` (linha 72):

```python
@router.get("/bills", response_model=PayablesPageOut)
def list_bills(
    status: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayablesPageOut:
    # Fuso resolvido UMA vez para a página inteira: `_out` por linha faria uma consulta de perfil
    # por conta (N+1). Mesmo cuidado da listagem de `receivables`.
    hoje = hoje_do_tenant(db)
    itens = service.list_payables(db, status=status, limit=limit, offset=offset)
    return PayablesPageOut(
        items=[service.payable_out(p, hoje) for p in itens],
        total=service.count_payables(db, status=status),
    )
```

- [ ] **Step 6: Conferir os outros chamadores de `list_payables`**

```
cd apps/api && grep -rn "list_payables" app tests
```

Qualquer chamada passando `status="open"` (string) vira `status=["open"]`. Corrija todas antes de
seguir.

- [ ] **Step 7: Rodar a suíte de payables inteira**

```
cd apps/api && .venv/Scripts/python -m pytest tests/test_payables_listagem.py tests/test_payables.py tests/test_payables_scheduled.py tests/test_payables_bank_origin.py tests/test_payables_paid_before.py -v
```

Esperado: PASS em tudo. Se algum teste antigo esperava lista nua de `GET /bills`, ele muda para
`["items"]` — é a mudança de contrato prevista na §5.1 da spec, não um teste enfraquecido.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/payables/schemas.py apps/api/app/modules/payables/service.py apps/api/app/modules/payables/router.py apps/api/tests/test_payables_listagem.py
git commit -m "feat: contas a pagar paginam com total real, sem teto silencioso"
```

---

### Task 2: filtros de status, período, texto, centro de custo e categoria

**Files:**
- Modify: `apps/api/app/modules/payables/service.py` (`_filtros`, `list_payables`, `count_payables`)
- Modify: `apps/api/app/modules/payables/router.py` (`list_bills`)
- Test: `apps/api/tests/test_payables_listagem.py` (acrescentar)

**Interfaces:**
- Consumes: `_filtros`, `list_payables`, `count_payables` da Task 1.
- Produces: assinatura final compartilhada pelas três funções —
  `*, status: list[str] | None, due_from: date | None, due_to: date | None, q: str | None, cost_center_id: str | None, chart_account_id: str | None` e, só em `list_payables`, `order: str = "asc"` além de `limit`/`offset`.
- Produces: `service._escapa_curinga(termo: str) -> str`

⚠️ `from` é palavra reservada em Python: o parâmetro se chama `due_from` e recebe `alias="from"` no
`Query`. Mesmo para `due_to`/`to`, por simetria.

- [ ] **Step 1: Escrever os testes dos filtros**

Acrescentar a `apps/api/tests/test_payables_listagem.py`:

```python
def test_status_aceita_mais_de_um_valor(client: TestClient, headers):
    aberta = _cria(client, headers, description="Aberta")
    cancelada = _cria(client, headers, description="Cancelada")
    client.post(f"/payables/bills/{cancelada['id']}/cancel", headers=headers)

    corpo = client.get("/payables/bills?status=open&status=scheduled", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert aberta["id"] in ids
    assert cancelada["id"] not in ids
    assert corpo["total"] == len(ids)


def test_from_ausente_nao_engole_atrasado_antigo(client: TestClient, headers):
    """A visão padrão da tela NÃO manda `from`. Se alguém "simplificar" pondo um piso de data, a
    conta mais urgente que existe — a vencida — some justamente da tela que serve para pagá-la."""
    antiga = _cria(client, headers, description="Vencida", due_date="2026-02-01")
    futura = _cria(client, headers, description="Futura", due_date="2027-01-10")

    corpo = client.get("/payables/bills?status=open&to=2027-06-30", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert antiga["id"] in ids, "atrasado antigo tem de aparecer sem `from`"
    assert futura["id"] in ids


def test_to_e_inclusivo_na_borda(client: TestClient, headers):
    na_borda = _cria(client, headers, description="Borda", due_date="2027-03-31")
    depois = _cria(client, headers, description="Depois", due_date="2027-04-01")

    corpo = client.get("/payables/bills?to=2027-03-31", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert na_borda["id"] in ids
    assert depois["id"] not in ids


def test_q_busca_em_descricao_e_em_fornecedor(client: TestClient, headers):
    por_descricao = _cria(client, headers, description="Assinatura Anthropic", supplier="X")
    por_fornecedor = _cria(client, headers, description="Ferramenta", supplier="Anthropic")
    outra = _cria(client, headers, description="Aluguel", supplier="Imobiliária")

    corpo = client.get("/payables/bills?q=anthropic", headers=headers).json()
    ids = [i["id"] for i in corpo["items"]]
    assert por_descricao["id"] in ids, "busca tem de ser case-insensitive"
    assert por_fornecedor["id"] in ids
    assert outra["id"] not in ids


def test_q_escapa_curinga_do_like(client: TestClient, headers):
    """`ilike` interpreta `%` e `_`. Sem escape, digitar `%` casa com TUDO e a busca parece estar
    funcionando quando não está filtrando nada. A implementação ingênua passa em todos os outros
    testes e falha só neste."""
    com_percent = _cria(client, headers, description="100% Cacau", supplier="Doceria")
    sem_percent = _cria(client, headers, description="Anthropic", supplier="X")

    corpo = client.get("/payables/bills?q=%25", headers=headers).json()  # %25 = "%"
    ids = [i["id"] for i in corpo["items"]]
    assert com_percent["id"] in ids
    assert sem_percent["id"] not in ids
    assert corpo["total"] == 1


def test_order_desc_inverte_a_lista(client: TestClient, headers):
    _cria(client, headers, description="Primeira", due_date="2027-01-10")
    _cria(client, headers, description="Ultima", due_date="2027-09-10")

    asc = client.get("/payables/bills?order=asc", headers=headers).json()["items"]
    desc = client.get("/payables/bills?order=desc", headers=headers).json()["items"]
    assert asc[0]["description"] == "Primeira"
    assert desc[0]["description"] == "Ultima"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?status=open",
        "?status=open&status=scheduled",
        "?to=2027-06-30",
        "?from=2027-01-01&to=2027-12-31",
        "?q=anthropic",
        "?q=anthropic&status=open",
    ],
)
def test_total_sempre_casa_com_a_lista(client: TestClient, headers, query: str):
    """O alarme contra `list_payables` e `count_payables` divergirem de predicado."""
    _cria(client, headers, description="Assinatura Anthropic", due_date="2027-01-10")
    _cria(client, headers, description="Aluguel", due_date="2027-05-10")
    _cria(client, headers, description="Curso", due_date="2028-01-10")

    sep = "&" if query else "?"
    corpo = client.get(f"/payables/bills{query}{sep}limit=500", headers=headers).json()
    assert corpo["total"] == len(corpo["items"]), f"total divergiu da lista em {query!r}"
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
cd apps/api && .venv/Scripts/python -m pytest tests/test_payables_listagem.py -v
```

Esperado: os testes novos falham (parâmetros ignorados devolvem tudo). Os dois da Task 1 continuam
passando.

- [ ] **Step 3: Implementar os filtros no service**

Em `apps/api/app/modules/payables/service.py`, substituir o `_filtros` da Task 1 e ajustar as duas
funções que o usam:

```python
def _escapa_curinga(termo: str) -> str:
    """Neutraliza `%` e `_` para que o texto do usuário seja tratado como TEXTO no `ilike`.

    Sem isto, buscar `%` casa com todas as linhas e a busca parece funcionar enquanto não filtra
    nada — o pior tipo de defeito de busca, porque não tem sintoma.
    """
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtros(
    stmt,
    *,
    status: list[str] | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    cost_center_id: str | None = None,
    chart_account_id: str | None = None,
):
    """Construtor ÚNICO do predicado da listagem — usado por `list_payables` E `count_payables`.

    ⚠️ **Não duplique este `where` do outro lado.** Dois blocos copiados divergem na primeira
    manutenção, e a partir daí a tela anuncia um `total` que a própria lista não confirma: nada
    quebra, o rodapé só passa a mentir. É um modo de falha discreto e caro de achar.

    `due_from` é opcional **e a tela não o manda na visão padrão, de propósito**: atrasado tem
    vencimento no passado, então qualquer piso de data esconde a conta mais urgente que existe.
    """
    if status:
        stmt = stmt.where(Payable.status.in_(status))
    if due_from is not None:
        stmt = stmt.where(Payable.due_date >= due_from)
    if due_to is not None:
        stmt = stmt.where(Payable.due_date <= due_to)
    if q:
        alvo = f"%{_escapa_curinga(q)}%"
        stmt = stmt.where(
            or_(
                Payable.description.ilike(alvo, escape="\\"),
                Payable.supplier.ilike(alvo, escape="\\"),
            )
        )
    if cost_center_id:
        stmt = stmt.where(Payable.cost_center_id == cost_center_id)
    if chart_account_id:
        stmt = stmt.where(Payable.chart_account_id == chart_account_id)
    return stmt


def list_payables(
    db: Session,
    *,
    status: list[str] | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    cost_center_id: str | None = None,
    chart_account_id: str | None = None,
    order: str = "asc",
    limit: int = 200,
    offset: int = 0,
) -> list[Payable]:
    limit = max(1, min(limit, 500))
    stmt = _filtros(
        select(Payable),
        status=status,
        due_from=due_from,
        due_to=due_to,
        q=q,
        cost_center_id=cost_center_id,
        chart_account_id=chart_account_id,
    )
    coluna = Payable.due_date.desc() if order == "desc" else Payable.due_date.asc()
    stmt = stmt.order_by(coluna, Payable.id)
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def count_payables(
    db: Session,
    *,
    status: list[str] | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    q: str | None = None,
    cost_center_id: str | None = None,
    chart_account_id: str | None = None,
) -> int:
    """Quantas contas o recorte tem, ignorando `limit`/`offset`."""
    stmt = _filtros(
        select(func.count()).select_from(Payable),
        status=status,
        due_from=due_from,
        due_to=due_to,
        q=q,
        cost_center_id=cost_center_id,
        chart_account_id=chart_account_id,
    )
    return int(db.scalar(stmt) or 0)
```

`or_`, `func`, `select` e `date` já estão importados no topo do arquivo (linhas 4 e 6).

O desempate por `Payable.id` no `order_by` não é enfeite: sem ele, contas com o mesmo vencimento
podem trocar de posição entre páginas e o `offset` repete ou pula linha — o `test_pagina_nao_repete_nem_pula_conta` da Task 1 é quem cobra isso.

- [ ] **Step 4: Repassar os parâmetros na rota**

Substituir `list_bills` em `apps/api/app/modules/payables/router.py`:

```python
@router.get("/bills", response_model=PayablesPageOut)
def list_bills(
    status: list[str] | None = Query(default=None),
    # `from`/`to` são as palavras naturais na URL; `from` é reservada em Python, daí o alias.
    due_from: date_type | None = Query(default=None, alias="from"),
    due_to: date_type | None = Query(default=None, alias="to"),
    q: str | None = Query(default=None, max_length=120),
    cost_center_id: str | None = Query(default=None),
    chart_account_id: str | None = Query(default=None),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayablesPageOut:
    hoje = hoje_do_tenant(db)
    recorte = dict(
        status=status,
        due_from=due_from,
        due_to=due_to,
        q=q,
        cost_center_id=cost_center_id,
        chart_account_id=chart_account_id,
    )
    itens = service.list_payables(db, order=order, limit=limit, offset=offset, **recorte)
    return PayablesPageOut(
        items=[service.payable_out(p, hoje) for p in itens],
        total=service.count_payables(db, **recorte),
    )
```

O `recorte` como dict único é o que garante que buscar e contar recebam **exatamente** os mesmos
filtros — esquecer um argumento em uma das chamadas é o mesmo defeito da §5.2 pela porta da rota.

- [ ] **Step 5: Rodar os testes**

```
cd apps/api && .venv/Scripts/python -m pytest tests/test_payables_listagem.py -v
```

Esperado: PASS em todos, incluindo os sete casos parametrizados de `test_total_sempre_casa_com_a_lista`.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/payables/service.py apps/api/app/modules/payables/router.py apps/api/tests/test_payables_listagem.py
git commit -m "feat: listagem de contas a pagar aceita status, periodo, texto e dimensoes"
```

---

### Task 3: `POST /bills/{id}/reactivate`

**Files:**
- Modify: `apps/api/app/modules/payables/service.py` (nova `reactivate_payable`, logo abaixo de `cancel_payable`, hoje na linha 713)
- Modify: `apps/api/app/modules/payables/router.py` (nova rota, depois de `cancel_bill`)
- Test: `apps/api/tests/test_payables_reactivate.py` (novo)

**Interfaces:**
- Produces: `service.reactivate_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable`
- Produces: rota `POST /payables/bills/{payable_id}/reactivate` → `PayableOut`
- Consumes: `STATUS_OPEN` e `STATUS_CANCELED` de `app.modules.payables.models` (já importados no service).

- [ ] **Step 1: Escrever os testes**

Criar `apps/api/tests/test_payables_reactivate.py`:

```python
"""Reativar conta cancelada (spec 2026-08-18, §6)."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.tz import DEFAULT_TENANT_TIMEZONE, tenant_today

REGISTER = {
    "legal_name": "Reativa Co",
    "document": "10101010000179",
    "slug": "reativaco",
    "email": "reativa@example.com",
    "name": "Reativa",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _cria(client: TestClient, headers, **campos) -> dict:
    corpo = {
        "description": "Conta",
        "category": "Ferramentas",
        "supplier": "Fornecedor",
        "amount_cents": 10_000,
        "due_date": date(2027, 1, 10).isoformat(),
    }
    corpo.update(campos)
    resp = client.post("/payables/bills", json=corpo, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_cancelada_volta_para_aberta_com_vencimento_intacto(client: TestClient, headers):
    conta = _cria(client, headers, due_date="2027-01-10")
    client.post(f"/payables/bills/{conta['id']}/cancel", headers=headers)

    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open"
    assert resp.json()["due_date"] == "2027-01-10", "o vencimento contratado não se reescreve"


def test_reativada_com_vencimento_passado_nasce_atrasada(client: TestClient, headers):
    """Vencimento preservado + `is_overdue` derivado = ela volta Atrasada, que é o que ela é.

    A data vem de `tenant_today`, nunca da hora em que a suíte roda.
    """
    ontem = tenant_today(DEFAULT_TENANT_TIMEZONE) - timedelta(days=1)
    conta = _cria(client, headers, due_date=ontem.isoformat())
    client.post(f"/payables/bills/{conta['id']}/cancel", headers=headers)

    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "open"
    assert resp.json()["is_overdue"] is True


def test_conta_aberta_nao_pode_ser_reativada(client: TestClient, headers):
    conta = _cria(client, headers)
    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)
    assert resp.status_code == 409
    assert "cancelada" in resp.json()["detail"].lower()


def test_conta_paga_nao_pode_ser_reativada(client: TestClient, headers):
    """Conta paga tem movimento bancário atrás dela; o caminho de volta dela é `/reverse`."""
    resp_conta = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 500_000,
            "opening_balance_is_known": True,
            "opening_date": "2026-01-01",
        },
        headers=headers,
    )
    banco = resp_conta.json()["id"]
    hoje = tenant_today(DEFAULT_TENANT_TIMEZONE).isoformat()
    conta = _cria(client, headers, due_date=hoje)
    paga = client.post(
        f"/payables/bills/{conta['id']}/pay",
        json={"bank_account_id": banco, "paid_on": hoje},
        headers=headers,
    )
    assert paga.status_code == 200, paga.text

    resp = client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)
    assert resp.status_code == 409


def test_conta_inexistente_devolve_404(client: TestClient, headers):
    resp = client.post("/payables/bills/nao-existe/reactivate", headers=headers)
    assert resp.status_code == 404


def test_reativacao_entra_na_auditoria(client: TestClient, headers, db):
    from sqlalchemy import select

    from app.core.audit import AuditEntry

    conta = _cria(client, headers)
    client.post(f"/payables/bills/{conta['id']}/cancel", headers=headers)
    client.post(f"/payables/bills/{conta['id']}/reactivate", headers=headers)

    acoes = list(db.scalars(select(AuditEntry.action).where(AuditEntry.target == conta["id"])))
    assert "payable.reactivate" in acoes
```

⚠️ Antes de rodar, confirme o caminho real do modelo de auditoria:
`grep -rn "class AuditEntry" apps/api/app`. Ajuste o import do último teste se o nome ou o módulo
diferirem — o resto do teste não muda.

- [ ] **Step 2: Rodar e confirmar que falha**

```
cd apps/api && .venv/Scripts/python -m pytest tests/test_payables_reactivate.py -v
```

Esperado: FAIL com 404/405 em todos — a rota não existe.

- [ ] **Step 3: Implementar `reactivate_payable`**

Em `apps/api/app/modules/payables/service.py`, logo depois de `cancel_payable`:

```python
def reactivate_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    """Devolve uma conta CANCELADA para 'open', com o vencimento original intacto.

    ⚠️ **Não é `reverse`, e a separação é de significado, não de estilo.** `reverse` quer dizer
    *"esta saída não vai acontecer"*, e o trabalho dele é APAGAR o movimento bancário. Reativar
    quer dizer o oposto: *"esta saída volta a ser esperada"*. E como `cancel_payable` só aceita
    conta em aberto, aqui **não existe movimento bancário nem evento de Agenda para desfazer** —
    cancelar nunca criou nem removeu nenhum dos dois. Fundir os dois verbos obrigaria um
    `if status == canceled: pula tudo` no meio da lógica mais delicada do arquivo, e é assim que
    um dos dois caminhos deixa de receber a próxima correção.

    **O vencimento não se reescreve.** Reativada depois do prazo, a conta volta Atrasada — porque é
    o que ela é. Empurrar a data para hoje apagaria o vencimento que o dono de fato contratou, e a
    Projeção e o DRE passariam a contar uma data que nunca existiu. Ela nasce editável (`open`),
    então corrigir a data continua sendo um gesto disponível, só não imposto.
    """
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    if p.status != STATUS_CANCELED:
        raise PayableError("Só contas canceladas podem ser reativadas", 409)
    p.status = STATUS_OPEN
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.reactivate", target=p.id)
    db.commit()
    db.refresh(p)
    return p
```

- [ ] **Step 4: Expor a rota**

Em `apps/api/app/modules/payables/router.py`, depois de `cancel_bill`:

```python
@router.post("/bills/{payable_id}/reactivate", response_model=PayableOut)
def reactivate_bill(
    payable_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.reactivate_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(db, p)
```

`PayableOut` continua sendo importado no router (a Task 1 acrescentou `PayablesPageOut`, não
substituiu) — confirme que os dois estão no bloco de import.

- [ ] **Step 5: Rodar os testes**

```
cd apps/api && .venv/Scripts/python -m pytest tests/test_payables_reactivate.py -v
```

Esperado: PASS nos seis.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/payables/service.py apps/api/app/modules/payables/router.py apps/api/tests/test_payables_reactivate.py
git commit -m "feat: conta a pagar cancelada volta a ser reativavel"
```

---

### Task 4: `filtros.ts` — o estado do filtro, puro e testável

**Files:**
- Create: `apps/web/src/features/pagar/filtros.ts`
- Create: `apps/web/src/features/pagar/filtros.test.ts`
- Modify: `packages/shared-types/src/index.ts` (acrescentar `PayablesPage` logo depois de `Payable`, hoje terminando na linha 481)

**Interfaces:**
- Produces (TS):
  - `interface PayablesPage { items: Payable[]; total: number }` em `shared-types`
  - `type FiltroPagar = { status: PayableStatus[]; de: string | null; ate: string | null; q: string; centroDeCusto: string; categoria: string }`
  - `function fimDoMesSeguinte(hojeYmd: string): string`
  - `function filtroPadrao(hojeYmd: string): FiltroPagar`
  - `function paraQuery(f: FiltroPagar, limit: number, offset: number): Record<string, unknown>`
- Consumes: nada de tasks anteriores (é o primeiro arquivo de front).

- [ ] **Step 1: Escrever os testes**

Criar `apps/web/src/features/pagar/filtros.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { fimDoMesSeguinte, filtroPadrao, paraQuery } from "./filtros";

describe("fimDoMesSeguinte", () => {
  it("agosto devolve o fim de setembro", () => {
    expect(fimDoMesSeguinte("2026-08-18")).toBe("2026-09-30");
  });

  it("vira o ano em dezembro", () => {
    expect(fimDoMesSeguinte("2026-12-05")).toBe("2027-01-31");
  });

  it("acerta fevereiro bissexto", () => {
    expect(fimDoMesSeguinte("2028-01-10")).toBe("2028-02-29");
  });

  it("acerta fevereiro comum", () => {
    expect(fimDoMesSeguinte("2027-01-10")).toBe("2027-02-28");
  });

  it("acerta o ano secular nao bissexto", () => {
    expect(fimDoMesSeguinte("2100-01-10")).toBe("2100-02-28");
  });
});

describe("filtroPadrao", () => {
  const padrao = filtroPadrao("2026-08-18");

  it("abre em 'o que eu devo': aberta e agendada", () => {
    expect(padrao.status).toEqual(["open", "scheduled"]);
  });

  it("NAO tem piso de data", () => {
    // Atrasado vence no passado. Qualquer `de` esconde a conta mais urgente que existe.
    expect(padrao.de).toBeNull();
  });

  it("tem teto no fim do mes seguinte", () => {
    expect(padrao.ate).toBe("2026-09-30");
  });
});

describe("paraQuery", () => {
  it("omite o que esta vazio, em vez de mandar chave nula", () => {
    const q = paraQuery(filtroPadrao("2026-08-18"), 50, 0);
    expect(q).toEqual({
      status: ["open", "scheduled"],
      to: "2026-09-30",
      order: "asc",
      limit: 50,
      offset: 0,
    });
    expect(q).not.toHaveProperty("from");
    expect(q).not.toHaveProperty("q");
  });

  it("manda o texto quando ele existe", () => {
    const f = { ...filtroPadrao("2026-08-18"), q: "anthropic" };
    expect(paraQuery(f, 50, 0).q).toBe("anthropic");
  });

  it("historico vem decrescente", () => {
    const f = { ...filtroPadrao("2026-08-18"), status: ["paid" as const], ate: null };
    expect(paraQuery(f, 50, 0).order).toBe("desc");
  });

  it("repassa limit e offset da paginacao", () => {
    const q = paraQuery(filtroPadrao("2026-08-18"), 50, 100);
    expect(q.limit).toBe(50);
    expect(q.offset).toBe(100);
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
cd apps/web && pnpm vitest run src/features/pagar/filtros.test.ts
```

Esperado: FAIL — `Cannot find module "./filtros"`.

- [ ] **Step 3: Acrescentar `PayablesPage` a `shared-types`**

Em `packages/shared-types/src/index.ts`, logo depois da interface `Payable` (que termina na linha
481) e antes de `PayablesSummary`:

```ts
/** Uma página de `GET /payables/bills` — `items` mais o total REAL do recorte.
 *
 * O `total` ignora `limit`/`offset` de propósito: é ele que permite à tela dizer
 * "mostrando 50 de 213". Sem isso o truncamento volta a ser silencioso.
 */
export interface PayablesPage {
  items: Payable[];
  total: number;
}
```

- [ ] **Step 4: Implementar `filtros.ts`**

Criar `apps/web/src/features/pagar/filtros.ts`:

```ts
import type { PayableStatus } from "@e1p/shared-types";

/** O recorte da lista de Contas a Pagar. `de`/`ate` são YYYY-MM-DD ou `null` (sem limite). */
export type FiltroPagar = {
  status: PayableStatus[];
  de: string | null;
  ate: string | null;
  q: string;
  centroDeCusto: string;
  categoria: string;
};

const DIAS_NO_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function bissexto(ano: number): boolean {
  return (ano % 4 === 0 && ano % 100 !== 0) || ano % 400 === 0;
}

/**
 * Último dia do mês SEGUINTE ao de `hojeYmd`, também em YYYY-MM-DD.
 *
 * Aritmética de string, nunca `new Date`: o `hojeYmd` já chega no fuso do tenant (via
 * `today(useFuso())`), e reconstruir um `Date` a partir dele devolveria o cálculo ao fuso do
 * navegador — em UTC-3, das 21h à meia-noite o horizonte pularia um dia inteiro.
 */
export function fimDoMesSeguinte(hojeYmd: string): string {
  const [ano0, mes0] = hojeYmd.split("-").map(Number);
  // `mes0` é 1-based; usá-lo como índice 0-based já aponta para o mês seguinte.
  const ano = ano0 + Math.floor(mes0 / 12);
  const mes = (mes0 % 12) + 1;
  const dias = mes === 2 && bissexto(ano) ? 29 : DIAS_NO_MES[mes - 1];
  return `${ano}-${String(mes).padStart(2, "0")}-${String(dias).padStart(2, "0")}`;
}

/**
 * A visão padrão: "o que eu devo".
 *
 * `de: null` é deliberado e não é esquecimento. Atrasado tem vencimento no passado; qualquer piso
 * de data esconde exatamente a conta mais urgente que existe. O que o horizonte corta é só o
 * futuro distante — e o lugar de olhar longe é a Projeção de caixa.
 */
export function filtroPadrao(hojeYmd: string): FiltroPagar {
  return {
    status: ["open", "scheduled"],
    de: null,
    ate: fimDoMesSeguinte(hojeYmd),
    q: "",
    centroDeCusto: "",
    categoria: "",
  };
}

/** Histórico se lê do mais recente para o mais antigo; o que se deve, do mais próximo em diante. */
function ordem(status: PayableStatus[]): "asc" | "desc" {
  const olhandoParaTras = status.every((s) => s === "paid" || s === "canceled");
  return status.length > 0 && olhandoParaTras ? "desc" : "asc";
}

/** Serializa para os `params` do axios. Chave vazia é OMITIDA, nunca mandada como null. */
export function paraQuery(
  f: FiltroPagar,
  limit: number,
  offset: number,
): Record<string, unknown> {
  const q: Record<string, unknown> = { order: ordem(f.status), limit, offset };
  if (f.status.length > 0) q.status = f.status;
  if (f.de) q.from = f.de;
  if (f.ate) q.to = f.ate;
  if (f.q.trim()) q.q = f.q.trim();
  if (f.centroDeCusto) q.cost_center_id = f.centroDeCusto;
  if (f.categoria) q.chart_account_id = f.categoria;
  return q;
}
```

- [ ] **Step 5: Rodar os testes**

```
cd apps/web && pnpm vitest run src/features/pagar/filtros.test.ts
```

Esperado: PASS nos catorze.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/pagar/filtros.ts apps/web/src/features/pagar/filtros.test.ts packages/shared-types/src/index.ts
git commit -m "feat: estado do filtro de contas a pagar, isolado e testavel"
```

---

### Task 5: `PagarPage` consome `{items, total}` e ganha "carregar mais"

Sem filtros ainda — só o contrato novo, a contagem honesta e a paginação. A tela continua
mostrando o mesmo que hoje.

**Files:**
- Modify: `apps/web/src/features/pagar/PagarPage.tsx:88-124` (estado e `load`) e a região da tabela (linhas 200-295)
- Modify: `apps/web/src/features/pagar/PagarPage.test.tsx:49-57` (`mockComConta`) e demais mocks de `/payables/bills`

**Interfaces:**
- Consumes: `PayablesPage` e `filtroPadrao`/`paraQuery` da Task 4; `useFuso()` de `../../store/auth`; `today()` de `../../lib/datetime`.
- Produces: dentro de `PagarPage`, o estado `filtro`, `total`, `offset` e a função `load(reiniciando: boolean)` que a Task 6 vai reusar.

⚠️ O mock de `api.get` em `PagarPage.test.tsx` casa por `url === "/payables/bills"`. Como os
parâmetros vão no **config** do axios (`api.get(url, { params })`), a comparação continua valendo —
mas o **corpo** devolvido tem de virar `{ items: [...], total: n }`, senão a página lê `.items` de
um array e quebra. Ajuste todos os pontos que devolvem `/payables/bills`.

- [ ] **Step 1: Escrever os testes**

Acrescentar a `apps/web/src/features/pagar/PagarPage.test.tsx` (e primeiro ajustar `mockComConta` e
os demais mocks para devolverem `{ items: [CONTA_ABERTA], total: 1 }`):

```ts
it("pede a primeira pagina com o recorte padrao", async () => {
  mockComConta([CONTA]);
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );

  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/payables/bills", expect.anything()));
  const [, config] = vi.mocked(api.get).mock.calls.find(([u]) => u === "/payables/bills")!;
  const params = (config as { params: Record<string, unknown> }).params;
  expect(params.status).toEqual(["open", "scheduled"]);
  expect(params).not.toHaveProperty("from"); // atrasado antigo tem de caber na visao padrao
  expect(params.offset).toBe(0);
});

it("mostra quantas contas estao a vista e quantas existem", async () => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/payables/bills")
      return Promise.resolve({ data: { items: [CONTA_ABERTA], total: 213 } } as never);
    return Promise.resolve({ data: [] } as never);
  });
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );

  expect(await screen.findByText(/Mostrando 1 de 213/i)).toBeInTheDocument();
});

it("carregar mais ANEXA a lista em vez de substituir", async () => {
  const SEGUNDA = { ...CONTA_ABERTA, id: "b-2", description: "Energia" };
  vi.mocked(api.get).mockImplementation((url: string, config?: unknown) => {
    if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/payables/bills") {
      const offset = (config as { params: { offset: number } }).params.offset;
      return Promise.resolve({
        data: { items: offset === 0 ? [CONTA_ABERTA] : [SEGUNDA], total: 2 },
      } as never);
    }
    return Promise.resolve({ data: [] } as never);
  });
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );

  expect(await screen.findByText("Aluguel")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /carregar mais/i }));

  expect(await screen.findByText("Energia")).toBeInTheDocument();
  // O erro classico de paginacao: a segunda pagina apagar a primeira.
  expect(screen.getByText("Aluguel")).toBeInTheDocument();
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
cd apps/web && pnpm vitest run src/features/pagar/PagarPage.test.tsx
```

Esperado: FAIL nos três testes novos.

- [ ] **Step 3: Trocar o estado e o `load` em `PagarPage.tsx`**

Acrescentar aos imports do topo:

```tsx
import type { Contract, Payable, PayablesPage, PayablesSummary } from "@e1p/shared-types";
import { formatDay, today } from "../../lib/datetime";
import { useFuso } from "../../store/auth";
import { filtroPadrao, paraQuery, type FiltroPagar } from "./filtros";
```

Dentro de `PagarPage`, acrescentar aos `useState` existentes:

```tsx
const fuso = useFuso();
const [filtro, setFiltro] = useState<FiltroPagar>(() => filtroPadrao(today(fuso)));
const [total, setTotal] = useState(0);
const [offset, setOffset] = useState(0);
const [carregando, setCarregando] = useState(false);
```

Declarar `PAGINA` no **nível do módulo**, junto de `RECUR` e `EXPENSE_GROUPS` (topo do arquivo,
fora do componente) — o rodapé da tabela também a usa:

```tsx
/** Tamanho da página. 50 cabe numa rolagem curta e mantém o "carregar mais" barato. */
const PAGINA = 50;
```

E substituir o `load` (linha 104) por:

```tsx
const load = useCallback(
  async (proximoOffset = 0) => {
    setCarregando(true);
    try {
      const [s, b] = await Promise.all([
        api.get<PayablesSummary>("/payables/summary"),
        api.get<PayablesPage>("/payables/bills", {
          params: paraQuery(filtro, PAGINA, proximoOffset),
        }),
      ]);
      setSummary(s.data);
      // `proximoOffset > 0` é "carregar mais": ANEXA. Substituir aqui é o erro clássico de
      // paginação, e ele passa despercebido porque a primeira página sempre parece certa.
      setBills((antes) => (proximoOffset === 0 ? b.data.items : [...antes, ...b.data.items]));
      setTotal(b.data.total);
      setOffset(proximoOffset);
    } finally {
      setCarregando(false);
    }
    const [ca, cc] = await Promise.all([
      api.get<ChartAccount[]>("/chart-of-accounts").catch(() => ({ data: [] as ChartAccount[] })),
      api.get<CostCenter[]>("/cost-centers").catch(() => ({ data: [] as CostCenter[] })),
    ]);
    setChartAccounts(ca.data);
    setCostCenters(cc.data);
    const pend = await api
      .get<{ id: string }[]>("/payables/receipts")
      .catch(() => ({ data: [] as { id: string }[] }));
    setInbox(pend.data);
  },
  [filtro],
);

useEffect(() => {
  load(0);
}, [load]);
```

⚠️ As chamadas existentes `load()` depois de cancelar/estornar/pagar continuam válidas — sem
argumento elas recarregam a primeira página, que é o comportamento certo depois de uma ação que
muda status.

- [ ] **Step 4: Acrescentar o rodapé de contagem**

Logo **depois** do `</table>` e ainda dentro da `div` com `overflow-x-auto`
(hoje na linha ~293), acrescentar:

```tsx
<div className="flex items-center justify-between gap-3 border-t border-neutral-100 px-4 py-3">
  <p className="text-xs text-neutral-500">
    Mostrando {bills.length} de {total}
  </p>
  {bills.length < total && (
    <button
      onClick={() => load(offset + PAGINA)}
      disabled={carregando}
      className="min-h-[44px] rounded-pill px-4 text-sm font-medium text-primary-600 hover:bg-primary-50 disabled:opacity-50"
    >
      {carregando ? "Carregando…" : "Carregar mais"}
    </button>
  )}
</div>
```

A contagem aparece **sempre**, não só quando trunca: é ela que torna o corte visível antes de o
dono precisar dele.

- [ ] **Step 5: Rodar os testes de front**

```
cd apps/web && pnpm vitest run src/features/pagar/
```

Esperado: PASS. Testes antigos que mockavam `/payables/bills` como array precisam do ajuste do
aviso acima — é a mudança de contrato, não asserção enfraquecida.

- [ ] **Step 6: Typecheck**

```
cd apps/web && pnpm tsc --noEmit
```

Esperado: sem erro. Se `@e1p/shared-types` não resolver `PayablesPage`, rode o build do pacote
compartilhado antes (`cd packages/shared-types && pnpm build`).

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/pagar/PagarPage.tsx apps/web/src/features/pagar/PagarPage.test.tsx
git commit -m "feat: contas a pagar pagina e diz quantas contas existem"
```

---

### Task 6: a barra de filtros e o `GanchoDaVima` fora da primeira dobra

**Files:**
- Create: `apps/web/src/features/pagar/FiltrosDaLista.tsx`
- Modify: `apps/web/src/features/pagar/PagarPage.tsx` (montar a barra; mover `GanchoDaVima` para depois da tabela)
- Modify: `apps/web/src/features/pagar/PagarPage.test.tsx`

**Interfaces:**
- Consumes: `FiltroPagar` da Task 4; `ChartAccount` de `../financeiro/planoContas`; `CostCenter` de `../financeiro/costCenters`; o estado `filtro`/`setFiltro` da Task 5.
- Produces: `<FiltrosDaLista valor={FiltroPagar} onChange={(f: FiltroPagar) => void} categorias={ChartAccount[]} centros={CostCenter[]} />`

- [ ] **Step 1: Escrever os testes**

Acrescentar a `apps/web/src/features/pagar/PagarPage.test.tsx`:

```ts
it("digitar no filtro de texto dispara UMA chamada, nao uma por tecla", async () => {
  vi.useFakeTimers();
  mockComConta([CONTA]);
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
  await vi.runOnlyPendingTimersAsync();
  const antes = vi.mocked(api.get).mock.calls.filter(([u]) => u === "/payables/bills").length;

  fireEvent.change(screen.getByPlaceholderText(/fornecedor ou descri/i), {
    target: { value: "anthropic" },
  });
  await vi.advanceTimersByTimeAsync(400);

  const depois = vi.mocked(api.get).mock.calls.filter(([u]) => u === "/payables/bills").length;
  expect(depois - antes).toBe(1);
  vi.useRealTimers();
});

it("trocar o status para Cancelado refaz a busca com o recorte novo", async () => {
  mockComConta([CONTA]);
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
  await screen.findByText("Aluguel");

  fireEvent.change(screen.getByLabelText(/status/i), { target: { value: "canceled" } });

  await waitFor(() => {
    const ultima = vi
      .mocked(api.get)
      .mock.calls.filter(([u]) => u === "/payables/bills")
      .at(-1)!;
    const params = (ultima[1] as { params: Record<string, unknown> }).params;
    expect(params.status).toEqual(["canceled"]);
    expect(params.order).toBe("desc"); // historico se le do mais recente para tras
    expect(params.offset).toBe(0); // trocar filtro volta para a primeira pagina
  });
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
cd apps/web && pnpm vitest run src/features/pagar/PagarPage.test.tsx
```

Esperado: FAIL — não existe campo de texto nem seletor de status.

- [ ] **Step 3: Criar `FiltrosDaLista.tsx`**

```tsx
import type { PayableStatus } from "@e1p/shared-types";
import type { CostCenter } from "../financeiro/costCenters";
import type { ChartAccount } from "../financeiro/planoContas";
import type { FiltroPagar } from "./filtros";

/** Os recortes de status que a tela oferece. "Em aberto" são DOIS status, não um. */
const RECORTES: { value: string; label: string; status: PayableStatus[] }[] = [
  { value: "abertas", label: "Em aberto", status: ["open", "scheduled"] },
  { value: "paid", label: "Pago", status: ["paid"] },
  { value: "scheduled", label: "Agendada", status: ["scheduled"] },
  { value: "canceled", label: "Cancelado", status: ["canceled"] },
];

function valorDoRecorte(status: PayableStatus[]): string {
  const achado = RECORTES.find(
    (r) => r.status.length === status.length && r.status.every((s) => status.includes(s)),
  );
  return achado?.value ?? "abertas";
}

const campo =
  "min-h-[44px] rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400";

/**
 * A barra de recorte da lista.
 *
 * `flex-wrap` e não largura fixa: em 360px estes cinco controles reflui em duas linhas em vez de
 * se espremerem a ponto de o polegar não acertar nenhum. O gate de layout mede isso de verdade em
 * `e2e/pagar-360.spec.ts`.
 */
export default function FiltrosDaLista({
  valor,
  onChange,
  categorias,
  centros,
}: {
  valor: FiltroPagar;
  onChange: (f: FiltroPagar) => void;
  categorias: ChartAccount[];
  centros: CostCenter[];
}) {
  const padraoAtivo =
    valor.q === "" && valor.centroDeCusto === "" && valor.categoria === "" && valor.de === null;

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={valor.q}
          onChange={(e) => onChange({ ...valor, q: e.target.value })}
          placeholder="Buscar fornecedor ou descrição"
          aria-label="Buscar fornecedor ou descrição"
          className={`${campo} min-w-0 flex-1 basis-56`}
        />

        {/* Só `aria-label`, sem <label> irmão: os dois juntos fazem `getByLabel` casar duas vezes
            e o gate de 360px falha por strict mode do Playwright, não por defeito da tela. */}
        <select
          aria-label="Status"
          value={valorDoRecorte(valor.status)}
          onChange={(e) => {
            const r = RECORTES.find((x) => x.value === e.target.value)!;
            // Histórico não tem por que herdar o horizonte de "o que eu devo".
            const olhandoParaTras = r.status.every((s) => s === "paid" || s === "canceled");
            onChange({ ...valor, status: r.status, ate: olhandoParaTras ? null : valor.ate });
          }}
          className={campo}
        >
          {RECORTES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>

        <input
          type="date"
          aria-label="Vencimento até"
          value={valor.ate ?? ""}
          onChange={(e) => onChange({ ...valor, ate: e.target.value || null })}
          className={campo}
        />

        <select
          aria-label="Centro de custo"
          value={valor.centroDeCusto}
          onChange={(e) => onChange({ ...valor, centroDeCusto: e.target.value })}
          className={campo}
        >
          <option value="">Todos os centros</option>
          {centros.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>

        <select
          aria-label="Categoria"
          value={valor.categoria}
          onChange={(e) => onChange({ ...valor, categoria: e.target.value })}
          className={campo}
        >
          <option value="">Todas as categorias</option>
          {categorias.map((a) => (
            <option key={a.id} value={a.id}>
              {a.categoria}
            </option>
          ))}
        </select>
      </div>

      {!padraoAtivo && (
        <button
          onClick={() =>
            onChange({ ...valor, q: "", centroDeCusto: "", categoria: "", de: null })
          }
          className="mt-3 min-h-[44px] text-xs font-medium text-neutral-500 hover:text-primary-600"
        >
          Limpar filtros
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Montar a barra e aplicar o debounce em `PagarPage.tsx`**

Importar `import FiltrosDaLista from "./FiltrosDaLista";` e trocar o `useEffect` da Task 5 por uma
versão com debounce, seguindo o padrão de `AccountModal.tsx:154-170`:

```tsx
useEffect(() => {
  let vivo = true;
  // Um filtro de texto sem debounce dispara uma chamada por tecla; `vivo` descarta a resposta de
  // um recorte que o usuário já abandonou e evita a lista "piscar" com dado velho.
  const t = setTimeout(() => {
    if (vivo) load(0);
  }, 300);
  return () => {
    vivo = false;
    clearTimeout(t);
  };
}, [load]);
```

Renderizar a barra logo acima da `div` da tabela:

```tsx
<FiltrosDaLista
  valor={filtro}
  onChange={setFiltro}
  categorias={chartAccounts}
  centros={costCenters}
/>
```

- [ ] **Step 5: Mover o `GanchoDaVima` para depois da tabela**

Recortar `<GanchoDaVima gancho="payables.conta.criada" />` de onde está hoje (logo abaixo do
título) e colar **depois** do bloco `</div>` que fecha a tabela. Ele continua sendo respondido; só
para de ocupar cerca de 200px da primeira dobra, empurrando para fora da tela a lista que é o
motivo de a página existir.

- [ ] **Step 6: Rodar os testes e o typecheck**

```
cd apps/web && pnpm vitest run src/features/pagar/ && pnpm tsc --noEmit
```

Esperado: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/pagar/FiltrosDaLista.tsx apps/web/src/features/pagar/PagarPage.tsx apps/web/src/features/pagar/PagarPage.test.tsx
git commit -m "feat: contas a pagar abre no que se deve, com barra de recorte"
```

---

### Task 7: a ação "Reativar" na linha cancelada

**Files:**
- Modify: `apps/web/src/features/pagar/PagarPage.tsx` (funções de ação por volta da linha 150 e a célula de ações da tabela)
- Modify: `apps/web/src/features/pagar/PagarPage.test.tsx`

**Interfaces:**
- Consumes: rota `POST /payables/bills/{id}/reactivate` da Task 3; `load` da Task 5.
- Produces: nada consumido por tasks posteriores.

- [ ] **Step 1: Escrever os testes**

```ts
const CONTA_CANCELADA = {
  ...CONTA_ABERTA,
  id: "b-9",
  description: "Assinatura cancelada",
  status: "canceled",
};

function mockComCancelada() {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/payables/bills")
      return Promise.resolve({ data: { items: [CONTA_CANCELADA], total: 1 } } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
}

it("linha cancelada oferece Reativar", async () => {
  mockComCancelada();
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );

  expect(await screen.findByRole("button", { name: /reativar/i })).toBeInTheDocument();
});

it("linha aberta NAO oferece Reativar", async () => {
  mockComConta([CONTA]);
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
  await screen.findByText("Aluguel");

  expect(screen.queryByRole("button", { name: /reativar/i })).not.toBeInTheDocument();
});

it("Reativar chama a rota certa e recarrega", async () => {
  mockComCancelada();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );

  fireEvent.click(await screen.findByRole("button", { name: /reativar/i }));

  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith("/payables/bills/b-9/reactivate"),
  );
});
```

- [ ] **Step 2: Rodar e confirmar que falha**

```
cd apps/web && pnpm vitest run src/features/pagar/PagarPage.test.tsx
```

Esperado: FAIL — não existe botão "Reativar".

- [ ] **Step 3: Implementar a ação**

Ao lado de `cancel` e `reverse` em `PagarPage.tsx`:

```tsx
/**
 * Reativar é rota PRÓPRIA, não `/reverse`.
 *
 * `reverse` apaga movimento bancário — trabalho que aqui não existe, porque cancelar só age sobre
 * conta em aberto, que não tem movimento nenhum. A confirmação avisa do vencimento porque é a
 * única consequência que surpreende: reativada depois do prazo, a conta volta Atrasada, com a data
 * original preservada.
 */
async function reactivate(id: string) {
  if (
    !confirm(
      'Reativar esta conta? Ela volta para "A pagar" com o vencimento original — se ele já ' +
        "passou, ela aparece como Atrasada e você pode editar a data.",
    )
  )
    return;
  await api.post(`/payables/bills/${id}/reactivate`);
  load();
}
```

E na célula de ações da tabela, ao lado dos blocos `p.status === "paid"` e `p.status === "scheduled"`:

```tsx
{p.status === "canceled" && (
  <button
    onClick={() => reactivate(p.id)}
    className="text-xs font-medium text-neutral-500 hover:text-primary-600"
  >
    Reativar
  </button>
)}
```

- [ ] **Step 4: Rodar os testes**

```
cd apps/web && pnpm vitest run src/features/pagar/ && pnpm tsc --noEmit
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/pagar/PagarPage.tsx apps/web/src/features/pagar/PagarPage.test.tsx
git commit -m "feat: reativar conta cancelada pela tela de contas a pagar"
```

---

### Task 8: gate de layout a 360px

**Files:**
- Create: `apps/web/e2e/pagar-360.spec.ts`

**Interfaces:**
- Consumes: `mockarApi` de `apps/web/e2e/support/api.ts`; a barra da Task 6.
- Produces: nada.

⚠️ `mockarApi` casa por **prefixo mais longo**. Registre `/payables/bills` e, se algum teste
precisar, `/payables/bills/paid-before` — senão o segundo recebe a página de contas.

- [ ] **Step 1: Escrever a spec**

Criar `apps/web/e2e/pagar-360.spec.ts`:

```ts
import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";

/**
 * Gate de LAYOUT da tela de Contas a Pagar a 360px.
 *
 * Mede `boundingBox`, nunca classe CSS: `toContain("flex-wrap")` já passou verde neste projeto com
 * a tela quebrada. Payload de pior caso plausível — fornecedor comprido e valor de 6 dígitos —
 * porque dado curto sempre cabe, e medir com ele é medir uma tela que não existe.
 */
const CONTA = {
  id: "b-1",
  tenant_id: "t-1",
  description: "Assinatura anual da plataforma de inteligência",
  category: "Ferramentas",
  supplier: "Fornecedor Internacional de Tecnologia Ltda",
  amount_cents: 118_573_04,
  due_date: "2026-09-20",
  competence_date: null,
  chart_account_id: null,
  contract_id: null,
  cost_center_id: null,
  status: "open",
  is_overdue: false,
  paid_at: null,
  recurrence: "monthly",
  recurrence_count: 12,
  recurrence_group: "g-1",
  payment_code: "",
  attachment_url: "",
  created_at: "2026-01-01T00:00:00Z",
};

test.beforeEach(async ({ page }) => {
  await mockarApi(page, {
    "/payables/summary": {
      open_cents: 18_575_704,
      overdue_cents: 0,
      week_cents: 1_800_000,
      month_cents: 18_575_704,
      paid_month_cents: 562_541,
      scheduled_cents: 0,
    },
    "/payables/bills": { items: [CONTA], total: 213 },
    "/payables/receipts": [],
    "/chart-of-accounts": [],
    "/cost-centers": [],
  });
});

test("a barra de filtros reflui e nada estoura os 360px", async ({ page }) => {
  await page.goto("/pagar");

  const busca = page.getByLabel("Buscar fornecedor ou descrição");
  await expect(busca).toBeVisible();

  const largura = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(largura, "a pagina inteira nao pode rolar na horizontal").toBeLessThanOrEqual(360);

  for (const rotulo of ["Buscar fornecedor ou descrição", "Status", "Vencimento até"]) {
    const caixa = await page.getByLabel(rotulo).boundingBox();
    expect(caixa, `${rotulo} sem caixa`).not.toBeNull();
    expect(caixa!.x, `${rotulo} comeca fora da tela`).toBeGreaterThanOrEqual(0);
    expect(caixa!.x + caixa!.width, `${rotulo} estoura os 360px`).toBeLessThanOrEqual(360);
  }
});

test("os controles do filtro sao alvos de toque de 44px", async ({ page }) => {
  await page.goto("/pagar");

  for (const rotulo of ["Buscar fornecedor ou descrição", "Status", "Vencimento até"]) {
    const caixa = await page.getByLabel(rotulo).boundingBox();
    expect(caixa!.height, `${rotulo} baixo demais para o polegar`).toBeGreaterThanOrEqual(44);
  }
});

test("a contagem aparece e o gancho da Vima nao ocupa a primeira dobra", async ({ page }) => {
  await page.goto("/pagar");

  await expect(page.getByText(/Mostrando 1 de 213/i)).toBeVisible();

  const tabela = await page.locator("table").boundingBox();
  expect(tabela, "tabela sem caixa").not.toBeNull();
  // A lista é o motivo de a página existir: ela tem de começar dentro da primeira tela.
  expect(tabela!.y, "a tabela nasce abaixo da dobra").toBeLessThan(740);
});
```

⚠️ Confirme a rota real da tela antes de rodar: `grep -rn "PagarPage" apps/web/src/app`. Se o
caminho não for `/pagar`, ajuste os três `page.goto`.

- [ ] **Step 2: Rodar o gate**

```
cd apps/web && pnpm playwright test e2e/pagar-360.spec.ts
```

Esperado: PASS nos três. Se algo estourar a largura, o conserto é no `flex-wrap`/`basis` da barra —
não afrouxe a asserção.

- [ ] **Step 3: Commit**

```bash
git add apps/web/e2e/pagar-360.spec.ts
git commit -m "test: gate de layout de contas a pagar a 360px"
```

---

### Task 9: verificação final e registro no CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (raiz do repositório)

**Interfaces:**
- Consumes: tudo das Tasks 1-8.
- Produces: nada.

- [ ] **Step 1: Rodar a suíte de backend completa**

```
cd apps/api && .venv/Scripts/python -m pytest -q
```

Esperado: PASS. Rodar em primeiro plano e ler a saída inteira.

- [ ] **Step 2: Rodar a suíte de backend em UTC**

```
cd apps/api && TZ=UTC .venv/Scripts/python -m pytest -q
```

Esperado: PASS. Esta classe de quebra noturna já reincidiu duas vezes neste repositório; um teste
que passa no fuso local e falha em UTC é bug real, não flakiness.

- [ ] **Step 3: Rodar o isolamento por tenant**

```
cd apps/api && .venv/Scripts/python -m pytest -m rls_e2e
```

Exige Docker (leva ~10s). Esta task **mexeu em construtor de query**: um filtro que vaze escopo de
tenant é bug de segurança, não de usabilidade, e este marcador fica fora do `pytest -q` por padrão.

- [ ] **Step 4: Rodar front e gate de layout**

```
cd apps/web && pnpm vitest run && pnpm tsc --noEmit && pnpm playwright test
```

Esperado: PASS em tudo.

- [ ] **Step 5: Registrar no CLAUDE.md**

Acrescentar à seção de Contas a Pagar:

```markdown
### Contas a Pagar — o recorte da lista (2026-08-18)

A tela abre em **"o que eu devo"**: `status ∈ (open, scheduled)`, **sem piso de data** e com teto no
fim do mês seguinte. O "sem piso" é deliberado — atrasado vence no passado, e um `from` na visão
padrão esconderia a conta mais urgente que existe. Histórico (pago/cancelado) vem `order=desc`.

`GET /payables/bills` devolve **`{items, total}`**, não lista nua, e aceita `status` (repetível),
`from`, `to`, `q`, `cost_center_id`, `chart_account_id`, `order`, `limit`, `offset`. O `total` é o
do recorte inteiro: é ele que sustenta o "Mostrando 50 de 213". Antes desta mudança a rota devolvia
as **200 mais antigas** e o resto sumia sem aviso — inclusive contas futuras ainda por pagar.

`list_payables` e `count_payables` compartilham `_filtros()`. **Não duplique o `where`**: divergindo,
o rodapé passa a anunciar um número que a lista não confirma, sem nada quebrar.

`POST /payables/bills/{id}/reactivate` devolve conta cancelada para `open` **com o vencimento
original**. Não é `/reverse`: aquele apaga movimento bancário, e conta cancelada nunca teve um.

A **busca da barra de cima continua desligada** (`AppShell.tsx`, input sem handler). Não é
regressão e não é bug — é o Projeto B, ainda sem spec. O filtro de texto de Contas a Pagar é o
primitivo que ele vai reusar.
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: registra o recorte de contas a pagar e o reactivate"
```

---

## Verificação de cobertura da spec

| Seção da spec | Task |
|---|---|
| §3 visão padrão (dois status, sem piso, horizonte) | 4 (`filtroPadrao`), 6 (barra) |
| §3 ordenação por intenção | 2 (`order`), 4 (`ordem()`) |
| §4 contagem honesta + carregar mais | 5 |
| §4 cards não seguem o filtro | 5 (não são tocados, de propósito) |
| §4 `GanchoDaVima` desce | 6 |
| §5.1 `{items,total}` + params | 1, 2 |
| §5.2 predicado único | 1, 2 |
| §5.3 escape de curinga | 2 |
| §5.4 horizonte no fuso do tenant | 4 |
| §5.5 paginação | 1, 5 |
| §6 reativar (rota, serviço, vencimento preservado) | 3, 7 |
| §7 peças | 1-7 |
| §8 testes | todas |
| §9 360px | 8 |
| §11 assimetria de receivables | fora de escopo, registrada |
| §12 CLAUDE.md | 9 |
