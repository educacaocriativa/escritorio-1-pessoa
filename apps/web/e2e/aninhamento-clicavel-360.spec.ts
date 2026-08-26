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
 * A folga que a régua EXIGE entre a distância de saída da lixeira e o deslocamento do gesto — a
 * correção do #190, reforçada pelo #235.
 *
 * ⚠️ **Este número não é gosto, é o teto que a geometria de hoje permite.** Medido em 25/08/2026,
 * viewport 360×740, contra o HEAD desta branch:
 *
 * | tela | caixa da lixeira | direção do gesto | saída no eixo | folga para os 10px |
 * |---|---|---|---|---|
 * | `/funis` | 14 × 14 | (−1,000 · 0,000) | 7,00 | 3,00 |
 * | `/juridico` | 14 × 14 | (−0,997 · 0,080) | 7,02 | 2,98 |
 * | `/marketing` | 14 × 14 | (−0,376 · −0,927) | 7,56 | **2,44** |
 *
 * ⚠️ **O #235 encontrou o `/funis` com folga ZERO, não "pouca" — e é isso que esta linha
 * conserta.** Antes, a lixeira do `/funis` era `Trash2 size={16}`, 2px maior que as outras duas, e
 * centrada verticalmente no card (`top-1/2 -translate-y-1/2`, `dy = 0`, direção horizontal pura):
 * a saída dava `16/2 = 8,00` — o MESMO valor do teto de então (`10 - MARGEM_PX(2) = 8`). Qualquer
 * diferença sub-pixel na direção do gesto empurrava a asserção para o vermelho, e foi exatamente
 * isso que o CI (Ubuntu, medindo 8,035) mostrou contra este mesmo checkout (Windows, medindo
 * 8,0000 exatos) — mesmo código, máquinas diferentes. `FunisPage.tsx` foi alinhado para
 * `Trash2 size={14}`, igualando `/juridico` e `/marketing`; agora é o `/marketing` quem fixa o
 * teto, com 2,44px de folga — longe o bastante do zero para sobreviver a ruído sub-pixel entre
 * máquinas.
 *
 * ⚠️ **Encolher para 14px não colide com a régua de alvo tocável (44px — `toque-360.spec.ts` /
 * `alvosPequenos` em `support/medidas.ts`).** Nenhuma das duas mede `/funis`, `/juridico` ou
 * `/marketing`: elas cobrem `/financeiro/contas`, `/config` e `/financeiro/centros-custo`. A
 * lixeira desta família já era 14×14 em duas das três telas ANTES desta correção, e o ⚠️ no topo
 * deste arquivo ("a lixeira mantém o mesmo tamanho de antes, de propósito") já registrava essa
 * classe de alvo como dívida de toque CONHECIDA e deliberadamente fora do escopo desta régua —
 * engordá-la para 44px faria o deslocamento de 10px cair DENTRO dela, e a mutação que re-aninha os
 * botões sobreviveria verde. Encolher 2px dentro da MESMA classe de dívida já registrada não piora
 * nada que uma régua meça hoje: é dívida de outra issue tanto antes quanto depois do #235.
 *
 * `MARGEM_PX = 3` (o número sugerido na issue original do #190) continuaria devolvendo folga ZERO
 * no `/funis` mesmo com a lixeira em 14px (`saida = 7,00`, teto `10 - 3 = 7`) — o defeito voltaria
 * pela mesma porta, só que "resolvido" no papel. `MARGEM_PX = 2` é o que sobra de folga REAL nas
 * três rotas depois do encolhimento, com o `/marketing` (2,44px) como novo pior caso.
 *
 * ⚠️ **A linha do `/marketing` da issue original (direção −0,803 · −0,596, saída 8,72) NÃO se
 * reproduz, e a razão é estrutural.** O `git diff` desta branch não toca `features/marketing`,
 * `features/juridico` nem `components/` — só `features/funis/FunisPage.tsx`. E a altura do card do
 * `/marketing` não é negociável com o renderizador: o `CarouselThumb` passa `display = 240` para o
 * `ScaledSlide`, que fixa `height: H * scale = 1350 × (240/1080) = 300px` em estilo **inline**. Com
 * a miniatura de 300px o vetor fica quase vertical (`|uy| = 0,927`) e a saída, 7,56. Os 8,72 só
 * saem de um card de ~148×113, que essa geometria não produz.
 *
 * ⚠️ **O ganho do #190 não é o número, é a implicação.** A guarda velha (`min(w,h)/2`) podia
 * PASSAR afirmando 7 enquanto o gesto precisava de 8,72 — ela media uma grandeza que é sempre ≤ a
 * que importa. Com a guarda nova, "a guarda passou" implica "o gesto sai da lixeira com folga de
 * pelo menos 2px". Quando a folga acabar, a régua reprova **aqui**, no `beforeEach`, com
 * a mensagem que aponta o conserto — e não 30 linhas adiante, no alvo do clique, com a mensagem
 * que custou a investigação do #177.
 */
const MARGEM_PX = 2;

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

/** A caixa que o `boundingBox()` devolve — só os campos que a geometria abaixo usa. */
interface Caixa {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * A DIREÇÃO do gesto do #149: do centro do alvo INTERNO (a lixeira) para o centro do alvo EXTERNO
 * (o card), normalizada.
 *
 * A direção é calculada, não chutada: apontar para o centro do card garante que o `mouseup` caia
 * DENTRO da caixa do externo nas duas versões — a desaninhada e a mutante —, que é o que torna a
 * medição comparável. Um deslocamento fixo "para baixo" cairia fora do card em uma das três telas
 * e a régua mediria coisas diferentes em cada uma.
 *
 * ⚠️ **Ela é uma função COMPARTILHADA de propósito, e isso é metade da correção do #190.** Antes,
 * a guarda do `beforeEach` calculava a SUA grandeza (`min(w,h)/2`) e o gesto calculava a DELE —
 * então as duas podiam divergir, e divergiam: no `/marketing` de `f41e134` a guarda afirmava 7
 * onde o gesto precisava de 8,72. Com um só cálculo de direção, guarda e gesto não têm como medir
 * gestos diferentes.
 */
function escorregaoDe(
  caixaInterna: Caixa,
  caixaExterna: Caixa,
): { x0: number; y0: number; ux: number; uy: number } {
  const x0 = caixaInterna.x + caixaInterna.width / 2;
  const y0 = caixaInterna.y + caixaInterna.height / 2;
  const dx = caixaExterna.x + caixaExterna.width / 2 - x0;
  const dy = caixaExterna.y + caixaExterna.height / 2 - y0;
  const norma = Math.hypot(dx, dy) || 1;
  return { x0, y0, ux: dx / norma, uy: dy / norma };
}

/**
 * Quanto o `mouseup` precisa andar, **na direção do gesto**, para sair da caixa da lixeira.
 *
 * Escorregando ao longo do unitário `(ux, uy)` a partir do centro, a borda vertical é cruzada em
 * `(w/2)/|ux|` e a horizontal em `(h/2)/|uy|`; sai-se da caixa na PRIMEIRA das duas:
 *
 * ```
 * saida = min( (w/2)/|ux| , (h/2)/|uy| )
 * ```
 *
 * ⚠️ **É esta a grandeza que a régua precisa, e a guarda velha media outra.** `min(w,h)/2` é a
 * saída na melhor direção possível (a paralela ao lado menor), logo é **sempre ≤** `saida`. Uma
 * guarda sistematicamente otimista pode passar enquanto o gesto NÃO sai — que é exatamente o
 * vermelho do #177: o `mouseup` caiu na borda, o `click` foi para o próprio `svg` da lixeira e a
 * régua morreu no meio da asserção, sem dizer o que consertar (#190).
 *
 * ⚠️ **Eixo zero devolve `Infinity`, e isso é a resposta CERTA, não um caso de borda.** No
 * `/funis` a lixeira é centrada verticalmente no card (`top-1/2 -translate-y-1/2`), então `dy = 0`
 * e `uy = 0`: andando na horizontal pura **nunca** se cruza a borda de cima nem a de baixo, e
 * `Infinity` no `min` deixa o eixo X decidir.
 *
 * ⚠️ **Medido: com o `Math.abs` no denominador, apagar este ramo é um MUTANTE EQUIVALENTE.**
 * `8/Math.abs(+0)` e `8/Math.abs(-0)` dão os dois `Infinity` (`Math.abs(-0)` é `+0`), então a
 * conta não muda. O ramo fica como documentação executável do caso `uy = 0` — e como aviso: é o
 * `Math.abs` que segura a armadilha, porque `8/-0` cru devolve **`-Infinity`**, e um `-Infinity`
 * no `min` faria esta guarda passar calada contra qualquer caixa. Daí o piso do `beforeEach`.
 */
function distanciaDeSaida(caixaInterna: Caixa, caixaExterna: Caixa): number {
  const { ux, uy } = escorregaoDe(caixaInterna, caixaExterna);
  const saidaEmX = ux === 0 ? Infinity : caixaInterna.width / 2 / Math.abs(ux);
  const saidaEmY = uy === 0 ? Infinity : caixaInterna.height / 2 / Math.abs(uy);
  return Math.min(saidaEmX, saidaEmY);
}

/**
 * O GESTO do #149: `mousedown` no centro do alvo INTERNO (a lixeira) e `mouseup` deslocado
 * `DESLOCAMENTO_PX` na direção dada por `escorregaoDe` — a mesma que a guarda do `beforeEach` usa
 * para conferir se esse deslocamento SAI da lixeira.
 */
async function toqueQueEscorrega(page: Page, interno: Locator, externo: Locator): Promise<void> {
  const caixaInterna = await interno.boundingBox();
  const caixaExterna = await externo.boundingBox();
  expect(caixaInterna, "a lixeira precisa estar na tela — sem caixa não há gesto").not.toBeNull();
  expect(caixaExterna, "o card precisa estar na tela — sem caixa não há direção").not.toBeNull();

  const { x0, y0, ux, uy } = escorregaoDe(caixaInterna!, caixaExterna!);

  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.mouse.move(x0 + ux * DESLOCAMENTO_PX, y0 + uy * DESLOCAMENTO_PX);
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

      // ⚠️ **E o escorregão tem de SAIR da lixeira, com folga — a correção do #190.** Se o
      // `mouseup` cai dentro dela, o `click` vai para a própria lixeira, o `confirm` é dispensado
      // pelo Playwright e a régua fica VERDE com o defeito de pé (foi assim que a primeira versão
      // passou 14/15 contra o código aninhado). A grandeza é a distância de saída NO EIXO DO
      // GESTO, não `min(w,h)/2`: aquela é a saída na melhor direção possível, é sempre ≤ esta, e
      // por isso podia passar afirmando 7 onde o gesto precisava de 8,72.
      //
      // O `MARGEM_PX` transforma o fio da navalha em reprovação LEGÍVEL: quando a caixa crescer, a
      // régua morre aqui, com "a lixeira ficou grande demais", em vez de morrer no meio da
      // asserção do alvo do clique — a falha que *parece* regressão que o #162 cataloga.
      const caixaDoCard = (await page.getByTestId(tela.externo).boundingBox())!;
      const saida = distanciaDeSaida(caixa, caixaDoCard);
      // ⚠️ **Antes do teto, o PISO — e ele não é zelo, é o que impede a guarda de emudecer.**
      // `saida` divide meia-extensão por `|u| ≤ 1`, então é, por construção, **≥ `min(w,h)/2`**.
      // Um erro de sinal na fórmula (perder o `Math.abs`, trocar a direção) devolveria número
      // NEGATIVO, o teto abaixo passaria sempre, e o #190 estaria de volta — uma guarda calada,
      // que é exatamente o defeito que esta PR conserta. Medido: sem esta linha, apagar o
      // `Math.abs` deixa as três telas VERDES com a guarda neutralizada.
      expect(
        saida,
        `a fórmula da saída devolveu ${saida.toFixed(2)}px, menos que os ` +
          `${(Math.min(caixa.width, caixa.height) / 2).toFixed(2)}px de min(w,h)/2 — isso é ` +
          `impossível nesta geometria: quem está errada é a CONTA, não a tela`,
      ).toBeGreaterThanOrEqual(Math.min(caixa.width, caixa.height) / 2);

      expect(
        saida,
        `a lixeira ficou grande demais: sair dela na direção do gesto custa ${saida.toFixed(2)}px, ` +
          `e o escorregão do #149 é de ${DESLOCAMENTO_PX}px — sobram menos que os ${MARGEM_PX}px de ` +
          `folga que a régua exige. Encolha a caixa da lixeira (ou reveja a direção do gesto); ` +
          `NÃO aumente o deslocamento, que é a medição do #149 sobre o mundo real`,
      ).toBeLessThanOrEqual(DESLOCAMENTO_PX - MARGEM_PX);
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
