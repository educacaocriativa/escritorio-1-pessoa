import type { StockItem, StockSummary } from "@e1p/shared-types";
import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * "Movimentar: {item.name}" em 360×740 — um dos dois modais de título DIGITADO que faltavam (#130).
 *
 * `EstoquePage` monta o `AdjustModal` com <code>title={`Movimentar: ${item.name}`}</code>: o nome
 * do item é do dono e `ItemCreate.name` aceita **255 chars** (`stock/schemas.py`). É a exposição do
 * #119 — sem `min-w-0` o `<h2>` é item de flex com `min-width: auto`, então diante de uma palavra
 * sem espaço ele CRESCE, leva a linha do cabeçalho junto e empurra o "Fechar" para fora dos 360.
 *
 * ⚠️ A varredura é recortada pela CAIXA (`data-testid="modal-movimentar-item"`, aplicado pela prop
 * `testId` do `Modal`), nunca pelo conteúdo: com o recorte no `children`, cabeçalho e barra de ação
 * ficam fora da conta **por construção** — foi assim que uma medição devolveu lista vazia com o
 * botão 338px fora da tela (#119).
 *
 * ⚠️ E `scrollWidth` sozinho NÃO vê este defeito: com `min-w-0 break-words` removido do
 * `Modal.tsx`, `scrollWidth === clientWidth` segue verdadeiro enquanto a borda direita do título
 * vai muito além da caixa. Mede-se BORDA contra BORDA; `scrollWidth` é a segunda metade.
 */

// Pior caso PLAUSÍVEL (§5.1), não `lorem ipsum`: 76 chars sem espaço, hífen ou barra — o único
// formato em que o navegador não tem candidato a quebra —, dentro dos 255 que o backend aceita.
// É o que o dono digita de verdade num item de estoque com descrição comprida.
const NOME_SEM_ESPACO =
  "CartuchoDeTintaOriginalColoridoParaImpressoraMultifuncionalDoConsultorio664XL";

const ITEM: StockItem = {
  id: "00000000-0000-4000-8000-000000000010",
  tenant_id: "00000000-0000-4000-8000-000000000002",
  name: NOME_SEM_ESPACO,
  sku: "CTR-664XL-COLOR",
  product_id: null,
  quantity: 3,
  unit_cost_cents: 12990,
  min_quantity: 5,
  unit: "un",
  active: true,
  low: true,
  value_cents: 38970,
  created_at: "2026-01-10T10:00:00Z",
};

const RESUMO: StockSummary = {
  item_count: 1,
  // Valor de 6 dígitos: dado curto sempre cabe, e medir com ele é medir uma tela que não existe.
  total_value_cents: 12845079,
  low_stock_count: 1,
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/stock/summary": RESUMO,
    "/stock/items": [ITEM],
    "/products": [],
  });
  await page.goto("/estoque");
  await page.getByRole("button", { name: "Movimentar" }).click();
  await expect(page.getByTestId("modal-movimentar-item")).toBeVisible();
});

test("o nome digitado pelo dono não empurra o 'Fechar' para fora da tela", async ({ page }) => {
  const caixa = page.getByTestId("modal-movimentar-item");
  const fechar = await caixa.getByRole("button", { name: /fechar/i }).boundingBox();
  expect(fechar).not.toBeNull();
  expect(fechar!.x).toBeGreaterThanOrEqual(0);
  expect(fechar!.x + fechar!.width).toBeLessThanOrEqual(360);
});

test("o título QUEBRA dentro da caixa em vez de esticá-la", async ({ page }) => {
  const caixa = page.getByTestId("modal-movimentar-item");
  const titulo = caixa.getByRole("heading");
  await expect(titulo).toBeVisible();
  const daCaixa = await caixa.boundingBox();
  const doTitulo = await titulo.boundingBox();

  // As DUAS metades, e nesta ordem — a segunda sozinha é falsa confiança medida.
  //
  // 1) O `<h2>` não pode passar da borda direita da CAIXA. É esta que acusa o defeito do #119: o
  //    mínimo de um item de flex é o seu conteúdo mínimo (a palavra inteira), então ele não
  //    transborda — ele CRESCE, e leva o cabeçalho inteiro junto.
  expect(doTitulo!.x + doTitulo!.width).toBeLessThanOrEqual(daCaixa!.x + daCaixa!.width + 0.5);

  // 2) E não pode vazar TINTA mantendo a caixa no lugar (`overflow-wrap: normal` + palavra sem
  //    espaço) — o que `getBoundingClientRect` não vê e `scrollWidth` vê.
  const [scrollWidth, clientWidth] = await titulo.evaluate((el) => [el.scrollWidth, el.clientWidth]);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 0.5);
});

test("nada da CAIXA do 'Movimentar' existe só depois de rolar de lado", async ({ page }) => {
  expect(await textoForaDaTela(page, '[data-testid="modal-movimentar-item"]')).toEqual([]);

  // E a página não passa a rolar de lado só porque o modal abriu.
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("a régua enxerga um vazamento plantado no CABEÇALHO da caixa", async ({ page }) => {
  // Controle positivo, e é o ponto do #123: `[]` não distingue "nada vaza" de "nada foi medido".
  // A isca vai para o cabeçalho — a região que o recorte no `children` deixava de fora.
  const caixa = page.getByTestId("modal-movimentar-item");
  await caixa.evaluate((box) => {
    const isca = document.createElement("p");
    isca.textContent = "x".repeat(120);
    box.querySelector("h2")?.after(isca);
  });
  const cortes = await textoForaDaTela(page, '[data-testid="modal-movimentar-item"]');
  expect(cortes.length).toBeGreaterThan(0);
  expect(cortes[0].forcaFora).toBeGreaterThan(0.5);
});
