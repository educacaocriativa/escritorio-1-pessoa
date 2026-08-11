import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { alvosPequenos } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O modal de conta bancária em 360×740.
 *
 * Medido antes: conteúdo de **1010px** numa caixa de **629px** (`max-h-[85vh]`), com "Cadastrar
 * conta" a 942px do topo do modal — **y=1043,5**, ou seja 303px ABAIXO da borda inferior da tela,
 * e **467px** abaixo da escolha "Não sei o saldo agora" (Story 8.21) que ele efetiva. É a forma
 * exata do PR #56: o controle e a ação que o torna efetivo em lugares separados, e uma conta real
 * foi baixada sem confirmação visível.
 */
test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/bank/accounts": [],
    "/payables/bills/paid-before": {
      count: 0,
      total_cents: 0,
      oldest_paid_on: null,
      newest_paid_on: null,
    },
  });
  await page.goto("/financeiro/contas");
  await page.getByRole("button", { name: "Nova conta" }).click();
  await expect(page.getByRole("heading", { name: "Nova conta" })).toBeVisible();
});

test("o botão de cadastrar fica na tela enquanto o dono preenche", async ({ page }) => {
  await expect(page.getByRole("button", { name: "Cadastrar conta" })).toBeInViewport();
});

test("o botão continua na tela depois de escolher 'Não sei o saldo agora'", async ({ page }) => {
  await page.getByText("Não sei o saldo agora").click();
  await expect(page.getByRole("button", { name: "Cadastrar conta" })).toBeInViewport();
});

test("o botão continua na tela com o modal rolado até o fim", async ({ page }) => {
  await page.evaluate(() => {
    const caixa = document.querySelector(".fixed.inset-0.z-50 > div");
    if (caixa) caixa.scrollTop = caixa.scrollHeight;
  });
  await expect(page.getByRole("button", { name: "Cadastrar conta" })).toBeInViewport();
});

test("a escolha do saldo é tocável com o polegar", async ({ page }) => {
  for (const rotulo of ["Sei o saldo", "Não sei o saldo agora", "Conta principal"]) {
    const caixa = await page.getByText(rotulo, { exact: true }).boundingBox();
    expect(caixa, rotulo).not.toBeNull();
    expect(caixa!.height, rotulo).toBeGreaterThanOrEqual(44);
  }
});

test("nenhum BOTÃO do modal fica abaixo do mínimo tocável", async ({ page }) => {
  // Escopo no modal: a página por trás é assunto de outros specs.
  //
  // A asserção é sobre BOTÃO, não sobre todo controle, e o recorte é deliberado: os campos de
  // texto do `Field` têm 38px de altura e são compartilhados por todos os modais do app —
  // engordá-los aqui mudaria telas que este PR declara não tocar. O que a dívida mediu como
  // quebrado foi a ESCOLHA (rádios de 13px, coberta pelo teste acima) e o botão que a efetiva.
  // Os 38px ficam registrados como dívida no CLAUDE.md, não escondidos num filtro.
  const pequenos = (await alvosPequenos(page, 44, ".fixed.inset-0.z-50")).filter((a) =>
    a.descricao.startsWith("button"),
  );
  expect(pequenos).toEqual([]);
});
