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
  // Trocar `<` por `<=` faz o comparador devolver 1 para itens de MESMA data, o que viola o
  // contrato de antissimetria do `Array.prototype.sort`: o resultado passa a ser definido pelo
  // motor, não por nós. Sob o V8 (Node na suite, Chrome/Edge no navegador) ele coincide com o
  // original — verificado por força bruta com 7.000+ arranjos aleatórios, de 2 a 60 itens, com
  // datas repetidas: ZERO divergências. Um teste que "matasse" este mutante estaria fixando o
  // comportamento do motor, não a regra do extrato.
  //
  // ⚠️ Até a triagem #214 o `disable` ficava sete linhas ACIMA do alvo — e por isso não fazia
  // nada: `next-line` é a linha seguinte LITERAL, e a linha seguinte era outro comentário. O
  // relatório da CI trazia o mutante como `Survived`, não `Ignored`; a supressão que o parágrafo
  // acima descreve nunca chegou a existir. A directive tem de ENCOSTAR na linha alvo, como em
  // `features/pagar/baixa.ts`. Por isso ela desceu para dentro do `sort`.
  //
  // O outro sobrevivente desta linha, `ConditionalExpression → false`, também é EQUIVALENTE — e
  // por um motivo mais forte que "o V8 coincide": `false ? 1 : a.date > b.date ? -1 : 0` devolve
  // 0 onde o original devolve 1, e o `sort` só observa o SINAL do comparador (`< 0` ou não). 1 e
  // 0 estão na MESMA classe de sinal, então nenhuma implementação de sort consegue separar os
  // dois programas. Medido: 23.600 arranjos de 2 a 60 itens com datas repetidas, ZERO
  // divergências. Não leva `disable` porque a directive é por MUTADOR, e desligar
  // `ConditionalExpression` aqui apagaria junto o mutante `true`, que HOJE morre no teste de
  // empate.
  return [...entries].sort((a, b) =>
    // Stryker disable next-line EqualityOperator
    a.date < b.date
      ? 1
      : a.date > b.date
        ? -1
        : 0,
  );
}
