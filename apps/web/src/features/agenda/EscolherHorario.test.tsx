import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { localYmd } from "../../lib/datetime";
import EscolherHorario from "./EscolherHorario";
import { gradeDoMes, paramsDaGrade } from "./grade";
import { agendaEvent } from "../../test/fixtures/agenda";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  getGoogleStatus: vi.fn(() => Promise.resolve({ connected: false })),
  apiErrorMessage: () => "Erro inesperado",
}));

// O fuso do TENANT é trocável por teste (modelo de `NewEventModal.test.tsx`). O `vitest.config.ts`
// fixa o fuso da MÁQUINA em America/Sao_Paulo: enquanto o tenant mockado for esse mesmo valor,
// `eventosDoDia`/`faixasLivres`/`hojeDoTenant` lidos pelo fuso do tenant e lidos pelas partes
// locais do `Date` dão o MESMO resultado — e nenhuma asserção deste arquivo consegue distinguir
// os dois. É o defeito da issue #120, a família do `toContain("flex-wrap")` do CLAUDE.md §5.1.
let fusoDoTenant = "America/Sao_Paulo";
// Tóquio (UTC+9, sem horário de verão) está 12h à frente do runner: sob ele os dois caminhos
// discordam até sobre que DIA é. Mesmo valor que `grade.test.ts` usa no nível unitário — aqui
// ele prova que o COMPONENTE repassa o fuso do tenant àquela aritmética, e não outro qualquer.
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

// O dia base deste arquivo é quinta 15/10/2026 às 09:00 do tenant (12:00Z), não o 10/10 da
// fixture compartilhada.
const evento = (over: Record<string, unknown> = {}) =>
  agendaEvent({
    title: "Alinhamento do casamento",
    starts_at: "2026-10-15T12:00:00Z",
    ends_at: "2026-10-15T13:00:00Z",
    ...over,
  } as never);

function mockar(eventos: unknown[] = []) {
  vi.mocked(api.get).mockResolvedValue({ data: eventos } as never);
}

const abrir = (onEscolher = vi.fn()) => {
  render(<EscolherHorario open nome="Loana" onClose={() => {}} onEscolher={onEscolher} />);
  return onEscolher;
};

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  fusoDoTenant = "America/Sao_Paulo";
  // "Agora" fixo: 10/10/2026 09:00 no fuso do tenant. Sem isto, os testes de faixa livre
  // mudariam de resultado conforme o dia em que a suíte roda.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-10-10T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("EscolherHorario", () => {
  it("mostra a disponibilidade do dia escolhido antes de qualquer formulário", async () => {
    // ⚠️ Fuso do runner de propósito: este teste é sobre a ORDEM (a agenda antes do formulário) e
    // sobre a faixa tomada sumir da oferta — não sobre fuso. Ele não distingue tenant de
    // navegador, e não é para distinguir: quem faz essa prova é o `describe` "fuso do tenant,
    // não do navegador" no fim do arquivo. Não troque o fuso aqui.
    mockar([evento()]);
    abrir();

    await userEvent.click(await screen.findByRole("button", { name: /15 de outubro/ }));

    // O compromisso que já existe aparece — é a informação que o dono não tinha ao abrir o
    // formulário direto.
    expect(screen.getByText("Alinhamento do casamento")).toBeInTheDocument();
    // E a faixa que ele tomou some da oferta.
    expect(screen.queryByRole("button", { name: "09:00–10:00" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "10:00–11:00" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "08:00–09:00" })).toBeInTheDocument();
  });

  it("devolve o dia e a hora ao clicar numa faixa livre", async () => {
    mockar([evento()]);
    const onEscolher = abrir();

    await userEvent.click(await screen.findByRole("button", { name: /15 de outubro/ }));
    await userEvent.click(screen.getByRole("button", { name: "14:00–15:00" }));

    expect(onEscolher).toHaveBeenCalledTimes(1);
    const [dia, hora] = onEscolher.mock.calls[0];
    expect(localYmd(dia as Date)).toBe("2026-10-15");
    expect(hora).toBe(14);
  });

  it("devolve o dia sem hora quando o dono pede outro horário", async () => {
    mockar([]);
    const onEscolher = abrir();

    await userEvent.click(await screen.findByRole("button", { name: /15 de outubro/ }));
    await userEvent.click(screen.getByRole("button", { name: /outro horário/i }));

    const [dia, hora] = onEscolher.mock.calls[0];
    expect(localYmd(dia as Date)).toBe("2026-10-15");
    expect(hora).toBeNull();
  });

  it("no dia de hoje, não oferece horário que já passou", async () => {
    // ⚠️ Fuso do runner de propósito: o que se prova aqui é a REGRA DO CORTE (`<=`, a faixa das
    // 09h em ponto já não vale), não de que relógio ele sai. O teste irmão em "fuso do tenant,
    // não do navegador" faz a outra prova, com o corte lido em Tóquio.
    mockar([]);
    abrir();

    // Hoje (10/10) já vem selecionado; são 09:00 EM PONTO no fuso do tenant. A faixa das 09h
    // não tem mais nem um minuto de antecedência, então some junto com as que já correram.
    await waitFor(() => expect(vi.mocked(api.get)).toHaveBeenCalled());

    expect(screen.queryByRole("button", { name: "08:00–09:00" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "09:00–10:00" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "10:00–11:00" })).toBeInTheDocument();
  });

  it("avisa quando o dia não tem mais faixa livre, sem tirar a saída de escape", async () => {
    // 11:00Z–21:00Z = 08:00–18:00: a janela inteira tomada.
    mockar([evento({ starts_at: "2026-10-15T11:00:00Z", ends_at: "2026-10-15T21:00:00Z" })]);
    abrir();

    await userEvent.click(await screen.findByRole("button", { name: /15 de outubro/ }));

    expect(screen.getByText(/sem horário livre/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /outro horário/i })).toBeInTheDocument();
  });

  it("busca os eventos do mês novo ao navegar", async () => {
    mockar([]);
    abrir();
    await waitFor(() => expect(vi.mocked(api.get)).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: /mês seguinte/i }));

    const novembro = gradeDoMes(new Date(2026, 10, 1));
    await waitFor(() =>
      expect(vi.mocked(api.get)).toHaveBeenLastCalledWith(
        "/agenda/events",
        expect.objectContaining({
          params: expect.objectContaining({ start: paramsDaGrade(novembro.start, novembro.end).start }),
        }),
      ),
    );
  });

  it("ao trocar de mês, o painel do dia acompanha em vez de opinar sobre um dia fora da janela", async () => {
    // O defeito: `irPara` mexia só no mês da grade. O painel de baixo continuava escrito
    // "15 de outubro" enquanto `eventos` já era a lista de NOVEMBRO — então um dia lotado
    // aparecia com as dez faixas livres, e clicar numa delas marcava em cima de um compromisso.
    // Sem pista visual nenhuma: a célula selecionada nem existe na grade nova.
    mockar([evento({ starts_at: "2026-10-10T11:00:00Z", ends_at: "2026-10-10T21:00:00Z" })]);
    abrir();

    // Hoje (10/10) vem selecionado e está cheio de ponta a ponta.
    await waitFor(() => expect(screen.getByText(/sem horário livre/i)).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /mês seguinte/i }));

    expect(screen.getByRole("heading", { level: 4 })).toHaveTextContent(/novembro/i);
    expect(screen.getByRole("heading", { level: 4 })).not.toHaveTextContent(/outubro/i);
  });

  it("resposta atrasada de um mês antigo não sobrescreve a do mês visível", async () => {
    const deNovembro = evento({
      id: "ev-nov",
      title: "Compromisso de novembro",
      starts_at: "2026-11-16T12:00:00Z",
      ends_at: "2026-11-16T13:00:00Z",
    });
    let entregarOutubro = () => {};
    vi.mocked(api.get)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            entregarOutubro = () => resolve({ data: [evento()] } as never);
          }) as never,
      )
      .mockImplementationOnce(() => Promise.resolve({ data: [deNovembro] } as never));

    abrir();
    await userEvent.click(screen.getByRole("button", { name: /mês seguinte/i }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 4 })).toHaveTextContent(/novembro/i));

    // Só AGORA a requisição de outubro responde — fora de ordem, como uma rede lenta faria.
    entregarOutubro();

    await userEvent.click(screen.getByRole("button", { name: /16 de novembro/ }));
    expect(screen.getByText("Compromisso de novembro")).toBeInTheDocument();
    expect(screen.queryByText("Alinhamento do casamento")).not.toBeInTheDocument();
  });

  /**
   * `grade.test.ts` já prova, no nível unitário, que `eventosDoDia`/`faixasLivres`/`hojeDoTenant`
   * respeitam o fuso que RECEBEM. O que falta — e é o que estes dois testes fecham — é que o
   * COMPONENTE entregue a elas o fuso do TENANT (`useFuso()`), e não o relógio da máquina. Sem um
   * fuso distante do runner, essa passagem de parâmetro é invisível: os dois valores coincidem.
   */
  describe("fuso do tenant, não do navegador", () => {
    it("abre no dia de HOJE do tenant e corta o passado pelo relógio dele", async () => {
      // 10/10/2026 22:00Z é 11/10 07:00 em Tóquio e 10/10 19:00 em São Paulo (o fuso do runner).
      // Lendo pelo tenant: o seletor abre no dia 11 e, às 07h, a janela inteira de 08–18h ainda
      // está por vir. Lendo pelo navegador: abriria no dia 10 às 19h, com TUDO já no passado —
      // "Sem horário livre". Os dois desfechos são opostos, e é isso que a asserção mede.
      fusoDoTenant = FUSO_DISTANTE;
      vi.setSystemTime(new Date("2026-10-10T22:00:00Z"));
      mockar([]);
      abrir();

      await waitFor(() => expect(vi.mocked(api.get)).toHaveBeenCalled());

      expect(screen.getByRole("heading", { level: 4 })).toHaveTextContent(/11 de outubro/i);
      expect(screen.getByRole("button", { name: "08:00–09:00" })).toBeInTheDocument();
      expect(screen.queryByText(/sem horário livre/i)).not.toBeInTheDocument();
    });

    it("põe o compromisso no dia do tenant — e é lá que a faixa dele some da oferta", async () => {
      // 15/10 23:00Z–16/10 00:00Z é 16/10 08:00–09:00 em Tóquio e 15/10 20:00–21:00 em São Paulo.
      // O compromisso troca de DIA conforme o fuso, e a faixa que ele ocupa vai junto: só quem lê
      // pelo tenant o coloca no dia 16 tomando as 08h. Quem lê pelo navegador deixa o dia 16
      // inteiramente livre — e o seletor ofereceria 08:00 em cima de um compromisso existente,
      // que é o defeito exato que a feature existe para impedir.
      fusoDoTenant = FUSO_DISTANTE;
      mockar([evento({ starts_at: "2026-10-15T23:00:00Z", ends_at: "2026-10-16T00:00:00Z" })]);
      abrir();

      await userEvent.click(await screen.findByRole("button", { name: /16 de outubro/ }));

      expect(screen.getByText("Alinhamento do casamento")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "08:00–09:00" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "09:00–10:00" })).toBeInTheDocument();

      // E o espelho: no dia 15 — onde o relógio do NAVEGADOR o colocaria — ele não está, e as
      // 20h nem sequer são oferecidas (a janela para às 18h), então a prova é a ausência do
      // título e a oferta intacta das 08h.
      await userEvent.click(screen.getByRole("button", { name: /15 de outubro/ }));
      expect(screen.queryByText("Alinhamento do casamento")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "08:00–09:00" })).toBeInTheDocument();
    });
  });
});
