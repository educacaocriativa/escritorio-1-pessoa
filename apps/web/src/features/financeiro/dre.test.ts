import { describe, expect, it } from "vitest";
import { buildDreView, type DreReport, formatBRL, groupLabel } from "./dre";

/**
 * Smoke test da lógica que a DrePage usa para renderizar a DRE (Story 5.3).
 *
 * O projeto não tem infra de teste de componente React (sem jsdom / @testing-library) — os testes
 * de front são de lógica pura (ver src/lib/*.test.ts e planoContas.test.ts). Este teste cobre a
 * derivação das linhas (grupo → categorias, exclusão do INVESTIMENTO/sem-categoria do resultado);
 * um render-test de DOM (drill/expand por clique) fica como pendência documentada no Dev Agent
 * Record da story.
 */
const report = (over: Partial<DreReport> = {}): DreReport => ({
  start: "2026-07-01",
  end: "2026-07-31",
  groups: [
    {
      grupo_dre: "RECEITA",
      total_cents: 180000,
      categorias: [
        { categoria: "Consultoria", amount_cents: 150000, count: 2 },
        { categoria: "Mentoria", amount_cents: 30000, count: 1 },
      ],
    },
    { grupo_dre: "CUSTO_DIRETO", total_cents: -20000, categorias: [{ categoria: "Insumos", amount_cents: -20000, count: 1 }] },
    { grupo_dre: "DESPESA_FIXA", total_cents: 0, categorias: [] },
    { grupo_dre: "TRIBUTOS", total_cents: 0, categorias: [] },
    { grupo_dre: "FINANCEIRO", total_cents: 1500, categorias: [{ categoria: "Rendimento", amount_cents: 1500, count: 1 }] },
    { grupo_dre: "INVESTIMENTO", total_cents: -300000, categorias: [{ categoria: "Equipamentos", amount_cents: -300000, count: 1 }] },
  ],
  sem_categoria: { grupo_dre: "SEM_CATEGORIA", total_cents: 4000, categorias: [{ categoria: "Sem categoria", amount_cents: 4000, count: 2 }] },
  resultado_cents: 111500,
  notes: ["Regime de competência."],
  ...over,
});

describe("buildDreView (DRE — Story 5.3)", () => {
  it("mantém os grupos e expõe as categorias de cada um (drill)", () => {
    const { rows } = buildDreView(report());
    const receita = rows.find((r) => r.grupo_dre === "RECEITA")!;
    expect(receita.kind).toBe("result");
    expect(receita.categorias.map((c) => c.categoria)).toEqual(["Consultoria", "Mentoria"]);
  });

  it("marca INVESTIMENTO como informativo (fora do resultado)", () => {
    const { rows, resultado_cents } = buildDreView(report());
    const inv = rows.find((r) => r.grupo_dre === "INVESTIMENTO")!;
    expect(inv.kind).toBe("informational");
    // o resultado não inclui INVESTIMENTO nem sem-categoria
    expect(resultado_cents).toBe(111500);
  });

  it("inclui o bucket 'sem categoria' quando há lançamentos não classificados", () => {
    const { rows } = buildDreView(report());
    const sem = rows.find((r) => r.grupo_dre === "SEM_CATEGORIA");
    expect(sem?.kind).toBe("uncategorized");
    expect(sem?.categorias[0].count).toBe(2);
  });

  it("omite o bucket 'sem categoria' quando está vazio", () => {
    const { rows } = buildDreView(
      report({ sem_categoria: { grupo_dre: "SEM_CATEGORIA", total_cents: 0, categorias: [] } }),
    );
    expect(rows.find((r) => r.grupo_dre === "SEM_CATEGORIA")).toBeUndefined();
  });
});

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
