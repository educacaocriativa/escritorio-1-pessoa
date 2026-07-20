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

describe("PageBuilderPage — publicar: tratamento de erro (Story 7.19)", () => {
  it("caminho infeliz (POST /publish falha): PATCH resolve, POST rejeita → erro no DOM e tela segue interativa (AC 2, 4, 5)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockResolvedValue({ data: draftPage } as never);
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao publicar a página." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Publicar" }));

    // save() (PATCH) rodou e o POST /publish foi tentado.
    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalledWith("/pages/page-teste/publish"));
    // A mensagem do apiErrorMessage aparece no <div> de erro compartilhado.
    expect(await screen.findByText("Falha ao publicar a página.")).toBeInTheDocument();
    // Tela permanece montada, editável e funcional: botão "Publicar" segue presente e clicável,
    // título segue editável, "Salvar" reabilitado (sem crash / sem botão travado).
    expect(screen.getByRole("button", { name: "Publicar" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
    expect(screen.getByDisplayValue("Página de teste")).toBeInTheDocument();
  });

  it("caminho infeliz (save prévio falha): PATCH rejeita → POST /publish NÃO é chamado e o erro do save aparece sem duplicação (AC 1, 6)", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao salvar a página." } },
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Publicar" }));

    // O erro setado pelo próprio catch de save() permanece visível.
    expect(await screen.findByText("Falha ao salvar a página.")).toBeInTheDocument();
    // publish() retornou cedo: nenhum POST /publish disparado.
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    // Sem erro adicional/duplicado: exatamente um <div> de erro no DOM.
    expect(screen.getAllByText("Falha ao salvar a página.")).toHaveLength(1);
    // Tela segue interativa.
    expect(screen.getByRole("button", { name: "Publicar" })).toBeEnabled();
  });
});

describe("PageBuilderPage — copiar código do iframe", () => {
  it("salva a página e copia o <iframe> pronto pra colar em outro site", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    vi.mocked(api.patch).mockResolvedValue({ data: draftPage } as never);
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Copiar código/ }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const snippet = writeText.mock.calls[0][0] as string;
    expect(snippet).toContain("<iframe");
    expect(snippet).toContain(`src="${window.location.origin}/p/slug-teste"`);
    expect(await screen.findByRole("button", { name: /Copiado!/ })).toBeInTheDocument();
  });
});
