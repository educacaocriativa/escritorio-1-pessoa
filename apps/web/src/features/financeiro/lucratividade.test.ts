import { describe, expect, it } from "vitest";
import { computeTotals, sortByMargin, type ContractDreSummary } from "./lucratividade";

const row = (over: Partial<ContractDreSummary> = {}): ContractDreSummary => ({
  contract_id: "c1",
  title: "Projeto",
  client_name: null,
  receita_cents: 0,
  custo_direto_cents: 0,
  margem_contribuicao_cents: 0,
  margem_contribuicao_pct: null,
  overhead_allocated_cents: 0,
  resultado_cents: 0,
  ...over,
});

describe("sortByMargin", () => {
  it("ordena por margem de contribuição descendente sem mutar o array original", () => {
    const rows = [
      row({ contract_id: "a", margem_contribuicao_cents: 10000 }),
      row({ contract_id: "b", margem_contribuicao_cents: 50000 }),
      row({ contract_id: "c", margem_contribuicao_cents: -2000 }),
    ];
    const sorted = sortByMargin(rows);
    expect(sorted.map((r) => r.contract_id)).toEqual(["b", "a", "c"]);
    expect(rows.map((r) => r.contract_id)).toEqual(["a", "b", "c"]); // original intacto
  });
});

describe("computeTotals", () => {
  it("soma os valores simples e pondera a margem % pela receita (não é média aritmética)", () => {
    const rows = [
      row({ receita_cents: 100000, margem_contribuicao_cents: 80000, custo_direto_cents: -20000, overhead_allocated_cents: 0, resultado_cents: 80000 }),
      row({ receita_cents: 900000, margem_contribuicao_cents: 90000, custo_direto_cents: -810000, overhead_allocated_cents: 5000, resultado_cents: 85000 }),
    ];
    const totals = computeTotals(rows);
    expect(totals.receita_cents).toBe(1000000);
    expect(totals.custo_direto_cents).toBe(-830000);
    expect(totals.overhead_cents).toBe(5000);
    expect(totals.resultado_cents).toBe(165000);
    // ponderada: (80000+90000) / (100000+900000) = 0.17 — bem diferente da média aritmética das
    // duas margens % individuais (80% e 10%, que dariam 45%).
    expect(totals.margem_pct_media).toBeCloseTo(0.17, 5);
  });

  it("margem % média é null quando não há receita (proteção div/0)", () => {
    expect(computeTotals([row({ receita_cents: 0 })]).margem_pct_media).toBeNull();
  });

  it("lista vazia não quebra (todos os totais zerados/null)", () => {
    const totals = computeTotals([]);
    expect(totals).toEqual({
      receita_cents: 0, custo_direto_cents: 0, margem_pct_media: null,
      overhead_cents: 0, resultado_cents: 0,
    });
  });
});
