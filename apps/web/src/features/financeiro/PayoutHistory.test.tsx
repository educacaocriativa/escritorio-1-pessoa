import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PayoutHistory } from "./PayoutHistory";

const SAQUES = [
  {
    id: "p1",
    amount_cents: 300_000,
    paid_on: "2026-08-09",
    bank_account_id: "a1",
    bank_transaction_id: "b1",
  },
];
const CONTAS = { a1: "Itaú PJ" };

describe("PayoutHistory", () => {
  it("mostra valor, data e conta de destino", () => {
    render(<PayoutHistory payouts={SAQUES} accountNames={CONTAS} />);
    expect(screen.getByText("R$ 3.000,00")).toBeInTheDocument();
    expect(screen.getByText(/Itaú PJ/)).toBeInTheDocument();
    expect(screen.getByText("09/08/2026")).toBeInTheDocument();
  });

  it("NÃO usa <table> — a lição de 360px da Onda 2b-ii", () => {
    // Em 360px uma tabela de 3 colunas não cabe, e a saída não é rolar melhor: é não precisar.
    // O extrato da 2b-ii mostrava "R$ 3." no lugar de "R$ 3.000,00" com o `overflow-x` CORRETO —
    // nenhuma asserção de classe CSS pegaria aquilo, e por isso a forma é que vira contrato.
    const { container } = render(<PayoutHistory payouts={SAQUES} accountNames={CONTAS} />);
    expect(container.querySelector("table")).toBeNull();
    expect(container.querySelector("ul")).not.toBeNull();
  });

  it("o valor nunca quebra em duas linhas (whitespace-nowrap)", () => {
    // O valor É a informação num histórico de saques. Se ele quebrar ou for cortado, a linha
    // deixa de responder a única pergunta que a traz aqui.
    const { container } = render(<PayoutHistory payouts={SAQUES} accountNames={CONTAS} />);
    const valor = screen.getByText("R$ 3.000,00");
    expect(valor.className).toContain("whitespace-nowrap");
    // E o bloco da esquerda encolhe (min-w-0), senão ele empurraria o valor para fora da vista.
    expect(container.querySelector(".min-w-0")).not.toBeNull();
  });

  it("conta sem nome resolvido não vira 'undefined' na tela", () => {
    render(<PayoutHistory payouts={SAQUES} accountNames={{}} />);
    expect(screen.queryByText(/undefined/)).toBeNull();
  });

  it("sem saques, explica onde o saque aparece em vez de mostrar lista vazia", () => {
    render(<PayoutHistory payouts={[]} accountNames={{}} />);
    expect(screen.getByText(/Nenhum saque ainda/)).toBeInTheDocument();
  });
});
