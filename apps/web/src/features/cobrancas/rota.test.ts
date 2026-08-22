import type { Charge } from "@e1p/shared-types";
import { describe, expect, it } from "vitest";
import { diaDoCredito, rotaDaCobranca, rotuloDaRota } from "./rota";

/**
 * **A rota é DERIVADA dos dois ponteiros** (Story 8.15, AC4) — e é aqui que a derivação mora, em
 * vez de numa coluna `payment_route`. Um rótulo persistido pode divergir do fato; esta função não
 * pode, porque não guarda nada.
 */

const BASE = {
  id: "c-1",
  transaction_id: null as string | null,
  bank_account_id: null as string | null,
  paid_at: null as string | null,
} as unknown as Charge;

describe("rotaDaCobranca — a derivação", () => {
  it("transaction_id preenchido ⇒ trilho", () => {
    expect(rotaDaCobranca({ transaction_id: "tx-1", bank_account_id: null })).toBe("trilho");
  });

  it("bank_account_id preenchido ⇒ banco", () => {
    expect(rotaDaCobranca({ transaction_id: null, bank_account_id: "acc-1" })).toBe("banco");
  });

  it("nenhum dos dois ⇒ null: cobrança em aberto não tem rota, e inventar uma seria afirmar que houve dinheiro", () => {
    expect(rotaDaCobranca({ transaction_id: null, bank_account_id: null })).toBeNull();
  });

  it("os dois preenchidos ⇒ trilho tem precedência — mas esse estado é PROIBIDO pela invariante", () => {
    // A Invariante do Trilho (varrida no backend por `test_invariante_do_trilho.py`) torna este
    // caso inalcançável. A precedência existe para que a UI degrade de forma determinística se um
    // dado corrompido chegar, nunca para legitimá-lo.
    expect(rotaDaCobranca({ transaction_id: "tx-1", bank_account_id: "acc-1" })).toBe("trilho");
  });
});

describe("rotuloDaRota — o que a linha da lista diz", () => {
  const nome = (id: string) => (id === "acc-1" ? "Itaú PJ" : "");

  it("fora do trilho: diz QUAL conta recebeu e QUANDO", () => {
    const c = { ...BASE, bank_account_id: "acc-1", paid_at: "2026-08-04T00:00:00Z" } as Charge;
    expect(rotuloDaRota(c, nome)).toBe("caiu no Itaú PJ em 04/08");
  });

  it("pelo trilho: NENHUM rótulo — 'Recebido' já é a leitura certa e 'trilho' é vocabulário interno", () => {
    const c = { ...BASE, transaction_id: "tx-1" } as Charge;
    expect(rotuloDaRota(c, nome)).toBeNull();
  });

  it("em aberto: nenhum rótulo", () => {
    expect(rotuloDaRota(BASE, nome)).toBeNull();
  });

  it("conta desconhecida (lista ainda não carregou) degrada sem mentir", () => {
    const c = { ...BASE, bank_account_id: "acc-sumida", paid_at: null } as Charge;
    expect(rotuloDaRota(c, nome)).toBe("recebido direto na conta");
  });

  it("conta desconhecida MAS com data: nada de 'caiu no  em 04/08' com o buraco no meio", () => {
    // Provado por mutação (issue #191). O caso acima tinha `paid_at: null`, então conta E dia eram
    // vazios juntos e o `&&` da linha 53 nunca era exercido de verdade — trocá-lo por `||`
    // sobrevivia à suíte. Este é o caso que separa os dois: a lista de contas ainda não chegou
    // (nome vazio) mas o crédito tem data. Com o `||`, o dono leria "caiu no  em 04/08", uma frase
    // com um buraco onde deveria estar o nome do banco.
    const c = { ...BASE, bank_account_id: "acc-sumida", paid_at: "2026-08-04T00:00:00Z" } as Charge;
    expect(rotuloDaRota(c, nome)).toBe("recebido direto na conta");
  });

  it("conta conhecida SEM data: diz o banco e cala sobre o dia, em vez de calar sobre os dois", () => {
    // Provado por mutação (issue #191): o ramo `if (conta) return \`caiu no ${conta}\`` era o único
    // dos três sem caso próprio — apagá-lo passava verde. É o estado real de uma baixa manual sem
    // `paid_at`: o e1p sabe ONDE o dinheiro caiu e não sabe QUANDO. Degradar para "recebido direto
    // na conta" jogaria fora a metade que ele sabe.
    const c = { ...BASE, bank_account_id: "acc-1", paid_at: null } as Charge;
    expect(rotuloDaRota(c, nome)).toBe("caiu no Itaú PJ");
  });
});

describe("diaDoCredito — data de CALENDÁRIO, nunca horário local", () => {
  it("meia-noite UTC não vira o dia anterior (o bug de fuso do CLAUDE.md §6.0)", () => {
    // Em UTC-3, `new Date("2026-08-04T00:00:00Z").toLocaleDateString("pt-BR")` daria 03/08 — o dono
    // veria o Pix caindo um dia antes do que ele informou, em toda a Ficha 360° e na lista.
    expect(diaDoCredito("2026-08-04T00:00:00Z")).toBe("04/08");
    expect(diaDoCredito("2026-01-01T00:00:00Z")).toBe("01/01");
  });

  it("sem data, string vazia (nada a dizer)", () => {
    expect(diaDoCredito(null)).toBe("");
  });

  it("data TRUNCADA não vira 'undefined/08' na tela", () => {
    // Provado por mutação (issue #191): o `dia && mes ?` da linha 40 podia virar `true` ou `dia ||
    // mes` sem quebrar teste, porque todo caso testado era um ISO completo ou `null` — os dois
    // extremos, nenhum meio-termo. `"2026-08"` é o meio-termo: `split("-")` devolve duas partes, o
    // dia sai `undefined` e o template interpolaria a palavra "undefined" direto na linha da lista.
    expect(diaDoCredito("2026-08")).toBe("");
    expect(diaDoCredito("2026")).toBe("");
  });
});
