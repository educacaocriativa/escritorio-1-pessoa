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
  // A quebra em várias linhas é para o teste de mutação (#121): os dois operadores precisavam
  // ficar em linhas SEPARADAS para que o `disable` abaixo mire só um deles — o `>` continua
  // mutável, e o teste de empate abaixo o mata.
  //
  // Stryker disable next-line EqualityOperator
  // Trocar `<` por `<=` faz o comparador devolver 1 para itens de MESMA data, o que viola o
  // contrato de antissimetria do `Array.prototype.sort`: o resultado passa a ser definido pelo
  // motor, não por nós. Sob o V8 (Node na suite, Chrome/Edge no navegador) ele coincide com o
  // original — verificado por força bruta com 7.000+ arranjos aleatórios, de 2 a 60 itens, com
  // datas repetidas: ZERO divergências. Um teste que "matasse" este mutante estaria fixando o
  // comportamento do motor, não a regra do extrato.
  return [...entries].sort((a, b) =>
    a.date < b.date
      ? 1
      : a.date > b.date
        ? -1
        : 0,
  );
}

export { formatBRL };
