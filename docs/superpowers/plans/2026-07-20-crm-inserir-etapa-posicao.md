# Inserir etapa do Funil (CRM) em qualquer posição — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the "+ Nova etapa" button on the CRM Kanban board (`/crm`) insert the new stage
immediately after any existing stage the user picks, instead of always appending it at the end.

**Architecture:** No schema change. `pipeline_stages.position` already exists and ordering is
already `ORDER BY position, id`. `POST /crm/stages` gains an optional `after_stage_id` field; on
create, the backend renumbers all active (non-archived) stages sequentially (`0..N-1`) with the
new stage spliced in at the right index, inside the existing single-transaction commit. The
frontend replaces the current `window.prompt` with a small modal (name + "insert after" select,
defaulting to the last stage so unattended confirmation still appends like today).

**Tech Stack:** FastAPI + SQLAlchemy 2 (backend, `apps/api`), React 18 + TypeScript + Tailwind
(frontend, `apps/web`), pytest (backend tests). No new frontend test infra — this codebase's
convention (see `apps/web/vitest.config.ts` comment, "9 testes de lógica pura") is pure-logic
`.test.ts` files only; no existing component ever gained a `.test.tsx`. This feature is pure UI
wiring with no extractable pure logic worth its own test, so it is verified manually in the
running app, consistent with that convention.

## Global Constraints

- Rely exclusively on RLS for tenant isolation — never add a manual `tenant_id` filter to a
  query (Regra de Ouro nº 1, `apps/api/CLAUDE.md`).
- `after_stage_id` omitted/`None` MUST behave exactly like today (append to the end). Do not
  make it mean "insert at the start" — that was an error caught in the design's self-review and
  corrected in `docs/superpowers/specs/2026-07-20-crm-inserir-etapa-posicao-design.md`.
- No reordering of already-existing stages beyond what a new insertion requires (renumbering),
  and no drag-to-reorder UI — explicitly out of scope.
- Idioma do produto: PT-BR nas strings de UI e nomes de teste/asserts de domínio; identificadores
  de código em inglês (convenção do projeto, `CLAUDE.md` §8).

---

### Task 1: Backend — `after_stage_id` on `POST /crm/stages`

**Files:**
- Modify: `apps/api/app/modules/crm/schemas.py:14-24` (`StageCreate`)
- Modify: `apps/api/app/modules/crm/service.py:57-78` (`create_stage`)
- Test: `apps/api/tests/test_crm.py` (append new tests after `test_create_custom_stage`, i.e.
  after line 145)
- Regenerate (mechanical, no hand edits): `packages/shared-types/openapi.json`,
  `packages/shared-types/src/generated.ts`

**Interfaces:**
- Consumes: existing `PipelineStage` model (`apps/api/app/modules/crm/models.py:38-48`),
  existing `_ordered_stages(db) -> list[PipelineStage]` (`service.py:28-36`, already filters
  `is_archived=False` and orders by `position, id`).
- Produces: `StageCreate.after_stage_id: str | None` — later consumed by the frontend (Task 2),
  which will `POST /crm/stages` with `{ name, after_stage_id }`. No change to `StageOut` — the
  response shape is unchanged, so Task 2 doesn't need new response fields.

- [ ] **Step 1: Write the failing tests**

  Open `apps/api/tests/test_crm.py` and insert the following five tests immediately after
  `test_create_custom_stage` (which currently ends at line 145, right before
  `test_stage_cannot_be_won_and_lost`):

  ```python
  def test_create_stage_without_after_appends_to_end(client: TestClient, headers):
      client.get("/crm/board", headers=headers)  # seed
      resp = client.post("/crm/stages", json={"name": "Fechamento"}, headers=headers)
      assert resp.status_code == 201
      names = [s["name"] for s in client.get("/crm/stages", headers=headers).json()]
      assert names[-1] == "Fechamento"


  def test_create_stage_after_stage_inserts_in_the_middle(client: TestClient, headers):
      stages = client.get("/crm/stages", headers=headers).json()
      em_contato = next(s for s in stages if s["name"] == "Em contato")
      resp = client.post(
          "/crm/stages",
          json={"name": "Qualificação", "after_stage_id": em_contato["id"]},
          headers=headers,
      )
      assert resp.status_code == 201
      names = [s["name"] for s in client.get("/crm/stages", headers=headers).json()]
      assert names == ["Entrada", "Em contato", "Qualificação", "Proposta", "Ganho", "Perda"]


  def test_create_stage_after_last_stage_is_equivalent_to_append(client: TestClient, headers):
      stages = client.get("/crm/stages", headers=headers).json()
      perda = next(s for s in stages if s["name"] == "Perda")
      resp = client.post(
          "/crm/stages",
          json={"name": "Pós-venda", "after_stage_id": perda["id"]},
          headers=headers,
      )
      assert resp.status_code == 201
      names = [s["name"] for s in client.get("/crm/stages", headers=headers).json()]
      assert names[-1] == "Pós-venda"


  def test_create_stage_after_archived_stage_rejected(client: TestClient, headers):
      stages = client.get("/crm/stages", headers=headers).json()
      proposta = next(s for s in stages if s["name"] == "Proposta")
      client.post(f"/crm/stages/{proposta['id']}/archive", headers=headers)
      resp = client.post(
          "/crm/stages",
          json={"name": "Depois", "after_stage_id": proposta["id"]},
          headers=headers,
      )
      assert resp.status_code == 422


  def test_create_stage_after_unknown_id_rejected(client: TestClient, headers):
      client.get("/crm/board", headers=headers)  # seed
      resp = client.post(
          "/crm/stages",
          json={"name": "X", "after_stage_id": "nao-existe"},
          headers=headers,
      )
      assert resp.status_code == 422
  ```

- [ ] **Step 2: Run tests to verify they fail**

  Run: `cd apps/api && python -m pytest tests/test_crm.py -k "after_stage or without_after" -v`

  Expected: all 5 new tests FAIL — `test_create_stage_without_after_appends_to_end` fails only if
  order assertions don't match (it may actually pass by coincidence today since append-by-default
  already works); the other 4 MUST fail with either a Pydantic "extra fields not permitted"-style
  422 (if the model is strict) or, more likely, a 201 that silently ignores `after_stage_id`
  (Pydantic ignores unknown fields by default, so the request succeeds but the new stage lands at
  the position computed by the OLD `data.position` logic — always the end — so the middle-insert
  and archived/unknown-id rejection tests fail their assertions).

- [ ] **Step 3: Add `after_stage_id` to `StageCreate`**

  In `apps/api/app/modules/crm/schemas.py`, modify the `StageCreate` class (currently lines
  14-24):

  ```python
  class StageCreate(BaseModel):
      name: str = Field(min_length=1, max_length=64)
      position: int | None = None
      after_stage_id: str | None = None
      is_won: bool = False
      is_lost: bool = False

      @model_validator(mode="after")
      def _validate(self) -> StageCreate:
          if self.is_won and self.is_lost:
              raise ValueError("um estágio não pode ser 'ganho' e 'perda' ao mesmo tempo")
          return self
  ```

  (Only the new `after_stage_id: str | None = None` line is added; `position` stays as-is,
  unused by this flow, matching the design doc.)

- [ ] **Step 4: Rewrite `create_stage` to renumber on insert**

  In `apps/api/app/modules/crm/service.py`, replace the current `create_stage` function (lines
  57-78):

  ```python
  def create_stage(db: Session, *, tenant_id: str, actor: str, data: StageCreate) -> PipelineStage:
      active = _ordered_stages(db)
      if data.after_stage_id is not None:
          try:
              after_index = next(
                  i for i, s in enumerate(active) if s.id == data.after_stage_id
              )
          except StopIteration as e:
              raise CrmError("Etapa de referência não encontrada", 422) from e
          insert_index = after_index + 1
      else:
          insert_index = len(active)

      stage = PipelineStage(
          tenant_id=tenant_id,
          name=data.name,
          is_won=data.is_won,
          is_lost=data.is_lost,
      )
      ordered = active[:insert_index] + [stage] + active[insert_index:]
      for index, s in enumerate(ordered):
          s.position = index

      db.add(stage)
      audit.record(db, tenant_id=tenant_id, actor=actor, action="crm.stage.create", target=stage.id)
      try:
          db.commit()
      except IntegrityError as e:
          db.rollback()
          raise CrmError("Já existe um estágio com esse nome", 409) from e
      db.refresh(stage)
      return stage
  ```

  Note `stage.position` is intentionally not set in the constructor — the `for index, s in
  enumerate(ordered)` loop assigns it (along with every existing active stage's `position`)
  right before commit, covering the new stage too since it's part of `ordered`.

- [ ] **Step 5: Run tests to verify they pass**

  Run: `cd apps/api && python -m pytest tests/test_crm.py -v`

  Expected: all tests in the file PASS, including the 5 new ones and all pre-existing CRM tests
  (in particular `test_create_custom_stage`, `test_duplicate_stage_name_rejected`,
  `test_delete_empty_stage_succeeds`, `test_archive_stage_moves_clients` — none of these assert
  stage order, so the renumbering doesn't affect their outcomes).

- [ ] **Step 6: Run the full backend suite**

  Run: `cd apps/api && python -m pytest -q`

  Expected: PASS (no regressions in other modules — nothing else calls `service.create_stage`,
  confirmed by `grep -rn "create_stage" apps/api/app` during design research).

- [ ] **Step 7: Regenerate shared types**

  From the repo root:

  Run: `pnpm generate:types`

  If it fails to connect to a real database (e.g. no local Postgres reachable from this shell),
  run the two underlying steps with a harmless SQLite URL instead (the export script only needs
  to import the FastAPI app, not open a real connection — see the docstring in
  `apps/api/scripts/export_openapi.py`):

  ```bash
  cd apps/api && DATABASE_URL=sqlite:// python scripts/export_openapi.py
  cd .. && pnpm --filter @e1p/shared-types generate
  ```

  Expected: `packages/shared-types/openapi.json` and `packages/shared-types/src/generated.ts` are
  rewritten (the `StageCreate` schema in both files now includes `after_stage_id`). Do not hand-
  edit either file.

- [ ] **Step 8: Commit**

  ```bash
  git add apps/api/app/modules/crm/schemas.py apps/api/app/modules/crm/service.py \
    apps/api/tests/test_crm.py packages/shared-types/openapi.json \
    packages/shared-types/src/generated.ts
  git commit -m "feat: permite inserir etapa do funil em qualquer posição via after_stage_id"
  ```

---

### Task 2: Frontend — "Nova etapa" modal with insertion point

**Files:**
- Modify: `apps/web/src/features/crm/CrmPage.tsx`

**Interfaces:**
- Consumes: `PipelineStage` type from `@e1p/shared-types` (`{ id, name, position, is_won,
  is_lost }`); `Modal`/`Field` from `../../components/Modal` (existing, unchanged); `api`,
  `apiErrorMessage` from `../../lib/api` (existing, unchanged); `POST /crm/stages` now accepts
  `{ name: string, after_stage_id: string | null }` (Task 1).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Add the `PipelineStage` type import**

  In `apps/web/src/features/crm/CrmPage.tsx`, change line 1 from:

  ```typescript
  import type { Board, BoardColumn, Client } from "@e1p/shared-types";
  ```

  to:

  ```typescript
  import type { Board, BoardColumn, Client, PipelineStage } from "@e1p/shared-types";
  ```

- [ ] **Step 2: Replace `createStage` with modal state**

  In the same file, replace the `createStage` function (currently lines 42-52):

  ```typescript
    async function createStage() {
      const name = window.prompt("Nome da nova etapa:")?.trim();
      if (!name) return;
      try {
        await api.post("/crm/stages", { name });
      } catch (err) {
        alert(apiErrorMessage(err));
      } finally {
        load();
      }
    }
  ```

  with a boolean modal-open state (no function needed anymore — the modal component does the
  API call). Add this state declaration next to the existing `open`/`loading`/`dragOver` state
  (currently lines 10-13):

  ```typescript
    const [board, setBoard] = useState<Board>({ columns: [] });
    const [open, setOpen] = useState(false);
    const [stageModalOpen, setStageModalOpen] = useState(false);
    const [loading, setLoading] = useState(true);
    const [dragOver, setDragOver] = useState<string | null>(null);
  ```

  And delete the old `createStage` function body entirely (it's fully replaced by the
  `NewStageModal` component added in Step 4).

- [ ] **Step 3: Wire the "+ Nova etapa" button and render the modal**

  Still in `CrmPage.tsx`, change the button (currently lines 91-97) from:

  ```tsx
            <button
              onClick={createStage}
              className="flex h-12 w-56 shrink-0 items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-neutral-200 text-sm font-medium text-neutral-400 hover:border-primary-300 hover:text-primary-600"
            >
              <Plus size={16} />
              Nova etapa
            </button>
  ```

  to:

  ```tsx
            <button
              onClick={() => setStageModalOpen(true)}
              className="flex h-12 w-56 shrink-0 items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-neutral-200 text-sm font-medium text-neutral-400 hover:border-primary-300 hover:text-primary-600"
            >
              <Plus size={16} />
              Nova etapa
            </button>
  ```

  Then add the modal render next to the existing `<NewClientModal .../>` (currently line 101),
  so that block reads:

  ```tsx
        <NewClientModal open={open} onClose={() => setOpen(false)} onCreated={load} />
        <NewStageModal
          open={stageModalOpen}
          onClose={() => setStageModalOpen(false)}
          stages={board.columns.map((c) => c.stage)}
          onCreated={load}
        />
  ```

- [ ] **Step 4: Add the `NewStageModal` component**

  Add this new function to `CrmPage.tsx`, right after the existing `NewClientModal` function
  (which currently ends at line 275, just before the file's final line):

  ```tsx
  function NewStageModal({
    open,
    onClose,
    stages,
    onCreated,
  }: {
    open: boolean;
    onClose: () => void;
    stages: PipelineStage[];
    onCreated: () => void;
  }) {
    const [name, setName] = useState("");
    const [afterStageId, setAfterStageId] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
      if (!open) return;
      setName("");
      setError(null);
      setAfterStageId(stages.length > 0 ? stages[stages.length - 1].id : "");
    }, [open, stages]);

    async function save() {
      setError(null);
      setSaving(true);
      try {
        await api.post("/crm/stages", { name, after_stage_id: afterStageId || null });
        onCreated();
        onClose();
      } catch (err) {
        setError(apiErrorMessage(err));
      } finally {
        setSaving(false);
      }
    }

    return (
      <Modal title="Nova etapa" open={open} onClose={onClose}>
        <div className="space-y-3">
          <Field label="Nome da etapa" value={name} onChange={setName} placeholder="Negociação" />
          {stages.length > 0 && (
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-neutral-600">
                Inserir depois de
              </span>
              <select
                value={afterStageId}
                onChange={(e) => setAfterStageId(e.target.value)}
                className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
              >
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
          <button
            onClick={save}
            disabled={saving || !name.trim()}
            className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
          >
            {saving ? "Salvando..." : "Criar etapa"}
          </button>
        </div>
      </Modal>
    );
  }
  ```

  This closes over `stages` (always the board's current active stages, in order) and defaults
  `afterStageId` to the last one whenever the modal opens — reproducing today's "always appends"
  behavior for anyone who just types a name and confirms, per the approved design.

- [ ] **Step 5: Typecheck and lint**

  Run: `cd apps/web && pnpm typecheck`
  Expected: no errors.

  Run: `cd apps/web && pnpm lint`
  Expected: no errors (0 warnings — `--max-warnings 0` is configured).

- [ ] **Step 6: Manual verification in the running app**

  Bring the stack up (per `apps/api/CLAUDE.md` §9):

  ```bash
  docker start infra-postgres-1 infra-api-1
  pnpm --filter @e1p/web dev
  ```

  Open `http://127.0.0.1:5173/crm` (use `127.0.0.1`, not `localhost` — this repo's Vite dev
  server can collide with another local project on `localhost:5173`).

  Verify all of the following:
  1. Click "+ Nova etapa" → a modal titled "Nova etapa" opens (not a native browser prompt).
  2. The "Inserir depois de" select is pre-filled with the last column's name (e.g. "Perda").
  3. Type a name, leave the select on its default, click "Criar etapa" → the new column appears
     as the last column, same as the old behavior.
  4. Click "+ Nova etapa" again, pick a middle stage (e.g. "Em contato") from the select, type a
     name, confirm → the new column appears immediately after "Em contato" and before whatever
     came next.
  5. Reload the page (`F5`) → the inserted column stays in the same place (confirms the order
     came from the backend, not just local optimistic state).
  6. Try to confirm with an empty name → the "Criar etapa" button stays disabled.

- [ ] **Step 7: Commit**

  ```bash
  cd apps/web
  git add src/features/crm/CrmPage.tsx
  git commit -m "feat: modal de nova etapa do funil com seleção de posição de inserção"
  ```

## Self-Review Notes

- **Spec coverage:** Design doc §2 (scope: insert-only, no reorder) → Task 1 + Task 2 fully cover
  it; §3 backend algorithm → Task 1 Step 4 implements it verbatim; §3 frontend modal + default-
  to-last → Task 2 Steps 2-4; §4 test list → Task 1 Step 1 (all 5 cases, cross-tenant case
  explicitly and deliberately omitted per the design doc's own note on SQLite/RLS).
- **Placeholder scan:** no TBD/TODO; every step has literal code or literal commands with
  expected output.
- **Type consistency:** `after_stage_id: str | None` matches from schema (Task 1 Step 3) through
  service (Step 4) through the frontend payload (Task 2 Step 4, `after_stage_id: afterStageId ||
  null`). `PipelineStage` shape used in Task 2 matches `packages/shared-types/src/index.ts:197-203`
  exactly (`id`, `name`, `position`, `is_won`, `is_lost` — no `is_archived`, which is fine since
  `board.columns` already only contains active stages).
