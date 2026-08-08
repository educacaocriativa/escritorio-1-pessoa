/**
 * Contas de investimento (Story 5.6) — tipos + helpers PUROS de formatação.
 *
 * A lógica de formatação vive aqui (pura, testável) porque o projeto não tem infra de teste de
 * componente React — mesmo padrão de planoContas.ts / dre.ts. A InvestimentosPage consome estes
 * tipos e helpers.
 *
 * O rendimento (juro) é lançado como receita no grupo FINANCEIRO do plano de contas e entra na DRE
 * — NÃO é venda com split de Carteira (por isso a tela usa o seletor de contas FINANCEIRO do plano
 * de contas, não o fluxo de cobrança normal).
 */
import type { BankAccount } from "./contas";
import { formatBRL } from "./dre";

export { formatBRL };

/** Tipos de aplicação SUGERIDOS na UI (texto livre — o backend não valida contra lista fechada). */
export const SUGGESTED_KINDS = ["CDB", "Tesouro", "Fundo", "Poupança", "LCI/LCA", "Ações"] as const;

export interface InvestmentAccount {
  id: string;
  name: string;
  kind: string;
  index_rate_label: string;
  principal_cents: number;
  accrued_yield_cents: number;
  opened_at: string;
  created_at: string;
  /**
   * Onda 2b-i — a conta bancária ONDE ESTE DINHEIRO ESTÁ (`kind='investment'`), 1:1.
   * `null` = ainda não vinculada, e nesse estado o backend recusa o rendimento com **409
   * acionável** (`detail.acao === "cadastrar_conta"`): rendimento sem perna bancária é o termo P3
   * da pré-condição do gate do Epic 8.
   */
  bank_account_id: string | null;
}

export interface Rentability {
  account_id: string;
  principal_cents: number;
  accrued_yield_cents: number;
  total_rentability_pct: number | null;
  period_rentability_pct: number | null;
  period_yield_cents: number;
  start: string | null;
  end: string | null;
}

/**
 * Formata uma rentabilidade (fração, ex.: 0.055 → "5,50%"). `null` (principal 0 → divisão evitada)
 * vira "—" para não exibir "NaN%" ao usuário.
 */
export function formatPct(fraction: number | null): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "—";
  return (fraction * 100).toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) + "%";
}

// ── Onda 2b-i: o vínculo da aplicação com a conta bancária dela ─────────────────────────────

/** A ação que o rótulo mostra quando não há vínculo. Uma redação, um lugar. */
export const VINCULAR_LABEL = "Vincular a uma conta";

/**
 * As contas que PODEM receber o vínculo: `kind='investment'` e não arquivadas. PURA.
 *
 * Oferecer uma conta corrente levaria o dono a creditar o rendimento onde o dinheiro não está —
 * e o backend recusaria com 422 **depois** de ele já ter escolhido. Filtrar aqui é o que impede
 * a escolha errada de existir.
 */
export function contasDeAplicacao(contas: BankAccount[]): BankAccount[] {
  return contas.filter((c) => c.kind === "investment" && c.archived_at === null);
}

/**
 * Rótulo do vínculo da aplicação com a conta bancária dela. PURA.
 *
 * Sem vínculo — ou com vínculo apontando para conta que sumiu da lista — devolve a **AÇÃO**, nunca
 * um estado passivo tipo "sem conta": é este vínculo que o 409 de `register_yield` pede, e um
 * rótulo que só descreve o problema deixa o dono sabendo do problema e não do caminho.
 */
export function rotuloDoVinculo(account: InvestmentAccount, contas: BankAccount[]): string {
  const conta = contas.find((c) => c.id === account.bank_account_id);
  return conta ? conta.name : VINCULAR_LABEL;
}
