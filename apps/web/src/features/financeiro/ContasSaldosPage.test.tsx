import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import ContasSaldosPage from "./ContasSaldosPage";
import type { BankAccount, BankBalanceCheckpoint, BankTransaction } from "./contas";
import { DISPONIVEL_CAIXA_LABEL, TOTAL_EM_CONTAS_LABEL } from "./contas";
import { ROTULO_BANCO } from "./projecao";

/**
 * Testes de componente de Contas & Saldos (Story 8.7).
 *
 * O teste que dá nome a esta suíte é o da **divergência D-6**: esta tela e a Projeção de Caixa
 * (Story 8.8) exibem somas de saldo bancário com recortes DIFERENTES — a de lá exclui as
 * aplicações. Se as duas saíssem com o mesmo nome, o dono veria dois números conflitantes para a
 * mesma pergunta, e num produto cujo valor inteiro é ser testemunha confiável do dado isso não é
 * um detalhe de UI.
 *
 * (Sobre existir teste de componente aqui apesar do AC7 dizer que não há infra: ver a nota em
 * `ConferenciaPage.test.tsx` — a premissa da story está desatualizada desde a Story 7.3.)
 */
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

function conta(over: Partial<BankAccount> = {}): BankAccount {
  return {
    id: "acc-1",
    name: "Itaú PJ",
    kind: "checking",
    institution: "Itaú",
    institution_code: "341",
    branch: "1234",
    number: "56789-0",
    holder_document: "",
    pix_key: "",
    opening_balance_cents: 0,
    opening_date: "2026-01-01",
    is_primary: true,
    archived_at: null,
    saldo_derivado_cents: 4_000_000,
    saldo_derivado_origem: "banco",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

const checkpoint: BankBalanceCheckpoint = {
  id: "cp-1",
  bank_account_id: "acc-1",
  reference_date: "2026-07-28",
  balance_cents: 4_000_000,
  balance_origem: "banco",
  origin: "manual",
  created_by: "u-1",
  created_at: "2026-07-28T12:00:00Z",
};

function movimento(over: Partial<BankTransaction> = {}): BankTransaction {
  return {
    id: "tx-1",
    bank_account_id: "acc-1",
    posted_at: "2026-07-10",
    amount_cents: -80_000,
    raw_description: "Aluguel",
    user_description: "",
    description: "Aluguel",
    counterparty_name: "",
    counterparty_document: "",
    operation_nature: null,
    source: "manual",
    status: "unmatched",
    ignored_reason: "",
    created_at: "2026-07-10T12:00:00Z",
    updated_at: "2026-07-10T12:00:00Z",
    ...over,
  };
}

/** Mock de `api.get` que responde por URL (a página faz contas + checkpoints em paralelo). */
function mockApi(
  accounts: BankAccount[],
  checkpoints: BankBalanceCheckpoint[] = [],
  txs: BankTransaction[] = [],
) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/bank/accounts") return Promise.resolve({ data: accounts } as never);
    if (url.includes("/checkpoints")) return Promise.resolve({ data: checkpoints } as never);
    if (url === "/bank/transactions") return Promise.resolve({ data: txs } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PageActionsProvider>
        <ContasSaldosPage />
      </PageActionsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("⚠️ D-6 — os dois totais de saldo bancário do produto não podem ter o mesmo nome", () => {
  const comAplicacao = [
    conta({ id: "a", name: "Itaú PJ", kind: "checking", saldo_derivado_cents: 4_000_000 }),
    conta({ id: "b", name: "Poupança", kind: "savings", saldo_derivado_cents: 2_000_000 }),
    conta({ id: "c", name: "CDB", kind: "investment", saldo_derivado_cents: 4_000_000 }),
  ];

  it("exibe DOIS totais rotulados, e nenhum deles usa o rótulo da Projeção ('no banco')", async () => {
    mockApi(comAplicacao);
    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument());
    expect(screen.getByText(DISPONIVEL_CAIXA_LABEL)).toBeInTheDocument();

    // R$ 100.000 no total; R$ 60.000 como caixa (a aplicação fica de fora).
    expect(screen.getByText(/100\.000,00/)).toBeInTheDocument();
    expect(screen.getByText(/60\.000,00/)).toBeInTheDocument();

    // ⚠️ O ponto: "no banco" é o nome da PARCELA da Projeção de Caixa (Story 8.8), que é outro
    // recorte. Esta tela nunca o usa — nem como rótulo, nem no texto de apoio. A procedência por
    // conta continua dita, pelo vocabulário canônico do eixo A ("saldo da sua conta bancária"),
    // que é justamente por que esta exclusão é possível sem perder informação.
    expect(container.textContent).not.toContain(ROTULO_BANCO);
    expect(screen.getAllByText("saldo da sua conta bancária").length).toBe(3);
  });

  it("cada total diz o que inclui — o número nunca aparece sem a explicação", async () => {
    mockApi(comAplicacao);
    renderPage();

    await waitFor(() => expect(screen.getByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument());
    expect(screen.getByText(/incluindo aplicações/i)).toBeInTheDocument();
    expect(screen.getByText(/Exclui as aplicações/i)).toBeInTheDocument();
  });

  it("sem aplicação, um total só (os recortes coincidem e a 2ª linha viraria ruído)", async () => {
    mockApi([conta({ id: "a", saldo_derivado_cents: 4_000_000 })]);
    renderPage();

    await waitFor(() => expect(screen.getByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument());
    expect(screen.queryByText(DISPONIVEL_CAIXA_LABEL)).toBeNull();
  });
});

describe("AC6 — o consolidado nunca aparece sozinho: a decomposição está na mesma tela", () => {
  it("as contas aparecem uma a uma, com saldo e procedência coladas ao número", async () => {
    mockApi([
      conta({ id: "a", name: "Itaú PJ", saldo_derivado_cents: 4_000_000 }),
      conta({ id: "b", name: "Nubank PJ", saldo_derivado_cents: 2_000_000 }),
    ]);
    renderPage();

    await waitFor(() => expect(screen.getByText("Itaú PJ")).toBeInTheDocument());
    expect(screen.getByText("Nubank PJ")).toBeInTheDocument();
    // Regra dos Planos §1.3c: nenhum saldo na tela sem a origem ao lado.
    expect(screen.getAllByText("saldo da sua conta bancária")).toHaveLength(2);
    // Nada de "expandir": a lista está renderizada junto do total.
    expect(screen.queryByText(/expandir/i)).toBeNull();
  });
});

describe("AC1/AC2/AC3 — as portas e as ações por conta", () => {
  it('cada conta tem "Conferir" apontando para a rota fora do menu, com o account_id', async () => {
    mockApi([conta({ id: "acc-42" })]);
    renderPage();

    const link = await screen.findByRole("link", { name: /Conferir/ });
    expect(link).toHaveAttribute("href", "/financeiro/conferencia?account_id=acc-42");
  });

  it("oferece declarar saldo e lançar movimento por conta — e NÃO oferece excluir", async () => {
    mockApi([conta()]);
    renderPage();

    await waitFor(() => expect(screen.getByText("Declarar saldo")).toBeInTheDocument());
    expect(screen.getByText("Lançar movimento")).toBeInTheDocument();
    expect(screen.getByText("Arquivar")).toBeInTheDocument();
    // Não existe DELETE de conta na API (8.2) — oferecer o botão seria prometer o que não há.
    expect(screen.queryByText(/^Excluir/)).toBeNull();
  });

  it("mostra a data do último saldo declarado — ou diz que nunca houve", async () => {
    mockApi([conta()], [checkpoint]);
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Saldo declarado em 28\/07\/2026/)).toBeInTheDocument(),
    );
  });

  it("sem saldo declarado, diz isso em vez de mostrar uma data vazia", async () => {
    mockApi([conta()], []);
    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Nenhum saldo declarado ainda")).toBeInTheDocument(),
    );
  });

  it("conta arquivada aparece marcada e sem as ações de escrita", async () => {
    mockApi([conta({ archived_at: "2026-05-01T00:00:00Z" })]);
    renderPage();

    await waitFor(() => expect(screen.getByText("Arquivada")).toBeInTheDocument());
    expect(screen.queryByText("Declarar saldo")).toBeNull();
    expect(screen.queryByText("Lançar movimento")).toBeNull();
    expect(screen.queryByText("Arquivar")).toBeNull();
    // ...mas continua conferível: o estado final dela ainda é uma pergunta legítima.
    expect(screen.getByRole("link", { name: /Conferir/ })).toBeInTheDocument();
  });

  it("sem conta nenhuma, convida a cadastrar com o saldo que o banco já mostra", async () => {
    mockApi([]);
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Nenhuma conta cadastrada ainda/)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Cadastrar primeira conta" })).toBeInTheDocument();
    // Sem conta não há total nenhum a exibir — nem um R$ 0,00 com cara de fato.
    expect(screen.queryByText(TOTAL_EM_CONTAS_LABEL)).toBeNull();
  });
});

describe("REL-001 — as ações que mexem no saldo não podem falhar em silêncio", () => {
  /**
   * ⚠️ `ignorar`, `desfazerIgnorar` e `removerDeclaracao` chamavam a API **sem `try/catch`**: numa
   * falha (422/409/rede) a promise rejeitava, `load()` não rodava e a tela não mudava em NADA. O
   * usuário concluía que o clique não pegou — ou, pior, que pegou. "Ignorar" tira dinheiro do saldo
   * derivado, então achar que ignorou quando não ignorou é conferir depois um número que não bate,
   * sem ter como saber por quê. Achado do CodeRabbit, adotado pelo gate da Onda 0+1 (2026-07-30).
   *
   * Cada ação tem o par: a **falha** mostra a mensagem, e o **sucesso** recarrega a lista sem
   * deixar erro na tela — sem o segundo, um `catch` que engolisse tudo passaria no primeiro.
   */
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
    vi.mocked(api.delete).mockReset();
  });

  /**
   * Quantas vezes o **detalhe da conta** recarregou.
   *
   * ⚠️ Conta só `/bank/transactions`, e não `api.get` inteiro: `onChanged()` é o `load()` da PÁGINA
   * (contas + último saldo de cada uma) e sobe o contador geral sozinho. Um teste que olhasse o
   * total passaria mesmo com o `load()` do detalhe removido — foi o que um mutante mostrou aqui.
   */
  function recargasDoDetalhe() {
    return vi.mocked(api.get).mock.calls.filter(([url]) => url === "/bank/transactions").length;
  }

  /** Abre o detalhe da conta (é lá que vivem os três botões). */
  async function abrirMovimentos() {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByText("Ver movimentos"));
    await waitFor(() => expect(screen.getByText(/Movimentos — Itaú PJ/)).toBeInTheDocument());
    return user;
  }

  it("ignorar: a falha aparece na tela em vez de não acontecer nada", async () => {
    mockApi([conta()], [], [movimento()]);
    vi.mocked(api.post).mockRejectedValue(new Error("boom"));
    const user = await abrirMovimentos();

    await user.click(screen.getByRole("button", { name: "Ignorar" }));
    await user.click(screen.getByRole("button", { name: "Ignorar movimento" }));

    expect(await screen.findByText("Erro inesperado")).toBeInTheDocument();
    // O movimento continua listado como estava — a tela não finge que a ação aconteceu.
    expect(screen.getByText("Aluguel")).toBeInTheDocument();
  });

  it("ignorar: no sucesso recarrega a lista e não deixa erro na tela", async () => {
    mockApi([conta()], [], [movimento()]);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirMovimentos();
    const antes = recargasDoDetalhe();

    await user.click(screen.getByRole("button", { name: "Ignorar" }));
    await user.click(screen.getByRole("button", { name: "Ignorar movimento" }));

    await waitFor(() => expect(recargasDoDetalhe()).toBeGreaterThan(antes));
    expect(screen.queryByText("Erro inesperado")).toBeNull();
  });

  it("desfazer ignorar: a falha aparece na tela", async () => {
    mockApi([conta()], [], [movimento({ status: "ignored", ignored_reason: "duplicado" })]);
    vi.mocked(api.post).mockRejectedValue(new Error("boom"));
    const user = await abrirMovimentos();

    await user.click(screen.getByRole("button", { name: "Desfazer ignorar" }));

    expect(await screen.findByText("Erro inesperado")).toBeInTheDocument();
  });

  it("remover declaração: a falha aparece na tela", async () => {
    mockApi([conta()], [checkpoint], []);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api.delete).mockRejectedValue(new Error("boom"));
    const user = await abrirMovimentos();

    await user.click(screen.getByRole("button", { name: /Remover declaração/ }));

    expect(await screen.findByText("Erro inesperado")).toBeInTheDocument();
    // A linha do saldo declarado continua lá: nada foi removido, e a tela diz isso.
    expect(screen.getByRole("button", { name: /Remover declaração/ })).toBeInTheDocument();
  });

  it("remover declaração: no sucesso recarrega a lista e não deixa erro na tela", async () => {
    mockApi([conta()], [checkpoint], []);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(api.delete).mockResolvedValue({ data: {} } as never);
    const user = await abrirMovimentos();
    const antes = recargasDoDetalhe();

    await user.click(screen.getByRole("button", { name: /Remover declaração/ }));

    await waitFor(() => expect(recargasDoDetalhe()).toBeGreaterThan(antes));
    expect(screen.queryByText("Erro inesperado")).toBeNull();
  });
});

describe("AC8 — responsividade não é opcional neste repo (PR #56 / PR #58)", () => {
  it("a tabela de movimentos ROLA na horizontal; nada é cortado com overflow-hidden", async () => {
    mockApi([conta()]);
    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText("Ver movimentos")).toBeInTheDocument());
    screen.getByText("Ver movimentos").click();

    await waitFor(() => expect(screen.getByText(/Movimentos — Itaú PJ/)).toBeInTheDocument());
    // Sem movimentos no período o componente mostra o estado vazio; o que precisa ser garantido
    // em qualquer estado é que a tela não usa `overflow-hidden` (que CORTA) em lugar nenhum.
    expect(container.querySelectorAll(".overflow-hidden")).toHaveLength(0);
  });
});
