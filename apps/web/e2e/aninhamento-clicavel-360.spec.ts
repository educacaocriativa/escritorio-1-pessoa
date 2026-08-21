import { expect, test, type Locator, type Page } from "@playwright/test";
import { mockarApi } from "./support/api";
import { semearSessao } from "./support/sessao";

/**
 * A régua do ANINHAMENTO CLICÁVEL (#160) — o gêmeo estrutural do #149 (PR #159).
 *
 * Três telas de lista montavam a lixeira **dentro** do `<button>` que navega. Além de HTML
 * inválido, isso carrega o mecanismo exato medido no #149: quando dois alvos clicáveis são
 * aninhados, o navegador emite o `click` no **ANCESTRAL COMUM** de `mousedown` e `mouseup`. Um
 * deslocamento de **10px** — o limiar medido no #149, com o trace do CI a 0,1px do cálculo — faz o
 * toque na **lixeira** virar **navegação**, e nada reclama: o hit-target do Playwright está
 * satisfeito, porque o `mousedown` acertou o alvo certo.
 *
 * ⚠️ **Esta régua mede o DESLOCAMENTO, não o CSS nem o markup.** `expect(html).toContain("<div")`
 * seria a família do `toContain("flex-wrap")` que o CLAUDE.md §5.1 proíbe: passaria com a tela
 * quebrada, porque a estrutura pode mudar de nome sem mudar de comportamento. O que esta régua
 * pergunta é a única pergunta que importa para o dedo do dono: *o toque na lixeira, escorregando
 * 10px, disparou a ação do card?*
 *
 * ⚠️ **A lixeira mantém o mesmo tamanho de antes, de propósito.** Engordá-la para os 44px do
 * `alvosPequenos` faria o deslocamento de 10px cair DENTRO dela — e aí a régua mediria o
 * *padding*, não o aninhamento: a mutação que re-aninha os botões SOBREVIVERIA verde. O alvo
 * pequeno é dívida de outra issue; misturar as duas apagaria esta medição.
 *
 * ⚠️ **O gravador de cliques não é enfeite.** Um gesto que não emite `click` nenhum passaria em
 * todas as asserções negativas abaixo — verde por não ter medido nada, o modo de falha do #123.
 * Toda medição aqui exige, ANTES, que o navegador tenha emitido exatamente **1** `click`.
 *
 * ## O chip da `AgendaPage` fica FORA daqui, e a razão foi medida
 *
 * A issue #160 põe o `<div onClick>` dentro do `<button>` da célula do dia (`AgendaPage.tsx:224`,
 * contornado no #159 e não removido) "nesta mesma família". Está certo quanto ao MECANISMO e
 * errado quanto ao TAMANHO da correção — varrendo o mesmo gesto na `/agenda` em 20/08/2026,
 * viewport 360×740, chip de **31,3×20,5px** dentro de uma célula de **44,3×92px**:
 *
 * | deslocamento | alvo do `click` | detalhe (certo) | "Novo evento" (errado) |
 * |---|---|---|---|
 * | 8px | o próprio chip | 1 | 0 |
 * | 10px | o próprio chip | 1 | 0 |
 * | 11px | o próprio chip | 1 | 0 |
 * | **12px** | **o `<button>` da célula** | **0** | **1** |
 * | 14 / 16 / 20px | o `<button>` da célula | 0 | 1 |
 *
 * Ou seja: o defeito é REAL na agenda também, mas o limiar lá é **12px**, não 10 — o chip tem meia
 * altura de 10,25px, e é só isso que o separa. Não entra nesta PR por três motivos medidos:
 *
 * 1. **A correção é de outra natureza.** Nas três listas o alvo interno é um ícone de canto: vira
 *    irmão com `position: absolute` e a caixa não se move (medido — `x`/`y` idênticos antes e
 *    depois). Na agenda os chips são CONTEÚDO no fluxo da célula (até 3 por dia, mais o "+N"),
 *    então desaninhar significa remontar a célula do calendário em camadas, mexendo na geometria
 *    de 35 a 42 células de uma grade que já é apertada em 360px.
 * 2. **Raio de explosão.** `AgendaPage` tem `agenda-evento-360.spec.ts`, `ficha-agenda-360.spec.ts`
 *    e `AgendaPage.test.tsx` em cima dela, e o #159 acabou de mexer nesse arquivo.
 * 3. **É outra decisão de desenho**, com outro limiar (12px) e outra prova por mutação. Juntar as
 *    duas nesta PR misturaria uma correção mecânica de três linhas com um redesenho de grade.
 *
 * Fica como issue própria, com a tabela acima como enunciado pronto.
 */

/** O limiar medido no #149: 10px entre o `mousedown` e o `mouseup` já bastam. */
const DESLOCAMENTO_PX = 10;

/**
 * ⚠️ **O pior caso de §5.1 aqui é o pior caso ALCANÇÁVEL, e a diferença foi medida.**
 *
 * O nome sem espaço de 80 chars que a régua de layout usa (`support/rotas.ts`) empurra a lixeira
 * para **FORA da viewport de 360px** em duas das três telas — e uma lixeira fora da tela não pode
 * ser tocada, então o gesto do #149 não teria o que medir. Medido em 20/08/2026, viewport 360×740:
 *
 * | tela | título | caixa do card | x da lixeira |
 * |---|---|---|---|
 * | `/funis` | 80 chars sem espaço | 312 (a caixa segura) | **760,7** — 400px fora |
 * | `/juridico` | 33 chars com espaço | 312 | 310 ✅ |
 * | `/juridico` | 46 chars com espaço | **399,7** | **397,7** — 38px fora |
 * | `/juridico` | 61 chars com espaço | **468,7** | **466,7** — 107px fora |
 * | `/marketing` | 49 chars com espaço | 148 | 158 ✅ |
 *
 * Esse transbordo é **outro defeito, de outra família** (a do #58/#144, alcançabilidade) e está
 * FORA do alcance do #160 — o `scrollWidth` da página fica em **360** nos cinco casos, então
 * nenhuma régua de LARGURA o enxerga, e `rotas-360.spec.ts` cataloga `/funis` e `/juridico` como
 * rotas VAZIAS, sem dado nenhum na lista. Fica registrado aqui com número, não corrigido aqui.
 *
 * O que este arquivo mede é o ANINHAMENTO, e para isso a lixeira precisa estar na tela — daí a
 * guarda de viewport no `beforeEach`, que faz a régua gritar se a fixture voltar a escapar em vez
 * de passar verde por não ter medido nada.
 */
const NOME_FUNIL = "Captacao de clientes do segundo semestre para o escritorio em 2026";
const TITULO_DOC = "Contrato de prestacao de servicos";
const TOPICO_CARROSSEL = "Captacao de clientes do segundo semestre para 2026";

type JanelaComGravador = Window & { __cliques?: string[] };

/**
 * Grava, com `capture` no `document`, QUAL elemento o navegador escolheu como alvo de cada `click`.
 * É a leitura direta do mecanismo do #149 — o ancestral comum — e não uma inferência a partir do
 * sintoma.
 */
async function armarGravadorDeCliques(page: Page): Promise<void> {
  await page.evaluate(() => {
    const janela = window as Window & { __cliques?: string[] };
    janela.__cliques = [];
    document.addEventListener(
      "click",
      (ev) => {
        const alvo = ev.target as Element | null;
        const marca = alvo?.closest("[data-testid]")?.getAttribute("data-testid") ?? "";
        janela.__cliques?.push(`${alvo ? alvo.tagName.toLowerCase() : "?"}[${marca}]`);
      },
      true,
    );
  });
}

async function lerCliques(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as JanelaComGravador).__cliques ?? []);
}

/**
 * O GESTO do #149: `mousedown` no centro do alvo INTERNO (a lixeira) e `mouseup` deslocado
 * `DESLOCAMENTO_PX` na direção do centro do alvo EXTERNO (o card).
 *
 * A direção é calculada, não chutada: apontar para o centro do card garante que o `mouseup` caia
 * DENTRO da caixa do externo nas duas versões — a desaninhada e a mutante —, que é o que torna a
 * medição comparável. Um deslocamento fixo "para baixo" cairia fora do card em uma das três telas
 * e a régua mediria coisas diferentes em cada uma.
 */
async function toqueQueEscorrega(page: Page, interno: Locator, externo: Locator): Promise<void> {
  const caixaInterna = await interno.boundingBox();
  const caixaExterna = await externo.boundingBox();
  expect(caixaInterna, "a lixeira precisa estar na tela — sem caixa não há gesto").not.toBeNull();
  expect(caixaExterna, "o card precisa estar na tela — sem caixa não há direção").not.toBeNull();

  const x0 = caixaInterna!.x + caixaInterna!.width / 2;
  const y0 = caixaInterna!.y + caixaInterna!.height / 2;
  const dx = caixaExterna!.x + caixaExterna!.width / 2 - x0;
  const dy = caixaExterna!.y + caixaExterna!.height / 2 - y0;
  const norma = Math.hypot(dx, dy) || 1;

  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.mouse.move(x0 + (dx / norma) * DESLOCAMENTO_PX, y0 + (dy / norma) * DESLOCAMENTO_PX);
  await page.mouse.up();
}

/** Coleta os DELETE que a tela disparou — é assim que se pergunta "a lixeira agiu?". */
function coletarDeletes(page: Page): string[] {
  const feitos: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "DELETE") feitos.push(new URL(req.url()).pathname);
  });
  return feitos;
}

interface Tela {
  nome: string;
  rota: string;
  /** Texto que PROVA que a lista desenhou antes de qualquer medição (§5.1: `marca`). */
  marca: string;
  mocks: Record<string, unknown>;
  /** O card que NAVEGA — o alvo externo. */
  externo: string;
  /** A lixeira — o alvo interno. */
  interno: string;
  /** Para onde o card navega quando o toque acerta de verdade. */
  destino: RegExp;
  /** O caminho do DELETE que a lixeira dispara quando o toque acerta de verdade. */
  apagar: string;
}

const ID = "x1";

const TELAS: Tela[] = [
  {
    nome: "funis",
    rota: "/funis",
    marca: "Funis de Vendas",
    mocks: {
      "/funnels": [{ id: ID, name: NOME_FUNIL, node_count: 12, created_at: "2026-08-01T10:00:00Z" }],
    },
    externo: `abrir-funil-${ID}`,
    interno: `excluir-funil-${ID}`,
    destino: /\/funis\/x1$/,
    apagar: `/api/funnels/${ID}`,
  },
  {
    nome: "juridico",
    rota: "/juridico",
    marca: "Assistente Jurídico",
    mocks: {
      "/juridico/skills": [],
      "/juridico/documents": [
        {
          id: ID,
          skill: "contrato",
          category: "contratos",
          title: TITULO_DOC,
          client_id: null,
          client_name: null,
          status: "ready",
          created_at: "2026-08-01T10:00:00Z",
        },
      ],
    },
    externo: `abrir-documento-${ID}`,
    interno: `excluir-documento-${ID}`,
    destino: /\/juridico\/x1$/,
    apagar: `/api/juridico/documents/${ID}`,
  },
  {
    nome: "marketing",
    rota: "/marketing",
    marca: "Carrosséis",
    mocks: {
      "/marketing/carousels": [
        {
          id: ID,
          tenant_id: "t1",
          topic: TOPICO_CARROSSEL,
          platform: "instagram",
          slides: [
            {
              kind: "cover",
              heading: "Diagnostico do escritorio",
              body: "O que muda no segundo semestre",
              secondary: "Fale com a gente",
              highlight: "Diagnostico",
              photo_url: "",
              photo_position: "mid",
            },
          ],
          status: "draft",
          handle: "@escritorio1pessoa",
          caption: TOPICO_CARROSSEL,
          hashtags: "#escritorio1pessoa",
          template: "editorial",
          primary_color: "#123456",
          bg_color: "#ffffff",
          text_color: "#111111",
          accent_color: "#ff0000",
          font: "Inter",
          created_at: "2026-08-01T10:00:00Z",
        },
      ],
    },
    externo: `abrir-carrossel-${ID}`,
    interno: `excluir-carrossel-${ID}`,
    destino: /\/marketing\/x1$/,
    apagar: `/api/marketing/carousels/${ID}`,
  },
];

for (const tela of TELAS) {
  test.describe(`${tela.rota} — lixeira e card não se aninham`, () => {
    test.beforeEach(async ({ page }) => {
      await semearSessao(page);
      await mockarApi(page, tela.mocks);
      await page.goto(tela.rota);
      // A `marca` (§5.1): medir uma tela que renderizou em branco passa em qualquer régua negativa.
      await expect(page.getByRole("heading", { name: tela.marca })).toBeVisible();
      await expect(page.getByTestId(tela.externo)).toBeVisible();
      await expect(page.getByTestId(tela.interno)).toBeVisible();

      // ⚠️ **A guarda de ALCANCE, e ela não é zelo — é a lição do parágrafo lá de cima.** Com a
      // fixture de 80 chars sem espaço, a lixeira ia parar em **x=760,7** numa tela de 360 e o
      // gesto do #149 batia no `<html>`: o card não navegava, o teste ficava VERDE, e o que ele
      // media era o transbordo, não o aninhamento. `toBeVisible()` não acusa isso — o elemento
      // está lá, com caixa e tudo, só que fora da tela.
      const caixa = (await page.getByTestId(tela.interno).boundingBox())!;
      expect(caixa.x, "a lixeira escapou pela ESQUERDA da viewport de 360px").toBeGreaterThanOrEqual(0);
      expect(
        caixa.x + caixa.width,
        "a lixeira escapou pela DIREITA da viewport de 360px — a régua mediria o transbordo, não o aninhamento",
      ).toBeLessThanOrEqual(360);

      // E ela tem de ser MENOR que o deslocamento, senão o escorregão de 10px cai dentro dela e a
      // régua vira um medidor de padding (ver o ⚠️ do cabeçalho).
      expect(
        Math.min(caixa.width, caixa.height) / 2,
        `a lixeira ficou grande demais: o escorregão de ${DESLOCAMENTO_PX}px não sairia dela`,
      ).toBeLessThan(DESLOCAMENTO_PX);
    });

    test(`o toque na lixeira que escorrega ${DESLOCAMENTO_PX}px NÃO dispara a ação do card`, async ({
      page,
    }) => {
      const deletes = coletarDeletes(page);
      await armarGravadorDeCliques(page);

      await toqueQueEscorrega(page, page.getByTestId(tela.interno), page.getByTestId(tela.externo));

      // Controle positivo do INSTRUMENTO, antes de qualquer asserção negativa: o gesto TEM de ter
      // produzido um `click`. Zero cliques passaria em tudo que vem abaixo sem medir nada (#123).
      await expect
        .poll(async () => (await lerCliques(page)).length, {
          message: "o gesto não emitiu click nenhum — a régua não mediu nada",
        })
        .toBe(1);

      // ⚠️ **A segunda metade do controle, e ela foi medida na marra.** Na primeira versão desta
      // régua o deslocamento não SAÍA da lixeira em duas das três telas: o `mouseup` caía dentro
      // dela, o `click` ia para a própria lixeira, o `confirm` era dispensado pelo Playwright e o
      // teste ficava VERDE com o defeito de pé — 14/15 passando contra o código aninhado. Sem esta
      // linha, "a ação do card não aconteceu" não distingue "o aninhamento foi desfeito" de "o
      // gesto nunca chegou a escorregar".
      const [ondeCaiu] = await lerCliques(page);
      expect(
        ondeCaiu,
        `o deslocamento de ${DESLOCAMENTO_PX}px não saiu da lixeira — a régua não mediu o aninhamento`,
      ).not.toContain(tela.interno);

      // A AFIRMAÇÃO da issue: a ação do EXTERNO não aconteceu.
      await expect(page).toHaveURL(new RegExp(`${tela.rota}$`));

      // E nem a do interno: escorregando, o toque não faz NADA — que é o resultado desejado.
      // Antes, ele fazia a coisa ERRADA (navegava), e é essa a troca que a issue #160 compra.
      expect(deletes).toEqual([]);
    });

    test("o toque certeiro na lixeira apaga, e não navega", async ({ page }) => {
      const deletes = coletarDeletes(page);
      page.on("dialog", (d) => d.accept());

      await page.getByTestId(tela.interno).click();

      await expect.poll(() => deletes).toEqual([tela.apagar]);
      await expect(page).toHaveURL(new RegExp(`${tela.rota}$`));
    });

    test("o toque certeiro no card navega", async ({ page }) => {
      await page.getByTestId(tela.externo).click();
      await expect(page).toHaveURL(tela.destino);
    });

    test("os dois alvos são alcançáveis pelo TECLADO, um depois do outro", async ({ page }) => {
      // A metade que a desaninhagem não pode custar. `<button>` dentro de `<button>` é HTML
      // inválido justamente porque quebra a ordem de foco e faz o leitor de tela anunciar os dois
      // controles como um só; trocar esse defeito por um `<div>` mudo seria trocar de defeito.
      await page.getByTestId(tela.externo).focus();
      await expect(page.getByTestId(tela.externo)).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByTestId(tela.interno)).toBeFocused();

      // E a lixeira tem NOME acessível — sem ele, o leitor de tela anuncia "botão" e pronto.
      await expect(page.getByTestId(tela.interno)).toHaveAttribute("aria-label", /excluir/i);
    });

    test("o card ainda navega quando acionado pelo TECLADO", async ({ page }) => {
      await page.getByTestId(tela.externo).focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(tela.destino);
    });
  });
}
