import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ContractBuilderPage from "./ContractBuilderPage";

// Story 7.5 — Task 3. Rede sempre mockada (IV2): nenhum teste bate em /contracts real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Contrato válido devolvido pelo POST feliz (hydrate() lê status/public_slug/clauses...).
const savedContract = {
  id: "ct-1",
  public_slug: "abc123",
  status: "draft",
  title: "Prestação de serviços",
  client_id: null,
  clauses: [{ title: "", text: "Objeto do contrato: consultoria." }],
  variables: {},
};

// ContractBuilderPage usa useParams/useNavigate → monta a rota /contratos/novo (isNew=true).
function renderNew() {
  return render(
    <MemoryRouter initialEntries={["/contratos/novo"]}>
      <Routes>
        <Route path="/contratos/:id" element={<ContractBuilderPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/crm/clients") return Promise.resolve({ data: [] } as never);
    if (url === "/contracts/templates") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
  vi.mocked(api.post).mockReset();
  vi.mocked(api.patch).mockReset();
});

describe("ContractBuilderPage — salvar contrato (Story 7.5, Task 3)", () => {
  it("caminho feliz: título + ao menos uma cláusula → POST /contracts com clauses preenchidas", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValue({ data: savedContract } as never);
    renderNew();

    await user.type(screen.getByPlaceholderText("Título do contrato"), "Prestação de serviços");
    await user.type(
      screen.getByPlaceholderText(/Texto da cláusula/),
      "Objeto do contrato: consultoria.",
    );

    await user.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/contracts",
      expect.objectContaining({
        title: "Prestação de serviços",
        clauses: [expect.objectContaining({ text: "Objeto do contrato: consultoria." })],
      }),
    );
  });

  it("caminho infeliz: sem título/cláusula é bloqueado client-side, SEM chamar a API", async () => {
    const user = userEvent.setup();
    renderNew();

    // Clica "Salvar" com o formulário vazio (título vazio + cláusula sem texto).
    await user.click(screen.getByRole("button", { name: "Salvar" }));

    // Mensagem exata da validação client-side já existente no componente.
    expect(
      await screen.findByText("Informe um título e ao menos uma cláusula."),
    ).toBeInTheDocument();
    // Prova de que a validação é 100% client-side: nenhum round-trip ao backend.
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    expect(vi.mocked(api.patch)).not.toHaveBeenCalled();
  });
});
