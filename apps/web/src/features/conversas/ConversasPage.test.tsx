import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ConversasPage from "./ConversasPage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

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

    render(<ConversasPage />);
    await waitFor(() => screen.getByText("Doro Eventos"));
    await userEvent.click(screen.getByText("Doro Eventos"));
    // A prévia da lista e o corpo da mensagem no fio coincidem neste fixture, então mais de um
    // nó tem o mesmo texto — confirmamos que o fio abriu pela contagem (lista + bolha), não por
    // unicidade de texto.
    await waitFor(() => expect(screen.getAllByText("Oi, quero o cardápio")).toHaveLength(2));
    expect(screen.getByPlaceholderText(/mensagem/i)).toBeInTheDocument();
  });

  it("distingue autor e mostra dia e horário de cada mensagem", async () => {
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

    render(<ConversasPage />);
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

    render(<ConversasPage />);
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

    render(<ConversasPage />);
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

    render(<ConversasPage />);
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
