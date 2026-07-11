/**
 * Diagnóstico financeiro (Story 5.8) — tipos + lógica PURA usada pela DiagnosticoPage.
 *
 * Princípio central da story: os SINAIS 🟢🟡🔴 são determinísticos (motor puro no backend) e vêm
 * SEMPRE, com ou sem IA. A `narrative` é a leitura em linguagem natural — gerada pela IA quando
 * disponível (`narrative_source === "ai"`) ou por um fallback de template (`"template"`). A UI
 * mostra os sinais primeiro e a narrativa num bloco visualmente distinto, reforçando que os números
 * vêm antes da IA. A lógica pura vive aqui (testável) porque o projeto não tem infra de teste de
 * componente React — mesmo padrão de projecao.ts / dre.ts.
 */

export type SignalLevel = "verde" | "amarelo" | "vermelho";

export interface Signal {
  level: SignalLevel;
  title: string;
  explanation: string;
  source: string;
}

export interface Diagnostics {
  start: string;
  end: string;
  signals: Signal[];
  narrative: string;
  narrative_source: "ai" | "template";
}

export interface SignalVisual {
  emoji: string;
  label: string;
  /** Classes Tailwind do "selo" do sinal (borda/fundo/texto), no design "Portal". */
  badgeClass: string;
  cardClass: string;
}

const _VISUALS: Record<SignalLevel, SignalVisual> = {
  vermelho: {
    emoji: "🔴",
    label: "Crítico",
    badgeClass: "bg-red-100 text-red-700",
    cardClass: "bg-red-50 ring-1 ring-red-200",
  },
  amarelo: {
    emoji: "🟡",
    label: "Atenção",
    badgeClass: "bg-amber-100 text-amber-700",
    cardClass: "bg-amber-50 ring-1 ring-amber-200",
  },
  verde: {
    emoji: "🟢",
    label: "Saudável",
    badgeClass: "bg-emerald-100 text-emerald-700",
    cardClass: "bg-emerald-50 ring-1 ring-emerald-200",
  },
};

/** Config visual de um nível de sinal. Puro (sem DOM) → testável. */
export function signalVisual(level: SignalLevel): SignalVisual {
  return _VISUALS[level];
}

/** Contagem de sinais por nível — usado no resumo do topo. Puro. */
export function countByLevel(signals: Signal[]): Record<SignalLevel, number> {
  const counts: Record<SignalLevel, number> = { vermelho: 0, amarelo: 0, verde: 0 };
  for (const s of signals) counts[s.level] += 1;
  return counts;
}

/** Rótulo humano da origem do sinal (source do backend → texto PT-BR). Puro. */
export function sourceLabel(source: string): string {
  switch (source) {
    case "lucratividade":
      return "Lucratividade por contrato";
    case "projecao":
      return "Projeção de caixa";
    case "investimento":
      return "Investimentos";
    default:
      return source;
  }
}

/** Primeiro/último dia do mês "YYYY-MM" (bordas de data de calendário, sem depender de fuso). */
export function monthRange(month: string): { start: string; end: string } {
  const [y, m] = month.split("-").map(Number);
  const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return { start: `${month}-01`, end: `${month}-${String(lastDay).padStart(2, "0")}` };
}

/** Mês atual no formato "YYYY-MM". */
export function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
