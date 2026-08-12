import type { Payable } from "@e1p/shared-types";

/**
 * **Duplicar uma conta a pagar** — a regra de o que a cópia leva, e como o vencimento avança.
 *
 * Pura, sem React e sem relógio: é a única parte desta funcionalidade com regra de verdade, e
 * mora aqui para ser testável sem DOM (mesmo recorte de `baixa.ts`, ao lado).
 *
 * ⚠️ **Nada aqui pode construir `Date`.** `due_date` é uma data de CALENDÁRIO, e
 * `new Date("2026-07-31")` é meia-noite UTC — em UTC−3 o `getDate()` devolve **30**, e a cópia
 * nasceria com o vencimento um dia antes, em silêncio, só para quem está a oeste de Greenwich.
 * Regra §6.0 do CLAUDE.md, e é aqui que ela morde. A aritmética é sobre inteiros fatiados da
 * string, exatamente como `diaDoDebito` e `lib/datetime.formatDay` já fazem.
 */

/** Os campos do formulário de "Nova conta a pagar", nos mesmos nomes que ele usa no estado. */
export interface CamposDaConta {
  description: string;
  supplier: string;
  chartAccountId: string;
  costCenterId: string;
  /** Valor como texto com vírgula ("200,00") — o formulário faz o parse na hora de gravar. */
  value: string;
  /** "YYYY-MM-DD". Vazio quando a origem não tem data legível. */
  dueDate: string;
  recurrence: string;
  recurrenceCount: string;
  paymentCode: string;
  contractId: string;
}

const DIAS_POR_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function bissexto(ano: number): boolean {
  return (ano % 4 === 0 && ano % 100 !== 0) || ano % 400 === 0;
}

/** Último dia de um mês 1-12. Fevereiro é o único que depende do ano. */
function ultimoDiaDoMes(ano: number, mes: number): number {
  if (mes === 2) return bissexto(ano) ? 29 : 28;
  return DIAS_POR_MES[mes - 1];
}

/**
 * "2026-07-31" → "2026-08-31"; "2026-01-31" → "2026-02-28" (o mês destino não tem 31).
 *
 * Aceita um instante ISO completo e usa só a parte da data. Entrada ilegível devolve `""`, para o
 * campo nascer vazio e o botão de gravar ficar desabilitado — melhor pedir a data do que inventar.
 */
export function proximoVencimento(ymd: string): string {
  const [a, m, d] = ymd.slice(0, 10).split("-").map(Number);
  if (!a || !m || !d || m < 1 || m > 12) return "";
  const ano = m === 12 ? a + 1 : a;
  const mes = m === 12 ? 1 : m + 1;
  const dia = Math.min(d, ultimoDiaDoMes(ano, mes));
  return `${ano}-${String(mes).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
}

/**
 * O que a cópia leva. Deliberadamente **fora**: anexos (o comprovante da conta antiga pendurado
 * numa conta ainda não paga seria evidência de um pagamento colada em outro) e a recorrência
 * (duplicar É a alternativa manual a ela — copiá-la faria um gesto gerar doze contas).
 *
 * O código Pix/boleto **é** copiado por decisão do fundador (§4.2 da spec), com o risco aceito:
 * um código do mês anterior fica na linha nova com cara de válido.
 */
export function camposDaCopia(bill: Payable): CamposDaConta {
  return {
    description: bill.description,
    supplier: bill.supplier,
    chartAccountId: bill.chart_account_id ?? "",
    costCenterId: bill.cost_center_id ?? "",
    contractId: bill.contract_id ?? "",
    paymentCode: bill.payment_code,
    value: (bill.amount_cents / 100).toFixed(2).replace(".", ","),
    dueDate: proximoVencimento(bill.due_date),
    recurrence: "none",
    recurrenceCount: "12",
  };
}
