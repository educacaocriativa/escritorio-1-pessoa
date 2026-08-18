import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import BlocoDaAgenda from "./BlocoDaAgenda";

// Task 6 (Onda 2): o bloco reusa o `NewEventModal` da Task 5 — por isso o mock de `api` também
// precisa de `getGoogleStatus` (o modal a chama ao abrir) e `apiErrorMessage`, do mesmo jeito que
// `NewEventModal.test.tsx` já faz.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  getGoogleStatus: vi.fn(() => Promise.resolve({ connected: false })),
  apiErrorMessage: () => "Erro inesperado",
}));

// O fuso do TENANT é trocável por teste (modelo de `NewEventModal.test.tsx`). O `vitest.config.ts`
// fixa o fuso da MÁQUINA em America/Sao_Paulo: com os dois iguais, converter um instante pelo fuso
// do tenant e lê-lo pelas partes locais do `Date` dá o MESMO resultado, e a asserção de fuso fica
// estruturalmente incapaz de falhar (§5.1 do CLAUDE.md, a família do `toContain("flex-wrap")`).
let fusoDoTenant = "America/Sao_Paulo";
// Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner — sob ele os dois caminhos
// discordam até sobre que DIA é.
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

const evento = (over: Record<string, unknown> = {}) => ({
  id: "ev-1", tenant_id: "t1", title: "Atendimento", description: "", kind: "atendimento",
  status: "scheduled", priority: "normal", source: "manual",
  starts_at: "2026-08-20T13:00:00Z", ends_at: "2026-08-20T14:00:00Z",
  all_day: false, location: "", meeting_url: null, guests: [], amount_cents: null,
  external_ref: null, google_event_id: null, client_id: "cli-1", client_name: null,
  created_by_ai: false, created_at: "2026-08-15T10:00:00Z",
  ...over,
});

function mockar(eventos: unknown[]) {
  vi.mocked(api.get).mockResolvedValue({ data: eventos } as never);
}

const renderBloco = () => render(<BlocoDaAgenda clientId="cli-1" nome="Loana" />);

// Mesmo motivo do `beforeEach` em `BlocoDaConversa.test.tsx`: `mockReset()` devolve o próprio
// mock, e um corpo de expressão única faria o Vitest tratar esse retorno como hook de limpeza
// pós-teste, chamando `api.get()` sem `url` depois de cada teste.
beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
  fusoDoTenant = "America/Sao_Paulo";
});

// Em `afterEach`, não no corpo do teste: se uma asserção falhar antes do `useRealTimers()`, os
// fake timers vazam para os testes seguintes e uma falha vira cascata de falhas sem relação.
afterEach(() => {
  vi.useRealTimers();
});

describe("BlocoDaAgenda", () => {
  it("lista os próximos compromissos, do mais próximo para o mais distante", async () => {
    mockar([
      evento({ id: "ev-perto", title: "Atendimento amanhã", starts_at: "2026-08-16T13:00:00Z" }),
      evento({ id: "ev-longe", title: "Reunião semana que vem", starts_at: "2026-08-22T13:00:00Z" }),
    ]);
    renderBloco();

    expect(await screen.findByText("Atendimento amanhã")).toBeInTheDocument();
    const itens = screen.getAllByRole("listitem");
    expect(itens).toHaveLength(2);
    // A ordem em que o servidor devolve (mais próximo primeiro) é preservada, sem reordenar
    // no cliente — o bloco confia no `ORDER BY starts_at` do `list_events`.
    expect(itens[0]).toHaveTextContent("Atendimento amanhã");
    expect(itens[1]).toHaveTextContent("Reunião semana que vem");

    // O corte é no SERVIDOR via `start=`, não uma filtragem client-side depois do fetch — o
    // gap desta task era exatamente isto (ler o router em vez de inventar filtro no front).
    // `exclude_cancelled=true` também vai na URL: este bloco é o único dos três lugares que
    // "sabem" o que é próximo (Histórico, next_event_map, este) que não excluía cancelado por
    // padrão — pedir explicitamente evita impersonar um "próximo compromisso" cancelado.
    const url = vi.mocked(api.get).mock.calls[0][0] as string;
    expect(url).toContain("/agenda/events?client_id=cli-1");
    expect(url).toContain("start=");
    expect(url).toContain("exclude_cancelled=true");
  });

  it("mostra o evento de dia inteiro de hoje, mesmo com starts_at já no passado", async () => {
    // Espelha `test_next_event_map_inclui_evento_de_dia_inteiro_de_hoje` no backend: um evento de
    // dia inteiro é ancorado na meia-noite REAL do fuso do tenant, então às 15h seu `starts_at`
    // já ficou no passado — só o corte por `ends_at >= agora` (aplicado pelo SERVIDOR) o inclui.
    // Este teste prova que o BLOCO não reintroduz um corte por `starts_at` no cliente: se a API
    // devolve o evento, o bloco tem que renderizá-lo, não escondê-lo de novo.
    mockar([
      evento({
        id: "ev-hoje-dia-inteiro",
        title: "Compromisso de hoje",
        all_day: true,
        starts_at: "2026-08-16T00:00:00Z",
        ends_at: "2026-08-17T00:00:00Z",
      }),
    ]);
    renderBloco();

    expect(await screen.findByText("Compromisso de hoje")).toBeInTheDocument();
    // Dia inteiro formata pela STRING (`formatDay`), sem `Date` — nunca `formatDateTime`, que
    // trataria a meia-noite UTC como um instante e converteria para o fuso do tenant.
    //
    // ⚠️ Aqui o fuso do tenant é o do runner DE PROPÓSITO, e trocá-lo por Tóquio ENFRAQUECERIA a
    // asserção: este teste prova que a data de calendário NÃO converte, e quem denuncia a
    // conversão indevida é um fuso NEGATIVO (UTC−3 puxa a meia-noite UTC para 15/08 21:00). Em
    // Tóquio, 00:00Z vira 09:00 do MESMO dia 16 e a mutação sobreviveria. Não "conserte".
    expect(screen.getByText("16/08/2026")).toBeInTheDocument();
  });

  it("estado vazio diz que não há compromisso e oferece marcar", async () => {
    // ⚠️ Este é o estado MAIS IMPORTANTE do bloco: é ele que revela o contato que vai esfriar.
    mockar([]);
    renderBloco();

    expect(await screen.findByText("Nenhum compromisso marcado")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /marcar com este cliente/i }),
    ).toBeInTheDocument();
  });

  it("mostra a agenda antes do formulário — o formulário não abre no primeiro clique", async () => {
    // O gap que este bloco tinha: "Marcar com este cliente" abria o formulário direto, e o dono
    // escolhia a data sem ver o próprio calendário. Agora a disponibilidade vem primeiro.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
    mockar([]);
    renderBloco();

    await screen.findByText("Nenhum compromisso marcado");
    await userEvent.click(screen.getByRole("button", { name: /marcar com este cliente/i }));

    expect(screen.getByRole("heading", { name: "Marcar com Loana" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Novo evento" })).not.toBeInTheDocument();
  });

  it("escolher um horário abre o formulário já preenchido e, ao criar, recarrega a lista", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
    mockar([]);
    vi.mocked(api.post).mockResolvedValue({ data: { conflicts: [] } } as never);
    renderBloco();

    await screen.findByText("Nenhum compromisso marcado");
    await userEvent.click(screen.getByRole("button", { name: /marcar com este cliente/i }));
    await userEvent.click(await screen.findByRole("button", { name: /20 de agosto/ }));
    await userEvent.click(screen.getByRole("button", { name: "10:00–11:00" }));

    // O seletor sai de cena e o formulário entra com a escolha já feita — o dono não redigita
    // a data que acabou de apontar no calendário.
    //
    // ⚠️ Fuso do runner de propósito: este teste é sobre a COSTURA (a escolha atravessa do
    // seletor para o formulário), não sobre fuso. A prova de que a hora escolhida é a hora de
    // PAREDE DO TENANT — `instanteNoFuso` + `paraInputLocal`, com tenant em Tóquio — já vive em
    // `features/agenda/NewEventModal.test.tsx`, no dono da conversão. Trocar o fuso aqui só
    // trocaria a string esperada por outra igualmente arbitrária e duplicaria aquela prova.
    expect(screen.getByRole("heading", { name: "Novo evento" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Marcar com Loana" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Início")).toHaveValue("2026-08-20T10:00");
    expect(screen.getByLabelText("Fim")).toHaveValue("2026-08-20T11:00");

    // Depois de abrir, a próxima chamada a `GET /agenda/events` já devolve o evento recém-criado
    // — é isso que prova que a lista recarregou, e não só que o modal fechou.
    mockar([evento({ id: "ev-novo", title: "Atendimento cliente" })]);

    await userEvent.type(screen.getByLabelText("Título"), "Atendimento cliente");
    await userEvent.click(screen.getByRole("button", { name: "Criar evento" }));

    // O evento nasce ligado a ESTE contato — mesmo vínculo que a Task 5 testou no modal isolado.
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/agenda/events",
      expect.objectContaining({ client_id: "cli-1" }),
    );
    expect(await screen.findByText("Atendimento cliente")).toBeInTheDocument();
    // Sem conflito, o modal fecha sozinho — o heading "Novo evento" some.
    expect(screen.queryByRole("heading", { name: "Novo evento" })).not.toBeInTheDocument();
  });

  it("formata o horário no fuso do TENANT, não no do navegador", async () => {
    // Tenant em Tóquio (UTC+9), máquina em São Paulo (UTC−3, fixado pelo `vitest.config.ts`).
    // 20/08 23:00Z é 21/08 08:00 em Tóquio e 20/08 20:00 em São Paulo: os dois caminhos discordam
    // na HORA e no DIA, então a asserção abaixo só passa lendo pelo fuso do tenant.
    fusoDoTenant = FUSO_DISTANTE;
    mockar([evento({ starts_at: "2026-08-20T23:00:00Z" })]);
    renderBloco();

    expect(await screen.findByText("21/08/2026 08:00")).toBeInTheDocument();
    // O que `localYmd`/`toLocaleString` sem `timeZone` mostrariam — o relógio de quem abriu a tela.
    expect(screen.queryByText("20/08/2026 20:00")).not.toBeInTheDocument();
  });

  it("falha de rede vira aviso, não derruba a ficha", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("caiu"));
    renderBloco();

    expect(await screen.findByText(/não foi possível carregar a agenda/i)).toBeInTheDocument();
  });

  it("o formulário nasce limpo a cada escolha — 'Dia inteiro' de uma vez anterior não engole a hora nova", async () => {
    // O `NewEventModal` fica MONTADO o tempo todo e guarda estado próprio. `allDay`, título e
    // aviso de conflito nunca eram resetados: o dono marcava "Dia inteiro" uma vez e, na próxima
    // vez que apontasse uma faixa livre, o `save()` descartava `start`/`end` em silêncio e criava
    // um evento sem horário. É o defeito que o `NewBillModal` já pagou com `key` (CLAUDE.md).
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-08-16T12:00:00Z"));
    mockar([]);
    renderBloco();

    await screen.findByText("Nenhum compromisso marcado");
    await userEvent.click(screen.getByRole("button", { name: /marcar com este cliente/i }));
    await userEvent.click(await screen.findByRole("button", { name: /20 de agosto/ }));
    await userEvent.click(screen.getByRole("button", { name: "10:00–11:00" }));

    await userEvent.type(screen.getByLabelText("Título"), "rascunho abandonado");
    await userEvent.click(screen.getByLabelText("Dia inteiro"));
    expect(screen.getByLabelText("Dia inteiro")).toBeChecked();

    // Desiste e recomeça.
    await userEvent.click(screen.getByRole("button", { name: /fechar/i }));
    await userEvent.click(screen.getByRole("button", { name: /marcar com este cliente/i }));
    await userEvent.click(await screen.findByRole("button", { name: /21 de agosto/ }));
    await userEvent.click(screen.getByRole("button", { name: "14:00–15:00" }));

    expect(screen.getByLabelText("Dia inteiro")).not.toBeChecked();
    expect(screen.getByLabelText("Título")).toHaveValue("");
    expect(screen.getByLabelText("Início")).toHaveValue("2026-08-21T14:00");
  });
});
