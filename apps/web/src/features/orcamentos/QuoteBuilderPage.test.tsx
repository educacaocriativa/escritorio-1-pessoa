import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
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

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Issue #224 — separador de milhar no valor digitado (parseCentsBRL)
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// O `toCents` local desta tela (`Math.round(parseFloat((s||"").replace(",",".")||"0") * 100)`) só
// trocava a PRIMEIRA vírgula por ponto e nunca removia o ponto de milhar: "1.234,56" virava
// "1.234.56", `parseFloat` parava no segundo ponto e devolvia 1.234 → 123 centavos, não 123456. A
// #224 removeu o `toCents` local e trocou os 4 usos por `parseCentsBRL` (contas.ts), que trata o
// milhar corretamente. Os dois testes abaixo cobrem os dois SITES que recebem entrada distinta do
// usuário (preço do serviço e desconto — `subtotal`/`total`/`preview` derivam dos mesmos valores).
describe("QuoteBuilderPage — separador de milhar (#224)", () => {
  it("Valor unitário do serviço: '1.234,56' vira unit_price_cents 123456, não 123", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: savedQuote } as never);
    renderNew();

    await user.type(screen.getByPlaceholderText("Proposta comercial"), "Proposta comercial");
    await user.type(screen.getByPlaceholderText("Título exibido"), "Consultoria");
    await user.type(screen.getByLabelText("Valor unitário (R$)"), "1.234,56");

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/quotes",
      expect.objectContaining({
        items: [expect.objectContaining({ unit_price_cents: 123456 })],
      }),
    );
  });

  it("Desconto: '1.234,56' vira discount_cents 123456, não 123", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: savedQuote } as never);
    renderNew();

    await user.type(screen.getByPlaceholderText("Proposta comercial"), "Proposta comercial");
    await user.type(screen.getByPlaceholderText("Título exibido"), "Consultoria");
    await user.type(screen.getByLabelText("Desconto (R$)"), "1.234,56");

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/quotes",
      expect.objectContaining({ discount_cents: 123456 }),
    );
  });
});

// ── `GET /crm/clients` fora de forma (issue #225) ──────────────────────────────
//
// `setClients(data)` recebia o payload CRU. `clients.map` (aba "Dados", ~linha 497) está SEM
// guarda de `.length` — o crash só aparece quando o dono clica a aba, mas sem ErrorBoundary
// derruba o editor inteiro do orçamento na hora.
describe("QuoteBuilderPage — clientes fora de forma não derrubam a aba Dados (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → a aba Dados abre, com o select de cliente vazio", async (_rotulo, payload) => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/crm/clients") return Promise.resolve({ data: payload } as never);
      if (url === "/settings/profile") return Promise.resolve({ data: profile } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderNew();
    await assentar();

    await user.click(screen.getByRole("button", { name: "Dados" }));
    expect(screen.getByText("Cliente do CRM (opcional — gera a cobrança ao aprovar)")).toBeInTheDocument();
    expect(screen.getByText("Sem cliente do CRM")).toBeInTheDocument();
  });

  it("contra-teste: cliente de verdade continua aparecendo no select", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/crm/clients")
        return Promise.resolve({ data: [{ id: "c-1", name: "Maria Silva" }] } as never);
      if (url === "/settings/profile") return Promise.resolve({ data: profile } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderNew();
    await assentar();

    await user.click(screen.getByRole("button", { name: "Dados" }));
    expect(await screen.findByText("Maria Silva")).toBeInTheDocument();
  });
});
