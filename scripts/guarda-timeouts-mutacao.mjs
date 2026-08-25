#!/usr/bin/env node
// A corrida de mutação SÓ VALE EM MÁQUINA DEDICADA — e este script é quem cobra isso (issue #213).
//
// ── O DEFEITO DE RÉGUA ───────────────────────────────────────────────────────────────────────────
// No Stryker, `Timeout` conta como MORTO. A fórmula está em `mutation-testing-metrics@3.8.4`,
// `dist/src/calculateMetrics.js`, e é literal:
//
//     const totalDetected = timeout + killed;
//     mutationScore = (totalDetected / totalValid) * 100
//
// Consequência: todo mutante que estourar o relógio POR CONTENÇÃO DE CPU — e não por ter entrado
// em laço — é creditado como se um teste o tivesse pego. A régua fica OTIMISTA exatamente quando o
// ambiente está pior, que é o pior momento para ela mentir a favor.
//
// Medido em campo (issue #213, reproduzindo a triagem do #191 em `features/financeiro/contas.ts`):
//
//     Onde                                    | Score  | Sobreviventes | Timeouts
//     ----------------------------------------|--------|---------------|---------
//     CI (runner dedicado, 2 vCPU)            | 86,98  | 39            | 0
//     Local, 10 worktrees, ~80 processos node | 90,79  | 27            | 12
//
// 27 + 12 = 39: são OS MESMOS mutantes. Doze deles viraram `Timeout` em vez de `Survived`, e o
// módulo mediu ~3,8 pontos a mais do que a verdade. Os doze eram `StringLiteral` em declaração de
// constante (`export const KIND_INVESTMENT = "investment";`) — não existe laço possível ali. O
// timeout era do PROCESSO, não do mutante.
//
// ── POR QUE UM LIMIAR, E NÃO MEXER NO `timeoutMS`/`timeoutFactor` ────────────────────────────────
// Afrouxar o relógio (saída 1 da issue) reduz o falso-morto mas não o elimina: contenção não tem
// teto — com a máquina suficientemente carregada, QUALQUER `timeoutMS` finito estoura. E o preço é
// pago no caso que importa: um mutante que causa laço de verdade passaria mais tempo rodando antes
// de ser detectado, e quem o pegaria seria o teto do job (`timeout-minutes: 120`).
//
// Tratar `Timeout` como inconclusivo (saída 2) é o que a semântica pede, e NÃO É CONFIGURÁVEL na
// versão em uso: `@stryker-mutator/core@10.0.0` expõe 45 opções
// (`@stryker-mutator/api/dist/schema/stryker-core.json`) e nenhuma remapeia status — só
// `timeoutMS`, `timeoutFactor`, `dryRunTimeoutMinutes`, `ignoreStatic` e `ignorers` (que ignora
// mutantes por PADRÃO DE CÓDIGO, na instrumentação, não por resultado). A soma `timeout + killed`
// é código, não opção.
//
// Sobra a saída 3, e ela tem base empírica forte. As TRÊS corridas de CI que completaram mediram,
// cada uma, exatamente 1 timeout em 1.779 mutantes — e sempre O MESMO mutante:
//
//     run 32478357936  21/08/2026  e422278  | 1 timeout | grade.ts:294 UpdateOperator
//     run 32508528834  21/08/2026  707f28e  | 1 timeout | grade.ts:294 UpdateOperator
//     run 32557684625  22/08/2026  2d03320  | 1 timeout | grade.ts:294 UpdateOperator
//
// Esse mutante é um VERDADEIRO POSITIVO: `grade.ts:294` é
// `for (let h = HORA_ABERTURA; h < HORA_FECHAMENTO; h++)`, e o `UpdateOperator` troca `h++` por
// `h--`. É laço infinito de verdade — timeout é a detecção CERTA dele. Ou seja: em máquina
// dedicada o número de timeouts é estável, pequeno e inteiramente explicável. É justamente isso
// que o torna um sinal utilizável.
//
// ── DE ONDE VEM O 5 ──────────────────────────────────────────────────────────────────────────────
// Não é gosto; é a folga entre o regime medido e o defeito observado.
//
//  - **Piso:** 1, reproduzido em 3 de 3 corridas de CI, sempre o mesmo mutante de laço real.
//  - **Teto observado do defeito:** 12 timeouts em UM ÚNICO módulo na máquina carregada.
//  - **Custo de errar para cima:** cada timeout vale, no PIOR caso (se fosse `Survived`),
//    1/1772 = 0,0564 ponto de otimismo. Cinco valem 0,28 ponto — menos de 10% da margem de
//    3,52 pontos que separa o baseline (83,52) do `thresholds.break: 80`. Ou seja: uma medição
//    que PASSA por esta guarda pode estar otimista em no máximo ~0,3 ponto, e nessa escala o
//    `break` continua significando o que diz.
//  - **Tolerância a laço real novo:** 5 é 5x o piso. Quatro mutantes de laço genuínos podem
//    aparecer (código novo entra sozinho, `mutate` é DESCOBERTO) sem que a guarda dispare.
//
// 5 fica confortavelmente ACIMA do que a CI mede e confortavelmente ABAIXO do que a contenção
// produziu. Se um dia a guarda disparar por laço real, o conserto é subir o limiar COM a evidência
// — os mutantes listados na saída — e não silenciá-la.
//
// ── O QUE FAZER QUANDO ELA DISPARA ───────────────────────────────────────────────────────────────
// 1. Olhe a lista que este script imprime. `UpdateOperator`/`ConditionalExpression` em cabeçalho de
//    laço são candidatos a laço REAL. `StringLiteral` em declaração de constante não é: é máquina.
// 2. Se for máquina: a medição não vale. Rode de novo sozinho, sem outra suíte por cima
//    (`scripts/gates.sh` explica por que suítes concorrentes se contaminam, issue #162).
// 3. Se for laço real: suba `LIMIAR_PADRAO` aqui, citando a corrida que serviu de evidência.
//
// ── COMO RODAR ───────────────────────────────────────────────────────────────────────────────────
//   node scripts/guarda-timeouts-mutacao.mjs apps/web/reports/mutation/mutation.json
//   node scripts/guarda-timeouts-mutacao.mjs <relatorio.json> --limiar 3
//
// Saída: 0 = dentro do regime · 1 = timeouts acima do limiar (medição suspeita) · 2 = sem
// relatório legível. O 2 é deliberado: um guarda que se pula sozinho quando falta a entrada fica
// verde sem ter guardado nada, e é a mesma falha-dura anti-vacuidade que o `ci.yml` já aplica ao
// `rls_e2e` e aos gates de `infra/`.

import { readFileSync } from "node:fs";

/** Ver "DE ONDE VEM O 5" no cabeçalho. Mexer aqui exige citar a corrida que justifica. */
export const LIMIAR_PADRAO = 5;

/** Lê um relatório do Stryker; devolve `null` se não existir ou não for JSON válido. */
export function lerRelatorio(caminho) {
  try {
    return JSON.parse(readFileSync(caminho, "utf-8"));
  } catch {
    return null;
  }
}

/**
 * Extrai o que a guarda precisa de um `mutation.json`: os mutantes que estouraram o relógio e a
 * contagem por status (esta última alimenta a aritmética do pior caso).
 */
export function medirTimeouts(relatorio) {
  const timeouts = [];
  const contagem = { Killed: 0, Timeout: 0, Survived: 0, NoCoverage: 0 };

  for (const [caminho, arquivo] of Object.entries(relatorio.files ?? {})) {
    for (const mutante of arquivo.mutants ?? []) {
      if (mutante.status in contagem) contagem[mutante.status] += 1;
      if (mutante.status !== "Timeout") continue;
      timeouts.push({
        caminho,
        linha: mutante.location?.start?.line ?? 0,
        mutador: mutante.mutatorName ?? "?",
      });
    }
  }

  timeouts.sort((a, b) => a.caminho.localeCompare(b.caminho) || a.linha - b.linha);
  return { timeouts, contagem };
}

/**
 * O score como o Stryker o calcula, e o score do PIOR CASO — aquele em que todo timeout era, na
 * verdade, um sobrevivente. A distância entre os dois é o tamanho da dúvida que esta guarda mede.
 *
 * Fórmula conferida contra a corrida 32478357936, que o Stryker reportou como 83,52:
 * (1479 + 1) / 1772 = 83,52.
 */
export function scores({ Killed, Timeout, Survived, NoCoverage }) {
  const validos = Killed + Timeout + Survived + NoCoverage;
  if (validos === 0) return { medido: null, piorCaso: null };
  return {
    medido: ((Killed + Timeout) * 100) / validos,
    piorCaso: (Killed * 100) / validos,
  };
}

export function avaliar(relatorio, limiar = LIMIAR_PADRAO) {
  const { timeouts, contagem } = medirTimeouts(relatorio);
  return {
    timeouts,
    contagem,
    limiar,
    ...scores(contagem),
    // ESTRITO: um empate exato no limiar PASSA — a mesma convenção do `thresholds.break` do
    // Stryker, cujo `determineExitCode()` compara `mutationScore < break`.
    dispara: timeouts.length > limiar,
  };
}

const n2 = (v) => (v === null || v === undefined ? "—" : v.toFixed(2));

export function montarMensagem(r, limiarBreak) {
  const n = r.timeouts.length;
  const linhas = [];

  linhas.push(
    r.dispara
      ? `ERRO: ${n} timeouts na corrida de mutacao (limiar: ${r.limiar}). A MEDICAO NAO E CONFIAVEL.`
      : `OK: ${n} timeout(s) na corrida de mutacao (limiar: ${r.limiar}).`,
  );

  if (r.medido !== null) {
    linhas.push(
      `Score medido: ${n2(r.medido)}%. No pior caso — se TODO timeout fosse na verdade um ` +
        `sobrevivente — seria ${n2(r.piorCaso)}%, ou seja, ate ${n2(r.medido - r.piorCaso)} ` +
        `ponto(s) de otimismo.`,
    );
    if (typeof limiarBreak === "number") {
      linhas.push(
        `O thresholds.break e ${limiarBreak}: o pior caso ` +
          (r.piorCaso < limiarBreak
            ? `CRUZA o limiar (${n2(r.piorCaso)} < ${limiarBreak}).`
            : `ainda fica acima dele (${n2(r.piorCaso)} >= ${limiarBreak}).`),
      );
    }
  }

  if (n > 0) {
    linhas.push("", "Mutantes que estouraram o relogio:");
    for (const t of r.timeouts) linhas.push(`  - ${t.caminho}:${t.linha} (${t.mutador})`);
  }

  if (r.dispara) {
    linhas.push(
      "",
      "UpdateOperator/ConditionalExpression em cabecalho de laco podem ser laco REAL — timeout e a",
      "deteccao certa deles. StringLiteral em declaracao de constante nao pode enlacar: ali o",
      "timeout e da MAQUINA, e o score esta otimista (issue #213).",
      "",
      "A corrida de mutacao so vale em maquina dedicada. Rode de novo sem outra suite por cima.",
    );
  }

  return linhas.join("\n");
}

export function principal(argv) {
  const i = argv.indexOf("--limiar");
  const limiar = i === -1 ? LIMIAR_PADRAO : Number(argv[i + 1]);
  // ⚠️ O `i === -1` PRECISA ser tratado à parte: sem ele, `k !== i + 1` vira `k !== 0` e o filtro
  // come justamente o caminho do relatório — o uso mais comum (sem `--limiar`) devolvia exit 2
  // reclamando de argumento faltando. Pego na primeira execução contra o artefato real da CI.
  const caminho = (i === -1 ? argv : argv.filter((_, k) => k !== i && k !== i + 1))[0];

  if (!caminho || !Number.isFinite(limiar) || limiar < 0) {
    process.stderr.write(
      "uso: node scripts/guarda-timeouts-mutacao.mjs <mutation.json> [--limiar N]\n",
    );
    return 2;
  }

  const relatorio = lerRelatorio(caminho);
  if (!relatorio) {
    process.stderr.write(
      `ERRO: nao consegui ler ${caminho}. A corrida nao produziu relatorio — ela abortou antes de ` +
        "medir, e nao ha nada a guardar. Isto NAO e aprovacao.\n",
    );
    return 2;
  }

  const r = avaliar(relatorio, limiar);
  process.stdout.write(montarMensagem(r, relatorio.thresholds?.break) + "\n");
  return r.dispara ? 1 : 0;
}

// `import.meta.main` existe do Node 24 em diante — o mesmo Node do job. O fallback cobre quem
// rodar numa versão anterior na mão.
if (import.meta.main ?? process.argv[1]?.endsWith("guarda-timeouts-mutacao.mjs")) {
  process.exit(principal(process.argv.slice(2)));
}
