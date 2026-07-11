/**
 * Projeção de fluxo de caixa 30/60/90 + runway (Story 5.7) — tipos + lógica PURA usada pela
 * ProjecaoCaixaPage.
 *
 * Regime de CAIXA (oposto da DRE): o backend já projeta o saldo por janela usando a data de
 * pagamento prevista (vencimento dos itens em aberto), nunca a competência. Aqui só derivamos a
 * exibição — a trajetória para o gráfico e o rótulo "meses e dias" do runway. A lógica vive aqui
 * (pura, testável) porque o projeto não tem infra de teste de componente React — mesmo padrão de
 * dre.ts / planoContas.ts. `formatBRL` é reusado de dre.ts (DRY).
 */
export { formatBRL } from "./dre";

export interface ProjectionWindow {
  days: number;
  saldo_projetado_cents: number;
  alert: boolean;
}

export interface Runway {
  days: number | null;
  burn_rate_cents_per_day: number;
}

export interface Projection {
  today: string;
  saldo_inicial_cents: number;
  // Parcela de itens em aberto JÁ VENCIDOS (atraso/inadimplência) contada como caixa esperado
  // imediato — já embutida em todas as janelas; exposta à parte para sinalizar a incerteza
  // (recebíveis vencidos podem não chegar).
  overdue_inflow_cents: number;
  overdue_outflow_cents: number;
  windows: ProjectionWindow[];
  runway: Runway;
  notes: string[];
}

export interface TrajectoryPoint {
  days: number; // 0 = hoje (saldo inicial)
  saldo_cents: number;
}

/**
 * Pontos da trajetória do saldo: hoje (dia 0 = saldo inicial) seguido de cada janela projetada.
 * É o que o gráfico de linha desenha — mostra a queda/subida do caixa ao longo do horizonte.
 */
export function trajectoryPoints(p: Projection): TrajectoryPoint[] {
  return [
    { days: 0, saldo_cents: p.saldo_inicial_cents },
    ...p.windows.map((w) => ({ days: w.days, saldo_cents: w.saldo_projetado_cents })),
  ];
}

/**
 * Converte a trajetória em coordenadas de uma polyline SVG (string "x,y x,y ..."), normalizando os
 * valores de saldo no eixo Y do viewBox. Puro (sem DOM) → testável. O eixo X é proporcional aos
 * dias; o Y inverte (SVG cresce para baixo) e reserva `padding` nas bordas. Quando todos os valores
 * são iguais (faixa zero), a linha fica na horizontal central — sem divisão por zero.
 */
export function toPolylinePoints(
  points: TrajectoryPoint[],
  opts: { width: number; height: number; padding?: number },
): string {
  const { width, height } = opts;
  const padding = opts.padding ?? 4;
  if (points.length === 0) return "";

  const values = points.map((pt) => pt.saldo_cents);
  const maxDays = Math.max(...points.map((pt) => pt.days)) || 1;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1; // evita divisão por zero quando tudo é igual
  const innerH = height - padding * 2;

  return points
    .map((pt) => {
      const x = padding + (pt.days / maxDays) * (width - padding * 2);
      // saldo maior → mais alto (y menor). Normaliza [min,max] → [innerH, 0].
      const y = padding + innerH - ((pt.saldo_cents - min) / range) * innerH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/**
 * Rótulo do runway em "meses e dias" (AC2). `null` = caixa não está sendo queimado ("sem risco").
 * Meses de 30 dias (aproximação de exibição; o valor canônico numérico é `runway.days`).
 */
export function runwayLabel(days: number | null): string {
  if (days === null) return "Sem risco no horizonte projetado";
  if (days <= 0) return "Caixa no limite (0 dias)";
  const months = Math.floor(days / 30);
  const rem = days % 30;
  const parts: string[] = [];
  if (months > 0) parts.push(`${months} ${months === 1 ? "mês" : "meses"}`);
  if (rem > 0) parts.push(`${rem} ${rem === 1 ? "dia" : "dias"}`);
  return parts.join(" e ") || "0 dias";
}
