import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
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

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Issue #224 — separador de milhar no valor digitado (parseCentsBRL)
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// A conta manual antiga (`Math.round(parseFloat(v.replace(",", ".")) * 100)`) só troca a PRIMEIRA
// vírgula por ponto e nunca remove o ponto de milhar: "1.234,56" vira "1.234.56", `parseFloat` para
// no segundo ponto e devolve 1.234 → 123 centavos, não 123456. `parseCentsBRL` (contas.ts) trata o
// milhar corretamente; estes testes fixam esse contrato nos dois sites de ProdutosPage.
describe("ProdutosPage — separador de milhar (#224)", () => {
  it("Novo produto: '1.234,56' vira price_cents 123456, não 123", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo produto" }));
    await user.type(screen.getByLabelText("Nome"), "Mentoria anual");
    await user.type(screen.getByLabelText("Preço (R$)"), "1.234,56");
    await user.click(screen.getByRole("button", { name: "Criar produto" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/products",
      expect.objectContaining({ price_cents: 123456 }),
    );
  });

  it("Novo cupom (desconto fixo): '1.234,56' vira discount_value 123456, não 123", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Cupons" }));
    await user.click(await screen.findByRole("button", { name: "Novo cupom" }));
    await user.type(screen.getByLabelText("Código"), "PROMO1234");
    await user.selectOptions(screen.getByLabelText("Tipo"), "fixed");
    await user.type(screen.getByLabelText("Desconto (R$)"), "1.234,56");
    await user.click(screen.getByRole("button", { name: "Criar cupom" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/products/coupons",
      expect.objectContaining({ discount_value: 123456 }),
    );
  });
});

// ── `GET /products`, `/products/coupons`, `/products/enrollments` fora de forma (issue #252) ──
//
// `setProducts(p.data)`/`setCoupons(c.data)`/`setAlunos(e.data)` recebiam o payload CRU. Cada
// uma alimenta `.map`/`.length` direto no render da aba correspondente (grade de produtos,
// tabela de cupons, tabela de compradores), sem `Array.isArray` — um payload fora de forma
// faria `.map is not a function` estourar em qualquer uma das três abas.
describe("ProdutosPage — as três listas fora de forma não derrubam a tela (#252)", () => {
  it("products fora de forma → a aba Produtos mostra o estado vazio", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/products") return Promise.resolve({ data: { detail: "algo deu errado" } } as never);
      if (url === "/products/coupons") return Promise.resolve({ data: [] } as never);
      if (url === "/products/enrollments") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByRole("heading", { name: "Produtos" })).toBeInTheDocument();
    expect(await screen.findByText("Nenhum produto ainda.")).toBeInTheDocument();
  });

  it("coupons fora de forma → a aba Cupons mostra o estado vazio", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/products") return Promise.resolve({ data: [] } as never);
      if (url === "/products/coupons") return Promise.resolve({ data: "não é json" } as never);
      if (url === "/products/enrollments") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Cupons" }));
    await assentar();

    expect(await screen.findByText("Nenhum cupom.")).toBeInTheDocument();
  });

  it("alunos (compradores) fora de forma → a aba Compradores mostra o estado vazio", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/products") return Promise.resolve({ data: [] } as never);
      if (url === "/products/coupons") return Promise.resolve({ data: [] } as never);
      if (url === "/products/enrollments") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Compradores" }));
    await assentar();

    expect(await screen.findByText("Nenhum comprador ainda.")).toBeInTheDocument();
  });

  it("contra-teste: produto/cupom/comprador de verdade continuam aparecendo", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/products")
        return Promise.resolve({
          data: [{ id: "p-1", name: "Curso de React", kind: "digital", price_cents: 19700, active: true, students: 3, checkout_url: "https://x" }],
        } as never);
      if (url === "/products/coupons")
        return Promise.resolve({
          data: [{ id: "c-1", code: "PROMO10", discount_type: "percent", discount_value: 10, uses: 2, max_uses: null, active: true }],
        } as never);
      if (url === "/products/enrollments")
        return Promise.resolve({
          data: [{ id: "e-1", name: "Maria", email: "maria@x.com", product_name: "Curso de React", amount_cents: 19700, status: "active" }],
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("Curso de React")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cupons" }));
    expect(await screen.findByText("PROMO10")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Compradores" }));
    expect(await screen.findByText("Maria")).toBeInTheDocument();
  });
});
