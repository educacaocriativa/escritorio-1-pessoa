import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import JuridicoDocumentPage from "./JuridicoDocumentPage";

// Story 7.17 — Task 3. Rede sempre mockada (IV2): nenhum teste bate em /juridico real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Mitigação prescrita na Task 3: o jsdom NÃO implementa URL.createObjectURL/revokeObjectURL
// (usados em downloadDocx). Sem stub, chamar downloadDocx lança "Not implemented". Stub local,
// sem dependência nova (Regra de Ouro nº 4).
const createObjectURL = vi.fn(() => "blob:mock-url");
vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
// Evita o aviso "not implemented: HTMLAnchorElement.prototype.click" do jsdom no <a> sintético.
const clickSpy = vi
  .spyOn(HTMLAnchorElement.prototype, "click")
  .mockImplementation(() => {});

afterAll(() => {
  vi.unstubAllGlobals();
  clickSpy.mockRestore();
});

// LegalDocument fictício "ready" (sem PII real, AC3).
const readyDoc = {
  id: "doc-teste",
  tenant_id: "t-1",
  skill: "peticao-teste",
  category: "essenciais",
  title: "Petição fictícia",
  client_id: null,
  client_name: null,
  content: "Corpo do documento gerado (fictício).",
  metadata_raw: "",
  answers: {},
  input_tokens: 10,
  output_tokens: 20,
  status: "ready",
  created_at: "2026-07-11T00:00:00Z",
};

function renderDoc() {
  return render(
    <MemoryRouter initialEntries={["/juridico/doc-teste"]}>
      <Routes>
        <Route path="/juridico/:id" element={<JuridicoDocumentPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  createObjectURL.mockClear();
});

describe("JuridicoDocumentPage — download .docx (Story 7.17, Task 3)", () => {
  it("caminho feliz: baixar .docx chama GET com responseType blob e URL.createObjectURL(blob)", async () => {
    const user = userEvent.setup();
    const blob = new Blob(["fake docx"], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/juridico/documents/doc-teste") return Promise.resolve({ data: readyDoc } as never);
      if (url === "/juridico/documents/doc-teste/docx")
        return Promise.resolve({ data: blob } as never);
      return Promise.resolve({ data: {} } as never);
    });
    renderDoc();

    await user.click(await screen.findByRole("button", { name: /Word/ }));

    await waitFor(() =>
      expect(vi.mocked(api.get)).toHaveBeenCalledWith(
        "/juridico/documents/doc-teste/docx",
        { responseType: "blob" },
      ),
    );
    // Prova que o fluxo de download foi disparado (sem depender do download real do browser).
    expect(createObjectURL).toHaveBeenCalledWith(blob);
  });

  it("caminho infeliz: documento status=failed mostra a falha graciosa sem quebrar a tela", async () => {
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === "/juridico/documents/doc-teste")
        return Promise.resolve({
          data: {
            ...readyDoc,
            status: "failed",
            content: "Falha ao gerar: sem chave de API configurada",
          },
        } as never);
      return Promise.resolve({ data: {} } as never);
    });
    renderDoc();

    // Box de aviso (bg-warning/10) renderiza o content no lugar do <article> normal.
    expect(
      await screen.findByText("Falha ao gerar: sem chave de API configurada"),
    ).toBeInTheDocument();
    // Os botões continuam presentes e clicáveis — a tela não quebrou (cobre o AC1 do epic).
    expect(screen.getByRole("button", { name: "Copiar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Word/ })).toBeEnabled();
  });
});
