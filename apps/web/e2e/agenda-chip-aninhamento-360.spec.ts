import { expect, test, type Locator, type Page } from "@playwright/test";
import { mockarApi } from "./support/api";
import { agendaEvent as evento } from "./support/fixtures";
import { semearSessao } from "./support/sessao";

/**
 * A régua do ANINHAMENTO CLICÁVEL da AGENDA (#183) — a irmã do #160, com outro limiar.
 *
 * O chip do compromisso morava DENTRO do `<button>` da célula do dia (`AgendaPage.tsx`), e os dois
 * abrem modais DIFERENTES: chip → detalhe do evento · célula → "Novo evento". Com dois alvos
 * clicáveis aninhados, o navegador emite o `click` no ANCESTRAL COMUM de `mousedown` e `mouseup` —
 * então um escorregão de poucos pixels entre apertar e soltar troca a ação, sem erro nenhum: o
 * hit-target do Playwright está satisfeito, porque o `mousedown` acertou o chip.
 *
 * ## Por que este arquivo existe separado de `aninhamento-clicavel-360.spec.ts`
 *
 * Outro limiar, outra geometria, outra prova. Lá o alvo interno é um ícone de canto de 16px e o
 * limiar medido é **10px**; aqui o chip é CONTEÚDO NO FLUXO da célula, mede 31,3×20,5 dentro de uma
 * célula de 44,3×92, e a meia-altura de **10,25px** é tudo o que separa os dois regimes. Os helpers
 * abaixo são CÓPIA, não import: a duplicação é barata perto de acoplar duas réguas que medem
 * gestos diferentes em telas diferentes.
 *
 * ## O limiar, medido em 21/08/2026 contra `origin/main` (viewport 360×740)
 *
 * Chip 31,3×20,5 em (119,6 · 602,8); célula 44,3×92 em (113,6 · 553,0). Duas varreduras, porque a
 * DIREÇÃO do escorregão importa e o desenho novo a muda:
 *
 * | deslocamento | → centro da célula (para CIMA em `main`) | → para BAIXO |
 * |---|---|---|
 * | 8px | chip · detalhe 1 · "Novo evento" 0 | chip · detalhe 1 · "Novo evento" 0 |
 * | 10px | chip · detalhe 1 · "Novo evento" 0 | chip · detalhe 1 · "Novo evento" 0 |
 * | 11px | chip · detalhe 1 · "Novo evento" 0 | **célula · detalhe 0 · "Novo evento" 1** |
 * | **12px** | **célula · detalhe 0 · "Novo evento" 1** | célula · detalhe 0 · "Novo evento" 1 |
 * | 14 / 16 / 20px | célula · detalhe 0 · "Novo evento" 1 | célula · detalhe 0 · "Novo evento" 1 |
 *
 * A coluna da esquerda REPRODUZ exatamente a tabela da issue: 12px é o limiar quando o escorregão
 * aponta para o centro da célula. A da direita mostra que, para baixo, bastam 11px.
 *
 * ⚠️ **E é por isso que o GESTO desta régua escorrega para BAIXO, não "na direção do centro da
 * célula".** Desaninhar sobe o chip de `y=602,8` para `y=588,0` (o `<button>` centralizava o
 * conteúdo verticalmente; a `<div>` o alinha no topo), e o centro do chip passa a ficar a **0,75px**
 * do centro da célula — a direção "para o centro" vira degenerada e 12px param de sair do chip.
 * Régua com gesto degenerado no código CORRIGIDO mede coisas diferentes nas duas versões e deixa de
 * ser comparável. Para baixo o gesto é o mesmo nas duas, com a mesma folga de 1,75px além da borda
 * do chip, e é também o escorregão que o dedo faz de verdade: a página rolando enquanto ele desce.
 *
 * ⚠️ **Esta régua mede o GESTO, não o CSS nem o markup.** `expect(html).toContain("<div")` seria a
 * família do `toContain("flex-wrap")` que o CLAUDE.md §5.1 proíbe: passaria com a tela quebrada.
 * A pergunta é a do dedo do dono: *o toque no chip, escorregando 12px, abriu o modal errado?*
 *
 * ⚠️ **Os DOIS controles positivos não são enfeite.** Sem (a) — o gesto emitiu exatamente 1
 * `click` — um gesto que não clica em nada passaria em toda asserção negativa, verde por não ter
 * medido (o modo de falha do #123). Sem (b) — nenhum `click` saiu do chip — um escorregão que não
 * SAI do chip também passa: o `click` volta para o chip, o detalhe abre, e "o 'Novo evento' não
 * abriu" continua verdadeiro com o aninhamento de pé. Foi assim que a primeira versão da régua do
 * #175 ficou 14/15 verde contra o código aninhado. Os dois estão medidos na tabela de mutação da PR.
 */

/** O limiar da issue, e o número medido de novo aqui: 12px entre `mousedown` e `mouseup`. */
const DESLOCAMENTO_PX = 12;

const EVENTO_ID = "ev-chip";
const CHIP = `chip-evento-${EVENTO_ID}`;
/** A célula do dia 18/08/2026 — o relógio abaixo congela a grade nesse mês. */
const CELULA = "celula-dia-2026-08-18";

/**
 * Pior caso PLAUSÍVEL (§5.1), não `lorem ipsum`: `title` aceita 255 chars (`agenda/schemas.py`) e o
 * que o dono digita num compromisso comprido é isto — sem espaço, sem hífen, sem barra. É também o
 * título que produziu o nome acessível engolido no snapshot do CI do #149.
 */
const TITULO =
  "AlinhamentoFinalDoCasamentoDaJulianaComTodosOsFornecedoresBuffetFotografiaEDecoracao2026";

type JanelaComGravador = Window & { __cliques?: string[] };

/**
 * Grava, com `capture` no `document`, QUAL elemento o navegador escolheu como alvo de cada `click`.
 * É a leitura direta do mecanismo — o ancestral comum — e não uma inferência a partir do sintoma.
 */
async function armarGravadorDeCliques(page: Page): Promise<void> {
  await page.evaluate(() => {
    const janela = window as Window & { __cliques?: string[] };
    janela.__cliques = [];
    document.addEventListener(
      "click",
      (ev) => {
        const alvo = ev.target as Element | null;
        const marca = alvo?.closest("[data-testid]")?.getAttribute("data-testid") ?? "";
        janela.__cliques?.push(`${alvo ? alvo.tagName.toLowerCase() : "?"}[${marca}]`);
      },
      true,
    );
  });
}

async function lerCliques(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as JanelaComGravador).__cliques ?? []);
}

/**
 * O GESTO: `mousedown` no centro do chip, `mouseup` `DESLOCAMENTO_PX` abaixo — ainda DENTRO da
 * célula. O "dentro da célula" é exigência, não detalhe: se o `mouseup` saísse dela, o ancestral
 * comum mudaria e a régua passaria a medir outra coisa.
 */
async function toqueQueEscorrega(page: Page, chip: Locator, celula: Locator): Promise<void> {
  const doChip = await chip.boundingBox();
  const daCelula = await celula.boundingBox();
  expect(doChip, "o chip precisa estar na tela — sem caixa não há gesto").not.toBeNull();
  expect(daCelula, "a célula precisa estar na tela — sem caixa não há alvo externo").not.toBeNull();

  const x = doChip!.x + doChip!.width / 2;
  const y0 = doChip!.y + doChip!.height / 2;
  const y1 = y0 + DESLOCAMENTO_PX;
  expect(
    y1,
    "o mouseup caiu FORA da célula — a régua mediria outro ancestral comum, não o aninhamento",
  ).toBeLessThan(daCelula!.y + daCelula!.height);

  await page.mouse.move(x, y0);
  await page.mouse.down();
  await page.mouse.move(x, y1);
  await page.mouse.up();
}

test.beforeEach(async ({ page }) => {
  // Relógio congelado em 18/08/2026 (fuso do tenant): a grade abre no mês CORRENTE, e sem isto o
  // compromisso simplesmente não estaria na tela.
  await page.clock.setFixedTime(new Date("2026-08-18T12:00:00Z"));
  await semearSessao(page);
  await mockarApi(page, {
    "/agenda/events": [
      evento({
        id: EVENTO_ID,
        title: TITULO,
        starts_at: "2026-08-18T13:00:00Z",
        ends_at: "2026-08-18T14:00:00Z",
      }),
    ],
  });
  await page.goto("/agenda");

  // A `marca` (§5.1): medir uma /agenda que renderizou em branco passa em qualquer régua negativa.
  await expect(page.getByRole("button", { name: "Hoje" })).toBeVisible();
  await expect(page.getByTestId(CELULA)).toBeVisible();
  await expect(page.getByTestId(CHIP)).toBeVisible();

  const caixa = (await page.getByTestId(CHIP).boundingBox())!;

  // ⚠️ **A guarda de ALCANCE, e ela é a lição do #159.** O card fantasma do `GanchoDaVima` empurrava
  // a tela 101px e punha o chip a 7,8px da dobra de 740px; um chip fora da viewport não pode ser
  // tocado, e o gesto abaixo bateria no `<html>` — verde por não ter medido nada. `toBeVisible()`
  // não acusa isso: o elemento está lá, com caixa e tudo, só que fora da tela.
  expect(caixa.x, "o chip escapou pela ESQUERDA da viewport de 360px").toBeGreaterThanOrEqual(0);
  expect(
    caixa.x + caixa.width,
    "o chip escapou pela DIREITA da viewport de 360px",
  ).toBeLessThanOrEqual(360);
  expect(caixa.y, "o chip escapou pelo TOPO da viewport de 740px").toBeGreaterThanOrEqual(0);
  expect(
    caixa.y + caixa.height,
    "o chip caiu ABAIXO da dobra de 740px — o gesto bateria no <html> e a régua não mediria nada",
  ).toBeLessThanOrEqual(740);

  // E a meia-altura do chip TEM de ser menor que o deslocamento, senão o escorregão de 12px cai
  // dentro dele e a régua vira um medidor de padding.
  expect(
    caixa.height / 2,
    `o chip ficou alto demais: o escorregão de ${DESLOCAMENTO_PX}px para baixo não sairia dele`,
  ).toBeLessThan(DESLOCAMENTO_PX);
});

test(`o toque no chip que escorrega ${DESLOCAMENTO_PX}px NÃO abre o "Novo evento"`, async ({
  page,
}) => {
  await armarGravadorDeCliques(page);

  await toqueQueEscorrega(page, page.getByTestId(CHIP), page.getByTestId(CELULA));

  // Controle positivo (a) do INSTRUMENTO, antes de qualquer asserção negativa: o gesto TEM de ter
  // produzido um `click`. Zero cliques passaria em tudo que vem abaixo sem medir nada (#123).
  await expect
    .poll(async () => (await lerCliques(page)).length, {
      message: "o gesto não emitiu click nenhum — a régua não mediu nada",
    })
    .toBe(1);

  // Controle positivo (b): o escorregão tem de ter SAÍDO do chip. Sem esta linha, "o 'Novo evento'
  // não abriu" não distingue "o aninhamento foi desfeito" de "o gesto nunca chegou a escorregar" —
  // e a segunda é verde com o defeito de pé.
  const cliques = await lerCliques(page);
  expect(
    cliques.filter((c) => c.includes(CHIP)),
    `o deslocamento de ${DESLOCAMENTO_PX}px não saiu do chip — a régua não mediu o aninhamento`,
  ).toEqual([]);

  // A AFIRMAÇÃO da issue: o modal ERRADO não abriu.
  await expect(
    page.getByRole("heading", { name: "Novo evento" }),
    `o escorregão de ${DESLOCAMENTO_PX}px abriu o "Novo evento": o chip voltou a ser filho do <button> da célula e o click caiu no ancestral comum (#183)`,
  ).toHaveCount(0);
});

test("o toque certeiro no chip abre o DETALHE, e não o 'Novo evento'", async ({ page }) => {
  await page.getByTestId(CHIP).click();

  await expect(page.getByTestId("modal-evento")).toBeVisible();
  // A metade que falta: com os dois handlers disparando, os DOIS modais ficam de pé e a linha de
  // cima passa verde.
  await expect(page.getByRole("heading", { name: "Novo evento" })).toHaveCount(0);
});

test("a célula continua abrindo o 'Novo evento' — pelo espaço vazio e pelo dia sem compromisso", async ({
  page,
}) => {
  // Abaixo do chip, na MESMA célula que tem compromisso: é o pedaço da célula que o dono toca para
  // marcar mais uma coisa naquele dia, e desaninhar não pode custá-lo.
  await page.getByTestId(CELULA).click({ position: { x: 22, y: 84 } });
  await expect(page.getByRole("heading", { name: "Novo evento" })).toBeVisible();
  await page.getByRole("button", { name: /fechar/i }).first().click();
  await expect(page.getByRole("heading", { name: "Novo evento" })).toHaveCount(0);

  // E um dia sem nenhum compromisso, onde a célula é a única coisa clicável.
  await page.getByTestId("celula-dia-2026-08-20").click();
  await expect(page.getByRole("heading", { name: "Novo evento" })).toBeVisible();
});

test("o nome acessível da célula não engole mais o compromisso", async ({ page }) => {
  // Aninhado, o snapshot do CI do #149 anunciava dia e compromisso como UM controle só:
  // `button "18 10:00 AlinhamentoFinalDoCasamentoDaJuliana…"`. A âncora `^...$` é o que prova que o
  // título não está mais lá dentro — uma asserção só de "contém 18" passaria com o defeito de pé.
  await expect(page.getByTestId(CELULA)).toHaveAccessibleName(/^Novo evento em 18 de agosto$/);

  // E o compromisso passa a ser um controle PRÓPRIO, com nome próprio — antes era uma `<div>` muda.
  await expect(page.getByTestId(CHIP)).toHaveRole("button");
  await expect(page.getByTestId(CHIP)).toHaveAccessibleName(new RegExp(TITULO));
});

test("os dois alvos são alcançáveis pelo TECLADO, um depois do outro", async ({ page }) => {
  // A metade que a desaninhagem não pode custar. Antes o chip era `<div onClick>`: invisível para o
  // teclado. Trocar um defeito de mouse por um de teclado seria trocar de defeito.
  await page.getByTestId(CELULA).focus();
  await expect(page.getByTestId(CELULA)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId(CHIP)).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("modal-evento")).toBeVisible();
});

test("a grade do mês continua inteira em 360px depois da remontagem", async ({ page }) => {
  // O custo que a issue avisou: desaninhar chips que são CONTEÚDO NO FLUXO significa remontar a
  // célula, e a grade tem de 35 a 42 delas numa tela de 360. Medido antes e depois: 42 células de
  // 44,3×92, nas mesmas 7 colunas, `scrollWidth` 360 nos dois casos.
  const celulas = page.locator('[data-testid^="celula-dia-"]');
  const total = await celulas.count();
  expect(total).toBeGreaterThanOrEqual(35);
  expect(total).toBeLessThanOrEqual(42);

  const caixas = [];
  for (let i = 0; i < total; i++) caixas.push((await celulas.nth(i).boundingBox())!);

  const larguras = new Set(caixas.map((c) => c.width.toFixed(1)));
  expect(larguras.size, "as células deixaram de ter a mesma largura").toBe(1);

  const colunas = new Set(caixas.map((c) => c.x.toFixed(1)));
  expect(colunas.size, "a grade deixou de ter 7 colunas alinhadas").toBe(7);

  for (const c of caixas) {
    expect(c.x, "uma célula escapou pela ESQUERDA da viewport de 360px").toBeGreaterThanOrEqual(0);
    expect(
      c.x + c.width,
      "uma célula escapou pela DIREITA da viewport de 360px",
    ).toBeLessThanOrEqual(360);
  }

  const larguraDaPagina = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(larguraDaPagina, "a /agenda passou a rolar de lado em 360px").toBe(360);
});
