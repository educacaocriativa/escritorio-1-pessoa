import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { agendaEvent as evento } from "./support/fixtures";
import { semearSessao } from "./support/sessao";

/**
 * O detalhe de compromisso da Agenda em 360×740 — o gêmeo exato do defeito do #119.
 *
 * `AgendaPage` monta este modal com `<Modal title={event.title}>`: o título é **digitado pelo
 * dono** e `title` aceita **255 chars** (`agenda/schemas.py`). Sem espaço, hífen ou barra não há
 * onde quebrar — o `<h2>` cresce, espreme o "Fechar" e o empurra para fora da tela. Foi assim, no
 * seletor de horário, que o botão foi parar em **x=698** numa viewport de 360.
 *
 * ⚠️ A varredura é recortada pela CAIXA (`data-testid="modal-evento"`, aplicado pela prop `testId`
 * do `Modal`), nunca pelo conteúdo. Recorte no `children` deixa cabeçalho e rodapé fora da conta
 * por construção, e foi ele que devolveu **lista vazia** com o botão 338px fora da tela. Os dois
 * disfarces continuam de pé e por isso não bastam sozinhos: o `scrollWidth` da PÁGINA segue 360
 * (a caixa tem `overflow-y-auto`) e um `<h2>` sem `min-w-0 break-words` cresce em vez de quebrar.
 */

// Pior caso PLAUSÍVEL (§5.1), não `lorem ipsum`: um lorem tem espaço sobrando e mediria uma tela
// que não existe. O que o dono digita de verdade num título comprido é isto — sem espaço, sem
// hífen e sem barra, o único formato em que o navegador não tem candidato a quebra.
const TITULO_SEM_ESPACO =
  "AlinhamentoFinalDoCasamentoDaJulianaComTodosOsFornecedoresBuffetFotografiaEDecoracao2026";

test.beforeEach(async ({ page }) => {
  // Relógio congelado em 18/08/2026 (fuso do tenant): a grade abre no mês CORRENTE, e sem isto o
  // compromisso simplesmente não estaria na tela em setembro.
  await page.clock.setFixedTime(new Date("2026-08-18T12:00:00Z"));
  await semearSessao(page);
  await mockarApi(page, {
    "/agenda/events": [
      evento({
        id: "ev-longo",
        title: TITULO_SEM_ESPACO,
        starts_at: "2026-08-18T13:00:00Z",
        ends_at: "2026-08-18T14:00:00Z",
        location: "Espaço de eventos",
        guests: ["juliana@exemplo.com.br"],
      }),
    ],
  });
  await page.goto("/agenda");
  // O chip do mês tem `truncate` — o que se mede aqui é o MODAL que ele abre.
  await page.getByText(TITULO_SEM_ESPACO.slice(0, 24), { exact: false }).first().click();
  await expect(page.getByTestId("modal-evento")).toBeVisible();
});

test("o título digitado pelo dono não empurra o 'Fechar' para fora da tela", async ({ page }) => {
  const fechar = page.getByTestId("modal-evento").getByRole("button", { name: /fechar/i });
  const caixa = await fechar.boundingBox();
  expect(caixa).not.toBeNull();
  expect(caixa!.x).toBeGreaterThanOrEqual(0);
  expect(caixa!.x + caixa!.width).toBeLessThanOrEqual(360);
});

test("o título QUEBRA dentro da caixa em vez de esticá-la", async ({ page }) => {
  const titulo = page.getByRole("heading", { name: TITULO_SEM_ESPACO });
  await expect(titulo).toBeVisible();
  const caixa = await page.getByTestId("modal-evento").boundingBox();
  const doTitulo = await titulo.boundingBox();

  // As DUAS metades, e nesta ordem — porque a segunda sozinha é falsa confiança medida.
  //
  // 1) O `<h2>` não pode passar da borda direita da CAIXA. É esta que acusa o defeito do #119:
  //    sem `min-w-0`, o `<h2>` é item de flex com `min-width: auto`, e o mínimo de um item de
  //    flex é o seu conteúdo mínimo — a palavra inteira. Ele não transborda: ele CRESCE, e leva
  //    a linha do cabeçalho junto.
  expect(doTitulo!.x + doTitulo!.width).toBeLessThanOrEqual(caixa!.x + caixa!.width + 0.5);

  // 2) E não pode vazar TINTA mantendo a caixa no lugar (`overflow-wrap: normal` + palavra sem
  //    espaço) — o que `getBoundingClientRect` não vê e `scrollWidth` vê.
  //
  // ⚠️ Medido com `min-w-0 break-words` removido do `Modal.tsx`: a metade (2) continua VERDE
  //    (`scrollWidth === clientWidth`) enquanto a metade (1) devolve 946px de borda direita numa
  //    tela de 360. Uma asserção de `scrollWidth` sozinha aqui seria o teste que passa com a tela
  //    quebrada — a forma exata que o CLAUDE.md §5.1 proíbe.
  const [scrollWidth, clientWidth] = await titulo.evaluate((el) => [el.scrollWidth, el.clientWidth]);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 0.5);
});

test("nada da CAIXA do detalhe existe só depois de rolar de lado", async ({ page }) => {
  expect(await textoForaDaTela(page, '[data-testid="modal-evento"]')).toEqual([]);

  // E a página não passa a rolar de lado só porque o detalhe abriu.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});

test("a régua enxerga um vazamento plantado no CABEÇALHO da caixa", async ({ page }) => {
  // Controle positivo, e ele é o ponto do #123: uma varredura que devolve `[]` não distingue
  // "nada vaza" de "nada foi medido". Aqui o vazamento é plantado DENTRO do cabeçalho — a região
  // que o recorte antigo (no `children`) deixava de fora — e a régua tem de acusá-lo.
  await page.getByTestId("modal-evento").evaluate((caixa) => {
    const isca = document.createElement("p");
    isca.textContent = "x".repeat(120);
    isca.setAttribute("data-isca", "1");
    caixa.querySelector("h2")?.after(isca);
  });
  const cortes = await textoForaDaTela(page, '[data-testid="modal-evento"]');
  expect(cortes.length).toBeGreaterThan(0);
  expect(cortes[0].forcaFora).toBeGreaterThan(0.5);
});
