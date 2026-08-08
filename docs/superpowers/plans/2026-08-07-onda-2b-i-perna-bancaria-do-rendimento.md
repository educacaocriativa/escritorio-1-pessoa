# Onda 2b-i — a perna bancária do rendimento · Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o rendimento de aplicação gerar o `bank_transaction` correspondente, para que o termo **P3** da pré-condição do gate do Epic 8 vá a zero por construção e a métrica primária do épico possa ser lida.

**Architecture:** Três peças. (1) O contador de P3 passa a verificar de fato se existe perna bancária (`NOT EXISTS`), honrando o próprio nome. (2) `investment_accounts` ganha `bank_account_id` — ligação 1:1 com a `bank_account` `kind='investment'` — e `register_yield` recusa com **409 acionável** sem ela. (3) `register_yield` chama `sync_origin_movement(source='yield')`, o mesmo ponto único de escrita usado por `payables`/`receivables`/`transfers`, na mesma transação.

**Tech Stack:** FastAPI (Python 3.13), SQLAlchemy 2 + Alembic, PostgreSQL 16 (SQLite na suíte unitária), React 18 + Vite + TypeScript, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento-design.md`

---

## Global Constraints

Valem em **toda** task. Não repetidas nas tasks individuais.

- **Idioma:** domínio, comentários e mensagens de erro em **PT-BR**; identificadores em inglês.
- **Dinheiro em centavos**, `BigInteger`. Nunca float.
- **RLS é a ÚNICA garantia de isolamento** — nenhuma query filtra `tenant_id` manualmente (Regra de Ouro nº 1). Conta de outro tenant → **404 fail-closed**, nunca 403 e nunca 409 (409 vazaria existência).
- **`sync_origin_movement` é a ÚNICA função do repositório que escreve `source ∈ SOURCES_SISTEMA`.** Não abra um segundo caminho: se faltar algo, o que se acrescenta é um **parâmetro nela**.
- **Direção de import:** `investments` **pode** importar `bank`. `bank` **NUNCA** importa `investments`/`payables`/`receivables` — dois gates (AST + texto cru) em `tests/test_money_planes.py`. Nenhuma task deste plano toca esses gates.
- **"Hoje" nunca é `datetime.now(UTC).date()`** — é `settings.service.hoje_do_tenant(db)`. Gate AST em `tests/test_fuso_do_tenant.py`.
- **Nenhuma migration deste plano faz `UPDATE`.** `ADD COLUMN`/`CREATE INDEX` são DDL e a RLS não os alcança. Um `UPDATE` de backfill em tabela sob `FORCE ROW LEVEL SECURITY` é filtrado a **zero linhas em silêncio** e o SQLite dos testes **não pega** — seis migrations deste repo já pagaram por isso (`0046`, `0066`, `0067`, `0068`, `0069`, `0073`).
- **Head do alembic:** verificado como `0074` em 2026-08-07. **Reconfira programaticamente antes de mergear** (`alembic heads`), não só ao escrever: branches paralelas já colidiram numeração neste repo.
- **Commits:** Conventional Commits, em PT-BR, referenciando a onda. Ex.: `feat: o rendimento de aplicação gera o movimento bancário [Onda 2b-i]`.
- **Rodar os testes:**
  - Backend: `cd apps/api && .venv/Scripts/python -m pytest <arquivo> -v` (Windows) — **em primeiro plano, nunca em background.**
  - Frontend: `pnpm --filter @e1p/web test -- --run <arquivo>`
  - ⚠️ **NÃO use `scripts/check.sh` como prova** — ele mascara falha de frontend com `|| true`. Rode as etapas individualmente.
- **Última task é a entrada no `CLAUDE.md`** — é AC obrigatório de toda story neste projeto (`CLAUDE.md` §5, passo 4), com o mesmo peso do teste.

---

## File Structure

**Backend — modificados:**

| Arquivo | Responsabilidade nesta onda |
|---|---|
| `apps/api/app/modules/receivables/service.py` | Contador de P3 passa a exigir ausência de perna (`NOT EXISTS`) |
| `apps/api/migrations/versions/0075_investment_bank_account.py` | **Criar** — coluna + índice único parcial. Sem `UPDATE` |
| `apps/api/app/modules/investments/models.py` | Coluna `bank_account_id` |
| `apps/api/app/modules/investments/schemas.py` | `bank_account_id` em Create/Update/Out |
| `apps/api/app/modules/investments/service.py` | Validação do alvo, 409 acionável, chamada a `sync_origin_movement`, 422 de data futura |
| `apps/api/app/modules/investments/router.py` | `detail` estruturado no erro acionável; `bank_account_id` no `_out` |
| `apps/api/app/modules/bank/reconciliation.py` | Frase da nota de P3 deixa de nomear uma onda |

**Frontend — modificados:**

| Arquivo | Responsabilidade |
|---|---|
| `apps/web/src/features/financeiro/investimentos.ts` | Tipo `InvestmentAccount` ganha `bank_account_id`; helper puro de rótulo do vínculo |
| `apps/web/src/features/financeiro/InvestimentosPage.tsx` | Campo de vínculo no formulário da aplicação |

**Testes — modificados/criados:**

| Arquivo | O que cobre |
|---|---|
| `apps/api/tests/test_bank_reconciliation_report.py` | P3 com perna sai da população; a frase nova da nota |
| `apps/api/tests/test_investments.py` | Vínculo, 409, o movimento, o 422 de data futura, IV1 preservada |
| `apps/web/src/features/financeiro/conferencia.test.ts` | Asserção da frase da nota |
| `apps/web/src/features/financeiro/ConferenciaPage.test.tsx` | Idem |
| `apps/web/src/features/financeiro/investimentos.test.ts` | Helper do rótulo do vínculo |

---

### Task 1: O predicado de P3 passa a honrar o próprio nome

**Files:**
- Modify: `apps/api/app/modules/receivables/service.py:52` (import) e `:972-999` (o contador)
- Test: `apps/api/tests/test_bank_reconciliation_report.py`

**Interfaces:**
- Consumes: nada de tasks anteriores (é a primeira).
- Produces: `contar_rendimentos_sem_perna_bancaria(db, *, start: date, end: date) -> tuple[int, int]` — assinatura **inalterada**; só o predicado muda. Continua consumida por `app/main.py::probe_termos_do_gate`.

**Por que esta task vem primeiro.** Ela é a definição executável do resultado que as tasks 2-4 precisam produzir. E o membro que a prova — *um rendimento **com** perna* — é construtível no teste **agora**, chamando `sync_origin_movement` diretamente: `SOURCE_YIELD` já está em `SOURCES_SISTEMA` e a função já aceita. O que não existe ainda é o caminho de **produção** que a chama; isso é a Task 4.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `apps/api/tests/test_bank_reconciliation_report.py`, logo após `test_a1_o_rendimento_de_aplicacao_nao_entra_no_termo_de_conta_informada` (por volta da linha 1436):

```python
def test_rendimento_COM_perna_bancaria_sai_do_termo_P3(
    client: TestClient, headers, db: Session
):
    """**O membro que era inconstruível, e por isso o defeito viveu.**

    `contar_rendimentos_sem_perna_bancaria` contava TODO rendimento da janela — nenhum join,
    nenhum `NOT EXISTS`. Pré-2b isso era inofensivo, porque *"todos os rendimentos"* e *"os
    rendimentos sem perna"* eram o mesmo conjunto. Ligado o movimento (Task 4), os dois se
    separam, e sem este predicado P3 seguiria contando os rendimentos que passaram a ter perna:
    **o gate não abriria nem depois da onda que existe para destravá-lo.**

    O saldo declarado já inclui o rendimento (1.000.000 + 48.000) justamente para que a conta
    continue batendo e a única coisa medida aqui seja o termo P3.

    **Mutante que este teste mata:** remover o `~_tem_perna_bancaria` do `where` — P3 volta a 1.
    Segundo mutante: trocar `SOURCE_YIELD` por outro `source` no `NOT EXISTS` — idem.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_048_000)
    rendimento = _charge_de_rendimento(db, tenant_id, valor=48_000, pago_em=date(2026, 7, 14))

    bank_origin.sync_origin_movement(
        db,
        tenant_id=tenant_id,
        actor="teste",
        source=SOURCE_YIELD,
        origin_id=rendimento.id,
        bank_account_id=conta["id"],
        posted_at=date(2026, 7, 14),
        amount_cents=48_000,
        description="Rendimento CDB",
    )
    db.commit()

    r = _report(db)
    assert r.rendimentos_sem_perna_bancaria == 0, (
        "o rendimento TEM perna bancária — contá-lo em P3 mantém o gate fechado depois da 2b"
    )
    assert r.valor_rendimentos_sem_perna_cents == 0
    assert r.notes == [], "zero termo não-zero ⇒ zero nota"
```

E acrescentar aos imports do topo do arquivo de teste:

```python
from app.modules.bank import origin as bank_origin
from app.modules.bank.models import SOURCE_YIELD
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_reconciliation_report.py::test_rendimento_COM_perna_bancaria_sai_do_termo_P3 -v`

Expected: **FAIL** — `assert 1 == 0`, com a mensagem sobre o gate fechado.

Se falhar por `posted_at` recusado (piso `> opening_date`), confira a constante `OPENING` no topo do arquivo: ela precisa ser anterior a 2026-07-14. Ajuste a data do movimento, **não** o piso.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/receivables/service.py`, linha 52, acrescentar `SOURCE_YIELD` e `BankTransaction` ao import existente:

```python
from app.modules.bank.models import SOURCE_CHARGE, SOURCE_YIELD, BankAccount, BankTransaction
```

E no corpo de `contar_rendimentos_sem_perna_bancaria` (a partir da linha 990), substituir a query:

```python
    de, ate = janela_de_caixa(start, end)
    # O `NOT EXISTS` é o que faz a função HONRAR o próprio nome. Sem ele, ela conta todo
    # rendimento da janela — o que coincidia com "sem perna" só enquanto perna nenhuma existia.
    # Correlaciona por `origin_id`, que para origem de perna única É o id do lançamento
    # (bank/transfers.py:18), e nunca por data: a pergunta do termo é *"existe perna?"*, não
    # *"a perna caiu nesta janela?"*.
    _tem_perna_bancaria = (
        select(BankTransaction.id)
        .where(
            BankTransaction.source == SOURCE_YIELD,
            BankTransaction.origin_id == Charge.id,
        )
        .exists()
    )
    row = db.execute(
        select(func.count(), func.coalesce(func.sum(Charge.amount_cents), 0)).where(
            ~_not_investment_yield(),
            Charge.paid_at.is_not(None),
            Charge.paid_at >= de,
            Charge.paid_at < ate,
            ~_tem_perna_bancaria,
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)
```

Acrescentar ao final da docstring da função:

```
    **A partir da Onda 2b-i o predicado inclui `NOT EXISTS` sobre `bank_transactions`
    (`source='yield'`, `origin_id = charge.id`).** Antes dela a função contava TODO rendimento da
    janela: coincidia com a intenção só porque perna nenhuma existia. Ligado o movimento, contar
    o rendimento que JÁ tem perna manteria o gate fechado depois da própria onda que o destrava.
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_reconciliation_report.py -v`

Expected: **PASS**, incluindo `test_a1_o_rendimento_de_aplicacao_nao_entra_no_termo_de_conta_informada` (rendimento **sem** perna continua contando) e `test_os_dois_termos_geram_duas_notas_com_ondas_diferentes`.

- [ ] **Step 5: Matar os dois mutantes**

⚠️ **Restaure por CÓPIA DE ARQUIVO, nunca por `git checkout`** — um `checkout` sobre arquivo com trabalho não commitado já apagou uma sessão inteira neste épico.

```bash
cd apps/api
cp app/modules/receivables/service.py /tmp/service.py.bak
```

Mutante M1 — remova a linha `~_tem_perna_bancaria,` do `where`. Rode o teste da Step 2: **deve FALHAR**.
Mutante M2 — troque `BankTransaction.source == SOURCE_YIELD` por `== SOURCE_CHARGE`. Rode: **deve FALHAR**.

```bash
cp /tmp/service.py.bak app/modules/receivables/service.py
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/receivables/service.py apps/api/tests/test_bank_reconciliation_report.py
git commit -m "fix: o contador de P3 passa a verificar se existe perna bancária [Onda 2b-i]"
```

---

### Task 2: A aplicação aponta para a conta bancária dela

**Files:**
- Create: `apps/api/migrations/versions/0075_investment_bank_account.py`
- Modify: `apps/api/app/modules/investments/models.py:54` (fim da classe)
- Modify: `apps/api/app/modules/investments/schemas.py` (Create, Update, Out)
- Modify: `apps/api/app/modules/investments/service.py` (validação + create/update)
- Modify: `apps/api/app/modules/investments/router.py:25-35` (`_out`)
- Test: `apps/api/tests/test_investments.py`

**Interfaces:**
- Consumes: nada da Task 1.
- Produces:
  - `InvestmentAccount.bank_account_id: Mapped[str | None]`
  - `investments.service._validate_bank_account(db: Session, bank_account_id: str) -> None` — levanta `InvestmentError` (404 inexistente/cross-tenant, 422 `kind` errado, 409 arquivada)
  - `InvestmentAccountCreate.bank_account_id: str | None`, `InvestmentAccountUpdate.bank_account_id: str | None`, `InvestmentAccountOut.bank_account_id: str | None`

⚠️ **Desvio declarado da spec §4.1.** A spec dizia *"409 reaproveitando `_CONTA_ARQUIVADA_MSG`"*. Essa constante é **privada de `payables/service.py`** e importá-la de `investments` seria acoplamento gratuito entre dois módulos de negócio — exatamente o que o repo evita duplicando `ACAO_CADASTRAR_CONTA` de propósito. A mensagem é **escrita localmente**, abaixo.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar ao fim de `apps/api/tests/test_investments.py`:

```python
# ── Onda 2b-i — o vínculo 1:1 com a conta bancária da aplicação ──────────────────────────────


def _conta_bancaria(client: TestClient, headers, *, kind: str = "investment") -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "CDB Itaú",
            "kind": kind,
            "number": "",
            "opening_balance_cents": 0,
            "opening_balance_is_known": True,
            "opening_date": "2026-06-01",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _aplicacao(client: TestClient, headers, **extra) -> dict:
    body = {"name": "CDB", "kind": "CDB", "principal_cents": 100_000, "opened_at": "2026-06-01"}
    body.update(extra)
    resp = client.post("/investments", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_vincular_a_aplicacao_a_conta_bancaria_dela(client: TestClient, headers):
    """O caminho feliz do vínculo 1:1, pelo PATCH — é assim que a aplicação legada é vinculada."""
    conta = _conta_bancaria(client, headers)
    app_ = _aplicacao(client, headers)
    assert app_["bank_account_id"] is None

    resp = client.patch(
        f"/investments/{app_['id']}", json={"bank_account_id": conta["id"]}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["bank_account_id"] == conta["id"]


def test_a_conta_vinculada_precisa_ser_do_tipo_aplicacao(client: TestClient, headers):
    """Vincular a aplicação a uma conta CORRENTE creditaria o rendimento no lugar errado — e o
    saldo derivado das duas contas passaria a mentir junto."""
    corrente = _conta_bancaria(client, headers, kind="checking")
    app_ = _aplicacao(client, headers)

    resp = client.patch(
        f"/investments/{app_['id']}", json={"bank_account_id": corrente["id"]}, headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert "aplicação" in resp.json()["detail"]


def test_conta_bancaria_inexistente_da_404_e_nunca_409(client: TestClient, headers):
    """404 fail-closed. **409 confirmaria a existência da linha** — e conta de outro tenant chega
    aqui exatamente assim, escondida pela RLS."""
    app_ = _aplicacao(client, headers)
    resp = client.patch(
        f"/investments/{app_['id']}",
        json={"bank_account_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py -k "vincular or tipo_aplicacao or inexistente" -v`

Expected: **FAIL** — `KeyError: 'bank_account_id'` no primeiro, 200 em vez de 422/404 nos demais.

- [ ] **Step 3: A migration**

Criar `apps/api/migrations/versions/0075_investment_bank_account.py`:

```python
"""A aplicação aponta para a conta bancária dela (Onda 2b-i)

Revision ID: 0075
Revises: 0074
Create Date: 2026-08-07

**Por quê.** `register_yield` cria uma `Charge` sintética paga (Story 5.6) e nada mais: o dinheiro
que entrou na aplicação real não vira `bank_transaction` nenhum. Isso é o termo **P3** da
pré-condição do gate do Epic 8, e enquanto ele for não-vazio numa janela a divergência daquele
ciclo **não pode ser lida**. Esta coluna é o que diz ao `sync_origin_movement` QUAL conta creditar.

**`investment_accounts` NÃO é absorvida por `bank_accounts`** — ela é a faceta de PRODUTO
(rentabilidade, indexador, principal), e a `bank_account` `kind='investment'` é onde o dinheiro
está. São duas coisas, e a ligação é 1:1.

⚠️ **NENHUM `UPDATE`, e é isso que torna esta migration segura.** As seis armadilhas registradas
neste repo (`0046`, `0066`, `0067`, `0068`, `0069`, `0073`) são a mesma: backfill filtrado em
silêncio pela RLS, completando com **sucesso aparente**, invisível para o SQLite da suíte.
`ADD COLUMN` e `CREATE INDEX` são **DDL** — a RLS não os alcança. A aplicação que já existe em
produção é vinculada pelo dono, **por ato**, na tela. O backfill que não existe é o backfill que
não pode falhar em silêncio.

⚠️ **`tenant_id` é a PRIMEIRA coluna do índice único, e a ordem não é estética.** Índice único é
global e **não respeita RLS**: sem o `tenant_id` na frente, o tenant B receberia violação de
unicidade causada por dado do tenant A — bug **e** vazamento de existência. Lição já paga na 8.2.

**A cláusula parcial** (`WHERE bank_account_id IS NOT NULL`) mantém N aplicações não-vinculadas
convivendo. Ela não é o que garante a unicidade dos `NULL` (em índice único `NULL` já é distinto
de `NULL` por padrão) — está aqui por tamanho e por intenção declarada, e a justificativa é esta,
não a que a 8.9 escreveu e que era falsa.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "investment_accounts"
_COLUMN = "bank_account_id"
_INDEX = "uq_investment_accounts_bank_account"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(36), nullable=True))
    op.create_index(
        _INDEX,
        _TABLE,
        ["tenant_id", _COLUMN],
        unique=True,
        postgresql_where=sa.text("bank_account_id IS NOT NULL"),
        sqlite_where=sa.text("bank_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Não-destrutivo para o que existia antes: `principal_cents` e `accrued_yield_cents` nunca
    # foram tocados. O que se perde é o VÍNCULO — e com ele o `register_yield` volta a aceitar
    # rendimento sem perna bancária, reabrindo o termo P3. Escrito aqui para não ser descoberto
    # no meio de um rollback.
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, _COLUMN)
```

- [ ] **Step 4: O model**

Em `apps/api/app/modules/investments/models.py`, ao final da classe `InvestmentAccount` (após `opened_at`):

```python
    # A conta bancária ONDE ESTE DINHEIRO ESTÁ (Onda 2b-i). Ligação 1:1 com uma `bank_account`
    # `kind='investment'`. Referência SOLTA, sem FK dura — mesmo padrão do resto do projeto.
    # `None` = ainda não vinculada; nesse estado `register_yield` recusa com 409 acionável, porque
    # um rendimento sem perna bancária é o termo P3 e ele fecha o gate do Epic 8.
    bank_account_id: Mapped[str | None] = mapped_column(String(36), default=None, nullable=True)
```

- [ ] **Step 5: Os schemas**

Em `apps/api/app/modules/investments/schemas.py`, acrescentar o campo nas três classes:

```python
# em InvestmentAccountCreate, após `opened_at`:
    bank_account_id: str | None = Field(default=None, max_length=36)

# em InvestmentAccountUpdate, após `principal_cents`:
    bank_account_id: str | None = Field(default=None, max_length=36)

# em InvestmentAccountOut, após `opened_at`:
    bank_account_id: str | None
```

- [ ] **Step 6: A validação e a escrita no service**

Em `apps/api/app/modules/investments/service.py`, acrescentar aos imports:

```python
from app.modules.bank import service as bank_service
from app.modules.bank.models import KIND_INVESTMENT
```

Acrescentar a mensagem e o validador, logo após `_validate_financeiro_account`:

```python
_CONTA_NAO_E_APLICACAO_MSG = (
    "A conta bancária de uma aplicação precisa ser do tipo 'aplicação'. Se o dinheiro está numa "
    "conta corrente, ele não está aplicado — e o rendimento cairia na conta errada, fazendo os "
    "dois saldos derivados mentirem juntos."
)

_CONTA_ARQUIVADA_MSG = (
    "A conta bancária escolhida está arquivada e não recebe lançamentos novos. Escolha outra "
    "conta ou cadastre a conta que você usa hoje — com o saldo de abertura do dia."
)


def _validate_bank_account(db: Session, bank_account_id: str) -> None:
    """A conta bancária do vínculo existe (RLS), é aplicação e está ativa? (Onda 2b-i)

    404 se inexistente/de outro tenant — a RLS a esconde e `bank_service.get_account` é
    fail-closed. **Nunca 409 aqui**: 409 confirmaria a existência da linha.
    """
    try:
        acc = bank_service.get_account(db, bank_account_id)
    except bank_service.BankError as e:
        raise InvestmentError("Conta bancária não encontrada", e.status_code) from e
    if acc.kind != KIND_INVESTMENT:
        raise InvestmentError(_CONTA_NAO_E_APLICACAO_MSG, 422)
    if acc.archived_at is not None:
        raise InvestmentError(_CONTA_ARQUIVADA_MSG, 409)
```

Em `create_account`, antes do `InvestmentAccount(...)`:

```python
    if data.bank_account_id:
        _validate_bank_account(db, data.bank_account_id)
```

e acrescentar `bank_account_id=data.bank_account_id,` ao construtor.

Em `update_account`, após o bloco de `principal_cents`:

```python
    if data.bank_account_id is not None:
        _validate_bank_account(db, data.bank_account_id)
        acc.bank_account_id = data.bank_account_id
```

- [ ] **Step 7: O router**

Em `apps/api/app/modules/investments/router.py`, dentro de `_out`, acrescentar:

```python
        bank_account_id=a.bank_account_id,
```

E envolver `create_account` no mesmo `try/except` que `update_account` já tem, porque agora ele pode levantar `InvestmentError`:

```python
@router.post("", response_model=InvestmentAccountOut, status_code=201)
def create_account(
    data: InvestmentAccountCreate,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> InvestmentAccountOut:
    try:
        acc = service.create_account(db, tenant_id=user.tenant_id, actor=user.user_id, data=data)
    except service.InvestmentError as e:
        raise _err(e) from e
    return _out(acc)
```

- [ ] **Step 8: Rodar e confirmar que passa**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py -v`

Expected: **PASS** — os 3 testes novos e todos os antigos, inclusive o IV1 (`register_yield` não cria `Transaction`/`PlatformEarning`).

- [ ] **Step 9: Confirmar que a migration aplica**

Run: `cd apps/api && .venv/Scripts/python -m alembic heads`
Expected: `0075 (head)` — **um head só**. Dois heads = colisão de numeração; renumere antes de seguir.

- [ ] **Step 10: O cross-tenant, no Postgres REAL**

⚠️ **O teste de 404 do Step 1 roda em SQLite, que NÃO exercita RLS** — ele prova que a conversão de
erro está certa, não que a RLS esconde a linha. A garantia real mora em `rls_e2e`.

Acrescentar em `apps/api/tests/test_investments_rls.py` (o módulo já é `pytestmark =
pytest.mark.rls_e2e`), no mesmo padrão de `test_investment_cross_tenant_a_nao_ve_b`:

```python
def test_vincular_a_conta_bancaria_de_OUTRO_tenant_da_404_e_nunca_409() -> None:
    """A conta existe — no tenant B. Para o tenant A ela **não existe**, e a resposta tem de ser
    404.

    409 aqui confirmaria a existência da linha alheia: seria vazamento de existência com cara de
    validação. É o mesmo critério já fixado em `bank_service.get_account` e o mesmo que a 8.2
    pagou para aprender. **Só o Postgres reproduz** — no SQLite a linha do tenant B é visível e o
    teste passaria pelo motivo errado.
    """
```

Implemente o corpo seguindo a montagem de tenants que o arquivo já usa (dois tenants, `tenant_session`
de cada um): crie a `bank_account` `kind='investment'` no tenant **B**, a `InvestmentAccount` no
tenant **A**, e tente vincular pela sessão de A — esperando `InvestmentError` com `status_code == 404`.

Run: `cd apps/api && .venv/Scripts/python -m pytest -m rls_e2e tests/test_investments_rls.py -v` (exige Docker)
Expected: **PASS**

- [ ] **Step 11: Commit**

```bash
git add apps/api/migrations/versions/0075_investment_bank_account.py apps/api/app/modules/investments/ apps/api/tests/test_investments.py apps/api/tests/test_investments_rls.py
git commit -m "feat: a aplicação aponta para a conta bancária dela [Onda 2b-i]"
```

---

### Task 3: `register_yield` sem vínculo recusa com 409 acionável

**Files:**
- Modify: `apps/api/app/modules/investments/service.py` (`InvestmentError`, constantes, `register_yield`)
- Modify: `apps/api/app/modules/investments/router.py:38-39` (`_err`)
- Test: `apps/api/tests/test_investments.py`

**Interfaces:**
- Consumes: `InvestmentAccount.bank_account_id` (Task 2).
- Produces:
  - `investments.service.ACAO_CADASTRAR_CONTA: str` — **igual** a `payables.service.ACAO_CADASTRAR_CONTA` e `receivables.service.ACAO_CADASTRAR_CONTA`
  - `investments.service.SEM_CONTA_VINCULADA_MSG: str`
  - `InvestmentError.detail: dict | None` — `None` = o router serializa `str(e)`, como sempre

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar em `apps/api/tests/test_investments.py`:

```python
def test_a_acao_do_409_e_a_MESMA_string_de_payables_e_receivables():
    """**O contrato do 409 acionável é UM, com três constantes — e o teste é a sincronia.**

    A string é duplicada de propósito: fazer `investments` importar `payables` só por uma palavra
    seria acoplamento gratuito entre módulos de negócio. O que garante que as três não divirjam é
    **este teste**, não um comentário — a UI reconhece a situação por `acao`, e um segundo valor
    faria a tela deixar de abrir o caminho do vínculo **sem erro nenhum**, só sem funcionar.
    """
    from app.modules.investments import service as investments_service
    from app.modules.payables import service as payables_service
    from app.modules.receivables import service as receivables_service

    assert (
        investments_service.ACAO_CADASTRAR_CONTA
        == payables_service.ACAO_CADASTRAR_CONTA
        == receivables_service.ACAO_CADASTRAR_CONTA
    )


def test_registrar_rendimento_sem_vinculo_da_409_ACIONAVEL(client: TestClient, headers):
    """**É este 409 que põe P3 em zero POR CONSTRUÇÃO** — o mesmo mecanismo pelo qual a 8.12
    zerou P1 ao tornar a coluna obrigatória: a população esvazia sozinha e não depende de o dono
    lembrar de vincular.

    A degradação graciosa da Onda 3 (*"nada acontece, nada quebra"*) é certa LÁ e errada AQUI: o
    payout é disparado pelo sistema, sem humano na tela a quem perguntar; o rendimento é o dono
    digitando um valor agora.

    **Mutante que este teste mata:** remover a guarda — o rendimento volta a ser criável sem
    perna, e P3 deixa de ser zero por construção.
    """
    app_ = _aplicacao(client, headers)
    resp = client.post(
        f"/investments/{app_['id']}/yield",
        json={"amount_cents": 48_000, "date": "2026-07-14"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["acao"] == "cadastrar_conta", "a UI reconhece a situação por este campo"
    assert "Vincule esta aplicação" in detail["mensagem"]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py -k "acao_do_409 or sem_vinculo" -v`

Expected: **FAIL** — `AttributeError: module 'app.modules.investments.service' has no attribute 'ACAO_CADASTRAR_CONTA'` e 200 em vez de 409.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/investments/service.py`, substituir a classe `InvestmentError` e acrescentar o erro acionável:

```python
class InvestmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        # `None` = o router serializa `str(e)` como sempre. Só o erro ACIONÁVEL abaixo preenche.
        self.detail: dict | None = None


# ── O 409 ACIONÁVEL, no MESMO formato que a Story 8.12 fixou (AC9) ───────────────────────────
#
# ⚠️ **A string é duplicada de `payables.service.ACAO_CADASTRAR_CONTA` DE PROPÓSITO**, e a
# sincronia é garantida por **teste**, não por comentário:
# `test_investments.py::test_a_acao_do_409_e_a_MESMA_string_de_payables_e_receivables` compara as
# três constantes. Fazer `investments` importar `payables` só por causa de uma palavra seria
# acoplamento gratuito entre dois módulos de negócio — o mesmo motivo pelo qual `receivables` já
# a duplica em vez de importar.
ACAO_CADASTRAR_CONTA = "cadastrar_conta"

SEM_CONTA_VINCULADA_MSG = (
    "Para registrar o rendimento o e1p precisa saber em qual conta o dinheiro entrou — é isso "
    "que faz o movimento aparecer no seu extrato e a conferência valer alguma coisa. Vincule "
    "esta aplicação à conta bancária dela uma vez e o rendimento segue normalmente."
)


class ContaNaoVinculadaError(InvestmentError):
    """A aplicação não aponta para conta bancária nenhuma, e o rendimento precisa de uma perna.

    ⚠️ **409, não 422**, e o formato é o mesmo dos outros dois módulos: a tela reconhece a
    situação por `detail["acao"]` e abre o caminho do vínculo embutido. Um segundo valor no `acao`
    quebraria isso **sem erro nenhum**, só deixando de funcionar.
    """

    def __init__(self) -> None:
        super().__init__(SEM_CONTA_VINCULADA_MSG, 409)
        self.detail = {"acao": ACAO_CADASTRAR_CONTA, "mensagem": SEM_CONTA_VINCULADA_MSG}
```

Em `register_yield`, logo após `acc = get_account(db, account_id)`:

```python
    if not acc.bank_account_id:
        raise ContaNaoVinculadaError()
```

Em `apps/api/app/modules/investments/router.py`, substituir `_err`:

```python
def _err(e: service.InvestmentError) -> HTTPException:
    """`detail` estruturado quando o erro é ACIONÁVEL; string em todo o resto.

    Só `ContaNaoVinculadaError` preenche `detail` — é o contrato do 409 que a 8.12 fixou (AC9) e
    que a tela consome para oferecer o vínculo. Sem o `detail`, o front recebe uma frase e não
    tem como saber que existe uma ação.
    """
    return HTTPException(status_code=e.status_code, detail=e.detail or str(e))
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py -v`

Expected: **PASS**. ⚠️ Vários testes antigos de `register_yield` vão **quebrar** aqui — eles criam aplicação sem vínculo. Corrija-os passando `bank_account_id` na criação (via `_aplicacao(client, headers, bank_account_id=conta["id"])`), **nunca** relaxando a guarda.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/investments/ apps/api/tests/test_investments.py
git commit -m "feat: rendimento sem conta vinculada recusa com 409 acionável [Onda 2b-i]"
```

---

### Task 4: `register_yield` gera o movimento bancário

**Files:**
- Modify: `apps/api/app/modules/investments/service.py` (`register_yield`, `_today`, validação de data futura)
- Test: `apps/api/tests/test_investments.py`

**Interfaces:**
- Consumes: `InvestmentAccount.bank_account_id` (Task 2); `ContaNaoVinculadaError` (Task 3); `contar_rendimentos_sem_perna_bancaria` com `NOT EXISTS` (Task 1).
- Produces: um `BankTransaction` com `source='yield'`, `origin_id=charge.id`, `status='matched'`, `amount_cents` positivo. É este movimento que a Task 1 procura.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar em `apps/api/tests/test_investments.py`:

```python
def test_registrar_rendimento_gera_o_movimento_bancario_NASCIDO_CONCILIADO(
    client: TestClient, headers, db: Session
):
    """O coração da Onda 2b-i: o rendimento passa a ter perna bancária.

    **Crédito** (sinal positivo — o sinal vem da tabela de origem, `Charge` = +1, convenção
    canônica da 5.3), `origin_id = charge.id` **sem sufixo** (perna única ⇒ o `origin_id` É o id),
    e `status='matched'` porque movimento de origem do sistema **nasce conciliado** — ele não
    passa pelo matcher, e é isso que a Regra da Origem compra.
    """
    from app.modules.bank.models import SOURCE_YIELD, BankTransaction

    conta = _conta_bancaria(client, headers)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])

    resp = client.post(
        f"/investments/{app_['id']}/yield",
        json={"amount_cents": 48_000, "date": "2026-07-14"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    charge = db.scalars(
        select(Charge).where(Charge.external_ref == f"investment:{app_['id']}")
    ).one()
    tx = db.scalars(
        select(BankTransaction).where(BankTransaction.source == SOURCE_YIELD)
    ).one()

    assert tx.origin_id == charge.id, "perna única ⇒ o origin_id É o id, sem sufixo"
    assert tx.bank_account_id == conta["id"]
    assert tx.amount_cents == 48_000, "crédito: o sinal vem da tabela de origem (Charge = +1)"
    assert tx.posted_at == date(2026, 7, 14)
    assert tx.status == "matched", "movimento de origem do sistema NASCE conciliado"


def test_o_rendimento_com_perna_SAI_do_termo_P3(client: TestClient, headers, db: Session):
    """A ponta que fecha o círculo: o que a Task 1 mediu, agora produzido pelo caminho REAL.

    Este teste é o que prova que a onda entrega o que a justifica — os dois lados separados
    (o predicado e o movimento) poderiam estar corretos e não se encontrarem.
    """
    from app.modules.receivables.service import contar_rendimentos_sem_perna_bancaria

    conta = _conta_bancaria(client, headers)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])
    client.post(
        f"/investments/{app_['id']}/yield",
        json={"amount_cents": 48_000, "date": "2026-07-14"},
        headers=headers,
    )

    qtd, valor = contar_rendimentos_sem_perna_bancaria(
        db, start=date(2026, 7, 1), end=date(2026, 7, 31)
    )
    assert (qtd, valor) == (0, 0), "o rendimento tem perna — P3 tem de estar vazio"


def test_rendimento_com_data_FUTURA_e_recusado(client: TestClient, headers):
    """**A decisão que `bank/transfers.py:185` exige que a 2b tome em vez de copiar.**

    A razão NÃO é a mesma da transferência. É que um rendimento que ainda não caiu não é um
    rendimento; e, ao contrário de uma `Payable` com data futura, ele não teria para onde ir —
    não existe estado `scheduled` para rendimento, nem superfície onde apareceria, nem caminho de
    promoção. Aceitá-lo inventaria a quarta semântica de agendamento que o Art. IV proíbe.
    """
    from datetime import timedelta

    conta = _conta_bancaria(client, headers)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])
    # +2 dias, e não +1: com +1 a borda das 21h em UTC−3 tornaria o teste dependente da hora em
    # que a suíte roda — exatamente a classe de flake que `hoje_do_tenant` existe para eliminar.
    depois_de_amanha = date.today() + timedelta(days=2)

    resp = client.post(
        f"/investments/{app_['id']}/yield",
        json={"amount_cents": 48_000, "date": depois_de_amanha.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "ainda não caiu" in resp.json()["detail"]


def test_registrar_rendimento_CONTINUA_sem_criar_Transaction_nem_PlatformEarning(
    client: TestClient, headers, db: Session
):
    """**IV1 da Story 5.6, reafirmada e não relaxada.** A perna bancária é `bank_transactions`,
    que é o plano do BANCO. A Carteira é o plano da PLATAFORMA, e misturar os dois é exatamente o
    que produziu o bug de origem do Epic 8 (a Regra dos Planos).
    """
    conta = _conta_bancaria(client, headers)
    app_ = _aplicacao(client, headers, bank_account_id=conta["id"])
    antes_tx = len(db.scalars(select(Transaction)).all())
    antes_pe = len(db.scalars(select(PlatformEarning)).all())

    client.post(
        f"/investments/{app_['id']}/yield",
        json={"amount_cents": 48_000, "date": "2026-07-14"},
        headers=headers,
    )

    assert len(db.scalars(select(Transaction)).all()) == antes_tx
    assert len(db.scalars(select(PlatformEarning)).all()) == antes_pe
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py -k "movimento_bancario or SAI_do_termo or data_FUTURA" -v`

Expected: **FAIL** — `NoResultFound` no primeiro (nenhum `BankTransaction`), `(1, 48000) != (0, 0)` no segundo, 200 em vez de 422 no terceiro.

- [ ] **Step 3: Implementar**

Em `apps/api/app/modules/investments/service.py`, acrescentar aos imports:

```python
from app.modules.bank import origin as bank_origin
from app.modules.bank.models import KIND_INVESTMENT, SOURCE_YIELD
from app.modules.settings.service import hoje_do_tenant
```

Acrescentar a âncora de hoje e a guarda de data futura, antes de `register_yield`:

```python
def _today(db: Session) -> date:
    """A MESMA âncora de "hoje" do sistema (fuso do tenant) — nunca um segundo relógio.

    `datetime.now(UTC).date()` aqui adiantaria o dia das 21h à meia-noite em UTC−3 e recusaria um
    rendimento legítimo lançado à noite. Gate: `tests/test_fuso_do_tenant.py`.
    """
    return hoje_do_tenant(db)


_DATA_FUTURA_MSG = (
    "A data do rendimento não pode ser futura — um rendimento que ainda não caiu não é um "
    "rendimento. Lance-o no dia em que o banco creditar."
)
```

Substituir o corpo de `register_yield` a partir de `acc = get_account(...)`:

```python
    acc = get_account(db, account_id)
    # A perna bancária exige saber ONDE o dinheiro entrou. Sem vínculo, 409 ACIONÁVEL — é o que
    # põe P3 em zero por construção (ver a docstring de ContaNaoVinculadaError).
    if not acc.bank_account_id:
        raise ContaNaoVinculadaError()
    if date > _today(db):
        raise InvestmentError(_DATA_FUTURA_MSG, 422)
    if chart_account_id:
        _validate_financeiro_account(db, chart_account_id)

    acc.accrued_yield_cents += amount_cents

    # Charge sintética "já baixada": construída DIRETAMENTE (não via build_charge), NUNCA por
    # mark_paid/build_transaction → não gera Transaction/PlatformEarning (IV1). status=paid a torna
    # inclusive imune a um mark_paid/webhook posterior (guarda de idempotência).
    now = datetime.now(UTC)
    charge = Charge(
        tenant_id=tenant_id,
        client_id=None,  # rendimento não é de cliente nenhum
        description=f"Rendimento de aplicação: {acc.name}",
        kind=_YIELD_CHARGE_KIND,  # inerte (só afetaria o split, que não é acionado)
        method=_YIELD_CHARGE_METHOD,  # inerte
        amount_cents=amount_cents,
        due_date=date,
        competence_date=date,  # regime de competência (DRE, 5.3) — período do rendimento
        paid_at=now,  # regime de caixa: já realizado
        status=STATUS_PAID,
        chart_account_id=chart_account_id,  # grupo FINANCEIRO (validado acima quando informado)
        external_ref=external_ref_for(account_id),  # MARCA a origem (rendimento) + correlação
    )
    db.add(charge)
    db.flush()  # o id da Charge tem default Python-side; o origin_id abaixo precisa dele

    # ── A perna bancária (Onda 2b-i) ─────────────────────────────────────────────────────────
    # Pelo MESMO `sync_origin_movement` de payables/receivables/transfers — a única função do
    # repositório que escreve `source ∈ SOURCES_SISTEMA`. Não commita: movimento e lançamento
    # entram na MESMA transação, e é o commit abaixo que fecha os dois.
    #
    # `posted_at=date` e não `paid_at::date`: o `date` é o dia em que o rendimento caiu para o
    # dono. Usar o instante do registro erraria sempre que ele lançasse com qualquer atraso. O
    # resíduo (competência 31/07 × crédito 01/08) é o termo 3 da decomposição da divergência —
    # resíduo estrutural, que a banda de tolerância existe para absorver. Ele NÃO alcança o gate:
    # o predicado de P3 pergunta *"existe perna?"*, não *"a perna caiu nesta janela?"*.
    #
    # ⚠️ O ramo "origem desliquidada → apaga" de `sync_origin_movement` é INALCANÇÁVEL para
    # `source='yield'`: não existe caminho de estorno nem de exclusão de rendimento hoje (o router
    # só expõe `register_yield`). Está escrito aqui para quem reencontrar o ramo morto na 2b-ii
    # não achar que foi esquecimento.
    bank_origin.sync_origin_movement(
        db,
        tenant_id=tenant_id,
        actor=actor,
        source=SOURCE_YIELD,
        origin_id=charge.id,
        bank_account_id=acc.bank_account_id,
        posted_at=date,
        amount_cents=amount_cents,  # crédito: o sinal vem da tabela de origem (Charge = +1)
        description=f"Rendimento de aplicação: {acc.name}",
    )

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="investment.register_yield", target=acc.id
    )
    db.commit()
    db.refresh(acc)
    return acc
```

Acrescentar ao final da docstring do módulo (`investments/service.py`, antes do `"""` de fecho):

```
⚠️ ONDA 2b-i: `register_yield` passou a gerar TAMBÉM um `bank_transaction` `source='yield'`, pelo
`sync_origin_movement`. Isso **não relaxa a IV1**: `bank_transactions` é o plano do BANCO;
`Transaction`/`PlatformEarning` são o plano da PLATAFORMA, e continuam intocados. Misturar os dois
é a Regra dos Planos do Epic 8, e foi essa mistura que produziu o bug de origem daquele épico.
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_investments.py tests/test_bank_reconciliation_report.py tests/test_money_planes.py tests/test_invariante_do_trilho.py -v`

Expected: **PASS** em todos. ⚠️ Se `test_money_planes.py` ou `test_invariante_do_trilho.py` precisarem de edição, **pare** — é sinal de que a onda passou do escopo, não de que o gate está apertado demais.

- [ ] **Step 5: Matar os mutantes M3, M4 e M5**

Restaure por **cópia de arquivo**:

```bash
cd apps/api && cp app/modules/investments/service.py /tmp/inv.py.bak
```

- **M3** — remova `if not acc.bank_account_id: raise ContaNaoVinculadaError()`. `test_registrar_rendimento_sem_vinculo_da_409_ACIONAVEL` deve **FALHAR**.
- **M4** — troque `posted_at=date` por `posted_at=now.date()`. `test_registrar_rendimento_gera_o_movimento_bancario_NASCIDO_CONCILIADO` deve **FALHAR** na asserção de `posted_at`.
- **M5** — remova a guarda `if date > _today(db)`. `test_rendimento_com_data_FUTURA_e_recusado` deve **FALHAR**.

```bash
cp /tmp/inv.py.bak app/modules/investments/service.py
```

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/investments/ apps/api/tests/test_investments.py
git commit -m "feat: o rendimento de aplicação gera o movimento bancário [Onda 2b-i]"
```

---

### Task 5: A nota de P3 nomeia a causa, não a onda

**Files:**
- Modify: `apps/api/app/modules/bank/reconciliation.py:479-514` (comentário de bloco + `_note_rendimento_sem_perna`)
- Test: `apps/api/tests/test_bank_reconciliation_report.py:1433`
- Test: `apps/web/src/features/financeiro/conferencia.test.ts:408,441`
- Test: `apps/web/src/features/financeiro/ConferenciaPage.test.tsx:528`

**Interfaces:**
- Consumes: o comportamento das Tasks 3 e 4 (P3 zero por construção).
- Produces: `_note_rendimento_sem_perna(quantidade: int, valor_cents: int) -> str` — assinatura **inalterada**; só o texto muda.

⚠️ **Três asserções mudam de propósito, e isto está escrito ANTES de o arquivo ser aberto.** Ajustar asserção para fazer teste passar é a manobra que esconde regressão. Estas três mudam porque o **comportamento** mudou: depois das Tasks 3 e 4, a nota nunca mais pode prometer *"fecha na Onda 2b"*, porque a Onda 2b-i já fechou. `conferencia.test.ts:448` — que afirma que a nota de **P1/P2** *não* contém `"Onda 2b"` — permanece válida e **não se toca**.

- [ ] **Step 1: Reescrever a frase**

Em `apps/api/app/modules/bank/reconciliation.py`, substituir `_note_rendimento_sem_perna`:

```python
def _note_rendimento_sem_perna(quantidade: int, valor_cents: int) -> str:
    """P3 — o termo que a Onda 2b-i fechou POR CONSTRUÇÃO, e a frase mudou junto.

    Antes da 2b-i esta nota dizia *"este termo só fecha na Onda 2b"*, porque não havia nada que o
    dono pudesse fazer. Agora há: `register_yield` recusa (409 acionável) rendimento em aplicação
    sem conta vinculada, então todo rendimento novo nasce com perna e a população é vazia.

    **A nota fica, mesmo inalcançável no caminho normal.** Se ela disparar, não é mais uma onda
    faltando — é linha legada ou defeito, e ela precisa dizer o que FAZER. Uma frase que nomeasse
    uma onda já entregue seria mentira dita na tela, e apagar o contador deixaria a 2b-ii (que
    mexe justamente nesses dados) sem quem avise se eles voltarem inconsistentes.
    """
    plural = "s" if quantidade > 1 else ""
    return (
        f"{quantidade} rendimento{plural} de aplicação deste período ({_brl(valor_cents)}) ainda "
        f"não gera{'m' if quantidade > 1 else ''} movimento bancário. A divergência abaixo "
        "**inclui** esse valor. Vincule a aplicação à conta bancária dela para que o rendimento "
        "passe a aparecer no extrato."
    )
```

E no comentário de bloco acima (linhas 479-494), substituir o parágrafo *"Por que P1/P2 e P3 têm frases separadas"*:

```python
# **Por que P1/P2 e P3 continuam com frases separadas depois da Onda 2b-i:** os dois termos pedem
# ações DIFERENTES do dono. P1/P2 pedem informar a conta em cada lançamento legado; P3 pede
# vincular a aplicação à conta bancária dela, **uma vez**. Achatá-las numa frase só mandaria o
# dono caçar lançamento a lançamento um termo que se resolve num clique.
```

- [ ] **Step 2: Atualizar as três asserções, com a razão escrita**

Em `apps/api/tests/test_bank_reconciliation_report.py`, em `test_a1_...` (linhas 1433-1434):

```python
    assert "Onda 2b" not in nota, (
        "a Onda 2b-i FECHOU este termo — prometer uma onda já entregue é mentira na tela"
    )
    assert "Vincule a aplicação" in nota, "a nota nomeia a AÇÃO, agora que existe uma"
```

Em `apps/web/src/features/financeiro/conferencia.test.ts`, linha ~408, substituir a string esperada:

```ts
      "3 rendimentos de aplicação deste período (R$ 480,00) ainda não geram movimento bancário. A divergência abaixo **inclui** esse valor. Vincule a aplicação à conta bancária dela para que o rendimento passe a aparecer no extrato.",
```

e linha ~441:

```ts
    expect(comTermos.notes[1]).toContain("Vincule a aplicação");
```

Em `apps/web/src/features/financeiro/ConferenciaPage.test.tsx`, linha ~528, substituir a continuação da string:

```tsx
    "A divergência abaixo **inclui** esse valor. Vincule a aplicação à conta bancária dela " +
    "para que o rendimento passe a aparecer no extrato.",
```

⚠️ Confira o valor em `_brl` e a pluralização nas strings do frontend contra o que o backend produz — as duas asserções são literais completas.

- [ ] **Step 3: Rodar os dois lados**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_reconciliation_report.py -v`
Expected: **PASS**

Run: `pnpm --filter @e1p/web test -- --run src/features/financeiro/conferencia.test.ts src/features/financeiro/ConferenciaPage.test.tsx`
Expected: **PASS**

- [ ] **Step 4: Commit**

```bash
git add apps/api/app/modules/bank/reconciliation.py apps/api/tests/test_bank_reconciliation_report.py apps/web/src/features/financeiro/conferencia.test.ts apps/web/src/features/financeiro/ConferenciaPage.test.tsx
git commit -m "fix: a nota de P3 nomeia a ação, não uma onda já entregue [Onda 2b-i]"
```

---

### Task 6: O campo de vínculo na tela da aplicação

**Files:**
- Modify: `apps/web/src/features/financeiro/investimentos.ts`
- Modify: `apps/web/src/features/financeiro/InvestimentosPage.tsx`
- Test: `apps/web/src/features/financeiro/investimentos.test.ts`

**Interfaces:**
- Consumes: `InvestmentAccountOut.bank_account_id` (Task 2); o 409 com `detail.acao === "cadastrar_conta"` (Task 3).
- Produces: `rotuloDoVinculo(account: InvestmentAccount, contas: BankAccount[]): string` — puro, testável.

**Por que esta task existe.** Sem ela o 409 da Task 3 é um beco: o backend pede o vínculo e não há tela onde criá-lo. Capacidade de backend sem consumidor é a classe de defeito que o item 12 do WhatsApp já pagou neste repo.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `apps/web/src/features/financeiro/investimentos.test.ts`:

```ts
describe("rotuloDoVinculo", () => {
  const conta = { id: "c1", name: "CDB Itaú", kind: "investment", archived_at: null } as BankAccount;

  it("nomeia a conta quando a aplicação está vinculada", () => {
    const app = { id: "a1", bank_account_id: "c1" } as InvestmentAccount;
    expect(rotuloDoVinculo(app, [conta])).toBe("CDB Itaú");
  });

  it("diz o que FAZER quando não está vinculada — nunca só 'sem conta'", () => {
    const app = { id: "a1", bank_account_id: null } as InvestmentAccount;
    expect(rotuloDoVinculo(app, [conta])).toBe("Vincular a uma conta");
  });

  it("não inventa nome quando o vínculo aponta para conta que não está na lista", () => {
    const app = { id: "a1", bank_account_id: "sumida" } as InvestmentAccount;
    expect(rotuloDoVinculo(app, [conta])).toBe("Vincular a uma conta");
  });
});
```

Acrescentar aos imports do arquivo de teste:

```ts
import { rotuloDoVinculo, type InvestmentAccount } from "./investimentos";
import type { BankAccount } from "./contas";
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `pnpm --filter @e1p/web test -- --run src/features/financeiro/investimentos.test.ts`
Expected: **FAIL** — `rotuloDoVinculo is not a function`.

- [ ] **Step 3: Implementar o tipo e o helper**

Em `apps/web/src/features/financeiro/investimentos.ts`, acrescentar o campo à interface:

```ts
export interface InvestmentAccount {
  id: string;
  name: string;
  kind: string;
  index_rate_label: string;
  principal_cents: number;
  accrued_yield_cents: number;
  opened_at: string;
  created_at: string;
  /** A conta bancária ONDE ESTE DINHEIRO ESTÁ (Onda 2b-i). `null` = ainda não vinculada, e
   *  nesse estado o backend recusa o rendimento com 409 acionável. */
  bank_account_id: string | null;
}
```

E o helper, ao final do arquivo:

```ts
import type { BankAccount } from "./contas";

/**
 * Rótulo do vínculo da aplicação com a conta bancária dela. PURO.
 *
 * Sem vínculo (ou com vínculo apontando para conta que sumiu da lista) devolve a AÇÃO, nunca um
 * estado passivo tipo "sem conta": é este vínculo que o 409 do `register_yield` pede, e um rótulo
 * que só descreve o problema deixa o dono sem saber o que fazer.
 */
export function rotuloDoVinculo(
  account: InvestmentAccount,
  contas: BankAccount[],
): string {
  const conta = contas.find((c) => c.id === account.bank_account_id);
  return conta ? conta.name : "Vincular a uma conta";
}
```

- [ ] **Step 4: Ligar na tela**

Em `apps/web/src/features/financeiro/InvestimentosPage.tsx`:

1. Carregar as contas de aplicação ativas em `load()`:

```tsx
const { data: bankAccounts } = await api.get<BankAccount[]>("/bank/accounts");
setContas(bankAccounts.filter((c) => c.kind === "investment" && c.archived_at === null));
```

2. No card de cada aplicação (junto do `<Stat label="Principal" ...>`, por volta da linha 117), mostrar o vínculo:

```tsx
<Stat label="Conta bancária" value={rotuloDoVinculo(a, contas)} />
```

3. Extrair o seletor, para que `NewAccountModal` e `RegisterYieldModal` usem **o mesmo** (duas cópias divergem no primeiro ajuste):

```tsx
function SeletorDeConta({
  contas,
  value,
  onChange,
}: {
  contas: BankAccount[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="text-slate-600">Conta bancária da aplicação</span>
      <select
        className="mt-1 w-full rounded border border-slate-300 px-3 py-2"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">Escolha a conta…</option>
        {contas.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {contas.length === 0 && (
        <span className="mt-1 block text-xs text-amber-700">
          Nenhuma conta do tipo aplicação cadastrada. Cadastre-a em Contas &amp; Saldos.
        </span>
      )}
    </label>
  );
}
```

Em `NewAccountModal`, acrescentar `const [bankAccountId, setBankAccountId] = useState("");`, renderizar `<SeletorDeConta contas={contas} value={bankAccountId} onChange={setBankAccountId} />` e incluir no `api.post`:

```tsx
        bank_account_id: bankAccountId || null,
```

4. Em `RegisterYieldModal`, tratar o 409 acionável — é ele que transforma o erro num desvio de um passo em vez de um beco:

```tsx
  const [precisaVincular, setPrecisaVincular] = useState(false);
  const [bankAccountId, setBankAccountId] = useState("");

  async function save() {
    if (!account) return;
    setError(null);
    try {
      // Se o 409 pediu o vínculo e o dono acabou de escolher a conta, vincula ANTES de
      // reenviar — assim ele não perde o valor e a data que já digitou.
      if (precisaVincular && bankAccountId) {
        await api.patch(`/investments/${account.id}`, { bank_account_id: bankAccountId });
        setPrecisaVincular(false);
      }
      await api.post(`/investments/${account.id}/yield`, {
        amount_cents: Math.round(Number(amount.replace(",", ".")) * 100),
        date,
        chart_account_id: chartAccountId || null,
      });
      onSaved();
    } catch (e) {
      const detail = (e as AxiosError<{ detail?: { acao?: string; mensagem?: string } | string }>)
        .response?.data?.detail;
      if (typeof detail === "object" && detail?.acao === "cadastrar_conta") {
        setPrecisaVincular(true);
        setError(detail.mensagem ?? null);
        return;
      }
      setError(typeof detail === "string" ? detail : "Não foi possível registrar o rendimento.");
    }
  }
```

e, no JSX do modal, renderizar o seletor só quando o backend o pediu:

```tsx
      {precisaVincular && (
        <SeletorDeConta contas={contas} value={bankAccountId} onChange={setBankAccountId} />
      )}
```

⚠️ **`contas` precisa chegar aos dois modais** — passe como prop a partir do estado carregado no Step 4.1. Não refaça o `GET /bank/accounts` dentro de cada modal.

- [ ] **Step 5: Rodar**

Run: `pnpm --filter @e1p/web test -- --run src/features/financeiro/`
Expected: **PASS**

Run: `pnpm --filter @e1p/web exec tsc --noEmit`
Expected: exit 0

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/financeiro/
git commit -m "feat: a tela da aplicação vincula a conta bancária dela [Onda 2b-i]"
```

---

### Task 7: A entrada no CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — seção *"Financeiro: Controle Bancário e Conferência (Epic 8)"*, após o bloco *"Onda 2 (correção) — 'tenho a conta e NÃO sei o saldo'"*

**Interfaces:**
- Consumes: tudo.
- Produces: nada de código.

**Por que é uma task e não um passo.** No e1p a entrada no `CLAUDE.md` é **AC obrigatório de toda story**, com a mesma régua do teste (`CLAUDE.md` §5, passo 4). A razão está escrita lá: documentar como último passo é documentar o que vai ser cortado — foi assim que o Epic 5 inteiro ficou invisível por um mês.

- [ ] **Step 1: Escrever a entrada**

Acrescentar em `CLAUDE.md`, após a seção da Story 8.21:

```markdown
### Onda 2b-i — a perna bancária do rendimento (o termo P3 fecha)

> Spec: `docs/superpowers/specs/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-07-onda-2b-i-perna-bancaria-do-rendimento.md`

**A Onda 2b foi PARTIDA EM DUAS, e o recorte é a decisão.** O §647 do PRD descreve cinco
entregáveis; só dois tocam o gate, e o mais arriscado do épico inteiro (o backfill de
`principal_cents` sob `FORCE RLS`) não é nenhum dos dois. **2b-i** entrega o vínculo e o
movimento; **2b-ii** fica com o principal derivado, o backfill e o 409 de edição. Manter o
backfill colado ao destravamento da métrica primária refaria o acoplamento que o épico já
desfez uma vez ao separar a 2b da Onda 2.

**O achado que motivou o recorte, e que teria custado a onda inteira.**
`receivables.contar_rendimentos_sem_perna_bancaria` **não verificava se existia perna bancária** —
nenhum join, nenhum `NOT EXISTS`. Contava todo rendimento da janela. Pré-2b isso era inofensivo,
porque *"todos os rendimentos"* e *"os rendimentos sem perna"* eram o mesmo conjunto. Ligado o
movimento, os dois se separam e P3 seguiria contando o que passou a ter perna: **o gate não
abriria nem depois da onda que existe para destravá-lo**, e a nota na tela continuaria dizendo
*"este termo só fecha na Onda 2b"* sobre uma onda já fechada. O único teste que tocava a função
afirmava que ela era `callable` — e o membro que a mataria (um rendimento COM perna) era
inconstruível no caminho de produção. **É a família do §2 da Onda 2 (o teste que passa e não
prova nada), com um agravante: aqui o teste correto não podia sequer ser escrito.**

- [x] **`investment_accounts.bank_account_id`** (migration `0075`) — ligação 1:1 com a
  `bank_account` `kind='investment'`. `investment_accounts` **não** é absorvida: ela é a faceta
  de PRODUTO (rentabilidade, indexador), a `bank_account` é onde o dinheiro está. Índice único
  parcial com `tenant_id` na FRENTE (índice único é global e não respeita RLS — lição da 8.2).
  **Sem `UPDATE`:** `ADD COLUMN`/`CREATE INDEX` são DDL e a RLS não os alcança. A aplicação que
  já existia foi vinculada pelo dono, por ato, na tela.
- [x] **`register_yield` sem vínculo recusa com 409 acionável** (`{"acao":"cadastrar_conta"}`,
  terceira cópia da string, sincronia por teste). **É isso que põe P3 em zero POR CONSTRUÇÃO** —
  o mesmo mecanismo pelo qual a 8.12 zerou P1. A degradação graciosa da Onda 3 (*"nada acontece,
  nada quebra"*) foi rejeitada aqui, e a diferença é quem está na sala: o payout é disparado pelo
  sistema, sem humano a quem perguntar; o rendimento é o dono digitando um valor agora.
- [x] **`register_yield` gera `bank_transaction` `source='yield'`** pelo mesmo
  `sync_origin_movement`, na mesma transação, nascido conciliado. **`SOURCE_YIELD` já estava em
  `SOURCES_SISTEMA` desde a 0059** — como nenhuma regra do repo é escrita contra `source` solto,
  todas já cobriam `yield` sem uma linha de mudança. **A IV1 da 5.6 NÃO foi relaxada:**
  `bank_transactions` é o plano do BANCO, `Transaction`/`PlatformEarning` são o plano da
  PLATAFORMA, e continuam intocados.
- [x] **`posted_at = date` do rendimento, não o instante do registro** — e o resíduo está
  declarado: competência 31/07 com crédito em 01/08 desloca o movimento um dia. É o **termo 3**
  da decomposição da divergência, que a banda de tolerância existe para absorver. **A escolha só
  é barata porque o predicado de P3 é `NOT EXISTS`:** ele pergunta *"existe perna?"*, não *"a
  perna caiu nesta janela?"*. Se a data fosse o eixo do termo, isto seria decisão de gate.
- [x] **Data futura: 422** — a decisão que `bank/transfers.py:185` exigia que a 2b tomasse em vez
  de copiar. A razão **não** é a da transferência: um rendimento que ainda não caiu não é um
  rendimento, e ele não teria para onde ir — não existe `scheduled` para rendimento, nem
  superfície, nem caminho de promoção (Art. IV).
- [x] **A nota de P3 deixou de nomear uma onda e passou a nomear a AÇÃO** (*"Vincule a aplicação
  à conta bancária dela"*). Ela fica mesmo inalcançável no caminho normal: se disparar, é linha
  legada ou defeito, e apagá-la deixaria a 2b-ii sem quem avise se os dados voltarem
  inconsistentes.

**Regra que fica (reverberar): função cujo NOME promete um filtro tem de tê-lo, mesmo quando o
filtro é hoje redundante.** `contar_rendimentos_sem_perna_bancaria` esteve certa por coincidência
de população durante uma onda inteira. A coincidência não deixa rastro no código, não quebra teste
ao terminar, e o dia em que ela termina é justamente o dia em que a função vira defeito.

- **Dívida:** o ramo *"origem desliquidada → apaga"* de `sync_origin_movement` é **inalcançável**
  para `source='yield'` — não existe estorno nem exclusão de rendimento (o router só expõe
  `register_yield`). Está na docstring para não parecer esquecimento na 2b-ii.
- **Dívida:** **aceite visual em ~360px do campo de vínculo NÃO foi feito** — mesma dívida da
  8.13 AC9 e da 8.21. Bloqueia release, não bloqueia merge.
- **Dívida:** a 2b-ii continua com o único backfill do épico, e ele continua sendo o item de
  maior risco.
```

- [ ] **Step 2: Conferir que nada acima ficou desatualizado**

O §5 do bloco da Onda 2 (*"O gate NÃO abre 'depois da Onda 2'"*) diz *"Quem registra rendimento de
aplicação precisa da **2b**"*. Continua **verdadeiro** — e agora aponta para a 2b-i. Acrescente
`-i` ali para quem ler daqui a três meses não procurar a onda inteira.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: a Onda 2b-i entra na memória do projeto [Onda 2b-i]"
```

---

## Verificação final (antes de abrir o PR)

- [ ] Suíte backend inteira: `cd apps/api && .venv/Scripts/python -m pytest -q` — **em primeiro plano**
- [ ] `ruff check apps/api` → *All checks passed!*
- [ ] Suíte frontend inteira: `pnpm --filter @e1p/web test -- --run`
- [ ] `pnpm --filter @e1p/web exec tsc --noEmit` → exit 0
- [ ] `cd apps/api && .venv/Scripts/python -m alembic heads` → **um head só**, `0075`
- [ ] Migration validada contra **Postgres real** (não só SQLite) — mesmo sem `UPDATE`, o índice
      único parcial é a parte que o SQLite trata diferente
- [ ] `pytest -m rls_e2e tests/test_investments_rls.py` (exige Docker) — o 404 cross-tenant do
      vínculo. **O teste equivalente em SQLite não prova isso**
- [ ] **PR obrigatório:** `main` é protegida (GH006), com 4 checks. Push é do `@devops`.

**Não incluído de propósito, e é o que a 2b-ii carrega:** `principal_cents` derivado, o backfill
sob `FORCE RLS`, o 409 ao editar principal, o extrato da aplicação no `InvestimentosPage`.
