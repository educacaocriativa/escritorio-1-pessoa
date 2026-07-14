import type { Contract, Payable, PayablesSummary } from "@e1p/shared-types";
import { Copy, Paperclip } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import Attachments from "../../components/Attachments";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import ChartAccountSelect from "../financeiro/ChartAccountSelect";
import type { CostCenter } from "../financeiro/costCenters";
import CostCenterSelect from "../financeiro/CostCenterSelect";
import { type ChartAccount, GRUPOS_DRE } from "../financeiro/planoContas";

/** Grupos DRE cabíveis numa DESPESA (Contas a Pagar nunca lança em Receita). */
const EXPENSE_GROUPS = GRUPOS_DRE.filter((g) => g !== "RECEITA");

/** Seletor "Vincular a contrato" (Story 5.4) — opcional; vazio = bucket "Empresa" (overhead). */
function ContractSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [contracts, setContracts] = useState<Contract[]>([]);
  useEffect(() => {
    api.get<Contract[]>("/contracts").then((r) => setContracts(r.data)).catch(() => setContracts([]));
  }, []);
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">
        Vincular a contrato (opcional)
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
      >
        <option value="">Empresa (sem contrato)</option>
        {contracts.map((c) => (
          <option key={c.id} value={c.id}>
            {c.title}
            {c.client_name ? ` — ${c.client_name}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const RECUR = [
  ["none", "Não repete"],
  ["weekly", "Semanal"],
  ["monthly", "Mensal"],
  ["yearly", "Anual"],
] as const;

function statusInfo(p: Payable): { label: string; cls: string } {
  if (p.status === "paid") return { label: "Pago", cls: "bg-accent-50 text-accent-700" };
  if (p.status === "canceled") return { label: "Cancelado", cls: "bg-neutral-100 text-neutral-500" };
  if (p.is_overdue) return { label: "Atrasado", cls: "bg-red-50 text-danger" };
  return { label: "A pagar", cls: "bg-amber-50 text-amber-700" };
}

export default function PagarPage() {
  const empty: PayablesSummary = {
    open_cents: 0,
    overdue_cents: 0,
    week_cents: 0,
    month_cents: 0,
    paid_month_cents: 0,
  };
  const [summary, setSummary] = useState<PayablesSummary>(empty);
  const [bills, setBills] = useState<Payable[]>([]);
  const [chartAccounts, setChartAccounts] = useState<ChartAccount[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [open, setOpen] = useState(false);
  const [attach, setAttach] = useState<Payable | null>(null);
  const [edit, setEdit] = useState<Payable | null>(null);

  const load = useCallback(async () => {
    const [s, b] = await Promise.all([
      api.get<PayablesSummary>("/payables/summary"),
      api.get<Payable[]>("/payables/bills"),
    ]);
    setSummary(s.data);
    setBills(b.data);
    // Rótulos são só um complemento de exibição — se o usuário não tiver acesso a esses módulos
    // (require_module), a lista de contas a pagar continua funcionando normalmente.
    const [ca, cc] = await Promise.all([
      api.get<ChartAccount[]>("/chart-of-accounts").catch(() => ({ data: [] as ChartAccount[] })),
      api.get<CostCenter[]>("/cost-centers").catch(() => ({ data: [] as CostCenter[] })),
    ]);
    setChartAccounts(ca.data);
    setCostCenters(cc.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Rótulo estruturado quando o lançamento tem vínculo; senão cai no texto legado (`category`).
  const accountLabel = useMemo(
    () => Object.fromEntries(chartAccounts.map((a) => [a.id, a.categoria])),
    [chartAccounts],
  );
  const costCenterLabel = useMemo(
    () => Object.fromEntries(costCenters.map((c) => [c.id, c.name])),
    [costCenters],
  );

  usePrimaryAction("Nova conta", useCallback(() => setOpen(true), []));

  async function pay(id: string) {
    await api.post(`/payables/bills/${id}/pay`);
    load();
  }
  async function cancel(id: string) {
    if (!confirm("Cancelar esta conta?")) return;
    await api.post(`/payables/bills/${id}/cancel`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Contas a Pagar</p>
        <h1 className="text-2xl font-bold text-neutral-800">Despesas</h1>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="A pagar" value={brl(summary.open_cents)} tone="text-amber-700" />
        <Stat label="Atrasado" value={brl(summary.overdue_cents)} tone="text-danger" />
        <Stat label="Nesta semana" value={brl(summary.week_cents)} tone="text-neutral-700" />
        <Stat label="Pago no mês" value={brl(summary.paid_month_cents)} tone="text-accent-700" />
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {bills.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhuma conta. Clique em "Nova conta".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Conta</th>
                <th className="px-4 py-3 font-medium">Categoria</th>
                <th className="px-4 py-3 font-medium">Centro de custo</th>
                <th className="px-4 py-3 font-medium">Vencimento</th>
                <th className="px-4 py-3 font-medium">Valor</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {bills.map((p) => {
                const st = statusInfo(p);
                return (
                  <tr key={p.id} className="border-b border-neutral-50 last:border-0">
                    <td className="px-4 py-3">
                      <span className="text-neutral-800">{p.description || "—"}</span>
                      {p.supplier && (
                        <span className="block text-xs text-neutral-400">{p.supplier}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-neutral-500">
                      {(p.chart_account_id && accountLabel[p.chart_account_id]) || p.category}
                    </td>
                    <td className="px-4 py-3 text-neutral-500">
                      {(p.cost_center_id && costCenterLabel[p.cost_center_id]) || "—"}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-neutral-600">
                      {new Date(p.due_date + "T00:00").toLocaleDateString("pt-BR")}
                    </td>
                    <td className="px-4 py-3 font-medium tabular-nums">{brl(p.amount_cents)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-pill px-2 py-0.5 text-xs ${st.cls}`}>{st.label}</span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-3">
                        {p.payment_code && (
                          <button title="Copiar código do boleto/Pix" onClick={() => navigator.clipboard?.writeText(p.payment_code)} className="text-neutral-400 hover:text-primary-600">
                            <Copy size={14} />
                          </button>
                        )}
                        {p.status !== "canceled" && (
                          <button onClick={() => setAttach(p)} className="flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-primary-600">
                            <Paperclip size={12} /> Boleto/Pix
                          </button>
                        )}
                        {p.status === "open" && (
                          <>
                            <button onClick={() => setEdit(p)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
                              Editar
                            </button>
                            <button onClick={() => pay(p.id)} className="text-xs font-medium text-accent-600 hover:underline">
                              Marcar paga
                            </button>
                            <button onClick={() => cancel(p.id)} className="text-xs text-neutral-400 hover:text-danger">
                              Cancelar
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <NewBillModal open={open} onClose={() => setOpen(false)} onCreated={load} />
      {edit && (
        <EditBillModal
          bill={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            load();
          }}
        />
      )}
      {attach && (
        <AttachModal
          bill={attach}
          onClose={() => setAttach(null)}
          onSaved={() => {
            setAttach(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function EditBillModal({
  bill,
  onClose,
  onSaved,
}: {
  bill: Payable;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [description, setDescription] = useState(bill.description);
  const [chartAccountId, setChartAccountId] = useState(bill.chart_account_id ?? "");
  const [costCenterId, setCostCenterId] = useState(bill.cost_center_id ?? "");
  const [supplier, setSupplier] = useState(bill.supplier);
  const [value, setValue] = useState((bill.amount_cents / 100).toFixed(2).replace(".", ","));
  const [dueDate, setDueDate] = useState(bill.due_date);
  const [recurrence, setRecurrence] = useState(bill.recurrence);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/payables/bills/${bill.id}`, {
        description,
        chart_account_id: chartAccountId,
        cost_center_id: costCenterId,
        supplier,
        amount_cents: Math.round(parseFloat(value.replace(",", ".")) * 100),
        due_date: dueDate,
        recurrence,
      });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Editar conta" open onClose={onClose}>
      <div className="space-y-3">
        <Field label="Descrição" value={description} onChange={setDescription} />
        <Field label="Fornecedor" value={supplier} onChange={setSupplier} />
        <div className="flex gap-2">
          <div className="flex-1">
            <ChartAccountSelect
              value={chartAccountId}
              onChange={setChartAccountId}
              groups={EXPENSE_GROUPS}
              defaultNewGrupo="DESPESA_FIXA"
            />
          </div>
          <div className="flex-1">
            <CostCenterSelect value={costCenterId} onChange={setCostCenterId} />
          </div>
        </div>
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Recorrência</span>
          <select value={recurrence} onChange={(e) => setRecurrence(e.target.value as Payable["recurrence"])} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
            {RECUR.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <p className="text-xs text-neutral-400">Mudar o vencimento move o evento na Agenda.</p>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={save} disabled={saving || !value || !dueDate} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Salvando..." : "Salvar alterações"}
        </button>
      </div>
    </Modal>
  );
}

function AttachModal({
  bill,
  onClose,
  onSaved,
}: {
  bill: Payable;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [paymentCode, setPaymentCode] = useState(bill.payment_code);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function saveCode() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/payables/bills/${bill.id}`, { payment_code: paymentCode });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Boleto / Contrato / Pix" open onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-neutral-500">{bill.description || bill.supplier || "Conta"}</p>

        <div>
          <p className="mb-2 text-xs font-medium text-neutral-600">Anexar arquivos (PDF, JPEG ou PNG)</p>
          <Attachments
            ownerType="payable"
            ownerId={bill.id}
            slots={[{ key: "boleto", label: "Boleto" }, { key: "contrato", label: "Contrato" }]}
          />
        </div>

        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Pix copia-e-cola / linha do boleto (opcional)
          </span>
          <textarea value={paymentCode} onChange={(e) => setPaymentCode(e.target.value)} rows={2} placeholder="Cole aqui o código" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={saveCode}
          disabled={saving}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Salvar código"}
        </button>
      </div>
    </Modal>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}

function NewBillModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [description, setDescription] = useState("");
  const [chartAccountId, setChartAccountId] = useState("");
  const [costCenterId, setCostCenterId] = useState("");
  const [supplier, setSupplier] = useState("");
  const [value, setValue] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [recurrence, setRecurrence] = useState("none");
  const [recurrenceCount, setRecurrenceCount] = useState("12");
  const [paymentCode, setPaymentCode] = useState("");
  const [contractId, setContractId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const amount_cents = Math.round(parseFloat(value.replace(",", ".")) * 100);
      await api.post("/payables/bills", {
        description,
        chart_account_id: chartAccountId || null,
        cost_center_id: costCenterId || null,
        supplier,
        amount_cents,
        due_date: dueDate,
        recurrence,
        recurrence_count: recurrence === "none" ? 1 : Math.max(1, Math.min(60, parseInt(recurrenceCount, 10) || 1)),
        payment_code: paymentCode,
        contract_id: contractId || null,
      });
      onCreated();
      setDescription("");
      setChartAccountId("");
      setCostCenterId("");
      setSupplier("");
      setValue("");
      setDueDate("");
      setPaymentCode("");
      setContractId("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova conta a pagar" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Descrição" value={description} onChange={setDescription} placeholder="Aluguel" />
        <Field label="Fornecedor" value={supplier} onChange={setSupplier} placeholder="Imobiliária" />
        <div className="flex gap-2">
          <div className="flex-1">
            <ChartAccountSelect
              value={chartAccountId}
              onChange={setChartAccountId}
              groups={EXPENSE_GROUPS}
              defaultNewGrupo="DESPESA_FIXA"
            />
          </div>
          <div className="flex-1">
            <CostCenterSelect value={costCenterId} onChange={setCostCenterId} />
          </div>
        </div>
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} placeholder="2500,00" />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Recorrência</span>
            <select value={recurrence} onChange={(e) => setRecurrence(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              {RECUR.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
          {recurrence !== "none" && (
            <Field label="Repetir (vezes)" value={recurrenceCount} onChange={setRecurrenceCount} />
          )}
        </div>
        {recurrence !== "none" && (
          <p className="-mt-1 text-xs text-neutral-400">
            Gera uma conta por período, cada uma com seu vencimento (para anexar o boleto certo).
          </p>
        )}
        <ContractSelect value={contractId} onChange={setContractId} />
        <div className="rounded-lg bg-neutral-50 p-3">
          <p className="mb-2 text-xs font-medium text-neutral-600">Pix copia-e-cola / linha do boleto (opcional)</p>
          <textarea value={paymentCode} onChange={(e) => setPaymentCode(e.target.value)} rows={2} placeholder="Cole o código aqui (os arquivos do boleto/contrato você anexa depois, em Boleto/Pix)" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
        </div>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !value || !dueDate}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Adicionar conta"}
        </button>
      </div>
    </Modal>
  );
}
