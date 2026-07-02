import { Bot, Feather, Gavel, Landmark, Scale, type LucideIcon } from "lucide-react";

/** Rótulos e ícones das 5 categorias de skills jurídicas (lex-intelligentia). */
export const CATEGORY_META: Record<string, { label: string; icon: LucideIcon }> = {
  core: { label: "Essenciais", icon: Scale },
  magistrado: { label: "Magistratura", icon: Gavel },
  pesquisador: { label: "Pesquisa & Academia", icon: Landmark },
  automacao: { label: "Automação & IA", icon: Bot },
  criacao: { label: "Criação de Conteúdo", icon: Feather },
};

export const CATEGORY_ORDER = ["core", "magistrado", "pesquisador", "automacao", "criacao"];

export function categoryLabel(key: string): string {
  return CATEGORY_META[key]?.label ?? key;
}
