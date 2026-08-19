# Busca global — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** ligar o campo "Buscar cliente, projeto ou processo" da barra de cima, com uma camada rasa
(dropdown) e uma camada funda (página `/busca`) sobre sete entidades.

**Architecture:** um módulo `search` com um registro declarativo de entidades; o serviço roda uma
consulta curta por tipo e agrupa em Python — sem `UNION`, sem migration, sem índice novo (a medição
provou que a RLS impede qualquer índice de texto; ver spec §5). No front, um hook com debounce e
`AbortController` alimenta o dropdown do `AppShell` e a página `/busca`.

**Tech Stack:** FastAPI + SQLAlchemy 2 (Python 3.13), React + React Router + axios, pytest
(SQLite in-memory), vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-18-busca-global-design.md`

## Global Constraints

- **Datas sempre no fuso do tenant.** Backend: `hoje_do_tenant(db)` de
  `app.modules.settings.service`. Front: `useFuso()` de `store/auth.tsx` + `today(fuso)` de
  `lib/datetime.ts`. `datetime.now(UTC).date()` e `new Date()` cru são regressão.
- **Nenhuma query filtra tenant à mão.** O isolamento é da RLS; rotas usam
  `Depends(get_tenant_db)`. Ver `apps/api/app/db/session.py`.
- **`pytest -q` roda SQLite** (`tests/conftest.py:22`) — nada de SQL específico de Postgres no
  caminho da busca.
- **`paramsSerializer: {indexes: null}`** em `apps/web/src/lib/api.ts` não se mexe: sem ele o
  FastAPI ignora parâmetro repetido em silêncio.
- **Layout se prova medindo** com Playwright a 360px (`e2e/support/medidas.ts`). `toContain` de
  classe CSS não é prova.
- **Commits em português, conventional commits.** `main` é protegida: tudo por PR.
- **Antes de dizer "verde":** `pytest -q`, `TZ=UTC pytest -q` e `pytest -m rls_e2e` (este exige
  Docker). Rodar em primeiro plano.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `apps/api/app/core/textsearch.py` | escapar curinga e montar padrão de `ilike` — o primitivo, um lugar só | 1 |
| `apps/api/app/modules/search/registro.py` | as sete entidades, declarativas: campos, módulo RBAC, rótulo, rota | 2 |
| `apps/api/app/modules/search/service.py` | `buscar()` — uma consulta por tipo, agrupa, ordena | 2, 4 |
| `apps/api/app/modules/search/schemas.py` | `SearchItemOut`, `SearchGroupOut`, `SearchOut` | 3 |
| `apps/api/app/modules/search/router.py` | `GET /search`, filtro de RBAC | 3 |
| `apps/web/src/features/busca/resultado.ts` | rótulos, ordem, tipos do front — sem DOM | 6 |
| `apps/web/src/features/busca/useBusca.ts` | debounce + `AbortController` + estado | 6 |
| `apps/web/src/features/busca/BuscaGlobal.tsx` | campo + dropdown + teclado | 7 |
| `apps/web/src/features/busca/BuscaPage.tsx` | `/busca?q=` — camada funda, seletor de meses | 8 |

Backend e front ficam em módulos próprios porque `AppShell.tsx` já carrega a barra inteira e
`PagarPage.tsx` (660 linhas) é o exemplo de onde não se quer chegar. `resultado.ts` sem DOM é o que
permite testar ordem e rótulos sem montar a página.

---

## Task 1: O primitivo de texto, e a dívida do CRM

**Files:**
- Create: `apps/api/app/core/textsearch.py`
- Modify: `apps/api/app/modules/payables/service.py` (remove `_escapa_curinga`, importa o novo)
- Modify: `apps/api/app/modules/crm/service.py:392-393`
- Test: `apps/api/tests/test_textsearch.py` (criar), `apps/api/tests/test_crm.py` (acrescentar)

**Interfaces:**
- Consumes: nada.
- Produces: `escapa_curinga(termo: str) -> str` e `padrao_ilike(termo: str) -> str` em
  `app.core.textsearch`. As tasks 2 e 4 usam `padrao_ilike`.

- [ ] **Step 1: Escrever o teste que REPROVA o código de hoje**

Em `apps/api/tests/test_crm.py`, acrescentar (o arquivo já tem fixtures de cliente; seguir o padrão
local para criar clientes):

```python
def test_busca_do_crm_trata_porcento_como_texto(client, db):
    """`%` sem escape casa com TODAS as linhas: a busca parece funcionar e não filtra nada.

    Mesmo defeito que o #125 consertou em payables. Este teste FALHA no código de hoje.
    """
    _cria_cliente(db, name="Ana Souza")
    _cria_cliente(db, name="Bruno Lima")

    r = client.get("/crm/clients", params={"search": "%"}, headers=_auth())

    assert r.status_code == 200
    assert r.json() == [], "buscar '%' deve casar com NADA — hoje devolve todos os clientes"
```

Se `_cria_cliente`/`_auth` não existirem com esses nomes no arquivo, usar os helpers que já estão
lá; não criar helpers novos.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_crm.py::test_busca_do_crm_trata_porcento_como_texto -v`
Expected: FAIL — a resposta traz os dois clientes.

- [ ] **Step 3: Criar o primitivo**

`apps/api/app/core/textsearch.py`:

```python
"""Primitivo de busca textual — um lugar só para escapar curinga e montar o padrão do `ilike`.

Extraído de `payables/service.py` (#125) quando a busca global passou a precisar dele em sete
tabelas. Manter aqui, e não copiado por módulo: duas cópias divergem, e o modo de falha é mudo.
"""
from __future__ import annotations


def escapa_curinga(termo: str) -> str:
    """Neutraliza `%` e `_` para que o texto do usuário seja tratado como TEXTO no `ilike`.

    Sem isto, buscar `%` casa com todas as linhas e a busca parece funcionar enquanto não filtra
    nada — o pior tipo de defeito de busca, porque não tem sintoma.

    A barra invertida é escapada PRIMEIRO: fazê-lo por último re-escaparia as barras que os dois
    `replace` seguintes acabaram de inserir.
    """
    return termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def padrao_ilike(termo: str) -> str:
    """`%termo%` com o termo já escapado. Use sempre com `.ilike(padrao, escape="\\\\")`."""
    return f"%{escapa_curinga(termo)}%"
```

- [ ] **Step 4: Teste do primitivo**

`apps/api/tests/test_textsearch.py`:

```python
from app.core.textsearch import escapa_curinga, padrao_ilike


def test_escapa_porcento_e_underline():
    assert escapa_curinga("100%") == "100\\%"
    assert escapa_curinga("a_b") == "a\\_b"


def test_barra_invertida_e_escapada_primeiro():
    """Se a barra fosse escapada por último, ela duplicaria as barras recém-inseridas."""
    assert escapa_curinga("\\%") == "\\\\\\%"


def test_padrao_envolve_em_porcento_nao_escapados():
    assert padrao_ilike("ana") == "%ana%"
    assert padrao_ilike("50%") == "%50\\%%"
```

- [ ] **Step 5: Trocar as duas cópias**

Em `apps/api/app/modules/payables/service.py`: apagar a função `_escapa_curinga` e importar
`from app.core.textsearch import padrao_ilike`. Em `_filtros`, trocar
`alvo = f"%{_escapa_curinga(q)}%"` por `alvo = padrao_ilike(q)`. Não mudar mais nada — o
`escape="\\"` das duas chamadas `.ilike` permanece.

Em `apps/api/app/modules/crm/service.py:392-393`, trocar:

```python
    if search:
        like = f"%{search}%"
        stmt = stmt.where(Client.name.ilike(like))
```

por:

```python
    if search:
        # `escape` + `padrao_ilike`: sem os dois, buscar `%` casa com todas as linhas e a busca
        # parece funcionar enquanto não filtra nada (mesmo defeito do #125 em payables).
        stmt = stmt.where(Client.name.ilike(padrao_ilike(search), escape="\\"))
```

com `from app.core.textsearch import padrao_ilike` no topo.

- [ ] **Step 6: Rodar tudo e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_textsearch.py tests/test_crm.py tests/test_payables.py -v`
Expected: PASS, incluindo o `test_q_escapa_curinga_do_like` que já existia em payables — ele é a
rede que prova que a extração não mudou comportamento.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/core/textsearch.py apps/api/tests/test_textsearch.py apps/api/app/modules/payables/service.py apps/api/app/modules/crm/service.py apps/api/tests/test_crm.py
git commit -m "fix: buscar % no CRM devolvia todos os clientes

O primitivo de escape do #125 sai de payables e vira core/textsearch.py, com
tres chamadores. O CRM montava f\"%{search}%\" sem escapar nada: digitar % casava
com tudo e a busca parecia funcionar enquanto nao filtrava nada."
```

---

## Task 2: O registro das sete entidades e a busca rasa

**Files:**
- Create: `apps/api/app/modules/search/__init__.py` (vazio)
- Create: `apps/api/app/modules/search/registro.py`
- Create: `apps/api/app/modules/search/service.py`
- Test: `apps/api/tests/test_search_service.py`

**Interfaces:**
- Consumes: `padrao_ilike` da Task 1.
- Produces:
  - `Entidade` (dataclass) e `REGISTRO: tuple[Entidade, ...]` em `search.registro`
  - `buscar(db, *, q: str, modulos_liberados: list[str], limite: int = 3) -> list[GrupoBruto]`
    (a Task 4 **acrescenta** `profundidade` e `meses` a esta mesma função; nada é renomeado)
  - `GrupoBruto` = `dataclass(tipo: str, itens: list[ItemBruto], tem_mais: bool,
    total: int | None = None)`
  - `ItemBruto` = `dataclass(id: str, titulo: str, subtitulo: str, rota: str,
    trecho: str | None = None)`

  A Task 3 monta os schemas a partir desses três nomes.

- [ ] **Step 1: Escrever os testes da busca rasa**

`apps/api/tests/test_search_service.py`:

```python
"""A busca global — camada rasa. SQLite, como todo o `pytest -q`."""
from app.modules.crm.models import Client
from app.modules.juridico.models import LegalDocument
from app.modules.search.service import buscar
from app.modules.whatsapp_inbox.models import WhatsappChat

TODOS = []  # lista vazia = sem restrição de módulo (mesma regra de require_module)


def _cliente(db, tenant="t-aaaaaaaa", **kw):
    c = Client(tenant_id=tenant, name=kw.pop("name", "Ana Souza"), **kw)
    db.add(c)
    db.commit()
    return c


def test_casa_pelo_nome_do_cliente(db):
    _cliente(db, name="Ana Souza")
    _cliente(db, name="Bruno Lima")

    grupos = {g.tipo: g for g in buscar(db, q="ana", modulos_liberados=TODOS)}

    assert [i.titulo for i in grupos["client"].itens] == ["Ana Souza"]
    assert grupos["client"].itens[0].rota.startswith("/crm/clients/")


def test_casa_pelo_email_e_pelo_telefone(db):
    _cliente(db, name="Zulmira", email="contato@padaria.com.br", phone="11999998888")

    por_email = buscar(db, q="padaria", modulos_liberados=TODOS)
    por_telefone = buscar(db, q="99999", modulos_liberados=TODOS)

    assert {g.tipo for g in por_email if g.itens} == {"client"}
    assert {g.tipo for g in por_telefone if g.itens} == {"client"}


def test_porcento_nao_casa_com_tudo(db):
    _cliente(db, name="Ana Souza")

    grupos = buscar(db, q="%", modulos_liberados=TODOS)

    assert all(g.itens == [] for g in grupos)


def test_termo_curto_nao_devolve_nada(db):
    _cliente(db, name="Ana Souza")

    assert buscar(db, q="a", modulos_liberados=TODOS) == []
    assert buscar(db, q=" ", modulos_liberados=TODOS) == []


def test_prefixo_vem_antes_de_casamento_no_meio(db):
    _cliente(db, name="Mariana Costa")   # 'ana' no meio
    _cliente(db, name="Ana Beatriz")     # 'ana' no começo

    itens = {g.tipo: g for g in buscar(db, q="ana", modulos_liberados=TODOS)}["client"].itens

    assert [i.titulo for i in itens] == ["Ana Beatriz", "Mariana Costa"]


def test_grupo_vazio_nao_entra_no_resultado(db):
    _cliente(db, name="Ana Souza")

    tipos = {g.tipo for g in buscar(db, q="ana", modulos_liberados=TODOS)}

    assert tipos == {"client"}


def test_tem_mais_quando_passa_do_limite(db):
    for i in range(5):
        _cliente(db, name=f"Ana {i}")

    grupo = {g.tipo: g for g in buscar(db, q="ana", modulos_liberados=TODOS, limite=3)}["client"]

    assert len(grupo.itens) == 3
    assert grupo.tem_mais is True
    assert grupo.total is None, "camada rasa não conta — conta é da funda"


def test_conversa_casa_pelo_nome_do_cliente_vinculado(db):
    """`WhatsappChat.title` é nullable; quem procura conversa procura pelo nome da pessoa."""
    ana = _cliente(db, name="Ana Souza")
    db.add(WhatsappChat(tenant_id="t-aaaaaaaa", chat_jid="5511@s.whatsapp.net",
                        title=None, client_id=ana.id))
    db.commit()

    grupos = {g.tipo: g for g in buscar(db, q="ana", modulos_liberados=TODOS)}

    assert grupos["conversation"].itens[0].titulo == "Ana Souza"


def test_modulo_bloqueado_nao_produz_grupo(db):
    """RBAC (spec §6.4): sub-usuário sem `juridico` não recebe grupo de jurídico."""
    _cliente(db, name="Ana Souza")
    db.add(LegalDocument(tenant_id="t-aaaaaaaa", skill="peticao", title="Peticao da Ana"))
    db.commit()

    tipos = {g.tipo for g in buscar(db, q="ana", modulos_liberados=["crm"])}

    assert "client" in tipos
    assert "legal_document" not in tipos
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_search_service.py -v`
Expected: FAIL com `ModuleNotFoundError: app.modules.search`.

- [ ] **Step 3: Escrever o registro**

`apps/api/app/modules/search/registro.py`:

```python
"""As entidades que a busca global enxerga — declarativas, num lugar só.

Acrescentar um tipo é acrescentar uma entrada. O que NÃO entra aqui: lista sem endereço que saiba
receber busca (contas a pagar, cobranças, produtos — ver spec §2 e issue #138).

`modulo` não é decoração: a RLS garante o tenant certo, não que ESTE usuário pode ver ESTE módulo.
Sem ele, esta rota seria a porta dos fundos do `require_module` (spec §6.4).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.modules.contracts.models import Contract
from app.modules.crm.models import Client
from app.modules.funnels.models import Funnel
from app.modules.juridico.models import LegalDocument
from app.modules.pages.models import Page
from app.modules.quotes.models import Quote
from app.modules.whatsapp_inbox.models import WhatsappChat


@dataclass(frozen=True)
class Entidade:
    tipo: str
    modelo: Any
    modulo: str
    campos_rasos: tuple
    campos_fundos: tuple
    principal: Any               # coluna que decide "prefixo vem antes" na ordenação
    recencia: Any
    titulo: Callable[[Any], str]
    subtitulo: Callable[[Any], str]
    rota: Callable[[Any], str]
    # Predicado alternativo: usado só por `conversation`, que casa por join e não por coluna.
    # NOTA: a Task 4 acrescenta dois parâmetros a este callable (`fundo`, `corte`). Se você já
    # está implementando as duas, escreva direto na forma de quatro argumentos.
    predicado: Callable[[str, str], Any] | None = field(default=None)


def _predicado_da_conversa(padrao: str, escape: str):
    """Conversa casa pelo título OU pelo nome do cliente vinculado.

    `WhatsappChat.title` é nullable e curto (grupo sem assunto conhecido, `@lid` sem telefone).
    Ninguém procura conversa pelo título dela — procura pelo nome da pessoa, que mora em `clients`.
    """
    from sqlalchemy import or_, select

    subquery = select(Client.id).where(Client.name.ilike(padrao, escape=escape))
    return or_(
        WhatsappChat.title.ilike(padrao, escape=escape),
        WhatsappChat.client_id.in_(subquery),
    )


REGISTRO: tuple[Entidade, ...] = (
    Entidade(
        tipo="client", modelo=Client, modulo="crm",
        campos_rasos=(Client.name, Client.email, Client.phone, Client.document),
        campos_fundos=(Client.notes,),
        principal=Client.name, recencia=Client.updated_at,
        titulo=lambda c: c.name,
        subtitulo=lambda c: c.email or c.phone or "",
        rota=lambda c: f"/crm/clients/{c.id}",
    ),
    Entidade(
        tipo="conversation", modelo=WhatsappChat, modulo="crm",
        campos_rasos=(WhatsappChat.title,), campos_fundos=(),
        principal=WhatsappChat.title, recencia=WhatsappChat.updated_at,
        titulo=lambda ch: ch.title or "Conversa",
        subtitulo=lambda ch: ch.chat_jid,
        rota=lambda ch: f"/conversas/{ch.id}",
        predicado=_predicado_da_conversa,
    ),
    Entidade(
        tipo="contract", modelo=Contract, modulo="contracts",
        campos_rasos=(Contract.title, Contract.signer_name), campos_fundos=(),
        principal=Contract.title, recencia=Contract.updated_at,
        titulo=lambda c: c.title,
        subtitulo=lambda c: c.signer_name or c.status,
        rota=lambda c: f"/contratos/{c.id}",
    ),
    Entidade(
        tipo="quote", modelo=Quote, modulo="quotes",
        campos_rasos=(Quote.title, Quote.client_name), campos_fundos=(Quote.notes,),
        principal=Quote.title, recencia=Quote.updated_at,
        titulo=lambda q: q.title,
        subtitulo=lambda q: q.client_name or q.status,
        rota=lambda q: f"/orcamentos/{q.id}",
    ),
    Entidade(
        tipo="legal_document", modelo=LegalDocument, modulo="juridico",
        campos_rasos=(LegalDocument.title, LegalDocument.skill),
        campos_fundos=(LegalDocument.content,),
        principal=LegalDocument.title, recencia=LegalDocument.updated_at,
        titulo=lambda d: d.title,
        subtitulo=lambda d: d.skill,
        rota=lambda d: f"/juridico/{d.id}",
    ),
    Entidade(
        tipo="page", modelo=Page, modulo="pages",
        campos_rasos=(Page.title, Page.public_slug), campos_fundos=(),
        principal=Page.title, recencia=Page.updated_at,
        titulo=lambda p: p.title,
        subtitulo=lambda p: p.public_slug or p.status,
        rota=lambda p: f"/sites/{p.id}",
    ),
    Entidade(
        tipo="funnel", modelo=Funnel, modulo="funnels",
        campos_rasos=(Funnel.name,), campos_fundos=(),
        principal=Funnel.name, recencia=Funnel.updated_at,
        titulo=lambda f: f.name,
        subtitulo=lambda f: "",
        rota=lambda f: f"/funis/{f.id}",
    ),
)
```

Se algum campo não existir com esse nome (ex.: `Contract.signer_name`, `Page.status`), **conferir o
modelo e corrigir a entrada** — não inventar campo. A ordem das entradas é a ordem dos grupos na
tela e não deve ser alterada.

- [ ] **Step 4: Escrever o serviço (camada rasa)**

`apps/api/app/modules/search/service.py`:

```python
"""A busca global. Uma consulta curta por tipo, agrupada em Python.

Sem `UNION`: como o resultado é agrupado por tipo (spec §9), não existe ranking global a calcular e
não há nada para o banco juntar. Cada consulta fica trivial e idêntica em SQLite e Postgres — que é
o que mantém isto coberto pelo `pytest -q`.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.core.textsearch import escapa_curinga, padrao_ilike
from app.modules.search.registro import REGISTRO, Entidade

MIN_CARACTERES = 2
_ESCAPE = "\\"


@dataclass
class ItemBruto:
    id: str
    titulo: str
    subtitulo: str
    rota: str
    trecho: str | None = None


@dataclass
class GrupoBruto:
    tipo: str
    itens: list[ItemBruto]
    tem_mais: bool
    total: int | None = None


def _liberado(entidade: Entidade, modulos_liberados: list[str]) -> bool:
    """Espelha `require_module`: lista vazia = sem restrição. Ver spec §6.4."""
    return not modulos_liberados or entidade.modulo in modulos_liberados


def _predicado(entidade: Entidade, padrao: str):
    if entidade.predicado is not None:
        return entidade.predicado(padrao, _ESCAPE)
    return or_(*[c.ilike(padrao, escape=_ESCAPE) for c in entidade.campos_rasos])


def _ordem(entidade: Entidade, termo: str):
    """Dois degraus: prefixo antes de casamento no meio; depois, o mais recente.

    Dois e não três porque cabe num `case()` portátil e num teste que se lê.
    """
    prefixo = f"{escapa_curinga(termo)}%"
    return (
        case((entidade.principal.ilike(prefixo, escape=_ESCAPE), 0), else_=1),
        entidade.recencia.desc(),
    )


def buscar(
    db: Session,
    *,
    q: str,
    modulos_liberados: list[str],
    limite: int = 3,
) -> list[GrupoBruto]:
    termo = " ".join(q.split())
    if len(termo) < MIN_CARACTERES:
        # Uma letra casa com quase tudo e custaria sete varreduras por tecla.
        return []

    padrao = padrao_ilike(termo)
    grupos: list[GrupoBruto] = []

    for entidade in REGISTRO:
        if not _liberado(entidade, modulos_liberados):
            continue
        stmt = (
            select(entidade.modelo)
            .where(_predicado(entidade, padrao))
            .order_by(*_ordem(entidade, termo))
            .limit(limite + 1)  # +1 = descobre `tem_mais` sem um `count()` por tipo
        )
        linhas = list(db.scalars(stmt).all())
        if not linhas:
            continue
        grupos.append(
            GrupoBruto(
                tipo=entidade.tipo,
                itens=[
                    ItemBruto(
                        id=linha.id,
                        titulo=entidade.titulo(linha),
                        subtitulo=entidade.subtitulo(linha),
                        rota=entidade.rota(linha),
                    )
                    for linha in linhas[:limite]
                ],
                tem_mais=len(linhas) > limite,
            )
        )
    return grupos
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_search_service.py -v`
Expected: PASS nos 9 testes.

Se `test_conversa_casa_pelo_nome_do_cliente_vinculado` falhar por causa do `in_(subquery)` em
SQLite, **não trocar por filtro em Python** — conferir o `select` da subquery. Filtrar em Python
quebraria o `limit` e o `tem_mais`.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/search/ apps/api/tests/test_search_service.py
git commit -m "feat: o registro das sete entidades e a busca rasa

Uma consulta por tipo, sem UNION: como o resultado e agrupado por tipo, nao ha
ranking global a calcular e nada para o banco juntar. Conversa casa pelo nome do
cliente vinculado, porque WhatsappChat.title e nullable e ninguem procura conversa
pelo titulo dela."
```

---

## Task 3: A rota `GET /search`

**Files:**
- Create: `apps/api/app/modules/search/schemas.py`
- Create: `apps/api/app/modules/search/router.py`
- Modify: `apps/api/app/modules/__init__.py` (import + entrada em `ALL_ROUTERS`)
- Test: `apps/api/tests/test_search_router.py`

**Interfaces:**
- Consumes: `buscar`, `GrupoBruto`, `ItemBruto` da Task 2.
- Produces: `GET /search?q=&depth=&months=&limit=` devolvendo
  `{"groups": [{"type","has_more","total","items":[{"id","title","subtitle","route","snippet"}]}]}`.
  A Task 6 escreve os tipos do front a partir disso.

- [ ] **Step 1: Escrever o teste da rota**

`apps/api/tests/test_search_router.py`:

```python
def test_rota_agrupa_por_tipo(client, db):
    _cria_cliente(db, name="Ana Souza")

    r = client.get("/search", params={"q": "ana"}, headers=_auth())

    assert r.status_code == 200
    grupos = r.json()["groups"]
    assert grupos[0]["type"] == "client"
    assert grupos[0]["items"][0]["title"] == "Ana Souza"
    assert grupos[0]["items"][0]["route"].startswith("/crm/clients/")
    assert grupos[0]["has_more"] is False
    assert grupos[0]["total"] is None


def test_termo_curto_devolve_lista_vazia(client, db):
    _cria_cliente(db, name="Ana Souza")

    r = client.get("/search", params={"q": "a"}, headers=_auth())

    assert r.status_code == 200
    assert r.json() == {"groups": []}


def test_sem_token_e_401(client):
    assert client.get("/search", params={"q": "ana"}).status_code == 401
```

Reusar os helpers de autenticação já existentes nos testes do repositório (ver
`tests/test_crm.py`); não criar um esquema de auth novo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_search_router.py -v`
Expected: FAIL com 404 — a rota não existe.

- [ ] **Step 3: Schemas**

`apps/api/app/modules/search/schemas.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class SearchItemOut(BaseModel):
    id: str
    title: str
    subtitle: str
    route: str
    snippet: str | None = None


class SearchGroupOut(BaseModel):
    type: str
    has_more: bool
    # `total` só existe em `depth=deep`. Na camada rasa, contar custaria sete `count()` por tecla
    # — e `has_more` não tem como mentir sobre um número que não anuncia.
    total: int | None = None
    items: list[SearchItemOut]


class SearchOut(BaseModel):
    groups: list[SearchGroupOut]
```

- [ ] **Step 4: Router**

`apps/api/app/modules/search/router.py`:

```python
"""Busca global — a rota.

Sem `require_module`: a busca cruza sete módulos e um guard só não serviria. O RBAC entra como
FILTRO por entidade (spec §6.4), usando o mesmo critério de `require_module` — dono ou
`allowed_modules` vazio vê tudo.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser, get_current_user, get_tenant_db
from app.modules.search import service
from app.modules.search.schemas import SearchGroupOut, SearchItemOut, SearchOut

router = APIRouter(prefix="/search", tags=["search"])


def _modulos(user: CurrentUser) -> list[str]:
    """Mesma regra de `require_module`: owner ou lista vazia = sem restrição."""
    if user.role == "owner":
        return []
    return user.allowed_modules


@router.get("", response_model=SearchOut)
def search(
    q: str = Query(default=""),
    limit: int = Query(default=3, ge=1, le=50),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
) -> SearchOut:
    grupos = service.buscar(db, q=q, modulos_liberados=_modulos(user), limite=limit)
    return SearchOut(
        groups=[
            SearchGroupOut(
                type=g.tipo,
                has_more=g.tem_mais,
                total=g.total,
                items=[
                    SearchItemOut(
                        id=i.id, title=i.titulo, subtitle=i.subtitulo,
                        route=i.rota, snippet=i.trecho,
                    )
                    for i in g.itens
                ],
            )
            for g in grupos
        ]
    )
```

- [ ] **Step 5: Registrar o router**

Em `apps/api/app/modules/__init__.py`: acrescentar
`from app.modules.search.router import router as search_router` junto dos outros imports (ordem
alfabética) e `search_router` na lista `ALL_ROUTERS`.

- [ ] **Step 6: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_search_router.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/search/ apps/api/app/modules/__init__.py apps/api/tests/test_search_router.py
git commit -m "feat: GET /search devolve os resultados agrupados por tipo

Sem require_module na rota: a busca cruza sete modulos e um guard so nao serviria.
O RBAC entra como filtro por entidade, com o mesmo criterio (dono ou
allowed_modules vazio ve tudo)."
```

---

## Task 4: A camada funda

**Files:**
- Modify: `apps/api/app/modules/search/service.py`
- Modify: `apps/api/app/modules/search/router.py`
- Test: `apps/api/tests/test_search_deep.py`

**Interfaces:**
- Consumes: tudo da Task 2 e 3.
- Produces: `buscar(..., profundidade="deep", meses=12)` preenchendo `trecho` e `total`;
  a rota aceita `depth=shallow|deep` e `months=3|12|0` (`0` = tudo).

- [ ] **Step 1: Escrever os testes**

`apps/api/tests/test_search_deep.py`:

```python
"""Camada funda: corpo de documento, notas e mensagens, com recorte de meses."""
from datetime import UTC, datetime, timedelta


def test_acha_no_corpo_do_documento_juridico(db):
    from app.modules.juridico.models import LegalDocument
    from app.modules.search.service import buscar

    db.add(LegalDocument(tenant_id="t-aaaaaaaa", skill="peticao", title="Peticao 1",
                         content="... pedido de rescisao antecipada ..."))
    db.commit()

    rasa = buscar(db, q="rescisao", modulos_liberados=[])
    funda = buscar(db, q="rescisao", modulos_liberados=[], profundidade="deep")

    assert rasa == [], "corpo não é lido na camada rasa"
    assert {g.tipo for g in funda} == {"legal_document"}
    assert "rescisao" in funda[0].itens[0].trecho.lower()


def test_funda_conta_o_total_exato(db):
    from app.modules.juridico.models import LegalDocument
    from app.modules.search.service import buscar

    for i in range(7):
        db.add(LegalDocument(tenant_id="t-aaaaaaaa", skill="peticao", title=f"Doc {i}",
                             content="rescisao"))
    db.commit()

    grupo = buscar(db, q="rescisao", modulos_liberados=[], profundidade="deep", limite=3)[0]

    assert len(grupo.itens) == 3
    assert grupo.total == 7, "na página funda a contagem É a informação; ela é exata"


def test_uma_conversa_e_UM_resultado_mesmo_com_muitas_mensagens(db):
    """Spec §3: quarenta mensagens do mesmo chat saem como uma linha, não quarenta."""
    from app.modules.search.service import buscar
    from app.modules.whatsapp_inbox.models import WhatsappChat, WhatsappMessage

    chat = WhatsappChat(tenant_id="t-aaaaaaaa", chat_jid="5511@s.whatsapp.net", title="Ana")
    db.add(chat)
    db.commit()
    for i in range(40):
        db.add(WhatsappMessage(tenant_id="t-aaaaaaaa", chat_id=chat.id, direction="in",
                               text_body=f"falamos de rescisao {i}"))
    db.commit()

    grupo = {g.tipo: g for g in
             buscar(db, q="rescisao", modulos_liberados=[], profundidade="deep")}["conversation"]

    assert len(grupo.itens) == 1
    assert grupo.total == 1


def test_recorte_de_meses_vale_SO_para_mensagens(db):
    """Spec §6.2: cortar documentos por data esconderia a petição de dois anos atrás."""
    from app.modules.juridico.models import LegalDocument
    from app.modules.search.service import buscar
    from app.modules.whatsapp_inbox.models import WhatsappChat, WhatsappMessage

    antigo = datetime.now(UTC) - timedelta(days=800)
    doc = LegalDocument(tenant_id="t-aaaaaaaa", skill="peticao", title="Antiga",
                        content="rescisao")
    doc.created_at = antigo
    db.add(doc)
    chat = WhatsappChat(tenant_id="t-aaaaaaaa", chat_jid="5511@s.whatsapp.net", title="Ana")
    db.add(chat)
    db.commit()
    msg = WhatsappMessage(tenant_id="t-aaaaaaaa", chat_id=chat.id, direction="in",
                          text_body="rescisao")
    msg.created_at = antigo
    db.add(msg)
    db.commit()

    tipos = {g.tipo for g in
             buscar(db, q="rescisao", modulos_liberados=[], profundidade="deep", meses=12)}

    assert "legal_document" in tipos, "documento antigo NÃO pode ser cortado pelo recorte"
    assert "conversation" not in tipos, "mensagem antiga fica fora dos últimos 12 meses"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_search_deep.py -v`
Expected: FAIL — `buscar()` não aceita `profundidade`.

- [ ] **Step 3: Implementar**

Em `service.py`, acrescentar:

```python
from datetime import datetime, time, timedelta

from sqlalchemy import func

from app.modules.settings.service import hoje_do_tenant

TRECHO_ANTES = 40
TRECHO_DEPOIS = 80


def _trecho(texto: str, termo: str) -> str:
    """Um pedaço do corpo em volta do casamento, para o leitor reconhecer o contexto."""
    if not texto:
        return ""
    pos = texto.lower().find(termo.lower())
    if pos < 0:
        return texto[:TRECHO_DEPOIS]
    inicio = max(0, pos - TRECHO_ANTES)
    fim = min(len(texto), pos + len(termo) + TRECHO_DEPOIS)
    return ("..." if inicio > 0 else "") + texto[inicio:fim] + ("..." if fim < len(texto) else "")


def _corte_de_mensagens(db: Session, meses: int) -> datetime | None:
    """A data-piso do recorte, no FUSO DO TENANT.

    `datetime.now(UTC)` aqui reintroduziria a classe de bug do fuso pela porta do filtro: em UTC-3,
    das 21h à meia-noite o piso pularia um dia inteiro. `meses=0` significa "tudo".
    """
    if meses <= 0:
        return None
    hoje = hoje_do_tenant(db)
    return datetime.combine(hoje - timedelta(days=30 * meses), time.min, tzinfo=UTC)
```

Substituir `_predicado` e `buscar` por:

```python
def _predicado(entidade: Entidade, padrao: str, fundo: bool, corte):
    """Construtor ÚNICO do predicado — usado pela LISTA e pela CONTAGEM.

    ⚠️ Não duplique este `where` do outro lado. Dois blocos copiados divergem na primeira
    manutenção, e a partir daí a tela anuncia um `total` que a própria lista não confirma: nada
    quebra, o rodapé só passa a mentir. É a lição do #125.
    """
    if entidade.predicado is not None:
        return entidade.predicado(padrao, _ESCAPE, fundo, corte)
    campos = entidade.campos_rasos + (entidade.campos_fundos if fundo else ())
    return or_(*[c.ilike(padrao, escape=_ESCAPE) for c in campos])


def buscar(
    db: Session,
    *,
    q: str,
    modulos_liberados: list[str],
    profundidade: str = "shallow",
    meses: int = 12,
    limite: int = 3,
) -> list[GrupoBruto]:
    termo = " ".join(q.split())
    if len(termo) < MIN_CARACTERES:
        return []

    fundo = profundidade == "deep"
    padrao = padrao_ilike(termo)
    corte = _corte_de_mensagens(db, meses) if fundo else None
    grupos: list[GrupoBruto] = []

    for entidade in REGISTRO:
        if not _liberado(entidade, modulos_liberados):
            continue
        onde = _predicado(entidade, padrao, fundo, corte)
        stmt = (
            select(entidade.modelo)
            .where(onde)
            .order_by(*_ordem(entidade, termo))
            .limit(limite + 1)
        )
        linhas = list(db.scalars(stmt).all())
        if not linhas:
            continue
        # `total` só na camada funda: contar na rasa custaria sete `count()` por tecla, e
        # `tem_mais` não tem como mentir sobre um número que não anuncia.
        total = (
            db.scalar(select(func.count()).select_from(entidade.modelo).where(onde))
            if fundo
            else None
        )
        grupos.append(
            GrupoBruto(
                tipo=entidade.tipo,
                itens=[
                    ItemBruto(
                        id=linha.id,
                        titulo=entidade.titulo(linha),
                        subtitulo=entidade.subtitulo(linha),
                        rota=entidade.rota(linha),
                        trecho=_trecho_da_linha(entidade, linha, termo) if fundo else None,
                    )
                    for linha in linhas[:limite]
                ],
                tem_mais=len(linhas) > limite,
                total=total,
            )
        )
    return grupos


def _trecho_da_linha(entidade: Entidade, linha, termo: str) -> str | None:
    """O primeiro campo fundo que contém o termo vira o trecho mostrado na tela."""
    for coluna in entidade.campos_fundos:
        texto = getattr(linha, coluna.key, "") or ""
        if termo.lower() in texto.lower():
            return _trecho(texto, termo)
    return None
```

E em `registro.py`, `_predicado_da_conversa` ganha a forma funda — **é ela que faz uma conversa ser
UM resultado e o recorte de meses valer só para mensagens**:

```python
def _predicado_da_conversa(padrao: str, escape: str, fundo: bool, corte):
    from sqlalchemy import or_, select

    from app.modules.whatsapp_inbox.models import WhatsappMessage

    clientes = select(Client.id).where(Client.name.ilike(padrao, escape=escape))
    condicoes = [
        WhatsappChat.title.ilike(padrao, escape=escape),
        WhatsappChat.client_id.in_(clientes),
    ]
    if fundo:
        # A subquery devolve CHATS, não mensagens: quarenta mensagens casando viram uma linha.
        mensagens = select(WhatsappMessage.chat_id).where(
            WhatsappMessage.text_body.ilike(padrao, escape=escape)
        )
        if corte is not None:
            mensagens = mensagens.where(WhatsappMessage.created_at >= corte)
        condicoes.append(WhatsappChat.id.in_(mensagens))
    return or_(*condicoes)
```

O tipo do campo no dataclass passa a `Callable[[str, str, bool, Any], Any]`, e a chamada rasa da
Task 2 vira `entidade.predicado(padrao, _ESCAPE, False, None)`.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_search_deep.py tests/test_search_service.py -v`
Expected: PASS. Rodar também `TZ=UTC` e um fuso diferente:
`cd apps/api && TZ=America/Sao_Paulo .venv/Scripts/python -m pytest tests/test_search_deep.py -v`

- [ ] **Step 5: Expor na rota**

Em `router.py`, acrescentar os parâmetros e repassá-los:

```python
    depth: str = Query(default="shallow", pattern="^(shallow|deep)$"),
    months: int = Query(default=12, ge=0, le=120),
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/search/ apps/api/tests/test_search_deep.py
git commit -m "feat: a camada funda le corpo de documento, notas e mensagens

Uma conversa e UM resultado mesmo com quarenta mensagens casando — senao o proprio
grupo se afogaria em repeticao do mesmo dialogo. O recorte de meses vale SO para
mensagens: cortar documento por data esconderia a peticao de dois anos atras, que
e justamente o que se procura por texto."
```

---

## Task 5: Isolamento cross-tenant no Postgres real

**Files:**
- Modify: `apps/api/tests/test_rls_isolation.py` (acrescentar função, NÃO criar arquivo novo)

**Interfaces:**
- Consumes: `buscar` da Task 2/4.
- Produces: nada consumido por outras tasks.

**Por que neste arquivo:** cada `PostgresContainer` custa minutos de CI, e `test_rls_isolation.py`
já faz o bootstrap do papel `e1p_app` e roda as migrations. O repositório instrui explicitamente a
estender em vez de criar mais um arquivo de testcontainer (ver o cabeçalho de
`tests/test_bank_rls.py`).

- [ ] **Step 1: Escrever o teste**

Acrescentar em `apps/api/tests/test_rls_isolation.py`:

```python
def _busca_pela_otica_de(app_url: str, tenant_id: str, termo: str) -> set[str]:
    """Roda a busca global como `e1p_app` com a GUC do tenant — RLS real, não SQLite."""
    from sqlalchemy.orm import Session

    from app.modules.search.service import buscar

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                {"tid": tenant_id},
            )
            conn.commit()
            with Session(bind=conn) as db:
                grupos = buscar(db, q=termo, modulos_liberados=[])
                return {i.titulo for g in grupos for i in g.itens}
    finally:
        engine.dispose()


def test_busca_global_nao_atravessa_tenant() -> None:
    """A busca cruza sete tabelas; o isolamento tem que valer em TODAS elas."""
    with PostgresContainer(
        "postgres:16-alpine", username=_ROOT_USER, password=_ROOT_PASS,
        dbname=_DB_NAME, driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url)

        joao = str(uuid4())
        maria = str(uuid4())
        _insert_cliente(app_url, joao, "Ana do Joao")
        _insert_cliente(app_url, maria, "Ana da Maria")

        assert _busca_pela_otica_de(app_url, joao, "ana") == {"Ana do Joao"}
        assert _busca_pela_otica_de(app_url, maria, "ana") == {"Ana da Maria"}
```

Escrever `_insert_cliente` no mesmo arquivo, espelhando `_insert_audit` que já existe lá (INSERT
cru com a GUC do tenant setada).

- [ ] **Step 2: Rodar (exige Docker)**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_rls_isolation.py -m rls_e2e -v`
Expected: PASS. Se o Docker não estiver de pé, o teste é pulado — **isso não conta como verde.**

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_rls_isolation.py
git commit -m "test: a busca global nao atravessa tenant, no Postgres real

A busca cruza sete tabelas e o isolamento tem que valer em todas. Roda como
e1p_app (nao-superusuario), no arquivo que ja tem o bootstrap — cada container
novo custa minutos de CI."
```

---

## Task 6: Os tipos e o hook do front

**Files:**
- Modify: `packages/shared-types/src/index.ts`
- Create: `apps/web/src/features/busca/resultado.ts`
- Create: `apps/web/src/features/busca/useBusca.ts`
- Test: `apps/web/src/features/busca/resultado.test.ts`

**Interfaces:**
- Consumes: o contrato JSON da Task 3/4.
- Produces: `SearchGroup`, `SearchItem` em `@e1p/shared-types`; `ROTULOS`, `ordenarGrupos()` em
  `resultado.ts`; `useBusca(q, {profundidade, meses})` devolvendo
  `{grupos, carregando, vazio}`. As Tasks 7 e 8 consomem os três.

- [ ] **Step 1: Tipos compartilhados**

Em `packages/shared-types/src/index.ts`, ao lado dos outros (escritos à mão, como `Payable`):

```ts
export type SearchType =
  | "client" | "conversation" | "contract" | "quote"
  | "legal_document" | "page" | "funnel";

export interface SearchItem {
  id: UUID;
  title: string;
  subtitle: string;
  /** Caminho pronto para o router — o backend decide para onde o resultado leva. */
  route: string;
  /** Só em depth=deep; null na camada rasa, onde não há corpo de onde extrair trecho. */
  snippet: string | null;
}

export interface SearchGroup {
  type: SearchType;
  has_more: boolean;
  /** Só em depth=deep. Na camada rasa a contagem custaria sete count() por tecla. */
  total: number | null;
  items: SearchItem[];
}
```

- [ ] **Step 2: Teste de `resultado.ts`**

`apps/web/src/features/busca/resultado.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ROTULOS, ordenarGrupos } from "./resultado";

describe("resultado da busca", () => {
  it("mantém a ordem do backend e descarta grupo vazio", () => {
    const grupos = ordenarGrupos([
      { type: "contract", has_more: false, total: null, items: [] },
      { type: "client", has_more: false, total: null,
        items: [{ id: "1", title: "Ana", subtitle: "", route: "/crm/clients/1", snippet: null }] },
    ]);
    expect(grupos.map((g) => g.type)).toEqual(["client"]);
  });

  it("tem rótulo em português para os sete tipos", () => {
    expect(Object.keys(ROTULOS)).toHaveLength(7);
    expect(ROTULOS.legal_document).toBe("Jurídico");
  });
});
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd apps/web && npx vitest run src/features/busca/resultado.test.ts`
Expected: FAIL — módulo não existe.

- [ ] **Step 4: Implementar `resultado.ts`**

```ts
import type { SearchGroup, SearchType } from "@e1p/shared-types";

/** Rótulos em português. O backend manda `type`; a UI mora aqui. */
export const ROTULOS: Record<SearchType, string> = {
  client: "Clientes",
  conversation: "Conversas",
  contract: "Contratos",
  quote: "Orçamentos",
  legal_document: "Jurídico",
  page: "Sites",
  funnel: "Funis",
};

/** A ordem é a do backend (um lugar só). Aqui só se descarta grupo sem item. */
export function ordenarGrupos(grupos: SearchGroup[]): SearchGroup[] {
  return grupos.filter((g) => g.items.length > 0);
}

/** Todos os itens numa lista só — é o que o teclado percorre, atravessando grupos. */
export function itensEmSequencia(grupos: SearchGroup[]) {
  return grupos.flatMap((g) => g.items);
}
```

- [ ] **Step 5: Implementar `useBusca.ts`**

```ts
import type { SearchGroup } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ordenarGrupos } from "./resultado";

const DEBOUNCE_MS = 250;
const MIN_CARACTERES = 2;

export function useBusca(
  q: string,
  opcoes: { profundidade?: "shallow" | "deep"; meses?: number; limite?: number } = {},
) {
  const { profundidade = "shallow", meses = 12, limite = 3 } = opcoes;
  const [grupos, setGrupos] = useState<SearchGroup[]>([]);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    const termo = q.trim();
    if (termo.length < MIN_CARACTERES) {
      setGrupos([]);
      return;
    }
    // `AbortController` não é enfeite: sem ele a resposta de uma consulta ANTERIOR chega depois e
    // sobrescreve a atual. O sintoma é "o resultado pisca errado", não um erro.
    const controle = new AbortController();
    const timer = setTimeout(async () => {
      setCarregando(true);
      try {
        const r = await api.get<{ groups: SearchGroup[] }>("/search", {
          params: { q: termo, depth: profundidade, months: meses, limit: limite },
          signal: controle.signal,
        });
        setGrupos(ordenarGrupos(r.data.groups));
      } catch {
        // Requisição cancelada é o caso normal aqui, não erro de produto.
      } finally {
        setCarregando(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controle.abort();
    };
  }, [q, profundidade, meses, limite]);

  return { grupos, carregando, vazio: !carregando && grupos.length === 0 };
}
```

- [ ] **Step 6: Rodar e ver passar**

Run: `cd apps/web && npx vitest run src/features/busca/ && npx tsc --noEmit`
Expected: PASS + typecheck limpo.

- [ ] **Step 7: Commit**

```bash
git add packages/shared-types/src/index.ts apps/web/src/features/busca/
git commit -m "feat(web): os tipos e o hook da busca global

O AbortController evita o defeito classico da busca incremental: a resposta antiga
chegando depois e sobrescrevendo a nova. Aparece como resultado piscando errado, e
nao como erro."
```

---

## Task 7: O dropdown na barra de cima

**Files:**
- Create: `apps/web/src/features/busca/BuscaGlobal.tsx`
- Modify: `apps/web/src/app/AppShell.tsx:174-195`
- Modify: `apps/web/src/app/App.tsx` (rota `/busca`)
- Test: `apps/web/src/features/busca/BuscaGlobal.test.tsx`

**Interfaces:**
- Consumes: `useBusca`, `ROTULOS`, `ordenarGrupos`, `itensEmSequencia` da Task 6.
- Produces: componente `<BuscaGlobal />`, montado pelo `AppShell`.

- [ ] **Step 1: Teste de teclado**

`apps/web/src/features/busca/BuscaGlobal.test.tsx`: montar com `MemoryRouter`, mockar `api.get`
(vitest `vi.mock("@/lib/api")`) devolvendo dois grupos com um item cada, e asserir:

```tsx
it("a seta para baixo atravessa grupos e o Enter navega para o item focado", async () => {
  render(<MemoryRouter><BuscaGlobal /></MemoryRouter>);
  const campo = screen.getByPlaceholderText("Buscar cliente, contrato ou documento");
  await userEvent.type(campo, "ana");
  await screen.findByText("Clientes");

  await userEvent.keyboard("{ArrowDown}{ArrowDown}");
  expect(screen.getByRole("option", { selected: true })).toHaveTextContent("Contrato da Ana");
});

it("Esc fecha e devolve o foco ao campo", async () => {
  // ...
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(campo).toHaveFocus();
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/web && npx vitest run src/features/busca/BuscaGlobal.test.tsx`
Expected: FAIL — componente não existe.

- [ ] **Step 3: Implementar o componente**

O miolo é o teclado — o resto é marcação:

```tsx
import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ROTULOS, itensEmSequencia } from "./resultado";
import { useBusca } from "./useBusca";

export function BuscaGlobal() {
  const [termo, setTermo] = useState("");
  const [aberto, setAberto] = useState(false);
  const [foco, setFoco] = useState(-1);          // -1 = nenhum item focado
  const campo = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { grupos, vazio } = useBusca(termo);
  const sequencia = itensEmSequencia(grupos);    // o teclado ATRAVESSA grupos

  // Ctrl/Cmd+K foca o campo. Listener no document, removido no cleanup.
  useEffect(() => {
    const atalho = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        campo.current?.focus();
      }
    };
    document.addEventListener("keydown", atalho);
    return () => document.removeEventListener("keydown", atalho);
  }, []);

  // O foco é reposicionado a cada resultado novo: manter o índice antigo apontaria para um item
  // que não está mais na lista, e o Enter abriria o registro errado.
  useEffect(() => setFoco(-1), [grupos]);

  function paraAPagina() {
    navigate(`/busca?q=${encodeURIComponent(termo)}`);
    setAberto(false);
  }

  function noTeclado(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFoco((i) => Math.min(i + 1, sequencia.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFoco((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (foco >= 0 && sequencia[foco]) {
        navigate(sequencia[foco].route);
        setAberto(false);
      } else {
        paraAPagina();
      }
    } else if (e.key === "Escape") {
      setAberto(false);
      campo.current?.focus();
    }
  }

  let indice = -1;   // numeração contínua entre grupos, para casar com `sequencia`

  return (
    <div className="relative hidden min-w-0 max-w-md flex-1 md:block" onBlur={(e) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node)) setAberto(false);
    }}>
      <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
      <input
        ref={campo}
        role="combobox"
        aria-expanded={aberto}
        aria-controls="busca-resultados"
        placeholder="Buscar cliente, contrato ou documento"
        value={termo}
        onChange={(e) => { setTermo(e.target.value); setAberto(true); }}
        onFocus={() => setAberto(true)}
        onKeyDown={noTeclado}
        className="w-full rounded-pill bg-neutral-50 py-2 pl-9 pr-4 text-sm outline-none focus:ring-2 focus:ring-primary-300"
      />
      {aberto && termo.trim().length >= 2 && (
        <div id="busca-resultados" role="listbox"
             className="absolute z-20 mt-1 w-full rounded-2xl border border-neutral-100 bg-white shadow-lg">
          {grupos.map((g) => (
            <div key={g.type}>
              <p className="px-3 pt-2 text-xs font-semibold text-neutral-400">{ROTULOS[g.type]}</p>
              {g.items.map((item) => {
                indice += 1;
                const meu = indice;
                return (
                  <button key={item.id} role="option" aria-selected={foco === meu}
                          onMouseDown={() => navigate(item.route)}
                          className={`flex w-full flex-col px-3 py-2 text-left text-sm ${foco === meu ? "bg-primary-50" : ""}`}>
                    <span className="truncate">{item.title}</span>
                    <span className="truncate text-xs text-neutral-400">{item.subtitle}</span>
                  </button>
                );
              })}
            </div>
          ))}
          {vazio && (
            <div className="px-3 py-3 text-sm text-neutral-500">
              Nada encontrado para «{termo}».{" "}
              <button onMouseDown={paraAPagina} className="text-primary-600 underline">
                procurar em documentos e mensagens
              </button>
            </div>
          )}
          {!vazio && (
            <button onMouseDown={paraAPagina}
                    className="w-full border-t border-neutral-100 px-3 py-2 text-left text-xs text-primary-600">
              ver todos os resultados
            </button>
          )}
        </div>
      )}
    </div>
  );
}
```

`onMouseDown` e não `onClick` nos itens: o `onBlur` do contêiner fecha o dropdown antes que um
`click` chegue a disparar, e o resultado é um item que não abre quando clicado com o mouse.

- [ ] **Step 4: Ligar no AppShell**

Em `AppShell.tsx`, no bloco `hidden ... md:block` (linhas ~185-195), trocar o `<input>` decorativo
por `<BuscaGlobal />`, apagando o comentário *"A busca não tem handler nenhum"*, que deixa de ser
verdade.

No botão de menu (linhas ~174-183): trocar `<Search size={16} />` por `<Menu size={16} />`
(importar `Menu` de `lucide-react`). Ele tem `aria-label="Abrir menu"` e usar uma lupa ali, com uma
lupa de verdade ao lado, seriam dois ícones iguais com significados diferentes.

Acrescentar, visível só abaixo de `md`, um botão com `aria-label="Buscar"` e ícone `Search` que faz
`navigate("/busca")`.

- [ ] **Step 5: Registrar a rota**

Em `App.tsx`, junto das rotas protegidas: `<Route path="/busca" element={<BuscaPage />} />`.
Se a Task 8 ainda não rodou, criar `BuscaPage.tsx` como um componente mínimo que renderiza o termo
— e completá-lo na Task 8. Não deixar a rota apontando para componente inexistente.

- [ ] **Step 6: Rodar e ver passar**

Run: `cd apps/web && npx vitest run && npx tsc --noEmit && npx eslint . --max-warnings 0`
Expected: PASS nos três. `AppShell.test.tsx` já existe — se ele afere o `<input>` antigo,
atualizá-lo, não removê-lo.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/busca/ apps/web/src/app/AppShell.tsx apps/web/src/app/App.tsx
git commit -m "feat(web): a busca da barra de cima passa a buscar

O botao de menu troca a lupa por Menu: com uma lupa de verdade ao lado, seriam dois
icones iguais com significados diferentes. Abaixo de md o campo continua escondido
(medicao do #58) e uma lupa leva para /busca."
```

---

## Task 8: A página `/busca`

**Files:**
- Modify: `apps/web/src/features/busca/BuscaPage.tsx`
- Test: `apps/web/src/features/busca/BuscaPage.test.tsx`

**Interfaces:**
- Consumes: `useBusca` com `profundidade: "deep"`, `ROTULOS`.
- Produces: a tela de `/busca?q=`.

- [ ] **Step 1: Teste**

```tsx
it("lê o termo da URL e busca fundo", async () => {
  render(<MemoryRouter initialEntries={["/busca?q=rescisao"]}>
    <Routes><Route path="/busca" element={<BuscaPage />} /></Routes>
  </MemoryRouter>);
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/search",
    expect.objectContaining({ params: expect.objectContaining({ q: "rescisao", depth: "deep" }) })));
});

it("mostra a contagem exata por grupo", async () => {
  // grupo com total: 12 e 3 itens
  expect(await screen.findByText("Jurídico (12)")).toBeInTheDocument();
});
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd apps/web && npx vitest run src/features/busca/BuscaPage.test.tsx`

- [ ] **Step 3: Implementar**

- Lê `q` de `useSearchParams`; digitar no campo da página atualiza a URL com `replace: true` (uma
  entrada de histórico por tecla encheria o botão "voltar").
- `useBusca(q, { profundidade: "deep", meses, limite: 20 })`.
- Seletor de meses com três opções e o rótulo **"mensagens dos últimos 12 meses"** — o recorte vale
  só para mensagens (spec §6.2), e o rótulo tem que dizer isso, senão vira recorte silencioso.
- Cada grupo: `{ROTULOS[g.type]} ({g.total})`, itens com `snippet` quando houver.
- Estado vazio honesto: *"Nada encontrado para «termo» nas mensagens dos últimos 12 meses"*, com
  atalho para ampliar o recorte.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/web && npx vitest run && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/busca/
git commit -m "feat(web): a pagina /busca procura no corpo dos documentos e nas mensagens

O seletor diz 'mensagens dos ultimos 12 meses' porque o recorte vale so para elas.
Rotulo generico faria o usuario achar que documento antigo tambem foi cortado — e
recorte que nao se anuncia e o defeito que o #125 acabou de consertar."
```

---

## Task 9: As duas medições de Playwright

**Files:**
- Create: `apps/web/e2e/busca-url.spec.ts`
- Create: `apps/web/e2e/busca-360.spec.ts`

**Interfaces:**
- Consumes: `mockarApi` (`e2e/support/api.ts`), `semearSessao` (`e2e/support/sessao.ts`),
  `medirPagina` e `alvosPequenos` (`e2e/support/medidas.ts`).
- Produces: nada.

- [ ] **Step 1: `busca-url.spec.ts` — medir a query string real**

```ts
import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { semearSessao } from "./support/sessao";

/**
 * O contrato de QUERY STRING da busca — o único lugar onde axios de verdade roda.
 *
 * As outras três camadas são cegas a isto: o pytest monta a URL crua, o vitest assere o objeto
 * `params` ANTES de serializar, e o mock e2e devolve payload fixo seja qual for a query. Foi essa
 * fresta que escondeu o `status[]` no #125.
 */
test("a busca funda manda q, depth e months na forma que o FastAPI lê", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/search": { groups: [] } });

  const urls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/search")) urls.push(r.url());
  });

  await page.goto("/busca?q=rescisao");
  await expect.poll(() => urls.length).toBeGreaterThan(0);

  const query = decodeURIComponent(new URL(urls[0]).search);
  expect(query, `query real: ${query}`).toContain("q=rescisao");
  expect(query, `query real: ${query}`).toContain("depth=deep");
  expect(query, `query real: ${query}`).toContain("months=12");
});

test("o termo do usuário vai escapado, não interpretado", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/search": { groups: [] } });
  const urls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/search")) urls.push(r.url());
  });

  await page.goto("/busca?q=100%25");
  await expect.poll(() => urls.length).toBeGreaterThan(0);

  expect(new URL(urls[0]).searchParams.get("q")).toBe("100%");
});
```

- [ ] **Step 2: `busca-360.spec.ts` — medir, não aferir classe**

```ts
import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina } from "./support/medidas";
import { semearSessao } from "./support/sessao";

test.use({ viewport: { width: 360, height: 740 } });

test("a 360px o campo some, a lupa aparece e leva para /busca", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/search": { groups: [] } });

  await page.goto("/");
  await expect(page.getByPlaceholder("Buscar cliente, contrato ou documento")).toBeHidden();

  await page.getByLabel("Buscar").click();
  await expect(page).toHaveURL(/\/busca/);
});

test("a página de resultados não rola de lado a 360px", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/search": {
      groups: [{
        type: "legal_document", has_more: true, total: 42,
        items: Array.from({ length: 20 }, (_, i) => ({
          id: `d${i}`,
          title: "Peticao inicial de rescisao contratual antecipada com pedido liminar",
          subtitle: "peticao",
          route: `/juridico/d${i}`,
          snippet: "...combinada a rescisao antecipada conforme clausula decima segunda...",
        })),
      }],
    },
  });

  await page.goto("/busca?q=rescisao");
  await expect(page.getByText("Jurídico (42)")).toBeVisible();

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina, "a página rola de lado a 360px").toBeLessThanOrEqual(360);
});
```

Os payloads são de **pior caso plausível** — título longo, 20 itens, trecho comprido. Dado curto
sempre cabe: medir com ele é medir uma tela que não existe.

- [ ] **Step 3: Rodar**

Run: `cd apps/web && npx playwright test e2e/busca-url.spec.ts e2e/busca-360.spec.ts`
Expected: PASS nos quatro.

- [ ] **Step 4: Commit**

```bash
git add apps/web/e2e/busca-url.spec.ts apps/web/e2e/busca-360.spec.ts
git commit -m "test(web): a query string e a regua de 360px da busca, medidas

A URL e medida de verdade porque as outras tres camadas sao cegas a ela — foi essa
fresta que escondeu o status[] no #125. E o layout e medido com boundingBox:
toContain de classe CSS ja passou verde com a tela quebrada neste projeto."
```

---

## Fechamento

- [ ] **Suíte inteira, em primeiro plano, nos três modos**

```bash
cd apps/api && .venv/Scripts/python -m pytest -q
cd apps/api && TZ=UTC .venv/Scripts/python -m pytest -q
cd apps/api && .venv/Scripts/python -m pytest -m rls_e2e     # exige Docker
cd apps/web && npx vitest run && npx tsc --noEmit && npx eslint . --max-warnings 0
cd apps/web && npx playwright test
```

Teste **pulado por falta de Docker não é teste verde.** Se `rls_e2e` não rodou, dizer isso.

- [ ] **Abrir o PR** (`main` é protegida; 5 checks). Corpo do PR: o que muda para o dono, a decisão
  do §5 (por que não há migration) e a nota de que a dívida do CRM foi paga junto.
