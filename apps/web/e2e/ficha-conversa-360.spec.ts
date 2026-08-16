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
  await page.evaluate(() => {
    const marca = document.createElement("span");
    marca.textContent = "marca de controle positivo";
    marca.style.cssText = "position:absolute;left:9999px;top:0;white-space:nowrap;";
    marca.setAttribute("data-marca-controle-positivo", "");
    document.body.appendChild(marca);
  });
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);
});
