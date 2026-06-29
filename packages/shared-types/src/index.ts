/**
 * Contrato de API compartilhado entre web e (futura) mobile.
 * Deve espelhar os schemas Pydantic do backend (apps/api/app/.../schemas).
 * Quando um schema do backend mudar, atualize aqui — os agentes de QA (dedup-checker)
 * vigiam tipos que deveriam morar neste pacote.
 */

// ── Identidade / acesso ────────────────────────────────
export type UUID = string;

export type UserRole = "owner" | "sub_user";

export interface Tenant {
  id: UUID;
  slug: string; // subdomínio: <slug>.e1p.com
  legal_name: string;
  document: string; // CNPJ/CPF
  created_at: string;
}

export interface User {
  id: UUID;
  tenant_id: UUID;
  email: string;
  name: string;
  role: UserRole;
  /** Módulos que um sub-usuário pode acessar (RBAC). Vazio = todos (owner). */
  allowed_modules: string[];
  is_active: boolean;
  created_at: string;
}

export interface AuthToken {
  access_token: string;
  token_type: "bearer";
  user: User;
  tenant: Tenant;
}

// ── Auditoria ──────────────────────────────────────────
export interface AuditEntry {
  id: UUID;
  tenant_id: UUID;
  actor: string; // user id ou "ai"
  is_ai: boolean; // true => "Ação executada pela IA"
  action: string;
  target: string;
  created_at: string;
}

// ── Envelope de erro padrão da API ─────────────────────
export interface ApiError {
  detail: string;
  code?: string;
}

// Os tipos de cada módulo (agenda, crm, financeiro...) entram aqui conforme forem construídos.
