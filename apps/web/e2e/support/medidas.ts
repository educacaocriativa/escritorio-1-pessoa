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
  /**
   * `type` do `<input>` — `""` para todo o resto. Existe porque um spec precisa distinguir a
   * CAIXINHA do checkbox (20×20 por convenção do repo, e o alvo do dedo é o `<label>` em volta)
   * de um campo de TEXTO pequeno demais. Enquanto não existia, o único recorte possível era
   * `descricao.startsWith("input")`, que joga os dois fora juntos — e foi por esse buraco que o
   * `<input>` de 38px do `Field` atravessou o #181 (está escrito no `toque-360.spec.ts`).
   */
  tipo: string;
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
 * Um controle tocável, medido no navegador, com tudo o que a régua precisa saber sobre ele.
 *
 * Existe UMA coleta só porque as perguntas são duas — "é pequeno demais?" (`alvosPequenos`) e
 * "dá para alcançar?" (`controlesInalcancaveis`) — sobre exatamente o MESMO conjunto de
 * elementos. Duplicar o seletor e o `visivel` em dois `page.evaluate` seria criar duas
 * definições de "controle" que divergem no primeiro dia em que alguém corrigir só uma.
 */
interface ControleMedido {
  descricao: string;
  /** `type` do `<input>`; `""` para `button`, `select`, `a`, `summary` e afins. */
  tipo: string;
  largura: number;
  altura: number;
  esquerda: number;
  direita: number;
  /** Borda direita ALCANÇÁVEL: a menor entre a viewport e a de todo ancestral que recorta. */
  limiteDireito: number;
  /** Ancestral que rola na horizontal e cabe na tela (logo, resgata o controle). `null` = não há. */
  deslizador: string | null;
  /** Casou com algum seletor de `EXCECOES_DE_ALCANCE` — ver a razão escrita lá. */
  excecao: boolean;
}

/**
 * Coleta bruta. Nenhum critério aqui, só número medido: quem decide o que é defeito são as
 * funções abaixo, em Node, onde a razão pode ser lida e discutida.
 */
async function medirControles(
  page: Page,
  raiz?: string,
  excecoes: string[] = [],
): Promise<ControleMedido[]> {
  return page.evaluate(
    ({ raizSel, excSel }) => {
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
      const vw = document.documentElement.clientWidth;
      // A página inteira rolar de lado TAMBÉM é escape — e é a classe do #135, que `medirPagina`
      // já mede. As duas réguas não podem acusar o mesmo defeito duas vezes.
      const paginaRola =
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      const escopo: ParentNode = raizSel ? (document.querySelector(raizSel) ?? document) : document;
      return [...escopo.querySelectorAll(SEL)].filter(visivel).map((el) => {
        const r = el.getBoundingClientRect();
        let limite = vw;
        let deslizador: string | null = paginaRola ? "document" : null;
        for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
          const ox = getComputedStyle(p).overflowX;
          if (ox === "visible") continue;
          const rp = p.getBoundingClientRect();
          // Recorta: a borda DELE passa a valer tanto quanto a da tela.
          limite = Math.min(limite, rp.right);
          // Rola: o dono desliza e o controle vem. Mas só vale se a caixa do próprio deslizador
          // couber na tela — um deslizador que já está metade fora não tem para onde trazer nada.
          if (
            deslizador === null &&
            (ox === "auto" || ox === "scroll") &&
            p.scrollWidth > p.clientWidth + 1 &&
            rp.right <= vw + 0.5 &&
            rp.left >= -0.5
          ) {
            deslizador = descrever(p).slice(0, 60);
          }
        }
        return {
          descricao: descrever(el),
          tipo: el.tagName === "INPUT" ? ((el as HTMLInputElement).getAttribute("type") ?? "text") : "",
          largura: +r.width.toFixed(1),
          altura: +r.height.toFixed(1),
          esquerda: +r.left.toFixed(1),
          direita: +r.right.toFixed(1),
          limiteDireito: +limite.toFixed(1),
          deslizador,
          excecao: excSel.some((sel) => el.closest(sel) !== null),
        };
      });
    },
    { raizSel: raiz, excSel: excecoes },
  );
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
  const todos = await medirControles(page, raiz);
  return todos
    .filter((c) => c.altura < min || c.largura < min)
    .map(({ descricao, tipo, largura, altura }) => ({ descricao, tipo, largura, altura }));
}

/** Um campo de digitação medido: só ALTURA, porque é ela que decide se o dedo acerta a linha. */
export interface Campo {
  descricao: string;
  altura: number;
}

/**
 * Campos de DIGITAÇÃO abaixo do mínimo tocável — `<input>` de texto, `<select>` e `<textarea>`.
 *
 * ⚠️ **Não é `alvosPequenos` com outro nome, e a diferença é o buraco por onde estes campos
 * passaram.** São duas decisões distintas:
 *
 *   - `alvosPequenos` mede ALTURA **e** LARGURA, porque um ícone de 44×16 é tão inatingível
 *     quanto um de 16×44. Aqui a largura não entra: um `<input type="number">` de `w-20` (80px)
 *     para quantidade é uma escolha de layout, não um defeito — o que decide se o dedo acerta a
 *     LINHA certa do formulário é a altura dela.
 *   - `alvosPequenos` varre todo controle (`button`, `a`, `summary`, `[role]`); aqui o conjunto é
 *     só o que se DIGITA. `checkbox`, `radio`, `file`, `color` e `range` ficam de fora por
 *     construção: no repo a caixinha do checkbox tem 20×20 e quem cumpre os 44px é o `<label>`
 *     em volta (`ContasSaldosPage.tsx:208`), e exigir 44 do quadrado desenhado daria um botão
 *     onde deve haver um checkbox.
 *
 * O nome do campo vem do `<label>` que o envolve quando há um — sem isso o vermelho seria uma
 * lista de `input.w-full.rounded-lg...` idênticos e ninguém saberia qual dos treze encolheu.
 *
 * `raiz` recorta a varredura. **Use sempre ao medir um modal**: sem ele a página por trás entra
 * na conta. Escopo que não casa cai no documento inteiro — seletor podre tem de virar ruído,
 * nunca aprovação.
 */
export async function camposBaixos(page: Page, raiz?: string, min = 44): Promise<Campo[]> {
  return page.evaluate(
    ({ raizSel, minimo }) => {
      const SEL =
        'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])' +
        ':not([type="file"]):not([type="color"]):not([type="range"]),select,textarea';
      const escopo: ParentNode = raizSel
        ? (document.querySelector(raizSel) ?? document)
        : document;
      const visivel = (el: Element): boolean => {
        const s = getComputedStyle(el);
        if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      };
      return [...escopo.querySelectorAll(SEL)]
        .filter(visivel)
        .map((el) => {
          const r = el.getBoundingClientRect();
          const rotulo = (el.closest("label")?.textContent ?? "")
            .trim()
            .replace(/\s+/g, " ")
            .slice(0, 40);
          const tag =
            el.tagName.toLowerCase() +
            (el.tagName === "INPUT" ? `[${el.getAttribute("type") ?? "text"}]` : "");
          return { descricao: rotulo ? `${tag} «${rotulo}»` : tag, altura: +r.height.toFixed(1) };
        })
        .filter((c) => c.altura < minimo);
    },
    { raizSel: raiz, minimo: min },
  );
}

/** Um controle que o dedo não alcança. `foraPor` e as bordas são px medidos na viewport. */
export interface Inalcancavel {
  descricao: string;
  esquerda: number;
  direita: number;
  /** Quantos px do controle ficam além da borda alcançável. */
  foraPor: number;
  /** `true` quando NEM A BORDA ESQUERDA entra: o controle não existe para o dedo. */
  inteiramenteFora: boolean;
}

/**
 * Seletores cujo conteúdo esta régua NÃO mede — cada um com a razão escrita, porque allowlist sem
 * razão é exatamente como uma régua vira enfeite.
 *
 * `.react-flow` — a lona do construtor de funis. Os nós e as arestas ficam num `viewport` movido
 * por `transform`, com pan e zoom no dedo: não há `overflow-x` nenhum para esta régua encontrar,
 * e a lona é MAIOR que qualquer tela por construção (a fixture do funil tem um nó em x=900).
 * Medido: sem esta exceção, `/funis/f1` acusa 2 falsos positivos — `g [Edge from n1 to n2]`
 * (81 -> 531) e a `div` do nó de x=900 (493,5 -> 568,5) — que nenhum conserto de layout
 * resolve, porque a lona é para ser navegada e não para caber. Os CONTROLES DE TELA do construtor (cabeçalho, paleta,
 * painel lateral) ficam FORA de `.react-flow` e continuam medidos — é lá que mora o #144.
 */
export const EXCECOES_DE_ALCANCE = [".react-flow"];

/**
 * Controles que o dedo NÃO alcança: terminam além da borda visível e não há nada que role para
 * trazê-los. É a classe do #58 («Estornar» inalcançável) e do #144 («Salvar» do funil começando
 * em x=536 numa tela de 360).
 *
 * ⚠️ **Não é a mesma pergunta que `medirPagina`, e é por isso que este arquivo precisa das duas.**
 * `main` é `overflow-x-hidden` (`AppShell.tsx:64`): conteúdo largo demais é RECORTADO, não empurra
 * o documento, e `document.documentElement.scrollWidth` continua devolvendo 360. A régua do #135
 * mede o que ESCAPA do recorte; esta mede o que fica PRESO atrás dele. O que uma vê, a outra não
 * pode ver — por construção, não por fresta. Daí a página que rola de lado contar aqui como
 * ALCANÇÁVEL: se ela rola, o dono chega ao controle, e o defeito (se houver) é do outro tipo e
 * tem o outro dono.
 *
 * ⚠️ Um ancestral com `overflow-x: auto|scroll` que de fato tenha o que rolar (`scrollWidth >
 * clientWidth`) ABSOLVE o controle: o deslizador da DRE de 12 meses e o Kanban existem para ser
 * deslizados, e uma régua que os acusasse seria descartada na primeira semana — junto com os
 * defeitos de verdade que ela carrega. O que NÃO absolve é um deslizador cuja própria caixa já
 * está fora da tela: ele não tem para onde trazer nada.
 */
export async function controlesInalcancaveis(
  page: Page,
  raiz?: string,
  excecoes: string[] = EXCECOES_DE_ALCANCE,
): Promise<Inalcancavel[]> {
  const todos = await medirControles(page, raiz, excecoes);
  return todos
    .filter((c) => !c.excecao && c.deslizador === null && c.direita > c.limiteDireito + 0.5)
    .map((c) => ({
      descricao: c.descricao,
      esquerda: c.esquerda,
      direita: c.direita,
      foraPor: +(c.direita - c.limiteDireito).toFixed(1),
      inteiramenteFora: c.esquerda >= c.limiteDireito - 0.5,
    }));
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
