import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import CockpitPage from "./CockpitPage";

// Story 7.15 — Task 3. Rede sempre mockada (IV2): nenhum teste bate em /cockpit real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// CockpitPage usa useAuth() (lança sem AuthProvider). Mockamos o store para não montar o provider
// (que registra um interceptor no `api` real — desnecessário e ruidoso no teste). `user` pode ser null.
vi.mock("../../store/auth", () => ({
  useAuth: () => ({ user: null }),
}));

const EMPTY = {
  agenda: { today_count: 0, today_events: [], upcoming_critical: [] },
  crm: { total_clients: 0, won_count: 0, lost_count: 0, conversion_rate: 0, by_stage: [] },
  finance: { available: false, net_revenue_cents: null, monthly_costs_cents: null, signed_contracts: null },
  overdue: [],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <CockpitPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

describe("CockpitPage — Cobrar com IA e resiliência (Story 7.15, Task 3)", () => {
  it("caminho feliz: 'Cobrar com IA' num cliente em atraso abre o modal com a mensagem gerada", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.startsWith("/cockpit/summary"))
        return Promise.resolve({
          data: {
            ...EMPTY,
            overdue: [
              {
                charge_id: "c-1",
                client_name: "Maria Teste",
                amount_cents: 5000,
                due_date: "2026-07-01",
                description: "Mensalidade",
              },
            ],
          },
        } as never);
      return Promise.resolve({ data: {} } as never);
    });
    vi.mocked(api.post).mockResolvedValue({
      data: { message: "Olá Maria, notamos uma pendência..." },
    } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Cobrar com IA" }));

    // POST no endpoint de collect do charge e o modal com a mensagem gerada.
    await waitFor(() =>
      expect(vi.mocked(api.post)).toHaveBeenCalledWith("/receivables/charges/c-1/collect"),
    );
    expect(await screen.findByText("Olá Maria, notamos uma pendência...")).toBeInTheDocument();
    expect(screen.getByText("Cobrança enviada pela IA")).toBeInTheDocument();
  });

  it("caminho infeliz: falha ao carregar /cockpit/summary não quebra a tela (resumo vazio)", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.startsWith("/cockpit/summary")) return Promise.reject(new Error("network 500"));
      return Promise.resolve({ data: {} } as never);
    });
    renderPage();

    // O .catch(() => setSummary(EMPTY)) já existente mantém a tela: StatCards montados,
    // "Compromissos Hoje" = 0, nenhuma seção "Clientes em atraso".
    expect(await screen.findByText("Compromissos Hoje")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(/Clientes em atraso/)).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Faturamento Líquido")).toBeInTheDocument();
    expect(screen.getByText("Taxa de Conversão")).toBeInTheDocument();
  });
});
