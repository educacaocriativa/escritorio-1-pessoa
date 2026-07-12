import type { SessionInfo, Tenant, User } from "@e1p/shared-types";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Testes de componente da tela de 1º acesso — FirstAccessPage (Story 7.4, AC2/AC3).
// Mesmo padrão da 7.3: imports explícitos de `vitest`, user-event, matchers/cleanup globais de
// `src/test-setup.ts`, e REDE SEMPRE MOCKADA (IV2). Escopo (Task 2): testa a tela diretamente
// (o roteamento condicional `if (user?.must_reset_password)` vive em App.tsx/ProtectedLayout,
// fora deste teste de componente).

// `useAuth()` mockado: FirstAccessPage usa apenas `updateUser` e `logout`.
const { updateUserMock, logoutMock } = vi.hoisted(() => ({
  updateUserMock: vi.fn(),
  logoutMock: vi.fn(),
}));
vi.mock("../../store/auth", () => ({
  useAuth: () => ({ updateUser: updateUserMock, logout: logoutMock }),
}));

// `lib/api` mockado só no `api.post`; `apiErrorMessage` REAL preservado (importActual).
const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));
vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, api: { post: postMock } };
});

import FirstAccessPage from "./FirstAccessPage";

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
  // Após a troca, o flag do 1º acesso é limpo → libera o app.
  must_reset_password: false,
  created_at: "2026-01-01T00:00:00Z",
};

const session: SessionInfo = { user, tenant };

describe("FirstAccessPage (Story 7.4 — 1º acesso / troca de senha)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("caminho feliz: senhas conferem, chama POST /auth/change-password e atualiza o usuário", async () => {
    postMock.mockResolvedValueOnce({ data: session });

    render(<FirstAccessPage />);

    const novaSenha = "senha-nova-123"; // >= 8 caracteres (respeita o `disabled` do botão)
    await userEvent.type(
      screen.getByPlaceholderText("Nova senha (mín. 8 caracteres)"),
      novaSenha,
    );
    await userEvent.type(screen.getByPlaceholderText("Confirme a nova senha"), novaSenha);
    await userEvent.click(screen.getByRole("button", { name: /salvar e entrar/i }));

    // Chamou a API com o corpo esperado...
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith("/auth/change-password", { new_password: novaSenha }),
    );
    // ...e propagou o usuário atualizado (must_reset_password=false) para o contexto.
    expect(updateUserMock).toHaveBeenCalledWith(session.user);
  });

  it("caminho infeliz: senhas divergentes bloqueiam sem chamar a API", async () => {
    render(<FirstAccessPage />);

    // Ambas com >= 8 chars (botão habilitado), porém DIFERENTES → validação client-side barra.
    await userEvent.type(
      screen.getByPlaceholderText("Nova senha (mín. 8 caracteres)"),
      "senha-nova-123",
    );
    await userEvent.type(
      screen.getByPlaceholderText("Confirme a nova senha"),
      "senha-diferente-456",
    );
    await userEvent.click(screen.getByRole("button", { name: /salvar e entrar/i }));

    // A mensagem de divergência aparece...
    expect(await screen.findByText("As senhas não conferem.")).toBeInTheDocument();
    // ...e a API nunca é chamada (bloqueio antes de qualquer rede — IV2).
    expect(postMock).not.toHaveBeenCalled();
    expect(updateUserMock).not.toHaveBeenCalled();
  });
});
