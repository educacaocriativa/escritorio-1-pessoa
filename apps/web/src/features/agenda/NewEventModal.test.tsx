import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import NewEventModal from "./NewEventModal";

// Onda 2, Task 5: extração do NewEventModal de AgendaPage.tsx para arquivo próprio, para que a
// ficha 360° do contato (Task 6) reuse o mesmo modal em vez de reimplementar o aviso de conflito.
// Rede sempre mockada (IV2): nenhum teste bate em /agenda real.
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
});
