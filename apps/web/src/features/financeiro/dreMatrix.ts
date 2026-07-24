/**
 * DRE em matriz mensal (Story 5.11) — tipos + transformação PURA que a DrePage usa.
 * O backend já devolve os totais assinados e o subtotal/grand_total prontos (só somam linhas
 * kind="result"); aqui só resolvemos o RÓTULO de exibição do grupo, que difere por modo.
 */
import { groupLabel } from "./dre";

export interface DreMatrixRow {
  label: string;
  kind: "result" | "informational" | "uncategorized";
  /** Grupo DRE de origem do lançamento (null = linha "Sem categoria") — usado no drill-down
   * analítico da célula (ver `dreMatrixEntries.ts`). */
  grupo_dre: string | null;
  monthly_cents: number[];
  total_cents: number;
}

export interface DreMatrixGroup {
  key: string;
  /** Nome do centro de custo (group_by="cost_center") — null quando group_by="dre". */
  label: string | null;
  rows: DreMatrixRow[];
  subtotal_cents: number[];
  subtotal_total: number;
}

export interface DreMatrixReport {
  months: string[];
  groups: DreMatrixGroup[];
  grand_total_cents: number[];
  grand_total: number;
  notes: string[];
}

export type GroupBy = "dre" | "cost_center";

/** Rótulo de exibição do grupo: nome do centro de custo (group_by="cost_center", já vem pronto do
 * backend) OU o rótulo PT-BR do grupo DRE (group_by="dre" — o backend só manda o código, a
 * tradução já existe em `groupLabel`, sem duplicar a tabela). */
export function matrixGroupLabel(group: DreMatrixGroup, groupBy: GroupBy): string {
  if (groupBy === "cost_center") return group.label ?? group.key;
  return groupLabel(group.key);
}

/** Soma, mês a mês e no total do período, só as linhas `kind="informational"` (Investimento) de
 * TODOS os grupos — funciona nos dois modos: em `group_by="dre"` é exatamente o grupo
 * "INVESTIMENTO"; em `group_by="cost_center"` as linhas de investimento ficam espalhadas por
 * vários centros, então soma-se por `kind`, não por grupo. Usado pra compor "TOTAL GERAL +
 * INVESTIMENTO" (o gasto total do período, incluindo o que o resultado operacional exclui). */
export function investmentTotals(report: DreMatrixReport): { monthly: number[]; total: number } {
  const monthly = report.months.map(() => 0);
  let total = 0;
  for (const group of report.groups) {
    for (const row of group.rows) {
      if (row.kind !== "informational") continue;
      row.monthly_cents.forEach((c, i) => {
        monthly[i] += c;
      });
      total += row.total_cents;
    }
  }
  return { monthly, total };
}

/** Em `group_by="dre"`, separa o grupo Investimento (e o bucket sintético Sem Categoria, que já
 * vem depois dele) do resto — pra renderizar TOTAL GERAL logo após Financeiro/antes de
 * Investimento, e só então o Investimento + o total combinado. Em `group_by="cost_center"` não há
 * uma seção de investimento separada (fica misturada em cada centro de custo), então `after` fica
 * vazio e nada é reordenado. */
export function splitGroupsAroundInvestment(
  groups: DreMatrixGroup[],
  groupBy: GroupBy,
): { before: DreMatrixGroup[]; after: DreMatrixGroup[] } {
  if (groupBy !== "dre") return { before: groups, after: [] };
  return {
    before: groups.filter((g) => g.key !== "INVESTIMENTO" && g.key !== "SEM_CATEGORIA"),
    after: groups.filter((g) => g.key === "INVESTIMENTO" || g.key === "SEM_CATEGORIA"),
  };
}
