import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import QuoteBuilderPage from "./QuoteBuilderPage";

// Story 7.5 — Task 4 (criação). Rede sempre mockada (IV2): nenhum teste bate em /quotes real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Perfil (Brand Kit) herdado no mount de um orçamento novo.
const profile = {
  logo_url: "",
  primary_color: "#5D44F8",
  bg_color: "#FFFFFF",
  text_color: "#1F2937",
  accent_color: "#3DD68C",
};

// Quote válido devolvido pelo POST feliz (hydrate() lê muitos campos).
const savedQuote = {
  id: "q-1",
  public_slug: "slug-1",
  status: "draft",
  title: "Proposta comercial",
  client_id: null,
  items: [{ description: "Consultoria", subtitle: "", quantity: 1, unit_price_cents: 100000 }],
  discount_cents: 0,
  client_name: "",
  client_whatsapp: "",
  payment_terms: "",
  show_gallery: false,
  gallery: [],
  show_schedule: false,
  schedule: [],
  show_contract: false,
  contract_text: "",
  logo_url: "",
  primary_color: "#5D44F8",
  bg_color: "#FFFFFF",
  text_color: "#1F2937",
  accent_color: "#3DD68C",
};

function renderNew() {
  return render(
    <MemoryRouter initialEntries={["/orcamentos/novo"]}>
      <Routes>
        <Route path="/orcamentos/:id" element={<QuoteBuilderPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/crm/clients") return Promise.resolve({ data: [] } as never);
    if (url === "/settings/profile") return Promise.resolve({ data: profile } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
});

describe("QuoteBuilderPage — salvar orçamento (Story 7.5, Task 4)", () => {
  it("caminho feliz: título + ao menos um serviço → POST /quotes com o item preenchido", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: savedQuote } as never);
    renderNew();

    // Aba "Serviços" é a inicial: título da proposta + descrição do 1º serviço.
    await user.type(screen.getByPlaceholderText("Proposta comercial"), "Proposta comercial");
    await user.type(screen.getByPlaceholderText("Título exibido"), "Consultoria");

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/quotes",
      expect.objectContaining({
        title: "Proposta comercial",
        items: [expect.objectContaining({ description: "Consultoria" })],
      }),
    );
  });

  it("caminho infeliz: sem título/serviço é bloqueado client-side, SEM chamar a API", async () => {
    const user = userEvent.setup();
    renderNew();

    // Formulário vazio (título vazio + serviço sem descrição → items.length === 0).
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    expect(
      await screen.findByText("Informe um título e ao menos um serviço."),
    ).toBeInTheDocument();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    expect(vi.mocked(api.patch)).not.toHaveBeenCalled();
  });
});
