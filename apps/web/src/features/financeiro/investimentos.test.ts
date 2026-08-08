import { describe, expect, it } from "vitest";
import type { BankAccount } from "./contas";
import {
  contasDeAplicacao,
  formatPct,
  type InvestmentAccount,
  rotuloDoVinculo,
} from "./investimentos";

/**
 * Smoke test do helper de formatação de rentabilidade (Story 5.6). O projeto não tem infra de teste
 * de componente React — os testes de front são de lógica pura (ver planoContas.test.ts / dre).
 */
describe("formatPct (rentabilidade — Story 5.6)", () => {
  it("formata a fração como percentual pt-BR com 2 casas", () => {
    expect(formatPct(0.055)).toBe("5,50%");
    expect(formatPct(0.05)).toBe("5,00%");
    expect(formatPct(0)).toBe("0,00%");
  });

  it("mostra '—' quando a rentabilidade é null (principal 0 — divisão evitada)", () => {
    expect(formatPct(null)).toBe("—");
    expect(formatPct(Number.NaN)).toBe("—");
  });
});

describe("contasDeAplicacao / rotuloDoVinculo (Onda 2b-i)", () => {
  const aplicacao = { id: "c1", name: "CDB Itaú", kind: "investment", archived_at: null };
  const corrente = { id: "c2", name: "Itaú PJ", kind: "checking", archived_at: null };
  const arquivada = { id: "c3", name: "CDB velho", kind: "investment", archived_at: "2026-01-01" };
  const contas = [aplicacao, corrente, arquivada] as unknown as BankAccount[];

  it("só oferece conta de APLICAÇÃO e não arquivada", () => {
    // Oferecer a corrente levaria o dono a creditar o rendimento onde o dinheiro não está — e o
    // backend recusaria com 422 depois de ele já ter escolhido.
    expect(contasDeAplicacao(contas).map((c) => c.id)).toEqual(["c1"]);
  });

  it("nomeia a conta quando a aplicação está vinculada", () => {
    const app = { id: "a1", bank_account_id: "c1" } as InvestmentAccount;
    expect(rotuloDoVinculo(app, contas)).toBe("CDB Itaú");
  });

  it("diz o que FAZER quando não está vinculada — nunca só 'sem conta'", () => {
    // É este vínculo que o 409 de `register_yield` pede. Um rótulo que só descreve o estado
    // deixaria o dono sabendo do problema e não do caminho.
    const app = { id: "a1", bank_account_id: null } as InvestmentAccount;
    expect(rotuloDoVinculo(app, contas)).toBe("Vincular a uma conta");
  });

  it("não inventa nome quando o vínculo aponta para conta fora da lista", () => {
    const app = { id: "a1", bank_account_id: "sumida" } as InvestmentAccount;
    expect(rotuloDoVinculo(app, contas)).toBe("Vincular a uma conta");
  });
});
