/**
 * Drill-down analítico de uma célula da matriz DRE (Story 5.13) — tipos + transformação PURA que
 * o drawer "ver analítico" da DrePage usa. Lógica pura/testável (sem jsdom/@testing-library).
 */
export interface DreMatrixEntry {
  id: string;
  source: "charge" | "payable" | "transaction";
  date: string;
  description: string;
  status: string;
  amount_cents: number; // já assinado (Charge/Transaction=+, Payable=−)
}

/** Mais recente primeiro (mesma convenção do extrato de contrato). Não muta o array recebido. */
export function sortDescending(entries: DreMatrixEntry[]): DreMatrixEntry[] {
  return [...entries].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}
