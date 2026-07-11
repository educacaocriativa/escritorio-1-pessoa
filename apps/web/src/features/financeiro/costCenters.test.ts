import { describe, expect, it } from "vitest";
import {
  type CostCenterBucket,
  COST_CENTER_KINDS,
  formatBRL,
  hasActivity,
  kindLabel,
} from "./costCenters";

/**
 * Smoke test da lógica pura do centro de custo (Story 5.5).
 *
 * O projeto não tem infra de teste de componente React (sem jsdom / @testing-library) — os testes
 * de front são de lógica pura (ver src/lib/*.test.ts, dre.test.ts). Aqui cobrimos o rótulo do
 * `kind` (texto livre — mostra o valor cru fora do vocabulário sugerido) e o helper de atividade.
 */
describe("kindLabel (Story 5.5)", () => {
  it("rotula os tipos sugeridos em PT-BR", () => {
    expect(kindLabel("socio")).toBe("Sócio");
    expect(kindLabel("area")).toBe("Área");
    expect(kindLabel("unidade")).toBe("Unidade");
    expect(kindLabel("outro")).toBe("Outro");
  });

  it("mostra o valor cru quando o kind é texto livre fora do vocabulário", () => {
    // centro de custo NÃO é enum fechado (contraste com grupo_dre) — não trava o usuário
    expect(kindLabel("regional")).toBe("regional");
  });

  it("expõe exatamente os 4 tipos sugeridos", () => {
    expect(COST_CENTER_KINDS.map(([v]) => v)).toEqual(["socio", "area", "unidade", "outro"]);
  });
});

describe("hasActivity", () => {
  const bucket = (over: Partial<CostCenterBucket> = {}): CostCenterBucket => ({
    cost_center_id: "cc-1",
    name: "Sócio A",
    kind: "socio",
    receita_cents: 0,
    resultado_cents: 0,
    lancamentos: 0,
    ...over,
  });

  it("é falso para um centro sem movimento no período (ocioso)", () => {
    expect(hasActivity(bucket())).toBe(false);
  });

  it("é verdadeiro quando há lançamentos", () => {
    expect(hasActivity(bucket({ lancamentos: 3 }))).toBe(true);
  });

  it("trata o bucket sintético 'Não atribuído' (cost_center_id null) como um bucket normal", () => {
    const naoAtribuido = bucket({ cost_center_id: null, name: "Não atribuído", kind: null });
    expect(naoAtribuido.cost_center_id).toBeNull();
    expect(hasActivity(naoAtribuido)).toBe(false);
  });
});

describe("formatBRL (reuso de dre.ts)", () => {
  it("formata centavos preservando o sinal", () => {
    expect(formatBRL(60000)).toContain("600,00");
    expect(formatBRL(-2500)).toContain("-");
  });
});
