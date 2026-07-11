/**
 * Contas de investimento (Story 5.6) — tipos + helpers PUROS de formatação.
 *
 * A lógica de formatação vive aqui (pura, testável) porque o projeto não tem infra de teste de
 * componente React — mesmo padrão de planoContas.ts / dre.ts. A InvestimentosPage consome estes
 * tipos e helpers.
 *
 * O rendimento (juro) é lançado como receita no grupo FINANCEIRO do plano de contas e entra na DRE
 * — NÃO é venda com split de Carteira (por isso a tela usa o seletor de contas FINANCEIRO do plano
 * de contas, não o fluxo de cobrança normal).
 */
import { formatBRL } from "./dre";

export { formatBRL };

/** Tipos de aplicação SUGERIDOS na UI (texto livre — o backend não valida contra lista fechada). */
export const SUGGESTED_KINDS = ["CDB", "Tesouro", "Fundo", "Poupança", "LCI/LCA", "Ações"] as const;

export interface InvestmentAccount {
  id: string;
  name: string;
  kind: string;
  index_rate_label: string;
  principal_cents: number;
  accrued_yield_cents: number;
  opened_at: string;
  created_at: string;
}

export interface Rentability {
  account_id: string;
  principal_cents: number;
  accrued_yield_cents: number;
  total_rentability_pct: number | null;
  period_rentability_pct: number | null;
  period_yield_cents: number;
  start: string | null;
  end: string | null;
}

/**
 * Formata uma rentabilidade (fração, ex.: 0.055 → "5,50%"). `null` (principal 0 → divisão evitada)
 * vira "—" para não exibir "NaN%" ao usuário.
 */
export function formatPct(fraction: number | null): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  return (fraction * 100).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) + "%";
}
