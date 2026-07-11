/**
 * Plano de contas (Story 5.1) — tipos + taxonomia de grupos DRE e helper de agrupamento.
 *
 * O grupo DRE é um enum FIXO de produto (6 valores) — o front NUNCA o expõe como texto livre.
 * `categoria` é livre. A lógica de agrupamento vive aqui (pura, testável) e é consumida pela
 * PlanoContasPage para renderizar a lista agrupada por grupo (accordion), sempre com os 6 grupos
 * na ordem canônica — mesmo os vazios.
 */

/** Grupos DRE na ORDEM canônica (receita → resultado). Espelha models.GROUP_ORDER do backend. */
export const GRUPOS_DRE = [
  "RECEITA",
  "CUSTO_DIRETO",
  "DESPESA_FIXA",
  "TRIBUTOS",
  "FINANCEIRO",
  "INVESTIMENTO",
] as const;

export type GrupoDre = (typeof GRUPOS_DRE)[number];

/** Rótulos PT-BR dos grupos (o produto é em PT-BR — CLAUDE.md §8). */
export const GRUPO_LABEL: Record<GrupoDre, string> = {
  RECEITA: "Receita",
  CUSTO_DIRETO: "Custo direto",
  DESPESA_FIXA: "Despesa fixa",
  TRIBUTOS: "Tributos",
  FINANCEIRO: "Financeiro",
  INVESTIMENTO: "Investimento",
};

export interface ChartAccount {
  id: string;
  grupo_dre: GrupoDre;
  categoria: string;
  archived_at: string | null;
  created_at: string;
}

export interface ChartGroup {
  grupo_dre: GrupoDre;
  label: string;
  categorias: ChartAccount[];
}

/**
 * Agrupa a lista flat de categorias por grupo DRE, devolvendo SEMPRE os 6 grupos na ordem
 * canônica (grupos sem categoria vêm com lista vazia). Categorias ordenadas por nome.
 */
export function buildHierarchy(accounts: ChartAccount[]): ChartGroup[] {
  const byGroup = new Map<GrupoDre, ChartAccount[]>();
  for (const grupo of GRUPOS_DRE) byGroup.set(grupo, []);
  for (const acc of accounts) {
    // Ignora grupos desconhecidos (defensivo: o enum é fixo, mas o backend é a fonte da verdade).
    if (byGroup.has(acc.grupo_dre)) byGroup.get(acc.grupo_dre)!.push(acc);
  }
  return GRUPOS_DRE.map((grupo) => ({
    grupo_dre: grupo,
    label: GRUPO_LABEL[grupo],
    categorias: [...byGroup.get(grupo)!].sort((a, b) =>
      a.categoria.localeCompare(b.categoria, "pt-BR"),
    ),
  }));
}
