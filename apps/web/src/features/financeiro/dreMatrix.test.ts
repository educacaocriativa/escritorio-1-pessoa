import { describe, expect, it } from "vitest";
import { matrixGroupLabel, type DreMatrixGroup } from "./dreMatrix";

const group = (over: Partial<DreMatrixGroup> = {}): DreMatrixGroup => ({
  key: "RECEITA",
  label: null,
  rows: [],
  subtotal_cents: [0],
  subtotal_total: 0,
  ...over,
});

describe("matrixGroupLabel", () => {
  it("group_by=dre: traduz o código do grupo em PT-BR via groupLabel", () => {
    expect(matrixGroupLabel(group({ key: "RECEITA" }), "dre")).toBe("Receita");
    expect(matrixGroupLabel(group({ key: "SEM_CATEGORIA" }), "dre")).toBe("Sem categoria");
  });

  it("group_by=cost_center: usa o label vindo do backend (nome do centro de custo)", () => {
    expect(matrixGroupLabel(group({ key: "cc-1", label: "Tecnica" }), "cost_center")).toBe("Tecnica");
  });

  it("group_by=cost_center sem label cai no key (defensivo)", () => {
    expect(matrixGroupLabel(group({ key: "_unassigned", label: null }), "cost_center")).toBe("_unassigned");
  });
});
