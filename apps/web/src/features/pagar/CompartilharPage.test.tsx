import { act, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, useEffect, useRef } from "react";
import type { NavigateFunction } from "react-router-dom";
import { MemoryRouter, Route, Routes, useNavigate, useNavigationType } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { takeSharedFile } from "../../lib/shareInbox";
import CompartilharPage from "./CompartilharPage";

vi.mock("../../lib/api", () => ({
  api: { post: vi.fn() },
  apiErrorMessage: (e: unknown) => String(e),
}));
vi.mock("../../lib/shareInbox", () => ({ takeSharedFile: vi.fn() }));

type ProbeHandle = { navigate: NavigateFunction; getActionType: () => string };

/** Expõe, para os testes, uma forma de navegar imperativamente e de ler o tipo da navegação mais
 * recente (PUSH/REPLACE/POP) — sem trocar para createMemoryRouter (o data router deste projeto
 * dispara um `AbortSignal` que o polyfill fetch do jsdom/undici não reconhece nesse ambiente de
 * teste, travando qualquer navegação). */
function TestProbe({ onReady }: { onReady: (handle: ProbeHandle) => void }) {
  const navigate = useNavigate();
  const actionType = useNavigationType();
  const actionRef = useRef(actionType);
  actionRef.current = actionType;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    onReadyRef.current({ navigate, getActionType: () => actionRef.current });
  }, [navigate]);

  return null;
}

function renderAt(url: string, extraRoutes: JSX.Element[] = [], strict = false) {
  let handle: ProbeHandle | null = null;
  const tree = (
    <MemoryRouter initialEntries={[url]}>
      <TestProbe onReady={(h) => (handle = h)} />
      <Routes>
        <Route path="/compartilhar" element={<CompartilharPage />} />
        <Route path="/comprovante/:id" element={<p>tela do comprovante</p>} />
        {extraRoutes}
      </Routes>
    </MemoryRouter>
  );
  render(strict ? <StrictMode>{tree}</StrictMode> : tree);
  return {
    navigate: (to: string) => act(() => handle!.navigate(to)),
    getActionType: () => handle!.getActionType(),
  };
}

describe("CompartilharPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sobe o arquivo compartilhado e vai para a tela de vinculacao com replace (Back nao reentra na chave consumida)", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockResolvedValue({ data: { id: "r-1" } } as never);

    const { getActionType } = renderAt("/compartilhar?k=abc");

    await waitFor(() => screen.getByText("tela do comprovante"));
    expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/payables/receipts");
    // Achado 4: a navegação precisa ser REPLACE, não PUSH — senão Back volta para /compartilhar
    // com a chave já consumida (spinner eterno / "arquivo não encontrado" de novo).
    await waitFor(() => expect(getActionType()).toBe("REPLACE"));
  });

  it("mostra recado tratado quando a chave nao existe mais", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(null);
    renderAt("/compartilhar?k=perdida");
    await waitFor(() => screen.getByText(/não encontramos o arquivo/i));
    expect(screen.getByRole("link", { name: /contas a pagar/i })).toBeTruthy();
  });

  it("mostra recado quando o service worker sinaliza erro", async () => {
    renderAt("/compartilhar?erro=falha");
    await waitFor(() => screen.getByText(/não conseguimos receber/i));
    expect(vi.mocked(takeSharedFile)).not.toHaveBeenCalled();
  });

  it("mostra o erro da API sem tela em branco quando o upload falha", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockRejectedValue(new Error("413"));
    renderAt("/compartilhar?k=abc");
    await waitFor(() => screen.getByText(/413/));
  });

  // Achado 1: takeSharedFile também pode REJEITAR (erro de IndexedDB), não só resolver null.
  // Sem essa cobertura, a promessa rejeitada virava unhandled rejection e a tela ficava presa em
  // "Enviando comprovante..." para sempre — exatamente a tela em branco que o brief proíbe.
  it("mostra recado tratado quando takeSharedFile REJEITA (erro de IndexedDB), sem spinner preso", async () => {
    vi.mocked(takeSharedFile).mockRejectedValue(new Error("erro-indexeddb"));
    renderAt("/compartilhar?k=abc");
    await waitFor(() => screen.getByText(/erro-indexeddb/));
    expect(screen.queryByText(/enviando comprovante/i)).toBeNull();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  });

  // Achado 2: o guard de StrictMode não pode ser um booleano permanente. Se o SW navegar a mesma
  // janela para uma chave nova (sem reload de documento), o compartilhamento seguinte precisa ser
  // processado — não travar silenciosamente porque "já rodou uma vez".
  it("processa um compartilhamento seguinte quando o SW navega a mesma janela para uma nova chave", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["y"], "comp2.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockResolvedValue({ data: { id: "r-2" } } as never);

    const { navigate } = renderAt("/compartilhar?erro=falha");
    await waitFor(() => screen.getByText(/não conseguimos receber/i));
    expect(vi.mocked(takeSharedFile)).not.toHaveBeenCalled();

    navigate("/compartilhar?k=abc2");

    await waitFor(() => screen.getByText("tela do comprovante"));
    expect(vi.mocked(takeSharedFile)).toHaveBeenCalledWith("abc2");
  });

  // Achado 3: se o usuário sair da tela enquanto o upload está pendente, a resolução tardia não
  // pode navegar para uma tela que ele já abandonou.
  it("ignora o resultado do upload se o usuario ja saiu da tela de transito", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    let resolvePost!: (v: { data: { id: string } }) => void;
    vi.mocked(api.post).mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve;
      }) as never,
    );

    const { navigate } = renderAt("/compartilhar?k=abc", [
      <Route key="outra" path="/outra" element={<p>outra tela</p>} />,
    ]);

    await waitFor(() => expect(vi.mocked(api.post)).toHaveBeenCalled());

    navigate("/outra");
    await waitFor(() => screen.getByText("outra tela"));

    await act(async () => {
      resolvePost({ data: { id: "r-1" } });
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.queryByText("tela do comprovante")).toBeNull());
    expect(screen.getByText("outra tela")).toBeTruthy();
  });

  // Achado 5 (#226): sob React.StrictMode (produção real via main.tsx), a 2ª montagem do efeito
  // via que `startedFor === token` e desistia SEM se inscrever no resultado. Quando a limpeza do
  // StrictMode cancelava a 1ª montagem, ninguém vivo chamava setError/navigate e o spinner ficava
  // preso em "Enviando comprovante..." para sempre. A 2ª montagem (a que sobrevive) precisa
  // terminar — sucesso ou erro — mesmo reaproveitando a mesma requisição da 1ª.
  it("sob StrictMode, a 2a montagem termina (sucesso) e nao trava em 'Enviando comprovante...'", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(
      new File(["x"], "comp.pdf", { type: "application/pdf" }),
    );
    vi.mocked(api.post).mockResolvedValue({ data: { id: "r-strict" } } as never);

    renderAt("/compartilhar?k=strict1", [], true);

    await waitFor(() => screen.getByText("tela do comprovante"), { timeout: 2000 });
    // dedup: mesmo com StrictMode montando duas vezes, a chave só é buscada uma vez.
    expect(vi.mocked(takeSharedFile)).toHaveBeenCalledTimes(1);
  });

  it("sob StrictMode, a 2a montagem termina (erro) e nao trava em 'Enviando comprovante...'", async () => {
    vi.mocked(takeSharedFile).mockResolvedValue(null);

    renderAt("/compartilhar?k=strict2", [], true);

    await waitFor(() => screen.getByText(/não encontramos o arquivo/i), { timeout: 2000 });
    expect(screen.queryByText(/enviando comprovante/i)).toBeNull();
  });
});
