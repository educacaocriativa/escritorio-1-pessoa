import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
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
