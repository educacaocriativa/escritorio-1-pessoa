import type { Page } from "@playwright/test";

/**
 * Intercepta `/api/**` e responde do mapa recebido. A chave é um PREFIXO do caminho (já sem o
 * `/api`) e vence a **MAIS LONGA** que casar. Rota não mapeada devolve `[]`: a tela não quebra por
 * causa de um endpoint que o teste não estava medindo.
 *
 * ⚠️ **Por que a mais longa, e não a primeira.** Com "a primeira que casar", `"/bank/accounts"`
 * engole `/bank/accounts/{id}/checkpoints` e a tela recebe uma LISTA DE CONTAS onde espera uma
 * lista de checkpoints — `cps.data[0]` vira uma conta, `checkpoint.reference_date` vira
 * `undefined`, e `formatDateBR` derruba a página inteira com "Cannot read properties of
 * undefined". O sintoma é uma tela em branco que parece bug do produto e é do mock. Depender da
 * ordem das chaves punia quem escrevesse a fixture na ordem natural; o comprimento não depende de
 * ninguém lembrar de nada.
 *
 * ⚠️ Os payloads são de **pior caso plausível** (nomes longos de banco, valores de 6 dígitos,
 * título de grupo comprido) e nas formas dos schemas reais de `packages/shared-types`. Dado curto
 * sempre cabe: medir com ele é medir uma tela que não existe.
 */
export async function mockarApi(page: Page, respostas: Record<string, unknown>): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const caminho = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    const chave = Object.keys(respostas)
      .filter((k) => caminho.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    await route.fulfill({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify(chave === undefined ? [] : respostas[chave]),
    });
  });
}
