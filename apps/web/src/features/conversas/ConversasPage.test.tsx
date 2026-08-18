import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ConversasPage from "./ConversasPage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

// O fuso do TENANT é trocável por teste (modelo de `NewEventModal.test.tsx`). Antes da issue #120
// este arquivo não mockava `useFuso` e caía no fallback `FUSO_PADRAO = "America/Sao_Paulo"` — o
// MESMO fuso que o `vitest.config.ts` fixa para a máquina. Com os dois iguais, o separador de dia
// e o horário de cada bolha saem idênticos lendo pelo tenant ou pelo relógio do navegador, e a
// asserção sobre eles fica estruturalmente incapaz de falhar. O default abaixo preserva
// exatamente o comportamento anterior de todos os outros testes deste arquivo.
// `ClientTimeline` (renderizado por esta tela) também consome `useFuso` — o mock parcial cobre
// os dois, e nenhum dos dois usa mais nada de `store/auth`.
let fusoDoTenant = "America/Sao_Paulo";
// Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner.
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

// Nenhum teste deste arquivo depende de chamadas de um teste anterior — cada um remonta seu
// próprio `mockImplementation`. Sem isto, o HISTÓRICO de chamadas (não só o resultado) vaza de
// um teste para o próximo, o que já quebrou uma asserção `not.toHaveBeenCalledWith` real (ver
// describe "a conversa tem URL própria"). `clearAllMocks`, não `resetAllMocks`: reset apagaria
// a implementação que cada teste instala antes do reset ter chance de rodar de novo.
beforeEach(() => {
  vi.clearAllMocks();
  fusoDoTenant = "America/Sao_Paulo";
});

function renderNaRota(rota: string) {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/conversas" element={<ConversasPage />} />
        <Route path="/conversas/:chatId" element={<ConversasPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ConversasPage", () => {
  it("lista as conversas e mostra o fio ao clicar numa delas", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") {
        return Promise.resolve({
          data: [{
            chat_id: "c1", kind: "direct" as const, title: "Doro Eventos", phone: "5511999999999", client_id: "c1",
            last_message_at: "2026-07-19T10:00:00Z", last_message_preview: "Oi, quero o cardápio",
            unread: true,
          }],
        });
      }
      if (url === "/whatsapp-conversations/c1/timeline") {
        return Promise.resolve({
          data: [{
            source: "conversation", direction: "in", kind: "text",
            text_body: "Oi, quero o cardápio", media_attachment_id: null, purpose_label: null, sender_name: null,
            created_at: "2026-07-19T10:00:00Z",
          }],
        });
      }
      if (url === "/whatsapp-conversations/c1/window") {
        return Promise.resolve({ data: { within_session_window: true } });
      }
      if (url === "/whatsapp-templates") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);

    renderNaRota("/conversas");
    await waitFor(() => screen.getByText("Doro Eventos"));
    await userEvent.click(screen.getByText("Doro Eventos"));
    // A prévia da lista e o corpo da mensagem no fio coincidem neste fixture, então mais de um
    // nó tem o mesmo texto — confirmamos que o fio abriu pela contagem (lista + bolha), não por
    // unicidade de texto.
    await waitFor(() => expect(screen.getAllByText("Oi, quero o cardápio")).toHaveLength(2));
    expect(screen.getByPlaceholderText(/mensagem/i)).toBeInTheDocument();
  });

  it("o separador de dia e o horário saem no fuso do TENANT, não no do navegador", async () => {
    // O fio agrupa por DIA (`dayKey`) e carimba cada bolha (`hhmm`), os dois no fuso do tenant.
    // O teste irmão abaixo mede as duas coisas com o tenant no MESMO fuso da máquina, e por isso
    // não consegue distinguir os dois caminhos — é o defeito da issue #120. Aqui o tenant vai
    // para Tóquio (UTC+9) e a máquina fica em São Paulo (UTC−3): 19/07 23:30Z é 20/07 08:30 em
    // Tóquio e 19/07 20:30 em São Paulo. Muda o horário E o dia do separador.
    fusoDoTenant = FUSO_DISTANTE;
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") {
        return Promise.resolve({
          data: [{
            chat_id: "c1", kind: "direct" as const, title: "Murilo Moreschi", phone: "5511977776666",
            client_id: "c1", last_message_at: "2026-07-19T23:30:00Z",
            last_message_preview: "sempre na curva", unread: false,
          }],
        });
      }
      if (url === "/whatsapp-conversations/c1/timeline") {
        return Promise.resolve({
          data: [{
            source: "conversation", direction: "in", kind: "text",
            text_body: "sempre na curva", media_attachment_id: null, purpose_label: null,
            sender_name: null, created_at: "2026-07-19T23:30:00Z",
          }],
        });
      }
      if (url === "/whatsapp-conversations/c1/window") {
        return Promise.resolve({ data: { within_session_window: true } });
      }
      if (url === "/whatsapp-templates") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });

    renderNaRota("/conversas");
    await waitFor(() => screen.getByText("Murilo Moreschi"));
    await userEvent.click(screen.getByText("Murilo Moreschi"));
    await waitFor(() => expect(screen.getAllByText("sempre na curva").length).toBeGreaterThan(0));

    expect(screen.getByText("08:30")).toBeInTheDocument();
    expect(screen.queryByText("20:30")).not.toBeInTheDocument();
    // O separador do dia acompanha: segunda 20/07 em Tóquio, domingo 19/07 em São Paulo. O regex
    // exige o dia-da-semana antes da data, o que distingue o SEPARADOR do carimbo da lista de
    // conversas (que é só a data) — mesma distinção do teste irmão.
    expect(screen.getByText(/^\S+,? 20\/07\/2026$/)).toBeInTheDocument();
    // 19/07 não aparece em lugar NENHUM da tela: nem no separador, nem no carimbo da lista, que
    // também converte pelo fuso do tenant.
    expect(screen.queryAllByText(/19\/07\/2026/)).toHaveLength(0);
  });

  it("distingue autor e mostra dia e horário de cada mensagem", async () => {
    // ⚠️ Fuso do runner de propósito: o que este teste mede é a AUTORIA ("Você ·") e a contagem
    // de separadores (um por dia, não um por mensagem) — não a conversão de fuso, que o teste
    // logo acima prova com o tenant em Tóquio. Não troque o fuso aqui.
    // Instantes fixos em UTC-3 (fuso do produto) para o horário renderizado ser previsível.
    // Os dois primeiros são do mesmo dia; o terceiro é de outro dia — exige 2 separadores.
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") {
        return Promise.resolve({
          data: [{
            chat_id: "c1", kind: "direct" as const, title: "Murilo Moreschi", phone: "5511977776666", client_id: "c1",
            last_message_at: "2026-07-20T17:19:00-03:00", last_message_preview: "Ok",
            unread: false,
          }],
        });
      }
      if (url === "/whatsapp-conversations/c1/timeline") {
        return Promise.resolve({
          data: [
            {
              source: "conversation", direction: "in", kind: "text",
              text_body: "sempre na curva", media_attachment_id: null, purpose_label: null, sender_name: null,
              created_at: "2026-07-19T14:18:00-03:00",
            },
            {
              source: "conversation", direction: "out", kind: "text",
              text_body: "Ok", media_attachment_id: null, purpose_label: null, sender_name: null,
              created_at: "2026-07-19T14:19:00-03:00",
            },
            {
              source: "conversation", direction: "out", kind: "text",
              text_body: "Primeira enviada", media_attachment_id: null, purpose_label: null, sender_name: null,
              created_at: "2026-07-20T17:19:00-03:00",
            },
          ],
        });
      }
      if (url === "/whatsapp-conversations/c1/window") {
        return Promise.resolve({ data: { within_session_window: true } });
      }
      if (url === "/whatsapp-templates") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);

    renderNaRota("/conversas");
    await waitFor(() => screen.getByText("Murilo Moreschi"));
    await userEvent.click(screen.getByText("Murilo Moreschi"));
    await waitFor(() => screen.getByText("sempre na curva"));

    // Autoria em texto: só as duas mensagens NOSSAS são marcadas "Você".
    expect(screen.getAllByText(/^Você ·/)).toHaveLength(2);
    // ...e a do cliente carrega só o horário, sem "Você".
    expect(screen.getByText("14:18")).toBeInTheDocument();
    expect(screen.getByText("Você · 14:19")).toBeInTheDocument();

    // Um separador por DIA (o fixture tem 3 mensagens em 2 dias), não um por mensagem. O
    // regex exige o dia-da-semana antes da data, o que distingue o separador ("dom., 19/07/2026")
    // do carimbo da lista de conversas, que é só a data ("20/07/2026").
    const separadores = screen.getAllByText(/^\S+,? \d{2}\/\d{2}\/\d{4}$/);
    expect(separadores.map((n) => n.textContent)).toEqual([
      "dom., 19/07/2026", "seg., 20/07/2026",
    ]);
  });

  it("abre um grupo, nomeia quem falou e permite responder", async () => {
    // O defeito reportado: grupo caía num balde "Não identificados" com `client_id: null`, que
    // a tela usava como chave de rota — clicar não abria nada, e o nome do grupo nunca aparecia.
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") {
        return Promise.resolve({
          data: [{
            chat_id: "g1", kind: "group" as const, title: "Automação Residencial",
            phone: null, client_id: null,
            last_message_at: "2026-07-20T11:05:00-03:00",
            last_message_preview: "Gabriel B: alguém indica?", unread: true,
          }],
        });
      }
      if (url === "/whatsapp-conversations/g1/timeline") {
        return Promise.resolve({
          data: [
            {
              source: "conversation", direction: "in", kind: "text",
              text_body: "alguém indica?", media_attachment_id: null, purpose_label: null,
              sender_name: "Gabriel B", created_at: "2026-07-20T11:05:00-03:00",
            },
            {
              source: "conversation", direction: "in", kind: "text",
              text_body: "eu uso a Intelbras", media_attachment_id: null, purpose_label: null,
              sender_name: "Ana P", created_at: "2026-07-20T11:07:00-03:00",
            },
          ],
        });
      }
      // Grupo não tem janela de 24h — o backend responde sempre "aberta".
      if (url === "/whatsapp-conversations/g1/window") {
        return Promise.resolve({ data: { within_session_window: true } });
      }
      if (url === "/whatsapp-templates") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);

    renderNaRota("/conversas");
    await waitFor(() => screen.getByText("Automação Residencial"));
    await userEvent.click(screen.getByText("Automação Residencial"));

    // O fio abriu de verdade — é o que não acontecia antes.
    await waitFor(() => screen.getByText("alguém indica?"));
    expect(screen.getByText("eu uso a Intelbras")).toBeInTheDocument();

    // Cada bolha recebida diz quem falou; sem isso o grupo é um muro anônimo.
    expect(screen.getByText("Gabriel B")).toBeInTheDocument();
    expect(screen.getByText("Ana P")).toBeInTheDocument();

    // E dá pra responder no grupo (decisão do fundador: grupo não é só leitura).
    expect(screen.getByPlaceholderText(/mensagem/i)).toBeInTheDocument();
  });

  it("troca pro seletor de template quando a janela de 24h está fechada", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") {
        return Promise.resolve({
          data: [{
            chat_id: "c2", kind: "direct" as const, title: "Cliente Antigo", phone: "5511888888888", client_id: "c2",
            last_message_at: "2026-07-01T10:00:00Z", last_message_preview: "oi",
            unread: false,
          }],
        });
      }
      if (url === "/whatsapp-conversations/c2/timeline") return Promise.resolve({ data: [] });
      if (url === "/whatsapp-conversations/c2/window") {
        return Promise.resolve({ data: { within_session_window: false } });
      }
      if (url === "/whatsapp-templates") {
        return Promise.resolve({
          data: [{
            id: "t1", name: "boas_vindas", language: "pt_BR", category_requested: "UTILITY",
            category_approved: "UTILITY", status: "APPROVED", rejected_reason: null,
            meta_template_id: "m1", body_text: "Olá {{1}}", variable_count: 1,
            variable_examples: ["Nome"], created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          }],
        });
      }
      return Promise.resolve({ data: [] });
    });

    renderNaRota("/conversas");
    await waitFor(() => screen.getByText("Cliente Antigo"));
    await userEvent.click(screen.getByText("Cliente Antigo"));
    await waitFor(() => expect(screen.queryByPlaceholderText(/mensagem/i)).not.toBeInTheDocument());
    // Exato (não regex): a mensagem explicativa acima do select também contém a substring
    // "selecione um template" em minúsculas, então um regex case-insensitive casa os dois nós.
    // O texto exato da option ("Selecione um template") é único.
    expect(screen.getByText("Selecione um template")).toBeInTheDocument();
  });

  it("limpa o rascunho e o fio anterior ao trocar de conversa", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") {
        return Promise.resolve({
          data: [
            {
              chat_id: "c1", kind: "direct" as const, title: "Cliente A", phone: "5511111111111", client_id: "c1",
              last_message_at: "2026-07-19T10:00:00Z", last_message_preview: "prévia A",
              unread: false,
            },
            {
              chat_id: "c2", kind: "direct" as const, title: "Cliente B", phone: "5511222222222", client_id: "c2",
              last_message_at: "2026-07-19T11:00:00Z", last_message_preview: "prévia B",
              unread: false,
            },
          ],
        });
      }
      if (url === "/whatsapp-conversations/c1/timeline") {
        return Promise.resolve({
          data: [{
            source: "conversation", direction: "in", kind: "text",
            text_body: "Mensagem da conversa A", media_attachment_id: null, purpose_label: null, sender_name: null,
            created_at: "2026-07-19T10:00:00Z",
          }],
        });
      }
      if (url === "/whatsapp-conversations/c1/window") {
        return Promise.resolve({ data: { within_session_window: true } });
      }
      if (url === "/whatsapp-conversations/c2/timeline") {
        return Promise.resolve({
          data: [{
            source: "conversation", direction: "in", kind: "text",
            text_body: "Mensagem da conversa B", media_attachment_id: null, purpose_label: null, sender_name: null,
            created_at: "2026-07-19T11:00:00Z",
          }],
        });
      }
      if (url === "/whatsapp-conversations/c2/window") {
        return Promise.resolve({ data: { within_session_window: true } });
      }
      if (url === "/whatsapp-templates") return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);

    renderNaRota("/conversas");
    await waitFor(() => screen.getByText("Cliente A"));

    await userEvent.click(screen.getByText("Cliente A"));
    await waitFor(() => screen.getByText("Mensagem da conversa A"));

    const input = screen.getByPlaceholderText(/mensagem/i) as HTMLInputElement;
    await userEvent.type(input, "rascunho para A");
    expect(input).toHaveValue("rascunho para A");

    await userEvent.click(screen.getByText("Cliente B"));
    await waitFor(() => screen.getByText("Mensagem da conversa B"));

    expect(screen.queryByText("Mensagem da conversa A")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/mensagem/i)).toHaveValue("");
  });
});

const CONVERSA_DIRETA = {
  chat_id: "c1", kind: "direct" as const, title: "Flavio Kato", phone: "5511999998888",
  client_id: "cli1", last_message_at: "2026-08-04T10:00:00Z",
  last_message_preview: "Oi", unread: false,
};

const GRUPO = {
  chat_id: "g1", kind: "group" as const, title: "Turma 2026", phone: null,
  client_id: null, last_message_at: "2026-08-04T10:00:00Z",
  last_message_preview: "Bom dia", unread: false,
};

const TIMELINE_DO_CRM = {
  entries: [
    {
      id: "e1", kind: "crm.lead.criado", title: "Chegou pelo site", body: "",
      actor: "pagina:lead", is_ai: false, at: "2026-07-01T10:00:00Z",
    },
  ],
  truncated: false,
};

function mockarConversas(conversas: unknown[]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/whatsapp-conversations") {
      return Promise.resolve({ data: conversas } as never);
    }
    if (url.startsWith("/crm/clients/")) {
      return Promise.resolve({ data: TIMELINE_DO_CRM } as never);
    }
    if (url.endsWith("/window")) {
      return Promise.resolve({ data: { within_session_window: true } } as never);
    }
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
}

describe("ConversasPage — painel de histórico", () => {
  it("conversa direta com contato mostra o histórico do CRM", async () => {
    mockarConversas([CONVERSA_DIRETA]);
    renderNaRota("/conversas");
    await userEvent.click(await screen.findByText("Flavio Kato"));

    expect(await screen.findByTestId("painel-historico")).toBeInTheDocument();
    expect(await screen.findByText("Chegou pelo site")).toBeInTheDocument();
  });

  it("conversa de grupo diz em TEXTO que não há contato ligado", async () => {
    mockarConversas([GRUPO]);
    renderNaRota("/conversas");
    await userEvent.click(await screen.findByText("Turma 2026"));

    expect(
      await screen.findByText(/não está ligada a um contato do CRM/i),
    ).toBeInTheDocument();
  });

  it("o histórico NÃO entra no polling de 7s", async () => {
    // `fireEvent` em vez de `userEvent` aqui de propósito: userEvent com fake timers exige
    // configuração de `advanceTimers` e falha de forma confusa sem ela.
    vi.useFakeTimers();
    mockarConversas([CONVERSA_DIRETA]);
    renderNaRota("/conversas");
    await vi.advanceTimersByTimeAsync(0);      // resolve a carga inicial das conversas
    fireEvent.click(screen.getByText("Flavio Kato"));
    await vi.advanceTimersByTimeAsync(0);      // resolve a carga da timeline

    const chamadasDeTimeline = () =>
      vi.mocked(api.get).mock.calls.filter(([u]) =>
        String(u).startsWith("/crm/clients/"),
      ).length;

    const antes = chamadasDeTimeline();
    expect(antes).toBeGreaterThan(0);          // controle positivo: carregou uma vez

    await vi.advanceTimersByTimeAsync(21_000); // 3 ciclos de POLL_MS
    expect(chamadasDeTimeline()).toBe(antes);
    vi.useRealTimers();
  });
});

// ── Conversa com URL própria ────────────────────────────────────────────────

/** Duas conversas, para que "abriu a certa" seja uma afirmação com conteúdo. */
function mockarDuasConversas() {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/whatsapp-conversations") {
      return Promise.resolve({
        data: [
          {
            chat_id: "c1", kind: "direct" as const, title: "Doro Eventos",
            phone: "5511999999999", client_id: "cli-1",
            last_message_at: "2026-07-19T10:00:00Z",
            last_message_preview: "Oi, quero o cardápio", unread: true,
          },
          {
            chat_id: "c2", kind: "direct" as const, title: "Murilo Moreschi",
            phone: "5511977776666", client_id: "cli-2",
            last_message_at: "2026-07-20T11:00:00Z",
            last_message_preview: "Ok", unread: false,
          },
        ],
      });
    }
    if (url.endsWith("/timeline")) {
      return Promise.resolve({
        data: [{
          source: "conversation", direction: "in", kind: "text",
          text_body: "Oi, quero o cardápio", media_attachment_id: null,
          purpose_label: null, sender_name: null, created_at: "2026-07-19T10:00:00Z",
        }],
      });
    }
    if (url.endsWith("/window")) {
      return Promise.resolve({ data: { within_session_window: true } });
    }
    if (url === "/whatsapp-templates") return Promise.resolve({ data: [] });
    return Promise.resolve({ data: [] });
  });
  // Abrir uma conversa dispara POST /{id}/read. Sem isto o `await` recebe undefined e o
  // teste passa por acidente — melhor mockar do que depender disso.
  vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
}

describe("ConversasPage — a conversa tem URL própria", () => {
  it("com /conversas/:chatId, abre aquela conversa direto", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas/c2");
    // O campo de digitar só existe quando uma conversa está aberta.
    expect(await screen.findByPlaceholderText(/mensagem/i)).toBeInTheDocument();
    // E abriu a CERTA: a prova é qual timeline foi buscada, não o título na tela — título
    // aparece na lista também, e a asserção ficaria verde com a conversa errada aberta.
    expect(api.get).toHaveBeenCalledWith("/whatsapp-conversations/c2/timeline");
    expect(api.get).not.toHaveBeenCalledWith("/whatsapp-conversations/c1/timeline");
  });

  it("com /conversas, mostra a lista sem nenhuma conversa aberta", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas");
    expect(await screen.findByText("Doro Eventos")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/mensagem/i)).not.toBeInTheDocument();
  });

  it("clicar numa conversa muda a URL", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas");
    await userEvent.click(await screen.findByText("Doro Eventos"));
    expect(await screen.findByPlaceholderText(/mensagem/i)).toBeInTheDocument();
    // A prova de que a URL realmente mudou (não só que "alguma" conversa abriu): o componente lê
    // o id da URL via `useParams`, então uma timeline buscada para c1 só acontece se a rota virou
    // /conversas/c1 — mesmo raciocínio do primeiro teste deste describe.
    expect(api.get).toHaveBeenCalledWith("/whatsapp-conversations/c1/timeline");
  });

  it("chatId que não existe cai na lista com aviso, e não em tela branca", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas/nao-existe");
    expect(await screen.findByText(/conversa não encontrada/i)).toBeInTheDocument();
    expect(screen.getByText("Doro Eventos")).toBeInTheDocument();
  });

  it("chatId que não existe NÃO monta o painel de conversa nem bate a API dele", async () => {
    // Achado da revisão: `mockarDuasConversas` responde `/timeline` para QUALQUER id (inclusive
    // um inventado), então uma checagem só de "a tela não quebrou" não pega o painel montando por
    // engano — o mock "concorda" alegremente com o id errado. A prova real é dupla: o campo de
    // digitar (só existe com uma conversa aberta de verdade) não aparece, E a API do painel nunca
    // foi chamada para o id que não existe.
    mockarDuasConversas();
    renderNaRota("/conversas/nao-existe");
    await screen.findByText(/conversa não encontrada/i);
    expect(screen.queryByPlaceholderText(/mensagem/i)).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalledWith("/whatsapp-conversations/nao-existe/timeline");
  });
});

// ── "Ainda carregando" vs. "carregou e está vazia" ──────────────────────────
//
// Achado da revisão final: `naoEncontrada` exigia `conversations.length > 0`, então um tenant
// SEM NENHUMA conversa nunca tornava essa condição verdadeira — um `/conversas/:id` de bookmark
// velho ficava travado para sempre (não um flash: permanente). Os quatro testes abaixo cobrem os
// estados que a distinção "carregou" vs. "não carregou ainda" precisa separar corretamente, e
// verificam em cada um o invariante do celular: lista OU conversa, nunca as duas.

/** No celular (jsdom não aplica CSS de verdade), a classe `hidden` é o que de fato esconde a
 * coluna — checar direto na `className` em vez de `toBeVisible()`, que não enxerga Tailwind
 * sem folha de estilo carregada. */
function visivelNoCelular(el: HTMLElement): boolean {
  return !el.className.split(/\s+/).includes("hidden");
}

describe("ConversasPage — carregando vs. vazia", () => {
  it("chatId desconhecido num tenant SEM NENHUMA conversa mostra aviso, não fica travado", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") return Promise.resolve({ data: [] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderNaRota("/conversas/nao-existe");

    expect(await screen.findByText(/conversa não encontrada/i)).toBeInTheDocument();
    expect(screen.getByText(/nenhuma conversa ainda/i)).toBeInTheDocument();
    // Lista visível (com o aviso), painel escondido — não os dois ao mesmo tempo no celular.
    expect(visivelNoCelular(screen.getByTestId("lista-conversas"))).toBe(true);
    expect(visivelNoCelular(screen.getByTestId("painel-conversa"))).toBe(false);
  });

  it("id válido ANTES da lista responder mostra um carregando neutro, nunca 'selecione uma conversa'", async () => {
    // `/whatsapp-conversations` fica pendurada de propósito — simula o instante entre o mount e
    // a resposta do fetch, que hoje (achado da revisão) mostrava "Selecione uma conversa" para
    // um usuário que JÁ selecionou, via link ou bookmark.
    let resolvePendente!: (v: unknown) => void;
    const pendente = new Promise((resolve) => { resolvePendente = resolve; });
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") return pendente as Promise<never>;
      if (url === "/whatsapp-conversations/c1/timeline") return Promise.resolve({ data: [] } as never);
      // Janela aberta de propósito: sem isto o fio (uma vez montado) trocaria o campo de texto
      // pelo seletor de template, e a asserção de `/mensagem/i` do fim deste teste erraria por
      // um motivo que nada tem a ver com o que ele está provando.
      if (url === "/whatsapp-conversations/c1/window") {
        return Promise.resolve({ data: { within_session_window: true } } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);

    renderNaRota("/conversas/c1");

    expect(await screen.findByText(/carregando conversa/i)).toBeInTheDocument();
    expect(screen.queryByText(/^selecione uma conversa$/i)).not.toBeInTheDocument();
    // Lista escondida, painel (com o carregando) visível — mesmo invariante do celular.
    expect(visivelNoCelular(screen.getByTestId("lista-conversas"))).toBe(false);
    expect(visivelNoCelular(screen.getByTestId("painel-conversa"))).toBe(true);

    resolvePendente({
      data: [{
        chat_id: "c1", kind: "direct" as const, title: "Ju", phone: "5511999998888",
        client_id: "cli-1", last_message_at: "2026-08-15T23:10:00Z",
        last_message_preview: "Boa noite", unread: false,
      }],
    });
    // Resolveu e achou a conversa: o carregando neutro dá lugar ao fio de verdade.
    expect(await screen.findByPlaceholderText(/mensagem/i)).toBeInTheDocument();
    expect(screen.queryByText(/carregando conversa/i)).not.toBeInTheDocument();
  });

  it("/conversas sem id mostra só a lista, painel escondido — sem carregando nem aviso", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas");

    expect(await screen.findByText("Doro Eventos")).toBeInTheDocument();
    expect(screen.queryByText(/carregando conversa/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/conversa não encontrada/i)).not.toBeInTheDocument();
    expect(visivelNoCelular(screen.getByTestId("lista-conversas"))).toBe(true);
    expect(visivelNoCelular(screen.getByTestId("painel-conversa"))).toBe(false);
  });

  it("chatId válido, tenant COM conversas: lista some no celular, painel mostra o fio", async () => {
    mockarDuasConversas();
    renderNaRota("/conversas/c1");

    expect(await screen.findByPlaceholderText(/mensagem/i)).toBeInTheDocument();
    expect(visivelNoCelular(screen.getByTestId("lista-conversas"))).toBe(false);
    expect(visivelNoCelular(screen.getByTestId("painel-conversa"))).toBe(true);
  });
});
