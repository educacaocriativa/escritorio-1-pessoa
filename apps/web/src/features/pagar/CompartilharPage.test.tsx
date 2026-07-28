import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { takeSharedFile } from "../../lib/shareInbox";
import CompartilharPage from "./CompartilharPage";

vi.mock("../../lib/api", () => ({
  api: { post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));
vi.mock("../../lib/shareInbox", () => ({ takeSharedFile: vi.fn() }));

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/compartilhar" element={<CompartilharPage />} />
        <Route path="/comprovante/:id" element={<p>tela do comprovante</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CompartilharPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sobe o arquivo compartilhado e vai para a tela de vinculacao", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockResolvedValue({ data: { id: "r-1" } } as never);

    renderAt("/compartilhar?k=abc");

    await waitFor(() => screen.getByText("tela do comprovante"));
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/payables/receipts");
  });

  it("mostra recado tratado quando a chave nao existe mais", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(null);
    renderAt("/compartilhar?k=perdida");
    await waitFor(() => screen.getByText(/não encontramos o arquivo/i));
    expect(screen.getByRole("link", { name: /contas a pagar/i })).toBeTruthy();
  });

  it("mostra recado quando o service worker sinaliza erro", async () => {
    renderAt("/compartilhar?erro=falha");
    await waitFor(() => screen.getByText(/não conseguimos receber/i));
    expect(vi.mocked(takeSharedFile)).not.toHaveBeenCalled();
  });

  it("mostra o erro da API sem tela em branco quando o upload falha", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockRejectedValue(new Error("413"));
    renderAt("/compartilhar?k=abc");
    await waitFor(() => screen.getByText(/413/));
  });
});
