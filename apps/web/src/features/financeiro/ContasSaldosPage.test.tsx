import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import ContasSaldosPage from "./ContasSaldosPage";
import type {
  BankAccount,
  BankBalanceCheckpoint,
  BankTransaction,
  PayablesPaidBefore,
} from "./contas";
import {
  AGENDADO_ENTRADA_LABEL,
  AGENDADO_SAIDA_LABEL,
  DISPONIVEL_CAIXA_LABEL,
  TOTAL_EM_CONTAS_LABEL,
  TRANSFERIR_LABEL,
} from "./contas";
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
    opening_balance_is_known: true,
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

/** Resposta default do agregado da Story 8.11 — silêncio (nenhuma conta paga antes). */
const SEM_PAGAS: PayablesPaidBefore = {
  count: 0,
  total_cents: 0,
  oldest_paid_on: null,
  newest_paid_on: null,
};

/** Mock de `api.get` que responde por URL (a página faz contas + checkpoints em paralelo). */
function mockApi(
  accounts: BankAccount[],
  checkpoints: BankBalanceCheckpoint[] = [],
  txs: BankTransaction[] = [],
  paidBefore: PayablesPaidBefore | Error = SEM_PAGAS,
) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/bank/accounts") return Promise.resolve({ data: accounts } as never);
    if (url.includes("/checkpoints")) return Promise.resolve({ data: checkpoints } as never);
    if (url === "/bank/transactions") return Promise.resolve({ data: txs } as never);
    if (url === "/payables/bills/paid-before") {
      return paidBefore instanceof Error
        ? Promise.reject(paidBefore)
        : Promise.resolve({ data: paidBefore } as never);
    }
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

  it("desfazer ignorar: no sucesso recarrega a lista e não deixa erro na tela", async () => {
    /**
     * ⚠️ **Par acrescentado no re-gate do Epic 8 (2026-07-30) por sobreviver a uma mutação.**
     * As outras duas ações ganharam o par de sucesso; esta ficou só com o de falha, e removendo o
     * `load()` do caminho feliz de `desfazerIgnorar` a suíte ficava **verde** (`16 passed`).
     *
     * O dano é menor que o das irmãs, mas é da mesma família: `unignore` **devolve** dinheiro ao
     * saldo derivado, e sem o `load()` do detalhe o movimento continua desenhado como ignorado
     * enquanto o saldo da página (recarregado por `onChanged()`) já mudou — dois números na mesma
     * tela contando histórias diferentes sobre a mesma ação.
     */
    mockApi([conta()], [], [movimento({ status: "ignored", ignored_reason: "duplicado" })]);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    const user = await abrirMovimentos();
    const antes = recargasDoDetalhe();

    await user.click(screen.getByRole("button", { name: "Desfazer ignorar" }));

    await waitFor(() => expect(recargasDoDetalhe()).toBeGreaterThan(antes));
    expect(screen.queryByText("Erro inesperado")).toBeNull();
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

describe("⚠️ Story 8.11 — a metade da guarda que vive no FORMULÁRIO (AC2b)", () => {
  /**
   * **Sem estes testes a Story 8.11 é decorativa, e isso não é figura de linguagem.**
   *
   * Até aqui, `AccountModal.save()` mandava `opening_balance_cents` SEMPRE, pré-preenchido com o
   * valor antigo, nos dois caminhos (POST e PATCH). O 422 que o backend passou a devolver quando o
   * recuo vem sem saldo — a guarda do design §4.3, o gêmeo do BANK-001 pela porta oposta — **nunca
   * dispararia pela UI real**: o usuário recuaria a data, o formulário mandaria o saldo velho por
   * conta própria, o backend responderia 200, e a divergência inventada aconteceria exatamente
   * como se a guarda não existisse.
   *
   * A guarda de API continua indispensável (Atalho do iOS, script, curl, cliente futuro) — mas é
   * daqui que vem a proteção do dono na semana do mutirão das 45 contas (epic §7.2).
   */
  const CONTA = conta({ id: "acc-1", opening_date: "2026-06-15", opening_balance_cents: 100_000 });

  beforeEach(() => {
    vi.mocked(api.patch).mockReset();
    vi.mocked(api.post).mockReset();
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
  });

  /** Abre o modal de EDIÇÃO da conta (é lá que o conceito de "recuo" existe). */
  async function abrirEdicao(accounts: BankAccount[] = [CONTA]) {
    const user = userEvent.setup();
    mockApi(accounts);
    renderPage();
    await user.click(await screen.findByText("Editar"));
    await waitFor(() => expect(screen.getByText("Editar conta")).toBeInTheDocument());
    return user;
  }

  function campoData() {
    return screen.getByLabelText("Data de abertura") as HTMLInputElement;
  }

  function campoSaldo() {
    // O rótulo MUDA ao recuar (passa a nomear o dia pedido) — por isso a busca é por prefixo.
    return screen.getByLabelText(/^Saldo/) as HTMLInputElement;
  }

  it("recuar a data LIMPA o saldo herdado e desabilita o salvar até haver valor", async () => {
    await abrirEdicao();
    expect(campoSaldo().value).toBe("1000,00");

    fireEvent.change(campoData(), { target: { value: "2026-06-01" } });

    await waitFor(() => expect(campoSaldo().value).toBe(""));
    // O saldo antigo era o saldo de OUTRO dia: reaproveitá-lo é a divergência inventada.
    expect(screen.getByRole("button", { name: "Salvar" })).toBeDisabled();
    // ...e a tela diz de QUAL dia é o saldo pedido — as duas datas, como no 422 do backend.
    expect(screen.getByText(/O saldo que você informou era o saldo de/)).toBeInTheDocument();
    expect(screen.getByText("15/06/2026")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Saldo em 01\/06\/2026 \(R\$\) — obrigatório$/)).toBeTruthy();
  });

  it("digitado o saldo novo, o salvar reabre e o PATCH leva o valor REDECLARADO", async () => {
    const user = await abrirEdicao();
    fireEvent.change(campoData(), { target: { value: "2026-06-01" } });
    await waitFor(() => expect(campoSaldo().value).toBe(""));

    await user.type(campoSaldo(), "3400,00");
    const salvar = screen.getByRole("button", { name: "Salvar" });
    await waitFor(() => expect(salvar).toBeEnabled());
    await user.click(salvar);

    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const [url, body] = vi.mocked(api.patch).mock.calls[0];
    expect(url).toBe("/bank/accounts/acc-1");
    expect(body).toMatchObject({ opening_date: "2026-06-01", opening_balance_cents: 340_000 });
  });

  it("avançar a data NÃO limpa nada (a guarda é sobre o recuo, não sobre mexer na data)", async () => {
    await abrirEdicao();

    fireEvent.change(campoData(), { target: { value: "2026-06-20" } });

    await waitFor(() => expect(campoData().value).toBe("2026-06-20"));
    expect(campoSaldo().value).toBe("1000,00");
    expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
    expect(screen.queryByText(/O saldo que você informou era o saldo de/)).toBeNull();
  });

  it("AC10 — em ~360px os campos EMPILHAM e nada é cortado dentro do modal", async () => {
    /**
     * O que dá para garantir em jsdom (que não tem layout) é a **regra estrutural**, e é ela que
     * regride numa mudança de estilo: os pares Agência/Conta e Saldo/Data ficam em UMA coluna
     * abaixo de `sm` (em 360px o modal tem ~280px úteis; duas colunas dariam ~134px e um
     * `input[type=date]` já não cabe), e o modal não usa `overflow-hidden` (que CORTA — a lição
     * dos PRs #56/#58, em que "Estornar" e o checkbox de baixa ficaram inalcançáveis).
     *
     * ✅ **A altura foi CORRIGIDA** (commit `bf32a10`): `components/Modal.tsx` ganhou
     * `max-h-[85vh]` + `overflow-y-auto`, então um modal mais alto que a viewport ROLA em vez de
     * transbordar escondendo o botão de salvar. Este comentário dizia "pré-existente, não corrigido
     * nesta story" e ficou desatualizado — a garantia da altura mora hoje em `Modal.test.tsx`.
     */
    await abrirEdicao();
    const container = document.body;

    const grades = Array.from(container.querySelectorAll("div.grid"));
    expect(grades.length).toBeGreaterThanOrEqual(2);
    for (const g of grades) {
      expect(g.className).toContain("grid-cols-1");
      expect(g.className).toContain("sm:grid-cols-2");
    }
    expect(container.querySelectorAll(".overflow-hidden")).toHaveLength(0);
  });

  it("durante o recuo, a dica genérica ('use o saldo de HOJE') sai de cena", async () => {
    // Duas instruções opostas na mesma tela é como se perde a confiança na que está certa.
    await abrirEdicao();
    expect(screen.getByText(/o saldo que o app do seu banco mostra hoje/)).toBeInTheDocument();

    fireEvent.change(campoData(), { target: { value: "2026-06-01" } });

    await waitFor(() =>
      expect(screen.queryByText(/o saldo que o app do seu banco mostra hoje/)).toBeNull(),
    );
  });

  it("voltar a data para o lugar RESTAURA o saldo — nunca manda um 0 fabricado", async () => {
    /**
     * ⚠️ O modo de falha que este teste fecha: limpar no recuo e **não** restaurar deixaria o campo
     * vazio depois de o usuário desistir, e `parseCentsBRL("")` é **0**. O PATCH zeraria o saldo de
     * abertura em silêncio — trocar um bug de saldo por outro, pior porque ninguém o pediu.
     */
    await abrirEdicao();
    fireEvent.change(campoData(), { target: { value: "2026-06-01" } });
    await waitFor(() => expect(campoSaldo().value).toBe(""));

    fireEvent.change(campoData(), { target: { value: "2026-06-15" } });

    await waitFor(() => expect(campoSaldo().value).toBe("1000,00"));
    expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
  });
});

describe("Story 8.11 — o aviso pró-ativo: o e1p diz QUAL número buscar, e não inventa nenhum (AC3/AC4)", () => {
  const PAGAS: PayablesPaidBefore = {
    count: 45,
    total_cents: 1_234_500,
    oldest_paid_on: "2026-03-10",
    newest_paid_on: "2026-07-28",
  };

  beforeEach(() => {
    vi.mocked(api.patch).mockReset();
    vi.mocked(api.post).mockReset();
  });

  async function abrirCadastro(paidBefore: PayablesPaidBefore | Error) {
    const user = userEvent.setup();
    mockApi([], [], [], paidBefore);
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Cadastrar primeira conta" }));
    await waitFor(() => expect(screen.getByText("Nova conta")).toBeInTheDocument());
    return user;
  }

  it("com contas pagas anteriores, diz quantas, o intervalo e o total PAGO", async () => {
    await abrirCadastro(PAGAS);

    const aviso = await screen.findByText(/45 contas pagas entre 10\/03\/2026 e 28\/07\/2026/);
    expect(aviso).toBeInTheDocument();
    // "pagos" e não "saldo": o total é o que saiu da conta, nunca um valor de partida (AC4).
    expect(aviso.textContent).toContain("pagos");
    expect(aviso.textContent).toMatch(/não vão entrar no extrato do e1p/);
  });

  it("o botão da sugestão preenche SÓ a data — o saldo continua sendo digitado pelo usuário", async () => {
    const user = await abrirCadastro(PAGAS);
    const saldoAntes = (screen.getByLabelText(/^Saldo/) as HTMLInputElement).value;

    // O dia ANTERIOR à mais antiga (09/03), nunca o mesmo dia: `posted_at > opening_date` é
    // estrito, então abrir em 10/03 deixaria justamente a conta mais antiga de fora.
    const botao = await screen.findByRole("button", { name: /Abrir em 09\/03\/2026/ });
    await user.click(botao);

    expect((screen.getByLabelText("Data de abertura") as HTMLInputElement).value).toBe(
      "2026-03-09",
    );
    expect((screen.getByLabelText(/^Saldo/) as HTMLInputElement).value).toBe(saldoAntes);
  });

  it("sem contas pagas anteriores, SILÊNCIO — nenhum aviso, nenhum botão", async () => {
    await abrirCadastro(SEM_PAGAS);

    await waitFor(() =>
      expect(vi.mocked(api.get).mock.calls.some(([u]) => u === "/payables/bills/paid-before")).toBe(
        true,
      ),
    );
    expect(screen.queryByText(/contas pagas/)).toBeNull();
    expect(screen.queryByRole("button", { name: /^Abrir em/ })).toBeNull();
  });

  it("falha do endpoint degrada em SILÊNCIO: o modal segue funcional e a conta é cadastrável", async () => {
    /**
     * O aviso é conveniência; cadastrar a conta é o produto. Mesmo padrão fail-safe de `PagarPage`
     * com `require_module`: uma falha de rede/401/módulo não permitido **nunca** pode bloquear o
     * cadastro — nem virar uma mensagem de erro que o usuário não sabe o que fazer com ela.
     */
    const user = await abrirCadastro(new Error("boom"));
    vi.mocked(api.post).mockResolvedValue({ data: conta() } as never);

    await waitFor(() =>
      expect(vi.mocked(api.get).mock.calls.some(([u]) => u === "/payables/bills/paid-before")).toBe(
        true,
      ),
    );
    expect(screen.queryByText("Erro inesperado")).toBeNull();
    expect(screen.queryByText(/contas pagas/)).toBeNull();

    await user.type(screen.getByLabelText("Nome da conta"), "Itaú PJ");
    // Story 8.21 — a escolha do saldo é OBRIGATÓRIA e trava o salvar até existir.
    await user.click(screen.getByLabelText("Não sei o saldo agora"));
    await user.click(screen.getByRole("button", { name: "Cadastrar conta" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/bank/accounts", expect.anything()));
  });

  it("a frase do aviso não reusa NENHUM rótulo de saldo do produto (UX-001 / D-6)", async () => {
    await abrirCadastro(PAGAS);
    const aviso = await screen.findByText(/45 contas pagas/);

    // "no banco" nomeia a PARCELA da Projeção; os outros dois são os totais desta tela. Texto de
    // formulário não é rótulo de saldo, e confundi-los é a colisão que o épico já pagou p/ separar.
    expect(aviso.textContent).not.toContain(ROTULO_BANCO);
    expect(aviso.textContent).not.toContain(TOTAL_EM_CONTAS_LABEL);
    expect(aviso.textContent).not.toContain(DISPONIVEL_CAIXA_LABEL);
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

describe("Story 8.10 — a data de apuração do saldo aparece na tela", () => {
  /**
   * **Por que congelar o relógio aqui.** A tela mostra a data de apuração do saldo *corrente*, que
   * é "hoje" — e um teste que recalculasse "hoje" com o mesmo código da tela seria tautológico:
   * passaria inclusive se a tela mostrasse a data errada, desde que errasse igual. Com o relógio
   * fixo, a string esperada é literal.
   *
   * `shouldAdvanceTime` mantém os timers correndo para o `waitFor` do testing-library não travar.
   */
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 6, 30, 12, 0, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("cada conta mostra 'Saldo em DD/MM' ao lado do número — nunca um saldo sem data", async () => {
    mockApi([conta({ id: "a", name: "Itaú PJ", saldo_derivado_cents: 4_000_000 })]);
    renderPage();

    await waitFor(() => expect(screen.getByText("Itaú PJ")).toBeInTheDocument());
    expect(screen.getByText("Saldo em 30/07")).toBeInTheDocument();
  });

  it("os totais também dizem em que data foram apurados", async () => {
    mockApi([
      conta({ id: "a", saldo_derivado_cents: 4_000_000 }),
      conta({ id: "c", kind: "investment", saldo_derivado_cents: 1_000_000 }),
    ]);
    renderPage();

    await waitFor(() => expect(screen.getByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument());
    expect(screen.getByText(/apuradas em 30\/07\/2026/)).toBeInTheDocument();
  });

  it("⚠️ a data do saldo CALCULADO não se confunde com a do saldo DECLARADO", async () => {
    // As duas testemunhas na mesma linha da tela, com datas diferentes: o e1p apurou hoje; o banco
    // atestou dia 28. Se as duas frases começassem igual, a tela diria a mesma coisa sobre coisas
    // opostas — a colisão que o UX-001 pagou para desfazer.
    mockApi([conta()], [checkpoint]);
    renderPage();

    await waitFor(() => expect(screen.getByText("Saldo em 30/07")).toBeInTheDocument());
    expect(screen.getByText(/Saldo declarado em 28\/07\/2026/)).toBeInTheDocument();
  });

  it("⚠️ [8.14] sem nada agendado, a tela continua com os DOIS totais — o terceiro é omitido", async () => {
    // **Mudança de expectativa parcial, e ela é a CORREÇÃO.** Este teste se chamava "AC9 — nenhum
    // rótulo NOVO de total" e dizia, em comentário, *"'Agendado para sair' é da Story 8.14. Esta
    // story não acrescenta terceiro número à tela"*. A 8.14 chegou — mas a asserção de ausência
    // **continua valendo neste cenário**, agora por outro motivo: o terceiro número existe e é
    // **omitido quando é zero**, pela mesma disciplina anti-ruído do "Disponível como caixa".
    //
    // Ou seja: o dono que nunca agendou nada vê exatamente a mesma tela de antes. Isso é o que
    // este teste passa a proteger, e é uma afirmação mais forte que a original.
    mockApi([
      conta({ id: "a", saldo_derivado_cents: 4_000_000 }),
      conta({ id: "c", kind: "investment", saldo_derivado_cents: 1_000_000 }),
    ]);
    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(TOTAL_EM_CONTAS_LABEL)).toBeInTheDocument());
    expect(screen.getByText(DISPONIVEL_CAIXA_LABEL)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/agendado/i);
    expect(container.textContent).not.toContain(ROTULO_BANCO);
  });

  it("⚠️ [8.14] havendo débito agendado, o TERCEIRO número aparece — e não contamina o saldo", async () => {
    // O cenário que a story existe para resolver: R$ 50.000 em contas, R$ 5.000 já com dia
    // marcado para sair. Os dois números convivem, com rótulos que não se confundem.
    mockApi([
      conta({ id: "a", saldo_derivado_cents: 5_000_000, agendado_saida_cents: 500_000 }),
    ]);
    renderPage();

    await waitFor(() => expect(screen.getByText(AGENDADO_SAIDA_LABEL)).toBeInTheDocument());
    // Escopado ao cartão dos totais: "R$ 50.000,00" também aparece no cartão da conta, e é o
    // TOPO da tela (onde os recortes convivem) que este teste está afirmando.
    const totais = screen.getByText(TOTAL_EM_CONTAS_LABEL).closest("div")
      ?.parentElement as HTMLElement;
    // O "Total em contas" NÃO foi reduzido pelo agendado: o dinheiro ainda está lá.
    expect(within(totais).getByText("R$ 50.000,00")).toBeInTheDocument();
    expect(within(totais).getByText("R$ 5.000,00")).toBeInTheDocument();
    // A explicação acompanha o número, como nos outros dois totais.
    expect(screen.getByText(/data futura/i)).toBeInTheDocument();
    // E o par simétrico continua omitido — ele só passa a ter valor na Story 8.15.
    expect(screen.queryByText(AGENDADO_ENTRADA_LABEL)).toBeNull();
  });
});

// ── Story 8.17 — o manual curado e o 409 acionável na tela (AC1 / AC8) ───────────────────────

describe("Story 8.17 — o formulário pergunta PARA QUE SERVE, e a guarda tem escolha", () => {
  const CONTA = conta({ id: "acc-1" });

  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  /** Abre o modal "Lançar movimento" com um valor de saída já digitado. */
  async function abrirLancamento() {
    const user = userEvent.setup();
    mockApi([CONTA]);
    renderPage();
    await user.click(await screen.findByText("Lançar movimento"));
    await waitFor(() =>
      expect(screen.getByText("Lançar movimento — Itaú PJ")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Valor (R$)"), { target: { value: "380,00" } });
    return user;
  }

  /**
   * O painel do modal, para escopar as buscas: **"Lançar movimento" é o rótulo do gatilho no
   * cartão da conta E do botão que efetiva dentro do modal** — `getByRole` global acharia os dois.
   * O painel é o avô do `<h2>` do título (`h2` → `div.mb-4` → painel, ver `components/Modal.tsx`).
   */
  function modal(): HTMLElement {
    const titulo = screen.getByText("Lançar movimento — Itaú PJ");
    return titulo.parentElement?.parentElement as HTMLElement;
  }

  function botaoLancar() {
    return within(modal()).getByRole("button", { name: "Lançar movimento" });
  }

  it("a finalidade é obrigatória na tela — o botão só abre depois de respondida", async () => {
    // A porta primária deixa de "parecer o jeito de registrar qualquer coisa". A obrigatoriedade é
    // de UI: a API continua aceitando `null` (movimento legado nasceu assim — AC7).
    await abrirLancamento();
    expect(botaoLancar()).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Para que serve este movimento"), {
      target: { value: "tarifa_bancaria" },
    });
    await waitFor(() => expect(botaoLancar()).toBeEnabled());
  });

  it("a lista é curta e SUGERIDA — 'Outro (descreva)' abre o texto livre e é ele que viaja", async () => {
    const user = await abrirLancamento();
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);

    fireEvent.change(screen.getByLabelText("Para que serve este movimento"), {
      target: { value: "_outro" },
    });
    fireEvent.change(await screen.findByLabelText("Descreva a finalidade"), {
      target: { value: "estorno de tarifa" },
    });
    await user.click(botaoLancar());

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({
      amount_cents: -38_000,
      operation_nature: "estorno de tarifa",
      confirmar_avulso: false,
    });
  });

  it("o 409 oferece DUAS ações, nenhuma pré-selecionada, e não apaga o formulário", async () => {
    // ⚠️ Um 409 que apaga o formulário treina o usuário a marcar "é outro pagamento" sem ler.
    const user = await abrirLancamento();
    const mensagem =
      "Existe uma conta a pagar de R$ 380,00 com vencimento em 12/07 (Enel). Quer dar baixa nela?";
    vi.mocked(api.post).mockRejectedValue({
      response: {
        status: 409,
        data: { detail: { acao: "baixar_payable", payable_id: "p-1", mensagem } },
      },
    });
    fireEvent.change(screen.getByLabelText("Para que serve este movimento"), {
      target: { value: "tarifa_bancaria" },
    });

    await user.click(botaoLancar());

    // A frase é a da API — uma redação, um lugar (mesma disciplina do `_NOTE_SEM_CHECKPOINT`).
    expect(await screen.findByText(mensagem)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dar baixa nessa conta" })).toHaveAttribute(
      "href",
      "/pagar",
    );
    expect(screen.getByRole("button", { name: "É outro pagamento" })).toBeInTheDocument();
    // O formulário CONTINUA lá, com tudo o que foi digitado.
    expect((screen.getByLabelText("Valor (R$)") as HTMLInputElement).value).toBe("380,00");
    expect(
      (screen.getByLabelText("Para que serve este movimento") as HTMLSelectElement).value,
    ).toBe("tarifa_bancaria");
  });

  it("'É outro pagamento' reenvia com `confirmar_avulso: true` e o movimento nasce", async () => {
    const user = await abrirLancamento();
    vi.mocked(api.post)
      .mockRejectedValueOnce({
        response: { status: 409, data: { detail: { acao: "baixar_payable", payable_id: "p-1", mensagem: "x" } } },
      })
      .mockResolvedValueOnce({ data: {} } as never);
    fireEvent.change(screen.getByLabelText("Para que serve este movimento"), {
      target: { value: "tarifa_bancaria" },
    });

    await user.click(botaoLancar());
    await user.click(await screen.findByRole("button", { name: "É outro pagamento" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.post).mock.calls[1][1]).toMatchObject({ confirmar_avulso: true });
  });

  it("erro comum (não acionável) continua aparecendo como erro, sem as duas ações", async () => {
    const user = await abrirLancamento();
    vi.mocked(api.post).mockRejectedValue({ response: { status: 422, data: { detail: "nope" } } });
    fireEvent.change(screen.getByLabelText("Para que serve este movimento"), {
      target: { value: "tributo" },
    });

    await user.click(botaoLancar());

    expect(await screen.findByText("Erro inesperado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "É outro pagamento" })).toBeNull();
  });
});

describe("Story 8.17 — movimento legado com finalidade NULA continua legítimo (AC7)", () => {
  it("a linha não pede preenchimento retroativo nem mostra 'não informado'", async () => {
    mockApi([conta()], [], [movimento({ operation_nature: null })]);
    renderPage();
    await screen.findByText("Itaú PJ");
    fireEvent.click(screen.getByText("Ver movimentos"));

    expect(await screen.findByText("Aluguel")).toBeInTheDocument();
    expect(screen.queryByText(/não informad/i)).toBeNull();
  });

  it("com finalidade, ela aparece traduzida ao lado da descrição", async () => {
    mockApi([conta()], [], [movimento({ operation_nature: "tarifa_bancaria" })]);
    renderPage();
    await screen.findByText("Itaú PJ");
    fireEvent.click(screen.getByText("Ver movimentos"));

    expect(await screen.findByText("Tarifa / juros")).toBeInTheDocument();
  });
});


// ── Story 8.18 — transferência entre contas próprias ─────────────────────────────────────────

describe("Story 8.18 — a ação de transferir mora em Contas & Saldos, sem tela nova (AC10)", () => {
  const duasContas = [
    conta({ id: "a", name: "Itaú PJ", kind: "checking", saldo_derivado_cents: 5_000_00 }),
    conta({ id: "b", name: "Nubank PJ", kind: "checking", saldo_derivado_cents: 200_00 }),
  ];

  it("com DUAS contas ativas a ação aparece; com UMA, não (não há para onde transferir)", async () => {
    mockApi(duasContas);
    const { unmount } = renderPage();
    await screen.findByText("Itaú PJ");
    expect(screen.getAllByRole("button", { name: TRANSFERIR_LABEL }).length).toBeGreaterThan(0);
    unmount();

    mockApi([duasContas[0]]);
    renderPage();
    await screen.findByText("Itaú PJ");
    expect(screen.queryByRole("button", { name: TRANSFERIR_LABEL })).toBeNull();
  });

  it("o destino NUNCA nasce igual à origem — seria 422 e não moveria dinheiro nenhum", async () => {
    mockApi(duasContas);
    renderPage();
    await screen.findByText("Itaú PJ");

    await userEvent.click(screen.getAllByRole("button", { name: TRANSFERIR_LABEL })[0]);
    const origem = (await screen.findByLabelText("Conta de origem")) as HTMLSelectElement;
    const destino = screen.getByLabelText("Conta de destino") as HTMLSelectElement;
    expect(origem.value).not.toBe(destino.value);
  });

  it("envia amount_cents POSITIVO e o `kind` DERIVADO das duas contas — nunca perguntado", async () => {
    // O sinal vive nas pernas (o backend o aplica). E não existe `<select>` de "tipo de
    // transferência": um terceiro campo dizendo o que os dois seletores já dizem poderia discordar
    // deles, e não haveria regra escrita sobre quem vence (o defeito D-3 na camada de formulário).
    mockApi(duasContas);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    renderPage();
    await screen.findByText("Itaú PJ");

    await userEvent.click(screen.getAllByRole("button", { name: TRANSFERIR_LABEL })[0]);
    const valor = await screen.findByLabelText("Valor (R$)");
    fireEvent.change(valor, { target: { value: "1.000,00" } });
    await userEvent.click(screen.getByRole("button", { name: "Registrar transferência" }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, body] = vi.mocked(api.post).mock.calls.at(-1) as [string, Record<string, unknown>];
    expect(url).toBe("/bank/transfers");
    expect(body.amount_cents).toBe(100_000);
    expect(body.from_account_id).toBe("a");
    expect(body.to_account_id).toBe("b");
    expect(body.kind).toBe("own_transfer");
    expect(screen.queryByLabelText(/tipo de transfer/i)).toBeNull();
  });

  it("destino APLICAÇÃO avisa, ANTES de confirmar, que o valor sai do disponível como caixa", async () => {
    // Obrigatório, não polimento (decisão do @po): é a primeira vez no produto que uma ação do dono
    // encurta o runway sem que nada tenha sido pago. Sem o aviso, ele veria o número cair e sairia
    // procurando um furo que não existe.
    mockApi([duasContas[0], conta({ id: "c", name: "CDB", kind: "investment", saldo_derivado_cents: 0 })]);
    renderPage();
    await screen.findByText("Itaú PJ");

    await userEvent.click(screen.getAllByRole("button", { name: TRANSFERIR_LABEL })[0]);
    const aviso = await screen.findByText(/é uma conta de aplicação/i);
    expect(aviso.textContent).toContain("CDB");
    // E ele diz o que NÃO muda — senão "aplicar" seria lido como "perder dinheiro".
    expect(aviso.textContent).toContain(TOTAL_EM_CONTAS_LABEL);
  });

  it("entre contas elegíveis NÃO há aviso — silêncio é o default (disciplina anti-ruído)", async () => {
    mockApi(duasContas);
    renderPage();
    await screen.findByText("Itaú PJ");

    await userEvent.click(screen.getAllByRole("button", { name: TRANSFERIR_LABEL })[0]);
    await screen.findByLabelText("Conta de origem");
    expect(screen.queryByText(/é uma conta de aplicação/i)).toBeNull();
  });

  it("o botão de confirmar fica DESABILITADO enquanto o valor é zero (mesmo bloco visível)", async () => {
    mockApi(duasContas);
    renderPage();
    await screen.findByText("Itaú PJ");

    await userEvent.click(screen.getAllByRole("button", { name: TRANSFERIR_LABEL })[0]);
    const confirmar = await screen.findByRole("button", { name: "Registrar transferência" });
    expect(confirmar).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Valor (R$)"), { target: { value: "10,00" } });
    await waitFor(() => expect(confirmar).toBeEnabled());
  });

  it("falha da API aparece na tela e o formulário NÃO é perdido", async () => {
    mockApi(duasContas);
    vi.mocked(api.post).mockRejectedValue(new Error("boom"));
    renderPage();
    await screen.findByText("Itaú PJ");

    await userEvent.click(screen.getAllByRole("button", { name: TRANSFERIR_LABEL })[0]);
    fireEvent.change(await screen.findByLabelText("Valor (R$)"), { target: { value: "10,00" } });
    await userEvent.click(screen.getByRole("button", { name: "Registrar transferência" }));

    expect(await screen.findByText("Erro inesperado")).toBeInTheDocument();
    expect((screen.getByLabelText("Valor (R$)") as HTMLInputElement).value).toBe("10,00");
  });
});

describe("Story 8.18 (AC9) — a perna não é editável nem ignorável PELA TELA", () => {
  const perna = movimento({
    id: "tx-perna",
    source: "transfer",
    transfer_id: "tr-1",
    amount_cents: -100_000,
    raw_description: "Transferência para Nubank PJ",
    description: "Transferência para Nubank PJ",
    operation_nature: "transferencia_propria",
    status: "matched",
  });

  it("some com Editar/Ignorar e diz POR QUÊ — linha sem botão e sem frase é lida como bug", async () => {
    mockApi([conta()], [], [perna]);
    renderPage();
    await screen.findByText("Itaú PJ");
    fireEvent.click(screen.getByText("Ver movimentos"));

    await screen.findByText("Transferência para Nubank PJ");
    const tabela = within(screen.getByRole("table"));
    expect(tabela.queryByRole("button", { name: "Editar" })).toBeNull();
    expect(tabela.queryByRole("button", { name: "Ignorar" })).toBeNull();
    expect(screen.getByText(/apague a transferência/i)).toBeInTheDocument();
    // O rótulo da transferência aparece na linha (AC10) — a tela lê `operation_nature`.
    expect(screen.getByText("Transferência entre minhas contas")).toBeInTheDocument();
  });

  it("oferece 'Desfazer transferência', e o DELETE é sobre o LANÇAMENTO (as duas pernas)", async () => {
    mockApi([conta()], [], [perna]);
    vi.mocked(api.delete).mockResolvedValue({ data: null } as never);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByText("Itaú PJ");
    fireEvent.click(screen.getByText("Ver movimentos"));

    await userEvent.click(await screen.findByRole("button", { name: "Desfazer transferência" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/bank/transfers/tr-1"));
  });

  it("o movimento MANUAL continua editável e ignorável — a guarda é sobre ORIGEM DE SISTEMA", async () => {
    // Sem este par ao lado, o teste acima estaria satisfeito pela forma mais fácil e mais errada:
    // esconder os botões de todo mundo.
    mockApi([conta()], [], [movimento()]);
    renderPage();
    await screen.findByText("Itaú PJ");
    fireEvent.click(screen.getByText("Ver movimentos"));

    const tabelaManual = within(await screen.findByRole("table"));
    expect(tabelaManual.getByRole("button", { name: "Editar" })).toBeInTheDocument();
    expect(tabelaManual.getByRole("button", { name: "Ignorar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Desfazer transferência" })).toBeNull();
  });
});
