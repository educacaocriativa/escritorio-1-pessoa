import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import SitesPage from "./SitesPage";

// issue #207 — `setPages(data)`: payload cru no setter, SEM operador nenhum.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <SitesPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

// Sem a guarda, `pages.length === 0` de um objeto é `undefined === 0` → falso, e o fluxo cai no
// `pages.map`, que estoura no render. Ver `src/test/assentar.ts` para por que o `assentar()`.
describe("SitesPage — lista de páginas fora de forma não derruba a tela (#207)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a tela mostra o estado vazio em vez de estourar", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    renderPage();
    await assentar();

    expect(screen.getByText('Nenhuma página ainda. Clique em "Nova página".')).toBeInTheDocument();
  });

  it("contra-teste: página de verdade continua chegando à grade", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: "p-1",
          title: "Landing de agosto",
          model: "captura",
          status: "published",
          public_slug: "landing-agosto",
        },
      ],
    } as never);
    renderPage();
    await assentar();

    expect(screen.getByText("Landing de agosto")).toBeInTheDocument();
    expect(screen.getByText("Captura de leads")).toBeInTheDocument();
  });
});
