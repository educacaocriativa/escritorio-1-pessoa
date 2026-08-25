import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import InvestimentosPage from "./InvestimentosPage";

// issue #207 — `setAccounts(data)` de `GET /investments`: payload cru no setter, SEM operador
// nenhum. `accounts.map` é o corpo da tela, e o mesmo `data` alimentava o `Promise.all` do `load`.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

const VAZIO = 'Nenhuma conta de investimento ainda. Clique em "Nova conta de investimento".';

/** Só `/investments` é corrompido — `/bank/accounts` fica válido para a falha ser atribuível. */
function mockInvestments(payload: unknown) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/investments") return Promise.resolve({ data: payload } as never);
    if (url === "/bank/accounts") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: { total_yield: 0 } } as never);
  });
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <InvestimentosPage />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("InvestimentosPage — lista de aplicações fora de forma não derruba a tela (#207)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a tela mostra o estado vazio em vez de estourar", async (_rotulo, payload) => {
    mockInvestments(payload);
    renderPage();
    await assentar();

    expect(screen.getByText(VAZIO)).toBeInTheDocument();
  });

  it("contra-teste: aplicação de verdade continua listada", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/investments")
        return Promise.resolve({
          data: [
            {
              id: "i-1",
              name: "CDB Banco X",
              kind: "CDB",
              index_rate_label: "110% CDI",
              principal: 1000,
              bank_account_id: null,
              archived_at: null,
            },
          ],
        } as never);
      if (url === "/bank/accounts") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: { total_yield: 0 } } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("CDB Banco X")).toBeInTheDocument();
    expect(screen.queryByText(VAZIO)).not.toBeInTheDocument();
  });
});
