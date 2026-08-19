import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * A busca a 360px — MEDIDA, não aferida por classe.
 *
 * `toContain("flex-wrap")` já passou verde neste projeto durante duas sessões com a
 * `FilaPagamentosPage` quebrada em produção: o `overflow-x` estava certo, o `flex-wrap` estava
 * certo, e a tela estava errada. Aqui tudo que decide é número vindo do navegador.
 *
 * Os payloads são de PIOR CASO plausível: título longo, vinte itens, trecho comprido. Dado curto
 * sempre cabe — medir com ele é medir uma tela que não existe.
 */

const RESULTADOS = {
  groups: [
    {
      type: "legal_document",
      has_more: true,
      total: 42,
      items: Array.from({ length: 20 }, (_, i) => ({
        id: `d${i}`,
        title: "Peticao inicial de rescisao contratual antecipada com pedido de tutela liminar",
        subtitle: "peticao",
        route: `/juridico/d${i}`,
        snippet:
          "...ficou combinada a rescisao antecipada do contrato conforme a clausula decima " +
          "segunda, com aviso previo de trinta dias corridos contados da notificacao...",
      })),
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
});

// A barra é medida a partir de `/financeiro/investimentos`, e não da raiz: `/` passa pelo
// `EntradaDoDia`, que decide a porta do dia e não renderiza a shell com payload genérico. É a
// mesma rota que o `shell-360.spec.ts` usa para medir esta barra, pelo mesmo motivo.
const TELA_COM_SHELL = "/financeiro/investimentos";
const MOCKS_DA_SHELL = { "/search": { groups: [] }, "/investments": [], "/bank/accounts": [] };

test("a 360px o campo da barra some e a lupa leva para /busca", async ({ page }) => {
  await mockarApi(page, MOCKS_DA_SHELL);

  await page.goto(TELA_COM_SHELL);
  // O campo continua escondido abaixo de `md` — é a medição do #58, não um esquecimento.
  await expect(page.getByPlaceholder("Buscar cliente, contrato ou documento")).toBeHidden();

  await page.getByRole("button", { name: "Buscar" }).click();

  await expect(page).toHaveURL(/\/busca/);
});

test("o alvo da lupa é tocável (44px) e não disputa com o botão de menu", async ({ page }) => {
  await mockarApi(page, MOCKS_DA_SHELL);
  await page.goto(TELA_COM_SHELL);

  const lupa = await page.getByRole("button", { name: "Buscar" }).boundingBox();
  const menu = await page.getByRole("button", { name: "Abrir menu" }).boundingBox();

  expect(lupa).not.toBeNull();
  expect(menu).not.toBeNull();
  expect(lupa!.width, "alvo menor que o polegar acerta").toBeGreaterThanOrEqual(44);
  expect(lupa!.height).toBeGreaterThanOrEqual(44);
  // Sobreposição faria um dos dois receber o toque destinado ao outro.
  expect(lupa!.x >= menu!.x + menu!.width || menu!.x >= lupa!.x + lupa!.width).toBe(true);
});

test("a página de resultados não rola de lado a 360px", async ({ page }) => {
  await mockarApi(page, { "/search": RESULTADOS });

  await page.goto("/busca?q=rescisao");
  await expect(page.getByText("Jurídico (42)")).toBeVisible();

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina, "a página estourou a viewport de 360px").toBe(360);
});

test("o seletor de recorte cabe e continua legível a 360px", async ({ page }) => {
  await mockarApi(page, { "/search": RESULTADOS });
  await page.goto("/busca?q=rescisao");

  const caixa = await page.getByLabel(/mensagens dos últimos/i).boundingBox();

  expect(caixa).not.toBeNull();
  expect(caixa!.width).toBeGreaterThan(0);
  expect(caixa!.x + caixa!.width, "o seletor saiu da viewport").toBeLessThanOrEqual(360);
});
