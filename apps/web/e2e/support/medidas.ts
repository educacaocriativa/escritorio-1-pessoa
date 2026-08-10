import type { Page } from "@playwright/test";

/**
 * A régua.
 *
 * Tudo aqui devolve NÚMERO medido no navegador. Nenhuma função afere classe CSS, e nenhum spec
 * deste diretório deve fazê-lo: `toContain("flex-wrap")` passou durante duas sessões com a
 * `FilaPagamentosPage` quebrada em produção. O `overflow-x` estava certo, o `flex-wrap` estava
 * certo, e a tela estava errada.
 */

export interface Medidas {
  /** `document.documentElement.scrollWidth`. Maior que a viewport = a página rola de lado. */
  larguraDaPagina: number;
  alturaDaPagina: number;
}

export interface Alvo {
  descricao: string;
  largura: number;
  altura: number;
}

export interface Corte {
  texto: string;
  descricao: string;
  forcaFora: number;
}

export async function medirPagina(page: Page): Promise<Medidas> {
  return page.evaluate(() => ({
    larguraDaPagina: document.documentElement.scrollWidth,
    alturaDaPagina: document.documentElement.scrollHeight,
  }));
}

/**
 * Controles menores que o mínimo tocável. `min` é ALTURA e LARGURA em CSS px.
 *
 * 44px não é preciosismo: foi um checkbox pequeno demais, separado da ação que o tornava efetivo,
 * que fez uma conta real ser marcada como paga sem o dono conseguir ver (PR #56).
 */
export async function alvosPequenos(page: Page, min = 44): Promise<Alvo[]> {
  return page.evaluate((limite) => {
    // As auxiliares são declaradas AQUI DENTRO de propósito: o corpo de um `page.evaluate` é
    // serializado e executado no navegador, e nada do escopo do Node viaja junto.
    const descrever = (el: Element): string => {
      const cls =
        typeof el.className === "string"
          ? el.className.split(/\s+/).filter(Boolean).slice(0, 5).join(".")
          : "";
      const txt = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 50);
      return el.tagName.toLowerCase() + (cls ? "." + cls : "") + (txt ? ` «${txt}»` : "");
    };
    const visivel = (el: Element): boolean => {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const SEL =
      'button,a[href],input:not([type="hidden"]),select,textarea,' +
      '[role="button"],[role="checkbox"],summary';
    return [...document.querySelectorAll(SEL)]
      .filter(visivel)
      .map((el) => {
        const r = el.getBoundingClientRect();
        return {
          descricao: descrever(el),
          largura: +r.width.toFixed(1),
          altura: +r.height.toFixed(1),
        };
      })
      .filter((a) => a.altura < limite || a.largura < limite);
  }, min);
}

/**
 * Texto que só EXISTE se o dono rolar de lado — o defeito que a Onda 2b-ii achou na primeira
 * medição (`R$ 3.` no lugar de `R$ 3.000,00`). Para cada folha com texto, acha o ancestral que
 * recorta e mede quanto sobra fora dele.
 */
export async function textoForaDaTela(page: Page): Promise<Corte[]> {
  return page.evaluate(() => {
    const descrever = (el: Element): string => {
      const cls =
        typeof el.className === "string"
          ? el.className.split(/\s+/).filter(Boolean).slice(0, 5).join(".")
          : "";
      return el.tagName.toLowerCase() + (cls ? "." + cls : "");
    };
    const visivel = (el: Element): boolean => {
      const s = getComputedStyle(el);
      if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    // Quem de fato recorta este elemento — o ancestral mais próximo com `overflow-x` que não seja
    // `visible`. É contra a borda DELE que o texto sobra, não contra a da página: era exatamente
    // isso que `main.overflow-x-hidden` escondia enquanto o `scrollWidth` da página dizia 360.
    const recorte = (el: Element): Element => {
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if (ox === "hidden" || ox === "auto" || ox === "scroll" || ox === "clip") return p;
      }
      return document.documentElement;
    };
    const vw = document.documentElement.clientWidth;
    const fora: { texto: string; descricao: string; forcaFora: number }[] = [];
    for (const el of [...document.querySelectorAll("body *")].filter(visivel)) {
      if (el.children.length > 0 || !(el.textContent ?? "").trim()) continue;
      const r = el.getBoundingClientRect();
      const limite = Math.min(recorte(el).getBoundingClientRect().right, vw);
      const sobra = +(r.right - limite).toFixed(1);
      if (sobra > 0.5) {
        fora.push({
          texto: (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 60),
          descricao: descrever(el),
          forcaFora: sobra,
        });
      }
    }
    return fora;
  });
}
