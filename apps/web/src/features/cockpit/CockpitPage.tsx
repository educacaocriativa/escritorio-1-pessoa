import type { CockpitSummary } from "@e1p/shared-types";
import { CalendarDays, FileSignature, TrendingUp, Wallet } from "lucide-react";

/**
 * Cockpit (Dashboard de Entrada) — módulo 19. Mostra o resumo do dia agregando Agenda + CRM.
 * O backend expõe GET /cockpit/summary; o fetch real entra com o login. Aqui um resumo vazio
 * ilustra a estrutura. Indicadores financeiros ficam "—" até a Fase 2.
 */
export default function CockpitPage() {
  const summary: CockpitSummary = {
    agenda: { today_count: 0, today_events: [], upcoming_critical: [] },
    crm: { total_clients: 0, won_count: 0, lost_count: 0, conversion_rate: 0, by_stage: [] },
    finance: { available: false, net_revenue_cents: null, monthly_costs_cents: null, signed_contracts: null },
  };

  const conv = `${Math.round(summary.crm.conversion_rate * 100)}%`;

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Cockpit</p>
        <h1 className="text-2xl font-bold text-neutral-800">Bom dia 👋</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Faturamento Líquido" value="R$ —" hint="Fase 2" tone="accent" icon={Wallet} />
        <StatCard label="Contratos Assinados" value="—" hint="Fase 2" tone="primary" icon={FileSignature} />
        <StatCard label="Taxa de Conversão" value={conv} hint="funil do CRM" tone="info" icon={TrendingUp} />
        <StatCard label="Compromissos Hoje" value={String(summary.agenda.today_count)} hint="agenda" tone="primary" icon={CalendarDays} />
      </div>

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

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
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
