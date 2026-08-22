/**
 * O CATÁLOGO DE ROTAS medidas em 360px — fixtures de pior caso, `marca` e mocks, num lugar só.
 *
 * Vive aqui, e não dentro de um spec, porque hoje DUAS réguas diferentes percorrem a mesma lista:
 * `rotas-360.spec.ts` pergunta se a página rola de lado (a classe do #135, o que ESCAPA do
 * recorte) e `alcance-360.spec.ts` pergunta se todo controle é alcançável (a classe do #58/#144,
 * o que fica PRESO atrás dele). São perguntas opostas sobre a MESMA tela: manter duas cópias das
 * fixtures garantiria que uma régua medisse uma tela que a outra não mede, e a diferença
 * apareceria como "defeito que só uma pega" em vez de como o descuido que seria.
 *
 * ⚠️ **A `marca` não é conveniência.** Medir uma rota que renderizou em branco (mock que não
 * casou, erro de boot, redirect silencioso) passa nas duas réguas — verde por não ter desenhado
 * nada. Toda rota aqui declara um texto que TEM de estar visível antes de qualquer medição.
 *
 * ⚠️ Rota dirigida por dado recebe payload de **pior caso plausível**, na forma do schema real de
 * `packages/shared-types` — nome sem espaço, 12 meses de colunas, texto longo. Dado curto sempre
 * cabe: medir com ele é medir uma tela que não existe. As que aqui ficam em estado vazio estão
 * marcadas com `// vazio:` e provam só o SHELL.
 */

// Pior caso plausível: sem espaço para quebrar, dentro dos limites que os schemas aceitam.
export const LONGO = "RelatorioDeDiagnosticoFinanceiroConsolidadoDoExercicioDeDoisMilEVinteESeis";

/** 12 meses de colunas — a DRE larga de verdade, que é onde o `overflow-x-auto` tem de trabalhar. */
const MESES = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
  "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"];
const CENTS = MESES.map((_, i) => (i + 1) * 1234567);

export const DRE_MATRIX = {
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

/**
 * `/vima/briefing` devolve OBJETO (`BriefingOut`, `apps/api/app/modules/vima/schemas.py`). Com o
 * `[]` default de `mockarApi` a tela nunca sai de "Preparando seu resumo…" — mediria 360 por
 * não ter briefing nenhum, e a `marca` "Seu dia" (que só existe no estado CARREGADO) é
 * exatamente o que reprova esse verde.
 *
 * Pior caso plausível na forma real: `linhas[].texto` é o `title` da ausência, montado com nome
 * DIGITADO pelo dono — fornecedor, título do prazo, nome da conversa (`vima/absences.py`) — e a
 * narração repete esses nomes. Um token sem espaço ali é o que mais empurra numa tela cuja caixa
 * é `max-w-prose` e que não recorta nada: `/vima` mora no `ProtectedBareLayout`, sem o
 * `main.overflow-x-hidden` que segura as telas com shell.
 *
 * `kind` preenchido na PRIMEIRA linha PENDENTE não é enfeite: é o que faz `BriefingPage` montar
 * `GanchoDaVima` (`BriefingPage.tsx:177`) — o caminho que dá nome a esta issue. O card em si
 * segue de fora pelo default `"/dna/pendente": null` de `support/api.ts`, como nas outras cinco.
 *
 * `read_at: null` é o estado em que o dono ABRE a porta do dia; o POST de leitura que ele dispara
 * cai no mesmo prefixo e recebe o mesmo objeto.
 */
const BRIEFING = {
  id: "b1",
  reference_date: "2026-08-21",
  texto: `Bom dia. A conta ${LONGO} venceu ontem, e ${LONGO} escreveu e ainda espera resposta.`,
  por_ia: true,
  vazio: false,
  excedente: 4,
  linhas: [
    { secao: "PENDENTE", module: "financeiro", texto: `${LONGO} — R$ 12.345,67 venceu em 19/08`, kind: "financeiro.conta.vencendo" },
    { secao: "PENDENTE", module: "comercial", texto: `${LONGO} escreveu e ainda não foi respondido`, kind: "comercial.contato.esperando_resposta" },
    { secao: "ACONTECEU", module: "comercial", texto: `${LONGO} virou cliente`, kind: "" },
    { secao: "NÚMEROS", module: "financeiro", texto: `${LONGO}: R$ 123.456,78 recebidos no mês`, kind: "" },
  ],
  read_at: null,
  created_at: "2026-08-21T08:00:00Z",
};

export interface Caso {
  rota: string;
  /** Texto que PRECISA estar visível antes de medir. Sem ele, 360 significaria "tela em branco". */
  marca: string | RegExp;
  mocks?: Record<string, unknown>;
}

export const CASOS: Caso[] = [
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
  // A partir daqui, rotas acrescentadas pelo #144. `/funis/novo` é a outra metade da issue: mesmo
  // componente do `/funis/:id`, estado inicial diferente — e o cabeçalho que não cabia era o
  // mesmo nos dois. As demais são as telas de CONSTRUTOR, que é onde a classe do #58/#144 mora:
  // cabeçalho com pilha de ações e nenhum lugar para elas irem.
  { rota: "/funis/novo", marca: "Automação", mocks: { "/funnels/components": CATALOGO_FUNIL, "/crm/clients": [] } },
  { rota: "/orcamentos/novo", marca: "Orçamentos" }, // vazio: orçamento em branco
  { rota: "/contratos/novo", marca: "Contratos" }, // vazio
  { rota: "/marketing/novo", marca: "Marketing" }, // vazio
  { rota: "/financeiro/investimentos", marca: "Investimentos" }, // vazio
  { rota: "/financeiro/contas", marca: "Contas & Saldos" }, // vazio
  { rota: "/produtos", marca: "Produtos" }, // vazio
  { rota: "/estoque", marca: "Controle de Estoque" }, // vazio
  { rota: "/busca", marca: "Busca" }, // vazio
  { rota: "/pagar", marca: "Despesas" }, // vazio
  { rota: "/conversas", marca: "Conversas" }, // vazio
  // A PORTA DO DIA (#178). `EntradaDoDia` manda a raiz autenticada para cá enquanto o briefing de
  // hoje não foi lido: é a PRIMEIRA tela que o dono vê no aparelho de 360px, e era a única das
  // seis que montam `GanchoDaVima` sem régua nenhuma. Mora no `ProtectedBareLayout` — sem shell,
  // logo sem o `main.overflow-x-hidden`: aqui o que não cabe faz a PÁGINA rolar em vez de ficar
  // recortado, e é a régua do #135 que o pega primeiro.
  { rota: "/vima", marca: "Seu dia", mocks: { "/vima/briefing": BRIEFING } },
];
