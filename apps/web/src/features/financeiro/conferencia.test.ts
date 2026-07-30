import { describe, expect, it } from "vitest";
import {
  avisoTotalParcial,
  avisoUltimaConferencia,
  type ConferenciaConta,
  type ConferenciaReport,
  FONTE_LABEL,
  fonteLabel,
  fraseConferencia,
  ordenarContas,
  tomVisual,
} from "./conferencia";
import { ORIGEM_LABEL } from "./projecao";

function conta(over: Partial<ConferenciaConta> = {}): ConferenciaConta {
  return {
    bank_account_id: "acc-1",
    bank_account_name: "Itaú PJ",
    bank_account_kind: "checking",
    saldo_banco_cents: 2_500_000,
    saldo_banco_origem: "banco",
    saldo_banco_fonte: "manual",
    saldo_banco_data: "2026-07-31",
    saldo_sistema_cents: 2_500_000,
    saldo_sistema_origem: "banco",
    divergencia_cents: 0,
    dentro_da_tolerancia: true,
    tolerancia_cents: 12_500,
    dias_desde_ultima_conferencia: 0,
    movimentos_ignorados: 0,
    notes: [],
    ...over,
  };
}

function report(over: Partial<ConferenciaReport> = {}): ConferenciaReport {
  return {
    start: "2026-07-01",
    end: "2026-07-31",
    contas: [],
    total_divergencia_cents: null,
    contas_avaliadas: 0,
    contas_sem_checkpoint: 0,
    contas_fora_da_banda: [],
    notes: [],
    ...over,
  };
}

describe("fraseConferencia — os quatro casos do AC4", () => {
  it("divergência NEGATIVA fora da banda: 'abaixo' + faltam lançamentos de SAÍDA", () => {
    // banco − sistema < 0 → o banco tem MENOS do que o e1p calculou: dinheiro saiu sem registro.
    // É o achado de maior valor do épico (REQ-14).
    const f = fraseConferencia(
      conta({ divergencia_cents: -234_000, dentro_da_tolerancia: false, tolerancia_cents: 12_500 }),
    );
    expect(f.tom).toBe("alerta");
    expect(f.texto).toMatch(/2\.340,00 abaixo/);
    expect(f.texto).toContain("Itaú PJ");
    expect(f.texto).toContain("faltam lançamentos de saída");
    // O número aparece em MÓDULO, com a direção dita em palavra — nunca "-R$ 2.340,00 abaixo".
    expect(f.texto).not.toContain("-R$");
  });

  it("divergência POSITIVA fora da banda: 'acima' + faltam lançamentos de ENTRADA", () => {
    const f = fraseConferencia(
      conta({ divergencia_cents: 120_000, dentro_da_tolerancia: false, tolerancia_cents: 12_500 }),
    );
    expect(f.tom).toBe("atencao");
    expect(f.texto).toMatch(/1\.200,00 acima/);
    expect(f.texto).toContain("faltam lançamentos de entrada");
  });

  it("dentro da banda: 'está tudo batendo', com a diferença E a tolerância explícitas", () => {
    const f = fraseConferencia(
      conta({ divergencia_cents: 350, dentro_da_tolerancia: true, tolerancia_cents: 12_500 }),
    );
    expect(f.tom).toBe("ok");
    expect(f.texto).toMatch(/^Está tudo batendo na conta Itaú PJ/);
    expect(f.texto).toMatch(/3,50/);
    expect(f.texto).toMatch(/dentro da tolerância de .*125,00/);
  });

  it("saldo indisponível: NENHUM número na frase, e um convite a declarar", () => {
    const f = fraseConferencia(
      conta({
        bank_account_name: "Nubank PJ",
        saldo_banco_cents: null,
        saldo_banco_origem: "indisponivel",
        saldo_banco_fonte: null,
        saldo_banco_data: null,
        saldo_sistema_cents: null,
        divergencia_cents: null,
        dentro_da_tolerancia: null,
        tolerancia_cents: 0,
        dias_desde_ultima_conferencia: null,
      }),
    );
    expect(f.tom).toBe("desconhecido");
    expect(f.texto).toContain("Não sei o saldo da conta Nubank PJ");
    expect(f.texto).toContain("declare o saldo");
    // ⚠️ O ponto do caso: ZERO dígitos. Um "R$ 0,00 de divergência" afirmaria que está batendo —
    // exatamente o que o e1p não tem lastro para dizer. (O nome da conta não tem dígito.)
    expect(f.texto).not.toMatch(/\d/);
    expect(f.texto).not.toContain("R$");
  });

  it("divergência ZERO avaliada é 'batendo', não 'não sei' (0 ≠ ausência)", () => {
    // A guarda é pelos campos serem `null`, nunca por falsidade: `!0` mandaria uma conta conferida
    // e exata para o caminho "não sei".
    const f = fraseConferencia(conta({ divergencia_cents: 0, dentro_da_tolerancia: true }));
    expect(f.tom).toBe("ok");
    expect(f.texto).toMatch(/^Está tudo batendo/);
  });

  it("a frase SEMPRE nomeia a conta — nos quatro casos", () => {
    const casos = [
      conta({ divergencia_cents: -1, dentro_da_tolerancia: false }),
      conta({ divergencia_cents: 1, dentro_da_tolerancia: false }),
      conta({ divergencia_cents: 0, dentro_da_tolerancia: true }),
      conta({ divergencia_cents: null, dentro_da_tolerancia: null }),
    ];
    for (const c of casos) expect(fraseConferencia(c).texto).toContain("Itaú PJ");
  });
});

describe("AC5 — dentro da banda é 🟢 e SILÊNCIO (o dado que a tela lê)", () => {
  it("R$ 3,50 num saldo de R$ 25.000 NÃO autoriza ícone de alerta", () => {
    const f = fraseConferencia(
      conta({ divergencia_cents: 350, dentro_da_tolerancia: true, tolerancia_cents: 12_500 }),
    );
    const v = tomVisual(f.tom);
    expect(v.alerta).toBe(false);
    expect(v.emoji).toBe("🟢");
    // Nenhuma cor de erro no cartão: nem `danger`, nem vermelho, nem âmbar.
    expect(v.cardClass).not.toMatch(/red|danger|amber/);
  });

  it("o caso 'não sei' também é silencioso — ausência de dado não é alarme", () => {
    const v = tomVisual("desconhecido");
    expect(v.alerta).toBe(false);
    expect(v.cardClass).not.toMatch(/red|danger|amber/);
  });

  it("fora da banda, aí sim: os dois tons de fora da banda autorizam alerta", () => {
    expect(tomVisual("alerta").alerta).toBe(true);
    expect(tomVisual("atencao").alerta).toBe(true);
  });
});

describe("ordenarContas — o que dói primeiro; 'não sei' por último", () => {
  it("ordena por |divergência| decrescente e joga as não avaliáveis para o fim", () => {
    const contas = [
      conta({ bank_account_id: "a", divergencia_cents: 4_000, dentro_da_tolerancia: true }),
      conta({ bank_account_id: "sem", divergencia_cents: null, dentro_da_tolerancia: null }),
      conta({ bank_account_id: "b", divergencia_cents: -120_000, dentro_da_tolerancia: false }),
      conta({ bank_account_id: "c", divergencia_cents: 90_000, dentro_da_tolerancia: false }),
    ];
    expect(ordenarContas(contas).map((c) => c.bank_account_id)).toEqual(["b", "c", "a", "sem"]);
  });

  it("não muda o array recebido (pura)", () => {
    const contas = [
      conta({ bank_account_id: "a", divergencia_cents: 10 }),
      conta({ bank_account_id: "b", divergencia_cents: 900 }),
    ];
    ordenarContas(contas);
    expect(contas.map((c) => c.bank_account_id)).toEqual(["a", "b"]);
  });

  it("empate mantém a ordem do backend (sort estável)", () => {
    const contas = [
      conta({ bank_account_id: "x", divergencia_cents: 500 }),
      conta({ bank_account_id: "y", divergencia_cents: -500 }),
    ];
    expect(ordenarContas(contas).map((c) => c.bank_account_id)).toEqual(["x", "y"]);
  });
});

describe("AC6 — o consolidado nunca é veredito (cenário das três contas do epic §3.2)", () => {
  const tresContas = [
    conta({ bank_account_id: "a", bank_account_name: "Itaú PJ", divergencia_cents: 120_000, dentro_da_tolerancia: false }),
    conta({ bank_account_id: "b", bank_account_name: "Nubank PJ", divergencia_cents: -90_000, dentro_da_tolerancia: false }),
    conta({ bank_account_id: "c", bank_account_name: "Caixa", divergencia_cents: 4_000, dentro_da_tolerancia: true }),
  ];

  it("+R$ 1.200 / −R$ 900 / +R$ 40 somam +R$ 340 — e as TRÊS têm frase própria", () => {
    const soma = tresContas.reduce((acc, c) => acc + (c.divergencia_cents ?? 0), 0);
    expect(soma).toBe(34_000);
    // O consolidado "saudável" esconde DOIS problemas; a decomposição é que os revela.
    const frases = ordenarContas(tresContas).map(fraseConferencia);
    expect(frases).toHaveLength(3);
    expect(frases.map((f) => f.tom)).toEqual(["atencao", "alerta", "ok"]);
    expect(frases[0].texto).toContain("Itaú PJ");
    expect(frases[1].texto).toContain("Nubank PJ");
    expect(frases[2].texto).toContain("Caixa");
  });

  it("avisoTotalParcial fala quando o total NÃO cobre todas as contas", () => {
    expect(avisoTotalParcial(report({ contas_sem_checkpoint: 0 }))).toBeNull();
    expect(avisoTotalParcial(report({ contas_sem_checkpoint: 1 }))).toContain("1 conta está");
    const dois = avisoTotalParcial(report({ contas_sem_checkpoint: 2 }));
    expect(dois).toContain("2 contas estão");
    expect(dois).toContain("ficaram de fora");
  });
});

describe("FONTE_LABEL — eixo B, mapa SEPARADO do eixo A (D-3)", () => {
  it("traduz a porta de entrada do saldo externo", () => {
    expect(fonteLabel("manual")).toBe("informado por você");
    expect(fonteLabel("ofx")).toBe("lido do extrato");
    expect(fonteLabel(null)).toBe("sem saldo informado");
    expect(fonteLabel("csv")).toBe("csv");
  });

  it("os dois vocabulários NÃO se misturam — nenhuma chave em comum", () => {
    // Achatar os dois eixos num mapa só foi o que gerou três vocabulários incompatíveis no design.
    const a = Object.keys(ORIGEM_LABEL);
    const b = Object.keys(FONTE_LABEL);
    expect(b.filter((k) => a.includes(k))).toEqual([]);
    // ...e nenhum rótulo repetido entre eles (o mesmo texto para eixos diferentes confundiria).
    const rotulosA = Object.values(ORIGEM_LABEL);
    expect(Object.values(FONTE_LABEL).filter((r) => rotulosA.includes(r))).toEqual([]);
  });
});

describe("avisoUltimaConferencia — o contador de abandono (bloco 4 da 8.5)", () => {
  it("nunca declarado vira convite, não número", () => {
    expect(avisoUltimaConferencia(conta({ dias_desde_ultima_conferencia: null }))).toBe(
      "Esta conta nunca teve saldo informado.",
    );
  });

  it("declarado hoje não vira frase nenhuma ('há 0 dias' é ruído)", () => {
    expect(avisoUltimaConferencia(conta({ dias_desde_ultima_conferencia: 0 }))).toBeNull();
  });

  it("conta o tempo em dias, com plural correto", () => {
    expect(avisoUltimaConferencia(conta({ dias_desde_ultima_conferencia: 1 }))).toContain("1 dia.");
    expect(avisoUltimaConferencia(conta({ dias_desde_ultima_conferencia: 47 }))).toContain(
      "47 dias",
    );
  });
});
