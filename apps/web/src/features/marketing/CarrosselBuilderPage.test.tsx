import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import CarrosselBuilderPage from "./CarrosselBuilderPage";

// Story 7.18 — Task 1. Rede sempre mockada (IV2): nenhum teste bate em /marketing real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Brand Kit fictício mínimo (lido só quando isNew — sem PII real).
const profile = {
  primary_color: "#B078FF",
  accent_color: "#3CD3A4",
  font: "Raleway",
  website: "@perfil_teste",
};

// CarrosselBuilderPage usa useParams/useNavigate → rota /marketing/novo (isNew=true, linha 23).
function renderNew() {
  return render(
    <MemoryRouter initialEntries={["/marketing/novo"]}>
      <Routes>
        <Route path="/marketing/:id" element={<CarrosselBuilderPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/marketing/carousels/templates") return Promise.resolve({ data: [] } as never);
    if (url === "/settings/profile") return Promise.resolve({ data: profile } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
});

describe("CarrosselBuilderPage — gerar carrossel (Story 7.18, Task 1)", () => {
  it("caminho feliz: tema válido → POST /marketing/carousels/generate e a legenda gerada aparece", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({
      data: {
        slides: [{ kind: "editorial", heading: "Slide 1", secondary: "detalhe" }],
        caption: "Legenda IA de teste",
        hashtags: "#teste",
      },
    } as never);
    renderNew();

    const tema = await screen.findByPlaceholderText(
      "ex: o lado oculto da IA no mercado de trabalho",
    );
    await user.type(tema, "o lado oculto da IA no mercado de trabalho");

    await user.click(screen.getByRole("button", { name: "Gerar com IA" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/marketing/carousels/generate",
      expect.objectContaining({ topic: "o lado oculto da IA no mercado de trabalho", slides: 7 }),
    );
    // Estado local reflete o resultado: a legenda gerada aparece no campo controlado.
    expect(await screen.findByDisplayValue("Legenda IA de teste")).toBeInTheDocument();
  });

  it("caminho infeliz: tema vazio é bloqueado client-side, SEM chamar a API", async () => {
    const user = userEvent.setup();
    renderNew();

    // Botão habilitado (disabled só por `generating`), mas generate() faz early-return.
    await user.click(await screen.findByRole("button", { name: "Gerar com IA" }));

    expect(
      await screen.findByText("Escreva um tema para a IA gerar o carrossel."),
    ).toBeInTheDocument();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  });
});
