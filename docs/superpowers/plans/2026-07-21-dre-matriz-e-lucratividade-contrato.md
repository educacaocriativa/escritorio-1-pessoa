# DRE em Matriz Mensal + Lucratividade por Contrato — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-period DRE page with a month×category matrix, and add a new "Lucratividade por Contrato" ranking page with a per-contract ledger drawer — sharing one period-picker component between both.

**Architecture:** Backend adds two new read-only report functions to the existing `financial_intelligence` module (`dre.py`, `profitability.py`), following the module's established conventions exactly (sign convention: Charge=+/Payable=−; competence regime via `COALESCE(competence_date, due_date)`; `GROUP BY` in the DB, never in Python; RLS inherited automatically, no manual tenant filters). Frontend adds a shared `PeriodPicker` + `periodRange.ts`, rewrites `DrePage.tsx` as a table, and adds a new `LucratividadePage.tsx` + a new reusable `Drawer.tsx` slide-over.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Pydantic (backend), React + TypeScript + Vite + Tailwind + vitest (frontend, no component-test infra — logic is tested as pure functions, same pattern as `dre.test.ts`/`contratoDre.test.ts`).

## Global Constraints

- Regime de **competência** everywhere in this plan (never `paid_at`) — same rule as the rest of `financial_intelligence`.
- Sign convention: `Charge` = `+1`, `Payable` = `−1`, applied at the source-table level, never inferred from `grupo_dre`.
- No manual `tenant_id` filters anywhere — RLS is the only isolation mechanism (Regra de Ouro nº 1).
- `GROUP BY` must run in the database; never load individual rows to sum in Python (exception: `contract_ledger`, which intentionally returns individual rows — that's its whole purpose).
- Backend tests run via `cd apps/api && python -m pytest -q -m "not rls_e2e"`. RLS e2e tests run via `pytest -m rls_e2e` (spins up a real Postgres via testcontainers — requires Docker).
- Frontend tests run via `pnpm --filter @e1p/web test` (vitest, no jsdom — only pure-logic files get `.test.ts`, consistent with `dre.test.ts`/`costCenters.ts`).
- Frontend typecheck: `pnpm --filter @e1p/web typecheck`.
- Related specs: `docs/superpowers/specs/2026-07-21-dre-matriz-mensal-design.md` and `docs/superpowers/specs/2026-07-21-lucratividade-por-contrato-design.md`.

---

## File Structure Overview

**Backend (new/modified):**
- Modify `apps/api/app/modules/financial_intelligence/dre.py` — add month-bucketed aggregation + `dre_matrix_report`; later remove `dre_report`/`_sum_by_account`/`_sum_transactions_by_account`.
- Modify `apps/api/app/modules/financial_intelligence/profitability.py` — add `contracts_dre_report` + `contract_ledger`.
- Modify `apps/api/app/modules/financial_intelligence/schemas.py` — add matrix/ranking/ledger schemas; later remove `DreReportOut`.
- Modify `apps/api/app/modules/financial_intelligence/router.py` — add 3 new routes; later remove `GET /dre`.
- New `apps/api/tests/test_financial_intelligence_dre_matrix.py`.
- Modify `apps/api/tests/test_financial_intelligence_dre_rls.py` — add matrix cross-tenant test.
- Modify `apps/api/tests/test_financial_intelligence_profitability.py` — add ranking + ledger tests.
- Modify `apps/api/tests/test_financial_intelligence_profitability_rls.py` — add ranking + ledger cross-tenant tests.
- Delete `apps/api/tests/test_financial_intelligence_dre.py` (targets the endpoint being removed; its two Transaction-specific regression cases are ported into the new matrix test file first).

**Frontend (new/modified):**
- New `apps/web/src/features/financeiro/periodRange.ts` + `.test.ts`.
- New `apps/web/src/features/financeiro/PeriodPicker.tsx`.
- New `apps/web/src/features/financeiro/dreMatrix.ts` + `.test.ts`.
- Rewrite `apps/web/src/features/financeiro/DrePage.tsx`.
- Modify `apps/web/src/features/financeiro/dre.ts` — remove `DreReport`/`DreRowKind`/`DreRow`/`buildDreView` (keep `DreCategory`/`DreGroup`/`groupLabel`/`formatBRL`, still used by `ContratoDrePage.tsx`).
- Modify `apps/web/src/features/financeiro/dre.test.ts` — remove the `buildDreView` describe block.
- New `apps/web/src/features/financeiro/lucratividade.ts` + `.test.ts`.
- New `apps/web/src/features/financeiro/ledger.ts` + `.test.ts`.
- New `apps/web/src/components/Drawer.tsx`.
- New `apps/web/src/features/financeiro/LucratividadePage.tsx`.
- Modify `apps/web/src/app/App.tsx` — add route.
- Modify `apps/web/src/app/navigation.ts` — add nav entry.

---

### Task 1: `periodRange.ts` — shared period-shortcut resolver

**Files:**
- Create: `apps/web/src/features/financeiro/periodRange.ts`
- Test: `apps/web/src/features/financeiro/periodRange.test.ts`

**Interfaces:**
- Produces: `PeriodShortcut` type, `PeriodRange` interface (`{start: string, end: string}`, "YYYY-MM-DD"), `resolvePeriod(shortcut, today?, custom?): PeriodRange`, `PERIOD_SHORTCUT_LABEL: Record<PeriodShortcut, string>`. Consumed by Task 2 (`PeriodPicker.tsx`), Task 8 (`DrePage.tsx`), Task 15 (`LucratividadePage.tsx`).

- [ ] **Step 1: Write the failing test**

```typescript
// apps/web/src/features/financeiro/periodRange.test.ts
import { describe, expect, it } from "vitest";
import { resolvePeriod } from "./periodRange";

const TODAY = new Date(Date.UTC(2026, 6, 21)); // 21/07/2026 (mês = 6 = julho, 0-indexed)

describe("resolvePeriod", () => {
  it("this_month", () => {
    expect(resolvePeriod("this_month", TODAY)).toEqual({ start: "2026-07-01", end: "2026-07-31" });
  });

  it("last_month cruzando ano (janeiro -> dezembro do ano anterior)", () => {
    const jan = new Date(Date.UTC(2026, 0, 15));
    expect(resolvePeriod("last_month", jan)).toEqual({ start: "2025-12-01", end: "2025-12-31" });
  });

  it("this_quarter (julho cai no 3º trimestre: jul-set)", () => {
    expect(resolvePeriod("this_quarter", TODAY)).toEqual({ start: "2026-07-01", end: "2026-09-30" });
  });

  it("this_year", () => {
    expect(resolvePeriod("this_year", TODAY)).toEqual({ start: "2026-01-01", end: "2026-12-31" });
  });

  it("last_12_months (janela rolante terminando no mês atual)", () => {
    expect(resolvePeriod("last_12_months", TODAY)).toEqual({ start: "2025-08-01", end: "2026-07-31" });
  });

  it("all (início fixo, fim no mês atual)", () => {
    expect(resolvePeriod("all", TODAY)).toEqual({ start: "2000-01-01", end: "2026-07-31" });
  });

  it("custom repassa o range informado", () => {
    const custom = { start: "2026-02-01", end: "2026-02-10" };
    expect(resolvePeriod("custom", TODAY, custom)).toEqual(custom);
  });

  it("custom sem range lança erro", () => {
    expect(() => resolvePeriod("custom", TODAY)).toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @e1p/web test -- periodRange`
Expected: FAIL — `Cannot find module './periodRange'`

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/features/financeiro/periodRange.ts
/**
 * Seletor de período compartilhado entre a matriz da DRE e a Lucratividade por Contrato.
 * Resolve um atalho ("Este mês"/"Este ano"/...) para {start,end} — sempre datas de calendário
 * em UTC (mesmo padrão de DrePage.tsx/ContratoDrePage.tsx, sem depender do fuso do navegador).
 */
export type PeriodShortcut =
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "this_year"
  | "last_12_months"
  | "all"
  | "custom";

export interface PeriodRange {
  start: string; // "YYYY-MM-DD"
  end: string;
}

export const PERIOD_SHORTCUT_LABEL: Record<PeriodShortcut, string> = {
  this_month: "Este mês",
  last_month: "Mês anterior",
  this_quarter: "Este trimestre",
  this_year: "Este ano",
  last_12_months: "Últimos 12 meses",
  all: "Tudo",
  custom: "Personalizado",
};

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function lastDayOfMonth(year: number, month: number): number {
  // `month` é 1-indexed (1=janeiro).
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

function monthBounds(year: number, month: number): PeriodRange {
  return {
    start: `${year}-${pad2(month)}-01`,
    end: `${year}-${pad2(month)}-${pad2(lastDayOfMonth(year, month))}`,
  };
}

/**
 * Resolve um atalho para {start,end}. "all" usa 2000-01-01 como início — cobre qualquer
 * histórico plausível do tenant sem exigir uma query "sem limite inferior" separada no backend.
 * "custom" exige o 3º argumento (lança erro se omitido — a UI só usa "custom" quando o usuário
 * já preencheu os dois campos de data).
 */
export function resolvePeriod(
  shortcut: PeriodShortcut,
  today: Date = new Date(),
  custom?: PeriodRange,
): PeriodRange {
  const y = today.getUTCFullYear();
  const m = today.getUTCMonth() + 1; // 1-indexed

  switch (shortcut) {
    case "this_month":
      return monthBounds(y, m);
    case "last_month": {
      const py = m === 1 ? y - 1 : y;
      const pm = m === 1 ? 12 : m - 1;
      return monthBounds(py, pm);
    }
    case "this_quarter": {
      const qStartMonth = Math.floor((m - 1) / 3) * 3 + 1;
      return { start: monthBounds(y, qStartMonth).start, end: monthBounds(y, qStartMonth + 2).end };
    }
    case "this_year":
      return { start: `${y}-01-01`, end: `${y}-12-31` };
    case "last_12_months": {
      // janela rolante de 12 meses terminando no mês atual (inclusive) — volta 11 meses.
      const totalMonths = y * 12 + (m - 1) - 11;
      const startY = Math.floor(totalMonths / 12);
      const startM = (totalMonths % 12) + 1;
      return { start: monthBounds(startY, startM).start, end: monthBounds(y, m).end };
    }
    case "all":
      return { start: "2000-01-01", end: monthBounds(y, m).end };
    case "custom":
      if (!custom) throw new Error("período personalizado requer start/end");
      return custom;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter @e1p/web test -- periodRange`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/financeiro/periodRange.ts apps/web/src/features/financeiro/periodRange.test.ts
git commit -m "feat: seletor de período compartilhado (atalhos Este mês/trimestre/ano/tudo/personalizado)"
```

---

### Task 2: `PeriodPicker.tsx` — shared dropdown UI

**Files:**
- Create: `apps/web/src/features/financeiro/PeriodPicker.tsx`

**Interfaces:**
- Consumes: `resolvePeriod`, `PeriodRange`, `PeriodShortcut`, `PERIOD_SHORTCUT_LABEL` from `./periodRange` (Task 1).
- Produces: default export `PeriodPicker({ value, onChange }: { value: PeriodRange; onChange: (r: PeriodRange) => void })`. Consumed by Task 8 (`DrePage.tsx`) and Task 15 (`LucratividadePage.tsx`).

No test in this task: the project has no component-test infra (no jsdom/@testing-library — same documented limitation as every other `.tsx` file in `features/financeiro/`). Logic worth testing already lives in `periodRange.ts` (Task 1).

- [ ] **Step 1: Write the component**

```tsx
// apps/web/src/features/financeiro/PeriodPicker.tsx
import { useState } from "react";
import { PERIOD_SHORTCUT_LABEL, resolvePeriod, type PeriodRange, type PeriodShortcut } from "./periodRange";

const SHORTCUTS: PeriodShortcut[] = [
  "this_month",
  "last_month",
  "this_quarter",
  "this_year",
  "last_12_months",
  "all",
  "custom",
];

/** Dropdown de período (Este mês/Mês anterior/Este trimestre/Este ano/Últimos 12 meses/Tudo/
 * Personalizado) compartilhado pela DRE em matriz e pela Lucratividade por Contrato. */
export default function PeriodPicker({
  value,
  onChange,
}: {
  value: PeriodRange;
  onChange: (range: PeriodRange) => void;
}) {
  const [shortcut, setShortcut] = useState<PeriodShortcut>("this_year");
  const [customStart, setCustomStart] = useState(value.start);
  const [customEnd, setCustomEnd] = useState(value.end);

  function selectShortcut(next: PeriodShortcut) {
    setShortcut(next);
    if (next === "custom") {
      onChange({ start: customStart, end: customEnd });
      return;
    }
    onChange(resolvePeriod(next));
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        value={shortcut}
        onChange={(e) => selectShortcut(e.target.value as PeriodShortcut)}
        aria-label="Período"
        className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
      >
        {SHORTCUTS.map((s) => (
          <option key={s} value={s}>
            {PERIOD_SHORTCUT_LABEL[s]}
          </option>
        ))}
      </select>
      {shortcut === "custom" && (
        <>
          <input
            type="date"
            value={customStart}
            onChange={(e) => {
              setCustomStart(e.target.value);
              onChange({ start: e.target.value, end: customEnd });
            }}
            aria-label="Início do período personalizado"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
          <span className="text-sm text-neutral-400">até</span>
          <input
            type="date"
            value={customEnd}
            onChange={(e) => {
              setCustomEnd(e.target.value);
              onChange({ start: customStart, end: e.target.value });
            }}
            aria-label="Fim do período personalizado"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm --filter @e1p/web typecheck`
Expected: PASS (no errors — component isn't wired into any page yet, but is self-contained and type-correct)

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/features/financeiro/PeriodPicker.tsx
git commit -m "feat: componente PeriodPicker (dropdown de atalhos de período)"
```

---

### Task 3: Backend — `dre_matrix_report` (group_by="dre")

**Files:**
- Modify: `apps/api/app/modules/financial_intelligence/dre.py`
- Modify: `apps/api/app/modules/financial_intelligence/schemas.py`
- Modify: `apps/api/app/modules/financial_intelligence/router.py`
- Create: `apps/api/tests/test_financial_intelligence_dre_matrix.py`

**Interfaces:**
- Produces: `dre_service.DreMatrixRow`, `DreMatrixGroup`, `DreMatrixReport` dataclasses; `dre_service.dre_matrix_report(db, *, start, end, group_by="dre", cost_center_id=None) -> DreMatrixReport`; `GET /financial-intelligence/dre/matrix`. `group_by="cost_center"` raises `NotImplementedError` for now — completed in Task 4 (this task's tests only exercise `group_by="dre"`, the default).
- Consumes: `GROUP_ORDER`, `ChartAccount` (existing, `chart_of_accounts.models`); `Payable`/`Charge`/`Transaction` + status constants (existing).

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_financial_intelligence_dre_matrix.py
"""Testes da DRE em matriz mensal (Story 5.11) — meses x categorias, regime de competência.

group_by="dre": mesma hierarquia grupo->categoria da DRE por período (Story 5.3), com o eixo de
mês adicionado. group_by="cost_center" é coberto em testes adicionados na Task 4 deste plano.

Porta as duas regressões de Transaction de test_financial_intelligence_dre.py (venda avulsa conta
como receita; Transaction gerada por baixa de Charge não conta em dobro) — o arquivo antigo é
removido depois que o endpoint /dre é descontinuado (Task 6).
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.modules.wallet.models import Transaction

REGISTER = {
    "legal_name": "Consultoria Matriz",
    "document": "33444555000192",
    "slug": "matriz",
    "email": "matriz@example.com",
    "name": "Marina",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account(client: TestClient, headers, grupo: str, categoria: str) -> str:
    r = client.post(
        "/chart-of-accounts", json={"grupo_dre": grupo, "categoria": categoria}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _charge(client, headers, *, amount, competence, account_id=None):
    body = {
        "kind": "service", "method": "pix", "amount_cents": amount,
        "due_date": competence, "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    r = client.post("/receivables/charges", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _payable(client, headers, *, amount, competence, account_id=None):
    body = {
        "description": "conta", "amount_cents": amount,
        "due_date": competence, "competence_date": competence,
    }
    if account_id:
        body["chart_account_id"] = account_id
    r = client.post("/payables/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _matrix(client: TestClient, headers, *, start, end, group_by="dre"):
    r = client.get(
        "/financial-intelligence/dre/matrix",
        params={"start": start, "end": end, "group_by": group_by},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _group(body: dict, key: str) -> dict:
    return next(g for g in body["groups"] if g["key"] == key)


def test_requires_auth(client: TestClient):
    r = client.get(
        "/financial-intelligence/dre/matrix", params={"start": "2026-01-01", "end": "2026-01-31"}
    )
    assert r.status_code == 401


def test_months_are_contiguous_even_without_lancamentos(client: TestClient, headers):
    body = _matrix(client, headers, start="2026-01-01", end="2026-03-31")
    assert body["months"] == ["2026-01", "2026-02", "2026-03"]
    receita = _group(body, "RECEITA")
    assert receita["rows"] == []
    assert receita["subtotal_cents"] == [0, 0, 0]
    assert body["grand_total_cents"] == [0, 0, 0]


def test_aggregates_per_month_and_category(client: TestClient, headers):
    acc = _account(client, headers, "RECEITA", "Consultoria")
    custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    _charge(client, headers, amount=100000, competence="2026-01-10", account_id=acc)
    _charge(client, headers, amount=50000, competence="2026-01-20", account_id=acc)
    _charge(client, headers, amount=30000, competence="2026-02-05", account_id=acc)
    _payable(client, headers, amount=20000, competence="2026-02-08", account_id=custo)

    body = _matrix(client, headers, start="2026-01-01", end="2026-02-28")
    receita = _group(body, "RECEITA")
    consultoria = next(r for r in receita["rows"] if r["label"] == "Consultoria")
    assert consultoria["monthly_cents"] == [150000, 30000]
    assert consultoria["total_cents"] == 180000
    assert consultoria["kind"] == "result"
    assert receita["subtotal_cents"] == [150000, 30000]

    custo_direto = _group(body, "CUSTO_DIRETO")
    assert custo_direto["subtotal_cents"] == [0, -20000]

    assert body["grand_total_cents"] == [150000, 10000]  # 150000+0 ; 30000-20000
    assert body["grand_total"] == 160000


def test_investimento_kind_is_informational_and_excluded_from_grand_total(
    client: TestClient, headers
):
    inv = _account(client, headers, "INVESTIMENTO", "Equipamentos")
    _payable(client, headers, amount=300000, competence="2026-01-02", account_id=inv)

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    investimento = _group(body, "INVESTIMENTO")
    assert investimento["rows"][0]["kind"] == "informational"
    assert investimento["subtotal_cents"] == [0]  # informativo — não entra no subtotal do grupo
    assert body["grand_total_cents"] == [0]


def test_sem_categoria_bucket_appears_only_when_present(client: TestClient, headers):
    body_empty = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    assert all(g["key"] != "SEM_CATEGORIA" for g in body_empty["groups"])

    _charge(client, headers, amount=7000, competence="2026-01-12", account_id=None)
    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    sem = _group(body, "SEM_CATEGORIA")
    assert sem["rows"][0]["kind"] == "uncategorized"
    assert sem["rows"][0]["monthly_cents"] == [7000]
    assert body["grand_total_cents"] == [0]  # sem categoria não entra no resultado


def test_walkin_transaction_counts_as_receita(client: TestClient, headers):
    acc = _account(client, headers, "RECEITA", "Vendas avulsas")
    r = client.post(
        "/wallet/transactions",
        json={
            "kind": "service", "method": "pix", "gross_cents": 5000,
            "chart_account_id": acc, "competence_date": "2026-01-10",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    receita = _group(body, "RECEITA")
    assert receita["subtotal_cents"] == [5000]


def test_paid_charge_transaction_is_not_double_counted(client: TestClient, headers, db: Session):
    acc = _account(client, headers, "RECEITA", "Consultoria paga")
    charge = _charge(client, headers, amount=20000, competence="2026-01-05", account_id=acc)
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)

    tx = db.execute(
        select(Transaction).where(Transaction.external_ref == charge["id"])
    ).scalar_one()
    tx.competence_date = date(2026, 1, 5)
    db.commit()

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31")
    assert _group(body, "RECEITA")["subtotal_cents"] == [20000]  # só a Charge, não em dobro


def test_end_before_start_is_422(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/dre/matrix",
        params={"start": "2026-02-01", "end": "2026-01-01"},
        headers=headers,
    )
    assert r.status_code == 422


def test_invalid_group_by_is_422(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/dre/matrix",
        params={"start": "2026-01-01", "end": "2026-01-31", "group_by": "nonsense"},
        headers=headers,
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_dre_matrix.py`
Expected: FAIL — `404 Not Found` (route doesn't exist yet) on every test.

- [ ] **Step 3: Add month-bucketed aggregation + `dre_matrix_report` to `dre.py`**

Modify `apps/api/app/modules/financial_intelligence/dre.py`. First, update the `sqlalchemy` import line near the top:

```python
# Replace this line:
from sqlalchemy import func, select
# With:
from sqlalchemy import String, func, select
```

Add this import right after the `dataclasses`/`datetime` imports:

```python
from collections.abc import Callable
```

Append the following to the end of the file (after `by_cost_center_report` and its helpers):

```python
# ── Matriz mensal (Story 5.11: meses x categorias) ──────────────────────────────────────────────
def _month_keys(start: date, end: date) -> list[str]:
    """Lista contígua de meses "YYYY-MM" entre `start` e `end` (inclusive) — mesas mesmo quando
    não há nenhum lançamento no mês (a matriz não pode "pular" coluna)."""
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return months


def _sum_by_account_monthly(
    db: Session,
    model: type[Payable | Charge],
    *,
    start: date,
    end: date,
    canceled: str,
    sign: int,
    cost_center_id: str | None = None,
) -> list[tuple[str, str | None, int]]:
    """Como `_sum_by_account`, mas agrupando TAMBÉM por mês de competência (Story 5.11). O mês é
    extraído com CAST para texto + SUBSTR (funciona igual em SQLite e Postgres, sem
    `date_trunc`/`to_char` — os dois dialetos guardam/serializam a data em ISO 'YYYY-MM-DD').
    Retorna (mês 'YYYY-MM', chart_account_id | None, soma_com_sinal) — sem contagem (a matriz não
    usa `count`, ao contrário de `_sum_by_account`)."""
    competence = func.coalesce(model.competence_date, model.due_date)
    month_key = func.substr(func.cast(competence, String), 1, 7)
    stmt = select(
        month_key,
        model.chart_account_id,
        func.coalesce(func.sum(model.amount_cents), 0),
    ).where(competence >= start, competence <= end, model.status != canceled)
    if cost_center_id is not None:
        stmt = stmt.where(model.cost_center_id == cost_center_id)
    stmt = stmt.group_by(month_key, model.chart_account_id)
    rows = db.execute(stmt).all()
    return [(month, acc_id, sign * int(total or 0)) for month, acc_id, total in rows]


def _sum_transactions_by_account_monthly(
    db: Session, *, start: date, end: date, cost_center_id: str | None = None,
) -> list[tuple[str, str | None, int]]:
    """Como `_sum_transactions_by_account`, com o mês adicionado ao GROUP BY (Story 5.11)."""
    competence = func.coalesce(Transaction.competence_date, func.date(Transaction.created_at))
    month_key = func.substr(func.cast(competence, String), 1, 7)
    stmt = select(
        month_key,
        Transaction.chart_account_id,
        func.coalesce(func.sum(Transaction.gross_cents), 0),
    ).where(
        competence >= start,
        competence <= end,
        Transaction.status != TX_REFUNDED,
        Transaction.external_ref.is_(None),
    )
    if cost_center_id is not None:
        stmt = stmt.where(Transaction.cost_center_id == cost_center_id)
    stmt = stmt.group_by(month_key, Transaction.chart_account_id)
    rows = db.execute(stmt).all()
    return [(month, acc_id, int(total or 0)) for month, acc_id, total in rows]


@dataclass
class DreMatrixRow:
    label: str
    kind: str  # "result" | "informational" | "uncategorized"
    monthly_cents: list[int]
    total_cents: int


@dataclass
class DreMatrixGroup:
    key: str
    # Nome do centro de custo (group_by="cost_center", "Não atribuído" incluso) — None quando
    # group_by="dre" (o frontend já resolve o rótulo do grupo DRE a partir de `key`, código estável
    # tipo "RECEITA"; não duplicamos essa tabela de tradução no backend).
    label: str | None
    rows: list[DreMatrixRow]
    subtotal_cents: list[int]  # soma SÓ das linhas kind="result" (mesma exclusão do resultado)
    subtotal_total: int


@dataclass
class DreMatrixReport:
    months: list[str]
    groups: list[DreMatrixGroup]
    grand_total_cents: list[int]
    grand_total: int
    notes: list[str]


def _row_kind(grupo: str | None) -> str:
    if grupo is None:
        return "uncategorized"
    if grupo == "INVESTIMENTO":
        return "informational"
    return "result"


def _build_matrix_group(
    key: str,
    label: str | None,
    cats: dict[str, list[int]],
    kind_of: Callable[[str], str],
    n: int,
) -> DreMatrixGroup:
    rows = [
        DreMatrixRow(label=cat, kind=kind_of(cat), monthly_cents=cents, total_cents=sum(cents))
        for cat, cents in sorted(cats.items())
    ]
    subtotal = [sum(r.monthly_cents[i] for r in rows if r.kind == "result") for i in range(n)]
    return DreMatrixGroup(
        key=key, label=label, rows=rows, subtotal_cents=subtotal, subtotal_total=sum(subtotal),
    )


def dre_matrix_report(
    db: Session,
    *,
    start: date,
    end: date,
    group_by: str = "dre",
    cost_center_id: str | None = None,
) -> DreMatrixReport:
    """DRE em matriz (mês x categoria), regime de competência (Story 5.11). SOMENTE LEITURA.

    `group_by="dre"`: mesma hierarquia grupo->categoria de `dre_report`, com o eixo de mês
    adicionado. Aceita `cost_center_id` opcional (mesma semântica de `dre_report`).
    `group_by="cost_center"`: agrupa por centro de custo em vez de grupo DRE — implementado na
    Story 5.11 Task 4 (ver `_dre_matrix_by_cost_center`).

    Em AMBOS os modos, cada LINHA (não o grupo) carrega seu próprio `kind` — necessário porque em
    `group_by="cost_center"` um único centro de custo pode conter categorias de mais de um grupo
    DRE (ex.: uma categoria de INVESTIMENTO e uma de RECEITA sob o mesmo centro de custo). O
    subtotal de cada grupo e o `grand_total` somam SÓ linhas `kind="result"` — mesma exclusão de
    INVESTIMENTO/sem-categoria que a DRE por categoria já aplica hoje."""
    if group_by not in ("dre", "cost_center"):
        raise ValueError(f"group_by inválido: {group_by}")
    months = _month_keys(start, end)
    n = len(months)
    month_index = {mo: i for i, mo in enumerate(months)}

    if group_by == "cost_center":
        return _dre_matrix_by_cost_center(db, start=start, end=end, months=months, month_index=month_index, n=n)

    account_map: dict[str, tuple[str, str]] = {
        a.id: (a.grupo_dre, a.categoria) for a in db.scalars(select(ChartAccount)).all()
    }

    aggregated = _sum_by_account_monthly(
        db, Charge, start=start, end=end, canceled=CHARGE_CANCELED, sign=1,
        cost_center_id=cost_center_id,
    ) + _sum_by_account_monthly(
        db, Payable, start=start, end=end, canceled=PAYABLE_CANCELED, sign=-1,
        cost_center_id=cost_center_id,
    ) + _sum_transactions_by_account_monthly(
        db, start=start, end=end, cost_center_id=cost_center_id,
    )

    by_group: dict[str, dict[str, list[int]]] = {g: {} for g in GROUP_ORDER}
    sem_by_month = [0] * n

    for month, acc_id, amount in aggregated:
        idx = month_index[month]
        resolved = account_map.get(acc_id) if acc_id else None
        if resolved is None:
            sem_by_month[idx] += amount
            continue
        grupo, categoria = resolved
        cents = by_group.setdefault(grupo, {}).setdefault(categoria, [0] * n)
        cents[idx] += amount

    groups = [
        # `g=grupo` fixa o valor NESTA iteração (sem isso, todas as lambdas capturariam a
        # referência da variável `grupo` e, no fim do loop, resolveriam para o ÚLTIMO grupo —
        # clássica armadilha de closure tardia em Python).
        _build_matrix_group(grupo, None, by_group[grupo], lambda _c, g=grupo: _row_kind(g), n)
        for grupo in GROUP_ORDER
    ]
    has_sem_categoria = any(c != 0 for c in sem_by_month)
    if has_sem_categoria:
        groups.append(
            _build_matrix_group(
                "SEM_CATEGORIA", None, {"Sem categoria": sem_by_month}, lambda _c: "uncategorized", n,
            )
        )

    grand_total = [sum(g.subtotal_cents[i] for g in groups) for i in range(n)]
    notes = [_NOTE_COMPETENCIA, _NOTE_INVESTIMENTO]
    if has_sem_categoria:
        notes.append(_NOTE_SEM_CATEGORIA)

    return DreMatrixReport(
        months=months, groups=groups, grand_total_cents=grand_total,
        grand_total=sum(grand_total), notes=notes,
    )


def _dre_matrix_by_cost_center(
    db: Session, *, start: date, end: date, months: list[str], month_index: dict[str, int], n: int,
) -> DreMatrixReport:
    raise NotImplementedError("group_by='cost_center' — implementado na Task 4 deste plano")
```

- [ ] **Step 4: Add schemas**

In `apps/api/app/modules/financial_intelligence/schemas.py`, add (near the bottom, after `DiagnosticsOut`):

```python
# ── DRE em matriz mensal (Story 5.11) ───────────────────────────────────────
class DreMatrixRowOut(BaseModel):
    label: str
    kind: str  # "result" | "informational" | "uncategorized"
    monthly_cents: list[int]
    total_cents: int


class DreMatrixGroupOut(BaseModel):
    key: str
    label: str | None
    rows: list[DreMatrixRowOut]
    subtotal_cents: list[int]
    subtotal_total: int


class DreMatrixReportOut(BaseModel):
    """Matriz mês x categoria (Story 5.11). `groups` é a hierarquia grupo/centro-de-custo ->
    categoria; cada linha carrega seu próprio `kind` (ver docstring de `dre_matrix_report`).
    `grand_total_cents` soma só as linhas `kind="result"` de todos os grupos, mês a mês."""

    months: list[str]
    groups: list[DreMatrixGroupOut]
    grand_total_cents: list[int]
    grand_total: int
    notes: list[str]
```

- [ ] **Step 5: Add the router endpoint**

In `apps/api/app/modules/financial_intelligence/router.py`, add `DreMatrixReportOut` (and friends) to the existing `from app.modules.financial_intelligence.schemas import (...)` block (alphabetical, matching the existing style):

```python
from app.modules.financial_intelligence.schemas import (
    ContractDreOut,
    CostCenterBucketOut,
    CostCenterReportOut,
    DiagnosticsOut,
    DreCategoryOut,
    DreGroupOut,
    DreMatrixGroupOut,
    DreMatrixReportOut,
    DreMatrixRowOut,
    DreReportOut,
    ProjectionOut,
    ProjectionWindowOut,
    RunwayOut,
    SignalOut,
)
```

Add this block right after the existing `@router.get("/dre", ...)` handler (before `_cost_center_bucket_out`):

```python
def _matrix_row_out(r: dre_service.DreMatrixRow) -> DreMatrixRowOut:
    return DreMatrixRowOut(label=r.label, kind=r.kind, monthly_cents=r.monthly_cents, total_cents=r.total_cents)


def _matrix_group_out(g: dre_service.DreMatrixGroup) -> DreMatrixGroupOut:
    return DreMatrixGroupOut(
        key=g.key, label=g.label, rows=[_matrix_row_out(r) for r in g.rows],
        subtotal_cents=g.subtotal_cents, subtotal_total=g.subtotal_total,
    )


def _matrix_report_out(r: dre_service.DreMatrixReport) -> DreMatrixReportOut:
    return DreMatrixReportOut(
        months=r.months, groups=[_matrix_group_out(g) for g in r.groups],
        grand_total_cents=r.grand_total_cents, grand_total=r.grand_total, notes=r.notes,
    )


@router.get("/dre/matrix", response_model=DreMatrixReportOut)
def dre_matrix(
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    group_by: str = Query(
        default="dre",
        pattern="^(dre|cost_center)$",
        description="Story 5.11: 'dre' (grupo DRE, padrão) ou 'cost_center' (centro de custo).",
    ),
    cost_center_id: str | None = Query(
        default=None,
        description="Filtra por centro de custo — só se aplica quando group_by='dre'.",
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> DreMatrixReportOut:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    cost_center_id = cost_center_id or None
    _require_cost_center(db, cost_center_id)
    report = dre_service.dre_matrix_report(
        db, start=start, end=end, group_by=group_by, cost_center_id=cost_center_id,
    )
    return _matrix_report_out(report)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_dre_matrix.py`
Expected: PASS (10 tests)

- [ ] **Step 7: Run linter**

Run: `cd apps/api && ruff check app/modules/financial_intelligence/`
Expected: no errors (fix any import-order/unused-import issues before continuing)

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/financial_intelligence/dre.py apps/api/app/modules/financial_intelligence/schemas.py apps/api/app/modules/financial_intelligence/router.py apps/api/tests/test_financial_intelligence_dre_matrix.py
git commit -m "feat: DRE em matriz mensal (group_by=dre) — GET /financial-intelligence/dre/matrix"
```

---

### Task 4: Backend — `dre_matrix_report` group_by="cost_center"

**Files:**
- Modify: `apps/api/app/modules/financial_intelligence/dre.py`
- Modify: `apps/api/tests/test_financial_intelligence_dre_matrix.py`

**Interfaces:**
- Consumes: `DreMatrixReport`/`DreMatrixGroup`/`DreMatrixRow`/`_build_matrix_group`/`_row_kind`/`_month_keys` (Task 3); `CostCenter` (existing, `cost_centers.models`); `NAO_ATRIBUIDO` constant (existing, `dre.py`).
- Produces: working `group_by="cost_center"` — no new public names (fills in `_dre_matrix_by_cost_center`, which Task 3 stubbed).

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_financial_intelligence_dre_matrix.py`:

```python
def _cost_center(client, headers, *, name, kind="area"):
    r = client.post("/cost-centers", json={"name": name, "kind": kind}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_cost_center_grouping_splits_by_center_and_category(client: TestClient, headers):
    tecnica = _cost_center(client, headers, name="Tecnica")
    comercial = _cost_center(client, headers, name="Comercial")
    curso_acc = _account(client, headers, "DESPESA_FIXA", "Curso")

    def _payable_cc(amount, competence, cc_id, account_id):
        body = {
            "description": "conta", "amount_cents": amount,
            "due_date": competence, "competence_date": competence,
            "chart_account_id": account_id, "cost_center_id": cc_id,
        }
        r = client.post("/payables/bills", json=body, headers=headers)
        assert r.status_code == 201, r.text
        return r.json()

    _payable_cc(500000, "2026-01-10", tecnica, curso_acc)
    _payable_cc(200000, "2026-02-05", comercial, curso_acc)

    body = _matrix(client, headers, start="2026-01-01", end="2026-02-28", group_by="cost_center")
    tecnica_group = _group(body, tecnica)
    assert tecnica_group["label"] == "Tecnica"
    curso_row = next(r for r in tecnica_group["rows"] if r["label"] == "Curso")
    assert curso_row["monthly_cents"] == [-500000, 0]
    assert curso_row["kind"] == "result"

    comercial_group = _group(body, comercial)
    assert comercial_group["subtotal_cents"] == [0, -200000]


def test_cost_center_grouping_includes_unassigned_bucket(client: TestClient, headers):
    acc = _account(client, headers, "DESPESA_FIXA", "Aluguel")
    _payable(client, headers, amount=40000, competence="2026-01-01", account_id=acc)

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31", group_by="cost_center")
    unassigned = _group(body, "_unassigned")
    assert unassigned["label"] == "Não atribuído"
    assert unassigned["subtotal_cents"] == [-40000]


def test_cost_center_grouping_mixes_kinds_within_one_center(client: TestClient, headers):
    """Um único centro de custo pode ter uma categoria de RECEITA e uma de INVESTIMENTO —
    o subtotal do grupo soma só a linha kind='result', mesmo com as duas dentro do MESMO grupo
    (a razão de `kind` ter virado propriedade da LINHA, não do grupo — ver docstring)."""
    cc = _cost_center(client, headers, name="Sócio A")
    receita_acc = _account(client, headers, "RECEITA", "Consultoria")
    inv_acc = _account(client, headers, "INVESTIMENTO", "Equipamentos")

    r = client.post(
        "/receivables/charges",
        json={
            "kind": "service", "method": "pix", "amount_cents": 100000,
            "due_date": "2026-01-05", "competence_date": "2026-01-05",
            "chart_account_id": receita_acc, "cost_center_id": cc,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    client.post(
        "/payables/bills",
        json={
            "description": "notebook", "amount_cents": 300000,
            "due_date": "2026-01-06", "competence_date": "2026-01-06",
            "chart_account_id": inv_acc, "cost_center_id": cc,
        },
        headers=headers,
    )

    body = _matrix(client, headers, start="2026-01-01", end="2026-01-31", group_by="cost_center")
    group = _group(body, cc)
    kinds = {r["label"]: r["kind"] for r in group["rows"]}
    assert kinds == {"Consultoria": "result", "Equipamentos": "informational"}
    assert group["subtotal_cents"] == [100000]  # só a Consultoria — o investimento é informativo
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_dre_matrix.py -k cost_center`
Expected: FAIL — `NotImplementedError: group_by='cost_center' — implementado na Task 4 deste plano`

- [ ] **Step 3: Implement `_dre_matrix_by_cost_center` and the monthly cost-center aggregation helpers**

In `apps/api/app/modules/financial_intelligence/dre.py`, add these two functions right before `_dre_matrix_by_cost_center` (which you'll replace next):

```python
def _sum_by_cost_center_and_account_monthly(
    db: Session, model: type[Payable | Charge], *, start: date, end: date, canceled: str, sign: int,
) -> list[tuple[str, str | None, str | None, int]]:
    """Como `_sum_by_cost_center_and_account`, com o mês adicionado ao GROUP BY (Story 5.11)."""
    competence = func.coalesce(model.competence_date, model.due_date)
    month_key = func.substr(func.cast(competence, String), 1, 7)
    rows = db.execute(
        select(
            month_key,
            model.cost_center_id,
            model.chart_account_id,
            func.coalesce(func.sum(model.amount_cents), 0),
        )
        .where(competence >= start, competence <= end, model.status != canceled)
        .group_by(month_key, model.cost_center_id, model.chart_account_id)
    ).all()
    return [(month, cc_id, acc_id, sign * int(total or 0)) for month, cc_id, acc_id, total in rows]


def _sum_transactions_by_cost_center_and_account_monthly(
    db: Session, *, start: date, end: date,
) -> list[tuple[str, str | None, str | None, int]]:
    """Como `_sum_transactions_by_cost_center_and_account`, com o mês no GROUP BY (Story 5.11)."""
    competence = func.coalesce(Transaction.competence_date, func.date(Transaction.created_at))
    month_key = func.substr(func.cast(competence, String), 1, 7)
    rows = db.execute(
        select(
            month_key,
            Transaction.cost_center_id,
            Transaction.chart_account_id,
            func.coalesce(func.sum(Transaction.gross_cents), 0),
        )
        .where(
            competence >= start,
            competence <= end,
            Transaction.status != TX_REFUNDED,
            Transaction.external_ref.is_(None),
        )
        .group_by(month_key, Transaction.cost_center_id, Transaction.chart_account_id)
    ).all()
    return [(month, cc_id, acc_id, int(total or 0)) for month, cc_id, acc_id, total in rows]
```

Replace the `_dre_matrix_by_cost_center` stub with:

```python
def _dre_matrix_by_cost_center(
    db: Session, *, start: date, end: date, months: list[str], month_index: dict[str, int], n: int,
) -> DreMatrixReport:
    account_map: dict[str, tuple[str, str]] = {
        a.id: (a.grupo_dre, a.categoria) for a in db.scalars(select(ChartAccount)).all()
    }
    centers = list(db.scalars(select(CostCenter)).all())
    cc_map: dict[str, CostCenter] = {c.id: c for c in centers}

    aggregated = _sum_by_cost_center_and_account_monthly(
        db, Charge, start=start, end=end, canceled=CHARGE_CANCELED, sign=1,
    ) + _sum_by_cost_center_and_account_monthly(
        db, Payable, start=start, end=end, canceled=PAYABLE_CANCELED, sign=-1,
    ) + _sum_transactions_by_cost_center_and_account_monthly(db, start=start, end=end)

    # cost_center_id | None -> categoria -> cents_por_mes ; cost_center_id | None -> categoria -> kind
    by_cc: dict[str | None, dict[str, list[int]]] = {}
    kind_by_cc_cat: dict[str | None, dict[str, str]] = {}
    for month, cc_id, acc_id, amount in aggregated:
        idx = month_index[month]
        resolved = account_map.get(acc_id) if acc_id else None
        grupo = resolved[0] if resolved else None
        categoria = resolved[1] if resolved else "Sem categoria"
        cents = by_cc.setdefault(cc_id, {}).setdefault(categoria, [0] * n)
        cents[idx] += amount
        kind_by_cc_cat.setdefault(cc_id, {})[categoria] = _row_kind(grupo)

    groups: list[DreMatrixGroup] = []
    seen: set[str] = set()
    for c in sorted((c for c in centers if c.archived_at is None), key=lambda c: c.name.lower()):
        cats = by_cc.get(c.id, {})
        kinds = kind_by_cc_cat.get(c.id, {})
        groups.append(_build_matrix_group(c.id, c.name, cats, lambda cat, k=kinds: k[cat], n))
        seen.add(c.id)
    for cc_id, cats in by_cc.items():
        if cc_id is None or cc_id in seen:
            continue
        c = cc_map.get(cc_id)
        kinds = kind_by_cc_cat.get(cc_id, {})
        label = c.name if c else "(centro removido)"
        groups.append(_build_matrix_group(cc_id, label, cats, lambda cat, k=kinds: k[cat], n))
    if None in by_cc:
        kinds = kind_by_cc_cat.get(None, {})
        groups.append(
            _build_matrix_group("_unassigned", NAO_ATRIBUIDO, by_cc[None], lambda cat, k=kinds: k[cat], n)
        )

    grand_total = [sum(g.subtotal_cents[i] for g in groups) for i in range(n)]
    notes = [_NOTE_COMPETENCIA, _NOTE_INVESTIMENTO, _NOTE_NAO_ATRIBUIDO]
    return DreMatrixReport(
        months=months, groups=groups, grand_total_cents=grand_total,
        grand_total=sum(grand_total), notes=notes,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_dre_matrix.py`
Expected: PASS (13 tests)

- [ ] **Step 5: Run the full backend suite (regression check)**

Run: `cd apps/api && python -m pytest -q -m "not rls_e2e"`
Expected: PASS (no existing test broken)

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/modules/financial_intelligence/dre.py apps/api/tests/test_financial_intelligence_dre_matrix.py
git commit -m "feat: DRE em matriz mensal (group_by=cost_center)"
```

---

### Task 5: Backend — RLS e2e test for the matrix endpoint

**Files:**
- Modify: `apps/api/tests/test_financial_intelligence_dre_rls.py`

**Interfaces:**
- Consumes: `dre_matrix_report` (Tasks 3-4); existing `_bootstrap_rls_role`, `_run_migrations_as_app`, `_seed_tenant` helpers already in this file.

- [ ] **Step 1: Add the cross-tenant test**

Append to `apps/api/tests/test_financial_intelligence_dre_rls.py` (reuses the existing bootstrap helpers already defined above in the same file):

```python
def _matrix_grand_total(app_url: str, tenant_id: str | None) -> list[int]:
    from app.modules.financial_intelligence.dre import dre_matrix_report

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            report = dre_matrix_report(session, start=START, end=END)
            session.close()
            return report.grand_total_cents
    finally:
        engine.dispose()


def test_dre_matrix_cross_tenant_a_nao_ve_b() -> None:
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
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        _seed_tenant(app_url, tenant_a, receita=100000, despesa=40000)
        _seed_tenant(app_url, tenant_b, receita=777777, despesa=7777)

        assert _matrix_grand_total(app_url, tenant_a) == [60000], "RLS falhou: matriz do A somou dados do B"
        assert _matrix_grand_total(app_url, tenant_b) == [770000], "RLS falhou: matriz do B somou dados do A"
        assert _matrix_grand_total(app_url, None) == [0], "RLS não é fail-closed na matriz"
```

- [ ] **Step 2: Run to verify it passes (requires Docker)**

Run: `cd apps/api && python -m pytest -q -m rls_e2e tests/test_financial_intelligence_dre_rls.py`
Expected: PASS (2 tests total in the file: the existing `test_dre_cross_tenant_a_nao_ve_b` + the new one)

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_financial_intelligence_dre_rls.py
git commit -m "test: isolamento cross-tenant da DRE em matriz (RLS e2e)"
```

---

### Task 6: Backend — remove the old single-period `/dre` endpoint (dead code)

**Files:**
- Modify: `apps/api/app/modules/financial_intelligence/dre.py`
- Modify: `apps/api/app/modules/financial_intelligence/schemas.py`
- Modify: `apps/api/app/modules/financial_intelligence/router.py`
- Delete: `apps/api/tests/test_financial_intelligence_dre.py`

**Interfaces:**
- Nothing new produced. Verifies nothing else in the codebase still references `dre_report`, `_sum_by_account`, `_sum_transactions_by_account`, or `DreReportOut` before deleting them (grep first).

- [ ] **Step 1: Verify there are no remaining callers**

Run: `cd apps/api && grep -rn "dre_report\|_sum_by_account\b\|_sum_transactions_by_account\b\|DreReportOut" app/ --include=*.py`
Expected: only matches inside `dre.py` (the definitions themselves) and `router.py` (the `/dre` route being removed in this task). If anything else shows up, STOP — do not delete, something still depends on it.

- [ ] **Step 2: Remove the route from `router.py`**

Remove the entire `@router.get("/dre", response_model=DreReportOut)` function (`dre` handler) from `apps/api/app/modules/financial_intelligence/router.py`. Remove `DreReportOut` from the `schemas` import block. Leave `_group_out`/`_report_out` helpers removed too (only used by the deleted handler) — check with grep from Step 1 that nothing else calls `_report_out`/`_group_out` before deleting (the `by-cost-center` endpoint has its own `_cost_center_bucket_out`/`_cost_center_report_out`, unaffected).

- [ ] **Step 3: Remove `dre_report` and its private helpers from `dre.py`**

Remove `dre_report()`, `_sum_by_account()`, and `_sum_transactions_by_account()` from `apps/api/app/modules/financial_intelligence/dre.py`. Leave `DreCategory`/`DreGroup`/`DreReport` dataclasses removed too, but only `DreReport` — double-check `DreCategory`/`DreGroup` aren't imported anywhere else first:

Run: `cd apps/api && grep -rn "DreCategory\b\|DreGroup\b\|DreReport\b" app/ --include=*.py`
Expected: `DreCategory`/`DreGroup` still referenced by `profitability.py`'s `ContractDreCategory`/`ContractDreGroup` — those are SEPARATE dataclasses (different names, just structurally similar), not the same symbols, so this grep should show zero cross-references. If `dre.DreCategory`/`dre.DreGroup` really are imported elsewhere, keep those two classes and only remove `DreReport`.

- [ ] **Step 4: Remove `DreReportOut` from `schemas.py`**

Remove the `DreReportOut` class from `apps/api/app/modules/financial_intelligence/schemas.py`. Keep `DreCategoryOut`/`DreGroupOut` (still used by `ContractDreOut`).

- [ ] **Step 5: Delete the old test file**

```bash
rm apps/api/tests/test_financial_intelligence_dre.py
```

(Its two Transaction-specific regression tests were already ported into `test_financial_intelligence_dre_matrix.py` in Task 3 — `test_walkin_transaction_counts_as_receita` and `test_paid_charge_transaction_is_not_double_counted`.)

- [ ] **Step 6: Run the full backend suite**

Run: `cd apps/api && python -m pytest -q -m "not rls_e2e"`
Expected: PASS, no failures, no import errors

- [ ] **Step 7: Run linter**

Run: `cd apps/api && ruff check .`
Expected: no errors (catches any now-unused imports left behind)

- [ ] **Step 8: Commit**

```bash
git add -A apps/api/app/modules/financial_intelligence/ apps/api/tests/
git commit -m "chore: remove o endpoint /financial-intelligence/dre de período único (substituído pela matriz)"
```

---

### Task 7: Frontend — `dreMatrix.ts` pure types/transform

**Files:**
- Create: `apps/web/src/features/financeiro/dreMatrix.ts`
- Test: `apps/web/src/features/financeiro/dreMatrix.test.ts`

**Interfaces:**
- Consumes: `groupLabel` from `./dre` (existing, unchanged).
- Produces: `DreMatrixRow`, `DreMatrixGroup`, `DreMatrixReport`, `GroupBy` types; `matrixGroupLabel(group, groupBy): string`. Consumed by Task 8 (`DrePage.tsx`).

- [ ] **Step 1: Write the failing test**

```typescript
// apps/web/src/features/financeiro/dreMatrix.test.ts
import { describe, expect, it } from "vitest";
import { matrixGroupLabel, type DreMatrixGroup } from "./dreMatrix";

const group = (over: Partial<DreMatrixGroup> = {}): DreMatrixGroup => ({
  key: "RECEITA",
  label: null,
  rows: [],
  subtotal_cents: [0],
  subtotal_total: 0,
  ...over,
});

describe("matrixGroupLabel", () => {
  it("group_by=dre: traduz o código do grupo em PT-BR via groupLabel", () => {
    expect(matrixGroupLabel(group({ key: "RECEITA" }), "dre")).toBe("Receita");
    expect(matrixGroupLabel(group({ key: "SEM_CATEGORIA" }), "dre")).toBe("Sem categoria");
  });

  it("group_by=cost_center: usa o label vindo do backend (nome do centro de custo)", () => {
    expect(matrixGroupLabel(group({ key: "cc-1", label: "Tecnica" }), "cost_center")).toBe("Tecnica");
  });

  it("group_by=cost_center sem label cai no key (defensivo)", () => {
    expect(matrixGroupLabel(group({ key: "_unassigned", label: null }), "cost_center")).toBe("_unassigned");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @e1p/web test -- dreMatrix`
Expected: FAIL — `Cannot find module './dreMatrix'`

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/features/financeiro/dreMatrix.ts
/**
 * DRE em matriz mensal (Story 5.11) — tipos + transformação PURA que a DrePage usa.
 * O backend já devolve os totais assinados e o subtotal/grand_total prontos (só somam linhas
 * kind="result"); aqui só resolvemos o RÓTULO de exibição do grupo, que difere por modo.
 */
import { groupLabel } from "./dre";

export interface DreMatrixRow {
  label: string;
  kind: "result" | "informational" | "uncategorized";
  monthly_cents: number[];
  total_cents: number;
}

export interface DreMatrixGroup {
  key: string;
  /** Nome do centro de custo (group_by="cost_center") — null quando group_by="dre". */
  label: string | null;
  rows: DreMatrixRow[];
  subtotal_cents: number[];
  subtotal_total: number;
}

export interface DreMatrixReport {
  months: string[];
  groups: DreMatrixGroup[];
  grand_total_cents: number[];
  grand_total: number;
  notes: string[];
}

export type GroupBy = "dre" | "cost_center";

/** Rótulo de exibição do grupo: nome do centro de custo (group_by="cost_center", já vem pronto do
 * backend) OU o rótulo PT-BR do grupo DRE (group_by="dre" — o backend só manda o código, a
 * tradução já existe em `groupLabel`, sem duplicar a tabela). */
export function matrixGroupLabel(group: DreMatrixGroup, groupBy: GroupBy): string {
  if (groupBy === "cost_center") return group.label ?? group.key;
  return groupLabel(group.key);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter @e1p/web test -- dreMatrix`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/financeiro/dreMatrix.ts apps/web/src/features/financeiro/dreMatrix.test.ts
git commit -m "feat: tipos e rotulagem da DRE em matriz mensal (frontend)"
```

---

### Task 8: Frontend — rewrite `DrePage.tsx` + clean up `dre.ts`/`dre.test.ts`

**Files:**
- Modify: `apps/web/src/features/financeiro/DrePage.tsx` (full rewrite)
- Modify: `apps/web/src/features/financeiro/dre.ts` (remove dead exports)
- Modify: `apps/web/src/features/financeiro/dre.test.ts` (remove dead tests)

**Interfaces:**
- Consumes: `PeriodPicker` (Task 2), `resolvePeriod`/`PeriodRange` (Task 1), `DreMatrixReport`/`GroupBy`/`matrixGroupLabel` (Task 7), `formatBRL` (existing, `dre.ts` — kept), `api`/`apiErrorMessage` (existing, `lib/api.ts`).

- [ ] **Step 1: Remove dead exports from `dre.ts`**

In `apps/web/src/features/financeiro/dre.ts`, remove: `DreRowKind` type, `DreRow` interface, `buildDreView` function, and the `DreReport` interface. **Keep**: `DreCategory`, `DreGroup`, `groupLabel`, `formatBRL` (still imported by `contratoDre.ts`). The file should now contain only:

```typescript
/**
 * Tipos e formatação compartilhados pela DRE (matriz mensal e por contrato).
 *
 * O backend devolve os totais já ASSINADOS (Receber=+, Pagar=−). A lógica de exibição vive aqui
 * (pura, testável) porque o projeto não tem infra de teste de componente React (sem jsdom /
 * @testing-library).
 */
import { GRUPO_LABEL } from "./planoContas";

export interface DreCategory {
  categoria: string;
  amount_cents: number; // sinal natural (Receber=+, Pagar=−)
  count: number;
}

export interface DreGroup {
  grupo_dre: string;
  total_cents: number;
  categorias: DreCategory[];
}

/** Rótulo PT-BR do grupo (reusa a taxonomia do plano de contas; trata o bucket sintético). */
export function groupLabel(grupo: string): string {
  if (grupo === "SEM_CATEGORIA") return "Sem categoria";
  return (GRUPO_LABEL as Record<string, string>)[grupo] ?? grupo;
}

/** Formata centavos (inteiros) para R$ pt-BR. Mantém o sinal (deduções aparecem negativas). */
export function formatBRL(cents: number): string {
  return (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
```

- [ ] **Step 2: Remove the dead `buildDreView` describe block from `dre.test.ts`**

In `apps/web/src/features/financeiro/dre.test.ts`, remove the `report(...)` helper and the entire `describe("buildDreView (DRE — Story 5.3)", ...)` block. Keep the `describe("groupLabel / formatBRL", ...)` block and its two `it(...)` cases unchanged. The file should now contain only:

```typescript
import { describe, expect, it } from "vitest";
import { formatBRL, groupLabel } from "./dre";

describe("groupLabel / formatBRL", () => {
  it("rotula grupos em PT-BR e o bucket sintético", () => {
    expect(groupLabel("RECEITA")).toBe("Receita");
    expect(groupLabel("SEM_CATEGORIA")).toBe("Sem categoria");
  });

  it("formata centavos em R$ preservando o sinal das deduções", () => {
    expect(formatBRL(150000)).toContain("1.500,00");
    expect(formatBRL(-20000)).toContain("-");
  });
});
```

- [ ] **Step 3: Run test to verify the cleanup didn't break anything**

Run: `pnpm --filter @e1p/web test -- dre.test`
Expected: PASS (2 tests)

- [ ] **Step 4: Rewrite `DrePage.tsx`**

```tsx
// apps/web/src/features/financeiro/DrePage.tsx
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { formatBRL } from "./dre";
import { matrixGroupLabel, type DreMatrixGroup, type DreMatrixReport, type GroupBy } from "./dreMatrix";
import PeriodPicker from "./PeriodPicker";
import { resolvePeriod, type PeriodRange } from "./periodRange";

/**
 * DRE em matriz mensal (Story 5.11) — meses nas colunas, categorias nas linhas, agrupável por
 * grupo DRE ou por centro de custo. Substitui a DRE de período único (Story 5.3). Read-only: só
 * lê a agregação do backend, não altera nada. Design "Portal".
 */
export default function DrePage() {
  const [period, setPeriod] = useState<PeriodRange>(() => resolvePeriod("this_year"));
  const [groupBy, setGroupBy] = useState<GroupBy>("dre");
  const [report, setReport] = useState<DreMatrixReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.get<DreMatrixReport>("/financial-intelligence/dre/matrix", {
        params: { start: period.start, end: period.end, group_by: groupBy },
      });
      setReport(data);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [period, groupBy]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / DRE</p>
          <h1 className="text-2xl font-bold text-neutral-800">DRE por categoria</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Demonstrativo de resultado mês a mês, em regime de competência. Agrupe por grupo DRE
            ou por centro de custo e escolha o período.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            aria-label="Agrupar por"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="dre">Por grupo DRE</option>
            <option value="cost_center">Por centro de custo</option>
          </select>
          <PeriodPicker value={period} onChange={setPeriod} />
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {report && (
        <div className="rounded-2xl bg-white p-5 shadow-sm">
          <p className="text-sm text-neutral-500">Resultado do período</p>
          <p className={`mt-1 text-3xl font-bold ${report.grand_total >= 0 ? "text-emerald-600" : "text-danger"}`}>
            {loading ? "…" : formatBRL(report.grand_total)}
          </p>
        </div>
      )}

      {report && (
        <div className="overflow-x-auto rounded-2xl bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="sticky left-0 bg-white px-4 py-3">Categoria</th>
                {report.months.map((m) => (
                  <th key={m} className="px-4 py-3 text-right">{m}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.groups.map((g) => (
                <MatrixGroupRows key={g.key} group={g} groupBy={groupBy} />
              ))}
              <tr className="border-t-2 border-neutral-200 font-bold">
                <td className="sticky left-0 bg-white px-4 py-3">TOTAL GERAL</td>
                {report.grand_total_cents.map((c, i) => (
                  <td key={i} className="px-4 py-3 text-right">{formatBRL(c)}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {report && report.notes.length > 0 && (
        <ul className="space-y-1 text-xs text-neutral-400">
          {report.notes.map((n) => (
            <li key={n}>• {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MatrixGroupRows({ group, groupBy }: { group: DreMatrixGroup; groupBy: GroupBy }) {
  const monthsCount = group.subtotal_cents.length;
  const isUncategorized = group.rows.length > 0 && group.rows.every((r) => r.kind === "uncategorized");
  return (
    <>
      <tr className={isUncategorized ? "bg-amber-50" : "bg-neutral-50/60"}>
        <td
          className="sticky left-0 bg-inherit px-4 py-2 font-semibold text-neutral-800"
          colSpan={1 + monthsCount}
        >
          {matrixGroupLabel(group, groupBy)}
        </td>
      </tr>
      {group.rows.map((r) => (
        <tr key={r.label} className={r.kind === "informational" ? "text-neutral-400" : ""}>
          <td className="sticky left-0 bg-white px-4 py-2 pl-8">{r.label}</td>
          {r.monthly_cents.map((c, i) => (
            <td key={i} className={`px-4 py-2 text-right ${c < 0 ? "text-danger" : ""}`}>
              {formatBRL(c)}
            </td>
          ))}
        </tr>
      ))}
      <tr className="font-semibold">
        <td className="sticky left-0 bg-white px-4 py-2 pl-8">Subtotal</td>
        {group.subtotal_cents.map((c, i) => (
          <td key={i} className="px-4 py-2 text-right">{formatBRL(c)}</td>
        ))}
      </tr>
    </>
  );
}
```

- [ ] **Step 5: Typecheck**

Run: `pnpm --filter @e1p/web typecheck`
Expected: PASS

- [ ] **Step 6: Run full frontend test suite (regression check)**

Run: `pnpm --filter @e1p/web test`
Expected: PASS, no failures (in particular, `contratoDre.test.ts` and `costCenters.ts` consumers of `dre.ts` still resolve — they only use `DreCategory`/`DreGroup`/`formatBRL`, untouched)

- [ ] **Step 7: Manual smoke test**

Run: `docker start infra-postgres-1 infra-api-1` then `pnpm --filter @e1p/web dev`, open `http://127.0.0.1:5173/financeiro/dre` (use `127.0.0.1`, not `localhost` — avoids the known port collision noted in project memory), confirm the matrix table renders with the period picker and the group-by toggle, and switching "Por centro de custo" reshapes the rows.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/financeiro/DrePage.tsx apps/web/src/features/financeiro/dre.ts apps/web/src/features/financeiro/dre.test.ts
git commit -m "feat: DrePage vira matriz mensal (meses x categorias), com toggle grupo DRE / centro de custo"
```

---

### Task 9: Backend — `contracts_dre_report` (ranking)

**Files:**
- Modify: `apps/api/app/modules/financial_intelligence/profitability.py`
- Modify: `apps/api/app/modules/financial_intelligence/schemas.py`
- Modify: `apps/api/app/modules/financial_intelligence/router.py`
- Modify: `apps/api/tests/test_financial_intelligence_profitability.py`

**Interfaces:**
- Consumes: `contract_dre()` (existing, same file); `contracts_service.list_contracts` (existing, `contracts/service.py`); `STATUS_SIGNED` (existing, `contracts/models.py`); `Client` (existing, `crm/models.py`).
- Produces: `ContractDreSummary` dataclass; `contracts_dre_report(db, *, start, end, include_overhead=False) -> list[ContractDreSummary]`; `GET /financial-intelligence/contracts-dre`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_financial_intelligence_profitability.py`:

```python
def _ranking(client, headers, *, start=START, end=END, include_overhead=False):
    r = client.get(
        "/financial-intelligence/contracts-dre",
        params={"start": start, "end": end, "include_overhead": include_overhead},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _sign_contract_via_link(client, contract_id: str) -> None:
    """Assina o contrato pelo link público (é o único caminho de negócio até status='signed')."""
    slug = None
    # o slug não é devolvido pelo POST /contracts padrão do fixture `_contract`; buscamos direto.
    r = client.get(f"/contracts/{contract_id}")
    slug = r.json()["public_slug"]
    r2 = client.post(
        f"/public/contracts/{slug}/sign",
        json={"name": "Cliente Teste", "document": "12345678900"},
    )
    assert r2.status_code == 200, r2.text


def test_ranking_only_lists_signed_contracts(client: TestClient, headers):
    draft = _contract(client, headers, title="Rascunho")
    signed = _contract(client, headers, title="Assinado")
    _sign_contract_via_link(client, signed["id"])

    body = _ranking(client, headers)
    titles = {row["title"] for row in body}
    assert titles == {"Assinado"}
    assert draft["title"] not in titles


def test_ranking_includes_signed_contract_with_zero_movement(client: TestClient, headers):
    signed = _contract(client, headers, title="Parado")
    _sign_contract_via_link(client, signed["id"])

    body = _ranking(client, headers)
    row = next(r for r in body if r["title"] == "Parado")
    assert row["receita_cents"] == 0
    assert row["custo_direto_cents"] == 0
    assert row["margem_contribuicao_cents"] == 0
    assert row["margem_contribuicao_pct"] is None
    assert row["resultado_cents"] == 0


def test_ranking_reflects_margin_and_include_overhead(client: TestClient, headers):
    acc_receita = _account(client, headers, "RECEITA", "Consultoria")
    acc_custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    contract = _contract(client, headers, title="Projeto A")
    _sign_contract_via_link(client, contract["id"])
    _charge(client, headers, amount=100000, competence="2026-07-10", account_id=acc_receita, contract_id=contract["id"])
    _payable(client, headers, amount=20000, competence="2026-07-08", account_id=acc_custo, contract_id=contract["id"])

    body = _ranking(client, headers)
    row = next(r for r in body if r["title"] == "Projeto A")
    assert row["receita_cents"] == 100000
    assert row["custo_direto_cents"] == -20000
    assert row["margem_contribuicao_cents"] == 80000
    assert row["overhead_allocated_cents"] == 0  # include_overhead=False por padrão

    body_with_overhead = _ranking(client, headers, include_overhead=True)
    row2 = next(r for r in body_with_overhead if r["title"] == "Projeto A")
    # overhead pode ser 0 (sem despesa fixa "Empresa" no cenário) — o que importa é que o campo
    # responde ao toggle sem quebrar; a lógica de rateio em si já é coberta pelos testes de
    # contract_dre/allocate_overhead existentes acima neste arquivo.
    assert "overhead_allocated_cents" in row2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_profitability.py -k ranking`
Expected: FAIL — `404 Not Found` on the ranking calls (`/financial-intelligence/contracts-dre` doesn't exist yet). The `_sign_contract_via_link` helper's `POST /public/contracts/{slug}/sign` route already exists today (`apps/api/app/modules/contracts/router.py:156`, `public_router` with prefix `/public/contracts`) and accepts `{name, document, accept=True}` (`SignRequest` in `contracts/schemas.py`, `document` min length 11) — no adjustment needed there.

- [ ] **Step 3: Add `contracts_dre_report` to `profitability.py`**

Update the imports at the top of `apps/api/app/modules/financial_intelligence/profitability.py`:

```python
# Replace:
from app.modules.contracts.models import Contract
# With:
from app.modules.contracts import service as contracts_service
from app.modules.contracts.models import STATUS_SIGNED, Contract
```

Add this import (new line, after the `contracts` imports):

```python
from app.modules.crm.models import Client
```

Append to the end of `profitability.py`:

```python
# ── Ranking de lucratividade de todos os contratos (Story 5.12) ────────────────────────────────
@dataclass
class ContractDreSummary:
    contract_id: str
    title: str
    client_name: str | None
    receita_cents: int
    custo_direto_cents: int
    margem_contribuicao_cents: int
    margem_contribuicao_pct: float | None
    overhead_allocated_cents: int
    resultado_cents: int


def contracts_dre_report(
    db: Session, *, start: date, end: date, include_overhead: bool = False,
) -> list[ContractDreSummary]:
    """Ranking de lucratividade de TODOS os contratos ASSINADOS do tenant (Story 5.12). Contrato
    signed sem lançamento no período aparece com tudo zerado (não é filtrado) — permite comparar
    quem está "parado" vs. em execução. SOMENTE LEITURA; reusa `contract_dre` por contrato (mesma
    convenção de sinal/competência já ratificada), sem alterar nenhuma linha."""
    contracts = contracts_service.list_contracts(db, status=STATUS_SIGNED)
    summaries: list[ContractDreSummary] = []
    for contract in contracts:
        dre = contract_dre(db, contract=contract, start=start, end=end, include_overhead=include_overhead)
        client_name = None
        if contract.client_id:
            client = db.get(Client, contract.client_id)
            client_name = client.name if client else None
        summaries.append(
            ContractDreSummary(
                contract_id=contract.id,
                title=contract.title,
                client_name=client_name,
                receita_cents=dre.receita_cents,
                custo_direto_cents=dre.custo_direto_cents,
                margem_contribuicao_cents=dre.margem_contribuicao_cents,
                margem_contribuicao_pct=dre.margem_contribuicao_pct,
                overhead_allocated_cents=dre.overhead_allocated_cents,
                resultado_cents=dre.resultado_cents,
            )
        )
    return summaries
```

- [ ] **Step 4: Add the schema**

In `apps/api/app/modules/financial_intelligence/schemas.py`, add after `ContractDreOut`:

```python
class ContractDreSummaryOut(BaseModel):
    """Uma linha do ranking de lucratividade (Story 5.12) — mesmos campos-chave do `ContractDreOut`
    de um contrato só, sem o detalhe de categorias (a lista completa é obtida via `/ledger`)."""

    contract_id: str
    title: str
    client_name: str | None
    receita_cents: int
    custo_direto_cents: int
    margem_contribuicao_cents: int
    margem_contribuicao_pct: float | None
    overhead_allocated_cents: int
    resultado_cents: int
```

- [ ] **Step 5: Add the router endpoint**

In `apps/api/app/modules/financial_intelligence/router.py`, add `ContractDreSummaryOut` to the schemas import block, then append this after the existing `contract_dre` handler:

```python
def _contract_dre_summary_out(s: profitability_service.ContractDreSummary) -> ContractDreSummaryOut:
    return ContractDreSummaryOut(
        contract_id=s.contract_id, title=s.title, client_name=s.client_name,
        receita_cents=s.receita_cents, custo_direto_cents=s.custo_direto_cents,
        margem_contribuicao_cents=s.margem_contribuicao_cents,
        margem_contribuicao_pct=s.margem_contribuicao_pct,
        overhead_allocated_cents=s.overhead_allocated_cents, resultado_cents=s.resultado_cents,
    )


@router.get("/contracts-dre", response_model=list[ContractDreSummaryOut])
def contracts_dre(
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    include_overhead: bool = Query(
        default=False, description="Inclui o rateio de overhead em todas as linhas do ranking.",
    ),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[ContractDreSummaryOut]:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    summaries = profitability_service.contracts_dre_report(
        db, start=start, end=end, include_overhead=include_overhead,
    )
    return [_contract_dre_summary_out(s) for s in summaries]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_profitability.py`
Expected: PASS (all existing + 3 new ranking tests)

- [ ] **Step 7: Run linter and full backend suite**

Run: `cd apps/api && ruff check . && python -m pytest -q -m "not rls_e2e"`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/financial_intelligence/profitability.py apps/api/app/modules/financial_intelligence/schemas.py apps/api/app/modules/financial_intelligence/router.py apps/api/tests/test_financial_intelligence_profitability.py
git commit -m "feat: ranking de lucratividade por contrato — GET /financial-intelligence/contracts-dre"
```

---

### Task 10: Backend — `contract_ledger`

**Files:**
- Modify: `apps/api/app/modules/financial_intelligence/profitability.py`
- Modify: `apps/api/app/modules/financial_intelligence/schemas.py`
- Modify: `apps/api/app/modules/financial_intelligence/router.py`
- Modify: `apps/api/tests/test_financial_intelligence_profitability.py`

**Interfaces:**
- Consumes: `_account_map` (existing, same file, already used by `contract_dre`); `Contract`, `Charge`, `Payable` (existing).
- Produces: `LedgerEntry` dataclass; `contract_ledger(db, *, contract, start, end) -> list[LedgerEntry]`; `GET /financial-intelligence/contracts/{contract_id}/ledger`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/api/tests/test_financial_intelligence_profitability.py`:

```python
def _ledger(client, headers, contract_id, *, start=START, end=END):
    r = client.get(
        f"/financial-intelligence/contracts/{contract_id}/ledger",
        params={"start": start, "end": end},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_ledger_lists_individual_entries_signed_and_sorted(client: TestClient, headers):
    acc_receita = _account(client, headers, "RECEITA", "Consultoria")
    acc_custo = _account(client, headers, "CUSTO_DIRETO", "Insumos")
    contract = _contract(client, headers, title="Projeto Ledger")
    _charge(client, headers, amount=100000, competence="2026-07-20", account_id=acc_receita, contract_id=contract["id"])
    _payable(client, headers, amount=30000, competence="2026-07-05", account_id=acc_custo, contract_id=contract["id"])

    entries = _ledger(client, headers, contract["id"])
    assert [e["date"] for e in entries] == ["2026-07-05", "2026-07-20"]  # ascendente
    payable_entry = entries[0]
    assert payable_entry["source"] == "payable"
    assert payable_entry["amount_cents"] == -30000  # sinal aplicado
    assert payable_entry["categoria"] == "Insumos"
    charge_entry = entries[1]
    assert charge_entry["source"] == "charge"
    assert charge_entry["amount_cents"] == 100000


def test_ledger_excludes_other_contracts_and_canceled(client: TestClient, headers):
    acc = _account(client, headers, "RECEITA", "Consultoria")
    contract_a = _contract(client, headers, title="A")
    contract_b = _contract(client, headers, title="B")
    _charge(client, headers, amount=50000, competence="2026-07-10", account_id=acc, contract_id=contract_a["id"])
    other = _charge(client, headers, amount=999999, competence="2026-07-11", account_id=acc, contract_id=contract_b["id"])
    canceled = _charge(client, headers, amount=1234, competence="2026-07-12", account_id=acc, contract_id=contract_a["id"])
    client.post(f"/receivables/charges/{canceled['id']}/cancel", headers=headers)

    entries = _ledger(client, headers, contract_a["id"])
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 50000


def test_ledger_unknown_contract_is_404(client: TestClient, headers):
    r = client.get(
        "/financial-intelligence/contracts/nao-existe/ledger",
        params={"start": START, "end": END},
        headers=headers,
    )
    assert r.status_code == 404
```

(The `POST /receivables/charges/{id}/cancel` route used above is confirmed to exist as-is — `apps/api/app/modules/receivables/router.py:205`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_profitability.py -k ledger`
Expected: FAIL — `404 Not Found` (route doesn't exist yet)

- [ ] **Step 3: Add `contract_ledger` to `profitability.py`**

Append to `apps/api/app/modules/financial_intelligence/profitability.py`:

```python
# ── Extrato cronológico de um contrato (Story 5.12) ─────────────────────────────────────────────
@dataclass
class LedgerEntry:
    id: str
    source: str  # "charge" | "payable"
    date: date
    description: str
    categoria: str
    status: str
    amount_cents: int  # já assinado (Charge=+, Payable=−)


def contract_ledger(db: Session, *, contract: Contract, start: date, end: date) -> list[LedgerEntry]:
    """Extrato cronológico (linhas INDIVIDUAIS, não agregadas) de um contrato no período de
    competência (Story 5.12). Charge (+) e Payable (−), cancelados fora, ordenado por data
    ascendente. NÃO inclui `Transaction` (sem `contract_id` — mesma exclusão de `contract_dre`).
    SOMENTE LEITURA."""
    account_map = _account_map(db)
    entries: list[LedgerEntry] = []

    charge_competence = func.coalesce(Charge.competence_date, Charge.due_date)
    for c in db.scalars(
        select(Charge).where(
            Charge.contract_id == contract.id,
            charge_competence >= start,
            charge_competence <= end,
            Charge.status != CHARGE_CANCELED,
        )
    ).all():
        categoria = account_map[c.chart_account_id][1] if c.chart_account_id in account_map else "Sem categoria"
        entries.append(
            LedgerEntry(
                id=c.id, source="charge", date=c.competence_date or c.due_date,
                description=c.description or "Cobrança", categoria=categoria,
                status=c.status, amount_cents=c.amount_cents,
            )
        )

    payable_competence = func.coalesce(Payable.competence_date, Payable.due_date)
    for p in db.scalars(
        select(Payable).where(
            Payable.contract_id == contract.id,
            payable_competence >= start,
            payable_competence <= end,
            Payable.status != PAYABLE_CANCELED,
        )
    ).all():
        categoria = account_map[p.chart_account_id][1] if p.chart_account_id in account_map else "Sem categoria"
        entries.append(
            LedgerEntry(
                id=p.id, source="payable", date=p.competence_date or p.due_date,
                description=p.description or "Conta a pagar", categoria=categoria,
                status=p.status, amount_cents=-p.amount_cents,
            )
        )

    entries.sort(key=lambda e: e.date)
    return entries
```

- [ ] **Step 4: Add the schema**

In `apps/api/app/modules/financial_intelligence/schemas.py`, add after `ContractDreSummaryOut`:

```python
class LedgerEntryOut(BaseModel):
    id: str
    source: str  # "charge" | "payable"
    date: date
    description: str
    categoria: str
    status: str
    amount_cents: int
```

- [ ] **Step 5: Add the router endpoint**

In `apps/api/app/modules/financial_intelligence/router.py`, add `LedgerEntryOut` to the schemas import block, then append:

```python
def _ledger_entry_out(e: profitability_service.LedgerEntry) -> LedgerEntryOut:
    return LedgerEntryOut(
        id=e.id, source=e.source, date=e.date, description=e.description,
        categoria=e.categoria, status=e.status, amount_cents=e.amount_cents,
    )


@router.get("/contracts/{contract_id}/ledger", response_model=list[LedgerEntryOut])
def contract_ledger_route(
    contract_id: str,
    start: date = Query(..., description="Início do período (data de competência), YYYY-MM-DD"),
    end: date = Query(..., description="Fim do período (data de competência), YYYY-MM-DD"),
    _user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> list[LedgerEntryOut]:
    if end < start:
        raise HTTPException(status_code=422, detail="'end' não pode ser anterior a 'start'")
    try:
        contract = contracts_service.get_contract(db, contract_id)
    except contracts_service.ContractError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    entries = profitability_service.contract_ledger(db, contract=contract, start=start, end=end)
    return [_ledger_entry_out(e) for e in entries]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd apps/api && python -m pytest -q tests/test_financial_intelligence_profitability.py`
Expected: PASS (all existing + 3 new ledger tests)

- [ ] **Step 7: Run linter and full backend suite**

Run: `cd apps/api && ruff check . && python -m pytest -q -m "not rls_e2e"`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apps/api/app/modules/financial_intelligence/profitability.py apps/api/app/modules/financial_intelligence/schemas.py apps/api/app/modules/financial_intelligence/router.py apps/api/tests/test_financial_intelligence_profitability.py
git commit -m "feat: extrato cronológico do contrato — GET /financial-intelligence/contracts/{id}/ledger"
```

---

### Task 11: Backend — RLS e2e for ranking + ledger

**Files:**
- Modify: `apps/api/tests/test_financial_intelligence_profitability_rls.py`

**Interfaces:**
- Consumes: `contracts_dre_report`, `contract_ledger` (Tasks 9-10); the file's existing `_bootstrap_rls_role`, `_run_migrations_as_app`, `_seed_tenant` (creates one `Contract` + a Charge/Payable pair linked to it, `status` defaults to `"draft"`), `START`/`END` constants.

- [ ] **Step 1: Add the cross-tenant tests**

Append to `apps/api/tests/test_financial_intelligence_profitability_rls.py` (reuses `_bootstrap_rls_role`/`_run_migrations_as_app`/`_seed_tenant` already defined above in the same file — `_seed_tenant` returns the new contract's id):

```python
def _mark_signed(app_url: str, tenant_id: str, contract_id: str) -> None:
    """`_seed_tenant` cria o contrato em status='draft' (default do modelo); o ranking só lista
    'signed' (Story 5.12), então promovemos o status direto via ORM para este teste."""
    from app.modules.contracts.models import STATUS_SIGNED, Contract

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            contract = session.get(Contract, contract_id)
            assert contract is not None
            contract.status = STATUS_SIGNED
            session.commit()
            session.close()
    finally:
        engine.dispose()


def _ranking_titles_and_margins(app_url: str, tenant_id: str) -> dict[str, int]:
    from app.modules.financial_intelligence.profitability import contracts_dre_report

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            summaries = contracts_dre_report(session, start=START, end=END)
            session.close()
            return {s.title: s.margem_contribuicao_cents for s in summaries}
    finally:
        engine.dispose()


def _ledger_amounts(app_url: str, tenant_id: str, contract_id: str) -> list[int]:
    from app.modules.contracts.models import Contract
    from app.modules.financial_intelligence.profitability import contract_ledger

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            contract = session.get(Contract, contract_id)
            assert contract is not None
            entries = contract_ledger(session, contract=contract, start=START, end=END)
            session.close()
            return sorted(e.amount_cents for e in entries)
    finally:
        engine.dispose()


def test_contracts_dre_report_cross_tenant_a_nao_ve_b() -> None:
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
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        contract_a = _seed_tenant(app_url, tenant_a, receita=100000, custo=40000)  # margem 60000
        contract_b = _seed_tenant(app_url, tenant_b, receita=777777, custo=7777)  # margem 770000
        _mark_signed(app_url, tenant_a, contract_a)
        _mark_signed(app_url, tenant_b, contract_b)

        ranking_a = _ranking_titles_and_margins(app_url, tenant_a)
        ranking_b = _ranking_titles_and_margins(app_url, tenant_b)

        assert ranking_a == {"Projeto": 60000}, "RLS falhou: ranking do A viu contrato/valor de B"
        assert ranking_b == {"Projeto": 770000}, "RLS falhou: ranking do B viu contrato/valor de A"


def test_contract_ledger_cross_tenant_isolated() -> None:
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
        _run_migrations_as_app(app_url)

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        # A: Charge +100000, Payable −40000. B: Charge +777777, Payable −7777.
        contract_a = _seed_tenant(app_url, tenant_a, receita=100000, custo=40000)
        _seed_tenant(app_url, tenant_b, receita=777777, custo=7777)

        amounts = _ledger_amounts(app_url, tenant_a, contract_a)
        assert amounts == [-40000, 100000], (
            "RLS falhou: o extrato do contrato de A trouxe lançamentos de B"
        )
```

- [ ] **Step 2: Run to verify it passes (requires Docker)**

Run: `cd apps/api && python -m pytest -q -m rls_e2e tests/test_financial_intelligence_profitability_rls.py`
Expected: PASS (3 tests total in the file: the existing `test_contract_dre_cross_tenant_a_nao_ve_b` + the two new ones)

- [ ] **Step 3: Commit**

```bash
git add apps/api/tests/test_financial_intelligence_profitability_rls.py
git commit -m "test: isolamento cross-tenant do ranking e do ledger de contrato (RLS e2e)"
```

---

### Task 12: Frontend — `lucratividade.ts` pure transform

**Files:**
- Create: `apps/web/src/features/financeiro/lucratividade.ts`
- Test: `apps/web/src/features/financeiro/lucratividade.test.ts`

**Interfaces:**
- Produces: `ContractDreSummary` interface, `LucratividadeTotals` interface, `sortByMargin(rows)`, `computeTotals(rows)`. Consumed by Task 15 (`LucratividadePage.tsx`).

- [ ] **Step 1: Write the failing test**

```typescript
// apps/web/src/features/financeiro/lucratividade.test.ts
import { describe, expect, it } from "vitest";
import { computeTotals, sortByMargin, type ContractDreSummary } from "./lucratividade";

const row = (over: Partial<ContractDreSummary> = {}): ContractDreSummary => ({
  contract_id: "c1",
  title: "Projeto",
  client_name: null,
  receita_cents: 0,
  custo_direto_cents: 0,
  margem_contribuicao_cents: 0,
  margem_contribuicao_pct: null,
  overhead_allocated_cents: 0,
  resultado_cents: 0,
  ...over,
});

describe("sortByMargin", () => {
  it("ordena por margem de contribuição descendente sem mutar o array original", () => {
    const rows = [
      row({ contract_id: "a", margem_contribuicao_cents: 10000 }),
      row({ contract_id: "b", margem_contribuicao_cents: 50000 }),
      row({ contract_id: "c", margem_contribuicao_cents: -2000 }),
    ];
    const sorted = sortByMargin(rows);
    expect(sorted.map((r) => r.contract_id)).toEqual(["b", "a", "c"]);
    expect(rows.map((r) => r.contract_id)).toEqual(["a", "b", "c"]); // original intacto
  });
});

describe("computeTotals", () => {
  it("soma os valores simples e pondera a margem % pela receita (não é média aritmética)", () => {
    const rows = [
      row({ receita_cents: 100000, margem_contribuicao_cents: 80000, custo_direto_cents: -20000, overhead_allocated_cents: 0, resultado_cents: 80000 }),
      row({ receita_cents: 900000, margem_contribuicao_cents: 90000, custo_direto_cents: -810000, overhead_allocated_cents: 5000, resultado_cents: 85000 }),
    ];
    const totals = computeTotals(rows);
    expect(totals.receita_cents).toBe(1000000);
    expect(totals.custo_direto_cents).toBe(-830000);
    expect(totals.overhead_cents).toBe(5000);
    expect(totals.resultado_cents).toBe(165000);
    // ponderada: (80000+90000) / (100000+900000) = 0.17 — bem diferente da média aritmética das
    // duas margens % individuais (80% e 10%, que dariam 45%).
    expect(totals.margem_pct_media).toBeCloseTo(0.17, 5);
  });

  it("margem % média é null quando não há receita (proteção div/0)", () => {
    expect(computeTotals([row({ receita_cents: 0 })]).margem_pct_media).toBeNull();
  });

  it("lista vazia não quebra (todos os totais zerados/null)", () => {
    const totals = computeTotals([]);
    expect(totals).toEqual({
      receita_cents: 0, custo_direto_cents: 0, margem_pct_media: null,
      overhead_cents: 0, resultado_cents: 0,
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @e1p/web test -- lucratividade`
Expected: FAIL — `Cannot find module './lucratividade'`

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/features/financeiro/lucratividade.ts
/**
 * Ranking de lucratividade por contrato (Story 5.12) — tipos + transformação PURA que a
 * LucratividadePage usa. Lógica pura/testável porque o projeto não tem infra de teste de
 * componente React (sem jsdom / @testing-library) — mesmo padrão de dre.ts/contratoDre.ts.
 */
export interface ContractDreSummary {
  contract_id: string;
  title: string;
  client_name: string | null;
  receita_cents: number;
  custo_direto_cents: number;
  margem_contribuicao_cents: number;
  margem_contribuicao_pct: number | null;
  overhead_allocated_cents: number;
  resultado_cents: number;
}

export interface LucratividadeTotals {
  receita_cents: number;
  custo_direto_cents: number;
  /** ponderada: Σmargem / Σreceita — NÃO é a média aritmética das margens %, que deixaria um
   * contrato pequeno distorcer o número. null quando não há receita (proteção div/0). */
  margem_pct_media: number | null;
  overhead_cents: number;
  resultado_cents: number;
}

/** Ranking por margem de contribuição descendente. Não muta o array recebido. */
export function sortByMargin(rows: ContractDreSummary[]): ContractDreSummary[] {
  return [...rows].sort((a, b) => b.margem_contribuicao_cents - a.margem_contribuicao_cents);
}

/** Totais agregados do topo da tela — somas simples + margem % média ponderada pela receita. */
export function computeTotals(rows: ContractDreSummary[]): LucratividadeTotals {
  const receita_cents = rows.reduce((s, r) => s + r.receita_cents, 0);
  const custo_direto_cents = rows.reduce((s, r) => s + r.custo_direto_cents, 0);
  const margem_cents = rows.reduce((s, r) => s + r.margem_contribuicao_cents, 0);
  const overhead_cents = rows.reduce((s, r) => s + r.overhead_allocated_cents, 0);
  const resultado_cents = rows.reduce((s, r) => s + r.resultado_cents, 0);
  return {
    receita_cents,
    custo_direto_cents,
    margem_pct_media: receita_cents !== 0 ? margem_cents / receita_cents : null,
    overhead_cents,
    resultado_cents,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter @e1p/web test -- lucratividade`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/financeiro/lucratividade.ts apps/web/src/features/financeiro/lucratividade.test.ts
git commit -m "feat: tipos e agregação do ranking de lucratividade por contrato (frontend)"
```

---

### Task 13: Frontend — `ledger.ts` pure transform

**Files:**
- Create: `apps/web/src/features/financeiro/ledger.ts`
- Test: `apps/web/src/features/financeiro/ledger.test.ts`

**Interfaces:**
- Consumes: `formatBRL` from `./dre` (existing, re-exported).
- Produces: `LedgerEntry` interface, `statusLabel(status)`, `sortDescending(entries)`. Consumed by Task 15 (`LucratividadePage.tsx`).

- [ ] **Step 1: Write the failing test**

```typescript
// apps/web/src/features/financeiro/ledger.test.ts
import { describe, expect, it } from "vitest";
import { sortDescending, statusLabel, type LedgerEntry } from "./ledger";

const entry = (over: Partial<LedgerEntry> = {}): LedgerEntry => ({
  id: "e1",
  source: "charge",
  date: "2026-06-01",
  description: "desc",
  categoria: "Cat",
  status: "open",
  amount_cents: 1000,
  ...over,
});

describe("statusLabel", () => {
  it("traduz os status conhecidos", () => {
    expect(statusLabel("open")).toBe("Em aberto");
    expect(statusLabel("paid")).toBe("Realizado");
    expect(statusLabel("canceled")).toBe("Cancelado");
  });

  it("status desconhecido cai no valor cru (defensivo)", () => {
    expect(statusLabel("refunded")).toBe("refunded");
  });
});

describe("sortDescending", () => {
  it("ordena por data mais recente primeiro, sem mutar o array original", () => {
    const entries = [
      entry({ id: "a", date: "2026-06-14" }),
      entry({ id: "b", date: "2026-06-15" }),
      entry({ id: "c", date: "2026-06-01" }),
    ];
    const sorted = sortDescending(entries);
    expect(sorted.map((e) => e.id)).toEqual(["b", "a", "c"]);
    expect(entries.map((e) => e.id)).toEqual(["a", "b", "c"]); // original intacto
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --filter @e1p/web test -- ledger`
Expected: FAIL — `Cannot find module './ledger'`

- [ ] **Step 3: Write minimal implementation**

```typescript
// apps/web/src/features/financeiro/ledger.ts
/**
 * Extrato cronológico de um contrato (Story 5.12) — tipos + transformação PURA que o drawer de
 * "Detalhes" da LucratividadePage usa. Lógica pura/testável (sem jsdom/@testing-library).
 */
import { formatBRL } from "./dre";

export interface LedgerEntry {
  id: string;
  source: "charge" | "payable";
  date: string;
  description: string;
  categoria: string;
  status: string;
  amount_cents: number; // já assinado (Charge=+, Payable=−)
}

const STATUS_LABEL: Record<string, string> = {
  open: "Em aberto",
  paid: "Realizado",
  canceled: "Cancelado",
};

/** Rótulo PT-BR do status; status desconhecido cai no valor cru (defensivo, nunca quebra). */
export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** Mais recente primeiro (extrato tipo "bancário"). Não muta o array recebido. */
export function sortDescending(entries: LedgerEntry[]): LedgerEntry[] {
  return [...entries].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

export { formatBRL };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm --filter @e1p/web test -- ledger`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/financeiro/ledger.ts apps/web/src/features/financeiro/ledger.test.ts
git commit -m "feat: tipos e formatação do extrato de contrato (frontend)"
```

---

### Task 14: Frontend — `components/Drawer.tsx`

**Files:**
- Create: `apps/web/src/components/Drawer.tsx`

**Interfaces:**
- Produces: default export `Drawer({ title, subtitle?, open, onClose, children })`. Consumed by Task 15 (`LucratividadePage.tsx`). Generic/reusable — not specific to lucratividade.

No test in this task: same component-test-infra limitation as `Modal.tsx` (existing) and `PeriodPicker.tsx` (Task 2).

- [ ] **Step 1: Write the component**

```tsx
// apps/web/src/components/Drawer.tsx
import { X } from "lucide-react";
import type { ReactNode } from "react";

/**
 * Painel lateral (slide-over da direita) — mesmo modelo de open/onClose/clique-no-backdrop-fecha
 * do Modal.tsx, mas ancorado à direita em vez de centralizado. Reusável (não é single-use).
 */
export default function Drawer({
  title,
  subtitle,
  open,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-lg flex-col bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-neutral-800">{title}</h2>
            {subtitle && <p className="text-sm text-neutral-500">{subtitle}</p>}
          </div>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-700">
            <X size={20} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm --filter @e1p/web typecheck`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/Drawer.tsx
git commit -m "feat: componente Drawer (painel lateral reutilizável)"
```

---

### Task 15: Frontend — `LucratividadePage.tsx`

**Files:**
- Create: `apps/web/src/features/financeiro/LucratividadePage.tsx`

**Interfaces:**
- Consumes: `PeriodPicker`/`resolvePeriod`/`PeriodRange` (Tasks 1-2), `computeTotals`/`sortByMargin`/`ContractDreSummary` (Task 12), `sortDescending`/`statusLabel`/`LedgerEntry` (Task 13), `Drawer` (Task 14), `formatBRL` (existing, `dre.ts`), `api`/`apiErrorMessage` (existing, `lib/api.ts`).

- [ ] **Step 1: Write the component**

```tsx
// apps/web/src/features/financeiro/LucratividadePage.tsx
import { useCallback, useEffect, useState } from "react";
import Drawer from "../../components/Drawer";
import { api, apiErrorMessage } from "../../lib/api";
import { formatBRL } from "./dre";
import { sortDescending, statusLabel, type LedgerEntry } from "./ledger";
import { computeTotals, sortByMargin, type ContractDreSummary } from "./lucratividade";
import PeriodPicker from "./PeriodPicker";
import { resolvePeriod, type PeriodRange } from "./periodRange";

/**
 * Lucratividade por Contrato (Story 5.12) — ranking de todos os contratos ASSINADOS por margem
 * de contribuição, com "Detalhes" abrindo o extrato cronológico de lançamentos do contrato.
 * Read-only: só lê agregações do backend, não altera nada. Design "Portal".
 */
export default function LucratividadePage() {
  const [period, setPeriod] = useState<PeriodRange>(() => resolvePeriod("this_year"));
  const [includeOverhead, setIncludeOverhead] = useState(false);
  const [rows, setRows] = useState<ContractDreSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailContract, setDetailContract] = useState<ContractDreSummary | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.get<ContractDreSummary[]>("/financial-intelligence/contracts-dre", {
        params: { start: period.start, end: period.end, include_overhead: includeOverhead },
      });
      setRows(sortByMargin(data));
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [period, includeOverhead]);

  useEffect(() => {
    load();
  }, [load]);

  const openDetails = useCallback(
    async (row: ContractDreSummary) => {
      setDetailContract(row);
      setLedgerLoading(true);
      try {
        const { data } = await api.get<LedgerEntry[]>(
          `/financial-intelligence/contracts/${row.contract_id}/ledger`,
          { params: { start: period.start, end: period.end } },
        );
        setLedger(sortDescending(data));
      } catch (err) {
        setError(apiErrorMessage(err));
      } finally {
        setLedgerLoading(false);
      }
    },
    [period],
  );

  const totals = computeTotals(rows);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Lucratividade</p>
          <h1 className="text-2xl font-bold text-neutral-800">Lucratividade por Contrato</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Ranking dos contratos assinados por margem de contribuição, em regime de competência.
          </p>
        </div>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Receita total" value={formatBRL(totals.receita_cents)} />
        <KpiCard label="Custo direto" value={formatBRL(totals.custo_direto_cents)} />
        <KpiCard
          label="Margem % média"
          value={
            totals.margem_pct_media === null
              ? "—"
              : `${(totals.margem_pct_media * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`
          }
        />
        <KpiCard label="Overhead" value={formatBRL(totals.overhead_cents)} />
        <KpiCard label="Resultado" value={formatBRL(totals.resultado_cents)} />
      </div>

      <label className="flex items-center gap-2 text-sm text-neutral-600">
        <input
          type="checkbox"
          checked={includeOverhead}
          onChange={(e) => setIncludeOverhead(e.target.checked)}
          className="h-4 w-4 rounded border-neutral-300"
        />
        Ratear overhead da empresa em todas as linhas
      </label>

      <div className="overflow-x-auto rounded-2xl bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
              <th className="px-4 py-3">Contrato</th>
              <th className="px-4 py-3 text-right">Receita</th>
              <th className="px-4 py-3 text-right">Custo direto</th>
              <th className="px-4 py-3 text-right">Margem</th>
              <th className="px-4 py-3 text-right">Margem %</th>
              <th className="px-4 py-3 text-right">Overhead</th>
              <th className="px-4 py-3 text-right">Resultado</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className="px-4 py-3 text-neutral-400" colSpan={8}>Carregando…</td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td className="px-4 py-3 text-neutral-400" colSpan={8}>Nenhum contrato assinado.</td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.contract_id} className="border-b border-neutral-50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-neutral-800">{r.title}</div>
                    {r.client_name && <div className="text-xs text-neutral-400">{r.client_name}</div>}
                  </td>
                  <td className="px-4 py-3 text-right">{formatBRL(r.receita_cents)}</td>
                  <td className="px-4 py-3 text-right">{formatBRL(r.custo_direto_cents)}</td>
                  <td className={`px-4 py-3 text-right ${r.margem_contribuicao_cents < 0 ? "text-danger" : ""}`}>
                    {formatBRL(r.margem_contribuicao_cents)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {r.margem_contribuicao_pct === null
                      ? "—"
                      : `${(r.margem_contribuicao_pct * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`}
                  </td>
                  <td className="px-4 py-3 text-right">{formatBRL(r.overhead_allocated_cents)}</td>
                  <td className={`px-4 py-3 text-right font-semibold ${r.resultado_cents < 0 ? "text-danger" : ""}`}>
                    {formatBRL(r.resultado_cents)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => openDetails(r)}
                      className="rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
                    >
                      Detalhes
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Drawer
        title={detailContract?.title ?? ""}
        subtitle={detailContract ? `${period.start} a ${period.end}` : undefined}
        open={detailContract !== null}
        onClose={() => setDetailContract(null)}
      >
        {ledgerLoading ? (
          <p className="text-sm text-neutral-400">Carregando…</p>
        ) : ledger.length === 0 ? (
          <p className="text-sm text-neutral-400">Sem lançamentos neste período.</p>
        ) : (
          <ul className="divide-y divide-neutral-50">
            {ledger.map((e) => (
              <li key={e.id} className="py-3">
                <div className="flex items-center justify-between">
                  <span className={`font-semibold ${e.amount_cents < 0 ? "text-danger" : "text-emerald-600"}`}>
                    {formatBRL(e.amount_cents)}
                  </span>
                  <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                    {statusLabel(e.status)}
                  </span>
                </div>
                <p className="mt-1 text-sm text-neutral-700">{e.description}</p>
                <p className="text-xs text-neutral-400">{e.date} · {e.categoria}</p>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <p className="text-xs uppercase text-neutral-400">{label}</p>
      <p className="mt-1 text-lg font-bold text-neutral-800">{value}</p>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `pnpm --filter @e1p/web typecheck`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/features/financeiro/LucratividadePage.tsx
git commit -m "feat: página Lucratividade por Contrato (ranking + drawer de lançamentos)"
```

---

### Task 16: Frontend — routing + nav wiring

**Files:**
- Modify: `apps/web/src/app/App.tsx`
- Modify: `apps/web/src/app/navigation.ts`

**Interfaces:**
- Consumes: `LucratividadePage` (Task 15).

- [ ] **Step 1: Add the route**

In `apps/web/src/app/App.tsx`, add the import (alphabetically, next to the other `features/financeiro` imports):

```typescript
import InvestimentosPage from "../features/financeiro/InvestimentosPage";
import LucratividadePage from "../features/financeiro/LucratividadePage";
import PlanoContasPage from "../features/financeiro/PlanoContasPage";
```

Add the route right after `/financeiro/contratos/:id/dre`:

```tsx
<Route path="/financeiro/contratos/:id/dre" element={<ContratoDrePage />} />
<Route path="/financeiro/lucratividade" element={<LucratividadePage />} />
```

- [ ] **Step 2: Add the nav entry**

In `apps/web/src/app/navigation.ts`, add `Percent` to the `lucide-react` import block (alphabetically, between `PieChart` and `Receipt`):

```typescript
  PieChart,
  Percent,
  Receipt,
```

Wait — alphabetically `Percent` comes before `PieChart` (`Pe` < `Pi`). Use:

```typescript
  Package,
  Percent,
  PieChart,
  Receipt,
```

Add the nav item in the "Análise & Configuração Financeira" section, right after `DRE`:

```typescript
{ label: "DRE", to: "/financeiro/dre", icon: PieChart, ready: true },
{ label: "Lucratividade por Contrato", to: "/financeiro/lucratividade", icon: Percent, ready: true },
```

- [ ] **Step 3: Typecheck**

Run: `pnpm --filter @e1p/web typecheck`
Expected: PASS

- [ ] **Step 4: Manual smoke test**

With `docker start infra-postgres-1 infra-api-1` and `pnpm --filter @e1p/web dev` running, open `http://127.0.0.1:5173/financeiro/lucratividade`: confirm the nav entry appears under "Análise & Configuração Financeira", the ranking table loads (sign at least one contract via its public link first if the tenant has none), the KPI cards populate, the overhead checkbox recomputes the Overhead/Resultado columns, and clicking "Detalhes" opens the drawer with the ledger.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/App.tsx apps/web/src/app/navigation.ts
git commit -m "feat: rota e navegação da página Lucratividade por Contrato"
```

---

## Post-plan verification

- [ ] Run the full backend suite: `cd apps/api && ruff check . && python -m pytest -q -m "not rls_e2e"`
- [ ] Run the RLS e2e suite (requires Docker): `cd apps/api && python -m pytest -q -m rls_e2e`
- [ ] Run the full frontend suite: `pnpm --filter @e1p/web typecheck && pnpm --filter @e1p/web test`
- [ ] Manual smoke test both pages end-to-end in the browser (Tasks 8 and 16's manual-test steps)
- [ ] Confirm `docs/superpowers/specs/2026-07-21-dre-matriz-mensal-design.md` and `docs/superpowers/specs/2026-07-21-lucratividade-por-contrato-design.md` are both fully implemented (re-read each "Objetivo"/"Decisões" section against the shipped behavior)
