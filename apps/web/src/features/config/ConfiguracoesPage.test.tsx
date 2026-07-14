import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ConfiguracoesPage from "./ConfiguracoesPage";

// Story 7.18 — Task 3. Rede sempre mockada (IV2): nenhum teste bate em /settings real.
// getGoogleStatus/getGoogleConnectUrl/disconnectGoogle são exports nomeados de lib/api usados
// pela GoogleSection → mockados (Google "não configurado", sem chamada de rede real).
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  getGoogleStatus: vi.fn(() =>
    Promise.resolve({ configured: false, connected: false, email: null }),
  ),
  getGoogleConnectUrl: vi.fn(),
  disconnectGoogle: vi.fn(),
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// TenantProfile COMPLETO (16 campos, sem opcionais) — fixture parcial quebraria os inputs
// controlados (Task 3). Dados fictícios (sem PII real).
const profile = {
  display_name: "Empresa Fictícia",
  document: "12.345.678/0001-90",
  email: "contato@example.com",
  phone: "27999990000",
  address: "Rua Teste, 100",
  website: "https://example.com",
  about: "Sobre fictício",
  logo_url: "",
  primary_color: "#5D44F8",
  secondary_color: "#111827",
  accent_color: "#3CD3A4",
  text_color: "#111827",
  bg_color: "#FFFFFF",
  font: "Inter",
  timezone: "America/Sao_Paulo",
  default_entry_funnel_id: null,
};

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/settings/profile") return Promise.resolve({ data: profile } as never);
    if (url === "/funnels") return Promise.resolve({ data: [] } as never);
    if (url === "/integrations/leads/keys") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: {} } as never);
  });
  vi.mocked(api.patch).mockReset();
});

// A cor "Cor primária" tem um par <input type="color"> + <input> de texto sem <label> associado
// (o rótulo é um <span> irmão). Alcançamos o input de texto pelo container do rótulo.
function primaryColorTextInput(): HTMLInputElement {
  const label = screen.getByText("Cor primária");
  const group = label.closest("div") as HTMLElement;
  return group.querySelector('input:not([type="color"])') as HTMLInputElement;
}

describe("ConfiguracoesPage — Brand Kit (Story 7.18, Task 3)", () => {
  it("caminho feliz: edita a cor primária e salva → PATCH /settings/profile + 'Salvo HH:MM'", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockResolvedValue({
      data: { ...profile, primary_color: "#123456" },
    } as never);
    render(<ConfiguracoesPage />);

    await screen.findByText("Cor primária"); // espera o profile carregar
    // datetime/color/hex frágeis no user-event → fireEvent.change com o hex inteiro.
    fireEvent.change(primaryColorTextInput(), { target: { value: "#123456" } });

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(vi.mocked(api.patch)).toHaveBeenCalled());
    expect(vi.mocked(api.patch)).toHaveBeenCalledWith(
      "/settings/profile",
      expect.objectContaining({ primary_color: "#123456" }),
    );
    expect(await screen.findByText(/Salvo \d{1,2}:\d{2}/)).toBeInTheDocument();
  });

  it("caminho infeliz: erro do backend é exibido sem travar a tela (botão reabilitado)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao salvar as configurações." } },
    });
    render(<ConfiguracoesPage />);

    await screen.findByText("Cor primária");
    fireEvent.change(primaryColorTextInput(), { target: { value: "#123456" } });
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    expect(await screen.findByText("Falha ao salvar as configurações.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
  });
});

describe("ConfiguracoesPage — Funil de entrada padrão", () => {
  it("lista os funis e envia default_entry_funnel_id ao salvar", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/settings/profile") return Promise.resolve({ data: profile } as never);
      if (url === "/funnels") {
        return Promise.resolve({
          data: [{ id: "f-1", name: "Funil Principal", node_count: 3, created_at: "" }],
        } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    vi.mocked(api.patch).mockResolvedValue({
      data: { ...profile, default_entry_funnel_id: "f-1" },
    } as never);
    render(<ConfiguracoesPage />);

    const select = await screen.findByText("Funil Principal");
    expect(select).toBeInTheDocument();

    await user.selectOptions(screen.getByDisplayValue("Nenhum (não inscrever automaticamente)"), "f-1");
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() =>
      expect(vi.mocked(api.patch)).toHaveBeenCalledWith(
        "/settings/profile",
        expect.objectContaining({ default_entry_funnel_id: "f-1" }),
      ),
    );
  });
});

describe("ConfiguracoesPage — aba Integrações", () => {
  it("troca pra aba Integrações e lista as chaves", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/settings/profile") return Promise.resolve({ data: profile } as never);
      if (url === "/integrations/leads/keys") {
        return Promise.resolve({
          data: [{ id: "k-1", label: "Site Dóro", key_prefix: "abcd1234", revoked_at: null, created_at: "" }],
        } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    render(<ConfiguracoesPage />);

    await screen.findByText("Cor primária"); // espera o profile carregar
    await user.click(screen.getByRole("button", { name: /Integrações/ }));

    expect(await screen.findByText("Site Dóro")).toBeInTheDocument();
  });
});
