import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O bloco de Conversa da ficha 360° em 360px.
 *
 * O caso que estoura uma bolha de chat não é texto longo — é texto longo SEM ESPAÇO, que não
 * tem onde quebrar. `max-w-[85%]` limita a caixa e não o conteúdo: sem `break-words` o texto
 * transborda a bolha e leva a página junto. É por isso que a mensagem de entrada abaixo é um
 * token contínuo, sem espaço, hífen OU barra — uma URL não bastaria: `/` e `-` são pontos de
 * quebra válidos por padrão do navegador (UAX #14), e um `lorem ipsum` teria espaço sobrando.
 *
 * ⚠️ Esta falta de espaço, hífen e barra também expôs um ponto cego em `textoForaDaTela`
 * (`support/medidas.ts`): um bloco sem `width` própria mantém a CAIXA no tamanho do contêiner
 * mesmo quando o texto não tem onde quebrar — a tinta vaza da caixa sem alargá-la, e
 * `getBoundingClientRect` só vê caixa, não tinta. Como a ficha vive dentro do `<main
 * overflow-x-hidden>` do `AppShell`, essa tinta era cortada em silêncio: nem a página rolava,
 * nem a varredura via nada, e o teste passava com o texto de fato cortado no meio da palavra
 * (confirmado por screenshot antes do conserto). `textoForaDaTela` agora também compara
 * `scrollWidth` com `clientWidth` do próprio elemento — corrigido ali, não afrouxado aqui.
 */
const CONVERSA = {
  chat_id: "chat-1",
  kind: "direct",
  title: "Ju",
  phone: "554384035398",
  client_id: "c1",
  last_message_at: "2026-08-15T23:16:00Z",
  last_message_preview: "Boa noite",
  unread: false,
};

const fixtures = {
  "/crm/clients/c1": {
    id: "c1", tenant_id: "t1", name: "Ju", email: null, phone: "554384035398",
    document: null, gender: "unspecified", birthdate: null, notes: "", tags: [],
    source: "whatsapp", stage_id: "s1", stage_entered_at: "2026-08-15T12:00:00Z",
    created_at: "2026-08-15T12:00:00Z",
  },
  "/whatsapp-conversations/chat-1/timeline": [
    {
      source: "conversation", direction: "in", kind: "text",
      text_body: "aReallyLongTokenWithNoSpacesSlashesOrHyphensThatSimulatesAWorstCasePayload1234567890",
      media_attachment_id: null, purpose_label: null, sender_name: null,
      created_at: "2026-08-15T23:10:00Z",
    },
    {
      source: "conversation", direction: "out", kind: "text",
      text_body: "Oi Ju! Aqui é do Doro Eventos. Recebemos seu contato e vamos te chamar pelo nosso número oficial.",
      media_attachment_id: null, purpose_label: null, sender_name: null,
      created_at: "2026-08-15T23:16:00Z",
    },
  ],
  "/whatsapp-conversations": [CONVERSA],
  // Mapeado de propósito: sem esta chave, o prefixo mais longo que casa é `/crm/clients/c1` e
  // o `ClientTimeline` receberia o OBJETO do cliente onde espera `{entries, truncated}`. Ele
  // degrada em vez de quebrar (`Array.isArray(data?.entries)`), mas o teste estaria medindo
  // uma ficha sem Histórico — ou seja, uma tela mais curta que a real.
  "/crm/clients/c1/timeline": { entries: [], truncated: false },
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, fixtures);
});

test("a conversa na ficha cabe em 360px, mesmo com texto sem espaço", async ({ page }) => {
  await page.goto("/crm/clients/c1");

  await expect(page.getByRole("link", { name: "Abrir conversa" })).toBeVisible();

  // A PÁGINA não rola de lado. A ficha é uma coluna só — aqui, ao contrário do board, rolagem
  // horizontal é defeito e não recurso.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);

  // Varredura escopada à seção da conversa, com o controle positivo de sempre.
  //
  // ⚠️ O `<Section>` de `ClientDetailPage` é o MESMO componente para as sete seções da ficha
  // (Histórico, Conversa, Cobranças, Contratos...) — todas renderizam `div.rounded-2xl.bg-white`,
  // e `querySelector` devolve só a PRIMEIRA ocorrência no documento (mesma lógica do `.w-72` do
  // `crm-360.spec.ts`, que pega a primeira coluna). Nesta página a primeira `.rounded-2xl.bg-white`
  // é o CABEÇALHO do cliente (linha 86 do componente), não a Conversa — um seletor de classe
  // teria medido a seção errada em silêncio. Por isso a seção ganhou `data-testid="secao-conversa"`.
  expect(await textoForaDaTela(page, '[data-testid="secao-conversa"]')).toEqual([]);

  // CONTROLE POSITIVO — mas diferente do `crm-360.spec.ts`. Lá o seletor podre cai no documento
  // inteiro e pesca a segunda coluna do Kanban, que fica fora da tela DE PROPÓSITO. Aqui não: a
  // ficha é coluna única e, correta, não tem NENHUM corte em lugar nenhum da página — não existe
  // conteúdo fora da tela por acidente para o seletor podre encontrar. Por isso o controle planta,
  // só para o instante desta asserção, um texto sem filhos fora da tela: prova de que a função
  // ENXERGA corte nesta página quando ele existe — e não que a fixture por acaso nunca produz um.
  // O `<span>` acima é INLINE — some do DOM sozinho quando o Playwright fecha o contexto de
  // teste ao final (não há `marca.remove()`: cada teste roda numa página nova). Ele só prova o
  // caminho ANTIGO (`r.right`), o de sempre: inline reporta `scrollWidth === clientWidth === 0`,
  // então nunca cai no ramo `scrollWidth`.
  await page.evaluate(() => {
    const marca = document.createElement("span");
    marca.textContent = "marca de controle positivo";
    marca.style.cssText = "position:absolute;left:9999px;top:0;white-space:nowrap;";
    marca.setAttribute("data-marca-controle-positivo", "");
    document.body.appendChild(marca);
  });
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);
});

test("textoForaDaTela pega bloco SEM largura própria que vaza via scrollWidth", async ({ page }) => {
  // Controle positivo do ramo NOVO (`scrollWidth`), que o teste acima não cobre: o `<span>` dele
  // é inline e nunca cai nesse ramo (ver comentário lá). Revertendo `medidas.ts` para o
  // `r.right` puro (o Finding 2 do review final), aquele teste continua passando — SEM
  // ESTE aqui, o ponto cego que a Onda 1 fechou reabriria em silêncio.
  //
  // O elemento é um `<div>` de BLOCO (não `<span>`), sem `width` própria — herda a do contêiner
  // por `display:block` — com um token sem espaço, hífen ou barra: não tem onde quebrar. É o
  // cenário real que a bolha de chat expôs antes do `break-words` (ver o comentário no topo
  // deste arquivo): a CAIXA fica presa na largura do contêiner, a tinta vaza sem alargá-la, e
  // `getBoundingClientRect().right` não vê nada — só `scrollWidth` vê.
  await page.goto("/crm/clients/c1");
  await expect(page.getByRole("link", { name: "Abrir conversa" })).toBeVisible();

  await page.evaluate(() => {
    const bloco = document.createElement("div");
    bloco.textContent =
      "blocoDeTesteSemLarguraPropriaComUmTokenBemLongoSemEspacoQueVazaViaScrollWidth1234567890";
    bloco.setAttribute("data-marca-scrollwidth-bloco", "");
    document.querySelector('[data-testid="secao-conversa"]')?.appendChild(bloco);
  });

  const cortes = await textoForaDaTela(page, '[data-testid="secao-conversa"]');
  const achado = cortes.find((c) => c.texto.startsWith("blocoDeTesteSemLarguraPropria"));
  expect(achado).toBeDefined();
  expect(achado!.forcaFora).toBeGreaterThan(0);
});
