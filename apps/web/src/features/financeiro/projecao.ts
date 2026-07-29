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
  // O NÚMERO — continua exibido mesmo quando o veredito é calado (Story 8.1, AC4b).
  saldo_projetado_cents: number;
  alert: boolean;
  // Story 8.1: o "caixa fica negativo" foi CALADO porque o saldo inicial é de origem `plataforma`
  // (o disponível da Carteira e1p, não a conta bancária do usuário). Invariante do backend:
  // `alert_suprimido === true` ⇒ `alert === false`.
  alert_suprimido: boolean;
}

export interface Runway {
  days: number | null;
  // Story 8.1: `days === null` tem DOIS significados que a tela não pode confundir —
  // `days_suprimido === false` é "sem risco" (o caixa não está sendo queimado) e
  // `days_suprimido === true` é "não sei" (havia queima, mas o saldo de partida não tem lastro).
  // Invariante do backend: `days_suprimido === true` ⇒ `days === null`.
  days_suprimido: boolean;
  // NÃO é suprimido: vem das contas em aberto, não do saldo inicial — continua válido e exibido.
  burn_rate_cents_per_day: number;
}

export interface Projection {
  today: string;
  saldo_inicial_cents: number;
  // Story 8.1 (AC1) — Regra dos Planos: nenhum saldo trafega sem procedência. Chave de
  // `ORIGEM_LABEL`. Na Onda 0 é sempre "plataforma"; a Story 8.8 passa a devolver "misto".
  saldo_inicial_origem: string;
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
 * Rótulo humano da procedência do saldo (Story 8.1, AC1/AC5 — eixo A da Regra dos Planos). O
 * vocabulário canônico é `app/core/money_planes.py` no backend; aqui só traduzimos para o usuário.
 * ⚠️ Este mapa é do eixo A (`*_origem`). O eixo B (`*_fonte`: manual/ofx) é outra coisa e, quando
 * existir na tela (Story 8.7), ganha um mapa SEPARADO — nunca misture os dois.
 */
export const ORIGEM_LABEL: Record<string, string> = {
  plataforma: "disponível na Carteira e1p",
  banco: "saldo da sua conta bancária",
  misto: "conta bancária + Carteira e1p",
  indisponivel: "origem não disponível",
};

/** Rótulo da origem, tolerante a um valor novo vindo do backend (mostra o valor cru em vez de sumir). */
export function origemLabel(origem: string): string {
  return ORIGEM_LABEL[origem] ?? origem;
}

/**
 * Rótulo do runway em "meses e dias" (5.7 AC2). Meses de 30 dias (aproximação de exibição; o valor
 * canônico numérico é `runway.days`).
 *
 * **Story 8.1 (AC5) — três saídas que NUNCA podem colapsar em duas.** A assinatura mudou de
 * `(days: number | null)` para `(runway: Runway)` exatamente para tornar impossível renderizar o
 * caso suprimido sem saber que ele existe:
 *   1. `days_suprimido` → "Indisponível" + o motivo (o saldo de partida não é o do banco);
 *   2. `days === null` e não suprimido → "Sem risco no horizonte projetado" (5.7, intacto);
 *   3. número → "X meses e Y dias" (5.7, intacto).
 * Trocar (1) por (2) é o erro mais caro desta story: substitui um número falso por uma
 * tranquilidade falsa — o primeiro erra, o segundo dá permissão para gastar.
 */
export function runwayLabel(runway: Runway): string {
  if (runway.days_suprimido) return "Indisponível — saldo inicial não confirmado";
  const days = runway.days;
  if (days === null) return "Sem risco no horizonte projetado";
  if (days <= 0) return "Caixa no limite (0 dias)";
  const months = Math.floor(days / 30);
  const rem = days % 30;
  const parts: string[] = [];
  if (months > 0) parts.push(`${months} ${months === 1 ? "mês" : "meses"}`);
  if (rem > 0) parts.push(`${rem} ${rem === 1 ? "dia" : "dias"}`);
  return parts.join(" e ") || "0 dias";
}
