import { describe, expect, it } from "vitest";
import {
  ACAO_CADASTRAR_CONTA,
  ALTURA_DA_BARRA,
  acaoCadastrarConta,
  avisoDeDataFutura,
  type ContaDeBaixa,
  contaPreSelecionada,
  contasUtilizaveis,
  GAP_ENTRE_CAMPOS,
  larguraDoCampo,
  LARGURA_MINIMA_DO_CAMPO,
  nomeDaConta,
  PADDING_DA_BARRA,
  PADDING_INFERIOR_DA_PAGINA,
  rotuloDaAcao,
  tetoDaDataDeBaixa,
  VIEWPORT_ALVO,
} from "./baixa";

/** Story 8.13 — a lógica PURA compartilhada pelas três telas de baixa. */

function conta(over: Partial<ContaDeBaixa> = {}): ContaDeBaixa {
  return { id: "c-1", name: "Itaú PJ", is_primary: false, archived_at: null, ...over };
}

describe("o 409 acionável é reconhecido pela AÇÃO, nunca pela mensagem", () => {
  const erro = (detail: unknown) => ({ response: { data: { detail } } });

  it("reconhece o 409 acionável e devolve a mensagem do backend", () => {
    const r = acaoCadastrarConta(
      erro({ acao: ACAO_CADASTRAR_CONTA, mensagem: "Cadastre a sua conta bancária." }),
    );
    expect(r).toEqual({ mensagem: "Cadastre a sua conta bancária." });
  });

  it("reconhece as DUAS situações que compartilham a ação (sem conta / conta arquivada)", () => {
    // O contrato é `acao`; a frase muda conforme o caso, e é por isso que a tela não pode
    // reconhecer a situação por substring.
    const arquivada = acaoCadastrarConta(
      erro({ acao: ACAO_CADASTRAR_CONTA, mensagem: "A conta escolhida está arquivada." }),
    );
    expect(arquivada?.mensagem).toContain("arquivada");
  });

  it("NÃO confunde com outros erros: 422 do Pydantic, 404 em string, rede", () => {
    expect(acaoCadastrarConta(erro([{ loc: ["body"], msg: "campo", type: "x" }]))).toBeNull();
    expect(acaoCadastrarConta(erro("Conta não encontrada"))).toBeNull();
    expect(acaoCadastrarConta(erro({ acao: "outra_coisa", mensagem: "x" }))).toBeNull();
    expect(acaoCadastrarConta(new Error("Network Error"))).toBeNull();
    expect(acaoCadastrarConta(undefined)).toBeNull();
  });
});

describe("pré-seleção da conta", () => {
  it("pré-seleciona a conta PRIMÁRIA", () => {
    const contas = [conta({ id: "a" }), conta({ id: "b", is_primary: true })];
    expect(contaPreSelecionada(contas)).toBe("b");
  });

  it("⚠️ SEM primária, nada é pré-selecionado — nem 'a primeira', nem 'a única'", () => {
    // Estado válido: é onde o tenant fica ao arquivar a primária. Escolher por ele o destino do
    // dinheiro é o tipo de "ajuda" que só se descobre quando o dinheiro já foi para o lugar errado.
    expect(contaPreSelecionada([conta({ id: "a" })])).toBe("");
    expect(contaPreSelecionada([conta({ id: "a" }), conta({ id: "b" })])).toBe("");
    expect(contaPreSelecionada([])).toBe("");
  });

  it("conta ARQUIVADA não é pré-selecionada nem entra na lista utilizável", () => {
    const arquivada = conta({ id: "z", is_primary: true, archived_at: "2026-05-01T00:00:00Z" });
    expect(contaPreSelecionada([arquivada])).toBe("");
    expect(contasUtilizaveis([arquivada, conta({ id: "a" })]).map((c) => c.id)).toEqual(["a"]);
  });
});

describe("o nome da conta fica legível SEM interação adicional (AC5)", () => {
  it("o rótulo da ação diz para onde o dinheiro está indo", () => {
    expect(rotuloDaAcao("Anexar e dar baixa", "Itaú PJ")).toBe("Anexar e dar baixa · sai do Itaú PJ");
  });

  it("sem conta escolhida, o rótulo não inventa um destino", () => {
    expect(rotuloDaAcao("Anexar e dar baixa", "")).toBe("Anexar e dar baixa");
    expect(nomeDaConta([conta({ id: "a" })], "inexistente")).toBe("");
  });
});

describe("a data da baixa", () => {
  it("⚠️ [8.14] NÃO existe mais teto — `tetoDaDataDeBaixa` devolve `undefined`", () => {
    // **Mudança de expectativa, e ela é a CORREÇÃO.** Este teste afirmava `toBe("2026-07-30")` e
    // se chamava "o teto é HOJE — e sai na Story 8.14". A 8.14 chegou: o estado `scheduled` existe
    // e a data futura passou a ser um registro legítimo (débito agendado no app do banco), não um
    // erro de digitação. `undefined` (e não `""`) porque é assim que o React OMITE o atributo
    // `max` do `<input>` — com string vazia o atributo seria renderizado vazio.
    expect(tetoDaDataDeBaixa("2026-07-30")).toBeUndefined();
  });

  it("avisa (sem bloquear) quando a data é futura — e a frase agora CONFIRMA o agendamento", () => {
    // A frase antiga dizia "pagamento agendado ainda não é acompanhado pelo e1p" — verdade até a
    // 8.13, MENTIRA a partir daqui. Deixá-la seria pior que não avisar: mandaria o dono desfazer
    // exatamente o que o produto passou a fazer certo.
    const aviso = avisoDeDataFutura("2026-08-15", "2026-07-30");
    expect(aviso).toMatch(/agendada/i);
    expect(aviso).toMatch(/ainda não saiu/i);
    expect(aviso).not.toMatch(/não é acompanhado/i);
  });

  it("hoje NÃO dispara o aviso — a borda é `>`, e hoje é uma data legítima de baixa", () => {
    expect(avisoDeDataFutura("2026-07-30", "2026-07-30")).toBeNull();
    expect(avisoDeDataFutura("2026-07-29", "2026-07-30")).toBeNull();
    expect(avisoDeDataFutura("", "2026-07-30")).toBeNull();
  });
});

/**
 * **Auditoria estrutural de ~360px (AC9).**
 *
 * jsdom não faz layout, então o que dá para provar aqui é a ARITMÉTICA — e é ela que regride numa
 * mudança de estilo. O laço com o DOM real (as classes que alimentam estes números) é fechado em
 * `ComprovantePage.test.tsx`, que lê o `className` da barra fixa.
 */
describe("geometria da barra fixa em 360px", () => {
  it("os dois campos cabem lado a lado na largura alvo", () => {
    const largura = larguraDoCampo(VIEWPORT_ALVO, 2);
    // (360 − 16×2 − 8) ÷ 2 = 160
    expect(largura).toBe(160);
    expect(largura).toBeGreaterThanOrEqual(LARGURA_MINIMA_DO_CAMPO);
  });

  it("TRÊS colunas NÃO caberiam — é por isso que o resumo/checkbox fica em outra linha", () => {
    expect(larguraDoCampo(VIEWPORT_ALVO, 3)).toBeLessThan(LARGURA_MINIMA_DO_CAMPO);
  });

  it("a barra inteira cabe na viewport e ainda sobra tela para a lista", () => {
    // 640px é a altura CSS típica do aparelho de 360px de largura (Moto E / Galaxy A0x).
    expect(ALTURA_DA_BARRA).toBeLessThan(640 / 2);
  });

  it("⚠️ o padding inferior da página é MAIOR que a barra: o último cartão não fica embaixo dela", () => {
    // A ponta oposta do defeito do PR #58: lá o checkbox ficava acima da dobra; aqui o risco é a
    // barra (que cresceu com o seletor) tapar o fim da lista.
    expect(PADDING_INFERIOR_DA_PAGINA).toBeGreaterThanOrEqual(ALTURA_DA_BARRA);
  });

  it("as constantes correspondem às classes Tailwind usadas (p-4 / gap-2)", () => {
    expect(PADDING_DA_BARRA).toBe(16); // p-4
    expect(GAP_ENTRE_CAMPOS).toBe(8); // gap-2
  });
});
