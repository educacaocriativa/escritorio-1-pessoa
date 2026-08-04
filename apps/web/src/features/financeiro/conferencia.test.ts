import { describe, expect, it } from "vitest";
import {
  avisoTotalParcial,
  avisoUltimaConferencia,
  type ConferenciaConta,
  type ConferenciaReport,
  FONTE_LABEL,
  fonteLabel,
  fraseConferencia,
  LADO_BANCO_LABEL,
  LADO_E1P_LABEL,
  LADOS_GRUPO_LABEL,
  ordenarContas,
  tomVisual,
} from "./conferencia";
import { DISPONIVEL_CAIXA_LABEL, TOTAL_EM_CONTAS_LABEL } from "./contas";
import { ORIGEM_LABEL, ROTULO_BANCO } from "./projecao";

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
    // Story 8.16 — os termos da pré-condição do gate. Zero no default: o cenário limpo é o
    // silêncio, e cada teste liga só o termo que quer exercitar.
    lancamentos_sem_conta_informada: 0,
    valor_sem_conta_informada_cents: 0,
    rendimentos_sem_perna_bancaria: 0,
    valor_rendimentos_sem_perna_cents: 0,
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
    // UX-001: os dois lados nomeados como nas colunas — quem AFIRMA × quem CALCULA.
    expect(f.texto).toContain("O banco diz");
    expect(f.texto).toContain("do que eu calculei");
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

  it("Story 8.20 — saldo informado na DATA DE ABERTURA: não manda declarar de novo", () => {
    // O caso degenerado: houve declaração (`saldo_banco_data` preenchido) e mesmo assim a
    // comparação não decide nada. Pedir "declare o saldo para eu conferir" aqui mandaria o dono
    // repetir exatamente o ato que ele acabou de fazer — em laço.
    const f = fraseConferencia(
      conta({
        bank_account_name: "C6 PJ",
        saldo_banco_cents: null,
        saldo_banco_origem: "indisponivel",
        saldo_banco_fonte: null,
        saldo_banco_data: "2026-07-30",
        saldo_sistema_cents: null,
        divergencia_cents: null,
        dentro_da_tolerancia: null,
        tolerancia_cents: 0,
        dias_desde_ultima_conferencia: 0,
      }),
    );
    expect(f.tom).toBe("desconhecido");
    expect(f.texto).toContain("C6 PJ");
    expect(f.texto).toContain("30/07/2026");
    expect(f.texto).toContain("mesmo dia em que ela foi aberta no e1p");
    expect(f.texto).toContain("dia posterior");
    // ⚠️ A asserção NEGATIVA é o ponto do teste.
    expect(f.texto).not.toContain("declare o saldo para eu conferir");
    expect(f.texto).not.toContain("Não sei o saldo da conta");
    // Nenhum tom novo, nenhuma cor nova, nenhum ícone de alerta (AC5 da 8.7, intacto).
    expect(tomVisual(f.tom).alerta).toBe(false);
    expect(tomVisual(f.tom).emoji).toBe("⚪");
  });

  it("Story 8.20 — os DOIS ramos do 'não sei' têm o MESMO tom, e textos diferentes", () => {
    const base = {
      saldo_banco_cents: null,
      saldo_banco_origem: "indisponivel",
      saldo_sistema_cents: null,
      divergencia_cents: null,
      dentro_da_tolerancia: null,
      tolerancia_cents: 0,
    } as const;
    const semDeclaracao = fraseConferencia(
      conta({ ...base, saldo_banco_fonte: null, saldo_banco_data: null }),
    );
    const degenerada = fraseConferencia(
      conta({ ...base, saldo_banco_fonte: null, saldo_banco_data: "2026-07-30" }),
    );
    expect(semDeclaracao.tom).toBe("desconhecido");
    expect(degenerada.tom).toBe("desconhecido");
    expect(semDeclaracao.texto).not.toBe(degenerada.texto);
    // O ramo comum continua convidando a declarar — a correção não pode custar esse convite.
    expect(semDeclaracao.texto).toContain("declare o saldo para eu conferir");
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
    const um = avisoTotalParcial(report({ contas_sem_checkpoint: 1 }));
    expect(um).toContain("1 conta não foi avaliada");
    const dois = avisoTotalParcial(report({ contas_sem_checkpoint: 2 }));
    expect(dois).toContain("2 contas não foram avaliadas");
    expect(dois).toContain("ficaram de fora");
  });

  it("Story 8.20 — o aviso NÃO afirma o motivo: 'sem saldo informado' seria falso", () => {
    // Existem dois motivos para uma conta ficar de fora do total (nenhum saldo informado × saldo
    // informado na data de abertura). O agregado não sabe qual é — afirmar um deles moveria a
    // mentira de lugar em vez de removê-la. O motivo está na nota de cada conta.
    for (const n of [1, 2, 7]) {
      const aviso = avisoTotalParcial(report({ contas_sem_checkpoint: n })) ?? "";
      expect(aviso).not.toContain("sem saldo informado");
      expect(aviso).not.toContain("sem saldo declarado");
      expect(aviso).toContain("não cobre todas as suas contas");
    }
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

describe("UX-001 — os dois lados da conferência têm nomes distintos e NÃO confundíveis", () => {
  /**
   * O defeito que este bloco existe para impedir: a tela chamava o checkpoint de "Saldo no banco"
   * enquanto a Projeção chama de "no banco" (`ROTULO_BANCO`) o saldo DERIVADO — as duas pontas
   * exatas desta subtração, com a mesma palavra. Não basta os rótulos serem outros: eles precisam
   * continuar sendo *impossíveis de trocar um pelo outro*, e é isso que se afere aqui.
   */
  it("o par nomeia QUEM afirma cada número, e os dois nomes são diferentes", () => {
    expect(LADO_BANCO_LABEL).toBe("O que o banco diz");
    expect(LADO_E1P_LABEL).toBe("O que o e1p calculou");
    expect(LADO_BANCO_LABEL).not.toBe(LADO_E1P_LABEL);
    // Nem por substring: "Saldo" × "Saldo no banco" seriam "diferentes" e ainda assim confundíveis.
    expect(LADO_BANCO_LABEL).not.toContain(LADO_E1P_LABEL);
    expect(LADO_E1P_LABEL).not.toContain(LADO_BANCO_LABEL);
    // O verbo é o que carrega a diferença conceitual — afirmação externa × derivação interna.
    expect(LADO_BANCO_LABEL.toLowerCase()).toContain("diz");
    expect(LADO_E1P_LABEL.toLowerCase()).toContain("calcul");
  });

  it("⚠️ o lado do e1p NUNCA se chama 'banco' — foi essa metade que produziu o defeito", () => {
    expect(LADO_E1P_LABEL.toLowerCase()).not.toContain("banco");
    expect(LADO_E1P_LABEL.toLowerCase()).toContain("e1p");
  });

  it("⚠️ o lado do banco NUNCA fala em cálculo — é o número que o e1p não produziu", () => {
    expect(LADO_BANCO_LABEL.toLowerCase()).not.toMatch(/calcul|deriv|e1p|sistema/);
    expect(LADO_BANCO_LABEL.toLowerCase()).toContain("banco");
  });

  it("nenhum dos dois colide com os rótulos de saldo que já vivem em outras telas", () => {
    // Projeção ("no banco") e Contas & Saldos (os dois recortes da D-6). Um rótulo novo que
    // repetisse qualquer um deles seria a mesma classe de defeito noutra dupla de telas.
    for (const lado of [LADO_BANCO_LABEL, LADO_E1P_LABEL, LADOS_GRUPO_LABEL]) {
      for (const outro of [ROTULO_BANCO, TOTAL_EM_CONTAS_LABEL, DISPONIVEL_CAIXA_LABEL]) {
        expect(lado).not.toBe(outro);
        expect(lado.toLowerCase()).not.toContain(outro.toLowerCase());
      }
    }
  });

  it("`ROTULO_BANCO` segue sendo SÓ o da Projeção — a correção foi do lado da Conferência", () => {
    // Decisão registrada em `projecao.ts`: renomear a parcela da Projeção trocaria uma colisão por
    // outra (ela encostaria em "Total em contas"/"Disponível como caixa"). O que impede a volta do
    // defeito é esta invariante — "no banco" ter UM consumidor só.
    expect(ROTULO_BANCO).toBe("no banco");
    expect(`${LADO_BANCO_LABEL}|${LADO_E1P_LABEL}|${LADOS_GRUPO_LABEL}`).not.toContain(
      ROTULO_BANCO,
    );
  });

  it("a prosa usa o MESMO par das colunas — e nenhum dos quatro casos repete a colisão", () => {
    const casos = [
      conta({ divergencia_cents: -234_000, dentro_da_tolerancia: false }),
      conta({ divergencia_cents: 120_000, dentro_da_tolerancia: false }),
      conta({ divergencia_cents: 0, dentro_da_tolerancia: true }),
      conta({ divergencia_cents: null, dentro_da_tolerancia: null }),
    ];
    for (const c of casos) expect(fraseConferencia(c).texto).not.toContain(ROTULO_BANCO);
    // E os dois casos que comparam de fato nomeiam os dois lados, sem inverter os papéis.
    for (const c of casos.slice(0, 2)) {
      const texto = fraseConferencia(c).texto;
      expect(texto).toContain("O banco diz");
      expect(texto).toContain("eu calculei");
      expect(texto.indexOf("O banco diz")).toBeLessThan(texto.indexOf("eu calculei"));
    }
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

describe("Story 8.16 — as notas do bloco 4: a tela ANOTA, nunca recalcula", () => {
  const comTermos = report({
    contas: [conta({ divergencia_cents: 70_000, dentro_da_tolerancia: false })],
    total_divergencia_cents: 70_000,
    contas_avaliadas: 1,
    lancamentos_sem_conta_informada: 7,
    valor_sem_conta_informada_cents: 312_000,
    rendimentos_sem_perna_bancaria: 3,
    valor_rendimentos_sem_perna_cents: 48_000,
    notes: [
      "7 lançamentos deste período não informam de qual conta saiu ou entrou (R$ 3.120,00). A divergência abaixo **inclui** esse valor. Este termo fecha na Onda 2: assim que todo lançamento informar a conta, ele vai a zero sozinho.",
      "3 rendimentos de aplicação deste período (R$ 480,00) ainda não geram movimento bancário. A divergência abaixo **inclui** esse valor. Este termo só fecha na Onda 2b — não há o que corrigir à mão.",
    ],
  });

  it("a frase da conta é IDÊNTICA com e sem os termos do gate (ANOTA, NUNCA SUBTRAI)", () => {
    // Descontar o termo conhecido da divergência seria o checkpoint corrigindo o saldo derivado
    // com outra roupa: a divergência iria a zero por construção sempre que o sistema soubesse
    // explicar a diferença, e a métrica primária do épico morreria (Regra 5 do CLAUDE.md).
    const semTermos = report({
      contas: comTermos.contas,
      total_divergencia_cents: 70_000,
      contas_avaliadas: 1,
    });
    expect(semTermos.lancamentos_sem_conta_informada).toBe(0);
    expect(fraseConferencia(comTermos.contas[0])).toEqual(
      fraseConferencia(semTermos.contas[0]),
    );
    expect(comTermos.total_divergencia_cents).toBe(semTermos.total_divergencia_cents);
    expect(comTermos.contas_fora_da_banda).toEqual(semTermos.contas_fora_da_banda);
  });

  it("o aviso de total parcial não conhece os termos do gate", () => {
    // `avisoTotalParcial` fala de CONTAS não avaliadas; os termos do gate falam de LANÇAMENTOS sem
    // conta informada. Misturar as duas frases faria a tela dizer que o total é parcial por um
    // motivo que não é o dele.
    expect(avisoTotalParcial(comTermos)).toBeNull();
  });

  it("as notas do backend chegam prontas — a tela não monta frase nenhuma", () => {
    // Uma redação, um lugar (o mesmo bloco de `_NOTE_SEM_CHECKPOINT`, no backend). Duas redações
    // do mesmo fato viram duas frases diferentes conforme o caminho.
    expect(comTermos.notes).toHaveLength(2);
    expect(comTermos.notes[0]).toContain("Onda 2:");
    expect(comTermos.notes[1]).toContain("Onda 2b");
  });

  it("cada nota nomeia a ONDA que a fecha, e elas são diferentes", () => {
    // P1/P2 somem quando o dono terminar de corrigir os lançamentos; P3 NÃO some nesta onda. Uma
    // nota que promete "isso some quando você terminar o mutirão" sobre um termo que não some é a
    // mesma afirmação sem lastro que a Onda 0 removeu da Projeção.
    expect(comTermos.notes[0]).not.toContain("Onda 2b");
    expect(comTermos.notes[1]).toContain("não há o que corrigir à mão");
  });

  it("UX-001: as notas novas não reusam 'no banco' nem os rótulos de saldo vizinhos", () => {
    const texto = comTermos.notes.join(" ").toLowerCase();
    expect(texto).not.toContain(ROTULO_BANCO.toLowerCase());
    expect(texto).not.toContain(TOTAL_EM_CONTAS_LABEL.toLowerCase());
    expect(texto).not.toContain(DISPONIVEL_CAIXA_LABEL.toLowerCase());
  });

  it("zero termo não-zero ⇒ zero nota (o silêncio que diz 'o gate pode ser lido')", () => {
    const limpo = report({ contas: [conta()], contas_avaliadas: 1 });
    expect(limpo.notes).toEqual([]);
    expect(limpo.lancamentos_sem_conta_informada).toBe(0);
    expect(limpo.rendimentos_sem_perna_bancaria).toBe(0);
  });
});
