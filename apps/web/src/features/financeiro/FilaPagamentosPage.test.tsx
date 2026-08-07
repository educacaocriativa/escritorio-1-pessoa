import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import FilaPagamentosPage from "./FilaPagamentosPage";

/**
 * **Fila de Pagamentos — a terceira superfície de baixa (Story 8.13, AC6).**
 *
 * ⚠️ **Esta tela não tinha arquivo de teste, e foi por isso que ela quase foi para produção
 * quebrada.** A Story 8.12 tornou o corpo de `POST /payables/bills/{id}/pay` obrigatório; esta tela
 * chamava a rota **sem corpo**, com o comentário *"sem fluxo novo"*. Nenhum documento da Onda 2 a
 * nomeia — nem o epic, nem o design —, e nenhum teste a cobria: a quebra só apareceria no clique de
 * um usuário real. O teste existe para que a próxima mudança no contrato de `/pay` derrube a suíte
 * antes de derrubar a tela.
 */

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  // O `apiErrorMessage` real depende de `instanceof AxiosError`, que um erro forjado não satisfaz.
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

const CONTA = {
  id: "acc-1", name: "Itaú PJ", kind: "checking", is_primary: true, archived_at: null,
  opening_balance_cents: 0, opening_date: "2026-01-01",
  saldo_derivado_cents: 0, saldo_derivado_origem: "banco",
};

const ATRASADA = {
  id: "b-1", description: "Energia", supplier: "Copel", amount_cents: 30000,
  due_date: "2026-06-10", status: "open", is_overdue: true, paid_at: null,
  recurrence: "none", recurrence_count: 1, recurrence_group: null, payment_code: "",
  attachment_url: "", created_at: "2026-01-01T00:00:00Z", tenant_id: "t-1",
  competence_date: null, chart_account_id: null, contract_id: null, cost_center_id: null,
};

const FILA = {
  atrasados: [ATRASADA],
  hoje: [],
  proximos_7_dias: [],
  proximos_30_dias: [],
  summary: {
    atrasados_count: 1, atrasados_cents: 30000,
    hoje_count: 0, hoje_cents: 0,
    proximos_7_dias_count: 0, proximos_7_dias_cents: 0,
    proximos_30_dias_count: 0, proximos_30_dias_cents: 0,
  },
};

/** Story 8.14 — a conta cujo débito já tem dia marcado. Vence 10/06, sai 20/06. */
const AGENDADA = {
  ...ATRASADA,
  id: "b-agendada",
  description: "Aluguel",
  supplier: "Imobiliária",
  amount_cents: 500000,
  status: "scheduled",
  is_overdue: false,
  paid_at: "2026-06-20T00:00:00Z",
};

const FILA_COM_AGENDADA = {
  ...FILA,
  agendadas: [AGENDADA],
  summary: { ...FILA.summary, agendadas_count: 1, agendadas_cents: 500000 },
};

function mockApi(contas: unknown[] = [CONTA], fila: unknown = FILA) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/payables/queue") return Promise.resolve({ data: fila } as never);
    if (url === "/bank/accounts") return Promise.resolve({ data: contas } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

async function abrirBaixa() {
  const user = userEvent.setup();
  render(<FilaPagamentosPage />);
  await user.click(await screen.findByRole("button", { name: /marcar pago/i }));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("FilaPagamentosPage — a fila continua funcionando (IV2)", () => {
  it("lista os baldes e os totais do resumo, exatamente como o backend mandou", async () => {
    mockApi();
    render(<FilaPagamentosPage />);

    // Os números da fila e do `PaymentQueueSummary` são IDÊNTICOS antes e depois desta story: o
    // backend não foi tocado e os baldes seguem calculados na leitura, por `due_date`.
    expect(await screen.findByText("Atrasados")).toBeTruthy();
    expect(screen.getAllByText("R$ 300,00").length).toBeGreaterThan(0);
    expect(screen.getByText("Energia")).toBeTruthy();
    expect(screen.getByText(/Total pendente na fila/)).toBeTruthy();
  });

  it("balde vazio não vira seção vazia (o resumo continua contando 0)", async () => {
    mockApi();
    render(<FilaPagamentosPage />);

    await screen.findByText("Atrasados");
    // "Hoje"/"Próximos 7 dias" existem no RESUMO (os cartões), mas não como seção de lista.
    expect(screen.getAllByText("Hoje")).toHaveLength(1);
  });
});

describe("FilaPagamentosPage — a baixa (Story 8.13, AC6)", () => {
  it("⚠️ o clique NÃO paga direto: abre a escolha de conta e dia", async () => {
    mockApi();
    await abrirBaixa();

    expect(api.post).not.toHaveBeenCalled();
    expect(await screen.findByText("Dar baixa nesta conta")).toBeTruthy();
  });

  it("paga com o corpo COMPLETO — era esta chamada que voltava 422 depois da 8.12", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirBaixa();

    await user.click(await screen.findByRole("button", { name: /confirmar baixa/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0]).toEqual([
      "/payables/bills/b-1/pay",
      // A conta primária pré-selecionada e o dia = vencimento da conta (F10), não hoje.
      { bank_account_id: "acc-1", paid_on: "2026-06-10" },
    ]);
  });

  it("recarrega a fila depois da baixa (o item sai do balde)", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirBaixa();

    await user.click(await screen.findByRole("button", { name: /confirmar baixa/i }));

    await waitFor(() =>
      expect(
        vi.mocked(api.get).mock.calls.filter(([u]) => String(u) === "/payables/queue"),
      ).toHaveLength(2),
    );
  });

  it("409 acionável → cadastro embutido → retoma, pelo MESMO fluxo das outras telas", async () => {
    mockApi([]);
    await abrirBaixa();

    // Sem conta nenhuma, a tela oferece o cadastro em vez de um seletor vazio, e a confirmação
    // fica desabilitada — silêncio, nunca um palpite sobre para onde vai o dinheiro.
    expect(await screen.findByText(/precisa saber de qual conta bancária o dinheiro saiu/i))
      .toBeTruthy();
    expect(screen.getByRole("button", { name: /confirmar baixa/i })).toBeDisabled();

    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url === "/bank/accounts") {
        return Promise.resolve({ data: { ...CONTA, id: "acc-nova", name: "Nubank PJ" } } as never);
      }
      return Promise.resolve({ data: {} } as never);
    });

    await userEvent.click(screen.getByRole("button", { name: /cadastrar conta bancária/i }));
    await userEvent.type(screen.getByLabelText("Nome da conta"), "Nubank PJ");
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar conta" }));

    const retomar = await screen.findByRole("button", { name: /sai do Nubank PJ/i });
    await userEvent.click(retomar);

    await waitFor(() =>
      expect(
        vi.mocked(api.post).mock.calls.filter(([u]) => String(u) === "/payables/bills/b-1/pay"),
      ).toHaveLength(1),
    );
    expect(
      vi.mocked(api.post).mock.calls.find(([u]) => String(u) === "/payables/bills/b-1/pay")?.[1],
    ).toMatchObject({ bank_account_id: "acc-nova" });
  });

  it("erro do backend é exibido como veio, e a fila não some da tela", async () => {
    mockApi();
    vi.mocked(api.post).mockRejectedValue({
      response: { data: { detail: "Só contas em aberto podem ser pagas." } },
    });
    const user = await abrirBaixa();

    await user.click(await screen.findByRole("button", { name: /confirmar baixa/i }));

    expect(await screen.findByText("Só contas em aberto podem ser pagas.")).toBeTruthy();
    // A fila continua na tela por trás do diálogo (o nome aparece nos dois — lista e resumo da
    // confirmação), então a asserção é "não sumiu", não "aparece uma vez".
    expect(screen.getAllByText("Energia").length).toBeGreaterThan(0);
  });

  it("em ~360px a linha da fila QUEBRA em vez de empurrar o botão para fora (AC9)", async () => {
    mockApi();
    render(<FilaPagamentosPage />);

    const botao = await screen.findByRole("button", { name: /marcar pago/i });
    const linha = botao.closest("li") as HTMLElement;
    // `flex-wrap`: descrição + valor + copiar + baixa não cabem em 360px numa linha só. Sem ele,
    // o botão que comete a ação sai da área visível — o defeito dos PRs #56/#58, aqui pela ponta.
    expect(linha.className).toContain("flex-wrap");

    // ⚠️ `flex-wrap` SOZINHO NÃO QUEBRA A LINHA — e esta asserção sozinha passava com a tela
    // quebrada (aceite físico do AC9, 2026-08-06). Com `flex-1` (base 0%) + `min-w-0`, a descrição
    // encolhe até caber no que sobra em vez de forçar a quebra: 29px de largura num aparelho de
    // 360px, o nome da conta empilhando uma palavra por linha ao longo de ~300px de altura, com o
    // valor colidindo no meio. Quem quebra a linha é a BASE 100% da descrição. jsdom não calcula
    // layout, então o contrato verificável aqui é a classe — a medição real está no Dev Agent
    // Record da story.
    const descricao = linha.firstElementChild as HTMLElement;
    expect(descricao.className).toContain("basis-full");
    // `grow`, não `flex-1`: o shorthand `flex` reintroduz `flex-basis: 0%` e desfaz o `basis-full`
    // dependendo da ordem das regras do Tailwind. Trocar de volta reabre o defeito em silêncio.
    expect(descricao.className).not.toContain("flex-1");
  });
});

// ── Story 8.14 — o QUINTO balde ───────────────────────────────────────────────────────────────

describe("Story 8.14 — a conta agendada não some da Fila", () => {
  beforeEach(() => vi.clearAllMocks());

  it("aparece num balde próprio, com a data do DÉBITO — e sem botão de baixa", async () => {
    // **Esconder é erro; misturar também.** Sem o balde, uma saída certa de R$ 5.000 sumiria da
    // única tela que responde "o que sai do meu caixa nos próximos dias". E oferecer "Marcar pago"
    // aqui convidaria a uma segunda baixa do MESMO dinheiro.
    mockApi([CONTA], FILA_COM_AGENDADA);
    render(<FilaPagamentosPage />);

    expect(await screen.findByText("Agendadas")).toBeInTheDocument();
    expect(screen.getByText("Aluguel")).toBeInTheDocument();
    expect(screen.getByText(/sai 20\/06\/2026/)).toBeInTheDocument();
    // Um único "Marcar pago" na tela: o da conta ATRASADA, não o da agendada.
    expect(screen.getAllByRole("button", { name: /marcar pago/i })).toHaveLength(1);
  });

  it("o balde é OMITIDO quando não há agendada — e o payload antigo não quebra a tela", async () => {
    // `FILA` é o payload de um backend anterior à 8.14 (sem a chave `agendadas`): a tela tolera a
    // ausência em vez de estourar em `undefined.length`.
    mockApi();
    render(<FilaPagamentosPage />);

    await waitFor(() => expect(screen.getByText("Energia")).toBeInTheDocument());
    expect(screen.queryByText("Agendadas")).toBeNull();
  });

  it("o agendado fica FORA do 'total pendente' — ele não é pendência, já foi resolvido", async () => {
    mockApi([CONTA], FILA_COM_AGENDADA);
    render(<FilaPagamentosPage />);

    // Só a atrasada (R$ 300,00) entra no total; os R$ 5.000 agendados, não.
    const total = await screen.findByText(/Total pendente na fila/);
    // `within` porque o valor vive num `<strong>` aninhado — e comparação por nó, não por string
    // crua: `toLocaleString` usa espaço NÃO-QUEBRÁVEL depois de "R$", e `textContent` o preserva.
    expect(within(total).getByText("R$ 300,00")).toBeInTheDocument();
    expect(within(total).queryByText(/5\.300/)).toBeNull();
  });
});
