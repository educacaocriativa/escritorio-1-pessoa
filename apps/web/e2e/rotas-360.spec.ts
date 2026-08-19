import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina } from "./support/medidas";
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

// Pior caso plausível: sem espaço para quebrar, dentro dos limites que os schemas aceitam.
const LONGO = "RelatorioDeDiagnosticoFinanceiroConsolidadoDoExercicioDeDoisMilEVinteESeis";

/** 12 meses de colunas — a DRE larga de verdade, que é onde o `overflow-x-auto` tem de trabalhar. */
const MESES = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
  "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"];
const CENTS = MESES.map((_, i) => (i + 1) * 1234567);

const DRE_MATRIX = {
  months: MESES,
  groups: [{
    key: "RECEITA",
    label: null,
    rows: [{ label: LONGO, kind: "result", grupo_dre: "RECEITA", monthly_cents: CENTS, total_cents: 9999999 }],
    subtotal_cents: CENTS,
    subtotal_total: 9999999,
  }],
  grand_total_cents: CENTS,
  grand_total: 9999999,
  notes: [],
};

const PAGINA = {
  id: "s1", tenant_id: "t1", title: LONGO, model: "captura", status: "draft",
  public_slug: null, created_at: "2026-01-01T10:00:00Z",
  primary_color: "#123456", bg_color: "#ffffff", text_color: "#111111",
  accent_color: "#ff0000", font: "Inter", logo_url: "",
  blocks: [
    { type: "heading", text: LONGO },
    { type: "text", text: `${LONGO} ${LONGO}` },
    { type: "button", label: LONGO, url: `https://exemplo.com.br/${LONGO}` },
    { type: "form", button: LONGO, showEmail: true, extraFields: [], disclaimer: LONGO },
    { type: "divider" },
  ],
};

const slide = (kind: string) => ({
  kind, heading: LONGO, body: LONGO, secondary: LONGO,
  highlight: "Diagnostico", photo_url: "", photo_position: "mid",
});

const CARROSSEL = {
  id: "m1", tenant_id: "t1", topic: LONGO, platform: "instagram",
  slides: [slide("cover"), slide("editorial"), slide("accent"), slide("cta")],
  status: "draft", handle: `@${LONGO}`, caption: LONGO, hashtags: `#${LONGO}`,
  template: "editorial", primary_color: "#123456", bg_color: "#ffffff",
  text_color: "#111111", accent_color: "#ff0000", font: "Inter",
  created_at: "2026-01-01T10:00:00Z",
};

const CATALOGO_FUNIL = [{
  category: "gatilhos", label: "Gatilhos", color: "#123456",
  items: [{ key: "lead", label: LONGO, description: LONGO, shape: "node", action: "" }],
}];

const FUNIL = {
  id: "f1", tenant_id: "t1", name: LONGO,
  nodes: [
    { id: "n1", type: "default", position: { x: 0, y: 0 }, data: { label: LONGO, key: "lead", action: "" } },
    { id: "n2", type: "default", position: { x: 900, y: 400 }, data: { label: LONGO, key: "quote", action: "create_quote" } },
  ],
  edges: [{ id: "e1", source: "n1", target: "n2" }],
  created_at: "2026-01-01T10:00:00Z",
};

/** `/financial-intelligence/by-cost-center` devolve OBJETO. Com `[]` (o default de `mockarApi`)
 * a tela renderiza e quebra no primeiro campo — tela branca que mediria 360 e passaria. */
const RELATORIO_CC = {
  start: "2026-08-01", end: "2026-08-31",
  buckets: [
    { cost_center_id: "cc1", name: LONGO, kind: "operacional", receita_cents: 123456789, resultado_cents: -98765432, lancamentos: 42 },
    { cost_center_id: null, name: "Não atribuído", kind: null, receita_cents: 0, resultado_cents: -1234567, lancamentos: 3 },
  ],
  notes: [],
};

const CENTROS = [
  { id: "cc1", tenant_id: "t1", name: LONGO, kind: "operacional", archived_at: null, created_at: "2026-01-01T10:00:00Z" },
];

const PROJECAO = {
  today: "2026-08-19",
  saldo_inicial_cents: 12845079,
  saldo_inicial_origem: "misto",
  saldo_inicial_banco_cents: 12000000,
  saldo_inicial_plataforma_cents: 845079,
  overdue_inflow_cents: 1234567,
  overdue_outflow_cents: 7654321,
  windows: [
    { days: 30, saldo_projetado_cents: 9876543, alert: false, alert_suprimido: false },
    { days: 60, saldo_projetado_cents: -1234567, alert: true, alert_suprimido: false },
    { days: 90, saldo_projetado_cents: -9876543, alert: true, alert_suprimido: false },
  ],
  runway: { days: 47, days_suprimido: false, burn_rate_cents_per_day: 123456 },
  notes: [],
};

const DIAGNOSTICO = {
  start: "2026-08-01", end: "2026-08-31",
  signals: [
    { level: "vermelho", title: LONGO, explanation: `${LONGO} ${LONGO}`, source: "motor" },
    { level: "amarelo", title: LONGO, explanation: LONGO, source: "motor" },
    { level: "verde", title: LONGO, explanation: LONGO, source: "motor" },
  ],
  narrative: `${LONGO} ${LONGO} ${LONGO}`,
  narrative_source: "template",
};

interface Caso {
  rota: string;
  /** Texto que PRECISA estar visível antes de medir. Sem ele, 360 significaria "tela em branco". */
  marca: string | RegExp;
  mocks?: Record<string, unknown>;
}

const CASOS: Caso[] = [
  { rota: "/financeiro", marca: "Carteira" }, // vazio: lista sem dado
  { rota: "/financeiro/plano-contas", marca: "Plano de contas" }, // vazio
  { rota: "/financeiro/centros-custo", marca: "Centros de custo", mocks: { "/cost-centers": CENTROS, "/financial-intelligence/by-cost-center": RELATORIO_CC } },
  { rota: "/financeiro/dre", marca: "DRE por categoria", mocks: { "/financial-intelligence/dre/matrix": DRE_MATRIX } },
  { rota: "/financeiro/lucratividade", marca: "Lucratividade por Contrato" }, // vazio
  { rota: "/financeiro/projecao-caixa", marca: "Projeção de fluxo de caixa", mocks: { "/financial-intelligence/projection": PROJECAO } },
  { rota: "/financeiro/fila-pagamentos", marca: "Fila de pagamentos" }, // vazio
  { rota: "/financeiro/diagnostico", marca: "Diagnóstico financeiro", mocks: { "/financial-intelligence/diagnostics": DIAGNOSTICO } },
  { rota: "/cobrancas", marca: "Contas a Receber" }, // vazio
  { rota: "/sites", marca: "Sites & Páginas" }, // vazio
  { rota: "/sites/s1", marca: "Pré-visualização", mocks: { "/pages": PAGINA } },
  { rota: "/orcamentos", marca: "Orçamentos" }, // vazio
  { rota: "/contratos", marca: "Contratos" }, // vazio
  { rota: "/marketing", marca: "Carrosséis" }, // vazio
  { rota: "/marketing/m1", marca: "Pré-visualização (Instagram 4:5) — baixe em PNG", mocks: { "/marketing/carousels/templates": [], "/marketing/carousels": CARROSSEL } },
  { rota: "/juridico", marca: "Assistente Jurídico" }, // vazio
  { rota: "/funis", marca: "Funis de Vendas" }, // vazio
  { rota: "/funis/f1", marca: "Automação", mocks: { "/funnels/components": CATALOGO_FUNIL, "/funnels/f1": FUNIL, "/crm/clients": [] } },
];

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
 * CONTROLE POSITIVO — o que impede as 18 asserções acima de serem enfeite.
 *
 * Medido nesta issue (#135), e é o achado que reescreve a premissa: `main` é
 * `overflow-x-hidden` (`AppShell.tsx:64`). Uma tabela larga demais NÃO faz o documento rolar —
 * ela é recortada, e `larguraDaPagina` devolve 360 com a coluna da direita inalcançável. Provado
 * por mutação: tirar `overflow-x-auto` da `DrePage` (o deslizador da DRE de 12 meses) deixa as 18
 * rotas VERDES. Logo, esta régua não mede "conteúdo largo" — ela mede exatamente uma coisa, e é a
 * classe do #135: um elemento que ESCAPA do recorte e passa a contar no `scrollWidth` do
 * documento. É o que um `position: absolute` SEM offsets faz quando não há ancestral posicionado:
 * o bloco contêiner dele vira a página, e a sua posição estática — lá no fundo de um deslizador de
 * 12 colunas — vira largura de documento.
 *
 * Este teste planta essa classe de propósito, na `DrePage` (cujo `overflow-x-auto` da linha 131
 * não tem `relative`), e exige que a conta a enxergue. Se algum dia ele passar a devolver 360, a
 * medição ficou cega e as 18 asserções acima pararam de significar qualquer coisa — mesmo
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
