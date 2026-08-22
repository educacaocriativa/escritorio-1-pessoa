import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import MarketingPage from "./MarketingPage";

// issue #207 — `setCarousels(data)`: payload cru no setter, SEM operador nenhum.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <MarketingPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

// Sem a guarda, `carousels.length === 0` de um objeto é `undefined === 0` → falso, e o fluxo cai
// no `carousels.map`, que estoura no render. O `assentar()` é o que traz esse estouro para dentro
// da asserção — ver `src/test/assentar.ts`.
describe("MarketingPage — lista de carrosséis fora de forma não derruba a tela (#207)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a tela mostra o estado vazio em vez de estourar", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    renderPage();
    await assentar();

    expect(
      screen.getByText('Nenhum carrossel ainda. Clique em "Novo carrossel".'),
    ).toBeInTheDocument();
  });

  it("contra-teste: carrossel de verdade continua chegando à grade", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: "c-1",
          topic: "Lançamento de agosto",
          status: "ready",
          slides: [{ title: "Slide 1", body: "corpo" }],
        },
      ],
    } as never);
    renderPage();
    await assentar();

    expect(screen.getByText("Lançamento de agosto")).toBeInTheDocument();
    expect(screen.getByTestId("abrir-carrossel-c-1")).toBeInTheDocument();
  });
});
