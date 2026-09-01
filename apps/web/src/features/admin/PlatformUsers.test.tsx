import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { navSections } from "../../app/navigation";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import PlatformUsers, { MODULES } from "./PlatformUsers";

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
    // `delay: null` (em vez do default `0`) pula o `setTimeout` REAL entre cada tecla do
    // `userEvent.type()`. Com `delay: 0` o user-event ainda faz `await` numa Promise resolvida
    // por `setTimeout(fn, 0)` a cada caractere — sob contenção de CPU (várias worktrees/CI
    // concorrente) esse `setTimeout(0)` pode custar dezenas de ms cada, e este teste digita ~80
    // caracteres em 7 campos. Medido (issue #231): 2,1-2,4s isolado neste arquivo → risco real
    // de aproximar-se do `testTimeout` de 15000ms sob carga, como o próprio `vitest.config.ts`
    // documenta. `delay: null` não simula tempo nenhum (nem precisa de fake timers): ele só
    // remove a espera artificial entre eventos de teclado, sem mudar o que é digitado/disparado.
    const user = userEvent.setup({ delay: null });
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
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
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
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
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
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
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

// ── Editar permissões de um funcionário já cadastrado ─────────────────────────────────────────
//
// Até aqui `allowed_modules` só era definido na criação (`AddStaffModal`) — não havia nenhum jeito
// de VER ou AJUSTAR depois pela UI. O Master tinha de inspecionar a resposta de `GET /admin/users`
// no DevTools para descobrir por que um item da sidebar sumiu para um funcionário.
describe("PlatformUsers/OfficeCard — editar permissões de um funcionário (EditPermissionsModal)", () => {
  async function openCard(user: ReturnType<typeof userEvent.setup>) {
    renderPage();
    await user.click(await screen.findByText("Escritório Alpha Ltda"));
    expect(await screen.findByText("Funcionário Alpha")).toBeInTheDocument();
  }

  it("só o funcionário (staff) recebe o botão de editar — o dono sempre vê tudo, editar não teria efeito", async () => {
    const user = userEvent.setup({ delay: null });
    await openCard(user);

    expect(screen.getAllByTitle("Editar permissões")).toHaveLength(1);
  });

  it("abre pré-preenchido com os módulos ATUAIS do usuário, e salvar envia só o que está marcado", async () => {
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
    await openCard(user);

    await user.click(screen.getByTitle("Editar permissões"));
    expect(await screen.findByRole("heading", { name: "Permissões de Funcionário Alpha" })).toBeInTheDocument();

    // staffUser.allowed_modules = ["crm"]: o pill de CRM já nasce marcado (fundo roxo).
    expect(screen.getByRole("button", { name: "CRM" })).toHaveClass("bg-primary-500");
    expect(screen.getByRole("button", { name: "Configurações" })).not.toHaveClass("bg-primary-500");

    // Marca Configurações (o módulo que faltava para o Leonardo) e desmarca CRM.
    await user.click(screen.getByRole("button", { name: "Configurações" }));
    await user.click(screen.getByRole("button", { name: "CRM" }));
    await user.click(screen.getByRole("button", { name: "Salvar permissões" }));

    await waitFor(() =>
      expect(vi.mocked(api.patch)).toHaveBeenCalledWith("/admin/users/user-staff", {
        allowed_modules: ["settings"],
      }),
    );
  });

  it("desmarcar tudo salva lista VAZIA — é o valor que `hasModule` lê como acesso total, não ausência de mudança", async () => {
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
    await openCard(user);

    await user.click(screen.getByTitle("Editar permissões"));
    await screen.findByRole("heading", { name: "Permissões de Funcionário Alpha" });
    await user.click(screen.getByRole("button", { name: "CRM" })); // único módulo marcado (fixture)
    await user.click(screen.getByRole("button", { name: "Salvar permissões" }));

    await waitFor(() =>
      expect(vi.mocked(api.patch)).toHaveBeenCalledWith("/admin/users/user-staff", { allowed_modules: [] }),
    );
  });

  it("caminho infeliz: api.patch rejeita → erro no modal, e o modal NÃO fecha sozinho", async () => {
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
    vi.mocked(api.patch).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao salvar as permissões." } },
    });
    await openCard(user);

    await user.click(screen.getByTitle("Editar permissões"));
    await screen.findByRole("heading", { name: "Permissões de Funcionário Alpha" });
    await user.click(screen.getByRole("button", { name: "Salvar permissões" }));

    expect(await screen.findByText("Falha ao salvar as permissões.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Permissões de Funcionário Alpha" })).toBeInTheDocument();
  });
});

// ── A tela de confirmação não pode mentir sobre o envio (fix de 2026-08-05) ──────────────────
//
// Bug real de produção: o Master cadastrou um funcionário por WhatsApp e a tela disse
// "modo de teste (não saiu de verdade) — repasse a senha abaixo", com a caixa de senha VAZIA.
// Duas causas somadas: (a) `queued` (o status normal do WhatsApp desde a Onda 3) era tratado
// como falha, porque o código só aceitava `sent`; (b) em produção a API não devolve a senha
// (Story 2.1 AC3), e o JSX renderizava `{invite.temp_password}` cru — rótulo órfão sobre o nada.

async function cadastrarConta(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Nova conta" }));
  await user.type(screen.getByLabelText("Nome da empresa"), "Empresa Teste Ltda");
  await user.type(screen.getByLabelText("Subdomínio"), "empresa-teste");
  await user.type(screen.getByLabelText("Nome completo"), "Fulano de Tal");
  await user.type(screen.getByLabelText("CPF/CNPJ"), "12345678901");
  await user.type(screen.getByLabelText("WhatsApp"), "27999990000");
  await user.type(screen.getByLabelText("E-mail"), "fulano-teste@example.com");
  await user.type(screen.getByLabelText("Endereço"), "Rua Teste, 100");
  await user.click(screen.getByRole("button", { name: "Cadastrar e enviar senha" }));
  await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
}

describe("PlatformUsers — a confirmação do convite diz a verdade sobre a entrega", () => {
  it("'queued' é sucesso, não modo de teste", async () => {
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
    vi.mocked(api.post).mockResolvedValue({
      data: {
        temp_password: "senha-fake-123",
        delivery_status: "queued",
        delivery: "whatsapp",
        owner: { name: "Fulano de Tal" },
        tenant: { legal_name: "Empresa Teste Ltda" },
      },
    } as never);
    renderPage();
    await cadastrarConta(user);

    expect(await screen.findByRole("heading", { name: "Conta criada" })).toBeInTheDocument();
    expect(screen.queryByText(/modo de teste/i)).not.toBeInTheDocument();
    expect(screen.getByText(/enviada por WhatsApp/i)).toBeInTheDocument();
  });

  it("sem transporte: avisa que NÃO foi enviada", async () => {
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
    vi.mocked(api.post).mockResolvedValue({
      data: {
        temp_password: "senha-fake-123",
        delivery_status: "unconfigured",
        delivery: "whatsapp",
        owner: { name: "Fulano de Tal" },
        tenant: { legal_name: "Empresa Teste Ltda" },
      },
    } as never);
    renderPage();
    await cadastrarConta(user);

    expect(await screen.findByText(/não foi enviada/i)).toBeInTheDocument();
    // A senha veio no corpo (dev): continua à mão para o Master repassar.
    expect(screen.getByText("senha-fake-123")).toBeInTheDocument();
  });

  it("sem senha no corpo (produção): nenhuma caixa de senha vazia", async () => {
    const user = userEvent.setup({ delay: null }); // ver nota de perf no 1o teste deste arquivo
    vi.mocked(api.post).mockResolvedValue({
      data: {
        temp_password: null,
        delivery_status: "queued",
        delivery: "whatsapp",
        owner: { name: "Fulano de Tal" },
        tenant: { legal_name: "Empresa Teste Ltda" },
      },
    } as never);
    renderPage();
    await cadastrarConta(user);

    expect(await screen.findByRole("heading", { name: "Conta criada" })).toBeInTheDocument();
    expect(screen.queryByText("Senha temporária")).not.toBeInTheDocument();
  });
});

// ── `GET /admin/users` fora de forma (issue #207) ─────────────────────────────
//
// `setNodes(data)` recebia o payload CRU, sem operador nenhum. `nodes.reduce` roda dentro do
// `useMemo` dos totais, em tempo de RENDER — fora do alcance de qualquer `catch` do `load`. E o
// app não tem ErrorBoundary: o `TypeError` não deixa a lista vazia, desmonta a árvore inteira.
//
// ⚠️ O `assentar()` é a metade que MATA o mutante: sem ele o `getByText` acerta o estado vazio
// INICIAL e passa antes de o payload chegar ao setter. Ver `src/test/assentar.ts`.
describe("PlatformUsers — lista de contas fora de forma não derruba a aba (#207)", () => {
  function mockUsers(payload: unknown) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/admin/users") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a aba mostra o estado vazio em vez de estourar", async (_rotulo, payload) => {
    mockUsers(payload);
    renderPage();
    await assentar();

    expect(screen.getByText("Nenhuma conta ainda.")).toBeInTheDocument();
  });

  it("contra-teste: escritório de verdade continua listado", async () => {
    mockUsers([officeNode]);
    renderPage();
    await assentar();

    expect(screen.getByText("Escritório Alpha Ltda")).toBeInTheDocument();
    expect(screen.queryByText("Nenhuma conta ainda.")).not.toBeInTheDocument();
  });
});

// ── Gate: todo módulo de negócio da sidebar precisa poder ser CONCEDIDO pelo admin ────────────
//
// `MODULES` (o seletor de `AddStaffModal`/`EditPermissionsModal`) é uma cópia manual do conjunto
// de `item.module` de `app/navigation.ts` — foi divergirem que deixou o Master sem como conceder
// `settings` a um funcionário (o item já existia na sidebar desde a RBAC de 2026-08-25; a caixa
// para marcá-lo nunca existiu neste seletor). Sem um gate mecânico, a próxima rota nova com
// `module` ganha o mesmo destino: aparece na sidebar de quem tem o módulo, e não há como o Master
// concedê-la a mais ninguém — o defeito é silencioso, porque a tela de admin continua "funcionando".
describe("PlatformUsers — o seletor de módulos do admin cobre toda a sidebar (issue Leonardo/settings)", () => {
  it("todo `module` usado em algum item de navigation.ts está no seletor de permissões", () => {
    const modulosDaSidebar = new Set(
      navSections
        .flatMap((secao) => secao.items)
        .map((item) => item.module)
        .filter((m): m is string => Boolean(m)),
    );
    const modulosDoSeletor = new Set(MODULES.map((m) => m.key));

    const faltando = [...modulosDaSidebar].filter((m) => !modulosDoSeletor.has(m));

    expect(faltando).toEqual([]);
  });

  it("contra-teste: o gate REALMENTE falha quando um módulo da sidebar não está no seletor", () => {
    const modulosDaSidebar = new Set(
      navSections
        .flatMap((secao) => secao.items)
        .map((item) => item.module)
        .filter((m): m is string => Boolean(m)),
    );
    const seletorSemSettings = new Set(MODULES.filter((m) => m.key !== "settings").map((m) => m.key));

    const faltando = [...modulosDaSidebar].filter((m) => !seletorSemSettings.has(m));

    expect(faltando).toEqual(["settings"]);
  });
});
