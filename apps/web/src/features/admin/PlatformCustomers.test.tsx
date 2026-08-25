import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
import PlatformCustomers from "./PlatformCustomers";

// issue #207 — `setCustomers(data)`: payload cru no setter, SEM operador nenhum. `customers.reduce`
// roda no CORPO do componente (o chip de "compras"), sem portão de `.length` na frente — qualquer
// forma que não seja array estoura no render, longe do alcance do `.then`.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

const VAZIO =
  "Ainda não há clientes. Eles aparecem aqui quando um escritório vende um produto ou curso.";

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("PlatformCustomers — lista de clientes fora de forma não derruba a aba (#207)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a aba mostra o estado vazio em vez de estourar", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    render(<PlatformCustomers />);
    await assentar();

    expect(screen.getByText(VAZIO)).toBeInTheDocument();
  });

  it("contra-teste: cliente de verdade continua contado nos chips e listado", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: "c-1",
          name: "Maria Souza",
          email: "maria@exemplo.com",
          tenant_name: "Escritório Alpha",
          purchases: 3,
        },
      ],
    } as never);
    render(<PlatformCustomers />);
    await assentar();

    expect(screen.getByText("Maria Souza")).toBeInTheDocument();
    expect(screen.queryByText(VAZIO)).not.toBeInTheDocument();
  });
});
