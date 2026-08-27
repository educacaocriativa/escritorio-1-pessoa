import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import EstoquePage from "./EstoquePage";

// Story 7.16 — Task 1. Rede sempre mockada (IV2): nenhum teste bate em /stock real.
// `apiErrorMessage` mockado para devolver o `detail` do backend (o real depende de
// `instanceof AxiosError`, que um erro forjado no teste não satisfaz).
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

const emptySummary = { item_count: 0, total_value_cents: 0, low_stock_count: 0 };

// Estratégia (a) da Task 0 (Dev Agent Record da 7.5): o botão "Novo item" vive na topbar
// (AppShell), fora do escopo da página. Este componente local replica o contrato real da
// topbar — consome `usePageActions().action` — sem importar o AppShell inteiro.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <EstoquePage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/stock/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/stock/items") return Promise.resolve({ data: [] } as never);
    if (url === "/products") return Promise.resolve({ data: [] } as never); // NewItemModal no open
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("EstoquePage — Novo item de estoque (Story 7.16, Task 1)", () => {
  it("caminho feliz: cria item com nome preenchido; POST /stock/items com o nome digitado", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    // Abre o modal via o contrato da topbar (usePrimaryAction("Novo item", ...)).
    await user.click(await screen.findByRole("button", { name: "Novo item" }));

    await user.type(screen.getByLabelText("Nome"), "Camiseta P");
    // "Custo unitário" preenchido com "12,50" deve virar unit_cost_cents: 1250.
    await user.type(screen.getByLabelText("Custo unitário (R$)"), "12,50");

    await user.click(screen.getByRole("button", { name: "Criar item" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/stock/items",
      expect.objectContaining({ name: "Camiseta P", unit_cost_cents: 1250 }),
    );
  });

  it("caminho infeliz: erro do backend é exibido sem travar a tela (botão reabilitado)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao criar item de estoque." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo item" }));
    await user.type(screen.getByLabelText("Nome"), "Camiseta P");
    await user.click(screen.getByRole("button", { name: "Criar item" }));

    // Mensagem de erro no DOM, tela intacta: o modal continua aberto e o botão volta a habilitar.
    expect(await screen.findByText("Falha ao criar item de estoque.")).toBeInTheDocument();
    expect(screen.getByText("Novo item de estoque")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Criar item" })).toBeEnabled();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Issue #224 — separador de milhar no valor digitado (parseCentsBRL)
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// A conta manual antiga (`Math.round(parseFloat(v.replace(",", ".")) * 100)`) só troca a PRIMEIRA
// vírgula por ponto e nunca remove o ponto de milhar: "1.234,56" vira "1.234.56", `parseFloat` para
// no segundo ponto e devolve 1.234 → 123 centavos, não 123456. `parseCentsBRL` (contas.ts) trata o
// milhar corretamente; este teste fixa esse contrato no único site de EstoquePage.
describe("EstoquePage — separador de milhar (#224)", () => {
  it("'1.234,56' vira unit_cost_cents 123456, não 123", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo item" }));
    await user.type(screen.getByLabelText("Nome"), "Notebook usado");
    await user.type(screen.getByLabelText("Custo unitário (R$)"), "1.234,56");
    await user.click(screen.getByRole("button", { name: "Criar item" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/stock/items",
      expect.objectContaining({ unit_cost_cents: 123456 }),
    );
  });
});

// ── `GET /products` fora de forma (issue #225) ──────────────────────────────────
//
// `setProducts(data)` recebia o payload CRU. `products.map` (select "Ligar a um produto") está
// SEM guarda de `.length` — dispara assim que o modal "Novo item" abre.
describe("EstoquePage — produtos fora de forma não derrubam o modal Novo item (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → o modal abre, com o select de produto vazio", async (_rotulo, payload) => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/stock/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/stock/items") return Promise.resolve({ data: [] } as never);
      if (url === "/products") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Novo item" }));
    await assentar();

    expect(screen.getByLabelText("Nome")).toBeInTheDocument();
    expect(screen.getByText("Não ligar")).toBeInTheDocument();
  });

  it("contra-teste: produto de verdade continua aparecendo no select", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/stock/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/stock/items") return Promise.resolve({ data: [] } as never);
      if (url === "/products") return Promise.resolve({ data: [{ id: "p-1", name: "Camiseta P" }] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Novo item" }));
    await assentar();

    // "Camiseta P" também é o nome digitado no teste feliz acima, mas cada teste remonta a
    // página — aqui só a opção do select existe.
    expect(await screen.findByText("Camiseta P")).toBeInTheDocument();
  });
});

// ── `GET /stock/summary` fora de forma (issue #247) ─────────────────────────────────────
//
// `setSummary(s.data)` recebia o payload CRU. `summary.item_count`/`total_value_cents`/
// `low_stock_count` são lidos direto nos três cartões do topo, sem `?.` — uma raiz fora de forma
// (array, string, corpo vazio) faz `null.item_count` estourar. A guarda é por TIPO da raiz.
describe("EstoquePage — resumo fora de forma não derruba a tela (#247)", () => {
  it.each([
    ["array no lugar do objeto", [{ item_count: 3 }]],
    ["string no lugar do objeto", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela segue montada, com os cartões zerados", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/stock/summary") return Promise.resolve({ data: payload } as never);
      if (url === "/stock/items") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Controle de Estoque")).toBeInTheDocument();
    expect(screen.getByText("Itens ativos")).toBeInTheDocument();
    expect(screen.getAllByText("0").length).toBeGreaterThan(0);
  });

  it("contra-teste: resumo de verdade continua aparecendo nos cartões", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/stock/summary")
        return Promise.resolve({
          data: { item_count: 7, total_value_cents: 12345, low_stock_count: 2 },
        } as never);
      if (url === "/stock/items") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.getByText("R$ 123,45")).toBeInTheDocument();
  });
});

// ── `GET /stock/items` fora de forma (issue #252) ────────────────────────────────────────
//
// `setItems(i.data)` recebia o payload CRU. `items.map`/`.length` rodam direto no render (a
// tabela) sem `Array.isArray` — um payload fora de forma faria `items.map is not a function`
// estourar.
describe("EstoquePage — lista de itens fora de forma não derruba a tela (#252)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela segue montada, com o estado vazio", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/stock/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/stock/items") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Controle de Estoque")).toBeInTheDocument();
    expect(
      await screen.findByText('Nenhum item. Clique em "Novo item".'),
    ).toBeInTheDocument();
  });

  it("contra-teste: item de verdade continua aparecendo na tabela", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/stock/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/stock/items")
        return Promise.resolve({
          data: [{ id: "i-1", name: "Camiseta P", quantity: 10, unit: "un", unit_cost_cents: 100, value_cents: 1000, low: false, min_quantity: 0 }],
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("Camiseta P")).toBeInTheDocument();
  });
});
