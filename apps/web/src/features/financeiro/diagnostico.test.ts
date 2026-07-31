import { describe, expect, it } from "vitest";
import {
  completudeCaveat,
  completudeLevel,
  countByLevel,
  monthRange,
  type Signal,
  signalVisual,
  sourceLabel,
} from "./diagnostico";

/**
 * Smoke test da lógica pura do diagnóstico financeiro (Story 5.8). O projeto não tem infra de teste
 * de componente React — os testes de front são de lógica pura (ver projecao.test.ts / dre.test.ts).
 * Cobre a config visual por nível, a contagem por nível e o range de mês.
 */
const sig = (level: Signal["level"], source = "projecao"): Signal => ({
  level,
  title: "t",
  explanation: "e",
  source,
});

describe("signalVisual", () => {
  it("mapeia cada nível para emoji e rótulo", () => {
    expect(signalVisual("vermelho").emoji).toBe("🔴");
    expect(signalVisual("amarelo").label).toBe("Atenção");
    expect(signalVisual("verde").emoji).toBe("🟢");
  });
});

describe("countByLevel", () => {
  it("conta sinais por nível", () => {
    const counts = countByLevel([sig("vermelho"), sig("vermelho"), sig("amarelo")]);
    expect(counts).toEqual({ vermelho: 2, amarelo: 1, verde: 0 });
  });

  it("retorna tudo zero para lista vazia", () => {
    expect(countByLevel([])).toEqual({ vermelho: 0, amarelo: 0, verde: 0 });
  });
});

describe("sourceLabel", () => {
  it("traduz as origens conhecidas e devolve o cru para desconhecidas", () => {
    expect(sourceLabel("lucratividade")).toBe("Lucratividade por contrato");
    expect(sourceLabel("investimento")).toBe("Investimentos");
    expect(sourceLabel("desconhecido")).toBe("desconhecido");
  });

  it("rotula a origem 'completude' (Story 8.6)", () => {
    expect(sourceLabel("completude")).toBe("Completude dos lançamentos");
  });
});

/**
 * Story 8.6 — a ressalva de precedência semântica. A regra que ela representa: se o sistema não
 * sabe se os lançamentos estão completos, qualquer afirmação sobre margem/runway/rentabilidade é
 * feita sobre base possivelmente furada, e o usuário precisa ler isso ANTES dos números.
 */
describe("completudeLevel", () => {
  it("devolve o pior nível entre os sinais de completude", () => {
    expect(
      completudeLevel([sig("amarelo", "completude"), sig("vermelho", "completude")]),
    ).toBe("vermelho");
    expect(completudeLevel([sig("verde", "completude"), sig("amarelo", "completude")])).toBe(
      "amarelo",
    );
    expect(completudeLevel([sig("verde", "completude")])).toBe("verde");
  });

  it("ignora sinais de outras origens", () => {
    expect(completudeLevel([sig("vermelho", "projecao"), sig("amarelo", "lucratividade")])).toBe(
      null,
    );
    expect(completudeLevel([])).toBe(null);
  });
});

describe("completudeCaveat", () => {
  it("avisa quando a completude está 🔴", () => {
    const texto = completudeCaveat([sig("vermelho", "completude"), sig("verde", "projecao")]);
    expect(texto).toContain("possivelmente incompletos");
    expect(texto).toContain("divergência acima da tolerância");
  });

  it("avisa quando a completude está 🟡", () => {
    const texto = completudeCaveat([sig("amarelo", "completude")]);
    expect(texto).toContain("possivelmente incompletos");
  });

  it("cala quando a completude está 🟢 ou ausente", () => {
    expect(completudeCaveat([sig("verde", "completude")])).toBe(null);
    // Um 🔴 de OUTRA origem não gera a ressalva: ela é sobre confiar nos dados, não sobre gravidade.
    expect(completudeCaveat([sig("vermelho", "projecao")])).toBe(null);
    expect(completudeCaveat([])).toBe(null);
  });
});

describe("monthRange", () => {
  it("calcula o primeiro e último dia do mês", () => {
    expect(monthRange("2026-02")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(monthRange("2026-07")).toEqual({ start: "2026-07-01", end: "2026-07-31" });
  });
});
