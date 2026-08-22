import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { assentar } from "../../test/assentar";
import JuridicoPage from "./JuridicoPage";

// issue #207 — DOIS sites de payload cru no mesmo arquivo, com consequências DIFERENTES:
//   `setDocs(data)`   → `docs.slice(0, 6).map` no render
//   `setSkills(data)` → `for (const s of skills)` dentro do `useMemo`
// O segundo é o que a varredura por `.map`/`.length`/`.filter` NÃO enxerga — e é igualmente fatal.
vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  publicApi: { post: vi.fn() },
  apiErrorMessage: () => "Erro inesperado",
}));

const SKILL_OK = [
  {
    skill: "peticao-inicial",
    label: "Petição inicial",
    description: "Redige a peça",
    category: "core",
    output_type: "peça",
  },
];
const DOC_OK = [
  {
    id: "d-1",
    title: "Contrato de prestação",
    category: "core",
    client_name: "Cliente A",
    status: "ready",
  },
];

/** Só UM dos dois endpoints é corrompido por vez — a falha tem de ser atribuível ao seu site. */
function mock({ skills, docs }: { skills: unknown; docs: unknown }) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url === "/juridico/skills") return Promise.resolve({ data: skills } as never);
    if (url === "/juridico/documents") return Promise.resolve({ data: docs } as never);
    return Promise.resolve({ data: [] } as never);
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <JuridicoPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
});

describe("JuridicoPage — `GET /juridico/documents` fora de forma (#207)", () => {
  // ⚠️ Nem toda forma mata este site, e isso é medição, não escolha de conveniência: o render é
  // guardado por `docs.length > 0`, e em objeto ou número `.length` é `undefined` — `undefined > 0`
  // é falso e o `.map` nunca roda. Para ESSAS duas formas o mutante é equivalente. As duas abaixo
  // são as que passam pelo portão: string tem `.length` e não tem `.map`; `null` estoura no
  // próprio `.length`.
  it.each([
    ["string no lugar da lista", "não é json"],
    ["corpo vazio (204 / sem conteúdo)", null],
  ])("%s → a tela renderiza sem os documentos, e as skills continuam de pé", async (_r, payload) => {
    mock({ skills: SKILL_OK, docs: payload });
    renderPage();
    await assentar();

    // A seção de skills fica DEPOIS da de documentos na árvore: vê-la é a prova de que o render
    // chegou ao fim em vez de estourar no meio.
    expect(screen.getByText("Petição inicial")).toBeInTheDocument();
    expect(screen.queryByText("Documentos recentes")).not.toBeInTheDocument();
  });

  it("contra-teste: documento de verdade continua aparecendo", async () => {
    mock({ skills: SKILL_OK, docs: DOC_OK });
    renderPage();
    await assentar();

    expect(screen.getByText("Documentos recentes")).toBeInTheDocument();
    expect(screen.getByText("Contrato de prestação")).toBeInTheDocument();
  });
});

describe("JuridicoPage — `GET /juridico/skills` fora de forma (#207)", () => {
  // ⚠️ Aqui o consumo é `for (const s of skills)`: o que mata é ser NÃO ITERÁVEL, não a falta de
  // `.map`. Por isso a string sai da lista — string é iterável (por caractere), o `for..of` passa,
  // e o resultado é um mapa de categorias vazio. Mutante equivalente para essa forma, medido.
  it.each([
    ["envelope de erro devolvido com 200", { detail: "algo deu errado" }],
    ["corpo vazio (204 / sem conteúdo)", null],
    ["número no lugar da lista", 7],
  ])("%s → a tela renderiza sem as skills, e os documentos continuam de pé", async (_r, payload) => {
    mock({ skills: payload, docs: DOC_OK });
    renderPage();
    await assentar();

    expect(screen.getByText("Contrato de prestação")).toBeInTheDocument();
    expect(screen.queryByText("Petição inicial")).not.toBeInTheDocument();
  });

  it("contra-teste: skill de verdade continua agrupada na categoria", async () => {
    mock({ skills: SKILL_OK, docs: DOC_OK });
    renderPage();
    await assentar();

    expect(screen.getByText("Essenciais")).toBeInTheDocument();
    expect(screen.getByText("Petição inicial")).toBeInTheDocument();
  });
});
