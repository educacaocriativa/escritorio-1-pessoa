import { describe, expect, it } from "vitest";

import {
  FUSO_PADRAO,
  formatDate,
  formatDateShort,
  formatDateTime,
  formatDay,
  formatTime,
  fusoValido,
  today,
} from "./datetime";

// 2026-08-06T01:30Z é 2026-08-05 22:30 em São Paulo. Todo teste de fuso que importa mora nesta
// janela: em UTC já virou o dia, para o dono ainda é a noite do dia anterior.
const NOITE_DO_DIA_5 = "2026-08-06T01:30:00+00:00";

describe("formatação de instante", () => {
  it("converte para o fuso do tenant, não para o do navegador", () => {
    expect(formatDateTime(NOITE_DO_DIA_5, "America/Sao_Paulo")).toBe("05/08/2026 22:30");
  });

  it("o fuso é parâmetro de verdade — outro fuso, outro resultado", () => {
    expect(formatDateTime(NOITE_DO_DIA_5, "UTC")).toBe("06/08/2026 01:30");
    expect(formatDateTime(NOITE_DO_DIA_5, "America/Manaus")).toBe("05/08/2026 21:30");
  });

  it("formata só a data e só a hora", () => {
    expect(formatDate(NOITE_DO_DIA_5, "America/Sao_Paulo")).toBe("05/08/2026");
    expect(formatTime(NOITE_DO_DIA_5, "America/Sao_Paulo")).toBe("22:30");
  });

  it("devolve string vazia para nulo/indefinido/inválido em vez de 'Invalid Date'", () => {
    expect(formatDateTime(null, FUSO_PADRAO)).toBe("");
    expect(formatDateTime(undefined, FUSO_PADRAO)).toBe("");
    expect(formatDateTime("nem data é", FUSO_PADRAO)).toBe("");
  });

  it("formata dia/mês sem o ano, para caber no card do Kanban", () => {
    expect(formatDateShort(NOITE_DO_DIA_5, "America/Sao_Paulo")).toBe("05/08");
    // O fuso continua sendo parâmetro de verdade nesta variante também.
    expect(formatDateShort(NOITE_DO_DIA_5, "UTC")).toBe("06/08");
    expect(formatDateShort(null, FUSO_PADRAO)).toBe("");
  });
});

describe("formatação de data de calendário", () => {
  it("NÃO desloca um dia — o off-by-one que `new Date('2026-08-05')` produz em UTC−3", () => {
    expect(formatDay("2026-08-05")).toBe("05/08/2026");
    // A prova de que o cuidado é necessário: o caminho ingênuo erra.
    expect(new Date("2026-08-05").toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" }))
      .toBe("04/08/2026");
  });

  it("aceita o prefixo de um ISO completo", () => {
    expect(formatDay("2026-08-05T00:00:00+00:00")).toBe("05/08/2026");
  });

  it("tolera vazio", () => {
    expect(formatDay(null)).toBe("");
    expect(formatDay("")).toBe("");
  });
});

describe("hoje", () => {
  it("é o dia do TENANT, não o dia UTC", () => {
    const instante = new Date(NOITE_DO_DIA_5);
    expect(today("America/Sao_Paulo", instante)).toBe("2026-08-05");
    // O que o código antigo (`toISOString().slice(0, 10)`) devolvia:
    expect(instante.toISOString().slice(0, 10)).toBe("2026-08-06");
  });
});

describe("fuso inválido", () => {
  it("cai no padrão em vez de derrubar a tela", () => {
    expect(fusoValido("Marte/Olympus")).toBe(FUSO_PADRAO);
    expect(fusoValido(null)).toBe(FUSO_PADRAO);
    expect(fusoValido(undefined)).toBe(FUSO_PADRAO);
    expect(fusoValido("America/Manaus")).toBe("America/Manaus");
  });

  it("formatar com fuso corrompido não lança", () => {
    expect(formatDateTime(NOITE_DO_DIA_5, "Marte/Olympus")).toBe("05/08/2026 22:30");
  });
});
