import type { SearchGroup, SearchItem, SearchType } from "@e1p/shared-types";

/**
 * Rótulos em português. O backend manda `type`; a UI mora aqui.
 *
 * A ORDEM dos grupos NÃO mora neste arquivo — ela vem do registro do backend
 * (`app/modules/search/registro.py`), num lugar só. Reordenar aqui criaria uma segunda
 * definição de "o que vem primeiro", e as duas divergiriam.
 */
export const ROTULOS: Record<SearchType, string> = {
  client: "Clientes",
  conversation: "Conversas",
  contract: "Contratos",
  quote: "Orçamentos",
  legal_document: "Jurídico",
  page: "Sites",
  funnel: "Funis",
};

/** Grupo sem item não ocupa linha na tela. */
export function semVazios(grupos: SearchGroup[]): SearchGroup[] {
  return grupos.filter((g) => g.items.length > 0);
}

/**
 * Todos os itens numa fila só, na ordem em que aparecem na tela.
 *
 * É o que a seta para baixo percorre: o usuário não deveria precisar saber que passou de
 * Clientes para Contratos — para o polegar e para o teclado, a lista é uma só.
 */
export function itensEmSequencia(grupos: SearchGroup[]): SearchItem[] {
  return grupos.flatMap((g) => g.items);
}
