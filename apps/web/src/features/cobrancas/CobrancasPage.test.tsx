import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import CobrancasPage from "./CobrancasPage";

// Story 7.5 — Task 2. Rede sempre mockada (IV2): nenhum teste bate em /receivables real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

const emptySummary = {
  open_cents: 0,
  overdue_cents: 0,
  paid_cents: 0,
  open_count: 0,
  overdue_count: 0,
  scheduled_cents: 0,
};

// Estratégia (a) da Task 0 — replica o contrato da topbar sem importar o AppShell.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <CobrancasPage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/receivables/summary") return Promise.resolve({ data: emptySummary } as never);
    if (url === "/receivables/charges") return Promise.resolve({ data: [] } as never);
    if (url === "/crm/clients") return Promise.resolve({ data: [] } as never);
    if (url === "/contracts") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("CobrancasPage — Nova cobrança (Story 7.5, Task 2)", () => {
  it("caminho feliz: cria cobrança com valor + vencimento; POST com amount_cents coerente", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova cobrança" }));

    await user.type(screen.getByLabelText("Valor (R$)"), "150,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-09-10" } });

    await user.click(screen.getByRole("button", { name: "Gerar cobrança" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/receivables/charges",
      expect.objectContaining({ amount_cents: 15000, due_date: "2026-09-10" }),
    );
  });

  it("caminho infeliz: erro do backend é exibido sem quebrar a tela (modal segue aberto)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Vencimento inválido." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Nova cobrança" }));
    await user.type(screen.getByLabelText("Valor (R$)"), "150,00");
    fireEvent.change(screen.getByLabelText("Vencimento"), { target: { value: "2026-09-10" } });
    await user.click(screen.getByRole("button", { name: "Gerar cobrança" }));

    expect(await screen.findByText("Vencimento inválido.")).toBeInTheDocument();
    // Título do modal (heading) — desambigua do botão "Nova cobrança" da topbar.
    expect(screen.getByRole("heading", { name: "Nova cobrança" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerar cobrança" })).toBeEnabled();
  });
});

// ══════════════════════════════════════════════════════════════════════════════════════════════
// Story 8.15 — "Recebi direto na conta": a porta que não existia
// ══════════════════════════════════════════════════════════════════════════════════════════════
//
// Hoje o dono NÃO tem como dizer que uma cobrança caiu direto no banco dele: o botão "Marcar paga"
// foi removido de propósito (só o webhook do gateway marca pago), e a cobrança paga por fora fica
// em aberto para sempre — com a régua mandando lembrete a quem já pagou.

/** Hoje como data de calendário local — a mesma regra de `contas.hojeISO`. */
function hoje(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

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

const COBRANCA_ABERTA = {
  id: "c-1",
  tenant_id: "t-1",
  client_id: null,
  client_name: "Joana Ré",
  description: "Consultoria",
  kind: "service",
  method: "pix",
  amount_cents: 100000,
  due_date: "2026-08-10",
  competence_date: "2026-08-10",
  paid_at: null,
  chart_account_id: null,
  contract_id: null,
  cost_center_id: null,
  status: "open",
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

function mockCobrancas(charges: unknown[], contas: unknown[] = [CONTA_BANCARIA], resumo = emptySummary) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/receivables/summary") return Promise.resolve({ data: resumo } as never);
    if (url === "/receivables/charges") return Promise.resolve({ data: charges } as never);
    if (url === "/bank/accounts") return Promise.resolve({ data: contas } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

describe("CobrancasPage — recebimento fora do trilho (Story 8.15)", () => {
  async function abrirRegistro() {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Recebi direto na conta" }));
    return user;
  }

  it("⚠️ o rótulo é o FATO e NÃO é 'Marcar paga' — aquele botão foi removido de propósito", async () => {
    mockCobrancas([COBRANCA_ABERTA]);
    renderPage();

    expect(await screen.findByRole("button", { name: "Recebi direto na conta" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /marcar paga/i })).toBeNull();
  });

  it("convive com o 'simular pgto' sem ambiguidade: um finge o gateway, o outro registra o que aconteceu fora dele", async () => {
    mockCobrancas([COBRANCA_ABERTA]);
    renderPage();

    const linha = (await screen.findByRole("table")).querySelector("tbody tr") as HTMLElement;
    expect(within(linha).getByRole("button", { name: "Recebi direto na conta" })).toBeInTheDocument();
    expect(within(linha).getByRole("button", { name: "simular pgto" })).toBeInTheDocument();
  });

  it("a porta aparece SÓ em cobrança aberta (nem paga, nem agendada, nem cancelada)", async () => {
    mockCobrancas([
      { ...COBRANCA_ABERTA, id: "c-paga", status: "paid", transaction_id: "tx-1" },
      { ...COBRANCA_ABERTA, id: "c-cancelada", status: "canceled" },
      {
        ...COBRANCA_ABERTA,
        id: "c-agendada",
        status: "scheduled",
        bank_account_id: "acc-1",
        paid_at: "2026-08-20T00:00:00Z",
      },
    ]);
    renderPage();

    await screen.findByText("Recebido");
    expect(screen.queryByRole("button", { name: "Recebi direto na conta" })).toBeNull();
  });

  it("o clique NÃO registra direto: abre a confirmação com conta e dia", async () => {
    mockCobrancas([COBRANCA_ABERTA]);
    await abrirRegistro();

    expect(api.post).not.toHaveBeenCalled();
    expect(await screen.findByText("Recebi direto na conta", { selector: "h3, h2, p" })).toBeTruthy();
    expect(screen.getByLabelText(/conta bancária onde o dinheiro caiu/i)).toBeInTheDocument();
  });

  it("⚠️ o seletor e o botão de confirmar estão no MESMO bloco (a lição dos PRs #56 e #58)", async () => {
    // Não é estilo: duas vezes uma ação de dinheiro foi cometida com o controle que a torna
    // efetiva fora da área visível em ~360px. Terceira vez seria imperdoável. A asserção é
    // estrutural — o `<select>` está DENTRO do container direto do botão.
    mockCobrancas([COBRANCA_ABERTA]);
    await abrirRegistro();

    const botao = await screen.findByRole("button", { name: /confirmar recebimento/i });
    const bloco = botao.parentElement as HTMLElement;
    expect(within(bloco).getByLabelText(/conta bancária onde o dinheiro caiu/i)).toBeInTheDocument();
    expect(within(bloco).getByLabelText(/dia em que o dinheiro caiu na conta/i)).toBeInTheDocument();
  });

  it("envia bank_account_id e received_on; o dia default é HOJE (não o vencimento)", async () => {
    mockCobrancas([COBRANCA_ABERTA]);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirRegistro();

    const dia = (await screen.findByLabelText(/dia em que o dinheiro caiu na conta/i)) as HTMLInputElement;
    // O gesto aqui é "caiu na minha conta", um fato observado AGORA — diferente da baixa de Contas
    // a Pagar, que parte do vencimento (fundador F10). A assimetria é deliberada.
    expect(dia.value).toBe(hoje());
    expect(dia.value).not.toBe(COBRANCA_ABERTA.due_date);

    await user.click(screen.getByRole("button", { name: /confirmar recebimento/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0]).toEqual([
      "/receivables/charges/c-1/settle-externally",
      { bank_account_id: "acc-1", received_on: hoje() },
    ]);
  });

  it("a conta primária vem pré-selecionada e o NOME dela aparece no próprio botão", async () => {
    mockCobrancas([COBRANCA_ABERTA]);
    await abrirRegistro();

    const seletor = (await screen.findByLabelText(
      /conta bancária onde o dinheiro caiu/i,
    )) as HTMLSelectElement;
    expect(seletor.value).toBe("acc-1");
    // Pré-selecionar não é tornar opcional: o default tem de estar VISÍVEL — daí "caiu no Itaú PJ".
    expect(screen.getByRole("button", { name: /caiu no Itaú PJ/i })).toBeInTheDocument();
  });

  it("a conta é OBRIGATÓRIA: sem primária nada é escolhido e a confirmação fica DESABILITADA", async () => {
    mockCobrancas(
      [COBRANCA_ABERTA],
      [
        { ...CONTA_BANCARIA, id: "a", name: "Conta A", is_primary: false },
        { ...CONTA_BANCARIA, id: "b", name: "Conta B", is_primary: false },
      ],
    );
    await abrirRegistro();

    const seletor = (await screen.findByLabelText(
      /conta bancária onde o dinheiro caiu/i,
    )) as HTMLSelectElement;
    expect(seletor.value).toBe(""); // silêncio, nunca um palpite sobre onde o dinheiro caiu
    expect(screen.getByRole("button", { name: /confirmar recebimento/i })).toBeDisabled();
  });

  it("409 acionável → cadastro EMBUTIDO → RETOMA o registro com a conta nova selecionada", async () => {
    mockCobrancas([COBRANCA_ABERTA], [{ ...CONTA_BANCARIA, name: "Conta velha" }]);
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

    const user = await abrirRegistro();
    await user.click(await screen.findByRole("button", { name: /confirmar recebimento/i }));

    // (1) A mensagem do BACKEND aparece como veio — reconhecida por `acao`, não por substring.
    expect(await screen.findByText(mensagem409)).toBeInTheDocument();
    // (2) O cadastro abre ALI MESMO, sem tirar o dono da cobrança que ele estava registrando.
    expect(screen.getByRole("heading", { name: "Nova conta" })).toBeInTheDocument();
    // (3) Cadastra pelo formulário embutido (o MESMO de Contas & Saldos).
    await user.type(screen.getByLabelText("Nome da conta"), "Nubank PJ");
    await user.click(screen.getByRole("button", { name: "Cadastrar conta" }));
    // (4) O registro é RETOMADO com a conta recém-criada já selecionada.
    await user.click(await screen.findByRole("button", { name: /caiu no Nubank PJ/i }));

    await waitFor(() =>
      expect(
        vi
          .mocked(api.post)
          .mock.calls.filter(([u]) => String(u) === "/receivables/charges/c-1/settle-externally"),
      ).toHaveLength(2),
    );
    const ultima = vi
      .mocked(api.post)
      .mock.calls.filter(([u]) => String(u) === "/receivables/charges/c-1/settle-externally")
      .at(-1);
    expect(ultima?.[1]).toMatchObject({ bank_account_id: "acc-nova" });
  });

  it("tenant SEM conta nenhuma: a tela oferece o cadastro em vez de um seletor vazio", async () => {
    mockCobrancas([COBRANCA_ABERTA], []);
    await abrirRegistro();

    expect(
      await screen.findByText(/precisa saber em qual conta bancária o dinheiro caiu/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cadastrar conta bancária/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirmar recebimento/i })).toBeDisabled();
  });

  it("data futura AVISA (não impede): o registro nasce AGENDADO", async () => {
    mockCobrancas([COBRANCA_ABERTA]);
    const user = await abrirRegistro();

    const dia = await screen.findByLabelText(/dia em que o dinheiro caiu na conta/i);
    fireEvent.change(dia, { target: { value: "2099-01-01" } });

    expect(await screen.findByText(/será registrado como AGENDADO/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirmar recebimento/i })).toBeEnabled();
    expect(dia.getAttribute("max")).toBeNull(); // sem teto: futuro é agendamento, não erro
    await user.click(screen.getByRole("button", { name: /confirmar recebimento/i }));
  });

  it("a linha liquidada fora do trilho mostra QUAL conta recebeu e QUANDO", async () => {
    mockCobrancas([
      {
        ...COBRANCA_ABERTA,
        id: "c-fora",
        status: "paid",
        bank_account_id: "acc-1",
        bank_transaction_id: "bt-1",
        paid_at: "2026-08-04T00:00:00Z",
      },
    ]);
    renderPage();

    expect(await screen.findByText("caiu no Itaú PJ em 04/08")).toBeInTheDocument();
  });

  it("a linha do TRILHO não ganha rótulo de rota — 'Recebido' já é a leitura certa", async () => {
    mockCobrancas([
      { ...COBRANCA_ABERTA, id: "c-trilho", status: "paid", transaction_id: "tx-1" },
    ]);
    renderPage();

    await screen.findByText("Recebido");
    expect(screen.queryByText(/caiu no/i)).toBeNull();
  });

  it("a cobrança AGENDADA tem rótulo próprio — nem 'Recebido' nem 'A vencer'", async () => {
    mockCobrancas(
      [
        {
          ...COBRANCA_ABERTA,
          id: "c-agendada",
          status: "scheduled",
          bank_account_id: "acc-1",
          paid_at: "2026-08-20T00:00:00Z",
        },
      ],
      [CONTA_BANCARIA],
      { ...emptySummary, scheduled_cents: 100000 },
    );
    renderPage();

    const tabela = await screen.findByRole("table");
    expect(within(tabela).getByText("Agendado")).toBeInTheDocument();
    expect(within(tabela).queryByText("Recebido")).toBeNull();
    expect(within(tabela).queryByText("A vencer")).toBeNull();
    // E o valor não some da tela: ele tem cartão próprio (fora de "A vencer" e de "Recebido").
    expect(screen.getByText("Agendado para entrar")).toBeInTheDocument();
  });

  it("o cartão 'Agendado para entrar' SOME quando é zero (mesmo tratamento da 8.14)", async () => {
    mockCobrancas([COBRANCA_ABERTA]);
    renderPage();

    await screen.findByRole("table");
    expect(screen.queryByText("Agendado para entrar")).toBeNull();
  });
});
