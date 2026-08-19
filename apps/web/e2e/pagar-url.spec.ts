import { expect, type Page, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { semearSessao } from "./support/sessao";

/**
 * O recorte de Contas a Pagar na BARRA DE ENDEREÇO — link compartilhável e botão "voltar" (#138).
 *
 * ⚠️ **Por que este arquivo existe, e por que ele é Playwright e não vitest.** As outras camadas
 * são cegas à URL: o pytest monta a query crua já na forma certa, o vitest assere o objeto antes de
 * qualquer navegação, e o mock do gate de layout devolve payload fixo seja qual for a query. Um
 * teste que só olhasse o estado de React passaria com a barra de endereço VAZIA — que era
 * exatamente o defeito (`/pagar?q=anthropic` inerte). A mesma fresta escondeu o `status[]` até o
 * #125. Aqui o navegador de verdade navega, e o histórico de verdade empilha.
 *
 * Segue o precedente do `busca-url.spec.ts`: rede mockada por `page.route`, asserções sobre a query
 * string REAL que saiu no request.
 */

const BASE = {
  tenant_id: "00000000-0000-4000-8000-000000000002",
  category: "Ferramentas",
  supplier: "Fornecedor Internacional de Tecnologia Ltda",
  amount_cents: 118_573_04,
  competence_date: null,
  chart_account_id: null,
  contract_id: null,
  cost_center_id: null,
  is_overdue: false,
  paid_at: null,
  recurrence: "none",
  recurrence_count: 0,
  recurrence_group: null,
  payment_code: "",
  attachment_url: "",
  created_at: "2026-01-01T00:00:00Z",
};

/** Uma conta por status, com descrições DISTINTAS: é a descrição que a medição procura na tela. */
const CONTAS = [
  { ...BASE, id: "b-open", description: "Conta ABERTA", due_date: "2026-09-20", status: "open" },
  {
    ...BASE,
    id: "b-sched",
    description: "Conta AGENDADA",
    due_date: "2026-09-21",
    status: "scheduled",
  },
  {
    ...BASE,
    id: "b-paid",
    description: "Conta PAGA",
    due_date: "2026-08-10",
    status: "paid",
    paid_at: "2026-08-10T12:00:00Z",
  },
  {
    ...BASE,
    id: "b-canc",
    description: "Conta CANCELADA",
    due_date: "2026-09-22",
    status: "canceled",
  },
];

/**
 * Rede mockada que **obedece à query string**, em vez de devolver payload fixo.
 *
 * É essa obediência que transforma "a lista mostra pagas" numa medição de ponta a ponta: URL →
 * hidratação → `paraQuery` → request → lista renderizada. Com payload fixo, a linha "Conta PAGA"
 * apareceria mesmo se a hidratação não existisse, e o teste seria decorativo.
 *
 * A rota específica é registrada DEPOIS de `mockarApi` de propósito: no Playwright o handler mais
 * recente vence, então esta ganha da rota-curinga para `/payables/bills`.
 */
async function mockarPagar(page: Page): Promise<string[]> {
  await mockarApi(page, {
    "/payables/summary": {
      open_cents: 18_575_704,
      overdue_cents: 0,
      week_cents: 1_800_000,
      month_cents: 18_575_704,
      paid_month_cents: 562_541,
      scheduled_cents: 0,
    },
    "/payables/receipts": [],
    "/chart-of-accounts": [{ id: "ca-1", categoria: "Ferramentas", grupo: "DESPESA" }],
    "/cost-centers": [{ id: "cc-1", name: "Técnica e Infraestrutura" }],
  });

  const urls: string[] = [];
  await page.route("**/api/payables/bills*", async (route) => {
    const url = new URL(route.request().url());
    urls.push(url.search);
    const pedidos = url.searchParams.getAll("status");
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const itens = CONTAS.filter(
      (c) =>
        (pedidos.length === 0 || pedidos.includes(c.status)) &&
        (q === "" || c.description.toLowerCase().includes(q)),
    );
    await route.fulfill({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({ items: itens, total: itens.length }),
    });
  });
  return urls;
}

/** A última query que a lista realmente pediu ao servidor. */
const ultima = (urls: string[]) => decodeURIComponent(urls[urls.length - 1] ?? "");

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
});

test("/pagar?status=paid abre FILTRADO: a lista vem com pagas, e só", async ({ page }) => {
  const urls = await mockarPagar(page);
  await page.goto("/pagar?status=paid");

  // O que o dono vê. Era isto que não acontecia: o endereço parecia filtrar e não filtrava.
  await expect(page.getByText("Conta PAGA")).toBeVisible();
  await expect(page.getByText("Conta ABERTA")).toHaveCount(0);

  // E o que saiu no fio — o recorte do endereço chegou ao servidor, sem herdar o padrão.
  const query = ultima(urls);
  expect(query, `query real: ${query}`).toContain("status=paid");
  expect(query, `query real: ${query}`).not.toContain("status=open");
  expect(query, "colchete = o FastAPI ignora o parâmetro em silêncio (#125)").not.toContain("[]");

  // O controle da tela mostra o recorte do endereço, não o padrão.
  await expect(page.getByLabel("Status")).toHaveValue("paid");
});

test("o `status` da URL é REPETÍVEL: dois recortes chegam os dois", async ({ page }) => {
  const urls = await mockarPagar(page);
  await page.goto("/pagar?status=open&status=canceled");

  // Ler só o primeiro `status` devolveria uma lista sem canceladas, silenciosamente.
  await expect(page.getByText("Conta ABERTA")).toBeVisible();
  await expect(page.getByText("Conta CANCELADA")).toBeVisible();
  await expect(page.getByText("Conta PAGA")).toHaveCount(0);

  const query = ultima(urls);
  expect(query, `query real: ${query}`).toContain("status=open");
  expect(query, `query real: ${query}`).toContain("status=canceled");
});

test("sem query, abre no padrão de 'o que eu devo' — os DOIS status, sem colchete", async ({
  page,
}) => {
  const urls = await mockarPagar(page);
  await page.goto("/pagar");

  await expect(page.getByText("Conta ABERTA")).toBeVisible();
  await expect(page.getByText("Conta AGENDADA")).toBeVisible();

  const query = ultima(urls);
  expect(query, `query real: ${query}`).toContain("status=open");
  expect(query, `query real: ${query}`).toContain("status=scheduled");
  expect(query, `query real: ${query}`).not.toContain("[]");

  // URL vazia é o filtro padrão: escrever o default de volta seria poluição no endereço.
  expect(new URL(page.url()).search).toBe("");
});

test("`?q=` filtra de verdade — o link com texto não é mais inerte", async ({ page }) => {
  const urls = await mockarPagar(page);
  // O termo recorta DENTRO do status padrão (aberta + agendada): as duas contas caberiam, e é o
  // `q` que decide. Um termo que casasse só com uma paga seria cortado pelo status e o teste
  // passaria verde sem o `q` ter feito nada.
  await page.goto("/pagar?q=ABERTA");

  await expect(page.getByText("Conta ABERTA")).toBeVisible();
  await expect(page.getByText("Conta AGENDADA")).toHaveCount(0);
  expect(ultima(urls), `query real: ${ultima(urls)}`).toContain("q=ABERTA");
  await expect(page.getByLabel("Buscar fornecedor ou descrição")).toHaveValue("ABERTA");
});

test("trocar o status ESCREVE na URL, e o botão voltar devolve o recorte anterior", async ({
  page,
}) => {
  const urls = await mockarPagar(page);
  await page.goto("/pagar");
  await expect(page.getByText("Conta ABERTA")).toBeVisible();

  await page.getByLabel("Status").selectOption("paid");

  // 1. O recorte foi para o endereço — é o que se manda por WhatsApp e vira favorito.
  await expect.poll(() => new URL(page.url()).searchParams.getAll("status")).toEqual(["paid"]);
  await expect(page.getByText("Conta PAGA")).toBeVisible();
  await expect(page.getByText("Conta ABERTA")).toHaveCount(0);

  // 2. E criou entrada no histórico: "voltar" desfaz o FILTRO, não sai da tela.
  await page.goBack();

  await expect(page.getByText("Conta ABERTA")).toBeVisible();
  await expect(page.getByText("Conta PAGA")).toHaveCount(0);
  expect(new URL(page.url()).pathname, "voltar saiu da tela inteira").toBe("/pagar");
  expect(new URL(page.url()).search).toBe("");
  // A lista foi REBUSCADA no recorte anterior, não só repintada com dado velho.
  const query = ultima(urls);
  expect(query, `query real: ${query}`).toContain("status=open");
});

test("digitar no texto REESCREVE a URL: um voltar não desfaz letra por letra", async ({ page }) => {
  await mockarPagar(page);
  await page.goto("/pagar"); // histórico: [padrão]
  await expect(page.getByText("Conta ABERTA")).toBeVisible();

  await page.getByLabel("Status").selectOption("paid"); // EMPILHA: [padrão, ?status=paid]
  await expect.poll(() => new URL(page.url()).searchParams.get("status")).toBe("paid");

  // Nove teclas. Com `push` seriam nove entradas de histórico, e sair de «anthropic» custaria
  // nove cliques em "voltar".
  await page
    .getByLabel("Buscar fornecedor ou descrição")
    .pressSequentially("anthropic", { delay: 30 });
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("anthropic");
  await expect(page.getByLabel("Buscar fornecedor ou descrição")).toHaveValue("anthropic");

  // UM voltar tem de pular a digitação inteira e cair no estado ANTERIOR ao `?status=paid`.
  // Se o texto empilhasse, este voltar devolveria «anthropi» — ou seja, o `status` ainda estaria
  // no endereço e o `q` teria perdido só a última letra.
  await page.goBack();

  await expect.poll(() => new URL(page.url()).search).toBe("");
  await expect(page.getByText("Conta ABERTA")).toBeVisible();
});
