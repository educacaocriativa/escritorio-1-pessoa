import type {
  Charge,
  Client,
  Contract,
  FunnelRunSummary,
  LegalDocumentSummary,
  Quote,
} from "@e1p/shared-types";
import { ArrowLeft, FileSignature, FileText, Gavel, Pencil, Receipt, Workflow } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const dt = (s: string) => new Date(s + (s.length === 10 ? "T00:00" : "")).toLocaleDateString("pt-BR");

export default function ClientDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [client, setClient] = useState<Client | null>(null);
  const [charges, setCharges] = useState<Charge[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [legalDocs, setLegalDocs] = useState<LegalDocumentSummary[]>([]);
  const [journeys, setJourneys] = useState<FunnelRunSummary[]>([]);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    const [c, ch, co, qu, ld, jr] = await Promise.all([
      api.get<Client>(`/crm/clients/${id}`),
      api.get<Charge[]>(`/receivables/charges?client_id=${id}`),
      api.get<Contract[]>(`/contracts?client_id=${id}`),
      api.get<Quote[]>(`/quotes?client_id=${id}`),
      api.get<LegalDocumentSummary[]>(`/juridico/documents?client_id=${id}`),
      api.get<FunnelRunSummary[]>(`/funnels/runs?client_id=${id}`),
    ]);
    setClient(c.data);
    setCharges(ch.data);
    setContracts(co.data);
    setQuotes(qu.data);
    setLegalDocs(ld.data);
    setJourneys(jr.data);
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!client) return <div className="p-8 text-sm text-neutral-400">Carregando ficha...</div>;

  const openSum = charges.filter((c) => c.status === "open" && !c.is_overdue).reduce((a, c) => a + c.amount_cents, 0);
  const overdueSum = charges.filter((c) => c.is_overdue).reduce((a, c) => a + c.amount_cents, 0);
  const paidSum = charges.filter((c) => c.status === "paid").reduce((a, c) => a + c.amount_cents, 0);

  async function protest(cid: string) {
    await api.post(`/receivables/charges/${cid}/protest`);
    load();
  }
  async function reschedule(cid: string, due: string) {
    if (!due) return;
    await api.post(`/receivables/charges/${cid}/reschedule`, { due_date: due });
    load();
  }

  return (
    <div className="space-y-6">
      <button onClick={() => navigate("/crm")} className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-700">
        <ArrowLeft size={16} /> CRM & Kanban
      </button>

      {/* Cabeçalho do cliente */}
      <div className="rounded-2xl bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-neutral-800">{client.name}</h1>
            <p className="mt-1 text-sm text-neutral-500">
              {[client.email, client.phone, client.document].filter(Boolean).join(" · ") || "Sem contato cadastrado"}
            </p>
            {client.tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {client.tags.map((t) => (
                  <span key={t} className="rounded-pill bg-primary-50 px-2 py-0.5 text-xs text-primary-700">{t}</span>
                ))}
              </div>
            )}
          </div>
          <button onClick={() => setEditing(true)} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-600 hover:bg-neutral-200">
            <Pencil size={14} /> Editar
          </button>
        </div>
        {client.notes && <p className="mt-3 whitespace-pre-line rounded-lg bg-neutral-50 p-3 text-sm text-neutral-600">{client.notes}</p>}
      </div>

      {/* Resumo financeiro */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="A receber (a vencer)" value={brl(openSum)} tone="text-neutral-700" />
        <Stat label="Vencido" value={brl(overdueSum)} tone="text-danger" />
        <Stat label="Recebido" value={brl(paidSum)} tone="text-accent-700" />
      </div>

      {/* Cobranças */}
      <Section icon={<Receipt size={16} />} title={`Cobranças (${charges.length})`}>
        {charges.length === 0 ? (
          <Empty text="Nenhuma cobrança para este cliente." />
        ) : (
          <ul className="divide-y divide-neutral-100">
            {charges.map((c) => (
              <ChargeRow key={c.id} c={c} onProtest={protest} onReschedule={reschedule} />
            ))}
          </ul>
        )}
      </Section>

      {/* Contratos */}
      <Section icon={<FileSignature size={16} />} title={`Contratos (${contracts.length})`}>
        {contracts.length === 0 ? (
          <Empty text="Nenhum contrato." />
        ) : (
          <ul className="divide-y divide-neutral-100">
            {contracts.map((c) => (
              <li key={c.id} className="flex items-center justify-between py-2.5">
                <button onClick={() => navigate(`/contratos/${c.id}`)} className="text-left text-sm font-medium text-neutral-700 hover:text-primary-600">
                  {c.title}
                  {c.signer_name && <span className="block text-xs text-neutral-400">Assinado por {c.signer_name}</span>}
                </button>
                <StatusBadge status={c.status} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Orçamentos */}
      <Section icon={<FileText size={16} />} title={`Orçamentos (${quotes.length})`}>
        {quotes.length === 0 ? (
          <Empty text="Nenhum orçamento." />
        ) : (
          <ul className="divide-y divide-neutral-100">
            {quotes.map((q) => (
              <li key={q.id} className="flex items-center justify-between py-2.5">
                <button onClick={() => navigate(`/orcamentos/${q.id}`)} className="text-left text-sm font-medium text-neutral-700 hover:text-primary-600">
                  {q.title}
                  <span className="ml-2 text-xs text-neutral-400">{brl(q.total_cents)}</span>
                </button>
                <StatusBadge status={q.status} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Documentos jurídicos */}
      <Section icon={<Gavel size={16} />} title={`Documentos jurídicos (${legalDocs.length})`}>
        {legalDocs.length === 0 ? (
          <Empty text="Nenhum documento jurídico vinculado." />
        ) : (
          <ul className="divide-y divide-neutral-100">
            {legalDocs.map((d) => (
              <li key={d.id} className="flex items-center justify-between py-2.5">
                <button onClick={() => navigate(`/juridico/${d.id}`)} className="text-left text-sm font-medium text-neutral-700 hover:text-primary-600">
                  {d.title}
                  <span className="ml-2 text-xs text-neutral-400">{dt(d.created_at)}</span>
                </button>
                <StatusBadge status={d.status} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Jornadas no funil (automação) */}
      <Section icon={<Workflow size={16} />} title={`Jornadas no funil (${journeys.length})`}>
        {journeys.length === 0 ? (
          <Empty text="Este contato não está em nenhum funil." />
        ) : (
          <ul className="divide-y divide-neutral-100">
            {journeys.map((j) => (
              <li key={j.id} className="flex items-center justify-between py-2.5">
                <button onClick={() => navigate(`/funis/${j.funnel_id}`)} className="text-left text-sm font-medium text-neutral-700 hover:text-primary-600">
                  Funil
                  <span className="ml-2 text-xs text-neutral-400">{j.step_count} passo(s) · {dt(j.created_at)}</span>
                </button>
                <StatusBadge status={j.status} />
              </li>
            ))}
          </ul>
        )}
      </Section>

      {editing && <EditClientModal client={client} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); load(); }} />}
    </div>
  );
}

function ChargeRow({
  c,
  onProtest,
  onReschedule,
}: {
  c: Charge;
  onProtest: (id: string) => void;
  onReschedule: (id: string, due: string) => void;
}) {
  const [due, setDue] = useState(c.due_date);
  const [showDate, setShowDate] = useState(false);
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-3">
      <div className="min-w-0">
        <p className="font-medium text-neutral-800">
          {brl(c.amount_cents)}
          {c.protested_at && (
            <span className="ml-2 rounded-pill bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-danger">PROTESTADA</span>
          )}
        </p>
        <p className="text-xs text-neutral-400">
          {c.description || "Cobrança"} · vence {dt(c.due_date)}
        </p>
      </div>
      <div className="flex items-center gap-2">
        {c.status === "paid" ? (
          <span className="rounded-pill bg-accent-50 px-2 py-0.5 text-xs text-accent-700">Pago</span>
        ) : c.status === "canceled" ? (
          <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">Cancelada</span>
        ) : (
          <>
            {c.is_overdue && <span className="rounded-pill bg-red-50 px-2 py-0.5 text-xs text-danger">Vencida</span>}
            {showDate ? (
              <span className="flex items-center gap-1">
                <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="rounded-lg border border-neutral-200 px-2 py-1 text-xs outline-none" />
                <button onClick={() => { onReschedule(c.id, due); setShowDate(false); }} className="text-xs font-medium text-primary-600">OK</button>
              </span>
            ) : (
              <button onClick={() => setShowDate(true)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">Trocar venc.</button>
            )}
            {c.is_overdue && !c.protested_at && (
              <button onClick={() => onProtest(c.id)} className="flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-danger">
                <Gavel size={12} /> Protestar
              </button>
            )}
            <span className="text-[11px] text-neutral-300">aguardando pgto</span>
          </>
        )}
      </div>
    </li>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    draft: "bg-neutral-100 text-neutral-500",
    sent: "bg-blue-50 text-blue-700",
    approved: "bg-accent-50 text-accent-700",
    signed: "bg-accent-50 text-accent-700",
    rejected: "bg-red-50 text-danger",
    cancelled: "bg-red-50 text-danger",
  };
  const label: Record<string, string> = {
    draft: "Rascunho", sent: "Enviado", approved: "Aprovado", signed: "Assinado",
    rejected: "Recusado", cancelled: "Cancelado",
  };
  return <span className={`rounded-pill px-2 py-0.5 text-xs ${map[status] ?? "bg-neutral-100"}`}>{label[status] ?? status}</span>;
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h2 className="mb-2 flex items-center gap-2 font-semibold text-neutral-800">
        {icon} {title}
      </h2>
      {children}
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
function Empty({ text }: { text: string }) {
  return <p className="py-4 text-center text-sm text-neutral-400">{text}</p>;
}

function EditClientModal({
  client,
  onClose,
  onSaved,
}: {
  client: Client;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(client.name);
  const [email, setEmail] = useState(client.email ?? "");
  const [phone, setPhone] = useState(client.phone ?? "");
  const [document, setDocument] = useState(client.document ?? "");
  const [notes, setNotes] = useState(client.notes);
  const [tags, setTags] = useState(client.tags.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.patch(`/crm/clients/${client.id}`, {
        name,
        email: email || null,
        phone: phone || null,
        document: document || null,
        notes,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-card" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-lg font-bold text-neutral-800">Editar cliente</h3>
        <div className="space-y-3">
          <Input label="Nome" value={name} onChange={setName} />
          <Input label="E-mail" value={email} onChange={setEmail} />
          <Input label="Telefone" value={phone} onChange={setPhone} />
          <Input label="CPF/CNPJ" value={document} onChange={setDocument} />
          <Input label="Tags (separadas por vírgula)" value={tags} onChange={setTags} />
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Observações</span>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
          </label>
          {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
          <div className="flex gap-2">
            <button onClick={onClose} className="flex-1 rounded-pill bg-neutral-100 py-2.5 font-semibold text-neutral-600 hover:bg-neutral-200">Cancelar</button>
            <button onClick={save} disabled={saving || !name.trim()} className="flex-1 rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
              {saving ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (s: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
    </label>
  );
}
