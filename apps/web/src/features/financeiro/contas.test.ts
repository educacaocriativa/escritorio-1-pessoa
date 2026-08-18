import { describe, expect, it } from "vitest";
import {
  ACAO_BAIXAR_PAYABLE,
  acaoBaixarPayable,
  AGENDADO_ENTRADA_LABEL,
  AGENDADO_SAIDA_LABEL,
  avisoDestinoAplicacao,
  type BankAccount,
  BANK_ACCOUNT_KINDS,
  avisoContasPagasAnteriores,
  centsToInput,
  contasAtivas,
  diaAnteriorISO,
  DISPONIVEL_CAIXA_LABEL,
  formatDateBR,
  hojeISO,
  impedimentoDaTransferencia,
  isIgnored,
  isOrigemDoSistema,
  kindDaTransferencia,
  motivoDeNaoEditar,
  podeEditarOsFatosDoMovimento,
  SOURCE_MANUAL,
  SOURCE_PAYABLE,
  SOURCE_TRANSFER,
  SOURCES_SISTEMA,
  TRANSFER_KIND_INVESTMENT_IN,
  TRANSFER_KIND_INVESTMENT_OUT,
  TRANSFER_KIND_OWN,
  TRANSFERIR_LABEL,
  KIND_CASH,
  KIND_CHECKING,
  KIND_INVESTMENT,
  KIND_SAVINGS,
  kindLabel,
  KINDS_FORA_DO_CAIXA,
  naturezaParaEnvio,
  OPERATION_NATURE_OUTRO,
  OPERATION_NATURE_RECEITA_FINANCEIRA,
  OPERATION_NATURE_TARIFA,
  OPERATION_NATURE_TRANSFERENCIA,
  OPERATION_NATURE_TRIBUTO,
  OPERATION_NATURES,
  operationNatureLabel,
  origemLabel,
  ponteiroDaTransferencia,
  parseCentsBRL,
  type PayablesPaidBefore,
  resumoSaldos,
  SALDO_APURADO_PREFIXO,
  saldoApuradoEm,
  signedAmountView,
  statusLabel,
  STATUS_IGNORED,
  STATUS_UNMATCHED,
  TOTAL_EM_CONTAS_LABEL,
  totalAgendadoCents,
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
    opening_balance_is_known: true,
    opening_date: "2026-01-01",
    is_primary: true,
    archived_at: null,
    saldo_derivado_cents: 0,
    saldo_derivado_origem: "banco",
    // Story 8.14 — a conta padrão nasce SEM nada agendado, que é o estado do dono comum. Cada
    // teste que quer o terceiro número o pede explicitamente.
    agendado_saida_cents: 0,
    agendado_entrada_cents: 0,
    agendado_origem: "banco",
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

  it("⚠️ D-6: nenhum rótulo desta tela é o da parcela da Projeção ('no banco'), nem colide entre si", () => {
    // O ponto do épico inteiro: dois números diferentes NÃO podem sair com o mesmo nome. O
    // `ROTULO_BANCO` pertence à parcela da Story 8.8 (que exclui aplicação e é somada ao
    // disponível da Carteira); esta tela usa rótulos próprios.
    //
    // ⚠️ **[Story 8.14] ESTENDIDO, não duplicado.** O terceiro número ("Agendado para sair") e o
    // par simétrico dele passam pelos MESMOS testes de colisão que o UX-001 instituiu — a story
    // instrui a 8.15 e a 8.18 a fazerem o mesmo. Um teste paralelo por story faria cada rótulo
    // novo ser conferido contra um subconjunto diferente dos antigos, que é como a colisão volta.
    const rotulos = [
      TOTAL_EM_CONTAS_LABEL,
      DISPONIVEL_CAIXA_LABEL,
      AGENDADO_SAIDA_LABEL,
      AGENDADO_ENTRADA_LABEL,
    ];
    for (const r of rotulos) {
      expect(r).not.toBe(ROTULO_BANCO);
      // Nem SER nem CONTER: "Total em contas no banco" seria tão ruim quanto a igualdade.
      expect(r.toLowerCase()).not.toContain(ROTULO_BANCO.toLowerCase());
      expect(r.toLowerCase()).not.toContain("no banco");
    }
    // E nenhum contém OUTRO — dois recortes cujos nomes se contêm são lidos como o mesmo número
    // com um qualificador, que é a D-6 pela porta de dentro.
    for (const a of rotulos) {
      for (const b of rotulos) {
        if (a === b) continue;
        expect(a.toLowerCase()).not.toContain(b.toLowerCase());
      }
    }
    expect(new Set(rotulos).size).toBe(rotulos.length);
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

  // ── Story 8.14 — o terceiro número ─────────────────────────────────────────────────────────

  it("'Agendado para sair' é OMITIDO quando é zero (mesma disciplina anti-ruído do 2º total)", () => {
    // O dono que nunca agenda nada não pode ver uma linha "R$ 0,00" para sempre: um número que é
    // sempre zero é peso de ERP, e o produto recusa peso de ERP.
    const resumo = resumoSaldos([conta({ id: "a", saldo_derivado_cents: 100 })]);
    expect(resumo.map((r) => r.rotulo)).toEqual([TOTAL_EM_CONTAS_LABEL]);
  });

  it("havendo débito agendado, o TERCEIRO número aparece — com a explicação colada", () => {
    const resumo = resumoSaldos([
      conta({ id: "a", saldo_derivado_cents: 1_000_000, agendado_saida_cents: 500_000 }),
      conta({ id: "b", saldo_derivado_cents: 200_000, agendado_saida_cents: 30_000 }),
    ]);
    const agendado = resumo.find((r) => r.rotulo === AGENDADO_SAIDA_LABEL);
    expect(agendado?.cents).toBe(530_000);
    // O número nunca aparece sem dizer o que ele é — e sobretudo o que ele NÃO é.
    expect(agendado?.explicacao).toMatch(/data futura/i);
    expect(agendado?.explicacao).toMatch(/Total em contas/);
    // ...e ele NÃO contamina o saldo: o "Total em contas" continua sendo a soma dos saldos.
    expect(resumo[0]).toMatchObject({ rotulo: TOTAL_EM_CONTAS_LABEL, cents: 1_200_000 });
  });

  it("'Agendado para entrar' nasce omitido — só passa a ter valor na Story 8.15", () => {
    const resumo = resumoSaldos([
      conta({ id: "a", saldo_derivado_cents: 100, agendado_saida_cents: 50 }),
    ]);
    expect(resumo.map((r) => r.rotulo)).not.toContain(AGENDADO_ENTRADA_LABEL);
    // ...mas o par simétrico funciona no dia em que o backend o preencher (o contrato já existe).
    const comEntrada = resumoSaldos([
      conta({ id: "a", saldo_derivado_cents: 100, agendado_entrada_cents: 900 }),
    ]);
    expect(comEntrada.find((r) => r.rotulo === AGENDADO_ENTRADA_LABEL)?.cents).toBe(900);
  });

  it("conta ARQUIVADA não entra no agendado, como não entra em soma nenhuma", () => {
    expect(
      totalAgendadoCents(
        [
          conta({ id: "a", agendado_saida_cents: 100 }),
          conta({ id: "z", agendado_saida_cents: 900, archived_at: "2026-05-01T00:00:00Z" }),
        ],
        "agendado_saida_cents",
      ),
    ).toBe(100);
  });

  it("backend antigo (sem os campos) não quebra nem inventa número", () => {
    // O front tolera o payload anterior à 8.14: campo ausente vira 0, e a linha some por omissão —
    // nunca `NaN`, nunca "R$ 0,00" pendurado.
    const semOsCampos = { ...conta({ id: "a", saldo_derivado_cents: 100 }) } as BankAccount;
    delete (semOsCampos as Partial<BankAccount>).agendado_saida_cents;
    expect(totalAgendadoCents([semOsCampos], "agendado_saida_cents")).toBe(0);
    expect(resumoSaldos([semOsCampos]).map((r) => r.rotulo)).toEqual([TOTAL_EM_CONTAS_LABEL]);
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

describe("Story 8.11 — diaAnteriorISO: por que o DIA ANTERIOR, e não o mesmo dia", () => {
  it("volta um dia, atravessando mês, ano e ano bissexto", () => {
    expect(diaAnteriorISO("2026-03-10")).toBe("2026-03-09");
    expect(diaAnteriorISO("2026-03-01")).toBe("2026-02-28");
    expect(diaAnteriorISO("2026-01-01")).toBe("2025-12-31");
    expect(diaAnteriorISO("2024-03-01")).toBe("2024-02-29"); // bissexto
  });

  it("aritmética em UTC — não perde um dia extra em fuso negativo", () => {
    // Com `new Date("2026-03-01")` + hora local −03:00, o "dia anterior" sairia 27/02 (dois dias
    // antes). É a mesma classe de bug que sumiu com eventos da Agenda (CLAUDE.md §6.0).
    expect(diaAnteriorISO("2026-03-01")).not.toBe("2026-02-27");
  });

  it("entrada inválida volta como veio — nunca uma data inventada", () => {
    expect(diaAnteriorISO("")).toBe("");
    expect(diaAnteriorISO("nao-e-data")).toBe("nao-e-data");
  });
});

describe("Story 8.11 — a frase do aviso: silêncio por default e nenhum saldo dentro", () => {
  const PAGAS: PayablesPaidBefore = {
    count: 45,
    total_cents: 1_234_500,
    oldest_paid_on: "2026-03-10",
    newest_paid_on: "2026-07-28",
  };

  it("com N > 0, nomeia quantas, o intervalo, o total PAGO e a data escolhida", () => {
    const frase = avisoContasPagasAnteriores(PAGAS, "2026-07-30");
    expect(frase).toContain("45 contas pagas entre 10/03/2026 e 28/07/2026");
    expect(frase).toContain("pagos"); // total PAGO — jamais um saldo (AC4)
    expect(frase).toContain("30/07/2026");
    expect(frase).toContain("não vão entrar no extrato do e1p");
  });

  it("N == 1 fala no singular (a mensagem é lida no pior momento do usuário)", () => {
    const frase = avisoContasPagasAnteriores(
      { count: 1, total_cents: 25_000, oldest_paid_on: "2026-05-02", newest_paid_on: "2026-05-02" },
      "2026-06-01",
    );
    expect(frase).toContain("1 conta paga em 02/05/2026");
    expect(frase).toContain("ela não vai entrar");
    expect(frase).not.toContain("entre");
  });

  it("N == 0, dado ausente ou falha do endpoint → `null` (SILÊNCIO, nunca um aviso vazio)", () => {
    expect(
      avisoContasPagasAnteriores(
        { count: 0, total_cents: 0, oldest_paid_on: null, newest_paid_on: null },
        "2026-07-30",
      ),
    ).toBeNull();
    expect(avisoContasPagasAnteriores(null, "2026-07-30")).toBeNull();
    // Contagem sem data: estado incoerente do backend — cala em vez de montar meia frase.
    expect(
      avisoContasPagasAnteriores(
        { count: 3, total_cents: 1, oldest_paid_on: null, newest_paid_on: null },
        "2026-07-30",
      ),
    ).toBeNull();
  });

  it("⚠️ a frase NÃO reusa rótulo de saldo do produto (UX-001 / D-6)", () => {
    const frase = avisoContasPagasAnteriores(PAGAS, "2026-07-30") ?? "";
    expect(frase).not.toContain(ROTULO_BANCO);
    expect(frase).not.toContain(TOTAL_EM_CONTAS_LABEL);
    expect(frase).not.toContain(DISPONIVEL_CAIXA_LABEL);
  });
});

describe("Story 8.10 — saldoApuradoEm: a data em que o saldo derivado foi apurado", () => {
  it('"2026-07-30" → "Saldo em 30/07" (dia/mês, sem ano — é sempre um saldo corrente)', () => {
    expect(saldoApuradoEm("2026-07-30")).toBe("Saldo em 30/07");
    expect(saldoApuradoEm("2026-01-05")).toBe("Saldo em 05/01");
    // Aceita ISO com hora (mesmo contrato de `formatDateBR`), sempre por fatiamento de string —
    // `new Date("2026-01-01")` voltaria um dia em fuso negativo (CLAUDE.md §6.0).
    expect(saldoApuradoEm("2026-07-30T00:00:00Z")).toBe("Saldo em 30/07");
  });

  it("entrada inválida degrada para o texto cru — nunca devolve um prefixo órfão", () => {
    // "Saldo em " sozinho seria pior do que uma data feia: uma frase pela metade ao lado de um
    // número é exatamente o "saldo sem data de apuração" que esta story existe para eliminar.
    expect(saldoApuradoEm("")).toBe("Saldo em ");
    expect(saldoApuradoEm("sem-data")).toBe("Saldo em sem-data");
  });

  it("⚠️ o prefixo NÃO colide com o do saldo DECLARADO nem com rótulo de total (UX-001 / D-6)", () => {
    // As duas pontas da comparação da Conferência: aqui é o que o e1p CALCULOU; "Saldo declarado
    // em ..." é o que o BANCO diz. Compartilhar o prefixo faria a tela dizer a mesma coisa sobre
    // duas testemunhas diferentes — a colisão exata que o UX-001 pagou para desfazer.
    expect(SALDO_APURADO_PREFIXO).toBe("Saldo em");
    expect("Saldo declarado em".startsWith(SALDO_APURADO_PREFIXO)).toBe(false);
    const frase = saldoApuradoEm("2026-07-30");
    expect(frase).not.toContain(ROTULO_BANCO);
    expect(frase).not.toContain(TOTAL_EM_CONTAS_LABEL);
    expect(frase).not.toContain(DISPONIVEL_CAIXA_LABEL);
  });
});

// ── Story 8.17 — o manual curado e a guarda de contagem dupla ────────────────────────────────

describe("Story 8.17 — natureza da operação: curadoria, NUNCA whitelist", () => {
  it("a lista sugerida é a do backend (`models.OPERATION_NATURES`), na ordem da tela", () => {
    // Espelho manual: o outro lado deste pareamento é
    // `apps/api/tests/test_bank_contagem_dupla.py::test_vocabulario_sugerido_bate_com_a_ui`.
    // Só `tarifa_bancaria` é valor NOVO; os outros três já eram vocabulário do design-mãe §7.2.
    expect(OPERATION_NATURES.map(([v]) => v)).toEqual([
      OPERATION_NATURE_TARIFA,
      OPERATION_NATURE_TRIBUTO,
      OPERATION_NATURE_TRANSFERENCIA,
      OPERATION_NATURE_RECEITA_FINANCEIRA,
    ]);
    expect(OPERATION_NATURES.map(([v]) => v)).toEqual([
      "tarifa_bancaria",
      "tributo",
      "transferencia_propria",
      "receita_financeira",
    ]);
  });

  it("a válvula 'Outro' é sentinela de UI e NUNCA viaja para a API", () => {
    // O extrato está cheio do que ninguém imaginou (estorno de tarifa, cashback, crédito de
    // convênio). Recusar um fato legítimo recria a incompletude que a onda combate — por isso o
    // que viaja é o TEXTO do usuário, e o sentinela fica na tela.
    expect(OPERATION_NATURES.map(([v]) => v)).not.toContain(OPERATION_NATURE_OUTRO);
    expect(naturezaParaEnvio(OPERATION_NATURE_OUTRO, "estorno de tarifa")).toBe("estorno de tarifa");
  });

  it("escolha da lista viaja como veio; espaços em volta não viram valor", () => {
    expect(naturezaParaEnvio(OPERATION_NATURE_TARIFA, "")).toBe("tarifa_bancaria");
    expect(naturezaParaEnvio(OPERATION_NATURE_OUTRO, "   ")).toBeNull();
  });

  it("nada escolhido → `null`, e o backend aceita — a obrigatoriedade é de TELA (AC7)", () => {
    // Movimento legado nasceu com `operation_nature = NULL` e continua legítimo: forçar
    // preenchimento retroativo seria reescrever a afirmação do usuário (lição D-3).
    expect(naturezaParaEnvio("", "")).toBeNull();
    expect(operationNatureLabel(null)).toBe("");
  });

  it("um valor livre do backend aparece cru em vez de sumir da tela", () => {
    expect(operationNatureLabel("tarifa_bancaria")).toBe("Tarifa / juros");
    expect(operationNatureLabel("cashback")).toBe("cashback");
  });

  it("⚠️ nenhum rótulo da lista colide com rótulo de SALDO do produto (UX-001 / D-6)", () => {
    for (const [, rotulo] of OPERATION_NATURES) {
      expect(rotulo).not.toContain(ROTULO_BANCO);
      expect(rotulo).not.toBe(TOTAL_EM_CONTAS_LABEL);
      expect(rotulo).not.toBe(DISPONIVEL_CAIXA_LABEL);
    }
  });

  it("o ponteiro para a transferência (8.18) só existe quando ela existe", () => {
    // A opção "Transferência entre minhas contas" fica na lista de todo jeito — recusar um fato
    // legítimo é o defeito que esta story combate —, mas apontar para uma tela que não existe
    // mandaria o usuário para lugar nenhum.
    expect(ponteiroDaTransferencia(false)).toBeNull();
    expect(ponteiroDaTransferencia(true)).toContain("transferência entre contas");
  });
});

describe("Story 8.17 — o 409 acionável da contagem dupla", () => {
  const erro409 = (detail: unknown) => ({ response: { status: 409, data: { detail } } });

  it("reconhece pelo `acao`, nunca por substring da mensagem", () => {
    const acionavel = acaoBaixarPayable(
      erro409({ acao: ACAO_BAIXAR_PAYABLE, payable_id: "p-1", mensagem: "Existe uma conta…" }),
    );
    expect(acionavel).toEqual({ payableId: "p-1", mensagem: "Existe uma conta…" });
  });

  it("o formato é o MESMO da 8.12 — `acao` dentro de `detail`, não irmão dele", () => {
    // Dois formatos de erro acionável obrigariam cada tela a saber, por rota, onde procurar o
    // `acao` — que é como um contrato de erro deixa de ser contrato.
    expect(
      acaoBaixarPayable({
        response: { data: { acao: ACAO_BAIXAR_PAYABLE, payable_id: "p-1" } },
      }),
    ).toBeNull();
  });

  it("não confunde com o 409 de `cadastrar_conta` da 8.12 nem com erro comum", () => {
    expect(acaoBaixarPayable(erro409({ acao: "cadastrar_conta", mensagem: "x" }))).toBeNull();
    expect(acaoBaixarPayable(erro409("Movimento inválido"))).toBeNull();
    expect(acaoBaixarPayable(new Error("rede caiu"))).toBeNull();
    expect(acaoBaixarPayable(undefined)).toBeNull();
  });
});


// ── Story 8.18 — transferência entre contas próprias ─────────────────────────────────────────

describe("Story 8.18 — o vocabulário da transferência não colide com rótulo de SALDO (UX-001)", () => {
  it("⚠️ o rótulo da AÇÃO passa pelo MESMO teste de colisão dos totais, estendido", () => {
    // A instrução da 8.14 é literal: *"o teste que fixa isso é o MESMO de `contas.test.ts`,
    // estendido, nunca um paralelo"* — um teste por story faria cada rótulo novo ser conferido
    // contra um subconjunto diferente dos antigos, que é exatamente como a colisão volta.
    const rotulos = [
      TOTAL_EM_CONTAS_LABEL,
      DISPONIVEL_CAIXA_LABEL,
      AGENDADO_SAIDA_LABEL,
      AGENDADO_ENTRADA_LABEL,
      TRANSFERIR_LABEL,
    ];
    for (const r of rotulos) {
      expect(r).not.toBe(ROTULO_BANCO);
      expect(r.toLowerCase()).not.toContain(ROTULO_BANCO.toLowerCase());
      expect(r.toLowerCase()).not.toContain("no banco");
    }
    for (const a of rotulos) {
      for (const b of rotulos) {
        if (a === b) continue;
        expect(a.toLowerCase()).not.toContain(b.toLowerCase());
      }
    }
    expect(new Set(rotulos).size).toBe(rotulos.length);
  });

  it("é vocabulário de MOVIMENTO, não de saldo — não diz 'total', 'disponível' nem 'saldo'", () => {
    // "sair"/"entrar"/"transferir" descrevem o dinheiro se mexendo; "total"/"disponível"/"no banco"
    // descrevem o dinheiro parado. A tela não pode sugerir que são a mesma coisa.
    for (const palavra of ["total", "disponível", "saldo"]) {
      expect(TRANSFERIR_LABEL.toLowerCase()).not.toContain(palavra);
    }
  });
});

describe("Story 8.18 — kindDaTransferencia: DERIVADO das contas, nunca perguntado", () => {
  it("corrente → poupança é transferência entre contas próprias", () => {
    expect(kindDaTransferencia(KIND_CHECKING, KIND_SAVINGS)).toBe(TRANSFER_KIND_OWN);
    expect(kindDaTransferencia(KIND_CASH, KIND_CHECKING)).toBe(TRANSFER_KIND_OWN);
  });

  it("destino APLICAÇÃO é entrada de aplicação; origem aplicação é saída", () => {
    expect(kindDaTransferencia(KIND_CHECKING, KIND_INVESTMENT)).toBe(
      TRANSFER_KIND_INVESTMENT_IN,
    );
    expect(kindDaTransferencia(KIND_INVESTMENT, KIND_CHECKING)).toBe(
      TRANSFER_KIND_INVESTMENT_OUT,
    );
  });

  it("aplicação → aplicação conta como ENTRADA (o destino manda) — regra escrita, não acidente", () => {
    // Precedência declarada: o destino decide. Sem esta asserção, o caso ficaria por conta da ordem
    // dos `if`, e ninguém saberia que houve uma escolha.
    expect(kindDaTransferencia(KIND_INVESTMENT, KIND_INVESTMENT)).toBe(
      TRANSFER_KIND_INVESTMENT_IN,
    );
  });
});

describe("Story 8.18 — avisoDestinoAplicacao: obrigatório, e silêncio no resto", () => {
  it("com destino de aplicação, nomeia a conta, o recorte que CAI e o que NÃO muda", () => {
    const frase = avisoDestinoAplicacao(
      conta({ id: "c", name: "CDB Itaú", kind: KIND_INVESTMENT }),
    );
    expect(frase).toContain("CDB Itaú");
    // O que cai — e a frase cita a CONSTANTE do rótulo, não uma cópia do texto.
    expect(frase).toContain(DISPONIVEL_CAIXA_LABEL);
    expect(frase).toContain("Projeção de Caixa");
    // ...e o que NÃO cai, senão "aplicar" seria lido como "perder dinheiro".
    expect(frase).toContain(TOTAL_EM_CONTAS_LABEL);
  });

  it("destino elegível ou nenhum destino → `null` (silêncio é o default)", () => {
    expect(avisoDestinoAplicacao(conta({ kind: KIND_CHECKING }))).toBeNull();
    expect(avisoDestinoAplicacao(conta({ kind: KIND_SAVINGS }))).toBeNull();
    expect(avisoDestinoAplicacao(null)).toBeNull();
  });

  it("⚠️ o aviso não reusa o rótulo da parcela da Projeção ('no banco') — UX-001", () => {
    const frase = avisoDestinoAplicacao(conta({ kind: KIND_INVESTMENT })) ?? "";
    expect(frase).not.toContain(ROTULO_BANCO);
  });
});

describe("Story 8.18 — impedimentoDaTransferencia: o que a tela consegue antecipar, e só isso", () => {
  const a = conta({ id: "a", kind: KIND_CHECKING });
  const b = conta({ id: "b", kind: KIND_SAVINGS });
  // ⚠️ **`hojeISO()` e `Date.now()` ficam aqui de propósito — não é a classe da #120/#129.**
  // `impedimentoDaTransferencia` compara duas STRINGS `YYYY-MM-DD` e resolve "hoje" chamando
  // `hojeISO()` ela mesma; não existe fuso de tenant nesta função (nem `useFuso`, nem `today(tz)`),
  // então não há dois relógios a confundir e um fuso distante não teria o que matar. Congelar o
  // relógio aqui só amarraria o teste a um literal sem ganhar poder de detecção.
  //
  // ⚠️ O que estas asserções NÃO aguentam: se um dia `hojeISO()` virar o dia do TENANT (a dívida
  // anotada em `cobrancas/CobrancasPage.test.tsx`), o `amanha`/`ontem` derivados de UTC abaixo
  // passam a poder empatar com o "hoje" da função — num tenant a leste, o dia UTC seguinte JÁ é
  // hoje. Quem pagar aquela dívida derruba estes dois testes e tem de derivar as bordas do mesmo
  // relógio que a função passar a usar. É o aviso, não um convite a "consertar" antes da hora.
  const HOJE = hojeISO();

  it("sem as duas contas, pede as duas", () => {
    expect(impedimentoDaTransferencia(null, b, 100, HOJE)).toMatch(/origem e a de destino/);
    expect(impedimentoDaTransferencia(a, null, 100, HOJE)).toMatch(/origem e a de destino/);
  });

  it("mesma conta nos dois lados é impedimento — não moveria dinheiro nenhum", () => {
    expect(impedimentoDaTransferencia(a, a, 100, HOJE)).toMatch(/a mesma/);
  });

  it("valor zero ou negativo é impedimento — o sinal vive nas pernas", () => {
    expect(impedimentoDaTransferencia(a, b, 0, HOJE)).toMatch(/maior que zero/);
    expect(impedimentoDaTransferencia(a, b, -100, HOJE)).toMatch(/maior que zero/);
  });

  it("data futura é impedimento — o mesmo 422 que `create_transfer` aplica no backend", () => {
    // A tela antecipa a guarda para não montar uma parede um clique adiante; quem a APLICA é o
    // backend (achado A-3: ela não pode viver na guarda genérica do módulo, que aceita futuro para
    // origem de sistema desde a Story 8.14).
    const amanha = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
    expect(impedimentoDaTransferencia(a, b, 100, amanha)).toMatch(/não pode ser futura/);
  });

  it("tudo certo → `null`, inclusive HOJE (a borda aceita)", () => {
    expect(impedimentoDaTransferencia(a, b, 100_00, HOJE)).toBeNull();
    const ontem = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
    expect(impedimentoDaTransferencia(a, b, 100_00, ontem)).toBeNull();
  });
});

describe("Story 8.18 (AC9) — a tela LÊ o `source`; ela não conhece a regra", () => {
  const perna = (over: Partial<BankTransaction> = {}) =>
    ({ source: SOURCE_TRANSFER, transfer_id: "tr-1", ...over }) as BankTransaction;

  it("toda origem de SISTEMA perde a edição de fatos — escrito contra o CONJUNTO", () => {
    // Nunca contra `'transfer'` solto: quando a Onda 2b ligar `yield` e a Onda 3 ligar `payout`, a
    // tela herda o comportamento sem que ninguém edite um `if`.
    for (const source of SOURCES_SISTEMA) {
      const tx = { source } as BankTransaction;
      expect(isOrigemDoSistema(tx)).toBe(true);
      expect(podeEditarOsFatosDoMovimento(tx)).toBe(false);
      expect(motivoDeNaoEditar(tx)).toBeTruthy();
    }
  });

  it("o movimento MANUAL continua editável — a guarda é sobre origem, não sobre movimento", () => {
    const tx = { source: "manual" } as BankTransaction;
    expect(isOrigemDoSistema(tx)).toBe(false);
    expect(podeEditarOsFatosDoMovimento(tx)).toBe(true);
    expect(motivoDeNaoEditar(tx)).toBeNull();
  });

  it("`source` desconhecido cai no lado EXTERNO — o erro barulhento, não o silencioso", () => {
    // Assumir "de sistema" ESCONDERIA a edição de um movimento legítimo, e ninguém abre chamado
    // para um botão que nunca esteve lá. Assumir "externo" no máximo oferece um botão que o
    // backend recusa com 422 — visível e corrigível.
    const tx = { source: "origem_de_um_backend_mais_novo" } as BankTransaction;
    expect(podeEditarOsFatosDoMovimento(tx)).toBe(true);
  });

  it("a perna de transferência aponta para o gesto CERTO: apagar o lançamento, não a linha", () => {
    expect(motivoDeNaoEditar(perna())).toMatch(/apague a transferência/i);
    expect(motivoDeNaoEditar(perna())).toMatch(/as duas pernas somem juntas/i);
    // A origem de perna única aponta para o lançamento dela, que é outro gesto.
    expect(motivoDeNaoEditar({ source: SOURCE_PAYABLE } as BankTransaction)).toMatch(
      /corrija o lançamento de origem/i,
    );
  });

  it("o espelho de `SOURCES_SISTEMA` tem os cinco valores do backend", () => {
    expect([...SOURCES_SISTEMA].sort()).toEqual(
      ["charge", "payable", "payout", "transfer", "yield"],
    );
    expect(SOURCES_SISTEMA).not.toContain(SOURCE_MANUAL);
  });
});

describe("Story 8.18 — o ponteiro do manual passa a apontar para algo que existe", () => {
  it("a 8.17 o deixou condicional e a 8.18 é quem torna o `true` legítimo", () => {
    // A condicional FICA: ela é o registro de que este ponteiro depende de uma superfície existir.
    expect(ponteiroDaTransferencia(false)).toBeNull();
    expect(ponteiroDaTransferencia(true)).toContain("transferência entre contas");
    expect(ponteiroDaTransferencia(true)).toContain("não digita duas vezes");
  });
});
