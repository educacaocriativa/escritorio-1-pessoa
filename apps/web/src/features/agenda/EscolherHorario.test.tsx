import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { localYmd } from "../../lib/datetime";
import EscolherHorario from "./EscolherHorario";
import { gradeDoMes } from "./grade";
import { agendaEvent } from "../../test/fixtures/agenda";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  getGoogleStatus: vi.fn(() => Promise.resolve({ connected: false })),
  apiErrorMessage: () => "Erro inesperado",
}));

vi.mock("../../store/auth", () => ({ useFuso: () => "America/Sao_Paulo" }));



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
          params: expect.objectContaining({ start: `${localYmd(novembro.start)}T00:00:00.000Z` }),
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
});
