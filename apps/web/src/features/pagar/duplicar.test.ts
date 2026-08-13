import type { Payable } from "@e1p/shared-types";
import { describe, expect, it } from "vitest";
import { camposDaCopia, proximoVencimento } from "./duplicar";

/** Conta de origem rica: todos os campos que a cópia decide levar ou deixar. */
const ORIGEM = {
  id: "b-9",
  tenant_id: "t-1",
  description: "Aluguel Sala gravacao",
  category: "Mkt",
  supplier: "WorkPlace Palhano",
  amount_cents: 20000,
  due_date: "2026-07-31",
  chart_account_id: "ca-1",
  contract_id: "ct-1",
  cost_center_id: "cc-1",
  status: "paid",
  is_overdue: false,
  paid_at: "2026-07-31T00:00:00Z",
  recurrence: "monthly",
  recurrence_count: 12,
  recurrence_group: "grp-1",
  payment_code: "00020126580014BR.GOV.BCB.PIX",
  attachment_url: "",
  created_at: "2026-01-01T00:00:00Z",
} as unknown as Payable;

describe("proximoVencimento — a data avança um mês, com trava de fim de mês", () => {
  it("dia que existe no mês destino é preservado", () => {
    expect(proximoVencimento("2026-07-31")).toBe("2026-08-31");
    expect(proximoVencimento("2026-08-15")).toBe("2026-09-15");
  });

  it("dia que não existe no mês destino cai no último dia", () => {
    expect(proximoVencimento("2026-01-31")).toBe("2026-02-28");
    expect(proximoVencimento("2026-01-30")).toBe("2026-02-28");
    expect(proximoVencimento("2026-03-31")).toBe("2026-04-30");
  });

  it("ano bissexto dá 29 dias a fevereiro", () => {
    expect(proximoVencimento("2028-01-31")).toBe("2028-02-29");
    // 2100 não é bissexto (divisível por 100 e não por 400) — a regra completa, não só `% 4`.
    expect(proximoVencimento("2100-01-31")).toBe("2100-02-28");
    expect(proximoVencimento("2000-01-31")).toBe("2000-02-29");
  });

  it("não estica o dia só porque o mês destino é mais longo", () => {
    expect(proximoVencimento("2026-11-30")).toBe("2026-12-30");
  });

  it("dezembro vira janeiro do ano seguinte", () => {
    expect(proximoVencimento("2026-12-15")).toBe("2027-01-15");
    expect(proximoVencimento("2026-12-31")).toBe("2027-01-31");
  });

  it("aceita um instante ISO completo, usando só a parte da data", () => {
    expect(proximoVencimento("2026-07-31T00:00:00Z")).toBe("2026-08-31");
  });

  it("entrada inválida devolve string vazia, nunca 'NaN-NaN-NaN'", () => {
    // O campo nasce vazio e o botão "Adicionar conta" fica desabilitado — o dono escolhe a data.
    expect(proximoVencimento("")).toBe("");
    expect(proximoVencimento("qualquer coisa")).toBe("");
  });
});

describe("camposDaCopia — o que a cópia leva e o que ela deixa", () => {
  it("leva descrição, fornecedor, categoria, centro de custo e contrato", () => {
    const c = camposDaCopia(ORIGEM);
    expect(c.description).toBe("Aluguel Sala gravacao");
    expect(c.supplier).toBe("WorkPlace Palhano");
    expect(c.chartAccountId).toBe("ca-1");
    expect(c.costCenterId).toBe("cc-1");
    expect(c.contractId).toBe("ct-1");
  });

  it("leva o valor como texto com vírgula, no formato que o formulário consome", () => {
    expect(camposDaCopia(ORIGEM).value).toBe("200,00");
    expect(camposDaCopia({ ...ORIGEM, amount_cents: 1165 } as Payable).value).toBe("11,65");
  });

  it("leva o vencimento já avançado um mês", () => {
    expect(camposDaCopia(ORIGEM).dueDate).toBe("2026-08-31");
  });

  // Decisão do fundador, registrada na §4.2 da spec: a recomendação era NÃO copiar (código de
  // agosto não paga setembro). Ele optou por copiar, porque os fornecedores dele usam chave Pix
  // fixa. O teste existe para ninguém "corrigir" isso de volta lendo só a recomendação.
  it("leva o código Pix/boleto — decisão consciente, não descuido", () => {
    expect(camposDaCopia(ORIGEM).paymentCode).toBe("00020126580014BR.GOV.BCB.PIX");
  });

  // Duplicar É a alternativa manual à recorrência. Copiar "Mensal × 12" faria um gesto de
  // "repetir uma vez" gerar doze contas e doze eventos na Agenda, sem o dono pedir.
  it("NÃO leva a recorrência: nasce sempre em 'Não repete'", () => {
    const c = camposDaCopia(ORIGEM);
    expect(c.recurrence).toBe("none");
    expect(c.recurrenceCount).toBe("12"); // o default do formulário, inerte enquanto recurrence="none"
  });

  it("campos nulos na origem viram string vazia, nunca 'null' na tela", () => {
    const c = camposDaCopia({
      ...ORIGEM,
      chart_account_id: null,
      cost_center_id: null,
      contract_id: null,
    } as Payable);
    expect(c.chartAccountId).toBe("");
    expect(c.costCenterId).toBe("");
    expect(c.contractId).toBe("");
  });
});
