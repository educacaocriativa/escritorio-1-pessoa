import type { DnaPergunta } from "@e1p/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import PerguntaDaVima from "./PerguntaDaVima";

vi.mock("../../lib/api", () => ({
  api: {
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
  apiErrorMessage: (e: unknown) => String(e),
}));

const ESCOLHA: DnaPergunta = {
  key: "ritmo.card_parado_dias",
  classe: "calibracao",
  eixo: "ritmo",
  texto: "Uma negociação parada há quanto tempo te incomoda?",
  formato: "escolha",
  opcoes: [
    { rotulo: "5 dias", valor: 5 },
    { rotulo: "10 dias", valor: 10 },
  ],
};

const TEXTO: DnaPergunta = {
  key: "limites.nunca_faco",
  classe: "retrato",
  eixo: "limites",
  texto: "O que você nunca faz?",
  formato: "texto",
  opcoes: [],
};

describe("PerguntaDaVima", () => {
  it("responde uma escolha em um toque", async () => {
    const onPronto = vi.fn();
    render(<PerguntaDaVima pergunta={ESCOLHA} source="gancho" onPronto={onPronto} />);

    fireEvent.click(screen.getByRole("button", { name: "5 dias" }));

    await waitFor(() => expect(onPronto).toHaveBeenCalled());
    expect(api.put).toHaveBeenCalledWith("/dna/ritmo.card_parado_dias", {
      valor: 5,
      source: "gancho",
    });
  });

  it("avisa que Calibração vale a partir de amanhã", () => {
    render(<PerguntaDaVima pergunta={ESCOLHA} source="gancho" onPronto={vi.fn()} />);
    expect(screen.getByText(/a partir de amanhã/i)).toBeInTheDocument();
  });

  it("avisa que Retrato fica guardado, sem prometer efeito", () => {
    render(<PerguntaDaVima pergunta={TEXTO} source="config" onPronto={vi.fn()} />);
    expect(screen.getByText(/guardad/i)).toBeInTheDocument();
    expect(screen.queryByText(/a partir de amanhã/i)).not.toBeInTheDocument();
  });

  it("pular chama a rota de pular e não a de responder", async () => {
    const onPular = vi.fn();
    render(
      <PerguntaDaVima pergunta={TEXTO} source="gancho" onPronto={vi.fn()} onPular={onPular} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /depois/i }));

    await waitFor(() => expect(onPular).toHaveBeenCalled());
    expect(api.post).toHaveBeenCalledWith("/dna/limites.nunca_faco/pular", { source: "gancho" });
  });
});
