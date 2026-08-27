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

export const PAGINA = {
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

export const CARROSSEL = {
  id: "m1", tenant_id: "t1", topic: LONGO, platform: "instagram",
  slides: [slide("cover"), slide("editorial"), slide("accent"), slide("cta")],
  status: "draft", handle: `@${LONGO}`, caption: LONGO, hashtags: `#${LONGO}`,
  template: "editorial", primary_color: "#123456", bg_color: "#ffffff",
  text_color: "#111111", accent_color: "#ff0000", font: "Inter",
  created_at: "2026-01-01T10:00:00Z",
};

/** As LISTAS de `/funis` e `/juridico` (#182). Ficam aqui porque o catálogo é quem as usa; são
 * importadas por `card-largo-360.spec.ts`, que mede a BORDA do card, para não haver duas cópias. */
export const FUNIS_LONGOS = [
  { id: "f1", name: LONGO, node_count: 7, created_at: "2026-01-01T10:00:00Z" },
];

export const JURIDICO_DOCS = [
  { id: "d1", skill: "peticao", category: "core", title: LONGO, client_id: null,
    client_name: LONGO, status: "ready", created_at: "2026-01-01T10:00:00Z" },
];

export const JURIDICO_SKILLS = [
  { skill: "peticao", label: LONGO, category: "core", description: `${LONGO} ${LONGO}`,
    output_type: LONGO },
];

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

/**
 * `/dna/faltantes` devolve LISTA (`DnaPergunta[]`, `packages/shared-types/src/index.ts:1182`), e o
 * `[]` default de `mockarApi` é o pior mock que existe para esta rota: com a lista vazia a
 * `NucleoPage` chama `sair()` e **NAVEGA para a raiz** (`NucleoPage.tsx:110`). A régua mediria o
 * PAINEL acreditando ter medido o núcleo — 360 verdinho, tela errada. Por isso a `marca` é o texto
 * da PRIMEIRA pergunta, e não o título fixo "Me conta do seu negócio".
 *
 * **Só `perguntas[0]` está na tela por vez** — a página renderiza um índice, não a lista. Então o
 * pior caso mora na primeira; as seis continuam aqui porque o denominador é impresso ("1 de 6") e
 * porque `ehPergunta` (`GanchoDaVima.tsx:45`) filtra item a item: uma forma quebrada no meio da
 * lista muda o denominador sem derrubar a tela, e é assim que a produção se comporta.
 *
 * `formato: "escolha"` na primeira não é conveniência: é o ramo que rende os blocos de largura
 * inteira do `PerguntaDaVima` (`px-4 py-3`, um por opção) — a caixa mais larga que esta tela
 * desenha sem ninguém tocar em nada. Os outros dois formatos ficam nas seguintes.
 *
 * O catálogo mora no SERVIDOR (`apps/api/app/modules/dna/catalog.py`) e hoje é português
 * editorial, com espaço para quebrar — mas o front **não tem cópia dele** (é o que o próprio
 * `DnaPergunta` declara), e pergunta nova é um deploy. `LONGO` é o que guarda a PRÓXIMA: sem
 * espaço para quebrar, dentro do `max-w-md` de uma tela que não recorta nada.
 */
const NUCLEO_PERGUNTAS = [
  { key: "oferta.o_que_vende", classe: "retrato", eixo: "oferta", texto: `O que você vende, ${LONGO}?`,
    formato: "escolha", opcoes: [{ rotulo: LONGO, valor: "servico_recorrente" }, { rotulo: `${LONGO} avulso`, valor: "servico_projeto" }] },
  { key: "oferta.em_uma_frase", classe: "retrato", eixo: "oferta", texto: LONGO, formato: "texto", opcoes: [] },
  { key: "oferta.como_cobra", classe: "retrato", eixo: "oferta", texto: LONGO, formato: "escolha_multipla",
    opcoes: [{ rotulo: LONGO, valor: "hora" }] },
  { key: "oferta.ticket_tipico", classe: "retrato", eixo: "oferta", texto: LONGO, formato: "escolha", opcoes: [{ rotulo: LONGO, valor: 1 }] },
  { key: "cliente.como_chega", classe: "retrato", eixo: "cliente", texto: LONGO, formato: "escolha", opcoes: [{ rotulo: LONGO, valor: "indicacao" }] },
  { key: "limites.nunca_faco", classe: "retrato", eixo: "limites", texto: LONGO, formato: "texto", opcoes: [] },
];

/**
 * A BANDEJA do comprovante (`/comprovante/:id`) — duas listas, e as duas precisam de forma.
 *
 * `/payables/receipts` devolve `ReceiptInfo[]` (declarado em `ComprovantePage.tsx:17`; não existe
 * `GET /payables/receipts/{id}`, a tela FILTRA a bandeja pelo `id` da URL). O `id` daqui tem de
 * casar com o da rota (`/comprovante/r1`), senão `receipt` fica `null` e o cabeçalho cai no texto
 * genérico — verde medindo o estado de fallback em vez do estado real.
 *
 * `/payables/receipts/candidates` devolve `Payable[]`
 * (`packages/shared-types/src/index.ts:459`). Vence a chave MAIS LONGA em `mockarApi`, então as
 * duas convivem. Com o `[]` default as duas caem no estado vazio — cabeçalho genérico e "Nenhuma
 * conta encontrada" —, que mede 360 por não ter desenhado a tela que interessa.
 *
 * Pior caso plausível na forma real: `description`/`supplier` são DIGITADOS pelo dono (o
 * fornecedor vem do app do banco, copiado no celular) e `filename` vem do share sheet do
 * Android — nenhum dos três tem espaço garantido. `amount_cents` acompanha as demais fixtures do
 * catálogo (`RELATORIO_CC`): R$ 1.234.567,89, que é o que faz a coluna `shrink-0` da direita
 * valer o que ela vale. A segunda candidata é `description: ""` + `status: "paid"`, os dois
 * ramos que o cartão tem de próprio (`c.description || c.supplier` e o chip "Pago").
 *
 * ⚠️ **A barra fixa do rodapé fica FORA desta medida**: `EscolhaDaBaixa` e o rótulo com o nome da
 * conta só montam depois de TOCAR numa candidata (`daBaixa`), e este catálogo não toca em nada. O
 * que a barra tem de próprio continua sendo assunto de spec dedicada — é a dívida do
 * `ALTURA_DA_BARRA` registrada no §5.1, e esta entrada não a fecha.
 */
const RECEIPTS = [{ id: "r1", filename: `${LONGO}.pdf`, size: 3_670_016 }];

const CANDIDATAS = [
  { id: "p1", tenant_id: "t1", description: LONGO, category: LONGO, supplier: LONGO,
    amount_cents: 123456789, due_date: "2026-08-19", chart_account_id: null, contract_id: null,
    cost_center_id: null, status: "open", is_overdue: true, paid_at: null, recurrence: "none",
    recurrence_count: 0, recurrence_group: null, payment_code: LONGO, attachment_url: "",
    created_at: "2026-08-01T10:00:00Z" },
  { id: "p2", tenant_id: "t1", description: "", category: "Geral", supplier: LONGO,
    amount_cents: 987654321, due_date: "2026-09-30", chart_account_id: null, contract_id: null,
    cost_center_id: null, status: "paid", is_overdue: false, paid_at: "2026-08-20T10:00:00Z",
    recurrence: "none", recurrence_count: 0, recurrence_group: null, payment_code: "",
    attachment_url: "", created_at: "2026-08-01T10:00:00Z" },
];

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
  // #182: as duas saíram do estado vazio. A `marca` é o TÍTULO DO CARD, não o da página: com o
  // título da página elas passavam sem card nenhum, e foi assim que o card de 316px fora da tela
  // atravessou o #135, o #144 e o #160. A borda do card é medida em `card-largo-360.spec.ts`.
  { rota: "/juridico", marca: LONGO, mocks: { "/juridico/documents": JURIDICO_DOCS, "/juridico/skills": JURIDICO_SKILLS } },
  { rota: "/funis", marca: LONGO, mocks: { "/funnels": FUNIS_LONGOS } },
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
  // AS OUTRAS TRÊS DO `ProtectedBareLayout` (#208). Mesma caixa de layout da `/vima`, e foi a
  // FORMA dessa caixa — não a tela — que produziu os 649px do #178: sem shell não há
  // `main.overflow-x-hidden`, então o que não cabe VAZA em vez de ficar recortado. Entram no fim
  // do array de propósito: a ordem das anteriores é o histórico das issues que as trouxeram.
  { rota: "/dna/nucleo", marca: LONGO, mocks: { "/dna/faltantes": NUCLEO_PERGUNTAS } },
  // `/compartilhar` é a única das quatro que NÃO é dirigida por payload: é rota de trânsito do
  // Web Share Target e desenha dois estados só — o spinner e o erro. O que se mede é o ERRO, o
  // único com conteúdo; e `?erro=` é como o service worker o reporta quando o POST do share
  // sheet falha (`public/sw.js:55` — o valor `falha` é o que o SW emite de verdade; o outro é
  // `sem-arquivo`). A `marca` é a frase que SÓ esse ramo produz: sem ela o teste
  // passaria medindo "Enviando comprovante...", que é a tela em branco desta rota.
  //
  // ⚠️ **Por que `?erro=` e não `?k=<chave já consumida>`**, que seria o caminho mais comum em
  // campo: medido no #208, com `?k=` a tela fica PRESA no spinner em modo de desenvolvimento e a
  // `marca` reprova. Não é defeito da fixture — é o guard de StrictMode do `CompartilharPage`
  // (`startedFor`) casando com o `cancelled` por execução: a primeira montagem começa o trabalho
  // assíncrono e é cancelada na limpeza, a segunda vê o mesmo token e desiste, e ninguém chama
  // `setError`. O ramo do `?erro=` é SÍNCRONO, então o estado sobrevive à dobra. Está registrado
  // como achado fora do escopo do #208; a régua mede o estado que existe, e não fica vermelha
  // esperando o conserto de outra issue.
  { rota: "/compartilhar?erro=falha", marca: "Não conseguimos receber o arquivo compartilhado" },
  // TELA DE DINHEIRO, e a que carrega a dívida de medição do §5.1: o `ALTURA_DA_BARRA` do
  // `baixa.ts` tem seis mutantes sobreviventes porque o número é medida do DOM e ninguém media
  // esta tela. O `r1` da rota casa com o `id` de `RECEIPTS` — ver a nota da fixture.
  { rota: "/comprovante/r1", marca: LONGO, mocks: { "/payables/receipts": RECEIPTS, "/payables/receipts/candidates": CANDIDATAS } },
];
