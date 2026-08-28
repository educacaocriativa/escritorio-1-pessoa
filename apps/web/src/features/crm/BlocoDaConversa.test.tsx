import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { api } from "../../lib/api";
import BlocoDaConversa from "./BlocoDaConversa";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

// O fuso do TENANT é trocável por teste (modelo de `NewEventModal.test.tsx`). O `vitest.config.ts`
// fixa o fuso da MÁQUINA em America/Sao_Paulo: com os dois iguais, `formatTime(m.created_at, fuso)`
// e ler o relógio do navegador dão a MESMA hora por construção, e nenhuma asserção consegue
// distinguir um do outro (issue #120).
let fusoDoTenant = "America/Sao_Paulo";
// Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner.
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

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

function mockar(
  conversas: unknown[],
  timeline: unknown[] = mensagens,
  whatsappProvider: string | null = null,
) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url.startsWith("/whatsapp-conversations?")) {
      return Promise.resolve({ data: conversas } as never);
    }
    if (url.includes("/timeline")) return Promise.resolve({ data: timeline } as never);
    if (url === "/settings/profile") {
      return Promise.resolve({ data: { whatsapp_provider: whatsappProvider } } as never);
    }
    return Promise.resolve({ data: [] } as never);
  });
}

const renderBloco = (clientPhone: string | null = "5511999998888") =>
  render(
    <MemoryRouter>
      <BlocoDaConversa clientId="cli-1" clientPhone={clientPhone} />
    </MemoryRouter>,
  );

// Corpo em bloco de propósito: `mockReset()` devolve o próprio mock (para encadeamento), e um
// `beforeEach` de expressão única devolveria esse mock como seu retorno. O Vitest trata QUALQUER
// função devolvida por `beforeEach`/`it` como um hook de limpeza pós-teste — e chamaria
// `api.get()` sem argumento nenhum depois de cada teste, um `url` `undefined` que quebrava
// `url.startsWith(...)` no `mockar`. Mesmo padrão de `ConversasPage.test.tsx`/`ClientTimeline.test.tsx`.
beforeEach(() => {
  vi.mocked(api.get).mockReset();
  fusoDoTenant = "America/Sao_Paulo";
});

describe("BlocoDaConversa", () => {
  it("mostra as últimas mensagens da conversa", async () => {
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();
    expect(await screen.findByText("Boa noite")).toBeInTheDocument();
    expect(screen.getByText("Oi Ju, tudo bem?")).toBeInTheDocument();
  });

  it("carimba a hora da mensagem no fuso do TENANT, não no do navegador", async () => {
    // O bloco mostra a hora de cada bolha (`formatTime(m.created_at, fuso)`) e, até a issue #120,
    // NENHUM teste daqui afirmava nada sobre ela — o mock de `useFuso` existia só para a tela não
    // quebrar. Com tenant e runner no mesmo fuso, acrescentar a asserção também não provaria
    // nada: 23:10Z daria 20:10 pelos dois caminhos.
    //
    // Tenant em Tóquio (UTC+9), máquina em São Paulo (UTC−3): 15/08 23:10Z é 08:10 do dia
    // SEGUINTE em Tóquio e 20:10 do mesmo dia em São Paulo.
    fusoDoTenant = FUSO_DISTANTE;
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();

    await screen.findByText("Boa noite");
    expect(screen.getByText("08:10")).toBeInTheDocument();
    expect(screen.queryByText("20:10")).not.toBeInTheDocument();
  });

  it("pede a timeline já cortada no servidor (limit=5), não a inteira", async () => {
    // Achado da revisão final: a ficha baixava a conversa INTEIRA (podem ser milhares de
    // mensagens num cliente ativo) só para mostrar cinco bolhas, cortando no cliente com
    // `.slice(-5)`. O corte tem que ser um parâmetro na URL, não um `.slice` depois do fetch —
    // senão o bug volta na próxima vez que alguém tocar neste componente sem notar a régua.
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();
    await screen.findByText("Boa noite");
    expect(api.get).toHaveBeenCalledWith("/whatsapp-conversations/chat-1/timeline?limit=5");
  });

  it("leva para a conversa com o link certo", async () => {
    mockar([conversa("chat-1", "Ju")]);
    renderBloco();
    const link = await screen.findByRole("link", { name: /abrir conversa/i });
    expect(link).toHaveAttribute("href", "/conversas/chat-1");
  });

  it("sem conversa na Meta, diz isso e NÃO oferece iniciar uma", async () => {
    // Meta exige template aprovado pra abrir do zero — sem isso, um botão que sempre falha é
    // pior que nenhum (mesmo raciocínio de antes desta mudança, agora restrito ao transporte).
    mockar([], mensagens, null);
    renderBloco();
    expect(await screen.findByText(/nenhuma conversa no whatsapp/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /iniciar/i })).not.toBeInTheDocument();
  });

  it("sem conversa na Evolution, oferece iniciar uma", async () => {
    // Evolution (QR code) não tem janela de 24h nem template — abrir do zero é possível.
    mockar([], mensagens, "evolution");
    renderBloco();
    expect(await screen.findByRole("button", { name: /iniciar conversa/i })).toBeInTheDocument();
  });

  it("sem conversa na Evolution mas sem telefone cadastrado, NÃO oferece iniciar", async () => {
    mockar([], mensagens, "evolution");
    renderBloco(null);
    await screen.findByText(/nenhuma conversa no whatsapp/i);
    expect(screen.queryByRole("button", { name: /iniciar conversa/i })).not.toBeInTheDocument();
  });

  it("envia a primeira mensagem e passa a mostrar a conversa criada", async () => {
    mockar([], mensagens, "evolution");
    vi.mocked(api.post).mockResolvedValue({ data: { chat_id: "chat-novo" } } as never);
    renderBloco();

    const user = userEvent.setup();
    const botao = await screen.findByRole("button", { name: /iniciar conversa/i });
    const campo = screen.getByRole("textbox");
    await user.type(campo, "Oi! Bem-vindo.");

    // A partir daqui a conversa já existe — a mesma lista que a tela buscaria de novo.
    mockar([conversa("chat-novo", "Ju")], mensagens, "evolution");
    await user.click(botao);

    expect(api.post).toHaveBeenCalledWith("/whatsapp-conversations/start", {
      client_id: "cli-1",
      text: "Oi! Bem-vindo.",
    });
    expect(await screen.findByRole("link", { name: /abrir conversa/i }))
      .toHaveAttribute("href", "/conversas/chat-novo");
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

  it("com três conversas, pluraliza corretamente o aviso da outras", async () => {
    mockar([
      { ...conversa("chat-1", "Ju"), last_message_at: "2026-08-01T10:00:00Z" },
      { ...conversa("chat-2", "Ju"), last_message_at: "2026-08-05T10:00:00Z" },
      { ...conversa("chat-3", "Ju"), last_message_at: "2026-08-15T23:10:00Z" },
    ]);
    renderBloco();
    expect(await screen.findByText(/\+2 outras conversas/i)).toBeInTheDocument();
  });

  it("escolhe a conversa com data em vez da sem data, mesmo a sem data vindo primeiro", async () => {
    // A sem-data aparece PRIMEIRO de propósito: se `maisRecente` naivamente pegasse o primeiro
    // item da lista, o teste pegaria isso.
    mockar([
      { ...conversa("chat-sem-data", "Ju"), last_message_at: null },
      { ...conversa("chat-com-data", "Ju"), last_message_at: "2026-08-10T10:00:00Z" },
    ]);
    renderBloco();
    expect(await screen.findByRole("link", { name: /abrir conversa/i }))
      .toHaveAttribute("href", "/conversas/chat-com-data");
  });

  it("falha de rede vira aviso, não derruba a ficha", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("caiu"));
    renderBloco();
    expect(await screen.findByText(/não foi possível carregar a conversa/i)).toBeInTheDocument();
  });

  it("falha só na timeline (segunda chamada) também vira aviso, sem meio-render", async () => {
    // A lista de conversas carrega bem — só o histórico de mensagens falha. Hoje as duas
    // chamadas dividem um único try/catch, então o bloco inteiro degrada para o aviso. Este
    // teste existe para pegar um futuro refactor que separe as duas chamadas e deixe o link
    // "Abrir conversa" pendurado com a área de mensagens vazia, sem avisar o dono de nada.
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.startsWith("/whatsapp-conversations?")) {
        return Promise.resolve({ data: [conversa("chat-1", "Ju")] } as never);
      }
      if (url.includes("/timeline")) return Promise.reject(new Error("caiu no timeline"));
      return Promise.resolve({ data: [] } as never);
    });
    renderBloco();
    expect(await screen.findByText(/não foi possível carregar a conversa/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /abrir conversa/i })).not.toBeInTheDocument();
  });
});
