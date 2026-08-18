import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import type { Board } from "@e1p/shared-types";
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

// O fuso do TENANT é trocável por teste (modelo de `NewEventModal.test.tsx`). Antes da issue #120
// este arquivo não mockava `useFuso` e caía no fallback `FUSO_PADRAO = "America/Sao_Paulo"` — o
// MESMO fuso que o `vitest.config.ts` fixa para a máquina. Com os dois iguais, converter um
// instante pelo fuso do tenant e lê-lo pelo relógio do navegador dá o mesmo resultado por
// construção, e a asserção de fuso não consegue falhar. `CrmPage` e sua subárvore (`Modal`,
// `GanchoDaVima`, `pageActions`) só usam `useFuso` deste módulo — o mock parcial é seguro.
let fusoDoTenant = "America/Sao_Paulo";
// Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner: sob ele os dois caminhos
// discordam até sobre que DIA é.
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

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
  fusoDoTenant = "America/Sao_Paulo";
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

describe("CrmPage — ponto de mensagem esperando resposta", () => {
  // Tipado como `Board` (não `as never`): achado do review — o cast escondia que este
  // literal já estava mais estreito que o `Client` real (faltavam tenant_id, gender,
  // birthdate, created_at). Tipar aqui faz o compilador cobrar essas quatro colunas.
  const boardCom = (unread: boolean): Board => ({
    columns: [{
      stage: { id: "s1", name: "Entrada", position: 0, is_won: false, is_lost: false },
      clients: [{
        id: "c1", tenant_id: "t1", name: "Ju", email: null, phone: null, document: null,
        gender: "unspecified", birthdate: null, notes: "", tags: [], source: "whatsapp",
        stage_id: "s1", created_at: "2026-08-15T12:00:00Z",
        stage_entered_at: "2026-08-15T12:00:00Z", last_interaction_at: null,
        unread, next_event_at: null, next_event_title: null, next_event_all_day: false,
      }],
    }],
  });

  it("mostra o ponto quando o contato está esperando resposta", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: boardCom(true) } as never);
    renderPage();
    expect(await screen.findByLabelText("Mensagem esperando resposta")).toBeInTheDocument();
  });

  it("não mostra o ponto quando não há nada esperando", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: boardCom(false) } as never);
    renderPage();
    expect(await screen.findByText("Ju")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mensagem esperando resposta")).not.toBeInTheDocument();
  });
});

describe("CrmPage — a linha do próximo passo", () => {
  // Próximo compromisso e a AUSÊNCIA dele são estados opostos da mesma pergunta: nunca os dois
  // juntos. `nextEventAt: null` exercita o card sem nada marcado (o caso mais acionável, quem
  // vai esfriar); com data, exercita o card que já tem o próximo passo escrito.
  const boardCom = (
    nextEventAt: string | null, nextEventTitle: string | null, allDay = false,
  ): Board => ({
    columns: [{
      stage: { id: "s1", name: "Entrada", position: 0, is_won: false, is_lost: false },
      clients: [{
        id: "c1", tenant_id: "t1", name: "Ju", email: null, phone: null, document: null,
        gender: "unspecified", birthdate: null, notes: "", tags: [], source: "whatsapp",
        stage_id: "s1", created_at: "2026-08-15T12:00:00Z",
        stage_entered_at: "2026-08-15T12:00:00Z", last_interaction_at: null,
        unread: false, next_event_at: nextEventAt, next_event_title: nextEventTitle,
        next_event_all_day: allDay,
      }],
    }],
  });

  it("mostra o próximo compromisso quando existe", async () => {
    // ⚠️ Fuso do runner de propósito: este teste é sobre a LINHA existir com o título certo, não
    // sobre conversão de fuso — 14:00Z cai no dia 20 em qualquer fuso plausível. A prova de fuso
    // é o teste "converte o instante para o fuso do TENANT" mais abaixo. Não troque o fuso aqui.
    vi.mocked(api.get).mockResolvedValue({
      data: boardCom("2026-08-20T14:00:00Z", "Reunião de alinhamento"),
    } as never);
    renderPage();
    expect(
      await screen.findByText(/próximo: Reunião de alinhamento em 20\/08/i),
    ).toBeInTheDocument();
  });

  it("diz 'sem próximo passo' quando não existe", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: boardCom(null, null) } as never);
    renderPage();
    expect(await screen.findByText("sem próximo passo")).toBeInTheDocument();
  });

  it("nunca mostra os dois ao mesmo tempo", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: boardCom("2026-08-20T14:00:00Z", "Reunião de alinhamento"),
    } as never);
    renderPage();
    await screen.findByText(/próximo: Reunião de alinhamento em 20\/08/i);
    expect(screen.queryByText("sem próximo passo")).not.toBeInTheDocument();
  });
});

describe("CrmPage — próximo passo de dia inteiro não 'volta' um dia (achado da revisão final)", () => {
  // `receivables/service.py::build_charge` ancora o evento de cobrança à MEIA-NOITE UTC (não na
  // meia-noite do fuso do tenant, ao contrário de `agenda/service.py::create_event`). Com o
  // tenant em UTC−3 — o padrão deste arquivo — "2026-08-22T00:00:00Z" é 21/08 21h: o cenário
  // exato do achado. Formatar como INSTANTE (`formatDateShort`, que converte fuso) imprimiria
  // "21/08"; o card tem que usar `formatDay` (lê a string, sem conversão) e mostrar "22/08" — a
  // data real do vencimento.
  const boardComProximo = (
    nextEventAt: string, nextEventTitle: string, allDay: boolean,
  ): Board => ({
    columns: [{
      stage: { id: "s1", name: "Entrada", position: 0, is_won: false, is_lost: false },
      clients: [{
        id: "c1", tenant_id: "t1", name: "Ju", email: null, phone: null, document: null,
        gender: "unspecified", birthdate: null, notes: "", tags: [], source: "whatsapp",
        stage_id: "s1", created_at: "2026-08-15T12:00:00Z",
        stage_entered_at: "2026-08-15T12:00:00Z", last_interaction_at: null,
        unread: false, next_event_at: nextEventAt, next_event_title: nextEventTitle,
        next_event_all_day: allDay,
      }],
    }],
  });

  it("cobrança vencendo dia 22 mostra 22/08 no card, não 21/08", async () => {
    // ⚠️ Fuso do runner (UTC−3) DE PROPÓSITO, e trocá-lo por Tóquio ENFRAQUECERIA a asserção:
    // o que este teste prova é que a data de calendário NÃO converte, e quem denuncia a conversão
    // indevida é um fuso NEGATIVO — em UTC−3 a meia-noite UTC "volta" para 21/08 21h. Em Tóquio,
    // 00:00Z vira 09:00 do MESMO dia 22 e a troca por `formatDateShort` sobreviveria. Não
    // "conserte" este para um fuso distante.
    vi.mocked(api.get).mockResolvedValue({
      data: boardComProximo("2026-08-22T00:00:00Z", "A receber: Fulana", true),
    } as never);
    renderPage();
    expect(
      await screen.findByText(/próximo: A receber: Fulana em 22\/08/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/em 21\/08/i)).not.toBeInTheDocument();
  });

  it("compromisso COM horário converte o instante para o fuso do TENANT, não do navegador", async () => {
    // Contraste: `all_day: false` não pode passar a usar `formatDay` por engano — um evento com
    // horário É um instante de verdade, e tem que continuar convertendo fuso.
    //
    // Tenant em Tóquio (UTC+9), máquina em São Paulo (UTC−3): 20/08 23:00Z é 21/08 08:00 em
    // Tóquio e 20/08 20:00 em São Paulo. Só quem lê pelo fuso do TENANT escreve 21/08 no card;
    // ler pelo relógio do navegador — ou pela string, como o ramo `all_day` faz — daria 20/08.
    fusoDoTenant = FUSO_DISTANTE;
    vi.mocked(api.get).mockResolvedValue({
      data: boardComProximo("2026-08-20T23:00:00Z", "Reunião de alinhamento", false),
    } as never);
    renderPage();
    expect(
      await screen.findByText(/próximo: Reunião de alinhamento em 21\/08/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/em 20\/08/i)).not.toBeInTheDocument();
  });
});
