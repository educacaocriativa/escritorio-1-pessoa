import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("../../lib/api", () => ({ api: { get: (...a: unknown[]) => get(...a) } }));

import BuscaPage from "./BuscaPage";

function montar(url = "/busca?q=rescisao") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/busca" element={<BuscaPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const UM_GRUPO = {
  data: {
    groups: [
      {
        type: "legal_document",
        has_more: true,
        total: 12,
        items: [
          {
            id: "d1",
            title: "Peticao inicial",
            subtitle: "peticao",
            route: "/juridico/d1",
            snippet: "...combinada a rescisao antecipada...",
          },
        ],
      },
    ],
  },
};

describe("BuscaPage", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue(UM_GRUPO);
  });

  it("lê o termo da URL e busca FUNDO", async () => {
    montar();

    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        "/search",
        expect.objectContaining({
          params: expect.objectContaining({ q: "rescisao", depth: "deep", months: 12 }),
        }),
      ),
    );
  });

  it("mostra a contagem EXATA por grupo", async () => {
    montar();

    // Aqui a contagem É a informação — é o que impede o recorte de ser silencioso.
    expect(await screen.findByText("Jurídico (12)")).toBeInTheDocument();
  });

  it("mostra o trecho do corpo, que é o motivo de existir a camada funda", async () => {
    montar();

    expect(await screen.findByText(/rescisao antecipada/)).toBeInTheDocument();
  });

  it("o seletor diz que o recorte é SÓ das mensagens", async () => {
    montar();

    // Rótulo genérico faria o dono achar que o documento antigo também foi cortado.
    expect(await screen.findByLabelText(/mensagens dos últimos/i)).toBeInTheDocument();
  });

  it("trocar o recorte refaz a busca com o novo valor", async () => {
    montar();
    await screen.findByText("Jurídico (12)");

    await userEvent.selectOptions(screen.getByLabelText(/mensagens dos últimos/i), "0");

    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        "/search",
        expect.objectContaining({ params: expect.objectContaining({ months: 0 }) }),
      ),
    );
  });

  it("sem termo, não consulta o servidor", async () => {
    montar("/busca");

    expect(get).not.toHaveBeenCalled();
    expect(screen.getByRole("searchbox")).toHaveValue("");
  });
});
