import { expect, test } from "@playwright/test";
import { mockarApi } from "./support/api";
import { alvosPequenos, medirPagina, textoForaDaTela } from "./support/medidas";
import { agendaEvent as evento } from "./support/fixtures";
import { semearSessao } from "./support/sessao";

/**
 * O seletor de horário ("Marcar com este cliente") em 360px.
 *
 * É o controle mais denso que a ficha 360° ganhou: uma grade de SETE colunas dentro de um modal.
 * Sete colunas é a única forma do calendário que não dá para negociar — e é exatamente o tipo de
 * layout que passa numa asserção de classe CSS (`grid-cols-7` está lá!) enquanto some pela borda
 * da tela do dono. Aqui tudo é medido em pixel.
 */


const fixtures = {
  "/crm/clients/c1": {
    id: "c1", tenant_id: "t1", name: "Ju", email: null, phone: "554384035398",
    document: null, gender: "unspecified", birthdate: null, notes: "", tags: [],
    source: "whatsapp", stage_id: "s1", stage_entered_at: "2026-08-15T12:00:00Z",
    created_at: "2026-08-15T12:00:00Z",
  },
  "/crm/clients/c1/timeline": { entries: [], truncated: false },
  // Pior caso plausível para o PAINEL DO DIA: um título sem espaço nenhum, do mesmo naipe do que
  // `ficha-agenda-360.spec.ts` usa na lista — só que aqui ele divide a linha com a coluna de
  // horário, e sobra menos largura para quebrar.
  "/agenda/events": [
    evento(),
    evento({
      id: "ev-2",
      title:
        "ReuniaoDeAlinhamentoFinalDoCasamentoComTodosOsFornecedoresEEquipeCompletaUrgentissimo1234567890",
      starts_at: "2026-08-20T18:00:00Z",
      ends_at: "2026-08-20T19:00:00Z",
    }),
  ],
};

test.beforeEach(async ({ page }) => {
  // Relógio congelado em 18/08/2026 09:00 (fuso do tenant). Sem isto o spec é uma bomba-relógio:
  // o seletor abre no mês CORRENTE, e em setembro "20 de agosto" simplesmente não está na grade.
  await page.clock.setFixedTime(new Date("2026-08-18T12:00:00Z"));
  await semearSessao(page);
  await mockarApi(page, fixtures);
  await page.goto("/crm/clients/c1");
  await page.getByRole("button", { name: "Marcar com este cliente" }).click();
  await expect(page.getByRole("heading", { name: "Marcar com Ju" })).toBeVisible();
});

test("a grade de sete colunas cabe inteira em 360px", async ({ page }) => {
  // A página não passa a rolar de lado só porque o modal abriu.
  const { larguraDaPagina } = await medirPagina(page);
  expect(larguraDaPagina).toBe(360);

  // Cada coluna da grade tem de estar INTEIRA dentro da tela — a de sábado é a que morre
  // primeiro quando a conta de largura não fecha.
  for (const rotulo of ["Dom", "Sáb"]) {
    const caixa = await page.getByText(rotulo, { exact: true }).first().boundingBox();
    expect(caixa).not.toBeNull();
    expect(caixa!.x).toBeGreaterThanOrEqual(0);
    expect(caixa!.x + caixa!.width).toBeLessThanOrEqual(360);
  }

  // Nenhum texto do seletor sai pela borda do que o recorta.
  expect(await textoForaDaTela(page, '[data-testid="seletor-horario"]')).toEqual([]);
});

test("as faixas de horário e a saída de escape ficam alcançáveis", async ({ page }) => {
  await page.getByRole("button", { name: /20 de agosto/ }).click();

  // O compromisso que já existe é a informação que faltava — e o título sem espaço tem de
  // QUEBRAR dentro da caixa, não vazar por ela (o painel do dia não tem `truncate`).
  // Escopado ao seletor: o MESMO título também está na lista do `BlocoDaAgenda`, atrás do modal
  // — sem o recorte, o localizador casa dois elementos e o Playwright recusa em modo estrito.
  const titulo = page
    .getByTestId("seletor-horario")
    .getByText("ReuniaoDeAlinhamentoFinal", { exact: false });
  await expect(titulo).toBeVisible();
  const [scrollWidth, clientWidth] = await titulo.evaluate((el) => [el.scrollWidth, el.clientWidth]);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 0.5);

  // A faixa livre é o alvo do dedo: tem de caber na tela e ser tocável.
  const faixa = page.getByRole("button", { name: "09:00–10:00" });
  await expect(faixa).toBeVisible();
  const caixaDaFaixa = await faixa.boundingBox();
  expect(caixaDaFaixa!.x + caixaDaFaixa!.width).toBeLessThanOrEqual(360);

  // "Outro horário" mora na barra fixa do rodapé justamente para nunca sair da tela: sem ele um
  // dia cheio, ou uma agenda que não carregou, vira beco sem saída. Mede-se que ele está DENTRO
  // dos 740px de altura da viewport, não só presente no DOM.
  const escape = page.getByRole("button", { name: "Outro horário" });
  const caixaDoEscape = await escape.boundingBox();
  expect(caixaDoEscape).not.toBeNull();
  expect(caixaDoEscape!.y + caixaDoEscape!.height).toBeLessThanOrEqual(740);
});

test("os botões de ação do seletor respeitam o mínimo tocável", async ({ page }) => {
  await page.getByRole("button", { name: /20 de agosto/ }).click();

  // Recorte deliberado: as células da GRADE ficam de fora desta asserção. Sete colunas de 44px
  // pedem 308px + vãos, e a caixa do modal em 360px oferece 280px de área útil — 44px por célula
  // é aritmeticamente impossível sem quebrar o calendário em duas linhas por semana. É a mesma
  // postura documentada do `modal-conta-360.spec.ts` para os campos de 38px: a exceção fica
  // escrita, não escondida. O que ESTE teste protege são os alvos que dão para honrar — as faixas
  // de horário, o "Outro horário" e a navegação de mês —, e a grade tem sua própria rede: a
  // altura mínima medida abaixo.
  const pequenos = (await alvosPequenos(page, 44, ".fixed.inset-0.z-50")).filter(
    (a) => a.descricao.startsWith("button") && !a.descricao.includes("aspect-square"),
  );
  expect(pequenos).toEqual([]);

  // A rede da grade: célula quadrada de pelo menos 36px. Abaixo disso o dedo erra o dia, e o
  // erro é caro — marca o compromisso no dia errado sem aviso nenhum.
  const celula = await page.getByRole("button", { name: /20 de agosto/ }).boundingBox();
  expect(celula!.height).toBeGreaterThanOrEqual(36);
  expect(celula!.width).toBeGreaterThanOrEqual(36);
});

test("nome de contato sem espaço não empurra o 'Fechar' para fora da tela", async ({ page }) => {
  // O cabeçalho e o rodapé do `Modal` ficavam FORA da varredura: o `data-testid` estava no
  // `children`, então a régua media o miolo e dava tudo certo enquanto o `<h2>` do título
  // empurrava o botão "Fechar" 327px para fora dos 360. E o `scrollWidth` da PÁGINA continua 360
  // porque a caixa tem `overflow-y-auto` — o mesmo disfarce que `medidas.ts` documenta para o
  // `main.overflow-x-hidden`. `name` aceita 255 chars no backend; sem espaço é o pior caso real.
  await page.getByRole("button", { name: /fechar/i }).click();
  await page.route("**/api/crm/clients/c1", async (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: JSON.stringify({ ...fixtures["/crm/clients/c1"], name: "MariaEduardaDeAlmeidaFonsecaRodriguesDosSantosNascimentoJunior" }),
    }),
  );
  await page.goto("/crm/clients/c1");
  await page.getByRole("button", { name: "Marcar com este cliente" }).click();

  const fechar = page.getByRole("button", { name: /fechar/i });
  const caixa = await fechar.boundingBox();
  expect(caixa).not.toBeNull();
  expect(caixa!.x + caixa!.width).toBeLessThanOrEqual(360);

  // E a varredura agora enxerga a CAIXA inteira do modal, não só o miolo.
  expect(await textoForaDaTela(page, '[data-testid="seletor-horario"]')).toEqual([]);
});
