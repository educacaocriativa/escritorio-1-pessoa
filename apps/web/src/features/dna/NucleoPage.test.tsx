import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NucleoPage, { CHAVE_NUCLEO } from "./NucleoPage";

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

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
}));

const navegar = vi.hoisted(() => vi.fn());

vi.mock("../../lib/api", () => ({
  api: apiMock,
  apiErrorMessage: (e: unknown) => String(e),
}));

vi.mock("react-router-dom", async () => {
  const real = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...real, useNavigate: () => navegar };
});

function montar() {
  return render(
    <MemoryRouter>
      <NucleoPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  apiMock.get.mockResolvedValue({ data: PERGUNTAS });
  apiMock.put.mockResolvedValue({ data: {} });
  apiMock.post.mockResolvedValue({ data: {} });
});

describe("NucleoPage", () => {
  it("mostra uma pergunta por vez, com o progresso visível", async () => {
    montar();
    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());
    expect(screen.queryByText("O que você responde?")).not.toBeInTheDocument();
    expect(screen.getByText("1 de 2")).toBeInTheDocument();
  });

  it("oferece sair da sequência inteira — não é um beco", async () => {
    montar();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /pular por enquanto/i })).toBeInTheDocument(),
    );
  });

  it("avisa que o núcleo abriu, com o denominador que a pessoa VIU", async () => {
    montar();
    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());

    expect(apiMock.post).toHaveBeenCalledWith("/dna/nucleo/open", { exibidas: 2 });
  });

  it("403 no faltantes NÃO produz evento — a pessoa nunca entrou", async () => {
    apiMock.get.mockRejectedValue(new Error("403"));
    montar();

    await waitFor(() => expect(navegar).toHaveBeenCalledWith("/", { replace: true }));
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("núcleo vazio não é abertura nem abandono", async () => {
    apiMock.get.mockResolvedValue({ data: [] });
    montar();

    await waitFor(() => expect(navegar).toHaveBeenCalledWith("/", { replace: true }));
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("o beacon de abertura falhando NÃO tranca a entrada", async () => {
    // §6.2: a instrumentação tem de ter a mesma covardia que a página já tinha para o 403.
    apiMock.post.mockRejectedValue(new Error("500"));
    montar();

    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());
    expect(navegar).not.toHaveBeenCalled();
  });

  it("'Pular por enquanto' avisa o abandono E SAI SEM ESPERAR", async () => {
    // A asserção que mecaniza "a saída NÃO o aguarda": nenhum `await` entre o clique e a
    // verificação. Se alguém escrever `await api.post(...)` antes do `sair()`, a marca do
    // localStorage só existiria num microtask seguinte e esta linha falharia.
    apiMock.post.mockRejectedValue(new Error("500"));
    montar();
    const botao = await screen.findByRole("button", { name: /pular por enquanto/i });

    fireEvent.click(botao);

    expect(localStorage.getItem(CHAVE_NUCLEO)).toBe("1");
    expect(navegar).toHaveBeenCalledWith("/", { replace: true });
    expect(apiMock.post).toHaveBeenCalledWith("/dna/nucleo/abandon", {});
  });

  it("concluir a sequência NÃO é abandono", async () => {
    montar();
    // 1ª pergunta (escolha) → clica numa opção; 2ª é texto → escreve e salva.
    fireEvent.click(await screen.findByRole("button", { name: "Serviço por projeto" }));
    const caixa = await screen.findByPlaceholderText("Escreva do seu jeito");
    fireEvent.change(caixa, { target: { value: "Faço sites" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(navegar).toHaveBeenCalledWith("/", { replace: true }));
    expect(apiMock.post).not.toHaveBeenCalledWith("/dna/nucleo/abandon", {});
  });
});
