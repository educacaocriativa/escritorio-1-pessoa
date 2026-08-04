import type { Charge } from "@e1p/shared-types";

/**
 * **A rota do dinheiro de uma cobrança — DERIVADA, nunca persistida** (Story 8.15, AC4).
 *
 * > `"trilho"` se `transaction_id` estiver preenchido; `"banco"` se for o `bank_account_id`.
 *
 * ⚠️ **Não existe (nem deve existir) coluna nem campo `payment_route`.** A rota é uma leitura dos
 * dois ponteiros que a INVARIANTE DO TRILHO já mantém mutuamente exclusivos; um rótulo separado
 * pode divergir do fato e vira a terceira fonte de verdade sobre por onde o dinheiro entrou — a
 * lição D-3, aplicada preventivamente. Há um gate de AST no backend
 * (`test_money_planes.py::test_origin_type_e_payment_route_nao_existem`) reprovando a coluna; este
 * arquivo é o motivo de ela não ser necessária.
 *
 * `null` quando a cobrança não foi liquidada (em aberto, cancelada): não há rota a exibir, e
 * inventar uma seria afirmar que houve dinheiro.
 */
export type RotaDaCobranca = "trilho" | "banco";

export function rotaDaCobranca(c: {
  transaction_id: string | null;
  bank_account_id: string | null;
}): RotaDaCobranca | null {
  if (c.transaction_id) return "trilho";
  if (c.bank_account_id) return "banco";
  return null;
}

/**
 * O dia do crédito como **data de calendário**, `dd/mm`.
 *
 * ⚠️ `paid_at` é a meia-noite **UTC** da data informada. `new Date(paid_at).toLocaleDateString()`
 * mostraria o **dia anterior** em qualquer fuso negativo (o Brasil inteiro) — é exatamente o bug
 * de fuso da Agenda (`CLAUDE.md` §6.0: *"toda data de negócio deve ser comparada/exibida por data
 * de calendário, nunca por horário local"*). Mesmo helper de `PagarPage.diaDoDebito`.
 */
export function diaDoCredito(paidAt: string | null): string {
  if (!paidAt) return "";
  const [, mes, dia] = paidAt.slice(0, 10).split("-");
  return dia && mes ? `${dia}/${mes}` : "";
}

/** O rótulo curto da rota, para a linha da lista. `null` quando não há rota (nada a dizer). */
export function rotuloDaRota(c: Charge, nomeDaConta: (id: string) => string): string | null {
  const rota = rotaDaCobranca(c);
  if (rota === null) return null;
  // ⚠️ O lado do trilho NÃO ganha rótulo na tela de Cobranças: ali "Recebido" já é a leitura certa,
  // e nomear "trilho" exporia ao dono um vocabulário interno da plataforma sem nenhum ganho. O que
  // ele precisa saber é **onde o dinheiro caiu quando não foi pelo e1p**.
  if (rota === "trilho") return null;
  const conta = c.bank_account_id ? nomeDaConta(c.bank_account_id) : "";
  const dia = diaDoCredito(c.paid_at);
  if (conta && dia) return `caiu no ${conta} em ${dia}`;
  if (conta) return `caiu no ${conta}`;
  return "recebido direto na conta";
}
