import type { Page } from "@playwright/test";

/**
 * Intercepta `/api/**` e responde do mapa recebido. A chave é um PREFIXO do caminho (já sem o
 * `/api`); a primeira que casar vence, na ordem de inserção do objeto — então chave mais
 * específica vem primeiro. Rota não mapeada devolve `[]`: a tela não quebra por causa de um
 * endpoint que o teste não estava medindo.
 *
 * ⚠️ Os payloads são de **pior caso plausível** (nomes longos de banco, valores de 6 dígitos,
 * título de grupo comprido) e nas formas dos schemas reais de `packages/shared-types`. Dado curto
 * sempre cabe: medir com ele é medir uma tela que não existe.
 */
export async function mockarApi(page: Page, respostas: Record<string, unknown>): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const caminho = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    const chave = Object.keys(respostas).find((k) => caminho.startsWith(k));
    await route.fulfill({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify(chave === undefined ? [] : respostas[chave]),
    });
  });
}
