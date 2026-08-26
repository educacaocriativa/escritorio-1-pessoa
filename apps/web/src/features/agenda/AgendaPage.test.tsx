import type { AgendaEvent } from "@e1p/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import AgendaPage from "./AgendaPage";

// Story 7.15 — Task 2. Rede sempre mockada (IV2): nenhum teste bate em /agenda real.
// `getGoogleStatus` é export nomeado de lib/api (usado pelo NewEventModal) → mockado como
// "Google desconectado" para não disparar chamada de rede real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  getGoogleStatus: vi.fn(() => Promise.resolve({ connected: false })),
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Estratégia (a) da Task 0: o botão "Novo evento" vive na topbar (AppShell). Topbar de teste local.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <AgendaPage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/agenda/events") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("AgendaPage — Novo evento (Story 7.15, Task 2)", () => {
  it("caminho feliz: cria evento com título + horários; POST /agenda/events e o modal fecha", async () => {
    const user = userEvent.setup();
    // CreateEventResult sem conflitos → o modal fecha (data.conflicts.length === 0 → onClose()).
    vi.mocked(api.post).mockResolvedValue({ data: { conflicts: [] } } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo evento" }));

    await user.type(screen.getByLabelText("Título"), "Atendimento cliente");
    // datetime-local: fireEvent.change (digitação em campos de data/hora no jsdom é frágil por locale).
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-08-01T09:00" } });
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-08-01T10:00" } });

    await user.click(screen.getByRole("button", { name: "Criar evento" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/agenda/events",
      expect.objectContaining({
        title: "Atendimento cliente",
        kind: "atendimento", // default
        // Bug #23: o horário do input (local, sem fuso) é convertido para UTC real antes do
        // POST. Assertamos o mesmo cálculo do componente (local→UTC), robusto a qualquer fuso
        // do runner — antes enviava a string "naive" crua, que o backend tratava como UTC.
        starts_at: new Date("2026-08-01T09:00").toISOString(),
        ends_at: new Date("2026-08-01T10:00").toISOString(),
      }),
    );
    // Modal fecha: o título (heading) some (o botão "Novo evento" da topbar permanece).
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Novo evento" })).not.toBeInTheDocument(),
    );
  });

  it("caminho infeliz: erro do backend é exibido sem travar a tela (modal aberto, botão reabilitado)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao criar o evento." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo evento" }));
    await user.type(screen.getByLabelText("Título"), "Atendimento cliente");
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-08-01T09:00" } });
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-08-01T10:00" } });
    await user.click(screen.getByRole("button", { name: "Criar evento" }));

    expect(await screen.findByText("Falha ao criar o evento.")).toBeInTheDocument();
    // Modal permanece aberto e o botão volta a ficar habilitado (saving → false).
    expect(screen.getByRole("heading", { name: "Novo evento" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Criar evento" })).toBeEnabled();
  });
});

// Task 3 (Onda 2, limpeza do _events_out): `client_name` passou a vir de QUALQUER evento
// com contato vinculado, não só cobranças (ver AgendaPage.tsx, `chipLabel`). O card do
// calendário restringe o atalho "mostra o nome" aos kinds financeiros — os únicos cujo
// título é auto-gerado pelo backend. Eventos "reunião"/"atendimento" mostram o título que o
// dono digitou, mesmo linkados a um contato.
function agendaEvent(overrides: Partial<AgendaEvent> = {}): AgendaEvent {
  // "Hoje" no fuso fixo do runner (America/Sao_Paulo, ver vitest.config.ts) — mesmo fuso que
  // `hojeDoTenant` usa quando não há sessão (fallback FUSO_PADRAO), então o evento cai dentro
  // da grade do mês que a AgendaPage abre por padrão.
  //
  // ⚠️ **FICA assim de propósito — não migre para relógio congelado + Tóquio (#120/#129).** Este
  // `new Date()` monta uma FIXTURE (só precisa cair no mês aberto), não uma expectativa: nenhum
  // `expect` deste arquivo compara este valor com o que a tela calculou. A prova de que a grade
  // agrupa pelo dia do TENANT mora em `features/agenda/grade.test.ts`, que é onde o fuso distante
  // tem o que matar. Trocar o fuso aqui só faria a fixture sair do mês que a tela abre.
  const now = new Date();
  const at = (h: number) =>
    new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, 0, 0).toISOString();
  return {
    id: "ev-1",
    tenant_id: "t-1",
    title: "Evento",
    description: "",
    kind: "atendimento",
    status: "scheduled",
    priority: "normal",
    source: "manual",
    starts_at: at(9),
    ends_at: at(10),
    all_day: false,
    location: "",
    meeting_url: null,
    guests: [],
    amount_cents: null,
    external_ref: null,
    google_event_id: null,
    client_id: null,
    client_name: null,
    created_by_ai: false,
    created_at: at(8),
    ...overrides,
  };
}

function mockEvents(events: AgendaEvent[]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/agenda/events") return Promise.resolve({ data: events } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

describe("AgendaPage — chipLabel (Task 3, Onda 2): atalho de nome só para kinds financeiros", () => {
  it("cobrança com client_name mostra o NOME no card, não o título auto-gerado", async () => {
    mockEvents([
      agendaEvent({
        id: "ev-receber",
        title: "A receber: cobrança gerada automaticamente",
        kind: "cobranca_receber",
        client_name: "Fulana da Silva",
      }),
    ]);
    const { container } = renderPage();

    await waitFor(() => expect(container.textContent).toContain("Fulana da Silva"));
    expect(container.textContent).not.toContain("cobrança gerada automaticamente");
  });

  it("reunião com contato vinculado mostra o TÍTULO digitado, não o nome do contato", async () => {
    mockEvents([
      agendaEvent({
        id: "ev-reuniao",
        title: "Alinhamento do casamento 12/12",
        kind: "reuniao",
        client_name: "Cliente Vinculado",
      }),
    ]);
    const { container } = renderPage();

    await waitFor(() => expect(container.textContent).toContain("Alinhamento do casamento 12/12"));
    expect(container.textContent).not.toContain("Cliente Vinculado");
  });
});

// ── `GET /agenda/events` fora de forma (issue #207) ───────────────────────────
//
// `setEvents(data)` recebia o payload CRU, sem operador nenhum. A grade chama `eventsOfDay(events,
// d)` para CADA dia visível, e `eventsOfDay` abre com `events.filter` (`grade.ts`) — em tempo de
// render, fora do alcance do `.then`. Sem ErrorBoundary no app, o estouro no primeiro dia do mês
// desmonta a árvore inteira: a agenda é a tela que o dono abre primeiro no dia.
//
// ⚠️ Este site NÃO aparece numa varredura por `estado.map`/`.length`/`.filter` no arquivo: o
// consumo é indireto, através de `eventsOfDay`. Foi assim que ele escapou da triagem inicial.
//
// ⚠️ O `assentar()` é a metade que MATA o mutante — ver `src/test/assentar.ts`.
describe("AgendaPage — eventos fora de forma não derrubam a grade (#207)", () => {
  function mockEventos(payload: unknown) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/agenda/events") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a grade do mês continua montada, sem nenhum chip", async (_rotulo, payload) => {
    mockEventos(payload);
    renderPage();
    await assentar();

    expect(screen.getByRole("button", { name: "Hoje" })).toBeInTheDocument();
    expect(screen.queryByText("Atendimento fora de forma")).not.toBeInTheDocument();
  });

  it("contra-teste: evento de verdade continua virando chip no dia", async () => {
    const hoje = new Date();
    const ymd = `${hoje.getFullYear()}-${String(hoje.getMonth() + 1).padStart(2, "0")}-${String(
      hoje.getDate(),
    ).padStart(2, "0")}`;
    mockEventos([
      {
        id: "e-1",
        title: "Atendimento real",
        kind: "atendimento",
        all_day: true,
        starts_at: `${ymd}T09:00:00Z`,
        ends_at: `${ymd}T10:00:00Z`,
      } satisfies Partial<AgendaEvent> as AgendaEvent,
    ]);
    renderPage();
    await assentar();

    expect(screen.getByText("Atendimento real")).toBeInTheDocument();
  });
});

// ── `GET .../messages` fora de forma (issue #225) ────────────────────────────
//
// `setMessages(data)` (dentro de `EventDetailModal`) recebia o payload cru. `messages.map` está
// atrás de `messages.length === 0`, mas a mesma armadilha do `runs`/`tokens` acima se aplica: um
// payload cujo `.length` não é numérico (objeto) ou cuja string TEM `.length` > 0 cai no `.map`.
describe("AgendaPage — histórico de mensagens fora de forma não derruba o modal do evento (#225)", () => {
  function mockEventoReceber(payload: unknown) {
    const evento = agendaEvent({
      id: "ev-receber-msgs",
      kind: "cobranca_receber",
      external_ref: "chg-1",
      title: "A receber: Fulana",
    });
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/agenda/events") return Promise.resolve({ data: [evento] } as never);
      if (url === "/receivables/charges/chg-1/messages") return Promise.resolve({ data: payload } as never);
      if (url === "/receivables/charges/chg-1") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: [] } as never);
    });
    return evento;
  }

  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → o modal do evento abre, sem histórico", async (_rotulo, payload) => {
    const user = userEvent.setup();
    const evento = mockEventoReceber(payload);
    renderPage();

    await user.click(await screen.findByTestId(`chip-evento-${evento.id}`));
    await assentar();

    expect(screen.getByText("Histórico de mensagens")).toBeInTheDocument();
    expect(screen.getByText("Nenhuma mensagem enviada ainda.")).toBeInTheDocument();
  });

  it("contra-teste: mensagem de verdade continua aparecendo no histórico", async () => {
    const user = userEvent.setup();
    const evento = mockEventoReceber([
      { id: "m-1", message: "Mensagem real", status: "sent", created_at: "2026-08-01T10:00:00Z" },
    ]);
    renderPage();

    await user.click(await screen.findByTestId(`chip-evento-${evento.id}`));
    await assentar();

    expect(await screen.findByText("Mensagem real")).toBeInTheDocument();
  });
});
