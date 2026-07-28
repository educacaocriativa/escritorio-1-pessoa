import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Achado da revisão final de branch (Finding 2): o design pedia que uma visita deslogada a
// qualquer rota protegida (ex.: `/compartilhar?k=...`, `/comprovante/:id`) guardasse a origem e
// retomasse automaticamente depois do login. `ProtectedLayout` fazia `<Navigate to="/login"
// replace />` SEM state, e `LoginRoute` sempre mandava para `/` no sucesso — a chave do
// comprovante (só na URL) era destruída pelo `replace` e o arquivo ficava perdido no IndexedDB
// sem explicação. Esta suíte cobre o contrato genérico (qualquer rota protegida), não um
// caso especial de `/compartilhar`.
//
// `useAuth` é mockado (mesmo padrão de `LoginPage.test.tsx`) porque o objetivo aqui é o
// ROTEAMENTO em si — `ProtectedLayout`/`LoginRoute` — não a UI de login nem o AppShell
// autenticado (que tem suas próprias dependências de rede, fora do escopo deste teste).
const auth = vi.hoisted(() => ({ isAuthenticated: false }));
vi.mock("../store/auth", () => ({
  useAuth: () => ({ isAuthenticated: auth.isAuthenticated, user: null }),
}));
vi.mock("../store/useIdleTimeout", () => ({
  useIdleTimeout: () => ({ showWarning: false, stayConnected: vi.fn() }),
}));

import { LoginRoute, ProtectedLayout } from "./App";

/** Sonda que expõe a rota atual e o `state` carregado pelo history, para asserções sem UI real. */
function LocationProbe({ label }: { label: string }) {
  const location = useLocation();
  const from = (location.state as { from?: { pathname: string } } | null)?.from;
  return (
    <p>
      {label}: {location.pathname}
      {location.search} (origem guardada: {from?.pathname ?? "nenhuma"})
    </p>
  );
}

describe("Retorno pós-login para a rota de origem (Finding 2 — revisão final de branch)", () => {
  beforeEach(() => {
    auth.isAuthenticated = false;
  });

  it("visita deslogada a uma rota protegida redireciona para /login CARREGANDO a origem", async () => {
    render(
      <MemoryRouter initialEntries={["/compartilhar"]}>
        <Routes>
          <Route path="/login" element={<LocationProbe label="login" />} />
          <Route element={<ProtectedLayout />}>
            <Route path="/compartilhar" element={<LocationProbe label="compartilhar" />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    // Terminou em /login (não ficou preso em /compartilhar) e o `state.from` aponta de volta
    // para a rota que o usuário tentou acessar — é isso que o LoginRoute precisa para retomar.
    await waitFor(() =>
      screen.getByText("login: /login (origem guardada: /compartilhar)"),
    );
  });

  it("apos autenticar, LoginRoute retoma a origem guardada em vez de ir sempre para /", async () => {
    auth.isAuthenticated = true;

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/login",
            state: { from: { pathname: "/comprovante/r-1", search: "?k=abc", hash: "" } },
          },
        ]}
      >
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/comprovante/:id" element={<LocationProbe label="comprovante" />} />
          <Route path="/" element={<p>cockpit</p>} />
        </Routes>
      </MemoryRouter>,
    );

    // Pousa na rota de ORIGEM com a query string preservada (`?k=abc` — a chave do comprovante
    // no share flow), não em "/".
    await waitFor(() =>
      screen.getByText("comprovante: /comprovante/r-1?k=abc (origem guardada: nenhuma)"),
    );
    expect(screen.queryByText("cockpit")).toBeNull();
  });

  it("visita direta a /login (autenticado, sem origem guardada) vai para / normalmente", async () => {
    auth.isAuthenticated = true;

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/" element={<p>cockpit</p>} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => screen.getByText("cockpit"));
  });
});
