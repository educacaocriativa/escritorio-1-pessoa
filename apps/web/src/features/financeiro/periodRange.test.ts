import { describe, expect, it } from "vitest";
import {
  monthKeyToRange,
  PERIOD_SHORTCUT_LABEL,
  type PeriodShortcut,
  resolvePeriod,
} from "./periodRange";

const TODAY = new Date(Date.UTC(2026, 6, 21)); // 21/07/2026 (mês = 6 = julho, 0-indexed)

describe("resolvePeriod", () => {
  it("this_month", () => {
    expect(resolvePeriod("this_month", TODAY)).toEqual({ start: "2026-07-01", end: "2026-07-31" });
  });

  it("last_month cruzando ano (janeiro -> dezembro do ano anterior)", () => {
    const jan = new Date(Date.UTC(2026, 0, 15));
    expect(resolvePeriod("last_month", jan)).toEqual({ start: "2025-12-01", end: "2025-12-31" });
  });

  it("last_month dentro do mesmo ano (julho -> junho)", () => {
    // Achado por mutação (#121): o único teste de `last_month` era o de janeiro, que cai no ramo
    // `m === 1 ? 12`. O `m - 1` do outro ramo NUNCA era executado — trocar por `m + 1` sobrevivia.
    expect(resolvePeriod("last_month", TODAY)).toEqual({ start: "2026-06-01", end: "2026-06-30" });
  });

  it("this_quarter (julho cai no 3º trimestre: jul-set)", () => {
    expect(resolvePeriod("this_quarter", TODAY)).toEqual({ start: "2026-07-01", end: "2026-09-30" });
  });

  it("this_quarter nos outros três trimestres", () => {
    // ⚠️ Julho sozinho é um mês CEGO para este cálculo, e a mutação (#121) mostrou: trocar
    // `Math.floor((m - 1) / 3)` por `Math.floor((m + 1) / 3)` dá o MESMO 3º trimestre em julho
    // (`floor(6/3) = floor(8/3) = 2`) e sobrevivia à suíte. Em março os dois discordam: o certo
    // é jan-mar, o mutante diz abr-jun — um trimestre inteiro no futuro.
    const marco = new Date(Date.UTC(2026, 2, 31));
    expect(resolvePeriod("this_quarter", marco)).toEqual({ start: "2026-01-01", end: "2026-03-31" });

    const maio = new Date(Date.UTC(2026, 4, 9));
    expect(resolvePeriod("this_quarter", maio)).toEqual({ start: "2026-04-01", end: "2026-06-30" });

    const dezembro = new Date(Date.UTC(2026, 11, 1));
    expect(resolvePeriod("this_quarter", dezembro)).toEqual({ start: "2026-10-01", end: "2026-12-31" });
  });

  it("this_year", () => {
    expect(resolvePeriod("this_year", TODAY)).toEqual({ start: "2026-01-01", end: "2026-12-31" });
  });

  it("last_12_months (janela rolante terminando no mês atual)", () => {
    expect(resolvePeriod("last_12_months", TODAY)).toEqual({ start: "2025-08-01", end: "2026-07-31" });
  });

  it("all (início fixo, fim no mês atual)", () => {
    expect(resolvePeriod("all", TODAY)).toEqual({ start: "2000-01-01", end: "2026-07-31" });
  });

  it("custom repassa o range informado", () => {
    const custom = { start: "2026-02-01", end: "2026-02-10" };
    expect(resolvePeriod("custom", TODAY, custom)).toEqual(custom);
  });

  it("custom sem range lança erro", () => {
    expect(() => resolvePeriod("custom", TODAY)).toThrow();
  });
});

describe("monthKeyToRange", () => {
  it("converte uma chave 'YYYY-MM' no intervalo do mês inteiro", () => {
    expect(monthKeyToRange("2026-02")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
  });

  it("respeita ano bissexto (fevereiro com 29 dias)", () => {
    expect(monthKeyToRange("2028-02")).toEqual({ start: "2028-02-01", end: "2028-02-29" });
  });
});

describe("PERIOD_SHORTCUT_LABEL", () => {
  it("tem entrada para TODO atalho do seletor", () => {
    // Achado por mutação (#214): trocar o objeto inteiro por `{}` sobrevivia. Este mapa é lido
    // direto no `<option>` do `PeriodPicker`; sem entrada, o seletor de período de TODA a área
    // financeira (DRE, Lucratividade, Conferência, Contas) vira sete linhas em branco. O
    // `PeriodPicker.test.tsx` não pega — ele dirige o `<select>` por `value`, nunca pelo texto —
    // e a corrida de mutação exclui `.test.tsx` de propósito, então não havia rede nenhuma.
    //
    // A asserção é sobre a ESTRUTURA (existe rótulo para cada atalho), não sobre a redação: o
    // texto de cada rótulo é escolha de produto e continua livre para mudar.
    const atalhos: PeriodShortcut[] = [
      "this_month",
      "last_month",
      "this_quarter",
      "this_year",
      "last_12_months",
      "all",
      "custom",
    ];

    expect(Object.keys(PERIOD_SHORTCUT_LABEL).sort()).toEqual([...atalhos].sort());
  });
});
