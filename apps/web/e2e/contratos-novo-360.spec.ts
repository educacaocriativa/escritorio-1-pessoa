import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { camposBaixos, medirPagina } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * `/contratos/novo` — a fatia da issue #249 que o dono do produto decidiu fechar agora.
 *
 * A issue #249 original listava 4 telas densas sem decisão de produto: `/marketing/m1` (30
 * campos), `/sites/s1` (15), `/marketing/novo` (12), `/contratos/novo` (4). O dono escolheu só
 * esta — é o caso mais próximo do já fechado `/orcamentos/novo` (#227): o `<input>`/`<select>` do
 * TÍTULO e do CLIENTE em `ContractBuilderPage.tsx` usa a MESMA classe do `Field` de
 * `components/Modal.tsx` (`px-3 py-2 text-sm`, 38px medidos), só que fora de modal. As outras 3
 * telas ficam de fora — decisão de produto pendente, não procrastinação.
 *
 * `main` é o escopo (`AppShell.tsx:65`, `overflow-x-hidden p-6`): a tela não usa
 * `components/Modal.tsx`, é conteúdo de página inteira.
 */
async function contarCampos(page: import("@playwright/test").Page, raiz: string): Promise<number> {
  const naoDigitaveis =
    '[type="hidden"],[type="checkbox"],[type="radio"],[type="file"],[type="color"],[type="range"]';
  return page.locator(`${raiz} input:not(${naoDigitaveis}), ${raiz} select, ${raiz} textarea`).count();
}

test("os campos do CONTRATO (/contratos/novo) são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {});
  await page.goto("/contratos/novo");
  // A tela não tem `heading`: a `marca` é o rótulo "Contratos" do link de voltar
  // (`ContractBuilderPage.tsx:154`) — sem ele, "zero campos baixos" poderia significar "não montou".
  await expect(page.getByText("Contratos").first()).toBeVisible();

  // Título + cliente + template ("Usar template..." só existe em modo novo) + 1 cláusula
  // (título + texto) — os campos que a issue #227 mediu em 4, fora de modal.
  expect(await contarCampos(page, "main"), "contrato: campos de digitação").toBeGreaterThanOrEqual(4);
  expect(await camposBaixos(page, "main"), "contrato — campos abaixo de 44px").toEqual([]);

  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});
