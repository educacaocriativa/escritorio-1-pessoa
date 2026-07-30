import { describe, expect, it } from "vitest";
import {
  formatBRL,
  ORIGEM_LABEL,
  origemLabel,
  parcelasSaldoInicial,
  type Projection,
  ROTULO_BANCO,
  ROTULO_PLATAFORMA,
  type Runway,
  runwayLabel,
  toPolylinePoints,
  trajectoryPoints,
} from "./projecao";

/**
 * Smoke test da lógica pura da projeção de caixa (Story 5.7). O projeto não tem infra de teste de
 * componente React — os testes de front são de lógica pura (ver dre.test.ts / planoContas.test.ts).
 * Cobre a trajetória (hoje + janelas), o mapeamento para a polyline do gráfico e o rótulo do runway.
 *
 * **Story 8.1:** `runwayLabel` mudou de assinatura (`Runway` em vez de `days`) para que o caso
 * SUPRIMIDO não possa ser renderizado por engano como "sem risco" — o ramo mais valioso do frontend
 * nesta story. Também cobre o rótulo de procedência (`ORIGEM_LABEL`/`origemLabel`).
 */
const runway = (over: Partial<Runway> = {}): Runway => ({
  days: 90,
  days_suprimido: false,
  burn_rate_cents_per_day: 1000,
  ...over,
});

const projection = (over: Partial<Projection> = {}): Projection => ({
  today: "2026-07-11",
  saldo_inicial_cents: 90000,
  saldo_inicial_origem: "plataforma",
  saldo_inicial_banco_cents: 0,
  saldo_inicial_plataforma_cents: 90000,
  overdue_inflow_cents: 0,
  overdue_outflow_cents: 0,
  windows: [
    { days: 30, saldo_projetado_cents: 50000, alert: false, alert_suprimido: false },
    { days: 60, saldo_projetado_cents: -20000, alert: true, alert_suprimido: false },
    { days: 90, saldo_projetado_cents: -80000, alert: true, alert_suprimido: false },
  ],
  runway: runway(),
  notes: ["Regime de CAIXA."],
  ...over,
});

describe("trajectoryPoints", () => {
  it("começa em hoje (dia 0 = saldo inicial) e segue as janelas", () => {
    const pts = trajectoryPoints(projection());
    expect(pts).toEqual([
      { days: 0, saldo_cents: 90000 },
      { days: 30, saldo_cents: 50000 },
      { days: 60, saldo_cents: -20000 },
      { days: 90, saldo_cents: -80000 },
    ]);
  });
});

describe("toPolylinePoints", () => {
  it("mapeia os pontos para coordenadas dentro do viewBox (saldo maior = y menor)", () => {
    const pts = trajectoryPoints(projection());
    const poly = toPolylinePoints(pts, { width: 100, height: 40, padding: 0 });
    const coords = poly.split(" ").map((p) => p.split(",").map(Number));
    // 4 pontos, x crescente com os dias
    expect(coords).toHaveLength(4);
    expect(coords[0][0]).toBeLessThan(coords[3][0]);
    // o maior saldo (90000, primeiro ponto) fica no topo (y menor); o menor (-80000) no fundo
    const ys = coords.map((c) => c[1]);
    expect(Math.min(...ys)).toBe(ys[0]); // 90000 → topo
    expect(Math.max(...ys)).toBe(ys[3]); // -80000 → fundo
  });

  it("não divide por zero quando todos os saldos são iguais", () => {
    const flat = projection({
      saldo_inicial_cents: 1000,
      windows: [
        { days: 30, saldo_projetado_cents: 1000, alert: false, alert_suprimido: true },
        { days: 60, saldo_projetado_cents: 1000, alert: false, alert_suprimido: true },
        { days: 90, saldo_projetado_cents: 1000, alert: false, alert_suprimido: true },
      ],
    });
    const poly = toPolylinePoints(trajectoryPoints(flat), { width: 100, height: 40 });
    expect(poly).not.toContain("NaN");
  });

  it("retorna string vazia sem pontos", () => {
    expect(toPolylinePoints([], { width: 10, height: 10 })).toBe("");
  });
});

describe("runwayLabel", () => {
  it("converte dias em meses e dias (mês de 30 dias)", () => {
    expect(runwayLabel(runway({ days: 90 }))).toBe("3 meses");
    expect(runwayLabel(runway({ days: 45 }))).toBe("1 mês e 15 dias");
    expect(runwayLabel(runway({ days: 1 }))).toBe("1 dia");
  });

  it("trata caixa crescente (null) e limite (0)", () => {
    expect(runwayLabel(runway({ days: null, burn_rate_cents_per_day: 0 }))).toContain("Sem risco");
    expect(runwayLabel(runway({ days: 0 }))).toContain("0 dias");
  });

  it("[Story 8.1 AC5] suprimido diz INDISPONÍVEL e JAMAIS 'sem risco'", () => {
    // O teste mais valioso desta story no frontend: trocar "não sei" por "sem risco" substituiria
    // um número falso por uma tranquilidade falsa — e a segunda dá permissão para gastar.
    const label = runwayLabel(runway({ days: null, days_suprimido: true }));
    expect(label).toContain("Indisponível");
    expect(label.toLowerCase()).not.toContain("sem risco");
    // ...e aponta o MOTIVO (saldo inicial não confirmado), não uma indisponibilidade genérica
    expect(label.toLowerCase()).toContain("saldo inicial");
  });

  it("[Story 8.1 AC4] os três ramos produzem rótulos distintos entre si", () => {
    const suprimido = runwayLabel(runway({ days: null, days_suprimido: true }));
    const semRisco = runwayLabel(runway({ days: null, burn_rate_cents_per_day: 0 }));
    const comDias = runwayLabel(runway({ days: 43 }));
    expect(new Set([suprimido, semRisco, comDias]).size).toBe(3);
  });
});

describe("ORIGEM_LABEL / origemLabel (Story 8.1 AC1)", () => {
  it("cobre os QUATRO valores do eixo A e nenhum a mais", () => {
    // O vocabulário canônico é `app/core/money_planes.py::ORIGENS` — quatro valores. `declarado` e
    // `extrato` foram revogados (pertencem ao eixo B, `*_fonte`, e nunca entram neste mapa).
    expect(Object.keys(ORIGEM_LABEL).sort()).toEqual([
      "banco",
      "indisponivel",
      "misto",
      "plataforma",
    ]);
  });

  it("traduz a origem da Onda 0 e não engana o usuário chamando-a de conta bancária", () => {
    expect(origemLabel("plataforma")).toBe("disponível na Carteira e1p");
    expect(origemLabel("plataforma")).not.toContain("conta bancária");
  });

  it("é tolerante a um valor novo do backend (mostra o valor cru em vez de sumir)", () => {
    expect(origemLabel("valor-que-ainda-nao-existe")).toBe("valor-que-ainda-nao-existe");
  });
});

describe("parcelasSaldoInicial (Story 8.8 AC5)", () => {
  const misto = (over: Partial<Projection> = {}) =>
    projection({
      saldo_inicial_origem: "misto",
      saldo_inicial_cents: 840000,
      saldo_inicial_banco_cents: 750000,
      saldo_inicial_plataforma_cents: 90000,
      ...over,
    });

  it("sob 'misto' devolve as DUAS parcelas rotuladas, banco primeiro", () => {
    expect(parcelasSaldoInicial(misto())).toEqual([
      { rotulo: ROTULO_BANCO, cents: 750000 },
      { rotulo: ROTULO_PLATAFORMA, cents: 90000 },
    ]);
  });

  it("usa o vocabulário canônico da §1.2 — 'no banco' e 'na plataforma'", () => {
    // Os rótulos são o contrato com o usuário: eles são o que impede a soma entre planos de virar
    // um número anônimo. Sinônimos improvisados ("carteira", "disponível") reabririam a ambiguidade.
    expect(ROTULO_BANCO).toBe("no banco");
    expect(ROTULO_PLATAFORMA).toContain("na plataforma");
    expect(ROTULO_PLATAFORMA).toContain("sacar");
  });

  it("no fallback 'plataforma' devolve só a parcela de plataforma", () => {
    expect(parcelasSaldoInicial(projection())).toEqual([
      { rotulo: ROTULO_PLATAFORMA, cents: 90000 },
    ]);
  });

  it("sob 'misto' a parcela ZERADA continua sendo exibida — não some do rol", () => {
    // O caso de quem sacou tudo: a plataforma é 0 e o usuário precisa ver que ela é 0, não que ela
    // não existe. Se a parcela sumisse, a UI teria dois formatos e "esconder a composição" voltaria
    // pela porta dos fundos.
    const sacouTudo = misto({
      saldo_inicial_cents: 750000,
      saldo_inicial_plataforma_cents: 0,
    });
    const parcelas = parcelasSaldoInicial(sacouTudo);
    expect(parcelas).toHaveLength(2);
    expect(parcelas[1]).toEqual({ rotulo: ROTULO_PLATAFORMA, cents: 0 });
  });

  it("a soma das parcelas é SEMPRE o total (a invariante do AC2, também na tela)", () => {
    const casos = [
      projection(), // fallback
      misto(), // misto normal
      misto({ saldo_inicial_cents: 750000, saldo_inicial_plataforma_cents: 0 }), // sacou tudo
      // cheque especial: parcela bancária negativa somando com a plataforma
      misto({
        saldo_inicial_cents: -160000,
        saldo_inicial_banco_cents: -250000,
        saldo_inicial_plataforma_cents: 90000,
      }),
      // conta nova zerada: origem já é `misto`, as duas parcelas aparecem mesmo com total 0
      misto({
        saldo_inicial_cents: 0,
        saldo_inicial_banco_cents: 0,
        saldo_inicial_plataforma_cents: 0,
      }),
      // origem que o backend ainda não emite: a função continua total e a soma continua fechando
      projection({
        saldo_inicial_origem: "banco",
        saldo_inicial_cents: 500000,
        saldo_inicial_banco_cents: 500000,
        saldo_inicial_plataforma_cents: 0,
      }),
    ];
    for (const p of casos) {
      const soma = parcelasSaldoInicial(p).reduce((acc, x) => acc + x.cents, 0);
      expect(soma).toBe(p.saldo_inicial_cents);
    }
  });

  it("é pura: não muda a projeção recebida", () => {
    const p = misto();
    const copia = structuredClone(p);
    parcelasSaldoInicial(p);
    expect(p).toEqual(copia);
  });
});

describe("runwayLabel NÃO mudou na Story 8.8 (a restauração é do backend)", () => {
  it("os três ramos da 8.1 seguem intactos — nenhuma regra de supressão nova no frontend", () => {
    // A 8.8 restaura o runway trocando a ORIGEM no backend; se alguém tivesse acrescentado aqui um
    // `exibeRunwayEmDias` (ou qualquer condicional de origem), passaria a existir uma segunda regra
    // para manter em sincronia com a do backend — e ela divergiria no primeiro dia esquecido.
    const comOrigemMista = runway({ days: 43, days_suprimido: false });
    expect(runwayLabel(comOrigemMista)).toBe("1 mês e 13 dias");
    // O mesmo runway, se o backend disser que está suprimido, continua indisponível — a tela
    // obedece ao flag, não à origem.
    expect(runwayLabel(runway({ days: null, days_suprimido: true }))).toContain("Indisponível");
  });
});

describe("formatBRL (reuso de dre.ts)", () => {
  it("formata centavos preservando sinal", () => {
    expect(formatBRL(90000)).toContain("900,00");
    expect(formatBRL(-80000)).toContain("-");
  });
});
