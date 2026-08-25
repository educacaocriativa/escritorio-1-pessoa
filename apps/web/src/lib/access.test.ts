import { describe, expect, it } from "vitest";
import { hasModule } from "./access";

/**
 * Espelha, um a um, os ramos de `require_module` em `app/core/tenancy.py`:
 * `user.role == "owner" or not user.allowed_modules or module in user.allowed_modules`.
 */
describe("hasModule", () => {
  it("nenhum usuário logado nunca tem acesso", () => {
    expect(hasModule(null, "juridico")).toBe(false);
  });

  it("dono (role=owner) tem acesso a qualquer módulo, mesmo com allowed_modules restrito", () => {
    expect(hasModule({ role: "owner", allowed_modules: ["crm"] }, "juridico")).toBe(true);
  });

  it("allowed_modules VAZIO é 'sem restrição' — não 'sem módulo nenhum'", () => {
    expect(hasModule({ role: "sub_user", allowed_modules: [] }, "juridico")).toBe(true);
  });

  it("sub-usuário com o módulo na lista tem acesso", () => {
    expect(hasModule({ role: "sub_user", allowed_modules: ["crm", "juridico"] }, "juridico")).toBe(true);
  });

  it("sub-usuário sem o módulo na lista NÃO tem acesso — o caso que travava a tela", () => {
    expect(hasModule({ role: "sub_user", allowed_modules: ["crm"] }, "juridico")).toBe(false);
  });
});
