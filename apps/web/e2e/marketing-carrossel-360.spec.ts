import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { camposBaixos, medirPagina } from "./support/medidas";
import { semearSessao } from "./support/sessao";
import { CARROSSEL } from "./support/rotas";

/**
 * `/marketing/m1` e `/marketing/novo` — a fatia da issue #249 do CARROSSEL. As duas rotas
 * renderizam o MESMO componente (`CarrosselBuilderPage.tsx`): `/marketing/:id` hidrata via
 * `hydrate()` a partir de `GET /marketing/carousels/:id`; `/marketing/novo` nasce com
 * `slides: []`. Um único fix no arquivo cobre as duas.
 *
 * `main` é o escopo (`AppShell.tsx:65`, `overflow-x-hidden p-6`): página inteira, sem
 * `components/Modal.tsx`.
 *
 * ⚠️ **Os números medidos aqui DIVERGEM dos números pré-calculados na issue.** A pesquisa prévia
 * (baseada no catálogo de `#227`) previa 30 campos ABAIXO de 44px em `/marketing/m1`. Medido ao
 * vivo, ANTES do fix, contra este `main`: **26**, não 30. A diferença de 4 é real e explicada:
 * `topic` e `caption` (`<textarea rows={2}>`/`rows={3}`) e os campos `secondary` dos slides
 * `editorial`/`accent` (também `<textarea rows={2}>`) já nascem com >=44px de altura por terem
 * DUAS OU MAIS LINHAS — só o `<textarea>` de UMA linha equivalente (`rows=1` de fato, ou os
 * `<input>`/`<select>`) fica abaixo do alvo. `30` continua correto como CONTAGEM TOTAL de campos
 * de digitação (a régua `contarCampos` abaixo, que não filtra por altura) — é esse o número que a
 * issue original media, não "abaixo de 44px". Mesmo raciocínio para `/marketing/novo`: total
 * medido = 10 (a issue previa 12 — 2 a menos, mesma causa: sem slides, restam só os 10 campos
 * fixos), campos abaixo de 44px = 8 (`topic`/`caption` já tocáveis).
 */
async function contarCampos(page: import("@playwright/test").Page, raiz: string): Promise<number> {
  const naoDigitaveis =
    '[type="hidden"],[type="checkbox"],[type="radio"],[type="file"],[type="color"],[type="range"]';
  return page.locator(`${raiz} input:not(${naoDigitaveis}), ${raiz} select, ${raiz} textarea`).count();
}

test("os campos do CARROSSEL salvo (/marketing/m1) são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/marketing/carousels/templates": [], "/marketing/carousels": CARROSSEL });
  await page.goto("/marketing/m1");
  // A `marca`: o rótulo da prévia só existe depois de `hydrate()` ter rodado — sem ele, "zero
  // campos baixos" poderia significar "a rota nunca hidratou".
  await expect(page.getByText("Pré-visualização (Instagram 4:5) — baixe em PNG").first()).toBeVisible();

  // 10 campos fixos (tema, perfil, nº de slides, 4 cores, fonte, legenda, hashtags) + 5 por slide
  // (tipo, título, secundário/subtítulo, destaque, foto) × 4 slides do mock — a CONTAGEM TOTAL
  // que a issue #227 media em 30, confirmada ao vivo.
  expect(await contarCampos(page, "main"), "carrossel m1: total de campos de digitação").toBeGreaterThanOrEqual(30);
  expect(await camposBaixos(page, "main"), "carrossel m1 — campos abaixo de 44px").toEqual([]);

  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("os campos do CARROSSEL novo (/marketing/novo) são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/marketing/carousels/templates": [] });
  await page.goto("/marketing/novo");
  // Sem `id`, a tela nasce com `slides: []` — a `marca` é o rótulo do bloco "Gerar com IA", que
  // não depende de nenhum GET além de `/marketing/carousels/templates` (mockado vazio).
  await expect(page.getByText("Tema do carrossel").first()).toBeVisible();

  // Só os 10 campos fixos — nasce sem slide algum. Medido ao vivo: 10 (a issue #227 previa 12).
  expect(await contarCampos(page, "main"), "carrossel novo: total de campos de digitação").toBeGreaterThanOrEqual(10);
  expect(await camposBaixos(page, "main"), "carrossel novo — campos abaixo de 44px").toEqual([]);

  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});
