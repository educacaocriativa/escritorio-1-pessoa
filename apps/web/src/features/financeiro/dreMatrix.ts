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
