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
            client_id: "c1", client_name: "Doro Eventos", client_phone: "5511999999999",
            last_message_at: "2026-07-19T10:00:00Z", last_message_preview: "Oi, quero o cardápio",
            unread: true,
          }],
        });
      }
      if (url === "/whatsapp-conversations/c1/timeline") {
        return Promise.resolve({
          data: [{
            source: "conversation", direction: "in", kind: "text",
            text_body: "Oi, quero o cardápio", media_attachment_id: null, purpose_label: null,
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

  it("troca pro seletor de template quando a janela de 24h está fechada", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/whatsapp-conversations") {
        return Promise.resolve({
          data: [{
            client_id: "c2", client_name: "Cliente Antigo", client_phone: "5511888888888",
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
});
