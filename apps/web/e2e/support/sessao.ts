import type { Page } from "@playwright/test";

/**
 * Sessão autenticada sem passar pelo login: o app guarda tudo em `localStorage`
 * (`store/auth.tsx`) e não chama `/auth/me` no boot. Um teste de LAYOUT não deve gastar dois
 * requests provando de novo que o login funciona — isso é assunto de outro teste.
 */
export async function semearSessao(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem("e1p_token", "e2e.layout.token");
    localStorage.setItem(
      "e1p_user",
      JSON.stringify({
        id: "00000000-0000-4000-8000-000000000001",
        tenant_id: "00000000-0000-4000-8000-000000000002",
        email: "dono@exemplo.com.br",
        name: "Flávio Kato",
        role: "owner",
        allowed_modules: [],
        is_active: true,
        is_platform_admin: false,
        document: null,
        address: null,
        phone: null,
        must_reset_password: false,
      }),
    );
    localStorage.setItem(
      "e1p_tenant",
      JSON.stringify({
        id: "00000000-0000-4000-8000-000000000002",
        legal_name: "Flávio Kato Consultoria Empresarial ME",
        slug: "flaviokato",
        timezone: "America/Sao_Paulo",
      }),
    );
    // As duas marcas de "já decidi isto neste aparelho" — sem elas a raiz sequestra a navegação.
    localStorage.setItem("e1p_dna_nucleo", "1");
    localStorage.setItem("e1p_entrada_do_dia", "1");
  });
}
