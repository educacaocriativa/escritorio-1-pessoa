import type { SearchGroup } from "@e1p/shared-types";
import { describe, expect, it } from "vitest";
import { ROTULOS, itensEmSequencia, semVazios } from "./resultado";

function grupo(over: Partial<SearchGroup> = {}): SearchGroup {
  return {
    type: "client",
    has_more: false,
    total: null,
    items: [{ id: "1", title: "Ana", subtitle: "", route: "/crm/clients/1", snippet: null }],
    ...over,
  };
}

describe("resultado da busca", () => {
  it("descarta grupo sem item e preserva a ordem do backend", () => {
    const grupos = semVazios([
      grupo({ type: "contract", items: [] }),
      grupo({ type: "client" }),
      grupo({ type: "funnel" }),
    ]);

    expect(grupos.map((g) => g.type)).toEqual(["client", "funnel"]);
  });

  it("tem rótulo em português para os sete tipos", () => {
    expect(Object.keys(ROTULOS)).toHaveLength(7);
    expect(ROTULOS.legal_document).toBe("Jurídico");
    expect(ROTULOS.conversation).toBe("Conversas");
  });

  it("a sequência do teclado atravessa grupos", () => {
    const sequencia = itensEmSequencia([
      grupo({
        type: "client",
        items: [
          { id: "1", title: "Ana", subtitle: "", route: "/crm/clients/1", snippet: null },
          { id: "2", title: "Ana P", subtitle: "", route: "/crm/clients/2", snippet: null },
        ],
      }),
      grupo({
        type: "contract",
        items: [{ id: "9", title: "Contrato", subtitle: "", route: "/contratos/9", snippet: null }],
      }),
    ]);

    // Três itens numa fila só: é o que faz a seta para baixo sair de Clientes e cair em
    // Contratos sem o usuário precisar saber que mudou de grupo.
    expect(sequencia.map((i) => i.route)).toEqual([
      "/crm/clients/1",
      "/crm/clients/2",
      "/contratos/9",
    ]);
  });
});
