import { describe, expect, it } from "vitest";

import {
  FUSO_PADRAO,
  formatDate,
  formatDateShort,
  formatDateTime,
  formatDay,
  formatTime,
  formatWeekday,
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

  it("data INCOMPLETA devolve vazio em vez de interpolar 'undefined'", () => {
    // Provado por mutação (issue #191). O guarda `y && m && d ?` tinha QUATRO mutantes vivos: os
    // testes só usavam ISO completo, `null` e `""` — nunca uma string com algumas partes. As duas
    // linhas abaixo são as duas metades do `&&` encadeado:
    //   • `"2026-08"` (falta o dia) mata `true` e `y && m || d`;
    //   • `"-08-05"` (falta o ano) mata `y && m → true` e `y && m → y || m`.
    // Sem elas, uma `due_date` truncada pela API sairia como "undefined/08/2026" na tela — pior que
    // um campo vazio, porque parece um dado.
    expect(formatDay("2026-08")).toBe("");
    expect(formatDay("-08-05")).toBe("");
  });
});

describe("os vazios de cada formatador (nenhum devolve 'Invalid Date')", () => {
  // Provado por mutação (issue #191): só `formatDateTime` e `formatDateShort` tinham o caso nulo
  // preso. Os ramos `: ""` de `formatDate` e `formatTime` estavam sem asserção, e o contrato do
  // módulo — "devolve string vazia em vez de 'Invalid Date'" — vale para todos eles igualmente.
  it("nulo e indefinido saem vazios em todas as variantes", () => {
    expect(formatDate(null, FUSO_PADRAO)).toBe("");
    expect(formatDate(undefined, FUSO_PADRAO)).toBe("");
    expect(formatTime(null, FUSO_PADRAO)).toBe("");
    expect(formatTime(undefined, FUSO_PADRAO)).toBe("");
    expect(formatWeekday(null, FUSO_PADRAO)).toBe("");
  });
});

describe("formatWeekday", () => {
  // Provado por mutação (issue #191): a função inteira estava SEM COBERTURA — 5 mutantes
  // `NoCoverage`, incluindo esvaziar o corpo (`{}`) e apagar o objeto de opções. Não é dívida de
  // mutação e sim de cobertura: `formatWeekday` é a única porta do módulo que ninguém chamava num
  // teste, e ela é a que a Agenda usa no cabeçalho do dia.
  it("dia da semana por extenso, no fuso do TENANT", () => {
    expect(formatWeekday(NOITE_DO_DIA_5, "America/Sao_Paulo")).toBe("quarta-feira, 05 de agosto");
  });

  it("o fuso é parâmetro de verdade — em UTC já é outro dia, e outro dia da semana", () => {
    // 2026-08-06T01:30Z: para o dono ainda é quarta 05; em UTC já é quinta 06. Se as opções
    // (`weekday`/`day`/`month`) ou o fuso se perdessem, esta linha e a de cima colapsariam na mesma.
    expect(formatWeekday(NOITE_DO_DIA_5, "UTC")).toBe("quinta-feira, 06 de agosto");
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
