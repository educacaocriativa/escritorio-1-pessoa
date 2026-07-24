/**
 * Seletor de período compartilhado entre a matriz da DRE e a Lucratividade por Contrato.
 * Resolve um atalho ("Este mês"/"Este ano"/...) para {start,end} — sempre datas de calendário
 * em UTC (mesmo padrão de DrePage.tsx/ContratoDrePage.tsx, sem depender do fuso do navegador).
 */
export type PeriodShortcut =
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "this_year"
  | "last_12_months"
  | "all"
  | "custom";

export interface PeriodRange {
  start: string; // "YYYY-MM-DD"
  end: string;
}

export const PERIOD_SHORTCUT_LABEL: Record<PeriodShortcut, string> = {
  this_month: "Este mês",
  last_month: "Mês anterior",
  this_quarter: "Este trimestre",
  this_year: "Este ano",
  last_12_months: "Últimos 12 meses",
  all: "Tudo",
  custom: "Personalizado",
};

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function lastDayOfMonth(year: number, month: number): number {
  // `month` é 1-indexed (1=janeiro).
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

function monthBounds(year: number, month: number): PeriodRange {
  return {
    start: `${year}-${pad2(month)}-01`,
    end: `${year}-${pad2(month)}-${pad2(lastDayOfMonth(year, month))}`,
  };
}

/** Converte uma chave de mês "YYYY-MM" (coluna da matriz da DRE) no intervalo do mês inteiro —
 * usado pelo drill-down analítico da célula (Story 5.13). */
export function monthKeyToRange(monthKey: string): PeriodRange {
  const [year, month] = monthKey.split("-").map(Number);
  return monthBounds(year, month);
}

/**
 * Resolve um atalho para {start,end}. "all" usa 2000-01-01 como início — cobre qualquer
 * histórico plausível do tenant sem exigir uma query "sem limite inferior" separada no backend.
 * "custom" exige o 3º argumento (lança erro se omitido — a UI só usa "custom" quando o usuário
 * já preencheu os dois campos de data).
 */
export function resolvePeriod(
  shortcut: PeriodShortcut,
  today: Date = new Date(),
  custom?: PeriodRange,
): PeriodRange {
  const y = today.getUTCFullYear();
  const m = today.getUTCMonth() + 1; // 1-indexed

  switch (shortcut) {
    case "this_month":
      return monthBounds(y, m);
    case "last_month": {
      const py = m === 1 ? y - 1 : y;
      const pm = m === 1 ? 12 : m - 1;
      return monthBounds(py, pm);
    }
    case "this_quarter": {
      const qStartMonth = Math.floor((m - 1) / 3) * 3 + 1;
      return { start: monthBounds(y, qStartMonth).start, end: monthBounds(y, qStartMonth + 2).end };
    }
    case "this_year":
      return { start: `${y}-01-01`, end: `${y}-12-31` };
    case "last_12_months": {
      // janela rolante de 12 meses terminando no mês atual (inclusive) — volta 11 meses.
      const totalMonths = y * 12 + (m - 1) - 11;
      const startY = Math.floor(totalMonths / 12);
      const startM = (totalMonths % 12) + 1;
      return { start: monthBounds(startY, startM).start, end: monthBounds(y, m).end };
    }
    case "all":
      return { start: "2000-01-01", end: monthBounds(y, m).end };
    case "custom":
      if (!custom) throw new Error("período personalizado requer start/end");
      return custom;
  }
}
