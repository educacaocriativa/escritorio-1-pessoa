import type { Clause, Client, Contract, ContractTemplate } from "@e1p/shared-types";
import { ArrowLeft, Eye, GripVertical, Plus, Save, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";

const AUTO_VARS = new Set(["CLIENTE", "DATA", "EMPRESA"]);
const today = () => new Date().toLocaleDateString("pt-BR");

export default function ContractBuilderPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id || id === "novo";

  const [contractId, setContractId] = useState<string | null>(isNew ? null : id!);
  const [slug, setSlug] = useState<string | null>(null);
  const [status, setStatus] = useState<Contract["status"]>("draft");
  const [title, setTitle] = useState("");
  const [clientId, setClientId] = useState("");
  const [clauses, setClauses] = useState<Clause[]>([{ title: "", text: "" }]);
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [clients, setClients] = useState<Client[]>([]);
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    api.get<Client[]>("/crm/clients").then(({ data }) => setClients(data));
    api.get<ContractTemplate[]>("/contracts/templates").then(({ data }) => setTemplates(data));
  }, []);

  const hydrate = useCallback((c: Contract) => {
    setContractId(c.id);
    setSlug(c.public_slug);
    setStatus(c.status);
    setTitle(c.title);
    setClientId(c.client_id ?? "");
    setClauses(c.clauses.length ? c.clauses : [{ title: "", text: "" }]);
  }, []);

  useEffect(() => {
    if (!isNew && id) api.get<Contract>(`/contracts/${id}`).then(({ data }) => hydrate(data));
  }, [isNew, id, hydrate]);

  // Detecta variáveis [TOKEN] nas cláusulas (exceto as automáticas).
  const tokens = useMemo(() => {
    const found = new Set<string>();
    for (const c of clauses) {
      for (const m of c.text.matchAll(/\[([A-Z_]+)\]/g)) {
        if (!AUTO_VARS.has(m[1])) found.add(m[1]);
      }
    }
    return [...found];
  }, [clauses]);

  const clientName = clients.find((c) => c.id === clientId)?.name ?? "[CLIENTE]";

  function substitute(text: string): string {
    let out = text
      .replaceAll("[CLIENTE]", clientName)
      .replaceAll("[DATA]", today())
      .replaceAll("[EMPRESA]", "sua empresa");
    for (const [k, v] of Object.entries(variables)) {
      if (v) out = out.replaceAll(`[${k}]`, v);
    }
    return out;
  }

  function setClause(i: number, patch: Partial<Clause>) {
    setClauses((cs) => cs.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }
  function drop(target: number) {
    if (dragIdx === null || dragIdx === target) return;
    setClauses((cs) => {
      const next = [...cs];
      const [moved] = next.splice(dragIdx, 1);
      next.splice(target, 0, moved);
      return next;
    });
    setDragIdx(null);
  }

  function loadTemplate(tplId: string) {
    const tpl = templates.find((t) => t.id === tplId);
    if (tpl) setClauses(tpl.clauses.map((c) => ({ ...c })));
  }

  async function save(): Promise<string | null> {
    const valid = clauses.filter((c) => c.text.trim());
    if (!title.trim() || valid.length === 0) {
      setError("Informe um título e ao menos uma cláusula.");
      return null;
    }
    setSaving(true);
    setError(null);
    try {
      let c: Contract;
      if (contractId) {
        c = (await api.patch<Contract>(`/contracts/${contractId}`, {
          title,
          client_id: clientId || null,
          clauses: valid,
        })).data;
      } else {
        c = (await api.post<Contract>("/contracts", {
          title,
          client_id: clientId || null,
          clauses: valid,
          variables,
        })).data;
        window.history.replaceState(null, "", `/contratos/${c.id}`);
      }
      hydrate(c);
      setSavedAt(new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }));
      return c.id;
    } catch (err) {
      setError(apiErrorMessage(err));
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function send() {
    const savedId = contractId ?? (await save());
    if (!savedId) return;
    try {
      const { data } = await api.post<Contract>(`/contracts/${savedId}/send`);
      setStatus(data.status);
      setSavedAt("enviado");
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function view() {
    const savedId = await save();
    if (savedId && slug) window.open(`/contrato/${slug}`, "_blank");
  }

  const readonly = status !== "draft";

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <button onClick={() => navigate("/contratos")} className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-700">
          <ArrowLeft size={16} /> Contratos
        </button>
        <div className="flex items-center gap-2">
          <button onClick={send} disabled={saving || readonly} className="flex items-center gap-1.5 rounded-pill bg-primary-500 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-600 disabled:opacity-50">
            <Send size={14} /> Enviar
          </button>
          <button onClick={view} disabled={saving} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-4 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-200 disabled:opacity-50">
            <Eye size={14} /> Ver
          </button>
          <button onClick={save} disabled={saving || readonly} className="flex items-center gap-1.5 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-50">
            <Save size={14} /> {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>

      {readonly && (
        <div className="mb-3 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-700">
          Contrato <b>{status}</b> — não pode mais ser editado.
        </div>
      )}
      {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
      {savedAt && !error && (
        <div className="mb-3 text-xs text-neutral-400">
          {savedAt === "enviado" ? "Enviado ao cliente para assinatura." : `Salvo às ${savedAt}.`}
          {slug && (
            <a href={`/contrato/${slug}`} target="_blank" rel="noreferrer" className="ml-2 text-primary-600">
              link de assinatura
            </a>
          )}
        </div>
      )}

      <div className="grid flex-1 grid-cols-1 gap-6 overflow-hidden lg:grid-cols-2">
        {/* Editor */}
        <div className={`flex flex-col gap-3 overflow-auto rounded-2xl bg-white p-4 shadow-sm ${readonly ? "pointer-events-none opacity-60" : ""}`}>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Título do contrato" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm font-medium outline-none focus:border-primary-400" />

          <div className="flex gap-2">
            <select value={clientId} onChange={(e) => setClientId(e.target.value)} className="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              <option value="">Sem cliente</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            {isNew && (
              <select onChange={(e) => e.target.value && loadTemplate(e.target.value)} defaultValue="" className="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
                <option value="">Usar template...</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            )}
          </div>

          {tokens.length > 0 && (
            <div className="rounded-lg bg-primary-50 p-3">
              <p className="mb-2 text-xs font-medium text-primary-700">Preencher variáveis</p>
              <div className="grid grid-cols-2 gap-2">
                {tokens.map((tk) => (
                  <input
                    key={tk}
                    value={variables[tk] ?? ""}
                    onChange={(e) => setVariables((v) => ({ ...v, [tk]: e.target.value }))}
                    placeholder={tk}
                    className="rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none"
                  />
                ))}
              </div>
            </div>
          )}

          <p className="text-xs font-medium text-neutral-500">Cláusulas (arraste para reordenar)</p>
          {clauses.map((c, i) => (
            <div
              key={i}
              draggable
              onDragStart={() => setDragIdx(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => drop(i)}
              className="flex gap-2 rounded-xl border border-neutral-100 bg-white p-3"
            >
              <GripVertical size={16} className="mt-1 shrink-0 cursor-grab text-neutral-300" />
              <div className="flex-1 space-y-2">
                <input value={c.title} onChange={(e) => setClause(i, { title: e.target.value })} placeholder="Título da cláusula" className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm font-medium outline-none" />
                <textarea value={c.text} onChange={(e) => setClause(i, { text: e.target.value })} rows={3} placeholder="Texto da cláusula (use [VALOR], [OBJETO]... como variáveis)" className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
              </div>
              {clauses.length > 1 && (
                <button onClick={() => setClauses((cs) => cs.filter((_, idx) => idx !== i))} className="text-neutral-300 hover:text-danger">
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
          <button onClick={() => setClauses((cs) => [...cs, { title: "", text: "" }])} className="flex items-center gap-1 text-sm font-medium text-primary-600">
            <Plus size={14} /> Adicionar cláusula
          </button>
        </div>

        {/* Prévia */}
        <div className="overflow-auto rounded-2xl border border-neutral-100 bg-neutral-50 p-4">
          <p className="mb-2 text-center text-xs uppercase tracking-wide text-neutral-400">Pré-visualização</p>
          <div className="rounded-2xl bg-white p-6 shadow-sm">
            <h1 className="mb-5 text-xl font-bold text-neutral-800">{title || "Contrato"}</h1>
            <div className="space-y-4">
              {clauses.filter((c) => c.text.trim()).map((c, i) => (
                <div key={i}>
                  {c.title && (
                    <h2 className="text-sm font-bold uppercase tracking-wide text-neutral-500">
                      {i + 1}. {c.title}
                    </h2>
                  )}
                  <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-neutral-700">
                    {substitute(c.text)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
