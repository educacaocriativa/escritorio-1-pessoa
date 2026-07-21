import { describe, expect, it } from "vitest";
import { formatBRL, groupLabel } from "./dre";

describe("groupLabel / formatBRL", () => {
  it("rotula grupos em PT-BR e o bucket sintético", () => {
    expect(groupLabel("RECEITA")).toBe("Receita");
    expect(groupLabel("SEM_CATEGORIA")).toBe("Sem categoria");
  });

  it("formata centavos em R$ preservando o sinal das deduções", () => {
    expect(formatBRL(150000)).toContain("1.500,00");
    expect(formatBRL(-20000)).toContain("-");
  });
});
