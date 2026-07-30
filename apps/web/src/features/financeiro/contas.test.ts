import { describe, expect, it } from "vitest";
import {
  type BankAccount,
  BANK_ACCOUNT_KINDS,
  centsToInput,
  contasAtivas,
  DISPONIVEL_CAIXA_LABEL,
  formatDateBR,
  isIgnored,
  KIND_CASH,
  KIND_CHECKING,
  KIND_INVESTMENT,
  KIND_SAVINGS,
  kindLabel,
  KINDS_FORA_DO_CAIXA,
  origemLabel,
  parseCentsBRL,
  resumoSaldos,
  signedAmountView,
  statusLabel,
  STATUS_IGNORED,
  STATUS_UNMATCHED,
  TOTAL_EM_CONTAS_LABEL,
  totalSaldoCents,
} from "./contas";
import type { BankTransaction } from "./contas";
import { ORIGEM_LABEL, ROTULO_BANCO } from "./projecao";

function conta(over: Partial<BankAccount> = {}): BankAccount {
  return {
    id: "acc-1",
    name: "Itaú PJ",
    kind: KIND_CHECKING,
    institution: "Itaú",
    institution_code: "341",
    branch: "1234",
    number: "56789-0",
    holder_document: "",
    pix_key: "",
    opening_balance_cents: 0,
    opening_date: "2026-01-01",
    is_primary: true,
    archived_at: null,
    saldo_derivado_cents: 0,
    saldo_derivado_origem: "banco",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("kindLabel — vocabulário de tipo de conta", () => {
  it("traduz os quatro tipos de `models.KINDS`", () => {
    expect(kindLabel(KIND_CHECKING)).toBe("Conta corrente");
    expect(kindLabel(KIND_SAVINGS)).toBe("Poupança");
    expect(kindLabel(KIND_INVESTMENT)).toBe("Aplicação");
    expect(kindLabel(KIND_CASH)).toBe("Caixa");
  });

  it("um tipo desconhecido aparece cru em vez de sumir da tela", () => {
    expect(kindLabel("crypto")).toBe("crypto");
  });

  it("o `<select>` de cadastro oferece exatamente os quatro tipos do backend", () => {
    // `platform_wallet` NÃO é um tipo cadastrável: a Carteira e1p é outro plano de dinheiro
    // (design §1.1) e o backend recusa com 422. A UI nem chega a oferecê-lo.
    expect(BANK_ACCOUNT_KINDS.map(([v]) => v)).toEqual([
      KIND_CHECKING,
      KIND_SAVINGS,
      KIND_INVESTMENT,
      KIND_CASH,
    ]);
    expect(BANK_ACCOUNT_KINDS.map(([v]) => v)).not.toContain("platform_wallet");
  });
});

describe("origemLabel — UM vocabulário de eixo A no frontend (Story 8.1)", () => {
  it("é o mapa de `projecao.ts`, re-exportado — não uma segunda cópia", () => {
    // Se alguém criar um mapa novo em contas.ts, este teste passa a comparar dois objetos
    // diferentes e falha — que é exatamente o alarme que a Story 8.7 pediu.
    expect(origemLabel("banco")).toBe(ORIGEM_LABEL.banco);
    expect(origemLabel("indisponivel")).toBe(ORIGEM_LABEL.indisponivel);
  });

  it("o vocabulário tem 4 valores — `declarado` foi revogado (D-3)", () => {
    expect(Object.keys(ORIGEM_LABEL).sort()).toEqual([
      "banco",
      "indisponivel",
      "misto",
      "plataforma",
    ]);
    expect(ORIGEM_LABEL.declarado).toBeUndefined();
  });
});

describe("signedAmountView — o sinal é o dado, não um `kind` inventado pela UI", () => {
  it("valor positivo é Entrada, com o sinal explícito", () => {
    const v = signedAmountView(125000);
    expect(v.entrada).toBe(true);
    expect(v.rotulo).toBe("Entrada");
    expect(v.texto).toMatch(/^\+ .*1\.250,00$/);
    expect(v.className).toContain("emerald");
  });

  it("valor negativo é Saída, exibido em módulo com o sinal na frente", () => {
    const v = signedAmountView(-234000);
    expect(v.entrada).toBe(false);
    expect(v.rotulo).toBe("Saída");
    expect(v.texto).toMatch(/^− .*2\.340,00$/);
    // Nunca dois sinais ("− -R$ 2.340,00"): o número exibido é o MÓDULO.
    expect(v.texto).not.toContain("-");
  });

  it("zero (que o backend recusa) aparece visível como entrada, não classificado em silêncio", () => {
    expect(signedAmountView(0).rotulo).toBe("Entrada");
    expect(signedAmountView(0).texto).toMatch(/^\+ .*0,00$/);
  });
});

describe("statusLabel / isIgnored — o movimento conta ou não conta no saldo", () => {
  it("ignorado é dito como estando FORA do saldo (não é só um rótulo neutro)", () => {
    expect(statusLabel(STATUS_IGNORED)).toContain("fora do saldo");
    expect(statusLabel(STATUS_UNMATCHED)).toBe("No saldo");
  });

  it("isIgnored casa pelo status do backend, não por heurística de tela", () => {
    const tx = { status: STATUS_IGNORED } as BankTransaction;
    expect(isIgnored(tx)).toBe(true);
    expect(isIgnored({ status: STATUS_UNMATCHED } as BankTransaction)).toBe(false);
  });
});

describe("totalSaldoCents / resumoSaldos — a divergência D-6 dos dois totais", () => {
  const contas = [
    conta({ id: "a", kind: KIND_CHECKING, saldo_derivado_cents: 4_000_000 }),
    conta({ id: "b", kind: KIND_SAVINGS, saldo_derivado_cents: 2_000_000 }),
    conta({ id: "c", kind: KIND_INVESTMENT, saldo_derivado_cents: 4_000_000 }),
    conta({ id: "d", kind: KIND_CHECKING, saldo_derivado_cents: 9_900_000, archived_at: "2026-05-01T00:00:00Z" }),
  ];

  it("conta ARQUIVADA nunca entra em soma nenhuma, em nenhum recorte", () => {
    expect(contasAtivas(contas).map((a) => a.id)).toEqual(["a", "b", "c"]);
    expect(totalSaldoCents(contas)).toBe(10_000_000);
    expect(totalSaldoCents(contas, { excludeKinds: KINDS_FORA_DO_CAIXA })).toBe(6_000_000);
  });

  it("o recorte 'disponível como caixa' reproduz o default de `active_balance_total` (8.8)", () => {
    // O backend exclui `investment` por default (design §6.1). Se os dois recortes divergirem, o
    // dono vê dois números com a mesma pretensão em duas telas — que é a origem da D-6.
    expect(KINDS_FORA_DO_CAIXA).toEqual([KIND_INVESTMENT]);
    expect(totalSaldoCents(contas, { excludeKinds: KINDS_FORA_DO_CAIXA })).toBe(6_000_000);
  });

  it("⚠️ D-6: nenhum dos dois rótulos desta tela é o da parcela da Projeção ('no banco')", () => {
    // O ponto do épico inteiro: dois números diferentes NÃO podem sair com o mesmo nome. O
    // `ROTULO_BANCO` pertence à parcela da Story 8.8 (que exclui aplicação e é somada ao
    // disponível da Carteira); esta tela usa rótulos próprios.
    expect(TOTAL_EM_CONTAS_LABEL).not.toBe(ROTULO_BANCO);
    expect(DISPONIVEL_CAIXA_LABEL).not.toBe(ROTULO_BANCO);
    expect(TOTAL_EM_CONTAS_LABEL).not.toBe(DISPONIVEL_CAIXA_LABEL);
    for (const r of [TOTAL_EM_CONTAS_LABEL, DISPONIVEL_CAIXA_LABEL]) {
      expect(r.toLowerCase()).not.toContain("no banco");
    }
  });

  it("havendo aplicação ativa, saem DOIS totais rotulados — nunca um número ambíguo", () => {
    const resumo = resumoSaldos(contas);
    expect(resumo).toHaveLength(2);
    expect(resumo[0]).toMatchObject({ rotulo: TOTAL_EM_CONTAS_LABEL, cents: 10_000_000 });
    expect(resumo[1]).toMatchObject({ rotulo: DISPONIVEL_CAIXA_LABEL, cents: 6_000_000 });
    // Cada total carrega o que ele inclui — o número nunca aparece sem a explicação.
    expect(resumo[0].explicacao).toMatch(/incluindo aplica/i);
    expect(resumo[1].explicacao).toMatch(/Exclui as aplica/i);
  });

  it("sem aplicação ativa os dois recortes coincidem e a segunda linha é omitida (ruído)", () => {
    const semAplicacao = contas.filter((a) => a.kind !== KIND_INVESTMENT);
    const resumo = resumoSaldos(semAplicacao);
    expect(resumo).toHaveLength(1);
    expect(resumo[0].rotulo).toBe(TOTAL_EM_CONTAS_LABEL);
    expect(resumo[0].cents).toBe(6_000_000);
  });

  it("aplicação ARQUIVADA não faz a segunda linha aparecer (ela não está no total)", () => {
    const resumo = resumoSaldos([
      conta({ id: "a", saldo_derivado_cents: 100 }),
      conta({ id: "c", kind: KIND_INVESTMENT, saldo_derivado_cents: 5000, archived_at: "2026-05-01T00:00:00Z" }),
    ]);
    expect(resumo).toHaveLength(1);
    expect(resumo[0].cents).toBe(100);
  });

  it("sem conta nenhuma, o total é 0 e continua rotulado (não vira `NaN` nem some)", () => {
    expect(totalSaldoCents([])).toBe(0);
    expect(resumoSaldos([])).toHaveLength(1);
  });

  it("saldo negativo (cheque especial) entra na soma como negativo", () => {
    expect(
      totalSaldoCents([
        conta({ id: "a", saldo_derivado_cents: 50_000 }),
        conta({ id: "b", saldo_derivado_cents: -80_000 }),
      ]),
    ).toBe(-30_000);
  });
});

describe("parseCentsBRL / centsToInput — dinheiro em centavos até a borda", () => {
  it("aceita vírgula, ponto decimal e ponto de milhar", () => {
    expect(parseCentsBRL("1.234,56")).toBe(123456);
    expect(parseCentsBRL("1234,56")).toBe(123456);
    expect(parseCentsBRL("1234.56")).toBe(123456);
    expect(parseCentsBRL("1234")).toBe(123400);
  });

  it("desambigua o ponto: milhar quando forma grupos de 3, decimal caso contrário", () => {
    // O erro que as ~8 conversões inline do repo cometem: `"1.234"` vira 1,23 nelas.
    expect(parseCentsBRL("1.234")).toBe(123400);
    expect(parseCentsBRL("1.234.567")).toBe(123456700);
    expect(parseCentsBRL("1.2")).toBe(120);
    expect(parseCentsBRL("0.5")).toBe(50);
  });

  it("aceita negativo (conta no limite é saldo de abertura legítimo)", () => {
    expect(parseCentsBRL("-250,00")).toBe(-25000);
  });

  it("vazio ou lixo vira 0 — sem `NaN` viajando para o backend", () => {
    expect(parseCentsBRL("")).toBe(0);
    expect(parseCentsBRL("   ")).toBe(0);
    expect(parseCentsBRL("abc")).toBe(0);
  });

  it("centsToInput é o inverso para exibir no formulário de edição", () => {
    expect(centsToInput(123456)).toBe("1234,56");
    expect(centsToInput(-25000)).toBe("-250,00");
    expect(parseCentsBRL(centsToInput(987654))).toBe(987654);
  });
});

describe("formatDateBR — data de calendário por STRING, nunca `new Date` local", () => {
  it("converte sem risco de voltar um dia em fuso negativo", () => {
    // `new Date("2026-01-01").toLocaleDateString()` devolveria 31/12/2025 no Brasil — o bug de
    // fuso que sumiu com eventos da Agenda (CLAUDE.md §6.0).
    expect(formatDateBR("2026-01-01")).toBe("01/01/2026");
    expect(formatDateBR("2026-07-30T00:00:00Z")).toBe("30/07/2026");
  });
});
