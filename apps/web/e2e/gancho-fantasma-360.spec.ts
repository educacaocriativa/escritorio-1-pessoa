import { expect, test, type Page } from "@playwright/test";
import { mockarApi } from "./support/api";
import { semearSessao } from "./support/sessao";

/**
 * O GUARDA do default `"/dna/pendente": null` de `support/api.ts` (#164).
 *
 * `mockarApi` responde `[]` para toda rota não mapeada. `[]` é **verdadeiro** em JS, e
 * `GanchoDaVima` faz `setPergunta(data ?? null)` — a guarda `if (!pergunta) return null` não pega,
 * e SEIS telas (`agenda`, `cobrancas`, `crm`, `orcamentos`, `pagar`, `vima`) ganham um card que a
 * produção nunca monta. O PR #159 neutralizou o gatilho com uma linha no `PADROES`, e até aqui
 * **nada guardava essa linha**: medido no #164, removê-la deixava `agenda-evento-360` inteiro verde
 * (12 passed, `--repeat-each=3`), com as réguas de 360px medindo 101px de tela que não existe.
 *
 * ⚠️ **QUAL MUTAÇÃO ESTE ARQUIVO MATA — e qual ele DEIXOU de matar quando o #161 entrou.**
 *
 * | mutação no `PADROES` | antes do #161 | HOJE (guarda apertada em `main`) |
 * |---|---|---|
 * | apagar `"/dna/pendente": null` | mata os 2 | **SOBREVIVE — mutante equivalente** |
 * | trocar por payload de FORMA VÁLIDA | mata os 2 | **mata os 2** |
 *
 * Ambas as linhas foram MEDIDAS: a primeira contra a branch do #164 com a guarda ainda frouxa, e as
 * duas de novo em 2026-08-21 contra o `main` que já contém o #161 (PR #176). O `[]` deixou de virar
 * card porque `ehPergunta` o rejeita, então não há mais empurrão de 101px para medir por esse
 * caminho — e exigir morte de mutante equivalente só produziria teste que fixa literal sem
 * consequência.
 *
 * O que este arquivo guarda HOJE, e não é pouco: **a fixture PADRÃO não monta card do Gancho,
 * qualquer que seja o caminho**. O mock deixou de ser a única linha de defesa (o componente virou a
 * primeira), mas continua sendo o que faz as réguas de 360px medirem a tela que a produção produz.
 *
 * ⚠️ **UMA rota, não as seis.** O alvo é UMA linha de UM arquivo compartilhado, e as seis telas
 * chamam o MESMO endpoint (`/dna/pendente`, casado por prefixo de caminho, não por rota). Não
 * existe mutação que seis asserções matem e uma não — seriam seis mortes do mesmo mutante, a
 * ~1s/spec com `workers: 1`. O que acrescenta poder de morte aqui não é a segunda rota: é o
 * CONTROLE POSITIVO abaixo. Sem ele, `toHaveCount(0)` não distingue "o card não existe" de "o
 * seletor não vê card nenhum" — a armadilha do #123, e a família do `toContain("flex-wrap")`.
 *
 * A rota escolhida é a `/agenda` porque é onde o empurrão foi MEDIDO (#159: `main` 781→681) e onde
 * o card é o PRIMEIRO filho da página (`AgendaPage.tsx:93`), logo o empurrão é lido direto na
 * ordenada do cabeçalho, sem intermediário.
 */

/**
 * O único marcador comum ao card FANTASMA e ao card de verdade.
 *
 * Com `[]`, `pergunta.texto` e `pergunta.formato` são `undefined`: não há enunciado nem opções, e
 * sobram só o subtítulo da classe e este botão. Um seletor pelo enunciado veria o card real e NÃO
 * veria o fantasma — mediria a metade errada.
 */
const cardDoGancho = (page: Page) => page.getByRole("button", { name: "Responder depois" });

/** Ordenada do cabeçalho da Agenda — o primeiro elemento DEPOIS do gancho. */
async function topoDoCabecalho(page: Page): Promise<number> {
  const caixa = await page.getByRole("button", { name: "Hoje" }).boundingBox();
  expect(caixa).not.toBeNull();
  return caixa!.y;
}

async function abrirAgenda(page: Page, respostas: Record<string, unknown> = {}): Promise<void> {
  await mockarApi(page, respostas);
  await page.goto("/agenda");
  // A tela TEM de existir antes de ser medida: uma /agenda que não renderizou também devolve
  // "nenhum card" e passaria verde por não ter desenhado nada.
  await expect(page.getByRole("button", { name: "Hoje" })).toBeVisible();
}

/** Forma real de `DnaPergunta` (`packages/shared-types`), como o servidor devolve. */
const PERGUNTA = {
  key: "ritmo.card_parado_dias",
  classe: "calibracao",
  eixo: "ritmo",
  texto: "A partir de quantos dias parado um card te incomoda?",
  formato: "escolha",
  opcoes: [
    { rotulo: "5 dias", valor: 5 },
    { rotulo: "10 dias", valor: 10 },
  ],
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
});

test("a fixture padrão não monta o card do Gancho na /agenda", async ({ page }) => {
  await abrirAgenda(page);
  await expect(
    cardDoGancho(page),
    "a fixture padrão passou a montar o card do Gancho na /agenda. O default `/dna/pendente: null` de `support/api.ts` caiu, ou foi trocado por um payload de forma válida — e as réguas de 360px destas seis telas voltaram a medir ~101px de tela que a produção não produz (#164). NÃO é mais o `[]`: desde o #161 o próprio componente o rejeita.",
  ).toHaveCount(0);
});

test("controle positivo: a régua enxerga o card do Gancho, e ele empurra a tela", async ({
  page,
}) => {
  // Sem card: a linha de base. Se esta asserção cair, o número de baixo não significa nada.
  await abrirAgenda(page);
  await expect(cardDoGancho(page)).toHaveCount(0);
  const semCard = await topoDoCabecalho(page);

  // Com card: a MESMA tela, com o endpoint devolvendo o que a produção devolve quando há pergunta
  // do dia. `unrouteAll` porque `mockarApi` registra um `page.route` novo a cada chamada.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await abrirAgenda(page, { "/dna/pendente": PERGUNTA });
  await expect(cardDoGancho(page)).toBeVisible();
  const comCard = await topoDoCabecalho(page);

  // Medido nesta rota em 20/08/2026: **269px** — este é o card CHEIO (enunciado + duas opções),
  // maior que o fantasma. O fantasma do `[]` não tem enunciado nem opções e empurra os **101px**
  // que o #159 mediu. A exigência aqui é só que o empurrão EXISTA e seja da ordem de grandeza dos
  // dois: prender o número exato transformaria qualquer ajuste de padding do card num vermelho que
  // não é defeito, e o piso de 50px já é intransponível para "o card não apareceu".
  expect(comCard - semCard).toBeGreaterThan(50);
});
