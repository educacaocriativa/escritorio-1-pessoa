import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { api } from "../../lib/api";
import ClientDetailPage from "./ClientDetailPage";

// Issue #145 — a ficha do cliente NÃO é tela de leitura: ela dispara
// `POST /receivables/charges/{id}/settle-externally`, a MESMA ação de dinheiro da `CobrancasPage`
// (17 testes), e até aqui não tinha nenhum. Rede sempre mockada (IV2): nenhum teste bate em
// `/crm`, `/receivables` ou `/bank` reais.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// ── A régua do fuso (CLAUDE.md §5.2, issues #120/#129/#136) ───────────────────────────────────
//
// ⚠️ **Sem este mock, TODA asserção de dia deste arquivo nasceria incapaz de falhar.** O
// `vitest.config.ts` fixa `TZ: "America/Sao_Paulo"` para a suíte inteira — que é exatamente o
// `FUSO_PADRAO` em que `useFuso()` cai quando ninguém mocka `store/auth`. Ler um instante pelo
// fuso do TENANT e lê-lo pelo relógio do NAVEGADOR daria a mesma string por construção, e a
// mutação que troca um pelo outro sobreviveria. No PR #142, **8 dos 15 call sites corrigidos**
// continuaram verdes com o literal errado por essa exata razão.
//
// A subárvore desta tela (`ClientTimeline`, `BlocoDaConversa`, `BlocoDaAgenda`, `DialogDeBaixa` →
// `EscolhaDaBaixa` → `AccountModal`) só consome `useFuso` deste módulo — o mock total é seguro.
let fusoDoTenant = "America/Sao_Paulo";
/** Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner: os dois discordam do DIA. */
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

// ── O instante congelado ────────────────────────────────────────────────────
//
// ⚠️ **Um instante que separa só DOIS relógios deixa o terceiro sem medição — e quem fica de fora
// tem de ser o do navegador, nunca o do tenant.** Este arquivo nasceu com o instante da
// `CobrancasPage`, `2026-08-17T02:30:00Z`, e ali o tenant e o **UTC caem no MESMO dia** (17/08):
// trocar `HOJE_DO_TENANT` por `new Date().toISOString().slice(0, 10)` — o relógio **UTC**, que
// este repositório já teve de verdade (§5.2: *"opunha as duas únicas opções que existiam então —
// navegador e UTC"*) — **sobrevivia** aos 32 testes. Medido, não suposto.
//
// `2026-08-17T16:00:00Z` põe o TENANT sozinho, que é o lado certo de estar sozinho:
//   · **tenant** (Asia/Tokyo, UTC+9)              → 18/08 01:00 → **2026-08-18**
//   · **UTC**                                     → **2026-08-17**
//   · **navegador** (America/Sao_Paulo, o runner) → 17/08 13:00 → **2026-08-17**
// As DUAS regressões possíveis (ler o navegador, ler UTC) produzem 17/08 e morrem na MESMA
// asserção — nenhuma delas precisa de um segundo teste.
//
// ⚠️ **Dois-contra-um é o MÁXIMO alcançável; não "melhore" este instante.** Tóquio só passa do dia
// de UTC a partir das **15:00Z**, e São Paulo só fica atrás do dia de UTC antes das **03:00Z**: as
// duas condições são mutuamente exclusivas, então **nenhum** instante separa os três em três dias.
// Varredura dos 48 instantes de meia em meia hora ao longo de 24h: **0** com os três dias
// distintos, **18** que isolam o dia do tenant. Trocar por um que isole o NAVEGADOR (como o de
// 02:30Z fazia) devolve o ponto cego de UTC de graça.
const INSTANTE = "2026-08-17T16:00:00Z";
/** O dia do TENANT no `INSTANTE` — o que a tela deve mostrar e mandar (#136). */
const DIA_DO_TENANT = "2026-08-18";
/**
 * O dia do navegador **E o de UTC** no mesmo instante — os dois lados errados, de uma vez.
 * Afirmar que ele NÃO aparece é a metade que impede um "hoje" qualquer de passar por tenant.
 */
const DIA_FORA_DO_TENANT = "2026-08-17";

// `toLocaleString("pt-BR", { style: "currency" })` separa "R$" do número com um **NBSP**
// (U+00A0), não com espaço comum. Comparar contra um literal com espaço comum falharia por um
// caractere invisível; normalizar aqui mantém o arquivo 100% ASCII nesse ponto.
const semNbsp = (s: string | null | undefined) => (s ?? "").replace(/\u00a0/g, " ");

/**
 * `getByText` que compara o texto JA normalizado — o unico jeito de casar uma string com "R$"
 * sem colar um NBSP invisivel no fonte do teste (a licao do PR #142).
 */
function porTextoSemNbsp(esperado: string): HTMLElement {
  return screen.getByText((_conteudo, el) => semNbsp(el?.textContent) === esperado);
}

const CLIENTE = {
  id: "cli-1",
  tenant_id: "t-1",
  name: "Joana Ré",
  email: "joana@exemplo.com",
  phone: "11999990000",
  document: "123.456.789-00",
  gender: "unspecified",
  birthdate: null,
  notes: "Cliente antiga.",
  tags: ["vip", "recorrente"],
  source: "landing",
  stage_id: "s1",
  stage_entered_at: "2026-08-01T12:00:00Z",
  created_at: "2026-07-01T10:00:00Z",
};

const COBRANCA_BASE = {
  tenant_id: "t-1",
  client_id: "cli-1",
  client_name: "Joana Ré",
  kind: "service",
  method: "pix",
  // Vencimento **distante e literal**, nunca derivado do relógio vivo: em Tóquio ou em São Paulo
  // ele é o mesmo dia, e o teste do `dt()` de data de calendário depende de ele não se mexer.
  due_date: "2026-09-16",
  competence_date: "2026-09-16",
  paid_at: null,
  chart_account_id: null,
  contract_id: null,
  cost_center_id: null,
  is_overdue: false,
  protested_at: null,
  recurrence: "none",
  recurrence_group: null,
  payment_code: "pix-copia-e-cola",
  transaction_id: null,
  bank_account_id: null,
  bank_transaction_id: null,
  created_at: "2026-08-01T00:00:00Z",
};

// Os SEIS estados que a `ChargeRow` distingue. Os valores são todos DIFERENTES entre si e as três
// somas do resumo dão três números distintos — sem isso, trocar o recorte de uma soma pela outra
// seria mutante silencioso.
const ABERTA = { ...COBRANCA_BASE, id: "c-aberta", description: "Consultoria", amount_cents: 100000, status: "open" };
const VENCIDA = { ...COBRANCA_BASE, id: "c-vencida", description: "Mensalidade atrasada", amount_cents: 50000, status: "open", is_overdue: true, due_date: "2026-07-10", competence_date: "2026-07-10" };
const PAGA_FORA = { ...COBRANCA_BASE, id: "c-paga-fora", description: "Projeto do site", amount_cents: 20000, status: "paid", bank_account_id: "acc-1", bank_transaction_id: "bt-1", paid_at: "2026-08-04T00:00:00Z" };
const PAGA_TRILHO = { ...COBRANCA_BASE, id: "c-paga-trilho", description: "Curso online", amount_cents: 70000, status: "paid", transaction_id: "tx-1", paid_at: "2026-08-06T00:00:00Z" };
const AGENDADA = { ...COBRANCA_BASE, id: "c-agendada", description: "Adiantamento", amount_cents: 30000, status: "scheduled", bank_account_id: "acc-1", paid_at: "2026-09-20T00:00:00Z" };
const CANCELADA = { ...COBRANCA_BASE, id: "c-cancelada", description: "Serviço desistido", amount_cents: 40000, status: "canceled" };

const CONTA_BANCARIA = {
  id: "acc-1",
  name: "Itaú PJ",
  kind: "checking",
  is_primary: true,
  archived_at: null,
  opening_balance_cents: 0,
  opening_date: "2026-01-01",
  saldo_derivado_cents: 0,
  saldo_derivado_origem: "banco",
};

const CONTRATO = {
  id: "ct-1", tenant_id: "t-1", client_id: "cli-1", client_name: "Joana Ré", quote_id: null,
  title: "Contrato de consultoria", clauses: [], status: "signed", public_slug: null,
  fixed_costs_allocated_cents: null, signer_name: "Joana Ré", signer_document: "123",
  signed_at: "2026-08-02T00:00:00Z", created_at: "2026-08-01T00:00:00Z",
};

const ORCAMENTO = {
  id: "q-1", tenant_id: "t-1", client_id: "cli-1", client_name: "Joana Ré", client_whatsapp: "",
  title: "Orçamento do site", items: [], discount_cents: 0, subtotal_cents: 250000,
  total_cents: 250000, status: "sent", valid_until: null, notes: "", payment_terms: "",
  has_password: false, show_gallery: false, gallery: [], show_schedule: false,
};

// `created_at` é INSTANTE: 20/08 23:00Z é 21/08 08:00 em Tóquio e 20/08 20:00 em São Paulo.
// É por essa diferença que o teste do `dt()` consegue dizer QUAL relógio a tela leu.
const DOCUMENTO = {
  id: "doc-1", skill: "juridico", category: "notificacao", title: "Notificação extrajudicial",
  client_id: "cli-1", client_name: "Joana Ré", status: "draft", created_at: "2026-08-20T23:00:00Z",
};

const JORNADA = {
  id: "run-1", funnel_id: "fun-1", client_id: "cli-1", client_name: "Joana Ré",
  status: "running", resume_at: null, step_count: 3, created_at: "2026-08-20T23:00:00Z",
};

/**
 * O estado do "servidor" — LIDO A CADA CHAMADA, não capturado no `mockImplementation`.
 *
 * É isso que torna possível provar o `load()` que vem DEPOIS de cada ação de dinheiro: o teste
 * troca `ficha.charges` no meio, e só quem realmente recarrega vê o novo valor na tela. Um mock
 * que devolvesse sempre a mesma lista deixaria "recarregar" e "não recarregar" indistinguíveis.
 */
let ficha: {
  cliente: unknown;
  charges: unknown[];
  contracts: unknown[];
  quotes: unknown[];
  legalDocs: unknown[];
  journeys: unknown[];
  contas: unknown[];
};

/** As SEIS leituras do `Promise.all` da montagem, com o recorte por cliente na própria URL. */
const URLS_DA_MONTAGEM = [
  "/crm/clients/cli-1",
  "/receivables/charges?client_id=cli-1",
  "/contracts?client_id=cli-1",
  "/quotes?client_id=cli-1",
  "/juridico/documents?client_id=cli-1",
  "/funnels/runs?client_id=cli-1",
];

beforeEach(() => {
  ficha = {
    cliente: CLIENTE,
    charges: [ABERTA, VENCIDA, PAGA_FORA, PAGA_TRILHO, AGENDADA, CANCELADA],
    contracts: [CONTRATO],
    quotes: [ORCAMENTO],
    legalDocs: [DOCUMENTO],
    journeys: [JORNADA],
    contas: [CONTA_BANCARIA],
  };
  vi.mocked(api.get).mockImplementation((url: string) => {
    // Igualdade EXATA, nunca `startsWith`: `/crm/clients/cli-1/timeline` (do `ClientTimeline`)
    // tem a ficha do cliente como prefixo e receberia o objeto errado.
    if (url === "/crm/clients/cli-1") return Promise.resolve({ data: ficha.cliente } as never);
    if (url === "/receivables/charges?client_id=cli-1") return Promise.resolve({ data: ficha.charges } as never);
    if (url === "/contracts?client_id=cli-1") return Promise.resolve({ data: ficha.contracts } as never);
    if (url === "/quotes?client_id=cli-1") return Promise.resolve({ data: ficha.quotes } as never);
    if (url === "/juridico/documents?client_id=cli-1") return Promise.resolve({ data: ficha.legalDocs } as never);
    if (url === "/funnels/runs?client_id=cli-1") return Promise.resolve({ data: ficha.journeys } as never);
    if (url === "/bank/accounts") return Promise.resolve({ data: ficha.contas } as never);
    // Histórico, Conversa e Agenda carregam SOZINHOS (fora do `load()`) e degradam em silêncio —
    // é o contrato deles: uma falha do WhatsApp não pode segurar a ficha inteira.
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  // Volta ao fuso "coincidente" para não contaminar os testes que não falam de fuso.
  fusoDoTenant = "America/Sao_Paulo";
});

/** Destino de navegação que ECOA o `:id` recebido — ver a nota nas rotas abaixo. */
function Destino({ rotulo }: { rotulo: string }) {
  const { id = "" } = useParams();
  return <p>{`${rotulo} ${id}`}</p>;
}

function renderFicha() {
  return render(
    <MemoryRouter initialEntries={["/crm/cli-1"]}>
      <Routes>
        <Route path="/crm/:id" element={<ClientDetailPage />} />
        {/* ⚠️ Os destinos ECOAM o `:id` da rota, e isso não é enfeite: com um texto fixo
            (`<p>Tela do funil fun-1</p>`) o destino renderiza igual para qualquer parâmetro, e
            a mutação que troca `j.funnel_id` por `j.id` SOBREVIVE — medido, ela sobreviveu aos
            32 testes na primeira versão deste arquivo. O que separa o id certo do errado é o
            parâmetro chegar até a asserção. */}
        <Route path="/crm" element={<p>Quadro do CRM</p>} />
        <Route path="/contratos/:id" element={<Destino rotulo="Tela do contrato" />} />
        <Route path="/orcamentos/:id" element={<Destino rotulo="Tela do orçamento" />} />
        <Route path="/juridico/:id" element={<Destino rotulo="Tela do documento" />} />
        <Route path="/funis/:id" element={<Destino rotulo="Tela do funil" />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** As URLs pedidas até agora, na ordem — o recorte por cliente viaja DENTRO delas. */
const urlsPedidas = () => vi.mocked(api.get).mock.calls.map(([u]) => String(u));

/**
 * O valor de um cartão do resumo pelo seu RÓTULO.
 *
 * Estrutural de propósito, e sem tocar em classe CSS (regra dura do §5.1): os três cartões são o
 * MESMO componente `Stat`, e os valores colidem com os das linhas de cobrança (`R$ 1.000,00` é ao
 * mesmo tempo a soma "a vencer" e o valor da cobrança aberta). Buscar por texto devolveria dois
 * nós; ancorar no rótulo devolve o número certo.
 */
function valorDoCartao(rotulo: string): string {
  const label = screen.getByText(rotulo);
  return semNbsp((label.nextElementSibling as HTMLElement).textContent);
}

/** A `<li>` de uma cobrança, pela descrição dela — o recorte de cada `ChargeRow`. */
function linhaDaCobranca(descricao: string): HTMLElement {
  return screen.getByText(new RegExp(`^${descricao} `)).closest("li") as HTMLElement;
}

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 1. Montagem — SEIS leituras em paralelo, todas recortadas por este cliente
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — a montagem (issue #145)", () => {
  it("mostra 'Carregando ficha...' ANTES das seis leituras e as dispara todas com client_id", async () => {
    renderFicha();

    // Síncrono de propósito: o `Promise.all` só resolve no microtask seguinte, então este é o
    // único instante em que o estado de carregamento é observável. Sem ele, trocar o `if
    // (!client) return <Carregando>` por `return null` seria mutante invisível.
    expect(screen.getByText("Carregando ficha...")).toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Joana Ré" })).toBeInTheDocument();
    expect(screen.queryByText("Carregando ficha...")).toBeNull();

    // As SEIS, e cada uma carrega o recorte do cliente na própria URL. Uma leitura que perdesse o
    // `?client_id=` traria a lista do TENANT INTEIRO para dentro da ficha de uma pessoa.
    for (const url of URLS_DA_MONTAGEM) {
      expect(urlsPedidas()).toContain(url);
    }
  });

  it("o cabeçalho junta os três contatos com ' · ' e cai em 'Sem contato cadastrado' quando não há nenhum", async () => {
    renderFicha();
    expect(
      await screen.findByText("joana@exemplo.com · 11999990000 · 123.456.789-00"),
    ).toBeInTheDocument();
    expect(screen.getByText("vip")).toBeInTheDocument();
    expect(screen.getByText("Cliente antiga.")).toBeInTheDocument();
  });

  it("cliente sem e-mail, telefone nem documento mostra a frase de fallback (o `.filter(Boolean)`)", async () => {
    ficha.cliente = { ...CLIENTE, email: null, phone: null, document: null, tags: [], notes: "" };
    renderFicha();

    expect(await screen.findByText("Sem contato cadastrado")).toBeInTheDocument();
  });

  it("os contadores de cada seção contam a lista que chegou, não um número fixo", async () => {
    renderFicha();

    expect(await screen.findByText("Cobranças (6)")).toBeInTheDocument();
    expect(screen.getByText("Contratos (1)")).toBeInTheDocument();
    expect(screen.getByText("Orçamentos (1)")).toBeInTheDocument();
    expect(screen.getByText("Documentos jurídicos (1)")).toBeInTheDocument();
    expect(screen.getByText("Jornadas no funil (1)")).toBeInTheDocument();
  });

  it("lista vazia mostra o estado vazio da seção, nunca uma lista em branco", async () => {
    ficha.charges = [];
    ficha.contracts = [];
    renderFicha();

    expect(await screen.findByText("Nenhuma cobrança para este cliente.")).toBeInTheDocument();
    expect(screen.getByText("Nenhum contrato.")).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 2. O resumo financeiro — TRÊS somas com recortes DIFERENTES sobre a MESMA lista
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — as três somas do resumo (issue #145)", () => {
  it("'a vencer' EXCLUI a vencida; 'Vencido' é só ela; 'Recebido' é só o que foi pago", async () => {
    // Os três recortes andam sobre a mesma lista de seis cobranças e têm de dar TRÊS números
    // diferentes. Por isso as fixtures têm valores distintos: se `openSum` passasse a somar
    // também a vencida (`!c.is_overdue` → `true`) daria R$ 1.500,00, e a linha abaixo morre.
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    // Aberta (R$ 1.000,00) — sem a vencida, sem a agendada, sem a cancelada.
    expect(valorDoCartao("A receber (a vencer)")).toBe("R$ 1.000,00");
    // Só a vencida (R$ 500,00). O recorte aqui é `is_overdue`, e NÃO `status === "open"`.
    expect(valorDoCartao("Vencido")).toBe("R$ 500,00");
    // As duas pagas (R$ 200,00 + R$ 700,00), pelas DUAS rotas: a de banco e a do trilho.
    expect(valorDoCartao("Recebido")).toBe("R$ 900,00");
  });

  it("a cobrança AGENDADA e a CANCELADA não entram em soma nenhuma", async () => {
    // O caso que expõe o recorte `status === "open"` do `openSum`: `scheduled` e `canceled` não
    // são "a vencer", não são "vencido" e não são "recebido". Trocar o recorte por
    // `status !== "paid"` somaria R$ 700,00 aqui e a primeira linha morre.
    ficha.charges = [ABERTA, AGENDADA, CANCELADA];
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    expect(valorDoCartao("A receber (a vencer)")).toBe("R$ 1.000,00");
    expect(valorDoCartao("Vencido")).toBe("R$ 0,00");
    expect(valorDoCartao("Recebido")).toBe("R$ 0,00");
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 3. `ChargeRow` — os quatro estados, e a porta do dinheiro que só o ABERTO abre
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — os estados da cobrança (issue #145)", () => {
  it("paga / agendada / cancelada / aberta+vencida têm cada uma o SEU rótulo", async () => {
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    expect(within(linhaDaCobranca("Projeto do site")).getByText("Pago")).toBeInTheDocument();
    expect(within(linhaDaCobranca("Adiantamento")).getByText("Agendado")).toBeInTheDocument();
    expect(within(linhaDaCobranca("Serviço desistido")).getByText("Cancelada")).toBeInTheDocument();
    expect(within(linhaDaCobranca("Mensalidade atrasada")).getByText("Vencida")).toBeInTheDocument();
    // A aberta e a vencer não é nenhum dos três: ela mostra o "aguardando pgto".
    expect(within(linhaDaCobranca("Consultoria")).getByText("aguardando pgto")).toBeInTheDocument();
    expect(within(linhaDaCobranca("Consultoria")).queryByText("Vencida")).toBeNull();
  });

  it("a porta do dinheiro aparece SÓ nas abertas — nem paga, nem agendada, nem cancelada", async () => {
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    // Duas abertas (a vencer e a vencida), quatro cobranças que não são. Um `getAllBy` com
    // comprimento afirmado é o que impede o botão de vazar para um estado onde não pode existir.
    expect(screen.getAllByRole("button", { name: "Recebi direto na conta" })).toHaveLength(2);
    expect(within(linhaDaCobranca("Projeto do site")).queryByRole("button", { name: "Recebi direto na conta" })).toBeNull();
    expect(within(linhaDaCobranca("Adiantamento")).queryByRole("button", { name: "Recebi direto na conta" })).toBeNull();
    expect(within(linhaDaCobranca("Serviço desistido")).queryByRole("button", { name: "Recebi direto na conta" })).toBeNull();
    // ⚠️ E o rótulo é o FATO, nunca "Marcar paga" — aquele botão foi removido de propósito
    // (Story 8.15): só o webhook do gateway marca pago pelo trilho.
    expect(screen.queryByRole("button", { name: /marcar paga/i })).toBeNull();
  });

  it("'Protestar' só existe na VENCIDA e some quando ela já foi protestada", async () => {
    ficha.charges = [ABERTA, VENCIDA, { ...VENCIDA, id: "c-ja", description: "Já protestada", protested_at: "2026-08-01T00:00:00Z" }];
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    expect(within(linhaDaCobranca("Mensalidade atrasada")).getByRole("button", { name: /protestar/i })).toBeInTheDocument();
    // A que não venceu não tem o que protestar.
    expect(within(linhaDaCobranca("Consultoria")).queryByRole("button", { name: /protestar/i })).toBeNull();
    // A já protestada mostra a MARCA e perde o botão — protestar duas vezes não é operação.
    const linhaJa = linhaDaCobranca("Já protestada");
    expect(within(linhaJa).getByText("PROTESTADA")).toBeInTheDocument();
    expect(within(linhaJa).queryByRole("button", { name: /protestar/i })).toBeNull();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 4. A ROTA do dinheiro — derivada dos dois ponteiros, nunca persistida (`rota.ts`)
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — a rota da cobrança paga (issue #145)", () => {
  it("paga FORA do trilho diz 'caiu direto na sua conta'; a do trilho fica calada", async () => {
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    // `bank_account_id` preenchido e `transaction_id` nulo → rota "banco".
    expect(
      within(linhaDaCobranca("Projeto do site")).getByText("caiu direto na sua conta"),
    ).toBeInTheDocument();
    // `transaction_id` preenchido → rota "trilho": ali "Pago" já é a leitura certa, e nomear
    // "trilho" exporia ao dono um vocabulário interno da plataforma. As duas metades importam —
    // sem a segunda, trocar `rotaDaCobranca(c) === "banco"` por `!== null` sobreviveria.
    expect(
      within(linhaDaCobranca("Curso online")).queryByText("caiu direto na sua conta"),
    ).toBeNull();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 5. Protestar — POST e RECARGA
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — protestar (issue #145)", () => {
  it("manda o POST na cobrança certa e RECARREGA: a marca PROTESTADA aparece sem F5", async () => {
    const user = userEvent.setup();
    ficha.charges = [VENCIDA];
    vi.mocked(api.post).mockImplementation(() => {
      // O "servidor" passa a devolver a cobrança protestada — é o que a recarga tem de trazer.
      ficha.charges = [{ ...VENCIDA, protested_at: "2026-08-19T00:00:00Z" }];
      return Promise.resolve({ data: {} } as never);
    });
    renderFicha();

    await user.click(await screen.findByRole("button", { name: /protestar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0]).toEqual(["/receivables/charges/c-vencida/protest"]);
    // Sem o `load()` depois do POST, a tela continuaria mostrando a cobrança sem marca e o dono
    // não teria como saber se o protesto pegou. É esta linha que prende a recarga.
    expect(await screen.findByText("PROTESTADA")).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 6. Trocar vencimento — e o `if (!due) return` que existe para NÃO mandar nada
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — trocar vencimento (issue #145)", () => {
  it("manda a data NOVA em due_date e recarrega a ficha", async () => {
    const user = userEvent.setup();
    ficha.charges = [ABERTA];
    vi.mocked(api.post).mockImplementation(() => {
      ficha.charges = [{ ...ABERTA, due_date: "2026-10-31", competence_date: "2026-10-31" }];
      return Promise.resolve({ data: {} } as never);
    });
    renderFicha();

    await user.click(await screen.findByRole("button", { name: "Trocar venc." }));
    fireEvent.change(screen.getByDisplayValue("2026-09-16"), { target: { value: "2026-10-31" } });
    await user.click(screen.getByRole("button", { name: "OK" }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0]).toEqual([
      "/receivables/charges/c-aberta/reschedule",
      { due_date: "2026-10-31" },
    ]);
    // A recarga é o que faz a linha exibir o vencimento novo — sem ela o dono veria a data velha.
    expect(await screen.findByText(/vence 31\/10\/2026/)).toBeInTheDocument();
  });

  it("campo de data APAGADO não dispara nada — é o `if (!due) return`", async () => {
    // Sem a guarda, o `POST .../reschedule` sairia com `due_date: ""` e quem recusaria seria o
    // backend, depois de a chamada já ter ido. A guarda é o que impede a viagem inútil — e esta
    // é a única asserção capaz de dizer que ela existe.
    const user = userEvent.setup();
    ficha.charges = [ABERTA];
    renderFicha();

    await user.click(await screen.findByRole("button", { name: "Trocar venc." }));
    fireEvent.change(screen.getByDisplayValue("2026-09-16"), { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "OK" }));

    expect(api.post).not.toHaveBeenCalled();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 6b. O vencimento que o `load()` traz e o campo que não o vê (issue #155)
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — 'Trocar venc.' depois de um reagendamento do backend (issue #155)", () => {
  /** Uma SEGUNDA cobrança aberta: é o reagendamento DELA que dispara o `load()` da ficha. */
  const OUTRA = {
    ...COBRANCA_BASE,
    id: "c-outra",
    description: "Retainer mensal",
    amount_cents: 60000,
    status: "open",
  };

  /** O `<input type="date">` de uma linha — `null` quando o campo está FECHADO. */
  function campoDeData(descricao: string): HTMLInputElement | null {
    return linhaDaCobranca(descricao).querySelector('input[type="date"]');
  }

  /**
   * O valor do campo, ou um sentinela legível quando ele nem está aberto.
   *
   * `getByDisplayValue` esconderia o valor real na mensagem de erro, e um `!` cru faria o conserto
   * por `key` — que remonta a linha e fecha o campo junto — falhar com "Cannot read properties of
   * null" em vez de dizer o que aconteceu. Medido: é exatamente assim que ele falha.
   */
  function valorDoCampo(descricao: string): string {
    return campoDeData(descricao)?.value ?? "<campo fechado pela remontagem da linha>";
  }

  /**
   * Reagenda a `Retainer mensal` enquanto o "servidor" muda TAMBÉM o vencimento da `Consultoria`
   * — o reagendamento vindo de fora (outra aba, rotina do backend) do enunciado. A linha da
   * `Consultoria` nunca desmonta no meio: `key={c.id}` não depende do vencimento.
   */
  async function reagendarAOutraComAConsultoriaMudandoPorFora() {
    const user = userEvent.setup();
    ficha.charges = [ABERTA, OUTRA];
    vi.mocked(api.post).mockImplementation(() => {
      ficha.charges = [
        { ...ABERTA, due_date: "2026-11-05", competence_date: "2026-11-05" },
        { ...OUTRA, due_date: "2026-10-31", competence_date: "2026-10-31" },
      ];
      return Promise.resolve({ data: {} } as never);
    });
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    const outra = linhaDaCobranca("Retainer mensal");
    await user.click(within(outra).getByRole("button", { name: "Trocar venc." }));
    fireEvent.change(within(outra).getByDisplayValue("2026-09-16"), {
      target: { value: "2026-10-31" },
    });
    await user.click(within(outra).getByRole("button", { name: "OK" }));

    // A recarga JÁ chegou à linha da `Consultoria` — o texto dela mostra 05/11. Sem esta espera,
    // "campo com data velha" poderia ser apenas o `load()` que ainda não voltou, e o teste
    // mediria a corrida em vez do estado preso.
    expect(await screen.findByText(/vence 05\/11\/2026/)).toBeInTheDocument();
    return user;
  }

  it("o campo abre com o vencimento que o backend mandou, não com o da montagem", async () => {
    const user = await reagendarAOutraComAConsultoriaMudandoPorFora();

    await user.click(
      within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "Trocar venc." }),
    );

    expect(valorDoCampo("Consultoria")).toBe("2026-11-05");
  });

  it("confirmar sem reparar NÃO reenvia o vencimento velho", async () => {
    // A metade que custa dinheiro: o campo errado só é visível para quem olhar, mas o `OK` manda.
    const user = await reagendarAOutraComAConsultoriaMudandoPorFora();

    await user.click(
      within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "Trocar venc." }),
    );
    await user.click(within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "OK" }));

    expect(vi.mocked(api.post).mock.calls.map(([u, b]) => [String(u), b])).toEqual([
      ["/receivables/charges/c-outra/reschedule", { due_date: "2026-10-31" }],
      ["/receivables/charges/c-aberta/reschedule", { due_date: "2026-11-05" }],
    ]);
  });

  it("uma recarga no meio da digitação NÃO apaga o que o dono já escreveu", async () => {
    // Este é o teste que decide ENTRE os dois consertos possíveis do enunciado. Pôr o vencimento
    // na `key` da linha (`key={`${c.id}:${c.due_date}`}`) também faz o campo reabrir com a data
    // certa — remontando a linha inteira. O preço é este: a remontagem joga fora o rascunho, e
    // quem estava digitando quando a recarga chegou perde a data pela metade. Derivar o valor do
    // prop custa zero remontagens, então é este o conserto.
    const user = userEvent.setup();
    ficha.charges = [ABERTA, OUTRA];
    vi.mocked(api.post).mockImplementation(() => {
      // O reagendamento da OUTRA muda, de quebra, o vencimento da Consultoria lá no servidor.
      ficha.charges = [
        { ...ABERTA, due_date: "2026-11-05", competence_date: "2026-11-05" },
        { ...OUTRA, due_date: "2026-10-31", competence_date: "2026-10-31" },
      ];
      return Promise.resolve({ data: {} } as never);
    });
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    // O dono abre o campo da Consultoria e digita ANTES de qualquer recarga.
    await user.click(
      within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "Trocar venc." }),
    );
    fireEvent.change(campoDeData("Consultoria") as HTMLInputElement, {
      target: { value: "2026-12-24" },
    });

    // ...e só então a recarga chega, disparada pelo reagendamento da outra cobrança.
    const outra = linhaDaCobranca("Retainer mensal");
    await user.click(within(outra).getByRole("button", { name: "Trocar venc." }));
    fireEvent.change(within(outra).getByDisplayValue("2026-09-16"), {
      target: { value: "2026-10-31" },
    });
    await user.click(within(outra).getByRole("button", { name: "OK" }));
    expect(await screen.findByText(/vence 05\/11\/2026/)).toBeInTheDocument();

    // O que o dono digitou continua lá, e é ele que o `OK` manda — não o do servidor.
    expect(valorDoCampo("Consultoria")).toBe("2026-12-24");
    await user.click(within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "OK" }));
    expect(vi.mocked(api.post).mock.calls.at(-1)).toEqual([
      "/receivables/charges/c-aberta/reschedule",
      { due_date: "2026-12-24" },
    ]);
  });
  it("depois do OK o rascunho MORRE: o campo volta a seguir o servidor", async () => {
    // Quem grava o vencimento é o servidor, e ele pode gravar um dia DIFERENTE do pedido (dia
    // útil, normalização, uma alteração concorrente que chegou primeiro). Se o rascunho
    // sobrevivesse ao `OK`, o campo seguiria mostrando o que o dono DIGITOU em vez do que ficou
    // gravado — e o `OK` seguinte reenviaria isso. É a mesma falha da issue, um passo depois.
    const user = userEvent.setup();
    ficha.charges = [ABERTA];
    vi.mocked(api.post).mockImplementation(() => {
      ficha.charges = [{ ...ABERTA, due_date: "2026-11-05", competence_date: "2026-11-05" }];
      return Promise.resolve({ data: {} } as never);
    });
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });

    await user.click(
      within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "Trocar venc." }),
    );
    fireEvent.change(campoDeData("Consultoria") as HTMLInputElement, {
      target: { value: "2026-12-24" },
    });
    await user.click(within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "OK" }));
    expect(await screen.findByText(/vence 05\/11\/2026/)).toBeInTheDocument();

    await user.click(
      within(linhaDaCobranca("Consultoria")).getByRole("button", { name: "Trocar venc." }),
    );

    expect(valorDoCampo("Consultoria")).toBe("2026-11-05");
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 7. "Recebi direto na conta" — a MESMA porta da `CobrancasPage`, e o dia é o do TENANT (#136)
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — recebimento fora do trilho (Story 8.15, issue #145)", () => {
  async function abrirRegistro(descricao = "Consultoria") {
    const user = userEvent.setup();
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });
    await user.click(
      within(linhaDaCobranca(descricao)).getByRole("button", { name: "Recebi direto na conta" }),
    );
    return user;
  }

  it("o clique NÃO registra direto: abre a confirmação com o vocabulário de ENTRADA", async () => {
    ficha.charges = [ABERTA];
    await abrirRegistro();

    expect(api.post).not.toHaveBeenCalled();
    // ⚠️ `vocab={VOCAB_ENTRADA}`: o dinheiro anda na direção oposta à de Contas a Pagar. Sem ele o
    // componente cai no `VOCAB_SAIDA` default e a ficha perguntaria "de qual conta o dinheiro
    // SAIU" sobre um recebimento. As duas metades prendem a escolha.
    expect(screen.getByLabelText(/conta bancária onde o dinheiro caiu/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/conta bancária de onde o dinheiro saiu/i)).toBeNull();
    expect(screen.getByLabelText(/dia em que o dinheiro caiu na conta/i)).toBeInTheDocument();
    // A confirmação nomeia a conta pré-selecionada — pré-selecionar não é tornar invisível.
    expect(screen.getByRole("button", { name: /caiu no Itaú PJ/i })).toBeInTheDocument();
  });

  it("o dia default é HOJE **no fuso do TENANT** (#136) e é ele que VIAJA no received_on", async () => {
    // ⚠️ Tóquio + relógio congelado, e as duas coisas são necessárias. A tela passa
    // `dataPadrao={HOJE_DO_TENANT}` (a sentinela `null`) e quem resolve o dia é o
    // `useEscolhaDaBaixa`, com `today(useFuso())`. Qualquer "hoje" montado AQUI na tela dá 17/08 e
    // mata as linhas abaixo: `localYmd(new Date())` (navegador) e
    // `new Date().toISOString().slice(0, 10)` (UTC) — as duas regressões históricas deste repo,
    // pegas pelo MESMO instante. No fuso do runner nenhuma das duas conseguiria falhar.
    fusoDoTenant = FUSO_DISTANTE;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(INSTANTE));
    ficha.charges = [ABERTA];
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirRegistro();

    const dia = (await screen.findByLabelText(
      /dia em que o dinheiro caiu na conta/i,
    )) as HTMLInputElement;
    expect(dia.value).toBe(DIA_DO_TENANT);
    // O gesto é "caiu na minha conta", um fato observado AGORA — nunca o vencimento (que é a
    // regra da baixa de Contas a Pagar, fundador F10). A assimetria é deliberada.
    expect(dia.value).not.toBe(ABERTA.due_date);
    // Neste instante o navegador E o UTC dão 17/08 — uma linha só fecha as duas portas.
    expect(dia.value).not.toBe(DIA_FORA_DO_TENANT);

    await user.click(screen.getByRole("button", { name: /caiu no Itaú PJ/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    // As DUAS chaves do corpo importam e nenhuma delas é opcional: `bank_account_id` é a conta em
    // que o crédito vai aparecer no extrato, e `received_on` é o dia. `toEqual` (e não
    // `objectContaining`) porque uma chave a mais aqui é um campo que o backend não espera.
    expect(vi.mocked(api.post).mock.calls[0]).toEqual([
      "/receivables/charges/c-aberta/settle-externally",
      { bank_account_id: "acc-1", received_on: DIA_DO_TENANT },
    ]);
  });

  it("registrado: o dialog FECHA e a ficha RECARREGA — o valor sai de 'a vencer' e entra em 'Recebido'", async () => {
    ficha.charges = [ABERTA];
    vi.mocked(api.post).mockImplementation(() => {
      ficha.charges = [{ ...ABERTA, status: "paid", bank_account_id: "acc-1", paid_at: "2026-08-17T00:00:00Z" }];
      return Promise.resolve({ data: {} } as never);
    });
    const user = await abrirRegistro();
    await user.click(await screen.findByRole("button", { name: /caiu no Itaú PJ/i }));

    // `setRecebendo(null)`: sem ele o dono ficaria olhando a confirmação de algo já registrado, e
    // um segundo clique mandaria o POST de novo.
    await waitFor(() =>
      expect(screen.queryByLabelText(/conta bancária onde o dinheiro caiu/i)).toBeNull(),
    );
    // `load()`: sem ele os cartões continuariam mostrando o dinheiro como a receber.
    await waitFor(() => expect(valorDoCartao("Recebido")).toBe("R$ 1.000,00"));
    expect(valorDoCartao("A receber (a vencer)")).toBe("R$ 0,00");
  });

  it("o valor da confirmação nomeia a cobrança e o vencimento dela", async () => {
    ficha.charges = [ABERTA];
    await abrirRegistro();

    // O dono está declarando dinheiro sobre UMA cobrança: se a confirmação não disser qual, o
    // gesto vira um "ok" cego. `descricao` cai no nome do cliente quando a cobrança não tem uma.
    expect(await screen.findByText("Consultoria")).toBeInTheDocument();
    expect(porTextoSemNbsp("R$ 1.000,00 · vence 16/09/2026")).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 8. O 409 acionável — cadastro EMBUTIDO, sem tirar o dono da cobrança
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — o 409 acionável (issue #145)", () => {
  it("409 → cadastro embutido → RETOMA o registro com a conta nova selecionada", async () => {
    const user = userEvent.setup();
    ficha.charges = [ABERTA];
    ficha.contas = [{ ...CONTA_BANCARIA, name: "Conta velha" }];
    const mensagem409 =
      "A conta bancária escolhida está arquivada e não recebe lançamentos novos. Escolha outra " +
      "conta ou cadastre a conta que você usa hoje — com o saldo de abertura do dia.";
    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url === "/bank/accounts") {
        return Promise.resolve({
          data: { ...CONTA_BANCARIA, id: "acc-nova", name: "Nubank PJ" },
        } as never);
      }
      const jaCadastrou = vi
        .mocked(api.post)
        .mock.calls.some(([u]) => String(u) === "/bank/accounts");
      if (jaCadastrou) return Promise.resolve({ data: {} } as never);
      return Promise.reject({
        response: {
          status: 409,
          data: { detail: { acao: "cadastrar_conta", mensagem: mensagem409 } },
        },
      });
    });

    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });
    await user.click(screen.getByRole("button", { name: "Recebi direto na conta" }));
    await user.click(await screen.findByRole("button", { name: /caiu na Conta velha|caiu no Conta velha/i }));

    // (1) A mensagem do BACKEND aparece como veio — reconhecida por `acao`, não por substring.
    expect(await screen.findByText(mensagem409)).toBeInTheDocument();
    // (2) O cadastro abre ALI MESMO: o dono não perde de vista a cobrança que estava registrando.
    expect(screen.getByRole("heading", { name: "Nova conta" })).toBeInTheDocument();
    // (3) Cadastra pelo formulário embutido (o MESMO de Contas & Saldos).
    await user.type(screen.getByLabelText("Nome da conta"), "Nubank PJ");
    // Story 8.21 — a escolha do saldo é OBRIGATÓRIA e trava o salvar até existir.
    await user.click(screen.getByLabelText("Não sei o saldo agora"));
    await user.click(screen.getByRole("button", { name: "Cadastrar conta" }));
    // (4) O registro é RETOMADO com a conta recém-criada já selecionada.
    await user.click(await screen.findByRole("button", { name: /caiu no Nubank PJ/i }));

    const tentativas = () =>
      vi
        .mocked(api.post)
        .mock.calls.filter(([u]) => String(u) === "/receivables/charges/c-aberta/settle-externally");
    await waitFor(() => expect(tentativas()).toHaveLength(2));
    expect(tentativas().at(-1)?.[1]).toMatchObject({ bank_account_id: "acc-nova" });
  });

  it("tenant SEM conta nenhuma: a ficha oferece o cadastro em vez de um seletor vazio", async () => {
    const user = userEvent.setup();
    ficha.charges = [ABERTA];
    ficha.contas = [];
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });
    await user.click(screen.getByRole("button", { name: "Recebi direto na conta" }));

    expect(
      await screen.findByText(/precisa saber em qual conta bancária o dinheiro caiu/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cadastrar conta bancária/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirmar recebimento/i })).toBeDisabled();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 9. `EditClientModal` — o PATCH da ficha
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — editar cliente (issue #145)", () => {
  async function abrirEdicao() {
    const user = userEvent.setup();
    renderFicha();
    await screen.findByRole("heading", { name: "Joana Ré" });
    await user.click(screen.getByRole("button", { name: /editar/i }));
    return user;
  }

  it("tags separadas por vírgula viram lista limpa; campo vazio vira null (nunca string vazia)", async () => {
    const user = await abrirEdicao();
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);

    await user.clear(screen.getByLabelText("Tags (separadas por vírgula)"));
    await user.type(screen.getByLabelText("Tags (separadas por vírgula)"), "  ouro , , prata ,");
    await user.clear(screen.getByLabelText("E-mail"));
    await user.clear(screen.getByLabelText("Telefone"));
    await user.clear(screen.getByLabelText("CPF/CNPJ"));
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    // `toEqual` exato: as três metades do `.split(",").map(trim).filter(Boolean)` estão aqui —
    // o espaço em volta, o item vazio do meio e a vírgula solta do fim. E `email: null` (não
    // `""`) porque o backend distingue "sem e-mail" de "e-mail em branco".
    expect(vi.mocked(api.patch).mock.calls[0]).toEqual([
      "/crm/clients/cli-1",
      {
        name: "Joana Ré",
        email: null,
        phone: null,
        document: null,
        notes: "Cliente antiga.",
        tags: ["ouro", "prata"],
      },
    ]);
  });

  it("salvo: o modal FECHA e a ficha RECARREGA com o nome novo", async () => {
    const user = await abrirEdicao();
    vi.mocked(api.patch).mockImplementation(() => {
      ficha.cliente = { ...CLIENTE, name: "Joana Ré Sobrenome" };
      return Promise.resolve({ data: {} } as never);
    });

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Editar cliente" })).toBeNull());
    expect(await screen.findByRole("heading", { name: "Joana Ré Sobrenome" })).toBeInTheDocument();
  });

  it("erro do backend é exibido sem travar a tela (modal aberto, botão reabilitado)", async () => {
    const user = await abrirEdicao();
    vi.mocked(api.patch).mockRejectedValueOnce({
      response: { data: { detail: "Documento já cadastrado em outro contato." } },
    });

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    expect(
      await screen.findByText("Documento já cadastrado em outro contato."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Editar cliente" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
  });

  it("nome vazio DESABILITA o salvar — um contato sem nome não é um contato", async () => {
    const user = await abrirEdicao();

    await user.clear(screen.getByLabelText("Nome"));
    expect(screen.getByRole("button", { name: "Salvar" })).toBeDisabled();
    // Só espaço também não vale: é o `.trim()` da condição, e sem ele a régua seria decorativa.
    await user.type(screen.getByLabelText("Nome"), "   ");
    expect(screen.getByRole("button", { name: "Salvar" })).toBeDisabled();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 10. `dt()` — as DUAS espécies de data, e cada uma só se prova num fuso diferente
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — as duas espécies de data do `dt()` (CLAUDE.md §5.2, issue #145)", () => {
  it("data de CALENDÁRIO (`due_date`) NÃO converte fuso — 16/09, nunca 15/09", async () => {
    // ⚠️ **Fuso do runner (America/Sao_Paulo, UTC−3) DE PROPÓSITO — trocar por Tóquio
    // ENFRAQUECERIA esta asserção** (§5.2). `due_date` é `"2026-09-16"`, uma data de calendário
    // sem fuso; `dt()` a manda para `formatDay`, que trabalha na STRING e nunca constrói um
    // `Date`. Quem denuncia a conversão indevida (`formatDate`, que faria
    // `new Date("2026-09-16")` = meia-noite UTC) é um fuso NEGATIVO: em UTC−3 a meia-noite UTC
    // "volta" para 15/09 21h. Em Tóquio ela vira 09:00 do MESMO dia 16 e a mutação sobreviveria.
    ficha.charges = [ABERTA];
    renderFicha();

    expect(await screen.findByText(/vence 16\/09\/2026/)).toBeInTheDocument();
    expect(screen.queryByText(/vence 15\/09\/2026/)).toBeNull();
  });

  it("INSTANTE (`created_at`) converte para o fuso do TENANT — 21/08 em Tóquio, não 20/08", async () => {
    // O outro ramo do mesmo `dt()`, e ele exige o fuso DISTANTE pela razão oposta: `created_at` é
    // um ponto no tempo (`"2026-08-20T23:00:00Z"`), que em Tóquio (UTC+9) é 21/08 08:00 e no
    // runner (UTC−3) é 20/08 20:00. Só quem lê pelo fuso do TENANT escreve 21/08 — e trocar o
    // ramo por `formatDay` (ler a string crua) daria 20/08 e mata esta linha.
    fusoDoTenant = FUSO_DISTANTE;
    ficha.charges = [];
    renderFicha();

    expect(await screen.findByText("Notificação extrajudicial")).toBeInTheDocument();
    expect(screen.getByText("21/08/2026")).toBeInTheDocument();
    expect(screen.queryByText("20/08/2026")).toBeNull();
    // A jornada no funil lê o MESMO instante pelo MESMO `dt()` — se um dos dois call sites
    // divergir, este par de linhas separa qual.
    expect(screen.getByText(/3 passo\(s\) · 21\/08\/2026/)).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// 11. A navegação da ficha e o `StatusBadge` — os dois blocos que a contagem do enunciado não
//     tinha, e que também não estavam medidos em lugar nenhum
// ══════════════════════════════════════════════════════════════════════════════════════════════

describe("ClientDetailPage — para onde a ficha leva (issue #145)", () => {
  it("o contrato leva à tela do CONTRATO (quatro prefixos parecidos, escritos na mão)", async () => {
    // Quatro `navigate()` com quatro prefixos parecidos escritos na mão, um do lado do outro.
    // Trocar `/contratos/${c.id}` por `/orcamentos/${c.id}` é a mutação que ninguém percebe
    // lendo, e o único jeito de vê-la é seguir a rota até o destino.
    const user = userEvent.setup();
    renderFicha();

    await user.click(await screen.findByRole("button", { name: /Contrato de consultoria/ }));
    expect(await screen.findByText("Tela do contrato ct-1")).toBeInTheDocument();
  });

  it("o orçamento leva à tela do ORÇAMENTO", async () => {
    const user = userEvent.setup();
    renderFicha();

    await user.click(await screen.findByRole("button", { name: /Orçamento do site/ }));
    expect(await screen.findByText("Tela do orçamento q-1")).toBeInTheDocument();
  });

  it("o documento jurídico leva à tela do DOCUMENTO", async () => {
    const user = userEvent.setup();
    renderFicha();

    await user.click(await screen.findByRole("button", { name: /Notificação extrajudicial/ }));
    expect(await screen.findByText("Tela do documento doc-1")).toBeInTheDocument();
  });

  it("a jornada leva ao FUNIL (`funnel_id`), não à corrida (`id`) — dois UUIDs no mesmo objeto", async () => {
    // `j.id` e `j.funnel_id` são ambos ids válidos e ambos compilam: só a rota diz qual é o certo.
    const user = userEvent.setup();
    renderFicha();

    await user.click(await screen.findByRole("button", { name: /3 passo/ }));
    expect(await screen.findByText("Tela do funil fun-1")).toBeInTheDocument();
  });

  it("o voltar leva ao quadro do CRM", async () => {
    const user = userEvent.setup();
    renderFicha();

    await user.click(await screen.findByRole("button", { name: /CRM & Kanban/ }));
    expect(await screen.findByText("Quadro do CRM")).toBeInTheDocument();
  });

  it("o StatusBadge TRADUZ o que conhece e mostra CRU o que não conhece (nunca vazio)", async () => {
    // O `?? status` do fallback é o que impede um status novo do backend de virar uma pílula em
    // branco na tela — o dono veria a cobrança/contrato sem estado nenhum em vez de um rótulo
    // que ele pode perguntar o que é. `running` não está no mapa; `draft` está.
    renderFicha();

    expect(await screen.findByText("Assinado")).toBeInTheDocument(); // contrato `signed`
    expect(screen.getByText("Enviado")).toBeInTheDocument(); // orçamento `sent`
    expect(screen.getByText("Rascunho")).toBeInTheDocument(); // documento `draft`
    expect(screen.getByText("running")).toBeInTheDocument(); // jornada — fora do mapa, sai crua
  });
});
