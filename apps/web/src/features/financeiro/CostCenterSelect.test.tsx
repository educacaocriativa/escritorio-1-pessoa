import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
import CostCenterSelect from "./CostCenterSelect";

// Rede sempre mockada (IV2): nenhum teste bate em /cost-centers real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

function renderSelect() {
  return render(<CostCenterSelect value="" onChange={() => {}} />);
}

// ── `GET /cost-centers` fora de forma (issue #225) ─────────────────────────────
//
// `setCenters(data)` recebia o payload CRU. `centers.map` (linha ~66) está SEM guarda de
// `.length`, e o `<select>` é montado direto — sem modal por cima. Este componente é
// compartilhado por Contas a Pagar e Cobranças (ver `PagarPage.tsx`/`CobrancasPage.tsx`), então
// um payload fora de forma derrubaria as duas telas de uma vez.
describe("CostCenterSelect — lista fora de forma não derruba o select (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → o select continua montado, só com 'Não atribuído'", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    renderSelect();
    await assentar();

    expect(screen.getByText("Não atribuído")).toBeInTheDocument();
    expect(screen.getByText("+ Criar novo centro de custo...")).toBeInTheDocument();
  });

  it("contra-teste: centro de custo de verdade continua aparecendo no select", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "cc-1", name: "Sócio João", kind: "socio", is_archived: false }],
    } as never);
    renderSelect();
    await assentar();

    expect(await screen.findByText("Sócio João")).toBeInTheDocument();
  });
});
