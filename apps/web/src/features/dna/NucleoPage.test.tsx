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

// ── Payload fora de forma (issue #179) ───────────────────────────────────────
//
// Irmão direto do #161: lá `data ?? null` deixava passar truthy inesperado e rendia card
// FANTASMA; aqui `data ?? []` deixava passar e rendia **TELA BRANCA**. `{}` é truthy, então
// `!perguntas` não pega; `perguntas.length === 0` é `undefined === 0` → falso; e `perguntas[i].key`
// estoura DENTRO do render — que não cai no `.catch()` da promise.
describe("NucleoPage — payload fora de forma não deixa a tela branca", () => {
  // `0` e `""` são falsy e já caíam no ramo antigo; `[]`/`{}`/array de forma errada são os que
  // passavam. Todos são exercitados pelo mesmo contrato: degrada como núcleo vazio.
  it.each([
    ["objeto vazio", {}],
    ["objeto de erro serializado", { detail: "boom" }],
    ["string", "ok"],
    ["número", 7],
    ["booleano", true],
    ["array de forma errada", [{ foo: 1 }]],
    ["array com item sem opcoes", [{ key: "a", texto: "t", classe: "retrato", formato: "escolha" }]],
    ["null", null],
    ["zero", 0],
    ["string vazia", ""],
  ])("%s → sai como núcleo vazio, sem estourar", async (_rotulo, payload) => {
    apiMock.get.mockResolvedValue({ data: payload });
    montar();

    await waitFor(() => expect(navegar).toHaveBeenCalledWith("/", { replace: true }));
    // Nada foi exibido, então não houve abertura — o mesmo contrato do núcleo vazio.
    expect(apiMock.post).not.toHaveBeenCalled();
  });

  it("item malformado no meio da lista é DESCARTADO, os válidos continuam", async () => {
    // Filtrar, e não rejeitar a lista inteira: uma pergunta nova com contrato quebrado no servidor
    // não pode apagar as outras cinco. E o denominador que a telemetria grava passa a ser o que a
    // pessoa REALMENTE viu — que é o que o comentário de `avisar("open")` já prometia.
    apiMock.get.mockResolvedValue({ data: [PERGUNTAS[0], { foo: 1 }, PERGUNTAS[1]] });
    montar();

    await waitFor(() => expect(screen.getByText("O que você vende?")).toBeInTheDocument());
    expect(screen.getByText("1 de 2")).toBeInTheDocument();
    expect(apiMock.post).toHaveBeenCalledWith("/dna/nucleo/open", { exibidas: 2 });
  });
});
