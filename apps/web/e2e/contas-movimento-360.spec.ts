import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * Os três modais que faltavam da `ContasSaldosPage` (#130): "Transferir entre contas",
 * "Editar movimento" e "Ignorar movimento".
 *
 * ⚠️ **O controle positivo destes três é OUTRO.** Os títulos aqui são CONSTANTES, então remover
 * `min-w-0 break-words` do `Modal.tsx` — o defeito do #119 — **não** os deixa vermelhos: não há
 * palavra do dono no `<h2>` para não caber. Medido, não suposto (é o mesmo caso do `AccountModal`).
 * O que estes precisam provar é a outra metade do #119: que a região excluída **por construção**
 * pelo recorte antigo — o cabeçalho — está DENTRO da conta. Por isso a isca é plantada nele.
 *
 * O texto livre do dono chega aqui por outro caminho, e ele é medido de verdade:
 *  - "Transferir": o nome das contas nos dois `<select>` (`Sai de` / `Entra em`);
 *  - "Editar movimento": a `raw_description`, que vem do BANCO e chega COLADA
 *    ("PIXENVIADOCPF12345678900…") — o pior caso plausível não precisa ser inventado, é o formato
 *    nativo do extrato.
 *
 * A varredura é recortada pela CAIXA (`testId` do `Modal`), nunca pelo conteúdo.
 */

// Pior caso PLAUSÍVEL (§5.1): nome de conta sem espaço, hífen ou barra, dentro dos 120 chars que
// `bank/schemas.py` aceita.
const NOME_A = "ContaCorrentePrincipalBancoCooperativoSicrediAgencia1234DaEmpresaME";
const NOME_B = "ContaPoupancaDaReservaDeEmergenciaBancoNubankPagamentosSA";

// Como o extrato REALMENTE chega: sem um único espaço em 96 chars. Não é `lorem ipsum` — é a
// descrição que o banco escreve, e é ela que este modal exibe num `<p>` sem largura própria.
const DESCRICAO_DO_BANCO =
  "PIXENVIADOCPF12345678900JOAODASILVAPEREIRAFORNECEDORAGENCIA0001CONTA1234567BANCO341";

const conta = (id: string, name: string, principal: boolean) => ({
  id,
  name,
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
  is_primary: principal,
  archived_at: null,
  saldo_derivado_cents: 12845079,
  saldo_derivado_origem: "banco",
  agendado_saida_cents: 1238000,
  agendado_entrada_cents: 0,
  agendado_origem: "banco",
  created_at: "2026-01-01T10:00:00Z",
});

const CONTA_A = conta("00000000-0000-4000-8000-000000000001", NOME_A, true);
const CONTA_B = conta("00000000-0000-4000-8000-000000000002", NOME_B, false);

// `source: "manual"` NÃO é detalhe de fixture: `podeEditarOsFatosDoMovimento` esconde "Editar" e
// "Ignorar" em movimento de origem do sistema (`contas.ts`), e com `source: "transfer"` a linha
// nasceria sem os botões que este spec precisa clicar.
const MOVIMENTO = {
  id: "00000000-0000-4000-8000-000000000030",
  bank_account_id: CONTA_A.id,
  posted_at: "2026-08-14",
  amount_cents: -128450,
  raw_description: DESCRICAO_DO_BANCO,
  user_description: "",
  description: DESCRICAO_DO_BANCO,
  counterparty_name: "João da Silva Pereira",
  counterparty_document: "123.456.789-00",
  operation_nature: null,
  source: "manual",
  transfer_id: null,
  status: "unmatched",
  ignored_reason: "",
  created_at: "2026-08-14T10:00:00Z",
  updated_at: "2026-08-14T10:00:00Z",
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  // Chave por conta: `/bank/accounts` sozinha engoliria `/bank/accounts/{id}/checkpoints` e o
  // cartão leria uma LISTA DE CONTAS como se fosse checkpoint (ver `support/api.ts`).
  await mockarApi(page, {
    "/bank/accounts": [CONTA_A, CONTA_B],
    [`/bank/accounts/${CONTA_A.id}/checkpoints`]: [],
    [`/bank/accounts/${CONTA_B.id}/checkpoints`]: [],
    "/bank/transactions": [MOVIMENTO],
    "/bank/transfers": [],
  });
  await page.goto("/financeiro/contas");
});

/**
 * Abre o painel de movimentos da primeira conta — é de lá que saem "Editar" e "Ignorar".
 *
 * O escopo é a TABELA de propósito: o cartão da conta tem o seu próprio "Editar" (que abre o
 * cadastro), e com duas contas na tela são três botões com esse nome. Sem o recorte, o teste
 * abriria o modal errado e mediria uma tela que não é a que ele diz medir.
 */
async function abrirMovimentosDaPrimeiraConta(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: "Ver movimentos" }).first().click();
  await expect(acaoDoMovimento(page, "Editar")).toBeVisible();
}

const acaoDoMovimento = (page: import("@playwright/test").Page, nome: "Editar" | "Ignorar") =>
  page.getByRole("table").getByRole("button", { name: nome, exact: true });

/**
 * A TABELA de movimentos aberta, sem nenhum modal por cima (#135).
 *
 * Esta asserção parece redundante com as dos modais abaixo — e não é. Os 879px do #130 foram
 * medidos por ACASO: quem media o "Editar movimento" viu a PÁGINA rolar e foi atrás. A causa nunca
 * esteve no modal; está nesta tabela, no rótulo `sr-only` da coluna Valor, que é `position:
 * absolute` SEM offsets — logo ancorado na sua posição estática, lá dentro do deslizador de
 * `min-w-[40rem]`. Sem `relative` no deslizador, o bloco contêiner dele passa a ser a PÁGINA: o
 * rótulo escapa do recorte e conta no `scrollWidth` do documento.
 *
 * Enquanto a única testemunha for um modal, a cobertura depende de o modal continuar existindo e
 * de alguém continuar medindo a página inteira lá dentro — duas coisas que um refactor apaga sem
 * aviso, e o defeito volta invisível (é `sr-only`: nenhuma inspeção visual o denuncia). Aqui a
 * asserção fica onde a causa mora.
 */
test("a tabela de movimentos aberta não faz a PÁGINA rolar de lado", async ({ page }) => {
  await abrirMovimentosDaPrimeiraConta(page);

  // Nenhum modal aberto: o que estiver medindo é a tabela, e só ela.
  await expect(page.getByTestId("modal-editar-movimento")).toHaveCount(0);

  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("o 'Transferir entre contas' cabe em 360px, com nome de conta do dono nos seletores", async ({
  page,
}) => {
  await page.getByRole("button", { name: /transferir/i }).first().click();
  const caixa = page.getByTestId("modal-transferir");
  await expect(caixa).toBeVisible();

  const fechar = await caixa.getByRole("button", { name: /fechar/i }).boundingBox();
  expect(fechar).not.toBeNull();
  expect(fechar!.x).toBeGreaterThanOrEqual(0);
  expect(fechar!.x + fechar!.width).toBeLessThanOrEqual(360);

  expect(await textoForaDaTela(page, '[data-testid="modal-transferir"]')).toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("o 'Editar movimento' cabe em 360px com a descrição COLADA que o banco manda", async ({
  page,
}) => {
  await abrirMovimentosDaPrimeiraConta(page);
  await acaoDoMovimento(page, "Editar").click();
  const caixa = page.getByTestId("modal-editar-movimento");
  await expect(caixa).toBeVisible();

  const fechar = await caixa.getByRole("button", { name: /fechar/i }).boundingBox();
  expect(fechar).not.toBeNull();
  expect(fechar!.x + fechar!.width).toBeLessThanOrEqual(360);

  // A `raw_description` é exibida num `<p>` SEM largura própria: a caixa não cresce, a tinta vaza.
  // `getBoundingClientRect` não vê tinta — `textoForaDaTela` vê, pelo `scrollWidth` (§ da régua).
  expect(await textoForaDaTela(page, '[data-testid="modal-editar-movimento"]')).toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("o 'Ignorar movimento' cabe em 360px", async ({ page }) => {
  await abrirMovimentosDaPrimeiraConta(page);
  await acaoDoMovimento(page, "Ignorar").click();
  const caixa = page.getByTestId("modal-ignorar-movimento");
  await expect(caixa).toBeVisible();

  const fechar = await caixa.getByRole("button", { name: /fechar/i }).boundingBox();
  expect(fechar).not.toBeNull();
  expect(fechar!.x + fechar!.width).toBeLessThanOrEqual(360);

  expect(await textoForaDaTela(page, '[data-testid="modal-ignorar-movimento"]')).toEqual([]);
  expect((await medirPagina(page)).larguraDaPagina).toBe(360);
});

test("a régua enxerga uma isca plantada no CABEÇALHO de cada um dos três", async ({ page }) => {
  // O controle positivo destes três, e ele é o do `AccountModal`, não o do `agenda-evento`: com
  // título constante a mutação do `min-w-0` não os deixa vermelhos, então o que se prova aqui é
  // que o cabeçalho — a região que o recorte no `children` excluía por construção — está DENTRO
  // da conta. Uma varredura que devolve `[]` não distingue "nada vaza" de "nada foi medido".
  const plantarEMedir = async (testId: string) => {
    await page.getByTestId(testId).evaluate((box) => {
      const isca = document.createElement("p");
      isca.textContent = "x".repeat(120);
      box.querySelector("h2")?.after(isca);
    });
    const cortes = await textoForaDaTela(page, `[data-testid="${testId}"]`);
    return cortes.filter((c) => c.texto.startsWith("x"));
  };

  await page.getByRole("button", { name: /transferir/i }).first().click();
  await expect(page.getByTestId("modal-transferir")).toBeVisible();
  expect(await plantarEMedir("modal-transferir")).toHaveLength(1);
  await page.getByTestId("modal-transferir").getByRole("button", { name: /fechar/i }).click();

  await abrirMovimentosDaPrimeiraConta(page);

  await acaoDoMovimento(page, "Editar").click();
  await expect(page.getByTestId("modal-editar-movimento")).toBeVisible();
  expect(await plantarEMedir("modal-editar-movimento")).toHaveLength(1);
  await page.getByTestId("modal-editar-movimento").getByRole("button", { name: /fechar/i }).click();

  await acaoDoMovimento(page, "Ignorar").click();
  await expect(page.getByTestId("modal-ignorar-movimento")).toBeVisible();
  expect(await plantarEMedir("modal-ignorar-movimento")).toHaveLength(1);
});
