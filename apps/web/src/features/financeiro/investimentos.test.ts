import { describe, expect, it } from "vitest";
import { type BankAccount, ROTA_MOVIMENTOS } from "./contas";
import {
  avisoDeResgateExcedente,
  contasDeAplicacao,
  formatBRL,
  formatPct,
  formatPrincipal,
  PRINCIPAL_DESCONHECIDO,
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

// ── Onda 2b-ii — o principal calculado ───────────────────────────────────────────────────────

describe("formatPrincipal (Onda 2b-ii)", () => {
  it("formata o valor quando ele é afirmável", () => {
    // O NBSP (U+00A0) do `Intl.NumberFormat` é normalizado aqui de propósito: comparar contra
    // `formatBRL` seria tautológico (ele É a implementação), e comparar contra o literal com
    // espaço comum falha por um caractere invisível — que foi o que aconteceu ao escrever isto.
    // ⚠️ Ele vai como o escape `\u00a0`, NUNCA como o caractere literal. O literal faz
    // exatamente o que este teste descreve — some no diff — e reprova o `no-irregular-whitespace`
    // do `eslint`: foi assim que este arquivo deixou `pnpm lint` vermelho em `main` desde o
    // PR #102. O escape é visível para quem lê e para o linter, e o valor comparado é o mesmo.
    expect(formatPrincipal(1_000_000).replace(/\u00a0/g, " ")).toBe("R$ 10.000,00");
  });

  it("negativo é mostrado como é — clampar em zero seria esconder", () => {
    expect(formatPrincipal(-50_000)).toBe(formatBRL(-50_000));
  });

  it("null vira a frase de não-saber, nunca R$ 0,00", () => {
    // Zero seria a afirmação "você não tem nada aplicado" — falsa, e indistinguível de um saldo
    // genuinamente zerado. É o princípio da Story 8.21.
    expect(formatPrincipal(null)).toBe(PRINCIPAL_DESCONHECIDO);
    expect(formatPrincipal(null)).not.toBe(formatBRL(0));
  });
});

describe("avisoDeResgateExcedente (Onda 2b-ii)", () => {
  it("nomeia a diferença e a ação quando o principal é negativo", () => {
    const aviso = avisoDeResgateExcedente(-50_000);
    expect(aviso).toContain(formatBRL(50_000));
    expect(aviso).toContain("registre o rendimento do período");
    // "não adivinha" é literal e é regra do épico (Artigo IV): o sistema sabe que falta, e não
    // lança sozinho. Se esta asserção cair, alguém tirou a única frase que impede a próxima
    // pessoa de "resolver" o problema inferindo o valor.
    expect(aviso).toContain("não adivinha");
  });

  it("cala quando o principal é positivo, zero ou desconhecido", () => {
    expect(avisoDeResgateExcedente(1_000_000)).toBeNull();
    expect(avisoDeResgateExcedente(0)).toBeNull();
    expect(avisoDeResgateExcedente(null)).toBeNull();
  });
});

describe("o extrato da aplicação não é uma segunda fonte (Onda 2b-ii)", () => {
  const fontes = import.meta.glob("./{InvestimentosPage,ContasSaldosPage}.tsx", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>;

  it("as duas telas existem e foram lidas — controle positivo do gate abaixo", () => {
    // Sem isto, um glob que deixasse de casar tornaria o gate seguinte vacuamente verde: zero
    // arquivos varridos, zero ofensores, tudo "passando". É a família do teste que passa e não
    // prova nada.
    expect(Object.keys(fontes).sort()).toEqual([
      "./ContasSaldosPage.tsx",
      "./InvestimentosPage.tsx",
    ]);
  });

  it("nenhuma das duas escreve a rota de movimentos à mão", () => {
    // A duplicação de SUPERFÍCIE foi aceita (decisão do fundador, 2026-08-08): o extrato aparece
    // na tela da aplicação E em Contas & Saldos. A de CONSULTA, não — duas telas com filtros
    // próprios sobre o mesmo razão divergem, e a que diverge é a que ninguém olha. As duas
    // consomem `ROTA_MOVIMENTOS`, e é este gate que impede a string solta de voltar.
    const ofensores = Object.entries(fontes)
      .filter(([, fonte]) => fonte.includes(`"${ROTA_MOVIMENTOS}"`))
      .map(([caminho]) => caminho);

    expect(ofensores).toEqual([]);
  });
});
