import type { Client, FunnelRun, FunnelRunSummary } from "@e1p/shared-types";
import { Clock, Play, UserPlus, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

type Notify = (msg: string, type?: "ok" | "err") => void;

// Campos lidos pelo motor, dependentes do tipo de nó.
type ConfigPatch = {
  delay_value?: number; delay_unit?: "minutes" | "hours" | "days";
  field?: "always" | "has_tag" | "is_paid"; value?: string;
  amount_cents?: number; method?: "boleto" | "pix"; tag?: string;
};
type NodeLike = {
  key: string; action?: string;
  config?: ConfigPatch & { [k: string]: unknown };
};

const STATUS_LABEL: Record<string, string> = {
  running: "Executando", waiting: "Aguardando", done: "Concluída",
  failed: "Falhou", cancelled: "Cancelada",
};
const STATUS_COLOR: Record<string, string> = {
  running: "bg-blue-100 text-blue-700", waiting: "bg-amber-100 text-amber-700",
  done: "bg-emerald-100 text-emerald-700", failed: "bg-red-100 text-danger",
  cancelled: "bg-neutral-100 text-neutral-500",
};

/** Campos de automação no painel do nó: espera, condição, valor e tag. */
export function AutomationFields({
  data,
  onChange,
}: {
  data: NodeLike;
  onChange: (patch: ConfigPatch) => void;
}) {
  const cfg = data.config ?? {};
  const key = data.key;
  const action = data.action ?? "";

  if (key === "esperar") {
    return (
      <Box label="Esperar antes de seguir">
        <div className="flex gap-2">
          <input
            type="number" min={0} value={cfg.delay_value ?? ""}
            onChange={(e) => onChange({ delay_value: Number(e.target.value) })}
            placeholder="0"
            className="w-20 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none"
          />
          <select
            value={cfg.delay_unit ?? "minutes"}
            onChange={(e) => onChange({ delay_unit: e.target.value as ConfigPatch["delay_unit"] })}
            className="flex-1 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm"
          >
            <option value="minutes">minutos</option>
            <option value="hours">horas</option>
            <option value="days">dias</option>
          </select>
        </div>
      </Box>
    );
  }

  if (key === "se-ou") {
    return (
      <Box label="Condição (ramo Sim / Não)">
        <select
          value={cfg.field ?? "always"}
          onChange={(e) => onChange({ field: e.target.value as ConfigPatch["field"] })}
          className="mb-2 w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm"
        >
          <option value="always">Sempre (Sim)</option>
          <option value="has_tag">Contato tem a tag…</option>
          <option value="is_paid">Contato já pagou alguma cobrança</option>
        </select>
        {cfg.field === "has_tag" && (
          <input
            value={cfg.value ?? ""}
            onChange={(e) => onChange({ value: e.target.value })}
            placeholder="nome da tag"
            className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none"
          />
        )}
      </Box>
    );
  }

  if (action === "add_tag") {
    return (
      <Box label="Tag a aplicar">
        <input
          value={cfg.tag ?? ""}
          onChange={(e) => onChange({ tag: e.target.value })}
          placeholder="ex: lead-quente"
          className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none"
        />
      </Box>
    );
  }

  if (action === "create_charge" || action === "create_quote") {
    const reais = cfg.amount_cents ? (cfg.amount_cents / 100).toString() : "";
    return (
      <Box label={action === "create_charge" ? "Cobrança automática" : "Proposta automática"}>
        <input
          inputMode="decimal" value={reais}
          onChange={(e) =>
            onChange({ amount_cents: Math.round(parseFloat(e.target.value.replace(",", ".") || "0") * 100) })
          }
          placeholder="Valor (R$)"
          className="mb-2 w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none"
        />
        {action === "create_charge" && (
          <select
            value={cfg.method ?? "boleto"}
            onChange={(e) => onChange({ method: e.target.value as ConfigPatch["method"] })}
            className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm"
          >
            <option value="boleto">Boleto</option>
            <option value="pix">Pix</option>
          </select>
        )}
      </Box>
    );
  }

  return null;
}

function Box({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2 rounded-lg bg-primary-50/60 p-2">
      <p className="mb-1.5 flex items-center gap-1 text-xs font-semibold text-primary-700">
        <Clock size={12} /> {label}
      </p>
      {children}
    </div>
  );
}

/** Drawer lateral: inscrever contato, listar jornadas e rodar o agendador. */
export function FunnelAutomationDrawer({
  funnelId,
  onClose,
  onNotify,
}: {
  funnelId: string;
  onClose: () => void;
  onNotify: Notify;
}) {
  const [runs, setRuns] = useState<FunnelRunSummary[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [open, setOpen] = useState<FunnelRun | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get<FunnelRunSummary[]>(`/funnels/${funnelId}/runs`);
    setRuns(data);
  }, [funnelId]);

  useEffect(() => {
    load();
    api.get<Client[]>("/crm/clients").then(({ data }) => setClients(data));
  }, [load]);

  async function enroll() {
    setBusy(true);
    try {
      await api.post(`/funnels/${funnelId}/enroll`, { client_id: clientId || null });
      onNotify("Contato inscrito no funil");
      setClientId("");
      load();
    } catch (e) {
      onNotify(apiErrorMessage(e), "err");
    } finally {
      setBusy(false);
    }
  }

  async function tick() {
    setBusy(true);
    try {
      const { data } = await api.post<{ resumed: number }>("/funnels/runs/tick");
      onNotify(data.resumed > 0 ? `${data.resumed} jornada(s) avançaram` : "Nada pendente agora");
      load();
    } catch (e) {
      onNotify(apiErrorMessage(e), "err");
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: string) {
    await api.post(`/funnels/runs/${id}/cancel`);
    onNotify("Jornada cancelada");
    load();
  }

  return (
    <div className="absolute right-0 top-0 z-20 flex h-full w-96 flex-col border-l border-neutral-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-neutral-100 p-4">
        <h3 className="flex items-center gap-2 text-sm font-bold text-neutral-800">
          <Play size={15} className="text-primary-600" /> Automação do funil
        </h3>
        <button onClick={onClose} className="text-neutral-400 hover:text-neutral-700">
          <X size={18} />
        </button>
      </div>

      <div className="space-y-2 border-b border-neutral-100 p-4">
        <p className="text-xs font-medium text-neutral-600">Inscrever contato (dispara o funil)</p>
        <div className="flex gap-2">
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm"
          >
            <option value="">— Selecione —</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <button
            onClick={enroll}
            disabled={busy || !clientId}
            className="flex shrink-0 items-center gap-1 rounded-pill bg-primary-500 px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-600 disabled:opacity-50"
          >
            <UserPlus size={14} /> Inscrever
          </button>
        </div>
        <button
          onClick={tick}
          disabled={busy}
          className="flex w-full items-center justify-center gap-1.5 rounded-pill bg-neutral-100 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-200 disabled:opacity-50"
        >
          <Clock size={14} /> Processar esperas agora
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        <p className="mb-2 text-xs font-medium text-neutral-600">Jornadas ({runs.length})</p>
        {runs.length === 0 ? (
          <p className="text-xs text-neutral-400">Nenhuma jornada ainda. Inscreva um contato.</p>
        ) : (
          <ul className="space-y-2">
            {runs.map((r) => (
              <li key={r.id} className="rounded-xl border border-neutral-100 p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <button
                    onClick={() =>
                      api.get<FunnelRun>(`/funnels/runs/${r.id}`).then(({ data }) => setOpen(data))
                    }
                    className="min-w-0 flex-1 text-left"
                  >
                    <p className="truncate text-sm font-medium text-neutral-700">
                      {r.client_name ?? "Sem contato"}
                    </p>
                    <p className="text-[11px] text-neutral-400">{r.step_count} passo(s)</p>
                  </button>
                  <span className={`rounded-pill px-2 py-0.5 text-[11px] font-semibold ${STATUS_COLOR[r.status]}`}>
                    {STATUS_LABEL[r.status] ?? r.status}
                  </span>
                </div>
                {(r.status === "waiting" || r.status === "running") && (
                  <button
                    onClick={() => cancel(r.id)}
                    className="mt-1.5 text-[11px] text-neutral-400 hover:text-danger"
                  >
                    cancelar
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {open && (
        <div className="absolute inset-0 z-30 flex flex-col bg-white">
          <div className="flex items-center justify-between border-b border-neutral-100 p-4">
            <h4 className="text-sm font-bold text-neutral-800">Linha do tempo da jornada</h4>
            <button onClick={() => setOpen(null)} className="text-neutral-400 hover:text-neutral-700">
              <X size={18} />
            </button>
          </div>
          <div className="flex-1 overflow-auto p-4">
            <p className="mb-3 text-xs text-neutral-500">
              {open.client_name ?? "Sem contato"} ·{" "}
              <span className="font-semibold">{STATUS_LABEL[open.status] ?? open.status}</span>
              {open.error ? ` · ${open.error}` : ""}
            </p>
            <ol className="space-y-2">
              {open.steps.map((s, i) => (
                <li key={i} className="flex gap-2 text-xs">
                  <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${
                    s.status === "failed" ? "bg-danger" : s.status === "ok" ? "bg-emerald-500" : "bg-neutral-300"
                  }`} />
                  <div>
                    <p className="font-medium text-neutral-700">{s.key || s.action || "nó"}</p>
                    <p className="text-neutral-500">{s.message}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </div>
  );
}
