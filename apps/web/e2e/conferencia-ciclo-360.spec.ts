import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O ciclo da conferência em 360px (Epic 8).
 *
 * A tela ganhou duas superfícies novas — o `CicloCard`, que enquadra tudo, e o histórico mês a mês
 * — e as duas carregam DINHEIRO. É exatamente a forma que a Onda 2b-ii pegou na primeira medição:
 * um extrato de 3 colunas mostrava `R$ 3.` no lugar de `R$ 3.000,00`, com o `overflow-x` correto e
 * o `flex-wrap` correto. **Nenhuma asserção de classe CSS pegaria aquilo**, e é por isso que o
 * histórico nasceu `<ul>` em vez de `<table>` e é medido aqui.
 *
 * Os payloads são de pior caso plausível: valor de 6 dígitos no volume, motivo longo com dois
 * nomes de conta, e um ciclo dormente (volume zero) — que é o caso em que o denominador PRECISA
 * aparecer, porque é ele que diz que aquele mês não prova nada.
 */

const CICLOS = {
  ciclos: [
    {
      ano_mes: "2026-11", start: "2026-11-01", end: "2026-11-30",
      fechado: false, legivel: false, motivo_nao_legivel: null,
      total_divergencia_cents: null, contas_avaliadas: 0, contas_sem_checkpoint: 3,
      movimentos_no_periodo: 2, valor_movimentado_cents: 45_000,
    },
    {
      ano_mes: "2026-10", start: "2026-10-01", end: "2026-10-31",
      fechado: true, legivel: true, motivo_nao_legivel: null,
      total_divergencia_cents: -1_234_500, contas_avaliadas: 3, contas_sem_checkpoint: 0,
      movimentos_no_periodo: 14, valor_movimentado_cents: 1_840_200,
    },
    {
      // O mês dormente: divergência zero e volume zero. O denominador é a informação.
      ano_mes: "2026-09", start: "2026-09-01", end: "2026-09-30",
      fechado: true, legivel: true, motivo_nao_legivel: null,
      total_divergencia_cents: 0, contas_avaliadas: 3, contas_sem_checkpoint: 0,
      movimentos_no_periodo: 0, valor_movimentado_cents: 0,
    },
    {
      ano_mes: "2026-08", start: "2026-08-01", end: "2026-08-31",
      fechado: true, legivel: false,
      motivo_nao_legivel:
        "Faltou o saldo informado das contas Poupança Banco do Brasil, Aplicação CDB Itaú neste " +
        "mês — sem ele o e1p não consegue conferir o mês inteiro.",
      total_divergencia_cents: 1_250_000, contas_avaliadas: 1, contas_sem_checkpoint: 2,
      movimentos_no_periodo: 9, valor_movimentado_cents: 2_310_000,
    },
  ],
};

const conta = (id: string, nome: string, divergencia: number) => ({
  bank_account_id: id, bank_account_name: nome, bank_account_kind: "checking",
  saldo_banco_cents: 2_500_000, saldo_banco_origem: "banco", saldo_banco_fonte: "manual",
  saldo_banco_data: "2026-10-31", saldo_sistema_cents: 2_500_000 - divergencia,
  saldo_sistema_origem: "banco", divergencia_cents: divergencia,
  dentro_da_tolerancia: Math.abs(divergencia) <= 12_500, tolerancia_cents: 12_500,
  dias_desde_ultima_conferencia: 3, movimentos_ignorados: 0,
  movimentos_no_periodo: 9, valor_movimentado_cents: 1_840_200, notes: [],
});

const RELATORIO = {
  start: "2026-10-01", end: "2026-10-31",
  contas: [
    conta("a1", "Itaú Empresas Conta Corrente", -1_234_500),
    conta("a2", "Poupança Banco do Brasil", 0),
    conta("a3", "Aplicação CDB Itaú", 3_700),
  ],
  total_divergencia_cents: -1_230_800, contas_avaliadas: 3, contas_sem_checkpoint: 0,
  contas_fora_da_banda: [
    {
      bank_account_id: "a1", bank_account_name: "Itaú Empresas Conta Corrente",
      divergencia_cents: -1_234_500, tolerancia_cents: 12_500,
    },
  ],
  notes: [],
  lancamentos_sem_conta_informada: 0, valor_sem_conta_informada_cents: 0,
  rendimentos_sem_perna_bancaria: 0, valor_rendimentos_sem_perna_cents: 0,
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  // ⚠️ A chave mais LONGA vence (ver `support/api.ts`): sem `/bank/reconciliation-cycles` a
  // prefixo-regra cairia em `/bank/reconciliation-report` e a tela receberia o relatório onde
  // espera `{ ciclos }`.
  await mockarApi(page, {
    "/bank/reconciliation-report": RELATORIO,
    "/bank/reconciliation-cycles": CICLOS,
  });
  await page.goto("/financeiro/conferencia");
  await expect(page.getByTestId("historico-de-ciclos")).toBeVisible();
});

test("a página não rola de lado", async ({ page }) => {
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);
});

test("nenhum valor do ciclo existe só depois de rolar de lado", async ({ page }) => {
  const cortes = await textoForaDaTela(page);
  // A `TabelaContas` é pré-existente e rola de propósito no próprio contêiner; o que esta frente
  // acrescentou não pode depender de rolagem para ser lido. Filtra pelo que está DENTRO das duas
  // superfícies novas.
  const alvos = await page.evaluate(() => {
    const dentro = (sel: string) =>
      [...(document.querySelector(sel)?.querySelectorAll("*") ?? [])]
        .filter((el) => el.children.length === 0 && (el.textContent ?? "").trim())
        .map((el) => (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 60));
    return [...dentro('[data-testid="ciclo-card"]'), ...dentro('[data-testid="historico-de-ciclos"]')];
  });
  const cortadosNoCiclo = cortes.filter((c) => alvos.includes(c.texto));
  expect(cortadosNoCiclo, JSON.stringify(cortadosNoCiclo, null, 2)).toEqual([]);
});

test("o valor movimentado aparece INTEIRO, não truncado", async ({ page }) => {
  // A lição da 2b-ii em uma asserção: `R$ 3.` no lugar de `R$ 3.000,00` passava por qualquer teste
  // de classe CSS. Aqui o número é lido do DOM renderizado, com o separador de milhar completo.
  const historico = page.getByTestId("historico-de-ciclos");
  await expect(historico).toContainText("18.402,00");
  await expect(historico).toContainText("23.100,00");
});

test("o denominador zero aparece por extenso — é ele que diz que o mês não prova nada", async ({
  page,
}) => {
  await expect(page.getByTestId("historico-de-ciclos")).toContainText("nenhum movimento no período");
});

test("a qualificação vem ANTES das frases por conta", async ({ page }) => {
  // Elemento separado da afirmação que ele qualifica é elemento que não é lido — o épico pagou
  // dois PRs de campo (#56, #58) por essa classe.
  const ordem = await page.evaluate(() => {
    const card = document.querySelector('[data-testid="ciclo-card"]');
    const frase = document.querySelector('[data-testid="frase-conta"]');
    if (!card || !frase) return null;
    return Boolean(card.compareDocumentPosition(frase) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(ordem).toBe(true);
});

test("o histórico é lista, nunca tabela", async ({ page }) => {
  // Em 360px uma tabela de 3 colunas não cabe, e a saída não é rolar melhor: é não precisar.
  // ESCOPADO — a página tem um `<table>` legítimo logo acima.
  const historico = page.getByTestId("historico-de-ciclos");
  await expect(historico.locator("table")).toHaveCount(0);
  await expect(historico.locator("ul")).toHaveCount(1);
});
