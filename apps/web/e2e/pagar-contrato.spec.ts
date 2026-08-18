import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { semearSessao } from "./support/sessao";

/**
 * Contrato de QUERY STRING entre a tela e o FastAPI — o único lugar onde axios de verdade roda.
 *
 * ⚠️ **Por que este arquivo existe.** O filtro de status é uma LISTA, e o padrão do axios serializa
 * lista como `status[]=open&status[]=scheduled`. O FastAPI declara `status: list[str] | None =
 * Query(default=None)` e só reconhece a forma REPETIDA (`status=open&status=scheduled`); com
 * colchetes ele não vê parâmetro nenhum, devolve `None` e **ignora o filtro inteiro** — a tela
 * pediria "o que eu devo" e receberia pago e cancelado junto, sem erro, sem sintoma.
 *
 * Nenhuma das outras camadas pega isto: o pytest monta a URL crua na forma certa, o vitest assere
 * o objeto `params` ANTES de serializar, e o gate de layout recebe payload fixo seja qual for a
 * query. Só uma medição da URL real fecha essa fresta.
 */

test("o filtro de status vai na forma que o FastAPI lê (repetida, sem colchetes)", async ({
  page,
}) => {
  await semearSessao(page);
  await mockarApi(page, {
    "/payables/summary": {
      open_cents: 0, overdue_cents: 0, week_cents: 0,
      month_cents: 0, paid_month_cents: 0, scheduled_cents: 0,
    },
    "/payables/bills": { items: [], total: 0 },
    "/payables/receipts": [],
    "/chart-of-accounts": [],
    "/cost-centers": [],
  });

  const urls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/payables/bills")) urls.push(r.url());
  });

  await page.goto("/pagar");
  await expect(page.getByLabel("Status")).toBeVisible();
  await expect.poll(() => urls.length).toBeGreaterThan(0);

  const query = decodeURIComponent(new URL(urls[0]).search);
  expect(query, `query real: ${query}`).toContain("status=open");
  expect(query, `query real: ${query}`).toContain("status=scheduled");
  expect(query, "colchete = o FastAPI ignora o filtro em silêncio").not.toContain("status[]");
  expect(query, "índice = o FastAPI ignora o filtro em silêncio").not.toContain("status[0]");
});
