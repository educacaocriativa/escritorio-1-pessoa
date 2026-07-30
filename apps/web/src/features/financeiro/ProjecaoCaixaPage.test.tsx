import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import type { Projection } from "./projecao";
import ProjecaoCaixaPage from "./ProjecaoCaixaPage";

/**
 * Teste de componente da Projeção de Caixa — **AC5 da Story 8.1**, o único AC cujo comportamento
 * vive só na tela (os demais são aferíveis pela resposta da API).
 *
 * ⚠️ **Desvio declarado pelo @dev:** a Story 8.1 (Task 5) previa cobertura de frontend apenas em
 * `projecao.test.ts` porque "o projeto não tem infra de teste de componente React". Essa premissa
 * ficou **desatualizada**: a Story 7.3 introduziu jsdom + @testing-library e deixou
 * `components/Modal.test.tsx` explicitamente como MODELO para cobertura de UI. Sem este arquivo, o
 * AC5 ficaria sendo o único AC da story aferido por inspeção visual — e ele guarda justamente o
 * erro mais caro possível aqui: exibir "Sem risco" no caso suprimido. Segue o modelo da 7.3
 * (render + screen + `vi.mock` da camada de API, nunca rede real).
 */
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

/** Estado REAL da Onda 0: origem `plataforma`, com queima e com janelas negativas. */
const projecaoSuprimida: Projection = {
  today: "2026-07-29",
  saldo_inicial_cents: 90000,
  saldo_inicial_origem: "plataforma",
  overdue_inflow_cents: 0,
  overdue_outflow_cents: 0,
  windows: [
    { days: 30, saldo_projetado_cents: -110000, alert: false, alert_suprimido: true },
    { days: 60, saldo_projetado_cents: -110000, alert: false, alert_suprimido: true },
    { days: 90, saldo_projetado_cents: -110000, alert: false, alert_suprimido: true },
  ],
  runway: { days: null, days_suprimido: true, burn_rate_cents_per_day: 1000 },
  notes: ["Regime de CAIXA: usa a data de pagamento prevista."],
};

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("ProjecaoCaixaPage — Story 8.1 (AC5): a tela declara a origem e não afirma o que não sabe", () => {
  it("no caso suprimido, diz INDISPONÍVEL e em nenhum lugar da tela diz 'sem risco'", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: projecaoSuprimida } as never);
    const { container } = render(<ProjecaoCaixaPage />);

    await waitFor(() => expect(screen.getByText(/Indisponível/)).toBeInTheDocument());
    // A frase aponta o MOTIVO, não uma indisponibilidade genérica.
    expect(screen.getByText(/saldo inicial não confirmado/i)).toBeInTheDocument();
    // ⚠️ O erro mais caro desta story: trocar "não sei" por "sem risco" (falso tranquilizador).
    expect(container.textContent?.toLowerCase()).not.toContain("sem risco");
    // Nem um fôlego em meses/dias: o valor exibido no lugar do runway é SÓ a indisponibilidade.
    // (`/\d+ dias/` sozinho não serviria — os cartões de janela dizem "Em 30 dias" legitimamente.)
    expect(screen.queryByText(/^\d+ (mês|meses)( e \d+ dias?)?$/)).toBeNull();
  });

  it("mostra a procedência colada ao saldo inicial (nenhum saldo sem origem na tela)", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: projecaoSuprimida } as never);
    render(<ProjecaoCaixaPage />);

    await waitFor(() => expect(screen.getByText("Saldo inicial de hoje")).toBeInTheDocument());
    // O rótulo do eixo A aparece na tela, e diz o que o número NÃO é.
    expect(screen.getAllByText(/disponível na Carteira e1p/).length).toBeGreaterThan(0);
    expect(screen.getByText(/não o da sua conta bancária/)).toBeInTheDocument();
  });

  it("suprime a AFIRMAÇÃO e NUNCA o NÚMERO: saldos e queima continuam visíveis", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: projecaoSuprimida } as never);
    const { container } = render(<ProjecaoCaixaPage />);

    await waitFor(() => expect(screen.getByText(/Indisponível/)).toBeInTheDocument());
    // Os três saldos projetados negativos continuam exibidos...
    expect(screen.getAllByText(/1\.100,00/).length).toBe(3);
    // ...e a queima diária, que NÃO está contaminada, também.
    expect(screen.getByText(/Queima de .*10,00 por dia/)).toBeInTheDocument();
    // O que sai é só o veredito.
    expect(container.textContent).not.toContain("Caixa fica negativo nesta janela");
  });

  it("o ÍCONE também é afirmação: sob supressão fica neutro, sem seta verde nem vermelha", async () => {
    // 3ª superfície contaminada da story. `cents >= 0 → TrendingUp verde` é o mesmo cruzamento de
    // limiar do `alert`, com polaridade invertida — e, como `available_cents` só cresce, a seta
    // verde apareceria justamente nas janelas em que o caixa verdadeiro pode estar apertado.
    // Cenário escolhido de propósito com saldo projetado POSITIVO: é onde o verde apareceria.
    vi.mocked(api.get).mockResolvedValue({
      data: {
        ...projecaoSuprimida,
        windows: projecaoSuprimida.windows.map((w) => ({ ...w, saldo_projetado_cents: 250000 })),
      } satisfies Projection,
    } as never);
    const { container } = render(<ProjecaoCaixaPage />);

    await waitFor(() => expect(screen.getAllByText(/2\.500,00/).length).toBe(3));
    // Nenhuma tendência afirmada: nem o verde do TrendingUp, nem o danger do AlertTriangle.
    expect(container.querySelectorAll(".text-emerald-500").length).toBe(0);
    expect(container.querySelectorAll(".text-danger").length).toBe(0);
    // ...e o glifo neutro está lá, um por janela (não é "sumiu o ícone", é "o ícone não afirma").
    expect(screen.getAllByLabelText("Tendência não informada").length).toBe(3);
  });

  it("com origem confirmada (Story 8.8), o ícone volta a colorir — a supressão é reversível", async () => {
    // O simétrico do teste acima: mesma tela, mesmos saldos positivos, flags em `false`. Prova de
    // que a 8.8 restaura o ícone SOZINHA, só trocando a origem — sem tocar neste componente.
    vi.mocked(api.get).mockResolvedValue({
      data: {
        ...projecaoSuprimida,
        saldo_inicial_origem: "misto",
        runway: { days: 43, days_suprimido: false, burn_rate_cents_per_day: 1000 },
        windows: projecaoSuprimida.windows.map((w) => ({
          ...w,
          saldo_projetado_cents: 250000,
          alert: false,
          alert_suprimido: false,
        })),
      } satisfies Projection,
    } as never);
    const { container } = render(<ProjecaoCaixaPage />);

    await waitFor(() => expect(screen.getAllByText(/2\.500,00/).length).toBe(3));
    expect(container.querySelectorAll(".text-emerald-500").length).toBe(3);
    expect(screen.queryAllByLabelText("Tendência não informada").length).toBe(0);
  });

  it("com origem confirmada (Story 8.8), a tela volta a afirmar — nada foi removido, só calado", async () => {
    // Prova de que a supressão é dirigida pelos flags do backend, não hard-coded na tela: mesmo
    // componente, origem `misto` e flags falsos → runway em dias e alerta vermelho de volta.
    vi.mocked(api.get).mockResolvedValue({
      data: {
        ...projecaoSuprimida,
        saldo_inicial_origem: "misto",
        runway: { days: 43, days_suprimido: false, burn_rate_cents_per_day: 1000 },
        windows: projecaoSuprimida.windows.map((w) => ({
          ...w,
          alert: true,
          alert_suprimido: false,
        })),
      } satisfies Projection,
    } as never);
    render(<ProjecaoCaixaPage />);

    await waitFor(() => expect(screen.getByText("1 mês e 13 dias")).toBeInTheDocument());
    expect(screen.getAllByText("Caixa fica negativo nesta janela").length).toBe(3);
    expect(screen.getByText(/conta bancária \+ Carteira e1p/)).toBeInTheDocument();
    expect(screen.queryByText(/Indisponível/)).toBeNull();
  });
});
