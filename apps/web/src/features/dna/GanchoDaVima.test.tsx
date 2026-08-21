import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

/**
 * Monta o gancho com `data` como resposta de `/dna/pendente` e SÓ DEVOLVE depois que o `.then()`
 * do axios e o `setState` correspondente já rodaram.
 *
 * Sem esse flush, `expect(container).toBeEmptyDOMElement()` passaria no instante 0 — antes de o
 * componente ter chance de renderizar o card fantasma — e o teste aprovaria a regressão que
 * existe para pegar. O `waitFor` sozinho não resolve: ele para na PRIMEIRA passada.
 */
async function montar(data: unknown) {
  vi.mocked(api.get).mockResolvedValue({ data });
  const utils = render(<GanchoDaVima gancho="briefing.ausencia.comercial.card.parado" />);
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
  await act(async () => {
    await Promise.resolve();
  });
  return utils;
}

/**
 * Erros que o React reportou durante o teste.
 *
 * Um payload sem forma não pode só deixar o DOM vazio — `PerguntaDaVima` faz `.map` em `opcoes`,
 * e um estouro no RENDER também esvazia o container (o React desmonta a árvore sem error
 * boundary). Sem esta lista, `toBeEmptyDOMElement()` aprovaria a tela hospedeira caindo, que é o
 * oposto do "falha em silêncio, sempre" — medido: sob a mutação `data ?? null`, os dois casos de
 * `opcoes` passavam verdes com `TypeError: Cannot read properties of undefined (reading 'map')`
 * no stderr.
 */
let errosDoReact: unknown[][] = [];

beforeEach(() => {
  vi.clearAllMocks();
  errosDoReact = [];
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    errosDoReact.push(args);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GanchoDaVima", () => {
  it("não renderiza nada quando não há pergunta para hoje", async () => {
    const { container } = await montar(null);
    expect(container).toBeEmptyDOMElement();
  });

  it("some depois de responder, sem recarregar a tela", async () => {
    vi.mocked(api.put).mockResolvedValue({ data: {} });
    await montar(PERGUNTA);
    expect(screen.getByText("Há quanto tempo te incomoda?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "5 dias" }));
    await waitFor(() =>
      expect(screen.queryByText("Há quanto tempo te incomoda?")).not.toBeInTheDocument(),
    );
  });

  it("erro na busca não derruba a tela hospedeira", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("403"));
    const { container } = render(<GanchoDaVima gancho="qualquer" />);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    await act(async () => {
      await Promise.resolve();
    });
    expect(container).toBeEmptyDOMElement();
  });

  // ── Guarda por forma (issue #161) ────────────────────────────────────────────
  //
  // O card fantasma custou 101px de deslocamento acima da dobra em SEIS telas (agenda, cobrancas,
  // crm, orcamentos, pagar, vima). Cada caso abaixo é um payload que `data ?? null` deixava passar
  // e que a guarda por veracidade (`if (!pergunta)`) não pegava.
  describe("payload sem forma de pergunta não vira card", () => {
    const INVALIDOS: [string, unknown][] = [
      // O gatilho literal do #149: `mockarApi` devolvia `[]` para rota não mapeada, e `[]` é truthy.
      ["array vazio (rota não mapeada no mock e2e)", []],
      ["array com um objeto bem formado dentro", [PERGUNTA]],
      ["objeto vazio", {}],
      ["zero", 0],
      ["string vazia", ""],
      ["string não vazia", "sem pergunta hoje"],
      ["true", true],
      ["null", null],
      ["undefined", undefined],
      // Bem formado por fora, fantasma por dentro: é EXATAMENTE o desenho do card quebrado da
      // issue — parágrafo vazio + "Responder depois" pendurado. Rejeitar é o certo; aceitar seria
      // consertar o `??` e continuar entregando o mesmo pixel errado.
      ["texto vazio", { ...PERGUNTA, texto: "" }],
      ["texto só com espaço", { ...PERGUNTA, texto: "   " }],
      ["texto ausente", { ...PERGUNTA, texto: undefined }],
      ["texto não-string", { ...PERGUNTA, texto: 42 }],
      ["key ausente", { ...PERGUNTA, key: undefined }],
      ["key não-string", { ...PERGUNTA, key: 42 }],
      ["key vazia", { ...PERGUNTA, key: "" }],
      ["classe fora do par calibracao/retrato", { ...PERGUNTA, classe: "inventada" }],
      ["classe ausente", { ...PERGUNTA, classe: undefined }],
      ["formato desconhecido", { ...PERGUNTA, formato: "slider" }],
      ["formato ausente", { ...PERGUNTA, formato: undefined }],
      // Sem este, `PerguntaDaVima` faz `.map` em `undefined` e ESTOURA no render — e render não
      // cai no `.catch()` da promise: derrubaria a tela hospedeira inteira.
      ["opcoes ausente", { ...PERGUNTA, opcoes: undefined }],
      ["opcoes não-array", { ...PERGUNTA, opcoes: { rotulo: "5 dias" } }],
    ];

    it.each(INVALIDOS)("%s → nada renderizado, sem estourar", async (_nome, data) => {
      const { container } = await montar(data);
      expect(container).toBeEmptyDOMElement();
      expect(screen.queryByRole("button", { name: "Responder depois" })).not.toBeInTheDocument();
      // DOM vazio por guarda, não por árvore desmontada depois de um estouro no render.
      expect(errosDoReact).toEqual([]);
    });
  });

  it("pergunta com forma completa ainda renderiza o card", async () => {
    await montar(PERGUNTA);
    expect(screen.getByText("Há quanto tempo te incomoda?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Responder depois" })).toBeInTheDocument();
  });

  // `opcoes: []` é legítimo no contrato (`formato: "texto"` não tem opções) — a guarda é de forma,
  // não de conteúdo, e inventar "escolha precisa de ao menos uma opção" seria regra nova.
  it("aceita opcoes vazia (formato texto)", async () => {
    await montar({ ...PERGUNTA, formato: "texto", opcoes: [] });
    expect(screen.getByText("Há quanto tempo te incomoda?")).toBeInTheDocument();
  });
});
