import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import PageBuilderPage from "./PageBuilderPage";

// Story 7.18 — Task 2. Rede sempre mockada (IV2): nenhum teste bate em /pages real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

const draftPage = {
  id: "page-teste",
  title: "Página de teste",
  blocks: [],
  status: "draft",
  public_slug: "slug-teste",
  primary_color: "#5D44F8",
  bg_color: "#FFFFFF",
  text_color: "#111827",
  accent_color: "#3CD3A4",
  font: "Inter",
  logo_url: "",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/sites/page-teste"]}>
      <Routes>
        <Route path="/sites/:id" element={<PageBuilderPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/pages/page-teste") return Promise.resolve({ data: draftPage } as never);
    return Promise.resolve({ data: {} } as never);
  });
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
});

describe("PageBuilderPage — publicar/salvar (Story 7.18, Task 2)", () => {
  it("caminho feliz: 'Publicar' faz PATCH depois POST /publish e o status vira 'Publicada'", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockResolvedValue({ data: draftPage } as never);
    vi.mocked(api.post).mockResolvedValue({
      data: { ...draftPage, status: "published" },
    } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Publicar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.patch)).toHaveBeenCalledWith(
      "/pages/page-teste",
      expect.objectContaining({ title: "Página de teste", blocks: [] }),
    );
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/pages/page-teste/publish");
    // Ordem: save() (PATCH) antes do POST /publish.
    expect(vi.mocked(api.patch).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.post).mock.invocationCallOrder[0],
    );
    expect(await screen.findByText("Publicada")).toBeInTheDocument();
  });

  it("caminho infeliz: erro ao Salvar é exibido sem travar a tela (botão reabilitado)", async () => {
    const user = userEvent.setup();
    // Usa "Salvar" (que TEM try/catch real), não "Publicar" — este chama POST /publish sem
    // tratamento de erro (achado documentado na Task 2); não escrevemos teste sobre unhandled rejection.
    vi.mocked(api.patch).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao salvar a página." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Salvar" }));

    expect(await screen.findByText("Falha ao salvar a página.")).toBeInTheDocument();
    // Tela segue montada e editável: o botão "Salvar" volta a ficar habilitado (saving → false).
    expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  });
});
