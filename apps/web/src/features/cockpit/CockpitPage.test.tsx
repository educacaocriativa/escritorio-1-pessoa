import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { TOTAL_EM_CONTAS_LABEL } from "../financeiro/contas";
import { ROTULO_BANCO } from "../financeiro/projecao";
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
// O fuso do TENANT é trocável por teste (mesmo modelo de `NewEventModal.test.tsx`). O
// `vitest.config.ts` fixa o fuso da MÁQUINA em America/Sao_Paulo; enquanto o tenant mockado for
// esse mesmo valor, `today(fuso)` e `localYmd(new Date())` devolvem o MESMO dia por construção, e
// um teste chamado "no fuso do tenant" passa mesmo com a tela lendo o fuso do NAVEGADOR.
let fusoDoTenant = "America/Sao_Paulo";
// Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner: sob ele os dois caminhos
// discordam, inclusive sobre que DIA é. É o único jeito de a asserção poder falhar.
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({
  useAuth: () => ({ user: null }),
  // O Cockpit pede `/cockpit/summary?day=` com o dia NO FUSO DO TENANT — sem isto o mock
  // derruba a tela antes de qualquer asserção.
  useFuso: () => fusoDoTenant,
}));

const EMPTY = {
  agenda: { today_count: 0, today_events: [], upcoming_critical: [] },
  crm: { total_clients: 0, won_count: 0, lost_count: 0, conversion_rate: 0, by_stage: [] },
  finance: {
    available: false,
    net_revenue_cents: null,
    monthly_costs_cents: null,
    signed_contracts: null,
    saldo_em_conta_cents: null,
    saldo_em_conta_origem: "indisponivel",
  },
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
  fusoDoTenant = "America/Sao_Paulo";
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

  /** O `?day=` efetivamente pedido ao servidor. */
  function diaPedido() {
    return vi
      .mocked(api.get)
      .mock.calls.find(([u]) => String(u).startsWith("/cockpit/summary"))?.[0];
  }

  it("pede o resumo do dia NO FUSO DO TENANT, não do dia UTC", async () => {
    // Às 23:30 em São Paulo já é o dia seguinte em UTC. O código antigo montava o parâmetro com
    // `new Date().toISOString().slice(0, 10)` e pedia ao servidor o resumo do dia SEGUINTE —
    // toda noite, das 21h à meia-noite, o Cockpit mostrava o dia errado.
    //
    // ⚠️ Este teste prova TENANT ≠ UTC, e SÓ isso: o tenant aqui é o mesmo fuso do runner, então
    // ele não distingue "dia do tenant" de "dia do navegador" — o teste irmão logo abaixo é quem
    // faz essa outra prova. Não "conserte" este trocando o fuso: a asserção UTC precisa de um
    // tenant a OESTE de Greenwich para existir.
    //
    // A data é deliberadamente distante de hoje: se os fake timers não pegassem, a asserção
    // cairia na data real e o teste falharia em vez de passar por engano.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2027-03-15T02:30:00Z")); // = 14/03/2027 23:30 em São Paulo
    vi.mocked(api.get).mockResolvedValue({ data: EMPTY } as never);

    renderPage();

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(diaPedido()).toBe("/cockpit/summary?day=2027-03-14"); // e NÃO ?day=2027-03-15 (o dia UTC)

    vi.useRealTimers();
  });

  it("pede o dia do TENANT, não o do NAVEGADOR", async () => {
    // Tenant em Tóquio (UTC+9), máquina em São Paulo (UTC−3, fixado pelo `vitest.config.ts`).
    // 14/03/2027 22:30Z é 15/03 07:30 em Tóquio, 14/03 19:30 em São Paulo e 14/03 em UTC — os
    // três discordam, e só quem lê pelo fuso do TENANT pede o dia 15.
    fusoDoTenant = FUSO_DISTANTE;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2027-03-14T22:30:00Z"));
    vi.mocked(api.get).mockResolvedValue({ data: EMPTY } as never);

    renderPage();

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    // `localYmd(new Date())` (fuso do navegador) e `toISOString().slice(0,10)` (UTC) dariam
    // ambos 2027-03-14 aqui: as duas mutações morrem nesta linha.
    expect(diaPedido()).toBe("/cockpit/summary?day=2027-03-15");

    vi.useRealTimers();
  });
});

describe("Onda 3 — os dois planos de dinheiro, lado a lado e nunca somados", () => {
  function mockFinance(over: Record<string, unknown>) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.startsWith("/cockpit/summary")) {
        return Promise.resolve({
          data: { ...EMPTY, finance: { ...EMPTY.finance, ...over } },
        } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
  }

  it("mostra o saldo em conta ao lado do faturamento, e NUNCA a soma dos dois", async () => {
    // Faturamento R$ 300 (plano 1) + em conta R$ 700 (plano 3). A soma — R$ 1.000,00 — é
    // proibida: um card único somando os planos é a mistura que produziu o bug do Epic 8.
    mockFinance({ net_revenue_cents: 300_00, saldo_em_conta_cents: 700_00, saldo_em_conta_origem: "banco" });
    renderPage();

    expect(await screen.findByText("R$ 700,00")).toBeInTheDocument();
    expect(screen.getByText("R$ 300,00")).toBeInTheDocument();
    expect(screen.getByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument();
    expect(screen.queryByText("R$ 1.000,00")).toBeNull();
  });

  it("sem conta cadastrada mostra travessão, não R$ 0,00", async () => {
    // Zero afirmaria "você não tem nada no banco" — falso, e indistinguível de um saldo
    // genuinamente zerado (princípio da Onda 0: suprimir a afirmação, nunca o número).
    mockFinance({ saldo_em_conta_cents: null, saldo_em_conta_origem: "indisponivel" });
    renderPage();

    expect(await screen.findByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument();
    expect(screen.queryByText("R$ 0,00")).toBeNull();
  });

  it("não usa o rótulo da Projeção ('no banco') — a colisão D-6/UX-001 não se repete aqui", async () => {
    mockFinance({ saldo_em_conta_cents: 700_00, saldo_em_conta_origem: "banco" });
    const { container } = renderPage();
    await screen.findByText(TOTAL_EM_CONTAS_LABEL);
    expect(container.textContent?.toLowerCase()).not.toContain(ROTULO_BANCO.toLowerCase());
  });
});
