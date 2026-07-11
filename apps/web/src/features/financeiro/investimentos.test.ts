import { describe, expect, it } from "vitest";
import { formatPct } from "./investimentos";

/**
 * Smoke test do helper de formatação de rentabilidade (Story 5.6). O projeto não tem infra de teste
 * de componente React — os testes de front são de lógica pura (ver planoContas.test.ts / dre).
 */
describe("formatPct (rentabilidade — Story 5.6)", () => {
  it("formata a fração como percentual pt-BR com 2 casas", () => {
    expect(formatPct(0.055)).toBe("5,50%");
    expect(formatPct(0.05)).toBe("5,00%");
    expect(formatPct(0)).toBe("0,00%");
  });

  it("mostra '—' quando a rentabilidade é null (principal 0 — divisão evitada)", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatPct(Number.NaN)).toBe("—");
  });
});
