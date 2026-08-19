import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ComprovantePage from "./ComprovantePage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

// ── A régua do fuso (CLAUDE.md §5.2, issues #120/#129) ────────────────────────────────────────
//
// O fuso do TENANT é trocável por teste (modelo de `EntradaDoDia.test.tsx`). O `vitest.config.ts`
// fixa o fuso da MÁQUINA em America/Sao_Paulo: enquanto o tenant for esse mesmo valor — e sem o
// mock abaixo ele É, porque `useFuso()` sem sessão cai no `FUSO_PADRAO` —, `today(fuso)` e o dia
// montado pelas partes locais do `Date` dão o MESMO resultado por construção. Era assim que "a
// data padrão é hoje" era afirmado aqui: com um `hoje()` montado a partir de
// `d.getFullYear()/getMonth()/getDate()`, o dia do NAVEGADOR. A asserção não conseguia falhar.
let fusoDoTenant = "America/Sao_Paulo";
/** Tóquio (UTC+9) está 12h à frente do runner — sob ele os dois caminhos discordam sobre o DIA. */
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({
  useFuso: () => fusoDoTenant,
}));

/**
 * O instante em que os três relógios discordam do jeito útil para esta tela.
 *
 * `2026-08-17T18:00:00Z` → **Tóquio 18/08 03:00** · **São Paulo 17/08 15:00** · **UTC 17/08**.
 *
 * Com Tóquio (+9) e São Paulo (−3) é impossível separar os três dias no mesmo instante (exigiria
 * UTC ≥ 15h *e* < 3h). O que importa é que o dia do TENANT difira dos DOIS candidatos errados —
 * e aqui difere: trocar a leitura para `localYmd(new Date())` (navegador) **ou** para
 * `toISOString().slice(0, 10)` (UTC) devolve 17/08 e mata o teste.
 */
const INSTANTE = "2026-08-17T18:00:00Z";
/** O dia do TENANT em `INSTANTE` — o único valor correto para um campo "hoje" desta tela. */
const DIA_DO_TENANT = "2026-08-18";

/** Congela o relógio em `INSTANTE`. `shouldAdvanceTime` mantém o `userEvent` respirando. */
function congelarRelogio() {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(INSTANTE));
}

const ABERTA = {
  id: "b-aberta", description: "Energia", supplier: "Copel", amount_cents: 30000,
  due_date: "2099-01-10", status: "open", is_overdue: false, paid_at: null,
};
const PAGA = {
  id: "b-paga", description: "Internet", supplier: "Vivo", amount_cents: 12000,
  due_date: "2099-01-05", status: "paid", is_overdue: false, paid_at: "2026-07-20T10:00:00Z",
};

/** Story 8.13 — a conta bancária de onde o dinheiro saiu (obrigatória na baixa desde a 8.12). */
const CONTA = {
  id: "acc-1", name: "Itaú PJ", kind: "checking", is_primary: true, archived_at: null,
  opening_balance_cents: 0, opening_date: "2026-01-01",
  saldo_derivado_cents: 0, saldo_derivado_origem: "banco",
};

function mockApi(candidates = [ABERTA, PAGA], contas: unknown[] = [CONTA]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url.startsWith("/payables/receipts/candidates")) {
      return Promise.resolve({ data: candidates });
    }
    if (url === "/payables/receipts") {
      return Promise.resolve({
        data: [{ id: "r-1", filename: "comp.pdf", content_type: "application/pdf",
                 size: 1024, created_at: "2026-07-28T10:00:00Z" }],
      });
    }
    if (url === "/bank/accounts") return Promise.resolve({ data: contas });
    return Promise.resolve({ data: [] });
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/comprovante/r-1"]}>
      <Routes>
        <Route path="/comprovante/:id" element={<ComprovantePage />} />
        <Route path="/pagar" element={<p>contas a pagar</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ComprovantePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fusoDoTenant = "America/Sao_Paulo";
  });
  afterEach(() => vi.useRealTimers());

  it("lista as contas candidatas com nome, valor e status", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));
    expect(screen.getByText("Internet")).toBeTruthy();
    expect(screen.getByText("Pago")).toBeTruthy();
  });

  // Achado da revisão final (item deferido, agora corrigido): o cabeçalho mostrava o texto
  // estático "Comprovante recebido" sem identificar QUAL arquivo — com a bandeja tendo vários,
  // o usuário não sabia o que estava prestes a anexar. `GET /payables/receipts` (já usado pela
  // bandeja/PagarPage) é filtrado pelo `id` da rota, sem endpoint novo.
  it("mostra o nome do arquivo do comprovante no cabeçalho, não um texto genérico", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("comp.pdf"));
    expect(screen.getByText(/1 KB/i)).toBeTruthy();
  });

  it("o botão Cancelar volta para Contas a Pagar sem descartar o comprovante", async () => {
    mockApi();
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await user.click(screen.getByRole("button", { name: /^cancelar$/i }));

    await waitFor(() => screen.getByText("contas a pagar"));
    expect(api.delete).not.toHaveBeenCalled();
  });

  it("mostra o checkbox de baixa apenas para conta em aberto", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    const check = screen.getByRole("checkbox", { name: /marcar como paga/i }) as HTMLInputElement;
    expect(check.checked).toBe(true); // marcado por padrão

    await userEvent.click(screen.getByText("Internet"));
    expect(screen.queryByRole("checkbox", { name: /marcar como paga/i })).toBeNull();
  });

  // Achado de campo (produção): o checkbox vivia num bloco separado, mais acima na página. Quem
  // selecionava uma conta e tocava direto em "Anexar" sem rolar NUNCA via o checkbox — a baixa
  // saía com o padrão (marcado) sem confirmação visível. Este teste prova a correção
  // estruturalmente: o checkbox e o botão "Anexar" precisam estar no MESMO contêiner (a barra
  // fixa do rodapé), não apenas ambos presentes em algum lugar da página — dois nós no mesmo pai
  // não podem ficar em posições de rolagem diferentes.
  it("o checkbox de baixa fica DENTRO da mesma barra fixa do botão Anexar, não numa seção à parte", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    const check = screen.getByRole("checkbox", { name: /marcar como paga/i });
    const anexar = screen.getByRole("button", { name: /^anexar/i });
    const footer = anexar.parentElement as HTMLElement;
    expect(check.closest("div")?.parentElement).toBe(footer);

    // O resumo, dentro da MESMA barra, também identifica QUAL conta será afetada — não só
    // que "alguma" será. O valor também aparece no cartão da lista (por isso a busca é
    // escopada ao rodapé, não à página inteira).
    expect(within(footer).getByText("R$ 300,00")).toBeTruthy();
  });

  it("vincula chamando link com o payload correto — e o `paid_on` é o dia do TENANT", async () => {
    // O `paid_on` que viaja é o default da bandeja, `localToday(fuso)`. Com o tenant em Tóquio e o
    // relógio congelado, ele é 18/08 — o navegador e o UTC diriam 17/08 (ver `INSTANTE`).
    fusoDoTenant = FUSO_DISTANTE;
    congelarRelogio();
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-aberta" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    await userEvent.click(screen.getByRole("button", { name: /^anexar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/payables/receipts/r-1/link");
    // Story 8.13: a conta bancária e o dia viajam junto — sem eles o backend responde 422.
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({
      bill_id: "b-aberta", mark_paid: true, bank_account_id: "acc-1", paid_on: DIA_DO_TENANT,
    });
  });

  it("envia mark_paid false quando o usuario desmarca — e SEM conta bancária", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-aberta" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    await userEvent.click(screen.getByRole("checkbox", { name: /marcar como paga/i }));
    await userEvent.click(screen.getByRole("button", { name: /^anexar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    // Anexar sem dar baixa não afirma que dinheiro saiu de lugar nenhum: mandar a conta aqui seria
    // gravar meia afirmação. O backend também não exige (`mark_paid=false` ignora o campo).
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({
      bill_id: "b-aberta", mark_paid: false,
    });
  });

  it("busca refaz a consulta com o termo digitado", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.type(screen.getByPlaceholderText(/buscar conta/i), "copel");
    await waitFor(() =>
      expect(
        vi.mocked(api.get).mock.calls.some(([url]) =>
          String(url).includes("candidates?q=copel"),
        ),
      ).toBe(true),
    );
  });

  it("cria conta nova a partir do formulario curto", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-novo" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    await userEvent.type(screen.getByPlaceholderText(/descrição/i), "Estacionamento");
    await userEvent.type(screen.getByPlaceholderText(/valor/i), "45,00");
    await userEvent.click(screen.getByRole("button", { name: /criar e anexar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, payload] = vi.mocked(api.post).mock.calls[0];
    expect(url).toBe("/payables/receipts/r-1/new-bill");
    expect((payload as { amount_cents: number }).amount_cents).toBe(4500);
  });

  it("descartar remove o comprovante e volta para contas a pagar", async () => {
    mockApi();
    vi.mocked(api.delete).mockResolvedValue({ data: null } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /descartar/i }));
    await waitFor(() => screen.getByText("contas a pagar"));
    expect(api.delete).toHaveBeenCalledWith("/payables/receipts/r-1");
  });

  // Achado (aplicando a lição da Task 9): a busca dispara uma nova requisição a cada tecla.
  // Se a resposta antiga (da query anterior) chegar DEPOIS da resposta nova (fora de ordem),
  // ela não pode sobrescrever a lista já atualizada — senão a tela "pisca" de volta para um
  // resultado que não corresponde mais ao que está no campo de busca.
  it("ignora resposta de busca antiga que chega fora de ordem", async () => {
    let resolveFirst!: (v: { data: (typeof ABERTA)[] }) => void;
    let resolveSecond!: (v: { data: (typeof PAGA)[] }) => void;
    let candidateCalls = 0;
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.startsWith("/payables/receipts/candidates")) {
        candidateCalls += 1;
        if (candidateCalls === 1) {
          return new Promise((resolve) => {
            resolveFirst = resolve;
          });
        }
        return new Promise((resolve) => {
          resolveSecond = resolve;
        });
      }
      return Promise.resolve({ data: [] });
    });

    renderPage();
    await waitFor(() => expect(candidateCalls).toBe(1));

    await userEvent.type(screen.getByPlaceholderText(/buscar conta/i), "x");
    await waitFor(() => expect(candidateCalls).toBe(2));

    // resolve a busca mais recente primeiro...
    resolveSecond({ data: [PAGA] });
    await waitFor(() => screen.getByText("Internet"));

    // ...e só depois a resposta antiga, que deve ser ignorada.
    resolveFirst({ data: [ABERTA] });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByText("Energia")).toBeNull();
    expect(screen.getByText("Internet")).toBeTruthy();
  });

  // Achado 1 da revisão: `toISOString()` formata o instante em UTC. À noite no Brasil (UTC−3), o
  // instante UTC já é o dia seguinte — a data de vencimento pré-preenchida do formulário de conta
  // nova virava "amanhã" silenciosamente.
  //
  // ⚠️ **Este teste já nasceu com relógio congelado e mesmo assim não conseguia falhar** (#129).
  // Ele congelava em `2026-03-10T23:30:00-03:00` e exigia o dia *local*: como o tenant também era
  // São Paulo, "dia local" e "dia do tenant" eram a mesma string, e trocar `today(fuso)` por
  // `localYmd(new Date())` na produção passava batido. Com o tenant em Tóquio, o campo tem de
  // mostrar o dia DO DONO — que não é o do navegador nem o de UTC.
  it("preenche a data de vencimento padrão com o dia do TENANT — não o do navegador, nem o de UTC", async () => {
    fusoDoTenant = FUSO_DISTANTE;
    congelarRelogio();

    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    const dateInput = screen.getByLabelText(/data de vencimento/i) as HTMLInputElement;
    expect(dateInput.value).toBe(DIA_DO_TENANT);
  });

  // Achado 2 da revisão: nada impedia selecionar uma conta candidata (habilitando o "Anexar"
  // fixo no rodapé) enquanto o formulário de conta nova também estava aberto e submissível —
  // dois caminhos de mutação alcançáveis ao mesmo tempo para o mesmo comprovante. Abrir o
  // formulário de conta nova precisa remover o "Anexar" do documento, não só desabilitá-lo.
  it("abrir o formulario de conta nova esconde o botao Anexar (fluxos mutuamente exclusivos)", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    expect(screen.getByRole("button", { name: /^anexar/i })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));

    expect(screen.queryByRole("button", { name: /^anexar/i })).toBeNull();
  });

  // Revisão final de branch (Finding 6): antes, uma vez escolhida uma candidata não havia como
  // desmarcá-la — "Criar conta nova" ficava travado atrás de `!chosen`, e a única saída era
  // filtrar a lista até a candidata sumir. Tocar de novo na mesma candidata precisa desmarcar
  // (toggle), devolvendo "Anexar" ao estado desabilitado e "Criar conta nova" ao alcance.
  it("tocar de novo na candidata ja selecionada desmarca (toggle-off), sem beco sem saida", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    // O resumo da conta escolhida (rodapé fixo) também mostra "Energia" depois da 1ª seleção —
    // por isso o cartão sempre é a PRIMEIRA ocorrência (ele vem antes no DOM).
    const card = () => screen.getAllByText("Energia")[0];

    await userEvent.click(card());
    expect(screen.getByRole("button", { name: /^anexar/i })).not.toBeDisabled();
    expect(screen.queryByRole("button", { name: /criar conta nova/i })).toBeNull();

    await userEvent.click(card());

    expect(screen.getByRole("button", { name: /^anexar/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /criar conta nova/i })).toBeTruthy();
  });

  // Achado 1 (rodada 2 de revisão): a correção anterior só fechava a exclusão mútua numa
  // direção. Nada resetava `showNew` ao selecionar uma candidata — abrir a conta nova e DEPOIS
  // selecionar uma candidata deixava os dois guards (`!chosen` e `!showNew`) falsos ao mesmo
  // tempo, escondendo tanto o formulário quanto o "Anexar". Usuário ficava sem nenhuma forma de
  // arquivar o comprovante (só Descartar). Selecionar uma candidata precisa fechar a conta nova.
  it("selecionar uma candidata com o formulario de conta nova aberto restaura o Anexar (sem beco sem saida)", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    expect(screen.queryByRole("button", { name: /^anexar/i })).toBeNull();

    await userEvent.click(screen.getByText("Energia"));

    expect(screen.getByRole("button", { name: /^anexar/i })).toBeTruthy();
    expect(screen.queryByPlaceholderText(/descrição/i)).toBeNull();
  });
});

/**
 * **Story 8.13 — o seletor de conta dentro da barra fixa.**
 *
 * O AC4 é a linha que reprova a story: *"é proibido pôr o seletor em qualquer bloco que exija
 * rolagem para ser visto"*. Dois PRs de fix de campo (#56, #58) já foram pagos exatamente por isso,
 * um deles com uma conta real marcada paga sem o usuário conseguir ver o que confirmava.
 */
describe("ComprovantePage — a escolha da baixa (Story 8.13)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fusoDoTenant = "America/Sao_Paulo";
  });
  afterEach(() => vi.useRealTimers());

  const seletor = () => screen.getByLabelText(/conta bancária de onde o dinheiro saiu/i);
  const campoDia = () => screen.getByLabelText(/dia em que o dinheiro saiu/i) as HTMLInputElement;

  async function escolherCandidata() {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));
    await userEvent.click(screen.getByText("Energia"));
  }

  it("⚠️ AC4 — o seletor de conta e o dia ficam na MESMA barra fixa do botão", async () => {
    await escolherCandidata();

    const anexar = screen.getByRole("button", { name: /^anexar/i });
    const barra = anexar.closest(".fixed");
    expect(barra).not.toBeNull();
    // A propriedade que importa não é "os dois existem na página": é que estão no MESMO bloco
    // fixo, então NÃO PODE haver rolagem entre um e outro. Mover o seletor para fora da barra
    // (um modal, um "expandir", uma seção acima) faz este teste cair — é essa a intenção.
    expect(seletor().closest(".fixed")).toBe(barra);
    expect(campoDia().closest(".fixed")).toBe(barra);
    // ...e o checkbox de baixa continua lá também (a garantia do PR #58 não regrediu).
    expect(screen.getByRole("checkbox", { name: /marcar como paga/i }).closest(".fixed")).toBe(barra);
  });

  it("a conta primária vem pré-selecionada e o nome dela aparece NO BOTÃO", async () => {
    await escolherCandidata();

    expect((seletor() as HTMLSelectElement).value).toBe("acc-1");
    expect(screen.getByRole("button", { name: /anexar e dar baixa · sai do Itaú PJ/i })).toBeTruthy();
  });

  it("a data padrão da BANDEJA é hoje NO FUSO DO TENANT (não o vencimento) — e [8.14] sem teto", async () => {
    fusoDoTenant = FUSO_DISTANTE;
    congelarRelogio();
    await escolherCandidata();

    // Aqui, diferente de PagarPage/Fila, o default é HOJE: o comprovante chega pelo share sheet no
    // instante do pagamento. **O default não mudou** — o que mudou foi o teto.
    //
    // ⚠️ E "hoje" é o dia do DONO, não o de quem abriu o navegador (#129). Este `expect` afirmava
    // `hoje()` — o dia montado com `d.getFullYear()/getMonth()/getDate()` — e com tenant e runner
    // no mesmo fuso os dois lados eram iguais por construção. Agora o tenant está em Tóquio e o
    // relógio congelado: 18/08 para o dono, 17/08 para o navegador e para o UTC.
    expect(campoDia().value).toBe(DIA_DO_TENANT);
    // ⚠️ **[Story 8.14] mudança de expectativa, e ela é a CORREÇÃO.** Este teste afirmava
    // `max === hoje()`. O teto era faseamento (garantir que não existisse `paid` com data futura
    // enquanto `scheduled` não existisse) e saiu no commit em que `scheduled` nasceu. A bandeja
    // herdou a mudança **sem ser editada**: as três telas de baixa compartilham `baixa.ts`, e é
    // esse o retorno de ter uma implementação só.
    expect(campoDia().getAttribute("max")).toBeNull();
  });

  it("⚠️ a bandeja NÃO abre acusando de futuro o dia que ela mesma preencheu (#136)", async () => {
    // ── O defeito 2 da #136, agora fixado num `expect` ────────────────────────────────────────
    //
    // O PR #133 ACHOU isto e deliberadamente não afirmou nada: com o tenant em Tóquio, a bandeja
    // abria com "Esta data é no futuro… será registrada como AGENDADA" **já visível, sem o dono
    // tocar em nada**. Um componente, dois relógios: o default vinha de `localToday(fuso)` (o
    // tenant, 18/08) e o `avisoDeDataFutura` comparava com `hojeISO()` (o navegador, 17/08) — a
    // tela acusava de errado o valor que ela mesma acabara de escrever. Travar o aviso num
    // `expect` naquele momento pregaria o defeito na parede; agora que a dívida foi paga, o que
    // se prega é a AUSÊNCIA dele.
    //
    // Este teste é o guardião do invariante: **default e validação bebem do mesmo relógio.** Ele
    // morre se alguém devolver um segundo "hoje" ao fluxo da baixa — e morre com o defeito exato
    // que existia em produção, não com um proxy dele.
    fusoDoTenant = FUSO_DISTANTE;
    congelarRelogio();
    await escolherCandidata();

    // Ponto de partida: o campo está no dia do tenant, intocado.
    expect(campoDia().value).toBe(DIA_DO_TENANT);
    expect(screen.queryByText(/esta data é no futuro/i)).toBeNull();

    // E o aviso continua FUNCIONANDO — ele não sumiu, só parou de mentir. Um dia realmente à
    // frente do hoje DO TENANT ainda avisa. Sem esta metade, apagar `avisoDeDataFutura` inteiro
    // deixaria a primeira metade verde.
    fireEvent.change(campoDia(), { target: { value: "2026-08-19" } });
    expect(screen.getByText(/esta data é no futuro/i)).toBeTruthy();

    // E o dia que é futuro só para o NAVEGADOR (18/08 é amanhã em São Paulo, hoje em Tóquio) NÃO
    // avisa: é aqui que se lê de qual relógio a validação bebe.
    fireEvent.change(campoDia(), { target: { value: DIA_DO_TENANT } });
    expect(screen.queryByText(/esta data é no futuro/i)).toBeNull();
  });

  it("o dia é EDITÁVEL e é o valor editado que viaja", async () => {
    await escolherCandidata();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-aberta" } } as never);

    fireEvent.change(campoDia(), { target: { value: "2026-07-01" } });
    await userEvent.click(screen.getByRole("button", { name: /^anexar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({ paid_on: "2026-07-01" });
  });

  it("SEM conta primária nada é pré-selecionado e o Anexar fica DESABILITADO", async () => {
    mockApi([ABERTA, PAGA], [
      { ...CONTA, id: "a", name: "Conta A", is_primary: false },
      { ...CONTA, id: "b", name: "Conta B", is_primary: false },
    ]);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));
    await userEvent.click(screen.getByText("Energia"));

    expect((seletor() as HTMLSelectElement).value).toBe("");
    expect(screen.getByRole("button", { name: /^anexar/i })).toBeDisabled();
  });

  it("conta JÁ PAGA não pede conta bancária (não há baixa a dar)", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Internet"));

    await userEvent.click(screen.getByText("Internet"));

    expect(screen.queryByLabelText(/conta bancária de onde o dinheiro saiu/i)).toBeNull();
    expect(screen.getByRole("button", { name: /^anexar$/i })).not.toBeDisabled();
  });

  it("desmarcar 'marcar como paga' esconde o seletor — o campo deixa de ser exigido", async () => {
    await escolherCandidata();
    expect(seletor()).toBeTruthy();

    await userEvent.click(screen.getByRole("checkbox", { name: /marcar como paga/i }));

    expect(screen.queryByLabelText(/conta bancária de onde o dinheiro saiu/i)).toBeNull();
    expect(screen.getByRole("button", { name: /^anexar$/i })).not.toBeDisabled();
  });

  it("409 acionável → cadastro embutido → retoma, SEM perder a candidata escolhida", async () => {
    mockApi();
    const mensagem409 = "Cadastre a sua conta bancária uma vez e o pagamento segue normalmente.";
    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url === "/bank/accounts") {
        return Promise.resolve({ data: { ...CONTA, id: "acc-nova", name: "Nubank PJ" } } as never);
      }
      const jaCadastrou = vi
        .mocked(api.post)
        .mock.calls.some(([u]) => String(u) === "/bank/accounts");
      if (jaCadastrou) return Promise.resolve({ data: { id: "b-aberta" } } as never);
      return Promise.reject({
        response: { data: { detail: { acao: "cadastrar_conta", mensagem: mensagem409 } } },
      });
    });

    renderPage();
    await waitFor(() => screen.getByText("Energia"));
    await userEvent.click(screen.getByText("Energia"));
    await userEvent.click(screen.getByRole("button", { name: /^anexar/i }));

    expect(await screen.findByText(mensagem409)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Nova conta" })).toBeTruthy();

    await userEvent.type(screen.getByLabelText("Nome da conta"), "Nubank PJ");
    // Story 8.21 — a escolha do saldo é OBRIGATÓRIA e trava o salvar.
    await userEvent.click(screen.getByLabelText("Não sei o saldo agora"));
    await userEvent.click(screen.getByRole("button", { name: "Cadastrar conta" }));

    // A candidata continua escolhida (a tela nunca foi desmontada) e a conta nova está selecionada.
    const retomar = await screen.findByRole("button", { name: /sai do Nubank PJ/i });
    await userEvent.click(retomar);

    await waitFor(() =>
      expect(
        vi.mocked(api.post).mock.calls.filter(([u]) => String(u) === "/payables/receipts/r-1/link"),
      ).toHaveLength(2),
    );
    const ultima = vi
      .mocked(api.post)
      .mock.calls.filter(([u]) => String(u) === "/payables/receipts/r-1/link")
      .at(-1);
    expect(ultima?.[1]).toMatchObject({ bill_id: "b-aberta", bank_account_id: "acc-nova" });
  });

  it("o formulário de conta nova também pede a conta — ele TAMBÉM dá baixa", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-novo" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    await userEvent.type(screen.getByPlaceholderText(/descrição/i), "Estacionamento");
    await userEvent.type(screen.getByPlaceholderText(/valor/i), "45,00");
    await userEvent.click(screen.getByRole("button", { name: /criar e anexar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][1]).toMatchObject({
      mark_paid: true, bank_account_id: "acc-1",
    });
  });

  /**
   * **Auditoria estrutural de ~360px (AC9).** Amarra a aritmética de `baixa.ts` ao DOM real: as
   * constantes só valem enquanto a barra usar estas classes. Se alguém trocar `p-4` por `p-6` ou
   * `grid-cols-2` por `grid-cols-3`, este teste cai antes do aparelho.
   */
  it("a barra fixa usa as classes que alimentam a aritmética de 360px", async () => {
    await escolherCandidata();

    const barra = screen.getByRole("button", { name: /^anexar/i }).closest(".fixed") as HTMLElement;
    expect(barra.className).toContain("p-4"); // PADDING_DA_BARRA = 16
    expect(barra.className).toContain("space-y-3"); // 12px entre resumo, campos e botão
    expect(barra.className).toContain("inset-x-0"); // largura da viewport, sem overflow lateral

    const grade = seletor().closest("div.grid") as HTMLElement;
    expect(grade.className).toContain("grid-cols-2"); // 2 colunas → 160px por campo em 360px
    expect(grade.className).toContain("gap-2"); // GAP_ENTRE_CAMPOS = 8

    // E a página reserva espaço embaixo para a barra (que cresceu): o último cartão da lista não
    // fica escondido atrás dela. `pb-52` = 208px ≥ ALTURA_DA_BARRA.
    const pagina = barra.parentElement as HTMLElement;
    expect(pagina.className).toContain("pb-52");
  });
});
