import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import JuridicoWizardPage from "./JuridicoWizardPage";

// Story 7.17 — Tasks 1 e 2. Rede sempre mockada (IV2/AC3): nenhum teste bate em /juridico real
// nem chama a API da Anthropic. TODO fixture é claramente fictício (AC3 — zero PII real).
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

// Contrato real de LegalWizardConfig (packages/shared-types). Wizard dinâmico MÍNIMO: 1 step,
// 1 campo text obrigatório "fatos" — prova que o formulário é gerado do config, não hardcoded.
const wizardText = {
  skill: "peticao-teste",
  label: "Petição de teste",
  category: "essenciais",
  description: "Skill fictícia de teste",
  output_type: "documento",
  steps: [
    {
      id: "s1",
      title: "Fatos do caso",
      fields: [{ key: "fatos", label: "Fatos", type: "text", required: true }],
    },
  ],
};

// Config da Task 2: 1 campo upload obrigatório — exercita a UI de anexo e a satisfação da
// validação obrigatória por `extracted.length > 0`.
const wizardUpload = {
  ...wizardText,
  steps: [
    {
      id: "s1",
      title: "Peças do processo",
      fields: [
        {
          key: "pecas",
          label: "Peças",
          type: "upload",
          accept: ".pdf,.docx,image/*,.txt",
          multiple: true,
          required: true,
        },
      ],
    },
  ],
};

function mockGet(cfg: unknown) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/juridico/skills/peticao-teste") return Promise.resolve({ data: cfg } as never);
    if (url === "/crm/clients") return Promise.resolve({ data: [] } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

// Wizard usa useSearchParams (?skill=) + useNavigate → MemoryRouter com rota /juridico/novo.
// Rota-stub /juridico/:id prova a navegação pós-geração (react-router prioriza segmento estático).
function renderWizard() {
  return render(
    <MemoryRouter initialEntries={["/juridico/novo?skill=peticao-teste"]}>
      <Routes>
        <Route path="/juridico/novo" element={<JuridicoWizardPage />} />
        <Route path="/juridico/:id" element={<div>Documento aberto</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.post).mockReset();
});

describe("JuridicoWizardPage — wizard dinâmico (Story 7.17, Task 1)", () => {
  it("caminho feliz: preenche o campo dinâmico e gera → POST /juridico/documents + navegação", async () => {
    const user = userEvent.setup();
    mockGet(wizardText);
    vi.mocked(api.post).mockResolvedValue({ data: { id: "doc-teste" } } as never);
    renderWizard();

    // Campo "Fatos" é gerado a partir do wizard_config mockado (prova que É dinâmico).
    const fatos = await screen.findByRole("textbox");
    await user.type(fatos, "Cliente sofreu dano em 01/01.");

    await user.click(screen.getByRole("button", { name: "Gerar documento" }));

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/juridico/documents", {
      skill: "peticao-teste",
      answers: { fatos: "Cliente sofreu dano em 01/01." },
      client_id: null,
      extracted_text: "",
    });
    // Navegou para /juridico/doc-teste (rota-stub).
    expect(await screen.findByText("Documento aberto")).toBeInTheDocument();
  });

  it("caminho infeliz: sem o campo obrigatório o botão fica disabled e NÃO chama a API", async () => {
    const user = userEvent.setup();
    mockGet(wizardText);
    renderWizard();

    // Espera o wizard montar (o campo dinâmico aparece), sem preencher "Fatos".
    await screen.findByRole("textbox");

    const gerar = screen.getByRole("button", { name: "Gerar documento" });
    expect(gerar).toBeDisabled();
    await user.click(gerar); // clique num botão desabilitado não dispara o onClick
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  });
});

describe("JuridicoWizardPage — anexo de peças (Story 7.17, Task 2)", () => {
  it("caminho feliz: upload extrai texto, lista o arquivo e satisfaz a validação obrigatória", async () => {
    const user = userEvent.setup();
    mockGet(wizardUpload);
    vi.mocked(api.post).mockResolvedValue({
      data: { filename: "peticao-teste.pdf", chars: 1234, text: "texto extraído fictício" },
    } as never);
    const { container } = renderWizard();

    // Antes do upload: campo upload obrigatório vazio → "Gerar documento" desabilitado.
    const gerar = await screen.findByRole("button", { name: "Gerar documento" });
    expect(gerar).toBeDisabled();

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      fileInput,
      new File(["conteudo fictício"], "peticao-teste.pdf", { type: "application/pdf" }),
    );

    // POST /juridico/extract chamado (multipart) e o arquivo aparece na lista de extraídos.
    await waitFor(() =>
      expect(vi.mocked(api.post)).toHaveBeenCalledWith(
        "/juridico/extract",
        expect.any(FormData),
        expect.objectContaining({ headers: { "Content-Type": "multipart/form-data" } }),
      ),
    );
    expect(
      await screen.findByText(/peticao-teste\.pdf — 1\.234 caracteres extraídos/),
    ).toBeInTheDocument();
    // extracted.length > 0 → validação obrigatória satisfeita → botão habilitado.
    expect(screen.getByRole("button", { name: "Gerar documento" })).toBeEnabled();
  });

  it("caminho infeliz: falha na extração exibe erro sem quebrar a tela", async () => {
    const user = userEvent.setup();
    mockGet(wizardUpload);
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Falha ao extrair o texto do arquivo." } },
    });
    const { container } = renderWizard();

    await screen.findByText("Enviar arquivo(s) — PDF, Word, imagem");
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      fileInput,
      new File(["conteudo fictício"], "peticao-teste.pdf", { type: "application/pdf" }),
    );

    expect(await screen.findByText("Falha ao extrair o texto do arquivo.")).toBeInTheDocument();
    // `extracting` volta a false no finally → rótulo do upload volta ao normal, tela intacta.
    expect(screen.getByText("Enviar arquivo(s) — PDF, Word, imagem")).toBeInTheDocument();
  });
});
