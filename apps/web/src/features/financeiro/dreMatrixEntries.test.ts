import { describe, expect, it } from "vitest";
import { sortDescending, type DreMatrixEntry } from "./dreMatrixEntries";

const entry = (over: Partial<DreMatrixEntry> = {}): DreMatrixEntry => ({
  id: "e1",
  source: "charge",
  date: "2026-06-01",
  description: "desc",
  status: "open",
  amount_cents: 1000,
  ...over,
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
