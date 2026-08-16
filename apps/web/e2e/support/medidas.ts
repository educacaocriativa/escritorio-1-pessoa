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
 *
 * `raiz` recorta a varredura a um seletor. **Use sempre que medir um modal:** sem ele a página
 * inteira por trás entra na conta e o resultado mistura o que se quer medir com o que já estava
 * lá — 62 elementos onde a pergunta era sobre 13.
 */
export async function alvosPequenos(page: Page, min = 44, raiz?: string): Promise<Alvo[]> {
  return page.evaluate(({ limite, raizSel }) => {
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
    const escopo: ParentNode = raizSel ? (document.querySelector(raizSel) ?? document) : document;
    return [...escopo.querySelectorAll(SEL)]
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
  }, { limite: min, raizSel: raiz });
}

/**
 * Texto que só EXISTE se o dono rolar de lado — o defeito que a Onda 2b-ii achou na primeira
 * medição (`R$ 3.` no lugar de `R$ 3.000,00`). Para cada folha com texto, acha o ancestral que
 * recorta e mede quanto sobra fora dele.
 *
 * `raiz` recorta a VARREDURA (nunca o cálculo: o ancestral que recorta continua sendo procurado
 * para cima, mesmo fora dela). Use quando a tela tiver um deslizador horizontal LEGÍTIMO e a
 * pergunta for sobre o que está dentro do painel visível — o Kanban é o caso: as colunas seguintes
 * ficam fora da viewport por construção, e sem o recorte elas afogam o resultado com três cortes
 * que não são defeito de ninguém. Escopo que deixou de casar cai no documento inteiro, e não em
 * lista vazia: um seletor podre tem de aparecer como ruído, nunca como aprovação.
 */
export async function textoForaDaTela(page: Page, raiz?: string): Promise<Corte[]> {
  return page.evaluate((raizSel) => {
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
    const escopo: ParentNode = raizSel ? (document.querySelector(raizSel) ?? document.body) : document.body;
    for (const el of [...escopo.querySelectorAll("*")].filter(visivel)) {
      if (el.children.length > 0 || !(el.textContent ?? "").trim()) continue;
      const r = el.getBoundingClientRect();
      const limite = Math.min(recorte(el).getBoundingClientRect().right, vw);
      // A CAIXA nem sempre é o CONTEÚDO. Um bloco sem `width` própria fica travado na largura do
      // contêiner mesmo quando o texto não tem onde quebrar (`overflow-wrap: normal` + palavra sem
      // espaço) — a tinta vaza para fora da caixa sem alargá-la, e `getBoundingClientRect` não vê
      // tinta, só caixa. `scrollWidth` vê: é o conteúdo real do próprio elemento. Só conta quando o
      // elemento NÃO recorta a si mesmo (`overflow-x` computado é `visible`) — truncamento com
      // reticências (`.truncate`: `overflow:hidden` nele mesmo) também tem `scrollWidth >
      // clientWidth`, e ali é a UI funcionando como projetada, não um corte a denunciar.
      //
      // MÁXIMO entre os dois, nunca substituição: `scrollWidth` exclui borda, `r.right - r.left`
      // inclui. Num elemento com borda onde `clientWidth < scrollWidth <= clientWidth +
      // larguraDaBorda`, trocar `r.right` por `r.left + scrollWidth` teria devolvido um corte
      // MENOR que o antigo caminho já enxergava — a régua ficando mais cega no exato ponto onde
      // devia ficar mais afiada.
      const direita =
        getComputedStyle(el).overflowX === "visible" && el.scrollWidth > el.clientWidth + 0.5
          ? Math.max(r.right, r.left + el.scrollWidth)
          : r.right;
      const sobra = +(direita - limite).toFixed(1);
      if (sobra > 0.5) {
        fora.push({
          texto: (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 60),
          descricao: descrever(el),
          forcaFora: sobra,
        });
      }
    }
    return fora;
  }, raiz);
}
