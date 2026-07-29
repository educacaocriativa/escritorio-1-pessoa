import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
        <Topbar />
      </PageActionsProvider>
    </MemoryRouter>,
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

// Task 11 — a correção do problema original: sem slot próprio, o comprovante era arquivado em
// "Contrato". O aviso avisa quando há comprovantes da bandeja (recebidos pelo celular) ainda sem
// vínculo com nenhuma conta, para o usuário não esquecer de resolvê-los depois.
describe("PagarPage — bandeja de comprovantes (Task 11)", () => {
  it("mostra o aviso quando há comprovantes aguardando", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills") return Promise.resolve({ data: [] } as never);
      if (url === "/payables/receipts")
        return Promise.resolve({
          data: [
            {
              id: "r-1",
              filename: "a.pdf",
              content_type: "application/pdf",
              size: 1,
              created_at: "2026-07-28T10:00:00Z",
            },
            {
              id: "r-2",
              filename: "b.pdf",
              content_type: "application/pdf",
              size: 1,
              created_at: "2026-07-28T11:00:00Z",
            },
          ],
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();

    await waitFor(() => screen.getByText(/2 comprovantes aguardando/i));
  });

  // Achado de campo (produção): o contêiner da tabela usava `overflow-hidden`, que CORTA em vez
  // de rolar — em tela estreita a coluna Status e os botões de ação (Editar/Marcar paga/
  // Estornar) ficavam invisíveis, sem nenhum jeito de alcançá-los. `overflow-x-auto` (mesmo
  // padrão de DrePage/LucratividadePage) torna a tabela rolável em vez de clipada.
  it("a tabela de contas é rolável horizontalmente, não cortada (overflow-x-auto)", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({
          data: [{
            id: "b-1", description: "Aluguel", category: "Estrutura", supplier: "Imobiliária",
            amount_cents: 250000, due_date: "2099-08-05", status: "open", is_overdue: false,
            paid_at: null, recurrence: "none", recurrence_count: 1, recurrence_group: null,
            payment_code: "", attachment_url: "", created_at: "2026-01-01T00:00:00Z",
            tenant_id: "t-1", competence_date: null, chart_account_id: null, contract_id: null,
            cost_center_id: null,
          }],
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();

    const table = await screen.findByRole("table");
    expect(table.parentElement?.className).toContain("overflow-x-auto");
    expect(table.parentElement?.className).not.toContain("overflow-hidden");
  });

  it("não mostra o aviso com a bandeja vazia", async () => {
    // beforeEach já mocka /payables/receipts (via fallback) devolvendo [].
    renderPage();

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByText(/aguardando/i)).toBeNull();
  });
});
