import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

/** Uma conta de investimento real, para abrir o modal "Registrar rendimento". */
function contaDeInvestimento() {
  return [
    {
      id: "i-1", name: "CDB Banco X", kind: "CDB", index_rate_label: "110% CDI",
      principal: 1000, bank_account_id: null, archived_at: null,
    },
  ];
}

// ── `GET /chart-of-accounts?grupo=FINANCEIRO` fora de forma (issue #225) ─────────────────────
//
// `setFinanceiro(data)` (dentro de `RegisterYieldModal`) recebia o payload cru — e o PRÓPRIO
// `.then` já lia `data.length` e `data[0].id` ANTES de qualquer render, sem passar pelo estado.
// Um envelope de erro ou string quebraria dentro do `.then`, fora do alcance de qualquer
// try/catch da tela — não é só um `.map` no render, como nos outros sites.
describe("InvestimentosPage — categorias fora de forma não derrubam o modal Registrar rendimento (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → o modal abre, sem pré-selecionar categoria", async (_rotulo, payload) => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/investments") return Promise.resolve({ data: contaDeInvestimento() } as never);
      if (url === "/bank/accounts") return Promise.resolve({ data: [] } as never);
      if (url === "/chart-of-accounts") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: { total_yield: 0 } } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: /registrar rendimento/i }));
    await assentar();

    expect(screen.getByRole("heading", { name: "Registrar rendimento" })).toBeInTheDocument();
    expect(screen.getByText("(crie uma categoria no plano de contas)")).toBeInTheDocument();
  });

  it("contra-teste: categoria de verdade continua pré-selecionada", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/investments") return Promise.resolve({ data: contaDeInvestimento() } as never);
      if (url === "/bank/accounts") return Promise.resolve({ data: [] } as never);
      if (url === "/chart-of-accounts")
        return Promise.resolve({ data: [{ id: "ca-1", categoria: "Rendimentos" }] } as never);
      return Promise.resolve({ data: { total_yield: 0 } } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: /registrar rendimento/i }));
    await assentar();

    expect(await screen.findByText("Rendimentos")).toBeInTheDocument();
  });
});
