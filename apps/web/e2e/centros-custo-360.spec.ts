import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { LONGO } from "./support/rotas";
import { semearSessao } from "./support/sessao";

/**
 * `/financeiro/centros-custo` medida pela régua de TEXTO CORTADO (#157) — a classe do `R$ 3.` no
 * lugar de `R$ 3.000,00`, não a de alcançabilidade que o #156 fechou nesta mesma rota.
 *
 * ⚠️ **As duas réguas desta rota olham para defeitos OPOSTOS, e o #156 não cobre este.**
 * `alcance-360.spec.ts` pergunta se o dedo chega ao controle; ali «Editar» e «Arquivar» estavam
 * INTEIRAMENTE fora e o `flex-wrap` do #156 os trouxe de volta. Mas o `flex-wrap` só reposiciona
 * caixa — a TINTA continuou recortada: medido em 20/08/2026, 14 elementos de texto terminando
 * além da borda do cartão, com a página inteira ainda dizendo `scrollWidth === 360` porque
 * `overflow-hidden` engole o excesso em silêncio. Nenhuma régua verde via isso.
 *
 * ⚠️ **A armadilha já medida no #156, para quem for mexer aqui.** Pôr `break-words` no rótulo do
 * centro NÃO muda número nenhum: o `<span>` é item de flex com `min-width: auto`, então ele
 * CRESCE em vez de transbordar, e o `scrollWidth` do próprio elemento (que é o que a régua lê
 * quando `overflow-x` é `visible`) continua igual ao `clientWidth`. Quem vê o defeito do rótulo é
 * a BORDA do cartão. O que destrava é `min-w-0` na cadeia de flex ACIMA dele — sem isso o
 * `break-words` é peso morto.
 *
 * ⚠️ **`overflow-x-auto` na tabela NÃO deixa esta régua verde, e isso foi medido, não suposto.**
 * `textoForaDaTela` compara a borda do texto com a do ancestral que RECORTA — e um deslizador
 * recorta. Medido em 20/08/2026 com `overflow-x-auto` + `min-w-[36rem]` no lugar do
 * `overflow-hidden`: **12 cortes** na tabela, os mesmos de antes com 1,5px a menos por causa da
 * barra. É a mesma conclusão que a `InvestimentosPage` já tinha escrito com outras palavras — em
 * 360px uma tabela de 4 colunas não cabe, e a saída não é fazer a rolagem funcionar melhor, é não
 * precisar dela. Por isso o comparativo vira CARTÃO abaixo de `sm`, e a tabela (que é o formato
 * certo no desktop, onde se compara sócio com sócio lado a lado) só existe a partir dali.
 */

// Pior caso plausível, e é o MESMO da fixture do #144/#156 (`support/rotas.ts`) de propósito: o
// número desta issue tem de ser comparável ao que aquele PR mediu. 74 chars sem espaço, hífen ou
// barra, dentro dos 120 que `cost_centers/schemas.py` aceita.
const CENTROS = [
  {
    id: "cc1",
    tenant_id: "t1",
    name: LONGO,
    kind: "operacional",
    archived_at: null,
    created_at: "2026-01-01T10:00:00Z",
  },
];

// `by-cost-center` devolve OBJETO (com `[]`, o default de `mockarApi`, a tela quebraria no
// primeiro campo e mediria uma página em branco). Valores de 6 dígitos + o bucket sintético
// "Não atribuído", que é o caso que o dono mais lê.
const RELATORIO = {
  start: "2026-08-01",
  end: "2026-08-31",
  buckets: [
    {
      cost_center_id: "cc1",
      name: LONGO,
      kind: "operacional",
      receita_cents: 123456789,
      resultado_cents: -98765432,
      lancamentos: 42,
    },
    {
      cost_center_id: null,
      name: "Não atribuído",
      kind: null,
      receita_cents: 0,
      resultado_cents: -1234567,
      lancamentos: 3,
    },
  ],
  notes: [],
};

const LISTA = '[data-testid="lista-centros"]';
const COMPARATIVO = '[data-testid="comparativo-centros"]';

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/cost-centers": CENTROS,
    "/financial-intelligence/by-cost-center": RELATORIO,
  });
  await page.goto("/financeiro/centros-custo");
  // A `marca`: sem ela, "360" e "[]" significariam "não desenhou nada".
  await expect(page.getByTestId("comparativo-centros")).toBeVisible();
  await expect(page.getByTestId("lista-centros")).toBeVisible();
});

test("a página não rola de lado", async ({ page }) => {
  // Verde ANTES e DEPOIS do conserto — está aqui como CONTRASTE, não como cobertura: é o
  // `scrollWidth === 360` desta linha que fazia o defeito parecer inexistente enquanto 14
  // elementos de texto terminavam fora da borda do cartão.
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("o nome e o tipo do centro na LISTA não ficam fora da borda do cartão", async ({ page }) => {
  const cortes = await textoForaDaTela(page, LISTA);
  expect(cortes, JSON.stringify(cortes, null, 2)).toEqual([]);
});

test("nenhum valor do COMPARATIVO existe só depois de rolar de lado", async ({ page }) => {
  const cortes = await textoForaDaTela(page, COMPARATIVO);
  expect(cortes, JSON.stringify(cortes, null, 2)).toEqual([]);
});

test("o comparativo mostra o valor INTEIRO, com o separador de milhar", async ({ page }) => {
  // O defeito da 2b-ii em uma asserção, e ela é sobre TINTA: o texto "R$ 1.234.567,89" está no
  // DOM mesmo recortado, então `toContainText` sozinho não prova nada. O que prova é a caixa do
  // elemento que o contém terminar dentro dos 360px.
  //
  // `visible=true` porque o comparativo tem DOIS desenhos do mesmo dado no DOM (cartão < `sm`,
  // tabela >= `sm`) e o valor casa nos dois. Medir o que está `display: none` daria `null` e o
  // teste morreria pelo motivo errado. Depois de filtrar tem de sobrar EXATAMENTE um: dois
  // visíveis significaria que os dois desenhos estão na tela ao mesmo tempo — o defeito que o
  // par `sm:hidden` / `hidden sm:table` existe para evitar.
  const valor = page
    .getByTestId("comparativo-centros")
    .getByText("R$ 1.234.567,89", { exact: true })
    .locator("visible=true");
  await expect(valor).toHaveCount(1);
  const caixa = await valor.boundingBox();
  expect(caixa).not.toBeNull();
  expect(caixa!.x).toBeGreaterThanOrEqual(0);
  expect(caixa!.x + caixa!.width).toBeLessThanOrEqual(360);
});

test("no desktop quem aparece é a TABELA, e ela sozinha", async ({ page }) => {
  // A OUTRA METADE do par `sm:hidden` / `hidden sm:table` — e ela é invisível para um gate que só
  // mede 360px. Medido em 20/08/2026: tirar o `sm:hidden` do `<ul>` dos cartões não move um pixel
  // aqui, o mutante SOBREVIVE aos cinco testes acima, e ainda assim põe cartão e tabela na mesma
  // tela a partir de 640px. Por isso esta é a única linha do arquivo que troca a viewport: sem
  // ela, metade do conserto ficaria sem régua.
  await page.setViewportSize({ width: 900, height: 740 });
  await expect(page.getByTestId("comparativo-centros").getByRole("table")).toBeVisible();
  await expect(page.getByTestId("comparativo-centros").locator("ul")).toBeHidden();
  // `linha-centro` marca a linha nos DOIS desenhos. Duas visíveis = as duas `<tr>` da tabela e
  // nenhum cartão; quatro seria o defeito.
  await expect(page.getByTestId("linha-centro").locator("visible=true")).toHaveCount(2);
});

test("a régua enxerga uma isca plantada DENTRO de cada uma das duas superfícies", async ({
  page,
}) => {
  // Controle positivo. `[]` não distingue "nada vaza" de "nada foi medido" — e aqui o risco é
  // concreto: o conserto troca a `<table>` por cartões abaixo de `sm`, então um seletor que
  // dependesse de `td`/`tr` passaria a casar com NADA e o teste ficaria verde por cegueira. Por
  // isso a isca entra pelos `data-testid` da LINHA, que sobrevivem aos dois desenhos.
  //
  // `white-space: nowrap` de propósito: com `break-words` na cadeia consertada, uma isca comum
  // quebraria e o controle positivo morreria junto com o defeito.
  const plantarEMedir = async (secao: string, linha: string) => {
    await page.locator(`${secao} ${linha}`).first().evaluate((el) => {
      const isca = document.createElement("span");
      isca.textContent = "x".repeat(120);
      isca.style.whiteSpace = "nowrap";
      el.append(isca);
    });
    const cortes = await textoForaDaTela(page, secao);
    return cortes.filter((c) => c.texto.startsWith("x"));
  };

  expect(await plantarEMedir(LISTA, '[data-testid="item-centro"]')).toHaveLength(1);
  expect(await plantarEMedir(COMPARATIVO, '[data-testid="linha-centro"]')).toHaveLength(1);
});

test("um escopo podre aparece como RUÍDO, nunca como aprovação", async ({ page }) => {
  // A outra metade do controle positivo: se `LISTA`/`COMPARATIVO` deixassem de casar, a régua cai
  // no DOCUMENTO INTEIRO em vez de devolver `[]` (ver `textoForaDaTela`). Sem esta linha, um
  // `data-testid` renomeado transformaria os dois testes acima em verde permanente.
  //
  // A isca é plantada no `body` e não se apoia em nenhum corte pré-existente da tela: depois do
  // conserto a rota não tem mais nenhum, e um controle que dependesse disso morreria exatamente
  // quando o produto ficasse certo.
  await page.evaluate(() => {
    const isca = document.createElement("span");
    isca.textContent = "x".repeat(120);
    isca.style.whiteSpace = "nowrap";
    document.body.append(isca);
  });
  const cortes = await textoForaDaTela(page, ".seletor-que-nao-existe");
  expect(cortes.filter((c) => c.texto.startsWith("x"))).toHaveLength(1);
});
