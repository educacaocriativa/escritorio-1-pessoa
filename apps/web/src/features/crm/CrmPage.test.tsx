import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import CrmPage from "./CrmPage";

// Story 7.15 — Task 1. Rede sempre mockada (IV2): nenhum teste bate em /crm real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Estratégia (a) da Task 0: o botão "Novo cliente" vive na topbar (AppShell). Topbar de teste local.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

// CrmPage usa <Card> com useNavigate → precisa de Router. Board vazio não renderiza cards,
// mas mantemos o MemoryRouter para robustez.
function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <CrmPage />
        <Topbar />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/crm/board") return Promise.resolve({ data: { columns: [] } } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("CrmPage — Novo cliente (Story 7.15, Task 1)", () => {
  it("caminho feliz: cria cliente com nome; POST /crm/clients com phone:null e tags:[]", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo cliente" }));

    await user.type(screen.getByLabelText("Nome"), "Maria Silva");
    await user.click(screen.getByRole("button", { name: "Criar cliente" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/crm/clients", {
      name: "Maria Silva",
      phone: null,
      tags: [],
    });
  });

  it("caminho infeliz: erro do backend é exibido sem travar a tela (modal aberto, botão reabilitado)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Nome já cadastrado." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo cliente" }));
    await user.type(screen.getByLabelText("Nome"), "Maria Silva");
    await user.click(screen.getByRole("button", { name: "Criar cliente" }));

    expect(await screen.findByText("Nome já cadastrado.")).toBeInTheDocument();
    // Modal segue aberto (título é heading, desambigua do botão da topbar) e botão reabilitado.
    expect(screen.getByRole("heading", { name: "Novo cliente" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Criar cliente" })).toBeEnabled();
  });
});

/** Board com um card só, para exercitar a linha da última interação. */
function boardComCard(
  lastInteractionAt: string | null,
  extra: { source?: string; tags?: string[] } = {},
) {
  return {
    columns: [
      {
        stage: {
          id: "s1", name: "Entrada", position: 0,
          is_won: false, is_lost: false, is_archived: false,
        },
        clients: [
          {
            id: "c1", tenant_id: "t1", name: "Flavio Kato", email: null, phone: null,
            document: null, gender: "unspecified", birthdate: null, notes: "",
            tags: extra.tags ?? [], source: extra.source ?? "landing", stage_id: "s1",
            created_at: "2026-07-01T10:00:00Z",
            stage_entered_at: "2026-07-28T12:00:00Z",
            last_interaction_at: lastInteractionAt,
          },
        ],
      },
    ],
  };
}

function mockarBoard(
  lastInteractionAt: string | null,
  extra: { source?: string; tags?: string[] } = {},
) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/crm/board") {
      return Promise.resolve({ data: boardComCard(lastInteractionAt, extra) } as never);
    }
    return Promise.resolve({ data: [] } as never);
  });
}

describe("CrmPage — última interação no card", () => {
  it("mostra a data quando o contato já teve interação", async () => {
    mockarBoard("2026-08-04T14:32:00Z");
    renderPage();
    expect(await screen.findByText(/última interação: 04\/08/i)).toBeInTheDocument();
  });

  it("card sem interação nenhuma não mostra rótulo vazio", async () => {
    mockarBoard(null);
    renderPage();
    await screen.findByText("Flavio Kato");
    expect(screen.queryByText(/última interação/i)).not.toBeInTheDocument();
  });
});

describe("CrmPage — a data que explica a posição na fila", () => {
  it("mostra as duas datas: posição na fila e temperatura da conversa", async () => {
    mockarBoard("2026-08-05T13:00:00Z");
    renderPage();

    // A coluna é ordenada por "na etapa desde"; sem ela na tela, a ordem seria um critério
    // invisível — dois cards com a mesma "última interação" em posições distantes.
    expect(await screen.findByText("na etapa desde: 28/07")).toBeInTheDocument();
    expect(await screen.findByText("última interação: 05/08")).toBeInTheDocument();
  });

  it("mostra a etapa mesmo quando o contato nunca interagiu", async () => {
    mockarBoard(null);
    renderPage();

    // `stage_entered_at` é coluna não-nula: todo card sempre sabe desde quando está ali.
    expect(await screen.findByText("na etapa desde: 28/07")).toBeInTheDocument();
  });
});

describe("CrmPage — de onde o contato veio", () => {
  // O card do WhatsApp não dizia NADA sobre a origem, enquanto os do site exibiam a tag
  // `vindo-do-site` — e tag é marcação do dono, não origem. Quem olhava a Entrada não conseguia
  // distinguir a oportunidade real da conversa avulsa que caiu no WhatsApp.
  it("o card do WhatsApp diz que veio do WhatsApp", async () => {
    mockarBoard(null, { source: "whatsapp" });
    renderPage();

    expect(await screen.findByTitle("De onde este contato veio")).toHaveTextContent("WhatsApp");
  });

  // `source` tem default "manual" no backend e nunca é nulo: NENHUM card fica sem origem.
  it("card sem porta de entrada conhecida ainda diz de onde veio", async () => {
    mockarBoard(null, { source: "manual" });
    renderPage();

    expect(await screen.findByTitle("De onde este contato veio")).toHaveTextContent("Manual");
  });

  it("a origem é um selo próprio, antes das tags — não mais uma tag no meio delas", async () => {
    mockarBoard(null, { source: "landing", tags: ["vindo-do-site"] });
    renderPage();

    const origem = await screen.findByTitle("De onde este contato veio");
    const tag = screen.getByText("vindo-do-site");

    // Elementos DISTINTOS: a asserção não pode ser por texto solto, senão passaria com os dois
    // pintados iguais — que é exatamente o defeito sendo corrigido.
    expect(origem).not.toBe(tag);
    expect(origem).toHaveTextContent("Site");
    // E a origem vem ANTES na leitura do card. (A distinção VISUAL não é aferível em jsdom; ela
    // é medida no navegador, em `e2e/crm-360.spec.ts`, comparando a cor computada das duas.)
    expect(origem.compareDocumentPosition(tag)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
