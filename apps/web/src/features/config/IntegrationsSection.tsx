import type { IntegrationKey, IntegrationKeyCreated } from "@e1p/shared-types";
import { Check, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

function publicCaptureUrl(rawKey: string): string {
  // Mesma convenção do `api` client (baseURL "/api"): em dev o Vite faz proxy /api -> :8000; em
  // produção o reverse proxy expõe a API sob o mesmo domínio em /api (ver docs/HOSTINGER-DEPLOY.md).
  return `${window.location.origin}/api/public/leads/${rawKey}`;
}

function snippetFor(rawKey: string): string {
  const url = publicCaptureUrl(rawKey);
  return `fetch("${url}", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name, email, phone }),
});`;
}

export default function IntegrationsSection() {
  const [keys, setKeys] = useState<IntegrationKey[]>([]);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<IntegrationKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<IntegrationKey[]>("/integrations/leads/keys");
    setKeys(Array.isArray(data) ? data : []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function create() {
    if (!label.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const { data } = await api.post<IntegrationKeyCreated>("/integrations/leads/keys", {
        label: label.trim(),
      });
      setCreated(data);
      setLabel("");
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: string) {
    if (!confirm("Revogar esta chave? Sites que a usam param de conseguir enviar leads.")) return;
    await api.post(`/integrations/leads/keys/${id}/revoke`);
    await load();
  }

  function copy(text: string) {
    navigator.clipboard?.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl bg-white p-5 shadow-sm">
        <h2 className="mb-1 font-semibold text-neutral-800">Integrações</h2>
        <p className="mb-4 text-xs text-neutral-400">
          Gere uma chave para o formulário de um site externo (ex.: a landing page de um cliente)
          enviar leads direto pra este CRM — cada lead entra com <code>source=api</code> e, se
          houver um Funil de entrada padrão configurado, já nasce inscrito nele.
        </p>

        <div className="mb-4 flex gap-2">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Nome da chave (ex.: Site Dóro Eventos)"
            className="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
          <button
            onClick={create}
            disabled={creating || !label.trim()}
            className="flex items-center gap-1.5 rounded-pill bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Plus size={14} /> Nova chave
          </button>
        </div>
        {error && <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}

        {created && (
          <div className="mb-4 rounded-xl border border-primary-200 bg-primary-50 p-4">
            <p className="mb-2 text-sm font-semibold text-primary-700">
              Chave criada — copie agora, ela não aparece de novo:
            </p>
            <div className="mb-3 flex items-center gap-2">
              <code className="flex-1 truncate rounded-lg bg-white px-3 py-2 text-xs">
                {created.raw_key}
              </code>
              <button
                onClick={() => copy(created.raw_key)}
                className="flex items-center gap-1 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-600 hover:bg-neutral-50"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />} Copiar
              </button>
            </div>
            <p className="mb-1 text-xs text-neutral-500">
              Repasse este exemplo pra quem cuida do site externo:
            </p>
            <div className="flex items-start gap-2">
              <pre className="flex-1 overflow-x-auto rounded-lg bg-neutral-900 p-3 text-xs text-neutral-100">
                {snippetFor(created.raw_key)}
              </pre>
              <button
                onClick={() => copy(snippetFor(created.raw_key))}
                className="rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs font-semibold text-neutral-600 hover:bg-neutral-50"
              >
                <Copy size={14} />
              </button>
            </div>
          </div>
        )}

        {keys.length === 0 ? (
          <p className="text-sm text-neutral-400">Nenhuma chave criada ainda.</p>
        ) : (
          <div className="space-y-2">
            {keys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between rounded-xl border border-neutral-100 px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-50 text-primary-600">
                    <KeyRound size={16} />
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-neutral-800">{k.label}</p>
                    <p className="text-xs text-neutral-400">
                      {k.key_prefix}••••••••
                      {k.revoked_at && <span className="ml-2 text-danger">revogada</span>}
                    </p>
                  </div>
                </div>
                {!k.revoked_at && (
                  <button
                    onClick={() => revoke(k.id)}
                    className="text-neutral-300 hover:text-danger"
                    title="Revogar"
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
