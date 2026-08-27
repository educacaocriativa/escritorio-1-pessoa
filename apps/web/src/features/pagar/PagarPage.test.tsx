import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import PagarPage from "./PagarPage";

// Story 7.5 — Task 1. Rede sempre mockada (IV2): nenhum teste bate em /payables real.
// `apiErrorMessage` mockado para devolver o `detail` do backend (o real depende de
// `instanceof AxiosError`, que um erro forjado no teste não satisfaz).
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// ── A régua do fuso (CLAUDE.md §5.2, issues #120/#129) ────────────────────────────────────────
//
// Havia aqui um `hoje()` montado com `d.getFullYear()/getMonth()/getDate()` — o dia do NAVEGADOR —
// usado para afirmar que a data da baixa **não** é hoje. Além de comparar contra um relógio vivo
// (bomba-relógio: bastava o dia real bater com o vencimento da fixture), ele lia o relógio errado.
//
// ⚠️ **Esta tela NÃO fica em Tóquio, e isso é deliberado.** `PagarPage` passa
// `dataPadrao={pagando.due_date}` para a `EscolhaDaBaixa`: o campo é preenchido com o VENCIMENTO
// da conta, e nenhum relógio — nem o do tenant, nem o do navegador — participa desse valor. A
// asserção existe para provar essa origem, não para provar fuso. Mocar `useFuso` aqui seria um
// mock inerte, e trocar o fuso não fortaleceria nada. O que a torna capaz de falhar é o relógio
// CONGELADO: com ele, "hoje" vira uma string conhecida em todos os fusos plausíveis, e substituir
// `pagando.due_date` por qualquer leitura de relógio na produção derruba o teste.
//
// `2026-08-17T18:00:00Z` → São Paulo (fuso do runner) e UTC: **17/08**; Tóquio: **18/08**.
const INSTANTE = "2026-08-17T18:00:00Z";
/** Os dias que "hoje" pode valer em `INSTANTE`. Nenhum deles é o vencimento da fixture. */
const HOJE_NO_NAVEGADOR_E_EM_UTC = "2026-08-17";
const HOJE_EM_TOQUIO = "2026-08-18";

const CONTA = {
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

const CONTA_ABERTA = {
  id: "b-1", description: "Aluguel", category: "Estrutura", supplier: "Imobiliária",
  amount_cents: 250000, due_date: "2026-06-10", status: "open", is_overdue: false,
  paid_at: null, recurrence: "none", recurrence_count: 1, recurrence_group: null,
  payment_code: "", attachment_url: "", created_at: "2026-01-01T00:00:00Z",
  tenant_id: "t-1", competence_date: null, chart_account_id: null, contract_id: null,
  cost_center_id: null,
};

/** Mocka a tela com uma conta a pagar em aberto e a lista de contas bancárias informada. */
function mockComConta(contasBancarias: unknown[]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/payables/bills")
      return Promise.resolve({ data: { items: [CONTA_ABERTA], total: 1 } } as never);
    if (url === "/bank/accounts") return Promise.resolve({ data: contasBancarias } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

const emptySummary = {
  open_cents: 0,
  overdue_cents: 0,
  week_cents: 0,
  month_cents: 0,
  paid_month_cents: 0,
};

/**
 * Estratégia (a) da Task 0: o botão que abre o modal "Nova conta" vive na topbar (AppShell),
 * fora do escopo da página. Este componente local replica o contrato real da topbar — consome
 * `usePageActions().action` e renderiza `<button onClick={action.onClick}>{action.label}</button>`
 * — sem importar o AppShell inteiro.
 */
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <PagarPage />
        <Topbar />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/payables/bills")
      return Promise.resolve({ data: { items: [], total: 0 } } as never);
    if (url === "/contracts") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

// Só um teste congela o relógio; o resto da suíte roda no relógio real e não pode herdá-lo.
afterEach(() => vi.useRealTimers());

describe("PagarPage — Nova conta a pagar (Story 7.5, Task 1)", () => {
  it("caminho feliz: cria conta a pagar com valor + vencimento; POST com amount_cents coerente", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    // Abre o modal via o contrato da topbar (usePrimaryAction("Nova conta", ...)).
    await user.click(await screen.findByRole("button", { name: "Nova conta" }));

    // "250,00" (com vírgula) deve virar amount_cents: 25000 pelo parsing do componente.
    await user.type(screen.getByLabelText("Valor (R$)"), "250,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-08-01" } });

    await user.click(screen.getByRole("button", { name: "Adicionar conta" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/payables/bills",
      expect.objectContaining({ amount_cents: 25000, due_date: "2026-08-01" }),
    );
  });

  it("caminho infeliz: erro 422 do backend é exibido sem quebrar a tela (modal segue aberto)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Valor acima do teto permitido." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova conta" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "999999999,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-08-01" } });
    await user.click(screen.getByRole("button", { name: "Adicionar conta" }));

    // Mensagem de erro no DOM, tela intacta: o modal continua visível e o botão volta a habilitar.
    expect(await screen.findByText("Valor acima do teto permitido.")).toBeInTheDocument();
    expect(screen.getByText("Nova conta a pagar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adicionar conta" })).toBeEnabled();
  });
});

// Task 11 — a correção do problema original: sem slot próprio, o comprovante era arquivado em
// "Contrato". O aviso avisa quando há comprovantes da bandeja (recebidos pelo celular) ainda sem
// vínculo com nenhuma conta, para o usuário não esquecer de resolvê-los depois.
describe("PagarPage — bandeja de comprovantes (Task 11)", () => {
  it("mostra o aviso quando há comprovantes aguardando", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: [], total: 0 } } as never);
      if (url === "/payables/receipts")
        return Promise.resolve({
          data: [
            {
              id: "r-1",
              filename: "a.pdf",
              content_type: "application/pdf",
              size: 1,
              created_at: "2026-07-28T10:00:00Z",
            },
            {
              id: "r-2",
              filename: "b.pdf",
              content_type: "application/pdf",
              size: 1,
              created_at: "2026-07-28T11:00:00Z",
            },
          ],
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();

    await waitFor(() => screen.getByText(/2 comprovantes aguardando/i));
  });

  // Achado de campo (produção): o contêiner da tabela usava `overflow-hidden`, que CORTA em vez
  // de rolar — em tela estreita a coluna Status e os botões de ação (Editar/Marcar paga/
  // Estornar) ficavam invisíveis, sem nenhum jeito de alcançá-los. `overflow-x-auto` (mesmo
  // padrão de DrePage/LucratividadePage) torna a tabela rolável em vez de clipada.
  it("a tabela de contas é rolável horizontalmente, não cortada (overflow-x-auto)", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({
          data: {
            items: [{
              id: "b-1", description: "Aluguel", category: "Estrutura", supplier: "Imobiliária",
              amount_cents: 250000, due_date: "2099-08-05", status: "open", is_overdue: false,
              paid_at: null, recurrence: "none", recurrence_count: 1, recurrence_group: null,
              payment_code: "", attachment_url: "", created_at: "2026-01-01T00:00:00Z",
              tenant_id: "t-1", competence_date: null, chart_account_id: null, contract_id: null,
              cost_center_id: null,
            }],
            total: 1,
          },
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();

    const table = await screen.findByRole("table");
    expect(table.parentElement?.className).toContain("overflow-x-auto");
    expect(table.parentElement?.className).not.toContain("overflow-hidden");
  });

  it("não mostra o aviso com a bandeja vazia", async () => {
    // beforeEach já mocka /payables/receipts (via fallback) devolvendo [].
    renderPage();

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByText(/aguardando/i)).toBeNull();
  });
});

/**
 * **Story 8.13 — a baixa passou a pedir conta bancária e dia.**
 *
 * Até a 8.12, "Marcar paga" fazia `POST /payables/bills/{id}/pay` **sem corpo**. O backend passou a
 * exigir o corpo (a conta de onde o dinheiro saiu), então esta tela quebrava com 422 — 8.12 e 8.13
 * são um par de release.
 */
describe("PagarPage — dar baixa (Story 8.13)", () => {
  async function abrirBaixa() {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Marcar paga" }));
    return user;
  }

  it('"Marcar paga" NÃO paga direto: abre a confirmação com conta e dia', async () => {
    mockComConta([CONTA]);
    await abrirBaixa();

    // O clique deixou de cometer a ação — nada foi enviado ainda.
    expect(api.post).not.toHaveBeenCalled();
    expect(await screen.findByText("Dar baixa nesta conta")).toBeInTheDocument();
    expect(screen.getByLabelText(/conta bancária de onde o dinheiro saiu/i)).toBeInTheDocument();
  });

  it("envia bank_account_id e paid_on; o dia vem do VENCIMENTO, não de hoje", async () => {
    // O relógio congelado é o que dá dentes ao `not.toBe` abaixo: sem ele, "hoje" era lido do
    // relógio vivo da máquina e a asserção só teria alguma chance de falhar no dia 10/06/2026.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(INSTANTE));
    mockComConta([CONTA]);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirBaixa();

    const dia = (await screen.findByLabelText(/dia em que o dinheiro saiu/i)) as HTMLInputElement;
    // Fundador F10: "deixar habilitado no vencimento, pois se estiver fazendo retroativo, pq não
    // deu certo no dia". NÃO é hoje, e não é `now()`.
    expect(dia.value).toBe("2026-06-10");
    // ...e não é hoje em relógio NENHUM: nem o do navegador/UTC, nem o de um tenant distante. É
    // esta linha que morre se alguém trocar `dataPadrao={pagando.due_date}` por `hojeISO()` ou
    // `today(fuso)` na `PagarPage` — o modo exato como esta tela poderia regredir.
    expect(dia.value).not.toBe(HOJE_NO_NAVEGADOR_E_EM_UTC);
    expect(dia.value).not.toBe(HOJE_EM_TOQUIO);

    await user.click(screen.getByRole("button", { name: /confirmar baixa/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0]).toEqual([
      "/payables/bills/b-1/pay",
      { bank_account_id: "acc-1", paid_on: "2026-06-10" },
    ]);
  });

  it("⚠️ [8.14] o campo de dia NÃO tem mais `max` — data futura é agendamento, não erro", async () => {
    // **Mudança de expectativa, e ela é a CORREÇÃO.** Este teste afirmava `max === hoje()` e o
    // próprio nome dele dizia "o `max` que a Story 8.14 remove". Removido: com o estado
    // `scheduled`, informar uma data futura é registrar um débito que o dono agendou no app do
    // banco — e o backend deriva o estado da data, sem inventar nada.
    mockComConta([CONTA]);
    await abrirBaixa();

    const dia = (await screen.findByLabelText(/dia em que o dinheiro saiu/i)) as HTMLInputElement;
    expect(dia.getAttribute("max")).toBeNull();
  });

  it("a conta primária vem pré-selecionada e o NOME dela aparece no próprio botão (AC5)", async () => {
    mockComConta([CONTA]);
    await abrirBaixa();

    const seletor = (await screen.findByLabelText(
      /conta bancária de onde o dinheiro saiu/i,
    )) as HTMLSelectElement;
    expect(seletor.value).toBe("acc-1");
    // Pré-selecionar não é tornar opcional: o default tem de estar VISÍVEL, senão é um campo
    // opcional pulado. Por isso o nome da conta vai no botão, não só dentro do `<select>`.
    expect(screen.getByRole("button", { name: /sai do Itaú PJ/i })).toBeInTheDocument();
  });

  it("SEM conta primária nada é pré-selecionado e a confirmação fica DESABILITADA", async () => {
    mockComConta([
      { ...CONTA, id: "a", name: "Conta A", is_primary: false },
      { ...CONTA, id: "b", name: "Conta B", is_primary: false },
    ]);
    await abrirBaixa();

    const seletor = (await screen.findByLabelText(
      /conta bancária de onde o dinheiro saiu/i,
    )) as HTMLSelectElement;
    expect(seletor.value).toBe(""); // silêncio, nunca um palpite
    expect(screen.getByRole("button", { name: /confirmar baixa/i })).toBeDisabled();
  });

  it("escolhida uma conta a dedo, a confirmação habilita e manda a conta escolhida", async () => {
    mockComConta([
      { ...CONTA, id: "a", name: "Conta A", is_primary: false },
      { ...CONTA, id: "b", name: "Conta B", is_primary: false },
    ]);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirBaixa();

    await user.selectOptions(
      await screen.findByLabelText(/conta bancária de onde o dinheiro saiu/i),
      "b",
    );
    await user.click(screen.getByRole("button", { name: /confirmar baixa/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ bank_account_id: "b" });
  });

  it("erro 422 do backend é exibido COMO VEIO (a mensagem nomeia as saídas reais)", async () => {
    mockComConta([CONTA]);
    const mensagem =
      "Esta conta bancária só existe no e1p a partir de 2026-07-01, então um pagamento em " +
      "2026-06-10 não entraria no extrato dela. Mova a abertura desta conta para antes de 10/06 " +
      "e informe o saldo daquele dia, ou escolha outra conta.";
    vi.mocked(api.post).mockRejectedValue({ response: { status: 422, data: { detail: mensagem } } });
    const user = await abrirBaixa();

    await user.click(await screen.findByRole("button", { name: /confirmar baixa/i }));

    expect(await screen.findByText(mensagem)).toBeInTheDocument();
  });

  /**
   * **O fluxo do AC2, ponta a ponta.** É o teste que a DoD desta story exige: sem conta utilizável,
   * a tela mostra o 409 acionável, abre o cadastro EMBUTIDO e **retoma o pagamento** — sem perder
   * de vista qual conta estava sendo paga.
   */
  it("409 acionável → cadastro embutido → RETOMA a baixa com a conta nova selecionada", async () => {
    // O tenant tem uma conta na lista, mas o backend a recusa (arquivada) — é assim que o 409
    // chega mesmo com a lista preenchida. O caminho "lista vazia" é o outro teste, abaixo.
    mockComConta([{ ...CONTA, name: "Conta velha" }]);
    const mensagem409 =
      "A conta bancária escolhida está arquivada e não recebe lançamentos novos. Escolha outra " +
      "conta ou cadastre a conta que você usa hoje — com o saldo de abertura do dia.";
    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url === "/bank/accounts") {
        return Promise.resolve({
          data: { ...CONTA, id: "acc-nova", name: "Nubank PJ" },
        } as never);
      }
      // A primeira baixa é recusada com o 409 acionável; a segunda (já com a conta nova) passa.
      const jaCadastrou = vi
        .mocked(api.post)
        .mock.calls.some(([u]) => String(u) === "/bank/accounts");
      if (jaCadastrou) return Promise.resolve({ data: {} } as never);
      return Promise.reject({
        response: { status: 409, data: { detail: { acao: "cadastrar_conta", mensagem: mensagem409 } } },
      });
    });

    const user = await abrirBaixa();
    await user.click(await screen.findByRole("button", { name: /confirmar baixa/i }));

    // (1) A mensagem do BACKEND aparece — não um erro cru, e não uma frase reescrita no frontend.
    expect(await screen.findByText(mensagem409)).toBeInTheDocument();
    // (2) O cadastro abre ALI MESMO, e o contexto do pagamento continua na tela por trás.
    // (o título do modal; "Nova conta" também é o rótulo do botão da topbar)
    expect(screen.getByRole("heading", { name: "Nova conta" })).toBeInTheDocument();
    // O painel da baixa continua montado por baixo, ainda dizendo QUAL conta está sendo paga —
    // é isso que significa "sem o usuário perder de vista o que ele estava pagando".
    const painel = screen
      .getByRole("heading", { name: "Dar baixa nesta conta" })
      .closest("div")?.parentElement as HTMLElement;
    expect(within(painel).getByText("Aluguel")).toBeInTheDocument();
    expect(within(painel).getByText(/R\$ 2\.500,00/)).toBeInTheDocument();

    // (3) Cadastra a conta pelo formulário embutido (o MESMO de Contas & Saldos).
    await user.type(screen.getByLabelText("Nome da conta"), "Nubank PJ");
    // Story 8.21 — a escolha do saldo é OBRIGATÓRIA e trava o salvar até existir.
    await user.click(screen.getByLabelText("Não sei o saldo agora"));
    await user.click(screen.getByRole("button", { name: "Cadastrar conta" }));

    // (4) A baixa é RETOMADA com a conta recém-criada já selecionada.
    const botao = await screen.findByRole("button", { name: /sai do Nubank PJ/i });
    await user.click(botao);

    await waitFor(() =>
      expect(
        vi.mocked(api.post).mock.calls.filter(([u]) => String(u) === "/payables/bills/b-1/pay"),
      ).toHaveLength(2),
    );
    const ultima = vi
      .mocked(api.post)
      .mock.calls.filter(([u]) => String(u) === "/payables/bills/b-1/pay")
      .at(-1);
    expect(ultima?.[1]).toMatchObject({ bank_account_id: "acc-nova" });
  });

  it("tenant SEM conta nenhuma: a tela oferece o cadastro em vez de um seletor vazio", async () => {
    mockComConta([]);
    await abrirBaixa();

    expect(await screen.findByText(/precisa saber de qual conta bancária o dinheiro saiu/i))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cadastrar conta bancária/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirmar baixa/i })).toBeDisabled();
  });

  it("a tabela é rolável e tem largura mínima — em 360px ela ROLA, não se espreme (AC9d)", async () => {
    mockComConta([CONTA]);
    renderPage();

    const table = await screen.findByRole("table");
    expect(table.parentElement?.className).toContain("overflow-x-auto");
    expect(table.className).toMatch(/min-w-\[/);
  });
});

// ── Story 8.14 — a conta AGENDADA na tela de Contas a Pagar ───────────────────────────────────

describe("Story 8.14 — a conta agendada tem rótulo próprio e gesto próprio", () => {
  const CONTA_AGENDADA = {
    ...CONTA_ABERTA,
    id: "b-agendada",
    description: "Energia",
    status: "scheduled",
    // Vence dia 10; o débito foi agendado para o dia 20 — as duas datas divergem por construção,
    // e é a do DÉBITO que responde à pergunta "quando o dinheiro sai?".
    due_date: "2026-06-10",
    paid_at: "2026-06-20T00:00:00Z",
    bank_account_id: "acc-1",
  };

  function mockComAgendada() {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills") {
        return Promise.resolve({ data: { items: [CONTA_AGENDADA], total: 1 } } as never);
      }
      if (url === "/bank/accounts") return Promise.resolve({ data: [CONTA] } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  it("mostra 'Agendada' — nem 'Pago' (o dinheiro não saiu) nem 'A pagar' (já foi resolvida)", async () => {
    mockComAgendada();
    renderPage();

    expect(await screen.findByText("Agendada")).toBeInTheDocument();
    // Escopado à TABELA: "A pagar" também é o rótulo de um dos cartões de resumo no topo da tela,
    // e é o STATUS da linha que está sendo afirmado aqui.
    const tabela = await screen.findByRole("table");
    expect(within(tabela).queryByText("Pago")).toBeNull();
    expect(within(tabela).queryByText("A pagar")).toBeNull();
    expect(within(tabela).getByText("Agendada")).toBeInTheDocument();
  });

  it("mostra a DATA DO DÉBITO na linha, não o vencimento", async () => {
    mockComAgendada();
    renderPage();

    // 20/06 é o `paid_at` (dia do débito). O vencimento (10/06) continua na coluna Vencimento.
    expect(await screen.findByText(/sai 20\/06/)).toBeInTheDocument();
  });

  it("oferece 'Cancelar agendamento' — mesma rota do estorno, outro nome", async () => {
    // No backend é o MESMO `POST /reverse` (não há verbo novo: `reverse` sempre significou "esta
    // saída não vai acontecer"). Na tela o nome precisa ser outro — "Estornar" uma conta que nunca
    // foi paga não é frase que o dono reconheça.
    mockComAgendada();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderPage();

    const botao = await screen.findByRole("button", { name: /cancelar agendamento/i });
    expect(screen.queryByRole("button", { name: /^estornar$/i })).toBeNull();
    await user.click(botao);

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/payables/bills/b-agendada/reverse");
    // A confirmação fala a linguagem do agendamento, não a do estorno.
    expect(confirmSpy.mock.calls[0][0]).toMatch(/cancelar o agendamento/i);
    confirmSpy.mockRestore();
  });

  it("NÃO oferece 'Marcar paga' nem 'Cancelar' — a conta já foi resolvida", async () => {
    // "Marcar paga" convidaria a uma segunda baixa do mesmo dinheiro; "Cancelar" (cancelar a
    // CONTA) é outro fato e o backend a recusa em `scheduled` de todo jeito.
    mockComAgendada();
    renderPage();

    await screen.findByText("Agendada");
    expect(screen.queryByRole("button", { name: /marcar paga/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^cancelar$/i })).toBeNull();
  });
});

/**
 * **Duplicar conta a pagar.**
 *
 * O botão NÃO vive no grid (a coluna de ações já carrega até cinco elementos e a tabela já rola
 * lateralmente em 360px) — vive dentro do modal "Boleto/Pix", que já é alcançável em toda linha
 * não cancelada.
 */
describe("PagarPage — duplicar conta a pagar", () => {
  const CONTA_PAGA = {
    ...CONTA_ABERTA,
    id: "b-9",
    description: "Aluguel Sala gravacao",
    supplier: "WorkPlace Palhano",
    amount_cents: 20000,
    due_date: "2026-07-31",
    status: "paid",
    paid_at: "2026-07-31T00:00:00Z",
    recurrence: "monthly",
    recurrence_count: 12,
    payment_code: "00020126580014BR.GOV.BCB.PIX",
    contract_id: "ct-1",
  };

  const OUTRA_CONTA = {
    ...CONTA_ABERTA,
    id: "b-10",
    description: "Curso Marketing",
    supplier: "Mafer",
    amount_cents: 547611,
    due_date: "2026-07-04",
  };

  function mockBills(bills: unknown[]) {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: bills, total: bills.length } } as never);
      return Promise.resolve({ data: [] } as never);
    });
  }

  /** Abre o modal Boleto/Pix da linha `indice` e clica em "Duplicar esta conta". */
  async function duplicar(user: ReturnType<typeof userEvent.setup>, indice = 0) {
    const botoes = await screen.findAllByRole("button", { name: "Boleto/Pix" });
    await user.click(botoes[indice]);
    await user.click(await screen.findByRole("button", { name: "Duplicar esta conta" }));
  }

  it("abre o cadastro preenchido, com o vencimento no mês seguinte e sem recorrência", async () => {
    const user = userEvent.setup();
    mockBills([CONTA_PAGA]);
    renderPage();

    await duplicar(user);

    // O modal de anexos saiu de cena e o de cadastro entrou.
    expect(screen.queryByText("Boleto / Contrato / Pix")).toBeNull();
    expect(screen.getByText("Nova conta a pagar")).toBeInTheDocument();

    expect(screen.getByLabelText("Descrição")).toHaveValue("Aluguel Sala gravacao");
    expect(screen.getByLabelText("Fornecedor")).toHaveValue("WorkPlace Palhano");
    expect(screen.getByLabelText("Valor (R$)")).toHaveValue("200,00");
    // 31/07 → 31/08: o dia existe em agosto e é preservado.
    expect(screen.getByLabelText("Vencimento")).toHaveValue("2026-08-31");
    // A origem é "monthly ×12"; a cópia nasce sem recorrência, senão um clique geraria 12 contas.
    expect(screen.getByLabelText("Recorrência")).toHaveValue("none");
  });

  it("gravar dispara um POST de conta NOVA, sem id, com os campos copiados", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    mockBills([CONTA_PAGA]);
    renderPage();

    await duplicar(user);
    await user.click(screen.getByRole("button", { name: "Adicionar conta" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    const [url, body] = vi.mocked(api.post).mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/payables/bills");
    expect(body).toMatchObject({
      description: "Aluguel Sala gravacao",
      supplier: "WorkPlace Palhano",
      amount_cents: 20000,
      due_date: "2026-08-31",
      recurrence: "none",
      recurrence_count: 1,
      payment_code: "00020126580014BR.GOV.BCB.PIX",
      contract_id: "ct-1",
    });
    // É uma conta NOVA, não um PATCH disfarçado na origem.
    expect(body).not.toHaveProperty("id");
  });

  // ⚠️ O teste que mata o bug de `key`: `useState(inicial)` só lê o prop na MONTAGEM, e o modal
  // fica montado o tempo todo. Sem remontar, a segunda duplicação mostraria a primeira conta —
  // e o defeito passa despercebido, porque a primeira duplicação de cada sessão funciona.
  it("duplicar uma segunda conta mostra a SEGUNDA, não a primeira", async () => {
    const user = userEvent.setup();
    mockBills([CONTA_PAGA, OUTRA_CONTA]);
    renderPage();

    await duplicar(user, 0);
    await user.click(screen.getByRole("button", { name: "Fechar" }));

    await duplicar(user, 1);
    expect(screen.getByLabelText("Descrição")).toHaveValue("Curso Marketing");
    expect(screen.getByLabelText("Valor (R$)")).toHaveValue("5476,11");
    expect(screen.getByLabelText("Vencimento")).toHaveValue("2026-08-04");
  });

  // ⚠️ O segundo ponto de limpeza: sem ele, "Nova conta" abriria o cadastro já preenchido com uma
  // despesa que o dono não pediu — a forma mais direta de gravar uma conta que não existe.
  it("depois de duplicar e fechar, 'Nova conta' abre um formulário EM BRANCO", async () => {
    const user = userEvent.setup();
    mockBills([CONTA_PAGA]);
    renderPage();

    await duplicar(user);
    await user.click(screen.getByRole("button", { name: "Fechar" }));

    await user.click(await screen.findByRole("button", { name: "Nova conta" }));
    expect(screen.getByLabelText("Descrição")).toHaveValue("");
    expect(screen.getByLabelText("Fornecedor")).toHaveValue("");
    expect(screen.getByLabelText("Valor (R$)")).toHaveValue("");
    expect(screen.getByLabelText("Vencimento")).toHaveValue("");
  });
});

describe("recorte e paginacao da lista (spec 2026-08-18)", () => {
  function renderPagar() {
    render(
      <MemoryRouter>
        <PageActionsProvider>
          <PagarPage />
        </PageActionsProvider>
      </MemoryRouter>,
    );
  }

  function paramsDaUltimaBusca(): Record<string, unknown> {
    const chamada = vi
      .mocked(api.get)
      .mock.calls.filter(([u]) => u === "/payables/bills")
      .at(-1)!;
    return (chamada[1] as { params: Record<string, unknown> }).params;
  }

  it("pede a primeira pagina com o recorte padrao", async () => {
    mockComConta([CONTA]);
    renderPagar();

    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/payables/bills", expect.anything()));
    const params = paramsDaUltimaBusca();
    expect(params.status).toEqual(["open", "scheduled"]);
    // Atrasado vence no passado: um piso de data esconderia a conta mais urgente que existe.
    expect(params).not.toHaveProperty("from");
    expect(params.offset).toBe(0);
  });

  it("mostra quantas contas estao a vista e quantas existem", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: [CONTA_ABERTA], total: 213 } } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPagar();

    expect(await screen.findByText(/Mostrando 1 de 213/i)).toBeInTheDocument();
  });

  it("carregar mais ANEXA a lista em vez de substituir", async () => {
    const SEGUNDA = { ...CONTA_ABERTA, id: "b-2", description: "Energia" };
    vi.mocked(api.get).mockImplementation((url: string, config?: unknown) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills") {
        const offset = (config as { params: { offset: number } }).params.offset;
        return Promise.resolve({
          data: { items: offset === 0 ? [CONTA_ABERTA] : [SEGUNDA], total: 2 },
        } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    renderPagar();

    expect(await screen.findByText("Aluguel")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /carregar mais/i }));

    expect(await screen.findByText("Energia")).toBeInTheDocument();
    // O erro classico de paginacao: a segunda pagina apagar a primeira.
    expect(screen.getByText("Aluguel")).toBeInTheDocument();
  });

  it("digitar no filtro de texto dispara UMA chamada, nao uma por tecla", async () => {
    mockComConta([CONTA]);
    renderPagar();
    await screen.findByText("Aluguel");
    const antes = vi.mocked(api.get).mock.calls.filter(([u]) => u === "/payables/bills").length;

    fireEvent.change(screen.getByLabelText(/buscar fornecedor ou descri/i), {
      target: { value: "anthropic" },
    });

    await waitFor(() => {
      expect(paramsDaUltimaBusca().q).toBe("anthropic");
    });
    const depois = vi.mocked(api.get).mock.calls.filter(([u]) => u === "/payables/bills").length;
    expect(depois - antes).toBe(1);
  });

  it("trocar o status para Cancelado refaz a busca com o recorte novo", async () => {
    mockComConta([CONTA]);
    renderPagar();
    await screen.findByText("Aluguel");

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "canceled" } });

    await waitFor(() => {
      const params = paramsDaUltimaBusca();
      expect(params.status).toEqual(["canceled"]);
      expect(params.order).toBe("desc"); // historico se le do mais recente para tras
      expect(params.offset).toBe(0); // trocar filtro volta para a primeira pagina
    });
  });
});

describe("reativar conta cancelada (spec 2026-08-18, §6)", () => {
  const CONTA_CANCELADA = {
    ...CONTA_ABERTA,
    id: "b-9",
    description: "Assinatura cancelada",
    status: "canceled",
  };

  function renderPagar() {
    render(
      <MemoryRouter>
        <PageActionsProvider>
          <PagarPage />
        </PageActionsProvider>
      </MemoryRouter>,
    );
  }

  function mockComCancelada() {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: [CONTA_CANCELADA], total: 1 } } as never);
      return Promise.resolve({ data: [] } as never);
    });
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
  }

  it("linha cancelada oferece Reativar", async () => {
    mockComCancelada();
    renderPagar();

    expect(await screen.findByRole("button", { name: /reativar/i })).toBeInTheDocument();
  });

  it("linha aberta NAO oferece Reativar", async () => {
    mockComConta([CONTA]);
    renderPagar();
    await screen.findByText("Aluguel");

    expect(screen.queryByRole("button", { name: /reativar/i })).not.toBeInTheDocument();
  });

  it("Reativar chama a rota propria, nao /reverse", async () => {
    mockComCancelada();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPagar();

    fireEvent.click(await screen.findByRole("button", { name: /reativar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/payables/bills/b-9/reactivate"));
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Issue #224 — separador de milhar no valor digitado (parseCentsBRL)
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// A conta manual antiga (`Math.round(parseFloat(v.replace(",", ".")) * 100)`) só troca a PRIMEIRA
// vírgula por ponto e nunca remove o ponto de milhar: "1.234,56" vira "1.234.56", `parseFloat` para
// no segundo ponto e devolve 1.234 → 123 centavos, não 123456. `parseCentsBRL` (contas.ts) trata o
// milhar corretamente; estes testes fixam esse contrato nos dois sites de PagarPage.
describe("PagarPage — separador de milhar (#224)", () => {
  it("Nova conta: '1.234,56' vira 123456 centavos, não 123 (regressão do parseFloat cru)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova conta" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "1.234,56");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-08-01" } });
    await user.click(screen.getByRole("button", { name: "Adicionar conta" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/payables/bills",
      expect.objectContaining({ amount_cents: 123456 }),
    );
  });

  it("Editar conta: '1.234,56' vira 123456 centavos, não 123", async () => {
    const user = userEvent.setup();
    mockComConta([CONTA]);
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Editar" }));
    const valor = await screen.findByLabelText("Valor (R$)");
    await user.clear(valor);
    await user.type(valor, "1.234,56");
    await user.click(screen.getByRole("button", { name: "Salvar alterações" }));

    await waitFor(() => expect(vi.mocked(api.patch)).toHaveBeenCalled());
    expect(vi.mocked(api.patch)).toHaveBeenCalledWith(
      "/payables/bills/b-1",
      expect.objectContaining({ amount_cents: 123456 }),
    );
  });
});

// ── `GET /contracts` fora de forma (issue #225) ─────────────────────────────────
//
// `setContracts(r.data)` (dentro do `ContractSelect` local desta tela) recebia o payload CRU no
// caminho de sucesso — só o `.catch` da rejeição tratava a forma. `contracts.map` (select
// "Vincular a contrato") é montado direto assim que o modal "Nova conta" abre.
describe("PagarPage — contratos fora de forma não derrubam o modal Nova conta (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
  ])("%s → o modal abre, com o select de contrato vazio", async (_rotulo, payload) => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills") return Promise.resolve({ data: { items: [], total: 0 } } as never);
      if (url === "/contracts") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Nova conta" }));
    await assentar();

    expect(screen.getByText("Vincular a contrato (opcional)")).toBeInTheDocument();
    expect(screen.getByText("Empresa (sem contrato)")).toBeInTheDocument();
  });

  it("contra-teste: contrato de verdade continua aparecendo no select", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills") return Promise.resolve({ data: { items: [], total: 0 } } as never);
      if (url === "/contracts")
        return Promise.resolve({ data: [{ id: "ct-1", title: "Consultoria", client_name: null }] } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Nova conta" }));
    await assentar();

    expect(await screen.findByText("Consultoria")).toBeInTheDocument();
  });
});

// ── `GET /payables/summary` fora de forma (issue #247) ──────────────────────────────────
//
// `setSummary(s.data)` recebia o payload CRU. `summary.open_cents`/etc. são lidos direto nos
// cartões, sem `?.` — uma raiz fora de forma faz `null.open_cents` estourar.
describe("PagarPage — resumo fora de forma não derruba a tela (#247)", () => {
  it.each([
    ["array no lugar do objeto", [{ open_cents: 100 }]],
    ["string no lugar do objeto", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela segue montada, com os cartões zerados", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: payload } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: [], total: 0 } } as never);
      return Promise.resolve({ data: [] } as never);
    });
    // `mockClear()`: sem isto, `toHaveBeenCalledWith` abaixo acha uma chamada de um teste ANTERIOR
    // (o mock nunca é limpo entre testes, só reimplementado) e o `waitFor` resolve na hora — antes
    // mesmo do debounce de 300ms (linha ~182) desta montagem disparar. Medido: sem o `mockClear`,
    // o teste "passa" mesmo com a guarda removida, porque nunca espera o bastante para o commit
    // real acontecer — falsa confiança do mesmo tipo que o docstring de `assentar.ts` descreve.
    vi.mocked(api.get).mockClear();
    renderPage();
    // `waitFor` polla com relógio de VERDADE (timeout default ~1s) até `/payables/summary` ter
    // sido chamado NESTA montagem — só então o debounce já disparou e o commit de `setSummary`
    // aconteceu. `assentar()` sozinho não basta: ele só esvazia microtarefas, não temporizadores.
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/payables/summary"));
    await assentar();

    expect(screen.getByRole("button", { name: "Nova conta" })).toBeInTheDocument();
    expect(screen.getAllByText("R$ 0,00").length).toBeGreaterThan(0);
  });
});

// ── `GET /payables/bills` fora de forma (issue #247) ─────────────────────────────────────
//
// `setBills(b.data.items)`/`setTotal(b.data.total)` recebiam o CAMPO cru — `bills.map` roda no
// render sem guarda, e `[...antes, ...b.data.items]` (página seguinte) estouraria num spread de
// `undefined`. A guarda é por CAMPO (`Array.isArray(b.data?.items)`), não pela raiz.
describe("PagarPage — página de contas fora de forma não derruba a lista (#247)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["objeto sem a chave items", { total: 3 }],
    ["array no lugar do objeto (raiz certa, campo errado)", [{ id: "x" }]],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a lista segue montada, vazia", async (_rotulo, payload) => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills") return Promise.resolve({ data: payload } as never);
      return Promise.resolve({ data: [] } as never);
    });
    // `mockClear()` + `waitFor` na chamada real (não em "Nenhuma conta", que já está no DOM desde
    // o estado inicial `bills = []` — a MESMA falsa confiança que o docstring de `assentar.ts`
    // descreve): sem isto o teste passaria mesmo com a guarda removida, porque nunca esperaria o
    // debounce de 300ms (linha ~182) o bastante para o commit de `setBills` realmente acontecer.
    vi.mocked(api.get).mockClear();
    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/payables/summary"));
    await assentar();

    expect(screen.getByRole("button", { name: "Nova conta" })).toBeInTheDocument();
    expect(await screen.findByText(/Nenhuma conta/i)).toBeInTheDocument();
  });

  it("contra-teste: conta de verdade continua aparecendo na lista", async () => {
    mockComConta([CONTA]);
    renderPage();
    await assentar();

    expect(await screen.findByText("Aluguel")).toBeInTheDocument();
  });
});

// ── chartAccounts/costCenters/inbox fora de forma (issue #252) ───────────────────────────
//
// `setChartAccounts(ca.data)`/`setCostCenters(cc.data)` alimentam `FiltrosDaLista` (`.map` direto,
// sem `Array.isArray`), e `setInbox(pend.data)` alimenta o aviso da bandeja (`.length`/`[0].id`).
// Um payload fora de forma faria `.map is not a function` (ou `.length` num objeto/string sem
// sentido) estourar em qualquer um dos três.
describe("PagarPage — filtros e bandeja fora de forma não derrubam a tela (#252)", () => {
  it("chartAccounts/costCenters fora de forma → os filtros seguem montados, sem estourar", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: [], total: 0 } } as never);
      if (url === "/chart-of-accounts")
        return Promise.resolve({ data: { detail: "erro" } } as never);
      if (url === "/cost-centers") return Promise.resolve({ data: "não é json" } as never);
      return Promise.resolve({ data: [] } as never);
    });
    // `mockClear()` + `waitFor` na chamada real: sem isto o teste passaria mesmo com a guarda
    // removida, porque nunca esperaria o debounce de 300ms (linha ~185) o bastante para o commit
    // de `setChartAccounts`/`setCostCenters` realmente acontecer — a mesma falsa confiança que o
    // docstring de `assentar.ts` descreve (medido: sem isto este mutante SOBREVIVE).
    vi.mocked(api.get).mockClear();
    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/chart-of-accounts"));
    await assentar();

    expect(screen.getByText("Todas as categorias")).toBeInTheDocument();
    expect(screen.getByText("Todos os centros")).toBeInTheDocument();
  });

  it("inbox (comprovantes) fora de forma → sem aviso, sem estourar", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: [], total: 0 } } as never);
      // ⚠️ Um OBJETO (`{ detail: ... }`) não serve aqui: `inbox.length` sobre ele é `undefined`,
      // `undefined > 0` é falso, e o aviso já nasce escondido pelo PRÓPRIO `inbox.length > 0` —
      // o mutante (payload cru) sobrevive porque nunca chega a executar `inbox[0].id`. `null` é
      // o payload que de fato força a leitura: `null.length` estoura sem a guarda.
      if (url === "/payables/receipts") return Promise.resolve({ data: null } as never);
      return Promise.resolve({ data: [] } as never);
    });
    // Mesma razão do teste acima: espera a chamada real antes de assentar.
    vi.mocked(api.get).mockClear();
    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/payables/receipts"));
    await assentar();

    expect(screen.getByRole("button", { name: "Nova conta" })).toBeInTheDocument();
    expect(screen.queryByText(/aguardando/i)).toBeNull();
  });

  it("contra-teste: categorias/centros/bandeja de verdade continuam aparecendo", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/payables/summary") return Promise.resolve({ data: emptySummary } as never);
      if (url === "/payables/bills")
        return Promise.resolve({ data: { items: [], total: 0 } } as never);
      if (url === "/chart-of-accounts")
        return Promise.resolve({ data: [{ id: "ca-1", categoria: "Estrutura" }] } as never);
      if (url === "/cost-centers")
        return Promise.resolve({ data: [{ id: "cc-1", name: "Sócio A" }] } as never);
      if (url === "/payables/receipts")
        return Promise.resolve({
          data: [{ id: "r-1", filename: "a.pdf", content_type: "application/pdf", size: 1, created_at: "2026-07-28T10:00:00Z" }],
        } as never);
      return Promise.resolve({ data: [] } as never);
    });
    renderPage();
    await assentar();

    expect(await screen.findByText("Estrutura")).toBeInTheDocument();
    expect(screen.getByText("Sócio A")).toBeInTheDocument();
    expect(screen.getByText(/1 comprovante aguardando/i)).toBeInTheDocument();
  });
});
