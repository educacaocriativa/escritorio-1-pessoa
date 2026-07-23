import { describe, expect, it } from "vitest";
import { sortDescending, statusLabel, type LedgerEntry } from "./ledger";

const entry = (over: Partial<LedgerEntry> = {}): LedgerEntry => ({
  id: "e1",
  source: "charge",
  date: "2026-06-01",
  description: "desc",
  categoria: "Cat",
  status: "open",
  amount_cents: 1000,
  ...over,
});

describe("statusLabel", () => {
  it("traduz os status conhecidos", () => {
    expect(statusLabel("open")).toBe("Em aberto");
    expect(statusLabel("paid")).toBe("Realizado");
    expect(statusLabel("canceled")).toBe("Cancelado");
  });

  it("status desconhecido cai no valor cru (defensivo)", () => {
    expect(statusLabel("refunded")).toBe("refunded");
  });
});

describe("sortDescending", () => {
  it("ordena por data mais recente primeiro, sem mutar o array original", () => {
    const entries = [
      entry({ id: "a", date: "2026-06-14" }),
      entry({ id: "b", date: "2026-06-15" }),
      entry({ id: "c", date: "2026-06-01" }),
    ];
    const sorted = sortDescending(entries);
    expect(sorted.map((e) => e.id)).toEqual(["b", "a", "c"]);
    expect(entries.map((e) => e.id)).toEqual(["a", "b", "c"]); // original intacto
  });
});
