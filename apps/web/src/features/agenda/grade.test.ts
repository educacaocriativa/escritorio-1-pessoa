import { describe, expect, it } from "vitest";
import { formatTime, localYmd, today } from "../../lib/datetime";
import {
  HORA_ABERTURA,
  HORA_FECHAMENTO,
  WEEKDAYS,
  addDays,
  densidadePorDia,
  eventYmd,
  eventosDoDia,
  eventsOfDay,
  faixasLivres,
  gradeDoMes,
  hojeDoTenant,
  instanteNoFuso,
  paramsDaGrade,
  sameDay,
  startOfDay,
  startOfWeek,
} from "./grade";
import { agendaEvent as evento } from "../../test/fixtures/agenda";

const FUSO = "America/Sao_Paulo"; // UTC−3: 12:00Z = 09:00 na tela

// ⚠️ O `vitest.config.ts` fixa `TZ: "America/Sao_Paulo"` para a suíte inteira. Enquanto o fuso do
// TENANT nos testes for esse mesmo, ler o instante pelo fuso do tenant e lê-lo pelas partes locais
// do `Date` produz o MESMO resultado — e um teste chamado "agrupa pelo fuso do tenant" passa mesmo
// com a produção lendo o fuso do NAVEGADOR. É a família do `toContain("flex-wrap")` que o CLAUDE.md
// §5.1 documenta: asserção estruturalmente incapaz de falhar.
// Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner: sob ele os dois caminhos
// discordam, e é por isso que os testes deste fuso existem.
const FUSO_DISTANTE = "Asia/Tokyo";



// Sábado 10/10/2026 — o dia que o dono clicou na grade.
const DIA = new Date(2026, 9, 10);
// Um "agora" bem distante do DIA, para que o corte do passado não interfira nos casos que não
// são sobre ele.
const ONTEM = new Date("2026-10-01T12:00:00Z");

const horas = (fx: { hora: number }[]) => fx.map((f) => f.hora);

describe("eventosDoDia", () => {
  it("agrupa pelo dia do TENANT, não pelo do navegador", () => {
    // 02:00Z de 11/10 ainda é 23:00 de 10/10 em UTC−3 — o compromisso é da noite de sábado.
    const noturno = evento({ starts_at: "2026-10-11T02:00:00Z", ends_at: "2026-10-11T03:00:00Z" });

    expect(eventosDoDia([noturno], DIA, FUSO)).toHaveLength(1);
    expect(eventosDoDia([noturno], new Date(2026, 9, 11), FUSO)).toHaveLength(0);
  });

  it("usa o fuso do tenant mesmo quando ele discorda do fuso da MÁQUINA", () => {
    // 23:00Z de 10/10 é 08:00 de 11/10 em Tóquio e 20:00 de 10/10 em São Paulo (o fuso do runner).
    // Só quem lê pelo fuso do TENANT põe este compromisso no dia 11.
    const e = evento({ starts_at: "2026-10-10T23:00:00Z", ends_at: "2026-10-11T00:00:00Z" });

    expect(eventosDoDia([e], new Date(2026, 9, 11), FUSO_DISTANTE)).toHaveLength(1);
    expect(eventosDoDia([e], DIA, FUSO_DISTANTE)).toHaveLength(0);
  });

  it("mantém o de dia inteiro na data de calendário dele, sem fuso", () => {
    const cobranca = evento({
      kind: "cobranca_receber",
      all_day: true,
      starts_at: "2026-10-10T00:00:00Z",
      ends_at: "2026-10-10T23:59:00Z",
    });

    expect(eventosDoDia([cobranca], DIA, FUSO)).toHaveLength(1);
  });

  it("ordena do mais cedo para o mais tarde", () => {
    const tarde = evento({ id: "tarde", starts_at: "2026-10-10T18:00:00Z", ends_at: "2026-10-10T19:00:00Z" });
    const cedo = evento({ id: "cedo", starts_at: "2026-10-10T12:00:00Z", ends_at: "2026-10-10T13:00:00Z" });

    expect(eventosDoDia([tarde, cedo], DIA, FUSO).map((e) => e.id)).toEqual(["cedo", "tarde"]);
  });
});

describe("faixasLivres", () => {
  it("oferece a janela inteira de 08h a 18h quando o dia está vazio", () => {
    const fx = faixasLivres([], DIA, FUSO, ONTEM);

    expect(horas(fx)).toEqual([8, 9, 10, 11, 12, 13, 14, 15, 16, 17]);
    expect(fx[0]).toMatchObject({ inicio: "08:00", fim: "09:00" });
    expect(fx[9]).toMatchObject({ inicio: "17:00", fim: "18:00" });
  });

  it("esconde a faixa tomada por um compromisso do dia", () => {
    // 12:00Z–13:00Z = 09:00–10:00 no fuso do tenant.
    const fx = faixasLivres([evento()], DIA, FUSO, ONTEM);

    expect(horas(fx)).not.toContain(9);
    expect(horas(fx)).toContain(8);
    expect(horas(fx)).toContain(10);
  });

  it("derruba as duas faixas que um compromisso atravessa pela metade", () => {
    // 09:30–10:30 encosta em 09h e em 10h: nenhuma das duas cabe inteira.
    const fx = faixasLivres(
      [evento({ starts_at: "2026-10-10T12:30:00Z", ends_at: "2026-10-10T13:30:00Z" })],
      DIA,
      FUSO,
      ONTEM,
    );

    expect(horas(fx)).not.toContain(9);
    expect(horas(fx)).not.toContain(10);
    expect(horas(fx)).toContain(11);
  });

  it("não deixa um compromisso de dia inteiro travar o dia", () => {
    // Cobrança, conta a pagar e prazo são TODOS `all_day`. Se ocupassem, todo dia com uma
    // parcela vencendo apareceria cheio — o oposto do que este seletor existe para mostrar.
    const fx = faixasLivres(
      [evento({ kind: "cobranca_receber", all_day: true, starts_at: "2026-10-10T00:00:00Z", ends_at: "2026-10-10T23:59:00Z" })],
      DIA,
      FUSO,
      ONTEM,
    );

    expect(horas(fx)).toHaveLength(10);
  });

  it("não deixa um compromisso cancelado travar a faixa", () => {
    const fx = faixasLivres([evento({ status: "cancelled" })], DIA, FUSO, ONTEM);

    expect(horas(fx)).toContain(9);
  });

  it("ignora compromisso de outro dia", () => {
    const fx = faixasLivres(
      [evento({ starts_at: "2026-10-11T12:00:00Z", ends_at: "2026-10-11T13:00:00Z" })],
      DIA,
      FUSO,
      ONTEM,
    );

    expect(horas(fx)).toHaveLength(10);
  });

  it("no dia de hoje, some a faixa que já começou", () => {
    // 17:30Z = 14:30 no fuso do tenant: 14h já correu, 15h ainda dá.
    const agora = new Date("2026-10-10T17:30:00Z");

    const fx = faixasLivres([], DIA, FUSO, agora);

    expect(horas(fx)).toEqual([15, 16, 17]);
  });

  it("marca a hora pelo fuso do tenant, não pelas partes locais do Date", () => {
    // Em Tóquio o compromisso é das 08:00 às 09:00 do dia 11; em São Paulo (fuso do runner) ele
    // seria 20:00 do dia 10. Ler pelas partes locais do `Date` não derrubaria a faixa das 08h.
    const fx = faixasLivres(
      [evento({ starts_at: "2026-10-10T23:00:00Z", ends_at: "2026-10-11T00:00:00Z" })],
      new Date(2026, 9, 11),
      FUSO_DISTANTE,
      ONTEM,
    );

    expect(horas(fx)).not.toContain(8);
    expect(horas(fx)).toContain(9);
  });

  it("o compromisso que atravessa a meia-noite ocupa a manhã do dia seguinte", () => {
    // 22:00 do dia 10 até 09:00 do dia 11, no fuso do tenant. O plantão acabou às 9h: as 08h do
    // dia 11 estão TOMADAS, e oferecê-las é oferecer um choque.
    const virada = evento({ starts_at: "2026-10-11T01:00:00Z", ends_at: "2026-10-11T12:00:00Z" });

    const fx = faixasLivres([virada], new Date(2026, 9, 11), FUSO, ONTEM);

    expect(horas(fx)).not.toContain(8);
    expect(horas(fx)).toContain(9);
  });

  it("o compromisso que vara a noite ocupa até o fim do dia em que COMEÇOU", () => {
    // 14:00 do dia 10 até 09:00 do dia 11. O teste irmão (acima) usa 22:00, que está fora da
    // janela 08–18 e por isso não distingue "ocupa até a meia-noite" de "ocupa até o ends_at":
    // sem um caso DENTRO da janela, o ramo do dia de início passa sem prova.
    const virada = evento({ starts_at: "2026-10-10T17:00:00Z", ends_at: "2026-10-11T12:00:00Z" });

    const fx = faixasLivres([virada], DIA, FUSO, ONTEM);

    expect(horas(fx)).toEqual([8, 9, 10, 11, 12, 13]);
  });

  it("o compromisso de vários dias deixa o dia do MEIO inteiramente ocupado", () => {
    // Uma viagem do dia 9 ao dia 12, com horário. O dia 10 não é nem o começo nem o fim — sem o
    // ramo do meio ele apareceria 100% livre. Criável na tela: os dois `datetime-local` do
    // formulário não impedem intervalo de vários dias.
    const viagem = evento({ starts_at: "2026-10-09T15:00:00Z", ends_at: "2026-10-12T15:00:00Z" });

    expect(faixasLivres([viagem], DIA, FUSO, ONTEM)).toEqual([]);
  });

  it("na hora cheia exata, a faixa que começa AGORA já não é oferecida", () => {
    // Borda: às 14:00:00 em ponto a faixa das 14h não tem mais nem um minuto de antecedência.
    // O caso de 14:30 (acima) passa com `<` e com `<=`; só a hora cheia separa os dois.
    const fx = faixasLivres([], DIA, FUSO, new Date("2026-10-10T17:00:00Z"));

    expect(horas(fx)).toEqual([15, 16, 17]);
  });

  it("compromisso com horário ilegível não apaga o resto do dia", () => {
    // Inalcançável pela API (`ends_at` é NOT NULL e validado), e é justamente por isso que o
    // modo de falha importa: uma linha estranha não pode varrer nove faixas em silêncio. O
    // aviso de conflito do `NewEventModal` continua sendo a rede.
    const fx = faixasLivres([evento({ ends_at: "" })], DIA, FUSO, ONTEM);

    expect(horas(fx)).toHaveLength(10);
  });

  it("devolve vazio quando o dia está cheio de ponta a ponta", () => {
    const fx = faixasLivres(
      [evento({ starts_at: "2026-10-10T11:00:00Z", ends_at: "2026-10-10T21:00:00Z" })],
      DIA,
      FUSO,
      ONTEM,
    );

    expect(fx).toEqual([]);
  });
});

describe("densidadePorDia", () => {
  // Ela existe por CUSTO (substituiu uma varredura de 42x no grid) e alimenta as bolinhas que
  // dizem "tem coisa aqui" — o sinal que faz o dono escolher em que dia clicar. Sem estes testes
  // ela podia devolver um mapa vazio e a suite inteira continuava verde.
  it("conta por dia, no fuso do tenant", () => {
    const mapa = densidadePorDia(
      [
        evento(),
        evento({ id: "b", starts_at: "2026-10-10T18:00:00Z", ends_at: "2026-10-10T19:00:00Z" }),
        evento({ id: "c", starts_at: "2026-10-11T18:00:00Z", ends_at: "2026-10-11T19:00:00Z" }),
      ],
      FUSO,
    );

    expect(mapa.get("2026-10-10")).toBe(2);
    expect(mapa.get("2026-10-11")).toBe(1);
    expect(mapa.get("2026-10-12")).toBeUndefined();
  });

  it("concorda com eventosDoDia, inclusive quando o fuso do tenant discorda da MÁQUINA", () => {
    // 23:00Z do dia 10 é 08:00 do dia 11 em Tóquio. As bolinhas da grade e a lista do painel têm
    // de apontar para o MESMO dia — senão o dono clica no dia com bolinha e não acha nada lá.
    const e = evento({ starts_at: "2026-10-10T23:00:00Z", ends_at: "2026-10-11T00:00:00Z" });
    const onze = new Date(2026, 9, 11);

    expect(densidadePorDia([e], FUSO_DISTANTE).get("2026-10-11")).toBe(1);
    expect(densidadePorDia([e], FUSO_DISTANTE).get("2026-10-10")).toBeUndefined();
    expect(eventosDoDia([e], onze, FUSO_DISTANTE)).toHaveLength(1);
  });

  it("conta o de dia inteiro pela data de calendário dele", () => {
    const cobranca = evento({
      all_day: true,
      starts_at: "2026-10-10T00:00:00Z",
      ends_at: "2026-10-10T23:59:00Z",
    });

    expect(densidadePorDia([cobranca], FUSO).get("2026-10-10")).toBe(1);
  });
});

describe("instanteNoFuso", () => {
  it("resolve a hora de parede do tenant no instante certo", () => {
    // 14:00 em São Paulo (UTC−3) é 17:00Z. É este instante que vai para a API — e é por isso que
    // a faixa oferecida não pode virar uma string ingênua reinterpretada no fuso do NAVEGADOR.
    expect(instanteNoFuso(DIA, 14 * 60, FUSO).toISOString()).toBe("2026-10-10T17:00:00.000Z");
  });

  it("resolve a mesma hora de parede num fuso adiantado", () => {
    // 14:00 em Tóquio (UTC+9) é 05:00Z do MESMO dia.
    expect(instanteNoFuso(DIA, 14 * 60, FUSO_DISTANTE).toISOString()).toBe("2026-10-10T05:00:00.000Z");
  });

  it("acerta o instante do outro lado de uma virada de horário de verão", () => {
    // ⚠️ A zona e a data NÃO são intercambiáveis, e a primeira versão deste teste era decorativa:
    // com `America/New_York` em 01/11 a transição (06:00Z) cai ANTES da parede das 14:00Z, então
    // a primeira aproximação já acerta e a segunda passada nunca é exercitada — uma implementação
    // de passada única passava neste teste.
    // Sydney (a LESTE de Greenwich) em 04/04/2026 é o caso que separa as duas: 16:00 locais são
    // 05:00Z, e a conta de uma passada só devolveria 06:00Z (17:00 na tela).
    expect(instanteNoFuso(new Date(2026, 3, 4), 16 * 60, "Australia/Sydney").toISOString()).toBe(
      "2026-04-04T05:00:00.000Z",
    );
    // A virada de outubro, no sentido oposto.
    expect(instanteNoFuso(new Date(2026, 9, 3), 17 * 60, "Australia/Sydney").toISOString()).toBe(
      "2026-10-03T07:00:00.000Z",
    );
    // E o caso original, que continua valendo como não-membro (acerta com uma ou duas passadas).
    expect(instanteNoFuso(new Date(2026, 10, 1), 14 * 60, "America/New_York").toISOString()).toBe(
      "2026-11-01T19:00:00.000Z",
    );
  });

  it("a hora de parede volta a ser a MESMA hora quando lida no fuso do tenant", () => {
    // O invariante que amarra `instanteNoFuso` ao resto: o que sai tem de ser lido de volta como a
    // hora que entrou. Varre zonas com e sem horário de verão, dos dois lados de Greenwich, em
    // datas de virada — é o que impediria uma implementação de offset que dependa do fuso da
    // MÁQUINA de passar despercebida sob um runner sem horário de verão.
    const zonas = [
      "America/Sao_Paulo",
      "Asia/Tokyo",
      "Australia/Sydney",
      "Pacific/Auckland",
      "America/New_York",
      "Europe/Lisbon",
      "Asia/Kathmandu",
    ];
    const dias = [new Date(2026, 3, 4), new Date(2026, 9, 3), new Date(2026, 10, 1), new Date(2026, 5, 15)];

    for (const zona of zonas) {
      for (const dia of dias) {
        for (let h = HORA_ABERTURA; h < HORA_FECHAMENTO; h++) {
          const lido = formatTime(instanteNoFuso(dia, h * 60, zona).toISOString(), zona);
          expect(`${zona} ${localYmd(dia)} ${h}h -> ${lido}`).toBe(
            `${zona} ${localYmd(dia)} ${h}h -> ${String(h).padStart(2, "0")}:00`,
          );
        }
      }
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// A aritmética da GRADE — achada pelo teste de mutação (issue #121).
//
// Antes desta data, `grade.test.ts` importava seis símbolos e a metade "posições na grade" do
// módulo (`startOfDay`, `addDays`, `startOfWeek`, `sameDay`, `hojeDoTenant`, `gradeDoMes`,
// `eventYmd`, `eventsOfDay`, `paramsDaGrade`, `WEEKDAYS`) não tinha NENHUM teste dedicado: 28
// mutantes sem cobertura. Passavam pelos testes de `AgendaPage.tsx` de raspão — o suficiente para
// a suíte ficar verde, não para alguém perceber que trocar `+ n` por `- n` em `addDays` não
// quebra nada.
//
// A ironia é que o docstring do módulo diz, com todas as letras, POR QUE essa aritmética foi
// extraída: "duplicar `startOfWeek`/`addDays` em dois lugares é como um dos dois calendários
// acaba começando a semana num dia diferente do outro". A regra estava escrita; o teste que a
// segura, não.
// ─────────────────────────────────────────────────────────────────────────────

// 10/10/2026 é um SÁBADO (getDay() === 6). Toda a aritmética abaixo depende disso.
const SABADO = new Date(2026, 9, 10, 15, 47, 33, 456);

describe("posições na grade", () => {
  it("startOfDay zera a hora e mantém o dia", () => {
    const zerado = startOfDay(SABADO);

    expect(localYmd(zerado)).toBe("2026-10-10");
    expect([zerado.getHours(), zerado.getMinutes(), zerado.getSeconds(), zerado.getMilliseconds()]).toEqual([
      0, 0, 0, 0,
    ]);
  });

  it("addDays anda para FRENTE com n positivo e para trás com n negativo", () => {
    // Direção e magnitude no mesmo teste: `+ n` → `- n` erra a direção, e um `setTime` no lugar
    // do `setDate` joga a data para 1970 — ambos morrem aqui.
    expect(localYmd(addDays(SABADO, 5))).toBe("2026-10-15");
    expect(localYmd(addDays(SABADO, -3))).toBe("2026-10-07");
    expect(localYmd(addDays(SABADO, 0))).toBe("2026-10-10");
  });

  it("addDays atravessa a virada do mês e do ano", () => {
    expect(localYmd(addDays(new Date(2026, 9, 31), 1))).toBe("2026-11-01");
    expect(localYmd(addDays(new Date(2026, 11, 31), 1))).toBe("2027-01-01");
    expect(localYmd(addDays(new Date(2027, 0, 1), -1))).toBe("2026-12-31");
  });

  it("startOfWeek volta ao DOMINGO anterior — nunca avança", () => {
    // O comentário do módulo é "semana começa no domingo". Sábado 10/10 pertence à semana que
    // abriu no domingo 04/10; sem o sinal negativo o cálculo pula para 16/10 — uma semana que
    // ainda não começou.
    expect(localYmd(startOfWeek(SABADO))).toBe("2026-10-04");
    // Domingo é ponto fixo: já é o começo da própria semana.
    const domingo = new Date(2026, 9, 4);
    expect(localYmd(startOfWeek(domingo))).toBe("2026-10-04");
  });

  it("sameDay ignora a hora e distingue dias vizinhos", () => {
    expect(sameDay(SABADO, new Date(2026, 9, 10, 0, 0, 0))).toBe(true);
    expect(sameDay(SABADO, new Date(2026, 9, 11))).toBe(false);
    expect(sameDay(SABADO, new Date(2026, 9, 9))).toBe(false);
  });

  it("WEEKDAYS está alinhado ao índice de `getDay()`", () => {
    // A asserção que importa não é "o array contém Dom..Sáb" e sim que a POSIÇÃO de cada rótulo
    // bate com o índice que o `Date` devolve: uma rotação de uma casa deixaria o cabeçalho do
    // calendário inteiro deslocado, com o array ainda "correto" de olho nu.
    expect(WEEKDAYS[new Date(2026, 9, 4).getDay()]).toBe("Dom");
    expect(WEEKDAYS[new Date(2026, 9, 7).getDay()]).toBe("Qua");
    expect(WEEKDAYS[SABADO.getDay()]).toBe("Sáb");
    expect(WEEKDAYS).toHaveLength(7);
  });

  it("hojeDoTenant devolve a meia-noite LOCAL do dia do tenant", () => {
    // Sem instante fixo de propósito: o que se afirma é a identidade `localYmd(hojeDoTenant(tz))
    // === today(tz)`, verdadeira em qualquer dia. Um `m + 1` no lugar do `m - 1` (o `Date` conta
    // mês a partir de zero) quebra a identidade sem depender de que dia é hoje.
    for (const zona of [FUSO, FUSO_DISTANTE, "Pacific/Auckland"]) {
      const inicio = hojeDoTenant(zona);
      expect(`${zona}: ${localYmd(inicio)}`).toBe(`${zona}: ${today(zona)}`);
      expect(inicio.getHours()).toBe(0);
    }
  });
});

describe("eventosDoDia (ordenação)", () => {
  it("ordena por horário mesmo recebendo a lista embaralhada", () => {
    // Achado por mutação (#121): trocar `+new Date(a) - +new Date(b)` por
    // `-new Date(a) - +new Date(b)` faz o comparador devolver sempre um número NEGATIVO — o
    // `sort` então preserva a ordem de entrada e sobrevive a qualquer teste cuja lista já
    // chegue ordenada. É por isso que esta entra fora de ordem.
    const tarde = evento({ id: "tarde", starts_at: "2026-10-10T18:00:00Z", ends_at: "2026-10-10T19:00:00Z" });
    const manha = evento({ id: "manha", starts_at: "2026-10-10T12:00:00Z", ends_at: "2026-10-10T13:00:00Z" });
    const meio = evento({ id: "meio", starts_at: "2026-10-10T15:00:00Z", ends_at: "2026-10-10T16:00:00Z" });

    expect(eventosDoDia([tarde, manha, meio], DIA, FUSO).map((e) => e.id)).toEqual(["manha", "meio", "tarde"]);
  });
});

describe("gradeDoMes", () => {
  it("são 42 células, do domingo anterior ao dia 1 em diante", () => {
    const { start, end, days } = gradeDoMes(new Date(2026, 9, 20));

    expect(days).toHaveLength(42);
    // 01/10/2026 é quinta; o domingo anterior é 27/09.
    expect(localYmd(start)).toBe("2026-09-27");
    expect(localYmd(days[0])).toBe("2026-09-27");
    expect(localYmd(days[41])).toBe("2026-11-07");
    // `end` é a fronteira EXCLUSIVA — o dia seguinte à última célula.
    expect(localYmd(end)).toBe("2026-11-08");
  });

  it("quando o dia 1 já é domingo, a grade começa nele — não uma semana antes", () => {
    // 01/11/2026 é domingo. `startOfWeek` de um domingo tem de ser ponto fixo, senão o mês
    // inteiro aparece deslocado sete dias.
    const { start } = gradeDoMes(new Date(2026, 10, 15));
    expect(localYmd(start)).toBe("2026-11-01");
  });
});

describe("paramsDaGrade", () => {
  it("pede o range em meia-noite UTC da DATA do grid", () => {
    const { start, end, days } = gradeDoMes(new Date(2026, 9, 20));

    expect(paramsDaGrade(start, end)).toEqual({
      start: "2026-09-27T00:00:00.000Z",
      end: "2026-11-08T00:00:00.000Z",
      limit: 500,
    });
    expect(days).toHaveLength(42);
  });
});

describe("eventYmd / eventsOfDay", () => {
  it("evento de dia inteiro é lido pela DATA crua, sem passar por fuso", () => {
    // Gravados à meia-noite UTC: convertê-los "volta" um dia em fuso negativo. O `slice(0, 10)`
    // é o que impede isso — e sem ele o retorno seria o ISO inteiro.
    const feriado = evento({ all_day: true, starts_at: "2026-10-10T00:00:00Z", ends_at: "2026-10-11T00:00:00Z" });
    expect(eventYmd(feriado)).toBe("2026-10-10");
  });

  it("evento com horário é lido pelo fuso do NAVEGADOR (convenção antiga do AgendaPage)", () => {
    // 02:00Z de 11/10 é 23:00 de 10/10 em UTC−3, que é o TZ que a suíte fixa.
    const noturno = evento({ starts_at: "2026-10-11T02:00:00Z", ends_at: "2026-10-11T03:00:00Z" });
    expect(eventYmd(noturno)).toBe("2026-10-10");
  });

  it("eventsOfDay filtra pelo dia e ORDENA por horário de início", () => {
    const tarde = evento({ id: "tarde", starts_at: "2026-10-10T18:00:00Z", ends_at: "2026-10-10T19:00:00Z" });
    const manha = evento({ id: "manha", starts_at: "2026-10-10T12:00:00Z", ends_at: "2026-10-10T13:00:00Z" });
    const outroDia = evento({ id: "outro", starts_at: "2026-10-12T12:00:00Z", ends_at: "2026-10-12T13:00:00Z" });

    // A lista entra FORA de ordem de propósito: com ela já ordenada, um comparador quebrado
    // devolve a mesma saída e o teste passa sem exercer a ordenação.
    const doDia = eventsOfDay([tarde, manha, outroDia], DIA);

    expect(doDia.map((e) => e.id)).toEqual(["manha", "tarde"]);
  });

  it("eventsOfDay não modifica a lista recebida", () => {
    const tarde = evento({ id: "tarde", starts_at: "2026-10-10T18:00:00Z", ends_at: "2026-10-10T19:00:00Z" });
    const manha = evento({ id: "manha", starts_at: "2026-10-10T12:00:00Z", ends_at: "2026-10-10T13:00:00Z" });
    const entrada = [tarde, manha];

    eventsOfDay(entrada, DIA);

    expect(entrada.map((e) => e.id)).toEqual(["tarde", "manha"]);
  });
});
