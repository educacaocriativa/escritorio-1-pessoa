import { describe, expect, it } from "vitest";
import {
  formatBRL,
  type Projection,
  runwayLabel,
  toPolylinePoints,
  trajectoryPoints,
} from "./projecao";

/**
 * Smoke test da lógica pura da projeção de caixa (Story 5.7). O projeto não tem infra de teste de
 * componente React — os testes de front são de lógica pura (ver dre.test.ts / planoContas.test.ts).
 * Cobre a trajetória (hoje + janelas), o mapeamento para a polyline do gráfico e o rótulo do runway.
 */
const projection = (over: Partial<Projection> = {}): Projection => ({
  today: "2026-07-11",
  saldo_inicial_cents: 90000,
  overdue_inflow_cents: 0,
  overdue_outflow_cents: 0,
  windows: [
    { days: 30, saldo_projetado_cents: 50000, alert: false },
    { days: 60, saldo_projetado_cents: -20000, alert: true },
    { days: 90, saldo_projetado_cents: -80000, alert: true },
  ],
  runway: { days: 90, burn_rate_cents_per_day: 1000 },
  notes: ["Regime de CAIXA."],
  ...over,
});

describe("trajectoryPoints", () => {
  it("começa em hoje (dia 0 = saldo inicial) e segue as janelas", () => {
    const pts = trajectoryPoints(projection());
    expect(pts).toEqual([
      { days: 0, saldo_cents: 90000 },
      { days: 30, saldo_cents: 50000 },
      { days: 60, saldo_cents: -20000 },
      { days: 90, saldo_cents: -80000 },
    ]);
  });
});

describe("toPolylinePoints", () => {
  it("mapeia os pontos para coordenadas dentro do viewBox (saldo maior = y menor)", () => {
    const pts = trajectoryPoints(projection());
    const poly = toPolylinePoints(pts, { width: 100, height: 40, padding: 0 });
    const coords = poly.split(" ").map((p) => p.split(",").map(Number));
    // 4 pontos, x crescente com os dias
    expect(coords).toHaveLength(4);
    expect(coords[0][0]).toBeLessThan(coords[3][0]);
    // o maior saldo (90000, primeiro ponto) fica no topo (y menor); o menor (-80000) no fundo
    const ys = coords.map((c) => c[1]);
    expect(Math.min(...ys)).toBe(ys[0]); // 90000 → topo
    expect(Math.max(...ys)).toBe(ys[3]); // -80000 → fundo
  });

  it("não divide por zero quando todos os saldos são iguais", () => {
    const flat = projection({
      saldo_inicial_cents: 1000,
      windows: [
        { days: 30, saldo_projetado_cents: 1000, alert: false },
        { days: 60, saldo_projetado_cents: 1000, alert: false },
        { days: 90, saldo_projetado_cents: 1000, alert: false },
      ],
    });
    const poly = toPolylinePoints(trajectoryPoints(flat), { width: 100, height: 40 });
    expect(poly).not.toContain("NaN");
  });

  it("retorna string vazia sem pontos", () => {
    expect(toPolylinePoints([], { width: 10, height: 10 })).toBe("");
  });
});

describe("runwayLabel", () => {
  it("converte dias em meses e dias (mês de 30 dias)", () => {
    expect(runwayLabel(90)).toBe("3 meses");
    expect(runwayLabel(45)).toBe("1 mês e 15 dias");
    expect(runwayLabel(1)).toBe("1 dia");
  });

  it("trata caixa crescente (null) e limite (0)", () => {
    expect(runwayLabel(null)).toContain("Sem risco");
    expect(runwayLabel(0)).toContain("0 dias");
  });
});

describe("formatBRL (reuso de dre.ts)", () => {
  it("formata centavos preservando sinal", () => {
    expect(formatBRL(90000)).toContain("900,00");
    expect(formatBRL(-80000)).toContain("-");
  });
});
