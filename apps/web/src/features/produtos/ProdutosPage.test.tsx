import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import ProdutosPage from "./ProdutosPage";

// Story 7.16 — Task 2. Rede sempre mockada (IV2): nenhum teste bate em /products real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Estratégia (a) da Task 0: o botão "Novo produto" (aba default "produtos") vive na topbar.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <ProdutosPage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/products") return Promise.resolve({ data: [] } as never);
    if (url === "/products/coupons") return Promise.resolve({ data: [] } as never);
    if (url === "/products/enrollments") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("ProdutosPage — Novo produto (Story 7.16, Task 2)", () => {
  it("caminho feliz: cria produto com nome + preço; POST /products com price_cents coerente", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    // Aba default é "produtos" → usePrimaryAction registra "Novo produto".
    await user.click(await screen.findByRole("button", { name: "Novo produto" }));

    await user.type(screen.getByLabelText("Nome"), "Curso de React");
    // "197,00" (com vírgula) deve virar price_cents: 19700.
    await user.type(screen.getByLabelText("Preço (R$)"), "197,00");

    await user.click(screen.getByRole("button", { name: "Criar produto" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/products",
      expect.objectContaining({ name: "Curso de React", price_cents: 19700 }),
    );
  });

  it("caminho infeliz: erro do backend é exibido sem travar a tela (botão reabilitado)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao criar produto." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo produto" }));
    await user.type(screen.getByLabelText("Nome"), "Curso de React");
    await user.type(screen.getByLabelText("Preço (R$)"), "197,00");
    await user.click(screen.getByRole("button", { name: "Criar produto" }));

    expect(await screen.findByText("Falha ao criar produto.")).toBeInTheDocument();
    // Título do modal (h2) — desambigua do botão "Novo produto" da topbar (role button).
    expect(screen.getByRole("heading", { name: "Novo produto" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Criar produto" })).toBeEnabled();
  });
});
