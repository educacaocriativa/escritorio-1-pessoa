import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import CrmPage from "./CrmPage";

// Story 7.15 — Task 1. Rede sempre mockada (IV2): nenhum teste bate em /crm real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Estratégia (a) da Task 0: o botão "Novo cliente" vive na topbar (AppShell). Topbar de teste local.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

// CrmPage usa <Card> com useNavigate → precisa de Router. Board vazio não renderiza cards,
// mas mantemos o MemoryRouter para robustez.
function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <CrmPage />
        <Topbar />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/crm/board") return Promise.resolve({ data: { columns: [] } } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("CrmPage — Novo cliente (Story 7.15, Task 1)", () => {
  it("caminho feliz: cria cliente com nome; POST /crm/clients com phone:null e tags:[]", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo cliente" }));

    await user.type(screen.getByLabelText("Nome"), "Maria Silva");
    await user.click(screen.getByRole("button", { name: "Criar cliente" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/crm/clients", {
      name: "Maria Silva",
      phone: null,
      tags: [],
    });
  });

  it("caminho infeliz: erro do backend é exibido sem travar a tela (modal aberto, botão reabilitado)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Nome já cadastrado." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo cliente" }));
    await user.type(screen.getByLabelText("Nome"), "Maria Silva");
    await user.click(screen.getByRole("button", { name: "Criar cliente" }));

    expect(await screen.findByText("Nome já cadastrado.")).toBeInTheDocument();
    // Modal segue aberto (título é heading, desambigua do botão da topbar) e botão reabilitado.
    expect(screen.getByRole("heading", { name: "Novo cliente" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Criar cliente" })).toBeEnabled();
  });
});
