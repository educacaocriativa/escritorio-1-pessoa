/**
 * Ranking de lucratividade por contrato (Story 5.12) — tipos + transformação PURA que a
 * LucratividadePage usa. Lógica pura/testável porque o projeto não tem infra de teste de
 * componente React (sem jsdom / @testing-library) — mesmo padrão de dre.ts/contratoDre.ts.
 */
export interface ContractDreSummary {
  contract_id: string;
  title: string;
  client_name: string | null;
  receita_cents: number;
  custo_direto_cents: number;
  margem_contribuicao_cents: number;
  margem_contribuicao_pct: number | null;
  overhead_allocated_cents: number;
  resultado_cents: number;
}

export interface LucratividadeTotals {
  receita_cents: number;
  custo_direto_cents: number;
  /** ponderada: Σmargem / Σreceita — NÃO é a média aritmética das margens %, que deixaria um
   * contrato pequeno distorcer o número. null quando não há receita (proteção div/0). */
  margem_pct_media: number | null;
  overhead_cents: number;
  resultado_cents: number;
}

/** Ranking por margem de contribuição descendente. Não muta o array recebido. */
export function sortByMargin(rows: ContractDreSummary[]): ContractDreSummary[] {
  return [...rows].sort((a, b) => b.margem_contribuicao_cents - a.margem_contribuicao_cents);
}

/** Totais agregados do topo da tela — somas simples + margem % média ponderada pela receita. */
export function computeTotals(rows: ContractDreSummary[]): LucratividadeTotals {
  const receita_cents = rows.reduce((s, r) => s + r.receita_cents, 0);
  const custo_direto_cents = rows.reduce((s, r) => s + r.custo_direto_cents, 0);
  const margem_cents = rows.reduce((s, r) => s + r.margem_contribuicao_cents, 0);
  const overhead_cents = rows.reduce((s, r) => s + r.overhead_allocated_cents, 0);
  const resultado_cents = rows.reduce((s, r) => s + r.resultado_cents, 0);
  return {
    receita_cents,
    custo_direto_cents,
    margem_pct_media: receita_cents !== 0 ? margem_cents / receita_cents : null,
    overhead_cents,
    resultado_cents,
  };
}
