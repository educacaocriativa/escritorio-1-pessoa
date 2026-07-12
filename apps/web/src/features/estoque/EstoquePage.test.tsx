import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
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
