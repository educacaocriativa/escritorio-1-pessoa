import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import FunnelBuilderPage from "./FunnelBuilderPage";

// Story 7.16 — Task 3. Rede sempre mockada (IV2): nenhum teste bate em /funnels real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Mitigação prescrita na Task 0/3: `reactflow` depende de `ResizeObserver`, que o jsdom NÃO
// implementa nativamente — sem este stub o mount do canvas lança. Stub local, sem dependência
// nova (Regra de Ouro nº 4). `html2canvas` não é exercitado aqui (o teste não baixa PNG).
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

// Catálogo mínimo: 1 categoria "gatilhos" (openCat inicial já é "gatilhos", não precisa expandir)
// com 1 item "Novo Lead".
const catalog = [
  {
    category: "gatilhos",
    label: "Gatilhos",
    color: "#F59E0B",
    items: [
      { key: "novo_lead", label: "Novo Lead", description: "Entrada de um novo lead", shape: "node" },
    ],
  },
];

// FunnelBuilderPage usa useParams/useNavigate → rota /funis/novo (isNew=true, sem GET /funnels/{id}).
// O default export já inclui <ReactFlowProvider> (não precisa adicionar outro).
function renderNew() {
  return render(
    <MemoryRouter initialEntries={["/funis/novo"]}>
      <Routes>
        <Route path="/funis/:id" element={<FunnelBuilderPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/funnels/components") return Promise.resolve({ data: catalog } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
});

describe("FunnelBuilderPage — criar nó e salvar funil (Story 7.16, Task 3)", () => {
  it("caminho feliz: clicar no item do catálogo adiciona um nó e Salvar faz POST /funnels", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "f-1", name: "Novo funil", nodes: [], edges: [] },
    } as never);
    renderNew();

    // O item da paleta é uma <div onClick={addByClick(...)}> (não um <button>) → getByText + click.
    await user.click(await screen.findByText("Novo Lead"));

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/funnels",
      expect.objectContaining({
        name: "Novo funil",
        nodes: [expect.objectContaining({ data: expect.objectContaining({ key: "novo_lead" }) })],
        edges: [],
      }),
    );
  });

  it("caminho infeliz: erro do backend ao salvar exibe toast de erro sem quebrar o canvas", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao salvar o funil." } },
    });
    renderNew();

    await user.click(await screen.findByText("Novo Lead"));
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    // Toast de erro (notify(..., "err") → classe bg-danger) com a mensagem do backend.
    const toast = await screen.findByText("Falha ao salvar o funil.");
    expect(toast).toBeInTheDocument();
    expect(toast).toHaveClass("bg-danger");
    // O canvas permanece montado: o botão "Salvar" segue presente (a tela não quebrou).
    expect(screen.getByRole("button", { name: "Salvar" })).toBeInTheDocument();
  });
});
