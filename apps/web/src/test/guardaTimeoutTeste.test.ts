import { describe, expect, it } from "vitest";
import type { File } from "vitest";
import {
  achatarTestes,
  encontrarTestesLentos,
  GuardaTimeoutTeste,
  LIMIAR_FRACAO_PADRAO,
  montarAviso,
} from "./guardaTimeoutTeste";

// Testa a LÓGICA PURA do guarda com números controlados — sem esperar tempo real nenhum. Mesmo
// padrão de `scripts/guarda-timeouts-mutacao.mjs`: a fixture é dado, não uma corrida de verdade.
// A prova de que o AVISO REALMENTE aparece numa corrida real (não só a matemática) foi feita à
// parte, rodando `npx vitest run <arquivo-lento> --testTimeout=<N baixo>` e conferindo o stderr —
// ver relatório da issue #231. Um teste PERMANENTEMENTE lento na suíte reintroduziria o próprio
// problema que a #231 resolve.

/** Monta uma File→Suite→Test mínima o bastante para `achatarTestes` andar. */
function arquivoComTeste(nome: string, tituloTeste: string, duracaoMs: number | undefined): File {
  const file = {
    type: "file" as const,
    id: "f1",
    name: nome,
    mode: "run" as const,
    meta: {},
    filepath: nome,
    projectName: undefined,
    tasks: [] as unknown[],
  } as unknown as File;
  const teste = {
    type: "test" as const,
    id: "f1_0",
    name: tituloTeste,
    mode: "run" as const,
    meta: {},
    file,
    result: duracaoMs === undefined ? undefined : { state: "pass" as const, duration: duracaoMs },
  };
  (file as unknown as { tasks: unknown[] }).tasks = [teste];
  return file;
}

describe("achatarTestes", () => {
  it("achata File > Test e mantém arquivo/título/duração", () => {
    const file = arquivoComTeste("a.test.ts", "faz algo", 1234);
    expect(achatarTestes([file])).toEqual([{ arquivo: "a.test.ts", titulo: "faz algo", duracaoMs: 1234 }]);
  });

  it("ignora testes sem duração (skip/todo/não rodou)", () => {
    const file = arquivoComTeste("a.test.ts", "pulado", undefined);
    expect(achatarTestes([file])).toEqual([]);
  });

  it("junta o nome da suite ao título (describe > it)", () => {
    const file = {
      type: "file" as const,
      id: "f1",
      name: "b.test.ts",
      mode: "run" as const,
      meta: {},
      filepath: "b.test.ts",
      projectName: undefined,
      tasks: [] as unknown[],
    } as unknown as File;
    const suite = {
      type: "suite" as const,
      id: "f1_0",
      name: "grupo",
      mode: "run" as const,
      meta: {},
      file,
      tasks: [] as unknown[],
    };
    const teste = {
      type: "test" as const,
      id: "f1_0_0",
      name: "caso",
      mode: "run" as const,
      meta: {},
      file,
      result: { state: "pass" as const, duration: 500 },
    };
    suite.tasks = [teste];
    (file as unknown as { tasks: unknown[] }).tasks = [suite];

    expect(achatarTestes([file])).toEqual([{ arquivo: "b.test.ts", titulo: "grupo > caso", duracaoMs: 500 }]);
  });
});

describe("encontrarTestesLentos", () => {
  const testes = [
    { arquivo: "x.test.ts", titulo: "rápido", duracaoMs: 100 },
    { arquivo: "x.test.ts", titulo: "na borda", duracaoMs: 7500 }, // exatamente 50% de 15000
    { arquivo: "x.test.ts", titulo: "lento", duracaoMs: 8474 }, // medido de verdade, issue #231
  ];

  it("usa o limiar padrão de 50% quando não especificado", () => {
    expect(LIMIAR_FRACAO_PADRAO).toBe(0.5);
    const lentos = encontrarTestesLentos(testes, 15000);
    expect(lentos.map((l) => l.titulo)).toEqual(["lento", "na borda"]);
  });

  it("empate exato no limiar CONTA como lento (>=, não >)", () => {
    const lentos = encontrarTestesLentos([{ arquivo: "x", titulo: "exato", duracaoMs: 5000 }], 10000, 0.5);
    expect(lentos).toHaveLength(1);
  });

  it("ordena do mais lento para o mais rápido", () => {
    const lentos = encontrarTestesLentos(testes, 15000);
    expect(lentos[0].titulo).toBe("lento");
    expect(lentos[0].fracao).toBeCloseTo(8474 / 15000);
  });

  it("testTimeout inválido (0, negativo, Infinity, NaN) devolve lista vazia, não divide por zero", () => {
    expect(encontrarTestesLentos(testes, 0)).toEqual([]);
    expect(encontrarTestesLentos(testes, -1)).toEqual([]);
    expect(encontrarTestesLentos(testes, Number.POSITIVE_INFINITY)).toEqual([]);
    expect(encontrarTestesLentos(testes, Number.NaN)).toEqual([]);
  });

  it("nenhum teste cruza o limiar → lista vazia", () => {
    expect(encontrarTestesLentos([{ arquivo: "x", titulo: "ok", duracaoMs: 10 }], 15000)).toEqual([]);
  });
});

describe("montarAviso", () => {
  it("cita título, arquivo, ms e percentual do testTimeout", () => {
    const msg = montarAviso(
      { arquivo: "src/features/admin/PlatformUsers.test.tsx", titulo: "caminho feliz", duracaoMs: 8474, fracao: 8474 / 15000 },
      15000,
    );
    expect(msg).toContain("PlatformUsers.test.tsx");
    expect(msg).toContain("caminho feliz");
    expect(msg).toContain("8474ms");
    expect(msg).toContain("56%"); // 8474/15000 arredondado
    expect(msg).toContain("15000ms");
  });
});

describe("GuardaTimeoutTeste (reporter)", () => {
  it("onFinished avisa (console.warn) quando um teste cruza o limiar, e cita o teste certo", () => {
    const avisos: unknown[] = [];
    const originalWarn = console.warn;
    console.warn = (...args: unknown[]) => avisos.push(args.join(" "));
    try {
      const guarda = new GuardaTimeoutTeste();
      guarda.onInit({ config: { testTimeout: 1000 } });
      const file = arquivoComTeste("lento.test.ts", "demora de propósito", 600); // 60% de 1000ms
      guarda.onFinished([file]);
    } finally {
      console.warn = originalWarn;
    }
    expect(avisos).toHaveLength(1);
    expect(String(avisos[0])).toContain("lento.test.ts");
    expect(String(avisos[0])).toContain("demora de propósito");
    expect(String(avisos[0])).toContain("60%");
  });

  it("onFinished NÃO avisa quando nenhum teste cruza o limiar", () => {
    const avisos: unknown[] = [];
    const originalWarn = console.warn;
    console.warn = (...args: unknown[]) => avisos.push(args.join(" "));
    try {
      const guarda = new GuardaTimeoutTeste();
      guarda.onInit({ config: { testTimeout: 15000 } });
      const file = arquivoComTeste("rapido.test.ts", "instantâneo", 50);
      guarda.onFinished([file]);
    } finally {
      console.warn = originalWarn;
    }
    expect(avisos).toHaveLength(0);
  });

  it("não seta process.exitCode — isto é aviso, não gate (ver cabeçalho do arquivo-fonte)", () => {
    const exitCodeAntes = process.exitCode;
    const guarda = new GuardaTimeoutTeste();
    guarda.onInit({ config: { testTimeout: 100 } });
    const originalWarn = console.warn;
    console.warn = () => {};
    try {
      guarda.onFinished([arquivoComTeste("x.test.ts", "y", 99999)]); // MUITO acima do timeout
    } finally {
      console.warn = originalWarn;
    }
    expect(process.exitCode).toBe(exitCodeAntes);
  });
});
