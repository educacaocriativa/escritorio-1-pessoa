import { describe, expect, it } from "vitest";
import { resolvePeriod } from "./periodRange";

const TODAY = new Date(Date.UTC(2026, 6, 21)); // 21/07/2026 (mês = 6 = julho, 0-indexed)

describe("resolvePeriod", () => {
  it("this_month", () => {
    expect(resolvePeriod("this_month", TODAY)).toEqual({ start: "2026-07-01", end: "2026-07-31" });
  });

  it("last_month cruzando ano (janeiro -> dezembro do ano anterior)", () => {
    const jan = new Date(Date.UTC(2026, 0, 15));
    expect(resolvePeriod("last_month", jan)).toEqual({ start: "2025-12-01", end: "2025-12-31" });
  });

  it("this_quarter (julho cai no 3º trimestre: jul-set)", () => {
    expect(resolvePeriod("this_quarter", TODAY)).toEqual({ start: "2026-07-01", end: "2026-09-30" });
  });

  it("this_year", () => {
    expect(resolvePeriod("this_year", TODAY)).toEqual({ start: "2026-01-01", end: "2026-12-31" });
  });

  it("last_12_months (janela rolante terminando no mês atual)", () => {
    expect(resolvePeriod("last_12_months", TODAY)).toEqual({ start: "2025-08-01", end: "2026-07-31" });
  });

  it("all (início fixo, fim no mês atual)", () => {
    expect(resolvePeriod("all", TODAY)).toEqual({ start: "2000-01-01", end: "2026-07-31" });
  });

  it("custom repassa o range informado", () => {
    const custom = { start: "2026-02-01", end: "2026-02-10" };
    expect(resolvePeriod("custom", TODAY, custom)).toEqual(custom);
  });

  it("custom sem range lança erro", () => {
    expect(() => resolvePeriod("custom", TODAY)).toThrow();
  });
});
