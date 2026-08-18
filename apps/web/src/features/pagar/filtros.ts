import type { PayableStatus } from "@e1p/shared-types";

/** O recorte da lista de Contas a Pagar. `de`/`ate` são YYYY-MM-DD ou `null` (sem limite). */
export type FiltroPagar = {
  status: PayableStatus[];
  de: string | null;
  ate: string | null;
  q: string;
  centroDeCusto: string;
  categoria: string;
};

const DIAS_NO_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function bissexto(ano: number): boolean {
  return (ano % 4 === 0 && ano % 100 !== 0) || ano % 400 === 0;
}

/**
 * Último dia do mês SEGUINTE ao de `hojeYmd`, também em YYYY-MM-DD.
 *
 * Aritmética de string, nunca `new Date`: o `hojeYmd` já chega no fuso do tenant (via
 * `today(useFuso())`), e reconstruir um `Date` a partir dele devolveria o cálculo ao fuso do
 * navegador — em UTC-3, das 21h à meia-noite o horizonte pularia um dia inteiro.
 */
export function fimDoMesSeguinte(hojeYmd: string): string {
  const [ano0, mes0] = hojeYmd.split("-").map(Number);
  // `mes0` é 1-based; usá-lo como índice 0-based já aponta para o mês seguinte.
  const ano = ano0 + Math.floor(mes0 / 12);
  const mes = (mes0 % 12) + 1;
  const dias = mes === 2 && bissexto(ano) ? 29 : DIAS_NO_MES[mes - 1];
  return `${ano}-${String(mes).padStart(2, "0")}-${String(dias).padStart(2, "0")}`;
}

/**
 * A visão padrão: "o que eu devo".
 *
 * `de: null` é deliberado e não é esquecimento. Atrasado tem vencimento no passado; qualquer piso
 * de data esconde exatamente a conta mais urgente que existe. O que o horizonte corta é só o
 * futuro distante — e o lugar de olhar longe é a Projeção de caixa.
 */
export function filtroPadrao(hojeYmd: string): FiltroPagar {
  return {
    status: ["open", "scheduled"],
    de: null,
    ate: fimDoMesSeguinte(hojeYmd),
    q: "",
    centroDeCusto: "",
    categoria: "",
  };
}

/** Histórico se lê do mais recente para o mais antigo; o que se deve, do mais próximo em diante. */
function ordem(status: PayableStatus[]): "asc" | "desc" {
  const olhandoParaTras = status.every((s) => s === "paid" || s === "canceled");
  return status.length > 0 && olhandoParaTras ? "desc" : "asc";
}

/** Serializa para os `params` do axios. Chave vazia é OMITIDA, nunca mandada como null. */
export function paraQuery(
  f: FiltroPagar,
  limit: number,
  offset: number,
): Record<string, unknown> {
  const q: Record<string, unknown> = { order: ordem(f.status), limit, offset };
  if (f.status.length > 0) q.status = f.status;
  if (f.de) q.from = f.de;
  if (f.ate) q.to = f.ate;
  if (f.q.trim()) q.q = f.q.trim();
  if (f.centroDeCusto) q.cost_center_id = f.centroDeCusto;
  if (f.categoria) q.chart_account_id = f.categoria;
  return q;
}
