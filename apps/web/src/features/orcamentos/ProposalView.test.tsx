import type { PublicProposal } from "@e1p/shared-types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ProposalView from "./ProposalView";

/**
 * Issue #209 — **a asserção que prende o acoplamento com `formatBRL`.**
 *
 * Antes desta issue, `brl` estava redefinido em 15 arquivos e importado em 0. Medido: quebrar
 * `formatBRL` (`dre.ts`) trocando `/ 100` por `/ 1` derrubava **21 testes em 10 arquivos, todos
 * dentro de `features/financeiro/`** — e **nenhuma** das 15 telas que tinham a cópia local. Cada
 * tela afirmava contra a própria cópia, então a divergência era invisível por construção.
 *
 * `ProposalView` é o pior caso dessa família: **5** call sites de dinheiro e **zero** testes. É
 * também o alvo mais barato de prender — componente puro, sem `api`, sem router, sem store.
 *
 * ⚠️ **Os literais aqui são fixos de propósito.** Comparar contra `formatBRL(x)` seria tautológico
 * (ele É a implementação sob teste — a mesma lição de `investimentos.test.ts:66`): a mutação
 * mudaria os dois lados e sobreviveria. Os cinco valores abaixo são distintos entre si e todos
 * passam do milhar, então três mutações independentes morrem aqui:
 *   · `/ 100` → `/ 1`            (centavos tratados como reais)
 *   · `"pt-BR"` → `"en-US"`      (vira "R$1,500.00": ponto e vírgula trocados)
 *   · `"BRL"` → `"USD"`          (vira "US$ 1.500,00")
 */

// `toLocaleString("pt-BR", { style: "currency" })` separa "R$" do número com um **NBSP** (U+00A0),
// não com espaço comum — medido: codepoint 160. Normalizar aqui mantém o fonte 100% ASCII neste
// ponto (a lição do PR #142: literal com NBSP colado é invisível na revisão).
const semNbsp = (s: string | null | undefined) => (s ?? "").replace(/\u00a0/g, " ");

/** `getByText` que compara o texto JÁ normalizado — casa "R$ x" sem NBSP invisível no fonte. */
function porTextoSemNbsp(esperado: string): HTMLElement {
  return screen.getByText((_conteudo, el) => semNbsp(el?.textContent) === esperado);
}

/** Cinco valores DISTINTOS, todos acima do milhar (o separador de milhar entra na asserção). */
const PROPOSTA: PublicProposal = {
  title: "Reforma do escritório",
  client_name: "Joana Ré",
  items: [
    { description: "Projeto executivo", subtitle: "", quantity: 3, unit_price_cents: 150_000 },
  ],
  subtotal_cents: 987_654,
  discount_cents: 12_345,
  total_cents: 1_234_567,
  payment_terms: "",
  show_gallery: false,
  gallery: [],
  show_schedule: false,
  schedule: [],
  show_contract: false,
  contract_text: "",
  logo_url: "",
  primary_color: "#123456",
  bg_color: "#ffffff",
  text_color: "#000000",
  accent_color: "#123456",
  status: "sent",
  valid_until: null,
};

describe("ProposalView — o dinheiro na tela vem de `formatBRL` (issue #209)", () => {
  it("formata os CINCO valores em R$ pt-BR a partir de centavos", () => {
    render(<ProposalView p={PROPOSTA} />);

    // unitário: 150.000 centavos = R$ 1.500,00 (`quantity > 1` faz a linha "3 × ..." aparecer)
    expect(porTextoSemNbsp("3 × R$ 1.500,00")).toBeTruthy();
    // total da linha: 3 × 150.000 = 450.000 centavos = R$ 4.500,00
    expect(porTextoSemNbsp("R$ 4.500,00")).toBeTruthy();
    // subtotal, desconto e total: props independentes, valores distintos entre si
    expect(porTextoSemNbsp("R$ 9.876,54")).toBeTruthy();
    expect(porTextoSemNbsp("- R$ 123,45")).toBeTruthy();
    expect(porTextoSemNbsp("R$ 12.345,67")).toBeTruthy();
  });

  it("não exibe o número cru de centavos em lugar nenhum", () => {
    const { container } = render(<ProposalView p={PROPOSTA} />);
    const texto = semNbsp(container.textContent);
    // A mutação `/ 100` → `/ 1` produz exatamente estes; afirmá-los ausentes mata também a
    // regressão em que uma tela volta a imprimir `{p.total_cents}` sem passar pelo formatador.
    expect(texto).not.toContain("1.234.567");
    expect(texto).not.toContain("987.654");
    expect(texto).not.toContain("150.000");
  });
});
