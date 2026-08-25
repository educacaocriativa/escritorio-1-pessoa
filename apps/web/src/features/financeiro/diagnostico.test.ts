import { describe, expect, it } from "vitest";
import {
  completudeCaveat,
  completudeLevel,
  countByLevel,
  monthRange,
  type Signal,
  signalVisual,
  sourceLabel,
} from "./diagnostico";

/**
 * Smoke test da lógica pura do diagnóstico financeiro (Story 5.8). O projeto não tem infra de teste
 * de componente React — os testes de front são de lógica pura (ver projecao.test.ts / dre.test.ts).
 * Cobre a config visual por nível, a contagem por nível e o range de mês.
 */
const sig = (level: Signal["level"], source = "projecao"): Signal => ({
  level,
  title: "t",
  explanation: "e",
  source,
});

describe("signalVisual", () => {
  it("mapeia cada nível para emoji e rótulo", () => {
    expect(signalVisual("vermelho").emoji).toBe("🔴");
    expect(signalVisual("amarelo").label).toBe("Atenção");
    expect(signalVisual("verde").emoji).toBe("🟢");
  });
});

describe("countByLevel", () => {
  it("conta sinais por nível", () => {
    const counts = countByLevel([sig("vermelho"), sig("vermelho"), sig("amarelo")]);
    expect(counts).toEqual({ vermelho: 2, amarelo: 1, verde: 0 });
  });

  it("retorna tudo zero para lista vazia", () => {
    expect(countByLevel([])).toEqual({ vermelho: 0, amarelo: 0, verde: 0 });
  });
});

describe("sourceLabel", () => {
  it("traduz as origens conhecidas e devolve o cru para desconhecidas", () => {
    expect(sourceLabel("lucratividade")).toBe("Lucratividade por contrato");
    // Achado por mutação (#214): `projecao` era a única origem do `switch` que NENHUM teste
    // afirmava. Apagar o corpo do `case` faz ele CAIR no case seguinte — e a projeção de caixa
    // passa a se chamar "Investimentos" na tela do diagnóstico, sem nada quebrar.
    expect(sourceLabel("projecao")).toBe("Projeção de caixa");
    expect(sourceLabel("investimento")).toBe("Investimentos");
    expect(sourceLabel("desconhecido")).toBe("desconhecido");
  });

  it("rotula a origem 'completude' (Story 8.6)", () => {
    expect(sourceLabel("completude")).toBe("Completude dos lançamentos");
  });
});

/**
 * Story 8.6 — a ressalva de precedência semântica. A regra que ela representa: se o sistema não
 * sabe se os lançamentos estão completos, qualquer afirmação sobre margem/runway/rentabilidade é
 * feita sobre base possivelmente furada, e o usuário precisa ler isso ANTES dos números.
 */
describe("completudeLevel", () => {
  it("devolve o pior nível entre os sinais de completude", () => {
    expect(
      completudeLevel([sig("amarelo", "completude"), sig("vermelho", "completude")]),
    ).toBe("vermelho");
    expect(completudeLevel([sig("verde", "completude"), sig("amarelo", "completude")])).toBe(
      "amarelo",
    );
    expect(completudeLevel([sig("verde", "completude")])).toBe("verde");
  });

  it("ignora sinais de outras origens", () => {
    expect(completudeLevel([sig("vermelho", "projecao"), sig("amarelo", "lucratividade")])).toBe(
      null,
    );
    expect(completudeLevel([])).toBe(null);
  });
});

describe("completudeCaveat", () => {
  it("avisa quando a completude está 🔴", () => {
    const texto = completudeCaveat([sig("vermelho", "completude"), sig("verde", "projecao")]);
    expect(texto).toContain("possivelmente incompletos");
    expect(texto).toContain("divergência acima da tolerância");
  });

  it("avisa quando a completude está 🟡", () => {
    const texto = completudeCaveat([sig("amarelo", "completude")]);
    expect(texto).toContain("possivelmente incompletos");
    // Achado por mutação (#214): "possivelmente incompletos" é a metade COMUM aos dois textos,
    // então fixar `level === "vermelho"` em `true` passava neste teste — o 🟡 exibia a redação do
    // 🔴 ("divergência acima da tolerância", uma afirmação de fato) sem ninguém perceber. O que
    // separa os dois estados é justamente a abertura.
    expect(texto).toContain("Ainda não dá para afirmar");
    expect(texto).not.toContain("divergência acima da tolerância");
  });

  it("cala quando a completude está 🟢 ou ausente", () => {
    expect(completudeCaveat([sig("verde", "completude")])).toBe(null);
    // Um 🔴 de OUTRA origem não gera a ressalva: ela é sobre confiar nos dados, não sobre gravidade.
    expect(completudeCaveat([sig("vermelho", "projecao")])).toBe(null);
    expect(completudeCaveat([])).toBe(null);
  });
});

describe("monthRange", () => {
  it("calcula o primeiro e último dia do mês", () => {
    expect(monthRange("2026-02")).toEqual({ start: "2026-02-01", end: "2026-02-28" });
    expect(monthRange("2026-07")).toEqual({ start: "2026-07-01", end: "2026-07-31" });
  });
});

describe("Story 8.16 — os rótulos das duas regras da Onda 2", () => {
  it("traduz `recebimento_externo` e `debito_nao_confirmado`", () => {
    expect(sourceLabel("recebimento_externo")).toBe("Recebimentos");
    expect(sourceLabel("debito_nao_confirmado")).toBe("Saídas");
  });

  it('NUNCA rotula a saída como "Agendamentos" (ratificação §C-2.3, ajuste 1)', () => {
    // Depois que o worker promove `scheduled → paid`, nada no dado distingue "agendei e o banco
    // não executou" de "paguei no caixa e o banco não compensou". Um rótulo que promete um recorte
    // que o dado não sustenta é o defeito D-3 na superfície mais cara — a que o dono lê.
    const rotulo = sourceLabel("debito_nao_confirmado");
    expect(rotulo.toLowerCase()).not.toContain("agendad");
    expect(rotulo.toLowerCase()).not.toContain("agendament");
  });

  it("nenhum rótulo do diagnóstico usa jargão interno do épico", () => {
    // "trilho", "split" e "plataforma" são vocabulário de dentro do e1p. O sinal de recebimento
    // fora da cobrança é, no estudo interno, vazamento de receita da plataforma — e mesmo assim
    // toda a redação é sobre o interesse do DONO (G-D7).
    const fontes = [
      "lucratividade",
      "projecao",
      "investimento",
      "completude",
      "recebimento_externo",
      "debito_nao_confirmado",
    ];
    for (const fonte of fontes) {
      const rotulo = sourceLabel(fonte).toLowerCase();
      for (const jargao of ["trilho", "split", "plataforma"]) {
        expect(rotulo).not.toContain(jargao);
      }
    }
  });

  it("não inventa rótulo para `source` desconhecido — devolve o próprio", () => {
    expect(sourceLabel("fonte_que_ainda_nao_existe")).toBe("fonte_que_ainda_nao_existe");
  });

  it("a ressalva de precedência continua sendo SÓ da completude", () => {
    // As duas regras novas são 🟡 e falam da mesma base de dados, mas NÃO geram a ressalva: ela é
    // a afirmação "não confio nos outros sinais até você fechar isto", e essa é da completude.
    expect(completudeCaveat([sig("amarelo", "recebimento_externo")])).toBe(null);
    expect(completudeCaveat([sig("amarelo", "debito_nao_confirmado")])).toBe(null);
    expect(completudeLevel([sig("amarelo", "debito_nao_confirmado")])).toBe(null);
  });
});
