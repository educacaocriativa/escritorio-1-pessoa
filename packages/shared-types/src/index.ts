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

/** Retorno de GET /auth/me — só identidade, sem credencial. */
export interface SessionInfo {
  user: User;
  tenant: Tenant;
}

/** Retorno de /auth/register e /auth/login — identidade + credencial. */
export interface AuthToken extends SessionInfo {
  access_token: string;
  token_type: "bearer";
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

// ── Agenda ─────────────────────────────────────────────
export type AgendaKind =
  | "atendimento"
  | "reuniao"
  | "audiencia"
  | "bloqueio"
  | "prazo"
  | "cobranca_receber"
  | "cobranca_pagar"
  | "lembrete";

export type AgendaStatus = "scheduled" | "confirmed" | "cancelled" | "done";
export type AgendaPriority = "normal" | "high" | "critical";

export interface AgendaEvent {
  id: UUID;
  tenant_id: UUID;
  title: string;
  description: string;
  kind: AgendaKind;
  status: AgendaStatus;
  priority: AgendaPriority;
  source: string;
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  /** Valor em centavos (inteiro) para eventos de cobrança. */
  amount_cents: number | null;
  external_ref: string | null;
  created_by_ai: boolean;
  created_at: string;
}

/** Resposta de criar/remarcar evento: a 'Guardiã da Agenda' devolve conflitos detectados. */
export interface CreateEventResult {
  event: AgendaEvent;
  conflicts: AgendaEvent[];
}

// ── CRM & Kanban ───────────────────────────────────────
export type Gender = "male" | "female" | "other" | "unspecified";

export interface PipelineStage {
  id: UUID;
  name: string;
  position: number;
  is_won: boolean;
  is_lost: boolean;
}

export interface Client {
  id: UUID;
  tenant_id: UUID;
  name: string;
  email: string | null;
  phone: string | null;
  document: string | null;
  gender: Gender;
  birthdate: string | null;
  notes: string;
  tags: string[];
  source: string;
  stage_id: UUID | null;
  created_at: string;
}

export interface BoardColumn {
  stage: PipelineStage;
  clients: Client[];
}

export interface Board {
  columns: BoardColumn[];
}

// ── Cockpit (dashboard de entrada) ─────────────────────
export interface AgendaSummary {
  today_count: number;
  today_events: AgendaEvent[];
  upcoming_critical: AgendaEvent[];
}

export interface StageCount {
  stage_id: UUID;
  name: string;
  count: number;
  is_won: boolean;
  is_lost: boolean;
}

export interface CrmSummary {
  total_clients: number;
  won_count: number;
  lost_count: number;
  conversion_rate: number; // 0..1
  by_stage: StageCount[];
}

export interface FinanceSummary {
  available: boolean;
  net_revenue_cents: number | null;
  monthly_costs_cents: number | null;
  signed_contracts: number | null;
}

export interface CockpitSummary {
  agenda: AgendaSummary;
  crm: CrmSummary;
  finance: FinanceSummary;
}

// Os tipos de cada módulo (financeiro...) entram aqui conforme forem construídos.
