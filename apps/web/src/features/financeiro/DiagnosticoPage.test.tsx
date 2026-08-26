import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import DiagnosticoPage from "./DiagnosticoPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <DiagnosticoPage />
    </MemoryRouter>,
  );
}

// Rede sempre mockada (IV2): nenhum teste bate em /financial-intelligence real.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn() },
  apiErrorMessage: (err: unknown) =>
    (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data
      ?.detail ??
    (err as { message?: string })?.message ??
    "Erro inesperado",
}));

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

// ── `GET /financial-intelligence/diagnostics` fora de forma (issue #247) ────────────────
//
// `setData(res.data)` recebia o payload CRU. `countByLevel(data.signals)` faz `for (const s of
// signals)` sem `?.` — `Array.isArray`, no molde de `CrmPage.tsx` (#225). Guarda por CAMPO, com
// `null` de fallback (a própria render checa `{data && (...)}`).
describe("DiagnosticoPage — diagnóstico fora de forma não derruba a tela (#247)", () => {
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["objeto sem a chave signals", { start: "2026-08-01", end: "2026-08-31" }],
    ["array no lugar do objeto (raiz certa, campo errado)", [{ level: "vermelho" }]],
    ["string no lugar do objeto", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela segue montada, sem os sinais", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);

    renderPage();
    await waitFor(() => expect(api.get).toHaveBeenCalled());

    expect(screen.getByText("Diagnóstico financeiro")).toBeInTheDocument();
    expect(screen.queryByText("Sinais determinísticos")).not.toBeInTheDocument();
  });

  it("contra-teste: diagnóstico de verdade continua mostrando os sinais", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        start: "2026-08-01",
        end: "2026-08-31",
        signals: [
          {
            level: "verde",
            title: "Tudo em dia",
            explanation: "Nenhuma divergência relevante.",
            source: "completude",
          },
        ],
        narrative: "Está tudo bem.",
        narrative_source: "template",
      },
    } as never);

    renderPage();

    expect(await screen.findByText("Sinais determinísticos")).toBeInTheDocument();
    expect(screen.getByText("Tudo em dia")).toBeInTheDocument();
  });
});
