import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import PerguntePage from "./PerguntePage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    "Erro inesperado",
}));

beforeEach(() => {
  vi.mocked(api.post).mockReset();
});

describe("PerguntePage", () => {
  it("mostra uma dica quando não há mensagem nenhuma ainda", () => {
    render(<PerguntePage />);
    expect(screen.getByText(/pergunte sobre/i)).toBeInTheDocument();
  });

  it("envia a pergunta e mostra a resposta da Vima", async () => {
    vi.mocked(api.post).mockResolvedValue({
      data: { resposta: "Você tem R$ 500,00 a receber.", por_ia: true },
    });
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(
      screen.getByPlaceholderText(/digite sua pergunta/i),
      "quanto tenho a receber?{enter}",
    );

    expect(await screen.findByText("quanto tenho a receber?")).toBeInTheDocument();
    expect(await screen.findByText("Você tem R$ 500,00 a receber.")).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("/vima/pergunta", {
      texto: "quanto tenho a receber?",
      historico: [],
    });
  });

  it("a segunda pergunta reenvia o histórico da primeira", async () => {
    vi.mocked(api.post)
      .mockResolvedValueOnce({ data: { resposta: "R$ 500,00", por_ia: true } })
      .mockResolvedValueOnce({ data: { resposta: "R$ 100,00 essa semana", por_ia: true } });
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(
      screen.getByPlaceholderText(/digite sua pergunta/i),
      "quanto tenho a receber?{enter}",
    );
    await screen.findByText("R$ 500,00");
    await usuario.type(screen.getByPlaceholderText(/digite sua pergunta/i), "e essa semana?{enter}");
    await screen.findByText("R$ 100,00 essa semana");

    expect(api.post).toHaveBeenLastCalledWith("/vima/pergunta", {
      texto: "e essa semana?",
      historico: [
        { papel: "usuario", texto: "quanto tenho a receber?" },
        { papel: "vima", texto: "R$ 500,00" },
      ],
    });
  });

  it("mostra o erro sem derrubar a tela quando a requisição falha", async () => {
    vi.mocked(api.post).mockRejectedValue({ response: { data: { detail: "IA indisponível" } } });
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(screen.getByPlaceholderText(/digite sua pergunta/i), "oi{enter}");
    expect(await screen.findByText("IA indisponível")).toBeInTheDocument();
  });

  it("não envia pergunta vazia", async () => {
    render(<PerguntePage />);
    const usuario = userEvent.setup();
    await usuario.type(screen.getByPlaceholderText(/digite sua pergunta/i), "   {enter}");
    await waitFor(() => expect(api.post).not.toHaveBeenCalled());
  });
});
