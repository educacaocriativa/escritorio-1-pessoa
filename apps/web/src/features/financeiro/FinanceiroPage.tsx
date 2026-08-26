import type { Transaction, WalletSummary } from "@e1p/shared-types";
import { useCallback, useEffect, useMemo, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import { Link } from "react-router-dom";
import { PayoutHistory, type Payout } from "./PayoutHistory";
import ChartAccountSelect from "./ChartAccountSelect";
import type { CostCenter } from "./costCenters";
import CostCenterSelect from "./CostCenterSelect";
import { parseCentsBRL } from "./contas";
import { type ChartAccount, GRUPOS_DRE } from "./planoContas";
import { formatBRL } from "./dre";

/** Grupos DRE cabíveis numa venda da Carteira (é sempre receita, nunca despesa). */
const REVENUE_GROUPS = GRUPOS_DRE.filter((g) => g === "RECEITA");

const KINDS = [
  ["service", "Serviço"],
  ["product", "Produto"],
  ["recurring", "Recorrente"],
] as const;
const METHODS = [
  ["pix", "Pix"],
  ["card", "Cartão"],
  ["boleto", "Boleto"],
] as const;

const statusLabel: Record<Transaction["status"], string> = {
  available: "Disponível",
  pending: "A receber",
  withdrawn: "Sacado",
  refunded: "Estornado",
};

export default function FinanceiroPage() {
  const empty: WalletSummary = {
    available_cents: 0,
    pending_cents: 0,
    withdrawn_cents: 0,
    gross_total_cents: 0,
    fees_total_cents: 0,
  };
  const [summary, setSummary] = useState<WalletSummary>(empty);
  const [txs, setTxs] = useState<Transaction[]>([]);
  const [chartAccounts, setChartAccounts] = useState<ChartAccount[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [open, setOpen] = useState(false);
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [contas, setContas] = useState<{ id: string; name: string }[]>([]);
  // O 409 da Onda 3 precisa de superficie: antes desta onda `request_payout` nunca recusava, e
  // a chamada nao tinha `try` nenhum — o botao simplesmente nao faria nada.
  const [payoutErro, setPayoutErro] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [s, t] = await Promise.all([
      api.get<WalletSummary>("/wallet/summary"),
      api.get<Transaction[]>("/wallet/transactions"),
    ]);
    setSummary(s.data);
    setTxs(t.data);
    // Rótulos são só um complemento de exibição — se o usuário não tiver acesso a esses módulos
    // (require_module), a lista de transações continua funcionando normalmente.
    const [ca, cc, po, bc] = await Promise.all([
      api.get<ChartAccount[]>("/chart-of-accounts").catch(() => ({ data: [] as ChartAccount[] })),
      api.get<CostCenter[]>("/cost-centers").catch(() => ({ data: [] as CostCenter[] })),
      api.get<Payout[]>("/wallet/payouts").catch(() => ({ data: [] as Payout[] })),
      // So para resolver o NOME da conta de destino. A Carteira nao pode ler o modulo do banco no
      // backend (Regra dos Planos §1.3b), entao `PayoutOut` traz o id e o nome se resolve aqui —
      // mesmo padrao de `accountLabel`/`costCenterLabel` logo abaixo.
      api
        .get<{ id: string; name: string }[]>("/bank/accounts")
        .catch(() => ({ data: [] as { id: string; name: string }[] })),
    ]);
    setChartAccounts(ca.data);
    setCostCenters(cc.data);
    setPayouts(po.data);
    setContas(bc.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const accountLabel = useMemo(
    () => Object.fromEntries(chartAccounts.map((a) => [a.id, a.categoria])),
    [chartAccounts],
  );
  const costCenterLabel = useMemo(
    () => Object.fromEntries(costCenters.map((c) => [c.id, c.name])),
    [costCenters],
  );

  usePrimaryAction("Registrar venda", useCallback(() => setOpen(true), []));

  async function settle(id: string) {
    await api.post(`/wallet/transactions/${id}/settle`);
    load();
  }
  async function payout() {
    if (!confirm("Sacar todo o saldo disponível para sua conta bancária?")) return;
    setPayoutErro(null);
    try {
      await api.post("/wallet/payout");
    } catch (e) {
      // ⚠️ Este `catch` é NOVO (Onda 3). Antes, `request_payout` nunca recusava e a chamada não
      // tinha tratamento: os dois 409 da onda (sem conta principal; conta aberta depois da data
      // do saque) cairiam numa promise rejeitada e o botão não faria NADA — sem erro, sem efeito.
      setPayoutErro(apiErrorMessage(e));
      return;
    }
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Financeiro</p>
        <h1 className="text-2xl font-bold text-neutral-800">Carteira</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Disponível para saque" value={formatBRL(summary.available_cents)} tone="accent" />
        <Stat label="A receber" value={formatBRL(summary.pending_cents)} tone="info" />
        <Stat label="Já sacado" value={formatBRL(summary.withdrawn_cents)} tone="neutral" />
        <Stat label="Taxas da plataforma" value={formatBRL(summary.fees_total_cents)} tone="neutral" />
      </div>

      {summary.available_cents > 0 && (
        <button
          onClick={payout}
          className="rounded-pill bg-primary-500 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-600"
        >
          Sacar {formatBRL(summary.available_cents)}
        </button>
      )}

      {payoutErro && (
        <div className="rounded-2xl bg-amber-50 p-4 text-sm text-amber-900">
          <p>{payoutErro}</p>
          {/*
            O link é parte da recusa, não enfeite. A frase manda definir a conta principal, e até
            a Onda 3 NÃO EXISTIA como fazer isso — o service `set_primary` estava lá desde a Story
            8.7 sem rota nem botão. Mandar o dono a uma tela onde a ação não existe seria pior do
            que não avisar.
          */}
          <Link
            to="/financeiro/contas"
            className="mt-2 inline-block font-semibold underline hover:text-amber-950"
          >
            Ir para Contas &amp; Saldos
          </Link>
        </div>
      )}

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {txs.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhuma transação. Clique em "Registrar venda".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Descrição</th>
                <th className="px-4 py-3 font-medium">Categoria</th>
                <th className="px-4 py-3 font-medium">Centro de custo</th>
                <th className="px-4 py-3 font-medium">Bruto</th>
                <th className="px-4 py-3 font-medium">Taxa</th>
                <th className="px-4 py-3 font-medium">Líquido</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {txs.map((t) => (
                <tr key={t.id} className="border-b border-neutral-50 last:border-0">
                  <td className="px-4 py-3">
                    <span className="text-neutral-800">{t.description || "—"}</span>
                    <span className="block text-xs text-neutral-400">
                      {t.kind} · {t.method}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-neutral-500">
                    {(t.chart_account_id && accountLabel[t.chart_account_id]) || "—"}
                  </td>
                  <td className="px-4 py-3 text-neutral-500">
                    {(t.cost_center_id && costCenterLabel[t.cost_center_id]) || "—"}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-neutral-600">{formatBRL(t.gross_cents)}</td>
                  <td className="px-4 py-3 tabular-nums text-danger">
                    -{formatBRL(t.platform_fee_cents)}
                  </td>
                  <td className="px-4 py-3 font-medium tabular-nums text-accent-700">
                    {formatBRL(t.net_cents)}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
                      {statusLabel[t.status]}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {t.status === "pending" && (
                      <button
                        onClick={() => settle(t.id)}
                        className="text-xs font-medium text-primary-600 hover:underline"
                      >
                        Liberar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/*
        O histórico de saques mora AQUI, dentro da Carteira — não vira item de menu. A Conferência
        já estabeleceu a régua: tela nova no menu vira peso de ERP, e consultar saques passados é
        episódico, não tarefa de rotina. O crédito correspondente também aparece no extrato da
        conta principal, em Contas & Saldos: são duas superfícies sobre o mesmo fato, de propósito.
      */}
      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        <h2 className="border-b border-neutral-100 px-4 py-3 text-sm font-semibold text-neutral-700">
          Saques
        </h2>
        <PayoutHistory
          payouts={payouts}
          accountNames={Object.fromEntries(contas.map((c) => [c.id, c.name]))}
        />
      </div>

      <NewSaleModal open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
  );
}

const tones = {
  accent: "text-accent-700",
  info: "text-blue-700",
  neutral: "text-neutral-700",
} as const;

function Stat({ label, value, tone }: { label: string; value: string; tone: keyof typeof tones }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tones[tone]}`}>{value}</p>
    </div>
  );
}

function NewSaleModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState("service");
  const [method, setMethod] = useState("pix");
  const [value, setValue] = useState("");
  const [description, setDescription] = useState("");
  const [chartAccountId, setChartAccountId] = useState("");
  const [costCenterId, setCostCenterId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const gross_cents = parseCentsBRL(value);
      await api.post("/wallet/transactions", {
        kind,
        method,
        gross_cents,
        description,
        chart_account_id: chartAccountId || null,
        cost_center_id: costCenterId || null,
      });
      onCreated();
      setValue("");
      setDescription("");
      setChartAccountId("");
      setCostCenterId("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Registrar venda" open={open} onClose={onClose}>
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo (define o split)</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Método</span>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {METHODS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <Field label="Valor (R$)" value={value} onChange={setValue} placeholder="150,00" />
        <Field label="Descrição" value={description} onChange={setDescription} placeholder="Consulta" />
        <div className="flex gap-2">
          <div className="flex-1">
            <ChartAccountSelect
              value={chartAccountId}
              onChange={setChartAccountId}
              groups={REVENUE_GROUPS}
              defaultNewGrupo="RECEITA"
            />
          </div>
          <div className="flex-1">
            <CostCenterSelect value={costCenterId} onChange={setCostCenterId} />
          </div>
        </div>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !value}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Registrar"}
        </button>
      </div>
    </Modal>
  );
}
