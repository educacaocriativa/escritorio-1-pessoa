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
  /**
   * Fuso IANA do tenant (ex.: "America/Sao_Paulo"). Vem junto com a sessão porque TODA
   * formatação de data/hora da UI depende dele — ver `lib/datetime.ts`. Opcional no tipo
   * para tolerar uma sessão gravada no localStorage ANTES deste campo existir.
   */
  timezone?: string;
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
  delivery_status: "sent" | "queued" | "logged" | "failed" | "unconfigured";
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
  delivery_status: "sent" | "queued" | "logged" | "failed" | "unconfigured";
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
// `detail` é string nos erros de negócio (HTTPException), mas o FastAPI devolve uma LISTA de
// objetos {loc, msg, type} em erros de validação Pydantic (422) — ambos os formatos são reais.
// O TERCEIRO formato é o erro ACIONÁVEL (Story 8.12): um objeto `{acao, mensagem}`, em que `acao`
// é contrato (a tela reconhece a situação pela ação, nunca por substring da mensagem).
export interface ApiActionableError {
  acao: string;
  mensagem: string;
}
export interface ApiError {
  detail:
    | string
    | { loc: (string | number)[]; msg: string; type: string }[]
    | ApiActionableError;
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
  | "lembrete"
  /** Espelhado a partir do Google Calendar (sync Google → e1p) — sem tipo de negócio do e1p. */
  | "google";

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
  /** De quem é este compromisso (aponta para `clients.id`). `null` para bloqueio de horário,
   *  prazo interno e conta a pagar — nunca têm contato (espelha `EventOut.client_id` em
   *  `agenda/schemas.py`). Gap deixado pela Task 2/3 desta onda: o backend já devolvia o campo,
   *  mas o tipo compartilhado não o declarava — a ficha 360° (Task 6) é a primeira consumidora. */
  client_id: string | null;
  /** Nome resolvido para exibição no card, no list/get — não da coluna do evento. Desde a
   *  Task 3 (Onda 2), o join direto por `client_id` resolve o NOME DO CONTATO para QUALQUER
   *  evento vinculado (reunião, atendimento, cobrança...), não só cobrança/conta a pagar; a
   *  metade sem `client_id` — conta a pagar — continua resolvendo o fornecedor por
   *  `external_ref` (ver `agenda/router.py::_events_out`). `chipLabel` (AgendaPage.tsx) usa
   *  isto como ATALHO só para os kinds financeiros, justamente porque o título deles já é
   *  auto-gerado ("A receber: Fulano") — não confundir a restrição de exibição com a origem
   *  do dado, que é ampla. */
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
  /** Desde quando o card está nesta etapa — a ordem da fila no Kanban. ISO 8601, nunca nulo. */
  stage_entered_at: string;
  created_at: string;
}

export interface ClientTimelineEntry {
  id: string;
  kind:
    | "lead_created" | "lead_return" | "stage_move" | "reopened" | "note" | "funnel"
    | "quote" | "charge" | "payment" | "agenda";
  title: string;
  body: string;
  actor: string;
  is_ai: boolean;
  /** O instante do fato: `created_at` do evento, ou `paid_at` da cobrança. */
  at: string;
}

export interface ClientTimelineOut {
  entries: ClientTimelineEntry[];
  /** `true` quando alguma fonte bateu no teto de 100 — a tela avisa. */
  truncated: boolean;
}

/** `Client` do board, com os sinais que só o board calcula. */
export interface BoardClient extends Client {
  last_interaction_at: string | null;
  /** Tem mensagem do contato esperando resposta. */
  unread: boolean;
  /** Próximo compromisso do contato na Agenda — `null` nos dois junto significa "sem próximo passo". */
  next_event_at: string | null;
  next_event_title: string | null;
  /** `next_event_at` é dia inteiro ou tem horário? Determina COMO formatar: dia inteiro usa
   *  `formatDay` (lê a data da string, sem fuso — `receivables` ancora à meia-noite UTC, não
   *  na do fuso do tenant); com horário usa `formatDateShort` (converte o instante para o fuso).
   *  Mesma distinção que `BlocoDaAgenda` já faz com `AgendaEvent.all_day`. */
  next_event_all_day: boolean;
}

export interface BoardColumn {
  stage: PipelineStage;
  clients: BoardClient[];
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
  /**
   * Onda 3 — o saldo no BANCO (plano 3), ao lado do faturamento (plano 1).
   *
   * `null` = nenhuma conta cadastrada, e **não zero**: zero afirmaria "não há nada no banco",
   * falso e indistinguível de um saldo genuinamente zerado.
   *
   * ⚠️ Os dois nunca são somados num único número (Regra dos Planos §1.3c). E `net_revenue_cents`
   * NÃO tem irmão `_origem` porque é faturamento, não saldo — a regra é sobre saldo.
   */
  saldo_em_conta_cents: number | null;
  /** `plataforma` | `banco` | `misto` | `indisponivel` — o plano de onde o saldo acima vem. */
  saldo_em_conta_origem: string;
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
  // Story 5.10: vínculo opcional ao plano de contas; null = sem categoria estruturada.
  chart_account_id: UUID | null;
  // Story 5.10: vínculo opcional ao centro de custo (2ª dimensão); null = "Não atribuído".
  cost_center_id: UUID | null;
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
// ⚠️ **[Story 8.15] `scheduled` — o Pix que o cliente agendou e ainda não caiu.**
// Nasce **só** pelo caminho fora do trilho (`POST /charges/{id}/settle-externally` com
// `received_on` futuro); o estado é **derivado da data** no backend, nunca escolhido pelo cliente.
// O caminho do gateway (webhook) continua sem estado agendado — a assimetria é a informação.
export type ChargeStatus = "open" | "scheduled" | "paid" | "canceled";

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
  // Story 5.1: vínculo opcional ao plano de contas; null = sem categoria estruturada.
  chart_account_id: UUID | null;
  // Story 5.4: vínculo opcional ao contrato (eixo "projeto"); null = bucket "Empresa".
  contract_id: UUID | null;
  // Story 5.5: vínculo opcional ao centro de custo (2ª dimensão); null = "Não atribuído".
  cost_center_id: UUID | null;
  status: ChargeStatus;
  is_overdue: boolean;
  protested_at: string | null;
  recurrence: Recurrence;
  recurrence_group: string | null;
  payment_code: string;
  // ── A INVARIANTE DO TRILHO, pelos DOIS ponteiros (Story 8.15) ─────────────────────────────
  // Numa cobrança liquidada, **exatamente um** deles é não-nulo:
  //   `transaction_id`  → **trilho**: caiu na Carteira da e1p, com split 40/30/20;
  //   `bank_account_id` → **fora do trilho**: caiu direto na conta bancária do dono, sem split.
  // ⚠️ **Não existe campo de rota.** Ela é DERIVADA (`features/cobrancas/rota.ts`); um rótulo
  // persistido pode divergir dos ponteiros e vira a terceira fonte de verdade.
  transaction_id: UUID | null;
  bank_account_id: UUID | null;
  bank_transaction_id: UUID | null;
  // Regime de CAIXA (`paid_at`) × regime de COMPETÊNCIA (`competence_date`) — nunca se invertem.
  competence_date: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface ChargesSummary {
  open_cents: number;
  overdue_cents: number;
  paid_cents: number;
  open_count: number;
  overdue_count: number;
  // [Story 8.15] Recebido fora do trilho com data FUTURA — fora de `open_cents` e de `paid_cents`.
  scheduled_cents: number;
}

// ── Contas a Pagar ─────────────────────────────────────
// ⚠️ **[Story 8.14] `scheduled` — débito AGENDADO no app do banco, com data futura.**
// O estado é **derivado da data** no backend (`paid_on > hoje ⇒ scheduled`), nunca escolhido pelo
// cliente: nenhum payload de entrada tem campo `status`. Uma agendada não é "a pagar" (já foi
// resolvida) nem "paga" (o dinheiro não saiu) — e é justamente por não caber em nenhum dos dois
// que ela precisou de valor próprio. Ver `apps/api/app/modules/payables/models.py`.
export type PayableStatus = "open" | "scheduled" | "paid" | "canceled";
export type Recurrence = "none" | "weekly" | "monthly" | "yearly";

export interface Payable {
  id: UUID;
  tenant_id: UUID;
  description: string;
  category: string;
  supplier: string;
  amount_cents: number;
  due_date: string;
  // Story 5.1: vínculo opcional ao plano de contas; null = sem categoria estruturada.
  chart_account_id: UUID | null;
  // Story 5.4: vínculo opcional ao contrato (eixo "projeto"); null = bucket "Empresa".
  contract_id: UUID | null;
  // Story 5.5: vínculo opcional ao centro de custo (2ª dimensão); null = "Não atribuído".
  cost_center_id: UUID | null;
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

/** Uma página de `GET /payables/bills` — `items` mais o total REAL do recorte.
 *
 * O `total` ignora `limit`/`offset` de propósito: é ele que permite à tela dizer
 * "mostrando 50 de 213". Sem isso o truncamento volta a ser silencioso.
 */
export interface PayablesPage {
  items: Payable[];
  total: number;
}

export interface PayablesSummary {
  open_cents: number;
  overdue_cents: number;
  week_cents: number;
  month_cents: number;
  paid_month_cents: number;
  // Story 8.14 — Σ das contas agendadas. **Fora** de `open_cents` e de `paid_month_cents`; os
  // cinco campos acima não mudaram de definição (`month_cents` continua contando a agendada por
  // vencimento, de propósito). Opcional no TS para que o front não quebre contra um backend antigo.
  scheduled_cents?: number;
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
  // Story 8.14 — o quinto balde. NÃO é balde de vencimento: é o que já tem dia marcado para sair.
  agendadas_count?: number;
  agendadas_cents?: number;
}

export interface PaymentQueue {
  atrasados: Payable[];
  hoje: Payable[];
  proximos_7_dias: Payable[];
  proximos_30_dias: Payable[];
  // Story 8.14 — ordenadas pela DATA DO DÉBITO (`paid_at`), não por `due_date`, e sem corte de 30
  // dias: um compromisso assumido para daqui a 60 dias continua sendo um compromisso.
  agendadas?: Payable[];
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
  /** Funil de Vendas em que todo lead novo (source=landing/api) é inscrito automaticamente.
   * null = auto-enroll desligado (comportamento até o dono configurar). */
  default_entry_funnel_id: UUID | null;
  /** WhatsApp Cloud API (Meta) — POR TENANT. true só quando token+phone_id+waba_id
   * estiverem TODOS configurados (ver `whatsapp_configured` no backend). */
  whatsapp_configured: boolean;
  /** "meta" | "evolution" | null — qual transporte está ativo. Só muda via
   * POST /whatsapp-session/connect+confirm (QR) ou credenciais Meta completas. */
  whatsapp_provider: "meta" | "evolution" | null;
  whatsapp_phone_id: string;
  whatsapp_waba_id: string;
  /** Só-leitura: token de verificação do webhook (auto-gerado pelo backend), usado para
   * configurar o callback no painel da Meta. */
  whatsapp_verify_token: string;
  /** Só-escrita: nunca vem preenchido no GET (o token nunca é devolvido em claro).
   * Setar antes do PATCH para configurar/trocar; "" limpa a credencial. */
  whatsapp_token?: string;
  /** Só-escrita: App Secret do App na Meta, usado para validar a assinatura do webhook.
   * Nunca vem preenchido no GET. Setar antes do PATCH para configurar/trocar. */
  whatsapp_app_secret?: string;
  /** Vínculo propósito→template_id para os fluxos FIXOS do sistema (lembrete de cobrança,
   * envio de contrato/orçamento, convite de staff, aviso de card movido) — diferente do nó
   * livre do Funil de Vendas, aqui o tenant vincula UM template aprovado por propósito.
   * Chave ausente/"" = esse fluxo ainda usa texto livre. Ver WHATSAPP_PURPOSES. */
  whatsapp_template_bindings: Record<string, string>;
}

/** Espelha `whatsapp_templates.models.PURPOSE_VARIABLE_SPECS` do backend — rótulo de cada
 * variável, na ordem em que o sistema preenche {{1}}, {{2}}, ... para aquele propósito. */
export const WHATSAPP_PURPOSES: { key: string; label: string; variables: string[] }[] = [
  {
    key: "charge_reminder", label: "Lembrete de cobrança (Cobrar com IA)",
    variables: ["Nome do cliente", "Frase de cobrança (a IA sugere)", "Valor", "Vencimento"],
  },
  {
    key: "contract_send", label: "Envio de contrato",
    variables: ["Nome do cliente", "Título do contrato", "Link de assinatura"],
  },
  {
    key: "quote_send", label: "Envio de orçamento/proposta",
    variables: ["Nome do cliente", "Título do orçamento", "Valor", "Link da proposta"],
  },
  {
    key: "staff_invite", label: "Convite de funcionário (senha temporária)",
    variables: ["Nome", "Empresa", "E-mail de login", "Senha temporária"],
  },
  {
    key: "client_moved", label: "Aviso interno: cliente mudou de etapa no CRM",
    variables: ["Nome do cliente", "Nome da nova etapa"],
  },
];

// ── WhatsApp Cloud API (Meta): templates de mensagem por tenant ────
// A Meta exige template pré-aprovado para toda mensagem business-initiated (fora da janela
// de 24h de atendimento) — ver app/core/whatsapp.py e app/modules/whatsapp_templates.
export type WhatsappTemplateStatus = "PENDING" | "APPROVED" | "REJECTED" | "PAUSED" | "DISABLED";
export type WhatsappTemplateCategory = "MARKETING" | "UTILITY" | "AUTHENTICATION";

export interface WhatsappTemplate {
  id: UUID;
  name: string;
  language: string;
  category_requested: WhatsappTemplateCategory;
  /** Categoria que a Meta de fato aprovou — pode divergir da solicitada. null até responder. */
  category_approved: WhatsappTemplateCategory | null;
  status: WhatsappTemplateStatus;
  rejected_reason: string | null;
  meta_template_id: string | null;
  /** Corpo com variáveis posicionais no formato Meta: {{1}}, {{2}}, ... */
  body_text: string;
  variable_count: number;
  variable_examples: string[];
  created_at: string;
  updated_at: string;
}

export interface WhatsappTemplateCreate {
  name: string;
  language: string;
  category: WhatsappTemplateCategory;
  body_text: string;
  variable_examples: string[];
}

// ── Inbox de WhatsApp (conversa de verdade com clientes) ────
/**
 * Uma CONVERSA (`whatsapp_chats`), não um cliente — é o que permite grupo existir na caixa de
 * entrada. `client_id` é vínculo opcional com o CRM: `null` em grupo (que por decisão de
 * produto nunca vira contato) e em conversa direta cujo telefone o WhatsApp não revelou.
 */
export interface ConversationSummary {
  chat_id: UUID;
  kind: "direct" | "group";
  title: string;
  phone: string | null;
  client_id: UUID | null;
  last_message_at: string | null;
  last_message_preview: string;
  unread: boolean;
}

export interface TimelineEntry {
  source: "conversation" | "automated";
  direction: "in" | "out";
  kind: "text" | "image" | "audio" | "document" | "video";
  text_body: string;
  media_attachment_id: string | null;
  purpose_label: string | null;
  /** Quem falou, em grupo. `null` em conversa direta e em mensagem nossa. */
  sender_name: string | null;
  created_at: string;
}

export interface WhatsappMessageOut {
  id: UUID;
  direction: "in" | "out";
  kind: "text" | "image" | "audio" | "document" | "video";
  text_body: string;
  status: "sent" | "logged" | "failed";
  created_at: string;
}

/** Credencial do Atalho do iOS. O token cru só existe na resposta da criação. */
export interface DeviceToken {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

// ── Integrações (captura de lead de sites externos) ────
export interface IntegrationKey {
  id: UUID;
  label: string;
  /** 8 primeiros caracteres da chave, só para identificar na lista. */
  key_prefix: string;
  revoked_at: string | null;
  created_at: string;
}

/** Retorno da criação: única vez em que a chave crua fica visível. */
export interface IntegrationKeyCreated extends IntegrationKey {
  raw_key: string;
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

// ── Vima: briefing do dia (Onda 4) ───────────────────────────────────────────

/**
 * Uma linha do payload determinístico. `texto` é a mesma informação que a narração reescreveu —
 * está aqui para que um cliente possa AGIR sobre um item sem fazer parsing de prosa.
 */
export interface BriefingLinha {
  secao: "PENDENTE" | "ACONTECEU" | "NÚMEROS";
  module: string;
  texto: string;
  /**
   * O `kind` da ausência que gerou a linha — é o que permite colar a pergunta de calibração do
   * DNA na linha que a motivou. Vazio em linhas que não são ausência e em briefings gravados
   * ANTES do V2, cujo payload não tinha o campo.
   */
  kind: string;
}

export interface Briefing {
  id: UUID;
  /** Data de CALENDÁRIO (YYYY-MM-DD) no fuso do tenant — não é instante, não converta fuso. */
  reference_date: string;
  texto: string;
  /** Se a narração veio da IA ou do template. Rotular como IA um texto de template seria falso. */
  por_ia: boolean;
  /** `true` = nada ACONTECEU na janela. Pendência e tendência podem existir mesmo assim. */
  vazio: boolean;
  excedente: number;
  linhas: BriefingLinha[];
  read_at: string | null;
  created_at: string;
}

export interface DnaOpcao {
  rotulo: string;
  valor: string | number | null;
}

/**
 * Uma pergunta do DNA da Empresa. Viaja INTEIRA do backend — o front não tem cópia do catálogo,
 * porque duas cópias divergem no primeiro ajuste de texto e a errada é sempre a que o dono lê.
 */
export interface DnaPergunta {
  key: string;
  /**
   * `calibracao` muda o briefing de amanhã; `retrato` é guardado para o V4. A tela DIZ isso —
   * prometer efeito imediato ao Retrato seria o erro que as duas classes existem para impedir.
   */
  classe: "calibracao" | "retrato";
  eixo: "oferta" | "cliente" | "ritmo" | "dinheiro" | "limites";
  texto: string;
  formato: "escolha" | "escolha_multipla" | "texto";
  opcoes: DnaOpcao[];
}

/**
 * Preferência de briefing DO USUÁRIO (mora em `users`, não no perfil da empresa) — por isso
 * editável sem o módulo `settings`.
 */
export interface BriefingPreferences {
  briefing_whatsapp_enabled: boolean;
  /** "HH:MM" no relógio de parede do dono. */
  briefing_hour: string;
  /** O tenant consegue entregar por WhatsApp hoje? Meta sem template aprovado → false. */
  briefing_whatsapp_disponivel: boolean;
  /** Texto pronto para a tela quando indisponível; `null` quando disponível. */
  briefing_whatsapp_indisponivel_motivo: string | null;
}

// ── Busca global ──────────────────────────────────────────────────────────────
//
// Oito tipos, e o critério de quem entra é ter endereço que saiba RECEBER uma busca — não é "ter
// tela de detalhe". Cobranças e produtos seguem de fora porque nenhuma das duas hidrata o próprio
// recorte a partir da URL: o clique cairia numa lista que ignora o filtro, que a spec
// `2026-08-18-busca-global-design.md` §2 (+ errata de 2026-08-19) considera pior que não oferecer
// o resultado. Contas a pagar entrou na issue #146: o PR #143 (issue #138) fez `/pagar` ler `q`,
// `status`, `de`/`ate`, `centro` e `categoria` do endereço, e o bloqueio dela deixou de existir.
//
// A ORDEM desta união é decorativa; quem manda na ordem dos grupos é o registro do backend
// (`app/modules/search/registro.py`).

export type SearchType =
  | "client"
  | "conversation"
  | "contract"
  | "quote"
  | "payable"
  | "legal_document"
  | "page"
  | "funnel";

export interface SearchItem {
  id: UUID;
  title: string;
  subtitle: string;
  /** Caminho pronto para o router. Quem decide o destino é o backend, no registro. */
  route: string;
  /** Só em `depth=deep`: na camada rasa não há corpo de onde extrair trecho. */
  snippet: string | null;
}

export interface SearchGroup {
  type: SearchType;
  has_more: boolean;
  /**
   * Só em `depth=deep`. Na camada rasa a contagem exata custaria oito `count()` por tecla — e
   * `has_more` não tem como mentir sobre um número que não anuncia.
   */
  total: number | null;
  items: SearchItem[];
}

export interface SearchResponse {
  groups: SearchGroup[];
}
