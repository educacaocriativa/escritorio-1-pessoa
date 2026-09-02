import type { AuthToken, Tenant, User } from "@e1p/shared-types";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError } from "axios";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Testes de componente da UI de `auth` — LoginPage/LoginForm (Story 7.4, AC1/AC3).
// Seguem o padrão estabelecido pela Story 7.3 (Dev Agent Record): imports explícitos de
// `vitest` (globals:false), queries por prioridade (getByRole > getByLabelText), interação via
// `@testing-library/user-event`, matchers jest-dom + cleanup herdados de `src/test-setup.ts`
// (sem repetir `afterEach(cleanup)`), e REDE SEMPRE MOCKADA (nunca bate no backend real — IV2).

// `useAuth()` mockado: LoginPage só destrutura `login` e o passa como `onLogin` ao LoginForm.
// Mockar aqui permite assertar que `login` recebe exatamente `(access_token, user, tenant)`
// vindos do payload da API — o contrato testável do componente em isolamento (ver AUTO-DECISION
// de escopo da Task 1: o redirecionamento em si vive em App.tsx/react-router, fora deste teste).
const { loginMock } = vi.hoisted(() => ({ loginMock: vi.fn() }));
vi.mock("../../store/auth", () => ({
  useAuth: () => ({ login: loginMock }),
}));

// `lib/api` mockado só no `api.post`; `apiErrorMessage` REAL é preservado (importActual) para
// exercer de verdade o parsing de `AxiosError.response.data.detail` no caminho de erro.
const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));
vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, api: { post: postMock } };
});

import LoginPage from "./LoginPage";

/**
 * A tela passou a exibir, fora do cartão, os links para `/privacidade` e `/termos` — e `<Link>`
 * exige contexto de rota. Envolver aqui mantém os testes exercitando o COMPONENTE REAL, em vez
 * de trocar os links por `<a>` só para não precisar de um Router no teste.
 */
function renderLoginPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

const tenant: Tenant = {
  id: "t-1",
  slug: "joaosilva",
  legal_name: "João Silva ME",
  document: "12345678000199",
  created_at: "2026-01-01T00:00:00Z",
};

const user: User = {
  id: "u-1",
  tenant_id: "t-1",
  email: "joao@e1p.com",
  name: "João Silva",
  role: "owner",
  allowed_modules: [],
  is_active: true,
  is_platform_admin: false,
  document: null,
  address: null,
  phone: null,
  must_reset_password: false,
  created_at: "2026-01-01T00:00:00Z",
};

const authToken: AuthToken = {
  access_token: "jwt-token-abc",
  token_type: "bearer",
  user,
  tenant,
};

describe("LoginPage / LoginForm (Story 7.4 — portão de entrada)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("caminho feliz: login válido chama POST /auth/login e propaga token/usuário/tenant", async () => {
    postMock.mockResolvedValueOnce({ data: authToken });

    renderLoginPage();

    await userEvent.type(screen.getByLabelText("E-mail"), "joao@e1p.com");
    await userEvent.type(screen.getByLabelText("Senha"), "senha-super-secreta");
    await userEvent.click(screen.getByRole("button", { name: /^entrar$/i }));

    // Chamou o endpoint correto com as credenciais preenchidas.
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith("/auth/login", {
        email: "joao@e1p.com",
        password: "senha-super-secreta",
      }),
    );
    // E propagou EXATAMENTE token/usuário/tenant do payload para o `login` do contexto.
    expect(loginMock).toHaveBeenCalledWith(authToken.access_token, authToken.user, authToken.tenant);
  });

  it("caminho infeliz: credencial inválida mostra o erro sem quebrar a tela", async () => {
    const err = new AxiosError("Request failed with status code 401");
    // Formato que `apiErrorMessage` espera: AxiosError com response.data.detail.
    (err as { response?: unknown }).response = {
      data: { detail: "E-mail ou senha inválidos" },
    };
    postMock.mockRejectedValueOnce(err);

    renderLoginPage();

    await userEvent.type(screen.getByLabelText("E-mail"), "joao@e1p.com");
    await userEvent.type(screen.getByLabelText("Senha"), "senha-errada");
    await userEvent.click(screen.getByRole("button", { name: /^entrar$/i }));

    // A mensagem de erro do backend aparece no DOM...
    expect(await screen.findByText("E-mail ou senha inválidos")).toBeInTheDocument();
    // ...`login` nunca é chamado (fluxo não completou)...
    expect(loginMock).not.toHaveBeenCalled();
    // ...e a tela continua interativa: `loading` voltou a false → o botão "Entrar" reabilitado.
    expect(screen.getByRole("button", { name: /^entrar$/i })).not.toBeDisabled();
  });

  it("caminho infeliz: campos vazios não chamam a API (validação nativa de `required`)", async () => {
    renderLoginPage();

    // Submete sem preencher nada — os inputs são `required`, então o jsdom bloqueia o submit.
    await userEvent.click(screen.getByRole("button", { name: /^entrar$/i }));

    expect(postMock).not.toHaveBeenCalled();
    expect(loginMock).not.toHaveBeenCalled();
  });
});

// ── `dev_reset_token` fora de forma (issue #179) ──────────────────────────────
//
// Sétimo site da classe, FORA da lista da issue: `devToken` é renderizado direto em
// `<code>{devToken}</code>`. Com `?? null`, um objeto *truthy* passava e o React estoura com
// "Objects are not valid as a React child" — tela branca no LOGIN, a única tela de onde ninguém
// consegue sair navegando.
describe("ForgotForm — dev_reset_token só é exibido se tiver FORMA de token", () => {
  beforeEach(() => {
    postMock.mockReset();
  });

  async function pedirRedefinicao() {
    renderLoginPage();
    await userEvent.click(screen.getByRole("button", { name: /esqueci minha senha/i }));
    await userEvent.type(screen.getByLabelText(/e-mail/i), "joao@e1p.com");
    await userEvent.click(screen.getByRole("button", { name: /enviar/i }));
  }

  it.each([
    ["objeto", { toString: "x" }],
    ["número", 12345],
    ["booleano", true],
    ["array", ["tok"]],
  ])("dev_reset_token %s não é renderizado e não derruba o login", async (_rotulo, valor) => {
    postMock.mockResolvedValue({ data: { message: "ok", dev_reset_token: valor } });
    await pedirRedefinicao();

    await waitFor(() => expect(screen.queryByRole("code")).not.toBeInTheDocument());
    expect(screen.queryByText(/token:/i)).not.toBeInTheDocument();
  });

  it("token string de verdade continua aparecendo", async () => {
    postMock.mockResolvedValue({ data: { message: "ok", dev_reset_token: "tok-123" } });
    await pedirRedefinicao();

    await waitFor(() => expect(screen.getByText("tok-123")).toBeInTheDocument());
  });
});
