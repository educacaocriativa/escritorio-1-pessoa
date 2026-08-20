import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("../../lib/api", () => ({ api: { get: (...a: unknown[]) => get(...a) } }));

import BuscaGlobal from "./BuscaGlobal";

/** Sonda: mostra a URL atual, para asserir navegação sem espiar o router por dentro. */
function Sonda() {
  const loc = useLocation();
  return <p data-testid="url">{loc.pathname + loc.search}</p>;
}

const RESPOSTA = {
  data: {
    groups: [
      {
        type: "client",
        has_more: false,
        total: null,
        items: [
          { id: "1", title: "Ana Souza", subtitle: "ana@x.com", route: "/crm/clients/1", snippet: null },
        ],
      },
      {
        type: "contract",
        has_more: false,
        total: null,
        items: [
          { id: "9", title: "Contrato da Ana", subtitle: "assinado", route: "/contratos/9", snippet: null },
        ],
      },
    ],
  },
};

function montar() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <BuscaGlobal />
      <Routes>
        <Route path="*" element={<Sonda />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("BuscaGlobal", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue(RESPOSTA);
  });

  it("a seta para baixo ATRAVESSA grupos", async () => {
    montar();
    await userEvent.type(screen.getByRole("combobox"), "ana");
    await screen.findByText("Clientes");

    await userEvent.keyboard("{ArrowDown}{ArrowDown}");

    // O segundo item está em OUTRO grupo: para o teclado a lista é uma só.
    expect(screen.getByRole("option", { selected: true })).toHaveTextContent("Contrato da Ana");
  });

  it("Enter sem item focado leva para a página de resultados", async () => {
    montar();
    await userEvent.type(screen.getByRole("combobox"), "ana");
    await screen.findByText("Clientes");

    await userEvent.keyboard("{Enter}");

    expect(screen.getByTestId("url")).toHaveTextContent("/busca?q=ana");
  });

  it("Enter com item focado abre o registro daquele item", async () => {
    montar();
    await userEvent.type(screen.getByRole("combobox"), "ana");
    await screen.findByText("Clientes");

    await userEvent.keyboard("{ArrowDown}{Enter}");

    expect(screen.getByTestId("url")).toHaveTextContent("/crm/clients/1");
  });

  it("Esc fecha e devolve o foco ao campo", async () => {
    montar();
    const campo = screen.getByRole("combobox");
    await userEvent.type(campo, "ana");
    await screen.findByRole("listbox");

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(campo).toHaveFocus();
  });

  it("com menos de dois caracteres não consulta o servidor", async () => {
    montar();
    await userEvent.type(screen.getByRole("combobox"), "a");

    // Uma letra casa com quase tudo: oito varreduras por tecla, para devolver ruído.
    expect(get).not.toHaveBeenCalled();
  });

  it("o vazio da camada rasa aponta para a funda", async () => {
    get.mockResolvedValue({ data: { groups: [] } });
    montar();
    await userEvent.type(screen.getByRole("combobox"), "rescisao");

    // É exatamente o caso em que a resposta pode estar na outra camada.
    expect(await screen.findByText(/procurar em documentos e mensagens/i)).toBeInTheDocument();
  });
});
