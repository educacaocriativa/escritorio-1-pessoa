/**
 * De onde o contato veio, em uma palavra — o selo do card do Kanban.
 *
 * **Não é espelho de `_ROTULO_DE_CHEGADA` (`crm/service.py`), e não deve virar um.** Lá a string é
 * uma FRASE de linha do tempo ("Chegou pelo WhatsApp"); aqui é um SELO de card, que divide a
 * largura com o nome e as tags em 360px. Superfícies diferentes, vocabulários diferentes: copiar a
 * frase longa para cá seria a duplicação ruim, não esta.
 *
 * ⚠️ O eixo a manter sincronizado é `SOURCE_VALUES` (`crm/models.py`), que tem SEIS membros — um a
 * mais que o mapa do backend, que esquece o `ai`. Origem que o backend aceita e a tela não nomeia
 * apareceria crua no card.
 */
const ROTULOS: Record<string, string> = {
  whatsapp: "WhatsApp",
  landing: "Site",
  api: "Integração",
  import: "Importado",
  manual: "Manual",
  ai: "IA",
};

export function rotuloDaOrigem(source: string): string {
  return ROTULOS[source] ?? source;
}
