/**
 * Contrato de API compartilhado entre web e (futura) mobile.
 * Deve espelhar os schemas Pydantic do backend (apps/api/app/.../schemas).
 * Quando um schema do backend mudar, atualize aqui — os agentes de QA (dedup-checker)
 * vigiam tipos que deveriam morar neste pacote.
 *
 * GERAÇÃO AUTOMÁTICA (Story 4.5): os tipos GERADOS a partir do OpenAPI do FastAPI agora vivem em
 * `./generated.ts`. Rode `pnpm generate:types` na RAIZ do monorepo para regenerá-los (exporta o
 * OpenAPI via `apps/api/scripts/export_openapi.py` → `openapi.json` → `openapi-typescript`).
 * Os tipos deste arquivo (`index.ts`) continuam mantidos À MÃO por retrocompatibilidade e devem
 * ser migrados incrementalmente para `generated.ts` em stories futuras (catalogar na Story 4.6).
 * ATENÇÃO: sem CI, a regeneração é um passo MANUAL após qualquer mudança de schema no backend —
 * `openapi.json`/`generated.ts` versionados podem sofrer drift se esquecerem de rodar o comando.
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
  /** Nível 1 (Master): gerencia todas as contas da plataforma. */
  is_platform_admin: boolean;
  document: string | null;
  address: string | null;
  phone: string | null;
  /** True = senha temporária; deve ser trocada no primeiro acesso. */
  must_reset_password: boolean;
  created_at: string;
}

/** Resultado do convite de um novo usuário: a senha temporária e como foi entregue. */
export interface StaffInvite {
  user: User;
  temp_password: string;
  delivery: "email" | "whatsapp";
  delivery_status: "sent" | "logged" | "failed";
}

/** Conta gerenciada pelo Super Admin: tenant + seu owner. */
export interface Account {
  tenant: Tenant;
  owner: User;
}

/** Cliente comprador (matrícula) — ainda não é um User de login. */
export interface PlatformCustomer {
  name: string;
  email: string | null;
  purchases: number;
}

/** Cliente na visão do Master: inclui o escritório de origem. */
export interface PlatformCustomerCard extends PlatformCustomer {
  tenant_id: UUID;
  tenant_name: string;
}

/** Conta criada por convite: dono + senha temporária e como foi entregue. */
export interface AccountInvite {
  tenant: Tenant;
  owner: User;
  temp_password: string;
  delivery: "email" | "whatsapp";
  delivery_status: "sent" | "logged" | "failed";
}

/** Nó da hierarquia que o Super Admin vê: escritório → Admin → funcionários + clientes. */
export interface TenantUsers {
  tenant: Tenant;
  admin: User | null;
  staff: User[];
  customers: PlatformCustomer[];
  staff_count: number;
  customer_count: number;
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

// ── Notificações ───────────────────────────────────────
export interface Notification {
  id: UUID;
  channel: string;
  recipient: string;
  client_id: UUID | null;
  message: string;
  status: string;
  created_at: string;
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
  location: string;
  /** Link de videoconferência (Google Meet, Zoom...). */
  meeting_url: string | null;
  /** E-mails dos convidados. */
  guests: string[];
  /** Valor em centavos (inteiro) para eventos de cobrança. */
  amount_cents: number | null;
  external_ref: string | null;
  /** Id do evento espelhado no Google Calendar (quando o Meet foi gerado via OAuth). */
  google_event_id: string | null;
  /** Nome do cliente (cobrança) ou fornecedor (conta a pagar), resolvido no list/get. */
  client_name: string | null;
  created_by_ai: boolean;
  created_at: string;
}

/** Estado da integração Google (Meet/Calendar) para a tela de Configurações. */
export interface GoogleCalendarStatus {
  /** App OAuth configurado na plataforma (mostra/esconde o botão "Conectar Google"). */
  configured: boolean;
  /** Este tenant já conectou uma conta Google. */
  connected: boolean;
  /** E-mail da conta Google conectada (null se não conectado). */
  email: string | null;
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

export interface OverdueCharge {
  charge_id: UUID;
  client_name: string;
  description: string;
  amount_cents: number;
  due_date: string;
}

export interface CockpitSummary {
  agenda: AgendaSummary;
  crm: CrmSummary;
  finance: FinanceSummary;
  overdue: OverdueCharge[];
}

// ── Carteira & Split ───────────────────────────────────
export type TransactionKind = "product" | "service" | "recurring";
export type PaymentMethod = "pix" | "card" | "boleto";
export type TransactionStatus = "pending" | "available" | "withdrawn" | "refunded";

export interface Transaction {
  id: UUID;
  tenant_id: UUID;
  kind: TransactionKind;
  method: PaymentMethod;
  description: string;
  gross_cents: number;
  platform_fee_cents: number;
  net_cents: number;
  status: TransactionStatus;
  client_id: UUID | null;
  external_ref: string | null;
  created_at: string;
}

export interface WalletSummary {
  available_cents: number;
  pending_cents: number;
  withdrawn_cents: number;
  gross_total_cents: number;
  fees_total_cents: number;
}

export interface PlatformEarningsSummary {
  gmv_cents: number;
  fees_cents: number;
  transaction_count: number;
  by_kind: Record<string, number>;
}

/** Taxas de split (% retido pela plataforma) — definidas pelo Super Admin. */
export interface SplitRates {
  product_pct: number;
  service_pct: number;
  recurring_pct: number;
}

// ── Contas a Receber ───────────────────────────────────
export type ChargeStatus = "open" | "paid" | "canceled";

export interface Charge {
  id: UUID;
  tenant_id: UUID;
  client_id: UUID | null;
  client_name: string | null;
  description: string;
  kind: TransactionKind;
  method: PaymentMethod;
  amount_cents: number;
  due_date: string;
  // Story 5.4: vínculo opcional ao contrato (eixo "projeto"); null = bucket "Empresa".
  contract_id: UUID | null;
  status: ChargeStatus;
  is_overdue: boolean;
  protested_at: string | null;
  recurrence: Recurrence;
  recurrence_group: string | null;
  payment_code: string;
  transaction_id: UUID | null;
  created_at: string;
}

export interface ChargesSummary {
  open_cents: number;
  overdue_cents: number;
  paid_cents: number;
  open_count: number;
  overdue_count: number;
}

// ── Contas a Pagar ─────────────────────────────────────
export type PayableStatus = "open" | "paid" | "canceled";
export type Recurrence = "none" | "weekly" | "monthly" | "yearly";

export interface Payable {
  id: UUID;
  tenant_id: UUID;
  description: string;
  category: string;
  supplier: string;
  amount_cents: number;
  due_date: string;
  // Story 5.4: vínculo opcional ao contrato (eixo "projeto"); null = bucket "Empresa".
  contract_id: UUID | null;
  status: PayableStatus;
  is_overdue: boolean;
  paid_at: string | null;
  recurrence: Recurrence;
  recurrence_count: number;
  recurrence_group: string | null;
  payment_code: string;
  attachment_url: string;
  created_at: string;
}

export interface PayablesSummary {
  open_cents: number;
  overdue_cents: number;
  week_cents: number;
  month_cents: number;
  paid_month_cents: number;
}

// Story 5.9: Fila de Pagamentos — visão nova sobre Payable (sem tabela nova). Baldes calculados
// na leitura: atrasados / hoje / próximos 7 dias / próximos 30 dias.
export interface PaymentQueueSummary {
  atrasados_count: number;
  atrasados_cents: number;
  hoje_count: number;
  hoje_cents: number;
  proximos_7_dias_count: number;
  proximos_7_dias_cents: number;
  proximos_30_dias_count: number;
  proximos_30_dias_cents: number;
}

export interface PaymentQueue {
  atrasados: Payable[];
  hoje: Payable[];
  proximos_7_dias: Payable[];
  proximos_30_dias: Payable[];
  summary: PaymentQueueSummary;
}

// ── Produtos, Cupons e Alunos ──────────────────────────
export type ProductKind = "physical" | "digital" | "membership";

export interface Product {
  id: UUID;
  tenant_id: UUID;
  name: string;
  kind: ProductKind;
  price_cents: number;
  description: string;
  active: boolean;
  stock: number | null;
  checkout_url: string;
  students: number;
  created_at: string;
}

export type DiscountType = "percent" | "fixed";

export interface Coupon {
  id: UUID;
  tenant_id: UUID;
  code: string;
  discount_type: DiscountType;
  discount_value: number;
  product_id: UUID | null;
  active: boolean;
  uses: number;
  max_uses: number | null;
  expires_at: string | null;
  created_at: string;
}

export interface Enrollment {
  id: UUID;
  tenant_id: UUID;
  product_id: UUID;
  product_name: string | null;
  name: string;
  email: string | null;
  status: string;
  amount_cents: number;
  created_at: string;
}

// ── Orçamentos / Construtor de proposta ────────────────
export type QuoteStatus = "draft" | "sent" | "approved" | "rejected";

export interface QuoteItem {
  description: string; // "Título exibido"
  subtitle?: string;
  quantity: number;
  unit_price_cents: number;
}

export interface GalleryImage {
  url: string;
  caption?: string;
}

export interface ScheduleStage {
  title: string;
  when?: string;
  description?: string;
}

export interface Quote {
  id: UUID;
  tenant_id: UUID;
  client_id: UUID | null;
  client_name: string;
  client_whatsapp: string;
  title: string;
  items: QuoteItem[];
  discount_cents: number;
  subtotal_cents: number;
  total_cents: number;
  status: QuoteStatus;
  valid_until: string | null;
  notes: string;
  payment_terms: string;
  has_password: boolean;
  show_gallery: boolean;
  gallery: GalleryImage[];
  show_schedule: boolean;
  schedule: ScheduleStage[];
  show_contract: boolean;
  contract_text: string;
  logo_url: string;
  primary_color: string;
  bg_color: string;
  text_color: string;
  accent_color: string;
  public_slug: string | null;
  charge_id: UUID | null;
  created_at: string;
}

// O que a página pública recebe (sem login)
export interface PublicProposal {
  title: string;
  client_name: string;
  items: QuoteItem[];
  subtotal_cents: number;
  discount_cents: number;
  total_cents: number;
  payment_terms: string;
  show_gallery: boolean;
  gallery: GalleryImage[];
  show_schedule: boolean;
  schedule: ScheduleStage[];
  show_contract: boolean;
  contract_text: string;
  logo_url: string;
  primary_color: string;
  bg_color: string;
  text_color: string;
  accent_color: string;
  status: QuoteStatus;
  valid_until: string | null;
}

export interface QuotesSummary {
  draft_count: number;
  sent_cents: number;
  approved_cents: number;
  approved_count: number;
}

// ── Contratos & Assinatura ─────────────────────────────
export type ContractStatus = "draft" | "sent" | "signed" | "cancelled";

export interface Clause {
  title: string;
  text: string;
}

export interface ContractTemplate {
  id: UUID;
  name: string;
  clauses: Clause[];
  created_at: string;
}

export interface Contract {
  id: UUID;
  tenant_id: UUID;
  client_id: UUID | null;
  client_name: string | null;
  quote_id: UUID | null;
  title: string;
  clauses: Clause[];
  status: ContractStatus;
  public_slug: string | null;
  // Story 5.4: custo fixo atribuído ao contrato (centavos), usado no break-even; null = não atribuído.
  fixed_costs_allocated_cents: number | null;
  signer_name: string;
  signer_document: string;
  signed_at: string | null;
  created_at: string;
}

export interface ContractsSummary {
  draft_count: number;
  sent_count: number;
  signed_count: number;
}

// ── Anexos (upload de arquivos) ────────────────────────
export interface Attachment {
  id: UUID;
  owner_type: string;
  owner_id: string;
  label: string;
  filename: string;
  content_type: string;
  size: number;
  created_at: string;
}

/**
 * Imagem intencionalmente PÚBLICA (logo/foto de proposta, carrossel, site) — retorno de
 * `POST /attachments/public-images`. `url` é o caminho da rota de leitura no backend
 * (`/public-images/{id}`); o helper `uploadPublicImage` prefixa o proxy `/api`.
 */
export interface PublicImage {
  id: UUID;
  url: string;
}

// ── Sites / Páginas ────────────────────────────────────
export type PageBlock = { type: string; [key: string]: unknown };

export interface PageStyle {
  primary_color: string;
  bg_color: string;
  text_color: string;
  accent_color: string;
  font: string;
  logo_url: string;
}

export interface PageSummary {
  id: UUID;
  title: string;
  model: string;
  status: string;
  public_slug: string | null;
  created_at: string;
}

export interface Page extends PageStyle {
  id: UUID;
  tenant_id: UUID;
  title: string;
  model: string;
  blocks: PageBlock[];
  status: string;
  public_slug: string | null;
  created_at: string;
}

export interface PublicPage extends PageStyle {
  title: string;
  blocks: PageBlock[];
}

// ── Configurações / Brand Kit ──────────────────────────
export interface TenantProfile {
  display_name: string;
  document: string;
  email: string;
  phone: string;
  address: string;
  website: string;
  about: string;
  logo_url: string;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  text_color: string;
  bg_color: string;
  font: string;
  timezone: string;
}

// ── Controle de Estoque ────────────────────────────────
export interface StockItem {
  id: UUID;
  tenant_id: UUID;
  name: string;
  sku: string;
  product_id: UUID | null;
  quantity: number;
  unit_cost_cents: number;
  min_quantity: number;
  unit: string;
  active: boolean;
  low: boolean;
  value_cents: number;
  created_at: string;
}

export interface StockMovement {
  id: UUID;
  item_id: UUID;
  delta: number;
  reason: string;
  note: string;
  created_at: string;
}

export interface StockSummary {
  item_count: number;
  total_value_cents: number;
  low_stock_count: number;
}

// ── Funil de Vendas ────────────────────────────────────
export interface FunnelComponentItem {
  key: string;
  label: string;
  description: string;
  shape: "page" | "node";
  action: string; // "" = só diagrama; senão executa ação (create_client, create_quote, ...)
}

export interface FunnelComponentCategory {
  category: string;
  label: string;
  color: string;
  items: FunnelComponentItem[];
}

export interface FunnelSummary {
  id: UUID;
  name: string;
  node_count: number;
  created_at: string;
}

export interface Funnel {
  id: UUID;
  tenant_id: UUID;
  name: string;
  // nós/arestas no formato do React Flow
  nodes: unknown[];
  edges: unknown[];
  created_at: string;
}

// Automação do funil: jornada (FunnelRun) de um contato.
export type FunnelRunStatus = "running" | "waiting" | "done" | "failed" | "cancelled";

export interface FunnelRunStep {
  node_id: string | null;
  key: string;
  action: string;
  status: string;
  message: string;
  at: string;
}

export interface FunnelRunSummary {
  id: UUID;
  funnel_id: UUID;
  client_id: UUID | null;
  client_name: string | null;
  status: FunnelRunStatus;
  resume_at: string | null;
  step_count: number;
  created_at: string;
}

export interface FunnelRun {
  id: UUID;
  tenant_id: UUID;
  funnel_id: UUID;
  client_id: UUID | null;
  client_name: string | null;
  status: FunnelRunStatus;
  current_node_id: string | null;
  resume_at: string | null;
  steps: FunnelRunStep[];
  error: string;
  created_at: string;
  updated_at: string;
}

export interface PublicContract {
  title: string;
  company_name: string;
  clauses: Clause[];
  status: ContractStatus;
  signer_name: string;
  signed_at: string | null;
}

// ── Marketing / Carrossel ──────────────────────────────
export type SlideKind = "cover" | "editorial" | "accent" | "cta";

export interface Slide {
  kind: SlideKind;
  heading: string;
  body: string;
  secondary: string;
  highlight: string;
  photo_url: string;
  photo_position: "top" | "mid" | "base";
}

export interface CarouselTemplate {
  key: string;
  label: string;
  primary_color: string;
  bg_color: string;
  text_color: string;
  accent_color: string;
  font: string;
}

export interface Carousel {
  id: UUID;
  tenant_id: UUID;
  topic: string;
  platform: string;
  slides: Slide[];
  status: string;
  handle: string;
  caption: string;
  hashtags: string;
  template: string;
  primary_color: string;
  bg_color: string;
  text_color: string;
  accent_color: string;
  font: string;
  created_at: string;
}

// ── Jurídico (Assistente Jurídico) ──────────────────────────────────────────
export interface LegalSkillSummary {
  skill: string;
  label: string;
  category: string;
  description: string;
  output_type: string;
}

export interface LegalWizardField {
  key: string;
  label: string;
  type: "text" | "textarea" | "select" | "upload";
  placeholder?: string;
  required?: boolean;
  options?: string[];
  accept?: string;
  multiple?: boolean;
}

export interface LegalWizardStep {
  id: string;
  title: string;
  description?: string;
  fields: LegalWizardField[];
}

export interface LegalWizardConfig {
  skill: string;
  label: string;
  category: string;
  description: string;
  output_type: string;
  steps: LegalWizardStep[];
}

export interface LegalDocumentSummary {
  id: UUID;
  skill: string;
  category: string;
  title: string;
  client_id: UUID | null;
  client_name: string | null;
  status: string;
  created_at: string;
}

export interface LegalDocument {
  id: UUID;
  tenant_id: UUID;
  skill: string;
  category: string;
  title: string;
  client_id: UUID | null;
  client_name: string | null;
  content: string;
  metadata_raw: string;
  answers: Record<string, unknown>;
  input_tokens: number;
  output_tokens: number;
  status: string;
  created_at: string;
}
