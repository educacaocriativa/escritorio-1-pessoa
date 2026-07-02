import type { CockpitSummary } from "@e1p/shared-types";
import { AlertTriangle, CalendarDays, FileSignature, Sparkles, TrendingUp, Wallet } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import Modal from "../../components/Modal";
import { api } from "../../lib/api";
import { useAuth } from "../../store/auth";

const EMPTY: CockpitSummary = {
  agenda: { today_count: 0, today_events: [], upcoming_critical: [] },
  crm: { total_clients: 0, won_count: 0, lost_count: 0, conversion_rate: 0, by_stage: [] },
  finance: { available: false, net_revenue_cents: null, monthly_costs_cents: null, signed_contracts: null },
  overdue: [],
};

export default function CockpitPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<CockpitSummary>(EMPTY);
  const [collecting, setCollecting] = useState<string | null>(null);
  const [aiMessage, setAiMessage] = useState<string | null>(null);

  useEffect(() => {
    const day = new Date().toISOString().slice(0, 10);
    api
      .get<CockpitSummary>(`/cockpit/summary?day=${day}`)
      // mescla sobre os defaults: uma resposta parcial/antiga nunca derruba a tela toda
      .then(({ data }) => setSummary({ ...EMPTY, ...data }))
      .catch(() => setSummary(EMPTY));
  }, []);

  async function collect(chargeId: string) {
    setCollecting(chargeId);
    try {
      const { data } = await api.post<{ message: string }>(
        `/receivables/charges/${chargeId}/collect`,
      );
      setAiMessage(data.message);
    } finally {
      setCollecting(null);
    }
  }

  const conv = `${Math.round((summary.crm?.conversion_rate ?? 0) * 100)}%`;
  const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const faturamento = summary.finance?.net_revenue_cents != null
    ? brl(summary.finance.net_revenue_cents)
    : "R$ —";

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Cockpit</p>
        <h1 className="text-2xl font-bold text-neutral-800">
          Bom dia, {user?.name?.split(" ")[0] ?? ""} 👋
        </h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Faturamento Líquido" value={faturamento} hint="carteira" tone="accent" icon={Wallet} />
        <StatCard label="Contratos Assinados" value="—" hint="Fase 2" tone="primary" icon={FileSignature} />
        <StatCard label="Taxa de Conversão" value={conv} hint="funil do CRM" tone="info" icon={TrendingUp} />
        <StatCard
          label="Compromissos Hoje"
          value={String(summary.agenda.today_count)}
          hint="agenda"
          tone="primary"
          icon={CalendarDays}
        />
      </div>

      {summary.overdue.length > 0 && (
        <div className="rounded-2xl border border-red-100 bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <AlertTriangle size={18} className="text-danger" />
            <h2 className="font-semibold text-neutral-800">
              Clientes em atraso ({summary.overdue.length})
            </h2>
          </div>
          <ul className="divide-y divide-neutral-100">
            {summary.overdue.map((o) => (
              <li key={o.charge_id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <span className="font-medium text-neutral-800">{o.client_name}</span>
                  {o.description && o.description !== o.client_name && (
                    <span className="ml-2 text-xs text-neutral-500">{o.description}</span>
                  )}
                  <span className="block text-xs text-neutral-400">
                    {brl(o.amount_cents)} · venceu {new Date(o.due_date + "T00:00").toLocaleDateString("pt-BR")}
                  </span>
                </div>
                <button
                  onClick={() => collect(o.charge_id)}
                  disabled={collecting === o.charge_id}
                  className="flex shrink-0 items-center gap-1.5 rounded-pill bg-primary-500 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-primary-600 disabled:opacity-60"
                >
                  <Sparkles size={13} />
                  {collecting === o.charge_id ? "Escrevendo..." : "Cobrar com IA"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Modal title="Cobrança enviada pela IA" open={aiMessage !== null} onClose={() => setAiMessage(null)}>
        <p className="rounded-lg bg-neutral-50 p-3 text-sm text-neutral-700">{aiMessage}</p>
        <p className="mt-3 text-xs text-neutral-400">
          Mensagem registrada para envio no WhatsApp do cliente.
        </p>
      </Modal>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Agenda do dia">
          {summary.agenda.today_events.length === 0 ? (
            <Empty text="Sem compromissos para hoje." />
          ) : (
            <ul className="divide-y divide-neutral-100">
              {summary.agenda.today_events.map((e) => (
                <li key={e.id} className="py-2 text-sm text-neutral-700">
                  {e.title}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Funil (CRM)">
          {summary.crm.by_stage.length === 0 ? (
            <Empty text="Nenhum cliente no funil ainda." />
          ) : (
            <ul className="space-y-2">
              {summary.crm.by_stage.map((s) => (
                <li key={s.stage_id} className="flex items-center justify-between text-sm">
                  <span className="text-neutral-600">{s.name}</span>
                  <span className="font-semibold text-neutral-800">{s.count}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

const tones = {
  accent: "bg-accent-50 text-accent-700",
  primary: "bg-primary-50 text-primary-700",
  info: "bg-blue-50 text-blue-700",
} as const;

function StatCard({
  label,
  value,
  hint,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint: string;
  tone: keyof typeof tones;
  icon: typeof Wallet;
}) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className={`mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg ${tones[tone]}`}>
        <Icon size={18} />
      </div>
      <p className="text-sm text-neutral-500">{label}</p>
      <p className="text-2xl font-bold text-neutral-800">{value}</p>
      <p className="text-xs text-neutral-400">{hint}</p>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h2 className="mb-3 font-semibold text-neutral-800">{title}</h2>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="py-8 text-center text-sm text-neutral-400">{text}</p>;
}
