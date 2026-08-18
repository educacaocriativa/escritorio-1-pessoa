import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { alvosPequenos, medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * Gate de LAYOUT da tela de Contas a Pagar em 360px (spec 2026-08-18).
 *
 * A tela ganhou uma superfície nova — a barra de recorte, com cinco controles — e um rodapé de
 * contagem. Cinco controles numa linha de 360px é exatamente a forma que se espreme até o polegar
 * não acertar nenhum, e nenhuma asserção de classe CSS pega isso: `toContain("flex-wrap")` já
 * passou verde neste projeto com a tela quebrada.
 *
 * Payload de pior caso plausível: fornecedor comprido, valor de 6 dígitos, e centros/categorias
 * com nomes longos — porque dado curto sempre cabe, e medir com ele é medir uma tela que não
 * existe.
 */

const CONTA = {
  id: "b-1",
  tenant_id: "00000000-0000-4000-8000-000000000002",
  description: "Assinatura anual da plataforma de inteligência",
  category: "Ferramentas",
  supplier: "Fornecedor Internacional de Tecnologia Ltda",
  amount_cents: 118_573_04,
  due_date: "2026-09-20",
  competence_date: null,
  chart_account_id: null,
  contract_id: null,
  cost_center_id: null,
  status: "open",
  is_overdue: false,
  paid_at: null,
  recurrence: "monthly",
  recurrence_count: 12,
  recurrence_group: "g-1",
  payment_code: "",
  attachment_url: "",
  created_at: "2026-01-01T00:00:00Z",
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/payables/summary": {
      open_cents: 18_575_704,
      overdue_cents: 0,
      week_cents: 1_800_000,
      month_cents: 18_575_704,
      paid_month_cents: 562_541,
      scheduled_cents: 0,
    },
    "/payables/bills": { items: [CONTA], total: 213 },
    "/payables/receipts": [],
    "/chart-of-accounts": [
      { id: "ca-1", categoria: "Ferramentas e assinaturas de software", grupo: "DESPESA" },
    ],
    "/cost-centers": [{ id: "cc-1", name: "Técnica e Infraestrutura" }],
  });
});

test("a barra de recorte reflui e a página não rola de lado", async ({ page }) => {
  await page.goto("/pagar");
  await expect(page.getByLabel("Buscar fornecedor ou descrição")).toBeVisible();

  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);

  // A tabela rola de lado por construção (`min-w-[48rem]` dentro de `overflow-x-auto`), então o
  // recorte é a barra: ali NADA pode sobrar, porque ela não tem deslizador nenhum.
  const cortes = await textoForaDaTela(page, "[data-testid='filtros-da-lista']");
  expect(cortes, JSON.stringify(cortes, null, 2)).toEqual([]);
});

test("cada controle do recorte cabe na tela e é tocável", async ({ page }) => {
  await page.goto("/pagar");
  await expect(page.getByLabel("Status")).toBeVisible();

  for (const rotulo of ["Buscar fornecedor ou descrição", "Status", "Vencimento até"]) {
    const caixa = await page.getByLabel(rotulo).boundingBox();
    expect(caixa, `${rotulo} sem caixa`).not.toBeNull();
    expect(caixa!.x, `${rotulo} começa fora da tela`).toBeGreaterThanOrEqual(0);
    expect(caixa!.x + caixa!.width, `${rotulo} estoura os 360px`).toBeLessThanOrEqual(360);
    expect(caixa!.height, `${rotulo} baixo demais para o polegar`).toBeGreaterThanOrEqual(44);
  }

  const pequenos = await alvosPequenos(page, 44, "[data-testid='filtros-da-lista']");
  expect(pequenos, JSON.stringify(pequenos, null, 2)).toEqual([]);
});

test("as dimensões extras existem, atrás de 'Mais filtros' no celular", async ({ page }) => {
  await page.goto("/pagar");
  await expect(page.getByLabel("Status")).toBeVisible();

  // Recolhidas por padrão em 360px — é o que devolve a dobra para a lista.
  await expect(page.getByLabel("Centro de custo")).toBeHidden();

  await page.getByRole("button", { name: "Mais filtros" }).click();

  await expect(page.getByLabel("Centro de custo")).toBeVisible();
  await expect(page.getByLabel("Categoria")).toBeVisible();
});

test("a contagem aparece e a lista começa dentro da primeira dobra", async ({ page }) => {
  await page.goto("/pagar");

  await expect(page.getByText(/Mostrando 1 de 213/i)).toBeVisible();

  const tabela = await page.locator("table").boundingBox();
  expect(tabela, "tabela sem caixa").not.toBeNull();
  // A lista é o motivo de a página existir. Com o GanchoDaVima acima do título ela nascia abaixo
  // da dobra; ele desceu para depois da tabela justamente por isso.
  expect(tabela!.y, "a tabela nasce abaixo da dobra de 740px").toBeLessThan(740);
});
