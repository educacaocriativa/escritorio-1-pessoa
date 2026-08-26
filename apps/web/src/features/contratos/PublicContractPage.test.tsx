import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { publicApi } from "../../lib/api";
import PublicContractPage from "./PublicContractPage";

// Rota PÚBLICA (sem sessão) — rede sempre mockada (IV2): nenhum teste bate em /public/contracts
// real.
vi.mock("../../lib/api", () => ({
  publicApi: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

beforeEach(() => {
  vi.mocked(publicApi.get).mockReset();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/assinar/abc123"]}>
      <Routes>
        <Route path="/assinar/:slug" element={<PublicContractPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ── `GET /public/contracts/{slug}` fora de forma (issue #247) ───────────────────────────
//
// `setContract(data)` recebia o payload CRU numa rota PÚBLICA (sem sessão, sem tenant): quem abre
// um link de contrato não pode ver a tela quebrar. `contract.clauses.map` roda direto no render,
// sem `?.` — `Array.isArray`, no molde de `CrmPage.tsx` (#225). Guarda por CAMPO, reusando o
// estado "Contrato indisponível." que a página já tem para o instante ANTES da resposta chegar.
describe("PublicContractPage — contrato fora de forma não derruba a assinatura (#247)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["objeto sem a chave clauses", { title: "Contrato", company_name: "e1p", status: "sent", signer_name: "", signed_at: null }],
    ["array no lugar do objeto (raiz certa, campo errado)", [{ title: "x" }]],
    ["string no lugar do objeto", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a página não estoura (mostra 'Contrato indisponível')", async (_rotulo, payload) => {
    vi.mocked(publicApi.get).mockResolvedValue({ data: payload } as never);

    renderPage();
    await waitFor(() => expect(publicApi.get).toHaveBeenCalled());

    expect(await screen.findByText("Contrato indisponível.")).toBeInTheDocument();
  });

  it("contra-teste: contrato de verdade continua mostrando as cláusulas", async () => {
    vi.mocked(publicApi.get).mockResolvedValue({
      data: {
        title: "Prestação de serviços",
        company_name: "e1p",
        clauses: [{ title: "Objeto", text: "Descrição do serviço." }],
        status: "sent",
        signer_name: "",
        signed_at: null,
      },
    } as never);

    renderPage();

    expect(await screen.findByText("Prestação de serviços")).toBeInTheDocument();
    expect(screen.getByText("Descrição do serviço.")).toBeInTheDocument();
  });
});
