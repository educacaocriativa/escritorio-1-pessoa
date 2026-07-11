/**
 * Centro de custo (Story 5.5) — tipos + vocabulário sugerido e helpers PUROS.
 *
 * O `kind` é TEXTO LIVRE categorizado (sócio/área/unidade/outro são SUGESTÕES da UI, não enum
 * fechado — ao contrário do `grupo_dre` do plano de contas). A lógica pura vive aqui (testável)
 * porque o projeto não tem infra de teste de componente React — mesmo padrão de dre.ts /
 * planoContas.ts. `formatBRL` é reusado de dre.ts (fonte única de formatação de dinheiro).
 */
import { formatBRL } from "./dre";

export { formatBRL };

export interface CostCenter {
  id: string;
  name: string;
  kind: string;
  archived_at: string | null;
  created_at: string;
}

/** Tipos SUGERIDOS na UI (não é enum fechado — `kind` aceita qualquer texto). */
export const COST_CENTER_KINDS = [
  ["socio", "Sócio"],
  ["area", "Área"],
  ["unidade", "Unidade"],
  ["outro", "Outro"],
] as const;

/** Rótulo PT-BR do tipo. Se `kind` está fora do vocabulário sugerido (texto livre), mostra o valor
 * cru — a dimensão não trava o usuário a uma lista fixa. */
export function kindLabel(kind: string): string {
  const found = COST_CENTER_KINDS.find(([v]) => v === kind);
  return found ? found[1] : kind;
}

// ── Cruzamento por centro de custo (endpoint /financial-intelligence/by-cost-center) ──
export interface CostCenterBucket {
  /** null = bucket sintético "Não atribuído" (lançamentos sem centro de custo — AC3). */
  cost_center_id: string | null;
  name: string;
  kind: string | null;
  receita_cents: number;
  resultado_cents: number;
  lancamentos: number;
}

export interface CostCenterReport {
  start: string;
  end: string;
  buckets: CostCenterBucket[];
  notes: string[];
}

/** True quando o bucket teve movimento no período (usado para destacar centros ociosos na UI). */
export function hasActivity(bucket: CostCenterBucket): boolean {
  return bucket.lancamentos > 0;
}
