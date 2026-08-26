import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import ContratosPage from "./ContratosPage";

// Rede sempre mockada (IV2): nenhum teste bate em /contracts real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

vi.mock("../../store/auth", () => ({ useFuso: () => "America/Sao_Paulo" }));

function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <ContratosPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/contracts/summary")
      return Promise.resolve({
        data: { draft_count: 0, sent_count: 0, signed_count: 0 },
      } as never);
    if (url === "/contracts") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
});

// ── `GET /contracts/summary` fora de forma (issue #247) ─────────────────────────────────
//
// `setSummary(s.data)` recebia o payload CRU. `summary.draft_count`/`sent_count`/`signed_count`
// são lidos direto nos três cartões, sem `?.` — uma raiz fora de forma (array, string, corpo
// vazio) faz `null.draft_count` estourar. A guarda é por TIPO da raiz.
describe("ContratosPage — resumo fora de forma não derruba a tela (#247)", () => {
  it.each([
    ["array no lugar do objeto", [{ draft_count: 3 }]],
    ["string no lugar do objeto", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela segue montada, com os cartões zerados", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/contracts/summary") return Promise.resolve({ data: payload } as never);
      if (url === "/contracts") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Contratos")).toBeInTheDocument();
    expect(screen.getByText("Rascunhos")).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
  });

  it("contra-teste: resumo de verdade continua aparecendo nos cartões", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/contracts/summary")
        return Promise.resolve({
          data: { draft_count: 4, sent_count: 2, signed_count: 9 },
        } as never);
      if (url === "/contracts") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("4")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });
});
