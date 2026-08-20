import type { Page } from "@playwright/test";

/**
 * Rotas que TODA tela pode chamar e que nenhuma medição está medindo. O default `[]` de rota não
 * mapeada não serve para elas: `[]` é **verdadeiro** em JS, e `GanchoDaVima` faz
 * `setPergunta(data ?? null)` — com `[]` a guarda `if (!pergunta) return null` não pega, e a tela
 * ganha um CARD VAZIO que a produção nunca produz (lá o endpoint devolve um objeto ou `null`).
 *
 * ⚠️ **Este card é a causa medida do flake do #149**, e a geometria fecha com o trace do CI
 * (run 32258769910). Ele empurra o conteúdo **101px** para baixo (`main` 681px → 782px). Na
 * `/agenda` isso põe a célula do dia 18 EM CIMA da dobra de 740px: medido em 19/08/2026, o chip
 * fica com **7,8px de folga** até o fundo (`bottom` 732,3) e a célula termina 14px FORA da tela
 * (`bottom` 754). Sem o card a mesma folga é **116,8px** e nada precisa rolar.
 *
 * O resto é consequência: o Playwright precisa do `scrollIntoViewIfNeeded` (o trace registra
 * `scroll_top = 8`), calcula o ponto do clique no centro do chip — **y = 729,87** no trace, contra
 * 722 + 8 medidos aqui — e dispara a 10px do fundo. Qualquer movimento residual de poucos pixels
 * entre o ponto e o `mouseup` tira o chip de baixo do ponteiro, e o navegador emite o `click` no
 * ANCESTRAL COMUM dos dois alvos: o `<button>` da célula do dia, que abre o modal ERRADO. Medido:
 * **10px de deslocamento já bastam** — exatamente a margem que sobra. O hit-target do Playwright
 * não acusa nada, porque o `mousedown` acertou o alvo certo.
 *
 * ⚠️ Por isso `data-testid` no chip **não conserta sozinho**: o alvo nunca foi ambíguo
 * (`getByText(...).count() === 1`, medido). Ambíguo era o PONTO. Seis telas montam o gancho
 * (`agenda`, `cobrancas`, `crm`, `orcamentos`, `pagar`, `vima`), então o default vale para todas
 * em vez de cada spec ter de lembrar.
 *
 * Sobrescrevível: quem quiser MEDIR o card passa `/dna/pendente` na própria fixture.
 */
const PADROES: Record<string, unknown> = {
  "/dna/pendente": null,
};

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
  const mapa = { ...PADROES, ...respostas };
  await page.route("**/api/**", async (route) => {
    const caminho = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    const chave = Object.keys(mapa)
      .filter((k) => caminho.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    await route.fulfill({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify(chave === undefined ? [] : mapa[chave]),
    });
  });
}
