import { describe, expect, it } from "vitest";
import {
  breakEvenLabel,
  buildContractDreView,
  type ContractDre,
  formatMarginPct,
} from "./contratoDre";

/**
 * Smoke test da lógica que a ContratoDrePage usa para renderizar a DRE do contrato (Story 5.4).
 *
 * Sem jsdom/@testing-library no projeto → teste de lógica pura (mesmo padrão de dre.test.ts). Cobre
 * a formatação da margem % (fração → %), o break-even atingível vs. não-atingível e a derivação da
 * view. O ponto crítico (margem = SOMA de totais assinados, não subtração) é responsabilidade do
 * backend e coberto lá; aqui só garantimos que a exibição respeita os sinais/estados.
 */
const dre = (over: Partial<ContractDre> = {}): ContractDre => ({
  contract_id: "c1",
  start: "2026-07-01",
  end: "2026-07-31",
  receita: {
    grupo_dre: "RECEITA",
    total_cents: 100000,
    categorias: [{ categoria: "Consultoria", amount_cents: 100000, count: 1 }],
  },
  custo_direto: {
    grupo_dre: "CUSTO_DIRETO",
    total_cents: -40000,
    categorias: [{ categoria: "Insumos", amount_cents: -40000, count: 1 }],
  },
  receita_cents: 100000,
  custo_direto_cents: -40000,
  margem_contribuicao_cents: 60000,
  margem_contribuicao_pct: 0.6,
  outros_resultado_cents: 0,
  fixed_costs_allocated_cents: 30000,
  overhead_allocated_cents: 0,
  resultado_cents: 30000,
  break_even_cents: 50000,
  break_even_reachable: true,
  notes: ["Regime de competência."],
  ...over,
});

describe("formatMarginPct", () => {
  it("converte a razão em porcentagem pt-BR", () => {
    expect(formatMarginPct(0.6)).toBe("60%");
    expect(formatMarginPct(0.125)).toBe("12,5%");
  });

  it("mostra '—' quando não há receita (null)", () => {
    expect(formatMarginPct(null)).toBe("—");
  });
});

describe("breakEvenLabel", () => {
  it("formata o valor em R$ quando atingível", () => {
    expect(breakEvenLabel(dre())).toContain("500,00");
  });

  it("avisa quando não atingível (margem não cobre custos fixos)", () => {
    const d = dre({ break_even_reachable: false, break_even_cents: null });
    expect(breakEvenLabel(d)).toMatch(/não atingível/i);
  });
});

describe("buildContractDreView", () => {
  it("expõe margem, resultado e detalhamento de receita/custo (drill)", () => {
    const v = buildContractDreView(dre());
    expect(v.margemCents).toBe(60000);
    expect(v.marginPct).toBe("60%");
    expect(v.resultadoCents).toBe(30000);
    expect(v.receita.categorias[0].categoria).toBe("Consultoria");
    expect(v.custoDireto.categorias[0].amount_cents).toBe(-40000);
    expect(v.breakEvenReachable).toBe(true);
  });

  it("reflete o overhead rateado quando presente", () => {
    const v = buildContractDreView(
      dre({ overhead_allocated_cents: 10000, resultado_cents: 20000 }),
    );
    expect(v.overheadCents).toBe(10000);
    expect(v.resultadoCents).toBe(20000);
  });

  it("expõe outros grupos de resultado (fora da margem, dentro do resultado)", () => {
    // margem 60000 + outros −15000 − custo fixo 30000 = 15000
    const v = buildContractDreView(
      dre({ outros_resultado_cents: -15000, resultado_cents: 15000 }),
    );
    expect(v.outrosResultadoCents).toBe(-15000);
    expect(v.margemCents).toBe(60000); // margem NÃO muda com outros grupos
    expect(v.resultadoCents).toBe(15000);
  });
});
