// Guarda de timeout individual (issue #231) — mesmo espírito de
// `scripts/guarda-timeouts-mutacao.mjs` (issue #213): transformar sintoma em SINAL antes de virar
// vermelho. Lá era timeout de mutante mascarando score; aqui é duração de teste se aproximando do
// `testTimeout` — o mesmo tipo de folga que já foi consumida uma vez (o próprio `vitest.config.ts`
// subiu de 5000 para 15000ms citando PlatformUsers.test.tsx/ContractBuilderPage.test.tsx, e os
// dois voltaram a se aproximar do teto sob carga). Sem um guarda, a suíte só avisa quando ESTOURA
// — tarde demais para quem só vê o CI vermelho e nenhuma pista de qual arquivo é o de sempre.
//
// ── POR QUE AVISO, E NÃO REPROVAR A SUÍTE ────────────────────────────────────────────────────────
// Reprovar exigiria um limiar rígido, e duração de teste sob CPU compartilhada (várias worktrees,
// CI concorrente) é ruidosa por natureza — o mesmo teste variou de ~2,1s isolado a ~8,5s sob a
// suíte inteira em paralelo (medido, issue #231). Um `expect` sobre isso seria flaky por
// construção. O valor aqui é o mesmo do guarda de mutação: dar NOME ao sintoma cedo, não bloquear
// a esteira por uma métrica ruidosa.
//
// ── POR QUE METADE DO `testTimeout` ──────────────────────────────────────────────────────────────
// 50% dá uma folga simétrica: um teste que já gastou metade do orçamento tem, na pior hipótese
// (mesma contenção dobrando de novo), exatamente o resto do orçamento para terminar. É o ponto em
// que "ainda passou" começa a virar "quase não passou" — cedo o bastante para agir antes do
// primeiro estouro real, tarde o bastante para não avisar por qualquer teste de componente normal
// (a suíte inteira, pós-conserto do #231, roda com folga de ~4x nesse limiar — ver
// `PlatformUsers.test.tsx`/`ContractBuilderPage.test.tsx`).

import type { File, Reporter, Task } from "vitest";

/** Ver "POR QUE METADE" no cabeçalho. Mexer aqui exige citar a medição que justifica. */
export const LIMIAR_FRACAO_PADRAO = 0.5;

export interface TesteMedido {
  arquivo: string;
  titulo: string;
  duracaoMs: number;
}

export interface TesteLento extends TesteMedido {
  fracao: number;
}

/**
 * Achata a árvore de tasks do Vitest (File → Suite → Test, aninhado) numa lista plana de testes
 * FOLHA que realmente rodaram (com `result.duration` populado). Suites, `describe`s e testes
 * pulados/todo não entram — não têm duração própria a medir.
 */
export function achatarTestes(files: readonly File[]): TesteMedido[] {
  const testes: TesteMedido[] = [];

  // Visita SÓ o que está DENTRO do file task (describe/it aninhados). Deliberadamente não decide
  // "é o file task?" olhando `task.type` — em runtime o node raiz de um arquivo às vezes chega
  // marcado como `type: 'suite'` (é uma Suite por herança de interface: `File extends Suite`), e
  // decidir por tipo o classificaria como describe e prefixaria o TÍTULO com o caminho do arquivo
  // inteiro (medido rodando de verdade — ver prova da issue #231). O parâmetro `files` já É a
  // lista de file tasks por construção (é o que o Vitest entrega em `onFinished`), então o nível
  // raiz nunca precisa disso — só os filhos.
  function visitar(task: Task, caminhoTitulo: string[]) {
    if (task.type === "suite") {
      for (const filho of task.tasks) visitar(filho, [...caminhoTitulo, task.name].filter(Boolean));
      return;
    }
    if (task.type !== "test") return; // "custom" (benchmarks etc.) fora do escopo deste guarda.
    const duracaoMs = task.result?.duration;
    if (typeof duracaoMs !== "number") return; // não rodou (skip/todo) ou não tem medição.
    testes.push({
      arquivo: task.file.filepath,
      titulo: [...caminhoTitulo, task.name].filter(Boolean).join(" > "),
      duracaoMs,
    });
  }

  for (const file of files) {
    for (const filho of file.tasks) visitar(filho, []);
  }
  return testes;
}

/**
 * Filtra os testes cuja duração já cruzou `limiarFracao` do `testTimeoutMs`, do mais lento para o
 * mais rápido. `testTimeoutMs` precisa ser > 0 — um projeto sem timeout configurado (`0`/`Infinity`
 * no Vitest) não tem "perto do limite" que faça sentido, e devolvemos lista vazia em vez de dividir
 * por zero/Infinity silenciosamente.
 */
export function encontrarTestesLentos(
  testes: readonly TesteMedido[],
  testTimeoutMs: number,
  limiarFracao: number = LIMIAR_FRACAO_PADRAO,
): TesteLento[] {
  if (!Number.isFinite(testTimeoutMs) || testTimeoutMs <= 0) return [];

  return testes
    .map((t) => ({ ...t, fracao: t.duracaoMs / testTimeoutMs }))
    .filter((t) => t.fracao >= limiarFracao)
    .sort((a, b) => b.fracao - a.fracao);
}

const n0 = (v: number) => Math.round(v);
const pct = (v: number) => Math.round(v * 100);

export function montarAviso(lento: TesteLento, testTimeoutMs: number): string {
  return (
    `AVISO [guarda-timeout-teste]: "${lento.titulo}" (${lento.arquivo}) levou ${n0(lento.duracaoMs)}ms ` +
    `— ${pct(lento.fracao)}% do testTimeout de ${testTimeoutMs}ms. Ainda passou, mas está perto do ` +
    "limite; se isto vira estouro sob carga (várias worktrees/CI concorrente), o conserto é a CAUSA " +
    "do teste (delay artificial, poll longo, userEvent sem `delay: null`), não subir o testTimeout " +
    "de novo — ver issue #231."
  );
}

/**
 * Reporter do Vitest: ao final da corrida, avisa (stderr) sobre testes que já cruzaram o limiar.
 * Deliberadamente NÃO altera `process.exitCode` — é aviso, não gate. Um gate duro sobre duração
 * ruidosa (CPU compartilhada) seria flaky por construção; ver cabeçalho do arquivo.
 */
export class GuardaTimeoutTeste implements Reporter {
  private testTimeoutMs = 5000; // default do Vitest; sobrescrito em onInit com o valor real.
  private readonly limiarFracao: number;

  constructor(opts: { limiarFracao?: number } = {}) {
    this.limiarFracao = opts.limiarFracao ?? LIMIAR_FRACAO_PADRAO;
  }

  onInit(ctx: { config: { testTimeout?: number } }): void {
    if (typeof ctx.config.testTimeout === "number") this.testTimeoutMs = ctx.config.testTimeout;
  }

  onFinished(files: File[] = []): void {
    const lentos = encontrarTestesLentos(achatarTestes(files), this.testTimeoutMs, this.limiarFracao);
    for (const lento of lentos) {
      console.warn(montarAviso(lento, this.testTimeoutMs));
    }
  }
}

export default GuardaTimeoutTeste;
