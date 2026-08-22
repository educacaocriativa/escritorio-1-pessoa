import { formatDateTime } from "../lib/datetime";

/**
 * Lê um `<input type="datetime-local">` como HORA DE PAREDE DO TENANT — não como a string crua
 * que o navegador escreveu (issue #185).
 *
 * ## O defeito que isto fecha
 *
 * O HTML define que o valor de um `datetime-local` é "naive": `"2026-10-10T09:00"`, sem fuso,
 * nas partes LOCAIS de quem abriu a tela. Um `expect(campo).toHaveValue("2026-10-10T09:00")`
 * está, portanto, afirmando sobre o fuso da MÁQUINA que roda a suíte — mesmo quando o teste
 * acha que fala do tenant. Enquanto o `env: { TZ: "America/Sao_Paulo" }` do `vitest.config.ts`
 * chega a tempo (pool `forks`), a asserção passa; sob qualquer runner que force `threads` — o
 * caso do `@stryker-mutator/vitest-runner` — o mesmo teste reprova com uma HORA errada, e a
 * mensagem fala de agenda em vez de ambiente. Foi o que a issue #169 pagou em `grade.test.ts`.
 *
 * A conversão de volta desfaz exatamente o que o navegador fez — `new Date(valor)` interpreta a
 * string naive no fuso local, o mesmo em que ela foi escrita — e entrega o INSTANTE, que não tem
 * fuso. Formatá-lo no fuso do TENANT dá a única leitura que o teste realmente quer afirmar, e ela
 * é a mesma em São Paulo, em UTC ou em Tóquio.
 *
 * ## O que isto NÃO faz
 *
 * Não substitui a prova de fuso: com o tenant no MESMO fuso da máquina, ida e volta se cancelam
 * por construção e uma conversão de tenant ausente na produção sobrevive. Quem mata essa mutação
 * é o teste que roda com `fusoDoTenant = "Asia/Tokyo"` — ver `NewEventModal.test.tsx` e a régua
 * do CLAUDE.md §5.2.
 *
 * @param el o campo `datetime-local` já obtido pela query do testing-library
 * @param tz fuso do tenant vigente NAQUELE teste (o mesmo que o `vi.mock` de `store/auth` devolve)
 * @returns `"10/10/2026 09:00"`, ou uma mensagem legível quando o campo não tem data válida —
 *          uma mutação que esvazia o campo tem de aparecer como campo vazio no diff da asserção,
 *          nunca como um `RangeError: Invalid time value` sem relação com o que se media.
 */
export function paredeDoTenant(el: HTMLElement, tz: string): string {
  const valor = (el as HTMLInputElement).value;
  const instante = new Date(valor);
  if (Number.isNaN(instante.getTime())) {
    return `(campo sem datetime-local válido: ${JSON.stringify(valor)})`;
  }
  return formatDateTime(instante.toISOString(), tz);
}
