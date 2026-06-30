import type { Charge, ChargesSummary, Client } from "@e1p/shared-types";
import { Barcode, Copy, Paperclip } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Attachments from "../../components/Attachments";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const KINDS = [
  ["service", "Serviço"],
  ["product", "Produto"],
  ["recurring", "Recorrente"],
] as const;
const METHODS = [
  ["pix", "Pix"],
  ["boleto", "Boleto"],
  ["card", "Link de cartão"],
] as const;

function statusInfo(c: Charge): { label: string; cls: string } {
  if (c.status === "paid") return { label: "Recebido", cls: "bg-accent-50 text-accent-700" };
  if (c.status === "canceled") return { label: "Cancelado", cls: "bg-neutral-100 text-neutral-500" };
  if (c.is_overdue) return { label: "Vencido", cls: "bg-red-50 text-danger" };
  return { label: "A vencer", cls: "bg-blue-50 text-blue-700" };
}

export default function CobrancasPage() {
  const empty: ChargesSummary = {
    open_cents: 0,
    overdue_cents: 0,
    paid_cents: 0,
    open_count: 0,
    overdue_count: 0,
  };
  const [summary, setSummary] = useState<ChargesSummary>(empty);
  const [charges, setCharges] = useState<Charge[]>([]);
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState("pix");
  const [docs, setDocs] = useState<Charge | null>(null);
  const [edit, setEdit] = useState<Charge | null>(null);

  const load = useCallback(async () => {
    const [s, c] = await Promise.all([
      api.get<ChargesSummary>("/receivables/summary"),
      api.get<Charge[]>("/receivables/charges"),
    ]);
    setSummary(s.data);
    setCharges(c.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction(
    "Nova cobrança",
    useCallback(() => {
      setPreset("pix");
      setOpen(true);
    }, []),
  );

  async function pay(id: string) {
    await api.post(`/receivables/charges/${id}/pay`);
    load();
  }
  async function cancel(id: string) {
    if (!confirm("Cancelar esta cobrança?")) return;
    await api.post(`/receivables/charges/${id}/cancel`);
    load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-neutral-500">Página / Cobranças</p>
          <h1 className="text-2xl font-bold text-neutral-800">Contas a Receber</h1>
        </div>
        <button
          onClick={() => {
            setPreset("boleto");
            setOpen(true);
          }}
          className="flex items-center gap-1.5 rounded-pill bg-primary-500 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-600"
        >
          <Barcode size={15} /> Criar boleto
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="A vencer" value={brl(summary.open_cents)} hint={`${summary.open_count} cobranças`} tone="text-blue-700" />
        <Stat label="Vencido" value={brl(summary.overdue_cents)} hint={`${summary.overdue_count} em atraso`} tone="text-danger" />
        <Stat label="Recebido" value={brl(summary.paid_cents)} hint="total" tone="text-accent-700" />
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {charges.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhuma cobrança. Clique em "Nova cobrança".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Cliente</th>
                <th className="px-4 py-3 font-medium">Descrição</th>
                <th className="px-4 py-3 font-medium">Vencimento</th>
                <th className="px-4 py-3 font-medium">Valor</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {charges.map((c) => {
                const st = statusInfo(c);
                return (
                  <tr key={c.id} className="border-b border-neutral-50 last:border-0">
                    <td className="px-4 py-3 font-medium text-neutral-800">
                      {c.client_name ?? <span className="text-neutral-300">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-neutral-800">{c.description || "—"}</span>
                      <span className="ml-2 inline-flex items-center gap-1 text-xs text-neutral-400">
                        {c.method}
                        <button
                          title="Copiar código de pagamento"
                          onClick={() => navigator.clipboard?.writeText(c.payment_code)}
                          className="hover:text-neutral-600"
                        >
                          <Copy size={11} />
                        </button>
                      </span>
                    </td>
                    <td className="px-4 py-3 tabular-nums text-neutral-600">
                      {new Date(c.due_date + "T00:00").toLocaleDateString("pt-BR")}
                    </td>
                    <td className="px-4 py-3 font-medium tabular-nums">{brl(c.amount_cents)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-pill px-2 py-0.5 text-xs ${st.cls}`}>{st.label}</span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <button onClick={() => setDocs(c)} className="flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-primary-600">
                          <Paperclip size={12} /> Contrato
                        </button>
                        {c.status === "open" && (
                          <>
                            <button onClick={() => setEdit(c)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
                              Editar
                            </button>
                            <button onClick={() => pay(c.id)} className="text-xs font-medium text-accent-600 hover:underline">
                              Marcar paga
                            </button>
                            <button onClick={() => cancel(c.id)} className="text-xs text-neutral-400 hover:text-danger">
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

      <NewChargeModal open={open} initialMethod={preset} onClose={() => setOpen(false)} onCreated={load} />
      {edit && (
        <EditChargeModal
          charge={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            load();
          }}
        />
      )}
      {docs && (
        <Modal title="Contrato / documentos da cobrança" open onClose={() => setDocs(null)}>
          <div className="space-y-3">
            <p className="text-sm text-neutral-500">
              {docs.client_name ?? docs.description ?? "Cobrança"} — {brl(docs.amount_cents)}
            </p>
            <p className="text-xs font-medium text-neutral-600">Anexar arquivos (PDF, JPEG ou PNG)</p>
            <Attachments
              ownerType="charge"
              ownerId={docs.id}
              slots={[{ key: "contrato", label: "Contrato" }, { key: "boleto", label: "Boleto" }]}
            />
          </div>
        </Modal>
      )}
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
      <p className="text-xs text-neutral-400">{hint}</p>
    </div>
  );
}

function EditChargeModal({
  charge,
  onClose,
  onSaved,
}: {
  charge: Charge;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [description, setDescription] = useState(charge.description);
  const [value, setValue] = useState((charge.amount_cents / 100).toFixed(2).replace(".", ","));
  const [dueDate, setDueDate] = useState(charge.due_date);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/receivables/charges/${charge.id}`, {
        description,
        amount_cents: Math.round(parseFloat(value.replace(",", ".")) * 100),
        due_date: dueDate,
      });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Editar cobrança" open onClose={onClose}>
      <div className="space-y-3">
        <Field label="Descrição" value={description} onChange={setDescription} />
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <p className="text-xs text-neutral-400">Mudar o vencimento move o evento na Agenda.</p>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={save} disabled={saving || !value || !dueDate} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Salvando..." : "Salvar alterações"}
        </button>
      </div>
    </Modal>
  );
}

function NewChargeModal({
  open,
  initialMethod = "pix",
  onClose,
  onCreated,
}: {
  open: boolean;
  initialMethod?: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState("service");
  const [method, setMethod] = useState(initialMethod);

  useEffect(() => {
    if (open) setMethod(initialMethod);
  }, [open, initialMethod]);
  const [value, setValue] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [description, setDescription] = useState("");
  const [clientId, setClientId] = useState("");
  const [clients, setClients] = useState<Client[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) api.get<Client[]>("/crm/clients").then(({ data }) => setClients(data));
  }, [open]);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const amount_cents = Math.round(parseFloat(value.replace(",", ".")) * 100);
      await api.post("/receivables/charges", {
        kind,
        method,
        amount_cents,
        due_date: dueDate,
        description,
        client_id: clientId || null,
      });
      onCreated();
      setValue("");
      setDueDate("");
      setDescription("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={initialMethod === "boleto" ? "Criar boleto" : "Nova cobrança"} open={open} onClose={onClose}>
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Cliente</span>
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="">Sem cliente</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
            <select value={kind} onChange={(e) => setKind(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              {KINDS.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Forma</span>
            <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              {METHODS.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} placeholder="150,00" />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <Field label="Descrição" value={description} onChange={setDescription} placeholder="Mensalidade" />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !value || !dueDate}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Gerando..." : "Gerar cobrança"}
        </button>
      </div>
    </Modal>
  );
}
