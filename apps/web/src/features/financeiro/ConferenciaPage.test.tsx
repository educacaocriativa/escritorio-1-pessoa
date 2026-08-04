import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ConferenciaPage from "./ConferenciaPage";
import {
  type ConferenciaConta,
  type ConferenciaReport,
  LADO_BANCO_LABEL,
  LADO_E1P_LABEL,
  LADOS_GRUPO_LABEL,
} from "./conferencia";
import { ROTULO_BANCO } from "./projecao";

/**
 * Testes de componente da Conferência (Story 8.7).
 *
 * ⚠️ **Desvio declarado do texto da story:** o AC7/Testing afirma que *"o projeto não tem infra de
 * teste de componente React para estas telas"*. A premissa está **desatualizada** desde a Story 7.3
 * (jsdom + `@testing-library/react`, com `components/Modal.test.tsx` deixado como modelo) e a
 * Story 8.1 já a usou em `ProjecaoCaixaPage.test.tsx`. Dois ACs desta story vivem SÓ na tela — o
 * silêncio dentro da banda (AC5) e a ordem "frase antes da tabela" com o consolidado nunca sozinho
 * (AC4/AC6) — e aferi-los por inspeção visual seria deixar sem rede justamente a regressão mais
 * fácil de introduzir num ajuste de estilo.
 */
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

function conta(over: Partial<ConferenciaConta> = {}): ConferenciaConta {
  return {
    bank_account_id: "acc-1",
    bank_account_name: "Itaú PJ",
    bank_account_kind: "checking",
    saldo_banco_cents: 2_500_000,
    saldo_banco_origem: "banco",
    saldo_banco_fonte: "manual",
    saldo_banco_data: "2026-07-31",
    saldo_sistema_cents: 2_500_000,
    saldo_sistema_origem: "banco",
    divergencia_cents: 0,
    dentro_da_tolerancia: true,
    tolerancia_cents: 12_500,
    dias_desde_ultima_conferencia: 0,
    movimentos_ignorados: 0,
    notes: [],
    ...over,
  };
}

function report(contas: ConferenciaConta[], over: Partial<ConferenciaReport> = {}): ConferenciaReport {
  const avaliaveis = contas.filter((c) => c.divergencia_cents !== null);
  return {
    start: "2026-01-01",
    end: "2026-12-31",
    contas,
    total_divergencia_cents: avaliaveis.length
      ? avaliaveis.reduce((a, c) => a + (c.divergencia_cents ?? 0), 0)
      : null,
    contas_avaliadas: avaliaveis.length,
    contas_sem_checkpoint: contas.length - avaliaveis.length,
    contas_fora_da_banda: contas
      .filter((c) => c.dentro_da_tolerancia === false && c.divergencia_cents !== null)
      .map((c) => ({
        bank_account_id: c.bank_account_id,
        bank_account_name: c.bank_account_name,
        divergencia_cents: c.divergencia_cents ?? 0,
        tolerancia_cents: c.tolerancia_cents,
      })),
    notes: [],
    // Story 8.16 — os termos da pré-condição do gate. Zero no default: o cenário limpo é o
    // silêncio, e é dele que a tela não deve mudar por causa da anotação.
    lancamentos_sem_conta_informada: 0,
    valor_sem_conta_informada_cents: 0,
    rendimentos_sem_perna_bancaria: 0,
    valor_rendimentos_sem_perna_cents: 0,
    ...over,
  };
}

function renderPage(url = "/financeiro/conferencia") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ConferenciaPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("AC5 — dentro da banda: 🟢 e SILÊNCIO VISUAL (o teste obrigatório desta story)", () => {
  it("R$ 3,50 de divergência num saldo de R$ 25.000 não produz alerta NENHUM", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: report([
        conta({
          saldo_banco_cents: 2_500_350,
          divergencia_cents: 350,
          dentro_da_tolerancia: true,
          tolerancia_cents: 12_500,
        }),
      ]),
    } as never);

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(/Está tudo batendo/)).toBeInTheDocument());
    // O estado verde está lá...
    expect(screen.getByText("🟢")).toBeInTheDocument();
    // ...e NADA de alerta: nenhum ícone, nenhuma cor de erro, nenhum "atenção"/"!".
    expect(screen.queryByLabelText("Divergência fora da tolerância")).toBeNull();
    expect(container.querySelectorAll(".text-danger")).toHaveLength(0);
    expect(container.querySelectorAll("[class*='text-red']")).toHaveLength(0);
    expect(container.querySelectorAll("[class*='bg-red']")).toHaveLength(0);
    expect(container.querySelectorAll("[class*='amber']")).toHaveLength(0);
    expect(container.textContent).not.toMatch(/atenç|alerta|!/i);
    expect(screen.queryByText("🔴")).toBeNull();
    expect(screen.queryByText("🟡")).toBeNull();
  });

  it("fora da banda, aí sim o alerta aparece — a supressão é do CASO, não da tela", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: report([
        conta({
          saldo_banco_cents: 2_266_000,
          divergencia_cents: -234_000,
          dentro_da_tolerancia: false,
          tolerancia_cents: 12_500,
        }),
      ]),
    } as never);

    const { container } = renderPage();

    await waitFor(() =>
      expect(screen.getByLabelText("Divergência fora da tolerância")).toBeInTheDocument(),
    );
    expect(screen.getByText("🔴")).toBeInTheDocument();
    expect(container.querySelectorAll(".text-danger").length).toBeGreaterThan(0);
  });
});

describe("AC4 — a frase vem ANTES da tabela, e nomeia a conta", () => {
  it("a frase de divergência negativa aponta o valor, a conta e o que provavelmente falta", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: report([
        conta({
          saldo_banco_cents: 2_266_000,
          divergencia_cents: -234_000,
          dentro_da_tolerancia: false,
        }),
      ]),
    } as never);

    renderPage();

    // A garantia (inalterada): valor, direção e NOME DA CONTA amarrados num único nó de texto —
    // uma frase que dissesse "R$ 2.340,00 abaixo" sem dizer de qual conta não serve. O UX-001 só
    // mudou a ordem e o sujeito ("O banco diz…" em vez de "Seu saldo no banco…").
    await waitFor(() =>
      expect(
        screen.getByText(/O banco diz que a conta Itaú PJ está R\$ 2\.340,00 abaixo do que eu calculei/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/faltam lançamentos de saída/)).toBeInTheDocument();
  });

  it("a frase está no DOM antes da tabela — não é 'a tabela com um resumo em cima'", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: report([conta({ divergencia_cents: -234_000, dentro_da_tolerancia: false })]),
    } as never);

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(/2\.340,00 abaixo/)).toBeInTheDocument());
    const frase = screen.getByText(/2\.340,00 abaixo/);
    const tabela = container.querySelector("table");
    expect(tabela).not.toBeNull();
    // `DOCUMENT_POSITION_FOLLOWING` = a tabela vem DEPOIS da frase na ordem do documento.
    expect(frase.compareDocumentPosition(tabela as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("saldo indisponível: a frase não traz número nenhum e oferece declarar o saldo", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: report([
        conta({
          bank_account_name: "Nubank PJ",
          saldo_banco_cents: null,
          saldo_banco_origem: "indisponivel",
          saldo_banco_fonte: null,
          saldo_banco_data: null,
          saldo_sistema_cents: null,
          divergencia_cents: null,
          dentro_da_tolerancia: null,
          tolerancia_cents: 0,
          dias_desde_ultima_conferencia: null,
        }),
      ]),
    } as never);

    renderPage();

    const frase = await screen.findByText(/Não sei o saldo da conta Nubank PJ/);
    expect(frase.textContent).not.toMatch(/\d/);
    expect(screen.getByRole("link", { name: "Declarar o saldo desta conta" })).toHaveAttribute(
      "href",
      "/financeiro/contas",
    );
    // O consolidado também diz "não sei" em vez de inventar um zero tranquilizador (e a tabela
    // repete a mesma resposta nas células de saldo — em nenhum lugar aparece um R$ 0,00 falso).
    expect(screen.getAllByText("Não sei").length).toBeGreaterThan(0);
    expect(screen.queryByText(/R\$\s*0,00/)).toBeNull();
  });

  it("Story 8.20 — saldo informado na data de ABERTURA: a tela não manda declarar de novo", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: report([
        conta({
          bank_account_name: "C6 PJ",
          saldo_banco_cents: null,
          saldo_banco_origem: "indisponivel",
          saldo_banco_fonte: null,
          // O discriminador: houve DECLARAÇÃO; o que faltou foi a COMPARAÇÃO.
          saldo_banco_data: "2026-07-30",
          saldo_sistema_cents: null,
          divergencia_cents: null,
          dentro_da_tolerancia: null,
          tolerancia_cents: 0,
          dias_desde_ultima_conferencia: 0,
          notes: [
            "Você informou o saldo desta conta em 2026-07-30, o mesmo dia em que a conta foi " +
              "aberta no e1p.",
          ],
        }),
      ]),
    } as never);

    const { container } = renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Você informou o saldo da conta C6 PJ/)).toBeInTheDocument(),
    );
    // ⚠️ A asserção NEGATIVA é o ponto: mandar "declare o saldo para eu conferir" a quem acabou de
    // declarar fecha um laço — o dono declara, a tela pede de novo, e o produto perde a confiança.
    expect(screen.queryByText(/declare o saldo para eu conferir/)).toBeNull();
    expect(screen.queryByText(/Não sei o saldo da conta C6 PJ/)).toBeNull();
    // Nem o bloco 4 mente: `0` é "confirmado hoje", e não "nunca teve saldo informado".
    expect(screen.queryByText(/nunca teve saldo informado/)).toBeNull();
    // A data declarada continua visível na coluna do lado do banco (o campo segue preenchido).
    const corpo = container.querySelector("tbody") as HTMLElement;
    expect(within(corpo).getByText(/em 30\/07\/2026/)).toBeInTheDocument();
    // Nenhum ícone de alerta: é "não dá para conferir", não é erro.
    expect(screen.queryByLabelText("Divergência fora da tolerância")).toBeNull();
  });
});

describe("AC6 — o consolidado nunca aparece sozinho (epic §3.2, decisão do fundador F3)", () => {
  const tres = [
    conta({
      bank_account_id: "a",
      bank_account_name: "Itaú PJ",
      divergencia_cents: 120_000,
      dentro_da_tolerancia: false,
    }),
    conta({
      bank_account_id: "b",
      bank_account_name: "Nubank PJ",
      divergencia_cents: -90_000,
      dentro_da_tolerancia: false,
    }),
    conta({
      bank_account_id: "c",
      bank_account_name: "Caixa da loja",
      bank_account_kind: "cash",
      divergencia_cents: 4_000,
      dentro_da_tolerancia: true,
    }),
  ];

  it("+R$ 1.200 / −R$ 900 / +R$ 40: as TRÊS linhas aparecem, e os +R$ 340 não são veredito", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report(tres) } as never);

    renderPage();

    await waitFor(() => expect(screen.getByText(/1\.200,00 acima/)).toBeInTheDocument());
    // As três frases, cada uma nomeando a sua conta (mesma amarração de antes do UX-001: conta +
    // valor + direção num nó só; o que mudou foi a ordem das palavras).
    expect(
      screen.getByText(/O banco diz que a conta Itaú PJ está R\$ 1\.200,00 acima do que eu calculei/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/O banco diz que a conta Nubank PJ está R\$ 900,00 abaixo do que eu calculei/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Está tudo batendo na conta Caixa da loja/)).toBeInTheDocument();

    // O consolidado existe, mas explicitamente desqualificado como veredito...
    expect(screen.getByText(/Soma das divergências/)).toBeInTheDocument();
    expect(screen.getByText(/não é um veredito/)).toBeInTheDocument();
    // ...e a decomposição está na MESMA tela, visível, não atrás de "expandir".
    expect(screen.queryByText(/expandir/i)).toBeNull();
    const linhas = document.querySelectorAll("tbody tr");
    expect(linhas).toHaveLength(3);
  });

  it("quando o total não cobre todas as contas, a tela diz isso", async () => {
    const comLacuna = [
      ...tres,
      conta({
        bank_account_id: "d",
        bank_account_name: "Poupança",
        divergencia_cents: null,
        dentro_da_tolerancia: null,
        saldo_banco_cents: null,
        saldo_banco_origem: "indisponivel",
        saldo_banco_fonte: null,
        saldo_banco_data: null,
        saldo_sistema_cents: null,
        dias_desde_ultima_conferencia: null,
      }),
    ];
    vi.mocked(api.get).mockResolvedValue({ data: report(comLacuna) } as never);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/Esta soma não cobre todas as suas contas/)).toBeInTheDocument(),
    );
    // Story 8.20 — "não avaliada", e não "sem saldo informado": há dois motivos para a conta ficar
    // de fora, e o agregado não sabe qual é.
    expect(screen.getByText(/1 conta não foi avaliada/)).toBeInTheDocument();
    expect(screen.queryByText(/sem saldo informado no período/)).toBeNull();
  });

  it("a ordem de leitura é 'o que dói primeiro' — não avaliáveis por último", async () => {
    const comLacuna = [
      conta({ bank_account_id: "z", bank_account_name: "Sem saldo", divergencia_cents: null, dentro_da_tolerancia: null }),
      ...tres,
    ];
    vi.mocked(api.get).mockResolvedValue({ data: report(comLacuna) } as never);

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(/1\.200,00 acima/)).toBeInTheDocument());
    const frases = Array.from(container.querySelectorAll("ul > li")).map((li) => li.textContent);
    expect(frases[0]).toContain("Itaú PJ");
    expect(frases[1]).toContain("Nubank PJ");
    expect(frases[2]).toContain("Caixa da loja");
    expect(frases[3]).toContain("Sem saldo");
  });
});

describe("UX-001 — os dois lados da comparação: nomeados, distintos e visivelmente pareados", () => {
  /** Uma conta de cada tom, para a varredura de texto cobrir as quatro prosas possíveis. */
  const quatroTons = [
    conta({ bank_account_id: "a", bank_account_name: "Itaú PJ", divergencia_cents: 120_000, dentro_da_tolerancia: false }),
    conta({ bank_account_id: "b", bank_account_name: "Nubank PJ", divergencia_cents: -90_000, dentro_da_tolerancia: false }),
    conta({ bank_account_id: "c", bank_account_name: "Caixa da loja", divergencia_cents: 4_000, dentro_da_tolerancia: true }),
    conta({
      bank_account_id: "d",
      bank_account_name: "Poupança",
      divergencia_cents: null,
      dentro_da_tolerancia: null,
      saldo_banco_cents: null,
      saldo_banco_origem: "indisponivel",
      saldo_banco_fonte: null,
      saldo_banco_data: null,
      saldo_sistema_cents: null,
      dias_desde_ultima_conferencia: null,
    }),
  ];

  it("as duas colunas têm nomes próprios e não-confundíveis, um por lado", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);

    renderPage();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    const tabela = screen.getByRole("table");
    const banco = within(tabela).getByText(LADO_BANCO_LABEL);
    const e1p = within(tabela).getByText(LADO_E1P_LABEL);
    expect(banco.tagName).toBe("TH");
    expect(e1p.tagName).toBe("TH");
    // O cabeçalho antigo ("Saldo no banco" × "Saldo no e1p") não pode voltar por baixo.
    expect(within(tabela).queryByText("Saldo no banco")).toBeNull();
    expect(within(tabela).queryByText("Saldo no e1p")).toBeNull();
  });

  it("são apresentadas como UM PAR: vizinhas, sob uma legenda comum e na mesma faixa visual", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);

    renderPage();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    const tabela = screen.getByRole("table");
    const banco = within(tabela).getByText(LADO_BANCO_LABEL);
    const e1p = within(tabela).getByText(LADO_E1P_LABEL);

    // 1) Vizinhas e na mesma linha de cabeçalho — nunca separadas por outra coluna.
    expect(banco.parentElement).toBe(e1p.parentElement);
    expect(banco.nextElementSibling).toBe(e1p);

    // 2) Sob uma legenda que cobre EXATAMENTE as duas colunas.
    const grupo = within(tabela).getByText(LADOS_GRUPO_LABEL);
    expect((grupo as HTMLTableCellElement).colSpan).toBe(2);

    // 3) Na mesma faixa visual, no cabeçalho E no corpo — é o que faz a comparação se ler linha a
    //    linha. A asserção não fixa QUAL é a cor (estilo pode mudar), e sim que os quatro lugares
    //    do par compartilham a MESMA — separar visualmente um lado do outro é o que se proíbe.
    const faixa = grupo.className.split(" ").find((c) => c.startsWith("bg-"));
    expect(faixa).toBeDefined();
    expect(banco.className.split(" ")).toContain(faixa);
    expect(e1p.className.split(" ")).toContain(faixa);
    const celulas = Array.from(tabela.querySelectorAll("tbody tr")[0].children);
    expect(celulas[1].className.split(" ")).toContain(faixa); // o que o banco diz
    expect(celulas[2].className.split(" ")).toContain(faixa); // o que o e1p calculou
  });

  it("⚠️ a tela NUNCA usa 'no banco' — essa string nomeia o lado OPOSTO na Projeção", async () => {
    // Simétrico ao guarda que a `ContasSaldosPage` já tem. `ROTULO_BANCO` é o rótulo da parcela
    // DERIVADA da Projeção de Caixa; usá-lo aqui nomearia o checkpoint — a outra ponta da conta.
    vi.mocked(api.get).mockResolvedValue({ data: report(quatroTons) } as never);

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    expect(container.textContent).not.toContain(ROTULO_BANCO);
  });

  it("a abertura da tela ensina o par antes de a tabela usá-lo", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    const intro = screen.getByText(/Compara, conta por conta/);
    // Os dois lados nomeados na abertura, com a procedência de cada um.
    expect(intro.textContent).toContain("o que o banco diz");
    expect(intro.textContent).toContain("o que o e1p calculou");
    expect(intro.textContent).toMatch(/declarou/);
    expect(intro.textContent).toMatch(/lançamentos/);
    expect(container.textContent).not.toContain(ROTULO_BANCO);
  });
});

describe("Contrato consumido e estados de borda", () => {
  it("com ?account_id= confere só aquela conta e oferece a volta para todas", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);

    renderPage("/financeiro/conferencia?account_id=acc-42");

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(api.get).toHaveBeenCalledWith(
      "/bank/reconciliation-report",
      expect.objectContaining({
        params: expect.objectContaining({ bank_account_id: "acc-42" }),
      }),
    );
    expect(screen.getByRole("link", { name: "Ver todas as contas" })).toBeInTheDocument();
  });

  it("sem ?account_id= NÃO manda o filtro (string vazia viraria 'nenhuma conta')", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);

    renderPage();

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    const params = vi.mocked(api.get).mock.calls[0][1]?.params as Record<string, unknown>;
    expect(params).not.toHaveProperty("bank_account_id");
  });

  it("os dois eixos de procedência aparecem na tabela, lado a lado e sem se misturarem", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);

    renderPage();

    await waitFor(() => expect(screen.getByText(/Está tudo batendo/)).toBeInTheDocument());
    const tabela = screen.getByRole("table");
    // Eixo A (plano) e eixo B (porta de entrada) — vocabulários distintos, ambos exibidos.
    expect(within(tabela).getAllByText("saldo da sua conta bancária").length).toBeGreaterThan(0);
    expect(within(tabela).getByText("informado por você")).toBeInTheDocument();
  });

  it("sem conta cadastrada, convida a cadastrar em vez de mostrar uma tabela vazia", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([]) } as never);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/ainda não tem conta bancária cadastrada/)).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Cadastrar uma conta" })).toHaveAttribute(
      "href",
      "/financeiro/contas",
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("a tabela rola na horizontal (AC8) — nunca corta as colunas da direita", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    const wrapper = screen.getByRole("table").parentElement;
    expect(wrapper?.className).toContain("overflow-x-auto");
    expect(container.querySelectorAll(".overflow-hidden")).toHaveLength(0);
  });
});

describe("Story 8.16 — as notas do bloco 4 na tela: declaração de limite, não alerta", () => {
  const NOTA_P1P2 =
    "7 lançamentos deste período não informam de qual conta saiu ou entrou (R$ 3.120,00). " +
    "A divergência abaixo **inclui** esse valor. Este termo fecha na Onda 2: assim que todo " +
    "lançamento informar a conta, ele vai a zero sozinho.";
  const NOTA_P3 =
    "3 rendimentos de aplicação deste período (R$ 480,00) ainda não geram movimento bancário. " +
    "A divergência abaixo **inclui** esse valor. Este termo só fecha na Onda 2b — não há o que " +
    "corrigir à mão.";

  it("as notas aparecem JUNTO das que já existem, sem bloco novo e sem cor de alerta", async () => {
    // AC10: a nota é declaração de limite, não problema. Ela entra no mesmo `<ul>` de `notes` que a
    // 8.5 já renderiza — nenhum componente novo, nenhuma cor de erro.
    vi.mocked(api.get).mockResolvedValue({
      data: report(
        [conta({ divergencia_cents: 0, dentro_da_tolerancia: true })],
        {
          lancamentos_sem_conta_informada: 7,
          valor_sem_conta_informada_cents: 312_000,
          rendimentos_sem_perna_bancaria: 3,
          valor_rendimentos_sem_perna_cents: 48_000,
          notes: [NOTA_P1P2, NOTA_P3],
        },
      ),
    } as never);

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText(NOTA_P1P2)).toBeInTheDocument());
    expect(screen.getByText(NOTA_P3)).toBeInTheDocument();
    // As duas notas são irmãs no MESMO container — sem bloco novo.
    expect(screen.getByText(NOTA_P1P2).parentElement).toBe(
      screen.getByText(NOTA_P3).parentElement,
    );
    // Sem cor de alerta: a conta está dentro da banda e continua 🟢 e muda.
    expect(container.querySelectorAll("[class*='text-red']")).toHaveLength(0);
    expect(container.querySelectorAll("[class*='bg-red']")).toHaveLength(0);
    expect(container.querySelectorAll("[class*='amber']")).toHaveLength(0);
    expect(screen.getByText("🟢")).toBeInTheDocument();
  });

  it("a frase da conta é a MESMA com e sem as notas (ANOTA, NUNCA SUBTRAI)", async () => {
    // A divergência exibida não pode se mover por causa da anotação: descontar o termo conhecido
    // seria o checkpoint corrigindo o saldo derivado com outra roupa (Regra 5 do CLAUDE.md).
    const fora = conta({
      saldo_banco_cents: 2_570_000,
      divergencia_cents: 70_000,
      dentro_da_tolerancia: false,
      tolerancia_cents: 12_850,
    });

    vi.mocked(api.get).mockResolvedValue({ data: report([fora]) } as never);
    const limpo = renderPage();
    await waitFor(() => expect(screen.getByText(/O banco diz que a conta/)).toBeInTheDocument());
    const fraseSemNota = screen.getByText(/O banco diz que a conta/).textContent;
    limpo.unmount();

    vi.mocked(api.get).mockResolvedValue({
      data: report([fora], {
        lancamentos_sem_conta_informada: 7,
        valor_sem_conta_informada_cents: 312_000,
        notes: [NOTA_P1P2],
      }),
    } as never);
    renderPage();
    await waitFor(() => expect(screen.getByText(NOTA_P1P2)).toBeInTheDocument());
    expect(screen.getByText(/O banco diz que a conta/).textContent).toBe(fraseSemNota);
    // O número continua sendo o mesmo R$ 700,00 (`\\s` porque `formatBRL` usa espaço não-quebrável).
    expect(fraseSemNota).toMatch(/R\$\s700,00/);
  });

  it("zero termo não-zero ⇒ nenhuma nota na tela", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: report([conta()]) } as never);
    renderPage();
    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    expect(screen.queryByText(/não informam de qual conta/)).toBeNull();
    expect(screen.queryByText(/rendimentos de aplicação/)).toBeNull();
  });
});
