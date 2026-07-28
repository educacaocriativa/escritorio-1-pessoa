import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import ComprovantePage from "./ComprovantePage";

vi.mock("../../lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));

const ABERTA = {
  id: "b-aberta", description: "Energia", supplier: "Copel", amount_cents: 30000,
  due_date: "2099-01-10", status: "open", is_overdue: false, paid_at: null,
};
const PAGA = {
  id: "b-paga", description: "Internet", supplier: "Vivo", amount_cents: 12000,
  due_date: "2099-01-05", status: "paid", is_overdue: false, paid_at: "2026-07-20T10:00:00Z",
};

function mockApi(candidates = [ABERTA, PAGA]) {
  vi.mocked(api.get).mockImplementation((url: string) => {
    if (url.startsWith("/payables/receipts/candidates")) {
      return Promise.resolve({ data: candidates });
    }
    if (url === "/payables/receipts") {
      return Promise.resolve({
        data: [{ id: "r-1", filename: "comp.pdf", content_type: "application/pdf",
                 size: 1024, created_at: "2026-07-28T10:00:00Z" }],
      });
    }
    return Promise.resolve({ data: [] });
  });
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/comprovante/r-1"]}>
      <Routes>
        <Route path="/comprovante/:id" element={<ComprovantePage />} />
        <Route path="/pagar" element={<p>contas a pagar</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ComprovantePage", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.useRealTimers());

  it("lista as contas candidatas com nome, valor e status", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));
    expect(screen.getByText("Internet")).toBeTruthy();
    expect(screen.getByText("Pago")).toBeTruthy();
  });

  it("mostra o checkbox de baixa apenas para conta em aberto", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    const check = screen.getByRole("checkbox", { name: /marcar como paga/i }) as HTMLInputElement;
    expect(check.checked).toBe(true); // marcado por padrão

    await userEvent.click(screen.getByText("Internet"));
    expect(screen.queryByRole("checkbox", { name: /marcar como paga/i })).toBeNull();
  });

  it("vincula chamando link com o payload correto", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-aberta" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    await userEvent.click(screen.getByRole("button", { name: /^anexar$/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/payables/receipts/r-1/link");
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({
      bill_id: "b-aberta", mark_paid: true,
    });
  });

  it("envia mark_paid false quando o usuario desmarca", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-aberta" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    await userEvent.click(screen.getByRole("checkbox", { name: /marcar como paga/i }));
    await userEvent.click(screen.getByRole("button", { name: /^anexar$/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(vi.mocked(api.post).mock.calls[0][1]).toEqual({
      bill_id: "b-aberta", mark_paid: false,
    });
  });

  it("busca refaz a consulta com o termo digitado", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.type(screen.getByPlaceholderText(/buscar conta/i), "copel");
    await waitFor(() =>
      expect(
        vi.mocked(api.get).mock.calls.some(([url]) =>
          String(url).includes("candidates?q=copel"),
        ),
      ).toBe(true),
    );
  });

  it("cria conta nova a partir do formulario curto", async () => {
    mockApi();
    vi.mocked(api.post).mockResolvedValue({ data: { id: "b-novo" } } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    await userEvent.type(screen.getByPlaceholderText(/descrição/i), "Estacionamento");
    await userEvent.type(screen.getByPlaceholderText(/valor/i), "45,00");
    await userEvent.click(screen.getByRole("button", { name: /criar e anexar/i }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, payload] = vi.mocked(api.post).mock.calls[0];
    expect(url).toBe("/payables/receipts/r-1/new-bill");
    expect((payload as { amount_cents: number }).amount_cents).toBe(4500);
  });

  it("descartar remove o comprovante e volta para contas a pagar", async () => {
    mockApi();
    vi.mocked(api.delete).mockResolvedValue({ data: null } as never);
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /descartar/i }));
    await waitFor(() => screen.getByText("contas a pagar"));
    expect(api.delete).toHaveBeenCalledWith("/payables/receipts/r-1");
  });

  // Achado (aplicando a lição da Task 9): a busca dispara uma nova requisição a cada tecla.
  // Se a resposta antiga (da query anterior) chegar DEPOIS da resposta nova (fora de ordem),
  // ela não pode sobrescrever a lista já atualizada — senão a tela "pisca" de volta para um
  // resultado que não corresponde mais ao que está no campo de busca.
  it("ignora resposta de busca antiga que chega fora de ordem", async () => {
    let resolveFirst!: (v: { data: (typeof ABERTA)[] }) => void;
    let resolveSecond!: (v: { data: (typeof PAGA)[] }) => void;
    let candidateCalls = 0;
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url.startsWith("/payables/receipts/candidates")) {
        candidateCalls += 1;
        if (candidateCalls === 1) {
          return new Promise((resolve) => {
            resolveFirst = resolve;
          });
        }
        return new Promise((resolve) => {
          resolveSecond = resolve;
        });
      }
      return Promise.resolve({ data: [] });
    });

    renderPage();
    await waitFor(() => expect(candidateCalls).toBe(1));

    await userEvent.type(screen.getByPlaceholderText(/buscar conta/i), "x");
    await waitFor(() => expect(candidateCalls).toBe(2));

    // resolve a busca mais recente primeiro...
    resolveSecond({ data: [PAGA] });
    await waitFor(() => screen.getByText("Internet"));

    // ...e só depois a resposta antiga, que deve ser ignorada.
    resolveFirst({ data: [ABERTA] });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.queryByText("Energia")).toBeNull();
    expect(screen.getByText("Internet")).toBeTruthy();
  });

  // Achado 1 da revisão: toISOString() formata o instante em UTC. À noite no Brasil (UTC-3),
  // o instante UTC já é o dia seguinte — então a data de vencimento pré-preenchida do
  // formulário de conta nova viraria "amanhã" silenciosamente. Fixamos o relógio num instante
  // em que UTC e horário local discordam de dia (23:30 local = já é o dia seguinte em UTC) e
  // exigimos que o campo mostre o dia LOCAL.
  it("preenche a data de vencimento padrao com o dia LOCAL, nao UTC, mesmo a noite", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-03-10T23:30:00-03:00")); // já é 2026-03-11 em UTC

    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    const dateInput = screen.getByLabelText(/data de vencimento/i) as HTMLInputElement;
    expect(dateInput.value).toBe("2026-03-10");
  });

  // Achado 2 da revisão: nada impedia selecionar uma conta candidata (habilitando o "Anexar"
  // fixo no rodapé) enquanto o formulário de conta nova também estava aberto e submissível —
  // dois caminhos de mutação alcançáveis ao mesmo tempo para o mesmo comprovante. Abrir o
  // formulário de conta nova precisa remover o "Anexar" do documento, não só desabilitá-lo.
  it("abrir o formulario de conta nova esconde o botao Anexar (fluxos mutuamente exclusivos)", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    expect(screen.getByRole("button", { name: /^anexar$/i })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));

    expect(screen.queryByRole("button", { name: /^anexar$/i })).toBeNull();
  });

  // Revisão final de branch (Finding 6): antes, uma vez escolhida uma candidata não havia como
  // desmarcá-la — "Criar conta nova" ficava travado atrás de `!chosen`, e a única saída era
  // filtrar a lista até a candidata sumir. Tocar de novo na mesma candidata precisa desmarcar
  // (toggle), devolvendo "Anexar" ao estado desabilitado e "Criar conta nova" ao alcance.
  it("tocar de novo na candidata ja selecionada desmarca (toggle-off), sem beco sem saida", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByText("Energia"));
    expect(screen.getByRole("button", { name: /^anexar$/i })).not.toBeDisabled();
    expect(screen.queryByRole("button", { name: /criar conta nova/i })).toBeNull();

    await userEvent.click(screen.getByText("Energia"));

    expect(screen.getByRole("button", { name: /^anexar$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /criar conta nova/i })).toBeTruthy();
  });

  // Achado 1 (rodada 2 de revisão): a correção anterior só fechava a exclusão mútua numa
  // direção. Nada resetava `showNew` ao selecionar uma candidata — abrir a conta nova e DEPOIS
  // selecionar uma candidata deixava os dois guards (`!chosen` e `!showNew`) falsos ao mesmo
  // tempo, escondendo tanto o formulário quanto o "Anexar". Usuário ficava sem nenhuma forma de
  // arquivar o comprovante (só Descartar). Selecionar uma candidata precisa fechar a conta nova.
  it("selecionar uma candidata com o formulario de conta nova aberto restaura o Anexar (sem beco sem saida)", async () => {
    mockApi();
    renderPage();
    await waitFor(() => screen.getByText("Energia"));

    await userEvent.click(screen.getByRole("button", { name: /criar conta nova/i }));
    expect(screen.queryByRole("button", { name: /^anexar$/i })).toBeNull();

    await userEvent.click(screen.getByText("Energia"));

    expect(screen.getByRole("button", { name: /^anexar$/i })).toBeTruthy();
    expect(screen.queryByPlaceholderText(/descrição/i)).toBeNull();
  });
});
