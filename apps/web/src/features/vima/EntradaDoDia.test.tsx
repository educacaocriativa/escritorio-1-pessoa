import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { today } from "../../lib/datetime";
import EntradaDoDia, { CHAVE_ENTRADA } from "./EntradaDoDia";

const FUSO = "America/Sao_Paulo";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: () => "erro",
}));

vi.mock("../../store/auth", () => ({
  useFuso: () => FUSO,
}));

function renderEntrada() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route
          path="/"
          element={
            <EntradaDoDia>
              <p>o cockpit</p>
            </EntradaDoDia>
          }
        />
        <Route path="/vima" element={<p>a tela do briefing</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.get).mockReset();
});

describe("EntradaDoDia — o briefing é porta de entrada UMA VEZ POR DIA", () => {
  it("briefing de hoje ainda não lido: a entrada é a Vima", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { id: "b1", read_at: null } });
    renderEntrada();
    await waitFor(() => expect(screen.getByText("a tela do briefing")).toBeInTheDocument());
  });

  it("briefing já lido: a entrada é o Cockpit", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { id: "b1", read_at: "2026-08-06T10:06:00Z" } });
    renderEntrada();
    await waitFor(() => expect(screen.getByText("o cockpit")).toBeInTheDocument());
  });

  it("já entrou hoje neste aparelho: vai direto ao Cockpit, SEM perguntar de novo", async () => {
    // A marca é o dia do TENANT, não `toISOString().slice(0,10)` (que é o dia UTC). A primeira
    // versão deste teste usou UTC e falhou só depois das 21h no Brasil — a mesma classe de bug
    // que a correção de fuso de 2026-08-05 eliminou de ~25 telas.
    localStorage.setItem(CHAVE_ENTRADA, today(FUSO));
    renderEntrada();
    await waitFor(() => expect(screen.getByText("o cockpit")).toBeInTheDocument());
    expect(api.get).not.toHaveBeenCalled();
  });

  it("marca de ONTEM não vale: o briefing é diário", async () => {
    localStorage.setItem(CHAVE_ENTRADA, "2020-01-01");
    vi.mocked(api.get).mockResolvedValue({ data: { id: "b1", read_at: null } });
    renderEntrada();
    await waitFor(() => expect(screen.getByText("a tela do briefing")).toBeInTheDocument());
  });

  it("marca o dia ao decidir — quem volta ao painel não é reenviado à Vima em loop", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { id: "b1", read_at: null } });
    renderEntrada();
    await waitFor(() => expect(screen.getByText("a tela do briefing")).toBeInTheDocument());
    expect(localStorage.getItem(CHAVE_ENTRADA)).toBeTruthy();
  });

  it("briefing indisponível não tranca a entrada: cai no Cockpit e tenta de novo depois", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("500"));
    renderEntrada();
    await waitFor(() => expect(screen.getByText("o cockpit")).toBeInTheDocument());
    // Sem marca: falhar hoje não pode custar o briefing de hoje na próxima tentativa.
    expect(localStorage.getItem(CHAVE_ENTRADA)).toBeNull();
  });
});
