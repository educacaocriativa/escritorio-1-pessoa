import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { medirPagina, textoForaDaTela } from "./support/medidas";
import { semearSessao } from "./support/sessao";

/**
 * O bloco de Agenda da ficha 360° em 360px.
 *
 * `BlocoDaAgenda` (Onda 2, Task 6) é o irmão mais novo de `BlocoDaConversa` (Onda 1) — e o
 * título do compromisso, ao contrário do nome do card do Kanban (`crm-360.spec.ts`), NÃO tem
 * `truncate`: `<p className="text-sm font-medium text-neutral-800">{e.title}</p>` é texto de
 * bloco cru. Um título comprido SEM espaço — sem onde quebrar — é o caso que estoura de
 * verdade, não por elipse faltando e sim por ausência de `break-words`: o mesmo defeito que a
 * bolha de chat da Conversa já tinha (ver o comentário em `ficha-conversa-360.spec.ts`).
 */
const EVENTO_CURTO = {
  id: "ev-1",
  tenant_id: "t1",
  title: "Prova do vestido",
  description: "",
  kind: "atendimento",
  status: "scheduled",
  priority: "normal",
  source: "manual",
  starts_at: "2026-08-20T13:00:00Z",
  ends_at: "2026-08-20T14:00:00Z",
  all_day: false,
  location: "",
  meeting_url: null,
  guests: [],
  amount_cents: null,
  external_ref: null,
  google_event_id: null,
  client_id: "c1",
  client_name: "Ju",
  created_by_ai: false,
  created_at: "2026-08-15T10:00:00Z",
};

// Pior caso plausível: SEM espaço, hífen OU barra — mesma exigência de `ficha-conversa-360.spec.ts`.
// Um `lorem ipsum` teria espaço sobrando; uma URL teria `/`, ponto de quebra válido por padrão
// do navegador (UAX #14). Um compromisso de casamento com nome comprido de fornecedor grudado
// é o cenário real: o dono digitando rápido, sem espaço entre as palavras.
const EVENTO_SEM_ESPACO = {
  id: "ev-2",
  tenant_id: "t1",
  title:
    "ReuniaoDeAlinhamentoFinalDoCasamentoComTodosOsFornecedoresEEquipeCompletaUrgentissimo1234567890",
  description: "",
  kind: "atendimento",
  status: "scheduled",
  priority: "high",
  source: "manual",
  starts_at: "2026-08-22T13:00:00Z",
  ends_at: "2026-08-22T14:00:00Z",
  all_day: false,
  location: "",
  meeting_url: null,
  guests: [],
  amount_cents: null,
  external_ref: null,
  google_event_id: null,
  client_id: "c1",
  client_name: "Ju",
  created_by_ai: false,
  created_at: "2026-08-15T10:00:00Z",
};

const fixtures = {
  "/crm/clients/c1": {
    id: "c1", tenant_id: "t1", name: "Ju", email: null, phone: "554384035398",
    document: null, gender: "unspecified", birthdate: null, notes: "", tags: [],
    source: "whatsapp", stage_id: "s1", stage_entered_at: "2026-08-15T12:00:00Z",
    created_at: "2026-08-15T12:00:00Z",
  },
  // Mesmo motivo do `ficha-conversa-360.spec.ts`: sem esta chave, `/crm/clients/c1` (prefixo
  // mais longo disponível) engoliria `/crm/clients/c1/timeline` e o `ClientTimeline` receberia
  // o cliente onde espera `{entries, truncated}` — a ficha ficaria mais curta que a real.
  "/crm/clients/c1/timeline": { entries: [], truncated: false },
  // `BlocoDaAgenda` chama `GET /agenda/events?client_id=c1&start=...&exclude_cancelled=true`;
  // o mock casa por PREFIXO de pathname (query descartada), então uma chave basta para as duas
  // consultas que a página faz aqui.
  "/agenda/events": [EVENTO_CURTO, EVENTO_SEM_ESPACO],
};

test.beforeEach(async ({ page }) => {
  await semearSessao(page);
  await mockarApi(page, fixtures);
});

test("a agenda cabe em 360px, mesmo com um compromisso de título sem espaço", async ({ page }) => {
  await page.goto("/crm/clients/c1");

  await expect(page.getByText("Prova do vestido")).toBeVisible();

  // O botão "Marcar com este cliente" fica AO LADO da lista, dentro da mesma seção — tem de
  // estar INTEIRO dentro da tela, não só presente no DOM.
  const marcar = page.getByRole("button", { name: "Marcar com este cliente" });
  await expect(marcar).toBeVisible();
  const caixaDoBotao = await marcar.boundingBox();
  expect(caixaDoBotao).not.toBeNull();
  expect(caixaDoBotao!.x).toBeGreaterThanOrEqual(0);
  expect(caixaDoBotao!.x + caixaDoBotao!.width).toBeLessThanOrEqual(360);

  // A PÁGINA não rola de lado — a ficha é coluna única, igual à Conversa.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);

  // Varredura escopada à seção da Agenda. As OITO seções da ficha compartilham
  // `rounded-2xl bg-white`, e `querySelector` devolve só a PRIMEIRA ocorrência do documento —
  // aqui, o cabeçalho do cliente, não a Agenda. Por isso a seção ganhou
  // `data-testid="secao-agenda"` (`ClientDetailPage.tsx`), mesmo motivo da Conversa.
  expect(await textoForaDaTela(page, '[data-testid="secao-agenda"]')).toEqual([]);

  // CONTROLE POSITIVO. A ficha, correta, não tem NENHUM corte em lugar nenhum da página — não
  // existe conteúdo fora da tela por acidente para um seletor podre achar sozinho. Por isso o
  // controle planta, só para o instante desta asserção, um texto sem filhos fora da tela: prova
  // de que a função ENXERGA corte nesta página quando ele existe, e não que a fixture por acaso
  // nunca produz um. Inline, some sozinho quando o Playwright fecha o contexto ao final do teste.
  await page.evaluate(() => {
    const marca = document.createElement("span");
    marca.textContent = "marca de controle positivo";
    marca.style.cssText = "position:absolute;left:9999px;top:0;white-space:nowrap;";
    marca.setAttribute("data-marca-controle-positivo", "");
    document.body.appendChild(marca);
  });
  expect(await textoForaDaTela(page, ".seletor-que-nao-existe")).not.toEqual([]);
});

test("o título sem espaço não vaza pela caixa do compromisso", async ({ page }) => {
  // Prova direta do `scrollWidth` do PRÓPRIO parágrafo do título — não só a ausência de corte
  // na varredura da seção. Mesma régua do `crm-360.spec.ts` para a linha de próximo passo do
  // card, mas o SENTIDO da prova é o oposto: lá `scrollWidth > clientWidth` prova que a
  // reticência ENGATOU (o `truncate` funcionando); aqui prova que o texto NÃO transbordou —
  // porque este parágrafo não tem `truncate`, tem `break-words`: o conserto é ele quebrar a
  // palavra, não escondê-la atrás de "...".
  await page.goto("/crm/clients/c1");

  const titulo = page.getByText(EVENTO_SEM_ESPACO.title.slice(0, 40), { exact: false });
  await expect(titulo).toBeVisible();

  const [scrollWidth, clientWidth] = await titulo.evaluate((el) => [el.scrollWidth, el.clientWidth]);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 0.5);
});
