import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import CobrancasPage from "./CobrancasPage";

// Story 7.5 — Task 2. Rede sempre mockada (IV2): nenhum teste bate em /receivables real.
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
  paid_cents: 0,
  open_count: 0,
  overdue_count: 0,
};

// Estratégia (a) da Task 0 — replica o contrato da topbar sem importar o AppShell.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <CobrancasPage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/receivables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/receivables/charges") return Promise.resolve({ data: [] } as never);
    if (url === "/crm/clients") return Promise.resolve({ data: [] } as never);
    if (url === "/contracts") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("CobrancasPage — Nova cobrança (Story 7.5, Task 2)", () => {
  it("caminho feliz: cria cobrança com valor + vencimento; POST com amount_cents coerente", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova cobrança" }));

    await user.type(screen.getByLabelText("Valor (R$)"), "150,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-09-10" } });

    await user.click(screen.getByRole("button", { name: "Gerar cobrança" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/receivables/charges",
      expect.objectContaining({ amount_cents: 15000, due_date: "2026-09-10" }),
    );
  });

  it("caminho infeliz: erro do backend é exibido sem quebrar a tela (modal segue aberto)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Vencimento inválido." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova cobrança" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "150,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-09-10" } });
    await user.click(screen.getByRole("button", { name: "Gerar cobrança" }));

    expect(await screen.findByText("Vencimento inválido.")).toBeInTheDocument();
    // Título do modal (heading) — desambigua do botão "Nova cobrança" da topbar.
    expect(screen.getByRole("heading", { name: "Nova cobrança" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerar cobrança" })).toBeEnabled();
  });
});
