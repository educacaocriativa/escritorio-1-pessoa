import { formatDay } from "../../lib/datetime";

// Mesmo padrão de toda página do app (`AgendaPage`, `CobrancasPage`, `EstoquePage`, `CockpitPage`
// …): cada uma define o seu. **Não** importe o `brl` exportado por `FinanceiroPage.tsx` — ela
// importa este componente, e o ciclo quebraria o build. Unificar os ~8 `brl` do repo num helper
// compartilhado é refactor legítimo, e não é desta onda.
const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export type Payout = {
  id: string;
  amount_cents: number;
  paid_on: string;
  bank_account_id: string;
  bank_transaction_id: string;
};

/**
 * Os saques da Carteira — que antes da Onda 3 não existiam em lugar nenhum: o dono via o saldo
 * sumir e só tinha o audit log, que guardava o VALOR e não um id.
 *
 * **Lista, nunca tabela — e isso é normativo, não estético.** A lição medida na Onda 2b-ii: em
 * 360px uma tabela de 3 colunas não cabe, e a saída não é fazer a rolagem funcionar melhor, é não
 * precisar dela. O extrato daquela onda nasceu `<table>` com `min-w-[20rem]` dentro de
 * `overflow-x-auto` — o `overflow-x` estava CERTO, o `flex-wrap` estava CERTO, e a tela mostrava
 * `R$ 3.` no lugar de `R$ 3.000,00`. Nenhuma asserção de classe CSS pega isso; só medir com
 * `boundingBox` pega.
 *
 * Forma: data e conta empilhadas à esquerda num bloco `min-w-0` (que encolhe); valor à direita com
 * `whitespace-nowrap` (que não).
 */
export function PayoutHistory({
  payouts,
  accountNames,
}: {
  payouts: Payout[];
  accountNames: Record<string, string>;
}) {
  if (payouts.length === 0) {
    return (
      <p className="p-8 text-center text-sm text-neutral-400">
        Nenhum saque ainda. O que você sacar aparece aqui e no extrato da sua conta.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-neutral-100">
      {payouts.map((p) => (
        <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            {/*
              `formatDay` de `lib/datetime`, NUNCA `new Date(...)`: desde o PR #78 o sistema
              inteiro vive no fuso do tenant, e `new Date("2026-08-09")` é interpretado como UTC —
              o saque do dia 9 apareceria como dia 8 para quem está em GMT-3. UTC cru é regressão.
            */}
            <p className="truncate text-sm text-neutral-800">{formatDay(p.paid_on)}</p>
            <p className="truncate text-xs text-neutral-400">
              {accountNames[p.bank_account_id] ?? "Conta removida"}
            </p>
          </div>
          <span className="whitespace-nowrap text-sm font-semibold text-neutral-800">
            {brl(p.amount_cents)}
          </span>
        </li>
      ))}
    </ul>
  );
}
