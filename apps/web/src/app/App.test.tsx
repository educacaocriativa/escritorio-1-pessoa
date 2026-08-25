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
const auth = vi.hoisted(() => ({
  isAuthenticated: false,
  user: null as { role: "owner" | "sub_user"; allowed_modules: string[] } | null,
}));
vi.mock("../store/auth", () => ({
  useAuth: () => ({ isAuthenticated: auth.isAuthenticated, user: auth.user }),
}));
vi.mock("../store/useIdleTimeout", () => ({
  useIdleTimeout: () => ({ showWarning: false, stayConnected: vi.fn() }),
}));

import { LoginRoute, Modulo, ProtectedBareLayout, ProtectedLayout } from "./App";

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

// Achado do usuário testando em campo: no celular a sidebar (256px fixos) e a topbar do
// AppShell espremiam /compartilhar e /comprovante/:id a ponto de o checkbox "marcar como paga"
// ficar fora da área visível — o usuário tocava Anexar sem conseguir ver/desmarcar o que estava
// confirmando. `ProtectedBareLayout` aplica a MESMA proteção de `ProtectedLayout` (mesmo
// `useAuthGate`) sem montar `AppShell` — o teste prova as duas metades: acesso bloqueado
// deslogado, e nenhum vestígio do shell quando autenticado.
describe("ProtectedBareLayout — mesma proteção do ProtectedLayout, sem sidebar/topbar", () => {
  beforeEach(() => {
    auth.isAuthenticated = false;
  });

  it("deslogado, redireciona para /login guardando a origem — igual ao ProtectedLayout", async () => {
    render(
      <MemoryRouter initialEntries={["/comprovante/r-1"]}>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route element={<ProtectedBareLayout />}>
            <Route path="/comprovante/:id" element={<p>tela do comprovante</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    // Chegar em <LoginPage> de verdade (não um probe) já prova o redirecionamento; a preservação
    // da origem via state é coberta, campo a campo, pelos testes de ProtectedLayout acima —
    // ambos os layouts chamam o MESMO useAuthGate, não duas implementações a manter em sincronia.
    await waitFor(() => screen.getByRole("button", { name: /^entrar$/i }));
  });

  it("autenticado, renderiza o conteúdo SEM sidebar nem topbar do AppShell", async () => {
    auth.isAuthenticated = true;

    render(
      <MemoryRouter initialEntries={["/comprovante/r-1"]}>
        <Routes>
          <Route element={<ProtectedBareLayout />}>
            <Route path="/comprovante/:id" element={<p>tela do comprovante</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => screen.getByText("tela do comprovante"));
    // "Sair" só existe na Sidebar do AppShell — sua ausência prova que o shell não montou.
    expect(screen.queryByText("Sair")).toBeNull();
  });
});

// A causa mais funda do defeito relatado (ficha do cliente e Configurações travadas em
// "Carregando..." para um sub-usuário sem certos módulos): a sidebar mostrava todo item a todo
// usuário e nenhuma rota sabia recusar antes de a página tentar buscar dados que voltariam 403.
// `Modulo` é a segunda metade da correção (a primeira é `visibleNavSections`, em
// `navigation.test.ts`) — protege contra link direto/favorito/URL digitada, não só o clique no
// menu.
describe("Modulo — guarda de rota por RBAC (espelha require_module do backend)", () => {
  it("dono (`allowed_modules` vazio) vê qualquer módulo", () => {
    auth.user = { role: "owner", allowed_modules: [] };
    render(
      <Modulo m="juridico">
        <p>conteúdo do módulo</p>
      </Modulo>,
    );
    expect(screen.getByText("conteúdo do módulo")).toBeInTheDocument();
  });

  it("sub-usuário COM o módulo em `allowed_modules` vê o conteúdo", () => {
    auth.user = { role: "sub_user", allowed_modules: ["crm", "juridico"] };
    render(
      <Modulo m="juridico">
        <p>conteúdo do módulo</p>
      </Modulo>,
    );
    expect(screen.getByText("conteúdo do módulo")).toBeInTheDocument();
  });

  it("sub-usuário SEM o módulo vê 'sem acesso' em vez do conteúdo — nunca um spinner eterno", () => {
    auth.user = { role: "sub_user", allowed_modules: ["crm"] };
    render(
      <Modulo m="juridico">
        <p>conteúdo do módulo</p>
      </Modulo>,
    );
    expect(screen.queryByText("conteúdo do módulo")).toBeNull();
    expect(screen.getByText(/não tem acesso a este módulo/i)).toBeInTheDocument();
  });
});
