import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
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
});
