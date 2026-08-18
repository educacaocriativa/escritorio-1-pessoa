import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import NewEventModal from "./NewEventModal";

// Onda 2, Task 5: extração do NewEventModal de AgendaPage.tsx para arquivo próprio, para que a
// ficha 360° do contato (Task 6) reuse o mesmo modal em vez de reimplementar o aviso de conflito.
// Rede sempre mockada (IV2): nenhum teste bate em /agenda real.
// O fuso do TENANT é trocável por teste: o `vitest.config.ts` fixa o fuso da MÁQUINA em
// America/Sao_Paulo, e é justamente a diferença entre os dois que este arquivo precisa exercitar.
let fusoDoTenant = "America/Sao_Paulo";
vi.mock("../../store/auth", () => ({ useFuso: () => fusoDoTenant }));

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  getGoogleStatus: vi.fn(() => Promise.resolve({ connected: false })),
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Título"), "Atendimento cliente");
  fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-08-01T09:00" } });
  fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-08-01T10:00" } });
  await user.click(screen.getByRole("button", { name: "Criar evento" }));
}

beforeEach(() => {
  vi.mocked(api.post).mockReset();
  fusoDoTenant = "America/Sao_Paulo";
});

describe("NewEventModal (Onda 2, Task 5)", () => {
  it("envia client_id quando recebe um", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: { conflicts: [] } } as never);

    render(
      <NewEventModal
        open
        initialDate={null}
        onClose={() => {}}
        onCreated={() => {}}
        clientId="contato-123"
      />,
    );

    await fillAndSubmit(user);

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/agenda/events",
      expect.objectContaining({ client_id: "contato-123" }),
    );
  });

  it("não envia client_id quando não recebe (evento solto, como na Agenda)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: { conflicts: [] } } as never);

    render(<NewEventModal open initialDate={null} onClose={() => {}} onCreated={() => {}} />);

    await fillAndSubmit(user);

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/agenda/events",
      expect.objectContaining({ client_id: null }),
    );
  });

  it("mostra o aviso de conflito sem fechar o modal", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({
      data: { conflicts: [{ id: "ev-outro", title: "Reunião existente" }] },
    } as never);
    const onClose = vi.fn();

    render(<NewEventModal open initialDate={null} onClose={onClose} onCreated={() => {}} />);

    await fillAndSubmit(user);

    expect(await screen.findByText(/Conflito de horário com: Reunião existente/)).toBeInTheDocument();
    // O modal continua aberto: onClose NÃO é chamado quando há conflito (o dono decide).
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Novo evento" })).toBeInTheDocument();
  });

  it("pré-preenche 09:00–10:00 ao abrir num dia, sem hora escolhida", () => {
    render(
      <NewEventModal
        open
        initialDate={new Date(2026, 9, 10)}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    );

    expect(screen.getByLabelText("Início")).toHaveValue("2026-10-10T09:00");
    expect(screen.getByLabelText("Fim")).toHaveValue("2026-10-10T10:00");
  });

  it("pré-preenche a hora escolhida no seletor, e a seguinte no fim", () => {
    render(
      <NewEventModal
        open
        initialDate={new Date(2026, 9, 10)}
        initialHour={14}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    );

    expect(screen.getByLabelText("Início")).toHaveValue("2026-10-10T14:00");
    expect(screen.getByLabelText("Fim")).toHaveValue("2026-10-10T15:00");
  });

  it("a hora escolhida é a hora do TENANT, mesmo com o navegador em outro fuso", () => {
    // O seletor decide as faixas no fuso do tenant; o `<input type="datetime-local">` fala no fuso
    // do NAVEGADOR. Entregar "14:00" como string ingênua fazia `new Date(...)` reinterpretá-la na
    // máquina de quem abriu a tela — o dono viajando marcava 15:00 achando que marcava 14:00.
    // Tenant em Tóquio (UTC+9), runner em São Paulo (UTC−3): 14:00 em Tóquio é 05:00Z, que o
    // navegador escreve como 02:00 do mesmo dia.
    fusoDoTenant = "Asia/Tokyo";

    render(
      <NewEventModal
        open
        initialDate={new Date(2026, 9, 10)}
        initialHour={14}
        onClose={() => {}}
        onCreated={() => {}}
      />,
    );

    const inicio = screen.getByLabelText("Início") as HTMLInputElement;
    expect(inicio).toHaveValue("2026-10-10T02:00");
    // O que importa não é a string e sim o INSTANTE que ela produz na hora de salvar.
    expect(new Date(inicio.value).toISOString()).toBe("2026-10-10T05:00:00.000Z");
  });
});
