import { FileSignature, TrendingUp, Wallet } from "lucide-react";

/**
 * Cockpit (Dashboard de Entrada) — módulo 19. Esqueleto com os 4 indicadores de topo
 * descritos na spec. Os dados reais entram quando os módulos financeiros existirem.
 */
export default function CockpitPage() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Cockpit</p>
        <h1 className="text-2xl font-bold text-neutral-800">Bom dia 👋</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Faturamento Líquido" value="R$ —" hint="mês atual" tone="accent" icon={Wallet} />
        <StatCard label="Contratos Assinados" value="—" hint="mês atual" tone="primary" icon={FileSignature} />
        <StatCard label="Taxa de Conversão" value="—%" hint="funil" tone="info" icon={TrendingUp} />
        <StatCard label="Custos do Mês" value="R$ —" hint="a pagar + estoque" tone="danger" icon={Wallet} />
      </div>

      <div className="rounded-2xl border border-dashed border-neutral-200 bg-white p-10 text-center text-neutral-400">
        Os blocos do Cockpit (agenda do dia, fluxo de caixa, diagnóstico da IA) aparecem aqui
        conforme os módulos forem construídos.
      </div>
    </div>
  );
}

const tones = {
  accent: "bg-accent-50 text-accent-700",
  primary: "bg-primary-50 text-primary-700",
  info: "bg-blue-50 text-blue-700",
  danger: "bg-red-50 text-danger",
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
