// Setup global da suíte de testes (Story 7.3), referenciado em `vitest.config.ts` (setupFiles).
// Registra os matchers de DOM do `@testing-library/jest-dom` no `expect` do Vitest
// (`.toBeInTheDocument()`, `.toHaveValue()`, etc.). Fica dentro de `src/` de propósito: como
// o `tsconfig.json` inclui `["src"]`, este import de side-effect torna a AUGMENTAÇÃO de tipos
// dos matchers visível ao `tsc --noEmit` para TODOS os testes de componente — pilotos e os das
// Stories 7.4/7.5 — sem precisar de import por arquivo nem de mudança no tsconfig.
import "@testing-library/jest-dom/vitest";

// ── GUARDA DE AMBIENTE: o fuso efetivo (issue #169) ────────────────────────────────────────────
//
// O job `Mutation (noturno)` abortou nas suas duas unicas execucoes (19 e 20/08/2026), sempre no
// dry run do Stryker, e a unica notícia que o log deu foi esta:
//
//     expected '2026-10-11' to be '2026-10-10' // Object.is equality
//
// A causa era o fuso — o runner do GitHub roda em UTC — mas a mensagem fala de uma DATA de
// agenda. Quem le procura bug em `grade.ts`, nao configuracao de job. Duas noites de vermelho
// sem ninguem saber que o que faltava era um `TZ`. Este bloco faz o sintoma dizer o proprio nome.
//
// ⚠️ Por que AQUI, no setup, e nao num `*.test.ts` proprio — isto foi MEDIDO, nao suposto.
// O `@stryker-mutator/vitest-runner` monta o vitest com `bail: 1`. Com a suite em UTC, o arquivo
// que reprova primeiro e `grade.test.ts`, e a corrida PARA ali: numa medicao de 20/08/2026 com um
// guarda em arquivo separado, o resultado foi `1 failed | 10 passed | 7 skipped` — o guarda caiu
// entre os SETE PULADOS e nunca apareceu. Guarda que depende da ordem dos arquivos nao guarda
// nada. `setupFiles` roda antes de CADA arquivo, entao este erro nasce no primeiro deles,
// qualquer que seja.
//
// ⚠️ E por que `Intl...resolvedOptions()` e NAO `process.env.TZ`: os dois DISCORDAM, e e nessa
// discordancia que o defeito mora. Medido em 20/08/2026 (vitest 2.1.9, Node 24, maquina em UTC),
// dentro do pool `threads` que o Stryker forca: `process.env.TZ` = "America/Sao_Paulo" e o fuso
// efetivo = "UTC". O `env` do vitest CHEGA — chega tarde. Afirmar o env aqui daria VERDE no
// cenario exato que este guarda existe para pegar.
const FUSO_ESPERADO = "America/Sao_Paulo";
const fusoEfetivo = Intl.DateTimeFormat().resolvedOptions().timeZone;
if (fusoEfetivo !== FUSO_ESPERADO) {
  throw new Error(
    [
      `FUSO ERRADO NA SUITE: o fuso EFETIVO deste processo e "${fusoEfetivo}", e a suite exige "${FUSO_ESPERADO}".`,
      "Nao e bug de agenda, de data nem de `grade.ts`: e o AMBIENTE.",
      "",
      "Diagnostico (os dois valores DISCORDAM quando o defeito e este):",
      `  process.env.TZ ........ ${JSON.stringify(process.env.TZ)}`,
      `  fuso efetivo .......... ${JSON.stringify(fusoEfetivo)}`,
      "",
      "Se `process.env.TZ` ja esta certo e o efetivo nao, o `env` do vitest chegou TARDE: e o caso",
      "do pool `threads`, que `@stryker-mutator/vitest-runner` forca. Uma thread nasce dentro de um",
      "processo que ja escolheu seu fuso, e escrever em `process.env` depois nao reabre a escolha.",
      "",
      "Conserto: fixar `TZ` FORA do Node — `env:` no nivel do job em `.github/workflows/`, ou a",
      "variavel do shell antes de chamar o vitest. Nunca so no `env` do `vitest.config.ts`.",
    ].join("\n"),
  );
}


import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Limpeza do DOM entre os testes. O @testing-library/react só registra o cleanup automático
// quando há um `afterEach` GLOBAL (config `globals: true`); como mantemos `globals: false`
// (padrão de imports explícitos do projeto), registramos o cleanup aqui manualmente. Sem isto,
// o DOM de um teste vaza para o próximo (ex.: `queryByText` acha um elemento do render anterior).
// Vale para TODA a suíte de componentes — Stories 7.4/7.5 herdam sem precisar repetir.
afterEach(() => {
  cleanup();
});
