import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
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

// ── `GET /funnels/components` fora de forma (issue #207) ──────────────────────
//
// `setCatalog(data)` recebia o payload CRU, sem operador NENHUM — o outro exemplo que a issue cita
// pelo nome. É o terceiro payload desta mesma tela: o PR #197 guardou `nodes`/`edges` (que ao
// menos tinham `?? []`) e o catálogo ficou de fora justamente por não ter operador algum e por
// isso não aparecer na varredura por `??`. `catalog.map` monta a paleta no render, fora do alcance
// do `.then`.
//
// ⚠️ O `assentar()` é a metade que MATA o mutante — ver `src/test/assentar.ts`.
describe("catálogo de componentes fora de forma não derruba o builder (#207)", () => {
  function mockCatalogo(payload: unknown) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/funnels/components") return Promise.resolve({ data: payload } as never);
      if (url === "/settings/profile") return Promise.resolve({ data: profile(null) } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → o builder monta com a paleta vazia em vez de estourar", async (_rotulo, payload) => {
    mockCatalogo(payload);
    renderNew();
    await assentar();

    // O canvas e a barra de ações continuam de pé...
    expect(screen.getByRole("button", { name: "Salvar" })).toBeInTheDocument();
    // ...e a paleta simplesmente não tem itens.
    expect(screen.queryByText("Novo Lead")).not.toBeInTheDocument();
  });

  it("contra-teste: catálogo de verdade continua montando a paleta", async () => {
    mockCatalogo(catalog);
    renderNew();
    await assentar();

    expect(screen.getByText("Novo Lead")).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Issue #224 — separador de milhar no valor digitado (parseCentsBRL)
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// A conta manual antiga (`Math.round(parseFloat(v.replace(",", ".")) * 100)`) só troca a PRIMEIRA
// vírgula por ponto e nunca remove o ponto de milhar: "1.234,56" vira "1.234.56", `parseFloat` para
// no segundo ponto e devolve 1.234 → 123 centavos, não 123456. `parseCentsBRL` (contas.ts) trata o
// milhar corretamente; estes testes fixam esse contrato nos dois sites de `RunNodeModal.run()`
// (create_quote e create_charge), que digitam no mesmo campo "Valor (R$)" mas montam o payload em
// dois `if` distintos (linhas 624 e 629 antes do #224).
const catalogComAcoesDeDinheiro = [
  {
    category: "gatilhos",
    label: "Gatilhos",
    color: "#F59E0B",
    items: [
      {
        key: "gerar-orcamento", label: "Gerar orçamento", description: "Cria um orçamento",
        shape: "node", action: "create_quote",
      },
      {
        key: "gerar-cobranca", label: "Gerar cobrança", description: "Cria uma cobrança",
        shape: "node", action: "create_charge",
      },
    ],
  },
];

describe("RunNodeModal — separador de milhar (#224)", () => {
  function mockComAcoes() {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/funnels/components") return Promise.resolve({ data: catalogComAcoesDeDinheiro } as never);
      if (url === "/settings/profile") return Promise.resolve({ data: profile(null) } as never);
      if (url === "/crm/clients") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  /** Adiciona o nó pelo item da paleta, seleciona-o no canvas e abre "Executar ação". */
  async function abrirExecutarAcao(user: ReturnType<typeof userEvent.setup>, itemLabel: string) {
    await user.click(await screen.findByText(itemLabel)); // item da paleta → cria o nó
    fireEvent.click(screen.getAllByText(itemLabel).at(-1)!); // seleciona o nó recém-criado
    await user.click(await screen.findByRole("button", { name: "Executar ação" }));
  }

  it("create_quote: '1.234,56' vira amount_cents 123456, não 123 (linha do params.amount_cents em create_quote)", async () => {
    const user = userEvent.setup();
    mockComAcoes();
    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url === "/funnels/run-node") return Promise.resolve({ data: { message: "ok" } } as never);
      return Promise.resolve({ data: {} } as never);
    });
    renderNew();

    await abrirExecutarAcao(user, "Gerar orçamento");
    await user.type(screen.getByLabelText("Valor (R$)"), "1.234,56");
    await user.click(screen.getByRole("button", { name: "Executar agora" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalledWith("/funnels/run-node", expect.anything()));
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/funnels/run-node",
      expect.objectContaining({
        action: "create_quote",
        params: expect.objectContaining({ amount_cents: 123456 }),
      }),
    );
  });

  it("create_charge: '1.234,56' vira amount_cents 123456, não 123 (linha do params.amount_cents em create_charge)", async () => {
    const user = userEvent.setup();
    mockComAcoes();
    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url === "/funnels/run-node") return Promise.resolve({ data: { message: "ok" } } as never);
      return Promise.resolve({ data: {} } as never);
    });
    renderNew();

    await abrirExecutarAcao(user, "Gerar cobrança");
    await user.type(screen.getByLabelText("Valor (R$)"), "1.234,56");
    await user.click(screen.getByRole("button", { name: "Executar agora" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalledWith("/funnels/run-node", expect.anything()));
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/funnels/run-node",
      expect.objectContaining({
        action: "create_charge",
        params: expect.objectContaining({ amount_cents: 123456 }),
      }),
    );
  });
});

// ── `GET /crm/clients` fora de forma dentro do `RunNodeModal` (issue #225) ───────────────────
//
// `setClients(data)` recebia o payload cru. `clients.map` (select "Cliente", linha ~685) é
// montado direto sempre que a ação precisa de cliente (`needsClient`) — aqui, `create_quote`.
describe("RunNodeModal — clientes fora de forma não derrubam 'Executar ação' (#225)", () => {
  function mockComAcoes(clientsPayload: unknown) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/funnels/components") return Promise.resolve({ data: catalogComAcoesDeDinheiro } as never);
      if (url === "/settings/profile") return Promise.resolve({ data: profile(null) } as never);
      if (url === "/crm/clients") return Promise.resolve({ data: clientsPayload } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  async function abrirExecutarAcao(user: ReturnType<typeof userEvent.setup>, itemLabel: string) {
    await user.click(await screen.findByText(itemLabel));
    fireEvent.click(screen.getAllByText(itemLabel).at(-1)!);
    await user.click(await screen.findByRole("button", { name: "Executar ação" }));
  }

  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → o modal 'Executar ação' abre, com o select de cliente vazio", async (_rotulo, payload) => {
    const user = userEvent.setup();
    mockComAcoes(payload);
    renderNew();

    await abrirExecutarAcao(user, "Gerar orçamento");

    expect(screen.getByText("Cliente")).toBeInTheDocument();
    expect(screen.getByText("Selecione um cliente")).toBeInTheDocument();
  });

  it("contra-teste: cliente de verdade continua aparecendo no select", async () => {
    const user = userEvent.setup();
    mockComAcoes([{ id: "c-1", name: "Maria Silva" }]);
    renderNew();

    await abrirExecutarAcao(user, "Gerar orçamento");

    expect(await screen.findByText("Maria Silva")).toBeInTheDocument();
  });
});

// ── `GET /whatsapp-templates` fora de forma no editor de mensagem (issue #225) ───────────────
//
// `setTemplates(data)` recebia o payload cru. `templates.map` alimenta o `<select>` de template
// aprovado — só existe no transporte Meta (`usaTemplate`), reaberto do mesmo editor já coberto
// pelo describe "nó de WhatsApp" acima.
describe("Editor de mensagem — templates fora de forma não derrubam o select (#225)", () => {
  async function abrirEditorDeMensagem(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByText("WhatsApp"));
    fireEvent.click(screen.getAllByText("WhatsApp").at(-1)!);
    await user.click(await screen.findByRole("button", { name: /Escrever mensagem/ }));
  }

  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s (Meta) → o editor abre, sem opções de template", async (_rotulo, payload) => {
    const user = userEvent.setup();
    mockApi("meta", payload as unknown as unknown[]);
    renderNew();

    await abrirEditorDeMensagem(user);

    expect(await screen.findByText("Template aprovado (Meta)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar no nó" })).toBeDisabled();
  });

  it("contra-teste: template de verdade continua aparecendo no select", async () => {
    const user = userEvent.setup();
    mockApi("meta", [
      { id: "tpl-1", name: "boas_vindas", language: "pt_BR", variable_count: 0 },
    ]);
    renderNew();

    await abrirEditorDeMensagem(user);

    expect(await screen.findByText("boas_vindas (pt_BR)")).toBeInTheDocument();
  });
});
