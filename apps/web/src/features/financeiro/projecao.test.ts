import { describe, expect, it } from "vitest";
import {
  formatBRL,
  ORIGEM_LABEL,
  origemLabel,
  type Projection,
  type Runway,
  runwayLabel,
  toPolylinePoints,
  trajectoryPoints,
} from "./projecao";

/**
 * Smoke test da lógica pura da projeção de caixa (Story 5.7). O projeto não tem infra de teste de
 * componente React — os testes de front são de lógica pura (ver dre.test.ts / planoContas.test.ts).
 * Cobre a trajetória (hoje + janelas), o mapeamento para a polyline do gráfico e o rótulo do runway.
 *
 * **Story 8.1:** `runwayLabel` mudou de assinatura (`Runway` em vez de `days`) para que o caso
 * SUPRIMIDO não possa ser renderizado por engano como "sem risco" — o ramo mais valioso do frontend
 * nesta story. Também cobre o rótulo de procedência (`ORIGEM_LABEL`/`origemLabel`).
 */
const runway = (over: Partial<Runway> = {}): Runway => ({
  days: 90,
  days_suprimido: false,
  burn_rate_cents_per_day: 1000,
  ...over,
});

const projection = (over: Partial<Projection> = {}): Projection => ({
  today: "2026-07-11",
  saldo_inicial_cents: 90000,
  saldo_inicial_origem: "plataforma",
  overdue_inflow_cents: 0,
  overdue_outflow_cents: 0,
  windows: [
    { days: 30, saldo_projetado_cents: 50000, alert: false, alert_suprimido: false },
    { days: 60, saldo_projetado_cents: -20000, alert: true, alert_suprimido: false },
    { days: 90, saldo_projetado_cents: -80000, alert: true, alert_suprimido: false },
  ],
  runway: runway(),
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
        { days: 30, saldo_projetado_cents: 1000, alert: false, alert_suprimido: true },
        { days: 60, saldo_projetado_cents: 1000, alert: false, alert_suprimido: true },
        { days: 90, saldo_projetado_cents: 1000, alert: false, alert_suprimido: true },
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
    expect(runwayLabel(runway({ days: 90 }))).toBe("3 meses");
    expect(runwayLabel(runway({ days: 45 }))).toBe("1 mês e 15 dias");
    expect(runwayLabel(runway({ days: 1 }))).toBe("1 dia");
  });

  it("trata caixa crescente (null) e limite (0)", () => {
    expect(runwayLabel(runway({ days: null, burn_rate_cents_per_day: 0 }))).toContain("Sem risco");
    expect(runwayLabel(runway({ days: 0 }))).toContain("0 dias");
  });

  it("[Story 8.1 AC5] suprimido diz INDISPONÍVEL e JAMAIS 'sem risco'", () => {
    // O teste mais valioso desta story no frontend: trocar "não sei" por "sem risco" substituiria
    // um número falso por uma tranquilidade falsa — e a segunda dá permissão para gastar.
    const label = runwayLabel(runway({ days: null, days_suprimido: true }));
    expect(label).toContain("Indisponível");
    expect(label.toLowerCase()).not.toContain("sem risco");
    // ...e aponta o MOTIVO (saldo inicial não confirmado), não uma indisponibilidade genérica
    expect(label.toLowerCase()).toContain("saldo inicial");
  });

  it("[Story 8.1 AC4] os três ramos produzem rótulos distintos entre si", () => {
    const suprimido = runwayLabel(runway({ days: null, days_suprimido: true }));
    const semRisco = runwayLabel(runway({ days: null, burn_rate_cents_per_day: 0 }));
    const comDias = runwayLabel(runway({ days: 43 }));
    expect(new Set([suprimido, semRisco, comDias]).size).toBe(3);
  });
});

describe("ORIGEM_LABEL / origemLabel (Story 8.1 AC1)", () => {
  it("cobre os QUATRO valores do eixo A e nenhum a mais", () => {
    // O vocabulário canônico é `app/core/money_planes.py::ORIGENS` — quatro valores. `declarado` e
    // `extrato` foram revogados (pertencem ao eixo B, `*_fonte`, e nunca entram neste mapa).
    expect(Object.keys(ORIGEM_LABEL).sort()).toEqual([
      "banco",
      "indisponivel",
      "misto",
      "plataforma",
    ]);
  });

  it("traduz a origem da Onda 0 e não engana o usuário chamando-a de conta bancária", () => {
    expect(origemLabel("plataforma")).toBe("disponível na Carteira e1p");
    expect(origemLabel("plataforma")).not.toContain("conta bancária");
  });

  it("é tolerante a um valor novo do backend (mostra o valor cru em vez de sumir)", () => {
    expect(origemLabel("valor-que-ainda-nao-existe")).toBe("valor-que-ainda-nao-existe");
  });
});

describe("formatBRL (reuso de dre.ts)", () => {
  it("formata centavos preservando sinal", () => {
    expect(formatBRL(90000)).toContain("900,00");
    expect(formatBRL(-80000)).toContain("-");
  });
});
