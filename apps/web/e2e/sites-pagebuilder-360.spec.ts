import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { camposBaixos, medirPagina } from "./support/medidas";
import { semearSessao } from "./support/sessao";
import { PAGINA } from "./support/rotas";

/**
 * `/sites/s1` — a fatia da issue #249 do CONSTRUTOR DE PÁGINAS. Dois arquivos, não um:
 * `PageBuilderPage.tsx` (editor + barra de ações) e `PageBlocks.tsx` (compartilhado, renderiza o
 * `LeadForm` de verdade — inputs reais, não preview estático — tanto na prévia dentro do editor
 * quanto na página pública `/p/:slug`, `PublicPage.tsx`, FORA do escopo desta issue).
 *
 * ⚠️ **`PublicPage.tsx`/`/p/:slug` herda esta correção automaticamente**, por usar o MESMO
 * `PageBlocks.tsx`. Não é escopo desta issue, mas é efeito colateral esperado e correto — o
 * `LeadForm` é literalmente o mesmo componente nos dois lugares, e não há como corrigir um sem
 * corrigir o outro.
 *
 * `main` é o escopo (`AppShell.tsx:65`, `overflow-x-hidden p-6`): página inteira, sem
 * `components/Modal.tsx`. O mock `PAGINA` do catálogo (`e2e/support/rotas.ts:43-55`) já inclui um
 * bloco `form` com `extraFields: []` — é o que faz o `LeadForm` de fato renderizar na prévia.
 *
 * ⚠️ **Os números medidos aqui DIVERGEM dos pré-calculados na issue #227 (15).** Medido ao vivo:
 * TOTAL de campos de digitação = 13 (10 no editor: título da barra de ações, fonte, URL do logo,
 * título/texto do bloco heading/text, label/URL do botão, texto do botão/ajuda do
 * WhatsApp/aviso do formulário; + 3 na prévia: nome/WhatsApp/e-mail do `LeadForm`) — 2 a menos que
 * os 15 da issue, mesma classe de causa das outras fatias (algum campo saiu do fluxo desde a
 * medição original). Campos ABAIXO de 44px, antes do fix: **10**, não 13 nem 15 — os `<textarea
 * rows={2}>`/`rows={3}` de heading/text/aviso do formulário já nascem com altura suficiente por
 * terem várias linhas; só sobra abaixo do alvo o que é de fato uma linha (inputs, selects, e o
 * `LeadForm` inteiro, que não tem textarea nenhum).
 */
async function contarCampos(page: import("@playwright/test").Page, raiz: string): Promise<number> {
  const naoDigitaveis =
    '[type="hidden"],[type="checkbox"],[type="radio"],[type="file"],[type="color"],[type="range"]';
  return page.locator(`${raiz} input:not(${naoDigitaveis}), ${raiz} select, ${raiz} textarea`).count();
}

test("os campos do CONSTRUTOR DE PÁGINAS (/sites/s1), editor E prévia com LeadForm, são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/pages": PAGINA });
  await page.goto("/sites/s1");
  // A `marca`: o rótulo da prévia só existe depois do `GET /pages/s1` ter resolvido — sem ele,
  // "zero campos baixos" poderia significar "a tela ficou em 'Carregando...'".
  await expect(page.getByText("Pré-visualização").first()).toBeVisible();
  // O LeadForm só renderiza depois que o bloco `form` do mock monta — confirmamos que ele está
  // de fato na prévia (não só no editor) antes de medir.
  await expect(page.getByText("Seu WhatsApp").first()).toBeVisible();

  expect(await contarCampos(page, "main"), "sites s1: total de campos de digitação").toBeGreaterThanOrEqual(13);
  expect(await camposBaixos(page, "main"), "sites s1 — campos abaixo de 44px (editor + prévia/LeadForm)").toEqual([]);

  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});
