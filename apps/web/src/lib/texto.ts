/**
 * Operações de texto que não pertencem a nenhum domínio.
 *
 * Existe pelo mesmo motivo de `lib/pluralize.ts`, que é um módulo de três linhas: um one-liner
 * repetido em quatro arquivos é quatro chances de alguém "melhorar" um deles. Não mora em
 * `lib/datetime.ts` de propósito — o contrato estreito daquele módulo ("data e hora, e as duas
 * espécies não se misturam") é justamente o que o torna cobrável.
 */

/** `"junho de 2026"` → `"Junho de 2026"`. Só a primeira letra, sem tocar no resto. */
export const sentenceCase = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
