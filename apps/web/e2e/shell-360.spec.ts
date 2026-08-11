import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * A barra superior em 360px.
 *
 * A atribuição original ("o culpado é o `ChevronDown` de `AppShell.tsx:209`") era geométrica, não
 * causal: o chevron é o ÚLTIMO da fila, então é sempre ele que sobra para fora. Medido, o que
 * decide se a linha cabe é o COMPRIMENTO DO RÓTULO da ação primária — largura mínima da linha de
 * 216px sem ação, 326px com "Nova conta", **375px** com "Nova conta de investimento". Tirar o
 * chevron compraria 24px e mascararia a classe até o próximo rótulo longo.
 *
 * O dano que os 15px de estouro escondiam era pior: todos os filhos tinham `flex-shrink: 1` sem
 * `min-width`, então o botão "Abrir menu" — o ÚNICO acesso à navegação no celular — era espremido
 * de 36px para **16px** de largura.
 */
test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/investments": [], "/bank/accounts": [] });
});

test("a rota de rótulo mais longo não faz a página rolar de lado", async ({ page }) => {
  await page.goto("/financeiro/investimentos");
  await expect(page.getByRole("button", { name: /Nova conta de investimento/ })).toBeVisible();

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});

test("o botão de abrir o menu continua tocável quando há ação primária", async ({ page }) => {
  await page.goto("/financeiro/investimentos");
  const caixa = await page.getByRole("button", { name: "Abrir menu" }).boundingBox();
  expect(caixa).not.toBeNull();
  expect(caixa!.width).toBeGreaterThanOrEqual(44);
  expect(caixa!.height).toBeGreaterThanOrEqual(44);
});

test("nenhum botão da barra fica abaixo do mínimo tocável", async ({ page }) => {
  for (const rota of ["/financeiro/investimentos", "/financeiro/contas"]) {
    await page.goto(rota);
    // Escopo pelo `header`, não por classe: `alvosPequenos` corta a lista de classes em 5 para o
    // relatório caber na tela, então filtrar por `.includes("rounded-pill")` acertaria por acaso
    // hoje e erraria em silêncio no dia em que alguém reordenasse as classes.
    const botoes = page.locator("header button");
    const total = await botoes.count();
    expect(total, `rota ${rota}`).toBeGreaterThan(0);
    for (let i = 0; i < total; i++) {
      const caixa = await botoes.nth(i).boundingBox();
      const texto = (await botoes.nth(i).innerText()).trim().slice(0, 30);
      expect(caixa!.height, `${rota} → botão «${texto || "(ícone)"}»`).toBeGreaterThanOrEqual(44);
    }
  }
});
