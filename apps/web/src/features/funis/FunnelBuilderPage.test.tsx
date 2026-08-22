import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      // `whatsapp` é a chave que `contentKind` mapeia para o editor de mensagem.
      { key: "whatsapp", label: "WhatsApp", description: "Envia mensagem", shape: "node",
        action: "send_message" },
    ],
  },
];

/** Perfil do tenant — só o transporte de WhatsApp importa aqui. */
function profile(provider: "meta" | "evolution" | null) {
  return { whatsapp_provider: provider };
}

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

function mockApi(provider: "meta" | "evolution" | null = null, templates: unknown[] = []) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/funnels/components") return Promise.resolve({ data: catalog } as never);
    if (url === "/settings/profile") return Promise.resolve({ data: profile(provider) } as never);
    if (url === "/whatsapp-templates") return Promise.resolve({ data: templates } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

beforeEach(() => {
  mockApi();
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

describe("nó de WhatsApp — template (Meta) × texto livre (Evolution)", () => {
  /** Adiciona o nó de WhatsApp, seleciona-o e abre o editor de conteúdo.
   *
   * O nó do canvas é selecionado com `fireEvent.click` (e não `userEvent`) de propósito: o
   * `userEvent` emite `mousedown`, o React Flow entrega ao `d3-drag`, e o `d3-drag` estoura no
   * jsdom (`nodrag.js` acessa `document` de uma view nula). Aqui interessa só o `onNodeClick`. */
  async function abrirEditorDeMensagem(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByText("WhatsApp")); // item da paleta → cria o nó
    // O nó recém-criado aparece no canvas com o mesmo rótulo — o último "WhatsApp" é o nó.
    fireEvent.click(screen.getAllByText("WhatsApp").at(-1)!);
    await user.click(await screen.findByRole("button", { name: /Escrever mensagem/ }));
  }

  it("Evolution (QR code): oferece texto livre, não pede template aprovado", async () => {
    const user = userEvent.setup();
    mockApi("evolution");
    renderNew();

    await abrirEditorDeMensagem(user);

    // O seletor de template da Meta não existe neste transporte...
    expect(screen.queryByText("Template aprovado (Meta)")).not.toBeInTheDocument();
    // ...e a lista de templates nem chega a ser buscada.
    expect(vi.mocked(api.get)).not.toHaveBeenCalledWith("/whatsapp-templates", expect.anything());

    // O que aparece é a caixa de mensagem livre, e ela destrava o "Salvar no nó".
    expect(screen.getByText("Mensagem")).toBeInTheDocument();
    const salvar = screen.getByRole("button", { name: "Salvar no nó" });
    expect(salvar).toBeDisabled(); // vazio ainda é entrada inválida
    await user.type(screen.getByPlaceholderText("Escreva mensagem..."), "Oi, tudo bem?");
    expect(salvar).toBeEnabled();
  });

  it("Meta: continua exigindo template aprovado (sem regressão)", async () => {
    const user = userEvent.setup();
    mockApi("meta");
    renderNew();

    await abrirEditorDeMensagem(user);

    expect(await screen.findByText("Template aprovado (Meta)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar no nó" })).toBeDisabled();
  });
});

// ── Payload fora de forma em `GET /funnels/{id}` (issue #179) ─────────────────
//
// `setNodes`/`setEdges` são setters de estado do React alimentados direto pelo payload. O antigo
// `data.nodes ?? []` só barrava `null`/`undefined`: qualquer *truthy* fora de formato chegava
// inteiro ao reactflow, que faz `.map` nele — e `.map` de não-array ESTOURA no render, que não
// cai no `.catch()` da promise. É a mesma armadilha que o `ClientTimeline` documenta.
describe("funil com nodes/edges fora de formato não derruba o builder", () => {
  function renderEdit() {
    return render(
      <MemoryRouter initialEntries={["/funis/f-1"]}>
        <Routes>
          <Route path="/funis/:id" element={<FunnelBuilderPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  function mockFunnel(payload: unknown) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/funnels/components") return Promise.resolve({ data: catalog } as never);
      if (url === "/settings/profile") return Promise.resolve({ data: profile(null) } as never);
      if (url === "/funnels/f-1") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    ["objeto no lugar da lista", { name: "F", nodes: { a: 1 }, edges: { b: 2 } }],
    ["string no lugar da lista", { name: "F", nodes: "n", edges: "e" }],
    ["número no lugar da lista", { name: "F", nodes: 3, edges: 4 }],
    ["payload inteiro fora de formato", "não é json"],
  ])("%s → o builder monta vazio em vez de estourar", async (_rotulo, payload) => {
    mockFunnel(payload);
    renderEdit();

    // O catálogo é a prova de que o render CHEGOU AO FIM: ele fica depois do canvas na árvore.
    await waitFor(() => expect(screen.getByText("Novo Lead")).toBeInTheDocument());
  });

  it("nodes/edges de verdade continuam chegando ao canvas", async () => {
    // Contra-teste: a guarda não pode ter fechado o caminho feliz.
    mockFunnel({
      name: "Funil real",
      nodes: [{ id: "n1", position: { x: 0, y: 0 }, data: { key: "novo_lead", label: "Novo Lead" } }],
      edges: [],
    });
    renderEdit();

    await waitFor(() => expect(screen.getByDisplayValue("Funil real")).toBeInTheDocument());
  });
});
