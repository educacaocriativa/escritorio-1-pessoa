import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import BriefingPage from "./BriefingPage";

// Rede sempre mockada: nenhum teste bate em /vima real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    "Erro inesperado",
}));

vi.mock("../../store/auth", () => ({
  useAuth: () => ({ user: { name: "Flávio Kato" } }),
  useFuso: () => "America/Sao_Paulo",
}));

const BRIEFING = {
  id: "b1",
  reference_date: "2026-08-06",
  texto: "Bom dia, Flávio. Entrou um pagamento de R$ 3.200,00 do João.",
  por_ia: true,
  vazio: false,
  excedente: 0,
  linhas: [
    { secao: "PENDENTE", module: "financeiro", texto: "Cobrança do João vencida há 4 dias" },
    { secao: "ACONTECEU", module: "financeiro", texto: "Pagamento de R$ 3.200,00 recebido" },
  ],
  read_at: null,
  created_at: "2026-08-06T10:05:00Z",
};

const PREFS = {
  briefing_whatsapp_enabled: false,
  briefing_hour: "07:00",
  briefing_whatsapp_disponivel: true,
  briefing_whatsapp_indisponivel_motivo: null,
};

/**
 * Responde por rota: a tela pede o briefing E as preferências. O `POST .../read` ECOA o mesmo
 * briefing com `read_at` preenchido — como a rota real faz. Devolver outro objeto aqui faria o
 * mock sobrescrever campos do caso sob teste (foi como este arquivo escondeu o caso `por_ia`).
 */
function mockGet(briefing: Record<string, unknown>, prefs: unknown = PREFS) {
  vi.mocked(api.get).mockImplementation((url: string) =>
    Promise.resolve({ data: url.includes("preferences") ? prefs : briefing }),
  );
  vi.mocked(api.post).mockResolvedValue({
    data: { ...briefing, read_at: "2026-08-06T10:06:00Z" },
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <BriefingPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
});

describe("BriefingPage", () => {
  it("mostra o texto do briefing e marca como lido", async () => {
    mockGet(BRIEFING);
    renderPage();

    await waitFor(() => expect(screen.getByText(/Entrou um pagamento/)).toBeInTheDocument());
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/vima/briefing/b1/read"));
  });

  it("marca como lido UMA vez — reabrir a tela não regrava a leitura", async () => {
    mockGet({ ...BRIEFING, read_at: "2026-08-06T10:06:00Z" });
    renderPage();

    await waitFor(() => expect(screen.getByText(/Entrou um pagamento/)).toBeInTheDocument());
    expect(api.post).not.toHaveBeenCalled();
  });

  it("dia sem nada não parece erro", async () => {
    mockGet({
      ...BRIEFING,
      id: "b2",
      texto: "Bom dia, Flávio. Tudo tranquilo por aqui.",
      vazio: true,
      linhas: [],
    });
    renderPage();

    await waitFor(() => expect(screen.getByText(/Tudo tranquilo/)).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("mostra as linhas como apoio, agrupadas por seção", async () => {
    mockGet(BRIEFING);
    renderPage();

    await waitFor(() => expect(screen.getByText(/vencida há 4 dias/)).toBeInTheDocument());
    expect(screen.getByText(/Pagamento de R\$ 3\.200,00 recebido/)).toBeInTheDocument();
  });

  it("rotula o rastro da IA quando a narração veio dela (Regra de Ouro nº 3)", async () => {
    mockGet(BRIEFING);
    renderPage();
    await waitFor(() => expect(screen.getByText(/Escrito pela IA/i)).toBeInTheDocument());
  });

  it("NÃO rotula quando o texto veio do template — dizer que foi a IA seria falso", async () => {
    mockGet({ ...BRIEFING, por_ia: false });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Entrou um pagamento/)).toBeInTheDocument());
    expect(screen.queryByText(/Escrito pela IA/i)).not.toBeInTheDocument();
  });

  it("falha de rede não deixa a tela em branco — o caminho para o painel continua", async () => {
    vi.mocked(api.get).mockRejectedValue({ response: { data: { detail: "Serviço indisponível" } } });
    renderPage();

    await waitFor(() => expect(screen.getByText(/Serviço indisponível/)).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /painel/i })).toBeInTheDocument();
  });
});

describe("BriefingPage — preferências na própria tela", () => {
  it("salva o horário sem exigir módulo nenhum", async () => {
    const user = userEvent.setup();
    mockGet(BRIEFING);
    vi.mocked(api.patch).mockResolvedValue({ data: { ...PREFS, briefing_hour: "08:30" } });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /prefer/i }));
    const hora = await screen.findByLabelText(/horário/i);
    await user.clear(hora);
    await user.type(hora, "08:30");
    await user.click(screen.getByRole("button", { name: /salvar/i }));

    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/auth/me/preferences", {
        briefing_hour: "08:30",
        briefing_whatsapp_enabled: false,
      }),
    );
  });

  it("tenant sem template aprovado: o switch fica desligado E a tela diz por quê", async () => {
    const user = userEvent.setup();
    mockGet(BRIEFING, {
      ...PREFS,
      briefing_whatsapp_disponivel: false,
      briefing_whatsapp_indisponivel_motivo:
        "O template do briefing ainda não foi aprovado pela Meta.",
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /prefer/i }));
    expect(await screen.findByText(/não foi aprovado pela Meta/)).toBeInTheDocument();
    expect(screen.getByLabelText(/whatsapp/i)).toBeDisabled();
  });

  it("entrega perdida não tranca a troca de horário", async () => {
    const user = userEvent.setup();
    mockGet(BRIEFING, {
      ...PREFS,
      // O estado que trava: ligado ANTES, indisponível AGORA (a Meta pausou o template, ou o
      // WhatsApp da empresa caiu). Reenviar `enabled: true` levaria 422 do backend e o dono
      // ficaria sem conseguir mudar nem o próprio horário.
      briefing_whatsapp_enabled: true,
      briefing_whatsapp_disponivel: false,
      briefing_whatsapp_indisponivel_motivo: "O template do briefing foi pausado pela Meta.",
    });
    vi.mocked(api.patch).mockResolvedValue({ data: PREFS });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /prefer/i }));
    await user.click(screen.getByRole("button", { name: /salvar/i }));

    await waitFor(() =>
      expect(api.patch).toHaveBeenCalledWith("/auth/me/preferences", {
        briefing_hour: "07:00",
        briefing_whatsapp_enabled: false,
      }),
    );
  });
});
