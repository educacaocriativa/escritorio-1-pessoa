# Onda 3 — o payout fecha o circuito · Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O saque da Carteira vira a entidade `Payout` e escreve o movimento bancário na mesma transação, fechando o termo P4 da pré-condição do gate do Epic 8.

**Architecture:** `wallet` declara um `Protocol` + registrador; `bank/payout.py` implementa; `app/main.py` faz a fiação com verificação fail-closed no boot. Nenhum dos dois módulos importa o outro — a dependência **some**, não é escondida. Tudo numa transação só: ou o saque e o movimento existem, ou nenhum dos dois.

**Tech Stack:** FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 (SQLite na suíte unitária, testcontainers nos `rls_e2e`) · React 18 + Vite + TypeScript + Tailwind · pytest · vitest · Playwright

**Spec:** `docs/superpowers/specs/2026-08-09-onda-3-payout-circuito-design.md`

---

## Global Constraints

Valem para **todas** as tarefas. Não repetidas por tarefa.

1. **Dinheiro sempre em centavos inteiros** (`BigInteger`), nunca float.
2. **Datas sempre pelo fuso do tenant:** `from app.modules.settings.service import hoje_do_tenant` (import lazy dentro da função, como `cockpit/service.py:101` faz). **`date.today()` é regressão.**
3. **`sync_origin_movement` NÃO commita** — contrato. Quem chama fecha a transação.
4. **`bank` não importa `wallet`; `wallet` não importa `bank`.** Nenhuma tarefa deste plano relaxa isso. Se seu código parece precisar disso, a peça que falta é um parâmetro no `Protocol`.
5. **`main` é protegida** (GH006, 4 checks). Trabalhe na branch `feat/onda-3-payout-circuito`. Push e PR são do `@devops` — **não faça push**.
6. **Migration com `UPDATE` sobre tabela com `FORCE RLS` é proibida neste plano.** A `0077` é só DDL. Se você se pegar escrevendo um `UPDATE`, pare e releia §3.3 da spec.
7. **A suíte backend leva ~10 min.** Rode o arquivo de teste específico durante o ciclo; a suíte inteira só nas tarefas que pedem.
8. **Comando de teste backend:** `cd apps/api && .venv/Scripts/python -m pytest <arquivo> -v` (venv único em `apps/api/.venv`).
9. **Comando de teste frontend:** `cd apps/web && npx vitest run <arquivo>`.
10. **Rótulos de saldo são constantes, nunca strings literais.** `TOTAL_EM_CONTAS_LABEL` / `DISPONIVEL_CAIXA_LABEL` (`apps/web/src/features/financeiro/contas.ts:512-513`). A string `"no banco"` é **proibida** fora da Projeção.
11. **Todo campo de saldo em schema de saída declara procedência** num irmão `*_origem` com valor de `app/core/money_planes.py` (`ORIGEM_PLATAFORMA`/`ORIGEM_BANCO`/`ORIGEM_MISTO`/`ORIGEM_INDISPONIVEL`).
12. **Commits atômicos e frequentes**, conventional commits, com `[Epic 8, Onda 3]` no assunto.

---

## Estrutura de arquivos

**Criar:**

| Arquivo | Responsabilidade |
|---|---|
| `apps/api/migrations/versions/0077_payouts.py` | DDL: tabela `payouts` + coluna `transactions.payout_id`. Zero `UPDATE`. |
| `apps/api/app/modules/bank/payout.py` | A implementação do registrador: acha a conta principal, chama o sincronizador. **~60 linhas.** Não importa `wallet`. |
| `apps/api/tests/test_wallet_payout.py` | Comportamento do payout: os dois 409, o caminho feliz, o vínculo `payout_id`. |
| `apps/api/tests/test_payout_registrar.py` | O contrato: `Protocol`, registrador, fail-closed de boot, gate de invariante. |
| `apps/api/tests/test_payout_rls.py` | `pytest.mark.rls_e2e` — Postgres real, migration 0077 exercitada, isolamento entre tenants. |
| `apps/web/src/features/financeiro/PayoutHistory.tsx` | Lista de saques. `<ul>`, nunca `<table>`. |
| `apps/web/src/features/financeiro/PayoutHistory.test.tsx` | Teste da lista. |

**Modificar:**

| Arquivo | Mudança |
|---|---|
| `apps/api/app/modules/bank/router.py` | **Task 2b:** expõe `POST /accounts/{id}/set-primary` — o service espera rota desde a Story 8.7. |
| `apps/web/src/features/financeiro/ContasSaldosPage.tsx` | **Task 2b:** botão "Tornar principal". |
| `apps/api/app/modules/wallet/models.py` | `class Payout` + `Transaction.payout_id`. |
| `apps/api/app/modules/wallet/service.py` | `Protocol` + registrador + `request_payout` reescrito + `list_payouts`. |
| `apps/api/app/modules/wallet/schemas.py` | `PayoutOut`; `PayoutResult` ganha `payout_id`. |
| `apps/api/app/modules/wallet/router.py:76-81` | `try/except WalletError` no `POST /payout` (**hoje não tem**) + `GET /payouts`. |
| `apps/api/app/main.py` | Fiação + `verifica_fiacao_do_payout()`. |
| `apps/api/app/modules/cockpit/service.py:127-137` | `finance_summary` passa a devolver o saldo em conta. |
| `apps/api/app/modules/cockpit/schemas.py:41-47` | `FinanceSummary` ganha dois campos. |
| `apps/api/tests/test_bank_origin.py:808` | Entrada nova em `_CHAMADORES_PERMITIDOS`. |
| `apps/api/tests/test_money_planes.py` | Asserção nova: `bank/payout.py` não cita `Transaction`. |
| `apps/web/src/features/financeiro/FinanceiroPage.tsx:85-88` | Tratamento do 409 + montagem do histórico. |
| `apps/web/src/features/cockpit/CockpitPage.tsx` | Card do saldo em conta. |
| `CLAUDE.md` | A entrada da onda (AC obrigatório, §5 passo 4). |

---

## Task 1: Migration 0077 e os modelos

**Files:**
- Create: `apps/api/migrations/versions/0077_payouts.py`
- Modify: `apps/api/app/modules/wallet/models.py`
- Test: `apps/api/tests/test_payout_registrar.py`

**Interfaces:**
- Consumes: `Base, TenantMixin, TimestampMixin, _uuid` de `app.db.base`
- Produces: `wallet.models.Payout` (colunas `id, tenant_id, amount_cents, paid_on, bank_account_id, bank_transaction_id, actor, created_at, updated_at`); `wallet.models.Transaction.payout_id: str | None`

- [ ] **Step 1: Escrever o teste que falha**

Criar `apps/api/tests/test_payout_registrar.py`:

```python
"""Onda 3 — o contrato do payout: modelo, registrador e fiação.

Espelha `test_bank_origin.py` (Story 8.9): **o contrato vem antes do comportamento.**
O comportamento do saque vive em `test_wallet_payout.py`.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.wallet.models import Payout


def test_payout_exige_bank_transaction_id(db: Session):
    """**A invariante da onda em forma de DDL: não existe `Payout` sem perna bancária.**

    É P4 = 0 escrito de forma auditável. Um `Payout` órfão significaria um saque que o razão
    bancário não conhece — exatamente o estado que esta onda existe para tornar impossível.
    """
    p = Payout(
        id="pay-1",
        tenant_id="t1",
        amount_cents=500_00,
        paid_on=date(2026, 8, 9),
        bank_account_id="acc-1",
        bank_transaction_id=None,  # ← o que precisa ser recusado
        actor="u1",
    )
    db.add(p)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_payout_persiste_completo(db: Session):
    p = Payout(
        id="pay-2",
        tenant_id="t1",
        amount_cents=500_00,
        paid_on=date(2026, 8, 9),
        bank_account_id="acc-1",
        bank_transaction_id="btx-1",
        actor="u1",
    )
    db.add(p)
    db.flush()
    assert db.get(Payout, "pay-2").amount_cents == 500_00
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v`
Expected: FAIL — `ImportError: cannot import name 'Payout' from 'app.modules.wallet.models'`

- [ ] **Step 3: Acrescentar o modelo**

Em `apps/api/app/modules/wallet/models.py`, depois de `class Transaction` (antes de `SETTINGS_ID`):

```python
class Payout(Base, TenantMixin, TimestampMixin):
    """O saque da Carteira como **fato**, não como troca de status (Onda 3).

    Antes desta onda, `request_payout` virava N `Transaction` para `withdrawn`, gravava
    `audit.record(target=str(total))` — o VALOR, não um id — e não deixava linha nenhuma. O dono
    via o saldo sumir e não conseguia listar o que sacou, quando, nem para onde.

    Isso não era só lacuna de produto: `bank.origin.sync_origin_movement` exige `origin_id`
    apontando para *"o lançamento que o gerou"*, sob índice único 1:1. **Sem entidade não havia
    para onde apontar**, e o payout não podia virar movimento bancário como as outras quatro
    origens já viraram.

    ⚠️ **`bank_account_id` é SNAPSHOT, não referência viva.** A conta principal pode mudar depois;
    o saque de agosto não pode passar a dizer que caiu na conta que virou principal em outubro.

    ⚠️ **`bank_transaction_id` é `NOT NULL`, e a diferença para os irmãos é deliberada.** Em
    `payable.bank_transaction_id` / `charge.bank_transaction_id` a coluna é nullable porque o
    lançamento pode legitimamente ainda não estar liquidado. **Payout não liquidado não existe** —
    o caminho de código não tem ramo que crie um sem destino (ver `wallet/service.request_payout`).
    Não "harmonize" as três colunas: elas têm contratos diferentes.
    """

    __tablename__ = "payouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    bank_account_id: Mapped[str] = mapped_column(String(36), nullable=False)
    bank_transaction_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor: Mapped[str] = mapped_column(String(36), nullable=False)
```

E dentro de `class Transaction`, logo depois de `external_ref`:

```python
    # Onda 3 — a qual saque esta venda pertence. NULL = ainda não sacada, **ou** sacada antes da
    # migration 0077 (não há backfill, e não pode haver: aqueles saques nunca foram registrados,
    # então não existe linha a que pertencer — a mesma manobra da 2b-ii).
    payout_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v`
Expected: PASS (2 testes)

- [ ] **Step 5: Escrever a migration**

Criar `apps/api/migrations/versions/0077_payouts.py`:

```python
"""O saque da Carteira vira fato, e ganha perna bancária (Epic 8, Onda 3)

Revision ID: 0077
Revises: 0076
Create Date: 2026-08-09

**Por quê.** `request_payout` marcava `withdrawn` e não deixava registro. Sem uma linha
representando o saque não existe `origin_id` para o `sync_origin_movement` apontar — e sem isso o
payout não pode virar `bank_transaction`, o que mantém aberto o termo **P4** da pré-condição do
gate do épico. Enquanto P4 for não-vazio numa janela, a divergência daquele ciclo **não pode ser
lida**, e nenhuma onda é liberada nem morta com base nela.

⚠️ **NENHUM `UPDATE`, e a ausência é a razão de esta migration ser segura.** As seis armadilhas
registradas neste repo (`0046`, `0066`, `0067`, `0068`, `0069`, `0073`) são todas a mesma: um
`UPDATE` de backfill filtrado em silêncio pela RLS, completando com sucesso APARENTE e invisível
para o SQLite da suíte. `CREATE TABLE` e `ADD COLUMN` são DDL — a RLS não os alcança.

**As `Transaction` já sacadas ficam com `payout_id IS NULL` para sempre, e isso não é dívida.**
Elas não têm saque a que pertencer, porque o saque nunca foi registrado. Inventar um `Payout`
retroativo seria escrever história sem testemunha — a manobra que a Onda 2b-ii recusou.

⚠️ **`bank_transaction_id` nasce `NOT NULL`.** É a invariante da onda (P4 = 0) fail-closed no
banco, e não uma escolha estética. Ver a docstring de `wallet.models.Payout`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: str | None = "0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payouts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("bank_account_id", sa.String(length=36), nullable=False),
        sa.Column("bank_transaction_id", sa.String(length=36), nullable=False),
        sa.Column("actor", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_payouts_paid_on", "payouts", ["tenant_id", "paid_on"])

    op.execute("ALTER TABLE payouts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE payouts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON payouts
            USING (tenant_id = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true))
        """
    )

    op.add_column("transactions", sa.Column("payout_id", sa.String(length=36), nullable=True))


def downgrade() -> None:
    # O que se perde é o REGISTRO do saque e o vínculo com o razão bancário — o payout volta a ser
    # uma troca de status sem testemunha e o termo P4 do gate reabre. Fica escrito aqui em vez de
    # ser descoberto no meio de um rollback.
    op.drop_column("transactions", "payout_id")
    op.drop_index("ix_payouts_paid_on", table_name="payouts")
    op.drop_table("payouts")
```

- [ ] **Step 6: Conferir que a cadeia do alembic está íntegra**

Run: `cd apps/api && .venv/Scripts/python -m alembic heads`
Expected: uma única head, `0077`.

Se aparecerem duas heads, alguém mergeou outra migration em `main` enquanto você trabalhava. **Renumere a sua** (quem mergeia depois renumera) — ver a docstring da `0076`, que documenta esta armadilha pela terceira vez neste repositório.

- [ ] **Step 7: Commit**

```bash
git add apps/api/migrations/versions/0077_payouts.py apps/api/app/modules/wallet/models.py apps/api/tests/test_payout_registrar.py
git commit -m "feat: o saque vira fato — tabela payouts e o vínculo com a venda [Epic 8, Onda 3]"
```

---

## Task 2: O contrato — `Protocol` e registrador na Carteira

**Files:**
- Modify: `apps/api/app/modules/wallet/service.py`
- Test: `apps/api/tests/test_payout_registrar.py`

**Interfaces:**
- Consumes: nada de tarefas anteriores além de `wallet.models.Payout`
- Produces:
  - `wallet.service.DestinoDoPayout` — dataclass frozen: `bank_account_id: str | None`, `bank_transaction_id: str | None`, `recusa_detalhe: str | None`
  - `wallet.service.RegistradorDePayout` — `Protocol` com `__call__(db, *, tenant_id, actor, payout_id, amount_cents, posted_at) -> DestinoDoPayout | None`
  - `wallet.service.register_payout_registrar(fn: RegistradorDePayout) -> None`
  - `wallet.service.payout_registrar_registrado() -> bool`
  - módulo-global `wallet.service._payout_registrar`

**Nota de refinamento sobre a spec §4.1.2.** A spec dizia *"a Carteira traduz"* o piso de data. A frase precisa da `opening_date`, que **só o módulo `bank` conhece** — e a Carteira não pode lê-la. Solução: `bank/payout.py` captura o `BankError` e devolve a mensagem dele em `recusa_detalhe` (um **fato**, já bem escrito: *"A data do movimento precisa ser posterior a 2026-07-01…"*); a Carteira decide o status code e a moldura da frase. O texto de "sem conta principal" — que não contém dado nenhum do banco — continua inteiramente da Carteira, como a spec quis.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `apps/api/tests/test_payout_registrar.py`:

```python
from app.modules.wallet import service as wallet_service


def test_registrador_comeca_nao_registrado(monkeypatch):
    monkeypatch.setattr(wallet_service, "_payout_registrar", None)
    assert wallet_service.payout_registrar_registrado() is False


def test_register_payout_registrar_liga_o_registrador(monkeypatch):
    monkeypatch.setattr(wallet_service, "_payout_registrar", None)

    def _fake(db, **kwargs):
        return wallet_service.DestinoDoPayout(
            bank_account_id="acc-1", bank_transaction_id="btx-1"
        )

    wallet_service.register_payout_registrar(_fake)
    assert wallet_service.payout_registrar_registrado() is True


def test_destino_do_payout_carrega_recusa_sem_ids():
    """A forma "não deu, e o motivo é um FATO do banco" — não uma frase de tela."""
    d = wallet_service.DestinoDoPayout(recusa_detalhe="A data precisa ser posterior a 2026-07-01.")
    assert d.bank_account_id is None
    assert d.recusa_detalhe.startswith("A data")
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v -k registrador or destino`
Expected: FAIL — `AttributeError: module 'app.modules.wallet.service' has no attribute '_payout_registrar'`

- [ ] **Step 3: Implementar o contrato**

Em `apps/api/app/modules/wallet/service.py`, no topo (depois dos imports existentes), acrescentar:

```python
from dataclasses import dataclass
from datetime import date
from typing import Protocol
```

E, antes de `def request_payout`:

```python
# ── O ponto de contato entre o plano da PLATAFORMA e o plano do BANCO (Onda 3) ────────────────
#
# ⚠️ **Este é o ÚNICO write que atravessa a fronteira dos planos** (design-mãe §1.2), e ele é
# declarado AQUI, do lado da Carteira, sendo implementado por `bank/payout.py` e ligado em
# `app/main.py`. Mesmo padrão das duas travessias irmãs (guarda de contagem dupla, Story 8.17 AC6;
# termos do gate, Story 8.16 AC7/AC8): **quem precisa do serviço declara o `Protocol`; quem
# implementa não é importado por ninguém; a fiação mora na composição.**
#
# **O gate `test_wallet_nao_importa_bank` fica verde porque a dependência SUMIU, não porque foi
# escondida.** Se o seu código parece precisar de `from app.modules.bank import ...` aqui, o que
# falta é um parâmetro neste `Protocol`.
#
# ⚠️ **Por que NÃO é `core/events` (o design-mãe §6.6 mandava).** `events.emit` engole exceção de
# assinante por contrato (*"o fato já aconteceu e foi commitado; reações são best-effort"*), e os
# dois assinantes existentes recebem o evento DEPOIS do commit. A Regra da Origem (a) exige o
# movimento na MESMA transação. Pelo barramento, um payout commitaria com a perna bancária
# faltando **e sem erro em lugar nenhum** — a família de defeito que o Epic 8 existe para eliminar.
# O §6.6 é anterior à Onda 2 e não sobrevive ao que ela estabeleceu.


@dataclass(frozen=True)
class DestinoDoPayout:
    """Para onde o saque foi — ou o **fato** que impediu.

    Três formas, e só três:

    - **sucesso:** os dois ids preenchidos, `recusa_detalhe is None`;
    - **sem conta principal:** o registrador devolve `None` (não esta dataclass). A frase é da
      Carteira, porque não contém dado nenhum do banco;
    - **o banco recusou o movimento** (hoje: data anterior à abertura da conta): `recusa_detalhe`
      traz a mensagem do próprio módulo `bank`, que já nomeia a data. A Carteira decide o status
      code e a moldura; o fato vem de quem o conhece.
    """

    bank_account_id: str | None = None
    bank_transaction_id: str | None = None
    recusa_detalhe: str | None = None


class RegistradorDePayout(Protocol):
    """Escreve a perna bancária do saque. Implementado por `bank/payout.py`. **NÃO commita.**

    Devolve `None` quando não há conta principal ativa — e isso é **valor de retorno, não
    exceção**, de propósito: assim o texto do 409 pertence à Carteira, que é quem tem o usuário na
    frente, e o módulo `bank` não precisa conhecer o vocabulário da tela do outro plano.
    """

    def __call__(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor: str,
        payout_id: str,
        amount_cents: int,
        posted_at: date,
    ) -> DestinoDoPayout | None: ...


_payout_registrar: RegistradorDePayout | None = None


def register_payout_registrar(fn: RegistradorDePayout) -> None:
    """Chamado UMA vez, por `app/main.py`. Ver `verifica_fiacao_do_payout` lá."""
    global _payout_registrar
    _payout_registrar = fn


def payout_registrar_registrado() -> bool:
    return _payout_registrar is not None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Confirmar que o gate da Regra dos Planos continua verde**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_money_planes.py -v`
Expected: PASS, **sem nenhuma alteração no arquivo de teste**. Se falhou, você importou `bank` dentro de `wallet` — desfaça.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/wallet/service.py apps/api/tests/test_payout_registrar.py
git commit -m "feat: o contrato do ponto de contato entre os planos, sem barramento [Epic 8, Onda 3]"
```

---

## Task 2b: A conta principal precisa poder ser escolhida

> ⚠️ **Esta tarefa não estava na spec, e sem ela a onda inteira entrega um beco sem saída.**
> `bank.service.set_primary` (`service.py:1040`) existe, tem `audit.record`, tem docstring
> explicando que faz a troca num commit só *"senão o consumidor da Onda 6 (payout) escolheria a
> conta de destino no par ou ímpar"* — **e não tem rota, não tem botão e não tem um único
> chamador.** `ContasSaldosPage` apenas *exibe* o selo `is_primary`.
>
> O 409 desta onda diz *"defina sua conta principal em Contas & Saldos"*. Sem esta tarefa, o dono
> vai lá e **não encontra como** — o saque fica travado para sempre, e a onda troca um problema
> silencioso (P4 aberto) por um problema barulhento (o botão de sacar não funciona nunca mais).
> É a mesma classe do PR #58: a ação existia, o caminho até ela não.

**Files:**
- Modify: `apps/api/app/modules/bank/router.py`, `apps/web/src/features/financeiro/ContasSaldosPage.tsx`
- Test: `apps/api/tests/test_bank_accounts.py`

**Interfaces:**
- Produces: `POST /bank/accounts/{account_id}/set-primary → BankAccountOut` (usado pelos testes das Tasks 3, 5 e 7)

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `apps/api/tests/test_bank_accounts.py`:

```python
def test_definir_conta_principal(client: TestClient, headers):
    a = client.post("/bank/accounts", json=_payload(name="Itaú"), headers=headers).json()
    b = client.post("/bank/accounts", json=_payload(name="Nubank"), headers=headers).json()

    resp = client.post(f"/bank/accounts/{a['id']}/set-primary", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_primary"] is True

    # Trocar a principal desmarca a anterior — no MESMO commit (service.py:1040).
    client.post(f"/bank/accounts/{b['id']}/set-primary", headers=headers)
    contas = {c["id"]: c["is_primary"] for c in client.get("/bank/accounts", headers=headers).json()}
    assert contas[b["id"]] is True
    assert contas[a["id"]] is False


def test_conta_arquivada_nao_vira_principal(client: TestClient, headers):
    a = client.post("/bank/accounts", json=_payload(), headers=headers).json()
    client.post(f"/bank/accounts/{a['id']}/archive", headers=headers)
    resp = client.post(f"/bank/accounts/{a['id']}/set-primary", headers=headers)
    assert resp.status_code == 422
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_accounts.py -v -k principal`
Expected: FAIL — 405/404 (rota inexistente)

- [ ] **Step 3: Expor a rota**

Em `apps/api/app/modules/bank/router.py`, junto das outras rotas de conta (depois de `archive`):

```python
@router.post("/accounts/{account_id}/set-primary", response_model=BankAccountOut)
def set_primary(
    account_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> BankAccountOut:
    """Elege a conta principal — o destino do payout da Carteira (Onda 3).

    ⚠️ **O service existe desde a Story 8.7 e ficou sem porta até aqui.** Ele foi escrito
    explicitamente para este consumidor (ver a docstring de `service.set_primary`), mas nenhuma
    rota o alcançava: o dono via o selo "principal" na tela e não tinha como atribuí-lo. A Onda 3 é
    a primeira que **depende** disso, e por isso é ela que abre a porta.
    """
    try:
        acc = service.set_primary(
            db, account_id=account_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.BankError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return _account_out(acc, db)
```

⚠️ **Use o mesmo helper de montagem do `BankAccountOut` que as outras rotas de conta usam** (o que resolve saldo derivado + `origem_do_saldo_derivado`). Leia `router.py:211-256` e copie a forma — não monte o schema à mão, senão esta rota devolveria a procedência do saldo por um caminho próprio, que é a duplicação que a Story 8.21 pagou para eliminar.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_bank_accounts.py -v`
Expected: PASS

- [ ] **Step 5: O botão em Contas & Saldos**

Em `apps/web/src/features/financeiro/ContasSaldosPage.tsx`, no cartão da conta (perto do selo `is_primary`, linha ~358), acrescentar a ação para quem **não** é principal:

```tsx
{!account.is_primary && !account.archived_at && (
  <button
    onClick={async () => {
      await api.post(`/bank/accounts/${account.id}/set-primary`);
      load();
    }}
    className="inline-flex items-center gap-1 text-neutral-600 hover:text-primary-600"
  >
    Tornar principal
  </button>
)}
```

- [ ] **Step 6: Teste do front**

Acrescentar ao teste existente de `ContasSaldosPage`:

```tsx
it("oferece tornar principal para conta que não é a principal", async () => {
  // mock: duas contas, nenhuma principal
  render(<ContasSaldosPage />);
  expect(await screen.findAllByText("Tornar principal")).toHaveLength(2);
});

it("não oferece tornar principal para a conta que já é principal", async () => {
  // mock: uma conta com is_primary: true
  render(<ContasSaldosPage />);
  expect(screen.queryByText("Tornar principal")).toBeNull();
});
```

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/bank/router.py apps/api/tests/test_bank_accounts.py apps/web/src/features/financeiro/ContasSaldosPage.tsx
git commit -m "feat: a conta principal passa a poder ser escolhida (o service esperava desde a 8.7) [Epic 8, Onda 3]"
```

---

## Task 3: A implementação — `bank/payout.py`

**Files:**
- Create: `apps/api/app/modules/bank/payout.py`
- Modify: `apps/api/tests/test_bank_origin.py:808` (allowlist), `apps/api/tests/test_money_planes.py`
- Test: `apps/api/tests/test_payout_registrar.py`

**Interfaces:**
- Consumes: `bank.service.primary_account`, `bank.service.BankError`, `bank.origin.sync_origin_movement`, `bank.models.SOURCE_PAYOUT`
- Produces: `bank.payout.registra_payout(db, *, tenant_id, actor, payout_id, amount_cents, posted_at) -> DestinoDoPayout | None`

⚠️ **Este arquivo NÃO importa `app.modules.wallet` e NÃO cita o símbolo `Transaction`.** Ele recebe números e ids como argumento. A dataclass de retorno é construída por *duck typing* — o registrador devolve um objeto com os três atributos, e quem tipa é o `Protocol` do outro lado. Isso é o que mantém `test_bank_nao_referencia_transaction` apertado **sem allowlist e sem justificativa escrita**.

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `apps/api/tests/test_payout_registrar.py`:

```python
from fastapi.testclient import TestClient

from app.modules.bank import payout as bank_payout
from app.modules.bank.models import SOURCE_PAYOUT, STATUS_MATCHED, BankTransaction

REGISTER_PAYOUT = {
    "legal_name": "Payout ME",
    "document": "11444777000161",
    "slug": "payoutme",
    "email": "payout@example.com",
    "name": "Bruna",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER_PAYOUT).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conta(client, headers, *, principal: bool, opening="2026-07-01") -> dict:
    acc = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 0,
            "opening_balance_is_known": True,
            "opening_date": opening,
        },
        headers=headers,
    ).json()
    if principal:
        client.post(f"/bank/accounts/{acc['id']}/set-primary", headers=headers)
    return acc


def test_sem_conta_principal_devolve_none(client: TestClient, headers, db: Session):
    """**`None` = "não há para onde mandar"**, e é valor de retorno, não exceção.

    `primary_account` devolve `None` também quando o tenant TEM contas e nenhuma é principal —
    arquivar a principal não elege sucessora em silêncio (Story 8.7 AC7).
    """
    _conta(client, headers, principal=False)
    assert (
        bank_payout.registra_payout(
            db,
            tenant_id="t1",
            actor="u1",
            payout_id="pay-1",
            amount_cents=500_00,
            posted_at=date(2026, 8, 9),
        )
        is None
    )


def test_escreve_movimento_positivo_conciliado(client: TestClient, headers, db: Session):
    """O crédito **entra** na conta do dono: valor POSITIVO, `source='payout'`, nasce `matched`."""
    acc = _conta(client, headers, principal=True)

    destino = bank_payout.registra_payout(
        db,
        tenant_id="t1",
        actor="u1",
        payout_id="pay-2",
        amount_cents=500_00,
        posted_at=date(2026, 8, 9),
    )

    assert destino.bank_account_id == acc["id"]
    assert destino.recusa_detalhe is None
    mov = db.get(BankTransaction, destino.bank_transaction_id)
    assert mov.amount_cents == 500_00          # POSITIVO — é entrada
    assert mov.source == SOURCE_PAYOUT
    assert mov.origin_id == "pay-2"
    assert mov.status == STATUS_MATCHED        # nasce conciliado: o e1p originou os dois lados


def test_data_anterior_a_abertura_vira_recusa_com_o_fato(client: TestClient, headers, db: Session):
    """O piso de data não explode: volta como FATO, para a Carteira moldurar.

    Sem isto, um 422 sobre `opening_date` — vocabulário do plano do banco — vazaria cru num botão
    do plano da plataforma.
    """
    _conta(client, headers, principal=True, opening="2026-08-20")

    destino = bank_payout.registra_payout(
        db,
        tenant_id="t1",
        actor="u1",
        payout_id="pay-3",
        amount_cents=500_00,
        posted_at=date(2026, 8, 9),
    )

    assert destino.bank_account_id is None
    assert "2026-08-20" in destino.recusa_detalhe
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v -k "conta_principal or movimento or abertura"`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.modules.bank.payout'`

- [ ] **Step 3: Implementar**

Criar `apps/api/app/modules/bank/payout.py`:

```python
"""A perna bancária do payout da Carteira (Epic 8, Onda 3) — o QUINTO chamador da Regra da Origem.

⚠️ **Este módulo é a implementação de um `Protocol` declarado em `wallet/service.py`, e NÃO importa
`app.modules.wallet`.** Ele recebe números e ids; o objeto que devolve é tipado do outro lado. É
isso que mantém `test_bank_nao_referencia_transaction` apertado — o gate diz, na própria docstring,
que quem precisar do símbolo *"atualiza este teste com justificativa escrita, nunca o apaga"*, e
**esta onda não precisa**. Um gate que já permite o que ninguém usa não avisa nada quando alguém
começar a usar.

A fiação (quem liga um no outro) mora em `app/main.py`, ao lado das duas travessias irmãs.

**O que este módulo NÃO faz:** não commita (contrato de `sync_origin_movement`), não escolhe conta
sozinho quando não há principal, e não formata frase de tela.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.modules.bank.models import SOURCE_PAYOUT
from app.modules.bank.origin import sync_origin_movement
from app.modules.bank.service import BankError, primary_account

_DESCRICAO = "Saque da Carteira e1p"


@dataclass(frozen=True)
class _Destino:
    """Estruturalmente igual a `wallet.service.DestinoDoPayout`, **de propósito**.

    Duplicar a forma é o preço de não importar o outro módulo, e é um preço baixo: são três campos
    sem comportamento. Importar o símbolo do outro lado custaria a direção de dependência que o
    §1.3b protege — e é a direção, não a dataclass, que impede o bug que originou o Epic 8.
    """

    bank_account_id: str | None = None
    bank_transaction_id: str | None = None
    recusa_detalhe: str | None = None


def registra_payout(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    payout_id: str,
    amount_cents: int,
    posted_at: date,
) -> _Destino | None:
    """Credita o saque na conta principal. **NÃO commita.**

    `None` ⇒ não há conta principal ativa. Não é erro: é ausência de destino, e quem transforma
    isso em 409 (com a frase) é a Carteira.

    `amount_cents` chega **positivo** — é entrada na conta do dono. Diferente de `payable`, que
    entra negativo. O sinal é responsabilidade de quem chama, e o `_validate_amount` do
    sincronizador recusa zero.
    """
    conta = primary_account(db)
    if conta is None:
        return None

    try:
        movimento = sync_origin_movement(
            db,
            tenant_id=tenant_id,
            actor=actor,
            source=SOURCE_PAYOUT,
            origin_id=payout_id,
            bank_account_id=conta.id,
            posted_at=posted_at,
            amount_cents=amount_cents,
            description=_DESCRICAO,
        )
    except BankError as e:
        # O caso conhecido é o piso de data (`posted_at <= opening_date`). Devolver o texto do
        # `bank` em vez de recopiar o predicado é deliberado: **duas cópias do mesmo predicado
        # divergem no dia em que só uma for corrigida** — a razão pela qual
        # `validate_posted_at_floor` foi extraída como função pública na Story 8.9.
        # Exceção que NÃO é `BankError` propaga e vira 500: erro de programação não se disfarça
        # de recusa de negócio.
        return _Destino(recusa_detalhe=str(e))

    return _Destino(bank_account_id=conta.id, bank_transaction_id=movimento.id)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Acrescentar a entrada na allowlist do sincronizador**

Em `apps/api/tests/test_bank_origin.py`, dentro de `_CHAMADORES_PERMITIDOS` (linha ~808), depois da entrada de `modules/investments/service.py`:

```python
    "modules/bank/payout.py": (
        "**Onda 3** — o payout da Carteira é o QUINTO chamador de produção da Regra da Origem, e "
        "o único que atravessa a fronteira entre o plano da PLATAFORMA e o plano do BANCO "
        "(design-mãe §1.2). Ele NÃO importa `wallet`: implementa um `Protocol` declarado lá e é "
        "ligado em `app/main.py`, como as duas travessias irmãs (8.17 AC6, 8.16 AC7/AC8). "
        "Escreve UMA perna, positiva (entrada), `origin_id = payout.id`, na MESMA transação do "
        "`Payout`. ⚠️ O ramo *'origem desliquidada → apaga'* é INALCANÇÁVEL aqui: não existe "
        "estorno de payout, e nenhum caminho leva `bank_account_id=None` para `source='payout'`."
    ),
```

- [ ] **Step 6: Acrescentar a asserção nova em `test_money_planes.py`**

No fim da seção da parte (b) de `apps/api/tests/test_money_planes.py`:

```python
def test_bank_payout_nao_importa_wallet_nem_cita_transaction():
    """**Onda 3, a asserção que impede o atalho óbvio.**

    O payout é o ponto de contato entre os planos 1 e 3, e §1.3b PERMITE `bank → wallet`. O atalho
    tentador é concreto: *"já que `bank/payout.py` registra o saque, ele podia ler as `Transaction`
    disponíveis e somar sozinho"*. Isso poria o cálculo do saldo da Carteira dentro do módulo do
    banco — a mistura exata que produziu o bug que originou o Epic 8.

    A onda foi construída para **não precisar**: o registrador recebe `amount_cents` pronto. Esta
    asserção é o que mantém a decisão depois que a memória de por que ela foi tomada se apagar.
    """
    caminho = BANK_DIR / "payout.py"
    assert caminho.exists(), "bank/payout.py sumiu — a Onda 3 foi revertida em silêncio?"

    texto = caminho.read_text(encoding="utf-8")
    tree = ast.parse(texto, filename=str(caminho))

    offenders = [f"import {m}" for m in _imported_modules(caminho) if "wallet" in m]
    offenders += [
        "símbolo Transaction"
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == "Transaction")
        or (isinstance(node, ast.Attribute) and node.attr == "Transaction")
    ]

    assert not offenders, (
        f"bank/payout.py passou a alcançar o plano da plataforma: {offenders}. O registrador "
        "recebe `amount_cents` PRONTO — se você precisa somar `Transaction` aqui, o que falta é "
        "um parâmetro no `Protocol` de `wallet/service.py`, não um import."
    )
```

- [ ] **Step 7: Rodar os dois gates**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_money_planes.py tests/test_bank_origin.py -v`
Expected: PASS. Nenhum gate existente foi afrouxado — `test_wallet_nao_importa_bank` e `test_bank_nao_referencia_transaction` continuam sem allowlist.

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/bank/payout.py apps/api/tests/
git commit -m "feat: a perna bancária do saque, sem cruzar a fronteira dos planos [Epic 8, Onda 3]"
```

---

## Task 4: A fiação e o fail-closed de boot

**Files:**
- Modify: `apps/api/app/main.py`
- Test: `apps/api/tests/test_payout_registrar.py`

**Interfaces:**
- Consumes: `wallet.service.register_payout_registrar`, `wallet.service.payout_registrar_registrado`, `bank.payout.registra_payout`
- Produces: `app.main.liga_o_registrador_de_payout()`, `app.main.verifica_fiacao_do_payout()`

- [ ] **Step 1: Escrever os testes que falham**

Acrescentar a `apps/api/tests/test_payout_registrar.py`:

```python
import ast
import pathlib

from app import main as app_main


def test_app_nao_sobe_sem_o_registrador_de_payout(monkeypatch):
    """**Um erro de fiação é condição de startup, não de request** (ratificação §C-5.2).

    A alternativa — deixar o request seguir sem registrador — é a Onda 3 **desligada em produção
    sem ninguém saber**: o payout volta ao comportamento pré-onda (marca `withdrawn` e pronto), o
    termo P4 reabre, e a divergência cresce sem explicação, contaminando exatamente a métrica que
    decide as Ondas 4 e 5.

    Espelho literal de `test_bank_contagem_dupla.py::test_app_nao_sobe_sem_o_probe_de_contagem_dupla`.
    """
    monkeypatch.setattr(wallet_service, "_payout_registrar", None)
    with pytest.raises(RuntimeError, match="registrador de payout"):
        app_main.verifica_fiacao_do_payout()


def test_a_verificacao_do_payout_e_chamada_no_nivel_do_modulo():
    """Teste **ESTRUTURAL**: um fail-closed que ninguém invoca é um comentário.

    Mutante a matar: apagar a chamada de `verifica_fiacao_do_payout()` do corpo de `app/main.py`.
    Nenhum teste de comportamento pegaria — a app continuaria subindo e a guarda viraria função
    morta. Mesmo par de testes de `test_a_guarda_de_boot_e_chamada_no_nivel_do_modulo`.
    """
    fonte = pathlib.Path(app_main.__file__).read_text(encoding="utf-8")
    tree = ast.parse(fonte)
    chamadas = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "verifica_fiacao_do_payout" in chamadas
    assert "liga_o_registrador_de_payout" in chamadas
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v -k fiacao or nao_sobe`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute 'verifica_fiacao_do_payout'`

- [ ] **Step 3: Implementar a fiação**

Em `apps/api/app/main.py`, acrescentar o import no topo (junto dos outros de módulo):

```python
from app.modules.bank import payout as bank_payout
from app.modules.wallet import service as wallet_service
```

E, **depois** do bloco `probe_termos_do_gate` (no fim das travessias existentes):

```python
# ── A composição do ponto de contato entre os planos (Epic 8, Onda 3) ────────────────────────
#
# ⚠️ **Terceira aplicação do mesmo padrão, e a primeira que atravessa a fronteira dos PLANOS de
# dinheiro** (design-mãe §1.2: o payout é o único write que a cruza). As duas irmãs acima ligam
# `bank` a módulos de negócio; esta liga a Carteira ao banco — a direção em que o Epic 8 nasceu de
# um bug.
#
# Aqui a declaração é do lado da CARTEIRA (`wallet/service.RegistradorDePayout`) e a implementação
# do lado do BANCO (`bank/payout.registra_payout`). Direção final: `main → wallet`, `main → bank`,
# e **nada** entre os dois. Os dois gates (`test_wallet_nao_importa_bank`,
# `test_bank_nao_referencia_transaction`) continuam apertados **e sem allowlist** — a dependência
# não existe, em vez de existir com permissão.
def liga_o_registrador_de_payout() -> None:
    wallet_service.register_payout_registrar(bank_payout.registra_payout)


def verifica_fiacao_do_payout() -> None:
    """**FAIL-CLOSED NO BOOT: a aplicação não sobe sem o registrador de payout.**

    *"Um erro de fiação é condição de startup, não de request."* Sem esta guarda, o modo de falha é
    silencioso e caro: o saque voltaria a ser troca de status sem perna bancária, o termo **P4** da
    pré-condição do gate reabriria, e `|divergencia_cents|` — a métrica que decide se as Ondas 4
    (import OFX) e 5 (matcher) valem o custo — voltaria a medir a própria incompletude do sistema
    sem que ninguém percebesse.

    ⚠️ **Não transforme isto num `warning`.** O par de testes que amarra o comportamento é
    `test_payout_registrar.py::test_app_nao_sobe_sem_o_registrador_de_payout` **e** o teste
    ESTRUTURAL que prova que esta função é chamada no nível do módulo — apagar a chamada abaixo
    reprova, porque um fail-closed que ninguém invoca é um comentário.
    """
    if not wallet_service.payout_registrar_registrado():
        raise RuntimeError(
            "O registrador de payout não foi ligado: `wallet.service.register_payout_registrar` "
            "não recebeu implementação. A aplicação NÃO sobe sem ele — sem essa ligação o saque "
            "da Carteira volta a não escrever movimento bancário nenhum, reabrindo o termo P4 do "
            "gate do Epic 8 em silêncio. Verifique `liga_o_registrador_de_payout` em app/main.py."
        )


liga_o_registrador_de_payout()
verifica_fiacao_do_payout()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_registrar.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/main.py apps/api/tests/test_payout_registrar.py
git commit -m "feat: a fiação do payout, fail-closed no boot [Epic 8, Onda 3]"
```

---

## Task 5: `request_payout` reescrito — a orquestração

**Files:**
- Modify: `apps/api/app/modules/wallet/service.py:228-244`, `apps/api/app/modules/wallet/schemas.py:69-71`, `apps/api/app/modules/wallet/router.py:76-81`
- Test: `apps/api/tests/test_wallet_payout.py`

**Interfaces:**
- Consumes: `DestinoDoPayout`, `_payout_registrar`, `wallet.models.Payout`, `app.db.base._uuid`, `settings.service.hoje_do_tenant`
- Produces: `request_payout(db, *, tenant_id, actor) -> dict` com chaves `amount_cents`, `transactions`, `payout_id`

- [ ] **Step 1: Escrever os testes que falham**

Criar `apps/api/tests/test_wallet_payout.py`:

```python
"""Onda 3 — o comportamento do saque. O contrato vive em `test_payout_registrar.py`."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.wallet.models import STATUS_WITHDRAWN, Payout, Transaction

REGISTER = {
    "legal_name": "Saque ME",
    "document": "11444777000161",
    "slug": "saqueme",
    "email": "saque@example.com",
    "name": "Bruna",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _conta_principal(client, headers, opening="2026-01-01") -> dict:
    acc = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 0,
            "opening_balance_is_known": True,
            "opening_date": opening,
        },
        headers=headers,
    ).json()
    client.post(f"/bank/accounts/{acc['id']}/set-primary", headers=headers)
    return acc


def _venda(client, headers, gross=1_000_00) -> dict:
    return client.post(
        "/wallet/transactions",
        json={"kind": "service", "method": "pix", "gross_cents": gross, "description": "Consulta"},
        headers=headers,
    ).json()


def test_saque_credita_a_conta_e_liga_as_vendas(client: TestClient, headers, db: Session):
    """O caminho feliz: um `Payout`, um movimento, e cada venda sabendo a qual saque pertence."""
    acc = _conta_principal(client, headers)
    _venda(client, headers)

    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transactions"] == 1
    assert body["payout_id"]

    payout = db.get(Payout, body["payout_id"])
    assert payout.amount_cents == body["amount_cents"]
    assert payout.bank_account_id == acc["id"]
    assert payout.bank_transaction_id  # NOT NULL, e é a invariante da onda

    txs = list(db.scalars(select(Transaction)).all())
    assert all(t.status == STATUS_WITHDRAWN and t.payout_id == payout.id for t in txs)


def test_sem_conta_principal_recusa_e_nada_muda(client: TestClient, headers, db: Session):
    """**A decisão central da onda.** Recusar é legítimo aqui porque quem ORIGINA o payout é o e1p
    — ele ainda não aconteceu. O resgate bruto da 2b-ii não podia ser recusado porque já tinha
    acontecido no banco.

    E o rollback tem de ser total: uma venda marcada `withdrawn` sem saque registrado seria dinheiro
    desaparecido da Carteira sem contrapartida em lugar nenhum.
    """
    _venda(client, headers)  # sem conta principal

    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 409
    assert "conta" in resp.json()["detail"].lower()

    assert db.scalar(select(Transaction)).status != STATUS_WITHDRAWN
    assert db.scalars(select(Payout)).first() is None


def test_sem_saldo_recusa(client: TestClient, headers):
    _conta_principal(client, headers)
    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 409
    assert "saldo" in resp.json()["detail"].lower()


def test_conta_aberta_depois_do_saque_recusa_com_a_data(client: TestClient, headers, db: Session):
    """O piso de data vira 409 com o fato dentro — não um 422 cru sobre `opening_date`."""
    _conta_principal(client, headers, opening="2099-01-01")
    _venda(client, headers)

    resp = client.post("/wallet/payout", headers=headers)
    assert resp.status_code == 409
    assert "2099-01-01" in resp.json()["detail"]
    assert db.scalars(select(Payout)).first() is None


def test_audit_aponta_para_o_payout_e_nao_para_o_valor(client: TestClient, headers, db: Session):
    """`target=str(total)` era o VALOR — trilha apontando para lugar nenhum (a família MNT-001)."""
    from app.core.audit import AuditEntry

    _conta_principal(client, headers)
    _venda(client, headers)
    payout_id = client.post("/wallet/payout", headers=headers).json()["payout_id"]

    log = db.scalars(select(AuditEntry).where(AuditEntry.action == "wallet.payout")).first()
    assert log.target == payout_id
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_wallet_payout.py -v`
Expected: FAIL — `KeyError: 'payout_id'` no primeiro teste, e 500 (não 409) nos de recusa.

- [ ] **Step 3: Reescrever `request_payout`**

Substituir `def request_payout(...)` inteiro em `apps/api/app/modules/wallet/service.py`:

```python
def request_payout(db: Session, *, tenant_id: str, actor: str) -> dict:
    """Saca todo o saldo disponível **e escreve a perna bancária, na MESMA transação** (Onda 3).

    Antes desta onda isto marcava `withdrawn` e commitava — sem registro do saque e sem movimento
    bancário. Era o termo **P4** da pré-condição do gate do Epic 8, e o último dos quatro aberto.

    **A ordem — destino ANTES de qualquer escrita — não é exigência de correção** (tudo está na
    mesma transação, e um `raise` desfaz o conjunto em qualquer ordem). É exigência de **leitura**:
    o código deve deixar óbvio que nada na Carteira muda antes de o destino estar garantido. Ordem
    que só está certa porque existe rollback é ordem que a próxima pessoa reordena sem perceber.

    ⚠️ **O id é gerado em Python antes do `INSERT`**, e é isso que sustenta o `NOT NULL` de
    `Payout.bank_transaction_id`. Funciona porque `bank_transactions.origin_id` **não é FK** — é
    coluna genérica sob índice único parcial, compartilhada pelas cinco origens de sistema.

    FOR UPDATE trava as linhas contra saque em dobro concorrente (real no Postgres, no-op no
    SQLite dos testes).
    """
    from app.db.base import _uuid
    from app.modules.settings.service import hoje_do_tenant

    txs = list(
        db.scalars(
            select(Transaction).where(Transaction.status == STATUS_AVAILABLE).with_for_update()
        ).all()
    )
    total = sum(t.net_cents for t in txs)
    if total <= 0:
        raise WalletError("Não há saldo disponível para saque.", 409)

    if _payout_registrar is None:  # pragma: no cover — `verifica_fiacao_do_payout` barra no boot
        raise WalletError("Saque indisponível: registrador não configurado.", 503)

    payout_id = _uuid()
    paid_on = hoje_do_tenant(db)

    destino = _payout_registrar(
        db,
        tenant_id=tenant_id,
        actor=actor,
        payout_id=payout_id,
        amount_cents=total,  # POSITIVO — é entrada na conta do dono
        posted_at=paid_on,
    )
    if destino is None:
        raise WalletError(
            "Escolha para qual conta bancária o dinheiro vai antes de sacar. "
            "Defina sua conta principal em Contas & Saldos.",
            409,
        )
    if destino.recusa_detalhe is not None:
        raise WalletError(
            "Não foi possível registrar o saque na sua conta bancária. "
            f"{destino.recusa_detalhe}",
            409,
        )

    payout = Payout(
        id=payout_id,
        tenant_id=tenant_id,
        amount_cents=total,
        paid_on=paid_on,
        bank_account_id=destino.bank_account_id,
        bank_transaction_id=destino.bank_transaction_id,
        actor=actor,
    )
    db.add(payout)
    db.flush()

    for t in txs:
        t.status = STATUS_WITHDRAWN
        t.payout_id = payout_id

    audit.record(db, tenant_id=tenant_id, actor=actor, action="wallet.payout", target=payout_id)
    db.commit()
    return {"amount_cents": total, "transactions": len(txs), "payout_id": payout_id}
```

Acrescentar `Payout` ao import de models no topo do arquivo:

```python
from app.modules.wallet.models import (  # ajuste a lista existente
    ...,
    Payout,
)
```

- [ ] **Step 4: Acrescentar `payout_id` ao schema de saída**

Em `apps/api/app/modules/wallet/schemas.py:69-71`:

```python
class PayoutResult(BaseModel):
    amount_cents: int
    transactions: int
    payout_id: str
```

- [ ] **Step 5: Tratar o `WalletError` na rota (hoje ela NÃO trata)**

Em `apps/api/app/modules/wallet/router.py:76-81`, substituir o handler:

```python
@router.post("/payout", response_model=PayoutResult)
def payout(
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayoutResult:
    # ⚠️ O `try` é NOVO (Onda 3). Antes desta onda `request_payout` não levantava `WalletError`, e
    # a rota não tratava nada — os dois 409 desta onda virariam **500** sem isto, e o dono veria
    # "erro inesperado" no lugar de "escolha sua conta principal".
    try:
        result = service.request_payout(db, tenant_id=user.tenant_id, actor=user.user_id)
    except service.WalletError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    return PayoutResult(**result)
```

- [ ] **Step 6: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_wallet_payout.py tests/test_wallet.py -v`
Expected: PASS. `test_wallet.py` (a suíte antiga da Carteira) pode ter um teste que espera payout sem conta bancária — se falhar, **atualize-o** com a justificativa (R-1 da spec: é mudança observável e deliberada), não o apague.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/wallet/ apps/api/tests/test_wallet_payout.py
git commit -m "feat: o saque escreve a perna bancária e o termo P4 zera [Epic 8, Onda 3]"
```

---

## Task 6: `GET /wallet/payouts` — o histórico

**Files:**
- Modify: `apps/api/app/modules/wallet/service.py`, `apps/api/app/modules/wallet/schemas.py`, `apps/api/app/modules/wallet/router.py`
- Test: `apps/api/tests/test_wallet_payout.py`

**Interfaces:**
- Produces: `wallet.service.list_payouts(db, *, limit=100, offset=0) -> list[Payout]`; schema `PayoutOut` com `id, amount_cents, paid_on, bank_account_id, bank_account_name, bank_transaction_id`

⚠️ `bank_account_name` **não** é resolvido pelo módulo `wallet` (ele não pode ler `bank`). O front já carrega a lista de contas para outras telas e resolve o nome pelo id — mesmo padrão de `accountLabel`/`costCenterLabel` em `FinanceiroPage.tsx:70-77`. O schema **não** tem `bank_account_name`; ele existe só no front.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `apps/api/tests/test_wallet_payout.py`:

```python
def test_historico_lista_do_mais_novo_para_o_mais_velho(client: TestClient, headers):
    _conta_principal(client, headers)
    _venda(client, headers, gross=1_000_00)
    primeiro = client.post("/wallet/payout", headers=headers).json()["payout_id"]
    _venda(client, headers, gross=2_000_00)
    segundo = client.post("/wallet/payout", headers=headers).json()["payout_id"]

    resp = client.get("/wallet/payouts", headers=headers)
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert ids == [segundo, primeiro]
    assert all(p["bank_transaction_id"] for p in resp.json())
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_wallet_payout.py::test_historico_lista_do_mais_novo_para_o_mais_velho -v`
Expected: FAIL — 404 (rota inexistente)

- [ ] **Step 3: Implementar**

Em `wallet/service.py`, depois de `request_payout`:

```python
def list_payouts(db: Session, *, limit: int = 100, offset: int = 0) -> list[Payout]:
    """Os saques do tenant, do mais novo para o mais velho. Mesmo teto de `list_transactions`."""
    limit = max(1, min(limit, 500))
    stmt = (
        select(Payout)
        .order_by(Payout.created_at.desc())
        .limit(limit)
        .offset(max(0, offset))
    )
    return list(db.scalars(stmt).all())
```

Em `wallet/schemas.py`, depois de `PayoutResult`:

```python
class PayoutOut(BaseModel):
    """Um saque, como o dono o vê. **Sem `*_origem`:** não é saldo, é valor de um evento."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    amount_cents: int
    paid_on: date
    bank_account_id: str
    bank_transaction_id: str
```

(Se `ConfigDict`/`date` ainda não estiverem importados no arquivo, acrescente `from datetime import date` e `from pydantic import ConfigDict`.)

Em `wallet/router.py`, depois da rota de payout:

```python
@router.get("/payouts", response_model=list[PayoutOut])
def payouts(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[PayoutOut]:
    return [
        PayoutOut.model_validate(p) for p in service.list_payouts(db, limit=limit, offset=offset)
    ]
```

E acrescente `PayoutOut` ao import de schemas no topo do router.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_wallet_payout.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/modules/wallet/
git commit -m "feat: o histórico de saques passa a existir [Epic 8, Onda 3]"
```

---

## Task 7: `rls_e2e` — Postgres real e a migration exercitada

**Files:**
- Create: `apps/api/tests/test_payout_rls.py`

**Interfaces:**
- Consumes: tudo das Tasks 1-6

⚠️ **Por que este teste não é opcional.** A suíte unitária roda em SQLite, que **não tem RLS** e não exercita a `0077`. Os `rls_e2e` sobem um Postgres real via testcontainers e rodam `alembic upgrade head` como o papel não-superusuário `e1p_app` — o mesmo caminho da produção. Custo medido nesta máquina: ~4s.

- [ ] **Step 1: Copiar a estrutura de um `rls_e2e` existente**

Leia `apps/api/tests/test_receipts_rls.py` inteiro antes de escrever. Ele é o modelo canônico: fixtures de testcontainer, criação dos dois tenants, o marker.

- [ ] **Step 2: Escrever o teste**

Criar `apps/api/tests/test_payout_rls.py`, seguindo a estrutura lida no passo 1:

```python
"""Onda 3 sob Postgres REAL — a migration 0077 e o isolamento entre tenants.

⚠️ **O que só este teste pega.** O SQLite da suíte unitária não tem RLS: um vazamento cross-tenant
no histórico de saques passaria verde lá. E a `0077` só é exercitada de verdade aqui, rodando como
o papel não-superusuário `e1p_app` — o mesmo caminho da produção.
"""
import pytest

pytestmark = pytest.mark.rls_e2e


def test_saque_de_um_tenant_nao_vaza_para_o_outro(...):
    """João saca; Maria não vê o saque dele no histórico nem o crédito no extrato dela.

    ⚠️ **Semeie a conta bancária principal dos DOIS tenants.** Sem a conta de Maria, o teste
    passaria **verde por vacuidade** — ela não teria histórico nenhum para vazar, e o vetor que o
    teste existe para exercitar nunca seria exercitado. Foi exatamente essa a armadilha do
    `rls_e2e` de PII da Onda 2b-ii.
    """
    # 1. registrar tenant A e tenant B, cada um com conta principal
    # 2. venda + payout em A
    # 3. venda + payout em B
    # 4. GET /wallet/payouts com o token de A → só o payout de A
    # 5. GET /bank/transactions com o token de A → só o crédito de A
    # 6. assert que os ids não se cruzam nos dois sentidos
```

**Preencha os passos 1-6 com o código concreto**, seguindo exatamente as helpers de `test_receipts_rls.py`. A docstring e a ordem acima são o contrato; o corpo é mecânico.

- [ ] **Step 3: Rodar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_payout_rls.py -v -m rls_e2e`
Expected: PASS. Se o Docker não estiver de pé, o teste é skipado — **isso não conta como passar**. Suba o Docker e rode de novo.

- [ ] **Step 4: Commit**

```bash
git add apps/api/tests/test_payout_rls.py
git commit -m "test: o payout sob Postgres real — 0077 e isolamento [Epic 8, Onda 3]"
```

---

## Task 8: O card do Cockpit

**Files:**
- Modify: `apps/api/app/modules/cockpit/service.py:127-137`, `apps/api/app/modules/cockpit/schemas.py:41-47`, `apps/web/src/features/cockpit/CockpitPage.tsx`
- Test: `apps/api/tests/test_cockpit.py`, `apps/web/src/features/cockpit/CockpitPage.test.tsx`

**Interfaces:**
- Consumes: `bank.service.derived_balances_as_of`, `bank.service.list_accounts`, `core.money_planes.ORIGEM_BANCO/ORIGEM_INDISPONIVEL`
- Produces: `FinanceSummary.saldo_em_conta_cents: int | None`, `FinanceSummary.saldo_em_conta_origem: str`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `apps/api/tests/test_cockpit.py`:

```python
def test_cockpit_expoe_saldo_em_conta_com_procedencia(client: TestClient, headers, db: Session):
    """§1.3c: todo campo de SALDO declara de qual plano vem. `net_revenue` não é saldo — é
    faturamento — e por isso **não** ganha `_origem` (§6.5 diz que aquele número está certo)."""
    acc = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 700_00,
            "opening_balance_is_known": True,
            "opening_date": "2026-01-01",
        },
        headers=headers,
    ).json()
    assert acc["id"]

    finance = client.get("/cockpit/summary", headers=headers).json()["finance"]
    assert finance["saldo_em_conta_cents"] == 700_00
    assert finance["saldo_em_conta_origem"] == "banco"
    assert "net_revenue_origem" not in finance


def test_sem_conta_o_saldo_em_conta_e_none_e_nao_zero(client: TestClient, headers):
    """`None` ≠ zero. Zero afirmaria "você não tem nada no banco" — falso e indistinguível de um
    saldo genuinamente zerado. Mesmo princípio do principal `None` da Onda 2b-ii."""
    finance = client.get("/cockpit/summary", headers=headers).json()["finance"]
    assert finance["saldo_em_conta_cents"] is None
    assert finance["saldo_em_conta_origem"] == "indisponivel"


def test_saldo_de_abertura_desconhecido_derruba_a_procedencia(client: TestClient, headers):
    """Story 8.21: o NÚMERO continua existindo; quem diz "não sei" é a procedência."""
    client.post(
        "/bank/accounts",
        json={
            "name": "Conta sem saldo declarado",
            "kind": "checking",
            "opening_balance_cents": 0,
            "opening_balance_is_known": False,
            "opening_date": "2026-01-01",
        },
        headers=headers,
    )
    finance = client.get("/cockpit/summary", headers=headers).json()["finance"]
    assert finance["saldo_em_conta_cents"] == 0        # o número existe
    assert finance["saldo_em_conta_origem"] == "indisponivel"  # a afirmação é suprimida
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_cockpit.py -v -k saldo_em_conta or procedencia`
Expected: FAIL — `KeyError: 'saldo_em_conta_cents'`

- [ ] **Step 3: Implementar o schema**

Em `apps/api/app/modules/cockpit/schemas.py`:

```python
class FinanceSummary(BaseModel):
    """Faturamento (plano 1) + custos + **saldo em conta** (plano 3), nunca somados.

    ⚠️ **`net_revenue_cents` NÃO tem `_origem`, e a ausência é deliberada.** §1.3c exige
    procedência em todo campo de **saldo**; faturamento não é saldo, e o design-mãe §6.5 diz
    explicitamente que aquele número está correto e não muda. Pendurar procedência nele aplicaria
    a regra fora do alvo e transformaria um invariante mecânico em ritual.
    """

    available: bool = False
    net_revenue_cents: int | None = None
    monthly_costs_cents: int | None = None
    signed_contracts: int | None = None
    # Plano 3 (banco). `None` = nenhuma conta cadastrada — NÃO zero (zero afirmaria "não há nada
    # no banco"). A soma é o recorte `TOTAL_EM_CONTAS_LABEL`: todas as contas ativas, aplicação
    # incluída. **Nunca somado com `net_revenue_cents` na tela** (Regra dos Planos §1.3c).
    saldo_em_conta_cents: int | None = None
    saldo_em_conta_origem: str = ORIGEM_INDISPONIVEL
```

com `from app.core.money_planes import ORIGEM_INDISPONIVEL` no topo.

- [ ] **Step 4: Implementar o service**

Em `apps/api/app/modules/cockpit/service.py`, acrescentar ao topo:

```python
from app.core.money_planes import ORIGEM_BANCO, ORIGEM_INDISPONIVEL
from app.modules.bank import service as bank_service
```

e substituir `finance_summary`:

```python
def finance_summary(db: Session) -> dict:
    """Faturamento líquido (Carteira, plano 1) + custos do mês + saldo em conta (banco, plano 3).

    ⚠️ **Os dois planos convivem no mesmo schema e NUNCA no mesmo número.** A tela mostra as duas
    parcelas rotuladas, lado a lado, sem total único (design-mãe §6.5, Regra dos Planos §1.3c).
    Somar "na plataforma" com "em conta" num card só é a mistura que originou o Epic 8.
    """
    w = wallet_service.wallet_summary(db)
    net_revenue = w["available_cents"] + w["pending_cents"] + w["withdrawn_cents"]

    contas = bank_service.list_accounts(db)
    if not contas:
        saldo_em_conta, origem = None, ORIGEM_INDISPONIVEL
    else:
        saldo_em_conta = sum(bank_service.derived_balances_as_of(db).values())
        # Basta UMA conta sem saldo de abertura declarado para o total deixar de ser afirmável
        # (Story 8.21). O número continua exposto — suprimir a afirmação, nunca o número.
        origem = (
            ORIGEM_BANCO
            if all(c.opening_balance_is_known for c in contas)
            else ORIGEM_INDISPONIVEL
        )

    return {
        "available": True,
        "net_revenue_cents": net_revenue,
        "monthly_costs_cents": payables_service.monthly_costs(db),
        "signed_contracts": None,  # módulo de Contratos (Fase 3)
        "saldo_em_conta_cents": saldo_em_conta,
        "saldo_em_conta_origem": origem,
    }
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_cockpit.py -v`
Expected: PASS

- [ ] **Step 6: O card no front**

Em `apps/web/src/features/cockpit/CockpitPage.tsx`, ao lado do card de faturamento, acrescentar — **usando a constante, nunca uma string literal**:

```tsx
import { TOTAL_EM_CONTAS_LABEL } from "../financeiro/contas";

// ...

{/* Plano 3 (banco), ao lado do plano 1 (plataforma) — rotulados, NUNCA somados num card só.
    O rótulo vem da constante compartilhada com Contas & Saldos: inventar um sinônimo aqui
    recriaria a colisão D-6/UX-001 numa terceira tela. E `"no banco"` é proibido fora da Projeção. */}
<Stat
  label={TOTAL_EM_CONTAS_LABEL}
  value={
    summary.finance?.saldo_em_conta_cents != null
      ? brl(summary.finance.saldo_em_conta_cents)
      : "—"
  }
  tone="neutral"
/>
```

Ajuste `defaultSummary` (linha 13) para incluir `saldo_em_conta_cents: null, saldo_em_conta_origem: "indisponivel"`.

- [ ] **Step 7: Teste do front**

Em `apps/web/src/features/cockpit/CockpitPage.test.tsx`:

```tsx
it("mostra o saldo em conta ao lado do faturamento, sem somar os dois", async () => {
  // mock: finance.net_revenue_cents = 300_00, saldo_em_conta_cents = 700_00
  render(<CockpitPage />);
  expect(await screen.findByText("R$ 700,00")).toBeInTheDocument();
  expect(screen.getByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument();
  // o total somado (R$ 1.000,00) NÃO pode aparecer em lugar nenhum
  expect(screen.queryByText("R$ 1.000,00")).toBeNull();
});
```

- [ ] **Step 8: Rodar e commitar**

Run: `cd apps/web && npx vitest run src/features/cockpit/CockpitPage.test.tsx`
Expected: PASS

```bash
git add apps/api/app/modules/cockpit/ apps/api/tests/test_cockpit.py apps/web/src/features/cockpit/
git commit -m "feat: o Cockpit mostra os dois planos lado a lado, sem somar [Epic 8, Onda 3]"
```

---

## Task 9: A Carteira — o 409 com rosto e o histórico

**Files:**
- Create: `apps/web/src/features/financeiro/PayoutHistory.tsx`, `apps/web/src/features/financeiro/PayoutHistory.test.tsx`
- Modify: `apps/web/src/features/financeiro/FinanceiroPage.tsx:85-88`

**Interfaces:**
- Consumes: `GET /wallet/payouts` (Task 6), `GET /bank/accounts` (para resolver o nome da conta)

- [ ] **Step 1: Escrever o teste que falha**

Criar `apps/web/src/features/financeiro/PayoutHistory.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayoutHistory } from "./PayoutHistory";

const SAQUES = [
  { id: "p1", amount_cents: 300_000, paid_on: "2026-08-09", bank_account_id: "a1", bank_transaction_id: "b1" },
];
const CONTAS = { a1: "Itaú PJ" };

describe("PayoutHistory", () => {
  it("mostra valor, data e conta de destino", () => {
    render(<PayoutHistory payouts={SAQUES} accountNames={CONTAS} />);
    expect(screen.getByText("R$ 3.000,00")).toBeInTheDocument();
    expect(screen.getByText(/Itaú PJ/)).toBeInTheDocument();
  });

  it("NÃO usa <table> — a lição de 360px da Onda 2b-ii", () => {
    // Em 360px uma tabela de 3 colunas não cabe, e a saída não é rolar melhor: é não precisar.
    // O extrato da 2b-ii mostrava "R$ 3." no lugar de "R$ 3.000,00" com o overflow-x CORRETO.
    const { container } = render(<PayoutHistory payouts={SAQUES} accountNames={CONTAS} />);
    expect(container.querySelector("table")).toBeNull();
    expect(container.querySelector("ul")).not.toBeNull();
  });

  it("conta sem nome resolvido não vira 'undefined' na tela", () => {
    render(<PayoutHistory payouts={SAQUES} accountNames={{}} />);
    expect(screen.queryByText(/undefined/)).toBeNull();
  });
});
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `cd apps/web && npx vitest run src/features/financeiro/PayoutHistory.test.tsx`
Expected: FAIL — módulo não encontrado

- [ ] **Step 3: Implementar o componente**

Criar `apps/web/src/features/financeiro/PayoutHistory.tsx`:

```tsx
import { formatDay } from "../../lib/datetime";

// Mesmo padrão de toda página do app (`AgendaPage`, `CobrancasPage`, `EstoquePage`, `CockpitPage`
// …): cada uma define o seu. **Não** importe o `brl` exportado por `FinanceiroPage.tsx` — ela
// importa este componente, e o ciclo quebraria o build. Unificar os ~8 `brl` do repo num helper
// compartilhado é refactor legítimo, e não é desta onda.
const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export type Payout = {
  id: string;
  amount_cents: number;
  paid_on: string;
  bank_account_id: string;
  bank_transaction_id: string;
};

/**
 * Os saques da Carteira. **Lista, nunca tabela — e isso é normativo, não estético.**
 *
 * A lição medida na Onda 2b-ii: em 360px uma tabela de 3 colunas não cabe, e a saída não é fazer
 * a rolagem funcionar melhor, é não precisar dela. O extrato daquela onda nasceu `<table>` com
 * `min-w-[20rem]` dentro de `overflow-x-auto` — o `overflow-x` estava CERTO, o `flex-wrap` estava
 * CERTO, e a tela mostrava `R$ 3.` no lugar de `R$ 3.000,00`. Nenhuma asserção de classe CSS pega
 * isso; só medir com `boundingBox` pega.
 *
 * Forma: data e conta empilhadas à esquerda num bloco `min-w-0`; valor à direita com
 * `whitespace-nowrap`.
 */
export function PayoutHistory({
  payouts,
  accountNames,
}: {
  payouts: Payout[];
  accountNames: Record<string, string>;
}) {
  if (payouts.length === 0) {
    return (
      <p className="p-8 text-center text-sm text-neutral-400">
        Nenhum saque ainda. O que você sacar aparece aqui e no extrato da sua conta.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-neutral-100">
      {payouts.map((p) => (
        <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            {/* `formatDay` de `lib/datetime`, NUNCA `new Date(...)`: desde o PR #78 o sistema
                inteiro vive no fuso do tenant, e `new Date("2026-08-09")` é interpretado como
                UTC — o saque do dia 9 apareceria como dia 8 para quem está em GMT-3. UTC cru é
                regressão, não detalhe. */}
            <p className="truncate text-sm text-neutral-800">{formatDay(p.paid_on)}</p>
            <p className="truncate text-xs text-neutral-400">
              {accountNames[p.bank_account_id] ?? "Conta removida"}
            </p>
          </div>
          <span className="whitespace-nowrap text-sm font-semibold text-neutral-800">
            {brl(p.amount_cents)}
          </span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd apps/web && npx vitest run src/features/financeiro/PayoutHistory.test.tsx`
Expected: PASS (3 testes)

- [ ] **Step 5: Ligar na `FinanceiroPage` e tratar o 409**

Em `apps/web/src/features/financeiro/FinanceiroPage.tsx`, substituir `payout()`:

```tsx
  const [payoutErro, setPayoutErro] = useState<string | null>(null);

  async function payout() {
    if (!confirm("Sacar todo o saldo disponível para sua conta bancária?")) return;
    setPayoutErro(null);
    try {
      await api.post("/wallet/payout");
    } catch (e: any) {
      // ⚠️ Antes da Onda 3 este `catch` NÃO existia — `request_payout` nunca recusava. Os dois 409
      // da onda (sem conta principal; conta aberta depois da data do saque) cairiam numa promise
      // rejeitada e o botão simplesmente não faria nada.
      setPayoutErro(e?.response?.data?.detail ?? "Não foi possível sacar agora.");
      return;
    }
    load();
  }
```

e, logo abaixo do botão "Sacar":

```tsx
      {payoutErro && (
        <div className="rounded-2xl bg-amber-50 p-4 text-sm text-amber-900">
          <p>{payoutErro}</p>
          <Link to="/financeiro/contas" className="mt-2 inline-block font-semibold underline">
            Ir para Contas &amp; Saldos
          </Link>
        </div>
      )}
```

E, no fim da página, a seção do histórico — carregando `GET /wallet/payouts` e `GET /bank/accounts` no `load()` existente e passando `accountNames` montado como `Object.fromEntries(contas.map(c => [c.id, c.name]))` (mesmo padrão de `accountLabel`, linha 70).

- [ ] **Step 6: Rodar a suíte do front**

Run: `cd apps/web && npx vitest run src/features/financeiro`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/financeiro/
git commit -m "feat: a Carteira nomeia a recusa e mostra o histórico de saques [Epic 8, Onda 3]"
```

---

## Task 10: Aceite em 360px, suíte completa e a entrada no CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`
- Create: screenshot do aceite (na raiz, como `onda-3-payout-360px.png`)

- [ ] **Step 1: Medir em ~360px, sem backend**

Suba só o Vite (`cd apps/web && npm run dev`) e use Playwright com `page.route("**/api/**")` para servir os mocks — o método que a 2b-ii validou (memória `feedback_aceite_360px_sem_backend`). Meça, **não assuma**:

```js
await page.setViewportSize({ width: 360, height: 800 });
// 1. nenhum valor monetário cortado: o boundingBox do <span> do valor cabe no viewport
// 2. document.scrollWidth — anote o número
```

**Anote os dois números no artefato.** ⚠️ Você vai encontrar `document.scrollWidth ≈ 375` (15px de estouro): isso é **pré-existente**, causado pelo `ChevronDown` em `app/AppShell.tsx:209`, medido e registrado na Onda 2b-ii. **Não corrija aqui** — misturar correção de defeito existente com regra nova no mesmo diff tira do gate a capacidade de julgar qual mudança quebrou o quê. Confirme que o número é o mesmo **com e sem** o histórico na tela; se subir, aí sim é desta onda.

- [ ] **Step 2: Rodar a suíte inteira**

Run: `cd apps/api && .venv/Scripts/python -m pytest -q` (background, ~10 min — não fique em polling)
Run: `cd apps/web && npx vitest run`
Run: `cd apps/api && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m mypy app`

⚠️ **Não use `bash scripts/check.sh`** — ele resolve `ruff`/`python` do PATH (que pode não ser o do venv) e **mascara falha de frontend** com `|| true` no vitest. Dívida conhecida; rode as etapas individualmente.

- [ ] **Step 3: Escrever a entrada no CLAUDE.md**

Acrescentar depois da seção "Onda 2b-ii", **escrita a partir do código que subiu, não do que este plano pretendia** (§5, passo 4 — é AC obrigatório, não documentação opcional):

```markdown
### Onda 3 — o payout fecha o circuito (o termo P4 zera)

> Spec: `docs/superpowers/specs/2026-08-09-onda-3-payout-circuito-design.md` ·
> Plano: `docs/superpowers/plans/2026-08-09-onda-3-payout-circuito.md`

- [x] **O saque virou FATO.** ... (o que passou a existir)
- [x] **O ponto de contato entre os planos NÃO é o barramento** — e por quê. ...
- ⚠️ **MUDANÇA OBSERVÁVEL DE COMPORTAMENTO (R-1):** sacar sem conta principal definida agora
  RECUSA (409). ...
- [x] **O aceite em 360px foi medido** — `document.scrollWidth` = ___ (o estouro de 15px do
  `AppShell` permanece, pré-existente).
- **Dívida:** ...
```

**Inclua obrigatoriamente:** (a) que P4 zerou e o que isso destrava; (b) que a leitura do gate continua bloqueada por **dado**, não por código; (c) R-1 em linha própria; (d) a dívida que sobrou. **Remova daqui** qualquer dívida que esta onda tenha fechado.

- [ ] **Step 4: Commit final**

```bash
git add CLAUDE.md onda-3-payout-360px.png
git commit -m "docs: registra a Onda 3 no CLAUDE.md [Epic 8, Onda 3]"
```

- [ ] **Step 5: Parar aqui**

**NÃO faça push e NÃO abra PR** — as duas operações são exclusivas do `@devops`, e `main` é protegida (GH006, 4 checks obrigatórios). Reporte que a branch `feat/onda-3-payout-circuito` está pronta para revisão.

---

## Auto-revisão deste plano

**Cobertura da spec:**

| Seção da spec | Tarefa |
|---|---|
| §1 entidade `Payout` | Task 1 |
| — **(lacuna achada na revisão, fora da spec)** a conta principal não tinha como ser escolhida | **Task 2b** |
| §2.2 padrão de composição | Tasks 2, 3, 4 |
| §2.3 `Protocol` | Task 2 |
| §2.4 fluxo e a ordem | Task 5 |
| §3.1 tabela `payouts` | Task 1 |
| §3.2 `transactions.payout_id` | Task 1 |
| §3.3 migration sem `UPDATE` | Task 1 (docstring da 0077) |
| §4.1 o 409 com rosto | Tasks 5 (backend), 9 (front) |
| §4.1.2 piso de data | Tasks 3, 5 (**refinado** — ver a nota na Task 2) |
| §4.2 histórico | Tasks 6 (API), 9 (tela) |
| §4.3 card do Cockpit | Task 8 |
| §5.1 invariante P4 = 0 | Task 1 (`NOT NULL`) + Task 5 (teste) |
| §5.2 fail-closed de boot | Task 4 |
| §5.3 gates intactos | Tasks 2 (step 5), 3 (steps 5-7) |
| §5.4 ramo inalcançável | Task 3 (allowlist, por escrito) |
| §5.5 concorrência | Task 5 (`FOR UPDATE` preservado) |
| §5.6 `rls_e2e` | Task 7 |
| §5.7 aceite 360px | Task 10 |
| §6 R-1 no CLAUDE.md | Task 10 |

**Sem lacunas.**

**Consistência de tipos:** `DestinoDoPayout` (wallet) e `_Destino` (bank) têm os mesmos três campos — a duplicação é deliberada e está justificada na docstring de `bank/payout.py`. `registra_payout` tem a assinatura exata do `Protocol` da Task 2. `PayoutResult` ganha `payout_id: str` na Task 5 e é consumido na Task 6.
