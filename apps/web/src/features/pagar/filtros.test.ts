import { describe, expect, it } from "vitest";
import {
  apenasTexto,
  daUrl,
  fimDoMesSeguinte,
  filtroPadrao,
  type FiltroPagar,
  paraQuery,
  paraUrl,
} from "./filtros";

describe("fimDoMesSeguinte", () => {
  it("agosto devolve o fim de setembro", () => {
    expect(fimDoMesSeguinte("2026-08-18")).toBe("2026-09-30");
  });

  it("vira o ano em dezembro", () => {
    expect(fimDoMesSeguinte("2026-12-05")).toBe("2027-01-31");
  });

  it("acerta fevereiro bissexto", () => {
    expect(fimDoMesSeguinte("2028-01-10")).toBe("2028-02-29");
  });

  it("acerta fevereiro comum", () => {
    expect(fimDoMesSeguinte("2027-01-10")).toBe("2027-02-28");
  });

  it("acerta o ano secular nao bissexto", () => {
    expect(fimDoMesSeguinte("2100-01-10")).toBe("2100-02-28");
  });
});

describe("filtroPadrao", () => {
  const padrao = filtroPadrao("2026-08-18");

  it("abre em 'o que eu devo': aberta e agendada", () => {
    expect(padrao.status).toEqual(["open", "scheduled"]);
  });

  it("NAO tem piso de data", () => {
    // Atrasado vence no passado. Qualquer `de` esconde a conta mais urgente que existe.
    expect(padrao.de).toBeNull();
  });

  it("tem teto no fim do mes seguinte", () => {
    expect(padrao.ate).toBe("2026-09-30");
  });
});

describe("paraQuery", () => {
  it("omite o que esta vazio, em vez de mandar chave nula", () => {
    const q = paraQuery(filtroPadrao("2026-08-18"), 50, 0);
    expect(q).toEqual({
      status: ["open", "scheduled"],
      to: "2026-09-30",
      order: "asc",
      limit: 50,
      offset: 0,
    });
    expect(q).not.toHaveProperty("from");
    expect(q).not.toHaveProperty("q");
  });

  it("manda o texto quando ele existe", () => {
    const f = { ...filtroPadrao("2026-08-18"), q: "anthropic" };
    expect(paraQuery(f, 50, 0).q).toBe("anthropic");
  });

  it("historico vem decrescente", () => {
    const f = { ...filtroPadrao("2026-08-18"), status: ["paid" as const], ate: null };
    expect(paraQuery(f, 50, 0).order).toBe("desc");
  });

  it("repassa limit e offset da paginacao", () => {
    const q = paraQuery(filtroPadrao("2026-08-18"), 50, 100);
    expect(q.limit).toBe(50);
    expect(q.offset).toBe(100);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// O recorte na BARRA DE ENDERECO (#138)
//
// Estes testes medem a IDA E VOLTA. Um teste que so olhasse o estado de React
// passaria com a URL vazia — foi exatamente essa fresta que deixou
// `/pagar?q=anthropic` inerte. Aqui a unidade sob teste E a query string.
// ─────────────────────────────────────────────────────────────────────────────

const PADRAO = filtroPadrao("2026-08-18"); // ate = 2026-09-30

/** A volta completa: filtro → query string → filtro. Tem de devolver o mesmo recorte. */
function idaEVolta(f: FiltroPagar): FiltroPagar {
  return daUrl(new URLSearchParams(paraUrl(f, PADRAO).toString()), PADRAO);
}

describe("paraUrl", () => {
  it("URL vazia e o filtro padrao: nada do default e escrito", () => {
    // Um `?status=open&status=scheduled&ate=2026-09-30` que so repete o default seria poluicao
    // que o dono le toda vez. E congelaria o favorito: `ate` omitido acompanha o horizonte movel.
    expect(paraUrl(PADRAO, PADRAO).toString()).toBe("");
  });

  it("escreve o `status` REPETIVEL, uma chave por valor", () => {
    const f = { ...PADRAO, status: ["open" as const, "paid" as const] };
    // Nunca `status[]` (o FastAPI ignora em silencio, #125) nem `status=open,paid`.
    expect(paraUrl(f, PADRAO).toString()).toBe("status=open&status=paid");
  });

  it("OMITE a chave de texto vazia, em vez de mandar `?q=`", () => {
    const f = { ...PADRAO, q: "", centroDeCusto: "", categoria: "" };
    const u = paraUrl(f, PADRAO);
    expect(u.has("q")).toBe(false);
    expect(u.has("centro")).toBe(false);
    expect(u.has("categoria")).toBe(false);
  });

  it("escreve os tres textos quando eles existem, pelos nomes da TELA", () => {
    const f = { ...PADRAO, q: "anthropic", centroDeCusto: "cc-1", categoria: "ca-1" };
    const u = paraUrl(f, PADRAO);
    expect(u.get("q")).toBe("anthropic");
    // `centro`/`categoria`, e nao `cost_center_id`/`chart_account_id`: a URL e digitada a mao.
    expect(u.get("centro")).toBe("cc-1");
    expect(u.get("categoria")).toBe("ca-1");
    expect(u.has("cost_center_id")).toBe(false);
    expect(u.has("chart_account_id")).toBe(false);
  });

  it("`ate: null` com padrao COM teto vira chave presente de valor vazio", () => {
    // "sem teto" e um VALOR escolhido (a tela faz isso ao trocar para Pago), nao vazio. Omitir a
    // chave devolveria o teto do padrao na volta, e o recorte compartilhado seria outro.
    expect(paraUrl({ ...PADRAO, ate: null }, PADRAO).toString()).toBe("ate=");
  });

  it("`status: []` (todos) vira chave presente de valor vazio, pelo mesmo motivo", () => {
    expect(paraUrl({ ...PADRAO, status: [] }, PADRAO).toString()).toBe("status=");
  });
});

describe("daUrl", () => {
  it("URL vazia devolve o filtro padrao inteiro", () => {
    expect(daUrl(new URLSearchParams(""), PADRAO)).toEqual(PADRAO);
  });

  it("`?q=anthropic` filtra o texto e PRESERVA o resto do padrao", () => {
    const f = daUrl(new URLSearchParams("q=anthropic"), PADRAO);
    expect(f.q).toBe("anthropic");
    expect(f.status).toEqual(["open", "scheduled"]);
    expect(f.ate).toBe("2026-09-30");
  });

  it("le o `status` REPETIVEL como lista, na ordem em que veio", () => {
    expect(daUrl(new URLSearchParams("status=open&status=scheduled"), PADRAO).status).toEqual([
      "open",
      "scheduled",
    ]);
  });

  it("`?status=paid` troca o recorte inteiro, sem herdar o do padrao", () => {
    expect(daUrl(new URLSearchParams("status=paid"), PADRAO).status).toEqual(["paid"]);
  });

  it("descarta status inventado, em vez de mandar lixo ao servidor", () => {
    expect(daUrl(new URLSearchParams("status=paid&status=xpto"), PADRAO).status).toEqual(["paid"]);
  });

  it("`?ate=` (vazio) e SEM TETO, nao o teto do padrao", () => {
    expect(daUrl(new URLSearchParams("ate="), PADRAO).ate).toBeNull();
    expect(daUrl(new URLSearchParams(""), PADRAO).ate).toBe("2026-09-30");
  });

  it("a data da URL segue STRING — nada de `new Date` no caminho", () => {
    // Reconstruir um `Date` devolveria a conta ao relogio do NAVEGADOR. Em UTC-3 a data voltaria
    // um dia. O valor tem de sair identico ao que entrou, caractere por caractere.
    const f = daUrl(new URLSearchParams("de=2026-01-01&ate=2026-12-31"), PADRAO);
    expect(f.de).toBe("2026-01-01");
    expect(f.ate).toBe("2026-12-31");
  });
});

describe("ida e volta URL <-> FiltroPagar", () => {
  const casos: [string, FiltroPagar][] = [
    ["o padrao", PADRAO],
    ["so o texto", { ...PADRAO, q: "anthropic" }],
    ["dois status (repetivel)", { ...PADRAO, status: ["open", "paid"] }],
    ["um status so", { ...PADRAO, status: ["canceled"] }],
    ["nenhum status (todos)", { ...PADRAO, status: [] }],
    ["historico sem teto", { ...PADRAO, status: ["paid"], ate: null }],
    ["periodo fechado", { ...PADRAO, de: "2026-01-01", ate: "2026-12-31" }],
    [
      "tudo junto",
      {
        status: ["open", "scheduled", "paid"],
        de: "2026-02-01",
        ate: null,
        q: "energia elétrica",
        centroDeCusto: "cc-1",
        categoria: "ca-1",
      },
    ],
  ];

  for (const [nome, f] of casos) {
    it(`volta identico: ${nome}`, () => {
      expect(idaEVolta(f)).toEqual(f);
    });
  }

  it("o que vai para a URL ainda serve o axios com os nomes da API", () => {
    // As duas serializacoes convivem: a URL fala com o dono, `paraQuery` fala com o FastAPI.
    const f = idaEVolta({ ...PADRAO, q: "anthropic", centroDeCusto: "cc-1", categoria: "ca-1" });
    const q = paraQuery(f, 50, 0);
    expect(q.q).toBe("anthropic");
    expect(q.cost_center_id).toBe("cc-1");
    expect(q.chart_account_id).toBe("ca-1");
  });
});

describe("apenasTexto — quem decide se o botao voltar tem o que desfazer", () => {
  it("mudar SO o texto e digitacao: a URL se reescreve", () => {
    // Uma entrada de historico por tecla obrigaria o dono a apertar "voltar" nove vezes.
    expect(apenasTexto(PADRAO, { ...PADRAO, q: "anthropic" })).toBe(true);
  });

  it("trocar o status e gesto deliberado: EMPILHA", () => {
    expect(apenasTexto(PADRAO, { ...PADRAO, status: ["paid"] })).toBe(false);
  });

  it("aplicar um periodo e gesto deliberado: EMPILHA", () => {
    expect(apenasTexto(PADRAO, { ...PADRAO, ate: null })).toBe(false);
    expect(apenasTexto(PADRAO, { ...PADRAO, de: "2026-01-01" })).toBe(false);
  });

  it("escolher centro de custo ou categoria EMPILHA", () => {
    expect(apenasTexto(PADRAO, { ...PADRAO, centroDeCusto: "cc-1" })).toBe(false);
    expect(apenasTexto(PADRAO, { ...PADRAO, categoria: "ca-1" })).toBe(false);
  });

  it("'Limpar filtros' mexe em quatro campos: EMPILHA, e o voltar desfaz a limpeza", () => {
    const sujo = { ...PADRAO, q: "x", centroDeCusto: "cc-1", categoria: "ca-1", de: "2026-01-01" };
    const limpo = { ...sujo, q: "", centroDeCusto: "", categoria: "", de: null };
    expect(apenasTexto(sujo, limpo)).toBe(false);
  });
});
