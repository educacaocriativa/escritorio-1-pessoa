import type { Payable, PayablesSummary } from "@e1p/shared-types";
import { Copy, Paperclip } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

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
  const [open, setOpen] = useState(false);
  const [attach, setAttach] = useState<Payable | null>(null);

  const load = useCallback(async () => {
    const [s, b] = await Promise.all([
      api.get<PayablesSummary>("/payables/summary"),
      api.get<Payable[]>("/payables/bills"),
    ]);
    setSummary(s.data);
    setBills(b.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

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
                    <td className="px-4 py-3 text-neutral-500">{p.category}</td>
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
                        {p.attachment_url && (
                          <a href={p.attachment_url} target="_blank" rel="noreferrer" title="Ver boleto anexado" className="text-neutral-400 hover:text-primary-600">
                            <Paperclip size={14} />
                          </a>
                        )}
                        {p.status !== "canceled" && (
                          <button onClick={() => setAttach(p)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
                            Boleto/Pix
                          </button>
                        )}
                        {p.status === "open" && (
                          <>
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
  const [attachmentUrl, setAttachmentUrl] = useState(bill.attachment_url);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/payables/bills/${bill.id}`, {
        payment_code: paymentCode,
        attachment_url: attachmentUrl,
      });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Boleto / Pix da conta" open onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-neutral-500">{bill.description || bill.supplier || "Conta"}</p>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Linha digitável do boleto OU Pix copia-e-cola
          </span>
          <textarea value={paymentCode} onChange={(e) => setPaymentCode(e.target.value)} rows={3} placeholder="Cole aqui o código" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
        </label>
        <Field label="Anexo do boleto (URL do PDF/imagem)" value={attachmentUrl} onChange={setAttachmentUrl} placeholder="https://..." />
        {attachmentUrl && (
          <a href={attachmentUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-primary-600">
            <Paperclip size={12} /> abrir anexo atual
          </a>
        )}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Salvar"}
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
  const [category, setCategory] = useState("Geral");
  const [supplier, setSupplier] = useState("");
  const [value, setValue] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [recurrence, setRecurrence] = useState("none");
  const [paymentCode, setPaymentCode] = useState("");
  const [attachmentUrl, setAttachmentUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const amount_cents = Math.round(parseFloat(value.replace(",", ".")) * 100);
      await api.post("/payables/bills", {
        description,
        category,
        supplier,
        amount_cents,
        due_date: dueDate,
        recurrence,
        payment_code: paymentCode,
        attachment_url: attachmentUrl,
      });
      onCreated();
      setDescription("");
      setSupplier("");
      setValue("");
      setDueDate("");
      setPaymentCode("");
      setAttachmentUrl("");
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
        <div className="flex gap-2">
          <Field label="Categoria" value={category} onChange={setCategory} placeholder="Estrutura" />
          <Field label="Fornecedor" value={supplier} onChange={setSupplier} placeholder="Imobiliária" />
        </div>
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} placeholder="2500,00" />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Recorrência</span>
          <select value={recurrence} onChange={(e) => setRecurrence(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
            {RECUR.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <div className="rounded-lg bg-neutral-50 p-3">
          <p className="mb-2 text-xs font-medium text-neutral-600">Boleto recebido / Pix (opcional)</p>
          <textarea value={paymentCode} onChange={(e) => setPaymentCode(e.target.value)} rows={2} placeholder="Cole a linha digitável do boleto ou o Pix copia-e-cola" className="mb-2 w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
          <Field label="Anexo do boleto (URL do PDF/imagem)" value={attachmentUrl} onChange={setAttachmentUrl} placeholder="https://..." />
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
