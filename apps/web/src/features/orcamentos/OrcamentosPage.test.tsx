import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import OrcamentosPage from "./OrcamentosPage";

// Story 7.5 — Task 4 (aprovação). Rede sempre mockada (IV2): nenhum teste bate em /quotes real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

const emptySummary = { draft_count: 0, sent_cents: 0, approved_cents: 0, approved_count: 0 };
const sentQuote = {
  id: "q-42",
  client_name: "Maria",
  title: "Consultoria tributária",
  total_cents: 250000,
  status: "sent",
};

// OrcamentosPage usa useNavigate (Router) e usePrimaryAction (PageActionsProvider).
function renderPage() {
  return render(
    <PageActionsProvider>
      <MemoryRouter>
        <OrcamentosPage />
      </MemoryRouter>
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/quotes/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/quotes") return Promise.resolve({ data: [sentQuote] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OrcamentosPage — aprovar orçamento (Story 7.5, Task 4)", () => {
  it("caminho feliz: confirmar a aprovação chama POST /quotes/{id}/approve (gera cobrança)", async () => {
    const user = userEvent.setup();
    // A ação "Aprovar" é financeiramente sensível: o código pede confirm() nativo antes do POST.
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Aprovar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/quotes/q-42/approve");
  });

  it("caminho infeliz/cancelamento: recusar o confirm() NÃO chama a API (sem quebrar a tela)", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Aprovar" }));

    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    // A tela continua funcional: o orçamento segue na lista.
    expect(screen.getByText("Consultoria tributária")).toBeInTheDocument();
  });
});
