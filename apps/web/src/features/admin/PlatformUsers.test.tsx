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

// Story 7.20 — fixture com conteúdo real p/ exercitar OfficeCard (a 7.18 mockava []).
// Tipos completos (Tenant/User/TenantUsers) — sem campos opcionais, mesma lição da 7.18.
const adminUser = {
  id: "user-admin",
  tenant_id: "tenant-alpha",
  email: "dono@alpha.com",
  name: "Dono Alpha",
  role: "owner",
  allowed_modules: [],
  is_active: true,
  is_platform_admin: false,
  document: "12345678901",
  address: "Rua A, 1",
  phone: "27999990000",
  must_reset_password: false,
  created_at: "2026-01-01T00:00:00Z",
};
const staffUser = {
  id: "user-staff",
  tenant_id: "tenant-alpha",
  email: "func@alpha.com",
  name: "Funcionário Alpha",
  role: "sub_user",
  allowed_modules: ["crm"],
  is_active: true,
  is_platform_admin: false,
  document: "10987654321",
  address: "Rua B, 2",
  phone: "27988880000",
  must_reset_password: false,
  created_at: "2026-01-02T00:00:00Z",
};
const officeNode = {
  tenant: {
    id: "tenant-alpha",
    slug: "alpha",
    legal_name: "Escritório Alpha Ltda",
    document: "12345678901",
    created_at: "2026-01-01T00:00:00Z",
  },
  admin: adminUser,
  staff: [staffUser],
  customers: [],
  staff_count: 1,
  customer_count: 0,
};

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/admin/users") return Promise.resolve({ data: [officeNode] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
  vi.mocked(api.delete).mockReset();
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

describe("PlatformUsers/OfficeCard — suspender/excluir usuário: tratamento de erro (Story 7.20)", () => {
  // Abre o cartão do escritório para expor as linhas de usuário (Admin + funcionário).
  async function openCard(user: ReturnType<typeof userEvent.setup>) {
    renderPage();
    await user.click(await screen.findByText("Escritório Alpha Ltda"));
    // Confirma que o funcionário está visível (cartão expandido).
    expect(await screen.findByText("Funcionário Alpha")).toBeInTheDocument();
  }

  it("caminho infeliz (toggleUser falha): api.patch rejeita → erro no DOM e cartão segue renderizado (AC 1, 4, 5)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao suspender o usuário." } },
    });
    await openCard(user);

    // Botão "Suspender" (ícone Power): admin e staff estão ativos → duas ocorrências.
    // Ordem de render: Admin (dono) primeiro, funcionário depois → [1] é o staff.
    const suspendButtons = screen.getAllByTitle("Suspender");
    await user.click(suspendButtons[1]);

    expect(await screen.findByText("Falha ao suspender o usuário.")).toBeInTheDocument();
    // Cartão segue renderizado e interativo.
    expect(screen.getByText("Funcionário Alpha")).toBeInTheDocument();
    expect(screen.getAllByTitle("Suspender")[1]).toBeEnabled();
    // Sucesso não foi alcançado → onChanged() (reload via api.get) não recarregou por sucesso.
    expect(vi.mocked(api.patch)).toHaveBeenCalledWith("/admin/users/user-staff", { is_active: false });
  });

  it("caminho infeliz (removeUser falha): confirm=true e api.delete rejeita → erro no DOM e cartão segue renderizado (AC 2, 4, 6)", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api.delete).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao excluir o usuário." } },
    });
    await openCard(user);

    // Só o funcionário (staff) recebe o botão "Excluir" (admin não recebe onDelete).
    await user.click(screen.getByTitle("Excluir"));

    expect(await screen.findByText("Falha ao excluir o usuário.")).toBeInTheDocument();
    expect(screen.getByText("Funcionário Alpha")).toBeInTheDocument();
    expect(vi.mocked(api.delete)).toHaveBeenCalledWith("/admin/users/user-staff");
  });
});
