import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider, usePageActions } from "../../store/pageActions";
import AgendaPage from "./AgendaPage";

// Story 7.15 — Task 2. Rede sempre mockada (IV2): nenhum teste bate em /agenda real.
// `getGoogleStatus` é export nomeado de lib/api (usado pelo NewEventModal) → mockado como
// "Google desconectado" para não disparar chamada de rede real.
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

// Estratégia (a) da Task 0: o botão "Novo evento" vive na topbar (AppShell). Topbar de teste local.
function Topbar() {
  const { action } = usePageActions();
  return action ? <button onClick={action.onClick}>{action.label}</button> : null;
}

function renderPage() {
  return render(
    <PageActionsProvider>
      <AgendaPage />
      <Topbar />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/agenda/events") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("AgendaPage — Novo evento (Story 7.15, Task 2)", () => {
  it("caminho feliz: cria evento com título + horários; POST /agenda/events e o modal fecha", async () => {
    const user = userEvent.setup();
    // CreateEventResult sem conflitos → o modal fecha (data.conflicts.length === 0 → onClose()).
    vi.mocked(api.post).mockResolvedValue({ data: { conflicts: [] } } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo evento" }));

    await user.type(screen.getByLabelText("Título"), "Atendimento cliente");
    // datetime-local: fireEvent.change (digitação em campos de data/hora no jsdom é frágil por locale).
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-08-01T09:00" } });
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-08-01T10:00" } });

    await user.click(screen.getByRole("button", { name: "Criar evento" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/agenda/events",
      expect.objectContaining({
        title: "Atendimento cliente",
        kind: "atendimento", // default
        starts_at: "2026-08-01T09:00",
        ends_at: "2026-08-01T10:00",
      }),
    );
    // Modal fecha: o título (heading) some (o botão "Novo evento" da topbar permanece).
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Novo evento" })).not.toBeInTheDocument(),
    );
  });

  it("caminho infeliz: erro do backend é exibido sem travar a tela (modal aberto, botão reabilitado)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao criar o evento." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Novo evento" }));
    await user.type(screen.getByLabelText("Título"), "Atendimento cliente");
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "2026-08-01T09:00" } });
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "2026-08-01T10:00" } });
    await user.click(screen.getByRole("button", { name: "Criar evento" }));

    expect(await screen.findByText("Falha ao criar o evento.")).toBeInTheDocument();
    // Modal permanece aberto e o botão volta a ficar habilitado (saving → false).
    expect(screen.getByRole("heading", { name: "Novo evento" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Criar evento" })).toBeEnabled();
  });
});
