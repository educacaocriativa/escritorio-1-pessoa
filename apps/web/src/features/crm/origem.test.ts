import { describe, expect, it } from "vitest";
import { rotuloDaOrigem } from "./origem";

describe("rotuloDaOrigem", () => {
  // Os SEIS de `SOURCE_VALUES` (crm/models.py) — não os cinco de `_ROTULO_DE_CHEGADA`, que
  // esquece o `ai`. Um valor que o backend ACEITA e a tela não sabe nomear apareceria cru.
  it("traduz os seis canais que o backend valida em SOURCE_VALUES", () => {
    expect(rotuloDaOrigem("whatsapp")).toBe("WhatsApp");
    expect(rotuloDaOrigem("landing")).toBe("Site");
    expect(rotuloDaOrigem("api")).toBe("Integração");
    expect(rotuloDaOrigem("import")).toBe("Importado");
    expect(rotuloDaOrigem("manual")).toBe("Manual");
    expect(rotuloDaOrigem("ai")).toBe("IA");
  });

  // O NÃO-MEMBRO. Sem ele o mapa passaria vazio, e uma porta de entrada nova (backend mais novo
  // que a tela em deploy) deixaria o card SEM origem nenhuma — de volta ao defeito que este
  // arquivo existe para corrigir. Mesma disciplina de `_titulo_de_chegada` no backend: um source
  // desconhecido cai num rótulo honesto em vez de sumir.
  it("origem desconhecida aparece crua, nunca some", () => {
    expect(rotuloDaOrigem("instagram")).toBe("instagram");
  });
});
