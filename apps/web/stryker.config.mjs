// @ts-check
import { readdirSync, statSync } from "node:fs";
import { join, sep } from "node:path";

/**
 * Teste de MUTAÇÃO — a categoria de verificação que faltava no pipeline (issue #121).
 *
 * ## Por que isto existe
 *
 * Na PR #119 o QA achou NOVE defeitos com a suíte 100% verde: 693 testes, 32 medições de
 * 360px, `tsc` e `eslint` limpos. Verde era exatamente o estado em que o caça-bugs disse
 * FAIL. O que achou os defeitos foi mutação — desfazer uma linha da produção e ver se algum
 * teste morre. Nenhum job do CI fazia isso.
 *
 * O repositório já praticava mutação À MÃO, e o CLAUDE.md registra "provado por mutação" em
 * pelo menos cinco lugares (o `>` vs `>=` do `posted_at` que sobreviveu a 58 testes verdes,
 * o `begin_nested()` do ledger de IA, o `_proximo_marco` da Vima, a troca de cores
 * origem × tag do Kanban, os 5 de 5 do `grade.ts`). A prática estava estabelecida e
 * dependia de alguém LEMBRAR. Este arquivo é o fim dessa dependência.
 *
 * ## Como rodar
 *
 *   pnpm --filter @e1p/web mutation                    # tudo (dezenas de minutos)
 *   pnpm --filter @e1p/web mutation --mutate src/features/agenda/grade.ts   # um módulo
 *
 * No CI: `.github/workflows/mutation.yml`, NOTURNO (`schedule`), nunca por PR.
 */

const RAIZ = "src";

/**
 * A lista de módulos mutados é DESCOBERTA, não escrita à mão.
 *
 * Regra: todo `src/**\/*.ts` que tem um irmão `<nome>.test.ts` do lado. É a mesma escolha
 * que o `ci.yml` já faz no job `cross-tenant-rls` — lá o filtro é o marker `rls_e2e`, não uma
 * lista de nove arquivos nomeados, "assim um 10º futuro entra automaticamente, sem reeditar
 * este ci.yml". Aqui vale igual: o 26º módulo de lógica pura entra sozinho no dia em que
 * ganhar teste dedicado, e ninguém precisa lembrar de vir aqui.
 *
 * O que a regra EXCLUI, e por quê:
 * - `.tsx` — fora de escopo por decisão da issue. Mutação em React é lenta e ruidosa; o
 *   retorno está na aritmética de dinheiro, data e fuso.
 * - `.ts` SEM teste dedicado (hoje 8: `lib/api.ts`, `lib/texto.ts`, `lib/pluralize.ts`,
 *   `lib/whatsappCapabilities.ts`, `features/juridico/categories.ts`,
 *   `store/useIdleTimeout.ts`, `test-setup.ts`, `test/fixtures/agenda.ts`). Módulo sem
 *   teste dedicado pontua perto de zero e não diz nada de novo: já SABEMOS que não tem
 *   teste, e isso é trabalho de cobertura, não de mutação. Misturá-los afogaria o sinal —
 *   o score global viraria uma média de duas perguntas diferentes.
 * - os próprios arquivos de teste.
 */
function modulosComTesteDedicado(dir = RAIZ, achados = []) {
  for (const entrada of readdirSync(dir)) {
    const caminho = join(dir, entrada);
    if (statSync(caminho).isDirectory()) {
      modulosComTesteDedicado(caminho, achados);
      continue;
    }
    if (!entrada.endsWith(".ts")) continue;
    if (/\.(test|spec)\.ts$/.test(entrada) || entrada.endsWith(".d.ts")) continue;
    const irmaoDeTeste = caminho.replace(/\.ts$/, ".test.ts");
    try {
      statSync(irmaoDeTeste);
    } catch {
      continue;
    }
    // Stryker quer glob POSIX; no Windows o `join` devolve `\`.
    achados.push(caminho.split(sep).join("/"));
  }
  return achados;
}

const mutate = modulosComTesteDedicado();

// Falha-dura anti-escopo-vazio, mesma ideia do guard de `rls_e2e` no ci.yml: uma corrida de
// mutação que não muta NADA termina com 100% e um relatório verde vazio. Se um refactor
// mover `src/` de lugar, é melhor o job explodir aqui do que publicar aprovação sem medição.
if (mutate.length === 0) {
  throw new Error(
    "stryker: nenhum módulo `.ts` com teste dedicado foi encontrado em `src/`. " +
      "Isso não é 100% de score — é escopo vazio. Verifique a estrutura de pastas antes de confiar no relatório.",
  );
}

/** @type {import('@stryker-mutator/api/core').PartialStrykerOptions} */
export default {
  packageManager: "pnpm",
  testRunner: "vitest",

  // ⚠️ Declarar o plugin EXPLICITAMENTE não é redundância. O default do Stryker é o glob
  // `["@stryker-mutator/*"]` resolvido dentro de `node_modules`, e sob pnpm esse glob NÃO
  // acha nada: o layout do pnpm põe o pacote real no store e deixa só um link em
  // `apps/web/node_modules/@stryker-mutator/vitest-runner`. O sintoma é enganoso —
  // "Cannot find TestRunner plugin \"vitest\". In fact, no TestRunner plugins were loaded.
  // Did you forget to install it?" — com o pacote instalado e visível no diretório.
  plugins: ["@stryker-mutator/vitest-runner"],
  //
  // Consequencia pratica: os plugins carregados sao SO estes. Passar `--reporters` na linha de
  // comando (ex.: `--reporters clear-text,progress`) derruba a corrida com um erro de injecao do
  // typed-inject, porque o reporter pedido nao esta entre os plugins carregados. Medido em
  // 18/08/2026: `pnpm mutation` e `stryker run --mutate <arquivo>` rodam; os mesmos com
  // `--reporters` falham. Para trocar de reporter, edite `reporters` AQUI, nao na CLI.

  // Config de vitest própria da mutação — ver o cabeçalho de `vitest.mutation.config.ts`
  // para os dois motivos (unidade de medida e tempo) e para a direção do erro que ela causa.
  vitest: { configFile: "vitest.mutation.config.ts" },

  mutate,

  // `perTest` faz o Stryker rodar, para cada mutante, SÓ os testes que passaram por aquela
  // linha na corrida inicial. Sem isso cada um dos ~2 mil mutantes pagaria a suíte inteira e
  // o job noturno não fecharia numa noite.
  coverageAnalysis: "perTest",

  // `html` para o artefato do job noturno (mesmo padrão do `playwright-report`); `json` para
  // quem quiser somar score por módulo sem abrir o navegador; `clear-text` lista os
  // sobreviventes no log do job — é ali que a triagem começa.
  reporters: ["html", "json", "progress", "clear-text"],
  htmlReporter: { fileName: "reports/mutation/mutation.html" },
  jsonReporter: { fileName: "reports/mutation/mutation.json" },
  clearTextReporter: { allowColor: false, maxTestsToLog: 0 },

  // ⚠️ SEM `break`. O gate nasce OBSERVÁVEL, igual a `secret-scan`, `sast-semgrep` e
  // `frontend` no ci.yml — e aqui há um motivo a mais: limiar escrito antes da primeira
  // medição é número sem evidência (Artigo IV da Constitution, "No Invention"). O baseline
  // medido está no CLAUDE.md §5.2; a promoção a bloqueante vem depois de um período de
  // observação, e é uma edição de uma linha aqui (`break: <n>`).
  // `high`/`low` só colorem o relatório — não reprovam nada.
  thresholds: { high: 80, low: 60, break: null },

  // O timeout do Stryker é `tempo-do-teste-original * fator + offset`. Os testes de lógica
  // pura rodam em milissegundos, então o fator multiplica quase nada e um mutante que cai em
  // laço infinito ficaria dependendo só do offset. 10s de folga é barato aqui (são 25
  // arquivos rápidos) e evita marcar como "timeout" o que é só contenção de CPU na máquina
  // de quem roda local — o mesmo tipo de flake que já obrigou o `testTimeout: 15000` do
  // `vitest.config.ts`.
  timeoutMS: 10000,
  timeoutFactor: 2,

  // Fora do repositório: o diretório de trabalho do Stryker é volumoso e efêmero.
  tempDirName: ".stryker-tmp",
  cleanTempDir: true,

  // Sem `concurrency` fixo: o default do Stryker é (cpus-1), que serve tanto ao runner do
  // GitHub (2 vCPU) quanto à máquina de 12 vCPU onde o baseline foi medido. Pinar um número
  // faria o runner engasgar ou a máquina local ociar. Para forçar, use `--concurrency N`.
  ignorePatterns: [
    "dist",
    "playwright-report",
    "test-results",
    "reports",
    "e2e",
    ".stryker-tmp",
  ],
};
