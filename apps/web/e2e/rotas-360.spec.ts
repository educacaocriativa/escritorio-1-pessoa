import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina } from "./support/medidas";
import { CASOS, DRE_MATRIX } from "./support/rotas";
import { semearSessao } from "./support/sessao";

/**
 * Cobertura de ROTA da régua de 360px (#135).
 *
 * O defeito que originou esta issue — um rótulo `sr-only` (`position: absolute` SEM offsets, logo
 * ancorado na posição estática) dentro de um `overflow-x-auto` sem ancestral posicionado, fazendo
 * a PÁGINA inteira rolar até 879px — não foi achado por uma régua que o procurasse. Ele apareceu
 * por acaso, enquanto se media um modal vizinho (#130/PR #134). O que faltou não foi técnica: a
 * `medirPagina` existe desde o começo. Faltou **rota medida**.
 *
 * Este arquivo fecha essa lacuna. Cada rota protegida que NENHUM outro spec media ganha aqui a
 * asserção mais barata e mais difícil de enganar que a régua tem: `document.documentElement
 * .scrollWidth === 360`. Um elemento invisível que empurre o documento é indistinguível de um
 * visível para esta conta — e era justamente o disfarce que tornava a classe perigosa.
 *
 * ⚠️ **A `marca` não é conveniência, é o que impede este arquivo de virar enfeite.** Medir uma
 * rota que renderizou em branco (mock que não casou, erro de boot, redirect silencioso) devolve
 * 360 e PASSA — verde por não ter desenhado nada. Foi assim que `toContain("flex-wrap")` passou
 * duas sessões com a tela quebrada. Então toda rota aqui declara um texto que TEM de estar
 * visível antes da medição: sem ele o teste falha por não ter tela, e não por ter tela larga.
 *
 * ⚠️ Rota cuja tela é dirigida por dado (tabela, construtor) recebe payload de **pior caso
 * plausível**, na forma do schema real — nome sem espaço, 12 meses de colunas, texto longo. Dado
 * curto sempre cabe: medir com ele é medir uma tela que não existe. As rotas de lista que aqui
 * ficam em estado vazio estão marcadas com `// vazio:` e provam só o SHELL — o que já basta para
 * o que elas têm de próprio, mas não substitui um spec dedicado quando ganharem conteúdo largo.
 */

for (const { rota, marca, mocks } of CASOS) {
  test(`${rota} não faz o documento rolar de lado em 360px`, async ({ page }) => {
    await semearSessao(page);
    await mockarApi(page, mocks ?? {});
    await page.goto(rota);

    // A tela TEM de existir antes de ser medida — ver o ⚠️ do cabeçalho.
    await expect(page.getByText(marca).first()).toBeVisible();

    const { larguraDaPagina } = await medirPagina(page);
    expect(larguraDaPagina, `a rota ${rota} estourou a viewport de 360px`).toBe(360);
  });
}

/**
 * CONTROLE POSITIVO — o que impede as 33 asserções acima de serem enfeite.
 *
 * Medido nesta issue (#135), e é o achado que reescreve a premissa: `main` é
 * `overflow-x-hidden` (`AppShell.tsx:64`). Uma tabela larga demais NÃO faz o documento rolar —
 * ela é recortada, e `larguraDaPagina` devolve 360 com a coluna da direita inalcançável. Provado
 * por mutação: tirar `overflow-x-auto` da `DrePage` (o deslizador da DRE de 12 meses) deixa as 33
 * rotas VERDES. Logo, esta régua não mede "conteúdo largo" — ela mede exatamente uma coisa, e é a
 * classe do #135: um elemento que ESCAPA do recorte e passa a contar no `scrollWidth` do
 * documento. É o que um `position: absolute` SEM offsets faz quando não há ancestral posicionado:
 * o bloco contêiner dele vira a página, e a sua posição estática — lá no fundo de um deslizador de
 * 12 colunas — vira largura de documento.
 *
 * Este teste planta essa classe de propósito, na `DrePage` (cujo `overflow-x-auto` da linha 131
 * não tem `relative`), e exige que a conta a enxergue. Se algum dia ele passar a devolver 360, a
 * medição ficou cega e as 33 asserções acima pararam de significar qualquer coisa — mesmo
 * continuando verdes.
 */
test("a régua enxerga a classe do #135 plantada num deslizador sem `relative`", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/financial-intelligence/dre/matrix": DRE_MATRIX });
  await page.goto("/financeiro/dre");
  await expect(page.getByText("DRE por categoria").first()).toBeVisible();

  // Antes da isca: a DRE de 12 meses já é MAIS larga que a tela, e mesmo assim não rola — é o
  // recorte do `main` fazendo o seu trabalho. Esta linha é o que prova que o 360 do "depois"
  // não vem de a tabela ser estreita.
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
  const larguraDoDeslizador = await page.evaluate(
    () => document.querySelector("table")!.getBoundingClientRect().width,
  );
  expect(larguraDoDeslizador).toBeGreaterThan(360);

  // A isca é o próprio defeito do #130, na forma literal do Tailwind `sr-only`: `position:
  // absolute` sem NENHUM offset, logo ancorado na posição estática — no fim da última coluna.
  await page.evaluate(() => {
    const ultima = document.querySelector("table thead tr")!.lastElementChild!;
    const isca = document.createElement("span");
    isca.setAttribute("data-isca", "sr-only-135");
    isca.textContent = "Total: ";
    isca.style.cssText =
      "position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;" +
      "clip:rect(0,0,0,0);white-space:nowrap;border-width:0";
    ultima.appendChild(isca);
  });

  // Um elemento de 1px que ninguém vê, empurrando o documento inteiro. É o disfarce da classe.
  const { larguraDaPagina } = await medirPagina(page);
  expect(
    larguraDaPagina,
    "a régua ficou CEGA para a classe do #135: um `absolute` sem ancestral posicionado escapou do recorte e a conta não viu",
  ).toBeGreaterThan(360);
});
