import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { controlesInalcancaveis, medirPagina, textoForaDaTela } from "./support/medidas";
import { FUNIS_LONGOS, JURIDICO_DOCS, JURIDICO_SKILLS, LONGO } from "./support/rotas";
import { semearSessao } from "./support/sessao";

/**
 * O CARD QUE TRANSBORDA A BORDA de 360px (#182) — a terceira pergunta sobre a mesma tela.
 *
 * `rotas-360.spec.ts` pergunta se a página rola de lado (#135) e `alcance-360.spec.ts` se todo
 * CONTROLE é alcançável (#58/#144). Medido nesta issue, em 360×740, com título de pior caso: as
 * duas são cegas para o defeito daqui, e por motivos diferentes.
 *
 *   - **`scrollWidth` não vê.** `main` é `overflow-x-hidden` (`AppShell.tsx:64`), então o card
 *     largo é RECORTADO em vez de empurrar o documento: `document.documentElement.scrollWidth`
 *     devolveu **360** nas CINCO rotas medidas aqui, com o card até 316px fora da tela.
 *   - **`controlesInalcancaveis` também não vê, em 4 das 5.** O card é um `<button w-full>`: a
 *     CAIXA dele mede 312px e cabe. O que vaza é a TINTA — um `<p>` dentro de um item de flex com
 *     `min-width: auto`, que não encolhe, com uma palavra sem espaço que não quebra. A régua de
 *     alcance mede `getBoundingClientRect` de controle, e `getBoundingClientRect` não vê tinta.
 *     Em `/juridico` ela via, e só ali: lá a GRADE não tinha `grid-cols-1`, a trilha `auto` crescia
 *     junto com o conteúdo, e a lixeira `absolute right-3` ia com ela para x=583,5 — inteiramente
 *     fora. As outras quatro grades têm `grid-cols-1` (que o Tailwind escreve `minmax(0, 1fr)`) e
 *     por isso seguravam a caixa enquanto deixavam a tinta sair.
 *
 * A pergunta que falta, e que esta régua faz, é a do §5.1: **a BORDA DIREITA do que foi desenhado
 * (`x + width`, ou `x + scrollWidth` quando o elemento não recorta a si mesmo) passa da borda que
 * o dono alcança?** É `textoForaDaTela` de `support/medidas.ts` — a mesma régua que o
 * `produtos-vender-360` já usa DENTRO do modal de venda, e que nunca tinha sido apontada para a
 * LISTA de nenhuma destas telas. Daí `/produtos` ter atravessado com um nome de 74 chars já na
 * fixture: o nome estava lá, o card estava desenhado, e a medição olhava só para o modal.
 *
 * ⚠️ O escopo é `main` de propósito. `textoForaDaTela` mede contra a borda do ancestral que
 * RECORTA, e um deslizador horizontal legítimo (a DRE de 12 meses, o Kanban) tem conteúdo fora
 * dessa borda por construção. Nenhuma das cinco rotas daqui tem deslizador — medido: com o
 * conserto aplicado, as cinco devolvem lista vazia.
 *
 * ## Por que spec próprio, e não mais entradas no catálogo de `support/rotas.ts`
 *
 * A `marca` do catálogo é o título da PÁGINA ("Funis de Vendas", "Produtos"). Ele aparece com a
 * lista vazia — que é o estado em que estas cinco rotas estavam catalogadas (`// vazio`) e a razão
 * de o defeito ter atravessado #135, #144 e #160 sem ninguém ver. Um card só é medível quando a
 * `marca` é o PRÓPRIO CARD: aqui toda rota declara um texto que só o card produz, e o teste
 * «reprova sem card» abaixo prova, com payload `[]`, que essa marca de fato reprova.
 *
 * As duas rotas de que a issue trata (`/funis` e `/juridico`) saíram do estado vazio no catálogo
 * TAMBÉM, porque é lá que mora a cegueira que a issue descreve — e as fixtures delas são
 * importadas daqui para não existirem em duas cópias. As outras três continuam `// vazio` lá: o
 * catálogo é percorrido pelas outras duas réguas e mudar o que ELAS medem em rotas fora desta
 * issue é decisão de outra issue, não efeito colateral desta.
 */

const PAGINAS_LONGAS = [
  {
    id: "s1",
    title: LONGO,
    model: "captura",
    status: "published",
    public_slug: LONGO,
    created_at: "2026-01-01T10:00:00Z",
  },
];

const PRODUTOS_LONGOS = [
  {
    id: "p1",
    tenant_id: "t1",
    name: LONGO,
    kind: "membership",
    price_cents: 299700,
    description: LONGO,
    active: false,
    stock: 42,
    checkout_url: `https://exemplo.com.br/${LONGO}`,
    students: 128,
    created_at: "2026-01-01T10:00:00Z",
  },
];

const INVESTIMENTOS_LONGOS = [
  {
    id: "i1",
    name: LONGO,
    kind: LONGO,
    index_rate_label: LONGO,
    principal_cents: 123456789,
    accrued_yield_cents: 98765,
    opened_at: "2026-01-01",
    created_at: "2026-01-01T10:00:00Z",
    bank_account_id: null,
    bank_account_name: null,
  },
];

interface CasoDeCard {
  rota: string;
  /** Título da PÁGINA — o que a tela mostra mesmo sem dado. Só serve para provar que ela abriu. */
  marcaDaPagina: string;
  /** Texto que SÓ o CARD produz. É ele que impede esta régua de medir uma lista vazia. */
  marcaDoCard: string;
  mocks: Record<string, unknown>;
  /** O mesmo mapa com as listas apagadas — usado pelo teste «reprova sem card». */
  semDado: Record<string, unknown>;
}

const CARDS: CasoDeCard[] = [
  {
    rota: "/funis",
    marcaDaPagina: "Funis de Vendas",
    marcaDoCard: LONGO,
    mocks: { "/funnels": FUNIS_LONGOS },
    semDado: { "/funnels": [] },
  },
  {
    rota: "/juridico",
    marcaDaPagina: "Assistente Jurídico",
    marcaDoCard: LONGO,
    mocks: { "/juridico/documents": JURIDICO_DOCS, "/juridico/skills": JURIDICO_SKILLS },
    semDado: { "/juridico/documents": [], "/juridico/skills": [] },
  },
  {
    rota: "/sites",
    marcaDaPagina: "Sites & Páginas",
    marcaDoCard: LONGO,
    mocks: { "/pages": PAGINAS_LONGAS },
    semDado: { "/pages": [] },
  },
  {
    rota: "/produtos",
    marcaDaPagina: "Produtos",
    marcaDoCard: LONGO,
    // As três chaves explícitas: `/products` sozinha casaria `/products/coupons` e
    // `/products/enrollments` (o mock resolve pelo prefixo mais longo — ver `support/api.ts`).
    mocks: { "/products": PRODUTOS_LONGOS, "/products/coupons": [], "/products/enrollments": [] },
    semDado: { "/products": [], "/products/coupons": [], "/products/enrollments": [] },
  },
  {
    rota: "/financeiro/investimentos",
    marcaDaPagina: "Investimentos",
    marcaDoCard: LONGO,
    mocks: { "/investments": INVESTIMENTOS_LONGOS, "/bank/accounts": [] },
    semDado: { "/investments": [], "/bank/accounts": [] },
  },
];

for (const { rota, marcaDoCard, mocks } of CARDS) {
  test(`${rota} não deixa o card passar da borda de 360px`, async ({ page }) => {
    await semearSessao(page);
    await mockarApi(page, mocks);
    await page.goto(rota);

    // O CARD tem de existir antes de ser medido — ver o «reprova sem card» abaixo.
    await expect(page.getByText(marcaDoCard).first()).toBeVisible();

    // Documenta o disfarce da classe, e não é enfeite: se um dia isto deixar de ser 360, o defeito
    // passou a ser o do #135 e tem outro dono. As linhas abaixo continuariam vermelhas de qualquer
    // jeito — mas por outro motivo, e quem for ler o vermelho precisa saber qual.
    expect((await medirPagina(page)).larguraDaPagina).toBe(360);

    const cortes = await textoForaDaTela(page, "main");
    expect(
      cortes,
      `a rota ${rota} desenhou card além da borda de 360px:\n` +
        cortes.map((c) => `  +${c.forcaFora}px ${c.descricao} «${c.texto}»`).join("\n"),
    ).toEqual([]);

    // A metade do #144 que ESTA classe também produz quando a grade não segura a trilha: a caixa
    // do card cresce e leva junto o que está `absolute` dentro dela — em `/juridico` a lixeira.
    const fora = await controlesInalcancaveis(page);
    expect(
      fora,
      `a rota ${rota} levou controle junto com o card:\n` +
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
 * REPROVA SEM CARD — o que impede as cinco asserções acima de medirem uma lista vazia.
 *
 * É a falha exata que deixou esta issue passar: as cinco rotas estavam no catálogo como `// vazio`,
 * a régua visitava, não havia card nenhum, e "nada fora da borda" era o resultado. Aqui o payload é
 * `[]` de propósito: a marca do CARD tem de sumir, e a da PÁGINA tem de continuar — sem a segunda
 * metade, uma tela que não abriu (mock podre, erro de boot) daria o mesmo verde.
 */
for (const { rota, marcaDaPagina, marcaDoCard, semDado } of CARDS) {
  test(`${rota}: a marca do card reprova quando a lista vem vazia`, async ({ page }) => {
    await semearSessao(page);
    await mockarApi(page, semDado);
    await page.goto(rota);

    await expect(page.getByText(marcaDaPagina).first()).toBeVisible();
    await expect(page.getByText(marcaDoCard)).toHaveCount(0);
  });
}

/**
 * CONTROLE POSITIVO — a régua VÊ tinta que sai da borda sem a caixa sair junto.
 *
 * Planta o defeito na sua forma nua dentro do `main` recortado: um bloco de largura normal com uma
 * palavra sem espaço e `white-space: nowrap`. A CAIXA continua cabendo (a asserção abaixo prova o
 * número), a página continua medindo 360 — e é exatamente aí que as outras duas réguas ficam
 * verdes. Se um dia este teste devolver lista vazia, as cinco asserções acima pararam de
 * significar qualquer coisa, mesmo continuando verdes.
 */
test("a régua enxerga tinta fora da borda com a caixa dentro dela", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/funnels": [] });
  await page.goto("/funis");
  await expect(page.getByText("Funis de Vendas").first()).toBeVisible();

  expect(await textoForaDaTela(page, "main")).toEqual([]);

  // A isca é marcada por CLASSE, e não por `data-isca`: `textoForaDaTela` descreve o elemento por
  // tag + classe e trunca o TEXTO em 60 chars, então procurar a palavra de 74 no texto devolvido
  // nunca casaria — a régua estaria certa e a asserção, errada.
  await page.evaluate((palavra) => {
    const isca = document.createElement("p");
    isca.className = "isca-182";
    isca.style.cssText = "white-space:nowrap";
    isca.textContent = palavra;
    document.querySelector("main")!.appendChild(isca);
  }, LONGO);

  const { caixa, larguraDaPagina } = await page.evaluate(() => {
    const el = document.querySelector(".isca-182")!;
    return {
      caixa: +el.getBoundingClientRect().right.toFixed(1),
      larguraDaPagina: document.documentElement.scrollWidth,
    };
  });
  // O disfarce: a caixa cabe e a página não rola. As duas réguas antigas ficariam verdes aqui.
  expect(caixa).toBeLessThanOrEqual(360);
  expect(larguraDaPagina).toBe(360);

  const cortes = await textoForaDaTela(page, "main");
  expect(
    cortes.map((c) => c.descricao),
    "a régua ficou CEGA para a classe do #182: tinta além da borda com a caixa dentro dela",
  ).toContain("p.isca-182");
});
