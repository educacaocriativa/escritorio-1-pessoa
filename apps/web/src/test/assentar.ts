import { act } from "@testing-library/react";

/**
 * Deixa as promessas já resolvidas COMPROMETEREM seus `setState` dentro de `act` — e faz um erro
 * de render nascido nesse commit reprovar o teste (issue #207).
 *
 * ## Por que isto existe, medido
 *
 * A forma óbvia de afirmar "payload fora de forma não derruba a tela" é `waitFor(() =>
 * expect(screen.getByText(estadoVazio)).toBeInTheDocument())`. Ela é FALSA CONFIANÇA quando o
 * estado inicial já é `[]`: o texto do estado vazio está no DOM desde a montagem, o primeiro
 * poll do `waitFor` acerta, e o teste retorna ANTES de o payload sequer chegar ao setter.
 *
 * Medido em 22/08/2026 em `FunisPage`, com a guarda `Array.isArray` REMOVIDA da produção:
 *
 *     TypeError: funnels.map is not a function   (4x, em stderr)
 *     Test Files  1 passed (1)
 *     Tests       5 passed (5)
 *
 * Cinco testes verdes sobre um render que estourou quatro vezes. O `TypeError` sai em stderr
 * porque o React o captura no commit e o relata; ninguém o converte em reprovação. Guarda cuja
 * mutação sobrevive não é proteção — é a mesma dívida um nível acima, a lição que o #179 registra.
 *
 * Com o flush DENTRO de `act`, o mesmo mutante reprova com a mensagem de verdade:
 *
 *     TypeError: funnels.map is not a function
 *     Test Files  1 failed (1)
 *
 * ## Por que `voltas`
 *
 * Uma volta esvazia um nível de microtarefa. Um `load` com `await` encadeado (`api.get` →
 * `Promise.all` → `setState`) precisa de uma volta por elo, senão o commit que interessa fica
 * pendente e o teste volta a passar por não ter chegado lá. Na dúvida, sobra volta — cada uma
 * custa uma microtarefa, e passar do necessário é inofensivo.
 */
export async function assentar(voltas = 4): Promise<void> {
  for (let i = 0; i < voltas; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}
