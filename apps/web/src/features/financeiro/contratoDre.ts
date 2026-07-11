/**
 * Lucratividade por contrato (Story 5.4) — tipos + transformação PURA que a ContratoDrePage usa.
 *
 * O backend devolve os totais já ASSINADOS (Receber=+, Pagar=−). A margem de contribuição é a SOMA
 * `receita_cents + custo_direto_cents` (custo já vem negativo) — NUNCA `receita − custo` (dupla
 * negação). Aqui só derivamos as LINHAS de exibição e a formatação. A lógica vive aqui (pura,
 * testável) porque o projeto não tem infra de teste de componente React (sem jsdom /
 * @testing-library) — mesmo padrão de dre.ts / planoContas.ts.
 */
import { type DreCategory, type DreGroup, formatBRL } from "./dre";

export { formatBRL };
export type { DreCategory, DreGroup };

export interface ContractDre {
  contract_id: string;
  start: string;
  end: string;
  receita: DreGroup;
  custo_direto: DreGroup;
  receita_cents: number;
  custo_direto_cents: number;
  margem_contribuicao_cents: number;
  /** razão MC/Receita (fração; multiplique por 100 para exibir %). null = sem receita (div/0). */
  margem_contribuicao_pct: number | null;
  /**
   * Soma assinada dos lançamentos do contrato em grupos de resultado ALÉM da margem
   * (Despesa Fixa/Tributos/Financeiro). NÃO entra na margem, mas compõe o resultado.
   */
  outros_resultado_cents: number;
  fixed_costs_allocated_cents: number;
  overhead_allocated_cents: number;
  resultado_cents: number;
  /** receita necessária para empatar os custos fixos; null quando não atingível. */
  break_even_cents: number | null;
  break_even_reachable: boolean;
  notes: string[];
}

/** Formata a margem de contribuição (%). null (sem receita) vira "—". */
export function formatMarginPct(ratio: number | null): string {
  if (ratio === null) return "—";
  return `${(ratio * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

/** Texto do break-even: valor em R$ quando atingível; aviso explícito quando não. */
export function breakEvenLabel(dre: ContractDre): string {
  if (!dre.break_even_reachable || dre.break_even_cents === null) {
    return "Não atingível no ritmo atual (a margem não cobre os custos fixos)";
  }
  return formatBRL(dre.break_even_cents);
}

export interface ContractDreView {
  receita: DreGroup;
  custoDireto: DreGroup;
  margemCents: number;
  marginPct: string;
  outrosResultadoCents: number;
  resultadoCents: number;
  fixedCents: number;
  overheadCents: number;
  breakEven: string;
  breakEvenReachable: boolean;
  notes: string[];
}

/** Deriva os dados de exibição (formatação/rótulos) da DRE do contrato. */
export function buildContractDreView(dre: ContractDre): ContractDreView {
  return {
    receita: dre.receita,
    custoDireto: dre.custo_direto,
    margemCents: dre.margem_contribuicao_cents,
    marginPct: formatMarginPct(dre.margem_contribuicao_pct),
    outrosResultadoCents: dre.outros_resultado_cents,
    resultadoCents: dre.resultado_cents,
    fixedCents: dre.fixed_costs_allocated_cents,
    overheadCents: dre.overhead_allocated_cents,
    breakEven: breakEvenLabel(dre),
    breakEvenReachable: dre.break_even_reachable,
    notes: dre.notes,
  };
}
