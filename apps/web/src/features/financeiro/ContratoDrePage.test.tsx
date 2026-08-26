import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
import ContratoDrePage from "./ContratoDrePage";

// Rede sempre mockada (IV2): nenhum teste bate em /contracts ou /cost-centers reais.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/contratos/ct-1/dre"]}>
      <Routes>
        <Route path="/contratos/:id/dre" element={<ContratoDrePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ── `GET /cost-centers` fora de forma (issue #225) ─────────────────────────────
//
// `setCostCenters(r.data)` recebia o payload CRU. O filtro por centro de custo (linha ~109) só
// aparece atrás de `costCenters.length > 0`, mas o `.then` já chamava `setCostCenters(payload)`
// direto — um objeto/string sem `.length` numérico passaria a checagem de forma inconsistente
// dependendo do shape (ex.: string TEM `.length`, e um `.map` sobre string quebra igual). A
// guarda no setter fecha os dois caminhos ao mesmo tempo.
describe("ContratoDrePage — centros de custo fora de forma não derrubam a página (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → a página segue montada, sem o filtro de centro de custo", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers") return Promise.resolve({ data: payload } as never);
      if (url === "/contracts/ct-1") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: null } as never);
    });
    renderPage();
    await assentar();

    expect(screen.getByText("Página / Contratos / DRE")).toBeInTheDocument();
    expect(screen.queryByLabelText("Filtrar por centro de custo")).not.toBeInTheDocument();
  });

  it("contra-teste: centro de custo de verdade continua aparecendo no filtro", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/cost-centers")
        return Promise.resolve({
          data: [{ id: "cc-1", name: "Sócio João", kind: "socio", is_archived: false }],
        } as never);
      if (url === "/contracts/ct-1") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: null } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByLabelText("Filtrar por centro de custo")).toBeInTheDocument();
    expect(screen.getByText("Sócio João")).toBeInTheDocument();
  });
});
