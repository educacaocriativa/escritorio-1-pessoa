import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import CentrosCustoPage from "./CentrosCustoPage";

// Rede sempre mockada (IV2): nenhum teste bate em /cost-centers real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

function renderPage() {
  return render(
    <PageActionsProvider>
      <CentrosCustoPage />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/cost-centers") return Promise.resolve({ data: [] } as never);
    if (url === "/financial-intelligence/by-cost-center")
      return Promise.resolve({
        data: { start: "2026-08-01", end: "2026-08-31", buckets: [], notes: [] },
      } as never);
    return Promise.resolve({ data: [] } as never);
  });
});

// ── `GET /financial-intelligence/by-cost-center` fora de forma (issue #247) ─────────────
//
// `setReport(r.data)` recebia o payload CRU. `report.buckets.length`/`.map` (dentro de
// `ComparativeCard`) rodam sem `?.` — `Array.isArray`, no molde de `CrmPage.tsx` (#225). A guarda
// é por CAMPO, com `null` de fallback: a mesma render já checa `report && report.buckets...`.
describe("CentrosCustoPage — comparativo fora de forma não derruba a tela (#247)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["objeto sem a chave buckets", { start: "2026-08-01", end: "2026-08-31" }],
    ["array no lugar do objeto (raiz certa, campo errado)", [{ name: "x" }]],
    ["string no lugar do objeto", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela segue montada, sem o comparativo", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers") return Promise.resolve({ data: [] } as never);
      if (url === "/financial-intelligence/by-cost-center")
        return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Centros de custo")).toBeInTheDocument();
    expect(screen.queryByTestId("comparativo-centros")).not.toBeInTheDocument();
  });

  it("contra-teste: comparativo de verdade continua aparecendo", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers") return Promise.resolve({ data: [] } as never);
      if (url === "/financial-intelligence/by-cost-center")
        return Promise.resolve({
          data: {
            start: "2026-08-01",
            end: "2026-08-31",
            buckets: [
              {
                cost_center_id: "cc-1",
                name: "Sócio A",
                kind: "socio",
                receita_cents: 100000,
                resultado_cents: 50000,
                lancamentos: 3,
              },
            ],
            notes: [],
          },
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByTestId("comparativo-centros")).toBeInTheDocument();
  });
});
