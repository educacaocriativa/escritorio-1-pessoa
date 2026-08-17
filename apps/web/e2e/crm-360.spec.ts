import { expect, test } from "@playwright/test";
// O atributo `with { type: "json" }` NÃO é opcional: o Playwright carrega os specs como ESM
// nativo do Node, que recusa importar JSON sem ele ("needs an import attribute").
import fixtures from "./fixtures/crm.json" with { type: "json" };
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O card do Kanban em 360px, depois que ele passou a dizer de onde o contato veio.
 *
 * O selo é o terceiro inquilino de uma linha que já dividia largura entre nome e tags, num card
 * que ainda tem alça de arrastar à esquerda e botão de ficha à direita. É exatamente a forma que
 * estourou a topbar (§5.1): todo filho encolhendo, ninguém com largura mínima.
 *
 * A fixture é de PIOR CASO PLAUSÍVEL: o rótulo mais comprido ("Integração") num card que também
 * tem o nome mais longo e duas tags, e o card de WhatsApp com o nome caindo no telefone cru —
 * que é como ele nasce quando o contato não tem `pushName`.
 *
 * [Onda 2, Task 8] O card ganhou uma TERCEIRA linha de rodapé: o próximo compromisso da Agenda
 * (ou o aviso de que não há um). `c2` — o card mais cheio, já disputando espaço com nome, duas
 * tags e o ponto de "esperando resposta" — é quem recebe o título de compromisso mais comprido
 * plausível, para provar que a linha TRUNCA de verdade em vez de só não estourar por sorte.
 */
test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, fixtures);
});

test("todo card diz de onde veio, e a origem cabe na tela", async ({ page }) => {
  await page.goto("/crm");

  const doWhatsapp = page.getByTitle("De onde este contato veio").first();
  await expect(doWhatsapp).toHaveText("WhatsApp");
  await expect(doWhatsapp).toBeInViewport();

  // O rótulo mais comprido, no card mais cheio. `toHaveText` (e não `toContainText`) porque um
  // selo truncado pela metade ainda conteria o começo da palavra.
  const daIntegracao = page.getByTitle("De onde este contato veio").nth(1);
  await expect(daIntegracao).toHaveText("Integração");
  await expect(daIntegracao).toBeInViewport();

  // A PÁGINA não rola de lado — quem rola é o contêiner do board, e isso é o que um Kanban é.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);

  // Por isso a varredura é escopada à PRIMEIRA coluna (`.w-72`, a que está na tela). Sem o
  // recorte, "Em contato", o contador dela e o "Solte um card aqui" aparecem como cortados —
  // três achados que existem porque a segunda coluna está adiante no deslizador, não porque
  // algum card esteja quebrado. Medido antes de escopar: eram exatamente esses três, e nenhum
  // texto de card. O comportamento é PRÉ-EXISTENTE e fora do escopo desta mudança.
  expect(await textoForaDaTela(page, ".w-72")).toEqual([]);

  // CONTROLE POSITIVO do recorte acima. Sem ele, um `.w-72` que deixasse de casar (renomear a
  // largura da coluna basta) devolveria vazio e o teste aprovaria a tela para sempre, sem medir
  // nada. Com seletor podre a varredura cai no documento inteiro e volta a achar as colunas
  // adiante — prova de que a função enxerga corte NESTA página, e que o `[]` acima é resultado.
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);
});

test("a origem não se parece com a tag", async ({ page }) => {
  await page.goto("/crm");
  await expect(page.getByText("vindo-do-site")).toBeVisible();

  // COR COMPUTADA, não classe CSS. `toContain("bg-neutral-100")` ficaria verde com o Tailwind
  // desligado, com a classe purgada do build, ou com um `bg-primary-50` vindo depois na cascata —
  // e a tela estaria com os dois selos idênticos, que é o defeito de origem desta mudança.
  //
  // ⚠️ E a asserção é ABSOLUTA, não relativa. `expect(origem).not.toBe(tag)` — a primeira forma
  // deste teste — sobrevivia à mutação que TROCA as duas cores: a diferença se preserva e o
  // significado se inverte, com o comentário do `CrmPage` dizendo o contrário do que a tela
  // mostra. Um caçador de bugs aplicou exatamente essa mutação e os 16 testes ficaram verdes.
  //
  // O que se afirma é o MATIZ, não o tom: a origem é acromática (cinza) e a tag é colorida (roxo).
  // Assim o teste não quebra quando o design system reajustar a escala — só quando alguém trocar
  // o papel das duas.
  //
  // Os limiares são MEDIDOS, não escolhidos: `neutral-100` (#ececef) dá croma **3** e `primary-50`
  // dá **18** nesta build. 8 e 12 dividem essa faixa com folga dos dois lados. Se um dia
  // encostarem, o design system aproximou as duas cores — e aí o teste está certo em reclamar,
  // porque a tela terá deixado de distinguir origem de tag.
  const croma = (sel: ReturnType<typeof page.getByText>) =>
    sel.evaluate((el) => {
      const [r, g, b] = (getComputedStyle(el).backgroundColor.match(/\d+/g) ?? []).map(Number);
      if (r === undefined) return { croma: -1, opaco: false };
      return {
        croma: Math.max(r, g, b) - Math.min(r, g, b),
        // Um selo sem fundo nenhum tem croma 0 e passaria como "cinza" — mas ele não existe na
        // tela. `backgroundColor` transparente vem como `rgba(0, 0, 0, 0)`: 4 números.
        opaco: !getComputedStyle(el).backgroundColor.startsWith("rgba(0, 0, 0, 0)"),
      };
    });

  const origem = await croma(page.getByTitle("De onde este contato veio").nth(1));
  const tag = await croma(page.getByText("vindo-do-site"));

  expect(origem.opaco).toBe(true);
  expect(tag.opaco).toBe(true);
  expect(origem.croma).toBeLessThanOrEqual(8); // cinza (medido: 3)
  expect(tag.croma).toBeGreaterThanOrEqual(12); // roxo (medido: 18)
});

test("o ponto de mensagem esperando resposta não empurra o nome para fora", async ({ page }) => {
  await page.goto("/crm");

  // O ponto está no card MAIS CHEIO da fixture: nome longo + duas tags + alça de arrastar +
  // botão de ficha. A linha do nome já era a mais disputada do card antes de ganhar inquilino.
  const ponto = page.getByLabel("Mensagem esperando resposta");
  await expect(ponto).toBeVisible();
  await expect(ponto).toBeInViewport();

  // O ponto tem `shrink-0`; quem cede é o nome, via `truncate`. A prova de que a divisão
  // funciona é o ponto estar INTEIRO dentro do card — 8px de largura, não 3 amassados.
  const caixaDoPonto = await ponto.boundingBox();
  expect(caixaDoPonto?.width).toBeGreaterThanOrEqual(7);

  // E nada da primeira coluna saiu da tela. Mesmo recorte `.w-72` e mesmo controle positivo
  // do primeiro teste deste arquivo — sem o controle, um seletor que deixasse de casar
  // aprovaria a tela para sempre.
  expect(await textoForaDaTela(page, ".w-72")).toEqual([]);
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});

test("a linha do próximo passo trunca — de verdade — e não estoura a coluna", async ({ page }) => {
  await page.goto("/crm");

  // O card mais cheio (c2, `next_event_title` da fixture) recebe o compromisso mais comprido
  // plausível: "Reunião de alinhamento do casamento 12/12". Não é escolhido por ACASO caber —
  // é escolhido por FORÇAR a reticência. A prova de que ela ENGATOU é `scrollWidth >
  // clientWidth` do próprio parágrafo (mesma régua de `.truncate` que a Onda 1 já usa em
  // `medidas.ts`), não a ausência de estouro na página: um texto que apenas coubesse por sorte
  // passaria nas DUAS provas e não provaria nada sobre o `truncate` em si.
  const proximo = page.getByText(/^próximo: Reunião de alinhamento/);
  await expect(proximo).toBeVisible();
  const [scrollWidth, clientWidth] = await proximo.evaluate((el) => [el.scrollWidth, el.clientWidth]);
  expect(scrollWidth).toBeGreaterThan(clientWidth);

  // A PÁGINA continua sem rolar de lado, e nada da PRIMEIRA coluna (onde o card mora) sai da
  // tela — mesmo recorte `.w-72` e mesmo controle positivo dos outros testes deste arquivo.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
  expect(await textoForaDaTela(page, ".w-72")).toEqual([]);
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);
});

test("o card sem próximo passo avisa, sem estourar a coluna", async ({ page }) => {
  await page.goto("/crm");

  // c1 tem `next_event_at`/`next_event_title` nulos os dois — o estado "sem próximo passo" que
  // a fixture exercita de propósito (ver comentário no topo do arquivo e em `crm.json`).
  await expect(page.getByText("sem próximo passo")).toBeVisible();

  expect(await textoForaDaTela(page, ".w-72")).toEqual([]);
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);
});
