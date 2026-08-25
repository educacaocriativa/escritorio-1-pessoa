import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { PageActionsProvider } from "../../store/pageActions";
import { assentar } from "../../test/assentar";
import PlanoContasPage from "./PlanoContasPage";

// issue #207 — `setAccounts(data)`: payload cru no setter, SEM operador nenhum. É o PIOR site da
// leva: `buildHierarchy(accounts)` roda no CORPO do componente, antes de qualquer JSX, e abre com
// `for (const acc of accounts)`. Payload não iterável estoura ali, e sem ErrorBoundary no app a
// árvore inteira some.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

function renderPage() {
  return render(
    <PageActionsProvider>
      <PlanoContasPage />
    </PageActionsProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("PlanoContasPage — plano de contas fora de forma não derruba a tela (#207)", () => {
  // ⚠️ A string sai da lista por medição, não por conveniência: string É iterável (por caractere),
  // o `for..of` passa, cada caractere devolve `grupo_dre === undefined`, o `byGroup.has` recusa e o
  // resultado é a hierarquia vazia. Mutante equivalente para essa forma. As três abaixo NÃO são
  // iteráveis e estouram.
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a tela mostra o estado vazio em vez de estourar", async (_rotulo, payload) => {
    vi.mocked(api.get).mockResolvedValue({ data: payload } as never);
    renderPage();
    await assentar();

    expect(
      screen.getByText(
        'Nenhuma categoria ainda. Clique em "Nova categoria" ou use as categorias sugeridas.',
      ),
    ).toBeInTheDocument();
    // Os 6 grupos DRE saem SEMPRE (`buildHierarchy` é total): vê-los prova que o corpo do
    // componente rodou até o fim em vez de estourar no `for..of`.
    expect(screen.getByText("Receita")).toBeInTheDocument();
    expect(screen.getByText("Investimento")).toBeInTheDocument();
  });

  it("contra-teste: categoria de verdade continua agrupada no grupo DRE", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: "a-1",
          grupo_dre: "RECEITA",
          categoria: "Consultoria",
          archived_at: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    } as never);
    renderPage();
    await assentar();

    expect(screen.getByText("Consultoria")).toBeInTheDocument();
    expect(
      screen.queryByText(
        'Nenhuma categoria ainda. Clique em "Nova categoria" ou use as categorias sugeridas.',
      ),
    ).not.toBeInTheDocument();
  });
});
