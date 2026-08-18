import { describe, expect, it } from "vitest";
import { fimDoMesSeguinte, filtroPadrao, paraQuery } from "./filtros";

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
