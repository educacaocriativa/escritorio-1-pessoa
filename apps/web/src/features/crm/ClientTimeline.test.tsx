import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ClientTimeline from "./ClientTimeline";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

// Fuso do tenant igual ao do runner (o `vitest.config.ts` fixa `TZ: "America/Sao_Paulo"`), e aqui
// isso NÃO é o defeito da issue #120: quem varia é a MÁQUINA — o teste "formata no fuso do tenant"
// lá embaixo troca `process.env.TZ` para Tóquio, que é a outra metade da mesma prova. Nenhum outro
// teste deste arquivo afirma coisa alguma sobre data ou hora, então nada mais aqui depende de fuso.
vi.mock("../../store/auth", () => ({ useFuso: () => "America/Sao_Paulo" }));

const ENTRADA = {
  id: "1", kind: "crm.lead.criado", title: "Chegou pelo site", body: "",
  actor: "pagina:lead", is_ai: false, at: "2026-07-01T10:00:00Z",
};
const RETORNO = {
  id: "2", kind: "crm.lead.retornou", title: "Voltou pelo site",
  body: "Quero orcamento para 50 convidados",
  actor: "pagina:lead", is_ai: false, at: "2026-08-04T14:32:00Z",
};

describe("ClientTimeline", () => {
  beforeEach(() => vi.clearAllMocks());

  it("mostra as entradas da mais recente para a mais antiga", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [RETORNO, ENTRADA], truncated: false },
    } as never);

    render(<ClientTimeline clientId="c1" />);

    const titulos = await screen.findAllByTestId("timeline-title");
    expect(titulos.map((t) => t.textContent)).toEqual([
      "Voltou pelo site", "Chegou pelo site",
    ]);
  });

  it("mostra o texto que a pessoa preencheu no retorno", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [RETORNO], truncated: false },
    } as never);

    render(<ClientTimeline clientId="c1" />);
    expect(await screen.findByText(/50 convidados/)).toBeInTheDocument();
  });

  it("avisa quando o historico foi cortado, em vez de fingir que aquilo e tudo", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [ENTRADA], truncated: true },
    } as never);

    render(<ClientTimeline clientId="c1" />);
    expect(await screen.findByText(/mais recentes/i)).toBeInTheDocument();
  });

  it("grava a nota e recarrega a timeline", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [ENTRADA], truncated: false },
    } as never);
    vi.mocked(api.post).mockResolvedValue({ data: { ...ENTRADA, id: "3" } } as never);

    render(<ClientTimeline clientId="c1" />);
    await screen.findAllByTestId("timeline-title");

    await userEvent.type(screen.getByPlaceholderText(/decis/i), "Fechamos com 10%");
    await userEvent.click(screen.getByRole("button", { name: /registrar/i }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/crm/clients/c1/notes", {
        title: "Fechamos com 10%",
        body: "",
      }),
    );
    expect(api.get).toHaveBeenCalledTimes(2);  // recarrega depois de gravar
  });

  it("estado vazio nao aparece como erro", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [], truncated: false },
    } as never);

    render(<ClientTimeline clientId="c1" />);
    expect(await screen.findByText(/nenhum registro/i)).toBeInTheDocument();
  });

  describe("fuso do tenant, não da máquina", () => {
    const TZ_ORIGINAL = process.env.TZ;

    afterEach(() => {
      process.env.TZ = TZ_ORIGINAL;
    });

    it("formata no fuso do tenant, não no do navegador", async () => {
      // `vitest.config.ts` fixa TZ=America/Sao_Paulo pra suíte inteira — o MESMO fuso do
      // tenant mockado acima, então rodar isto com o `TZ` padrão faria o `quando()` ANTIGO
      // (sem `timeZone`, no relógio da máquina) acertar por coincidência: máquina e tenant
      // dariam o mesmo resultado, e o teste passaria mesmo sem o conserto. Pra provar a
      // correção de verdade, este teste simula a MÁQUINA em outro fuso (a viagem/servidor
      // headless que o comentário original da ConversasPage descrevia) e confirma que a tela
      // ignora o relógio dela e usa sempre o fuso do tenant, vindo de `useFuso()`.
      process.env.TZ = "Asia/Tokyo";

      const ENTRADA = {
        id: "9", kind: "agenda", title: "Compromisso: Reunião", body: "",
        actor: "sistema", is_ai: false, at: "2026-08-16T23:30:00Z",
      };
      vi.mocked(api.get).mockResolvedValue({
        data: { entries: [ENTRADA], truncated: false },
      } as never);

      render(<ClientTimeline clientId="c1" />);
      await screen.findByTestId("timeline-title");

      // Fuso do tenant (America/Sao_Paulo, UTC-3): 23:30 UTC vira 20:30 do MESMO dia 16/08.
      expect(screen.getByText("16/08/2026 20:30")).toBeInTheDocument();
      // O `quando()` antigo, no relógio da MÁQUINA (Tóquio, UTC+9), teria mostrado
      // 17/08/2026 08:30 — um dia adiante e 12h de diferença. Isso NÃO pode aparecer.
      expect(screen.queryByText("17/08/2026 08:30")).not.toBeInTheDocument();
      // ✅ VERIFICADO POR MUTAÇÃO (issue #120): trocar `formatDateTime(e.at, fuso)` por
      // `formatDateTime(e.at, Intl.DateTimeFormat().resolvedOptions().timeZone)` — ler pelo fuso
      // do navegador — MATA este teste. É a prova de que o `process.env.TZ` acima chega mesmo ao
      // `Intl` em tempo de execução, e de que a asserção não é decorativa.
    });
  });

  it("compromisso realizado tem identidade visual própria, não o ícone neutro", async () => {
    // O vocabulário de `kind` em APARENCIA é FECHADO: um `kind` sem entrada ali cai no
    // `NEUTRO` (`bg-neutral-100`). Este teste prova que "agenda" TEM entrada própria (mesma
    // família visual das outras fontes derivadas, `bg-sky-50`) — se o mapa esquecesse
    // "agenda", o compromisso realizado ficaria indistinguível de um `kind` desconhecido.
    const COMPROMISSO = {
      id: "7", kind: "agenda", title: "Compromisso: Sessão de fotos", body: "",
      actor: "sistema", is_ai: false, at: "2026-08-10T14:00:00Z",
    };
    vi.mocked(api.get).mockResolvedValue({
      data: { entries: [COMPROMISSO], truncated: false },
    } as never);

    render(<ClientTimeline clientId="c1" />);
    const titulo = await screen.findByTestId("timeline-title");
    const item = titulo.closest("li");

    expect(item?.querySelector(".bg-sky-50")).not.toBeNull();
    expect(item?.querySelector(".bg-neutral-100")).toBeNull();
  });
});
