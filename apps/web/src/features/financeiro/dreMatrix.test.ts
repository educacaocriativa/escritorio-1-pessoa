import { describe, expect, it } from "vitest";
import {
  investmentTotals,
  matrixGroupLabel,
  splitGroupsAroundInvestment,
  type DreMatrixGroup,
  type DreMatrixReport,
  type DreMatrixRow,
} from "./dreMatrix";

const row = (over: Partial<DreMatrixRow> = {}): DreMatrixRow => ({
  label: "Categoria",
  kind: "result",
  grupo_dre: "RECEITA",
  monthly_cents: [0],
  total_cents: 0,
  ...over,
});

const group = (over: Partial<DreMatrixGroup> = {}): DreMatrixGroup => ({
  key: "RECEITA",
  label: null,
  rows: [],
  subtotal_cents: [0],
  subtotal_total: 0,
  ...over,
});

const report = (over: Partial<DreMatrixReport> = {}): DreMatrixReport => ({
  months: ["2026-01", "2026-02"],
  groups: [],
  grand_total_cents: [0, 0],
  grand_total: 0,
  notes: [],
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

describe("investmentTotals", () => {
  it("soma só as linhas kind=informational, mês a mês e no total", () => {
    const r = report({
      groups: [
        group({
          key: "INVESTIMENTO",
          rows: [
            row({ kind: "informational", monthly_cents: [-300000, 0], total_cents: -300000 }),
            row({ kind: "result", monthly_cents: [1000, 1000], total_cents: 2000 }), // não conta
          ],
        }),
      ],
    });
    expect(investmentTotals(r)).toEqual({ monthly: [-300000, 0], total: -300000 });
  });

  it("soma linhas informational espalhadas por vários grupos (group_by=cost_center)", () => {
    const r = report({
      groups: [
        group({ key: "cc-a", rows: [row({ kind: "informational", monthly_cents: [-100, 0], total_cents: -100 })] }),
        group({ key: "cc-b", rows: [row({ kind: "informational", monthly_cents: [0, -50], total_cents: -50 })] }),
      ],
    });
    expect(investmentTotals(r)).toEqual({ monthly: [-100, -50], total: -150 });
  });

  it("sem linhas informational, retorna zero (nunca quebra)", () => {
    expect(investmentTotals(report())).toEqual({ monthly: [0, 0], total: 0 });
  });
});

describe("splitGroupsAroundInvestment", () => {
  it("group_by=dre: separa INVESTIMENTO e SEM_CATEGORIA do resto, preservando ordem", () => {
    const groups = [
      group({ key: "RECEITA" }),
      group({ key: "CUSTO_DIRETO" }),
      group({ key: "INVESTIMENTO" }),
      group({ key: "SEM_CATEGORIA" }),
    ];
    const { before, after } = splitGroupsAroundInvestment(groups, "dre");
    expect(before.map((g) => g.key)).toEqual(["RECEITA", "CUSTO_DIRETO"]);
    expect(after.map((g) => g.key)).toEqual(["INVESTIMENTO", "SEM_CATEGORIA"]);
  });

  it("group_by=cost_center: não reordena nada (investimento fica espalhado por centro)", () => {
    const groups = [group({ key: "cc-a" }), group({ key: "_unassigned" })];
    const { before, after } = splitGroupsAroundInvestment(groups, "cost_center");
    expect(before).toEqual(groups);
    expect(after).toEqual([]);
  });
});
