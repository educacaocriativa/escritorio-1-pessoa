import type { Client, Quote, QuoteItem, QuotesSummary } from "@e1p/shared-types";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const statusInfo: Record<Quote["status"], { label: string; cls: string }> = {
  draft: { label: "Rascunho", cls: "bg-neutral-100 text-neutral-500" },
  sent: { label: "Enviado", cls: "bg-blue-50 text-blue-700" },
  approved: { label: "Aprovado", cls: "bg-accent-50 text-accent-700" },
  rejected: { label: "Recusado", cls: "bg-red-50 text-danger" },
};

export default function OrcamentosPage() {
  const empty: QuotesSummary = { draft_count: 0, sent_cents: 0, approved_cents: 0, approved_count: 0 };
  const [summary, setSummary] = useState<QuotesSummary>(empty);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const [s, q] = await Promise.all([
      api.get<QuotesSummary>("/quotes/summary"),
      api.get<Quote[]>("/quotes"),
    ]);
    setSummary(s.data);
    setQuotes(q.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo orçamento", useCallback(() => setOpen(true), []));

  async function act(id: string, action: "send" | "approve" | "reject") {
    if (action === "approve" && !confirm("Aprovar gera a cobrança automaticamente. Confirmar?"))
      return;
    await api.post(`/quotes/${id}/${action}`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Orçamentos</p>
        <h1 className="text-2xl font-bold text-neutral-800">Orçamentos</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Rascunhos" value={String(summary.draft_count)} tone="text-neutral-700" />
        <Stat label="Enviados (aguardando)" value={brl(summary.sent_cents)} tone="text-blue-700" />
        <Stat label="Aprovados" value={brl(summary.approved_cents)} tone="text-accent-700" />
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {quotes.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhum orçamento. Clique em "Novo orçamento".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Cliente</th>
                <th className="px-4 py-3 font-medium">Título</th>
                <th className="px-4 py-3 font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {quotes.map((q) => (
                <tr key={q.id} className="border-b border-neutral-50 last:border-0">
                  <td className="px-4 py-3 font-medium text-neutral-800">{q.client_name ?? "—"}</td>
                  <td className="px-4 py-3 text-neutral-600">{q.title}</td>
                  <td className="px-4 py-3 font-medium tabular-nums">{brl(q.total_cents)}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-pill px-2 py-0.5 text-xs ${statusInfo[q.status].cls}`}>
                      {statusInfo[q.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-3 text-xs font-medium">
                      {(q.status === "draft" || q.status === "sent") && (
                        <button onClick={() => act(q.id, "send")} className="text-blue-600 hover:underline">
                          Enviar
                        </button>
                      )}
                      {q.status !== "approved" && q.status !== "rejected" && (
                        <button onClick={() => act(q.id, "approve")} className="text-accent-600 hover:underline">
                          Aprovar
                        </button>
                      )}
                      {q.status !== "approved" && q.status !== "rejected" && (
                        <button onClick={() => act(q.id, "reject")} className="text-neutral-400 hover:text-danger">
                          Recusar
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <NewQuoteModal open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
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

type ItemRow = { description: string; quantity: string; price: string };

function NewQuoteModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [clientId, setClientId] = useState("");
  const [clients, setClients] = useState<Client[]>([]);
  const [rows, setRows] = useState<ItemRow[]>([{ description: "", quantity: "1", price: "" }]);
  const [discount, setDiscount] = useState("");
  const [brief, setBrief] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) api.get<Client[]>("/crm/clients").then(({ data }) => setClients(data));
  }, [open]);

  function setRow(i: number, patch: Partial<ItemRow>) {
    setRows((r) => r.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));
  }
  const total = rows.reduce(
    (sum, r) => sum + (parseInt(r.quantity || "0", 10) * Math.round(parseFloat(r.price.replace(",", ".") || "0") * 100)),
    0,
  );
  const finalTotal = Math.max(0, total - Math.round(parseFloat(discount.replace(",", ".") || "0") * 100));

  async function generateScope() {
    if (!brief.trim()) return;
    setAiBusy(true);
    try {
      const { data } = await api.post<{ description: string }>("/quotes/scope", { brief });
      setRow(0, { description: data.description });
    } finally {
      setAiBusy(false);
    }
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const items: QuoteItem[] = rows
        .filter((r) => r.description.trim())
        .map((r) => ({
          description: r.description,
          quantity: parseInt(r.quantity || "1", 10),
          unit_price_cents: Math.round(parseFloat(r.price.replace(",", ".") || "0") * 100),
        }));
      await api.post("/quotes", {
        title,
        client_id: clientId || null,
        items,
        discount_cents: Math.round(parseFloat(discount.replace(",", ".") || "0") * 100),
      });
      onCreated();
      onClose();
      setTitle("");
      setRows([{ description: "", quantity: "1", price: "" }]);
      setDiscount("");
      setBrief("");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Novo orçamento" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Título" value={title} onChange={setTitle} placeholder="Consultoria trabalhista" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Cliente</span>
          <select value={clientId} onChange={(e) => setClientId(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
            <option value="">Sem cliente</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>

        <div className="rounded-lg bg-primary-50 p-2">
          <span className="mb-1 block text-xs font-medium text-primary-700">
            Descrever escopo com IA
          </span>
          <div className="flex gap-2">
            <input value={brief} onChange={(e) => setBrief(e.target.value)} placeholder="ex: análise de rescisão" className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
            <button onClick={generateScope} disabled={aiBusy || !brief.trim()} className="flex shrink-0 items-center gap-1 rounded-lg bg-primary-500 px-3 text-xs font-semibold text-white disabled:opacity-60">
              <Sparkles size={12} /> {aiBusy ? "..." : "Gerar"}
            </button>
          </div>
        </div>

        <div className="space-y-2">
          <span className="text-xs font-medium text-neutral-600">Itens</span>
          {rows.map((r, i) => (
            <div key={i} className="flex gap-2">
              <input value={r.description} onChange={(e) => setRow(i, { description: e.target.value })} placeholder="Descrição" className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
              <input value={r.quantity} onChange={(e) => setRow(i, { quantity: e.target.value })} type="number" min={1} className="w-14 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
              <input value={r.price} onChange={(e) => setRow(i, { price: e.target.value })} placeholder="R$" className="w-20 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
              {rows.length > 1 && (
                <button onClick={() => setRows((rr) => rr.filter((_, idx) => idx !== i))} className="text-neutral-300 hover:text-danger">
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
          <button onClick={() => setRows((r) => [...r, { description: "", quantity: "1", price: "" }])} className="flex items-center gap-1 text-xs font-medium text-primary-600">
            <Plus size={12} /> Adicionar item
          </button>
        </div>

        <div className="flex items-center gap-2">
          <Field label="Desconto (R$)" value={discount} onChange={setDiscount} placeholder="0,00" />
          <div className="flex-1 text-right">
            <p className="text-xs text-neutral-400">Total</p>
            <p className="text-lg font-bold text-neutral-800">{brl(finalTotal)}</p>
          </div>
        </div>

        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !title || rows.every((r) => !r.description.trim())}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Criar orçamento"}
        </button>
      </div>
    </Modal>
  );
}
