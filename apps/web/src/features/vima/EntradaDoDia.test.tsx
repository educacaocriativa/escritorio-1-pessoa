import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import EntradaDoDia, { CHAVE_ENTRADA } from "./EntradaDoDia";

// O fuso do TENANT é trocável por teste (modelo de `NewEventModal.test.tsx`). O `vitest.config.ts`
// fixa o fuso da MÁQUINA em America/Sao_Paulo: enquanto o tenant mockado for esse mesmo valor,
// `today(fuso)` e `localYmd(new Date())` devolvem o MESMO dia por construção, e a marca de
// "já entrei hoje" não consegue provar que é o dia do TENANT.
let fusoDoTenant = "America/Sao_Paulo";
// Tóquio (UTC+9) está 12h à frente do runner — sob ele os dois caminhos discordam sobre o DIA.
const FUSO_DISTANTE = "Asia/Tokyo";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  apiErrorMessage: () => "erro",
}));

vi.mock("../../store/auth", () => ({
  useFuso: () => fusoDoTenant,
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
  fusoDoTenant = "America/Sao_Paulo";
});

// Em `afterEach`, não no corpo do teste: uma asserção que falha antes do `useRealTimers()` faria
// os fake timers vazarem para os testes seguintes, e uma falha viraria cascata sem relação.
afterEach(() => {
  vi.useRealTimers();
});

/**
 * Congela o relógio num instante em que TÓQUIO, SÃO PAULO e UTC discordam sobre que dia é:
 * 16/08/2026 22:00Z é 17/08 07:00 em Tóquio, 16/08 19:00 em São Paulo (o fuso do runner) e
 * 16/08 em UTC. Só quem lê pelo fuso do TENANT chega ao dia 17.
 */
const HOJE_EM_TOQUIO = "2026-08-17";
function relogioEmQueOsFusosDiscordam() {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-16T22:00:00Z"));
}

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
    // A marca é o dia do TENANT, não `toISOString().slice(0,10)` (que é o dia UTC) nem o dia do
    // NAVEGADOR. A primeira versão deste teste usou UTC e falhou só depois das 21h no Brasil — a
    // mesma classe de bug que a correção de fuso de 2026-08-05 eliminou de ~25 telas.
    //
    // ⚠️ A marca é uma STRING LITERAL de propósito. Escrevê-la com `today(fuso)` — como esta
    // versão fazia — usa a MESMA função que a tela usa: o teste compara o código consigo mesmo e
    // passa qualquer que seja o fuso, inclusive com a tela lendo o do navegador.
    fusoDoTenant = FUSO_DISTANTE;
    relogioEmQueOsFusosDiscordam();
    localStorage.setItem(CHAVE_ENTRADA, HOJE_EM_TOQUIO);
    // A rede responde, mesmo não devendo ser chamada: assim, uma marca que não bate falha na
    // asserção ("o cockpit" não aparece) em vez de estourar num `undefined.then` sem sentido.
    vi.mocked(api.get).mockResolvedValue({ data: { id: "b1", read_at: null } });
    renderEntrada();
    await waitFor(() => expect(screen.getByText("o cockpit")).toBeInTheDocument());
    expect(api.get).not.toHaveBeenCalled();
  });

  it("marca de ONTEM não vale: o briefing é diário", async () => {
    // Fuso do runner de propósito: "2020-01-01" está a seis anos de qualquer leitura possível, e
    // nenhum fuso do mundo muda essa resposta. Este teste é sobre a marca VELHA, não sobre fuso.
    localStorage.setItem(CHAVE_ENTRADA, "2020-01-01");
    vi.mocked(api.get).mockResolvedValue({ data: { id: "b1", read_at: null } });
    renderEntrada();
    await waitFor(() => expect(screen.getByText("a tela do briefing")).toBeInTheDocument());
  });

  it("marca o dia ao decidir — e o dia gravado é o do TENANT, não o do navegador", async () => {
    // O outro lado da marca: além de LER pelo fuso do tenant, a entrada tem que GRAVAR nele.
    // Gravar o dia do navegador faria a marca vencer cedo (ou tarde) demais para quem viaja.
    fusoDoTenant = FUSO_DISTANTE;
    relogioEmQueOsFusosDiscordam();
    vi.mocked(api.get).mockResolvedValue({ data: { id: "b1", read_at: null } });
    renderEntrada();
    await waitFor(() => expect(screen.getByText("a tela do briefing")).toBeInTheDocument());
    expect(localStorage.getItem(CHAVE_ENTRADA)).toBe(HOJE_EM_TOQUIO); // e NÃO "2026-08-16"
  });

  it("briefing indisponível não tranca a entrada: cai no Cockpit e tenta de novo depois", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("500"));
    renderEntrada();
    await waitFor(() => expect(screen.getByText("o cockpit")).toBeInTheDocument());
    // Sem marca: falhar hoje não pode custar o briefing de hoje na próxima tentativa.
    expect(localStorage.getItem(CHAVE_ENTRADA)).toBeNull();
  });
});
