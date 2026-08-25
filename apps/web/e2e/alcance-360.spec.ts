import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { controlesInalcancaveis, medirPagina } from "./support/medidas";
import { CASOS, DRE_MATRIX } from "./support/rotas";
import { semearSessao } from "./support/sessao";

/**
 * ALCANÇABILIDADE DE CONTROLE em 360px (#144) — a outra metade da régua de rota.
 *
 * `rotas-360.spec.ts` pergunta uma coisa só: a página rola de lado? É a classe do #135, e ela é
 * cega para a classe oposta **por construção**. `main` é `overflow-x-hidden` (`AppShell.tsx:64`):
 * um botão que não cabe não empurra o documento, é RECORTADO — e `document.documentElement
 * .scrollWidth` continua devolvendo 360, verdinho, com o botão inalcançável.
 *
 * Foi exatamente assim que o #144 se escondeu: a varredura de 18 rotas do PR #141 visitou
 * `/funis/f1`, a `marca` provou que a tela renderizou, a largura deu 360 — e o «Salvar» começava
 * em x=514 numa tela de 360px. **Inteiramente** fora. Num celular não havia como salvar um funil.
 *
 * Este arquivo faz a pergunta que falta: todo `button`/`a[href]`/campo VISÍVEL termina dentro da
 * borda que o dedo alcança? A régua está em `support/medidas.ts` (`controlesInalcancaveis`), e o
 * critério não é "termina depois de 360" — é ALCANÇABILIDADE:
 *
 *   - fora da borda visível (a menor entre a viewport e a de todo ancestral que recorta), E
 *   - sem nenhum ancestral que ROLE na horizontal para trazê-lo de volta.
 *
 * A diferença entre os dois critérios não é acadêmica. Medida nestas rotas: "termina depois de
 * 360" acusa **13 controles que estão certos** — os 12 botões de valor da DRE de 12 meses (dentro
 * de um `overflow-x-auto` que rola, que é o deslizador existir e funcionar) e o «Gerar com IA» do
 * carrossel (dentro do painel de edição com `overflow: auto`, a 20px da borda). Uma régua com 13
 * falsos positivos é descartada na primeira semana — e leva junto os defeitos de verdade.
 *
 * ⚠️ **As duas exigências abaixo são o que impede este arquivo de virar enfeite**, e nenhuma delas
 * é cortesia:
 *
 *   1. A `marca` de cada rota (em `support/rotas.ts`): tela que renderizou em branco não tem
 *      controle nenhum, e "zero controles inalcançáveis" é o resultado que ela devolve. Verde por
 *      não ter desenhado nada é como `toContain("flex-wrap")` passou duas sessões com a tela
 *      quebrada em produção.
 *   2. Os DOIS controles no fim deste arquivo. Um planta um botão inalcançável de propósito e
 *      exige que a régua o veja; o outro planta um botão igualmente fora da tela DENTRO de um
 *      deslizador que rola e exige que ela NÃO o acuse. Sem o primeiro ninguém sabe se ela
 *      enxerga; sem o segundo ninguém sabe se ela sabe parar.
 *
 * Cobertura: as 33 rotas de `support/rotas.ts` (as mesmas que `rotas-360.spec.ts` mede), de 47
 * não-públicas. As 14 que ficaram de fora estão listadas no CLAUDE.md §5.4, uma a uma, com o
 * motivo — e agora são **todas do `ProtectedLayout`**: a caixa sem shell fechou. `/vima` entrou
 * pelo #178 (é a PORTA DO DIA — `EntradaDoDia` manda a raiz autenticada para lá enquanto o
 * briefing de hoje não foi lido — e era a única das seis telas que montam `GanchoDaVima` sem
 * régua nenhuma); as outras três do `ProtectedBareLayout` entraram pelo #208, e a primeira
 * medição de `/dna/nucleo` deu **636px** numa viewport de 360 — a mesma classe dos 649px que a
 * `/vima` tinha escondido, pela mesma razão (sem shell não há `main.overflow-x-hidden`). Antes
 * de mexer nesse número, leia o "COMO RECONTAR" da §5.4: contar só uma das duas caixas de
 * layout já errou o denominador duas vezes.
 */

for (const { rota, marca, mocks } of CASOS) {
  test(`${rota} não deixa controle fora do alcance do dedo em 360px`, async ({ page }) => {
    await semearSessao(page);
    await mockarApi(page, mocks ?? {});
    await page.goto(rota);

    // A tela TEM de existir antes de ser medida — ver o ⚠️ 1 do cabeçalho.
    await expect(page.getByText(marca).first()).toBeVisible();

    const fora = await controlesInalcancaveis(page);
    expect(
      fora,
      `a rota ${rota} tem controle que o dedo não alcança em 360px:\n` +
        fora
          .map(
            (c) =>
              `  ${c.inteiramenteFora ? "INTEIRAMENTE FORA" : "parcialmente fora"} ` +
              `x ${c.esquerda} → ${c.direita} (${c.foraPor}px além da borda) — ${c.descricao}`,
          )
          .join("\n"),
    ).toEqual([]);
  });
}

/**
 * CONTROLE POSITIVO — a régua VÊ um controle recortado sem escape.
 *
 * Planta o #144 na sua forma nua: uma fila que não quebra, dentro do `main` recortado, com um
 * botão empurrado para além dos 360px. É o que os cinco botões do cabeçalho do construtor de
 * funis faziam — e o que nenhuma régua de largura de documento pode ver, porque o recorte do
 * `main` mantém `scrollWidth` em 360. Este teste exige as duas coisas ao mesmo tempo: a página
 * NÃO rola (360) e a régua ACUSA o botão. Se um dia ele passar a devolver lista vazia, as
 * asserções de rota acima pararam de significar qualquer coisa — mesmo continuando verdes.
 */
test("a régua enxerga um controle plantado fora do recorte do `main`", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {});
  await page.goto("/financeiro/plano-contas");
  await expect(page.getByText("Plano de contas").first()).toBeVisible();

  expect(await controlesInalcancaveis(page)).toEqual([]);

  await page.evaluate(() => {
    const fila = document.createElement("div");
    fila.style.cssText = "display:flex;gap:8px;white-space:nowrap";
    const empurra = document.createElement("span");
    empurra.style.cssText = "flex:0 0 520px";
    empurra.textContent = ".";
    const botao = document.createElement("button");
    botao.setAttribute("data-isca", "inalcancavel-144");
    botao.style.cssText = "flex:0 0 90px;height:44px";
    botao.textContent = "Salvar";
    fila.append(empurra, botao);
    document.querySelector("main")!.appendChild(fila);
  });

  // O disfarce da classe: a página continua medindo 360 com o botão inteiramente fora.
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);

  const fora = await controlesInalcancaveis(page);
  const isca = fora.find((c) => c.descricao.includes("Salvar"));
  expect(
    isca,
    "a régua ficou CEGA para a classe do #144: um controle recortado pelo `main` não foi acusado",
  ).toBeDefined();
  expect(isca!.inteiramenteFora).toBe(true);
  expect(isca!.esquerda).toBeGreaterThan(360);
});

/**
 * CONTROLE NEGATIVO — a régua SABE PARAR num deslizador que de fato rola.
 *
 * O outro lado da mesma moeda, e o mais fácil de esquecer: uma régua que acuse tudo que termina
 * depois de 360 acusaria os 12 botões de valor da DRE, que estão dentro de um `overflow-x-auto`
 * que rola — o deslizador funcionando como projetado. Aqui um botão é plantado no fim da última
 * coluna da DRE de 12 meses: ele começa MUITO além dos 360px (a asserção abaixo prova o número),
 * e mesmo assim a régua não pode acusá-lo, porque o dono desliza a tabela e chega nele.
 */
test("a régua NÃO acusa um controle plantado dentro de um deslizador que rola", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/financial-intelligence/dre/matrix": DRE_MATRIX });
  await page.goto("/financeiro/dre");
  await expect(page.getByText("DRE por categoria").first()).toBeVisible();

  await page.evaluate(() => {
    const ultima = document.querySelector("table thead tr")!.lastElementChild!;
    const botao = document.createElement("button");
    botao.setAttribute("data-isca", "dentro-do-deslizador");
    botao.style.cssText = "height:44px;width:90px";
    botao.textContent = "Estornar";
    ultima.appendChild(botao);
  });

  // Sem esta medição o "não acusou" seria vazio: prova que o botão ESTÁ fora da tela, e que o
  // deslizador tem o que rolar. É por isso que ele é alcançável, não por ser estreito.
  const { esquerda, sobraDoDeslizador } = await page.evaluate(() => {
    const b = document.querySelector("[data-isca='dentro-do-deslizador']")!;
    // O deslizador é achado por COMPUTED STYLE, não por nome de classe: `.overflow-x-auto` é o
    // jeito de escrever, não o fato medido, e o fato é o que este teste precisa provar.
    let d = b.parentElement!;
    while (!["auto", "scroll"].includes(getComputedStyle(d).overflowX)) d = d.parentElement!;
    return {
      esquerda: +b.getBoundingClientRect().left.toFixed(1),
      sobraDoDeslizador: d.scrollWidth - d.clientWidth,
    };
  });
  expect(esquerda).toBeGreaterThan(360);
  expect(sobraDoDeslizador).toBeGreaterThan(0);

  const fora = await controlesInalcancaveis(page);
  expect(
    fora.filter((c) => c.descricao.includes("Estornar")),
    "a régua virou enfeite: acusou um controle que o dono alcança deslizando a DRE",
  ).toEqual([]);
});
