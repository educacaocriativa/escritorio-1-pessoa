import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api } from "../../lib/api";
import BlocoDaConversa from "./BlocoDaConversa";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

vi.mock("../../store/auth", () => ({ useFuso: () => "America/Sao_Paulo" }));

const conversa = (chat_id: string, title: string) => ({
  chat_id, kind: "direct", title, phone: "5511999998888",
  client_id: "cli-1", last_message_at: "2026-08-15T23:10:00Z",
  last_message_preview: "Boa noite", unread: false,
});

const mensagens = [
  {
    source: "conversation", direction: "in", kind: "text",
    text_body: "Boa noite", media_attachment_id: null, purpose_label: null,
    sender_name: null, created_at: "2026-08-15T23:10:00Z",
  },
  {
    source: "conversation", direction: "out", kind: "text",
    text_body: "Oi Ju, tudo bem?", media_attachment_id: null, purpose_label: null,
    sender_name: null, created_at: "2026-08-15T23:16:00Z",
  },
];

function mockar(conversas: unknown[], timeline: unknown[] = mensagens) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url.startsWith("/whatsapp-conversations?")) {
      return Promise.resolve({ data: conversas } as never);
    }
    if (url.includes("/timeline")) return Promise.resolve({ data: timeline } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

const renderBloco = () =>
  render(
    <MemoryRouter>
      <BlocoDaConversa clientId="cli-1" />
    </MemoryRouter>,
  );

// Corpo em bloco de propósito: `mockReset()` devolve o próprio mock (para encadeamento), e um
// `beforeEach` de expressão única devolveria esse mock como seu retorno. O Vitest trata QUALQUER
// função devolvida por `beforeEach`/`it` como um hook de limpeza pós-teste — e chamaria
// `api.get()` sem argumento nenhum depois de cada teste, um `url` `undefined` que quebrava
// `url.startsWith(...)` no `mockar`. Mesmo padrão de `ConversasPage.test.tsx`/`ClientTimeline.test.tsx`.
beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("BlocoDaConversa", () => {
  it("mostra as últimas mensagens da conversa", async () => {
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();
    expect(await screen.findByText("Boa noite")).toBeInTheDocument();
    expect(screen.getByText("Oi Ju, tudo bem?")).toBeInTheDocument();
  });

  it("leva para a conversa com o link certo", async () => {
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();
    const link = await screen.findByRole("link", { name: /abrir conversa/i });
    expect(link).toHaveAttribute("href", "/conversas/chat-1");
  });

  it("sem conversa, diz isso e NÃO oferece iniciar uma", async () => {
    mockar([]);
    renderBloco();
    expect(await screen.findByText(/nenhuma conversa no whatsapp/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /iniciar/i })).not.toBeInTheDocument();
  });

  it("com duas conversas, mostra a mais recente e avisa da outra", async () => {
    // Fora de ordem de propósito: o bloco escolhe pela data, não pela posição na lista.
    mockar([
      { ...conversa("chat-antigo", "Ju"), last_message_at: "2026-08-01T10:00:00Z" },
      { ...conversa("chat-novo", "Ju"), last_message_at: "2026-08-15T23:10:00Z" },
    ]);
    renderBloco();
    expect(await screen.findByRole("link", { name: /abrir conversa/i }))
      .toHaveAttribute("href", "/conversas/chat-novo");
    expect(screen.getByText(/\+1 outra conversa/i)).toBeInTheDocument();
  });

  it("falha de rede vira aviso, não derruba a ficha", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("caiu"));
    renderBloco();
    expect(await screen.findByText(/não foi possível carregar a conversa/i)).toBeInTheDocument();
  });
});
