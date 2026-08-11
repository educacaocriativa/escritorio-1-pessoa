import { expect, test } from "@playwright/test";
// O atributo `with { type: "json" }` NÃO é opcional: o Playwright carrega os specs como ESM
// nativo do Node, que recusa importar JSON sem ele ("needs an import attribute").
import fixtures from "./fixtures/conversas.json" with { type: "json" };
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O Painel de Conversas em 360px.
 *
 * Antes deste spec, `w-80 shrink-0` (a lista, 320px) e `flex-1` (a conversa) dividiam a tela SEM
 * breakpoint: com uma conversa selecionada, o painel dela nascia em x=360 — inteiro fora da
 * viewport — e `main` tem `overflow-x-hidden`, então não havia barra nem pan por toque. O dono
 * tocava numa conversa e nada acontecia.
 */
test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, fixtures);
});

test("a lista cabe na tela e não força rolagem lateral", async ({ page }) => {
  await page.goto("/conversas");
  await expect(page.getByText("Maria Aparecida Gonçalves de Souza")).toBeVisible();

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});

test("tocar numa conversa mostra a conversa — inteira, dentro da tela", async ({ page }) => {
  await page.goto("/conversas");
  await page.getByText("Maria Aparecida Gonçalves de Souza").click();

  // A mensagem tem de estar VISÍVEL, não apenas presente no DOM: era exatamente isso que
  // `overflow-x-hidden` escondia enquanto o teste de classe CSS ficava verde.
  //
  // `exact: true` não é preciosismo de seletor: a prévia na lista CONTÉM o texto da mensagem
  // (é a mesma frase, truncada mais adiante), então busca por trecho casa com as duas e o teste
  // passaria olhando para a lista — justamente o elemento que já estava certo.
  const mensagem = page.getByText(
    "Bom dia! Consegui olhar a proposta ontem à noite, ficou muito bom mesmo.",
    { exact: true },
  );
  await expect(mensagem).toBeInViewport();

  const caixa = await mensagem.boundingBox();
  expect(caixa).not.toBeNull();
  expect(caixa!.x).toBeGreaterThanOrEqual(0);
  expect(caixa!.x + caixa!.width).toBeLessThanOrEqual(360);

  // E nada mais pode ter ficado para trás da borda.
  expect(await textoForaDaTela(page)).toEqual([]);
});

test("dá para voltar da conversa para a lista", async ({ page }) => {
  await page.goto("/conversas");
  await page.getByText("Maria Aparecida Gonçalves de Souza").click();
  // Texto que só existe DENTRO da conversa (a linha automática), nunca na prévia da lista.
  await expect(page.getByText("Olá Maria! Sua cobrança de R$ 3.000,00")).toBeInViewport();

  await page.getByRole("button", { name: "Voltar para as conversas" }).click();
  await expect(page.getByText("Obra Residencial Alphaville — Fornecedores")).toBeInViewport();
});
