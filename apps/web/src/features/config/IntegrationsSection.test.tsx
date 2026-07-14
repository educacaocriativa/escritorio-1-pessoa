import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import IntegrationsSection from "./IntegrationsSection";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

beforeEach(() => {
  vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
  vi.mocked(api.post).mockReset();
});

describe("IntegrationsSection", () => {
  it("cria uma chave, mostra a chave crua uma vez e some após recarregar a lista", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockImplementation((url: string) => {
      if (url === "/integrations/leads/keys") {
        return Promise.resolve({
          data: {
            id: "k-1", label: "Site Dóro", key_prefix: "abcd1234",
            revoked_at: null, created_at: "", raw_key: "abcd1234-segredo-completo",
          },
        } as never);
      }
      return Promise.resolve({ data: {} } as never);
    });
    render(<IntegrationsSection />);

    await user.type(
      screen.getByPlaceholderText(/Nome da chave/), "Site Dóro",
    );
    await user.click(screen.getByRole("button", { name: /Nova chave/ }));

    expect(await screen.findByText("abcd1234-segredo-completo")).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("/integrations/leads/keys", { label: "Site Dóro" });
  });

  it("lista chaves existentes e permite revogar", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue({
      data: [{ id: "k-1", label: "Site X", key_prefix: "aaaaaaaa", revoked_at: null, created_at: "" }],
    } as never);
    vi.mocked(api.post).mockResolvedValue({ data: {} } as never);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<IntegrationsSection />);

    expect(await screen.findByText("Site X")).toBeInTheDocument();
    await user.click(screen.getByTitle("Revogar"));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/integrations/leads/keys/k-1/revoke"),
    );
  });
});
