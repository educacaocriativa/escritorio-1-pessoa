import { cssVarName, generateScale, SHADE_KEYS } from "@e1p/design-tokens";
import { beforeEach, describe, expect, it } from "vitest";
import { applyBrandTheme } from "./theme";

describe("generateScale (design-tokens) — Story 5.11", () => {
  it("o tom 500 é a própria cor de entrada (verbatim, minúsculo)", () => {
    const scale = generateScale("#1A2B3C");
    expect(scale[500]).toBe("#1a2b3c");
  });

  it("é uma rampa monotônica: cada tom mais claro tem luminosidade >= ao anterior", () => {
    // Verificação indireta: dado o mesmo matiz, os hex mais "claros" (50) devem ter maior soma de
    // canais RGB que os mais "escuros" (900) — sem depender de reimplementar HSL no teste.
    const scale = generateScale("#5D44F8");
    const sum = (hex: string) =>
      parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16);
    const sums = SHADE_KEYS.map((s) => sum(scale[s]));
    for (let i = 1; i < sums.length; i++) {
      expect(sums[i]).toBeLessThanOrEqual(sums[i - 1]);
    }
  });

  it("cor base clara (perto do âncora de 50) não gera rampa invertida", () => {
    // Caso de borda: L já perto do teto (branco) — o "lado claro" quase não tem pra onde subir,
    // mas a rampa não pode quebrar (900 continua o mais escuro).
    const scale = generateScale("#F5F0FF"); // roxo bem claro
    const sum = (hex: string) =>
      parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16);
    expect(sum(scale[50])).toBeGreaterThanOrEqual(sum(scale[900]));
  });

  it("gera valores próximos da escala primary original a partir do mesmo hex base (#5D44F8)", () => {
    const scale = generateScale("#5d44f8");
    // Tolerância generosa (curva aproximada, não idêntica byte-a-byte) — só garante que o tom
    // "500" bate exato e os extremos ficam na mesma família de cor (não divergem pra outro matiz).
    expect(scale[500]).toBe("#5d44f8");
    expect(scale[50].toLowerCase()).toMatch(/^#f[0-9a-f]e/); // clarinho, tom de lilás
    expect(scale[900].toLowerCase()).toMatch(/^#1[0-9a-f]/); // bem escuro
  });
});

describe("applyBrandTheme — Story 5.11", () => {
  beforeEach(() => {
    for (const token of ["primary", "accent"] as const) {
      for (const shade of SHADE_KEYS) {
        document.documentElement.style.removeProperty(cssVarName(token, shade));
      }
    }
  });

  it("seta as 10 CSS vars de primary e accent a partir do Brand Kit", () => {
    applyBrandTheme({ primary_color: "#112233", accent_color: "#445566" });
    expect(document.documentElement.style.getPropertyValue(cssVarName("primary", 500)).trim()).toBe(
      "#112233",
    );
    expect(document.documentElement.style.getPropertyValue(cssVarName("accent", 500)).trim()).toBe(
      "#445566",
    );
    // todos os 10 tons de cada token foram setados, não só o 500
    for (const shade of SHADE_KEYS) {
      expect(document.documentElement.style.getPropertyValue(cssVarName("primary", shade))).not.toBe("");
      expect(document.documentElement.style.getPropertyValue(cssVarName("accent", shade))).not.toBe("");
    }
  });

  it("ignora hex inválido/vazio sem lançar (fail-safe — mantém o fallback estático do preset)", () => {
    expect(() => applyBrandTheme({ primary_color: "", accent_color: "não-é-hex" })).not.toThrow();
    expect(document.documentElement.style.getPropertyValue(cssVarName("primary", 500))).toBe("");
    expect(document.documentElement.style.getPropertyValue(cssVarName("accent", 500))).toBe("");
  });

  it("campos parciais só aplicam o que veio (primary sem accent, por exemplo)", () => {
    applyBrandTheme({ primary_color: "#0a0a0a" });
    expect(document.documentElement.style.getPropertyValue(cssVarName("primary", 500)).trim()).toBe(
      "#0a0a0a",
    );
    expect(document.documentElement.style.getPropertyValue(cssVarName("accent", 500))).toBe("");
  });
});
