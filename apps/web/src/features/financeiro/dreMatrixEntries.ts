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
