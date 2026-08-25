import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import FunisPage from "./FunisPage";

// issue #207 — `setFunnels(data)`: payload cru no setter, SEM operador nenhum. Rede sempre
// mockada (IV2).
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <FunisPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

// ── `GET /funnels` fora de forma (issue #207) ────────────────────────────────
//
// Sem a guarda, `funnels.length` de um objeto é `undefined`, `undefined === 0` é falso, e o fluxo
// cai justamente no `funnels.map` — que estoura no RENDER, fora do alcance do `.then`. O app não
// tem ErrorBoundary: isso desmonta a árvore inteira, não só esta lista.
//
// ⚠️ O `assentar()` é a metade que MATA o mutante: sem ele o `getByText` acerta o estado vazio
// INICIAL e passa antes de o payload chegar ao setter. Ver `src/test/assentar.ts`.
describe("FunisPage — lista de funis fora de forma não derruba a tela (#207)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a tela mostra o estado vazio em vez de estourar", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    renderPage();
    await assentar();

    expect(screen.getByText('Nenhum funil ainda. Clique em "Novo funil".')).toBeInTheDocument();
  });

  it("contra-teste: funil de verdade continua chegando à grade", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "f-1", name: "Funil de vendas", node_count: 3 }],
    } as never);
    renderPage();
    await assentar();

    expect(screen.getByText("Funil de vendas")).toBeInTheDocument();
    expect(screen.getByTestId("abrir-funil-f-1")).toBeInTheDocument();
  });
});
