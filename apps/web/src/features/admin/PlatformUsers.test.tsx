import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import PlatformUsers from "./PlatformUsers";

// Story 7.18 — Task 4. Rede sempre mockada (IV2): nenhum teste bate em /admin real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Estratégia (a) da Task 0: o botão "Nova conta" vive na topbar. Topbar de teste local.
// Testamos PlatformUsers (folha) diretamente, sem AdminDashboard (só adiciona abas por cima).
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <PlatformUsers />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/admin/users") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("PlatformUsers — cadastrar nova conta (Story 7.18, Task 4)", () => {
  it("caminho feliz: preenche os obrigatórios e cadastra → POST /admin/accounts + senha temporária", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({
      data: {
        temp_password: "senha-fake-123",
        delivery_status: "sent",
        delivery: "email",
        owner: { name: "Fulano de Tal" },
        tenant: { legal_name: "Empresa Teste Ltda" },
      },
    } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova conta" }));

    await user.type(screen.getByLabelText("Nome da empresa"), "Empresa Teste Ltda");
    await user.type(screen.getByLabelText("Subdomínio"), "empresa-teste");
    await user.type(screen.getByLabelText("Nome completo"), "Fulano de Tal");
    await user.type(screen.getByLabelText("CPF/CNPJ"), "12345678901"); // 11 dígitos fictícios
    await user.type(screen.getByLabelText("WhatsApp"), "27999990000"); // 8+ dígitos
    await user.type(screen.getByLabelText("E-mail"), "fulano-teste@example.com");
    await user.type(screen.getByLabelText("Endereço"), "Rua Teste, 100");

    await user.click(screen.getByRole("button", { name: "Cadastrar e enviar senha" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/admin/accounts", {
      legal_name: "Empresa Teste Ltda",
      slug: "empresa-teste",
      document: "12345678901",
      name: "Fulano de Tal",
      email: "fulano-teste@example.com",
      address: "Rua Teste, 100",
      phone: "27999990000",
      delivery: "email",
    });
    // Tela de confirmação com a senha temporária.
    expect(await screen.findByText("senha-fake-123")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Conta criada" })).toBeInTheDocument();
  });

  it("caminho infeliz: formulário incompleto mantém o botão disabled, SEM chamar a API", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova conta" }));

    // Preenche tudo MENOS o CPF/CNPJ (document) → `valid` fica false.
    await user.type(screen.getByLabelText("Nome da empresa"), "Empresa Teste Ltda");
    await user.type(screen.getByLabelText("Subdomínio"), "empresa-teste");
    await user.type(screen.getByLabelText("Nome completo"), "Fulano de Tal");
    await user.type(screen.getByLabelText("WhatsApp"), "27999990000");
    await user.type(screen.getByLabelText("E-mail"), "fulano-teste@example.com");
    await user.type(screen.getByLabelText("Endereço"), "Rua Teste, 100");

    const btn = screen.getByRole("button", { name: "Cadastrar e enviar senha" });
    expect(btn).toBeDisabled();
    await user.click(btn); // clique num botão desabilitado não dispara o onClick
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  });
});
