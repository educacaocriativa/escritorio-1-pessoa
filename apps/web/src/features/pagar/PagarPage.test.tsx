import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import PagarPage from "./PagarPage";

// Story 7.5 — Task 1. Rede sempre mockada (IV2): nenhum teste bate em /payables real.
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

const emptySummary = {
  open_cents: 0,
  overdue_cents: 0,
  week_cents: 0,
  month_cents: 0,
  paid_month_cents: 0,
};

/**
 * Estratégia (a) da Task 0: o botão que abre o modal "Nova conta" vive na topbar (AppShell),
 * fora do escopo da página. Este componente local replica o contrato real da topbar — consome
 * `usePageActions().action` e renderiza `<button onClick={action.onClick}>{action.label}</button>`
 * — sem importar o AppShell inteiro.
 */
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <PagarPage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/payables/bills") return Promise.resolve({ data: [] } as never);
    if (url === "/contracts") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("PagarPage — Nova conta a pagar (Story 7.5, Task 1)", () => {
  it("caminho feliz: cria conta a pagar com valor + vencimento; POST com amount_cents coerente", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    // Abre o modal via o contrato da topbar (usePrimaryAction("Nova conta", ...)).
    await user.click(await screen.findByRole("button", { name: "Nova conta" }));

    // "250,00" (com vírgula) deve virar amount_cents: 25000 pelo parsing do componente.
    await user.type(screen.getByLabelText("Valor (R$)"), "250,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-08-01" } });

    await user.click(screen.getByRole("button", { name: "Adicionar conta" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/payables/bills",
      expect.objectContaining({ amount_cents: 25000, due_date: "2026-08-01" }),
    );
  });

  it("caminho infeliz: erro 422 do backend é exibido sem quebrar a tela (modal segue aberto)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Valor acima do teto permitido." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova conta" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "999999999,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-08-01" } });
    await user.click(screen.getByRole("button", { name: "Adicionar conta" }));

    // Mensagem de erro no DOM, tela intacta: o modal continua visível e o botão volta a habilitar.
    expect(await screen.findByText("Valor acima do teto permitido.")).toBeInTheDocument();
    expect(screen.getByText("Nova conta a pagar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adicionar conta" })).toBeEnabled();
  });
});
