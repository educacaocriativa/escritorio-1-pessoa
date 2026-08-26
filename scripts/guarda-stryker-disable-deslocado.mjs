#!/usr/bin/env node
// `Stryker disable next-line <mutador>` só suprime a mutação da linha LITERAL seguinte — e nada
// detectava quando a diretiva estava deslocada do alvo (issue #229).
//
// ── O DEFEITO ────────────────────────────────────────────────────────────────────────────────────
// Achado na triagem do #214 (PR #222): `financeiro/ledger.ts` e `financeiro/dreMatrixEntries.ts`
// traziam
//
//     // Stryker disable next-line EqualityOperator
//
// SETE LINHAS ACIMA do alvo de verdade. A linha seguinte LITERAL não era o código que a diretiva
// alegava suprimir — era outro comentário, parte do mesmo parágrafo explicativo. A supressão que o
// parágrafo descrevia NUNCA EXISTIU: o Stryker não pula linha de comentário procurando código: ele
// desativa o mutador só na linha imediatamente após a diretiva, comentário ou não.
//
// Provado pelo `mutation-report` da corrida 32557684625:
//
//     Arquivo                          | EqualityOperator | "Ignored using a comment" no arquivo
//     ----------------------------------|-------------------|--------------------------------------
//     financeiro/ledger.ts:42           | Survived          | 0
//     financeiro/dreMatrixEntries.ts:28 | Survived          | 0
//     pagar/baixa.ts:197 (encostada)    | —                 | 6
//
// O mecanismo funciona quando a diretiva encosta na linha, e falha em silêncio quando não encosta.
// Passou por DOIS relatórios de CI sem ninguém notar: o mutante aparece como `Survived`, e isso é
// indistinguível de dívida de teste comum — quem for triar depois gasta tempo tentando matar um
// mutante que alguém já tinha decidido dispensar (ou escreve um teste que fixa literal sem
// consequência observável, a família que o CLAUDE.md §5.1 proíbe).
//
// Os dois casos foram consertados no PR #222. Esta guarda fecha a REINCIDÊNCIA: nada, antes dela,
// detectava uma diretiva deslocada — só a sorte de alguém abrir o `mutation-report` e comparar
// número de `Ignored` contra o esperado.
//
// ── A REGRA ──────────────────────────────────────────────────────────────────────────────────────
// Para cada linha que contém "Stryker disable next-line", a próxima linha NÃO-EM-BRANCO do arquivo
// tem de ser código executável — nunca outro comentário. Só linhas totalmente em branco são
// puladas na busca; qualquer OUTRA linha de comentário (`//`, `/*`, ou `*` de continuação de bloco)
// reprova, porque é exatamente esse o caso que escapou: comentário-sobre-comentário.
//
// `pagar/baixa.ts:197` é a referência POSITIVA: a diretiva é a ÚLTIMA linha de comentário antes do
// `export const ALTURA_DA_BARRA = ...`, sem nenhuma linha de explicação depois dela. É a posição
// que toda diretiva tem de ocupar — explicar ANTES, diretiva por ÚLTIMO, encostada no alvo.
//
// ── O QUE FAZER QUANDO ELA DISPARA ───────────────────────────────────────────────────────────────
// Mova a diretiva (e só ela — a explicação continua onde está) para a última linha de comentário
// imediatamente acima do código que ela alega suprimir. Não é preciso reescrever a explicação: o
// PR #222 só moveu a linha da diretiva, o resto do parágrafo ficou onde estava.
//
// ── COMO RODAR ───────────────────────────────────────────────────────────────────────────────────
//   node scripts/guarda-stryker-disable-deslocado.mjs                    # varre apps/web/src
//   node scripts/guarda-stryker-disable-deslocado.mjs caminho/qualquer   # varre outro diretório
//
// Saída: 0 = nenhuma diretiva deslocada · 1 = alguma diretiva deslocada (reprovar o gate) · 2 =
// diretório inexistente ou sem nenhum `.ts`/`.tsx` para varrer. O 2 é deliberado: uma guarda que
// fica verde quando não achou o que guardar é a mesma falha-mole que o `ci.yml` já reprova no
// `rls_e2e` e nos gates de `infra/` — silêncio indistinguível de aprovação.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
export const RAIZ_REPO = resolve(__dirname, "..");
export const ALVO_PADRAO = join(RAIZ_REPO, "apps", "web", "src");

const EXTENSOES_VARRIDAS = new Set([".ts", ".tsx"]);
const DIRETORIOS_IGNORADOS = new Set(["node_modules", "dist", "build", ".turbo", "coverage"]);
const DIRETIVA = /Stryker disable next-line/;

/** Lista, recursivamente, todo `.ts`/`.tsx` sob `dir` — ordem estável (facilita comparar saída). */
export function listarArquivos(dir) {
  const resultado = [];

  function caminha(atual) {
    let entradas;
    try {
      entradas = readdirSync(atual, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entrada of entradas) {
      if (entrada.isDirectory()) {
        if (DIRETORIOS_IGNORADOS.has(entrada.name)) continue;
        caminha(join(atual, entrada.name));
      } else if (entrada.isFile() && EXTENSOES_VARRIDAS.has(extname(entrada.name))) {
        resultado.push(join(atual, entrada.name));
      }
    }
  }

  caminha(dir);
  return resultado.sort();
}

/**
 * Acha, no conteúdo de UM arquivo, toda diretiva `Stryker disable next-line` cuja linha seguinte
 * não-branca é outro comentário (ou cuja diretiva é a última linha do arquivo). `caminhoRelativo`
 * é só o que aparece na mensagem — a função não toca o sistema de arquivos.
 */
export function analisarConteudo(caminhoRelativo, conteudo) {
  const linhas = conteudo.split(/\r?\n/);
  const violacoes = [];

  for (let i = 0; i < linhas.length; i++) {
    if (!DIRETIVA.test(linhas[i])) continue;

    // A busca pula SÓ linha em branco — nunca outra linha de comentário. É esse o ponto inteiro
    // da guarda: comentário-sobre-comentário é o defeito, não uma exceção a ele.
    let j = i + 1;
    while (j < linhas.length && linhas[j].trim() === "") j++;

    if (j >= linhas.length) {
      violacoes.push({ caminho: caminhoRelativo, linha: i + 1, motivo: "fim-do-arquivo" });
      continue;
    }

    const proxima = linhas[j].trim();
    const ehComentario =
      proxima.startsWith("//") || proxima.startsWith("/*") || proxima.startsWith("*");
    if (ehComentario) {
      violacoes.push({
        caminho: caminhoRelativo,
        linha: i + 1,
        linhaSeguinte: j + 1,
        motivo: "comentario",
      });
    }
  }

  return violacoes;
}

export function montarMensagem(violacoes, arquivosVarridos, alvoExibido) {
  const linhas = [];

  if (violacoes.length === 0) {
    linhas.push(
      `OK: nenhuma diretiva 'Stryker disable next-line' deslocada (${arquivosVarridos} arquivo(s) ` +
        `.ts/.tsx em ${alvoExibido}).`,
    );
    return linhas.join("\n");
  }

  linhas.push(
    `ERRO: ${violacoes.length} diretiva(s) 'Stryker disable next-line' DESLOCADA(S) do alvo ` +
      `(${arquivosVarridos} arquivo(s) .ts/.tsx em ${alvoExibido}).`,
    "",
  );

  for (const v of violacoes) {
    if (v.motivo === "fim-do-arquivo") {
      linhas.push(
        `  - ${v.caminho}:${v.linha} — a diretiva é a ÚLTIMA linha do arquivo; não existe linha ` +
          "seguinte para suprimir. A supressão não existe.",
      );
    } else {
      linhas.push(
        `  - ${v.caminho}:${v.linha} — a linha seguinte não-branca (linha ${v.linhaSeguinte}) é ` +
          "outro COMENTÁRIO, não código executável. 'Stryker disable next-line' só suprime a linha " +
          "LITERAL seguinte; aqui essa linha é comentário, e a supressão nunca existiu (issue #229).",
      );
    }
  }

  linhas.push(
    "",
    "Mova a diretiva (só ela — a explicação pode continuar onde está) para a ÚLTIMA linha de",
    "comentário IMEDIATAMENTE ANTES do código que ela alega suprimir — a mesma posição de",
    "'apps/web/src/features/pagar/baixa.ts:197', a referência positiva.",
  );

  return linhas.join("\n");
}

export function principal(argv) {
  const alvo = resolve(argv[0] ?? ALVO_PADRAO);
  const alvoExibido = relative(RAIZ_REPO, alvo).split("\\").join("/") || ".";

  let alvoValido = false;
  try {
    alvoValido = statSync(alvo).isDirectory();
  } catch {
    alvoValido = false;
  }

  if (!alvoValido) {
    process.stderr.write(
      `ERRO: ${alvo} não existe ou não é um diretório legível. Nada a guardar — isto NAO e ` +
        "aprovacao.\n",
    );
    return 2;
  }

  const arquivos = listarArquivos(alvo);
  if (arquivos.length === 0) {
    process.stderr.write(
      `ERRO: nenhum arquivo .ts/.tsx encontrado em ${alvo}. Nada a guardar — isto NAO e ` +
        "aprovacao.\n",
    );
    return 2;
  }

  const violacoes = [];
  for (const arquivo of arquivos) {
    const conteudo = readFileSync(arquivo, "utf-8");
    const caminhoRelativo = relative(RAIZ_REPO, arquivo).split("\\").join("/");
    violacoes.push(...analisarConteudo(caminhoRelativo, conteudo));
  }

  process.stdout.write(montarMensagem(violacoes, arquivos.length, alvoExibido) + "\n");
  return violacoes.length > 0 ? 1 : 0;
}

// `import.meta.main` existe do Node 24 em diante — o mesmo Node do job. O fallback cobre quem
// rodar numa versão anterior na mão.
if (import.meta.main ?? process.argv[1]?.endsWith("guarda-stryker-disable-deslocado.mjs")) {
  process.exit(principal(process.argv.slice(2)));
}
