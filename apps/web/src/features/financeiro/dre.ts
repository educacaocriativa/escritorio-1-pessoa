/**
 * DRE por categoria (Story 5.3) — tipos + transformação PURA que a DrePage usa para renderizar.
 *
 * O backend já devolve os grupos na ordem canônica (mesmo os vazios), com o sinal NATURAL de cada
 * lançamento (Receber=+, Pagar=−). Aqui só derivamos as LINHAS de exibição: grupos operacionais
 * (compõem o resultado), INVESTIMENTO (informativo, fora do resultado) e o bucket "sem categoria".
 * A lógica vive aqui (pura, testável) porque o projeto não tem infra de teste de componente React
 * (sem jsdom / @testing-library) — mesmo padrão de planoContas.ts / planoContas.test.ts.
 */
import { GRUPO_LABEL } from "./planoContas";

export interface DreCategory {
  categoria: string;
  amount_cents: number; // sinal natural (Receber=+, Pagar=−)
  count: number;
}

export interface DreGroup {
  grupo_dre: string;
  total_cents: number;
  categorias: DreCategory[];
}

export interface DreReport {
  start: string;
  end: string;
  groups: DreGroup[];
  sem_categoria: DreGroup;
  resultado_cents: number;
  notes: string[];
}

export type DreRowKind = "result" | "informational" | "uncategorized";

export interface DreRow {
  grupo_dre: string;
  label: string;
  total_cents: number;
  categorias: DreCategory[];
  kind: DreRowKind;
}

/** Rótulo PT-BR do grupo (reusa a taxonomia do plano de contas; trata o bucket sintético). */
export function groupLabel(grupo: string): string {
  if (grupo === "SEM_CATEGORIA") return "Sem categoria";
  return (GRUPO_LABEL as Record<string, string>)[grupo] ?? grupo;
}

/**
 * Deriva as linhas da DRE para exibição. Os grupos operacionais entram como `result`;
 * INVESTIMENTO como `informational` (fora do resultado); e o bucket "sem categoria" entra como
 * `uncategorized` apenas quando há lançamentos não classificados (não polui o relatório vazio).
 */
export function buildDreView(report: DreReport): { rows: DreRow[]; resultado_cents: number } {
  const rows: DreRow[] = report.groups.map((g) => ({
    grupo_dre: g.grupo_dre,
    label: groupLabel(g.grupo_dre),
    total_cents: g.total_cents,
    categorias: g.categorias,
    kind: g.grupo_dre === "INVESTIMENTO" ? "informational" : "result",
  }));

  const sem = report.sem_categoria;
  if (sem.categorias.length > 0 || sem.total_cents !== 0) {
    rows.push({
      grupo_dre: sem.grupo_dre,
      label: groupLabel(sem.grupo_dre),
      total_cents: sem.total_cents,
      categorias: sem.categorias,
      kind: "uncategorized",
    });
  }

  return { rows, resultado_cents: report.resultado_cents };
}

/** Formata centavos (inteiros) para R$ pt-BR. Mantém o sinal (deduções aparecem negativas). */
export function formatBRL(cents: number): string {
  return (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
