/**
 * Tipos e formatação compartilhados pela DRE (matriz mensal e por contrato).
 *
 * O backend devolve os totais já ASSINADOS (Receber=+, Pagar=−). A lógica de exibição vive aqui
 * (pura, testável) porque o projeto não tem infra de teste de componente React (sem jsdom /
 * @testing-library).
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

/** Rótulo PT-BR do grupo (reusa a taxonomia do plano de contas; trata o bucket sintético). */
export function groupLabel(grupo: string): string {
  if (grupo === "SEM_CATEGORIA") return "Sem categoria";
  return (GRUPO_LABEL as Record<string, string>)[grupo] ?? grupo;
}

/** Formata centavos (inteiros) para R$ pt-BR. Mantém o sinal (deduções aparecem negativas). */
export function formatBRL(cents: number): string {
  return (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
