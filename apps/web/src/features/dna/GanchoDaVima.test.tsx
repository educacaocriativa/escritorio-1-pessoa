import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import GanchoDaVima from "./GanchoDaVima";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

const PERGUNTA = {
  key: "ritmo.card_parado_dias",
  classe: "calibracao",
  eixo: "ritmo",
  texto: "Há quanto tempo te incomoda?",
  formato: "escolha",
  opcoes: [
    { rotulo: "5 dias", valor: 5 },
    { rotulo: "10 dias", valor: 10 },
  ],
};

describe("GanchoDaVima", () => {
  it("não renderiza nada quando não há pergunta para hoje", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });
    const { container } = render(
      <GanchoDaVima gancho="briefing.ausencia.comercial.card.parado" />,
    );
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("some depois de responder, sem recarregar a tela", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: PERGUNTA });
    vi.mocked(api.put).mockResolvedValue({ data: {} });

    render(<GanchoDaVima gancho="briefing.ausencia.comercial.card.parado" />);
    await waitFor(() =>
      expect(screen.getByText("Há quanto tempo te incomoda?")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "5 dias" }));
    await waitFor(() =>
      expect(screen.queryByText("Há quanto tempo te incomoda?")).not.toBeInTheDocument(),
    );
  });

  it("erro na busca não derruba a tela hospedeira", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("403"));
    const { container } = render(<GanchoDaVima gancho="qualquer" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
