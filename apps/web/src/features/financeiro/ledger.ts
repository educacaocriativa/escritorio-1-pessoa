/**
 * Extrato cronológico de um contrato (Story 5.12) — tipos + transformação PURA que o drawer de
 * "Detalhes" da LucratividadePage usa. Lógica pura/testável (sem jsdom/@testing-library).
 */
import { formatBRL } from "./dre";

export interface LedgerEntry {
  id: string;
  source: "charge" | "payable";
  date: string;
  description: string;
  categoria: string;
  status: string;
  amount_cents: number; // já assinado (Charge=+, Payable=−)
}

const STATUS_LABEL: Record<string, string> = {
  open: "Em aberto",
  paid: "Realizado",
  canceled: "Cancelado",
};

/** Rótulo PT-BR do status; status desconhecido cai no valor cru (defensivo, nunca quebra). */
export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** Mais recente primeiro (extrato tipo "bancário"). Não muta o array recebido. */
export function sortDescending(entries: LedgerEntry[]): LedgerEntry[] {
  return [...entries].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

export { formatBRL };
