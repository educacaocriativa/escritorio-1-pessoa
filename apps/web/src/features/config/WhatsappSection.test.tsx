import type { TenantProfile, WhatsappTemplate } from "@e1p/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import WhatsappSection from "./WhatsappSection";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

function profile(overrides: Partial<TenantProfile> = {}): TenantProfile {
  return {
    display_name: "Empresa",
    document: "",
    email: "",
    phone: "",
    address: "",
    website: "",
    about: "",
    logo_url: "",
    primary_color: "#000",
    secondary_color: "#000",
    accent_color: "#000",
    text_color: "#000",
    bg_color: "#fff",
    font: "Inter",
    timezone: "America/Sao_Paulo",
    default_entry_funnel_id: null,
    whatsapp_configured: false,
    whatsapp_phone_id: "",
    whatsapp_waba_id: "",
    ...overrides,
  };
}

function template(overrides: Partial<WhatsappTemplate> = {}): WhatsappTemplate {
  return {
    id: "t-1",
    name: "boas_vindas",
    language: "pt_BR",
    category_requested: "MARKETING",
    category_approved: null,
    status: "PENDING",
    rejected_reason: null,
    meta_template_id: null,
    body_text: "Olá {{1}}",
    variable_count: 1,
    variable_examples: ["João"],
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

function mockGet(p: TenantProfile, templates: WhatsappTemplate[] = []) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/settings/profile") return Promise.resolve({ data: p } as never);
    if (url === "/whatsapp-templates") return Promise.resolve({ data: templates } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
  vi.mocked(api.delete).mockReset();
});

describe("WhatsappSection — credenciais", () => {
  it("mostra 'Não conectado' quando whatsapp_configured é false", async () => {
    mockGet(profile({ whatsapp_configured: false }));
    render(<WhatsappSection />);

    expect(await screen.findByText("Não conectado")).toBeInTheDocument();
    expect(screen.queryByText("Conectado")).not.toBeInTheDocument();
  });

  it("mostra 'Conectado' quando whatsapp_configured é true", async () => {
    mockGet(
      profile({
        whatsapp_configured: true,
        whatsapp_phone_id: "phone-123",
        whatsapp_waba_id: "waba-456",
      }),
    );
    render(<WhatsappSection />);

    expect(await screen.findByText("Conectado")).toBeInTheDocument();
    expect(screen.getByDisplayValue("phone-123")).toBeInTheDocument();
    expect(screen.getByDisplayValue("waba-456")).toBeInTheDocument();
  });

  it("salva com payload mínimo (sem whatsapp_token) quando o token não foi tocado", async () => {
    const user = userEvent.setup();
    mockGet(
      profile({ whatsapp_configured: true, whatsapp_phone_id: "phone-123", whatsapp_waba_id: "waba-456" }),
    );
    vi.mocked(api.patch).mockResolvedValue({
      data: profile({ whatsapp_configured: true, whatsapp_phone_id: "phone-999", whatsapp_waba_id: "waba-456" }),
    } as never);
    render(<WhatsappSection />);

    await screen.findByText("Conectado");
    const phoneInput = screen.getByDisplayValue("phone-123");
    await user.clear(phoneInput);
    await user.type(phoneInput, "phone-999");

    const saveButtons = screen.getAllByRole("button", { name: /Salvar/ });
    await user.click(saveButtons[0]);

    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/settings/profile", {
        whatsapp_phone_id: "phone-999",
        whatsapp_waba_id: "waba-456",
      }),
    );
  });

  it("inclui whatsapp_token no payload quando o campo é editado", async () => {
    const user = userEvent.setup();
    mockGet(profile({ whatsapp_configured: false }));
    vi.mocked(api.patch).mockResolvedValue({ data: profile({ whatsapp_configured: true }) } as never);
    render(<WhatsappSection />);

    await screen.findByText("Não conectado");
    const tokenInput = screen.getByPlaceholderText("Cole o token de acesso");
    await user.type(tokenInput, "meu-token-secreto");

    const saveButtons = screen.getAllByRole("button", { name: /Salvar/ });
    await user.click(saveButtons[0]);

    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/settings/profile", {
        whatsapp_phone_id: "",
        whatsapp_waba_id: "",
        whatsapp_token: "meu-token-secreto",
      }),
    );
  });
});

describe("WhatsappSection — templates", () => {
  it("mostra dica quando as credenciais não estão configuradas", async () => {
    mockGet(profile({ whatsapp_configured: false }));
    render(<WhatsappSection />);

    expect(
      await screen.findByText("Configure as credenciais do WhatsApp acima primeiro."),
    ).toBeInTheDocument();
  });

  it("lista templates com badge de status e categoria solicitada vs aprovada", async () => {
    mockGet(profile({ whatsapp_configured: true }), [
      template({
        name: "promo_verao",
        status: "APPROVED",
        category_requested: "MARKETING",
        category_approved: "UTILITY",
      }),
    ]);
    render(<WhatsappSection />);

    expect(await screen.findByText(/promo_verao/)).toBeInTheDocument();
    expect(screen.getByText("Aprovado")).toBeInTheDocument();
    expect(screen.getByText("solicitado: Marketing → aprovado: Utilidade")).toBeInTheDocument();
  });

  it("mostra o motivo da rejeição quando presente", async () => {
    mockGet(profile({ whatsapp_configured: true }), [
      template({ status: "REJECTED", rejected_reason: "Conteúdo promocional não permitido" }),
    ]);
    render(<WhatsappSection />);

    expect(await screen.findByText("Conteúdo promocional não permitido")).toBeInTheDocument();
  });

  it("sincroniza um template chamando o endpoint correto", async () => {
    const user = userEvent.setup();
    mockGet(profile({ whatsapp_configured: true }), [template({ id: "t-1" })]);
    vi.mocked(api.post).mockResolvedValue({ data: template({ id: "t-1", status: "APPROVED" }) } as never);
    render(<WhatsappSection />);

    await screen.findByText(/boas_vindas/);
    await user.click(screen.getByTitle("Sincronizar"));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/whatsapp-templates/t-1/sync"));
  });

  it("exclui um template com confirmação e recarrega a lista", async () => {
    const user = userEvent.setup();
    mockGet(profile({ whatsapp_configured: true }), [template({ id: "t-1" })]);
    vi.mocked(api.delete).mockResolvedValue({ data: {} } as never);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<WhatsappSection />);

    await screen.findByText(/boas_vindas/);
    await user.click(screen.getByTitle("Excluir"));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/whatsapp-templates/t-1"));
  });

  it("o formulário de criação rastreia {{n}} no corpo do texto com inputs de exemplo dinâmicos", async () => {
    const user = userEvent.setup();
    mockGet(profile({ whatsapp_configured: true }), []);
    render(<WhatsappSection />);

    await user.click(await screen.findByRole("button", { name: /Novo template/ }));
    const body = screen.getByPlaceholderText("Use {{1}}, {{2}} etc para variáveis");
    // fireEvent.change (não user.type) porque `{{` é sintaxe especial de tecla no user-event.
    fireEvent.change(body, { target: { value: "Olá {{1}}, seu pedido {{2}} está pronto" } });

    expect(await screen.findByText("Exemplo da variável 1")).toBeInTheDocument();
    expect(screen.getByText("Exemplo da variável 2")).toBeInTheDocument();
    expect(screen.queryByText("Exemplo da variável 3")).not.toBeInTheDocument();
  });

  it("mostra erro de validação (422/409) retornado pela API ao criar template", async () => {
    const user = userEvent.setup();
    mockGet(profile({ whatsapp_configured: true }), []);
    vi.mocked(api.post).mockRejectedValue({
      response: { data: { detail: "Template com esse nome e idioma já existe" } },
    });
    render(<WhatsappSection />);

    await user.click(await screen.findByRole("button", { name: /Novo template/ }));
    await user.type(screen.getByPlaceholderText("ex: boas_vindas_lead"), "duplicado");
    await user.type(
      screen.getByPlaceholderText("Use {{1}}, {{2}} etc para variáveis"),
      "Corpo sem variáveis",
    );

    await user.click(screen.getByRole("button", { name: "Criar template" }));

    expect(
      await screen.findByText("Template com esse nome e idioma já existe"),
    ).toBeInTheDocument();
  });
});
