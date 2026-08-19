import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { semearSessao } from "./support/sessao";

/**
 * O contrato de QUERY STRING da busca — o único lugar onde o axios de verdade roda.
 *
 * ⚠️ **Por que este arquivo existe.** As outras três camadas são cegas à URL: o pytest monta a
 * query crua já na forma certa, o vitest assere o objeto `params` ANTES de serializar, e o mock
 * do gate de layout devolve payload fixo seja qual for a query. Foi exatamente essa fresta que
 * escondeu o `status[]` até o #125 — o filtro ia com colchetes, o FastAPI ignorava em silêncio e
 * a tela mostrava dado sem filtro nenhum, sem erro e sem sintoma.
 */

async function urlsDaBusca(page: Parameters<typeof semearSessao>[0]) {
  const urls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/search")) urls.push(r.url());
  });
  return urls;
}

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/search": { groups: [] } });
});

test("a busca funda manda q, depth e months na forma que o FastAPI lê", async ({ page }) => {
  const urls = await urlsDaBusca(page);

  await page.goto("/busca?q=rescisao");
  await expect.poll(() => urls.length).toBeGreaterThan(0);

  const query = decodeURIComponent(new URL(urls[0]).search);
  expect(query, `query real: ${query}`).toContain("q=rescisao");
  expect(query, `query real: ${query}`).toContain("depth=deep");
  expect(query, `query real: ${query}`).toContain("months=12");
  expect(query, "colchete = o FastAPI ignora o parâmetro em silêncio").not.toContain("[]");
});

test("o termo do usuário chega ao servidor como TEXTO, não interpretado", async ({ page }) => {
  const urls = await urlsDaBusca(page);

  // `%` é curinga do `ilike`. Se ele chegasse cru e sem escape no backend, a busca casaria com
  // tudo — o defeito que o #125 documentou e que esta entrega fecha no CRM.
  await page.goto("/busca?q=100%25");
  await expect.poll(() => urls.length).toBeGreaterThan(0);

  expect(new URL(urls[0]).searchParams.get("q")).toBe("100%");
});

test("trocar o recorte para 'tudo' manda months=0, e não omite o parâmetro", async ({ page }) => {
  const urls = await urlsDaBusca(page);
  await page.goto("/busca?q=rescisao");
  await expect.poll(() => urls.length).toBeGreaterThan(0);

  await page.getByLabel(/mensagens dos últimos/i).selectOption("0");

  // Omitir o parâmetro faria o backend aplicar o padrão de 12 meses — o oposto do pedido.
  await expect
    .poll(() => urls.some((u) => new URL(u).searchParams.get("months") === "0"))
    .toBe(true);
});

test("com menos de dois caracteres o servidor não é consultado", async ({ page }) => {
  const urls = await urlsDaBusca(page);

  await page.goto("/busca?q=a");
  await page.waitForTimeout(600); // acima do debounce de 250ms

  expect(urls, "uma letra casaria com quase tudo — sete varreduras por tecla").toHaveLength(0);
});
