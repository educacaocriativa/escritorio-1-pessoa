# Estornar Conta Paga Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Post-implementation note (2026-07-27):** Tasks 1 and 3 (Contas a Pagar) shipped as planned. Tasks 2 and 4 (Contas a Receber) were implemented, reviewed, and then reverted before merge — the final whole-branch review found that the reverse→re-pay flow would duplicate `platform_earnings` (the Master's global GMV ledger) with no way to reconcile it. See the "Adendo" in `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md` for the full writeup. Tasks 2/4 below are left as-is for historical/technical reference if this is revisited.

**Goal:** Add an "Estornar" action to paid bills (Contas a Pagar) and paid charges (Contas a Receber) that reverses the payment, reopening the record for full editing (including new attachments).

**Architecture:** Two new backend endpoints (`POST /payables/bills/{id}/reverse`, `POST /receivables/charges/{id}/reverse`) that flip status back to `open`/`paid_at=None` and revert the linked Agenda event to `scheduled`. The receivables version additionally flips the linked wallet `Transaction` to `refunded` (removing it from balance sums) and hard-blocks with 409 if that transaction was already `withdrawn`. Two matching frontend buttons, one per page, following each page's existing action-button conventions exactly (they differ slightly — see Task 3/4).

**Tech Stack:** FastAPI + SQLAlchemy 2 (backend, Python 3.13, pytest), React 18 + TypeScript + Vite (frontend), monorepo at `apps/api` / `apps/web`.

## Global Constraints

- Backend tests run via `apps/api/.venv/Scripts/python.exe -m pytest -q <path>` (Windows venv, already set up — confirmed working).
- Follow existing code patterns exactly: error class `PayableError`/`ReceivableError` with `(message, status_code)`, `audit.record(db, tenant_id=..., actor=..., action="...", target=...)` after mutation, `db.commit()` + `db.refresh()` before return.
- Action name convention: `payable.reverse` / `receivable.reverse` (matches existing `payable.paid`, `payable.cancel`, `receivable.paid`, `receivable.cancel`).
- No new fields in `shared-types` — `status` already includes `"open"` in both `PayableOut`/`ChargeOut`; reverse only moves a record back into an existing state.
- Full suite must still pass at the end: `bash scripts/check.sh` from repo root (`apps/api` lint+tests, `apps/web` typecheck+tests).
- PT-BR for all user-facing strings and error messages (existing convention).

---

### Task 1: Backend — reverse Payable (Contas a Pagar)

**Files:**
- Modify: `apps/api/app/modules/payables/service.py` (add `reverse_payable` after `cancel_payable`, currently ending at line 262)
- Modify: `apps/api/app/modules/payables/router.py` (add `POST /bills/{payable_id}/reverse` after `cancel_bill`, currently ending at line 135)
- Test: `apps/api/tests/test_payables.py`

**Interfaces:**
- Consumes: `PayableError(message: str, status_code: int = 400)`, `STATUS_OPEN`/`STATUS_PAID` (from `app.modules.payables.models`, already imported), `STATUS_SCHEDULED`/`AgendaEvent` (from `app.modules.agenda.models`, already imported at top of `service.py`), `audit.record` (already imported).
- Produces: `service.reverse_payable(db, *, payable_id: str, tenant_id: str, actor: str) -> Payable` — later consumed by `router.py`'s new endpoint. Router exposes `POST /payables/bills/{payable_id}/reverse` returning `PayableOut` (same shape as `/pay` and `/cancel`).

- [ ] **Step 1: Write the failing tests**

Add to the end of `apps/api/tests/test_payables.py`:

```python
def test_reverse_paid_payable(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(due_date="2026-08-05"), headers=headers).json()
    client.post(f"/payables/bills/{b['id']}/pay", headers=headers)

    resp = client.post(f"/payables/bills/{b['id']}/reverse", headers=headers)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == "open"
    assert out["paid_at"] is None

    # evento na Agenda volta a aparecer como pendente (não mais "concluído")
    ev = [e for e in client.get("/agenda/events?limit=500", headers=headers).json()
          if e["kind"] == "cobranca_pagar"][0]
    assert ev["status"] == "scheduled"

    # reaberta, volta a poder editar dados
    edit = client.patch(
        f"/payables/bills/{b['id']}", json={"amount_cents": 12345}, headers=headers
    )
    assert edit.status_code == 200
    assert edit.json()["amount_cents"] == 12345


def test_reverse_open_payable_rejected(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    resp = client.post(f"/payables/bills/{b['id']}/reverse", headers=headers)
    assert resp.status_code == 409


def test_reverse_canceled_payable_rejected(client: TestClient, headers):
    b = client.post("/payables/bills", json=_bill(), headers=headers).json()
    client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    resp = client.post(f"/payables/bills/{b['id']}/reverse", headers=headers)
    assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `apps/api`): `.venv/Scripts/python.exe -m pytest -q tests/test_payables.py -k reverse -v`
Expected: FAIL with `404 Not Found` (route doesn't exist yet — `assert resp.status_code == 200` fails since the response is a 404 error body).

- [ ] **Step 3: Implement `reverse_payable` in service.py**

Add immediately after `cancel_payable` (after the line `return p` that closes it, i.e. after current line 262):

```python
def reverse_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    """Estorna uma conta paga: volta para 'open', limpa paid_at, reabre a edição completa e
    devolve o evento vinculado na Agenda para pendente (desfaz o STATUS_DONE de mark_paid)."""
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    if p.status != STATUS_PAID:
        raise PayableError("Só contas pagas podem ser estornadas", 409)
    p.status = STATUS_OPEN
    p.paid_at = None
    if p.agenda_event_id:
        ev = db.get(AgendaEvent, p.agenda_event_id)
        if ev is not None:
            ev.status = STATUS_SCHEDULED
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.reverse", target=p.id)
    db.commit()
    db.refresh(p)
    return p
```

- [ ] **Step 4: Add the router endpoint**

Add to `apps/api/app/modules/payables/router.py` immediately after `cancel_bill` (end of file):

```python
@router.post("/bills/{payable_id}/reverse", response_model=PayableOut)
def reverse_bill(
    payable_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> PayableOut:
    try:
        p = service.reverse_payable(
            db, payable_id=payable_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.PayableError as e:
        raise _err(e) from e
    return _out(p)
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `apps/api`): `.venv/Scripts/python.exe -m pytest -q tests/test_payables.py -v`
Expected: PASS, all tests in the file including the 3 new ones (`test_reverse_paid_payable`, `test_reverse_open_payable_rejected`, `test_reverse_canceled_payable_rejected`).

- [ ] **Step 6: Lint**

Run (from `apps/api`): `.venv/Scripts/python.exe -m ruff check app/modules/payables`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/modules/payables/service.py apps/api/app/modules/payables/router.py apps/api/tests/test_payables.py
git commit -m "feat: add estornar (reverse) endpoint for paid bills"
```

---

### Task 2: Backend — reverse Charge (Contas a Receber)

**Files:**
- Modify: `apps/api/app/modules/receivables/service.py` (add wallet-models import + `reverse_charge` after `cancel_charge`, currently ending at line 497)
- Modify: `apps/api/app/modules/receivables/router.py` (add `POST /charges/{charge_id}/reverse` after `cancel_charge`, currently ending at line 217)
- Test: `apps/api/tests/test_receivables.py`

**Interfaces:**
- Consumes: `ReceivableError`, `STATUS_OPEN`/`STATUS_PAID` (already imported in `receivables/service.py`), `STATUS_SCHEDULED`/`AgendaEvent` (already imported), `STATUS_WITHDRAWN`/`STATUS_REFUNDED`/`Transaction` (NEW import needed from `app.modules.wallet.models`).
- Produces: `service.reverse_charge(db, *, charge_id: str, tenant_id: str, actor: str) -> Charge`. Router exposes `POST /receivables/charges/{charge_id}/reverse` returning `ChargeOut`.

- [ ] **Step 1: Write the failing tests**

Add to the end of `apps/api/tests/test_receivables.py`:

```python
def test_reverse_paid_charge_refunds_wallet(client: TestClient, headers):
    charge = client.post(
        "/receivables/charges", json=_charge(amount_cents=10000), headers=headers
    ).json()
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 7000

    resp = client.post(f"/receivables/charges/{charge['id']}/reverse", headers=headers)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == "open"
    assert out["paid_at"] is None

    # a transação estornada sai do saldo disponível
    assert client.get("/wallet/summary", headers=headers).json()["available_cents"] == 0

    # evento na Agenda volta a aparecer como pendente
    ev = [e for e in client.get("/agenda/events?limit=500", headers=headers).json()
          if e["kind"] == "cobranca_receber"][0]
    assert ev["status"] == "scheduled"

    # reaberta, volta a poder editar dados
    edit = client.patch(
        f"/receivables/charges/{charge['id']}", json={"amount_cents": 55500}, headers=headers
    )
    assert edit.status_code == 200
    assert edit.json()["amount_cents"] == 55500


def test_reverse_open_charge_rejected(client: TestClient, headers):
    charge = client.post("/receivables/charges", json=_charge(), headers=headers).json()
    resp = client.post(f"/receivables/charges/{charge['id']}/reverse", headers=headers)
    assert resp.status_code == 409


def test_reverse_blocked_after_payout(client: TestClient, headers):
    charge = client.post(
        "/receivables/charges", json=_charge(amount_cents=10000), headers=headers
    ).json()
    client.post(f"/receivables/charges/{charge['id']}/pay", headers=headers)
    # saca o saldo disponível — o valor sai fisicamente da carteira
    client.post("/wallet/payout", headers=headers)

    resp = client.post(f"/receivables/charges/{charge['id']}/reverse", headers=headers)
    assert resp.status_code == 409, resp.text
    # a cobrança continua paga (nada foi revertido)
    assert client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()["status"] == "paid"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `apps/api`): `.venv/Scripts/python.exe -m pytest -q tests/test_receivables.py -k reverse -v`
Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Add the wallet-models import**

In `apps/api/app/modules/receivables/service.py`, change the existing import line:

```python
from app.modules.wallet import service as wallet_service
```

to:

```python
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import STATUS_REFUNDED, STATUS_WITHDRAWN, Transaction
```

- [ ] **Step 4: Implement `reverse_charge` in service.py**

Add immediately after `cancel_charge` (after the `return charge` that closes it, i.e. after current line 497):

```python
def reverse_charge(db: Session, *, charge_id: str, tenant_id: str, actor: str) -> Charge:
    """Estorna uma cobrança paga: devolve a transação vinculada na Carteira para 'refunded'
    (sai do saldo disponível/a receber) e a cobrança para 'open'. Bloqueia se o valor já foi
    sacado (STATUS_WITHDRAWN) — nesse caso o dinheiro já saiu fisicamente da carteira e não há
    como desfazer só editando o registro. Não toca `platform_earnings` (ledger histórico
    imutável do Master — ver design doc)."""
    charge = db.scalar(select(Charge).where(Charge.id == charge_id).with_for_update())
    if charge is None:
        raise ReceivableError("Cobrança não encontrada", 404)
    if charge.status != STATUS_PAID:
        raise ReceivableError("Só cobranças pagas podem ser estornadas", 409)

    tx = db.get(Transaction, charge.transaction_id) if charge.transaction_id else None
    if tx is not None:
        if tx.status == STATUS_WITHDRAWN:
            raise ReceivableError(
                "Não é possível estornar: o valor já foi sacado da carteira", 409
            )
        tx.status = STATUS_REFUNDED

    charge.status = STATUS_OPEN
    charge.paid_at = None
    if charge.agenda_event_id:
        ev = db.get(AgendaEvent, charge.agenda_event_id)
        if ev is not None:
            ev.status = STATUS_SCHEDULED
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="receivable.reverse", target=charge.id
    )
    db.commit()
    db.refresh(charge)
    return charge
```

- [ ] **Step 5: Add the router endpoint**

Add to `apps/api/app/modules/receivables/router.py` immediately after `cancel_charge` (before `reschedule_charge`):

```python
@router.post("/charges/{charge_id}/reverse", response_model=ChargeOut)
def reverse_charge(
    charge_id: str,
    user: CurrentUser = Depends(_guard),
    db: Session = Depends(get_tenant_db),
) -> ChargeOut:
    try:
        charge = service.reverse_charge(
            db, charge_id=charge_id, tenant_id=user.tenant_id, actor=user.user_id
        )
    except service.ReceivableError as e:
        raise _err(e) from e
    return _out(charge, db)
```

- [ ] **Step 6: Run tests to verify they pass**

Run (from `apps/api`): `.venv/Scripts/python.exe -m pytest -q tests/test_receivables.py -v`
Expected: PASS, all tests in the file including the 3 new ones.

- [ ] **Step 7: Lint**

Run (from `apps/api`): `.venv/Scripts/python.exe -m ruff check app/modules/receivables`
Expected: no errors.

- [ ] **Step 8: Run the full backend suite** (guards against any cross-module regression, e.g. wallet balance assumptions elsewhere)

Run (from `apps/api`): `.venv/Scripts/python.exe -m pytest -q -m "not rls_e2e"`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/api/app/modules/receivables/service.py apps/api/app/modules/receivables/router.py apps/api/tests/test_receivables.py
git commit -m "feat: add estornar (reverse) endpoint for paid charges, blocked if already withdrawn"
```

---

### Task 3: Frontend — "Estornar" button in Contas a Pagar

**Files:**
- Modify: `apps/web/src/features/pagar/PagarPage.tsx`

**Interfaces:**
- Consumes: `POST /payables/bills/{id}/reverse` (Task 1). `api` / `apiErrorMessage` from `../../lib/api` (already imported at top of file).
- Produces: nothing consumed by other tasks — this is a leaf UI change.

- [ ] **Step 1: Add the `reverse` handler**

In `apps/web/src/features/pagar/PagarPage.tsx`, immediately after the existing `cancel` function (currently lines 113-117):

```tsx
async function reverse(id: string) {
  if (!confirm('Estornar esta conta? Ela volta para "A pagar" e pode ser editada de novo.')) return;
  await api.post(`/payables/bills/${id}/reverse`);
  load();
}
```

This mirrors the existing `pay`/`cancel` functions in this file exactly (no try/catch — same as `pay`/`cancel` above it; this file has no error-toast plumbing today, unlike `CobrancasPage.tsx`).

- [ ] **Step 2: Add the button**

In the same file, find the action cell block (currently lines 182-199):

```tsx
{p.status !== "canceled" && (
  <button onClick={() => setAttach(p)} className="flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-primary-600">
    <Paperclip size={12} /> Boleto/Pix
  </button>
)}
{p.status === "open" && (
  <>
    <button onClick={() => setEdit(p)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
      Editar
    </button>
    <button onClick={() => pay(p.id)} className="text-xs font-medium text-accent-600 hover:underline">
      Marcar paga
    </button>
    <button onClick={() => cancel(p.id)} className="text-xs text-neutral-400 hover:text-danger">
      Cancelar
    </button>
  </>
)}
```

Add a new conditional block right after the `p.status === "open"` block closes:

```tsx
{p.status === "paid" && (
  <button onClick={() => reverse(p.id)} className="text-xs font-medium text-neutral-400 hover:text-danger">
    Estornar
  </button>
)}
```

- [ ] **Step 3: Typecheck**

Run (from repo root): `pnpm --filter @e1p/web typecheck`
Expected: no errors.

- [ ] **Step 4: Manual verification**

Start the stack per `CLAUDE.md` §9 (`docker start infra-postgres-1 infra-api-1` + `pnpm --filter @e1p/web dev`), open `http://127.0.0.1:5173/pagar`, mark a bill as paid, confirm the new "Estornar" button appears only on "Pago" rows, click it, confirm the browser `confirm()` dialog text, confirm the row goes back to "A pagar" with Editar/Marcar paga/Cancelar restored, and confirm editing (e.g. changing the value) now succeeds.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/pagar/PagarPage.tsx
git commit -m "feat: add Estornar button to reopen paid bills for editing"
```

---

### Task 4: Frontend — "Estornar" button in Contas a Receber

**Files:**
- Modify: `apps/web/src/features/cobrancas/CobrancasPage.tsx`

**Interfaces:**
- Consumes: `POST /receivables/charges/{id}/reverse` (Task 2). `api` / `apiErrorMessage` / `notify` (all already present in this file — `notify` is the local toast helper defined at lines 54-57).
- Produces: nothing consumed by other tasks — leaf UI change.

- [ ] **Step 1: Add the `reverse` handler**

In `apps/web/src/features/cobrancas/CobrancasPage.tsx`, immediately after the existing `cancel` function (currently lines 106-114):

```tsx
async function reverse(id: string) {
  if (!confirm('Estornar esta cobrança? Ela volta para "A vencer" e pode ser editada de novo.')) return;
  try {
    await api.post(`/receivables/charges/${id}/reverse`);
    load();
  } catch (err) {
    notify(apiErrorMessage(err), "err");
  }
}
```

This mirrors this file's own `cancel` function exactly (confirm + try/catch + `notify` on error — this file DOES have toast plumbing, unlike `PagarPage.tsx`), so the 409 "valor já foi sacado" error surfaces as a toast instead of being silently swallowed.

- [ ] **Step 2: Add the button**

In the same file, find the action cell block (currently lines 186-204):

```tsx
{c.status === "open" && (
  <>
    <button onClick={() => setEdit(c)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
      Editar
    </button>
    <button onClick={() => simulatePayment(c)} title="Apenas teste do gateway — em produção o pagamento entra sozinho" className="text-[11px] text-neutral-300 hover:text-accent-600">
      simular pgto
    </button>
    <button onClick={() => cancel(c.id)} className="text-xs text-neutral-400 hover:text-danger">
      Cancelar
    </button>
  </>
)}
```

Add a new conditional block right after this block closes:

```tsx
{c.status === "paid" && (
  <button onClick={() => reverse(c.id)} className="text-xs font-medium text-neutral-400 hover:text-danger">
    Estornar
  </button>
)}
```

- [ ] **Step 3: Typecheck**

Run (from repo root): `pnpm --filter @e1p/web typecheck`
Expected: no errors.

- [ ] **Step 4: Manual verification**

With the stack still running, open `http://127.0.0.1:5173/cobrancas`, mark a charge as paid (via "simular pgto"), confirm "Estornar" appears only on "Recebido" rows, click it, confirm it reverts to "A vencer" with Editar/simular pgto/Cancelar restored. Separately, pay a charge, call `POST /wallet/payout` (e.g. via `/financeiro` withdraw action or `curl`), then try "Estornar" on that charge and confirm the toast shows the "valor já foi sacado" error and the row stays "Recebido".

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/cobrancas/CobrancasPage.tsx
git commit -m "feat: add Estornar button to reopen paid charges for editing"
```

---

## Final Verification

- [ ] Run `bash scripts/check.sh` from repo root — full lint + backend tests + frontend typecheck/tests must pass.
- [ ] Update `CLAUDE.md` "Financeiro: editar + agenda (reverberar)" section with a one-line note that paid bills/charges can now be estornado(a) to reopen editing (follow the existing terse bullet style used in that section).
