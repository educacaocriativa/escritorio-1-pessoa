import type { Product } from "@e1p/shared-types";
import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * "Vender: {product.name}" em 360×740 — o outro modal de título DIGITADO que faltava (#130).
 *
 * `ProdutosPage` monta o `SellModal` com <code>title={`Vender: ${product.name}`}</code>: o nome do
 * produto é do dono e `ProductCreate.name` aceita **255 chars** (`products/schemas.py`). Mesma
 * exposição do #119 do "Movimentar" do Estoque, e a de maior consequência das duas — este é o modal
 * que registra dinheiro entrando.
 *
 * ⚠️ A varredura é recortada pela CAIXA (`data-testid="modal-vender-produto"`, pela prop `testId`
 * do `Modal`), nunca pelo conteúdo: recorte no `children` deixa cabeçalho e barra de ação fora da
 * conta por construção, e é ali que mora a saída de escape do modal.
 *
 * ⚠️ `scrollWidth` sozinho não vê o defeito do título — a BORDA vê (§5.1).
 */

// Pior caso PLAUSÍVEL (§5.1): 74 chars sem espaço, hífen ou barra, dentro dos 255 do backend. Um
// `lorem ipsum` tem espaço sobrando e mediria uma tela que não existe.
const NOME_SEM_ESPACO =
  "CursoCompletoDeGestaoFinanceiraParaProfissionaisAutonomosComCertificado2026";

const PRODUTO: Product = {
  id: "00000000-0000-4000-8000-000000000020",
  tenant_id: "00000000-0000-4000-8000-000000000002",
  name: NOME_SEM_ESPACO,
  kind: "membership",
  // Valor de 6 dígitos (R$ 2.997,00): dado curto sempre cabe.
  price_cents: 299700,
  description: "Turma de 2026 com mentoria em grupo.",
  active: true,
  stock: null,
  checkout_url: "https://flaviokato.e1p.com/checkout/curso-completo-de-gestao-financeira",
  students: 128,
  created_at: "2026-02-01T10:00:00Z",
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  // As três chaves são explícitas: `/products` sozinha casaria também `/products/coupons` e
  // `/products/enrollments` — o mock resolve pelo prefixo MAIS LONGO (ver `support/api.ts`), e
  // sem elas as outras abas leriam uma lista de PRODUTOS como se fosse a sua.
  await mockarApi(page, {
    "/products": [PRODUTO],
    "/products/coupons": [],
    "/products/enrollments": [],
  });
  await page.goto("/produtos");
  await page.getByRole("button", { name: "Vender" }).click();
  await expect(page.getByTestId("modal-vender-produto")).toBeVisible();
});

test("o nome digitado pelo dono não empurra o 'Fechar' para fora da tela", async ({ page }) => {
  const caixa = page.getByTestId("modal-vender-produto");
  const fechar = await caixa.getByRole("button", { name: /fechar/i }).boundingBox();
  expect(fechar).not.toBeNull();
  expect(fechar!.x).toBeGreaterThanOrEqual(0);
  expect(fechar!.x + fechar!.width).toBeLessThanOrEqual(360);
});

test("o título QUEBRA dentro da caixa em vez de esticá-la", async ({ page }) => {
  const caixa = page.getByTestId("modal-vender-produto");
  const titulo = caixa.getByRole("heading");
  await expect(titulo).toBeVisible();
  const daCaixa = await caixa.boundingBox();
  const doTitulo = await titulo.boundingBox();

  // 1) A borda — é ela que acusa o #119. Sem `min-w-0`, o `<h2>` cresce em vez de transbordar.
  expect(doTitulo!.x + doTitulo!.width).toBeLessThanOrEqual(daCaixa!.x + daCaixa!.width + 0.5);

  // 2) E a tinta que vaza sem alargar a caixa — o que só `scrollWidth` vê. Segunda metade, nunca
  //    a única: sozinha ela fica VERDE com a tela quebrada.
  const [scrollWidth, clientWidth] = await titulo.evaluate((el) => [el.scrollWidth, el.clientWidth]);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 0.5);
});

test("nada da CAIXA do 'Vender' existe só depois de rolar de lado", async ({ page }) => {
  expect(await textoForaDaTela(page, '[data-testid="modal-vender-produto"]')).toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("a régua enxerga um vazamento plantado no CABEÇALHO da caixa", async ({ page }) => {
  // Controle positivo: `[]` não distingue "nada vaza" de "nada foi medido".
  const caixa = page.getByTestId("modal-vender-produto");
  await caixa.evaluate((box) => {
    const isca = document.createElement("p");
    isca.textContent = "x".repeat(120);
    box.querySelector("h2")?.after(isca);
  });
  const cortes = await textoForaDaTela(page, '[data-testid="modal-vender-produto"]');
  expect(cortes.length).toBeGreaterThan(0);
  expect(cortes[0].forcaFora).toBeGreaterThan(0.5);
});
