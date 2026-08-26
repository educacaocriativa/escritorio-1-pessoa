import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
import CelularSection from "./CelularSection";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

describe("CelularSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lista os dispositivos com o ultimo uso", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "t-1", name: "iPhone do Flavio", created_at: "2026-07-01T10:00:00Z",
               last_used_at: "2026-07-27T09:00:00Z" }],
    } as never);
    render(<CelularSection />);
    await waitFor(() => screen.getByText("iPhone do Flavio"));
  });

  it("mostra o token cru UMA vez ao criar", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.post).mockResolvedValue({
      data: { id: "t-2", name: "iPhone", token: "segredo-cru-do-token" },
    } as never);

    render(<CelularSection />);
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    await userEvent.type(screen.getByPlaceholderText(/nome do aparelho/i), "iPhone");
    await userEvent.click(screen.getByRole("button", { name: /gerar token/i }));

    await waitFor(() => screen.getByText("segredo-cru-do-token"));
    expect(screen.getByText(/só aparece uma vez/i)).toBeTruthy();
  });

  it("revoga o dispositivo", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "t-1", name: "iPhone", created_at: "2026-07-01T10:00:00Z", last_used_at: null }],
    } as never);
    vi.mocked(api.delete).mockResolvedValue({ data: null } as never);

    render(<CelularSection />);
    await waitFor(() => screen.getByText("iPhone"));
    await userEvent.click(screen.getByRole("button", { name: /revogar/i }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/settings/device-tokens/t-1"));
  });

  it("mostra erro quando a revogacao falha, sem travar a tela", async () => {
    // Nome de aparelho deliberadamente distinto de "iPhone" (o texto fixo do bloco de
    // instrucoes) para nao colidir na busca por texto.
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "t-1", name: "iPhone da Revogacao", created_at: "2026-07-01T10:00:00Z", last_used_at: null }],
    } as never);
    vi.mocked(api.delete).mockRejectedValue(new Error("Falha ao revogar"));

    render(<CelularSection />);
    await waitFor(() => screen.getByText("iPhone da Revogacao"));
    await userEvent.click(screen.getByRole("button", { name: /revogar/i }));

    await waitFor(() => screen.getByText(/falha ao revogar/i));
    // A lista continua visível — a tela não trava/some após a falha.
    expect(screen.getByText("iPhone da Revogacao")).toBeTruthy();
  });
});

// ── `GET /settings/device-tokens` fora de forma (issue #225) ─────────────────
//
// `setTokens(data)` recebia o payload CRU. `tokens.map` está atrás de `tokens.length > 0`, mas
// `.length` de um objeto/string/número não é 0 de forma confiável (string tem `.length`, objeto
// devolve `undefined` — `undefined > 0` é falso, MAS `.map` de string funciona diferente e
// qualquer mudança de forma no envelope de erro reabre o buraco). Sem ErrorBoundary, o estouro
// no render desmontaria a seção inteira do celular, não só a lista de tokens.
describe("CelularSection — lista de tokens fora de forma não derruba a seção (#225)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a seção continua montada, sem lista de tokens", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    render(<CelularSection />);
    await assentar();

    expect(screen.getByText("Celular — anexar comprovante")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /revogar/i })).not.toBeInTheDocument();
  });
});
