import { beforeEach, describe, expect, it, vi } from "vitest";

// `lib/api` cria os clientes axios no import; mockar a fábrica mantém o módulo importável sem
// rede e devolve o mesmo objeto em `api`/`publicApi` (o que basta: só `api.post` é exercido).
const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));
vi.mock("axios", () => {
  const instancia = {
    post: postMock,
    get: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  };
  return { default: { create: () => instancia, isAxiosError: () => false }, AxiosError: class {} };
});

const { refreshSession } = await import("./api");

beforeEach(() => {
  postMock.mockReset();
});

/**
 * `refreshSession` guarda a SESSÃO — por isso a checagem é de FORMA, não de veracidade (#179).
 *
 * O retorno vai direto para o `localStorage` e daí para o header `Authorization`. Com o antigo
 * `data.access_token ?? null`, qualquer *truthy* passava: um objeto de erro serializado viraria
 * `Bearer [object Object]` e o backend responderia 401 opaco a cada request seguinte — em vez do
 * `null` que significa "não renovou", que é o caso que o interceptor sabe tratar (logout limpo).
 */
describe("refreshSession — token só é token se tiver FORMA de token", () => {
  it("devolve a string quando o servidor renova de verdade", async () => {
    postMock.mockResolvedValue({ data: { access_token: "tok-novo" } });
    await expect(refreshSession()).resolves.toBe("tok-novo");
  });

  it.each([
    ["objeto", { erro: "boom" }],
    ["número", 12345],
    ["booleano", true],
    ["array", ["tok"]],
    ["string vazia", ""],
    ["ausente", undefined],
  ])("payload com access_token %s NÃO vira sessão", async (_rotulo, valor) => {
    postMock.mockResolvedValue({ data: { access_token: valor } });
    await expect(refreshSession()).resolves.toBeNull();
  });

  it("payload inteiro fora de formato não vira sessão nem estoura", async () => {
    postMock.mockResolvedValue({ data: "não é json" });
    await expect(refreshSession()).resolves.toBeNull();
  });

  it("falha de rede continua sendo `null`, nunca exceção", async () => {
    postMock.mockRejectedValue(new Error("offline"));
    await expect(refreshSession()).resolves.toBeNull();
  });
});
