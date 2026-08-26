import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
import ContratoDrePage from "./ContratoDrePage";

// Rede sempre mockada (IV2): nenhum teste bate em /contracts ou /cost-centers reais.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/contratos/ct-1/dre"]}>
      <Routes>
        <Route path="/contratos/:id/dre" element={<ContratoDrePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ── `GET /cost-centers` fora de forma (issue #225) ─────────────────────────────
//
// `setCostCenters(r.data)` recebia o payload CRU. O filtro por centro de custo (linha ~109) só
// aparece atrás de `costCenters.length > 0`, mas o `.then` já chamava `setCostCenters(payload)`
// direto — um objeto/string sem `.length` numérico passaria a checagem de forma inconsistente
// dependendo do shape (ex.: string TEM `.length`, e um `.map` sobre string quebra igual). A
// guarda no setter fecha os dois caminhos ao mesmo tempo.
describe("ContratoDrePage — centros de custo fora de forma não derrubam a página (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → a página segue montada, sem o filtro de centro de custo", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers") return Promise.resolve({ data: payload } as never);
      if (url === "/contracts/ct-1") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: null } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Página / Contratos / DRE")).toBeInTheDocument();
    expect(screen.queryByLabelText("Filtrar por centro de custo")).not.toBeInTheDocument();
  });

  it("contra-teste: centro de custo de verdade continua aparecendo no filtro", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers")
        return Promise.resolve({
          data: [{ id: "cc-1", name: "Sócio João", kind: "socio", is_archived: false }],
        } as never);
      if (url === "/contracts/ct-1") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: null } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByLabelText("Filtrar por centro de custo")).toBeInTheDocument();
    expect(screen.getByText("Sócio João")).toBeInTheDocument();
  });
});

/** DRE de contrato válido, com os TRÊS campos array que a página lê sem `?.`. */
function dreValido() {
  return {
    contract_id: "ct-1",
    start: "2026-08-01",
    end: "2026-08-31",
    receita: { grupo_dre: "RECEITA", total_cents: 500000, categorias: [] },
    custo_direto: { grupo_dre: "CUSTO_DIRETO", total_cents: 100000, categorias: [] },
    receita_cents: 500000,
    custo_direto_cents: 100000,
    margem_contribuicao_cents: 400000,
    margem_contribuicao_pct: 0.8,
    outros_resultado_cents: 0,
    resultado_cents: 400000,
    fixed_costs_allocated_cents: 0,
    overhead_allocated_cents: 0,
    break_even_reachable: true,
    notes: [],
  };
}

// ── `GET /financial-intelligence/contracts/{id}/dre` fora de forma (issue #247) ─────────
//
// `setDre(data)` recebia o payload CRU. `GroupRow` faz `group.categorias.reduce` sem `?.`, e o
// render faz `view.notes.length` sem `?.` — `Array.isArray`, no molde de `CrmPage.tsx` (#225), nos
// TRÊS campos array aninhados (`notes`, `receita.categorias`, `custo_direto.categorias`).
describe("ContratoDrePage — DRE fora de forma não derruba a página (#247)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["objeto sem a chave notes", { ...dreValido(), notes: undefined }],
    ["receita sem categorias", { ...dreValido(), receita: { grupo_dre: "RECEITA", total_cents: 0 } }],
    [
      "custo_direto.categorias não é array",
      { ...dreValido(), custo_direto: { ...dreValido().custo_direto, categorias: "x" } },
    ],
    ["array no lugar do objeto (raiz certa, campo errado)", [{ contract_id: "ct-1" }]],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a página segue montada, sem as métricas", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers") return Promise.resolve({ data: [] } as never);
      if (url === "/contracts/ct-1") return Promise.resolve({ data: null } as never);
      if (url === "/financial-intelligence/contracts/ct-1/dre")
        return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: null } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Página / Contratos / DRE")).toBeInTheDocument();
    expect(screen.queryByText("Margem de contribuição")).not.toBeInTheDocument();
  });

  it("contra-teste: DRE de verdade continua mostrando as métricas", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers") return Promise.resolve({ data: [] } as never);
      if (url === "/contracts/ct-1") return Promise.resolve({ data: null } as never);
      if (url === "/financial-intelligence/contracts/ct-1/dre")
        return Promise.resolve({ data: dreValido() } as never);
      return Promise.resolve({ data: null } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("Margem de contribuição")).toBeInTheDocument();
  });
});
