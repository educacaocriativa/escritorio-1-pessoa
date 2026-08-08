import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import EmpresaDnaTab from "./EmpresaDnaTab";

const CATALOGO = vi.hoisted(() => [
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
    key: "limites.nunca_faco",
    classe: "retrato",
    eixo: "limites",
    texto: "O que você nunca faz?",
    formato: "texto",
    opcoes: [],
  },
]);

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), put: vi.fn(), post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

function mockar(respostas: Record<string, unknown>) {
  vi.mocked(api.get).mockImplementation((url: string) =>
    Promise.resolve({ data: url === "/dna/catalogo" ? CATALOGO : respostas } as never),
  );
}

describe("EmpresaDnaTab", () => {
  it("agrupa por eixo e mostra quantas faltam", async () => {
    mockar({ "oferta.o_que_vende": "servico_projeto" });
    render(<EmpresaDnaTab />);

    await waitFor(() => expect(screen.getByText("Oferta")).toBeInTheDocument());
    expect(screen.getByText("Limites")).toBeInTheDocument();
    expect(screen.getByText(/1 de 2 respondidas/i)).toBeInTheDocument();
  });

  it("mostra o RÓTULO da resposta, não o valor interno", async () => {
    mockar({ "oferta.o_que_vende": "servico_projeto" });
    render(<EmpresaDnaTab />);

    await waitFor(() => expect(screen.getByText("Serviço por projeto")).toBeInTheDocument());
    expect(screen.queryByText("servico_projeto")).not.toBeInTheDocument();
  });

  it("a não respondida aparece como pergunta aberta", async () => {
    mockar({ "oferta.o_que_vende": "servico_projeto" });
    render(<EmpresaDnaTab />);

    await waitFor(() => expect(screen.getByText("O que você nunca faz?")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /salvar/i })).toBeInTheDocument();
  });
});
