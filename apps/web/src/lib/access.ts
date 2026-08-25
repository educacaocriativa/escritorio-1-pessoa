import type { User } from "@e1p/shared-types";

/**
 * Espelha `require_module` de `app/core/tenancy.py`: dono ou lista vazia não têm restrição;
 * senão, o módulo precisa estar em `allowed_modules`.
 *
 * ⚠️ **É a ÚNICA porta desta regra no frontend.** Antes deste módulo, nada aqui consultava
 * `allowed_modules` — a sidebar mostrava todo item a todo usuário e nenhuma tela sabia dizer
 * "você não tem este módulo" antes de disparar a requisição. O sintoma era a tela travar em
 * "Carregando..." para sempre quando a API respondia 403 (issue: ficha do cliente e
 * Configurações travadas para um sub-usuário sem Jurídico/Funis/Configurações).
 */
export function hasModule(user: Pick<User, "role" | "allowed_modules"> | null | undefined, module: string): boolean {
  if (!user) return false;
  if (user.role === "owner") return true;
  if (user.allowed_modules.length === 0) return true;
  return user.allowed_modules.includes(module);
}
