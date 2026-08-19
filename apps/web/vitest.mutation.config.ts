import { defineConfig, mergeConfig } from "vitest/config";

import base from "./vitest.config";

// Config usada SÓ pelo teste de mutação (`stryker.config.mjs`, issue #121). Nada aqui muda
// o que `pnpm test` roda — o CI e a máquina de quem desenvolve continuam usando
// `vitest.config.ts` puro.
//
// Ela é um `mergeConfig` do config real DE PROPÓSITO, não uma cópia: se alguém mexer no
// `environment`, no `setupFiles` ou no `TZ` lá, a corrida de mutação acompanha sozinha. Uma
// segunda config copiada e colada envelhece em silêncio, e mutação medida num ambiente que
// não é o da suíte mede outra coisa.
//
// A ÚNICA diferença é o `exclude` dos `.test.tsx`, por dois motivos:
//
// 1. **Unidade de medida.** A issue #121 define o escopo como "módulo `.ts` com teste
//    dedicado". O que queremos saber é se o teste DEDICADO prende a lógica — não se algum
//    teste de componente passa por ela de raspão. Deixar o `.tsx` matar o mutante credita
//    cobertura incidental: o número sobe e a pergunta original fica sem resposta.
// 2. **Tempo.** Medido nesta máquina (12 vCPU): suíte inteira = 74s, só os 25 arquivos
//    `.test.ts` = 13,5s (308 dos 693 testes). O custo não está em rodar os testes (1,1s
//    somados) e sim em levantar o jsdom em cada worker (76s acumulados na suíte inteira).
//    Mutação roda a suíte MUITAS vezes; 5,5x no ciclo base é a diferença entre um job
//    noturno e um job que ninguém espera terminar.
//
// ⚠️ O erro que isso introduz tem direção conhecida e é o lado seguro: um mutante que só
// um teste de componente mataria aparece aqui como SOBREVIVENTE. Ou seja, a régua pode
// pedir teste a mais — nunca a menos. Na triagem, sobrevivente é hipótese a investigar,
// não veredito.
export default mergeConfig(
  base,
  defineConfig({
    test: {
      exclude: ["**/node_modules/**", "**/dist/**", "src/**/*.{test,spec}.tsx"],
    },
  }),
);
