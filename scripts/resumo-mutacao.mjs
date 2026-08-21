#!/usr/bin/env node
// O job de mutação PASSA A FALAR — noite verde deixa de ser silenciosa.
//
// ── O PROBLEMA ───────────────────────────────────────────────────────────────────────────────────
// O `mutation.yml` só notifica quando FALHA: é assim que o GitHub Actions trata `schedule`. Com o
// `thresholds.break: 80` ligado (PR #189), isso significa que o score só vira notícia no dia em que
// cruza 80 — e a queda que levou até lá aconteceu em silêncio, uma noite de cada vez. O número
// existia apenas dentro do log e do artefato: para ver os 83,52 da primeira medição era preciso
// baixar 990 KB de JSON.
//
// Uma tendência que só fica visível depois de virar falha não é tendência, é surpresa. Este script
// põe o número na PÁGINA da corrida e compara com a noite anterior.
//
// ── COMO RODAR ───────────────────────────────────────────────────────────────────────────────────
//   node scripts/resumo-mutacao.mjs <atual.json> [anterior.json]
//
// Escreve markdown no stdout (o workflow redireciona para `$GITHUB_STEP_SUMMARY`) e, quando
// `GITHUB_OUTPUT` existe, publica `score`, `delta` e `alerta` para os passos seguintes.
//
// ── A REGRA DE ALERTA: EVENTO, NÃO ESTADO ────────────────────────────────────────────────────────
// Alerta só quando o score CAI >= 1,0 ponto contra a corrida anterior bem-sucedida.
//
// Foi considerado, e rejeitado, alertar por ESTADO ("margem até o break menor que 1 ponto").
// Estado repete: uma vez que o score se acomode em 80,4, TODA noite dispararia o mesmo aviso — e
// aviso que chega toda noite é aviso que se aprende a ignorar, o mesmo raciocínio que tirou a
// mutação das PRs, escrito no cabeçalho do `mutation.yml`. Queda é EVENTO: acontece uma vez, e
// depois dela o novo patamar vira a régua da comparação seguinte. Não repete sozinha.
//
// O caso "score baixo demais" já tem dono e não precisa de segundo mecanismo: o `thresholds.break`
// reprova o job, e job reprovado o GitHub notifica sozinho.
//
// ── FÓRMULA DO SCORE ─────────────────────────────────────────────────────────────────────────────
// (Killed + Timeout) / (Killed + Timeout + Survived + NoCoverage). `Ignored` fica FORA do
// denominador. Conferida contra a corrida 32478357936, que o Stryker reportou como 83,52:
// (1479 + 1) / 1772 = 83,52. Não é reimplementação por gosto — o `mutation.json` guarda mutantes,
// não o score, então somar é o único caminho a partir do artefato.

import { readFileSync, appendFileSync } from "node:fs";

const LIMIAR_DE_QUEDA = 1.0;

// Os mutadores que trocam COMPORTAMENTO, separados dos que trocam texto. A triagem da issue #191
// mostrou por que a distinção importa: 138 dos 269 sobreviventes da primeira corrida eram
// `StringLiteral`, e ordenar por contagem bruta apontava `app/navigation.ts` (51 sobreviventes,
// ZERO operador — é uma tabela declarativa, não exporta função nenhuma) como a pior dívida da
// árvore, quando o alvo de maior valor era uma única `ConditionalExpression` em `projecao.ts`.
// Um resumo que só mostrasse o total repetiria esse engano toda noite.
const OPERADORES = new Set([
  "ArithmeticOperator",
  "ConditionalExpression",
  "LogicalOperator",
  "EqualityOperator",
  "UpdateOperator",
  "MethodExpression",
  "OptionalChaining",
  "Regex",
]);

/** Lê um relatório; devolve `null` se não existir ou não for JSON válido. */
export function lerRelatorio(caminho) {
  try {
    return JSON.parse(readFileSync(caminho, "utf-8"));
  } catch {
    return null;
  }
}

function score(c) {
  const den = c.Killed + c.Timeout + c.Survived + c.NoCoverage;
  return den === 0 ? null : ((c.Killed + c.Timeout) * 100) / den;
}

export function medir(relatorio) {
  const porModulo = new Map();
  const total = { Killed: 0, Timeout: 0, Survived: 0, NoCoverage: 0, Ignored: 0 };

  for (const [caminho, arquivo] of Object.entries(relatorio.files ?? {})) {
    const m = { Killed: 0, Timeout: 0, Survived: 0, NoCoverage: 0, texto: 0, operadores: 0 };
    for (const mutante of arquivo.mutants ?? []) {
      if (mutante.status in total) total[mutante.status] += 1;
      if (mutante.status in m) m[mutante.status] += 1;
      if (mutante.status !== "Survived") continue;
      if (mutante.mutatorName === "StringLiteral") m.texto += 1;
      else if (OPERADORES.has(mutante.mutatorName)) m.operadores += 1;
    }
    porModulo.set(caminho, { ...m, score: score(m) });
  }

  return { score: score(total), total, porModulo };
}

const n2 = (v) => (v === null || v === undefined ? "—" : v.toFixed(2));

export function montarResumo(atual, anterior, limiarBreak) {
  const linhas = [];
  const delta = anterior && anterior.score !== null ? atual.score - anterior.score : null;
  const seta = delta === null ? "" : delta > 0.005 ? " ⬆️" : delta < -0.005 ? " ⬇️" : " ▪️";

  linhas.push(`## Mutation score: **${n2(atual.score)}%**${seta}`, "");

  if (delta === null) {
    linhas.push("_Sem corrida anterior para comparar — esta vira a régua da próxima._");
  } else {
    const sinal = delta >= 0 ? "+" : "";
    linhas.push(
      `Corrida anterior: ${n2(anterior.score)}% · **${sinal}${delta.toFixed(2)} ponto(s)**`,
    );
  }

  if (typeof limiarBreak === "number") {
    linhas.push(
      "",
      `Limiar de reprovação: **${limiarBreak}** · margem de **${(atual.score - limiarBreak).toFixed(2)} ponto(s)**.`,
    );
  }

  const t = atual.total;
  linhas.push(
    "",
    "| Mortos | Timeout | Sobreviventes | Sem cobertura | Ignorados |",
    "|---:|---:|---:|---:|---:|",
    `| ${t.Killed} | ${t.Timeout} | ${t.Survived} | ${t.NoCoverage} | ${t.Ignored} |`,
  );

  if (anterior) {
    // Quem PIOROU — a pergunta que o número global não responde. Sem isto, "caiu 1,4" manda
    // alguém baixar dois artefatos e fazer o diff à mão, que é exatamente o custo que este
    // script existe para tirar.
    const piores = [];
    for (const [caminho, a] of atual.porModulo) {
      const b = anterior.porModulo.get(caminho);
      if (!b || a.score === null || b.score === null) continue;
      if (a.score < b.score - 0.005) piores.push({ caminho, de: b.score, para: a.score });
    }
    piores.sort((x, y) => x.para - x.de - (y.para - y.de));
    if (piores.length) {
      linhas.push(
        "",
        "### Módulos que pioraram",
        "",
        "| Módulo | Antes | Agora |",
        "|---|---:|---:|",
      );
      for (const p of piores) {
        linhas.push(`| \`${p.caminho}\` | ${n2(p.de)} | **${n2(p.para)}** |`);
      }
    }

    const novos = [...atual.porModulo.keys()].filter((c) => !anterior.porModulo.has(c));
    if (novos.length) {
      // O escopo é DESCOBERTO (`stryker.config.mjs`): todo `.ts` com teste irmão entra sozinho.
      // É o suspeito nº 1 de uma queda que não veio de teste piorando — e a §5.3 do CLAUDE.md
      // avisa que a tabela de baseline não acompanha.
      linhas.push(
        "",
        `> ⚠️ **${novos.length} módulo(s) novo(s) no escopo** desde a corrida anterior: ` +
          novos.map((c) => `\`${c}\``).join(", ") +
          ". Módulo novo com teste mediano derruba o total sem que nenhum teste existente tenha piorado.",
      );
    }
  }

  // Ordenado por OPERADORES, não por total de sobreviventes: é a ordem de triagem da issue #191.
  const ordenado = [...atual.porModulo.entries()]
    .filter(([, m]) => m.Survived > 0)
    .sort((a, b) => b[1].operadores - a[1].operadores || b[1].Survived - a[1].Survived);

  if (ordenado.length) {
    linhas.push(
      "",
      "<details><summary>Sobreviventes por módulo (ordenado por operadores — ver #191)</summary>",
      "",
      "| Módulo | Score | Sobrev. | `StringLiteral` | Operadores |",
      "|---|---:|---:|---:|---:|",
    );
    for (const [caminho, m] of ordenado) {
      linhas.push(
        `| \`${caminho}\` | ${n2(m.score)} | ${m.Survived} | ${m.texto} | ${m.operadores} |`,
      );
    }
    linhas.push("", "</details>");
  }

  return { texto: linhas.join("\n"), delta };
}

export function principal(argv) {
  const relAtual = lerRelatorio(argv[0]);
  if (!relAtual) {
    // Corrida abortada (o dry run do Stryker morrendo, por exemplo) não produz relatório. Isso
    // NÃO é erro deste script: o job já falhou por conta própria e o GitHub já notificou.
    process.stdout.write(
      "## Mutation score: sem relatório\n\nA corrida não produziu `mutation.json` — abortou antes de medir. O vermelho do job é a notícia; o motivo está no log da etapa do Stryker.\n",
    );
    return { alerta: false, score: null, delta: null };
  }

  const atual = medir(relAtual);
  const relAnterior = argv[1] ? lerRelatorio(argv[1]) : null;
  const anterior = relAnterior ? medir(relAnterior) : null;

  const { texto, delta } = montarResumo(atual, anterior, relAtual.thresholds?.break);
  process.stdout.write(texto + "\n");

  const alerta = delta !== null && delta <= -LIMIAR_DE_QUEDA;

  if (process.env.GITHUB_OUTPUT) {
    appendFileSync(
      process.env.GITHUB_OUTPUT,
      `score=${n2(atual.score)}\ndelta=${delta === null ? "" : delta.toFixed(2)}\nalerta=${alerta}\n`,
    );
  }

  return { alerta, score: atual.score, delta };
}

// `import.meta.main` existe do Node 24 em diante — o mesmo Node do job. O fallback cobre quem
// rodar numa versão anterior na mão.
if (import.meta.main ?? process.argv[1]?.endsWith("resumo-mutacao.mjs")) {
  principal(process.argv.slice(2));
}
