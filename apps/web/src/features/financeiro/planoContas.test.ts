import { describe, expect, it } from "vitest";
import { type ChartAccount, buildHierarchy, GRUPOS_DRE } from "./planoContas";

/**
 * Smoke test da lógica que a PlanoContasPage usa para renderizar a lista agrupada (Story 5.1).
 *
 * Nota: o projeto não tem infraestrutura de teste de componente React (sem jsdom /
 * @testing-library) — os testes de front são de lógica pura (ver src/lib/*.test.ts). Este teste
 * cobre o agrupamento que alimenta o accordion; um render-test de DOM foi deixado como pendência
 * documentada no Dev Agent Record da story.
 */
let _seq = 0;
const acc = (over: Partial<ChartAccount>): ChartAccount => ({
  id: `acc-${++_seq}`,
  grupo_dre: "RECEITA",
  categoria: "X",
  archived_at: null,
  created_at: "2026-07-11T00:00:00Z",
  ...over,
});

describe("buildHierarchy (plano de contas — Story 5.1)", () => {
  it("sempre devolve os 6 grupos na ordem canônica, mesmo vazios", () => {
    const groups = buildHierarchy([]);
    expect(groups.map((g) => g.grupo_dre)).toEqual([...GRUPOS_DRE]);
    expect(groups.every((g) => g.categorias.length === 0)).toBe(true);
  });

  it("agrupa as categorias no grupo certo e ordena por nome", () => {
    const groups = buildHierarchy([
      acc({ grupo_dre: "RECEITA", categoria: "Serviços" }),
      acc({ grupo_dre: "RECEITA", categoria: "Assinaturas" }),
      acc({ grupo_dre: "DESPESA_FIXA", categoria: "Aluguel" }),
    ]);
    const receita = groups.find((g) => g.grupo_dre === "RECEITA")!;
    expect(receita.categorias.map((c) => c.categoria)).toEqual(["Assinaturas", "Serviços"]);
    const despesa = groups.find((g) => g.grupo_dre === "DESPESA_FIXA")!;
    expect(despesa.categorias.map((c) => c.categoria)).toEqual(["Aluguel"]);
  });

  it("expõe rótulos PT-BR por grupo", () => {
    const groups = buildHierarchy([]);
    const financeiro = groups.find((g) => g.grupo_dre === "FINANCEIRO")!;
    expect(financeiro.label).toBe("Financeiro");
  });
});
