import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { alvosPequenos, medirPagina } from "./support/medidas";
import { LONGO } from "./support/rotas";
import { semearSessao } from "./support/sessao";

const CONTA = {
  id: "00000000-0000-4000-8000-000000000001",
  name: "Conta Corrente Principal",
  kind: "checking",
  institution: "Banco Cooperativo Sicredi S.A.",
  institution_code: "748",
  branch: "1234-5",
  number: "12345-6",
  holder_document: "123.456.789-00",
  pix_key: "",
  opening_balance_cents: 125000,
  opening_balance_is_known: true,
  opening_date: "2026-01-01",
  is_primary: true,
  archived_at: null,
  saldo_derivado_cents: 12845079,
  saldo_derivado_origem: "banco",
  agendado_saida_cents: 1238000,
  agendado_entrada_cents: 0,
  agendado_origem: "banco",
  created_at: "2026-01-01T10:00:00Z",
};

// A ação "Transferir entre contas" só existe com DUAS contas ativas (com uma só não há para onde
// transferir, e o botão seria promessa vazia). Medir com uma conta deixaria essa ação de fora
// justamente na tela em que ela é a mais comprida.
const SEGUNDA_CONTA = {
  ...CONTA,
  id: "00000000-0000-4000-8000-000000000002",
  name: "Conta PJ Nubank",
  institution: "Nu Pagamentos S.A.",
  institution_code: "260",
  is_primary: false,
  saldo_derivado_cents: 300000,
  agendado_saida_cents: 0,
};

test("as ações da conta são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/bank/accounts": [CONTA, SEGUNDA_CONTA],
    // O cartão da conta busca o último saldo declarado por conta. Sem estas chaves, `mockarApi`
    // devolveria a LISTA DE CONTAS aqui (o prefixo casa) e o cartão leria uma conta como se fosse
    // um checkpoint — ver a nota em `support/api.ts`.
    [`/bank/accounts/${CONTA.id}/checkpoints`]: [],
    [`/bank/accounts/${SEGUNDA_CONTA.id}/checkpoints`]: [],
    "/bank/transfers": [],
  });
  await page.goto("/financeiro/contas");
  await expect(page.getByText("Conta Corrente Principal")).toBeVisible();

  // As sete ações por conta eram links de texto de 16px de altura, e "Arquivar" — destrutiva —
  // ficava a 4px de "Editar". É a classe de defeito do PR #56, num alvo que o polegar erra.
  for (const rotulo of [
    "Declarar saldo",
    "Lançar movimento",
    "Transferir entre contas",
    "Conferir",
    "Ver movimentos",
    "Editar",
    "Arquivar",
  ]) {
    const alvo = page.getByRole(rotulo === "Conferir" ? "link" : "button", { name: rotulo }).last();
    const caixa = await alvo.boundingBox();
    expect(caixa, rotulo).not.toBeNull();
    expect(caixa!.height, rotulo).toBeGreaterThanOrEqual(44);
  }

  const caixaCheckbox = await page.getByText("Mostrar arquivadas").boundingBox();
  expect(caixaCheckbox!.height).toBeGreaterThanOrEqual(44);

  // O "Transferir entre contas" do CABEÇALHO é outro botão, com outra classe — a medição final
  // achou que ele tinha ficado em 34px depois de as ações do cartão irem para 44.
  const cabecalho = await page
    .getByRole("button", { name: "Transferir entre contas" })
    .first()
    .boundingBox();
  expect(cabecalho!.height).toBeGreaterThanOrEqual(44);

  // O que já estava certo continua certo: a largura nunca precisou de rolagem lateral, e os
  // valores aparecem INTEIROS (`R$ 128.450,79`, não `R$ 128.` — o defeito da Onda 2b-ii).
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
  await expect(page.getByText("R$ 128.450,79")).toBeVisible();
});

// ── A aba "A sua empresa" ───────────────────────────────────────────────────────────────────
// Recorte real de `apps/api/app/modules/dna/catalog.py` — dois eixos bastam para medir.
const CATALOGO_DNA = [
  {
    key: "oferta.o_que_vende",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você vende?",
    formato: "escolha",
    opcoes: [
      { rotulo: "Serviço recorrente", valor: "servico_recorrente" },
      { rotulo: "Serviço por projeto", valor: "servico_projeto" },
      { rotulo: "Um pouco de cada", valor: "misto" },
    ],
  },
  {
    key: "oferta.em_uma_frase",
    classe: "retrato",
    eixo: "oferta",
    texto: "Se um cliente perguntar o que você faz, o que você responde?",
    formato: "texto",
    opcoes: [],
  },
  {
    key: "dinheiro.antecedencia_dias",
    classe: "calibracao",
    eixo: "dinheiro",
    texto: "E de uma conta a pagar?",
    formato: "escolha",
    opcoes: [
      { rotulo: "No próprio dia", valor: 0 },
      { rotulo: "1 dia antes", valor: 1 },
      { rotulo: "3 dias antes", valor: 3 },
      { rotulo: "1 semana antes", valor: 7 },
    ],
  },
  {
    key: "dinheiro.cobranca_antecedencia_dias",
    classe: "calibracao",
    eixo: "dinheiro",
    texto: "E de uma cobrança que você tem a receber?",
    formato: "escolha",
    opcoes: [
      { rotulo: "No próprio dia", valor: 0 },
      { rotulo: "1 dia antes", valor: 1 },
      { rotulo: "3 dias antes", valor: 3 },
      { rotulo: "1 semana antes", valor: 7 },
    ],
  },
];

test("a aba 'A sua empresa' abre recolhida, não com 22 telas de rolagem", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/dna/catalogo": CATALOGO_DNA,
    "/dna/respostas": {},
    // `TenantProfile` INTEIRO: a tela de Configurações lê brand kit, WhatsApp e vendas, e um
    // perfil pela metade a derruba antes de a aba do DNA existir (tela em branco).
    "/settings/profile": {
      display_name: "Flávio Kato Consultoria Empresarial ME",
      document: "12.345.678/0001-90",
      email: "dono@exemplo.com.br",
      phone: "+55 11 98765-4321",
      address: "Av. Brigadeiro Faria Lima, 3477 — 14º andar, São Paulo/SP",
      website: "https://exemplo.com.br",
      about: "Consultoria em gestão para pequenos negócios.",
      logo_url: "",
      primary_color: "#5D44F8",
      secondary_color: "#1F1235",
      accent_color: "#FF7A59",
      text_color: "#1F2937",
      bg_color: "#FFFFFF",
      font: "Inter",
      timezone: "America/Sao_Paulo",
      default_entry_funnel_id: null,
      whatsapp_configured: false,
      whatsapp_provider: "evolution",
      whatsapp_phone_id: "",
      whatsapp_waba_id: "",
      whatsapp_verify_token: "abc123",
      whatsapp_template_bindings: {},
    },
  });
  await page.goto("/config");
  await page.getByRole("button", { name: "A sua empresa" }).click();
  await expect(page.getByText("Oferta")).toBeVisible();

  // Medido antes: **16.495px = 22,3 telas** de 740px, com a pergunta que o PR #103 acrescentou ao
  // eixo `dinheiro` a **14,6 telas** do topo. O cabeçalho da própria aba diz que "a Vima pergunta
  // aos poucos" — despejar as 46 de uma vez contradiz a promessa que a tela faz.
  const { alturaDaPagina } = await medirPagina(page);
  expect(alturaDaPagina).toBeLessThan(1500);

  // E o eixo abre quando o dono pede — inclusive a linha que o PR #103 acrescentou ao `dinheiro`.
  await page.locator("details", { hasText: "Dinheiro" }).locator("summary").click();
  const pergunta = page.getByText("E de uma cobrança que você tem a receber?");
  await expect(pergunta).toBeVisible();

  // `toBeVisible` prova que renderizou; a largura prova que CABE. Não se exige `toBeInViewport`
  // aqui: o eixo aberto fica abaixo da dobra e rolar na vertical é o gesto normal — o que a
  // dívida cobra é não precisar rolar de LADO.
  await pergunta.scrollIntoViewIfNeeded();
  const caixa = await pergunta.boundingBox();
  expect(caixa!.x).toBeGreaterThanOrEqual(0);
  expect(caixa!.x + caixa!.width).toBeLessThanOrEqual(360);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

// ── `/financeiro/centros-custo` ────────────────────────────────────────────────────
// A TERCEIRA régua desta rota (#181), e as outras duas já passavam nela quando esta foi escrita.
//
// ⚠️ Três perguntas DIFERENTES sobre a mesma tela, e verde nas duas primeiras não diz nada sobre a
// terceira — foi exatamente assim que este defeito sobreviveu a dois PRs:
//
//   - `alcance-360` (#144/PR #156): o dedo CHEGA ao controle? Ali «Editar» e «Arquivar» começavam
//     em x=637 e x=699 numa tela de 360px — INTEIRAMENTE fora. O `flex-wrap` os trouxe de volta.
//   - `centros-custo-360` (#157/PR #174): a TINTA cabe? 14 elementos de texto terminavam além da
//     borda do cartão, com a página inteira ainda dizendo `scrollWidth === 360`.
//   - esta: o alvo tem TAMANHO de dedo? Os dois botões que o #156 tornou alcançáveis ficaram
//     alcançáveis **e de 16px de altura**, e o «Mostrar arquivados» era um checkbox de **13×13**
//     — a forma LITERAL do defeito do PR #56, onde um controle pequeno demais fez uma conta real
//     ser marcada como paga sem o dono conseguir ver.
//
// Medido em 21/08/2026, ANTES do conserto, com `alvosPequenos` no documento inteiro:
//   input                                  13   × 13
//   button «Editar»                        49,6 × 16
//   button «Arquivar»                      64,3 × 16
//
// A fixture é a MESMA de `centros-custo-360` e de `support/rotas.ts` (nome de 74 chars sem
// espaço) de propósito: 44px de altura muda o REFLOW do cartão, e medir com nome curto seria
// medir uma tela que o #157 já provou não existir.
const CENTRO = {
  id: "cc1",
  tenant_id: "t1",
  name: LONGO,
  kind: "operacional",
  archived_at: null,
  created_at: "2026-01-01T10:00:00Z",
};

const RELATORIO_CENTROS = {
  start: "2026-08-01",
  end: "2026-08-31",
  buckets: [
    {
      cost_center_id: "cc1",
      name: LONGO,
      kind: "operacional",
      receita_cents: 123456789,
      resultado_cents: -98765432,
      lancamentos: 42,
    },
    {
      cost_center_id: null,
      name: "Não atribuído",
      kind: null,
      receita_cents: 0,
      resultado_cents: -1234567,
      lancamentos: 3,
    },
  ],
  notes: [],
};

test("as ações do centro de custo são tocáveis com o polegar", async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/cost-centers": [CENTRO],
    // `by-cost-center` devolve OBJETO. Com o `[]` default de `mockarApi` a tela quebra no primeiro
    // campo e o que sobra é uma página em branco — que não tem controle nenhum e passaria.
    "/financial-intelligence/by-cost-center": RELATORIO_CENTROS,
  });
  await page.goto("/financeiro/centros-custo");
  // A `marca`: sem ela, "zero alvos pequenos" significaria "não desenhou nada".
  await expect(page.getByTestId("lista-centros")).toBeVisible();

  // As duas ações do cartão — as MESMAS que o #156 trouxe para dentro da tela, e «Arquivar» é
  // destrutiva. Mesma forma do bloco de `/financeiro/contas` acima, inclusive a mensagem por
  // rótulo: um vermelho sem nome não diz qual dos dois encolheu.
  for (const rotulo of ["Editar", "Arquivar"]) {
    const alvo = page.getByRole("button", { name: rotulo }).last();
    const caixa = await alvo.boundingBox();
    expect(caixa, rotulo).not.toBeNull();
    expect(caixa!.height, rotulo).toBeGreaterThanOrEqual(44);
  }

  // O alvo do checkbox é a LINHA INTEIRA do rótulo, não a caixinha — mesma convenção do
  // «Mostrar arquivadas» de `/financeiro/contas` (`ContasSaldosPage.tsx:208`). Engordar o
  // `<input>` para 44×44 daria um quadrado desenhado do tamanho de um botão; o que o dedo precisa
  // é de ÁREA, e o `<label>` já alterna o estado em qualquer ponto dela.
  const caixaCheckbox = await page.getByText("Mostrar arquivados").boundingBox();
  expect(caixaCheckbox, "Mostrar arquivados").not.toBeNull();
  expect(caixaCheckbox!.height, "Mostrar arquivados").toBeGreaterThanOrEqual(44);

  // O «Novo centro de custo» vem do `usePrimaryAction` e é desenhado pelo CABEÇALHO DO SHELL —
  // outro botão, outra classe, fora do `<main>`. É o mesmo cuidado que o bloco de
  // `/financeiro/contas` tem com o «Transferir entre contas» do cabeçalho: lá a medição final o
  // pegou em 34px depois de as ações do cartão irem para 44.
  const cabecalho = await page
    .getByRole("button", { name: "Novo centro de custo" })
    .boundingBox();
  expect(cabecalho, "Novo centro de custo").not.toBeNull();
  expect(cabecalho!.height, "Novo centro de custo").toBeGreaterThanOrEqual(44);

  // E a varredura, que é o que impede este arquivo de medir SÓ os três alvos que a issue já
  // conhecia. Documento inteiro de propósito: um ícone, um chip, um `summary` ou um controle de
  // filtro acrescentado depois entra na conta sem ninguém precisar lembrar de escrever a linha.
  //
  // ⚠️ **`checkbox` e `radio` ficam de fora, e o motivo é que `alvosPequenos` mede o ELEMENTO,
  // não a área que o dedo acerta.** A caixinha tem 20×20 DEPOIS do conserto, e continuará tendo:
  // quem cumpre os 44px é o `<label>` que a envolve — medido oito linhas acima, e a mesma
  // convenção de `ContasSaldosPage.tsx:208`. Exigir 44 do quadrado desenhado acusaria toda tela
  // que segue o padrão do repo e daria um botão onde deveria haver um checkbox.
  //
  // ⚠️ **O recorte era `!descricao.startsWith("input")` — TODO `<input>` — e o custo estava
  // escrito aqui: "um campo de TEXTO de 38px acrescentado a esta página passaria por aqui". Ele
  // passou.** O modal desta mesma rota tinha exatamente dois (`<input>` do `Field` a 38px,
  // `<select>` de tipo a 39px) e virou a issue #215. `Alvo` passou a carregar `tipo` justamente
  // para que este filtro pudesse recortar só o que precisa ser recortado: um `<input type="text"`
  // baixo demais agora reprova AQUI, além de reprovar na régua transversal
  // (`campo-modal-360.spec.ts`), que mede os campos com o modal ABERTO em 16 telas.
  const pequenos = (await alvosPequenos(page)).filter(
    (a) => a.tipo !== "checkbox" && a.tipo !== "radio",
  );
  expect(pequenos, "alvos abaixo de 44px").toEqual([]);

  // O que as outras duas réguas já garantiam continua garantido DEPOIS de os alvos crescerem:
  // 44px de altura mexe no reflow do cartão, e era o reflow que o #156 e o #157 consertaram.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
  await expect(page.getByTestId("comparativo-centros")).toBeVisible();
});

// ── `/agenda`, modal "Novo evento" — checkbox "Dia inteiro" ────────────────────────────────────
// A forma LITERAL do PR #56 (issue #227, item "Dívida menor"): o alvo era um checkbox de 13×13
// sem `min-h-[44px]` na LINHA do rótulo — e a consequência medida daquele PR foi uma conta real
// marcada como paga sem o dono conseguir ver. Aqui o controle troca "conta paga" por "evento de
// dia inteiro", mas o mecanismo do defeito é o mesmo dedo errando o mesmo alvo pequeno.
//
// Escopo deliberadamente pequeno: só a LINHA do rótulo ganha `min-h-[44px]` — mesma convenção do
// `ContasSaldosPage.tsx:208` e do teste de `/financeiro/centros-custo` acima. O `<input>` em si
// não muda de tamanho (a issue #227 é explícita: o alvo de toque é a linha inteira, não a
// caixinha).
test("o checkbox 'Dia inteiro' do modal de evento (/agenda) é tocável com o polegar", async ({
  page,
}) => {
  // Relógio congelado: `/agenda` abre no mês corrente e o modal de evento nasce com a data de
  // hoje. Sem isto o teste mede uma tela diferente a cada dia — mesma nota do bloco de
  // `campo-modal-360.spec.ts` para esta mesma rota.
  await page.clock.setFixedTime(new Date("2026-08-18T12:00:00Z"));
  await semearSessao(page);
  await mockarApi(page, {});
  await page.goto("/agenda");

  await page.getByRole("button", { name: "Novo evento" }).first().click();
  await expect(page.getByRole("heading", { name: "Novo evento" })).toBeVisible();

  const overlay = page.locator(".fixed.inset-0.z-50");
  const caixaCheckbox = await overlay.getByText("Dia inteiro").boundingBox();
  expect(caixaCheckbox, "Dia inteiro").not.toBeNull();
  expect(caixaCheckbox!.height, "Dia inteiro").toBeGreaterThanOrEqual(44);

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});

// ── `/financeiro/plano-contas` — checkbox "Mostrar arquivadas" ─────────────────────────────────
// Mesma dívida menor da issue #227: checkbox de 13×13 sem a classe `h-5 w-5` que é a convenção do
// repo para o quadrado do checkbox (20×20 — ver `ContasSaldosPage.tsx:208` e
// `CentrosCustoPage.tsx:86`). O `<label>` já cumpria os 44px? Não: também faltava `min-h-[44px]`
// na linha, então as duas metades da convenção (caixinha 20×20 + linha 44px) foram aplicadas
// juntas, exatamente como nas outras três telas de `/financeiro` que já seguem o padrão.
test("o checkbox 'Mostrar arquivadas' de /financeiro/plano-contas é tocável com o polegar", async ({
  page,
}) => {
  await semearSessao(page);
  await mockarApi(page, { "/chart-of-accounts": [] });
  await page.goto("/financeiro/plano-contas");
  await expect(page.getByRole("heading", { name: "Plano de contas" })).toBeVisible();

  const caixaCheckbox = await page.getByText("Mostrar arquivadas").boundingBox();
  expect(caixaCheckbox, "Mostrar arquivadas").not.toBeNull();
  expect(caixaCheckbox!.height, "Mostrar arquivadas").toBeGreaterThanOrEqual(44);

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});
