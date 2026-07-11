import type { Charge, ChargesSummary, Client, Contract } from "@e1p/shared-types";
import { Copy, Paperclip } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Attachments from "../../components/Attachments";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage, publicApi } from "../../lib/api";
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

  usePrimaryAction("Nova cobrança", useCallback(() => setOpen(true), []));

  // Em produção, o pagamento é reconhecido pelo gateway (webhook). Aqui é só simulação de teste
  // do gateway (Pix/cartão/boleto) — o dono NÃO marca pago manualmente.
  async function simulatePayment(c: Charge) {
    if (!confirm("Simular o pagamento do cliente (gateway de teste)?")) return;
    await publicApi.post("/receivables/webhook", {
      tenant_id: c.tenant_id,
      charge_id: c.id,
      status: "paid",
    });
    load();
  }
  async function cancel(id: string) {
    if (!confirm("Cancelar esta cobrança?")) return;
    await api.post(`/receivables/charges/${id}/cancel`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Cobranças</p>
        <h1 className="text-2xl font-bold text-neutral-800">Contas a Receber</h1>
        <p className="mt-1 text-sm text-neutral-500">
          O pagamento é reconhecido automaticamente (Pix/cartão/boleto). Você saca o que entra no
          Financeiro.
        </p>
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
                            <button onClick={() => simulatePayment(c)} title="Apenas teste do gateway — em produção o pagamento entra sozinho" className="text-[11px] text-neutral-300 hover:text-accent-600">
                              simular pgto
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

      <NewChargeModal open={open} onClose={() => setOpen(false)} onCreated={load} />
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
  const [dueDate, setDueDate] = useState("");
  const [description, setDescription] = useState("");
  const [clientId, setClientId] = useState("");
  const [recurrence, setRecurrence] = useState("none");
  const [recurrenceCount, setRecurrenceCount] = useState("12");
  const [clients, setClients] = useState<Client[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [contractId, setContractId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      api.get<Client[]>("/crm/clients").then(({ data }) => setClients(data));
      api.get<Contract[]>("/contracts").then(({ data }) => setContracts(data)).catch(() => setContracts([]));
    }
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
        contract_id: contractId || null,
        recurrence,
        recurrence_count: recurrence === "none" ? 1 : Math.max(1, Math.min(60, parseInt(recurrenceCount, 10) || 1)),
      });
      onCreated();
      setValue("");
      setDueDate("");
      setDescription("");
      setContractId("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova cobrança" open={open} onClose={onClose}>
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
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Vincular a contrato (opcional)
          </span>
          <select
            value={contractId}
            onChange={(e) => setContractId(e.target.value)}
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
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Recorrência</span>
            <select value={recurrence} onChange={(e) => setRecurrence(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              <option value="none">Não repete</option>
              <option value="weekly">Semanal</option>
              <option value="monthly">Mensal</option>
              <option value="yearly">Anual</option>
            </select>
          </label>
          {recurrence !== "none" && (
            <Field label="Repetir (vezes)" value={recurrenceCount} onChange={setRecurrenceCount} />
          )}
        </div>
        {recurrence !== "none" && (
          <p className="-mt-1 text-xs text-neutral-400">
            Gera uma cobrança por período, cada uma com seu vencimento e boleto.
          </p>
        )}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !value || !dueDate}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Gerando..." : method === "boleto" ? "Gerar boleto" : "Gerar cobrança"}
        </button>
      </div>
    </Modal>
  );
}
