import { expect, test, type Page } from "@playwright/test";
import crmFixtures from "./fixtures/crm.json" with { type: "json" };
import { mockarApi } from "./support/api";
import { camposBaixos, medirPagina } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O CAMPO DE DIGITAÇÃO em 360×740 — a quarta régua da família, e a primeira que atravessa telas.
 *
 * A pergunta é a do `toque-360.spec.ts` ("o alvo tem tamanho de dedo?") feita sobre o que se
 * DIGITA, e não sobre o que se clica. As três anteriores mediam botão, link e caixinha; o `Field`
 * de `components/Modal.tsx` nunca entrou em nenhuma delas.
 *
 * ⚠️ **Por que uma régua transversal, e não mais um spec por tela.** O `Field` é UM componente
 * usado por **84 `<Field>` em 14 telas**, e cada `<select>` ao lado dele é escrito à mão com a
 * mesma classe (`px-3 py-2 text-sm`). Medido contra `origin/main` em 22/08/2026, com o modal
 * ABERTO, **63 campos em 12 modais** estavam abaixo de 44px:
 *
 *   /agenda            Novo evento                    7   input 280×38 · select 183×39 · datetime 198×40
 *   /crm               Novo cliente                   3   input 280×38 (nome, telefone, tags)
 *   /cobrancas         Nova cobrança                 10   select 280×37 · input 114×38 · date 158×40
 *   /estoque           Novo item                      7   input 136×38 · select 280×39
 *   /financeiro        Registrar venda                6   select 280×39 · input 280×38
 *   /financeiro/contas Nova conta                     7   input 280×38 · select 280×39 · date 280×40
 *   .../centros-custo  Novo centro de custo           2   input 280×38 · select 280×39   ← a issue #215
 *   .../investimentos  Nova conta de investimento     5   input 280×38 · select 280×39
 *   .../plano-contas   Nova categoria                 2   select 280×39 · input 280×38
 *   /pagar             Nova conta                     8   input 119×38 · select 136×39
 *   /produtos          Novo produto                   4   input 280×38 · select 280×39
 *   /sites             Nova página                    2   input 280×38 · select 280×39
 *
 * A issue #215 contava **2** — o `<input>` do `Field` (38px) e o `<select>` de tipo (39px) de
 * `/financeiro/centros-custo` — e dizia por extenso que era PISO. Era: 2 dos 63.
 *
 * ⚠️ **O buraco que deixou isto passar pelo #181, e o que foi feito com ele.** O
 * `toque-360.spec.ts` filtrava `!descricao.startsWith("input")` para não exigir 44px da CAIXINHA
 * do checkbox (20×20 por convenção do repo; quem cumpre os 44 é o `<label>` em volta). O filtro
 * jogava fora, junto, todo campo de TEXTO — e o próprio spec escreveu o custo: "um campo de texto
 * de 38px acrescentado a esta página passaria por aqui". Duas coisas mudaram: `Alvo` passou a
 * carregar `tipo`, e lá o filtro agora recorta só `checkbox`/`radio`. Esta régua não depende
 * daquele filtro: `camposBaixos` tem conjunto próprio (só o que se digita) e mede só ALTURA —
 * um `<input type="number">` de 80px de largura para quantidade é layout, não defeito.
 *
 * ⚠️ **A `marca` não é conveniência.** Um modal que não renderizou campo nenhum devolve lista
 * vazia e PASSA. Por isso cada caso declara quantos campos de digitação tem, e o total medido é
 * conferido antes do veredito — foi assim que `/crm` denunciou que o mock de `/crm/board` estava
 * errado (a tela quebrava em branco e o botão "Novo cliente" nem existia).
 */

/** O overlay do `components/Modal.tsx`. Recorte obrigatório: a página por trás é de outros specs. */
const OVERLAY = ".fixed.inset-0.z-50";

interface CasoDeModal {
  rota: string;
  /** Rótulo do botão que abre — quase sempre a ação primária desenhada pelo shell. */
  abrir: string;
  /** Título do modal. Sem ele, "zero campos baixos" poderia significar "o modal não abriu". */
  marca: string;
  /** Campos de digitação que o modal tem. Piso medido, não teto: acrescentar campo não quebra. */
  campos: number;
  mocks?: Record<string, unknown>;
}

const CENTRO = {
  id: "cc1",
  tenant_id: "t1",
  name: "Sócio João",
  kind: "operacional",
  archived_at: null,
  created_at: "2026-01-01T10:00:00Z",
};

const RELATORIO_CC = { start: "2026-08-01", end: "2026-08-31", buckets: [], notes: [] };

const MODAIS: CasoDeModal[] = [
  { rota: "/agenda", abrir: "Novo evento", marca: "Novo evento", campos: 7 },
  // `/crm/board` devolve OBJETO (`{ columns: [] }`). Com o `[]` default de `mockarApi` a tela
  // quebra antes de montar o cabeçalho e o botão "Novo cliente" não existe — medido.
  {
    rota: "/crm",
    abrir: "Novo cliente",
    marca: "Novo cliente",
    campos: 3,
    mocks: crmFixtures as Record<string, unknown>,
  },
  { rota: "/cobrancas", abrir: "Nova cobrança", marca: "Nova cobrança", campos: 10 },
  { rota: "/estoque", abrir: "Novo item", marca: "Novo item de estoque", campos: 7 },
  { rota: "/financeiro", abrir: "Registrar venda", marca: "Registrar venda", campos: 6 },
  { rota: "/financeiro/contas", abrir: "Nova conta", marca: "Nova conta", campos: 7 },
  {
    rota: "/financeiro/centros-custo",
    abrir: "Novo centro de custo",
    marca: "Novo centro de custo",
    campos: 2,
    mocks: { "/cost-centers": [CENTRO], "/financial-intelligence/by-cost-center": RELATORIO_CC },
  },
  {
    rota: "/financeiro/investimentos",
    abrir: "Nova conta de investimento",
    marca: "Nova conta de investimento",
    campos: 5,
  },
  { rota: "/financeiro/plano-contas", abrir: "Nova categoria", marca: "Nova categoria", campos: 2 },
  { rota: "/pagar", abrir: "Nova conta", marca: "Nova conta a pagar", campos: 8 },
  { rota: "/produtos", abrir: "Novo produto", marca: "Novo produto", campos: 4 },
  { rota: "/sites", abrir: "Nova página", marca: "Nova página", campos: 2 },
];

/** O MESMO conjunto de `camposBaixos`, contado. É a `marca` do conteúdo: sem ela, um modal que
 * não desenhou campo nenhum devolveria lista vazia e passaria por conserto. */
async function contarCampos(page: Page, raiz: string): Promise<number> {
  const naoDigitaveis = '[type="hidden"],[type="checkbox"],[type="radio"],[type="file"],[type="color"],[type="range"]';
  return page
    .locator(`${raiz} input:not(${naoDigitaveis}), ${raiz} select, ${raiz} textarea`)
    .count();
}

for (const caso of MODAIS) {
  test(`os campos de «${caso.marca}» (${caso.rota}) são tocáveis com o polegar`, async ({
    page,
  }) => {
    // Relógio congelado: `/agenda` abre no mês corrente e o modal de evento nasce com a data de
    // hoje. Sem isto o teste mede uma tela diferente a cada dia.
    await page.clock.setFixedTime(new Date("2026-08-18T12:00:00Z"));
    await semearSessao(page);
    await mockarApi(page, caso.mocks ?? {});
    await page.goto(caso.rota);

    await page.getByRole("button", { name: caso.abrir }).first().click();
    await expect(page.getByRole("heading", { name: caso.marca })).toBeVisible();

    expect(
      await contarCampos(page, OVERLAY),
      `${caso.rota}: campos de digitação`,
    ).toBeGreaterThanOrEqual(caso.campos);

    expect(
      await camposBaixos(page, OVERLAY),
      `${caso.rota} — campos abaixo de 44px`,
    ).toEqual([]);

    // 44px de altura em 7 campos empilhados cresce a caixa: o que as outras réguas garantem
    // continua garantido depois do conserto.
    expect((await medirPagina(page)).larguraDaPagina).toBe(360);
  });
}

// ── /admin ────────────────────────────────────────────────────────────────────────
// A tela com MAIS `<Field>` do app (12) e a única atrás de `is_platform_admin`. Ficaria fora de
// qualquer varredura que só percorresse o catálogo de rotas de `support/rotas.ts`.
test("os campos de «Nova conta (escritório + dono)» (/admin) são tocáveis com o polegar", async ({
  page,
}) => {
  await semearSessao(page);
  await page.addInitScript(() => {
    const u = JSON.parse(localStorage.getItem("e1p_user") ?? "{}");
    localStorage.setItem("e1p_user", JSON.stringify({ ...u, is_platform_admin: true }));
  });
  await mockarApi(page, { "/admin/users": [] });
  await page.goto("/admin");
  await page.getByRole("button", { name: "Nova conta" }).first().click();
  await expect(page.getByRole("heading", { name: "Nova conta (escritório + dono)" })).toBeVisible();

  expect(await contarCampos(page, OVERLAY), "/admin: campos de digitação").toBeGreaterThanOrEqual(6);
  expect(await camposBaixos(page, OVERLAY), "/admin — campos abaixo de 44px").toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

// ── Os TRÊS CLONES do `Field` ─────────────────────────────────────────────────────
// Consertar `components/Modal.tsx` NÃO os alcança: cada um tem cópia própria da mesma classe
// (`px-3 py-2 text-sm`, 38px medidos). Sem estes três casos, "a classe está fechada" seria falso
// e ninguém saberia — que é exatamente a forma de defeito que esta issue existe para pagar.
//   auth/LoginPage.tsx:203               5 usos — a PRIMEIRA tela do produto
//   funis/FunnelBuilderPage.tsx:736      6 usos — modal escrito à mão (`.absolute.inset-0.z-30`)
//   juridico/JuridicoWizardPage.tsx:178  1 uso  — formulário de página inteira, não modal

test("os campos do LOGIN são tocáveis com o polegar", async ({ page }) => {
  await mockarApi(page, {});
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();
  expect(await contarCampos(page, "form"), "login: campos").toBeGreaterThanOrEqual(2);
  expect(await camposBaixos(page, "form"), "login — campos abaixo de 44px").toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

const FUNIL_ACAO = {
  id: "f1",
  tenant_id: "t1",
  name: "Funil de teste",
  nodes: [
    {
      id: "n1",
      type: "default",
      position: { x: 0, y: 0 },
      data: { label: "Gerar orçamento", key: "quote", action: "create_quote" },
    },
  ],
  edges: [],
  created_at: "2026-01-01T10:00:00Z",
};

test("os campos do executor de nó do FUNIL são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/funnels/components": [
      { category: "gatilhos", label: "Gatilhos", color: "#123456", items: [] },
    ],
    "/funnels/f1": FUNIL_ACAO,
    "/crm/clients": [{ id: "c1", name: "Cliente Exemplo" }],
  });
  await page.goto("/funis/f1");
  await page.getByText("Gerar orçamento").first().click();
  // Clique NO ELEMENTO, e não no PONTO dele: em 360px o painel lateral do construtor (`w-60
  // shrink-0`) cobre a coordenada do botão, e nem `force` resolve — o `mousedown` vai para o
  // painel. Essa é a dívida de ALCANCE do #144, que tem dono próprio em `alcance-360.spec.ts`.
  // Aqui a pergunta é a ALTURA dos campos do executor, e um clique bloqueado por outra dívida não
  // pode impedir esta régua de medi-los.
  await page
    .getByRole("button", { name: "Executar ação" })
    .evaluate((el: HTMLElement) => el.click());

  // O executor é um modal ESCRITO À MÃO — não passa por `components/Modal.tsx`, e por isso o
  // conserto de lá não chega até aqui sozinho.
  const CAIXA = ".absolute.inset-0.z-30";
  await expect(page.locator(CAIXA)).toBeVisible();
  expect(await contarCampos(page, CAIXA), "funil: campos").toBeGreaterThanOrEqual(3);
  expect(await camposBaixos(page, CAIXA), "funil — campos abaixo de 44px").toEqual([]);
});

const PECA = {
  skill: "peticao",
  label: "Petição inicial",
  description: "Peça inicial cível.",
  steps: [
    {
      id: "partes",
      title: "Partes",
      description: "Quem está de cada lado.",
      fields: [
        { key: "autor", label: "Autor", type: "text", required: true },
        { key: "reu", label: "Réu", type: "text", required: true },
        { key: "foro", label: "Foro", type: "select", options: ["Cível", "Trabalhista"] },
        { key: "fatos", label: "Fatos", type: "textarea" },
      ],
    },
  ],
};

test("os campos do WIZARD JURÍDICO são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, { "/juridico/skills/peticao": PECA, "/crm/clients": [] });
  await page.goto("/juridico/novo?skill=peticao");
  await expect(page.getByRole("heading", { name: "Petição inicial" })).toBeVisible();
  expect(await contarCampos(page, "main"), "jurídico: campos").toBeGreaterThanOrEqual(4);
  expect(await camposBaixos(page, "main"), "jurídico — campos abaixo de 44px").toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});
