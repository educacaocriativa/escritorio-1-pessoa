import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ClientTimeline from "./ClientTimeline";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

const ENTRADA = {
  id: "1", kind: "lead_created", title: "Chegou pelo site", body: "",
  actor: "pagina:lead", is_ai: false, at: "2026-07-01T10:00:00Z",
};
const RETORNO = {
  id: "2", kind: "lead_return", title: "Voltou pelo site",
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
});
