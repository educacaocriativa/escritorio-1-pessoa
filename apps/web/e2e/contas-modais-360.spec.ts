import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * "Declarar saldo" e "Lançar movimento" em 360×740 — os outros dois modais de título DIGITADO.
 *
 * `ContasSaldosPage` monta os dois com `title={`Declarar saldo — ${account.name}`}` (e o gêmeo do
 * lançamento): o nome da conta é do dono e aceita **120 chars** (`bank/schemas.py`). É a mesma
 * exposição do #119 — o `<h2>` sem `min-w-0` é item de flex com `min-width: auto`, então diante de
 * uma palavra sem espaço ele CRESCE, leva a linha do cabeçalho junto e empurra o "Fechar" para
 * fora dos 360.
 *
 * ⚠️ A varredura é recortada pela CAIXA (`testId` do `Modal`), nunca pelo conteúdo: com o recorte
 * no `children`, cabeçalho e barra de ação ficam fora da conta e a medição devolve lista vazia com
 * o botão a centenas de pixels da tela — foi exatamente o que aconteceu no #119.
 *
 * A página em si já é medida por `toque-360.spec.ts` (alvo tocável) e `modal-conta-360.spec.ts`
 * (o cadastro de conta). O que faltava aqui, e é do #123, era medir o que esses dois ABREM.
 */

// Pior caso PLAUSÍVEL (§5.1): 76 chars sem espaço, hífen ou barra, dentro dos 120 que o backend
// aceita. Não é `lorem ipsum` — um lorem tem espaço sobrando e mediria uma tela que não existe.
const NOME_SEM_ESPACO =
  "ContaCorrentePrincipalBancoCooperativoSicrediAgencia1234ContaDaEmpresaME";

const CONTA = {
  id: "00000000-0000-4000-8000-000000000001",
  name: NOME_SEM_ESPACO,
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

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/bank/accounts": [CONTA],
    // Sem esta chave o prefixo `/bank/accounts` casaria e o cartão leria uma LISTA DE CONTAS como
    // se fosse um checkpoint — ver a nota em `support/api.ts`.
    [`/bank/accounts/${CONTA.id}/checkpoints`]: [],
    "/bank/transfers": [],
  });
  await page.goto("/financeiro/contas");
  await expect(page.getByRole("button", { name: "Declarar saldo" })).toBeVisible();
});

test("o nome digitado pelo dono não empurra o 'Fechar' do 'Declarar saldo' para fora", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Declarar saldo" }).click();
  const caixa = page.getByTestId("modal-declarar-saldo");
  await expect(caixa).toBeVisible();

  const fechar = await caixa.getByRole("button", { name: /fechar/i }).boundingBox();
  expect(fechar).not.toBeNull();
  expect(fechar!.x).toBeGreaterThanOrEqual(0);
  expect(fechar!.x + fechar!.width).toBeLessThanOrEqual(360);

  // O título quebra dentro da caixa em vez de esticá-la. Medido pela BORDA, não por `scrollWidth`:
  // o `<h2>` sem `min-w-0` cresce em vez de transbordar, e ali `scrollWidth === clientWidth`
  // continua verdadeiro com a tela quebrada (medido no `agenda-evento-360.spec.ts`).
  const daCaixa = await caixa.boundingBox();
  const titulo = await caixa.getByRole("heading").boundingBox();
  expect(titulo!.x + titulo!.width).toBeLessThanOrEqual(daCaixa!.x + daCaixa!.width + 0.5);

  // E nada da CAIXA — cabeçalho e barra de ação inclusive — existe só depois de rolar de lado.
  expect(await textoForaDaTela(page, '[data-testid="modal-declarar-saldo"]')).toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("o mesmo nome não empurra o 'Fechar' do 'Lançar movimento' para fora", async ({ page }) => {
  await page.getByRole("button", { name: "Lançar movimento" }).click();
  const caixa = page.getByTestId("modal-lancar-movimento");
  await expect(caixa).toBeVisible();

  const fechar = await caixa.getByRole("button", { name: /fechar/i }).boundingBox();
  expect(fechar).not.toBeNull();
  expect(fechar!.x + fechar!.width).toBeLessThanOrEqual(360);

  const daCaixa = await caixa.boundingBox();
  const titulo = await caixa.getByRole("heading").boundingBox();
  expect(titulo!.x + titulo!.width).toBeLessThanOrEqual(daCaixa!.x + daCaixa!.width + 0.5);

  expect(await textoForaDaTela(page, '[data-testid="modal-lancar-movimento"]')).toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("a régua enxerga um vazamento plantado no CABEÇALHO da caixa", async ({ page }) => {
  // Controle positivo, e é o ponto do #123: `[]` não distingue "nada vaza" de "nada foi medido".
  // A isca vai para o cabeçalho — a região que o recorte no `children` deixava de fora.
  await page.getByRole("button", { name: "Declarar saldo" }).click();
  const caixa = page.getByTestId("modal-declarar-saldo");
  await expect(caixa).toBeVisible();

  await caixa.evaluate((box) => {
    const isca = document.createElement("p");
    isca.textContent = "x".repeat(120);
    box.querySelector("h2")?.after(isca);
  });
  const cortes = await textoForaDaTela(page, '[data-testid="modal-declarar-saldo"]');
  expect(cortes.length).toBeGreaterThan(0);
  expect(cortes[0].forcaFora).toBeGreaterThan(0.5);
});
