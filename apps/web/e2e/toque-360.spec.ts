import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina } from "./support/medidas";
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
