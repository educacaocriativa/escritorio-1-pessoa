import { describe, expect, it } from "vitest";
import { type NavItem, navSections, visibleNavSections } from "./navigation";

const itens: NavItem[] = navSections.flatMap((s) => s.items);

/**
 * Guardas estruturais da navegação (Story 8.7 — AC3 / IV2 / IV5).
 *
 * Duas destas asserções não são cosméticas: elas travam uma decisão de **posicionamento de
 * produto** que o design tratou como risco existencial da tese. O epic registra "produto virar ERP
 * contábil e perder o público" como impacto existencial, e o design §5.4 é explícito: *"o rótulo
 * comunica 'software de contabilidade' para todo usuário, inclusive quem nunca abre a tela"*.
 * Sem teste, o item de menu "Conciliação bancária" volta na primeira vez que alguém achar
 * estranho a rota não estar no menu.
 */
describe("Story 8.7 — 'Contas & Saldos' entra no menu; a conferência NÃO", () => {
  it("existe UM item 'Contas & Saldos' apontando para /financeiro/contas", () => {
    const contas = itens.filter((i) => i.to === "/financeiro/contas");
    expect(contas).toHaveLength(1);
    expect(contas[0].label).toBe("Contas & Saldos");
    expect(contas[0].ready).toBe(true);
  });

  it("nenhum item de menu aponta para /financeiro/conferencia", () => {
    // Ela é alcançada pelo sinal de completude do diagnóstico e pelo "Conferir" de cada conta.
    expect(itens.filter((i) => i.to.startsWith("/financeiro/conferencia"))).toEqual([]);
  });

  it("nenhum rótulo do menu contém 'Concilia' (em qualquer caixa) — rótulo PROIBIDO", () => {
    expect(itens.filter((i) => /concilia/i.test(i.label))).toEqual([]);
  });

  it("fica na seção 'Financeiro' (operacional), logo depois da Carteira", () => {
    // Decisão de posicionamento: "onde está o meu dinheiro", não relatório contábil. Colocá-lo em
    // "Análise & Configuração Financeira" empurraria a leitura para o lado errado (design §5.4).
    const financeiro = navSections.find((s) => s.title === "Financeiro");
    expect(financeiro).toBeDefined();
    const rotas = financeiro?.items.map((i) => i.to) ?? [];
    expect(rotas.indexOf("/financeiro/contas")).toBe(rotas.indexOf("/financeiro") + 1);
  });
});

/**
 * IV2 — nenhum item existente foi alterado ou removido. A lista abaixo é o estado ANTES desta
 * story (HEAD `172711d`); ela existe para que uma remoção acidental durante um merge apareça
 * como falha de teste, e não como um menu que perdeu uma entrada em silêncio.
 */
describe("IV2 — a navegação existente continua inteira", () => {
  const ROTAS_PRE_8_7 = [
    "/",
    "/agenda",
    "/crm",
    "/conversas",
    "/financeiro",
    "/cobrancas",
    "/pagar",
    "/financeiro/fila-pagamentos",
    "/financeiro/dre",
    "/financeiro/lucratividade",
    "/financeiro/projecao-caixa",
    "/financeiro/diagnostico",
    "/financeiro/investimentos",
    "/financeiro/plano-contas",
    "/financeiro/centros-custo",
    "/orcamentos",
    "/contratos",
    "/produtos",
    "/estoque",
    "/marketing",
    "/funis",
    "/sites",
    "/juridico",
    "/config",
  ];

  it("todas as rotas anteriores continuam no menu", () => {
    const rotas = itens.map((i) => i.to);
    for (const r of ROTAS_PRE_8_7) expect(rotas).toContain(r);
  });

  it("esta story acrescentou exatamente UM item", () => {
    expect(itens).toHaveLength(ROTAS_PRE_8_7.length + 1);
  });

  it("nenhuma rota duplicada no menu", () => {
    const rotas = itens.map((i) => i.to);
    expect(new Set(rotas).size).toBe(rotas.length);
  });
});

/**
 * `visibleNavSections` — o recorte da sidebar por RBAC (`allowed_modules`). Antes desta função a
 * sidebar mostrava todo item a todo usuário, e um sub-usuário sem um módulo clicava numa tela que
 * só sabia travar em "Carregando...". Ver `Modulo` em `app/App.tsx` para a segunda metade (o
 * guard de ROTA, contra link direto/URL digitada).
 */
describe("visibleNavSections", () => {
  it("dono (hasModule sempre true) vê a lista INTEIRA, mesma forma de navSections", () => {
    const visiveis = visibleNavSections(() => true).flatMap((s) => s.items);
    expect(visiveis).toEqual(itens);
  });

  it("sub-usuário sem nenhum módulo não vê NENHUM item com `module` — a seção some inteira", () => {
    const secoes = visibleNavSections(() => false);
    const visiveis = secoes.flatMap((s) => s.items);
    // O que sobra é só o que nunca teve `module` (hoje, nada — todo item de negócio tem um).
    expect(visiveis.every((i) => !i.module)).toBe(true);
  });

  it("um item sem `module` nunca é escondido, mesmo com hasModule sempre false", () => {
    const semModulo = itens.filter((i) => !i.module);
    const visiveis = visibleNavSections(() => false).flatMap((s) => s.items);
    for (const item of semModulo) expect(visiveis).toContainEqual(item);
  });

  it("sub-usuário restrito (o caso relatado — sem 'juridico' e 'funnels') não vê Jurídico nem Funil de Vendas, mas o resto continua", () => {
    const modulosPermitidos = new Set(["crm", "cockpit", "agenda", "receivables", "contracts"]);
    const secoes = visibleNavSections((m) => modulosPermitidos.has(m));
    const rotas = secoes.flatMap((s) => s.items).map((i) => i.to);

    expect(rotas).not.toContain("/juridico");
    expect(rotas).not.toContain("/funis");
    expect(rotas).toContain("/crm");
    expect(rotas).toContain("/cobrancas");
    expect(rotas).toContain("/contratos");
  });

  it("seção que fica sem item nenhum some inteira (não sobra título/divisor vazio)", () => {
    // "Análise & Configuração Financeira" é só módulos que este usuário não tem — a seção some.
    const secoes = visibleNavSections((m) => m === "crm");
    expect(secoes.some((s) => s.title === "Análise & Configuração Financeira")).toBe(false);
  });
});
