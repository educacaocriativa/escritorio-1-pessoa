import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import NucleoPage from "./NucleoPage";

// `vi.hoisted` porque a fábrica do `vi.mock` sobe para o topo do arquivo e não enxergaria um
// `const` comum declarado aqui.
const PERGUNTAS = vi.hoisted(() => [
  {
    key: "oferta.o_que_vende",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você vende?",
    formato: "escolha",
    opcoes: [
      { rotulo: "Serviço por projeto", valor: "servico_projeto" },
      { rotulo: "Produto digital", valor: "produto_digital" },
    ],
  },
  {
    key: "oferta.em_uma_frase",
    classe: "retrato",
    eixo: "oferta",
    texto: "O que você responde?",
    formato: "texto",
    opcoes: [],
  },
]);

vi.mock("../../lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: PERGUNTAS }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
  apiErrorMessage: (e: unknown) => String(e),
}));

describe("NucleoPage", () => {
  it("mostra uma pergunta por vez, com o progresso visível", async () => {
    render(
      <MemoryRouter>
        <NucleoPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());
    expect(screen.queryByText("O que você responde?")).not.toBeInTheDocument();
    expect(screen.getByText("1 de 2")).toBeInTheDocument();
  });

  it("oferece sair da sequência inteira — não é um beco", async () => {
    render(
      <MemoryRouter>
        <NucleoPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /pular por enquanto/i })).toBeInTheDocument(),
    );
  });
});
