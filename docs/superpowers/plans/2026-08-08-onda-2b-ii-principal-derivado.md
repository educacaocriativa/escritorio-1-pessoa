# Onda 2b-ii — `principal_cents` derivado · Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `investment_accounts.principal_cents` deixa de ser um campo digitado e passa a ser calculado dos movimentos da conta bancária da aplicação.

**Architecture:** A soma de movimentos que já existe (`bank/service._movements_sums`, a única do repositório) ganha um recorte por `source`; `investments/service` a consome para derivar o principal, excluindo `source='yield'` para não contar o rendimento duas vezes. A coluna antiga fica congelada com gate AST. **Sem migration, sem `UPDATE`, sem tabela nova** — o backfill do design-mãe §6.2 foi substituído por um script que reporta e pela correção como ato do dono.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, pytest (SQLite em memória) · React 18 + TypeScript + Vite, vitest

**Spec:** `docs/superpowers/specs/2026-08-08-onda-2b-ii-principal-derivado-design.md`
**Branch:** `feat/onda-2b-ii-principal-derivado` (já criada, com a spec commitada)

## Global Constraints

- **Idioma:** produto e comentários de domínio em **PT-BR**. Commits em PT-BR, Conventional Commits, referenciando a onda: `feat: o principal da aplicação passa a ser calculado [Onda 2b-ii]`.
- **Dinheiro em centavos** (`int`), sempre. Nunca `float` para valor.
- **"Hoje" é `hoje_do_tenant(db)`**, nunca `date.today()` nem `datetime.now(UTC).date()`. O gate `tests/test_fuso_do_tenant.py` reprova o contrário — inclusive em teste.
- **`investments` pode importar `bank`; `bank` NÃO pode importar `investments`.** Gate: `tests/test_money_planes.py::test_bank_transfers_nao_importa_investments`.
- **RLS é a única garantia de isolamento** — nenhuma query filtra `tenant_id` manualmente.
- **Rodar a suíte em PRIMEIRO PLANO**, nunca em background: `cd apps/api && .venv/Scripts/python -m pytest -q`.
- **Nenhuma migration nesta onda.** Se um passo parecer pedir uma, pare e releia a spec §1.1.
- **`main` é protegida (GH006), 4 checks obrigatórios.** Push e PR são do `@devops`.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `apps/api/app/modules/bank/service.py` | Ganha `exclude_sources` na soma e a porta pública `movement_sums` | Modify |
| `apps/api/app/modules/investments/service.py` | `principais_derivados`, `principal_derivado`, `_pct` robusto, a recusa 409 | Modify |
| `apps/api/app/modules/investments/schemas.py` | `principal_cents` vira `int \| None` nos dois schemas de saída | Modify |
| `apps/api/app/modules/investments/router.py` | `_out` passa a receber o principal derivado | Modify |
| `apps/api/app/scripts/investment_audit.py` | Reporta divergência coluna × derivado. Sem `--fix` | Create |
| `apps/api/tests/test_investments_principal.py` | Os testes 2,3,4,5,6,10 da spec §5 | Create |
| `apps/api/tests/test_investments_principal_gate.py` | O gate AST da coluna congelada, com controle positivo | Create |
| `apps/api/tests/test_investments.py` | O teste 7 (409 em create/update) | Modify |
| `apps/web/src/features/financeiro/investimentos.ts` | Tipos `number \| null` + helper do aviso de resgate excedente | Modify |
| `apps/web/src/features/financeiro/investimentos.test.ts` | Testes puros do helper e da formatação | Modify |
| `apps/web/src/features/financeiro/InvestimentosPage.tsx` | Principal sem campo, o aviso, o extrato | Modify |
| `CLAUDE.md` | A entrada da onda — **AC obrigatório** | Modify |

---

## Task 1: A soma de movimentos aprende a excluir uma origem

**Files:**
- Modify: `apps/api/app/modules/bank/service.py:557` (`_movements_sums`), e acrescentar `movement_sums` logo após `_movements_sum` (`:647`)
- Test: `apps/api/tests/test_bank_corte_de_data.py`

**Interfaces:**
- Consumes: nada (primeira task)
- Produces:
  - `bank.service.movement_sums(db: Session, *, accounts: Sequence[BankAccount], until: date | None = None, exclude_sources: frozenset[str] = frozenset()) -> dict[str, int]` — a porta **pública** da única soma de movimentos do repositório. `until=None` significa **hoje**, como em `derived_balance`. Conta sem movimento não aparece no dicionário; o chamador usa `.get(id, 0)`.

- [ ] **Step 1: Escrever o teste que falha**

O arquivo **já tem** os helpers de que este teste precisa: as fixtures `headers` e `tenant_id`, a
fábrica `_conta(client, headers, **over)` (abre a conta **ontem**, para que "hoje" seja posterior à
abertura) e `_plantar(db, *, tenant_id, account_id, amount_cents, posted_at, status)`, que monta o
movimento **direto pelo model**. **Não crie helper novo** — o único ajuste é dar a `_plantar` a
origem da linha, que hoje é fixa em `SOURCE_MANUAL`.

Primeiro torne `_plantar` capaz de plantar outra origem. Na assinatura (`:109`), acrescente o
último parâmetro, e troque o `source=SOURCE_MANUAL` fixo do corpo por `source=source`:

```python
def _plantar(
    db: Session,
    *,
    tenant_id: str,
    account_id: str,
    amount_cents: int,
    posted_at: date,
    status: str = STATUS_UNMATCHED,
    source: str = SOURCE_MANUAL,
) -> BankTransaction:
```

Aditivo: o default preserva byte a byte o comportamento de todos os chamadores que já existem.

Agora acrescente ao final do arquivo:

```python
def test_movement_sums_exclui_a_origem_pedida(client, db, headers, tenant_id):
    """`exclude_sources` tira uma origem da soma sem tocar nas outras (Onda 2b-ii).

    É o recorte de que o principal derivado depende: o rendimento já é contado por
    `accrued_yield_cents` e, desde a 2b-i, também gera `bank_transaction` — sem este filtro ele
    entraria DUAS vezes no saldo da aplicação.

    ⚠️ **Dois `assert`, e é de propósito.** Com só o caso do rendimento excluído, ignorar
    `exclude_sources` por completo ainda passaria: é o mutante `>` → `>=` da Onda 2, que sobreviveu
    a 58 testes por faltar o caso do outro lado. O primeiro `assert` é o outro lado.
    """
    from app.modules.bank import service as bank_service
    from app.modules.bank.models import SOURCE_YIELD

    conta = _conta(client, headers, kind=KIND_INVESTMENT, opening_balance_cents=0)
    hoje = _hoje()

    _plantar(
        db, tenant_id=tenant_id, account_id=conta["id"], amount_cents=15_00, posted_at=hoje
    )
    _plantar(
        db,
        tenant_id=tenant_id,
        account_id=conta["id"],
        amount_cents=100_00,
        posted_at=hoje,
        source=SOURCE_YIELD,
    )

    acc = bank_service.get_account(db, conta["id"])

    sem_recorte = bank_service.movement_sums(db, accounts=[acc])
    assert sem_recorte.get(acc.id) == 115_00, "sem recorte, os dois movimentos entram"

    sem_rendimento = bank_service.movement_sums(
        db, accounts=[acc], exclude_sources=frozenset({SOURCE_YIELD})
    )
    assert sem_rendimento.get(acc.id) == 15_00, "o rendimento saiu; o manual FICOU"
```

`KIND_INVESTMENT` vem de `app.modules.bank.models` — acrescente-o ao bloco de import do topo do
arquivo se ele ainda não estiver lá (`KIND_CHECKING` já está).

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_corte_de_data.py::test_movement_sums_exclui_a_origem_pedida -v
```

Esperado: **FAIL** com `AttributeError: module 'app.modules.bank.service' has no attribute 'movement_sums'`.

- [ ] **Step 3: Acrescentar o parâmetro em `_movements_sums`**

Em `apps/api/app/modules/bank/service.py`, na assinatura de `_movements_sums` (`:557`), acrescente o último parâmetro:

```python
def _movements_sums(
    db: Session,
    *,
    accounts: Sequence[BankAccount],
    until: date | None = None,
    since: date | None = None,
    sign: int | None = None,
    exclude_sources: frozenset[str] = frozenset(),
) -> dict[str, int]:
```

E, dentro do corpo, logo após o bloco do `sign` (antes do `return`):

```python
    if exclude_sources:
        stmt = stmt.where(BankTransaction.source.notin_(exclude_sources))
```

Acrescente à docstring da função, junto das outras cláusulas do `WHERE`:

```
          AND (:exclude_sources vazio OR source NOT IN :exclude_sources)  -- Onda 2b-ii
```

e, abaixo da explicação do `sign`:

```
    ⚠️ **[Onda 2b-ii] `exclude_sources` existe para que o principal derivado NÃO seja uma segunda
    fórmula.** O principal de uma aplicação é a soma dos movimentos da conta dela **menos os de
    rendimento** (que já são contados por `accrued_yield_cents`). Escrever essa soma noutro lugar
    duplicaria o piso `posted_at > opening_date` e o `status <> 'ignored'`, e o dia em que um dos
    dois fosse corrigido só de um lado o principal passaria a divergir do saldo por um motivo que
    ninguém acharia. Default vazio: todo chamador anterior a esta onda segue idêntico.
```

- [ ] **Step 4: Acrescentar a porta pública**

Logo após `_movements_sum` (`apps/api/app/modules/bank/service.py:647`):

```python
def movement_sums(
    db: Session,
    *,
    accounts: Sequence[BankAccount],
    until: date | None = None,
    exclude_sources: frozenset[str] = frozenset(),
) -> dict[str, int]:
    """A porta PÚBLICA da soma de movimentos — `{bank_account_id: centavos}`.

    Fina de propósito: delega para `_movements_sums`, que continua sendo a **única** implementação
    da fórmula. Ela existe porque `investments` precisa da soma com `exclude_sources` (Onda 2b-ii) e
    importar um símbolo `_` de outro módulo é o tipo de acesso que ninguém encontra depois — e que
    o `dedup-checker` não consegue julgar.

    `until=None` significa **hoje**, como em `derived_balance` (Story 8.10). Conta sem movimento não
    aparece no dicionário; use `.get(id, 0)`.
    """
    return _movements_sums(
        db, accounts=accounts, until=resolve_until(until, _today(db)), exclude_sources=exclude_sources
    )
```

- [ ] **Step 5: Rodar o teste novo e a suíte de bank**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_corte_de_data.py -v
cd apps/api && .venv/Scripts/python -m pytest tests/ -q -k "bank"
```

Esperado: tudo **PASS**. Se algo de `bank` quebrou, o `exclude_sources` não é aditivo como deveria — pare e investigue antes de seguir.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/bank/service.py apps/api/tests/test_bank_corte_de_data.py
git commit -m "feat: a soma de movimentos aprende a excluir uma origem [Onda 2b-ii]"
```

---

## Task 2: O principal derivado

**Files:**
- Modify: `apps/api/app/modules/investments/service.py` (acrescentar após `list_accounts`, `:171`)
- Test: `apps/api/tests/test_investments_principal.py` (criar)

**Interfaces:**
- Consumes: `bank.service.movement_sums(db, *, accounts, until=None, exclude_sources=frozenset()) -> dict[str, int]` (Task 1)
- Produces:
  - `investments.service.principais_derivados(db: Session, accs: Sequence[InvestmentAccount]) -> dict[str, int | None]` — chaveado pelo id da **`InvestmentAccount`**. `None` = inafirmável (sem vínculo, ou saldo de abertura desconhecido).
  - `investments.service.principal_derivado(db: Session, acc: InvestmentAccount) -> int | None` — delega para a de lote.

- [ ] **Step 1: Escrever os testes que falham**

Crie `apps/api/tests/test_investments_principal.py`:

```python
"""O principal da aplicação é CALCULADO, não digitado (Onda 2b-ii).

    principal = opening_balance_cents da conta de aplicação
              + Σ movimentos daquela conta com source <> 'yield'

Os três termos e o porquê de cada um estão na spec §3. O que estes testes seguram é que a
derivação não vire uma segunda fórmula e não conte o rendimento duas vezes.

RLS não é exercida aqui (SQLite — ver conftest); o isolamento cross-tenant da aplicação já é
coberto por `test_investments_rls.py`.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.investments import service as inv_service
from app.modules.investments.models import InvestmentAccount

REGISTER = {
    "legal_name": "Deriva Consultoria",
    "document": "11444777000161",
    "slug": "deriva",
    "email": "deriva@example.com",
    "name": "Dora",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conta_bancaria(
    client: TestClient,
    headers,
    *,
    name="CDB Itaú",
    kind="investment",
    opening_date="2026-01-01",
    opening_balance_cents=0,
    opening_balance_is_known=True,
) -> dict:
    r = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": kind,
            "opening_date": opening_date,
            "opening_balance_cents": opening_balance_cents,
            "opening_balance_is_known": opening_balance_is_known,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _aplicacao(client: TestClient, headers, *, bank_account_id: str | None, name="Reserva") -> dict:
    r = client.post(
        "/investments",
        json={
            "name": name,
            "kind": "CDB",
            "index_rate_label": "CDI 110%",
            "opened_at": "2026-01-01",
            "bank_account_id": bank_account_id,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _transferencia(client, headers, *, de: str, para: str, valor: int, quando: str, kind: str):
    r = client.post(
        "/bank/transfers",
        json={
            "from_account_id": de,
            "to_account_id": para,
            "amount_cents": valor,
            "transfer_date": quando,
            "kind": kind,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _acc(db: Session, account_id: str) -> InvestmentAccount:
    return db.get(InvestmentAccount, account_id)


# ── Teste 6 da spec §5 ────────────────────────────────────────────────────────────────────────
def test_o_saldo_de_abertura_entra_no_principal(client, db, headers):
    """O dinheiro que já estava aplicado no dia do cadastro é principal, e nunca teve movimento.

    Sem este termo, uma conta cadastrada com R$ 10.000 aplicados mostraria principal ZERO — um
    número errado com aparência de fato, que é a família de defeito que a Onda 0 existe para não
    repetir. É também o caso do fundador: ele cadastra a conta com o saldo que já tem.
    """
    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) == 10_000_00


# ── Teste 5 da spec §5 ────────────────────────────────────────────────────────────────────────
def test_aporte_MOVE_o_principal(client, db, headers):
    """Transferir da corrente para a aplicação aumenta o principal. É a metade viva do recorte."""
    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    _transferencia(
        client,
        headers,
        de=corrente["id"],
        para=aplicacao["id"],
        valor=3_000_00,
        quando="2026-02-10",
        kind="investment_in",
    )

    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) == 13_000_00


# ── Teste 4 da spec §5 ────────────────────────────────────────────────────────────────────────
def test_rendimento_NAO_move_o_principal(client, db, headers):
    """Registrar rendimento não mexe no principal — ele já é contado por `accrued_yield_cents`.

    ⚠️ Este teste sozinho NÃO prova o recorte: se `exclude_sources` fosse ignorado e a soma
    excluísse tudo, ele passaria igual. Quem o completa é `test_aporte_MOVE_o_principal`, acima.
    Os dois juntos particionam o conjunto: um membro de cada lado.
    """
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    r = client.post(
        f"/investments/{app_['id']}/yield",
        json={"amount_cents": 150_00, "date": "2026-02-28", "chart_account_id": None},
        headers=headers,
    )
    assert r.status_code == 200, r.text

    acc = _acc(db, app_["id"])
    assert acc.accrued_yield_cents == 150_00, "o rendimento foi registrado (controle positivo)"
    assert inv_service.principal_derivado(db, acc) == 10_000_00, "e NÃO entrou no principal"


# ── Teste 2 da spec §5 — a invariante ─────────────────────────────────────────────────────────
def test_a_invariante_saldo_igual_principal_mais_rendimento(client, db, headers):
    """`derived_balance(conta) == principal + accrued_yield`, com aporte, rendimento E resgate.

    Vale POR CONSTRUÇÃO enquanto todo rendimento tiver perna bancária — que é o que a 2b-i
    garantiu com o 409 de `register_yield`. Quebrá-la é sintoma de movimento escrito por fora da
    Regra da Origem.
    """
    from app.modules.bank import service as bank_service

    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    _transferencia(
        client, headers, de=corrente["id"], para=aplicacao["id"],
        valor=3_000_00, quando="2026-02-10", kind="investment_in",
    )
    client.post(
        f"/investments/{app_['id']}/yield",
        json={"amount_cents": 150_00, "date": "2026-02-28", "chart_account_id": None},
        headers=headers,
    )
    _transferencia(
        client, headers, de=aplicacao["id"], para=corrente["id"],
        valor=2_000_00, quando="2026-03-05", kind="investment_out",
    )

    acc = _acc(db, app_["id"])
    saldo = bank_service.derived_balance(db, bank_account_id=aplicacao["id"])
    assert saldo == inv_service.principal_derivado(db, acc) + acc.accrued_yield_cents
    assert saldo == 11_150_00, "10.000 + 3.000 + 150 − 2.000"


# ── Teste 3 da spec §5 ────────────────────────────────────────────────────────────────────────
def test_saldo_de_abertura_desconhecido_da_None_e_NAO_zero(client, db, headers):
    """Conta cadastrada como "tenho a conta e não sei o saldo" (Story 8.21) ⇒ principal `None`.

    **Zero seria uma afirmação** — *"você não tem nada aplicado"* —, falsa e indistinguível de um
    saldo genuinamente zerado. `None` é a ausência da afirmação, e é o princípio que a 8.21 fixou:
    suprimir a afirmação, nunca o número.
    """
    conta = _conta_bancaria(
        client, headers, opening_balance_cents=0, opening_balance_is_known=False
    )
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    principal = inv_service.principal_derivado(db, _acc(db, app_["id"]))
    assert principal is None
    assert principal != 0, "o 0 aqui seria uma afirmação; queremos a ausência dela"


def test_aplicacao_sem_vinculo_da_None(client, db, headers):
    """Sem `bank_account_id` não há de onde derivar. `None`, não zero, pelo mesmo motivo acima."""
    app_ = _aplicacao(client, headers, bank_account_id=None)
    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) is None


def test_principal_negativo_quando_o_resgate_excede(client, db, headers):
    """Resgate BRUTO (principal + rendimento não lançado) deixa o principal negativo — e aparece.

    Clampar em zero seria esconder; recusar o resgate seria recusar um fato que já aconteceu no
    banco. O número aparece como é, e quem o nomeia é a tela (spec §4.4).
    """
    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplicacao = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=aplicacao["id"])

    _transferencia(
        client, headers, de=aplicacao["id"], para=corrente["id"],
        valor=10_500_00, quando="2026-03-05", kind="investment_out",
    )

    assert inv_service.principal_derivado(db, _acc(db, app_["id"])) == -500_00


def test_principais_derivados_resolve_em_lote(client, db, headers):
    """A versão de lote existe para o `GET /investments` não virar N+1 — uma query, N contas."""
    c1 = _conta_bancaria(client, headers, name="CDB A", opening_balance_cents=1_000_00)
    c2 = _conta_bancaria(client, headers, name="CDB B", opening_balance_cents=2_000_00)
    a1 = _aplicacao(client, headers, bank_account_id=c1["id"], name="A")
    a2 = _aplicacao(client, headers, bank_account_id=c2["id"], name="B")
    a3 = _aplicacao(client, headers, bank_account_id=None, name="C")

    accs = [_acc(db, a["id"]) for a in (a1, a2, a3)]
    assert inv_service.principais_derivados(db, accs) == {
        a1["id"]: 1_000_00,
        a2["id"]: 2_000_00,
        a3["id"]: None,
    }
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments_principal.py -v
```

Esperado: **FAIL** com `AttributeError: module 'app.modules.investments.service' has no attribute 'principal_derivado'`.

- [ ] **Step 3: Implementar a derivação**

Em `apps/api/app/modules/investments/service.py`, acrescente após `list_accounts` (`:171`). Os imports novos vão junto dos que já existem no topo:

```python
from collections.abc import Sequence

from app.core.money_planes import ORIGEM_INDISPONIVEL
```

```python
def principais_derivados(
    db: Session, accs: Sequence[InvestmentAccount]
) -> dict[str, int | None]:
    """O principal CALCULADO de cada aplicação — `{investment_account_id: centavos | None}`.

        principal = opening_balance_cents da conta de aplicação
                  + Σ movimentos daquela conta com `source <> 'yield'`

    Os três termos, e por que cada um está aqui (spec §3):

    **(a) O saldo de abertura entra.** É o dinheiro que já estava aplicado no dia do cadastro —
    principal que nunca teve movimento. Somar só os movimentos daria R$ 0,00 numa conta com
    R$ 10.000 aplicados: um número errado com aparência de fato.

    **(b) `source <> 'yield'` impede a dupla contagem.** O rendimento já é contado por
    `accrued_yield_cents` e, desde a Onda 2b-i, também gera `bank_transaction`. Sem o recorte, cada
    rendimento entraria duas vezes no saldo da aplicação.

    **(c) O piso `posted_at > opening_date` e o teto `<= hoje` não são escolha desta função** —
    vêm de `_movements_sums`, a única soma de movimentos do repositório. Um aporte agendado para o
    mês que vem não é principal aplicado hoje.

    ⚠️ **`None` NÃO é zero, e a distinção é o ponto.** Devolvemos `None` em dois casos — aplicação
    sem vínculo, e conta cujo saldo de abertura o dono declarou **não saber** (Story 8.21,
    `origem_do_saldo_derivado`). Zero seria a afirmação *"você não tem nada aplicado"*, falsa e
    indistinguível de um saldo genuinamente zerado. É o princípio da Onda 0 e da 8.21: suprimir a
    afirmação, nunca o número.

    ⚠️ **A procedência é lida de `bank_service.origem_do_saldo_derivado`, nunca recomparada aqui.**
    A Story 8.21 pagou exatamente esse preço: a mesma decisão escrita duas vezes no `router.py`
    fazia a mesma conta responder coisas diferentes por portas diferentes.

    O principal **pode ser negativo** (resgate bruto que leva rendimento ainda não lançado junto).
    Não é clampado: quem o nomeia é a tela (spec §4.4), e clampar seria esconder.
    """
    vinculadas = {a.id: a.bank_account_id for a in accs if a.bank_account_id}
    if not vinculadas:
        return {a.id: None for a in accs}

    contas = {
        c.id: c
        for c in bank_service.list_accounts(db, include_archived=True)
        if c.id in set(vinculadas.values())
    }
    somas = bank_service.movement_sums(
        db, accounts=list(contas.values()), exclude_sources=frozenset({SOURCE_YIELD})
    )

    resultado: dict[str, int | None] = {}
    for a in accs:
        conta = contas.get(a.bank_account_id) if a.bank_account_id else None
        if conta is None or bank_service.origem_do_saldo_derivado(conta) == ORIGEM_INDISPONIVEL:
            resultado[a.id] = None
            continue
        resultado[a.id] = conta.opening_balance_cents + somas.get(conta.id, 0)
    return resultado


def principal_derivado(db: Session, acc: InvestmentAccount) -> int | None:
    """O principal de UMA aplicação. Delega para `principais_derivados` — ver a fórmula lá.

    Uma implementação, dois usos: duas cópias da fórmula divergiriam no dia em que uma delas
    ganhasse uma condição, e o sintoma seria um principal que muda conforme a tela que o pede —
    exatamente o que `_movements_sum`/`_movements_sums` já evitam um nível abaixo.
    """
    return principais_derivados(db, [acc])[acc.id]
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments_principal.py -v
```

Esperado: **9 passed**.

- [ ] **Step 5: Provar por mutação que o recorte está vivo**

Copie o arquivo antes de mutar — **nunca use `git checkout` para restaurar** (já apagou uma sessão inteira de trabalho não commitado nesta onda do épico):

```bash
cp apps/api/app/modules/investments/service.py /tmp/service.py.bak
```

Troque `exclude_sources=frozenset({SOURCE_YIELD})` por `exclude_sources=frozenset()` e rode:

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments_principal.py -q
```

Esperado: **`test_rendimento_NAO_move_o_principal` e `test_a_invariante_...` FALHAM.** Se passarem, o recorte não está sendo exercitado e o teste é do tipo errado — conserte o teste, não o código.

```bash
cp /tmp/service.py.bak apps/api/app/modules/investments/service.py
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/investments/service.py apps/api/tests/test_investments_principal.py
git commit -m "feat: o principal da aplicação passa a ser calculado dos movimentos [Onda 2b-ii]"
```

---

## Task 3: Os nove leitores da coluna, de uma vez

**Files:**
- Modify: `apps/api/app/modules/investments/service.py:333-337` (`_pct`) e `:360-369` (`rentability`)
- Modify: `apps/api/app/modules/investments/schemas.py:82`, `:91`
- Modify: `apps/api/app/modules/investments/router.py:25-35` (`_out`) e todas as rotas que o chamam
- Test: `apps/api/tests/test_investments_principal.py` (acrescentar)

**Interfaces:**
- Consumes: `principais_derivados`, `principal_derivado` (Task 2)
- Produces:
  - `InvestmentAccountOut.principal_cents: int | None`
  - `RentabilityOut.principal_cents: int | None`
  - `investments.router._out(a: InvestmentAccount, principal_cents: int | None) -> InvestmentAccountOut` — **assinatura nova, dois parâmetros**

**Por que de uma vez.** O inventário da spec §4.2.1 tem nove leitores. Fatiar isto deixaria a API respondendo `None` num campo tipado `int` no meio do caminho — 500 em produção se o deploy pegasse o estado intermediário.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `apps/api/tests/test_investments_principal.py`:

```python
def test_a_api_devolve_o_principal_derivado_e_ignora_a_coluna(client, db, headers):
    """`GET /investments` responde o CALCULADO, não o que está gravado na coluna.

    A coluna é semeada com um valor absurdo de propósito: se a API o devolvesse, o teste falharia
    com um número reconhecível em vez de um zero ambíguo.
    """
    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    acc = _acc(db, app_["id"])
    acc.principal_cents = 777_77  # o valor congelado, que ninguém pode mais ler
    db.commit()

    r = client.get("/investments", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()[0]["principal_cents"] == 10_000_00


def test_rentabilidade_e_None_com_principal_None_e_com_principal_negativo(client, db, headers):
    """`_pct` protege os TRÊS casos sem número: `None`, zero e negativo.

    `None` levantaria `TypeError` (divisão por `None`). **Negativo é o mais perigoso dos três**:
    devolveria um percentual de sinal invertido — plausível na tela, e errado. Rentabilidade sobre
    principal negativo não é um número menor: é uma pergunta sem sentido.
    """
    # (a) principal None — saldo de abertura desconhecido
    c_desconhecida = _conta_bancaria(
        client, headers, name="CDB ?", opening_balance_cents=0, opening_balance_is_known=False
    )
    a_none = _aplicacao(client, headers, bank_account_id=c_desconhecida["id"], name="Sem lastro")
    r = client.get(f"/investments/{a_none['id']}/rentability", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["principal_cents"] is None
    assert r.json()["total_rentability_pct"] is None

    # (b) principal negativo — resgate bruto
    corrente = _conta_bancaria(client, headers, name="Itaú PJ", kind="checking")
    aplic = _conta_bancaria(client, headers, name="CDB neg", opening_balance_cents=10_000_00)
    a_neg = _aplicacao(client, headers, bank_account_id=aplic["id"], name="Resgatada")
    client.post(
        f"/investments/{a_neg['id']}/yield",
        json={"amount_cents": 500_00, "date": "2026-02-28", "chart_account_id": None},
        headers=headers,
    )
    _transferencia(
        client, headers, de=aplic["id"], para=corrente["id"],
        valor=10_500_00, quando="2026-03-05", kind="investment_out",
    )
    r = client.get(f"/investments/{a_neg['id']}/rentability", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["principal_cents"] == -500_00, "o número aparece como é"
    assert r.json()["total_rentability_pct"] is None, "a rentabilidade sobre ele, não"
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments_principal.py -k "api_devolve or rentabilidade_e_None" -v
```

Esperado: **FAIL** — o primeiro devolvendo `77777`, o segundo com `ValidationError` (`principal_cents` não aceita `None`) ou `TypeError`.

- [ ] **Step 3: Os dois schemas de saída**

Em `apps/api/app/modules/investments/schemas.py`, troque as duas linhas:

```python
class InvestmentAccountOut(BaseModel):
    id: str
    name: str
    kind: str
    index_rate_label: str
    # Onda 2b-ii: CALCULADO dos movimentos da conta bancária vinculada, não mais a coluna.
    # `None` = inafirmável (sem vínculo, ou saldo de abertura declarado desconhecido — Story 8.21).
    # **`None` não é zero:** zero seria a afirmação "você não tem nada aplicado".
    principal_cents: int | None
    accrued_yield_cents: int
    opened_at: date
    bank_account_id: str | None
    created_at: datetime
```

```python
class RentabilityOut(BaseModel):
    account_id: str
    principal_cents: int | None  # Onda 2b-ii — ver InvestmentAccountOut
    accrued_yield_cents: int
    # Rentabilidade TOTAL (rendimento acumulado / principal). `None` quando o principal é `None`,
    # zero ou NEGATIVO — ver `service._pct`.
    total_rentability_pct: float | None
    # Rentabilidade do PERÍODO. Mesmas três condições de `None`.
    period_rentability_pct: float | None
    period_yield_cents: int
    start: date | None
    end: date | None
```

- [ ] **Step 4: `_pct` e `rentability`**

Em `apps/api/app/modules/investments/service.py`, substitua `_pct` (`:333-337`):

```python
def _pct(numerator: int, principal_cents: int | None) -> float | None:
    """Rentabilidade (fração), ou `None` quando a pergunta não tem sentido.

    Três casos sem número, e o terceiro é o que a Onda 2b-ii acrescentou:

    - **`None`** — o principal é inafirmável (sem vínculo, ou saldo de abertura desconhecido).
      Dividir levantaria `TypeError`.
    - **zero** — divisão por zero, protegida desde a 5.6.
    - **negativo** — resgate bruto que levou rendimento ainda não lançado junto. Dividir devolveria
      um percentual de **sinal invertido**: plausível na tela, e errado. *"Quanto rendeu
      percentualmente o que você não aplicou?"* não é uma pergunta com resposta menor — é uma
      pergunta sem resposta.

    O `None` já é renderizado como "—" pela tela desde a 5.6 (`investimentos.ts::formatPct`): a
    superfície existe e não precisa ser inventada.
    """
    if principal_cents is None or principal_cents <= 0:
        return None
    return numerator / principal_cents
```

E, em `rentability` (`:360-369`), troque as três linhas que leem a coluna:

```python
    principal = principal_derivado(db, acc)

    return {
        "account_id": acc.id,
        "principal_cents": principal,
        "accrued_yield_cents": acc.accrued_yield_cents,
        "total_rentability_pct": _pct(acc.accrued_yield_cents, principal),
        "period_rentability_pct": _pct(period_yield, principal),
        "period_yield_cents": period_yield,
        "start": start,
        "end": end,
    }
```

- [ ] **Step 5: O router**

Em `apps/api/app/modules/investments/router.py`, troque `_out` (`:25-35`):

```python
def _out(a: InvestmentAccount, principal_cents: int | None) -> InvestmentAccountOut:
    """O principal vem de FORA (Onda 2b-ii) — `a.principal_cents` está congelado.

    O parâmetro é obrigatório de propósito: um default lendo a coluna seria exatamente o caminho
    por onde o valor digitado voltaria a vencer, e nada quebraria para avisar.
    """
    return InvestmentAccountOut(
        id=a.id,
        name=a.name,
        kind=a.kind,
        index_rate_label=a.index_rate_label,
        principal_cents=principal_cents,
        accrued_yield_cents=a.accrued_yield_cents,
        opened_at=a.opened_at,
        bank_account_id=a.bank_account_id,
        created_at=a.created_at,
    )
```

E ajuste **todos** os chamadores. Na listagem, use a versão de **lote** (uma query, não N):

```python
@router.get("", response_model=list[InvestmentAccountOut])
def list_accounts(
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[InvestmentAccountOut]:
    contas = service.list_accounts(db)
    # Lote de propósito: uma query para N aplicações. `principal_derivado` num laço seria N+1,
    # que é o que `_movements_sums` existe para evitar um nível abaixo.
    principais = service.principais_derivados(db, contas)
    return [_out(a, principais[a.id]) for a in contas]
```

Nas rotas de uma conta só (`create_account`, `update_account`, `register_yield` e qualquer outra que retorne `InvestmentAccountOut`), use:

```python
    return _out(acc, service.principal_derivado(db, acc))
```

Encontre todas com:

```bash
cd apps/api && grep -n "_out(" app/modules/investments/router.py
```

**Nenhuma pode continuar chamando `_out` com um argumento só** — o Python vai reclamar, e é essa a intenção do parâmetro obrigatório.

- [ ] **Step 6: Rodar a suíte de investimentos inteira**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py tests/test_investments_principal.py -v
```

Esperado: **PASS**. Testes antigos de `test_investments.py` que assertavam o principal digitado **vão falhar — e devem**: o comportamento mudou. Ajuste-os para o valor derivado e **escreva na docstring por que a asserção mudou de propósito**. Ajustar asserção sem justificar é a manobra que esconde regressão; aqui a mudança é real e precisa estar dita.

- [ ] **Step 7: Suíte inteira + lint**

```bash
cd apps/api && .venv/Scripts/python -m pytest -q
cd apps/api && .venv/Scripts/python -m ruff check .
```

Esperado: tudo verde, `All checks passed!`.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/investments/ apps/api/tests/
git commit -m "feat: a API responde o principal calculado e a coluna deixa de ser lida [Onda 2b-ii]"
```

---

## Task 4: A recusa — o principal não se edita mais

**Files:**
- Modify: `apps/api/app/modules/investments/service.py` (`create_account` `:124-143`, `update_account` `:146-167`)
- Test: `apps/api/tests/test_investments.py`

**Interfaces:**
- Consumes: nada de tasks anteriores
- Produces: `investments.service.PrincipalNaoEditavelError(InvestmentError)` — 409, `detail` **não** estruturado (ver abaixo)

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `apps/api/tests/test_investments.py`:

```python
def test_editar_o_principal_e_recusado_com_409(client, headers):
    """`PATCH` com `principal_cents` → 409 apontando para a ação REAL (Onda 2b-ii).

    ⚠️ **Este 409 é o OPOSTO do 409 da 2b-i.** Aquele era caminho normal — o dono batia nele ao
    registrar rendimento, e por isso a tela oferecia a saída ali mesmo. Este é **inalcançável pela
    tela** (o campo saiu do formulário): se disparar, é integração antiga ou defeito. É guarda de
    contrato, não fluxo — e por isso **não** tem `detail["acao"]`: um `acao` sem modal do outro
    lado seria contrato com ninguém.

    A asserção é sobre um trecho ESPECÍFICO da frase, não sobre uma palavra genérica. "aporte"
    sozinho casaria com quase qualquer texto sobre aplicação; a manobra que a Onda 2 pegou foi
    `"trilho" in detail` casando também *"fora do trilho"*.
    """
    conta = _conta_bancaria(client, headers)
    r = client.post(
        "/investments",
        json={"name": "Reserva", "opened_at": "2026-01-01", "bank_account_id": conta["id"]},
        headers=headers,
    )
    account_id = r.json()["id"]

    r = client.patch(
        f"/investments/{account_id}", json={"principal_cents": 5_000_00}, headers=headers
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, str), "guarda de contrato não é 409 acionável — sem detail['acao']"
    assert "calculado pelos movimentos" in detail
    assert "registre a transferência" in detail


def test_criar_com_principal_diferente_de_zero_e_recusado(client, headers):
    """No CADASTRO o caminho do valor já aplicado é o **saldo de abertura** da conta bancária.

    Recusar sem dizer onde informar seria o beco sem saída que a 2b-i pagou para evitar.
    """
    conta = _conta_bancaria(client, headers)
    r = client.post(
        "/investments",
        json={
            "name": "Reserva",
            "opened_at": "2026-01-01",
            "bank_account_id": conta["id"],
            "principal_cents": 10_000_00,
        },
        headers=headers,
    )
    assert r.status_code == 409, r.text
    assert "saldo de abertura" in r.json()["detail"]


def test_criar_com_principal_zero_continua_passando(client, headers):
    """O default do schema é `0`. Recusá-lo quebraria todo cliente que não manda o campo.

    Sem este teste, a guarda mais óbvia (`if data.principal_cents is not None`) passaria verde e
    quebraria o cadastro inteiro em produção — o campo tem default, então ele NUNCA é `None`.
    """
    conta = _conta_bancaria(client, headers)
    r = client.post(
        "/investments",
        json={"name": "Reserva", "opened_at": "2026-01-01", "bank_account_id": conta["id"]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py -k "principal" -v
```

Esperado: os dois primeiros **FAIL** (200/201 em vez de 409); o terceiro já passa (é o controle).

- [ ] **Step 3: Implementar a recusa**

Em `apps/api/app/modules/investments/service.py`, logo após `ContaNaoVinculadaError`:

```python
_PRINCIPAL_DERIVADO_MSG = (
    "O valor aplicado agora é calculado pelos movimentos da conta. Para mudar quanto está "
    "aplicado, registre a transferência que você fez de verdade — da conta corrente para a "
    "aplicação (aporte) ou da aplicação para a corrente (resgate)."
)

_PRINCIPAL_NO_CADASTRO_MSG = (
    "No cadastro, o valor já aplicado é o saldo de abertura da conta bancária da aplicação — é "
    "lá que ele é informado, uma vez."
)


class PrincipalNaoEditavelError(InvestmentError):
    """O principal é derivado (Onda 2b-ii) e não se edita.

    ⚠️ **`detail` fica em texto, sem `{"acao": ...}` — e a ausência é a decisão.** O 409 acionável
    da 8.12/2b-i existe porque a tela reconhece a situação e oferece a saída ali mesmo. Este 409 é
    **inalcançável pela tela** (o campo saiu do formulário na E6): quem o recebe é uma integração
    antiga ou um defeito. Um `acao` sem modal do outro lado seria um contrato com ninguém, e
    convidaria a próxima pessoa a construir o modal que não deve existir.

    A ação que a mensagem manda fazer **existe hoje**: `investment_in`/`investment_out` são
    `TRANSFER_KINDS` desde a Onda 2, e a tela de transferência está em `ContasSaldosPage`. Recusar
    apontando para uma ação inexistente é o defeito que esta classe existe para não cometer.
    """

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem, 409)
```

Em `create_account`, como **primeira** linha do corpo:

```python
    # Onda 2b-ii. `principal_cents` tem default `0` no schema, então a guarda é sobre o VALOR e não
    # sobre a presença: `is not None` recusaria todo cadastro que simplesmente não manda o campo.
    if data.principal_cents:
        raise PrincipalNaoEditavelError(_PRINCIPAL_NO_CADASTRO_MSG)
```

e **remova** a linha `principal_cents=data.principal_cents,` da construção do `InvestmentAccount` — a coluna nasce no default `0` do model e nunca mais é escrita.

Em `update_account`, substitua o bloco `if data.principal_cents is not None:` (`:158-159`) por:

```python
    if data.principal_cents is not None:
        # Aqui `is not None` É a guarda certa: no `Update` o default é `None` e significa
        # "não altera" — o oposto exato do `Create`. A assimetria é deliberada e testada.
        raise PrincipalNaoEditavelError(_PRINCIPAL_DERIVADO_MSG)
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py tests/test_investments_principal.py -v
```

Esperado: **PASS**. Testes antigos que criavam aplicação com `principal_cents` preenchido vão falhar — troque-os por conta bancária com `opening_balance_cents`, que é o caminho novo.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/investments/service.py apps/api/tests/test_investments.py
git commit -m "feat: o principal deixa de ser editável e a recusa nomeia a ação real [Onda 2b-ii]"
```

---

## Task 5: O gate que congela a coluna

**Files:**
- Test: `apps/api/tests/test_investments_principal_gate.py` (criar)

**Interfaces:**
- Consumes: o estado final das Tasks 2, 3 e 4 (nenhum leitor da coluna em `app/modules/`)
- Produces: nada consumido por tasks posteriores

**Por que depois das outras.** Rodado antes, ele reprova o próprio código em construção.

- [ ] **Step 1: Escrever o gate e o controle positivo**

Crie `apps/api/tests/test_investments_principal_gate.py`:

```python
"""**Teste de ausência** — `investment_accounts.principal_cents` está congelada (Onda 2b-ii).

Quem ler a coluna vai receber `0` (ou o que sobrou de antes da onda), não o principal real. Nada
quebra se alguém voltar a lê-la: a coluna existe, tem valor, a leitura funciona. Só o dono, meses
depois, veria a tela discordar do extrato sobre quanto ele tem aplicado.

Este teste é o consumidor mecânico que essa mudança não tem sozinha.

**Precedente exato:** `tenant_profiles.timezone`, congelada em 2026-08-07 (migration 0073). Ela
tinha TRÊS consumidores que a investigação inicial não achou — Agenda, Cockpit e a validade das
notificações. Corrigir só o caminho óbvio teria quebrado os três em silêncio.

`app/scripts/investment_audit.py` lê a coluna **de propósito**, para comparar com o derivado, e
está fora do alcance desta varredura por construção: ela só visita `app/modules/`.
"""
from __future__ import annotations

import ast
from pathlib import Path

_MODULES = Path(__file__).resolve().parents[1] / "app" / "modules"

# O model DEFINE a coluna — mencioná-la lá não é lê-la.
_PODEM_MENCIONAR = {"investments/models.py"}


def _ofensores(raiz: Path, ignorar: set[str]) -> list[str]:
    achados: list[str] = []
    for arquivo in raiz.rglob("*.py"):
        rel = arquivo.relative_to(raiz).as_posix()
        if rel in ignorar:
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            # `<algo>.principal_cents` — o padrão de TODOS os call sites que existiam antes da
            # onda: `a.principal_cents`, `acc.principal_cents`, `data.principal_cents`.
            if isinstance(no, ast.Attribute) and no.attr == "principal_cents":
                base = no.value
                nome = base.id if isinstance(base, ast.Name) else None
                if nome in {"a", "acc", "account", "conta", "aplicacao", "InvestmentAccount"}:
                    achados.append(f"{rel}:{no.lineno} ({nome}.principal_cents)")
    return achados


def test_ninguem_le_o_principal_da_coluna():
    assert not _ofensores(_MODULES, _PODEM_MENCIONAR), (
        "Estes pontos leem `principal_cents` da COLUNA, que está congelada desde a Onda 2b-ii. "
        "Use `investments.service.principal_derivado(db, acc)` — ou, para várias contas, "
        f"`principais_derivados(db, accs)`: {_ofensores(_MODULES, _PODEM_MENCIONAR)}"
    )


def test_o_gate_reprova_quando_a_leitura_existe(tmp_path):
    """**Controle positivo.** Um gate que nunca reprovou nada não é um gate — é um teste que passa
    e não prova nada, a família dominante da Onda 2 (oito ocorrências independentes).
    """
    (tmp_path / "fake.py").write_text(
        "def f(acc):\n    return acc.principal_cents\n", encoding="utf-8"
    )
    achados = _ofensores(tmp_path, set())
    assert achados == ["fake.py:2 (acc.principal_cents)"]
```

- [ ] **Step 2: Rodar os dois**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments_principal_gate.py -v
```

Esperado: **2 passed**. Se `test_ninguem_le_o_principal_da_coluna` falhar, ele está certo e o código é que não terminou — volte à Task 3 e trate o que ele apontou. **Não acrescente o arquivo a `_PODEM_MENCIONAR` para fazer o teste passar**: a allowlist é para quem lê de propósito, e a lista é a garantia.

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_investments_principal_gate.py
git commit -m "test: gate de ausência congela a coluna principal_cents [Onda 2b-ii]"
```

---

## Task 6: O script que confere e não corrige

**Files:**
- Create: `apps/api/app/scripts/investment_audit.py`
- Test: `apps/api/tests/test_investments_principal.py` (acrescentar)

**Interfaces:**
- Consumes: `principais_derivados` (Task 2)
- Produces: `app.scripts.investment_audit.auditar(db) -> list[dict]` — por aplicação: `{"id", "name", "coluna_cents", "derivado_cents", "diverge"}`. `derivado_cents` é `int | None`.

- [ ] **Step 1: Escrever o teste que falha**

Acrescente a `apps/api/tests/test_investments_principal.py`:

```python
def test_a_auditoria_reporta_a_divergencia_sem_corrigir(client, db, headers):
    """O script REPORTA. Se ele corrigisse, o `UPDATE` que esta onda existe para não fazer
    voltaria pela porta dos fundos — e alguém o rodaria no deploy sem ler a saída.
    """
    from app.scripts import investment_audit

    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    acc = _acc(db, app_["id"])
    acc.principal_cents = 777_77
    db.commit()

    linhas = investment_audit.auditar(db)

    assert linhas == [
        {
            "id": app_["id"],
            "name": "Reserva",
            "coluna_cents": 777_77,
            "derivado_cents": 10_000_00,
            "diverge": True,
        }
    ]
    db.refresh(acc)
    assert acc.principal_cents == 777_77, "a auditoria NÃO corrige — a coluna segue como estava"


def test_a_auditoria_nao_marca_divergencia_quando_batem(client, db, headers):
    """Controle negativo: sem ele, `diverge: True` fixo passaria no teste acima."""
    from app.scripts import investment_audit

    conta = _conta_bancaria(client, headers, opening_balance_cents=10_000_00)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])
    acc = _acc(db, app_["id"])
    acc.principal_cents = 10_000_00
    db.commit()

    assert investment_audit.auditar(db)[0]["diverge"] is False
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments_principal.py -k auditoria -v
```

Esperado: **FAIL** com `ModuleNotFoundError: No module named 'app.scripts.investment_audit'`.

- [ ] **Step 3: Escrever o script**

Crie `apps/api/app/scripts/investment_audit.py`:

```python
"""Confere o principal das aplicações: o que a coluna congelada diz × o que os movimentos dizem.

    docker compose exec api python -m app.scripts.investment_audit

**Não existe `--fix`, e a ausência é a decisão.** A Onda 2b-ii substituiu o backfill do design-mãe
§6.2 — o único `UPDATE` sobre dado existente do épico, exposto à armadilha do `FORCE ROW LEVEL
SECURITY` — por *auditoria + ato do dono*. Uma flag de correção reintroduziria exatamente o que a
onda existe para não fazer, e alguém a rodaria no deploy sem ler a saída.

O que fazer com uma divergência: **o dono corrige por ato na tela** — declarando o saldo de abertura
da conta de aplicação, ou registrando o aporte que faltou como transferência. É o mesmo mecanismo
pelo qual a Onda 2b-i vinculou a aplicação legada, já validado em campo.

⚠️ **Isolamento:** itera a tabela GLOBAL `tenants` e abre `tenant_session` por tenant (RLS fixada),
mesmo padrão de `merge_duplicate_clients` e `migrate_attachments_to_s3`. Uma consulta em tabela com
RLS **sem** tenant devolve zero linhas **sem erro** — foi assim que a sondagem de `phone_key` em
produção quase virou um "está tudo limpo" falso. Por isso a saída imprime **quantos tenants foram
varridos**: `0 aplicações em 0 tenants` e `0 aplicações em 7 tenants` são resultados diferentes, e o
primeiro é um bug deste script.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db, tenant_session
from app.modules.auth.models import Tenant
from app.modules.investments import service as inv_service

logger = logging.getLogger("e1p.investment_audit")


def auditar(db: Session) -> list[dict]:
    """Uma linha por aplicação do tenant da sessão. **Só lê.**

    `coluna_cents` lê `principal_cents` de propósito — é o único lugar do repositório autorizado a
    fazê-lo, e é por isso que este arquivo vive em `app/scripts/` e não em `app/modules/`: o gate
    `test_investments_principal_gate.py` varre só os módulos.
    """
    contas = inv_service.list_accounts(db)
    derivados = inv_service.principais_derivados(db, contas)
    linhas = []
    for a in contas:
        derivado = derivados[a.id]
        linhas.append(
            {
                "id": a.id,
                "name": a.name,
                "coluna_cents": a.principal_cents,
                "derivado_cents": derivado,
                # `None` (inafirmável) NÃO é divergência: é ausência de comparação. Tratá-lo como
                # divergente mandaria o dono caçar um erro que não existe — o modo de falha que o
                # épico chama de "pior do que ficar calado".
                "diverge": derivado is not None and derivado != a.principal_cents,
            }
        )
    return linhas


def _tenant_ids() -> list[str]:
    gen = get_db()
    db = next(gen)
    try:
        return [t.id for t in db.scalars(select(Tenant)).all()]
    finally:
        gen.close()


def _reais(cents: int | None) -> str:
    return "não sei" if cents is None else f"R$ {cents / 100:,.2f}".replace(",", "@").replace(
        ".", ","
    ).replace("@", ".")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("=== Auditoria do principal das aplicações (Onda 2b-ii) — SÓ LEITURA ===")

    tenants = _tenant_ids()
    total = divergentes = 0
    for tenant_id in tenants:
        with tenant_session(tenant_id) as db:
            for linha in auditar(db):
                total += 1
                if not linha["diverge"]:
                    continue
                divergentes += 1
                logger.info("")
                logger.info("  %s (tenant %s)", linha["name"], tenant_id)
                logger.info("    principal na coluna : %s", _reais(linha["coluna_cents"]))
                logger.info("    principal calculado : %s", _reais(linha["derivado_cents"]))
                logger.info(
                    "    -> declare o saldo de abertura da conta de aplicação, ou registre o "
                    "aporte que faltou como transferência"
                )

    logger.info("")
    logger.info(
        "%d aplicação(ões) em %d tenant(s); %d com divergência.", total, len(tenants), divergentes
    )
    if not tenants:
        logger.warning(
            "NENHUM tenant varrido — isto é um defeito deste script, não um banco limpo."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Rodar e ver passar**

```bash
cd apps/api && .venv/Scripts/python -m pytest tests/test_investments_principal.py -k auditoria -v
```

Esperado: **2 passed**.

- [ ] **Step 5: Rodar o script de verdade contra o dev**

```bash
cd apps/api && .venv/Scripts/python -m app.scripts.investment_audit
```

Esperado: uma linha de resumo com a contagem de tenants. **Se sair `0 aplicação(ões) em 0 tenant(s)` mais o WARNING, o script não está enxergando o banco** — não é aprovação, é o defeito que ele mesmo denuncia.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/scripts/investment_audit.py apps/api/tests/test_investments_principal.py
git commit -m "feat: auditoria do principal reporta divergência e não corrige [Onda 2b-ii]"
```

---

## Task 7: Os tipos e o aviso, no frontend

**Files:**
- Modify: `apps/web/src/features/financeiro/investimentos.ts:25`, `:40`
- Test: `apps/web/src/features/financeiro/investimentos.test.ts`

**Interfaces:**
- Consumes: o contrato da API (Task 3) — `principal_cents: number | null`
- Produces:
  - `InvestmentAccount.principal_cents: number | null`, `Rentability.principal_cents: number | null`
  - `formatPrincipal(cents: number | null): string`
  - `avisoDeResgateExcedente(cents: number | null): string | null`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente a `apps/web/src/features/financeiro/investimentos.test.ts`:

```ts
import { avisoDeResgateExcedente, formatPrincipal } from "./investimentos";

describe("formatPrincipal", () => {
  it("formata o valor quando ele é afirmável", () => {
    expect(formatPrincipal(1_000_000)).toBe("R$ 10.000,00");
  });

  it("negativo é mostrado como é — clampar em zero seria esconder", () => {
    expect(formatPrincipal(-50_000)).toBe("-R$ 500,00");
  });

  it("null vira a frase de não-saber, nunca R$ 0,00", () => {
    // Zero seria a afirmação "você não tem nada aplicado" — falsa, e indistinguível de um saldo
    // genuinamente zerado. É o princípio da Story 8.21.
    expect(formatPrincipal(null)).toBe("Não informado");
    expect(formatPrincipal(null)).not.toBe("R$ 0,00");
  });
});

describe("avisoDeResgateExcedente", () => {
  it("nomeia a diferença e a ação quando o principal é negativo", () => {
    const aviso = avisoDeResgateExcedente(-50_000);
    expect(aviso).toContain("R$ 500,00");
    expect(aviso).toContain("registre o rendimento do período");
    // "não adivinha" é literal e é regra do épico (Artigo IV): o sistema sabe que falta, e não
    // lança sozinho. Se esta asserção cair, alguém tirou a única frase que impede a próxima
    // pessoa de "resolver" o problema inferindo o valor.
    expect(aviso).toContain("não adivinha");
  });

  it("cala quando o principal é positivo, zero ou desconhecido", () => {
    expect(avisoDeResgateExcedente(1_000_000)).toBeNull();
    expect(avisoDeResgateExcedente(0)).toBeNull();
    expect(avisoDeResgateExcedente(null)).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
pnpm --filter @e1p/web test -- --run investimentos
```

Esperado: **FAIL** — `formatPrincipal` e `avisoDeResgateExcedente` não existem.

- [ ] **Step 3: Implementar**

Em `apps/web/src/features/financeiro/investimentos.ts`, troque os dois campos de tipo:

```ts
export interface InvestmentAccount {
  id: string;
  name: string;
  kind: string;
  index_rate_label: string;
  /**
   * Onda 2b-ii — CALCULADO dos movimentos da conta bancária vinculada, não mais digitado.
   * `null` = inafirmável (sem vínculo, ou saldo de abertura declarado desconhecido — Story 8.21).
   * **`null` não é zero:** zero seria a afirmação "você não tem nada aplicado".
   * Pode ser NEGATIVO: resgate bruto que levou rendimento ainda não lançado junto.
   */
  principal_cents: number | null;
  accrued_yield_cents: number;
  opened_at: string;
  created_at: string;
  bank_account_id: string | null;
}
```

E o mesmo em `Rentability`:

```ts
  principal_cents: number | null;  // Onda 2b-ii — ver InvestmentAccount
```

Acrescente os dois helpers ao final do arquivo:

```ts
/** O texto de não-saber do principal. Uma frase, um lugar — a tela nunca a escreve à mão. */
export const PRINCIPAL_DESCONHECIDO = "Não informado";

/**
 * Formata o principal. `null` vira a frase de não-saber, **nunca "R$ 0,00"**.
 *
 * Zero seria uma afirmação ("você não tem nada aplicado"), falsa e indistinguível de um saldo
 * genuinamente zerado — o mesmo princípio pelo qual a Projeção de Caixa cala o runway em vez de
 * mostrar um número sem lastro (Story 8.21).
 */
export function formatPrincipal(cents: number | null): string {
  if (cents === null || cents === undefined) return PRINCIPAL_DESCONHECIDO;
  return formatBRL(cents);
}

/**
 * O aviso do resgate que levou rendimento junto — `null` quando não há o que dizer.
 *
 * O banco credita o resgate BRUTO (principal + rendimento). Registrado como transferência contra um
 * principal menor, o derivado fica negativo. O e1p **sabe** quanto falta e **não** lança sozinho: o
 * valor certo do rendimento é fato do banco, não dedução nossa (Artigo IV — No Invention).
 */
export function avisoDeResgateExcedente(principalCents: number | null): string | null {
  if (principalCents === null || principalCents === undefined || principalCents >= 0) return null;
  return (
    `Você resgatou ${formatBRL(-principalCents)} a mais do que aportou. Se essa diferença é ` +
    "rendimento que ainda não foi lançado, registre o rendimento do período — o e1p não adivinha " +
    "o valor."
  );
}
```

- [ ] **Step 4: Rodar e ver passar**

```bash
pnpm --filter @e1p/web test -- --run investimentos
pnpm --filter @e1p/web exec tsc --noEmit
```

Esperado: testes **PASS**. O `tsc` vai **falhar** em `InvestimentosPage.tsx:130` (`formatBRL` não aceita `null`) — é esperado e é a Task 8. Anote o erro e siga.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/financeiro/investimentos.ts apps/web/src/features/financeiro/investimentos.test.ts
git commit -m "feat: os tipos do principal aceitam não-saber e negativo [Onda 2b-ii]"
```

---

## Task 8: A tela — principal sem campo, o aviso e o extrato

**Files:**
- Modify: `apps/web/src/features/financeiro/InvestimentosPage.tsx` (`:130` o `Stat`, `:230-265` o formulário)
- Test: `apps/web/src/features/financeiro/investimentos.test.ts`

**Interfaces:**
- Consumes: `formatPrincipal`, `avisoDeResgateExcedente`, `PRINCIPAL_DESCONHECIDO` (Task 7)
- Produces: nada consumido por tasks posteriores

- [ ] **Step 1: O `Stat` do principal e o aviso**

Em `InvestimentosPage.tsx`, troque a linha `:130`:

```tsx
                <Stat
                  label="Principal aplicado"
                  value={formatPrincipal(a.principal_cents)}
                  tone={
                    a.principal_cents !== null && a.principal_cents < 0
                      ? "text-amber-700"
                      : undefined
                  }
                />
```

E, **logo abaixo do bloco de `Stat`s** (fora do `grid`, ocupando a largura inteira), o aviso:

```tsx
              {avisoDeResgateExcedente(a.principal_cents) && (
                <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  {avisoDeResgateExcedente(a.principal_cents)}
                </p>
              )}
```

⚠️ **O aviso fica colado no número, não numa seção "avisos" no fim da tela.** Em ~360px um aviso distante do valor que ele explica é um aviso que ninguém lê — a lição dos PRs #56 e #58, onde o checkbox e a ação que o tornava efetivo viviam em blocos separados e uma conta real foi paga sem o dono ver.

Importe os helpers no topo do arquivo, junto do `formatPct` que já vem de lá:

```tsx
import { avisoDeResgateExcedente, formatPrincipal } from "./investimentos";
```

- [ ] **Step 2: Tirar o campo do formulário**

No modal de criação (`:230-265`), remova o estado `principal`, o `<input>` correspondente e a linha `principal_cents:` do `api.post`. No lugar do campo, uma frase que **diz onde o valor mora agora**:

```tsx
              <p className="text-xs text-neutral-500">
                O valor já aplicado vem do <strong>saldo de abertura</strong> da conta bancária da
                aplicação — informe-o ao cadastrar a conta. Depois disso, aporte e resgate são
                transferências entre as suas contas.
              </p>
```

**Sem esta frase o campo apenas some**, e quem cadastra a aplicação não descobre onde informar o que tem aplicado. Recusar sem dizer onde é o beco que a 2b-i pagou para evitar.

- [ ] **Step 3: O extrato da aplicação**

Abaixo dos `Stat`s de cada aplicação vinculada, um bloco recolhível com os movimentos da conta:

```tsx
{a.bank_account_id && <ExtratoDaAplicacao bankAccountId={a.bank_account_id} />}
```

E o componente, no mesmo arquivo:

```tsx
/**
 * Extrato da aplicação — aportes, resgates e rendimentos.
 *
 * ⚠️ **Segunda superfície sobre o mesmo razão, de propósito** (decisão do fundador, 2026-08-08): a
 * primeira é "Ver movimentos" em `ContasSaldosPage`, porque a conta de aplicação é uma
 * `bank_account` como qualquer outra. A garantia contra as duas discordarem é **mecânica**: as
 * duas chamam o MESMO endpoint, sem consulta própria e sem filtro reescrito. O que difere entre
 * elas é apresentação. Se alguém der a esta um filtro próprio, `investimentos.test.ts` protesta.
 */
function ExtratoDaAplicacao({ bankAccountId }: { bankAccountId: string }) {
  const [aberto, setAberto] = useState(false);
  const [movimentos, setMovimentos] = useState<BankTransaction[] | null>(null);
  const fuso = useFuso();

  useEffect(() => {
    if (!aberto) return;
    let vivo = true;
    api
      .get<BankTransaction[]>("/bank/transactions", { params: { bank_account_id: bankAccountId } })
      .then((r) => {
        if (vivo) setMovimentos(Array.isArray(r.data) ? r.data : []);
      })
      .catch(() => {
        if (vivo) setMovimentos([]);
      });
    return () => {
      vivo = false;
    };
  }, [aberto, bankAccountId]);

  return (
    <div className="mt-4 border-t border-neutral-100 pt-3">
      <button
        onClick={() => setAberto((v) => !v)}
        className="text-sm font-medium text-primary-700 hover:underline"
      >
        {aberto ? "Ocultar extrato" : "Ver extrato da aplicação"}
      </button>
      {aberto && (
        <div className="mt-3 overflow-x-auto">
          {movimentos === null ? (
            <p className="text-sm text-neutral-500">Carregando…</p>
          ) : movimentos.length === 0 ? (
            <p className="text-sm text-neutral-500">Nenhum movimento nesta aplicação ainda.</p>
          ) : (
            <table className="w-full min-w-[20rem] text-sm">
              <tbody>
                {movimentos.map((m) => (
                  <tr key={m.id} className="border-b border-neutral-50">
                    <td className="py-2 pr-3 whitespace-nowrap text-neutral-500">
                      {formatDay(m.posted_at, fuso)}
                    </td>
                    <td className="py-2 pr-3">{m.user_description || m.raw_description}</td>
                    <td
                      className={
                        "py-2 text-right whitespace-nowrap " +
                        (m.amount_cents < 0 ? "text-neutral-700" : "text-accent-700")
                      }
                    >
                      {formatBRL(m.amount_cents)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
```

Importe `BankTransaction` de `./contas`, `formatDay` de `@/lib/datetime` e `useFuso` de `@/store/auth` — confira os caminhos exatos como `ContasSaldosPage.tsx` os importa e **use os mesmos**.

⚠️ **`overflow-x-auto` na tabela, nunca `overflow-hidden`.** Em tela estreita o `hidden` **corta** a coluna de valor sem deixar rastro — foi o defeito exato do PR #58 na `PagarPage`, onde os botões de ação (inclusive **Estornar**) ficaram invisíveis, sem jeito de conferir ou desfazer.

⚠️ **`Array.isArray`, não `?? []`.** Com `data = []`, `data.entries` é uma **função** (`Array.prototype.entries`) e um setter do React que recebe função a **executa** — foi assim que o `ClientTimeline` derrubou a página inteira de Conversas.

- [ ] **Step 4: O teste que amarra o endpoint único**

Acrescente a `investimentos.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";

describe("o extrato da aplicação não é uma segunda fonte", () => {
  it("bate no mesmo endpoint que Contas & Saldos, sem consulta própria", () => {
    const dir = join(__dirname);
    const investimentos = readFileSync(join(dir, "InvestimentosPage.tsx"), "utf-8");
    const contas = readFileSync(join(dir, "ContasSaldosPage.tsx"), "utf-8");

    // A duplicação de superfície foi aceita (decisão do fundador). A de CONSULTA, não: duas telas
    // com filtros próprios sobre o mesmo razão divergem, e a que diverge é a que ninguém olha.
    expect(investimentos).toContain('"/bank/transactions"');
    expect(contas).toContain('"/bank/transactions"');
  });
});
```

- [ ] **Step 5: Rodar tudo**

```bash
pnpm --filter @e1p/web test -- --run
pnpm --filter @e1p/web exec tsc --noEmit
```

Esperado: testes **PASS**, `tsc` com **exit 0** (o erro anotado na Task 7 sumiu).

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/financeiro/
git commit -m "feat: a tela da aplicação mostra o principal calculado e o extrato [Onda 2b-ii]"
```

---

## Task 9: O aceite em ~360px e a memória do projeto

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: tudo
- Produces: nada

- [ ] **Step 1: Medir a tela em 360px — de verdade**

Suba a stack (`docker start infra-postgres-1 infra-api-1` + `pnpm --filter @e1p/web dev`) e abra `http://127.0.0.1:5173/financeiro/investimentos` (**`127.0.0.1`, não `localhost`** — a 5173 pode colidir com outro projeto). Com o Playwright MCP, redimensione para **360×740** e verifique, com screenshot:

- [ ] o valor do principal aparece inteiro, sem corte
- [ ] o aviso de resgate excedente aparece **junto** do número, sem rolagem para descobri-lo
- [ ] a tabela do extrato **rola na horizontal** e a coluna de valor é alcançável
- [ ] nada da linha de `Stat`s some atrás da borda

⚠️ **`toContain("flex-wrap")` NÃO é aceite.** Aquela asserção passou com a `FilaPagamentosPage` quebrada em produção por duas sessões: `flex-wrap` não quebra a linha quando o irmão é `min-w-0 flex-1`. **Layout só se prova medindo** — screenshot, não string.

Se algo estiver cortado, corrija e repita. Esta é a quarta vez que este débito aparece no épico e três PRs de campo já foram pagos por ele.

- [ ] **Step 2: Escrever a entrada no `CLAUDE.md`**

Acrescente **após** a seção "Onda 2b-i", escrita a partir do código que subiu e não do que o plano pretendia:

````markdown
### Onda 2b-ii — o principal deixa de ser digitado (e o backfill deixa de existir)

> Spec: `docs/superpowers/specs/2026-08-08-onda-2b-ii-principal-derivado-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-08-onda-2b-ii-principal-derivado.md`

**A onda que era "o item de maior risco do épico inteiro" não tem migration.** Todo documento
anterior descrevia a 2b-ii como a onda do backfill — o único `UPDATE` sobre dado existente do
épico, sob a armadilha do `FORCE RLS` (`UPDATE` filtrado a zero linhas **em silêncio**, que o
SQLite dos testes não pega). Duas coisas o dissolveram: a **2b-i já executou os passos 1-2 do
design-mãe §6.2 por ato do dono** (coluna via DDL puro, vínculo pela tela), e
`investment_accounts` está **vazia em produção**. Os passos 3-4 não tinham sobre o que rodar.

> **A regra que fica (reverberar): quando um backfill existe para reconstruir histórico que um
> ATO DO DONO reconstrói melhor, o backfill é o caminho pior.** Ele escreve sem testemunha, num
> regime onde o fracasso é silencioso. Trocar escrita retroativa por *auditoria + ato* foi a
> manobra da 2b-i; esta é a segunda aplicação, e agora é padrão.

- [x] **`principal = opening_balance_cents + Σ movimentos com `source <> 'yield'`.** O saldo de
  abertura entra, e **isso não estava no design-mãe**: é o dinheiro que já estava aplicado no dia
  do cadastro, principal que nunca teve movimento. Sem ele, uma conta cadastrada com R$ 10.000
  mostraria principal ZERO — número errado com aparência de fato, a família que a Onda 0 existe
  para não repetir. O recorte de `source` impede a dupla contagem: o rendimento já é
  `accrued_yield_cents` e, desde a 2b-i, também é `bank_transaction`.
- [x] **`exclude_sources` entrou em `_movements_sums`, não numa query nova.** A docstring dela já
  dizia por quê: duas cópias da fórmula divergiriam, e o sintoma seria um saldo que muda conforme
  a tela que o pede. `bank.service.movement_sums` é a porta pública fina — existe porque
  `investments` precisava dela e importar um símbolo `_` de outro módulo é acesso que ninguém
  encontra depois.
- [x] **Saldo de abertura desconhecido ⇒ principal `None`, nunca zero.** Reusa
  `origem_do_saldo_derivado` (Story 8.21) em vez de recomparar — foi exatamente essa recomparação
  duplicada que a 8.21 pagou para eliminar. Zero seria a afirmação *"você não tem nada
  aplicado"*, falsa e indistinguível de um saldo genuinamente zerado.
- [x] **A coluna `principal_cents` está CONGELADA** — sem leitor, sem escritor, gate AST com
  controle positivo. Terceiro uso do padrão (`attachments.data`, `tenant_profiles.timezone`).
  **Eram NOVE leitores**, levantados por `grep` antes de a spec fechar e não durante a
  implementação — a lição da 0073, onde três consumidores não apareceram na investigação inicial.
  Drop numa migration posterior.
- [x] **O leitor que quase passou: `_pct` DIVIDE pelo principal.** Com `None` levantaria
  `TypeError`; com **negativo** devolveria um percentual de sinal invertido — plausível na tela, e
  errado. Agora protege os três casos (`None`, zero, negativo). *"Quanto rendeu percentualmente o
  que você não aplicou?"* não é pergunta com resposta menor: é pergunta sem resposta.
- [x] **Editar o principal: 409, e ele é o OPOSTO do 409 da 2b-i.** Aquele era caminho normal e
  por isso a tela oferecia a saída no próprio modal. Este é **inalcançável pela tela** (o campo
  saiu do formulário): se disparar, é integração antiga ou defeito. Por isso **não** tem
  `detail["acao"]` — um `acao` sem modal do outro lado é contrato com ninguém. A guarda do
  `create` é sobre o **valor** (`if data.principal_cents:`) e a do `update` sobre a **presença**
  (`is not None`), porque o default do schema é `0` num e `None` no outro; a assimetria é
  deliberada e testada.
- [x] **REQ-25 cumprido na LEITURA, não na escrita — desvio declarado.** O resgate bruto deixa o
  principal negativo. Recusar o resgate exigiria `bank/transfers.py` consultar `investments`, que
  o gate `test_bank_transfers_nao_importa_investments` proíbe — e recusaria um fato que **já
  aconteceu no banco**, o inverso do princípio da Onda 0. A tela nomeia a diferença e a ação, e
  **não adivinha o valor** (Artigo IV): o sistema sabe que faltam R$ 500 e não os lança sozinho.
- [x] **`app/scripts/investment_audit.py` — sem `--fix`, e a ausência é a decisão.** Com uma flag
  de correção, alguém a rodaria no deploy sem ler a saída e o `UPDATE` voltaria pela porta dos
  fundos. Imprime **quantos tenants varreu**: `0 aplicações em 0 tenants` e `0 em 7` são
  resultados diferentes, e o primeiro é bug do próprio script (a lição da sondagem de `phone_key`,
  onde a RLS devolveu zero linhas sem erro e o silêncio quase virou aprovação).
- [x] **O extrato da aplicação é a SEGUNDA superfície sobre o mesmo razão, de propósito** (decisão
  do fundador). A primeira é "Ver movimentos" em Contas & Saldos. A garantia contra divergência é
  mecânica, não disciplina: as duas chamam o **mesmo endpoint**, com teste amarrando.

- **Dívida:** `packages/shared-types/src/generated.ts` tem `principal_cents` em quatro lugares e
  segue defasado desde o PR #45, sem check de drift no CI. Dívida do épico, não desta onda.
- **Dívida:** REQ-26 (cotização e liquidação em datas diferentes) segue não implementado —
  declarado fora de escopo, não esquecido.
- **Dívida:** o `DROP COLUMN principal_cents` é migration posterior, depois de um ciclo.
````

- [ ] **Step 3: Conferir que nada acima ficou desatualizado**

A seção da Onda 2b-i diz *"a 2b-ii continua com o único backfill do épico, e ele continua sendo o
item de maior risco"*. **Isso deixou de ser verdade.** Troque por:

```markdown
- **Dívida:** ~~a 2b-ii continua com o único backfill do épico~~ — **FECHADA na 2b-ii
  (2026-08-08): o backfill não foi mitigado, deixou de existir.** Ver a seção da Onda 2b-ii.
```

**Dívida resolvida e ainda escrita manda o próximo leitor resolver de novo o que já está
resolvido** (§5, passo 4 deste arquivo).

- [ ] **Step 4: Verificação final**

```bash
cd apps/api && .venv/Scripts/python -m pytest -q          # em PRIMEIRO PLANO
cd apps/api && .venv/Scripts/python -m ruff check .        # All checks passed!
pnpm --filter @e1p/web test -- --run
pnpm --filter @e1p/web exec tsc --noEmit                   # exit 0
cd apps/api && .venv/Scripts/python -m alembic heads       # UM head só, 0075 — sem migration nova
```

⚠️ **`scripts/check.sh` mascara falha de frontend com `|| true` no vitest** — rode as etapas
individualmente, como acima, até isso ser corrigido.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: a Onda 2b-ii entra na memória do projeto [Onda 2b-ii]"
```

---

## Verificação final (antes de abrir o PR)

- [ ] Suíte backend inteira verde, **em primeiro plano**
- [ ] `ruff check` limpo
- [ ] Suíte frontend inteira verde + `tsc --noEmit` exit 0
- [ ] `alembic heads` → **um head só, `0075`** — se apareceu `0076`, alguém escreveu uma migration
      e o §1.1 da spec foi violado
- [ ] `python -m app.scripts.investment_audit` roda e imprime a contagem de tenants
- [ ] Aceite visual em ~360px feito **com screenshot**, não com asserção de classe CSS
- [ ] A entrada no `CLAUDE.md` existe e a dívida da 2b-i foi fechada
- [ ] **PR obrigatório:** `main` é protegida (GH006), 4 checks. Push é do `@devops`.
