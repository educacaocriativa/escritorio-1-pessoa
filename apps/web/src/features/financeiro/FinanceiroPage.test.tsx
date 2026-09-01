import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import FinanceiroPage from "./FinanceiroPage";

// Rede sempre mockada (IV2): nenhum teste bate em /wallet real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

const emptySummary = {
  available_cents: 0,
  pending_cents: 0,
  withdrawn_cents: 0,
  gross_total_cents: 0,
  fees_total_cents: 0,
};

// Estratégia (a): o botão "Registrar venda" vive na topbar (AppShell), fora do escopo da página.
// Este componente local replica o contrato real da topbar — consome `usePageActions().action` —
// sem importar o AppShell inteiro.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <FinanceiroPage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/wallet/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/wallet/transactions") return Promise.resolve({ data: [] } as never);
    if (url === "/chart-of-accounts") return Promise.resolve({ data: [] } as never);
    if (url === "/cost-centers") return Promise.resolve({ data: [] } as never);
    if (url === "/wallet/payouts") return Promise.resolve({ data: [] } as never);
    if (url === "/bank/accounts") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Issue #224 — separador de milhar no valor digitado (parseCentsBRL)
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// A conta manual antiga (`Math.round(parseFloat(v.replace(",", ".")) * 100)`) só troca a PRIMEIRA
// vírgula por ponto e nunca remove o ponto de milhar: "1.234,56" vira "1.234.56", `parseFloat` para
// no segundo ponto e devolve 1.234 → 123 centavos, não 123456. `parseCentsBRL` (contas.ts) trata o
// milhar corretamente; este teste fixa esse contrato no único site de FinanceiroPage.
describe("FinanceiroPage — separador de milhar (#224)", () => {
  it("Registrar venda: '1.234,56' vira gross_cents 123456, não 123", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Registrar venda" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "1.234,56");
    await user.click(screen.getByRole("button", { name: "Registrar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/wallet/transactions",
      expect.objectContaining({ gross_cents: 123456 }),
    );
  });
});

describe("FinanceiroPage — Registrar venda: documento/observações e anexo", () => {
  it("envia documento e observações no POST", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "tx-novo" } } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Registrar venda" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "150,00");
    await user.type(screen.getByLabelText("Documento (opcional)"), "NF-77");
    await user.type(screen.getByLabelText("Observações (opcional)"), "Pago na hora");
    await user.click(screen.getByRole("button", { name: "Registrar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/wallet/transactions",
      expect.objectContaining({ documento: "NF-77", observacoes: "Pago na hora" }),
    );
  });

  // A venda precisa de um `id` real ANTES de aceitar anexo (Attachments.tsx exige owner_id
  // existente) — por isso o modal não fecha ao salvar: ele troca para a fase de anexo.
  it("depois de registrar, o modal troca para a fase de anexo (sem fechar) e 'Concluir' fecha", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "tx-novo", description: "Consulta" } } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Registrar venda" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "150,00");
    await user.click(screen.getByRole("button", { name: "Registrar" }));

    expect(await screen.findByText(/Venda registrada: Consulta/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Contrato" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Comprovante" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Concluir" }));
    expect(screen.queryByRole("heading", { name: "Registrar venda" })).not.toBeInTheDocument();
  });
});

// ── `GET /wallet/summary` fora de forma (issue #247) ────────────────────────────────────
//
// `setSummary(s.data)` recebia o payload CRU. `summary.available_cents`/etc. são lidos direto nos
// cartões e no botão "Sacar" (`summary.available_cents > 0`), sem `?.` — uma raiz fora de forma
// (array, string, corpo vazio) faz `null.available_cents` estourar.
describe("FinanceiroPage — resumo fora de forma não derruba a tela (#247)", () => {
  it.each([
    ["array no lugar do objeto", [{ available_cents: 100 }]],
    ["string no lugar do objeto", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela segue montada, com os cartões zerados", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/wallet/summary") return Promise.resolve({ data: payload } as never);
      if (url === "/wallet/transactions") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Carteira")).toBeInTheDocument();
    expect(screen.getAllByText("R$ 0,00").length).toBeGreaterThan(0);
    // O botão só aparece quando `available_cents > 0` — com o resumo zerado, ele some.
    expect(screen.queryByRole("button", { name: /Sacar/ })).not.toBeInTheDocument();
  });

  it("contra-teste: resumo de verdade continua aparecendo nos cartões", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/wallet/summary")
        return Promise.resolve({
          data: {
            available_cents: 50000,
            pending_cents: 0,
            withdrawn_cents: 0,
            gross_total_cents: 50000,
            fees_total_cents: 0,
          },
        } as never);
      if (url === "/wallet/transactions") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("R$ 500,00")).toBeInTheDocument();
  });
});

// ── As CINCO leituras secundárias fora de forma (issue #252) ─────────────────────────────
//
// `setTxs(t.data)`/`setChartAccounts(ca.data)`/`setCostCenters(cc.data)`/`setPayouts(po.data)`/
// `setContas(bc.data)` recebiam o payload CRU. `txs.map`/`.length` roda na tabela principal; os
// outros quatro alimentam rótulos (`accountLabel`/`costCenterLabel`) e o `PayoutHistory` — um
// payload fora de forma faria `.map is not a function` estourar em qualquer um dos cinco.
describe("FinanceiroPage — as cinco leituras secundárias fora de forma (#252)", () => {
  it("txs fora de forma → tabela principal degrada para o estado vazio", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/wallet/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/wallet/transactions")
        return Promise.resolve({ data: { detail: "algo deu errado" } } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Carteira")).toBeInTheDocument();
    expect(
      await screen.findByText('Nenhuma transação. Clique em "Registrar venda".'),
    ).toBeInTheDocument();
  });

  it("chartAccounts/costCenters fora de forma → linha da transação não estoura, rótulo cai no '—'", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/wallet/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/wallet/transactions")
        return Promise.resolve({
          data: [
            {
              id: "t-1", kind: "service", method: "pix", description: "Consultoria",
              chart_account_id: "ca-1", cost_center_id: "cc-1",
              gross_cents: 10000, platform_fee_cents: 500, net_cents: 9500, status: "available",
            },
          ],
        } as never);
      if (url === "/chart-of-accounts") return Promise.resolve({ data: "não é json" } as never);
      if (url === "/cost-centers") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("Consultoria")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("payouts fora de forma → histórico de saques mostra o estado vazio", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/wallet/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/wallet/transactions") return Promise.resolve({ data: [] } as never);
      if (url === "/wallet/payouts") return Promise.resolve({ data: { detail: "erro" } } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(
      await screen.findByText("Nenhum saque ainda. O que você sacar aparece aqui e no extrato da sua conta."),
    ).toBeInTheDocument();
  });

  it("contas (bank/accounts) fora de forma → nome da conta de destino não estoura", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/wallet/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/wallet/transactions") return Promise.resolve({ data: [] } as never);
      if (url === "/wallet/payouts")
        return Promise.resolve({
          data: [{ id: "po-1", amount_cents: 5000, paid_on: "2026-08-01", bank_account_id: "acc-1", bank_transaction_id: "bt-1" }],
        } as never);
      if (url === "/bank/accounts") return Promise.resolve({ data: "não é json" } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    // Sem o nome resolvido (o `Object.fromEntries` ficou vazio), cai no fallback do próprio
    // `PayoutHistory` — a tela não estoura.
    expect(await screen.findByText("Conta removida")).toBeInTheDocument();
  });

  it("contra-teste: as cinco leituras de verdade continuam aparecendo", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/wallet/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/wallet/transactions")
        return Promise.resolve({
          data: [
            {
              id: "t-1", kind: "service", method: "pix", description: "Consultoria",
              chart_account_id: "ca-1", cost_center_id: "cc-1",
              gross_cents: 10000, platform_fee_cents: 500, net_cents: 9500, status: "available",
            },
          ],
        } as never);
      if (url === "/chart-of-accounts")
        return Promise.resolve({ data: [{ id: "ca-1", categoria: "Serviços" }] } as never);
      if (url === "/cost-centers")
        return Promise.resolve({ data: [{ id: "cc-1", name: "Sócio A" }] } as never);
      if (url === "/wallet/payouts")
        return Promise.resolve({
          data: [{ id: "po-1", amount_cents: 5000, paid_on: "2026-08-01", bank_account_id: "acc-1", bank_transaction_id: "bt-1" }],
        } as never);
      if (url === "/bank/accounts")
        return Promise.resolve({ data: [{ id: "acc-1", name: "Itaú PJ" }] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("Consultoria")).toBeInTheDocument();
    expect(screen.getByText("Serviços")).toBeInTheDocument();
    expect(screen.getByText("Sócio A")).toBeInTheDocument();
    expect(screen.getByText("Itaú PJ")).toBeInTheDocument();
  });
});
