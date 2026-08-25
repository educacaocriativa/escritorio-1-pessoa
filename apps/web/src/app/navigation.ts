import {
  Activity,
  CalendarDays,
  CreditCard,
  FileSignature,
  FileText,
  Globe,
  Landmark,
  Layers,
  LayoutDashboard,
  LineChart,
  ListChecks,
  ListTree,
  type LucideIcon,
  Megaphone,
  MessageCircle,
  Package,
  PieChart,
  Receipt,
  Scale,
  Settings,
  ShoppingBag,
  TrendingUp,
  Trophy,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";

export interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  /** false enquanto o módulo ainda não foi construído (mostra como "em breve"). */
  ready?: boolean;
  /** Casamento EXATO da rota ativa (evita acender junto com sub-rotas, ex.: /financeiro x
   * /financeiro/plano-contas). Sem isto, o NavLink usa match por prefixo. */
  exact?: boolean;
  /**
   * O mesmo nome que `require_module` usa no backend (`app/core/tenancy.py`) para a rota que
   * este item abre. Um sub-usuário sem este módulo em `allowed_modules` não vê o item — antes
   * disto a sidebar mostrava tudo a todo mundo, e quem clicasse num módulo sem permissão via a
   * tela travar em "Carregando..." (a API 403 e nenhuma página tratava isso). Ausente = item sem
   * módulo próprio de negócio (não deve ser escondido por RBAC).
   */
  module?: string;
}

export interface NavSection {
  title?: string;
  items: NavItem[];
}

/**
 * Seções por ORDEM DE USO (mais usado no dia a dia primeiro), no formato do design "Portal".
 * Cada grupo é separado por um divisor tracejado (ver AppShell.tsx) — evita a lista única
 * misturando navegação diária com telas de configuração/relatório raramente abertas.
 */
// ── FORA DO TESTE DE MUTAÇÃO, e a medição que decidiu isso (issue #191) ──────────────────────
//
// `navigation.ts` era o PIOR score da árvore — 55,65%, 51 dos 269 sobreviventes da primeira
// corrida completa (run 32478357936). Ordenado por contagem, seria o alvo nº1. Medido por TIPO,
// não é dívida nenhuma.
//
// Os 115 mutantes deste arquivo são, sem exceção: 53 `StringLiteral`, 26 `BooleanLiteral`,
// 30 `ObjectLiteral` e 6 `ArrayDeclaration`. **Zero** `ConditionalExpression`, `LogicalOperator`,
// `EqualityOperator` ou `ArithmeticOperator` — e não é coincidência: este módulo não exporta
// função nenhuma, só a tabela abaixo. Não há expressão para mutar porque não há lógica. A
// pergunta que a mutação faz ("o teste prende a lógica?") não tem sujeito aqui.
//
// Matar os 51 sobreviventes significaria afirmar cada `label` e cada `ready` num teste — uma
// SEGUNDA CÓPIA desta tabela, que dobra o custo de mexer no menu e não pega nada que um humano
// não veja na tela em um segundo. Seria dívida nova, não dívida paga.
//
// E há a prova de que o número era um artefato da régua, não do código: a corrida exclui
// `.test.tsx` de propósito (ver `vitest.mutation.config.ts`), e `ClientDetailPage.test.tsx:880`
// clica em `findByRole("button", { name: /CRM & Kanban/ })` — esse teste MATA um dos 26 mutantes
// de string. Os 51 mediam a ausência de teste de componente na corrida, não a qualidade do
// `navigation.test.ts`.
//
// **Por que aqui e não em `stryker.config.mjs`.** A regra de descoberta de lá ("todo `.ts` com um
// irmão `.test.ts`") é boa e não deve ganhar a primeira exceção por nome de arquivo — a segunda
// viria fácil. O `disable` fica no lugar onde a próxima pessoa lê o motivo, e é BRACKETADO: se um
// dia alguém exportar uma função daqui, ela nasce fora do bloco e entra na corrida sozinha.
//
// O `navigation.test.ts` continua rodando e continua guardando o que importa — as quatro travas
// da Story 8.7 e as 24 rotas pré-existentes. Isto não afrouxa teste nenhum; só para de pontuar
// uma tabela de dados como se fosse lógica.
//
// Impacto medido no score GLOBAL: 83,52% → 85,46% (1.480/1.772 → 1.416/1.657) só por sair.
//
// Stryker disable all : tabela de dados declarativa, sem lógica — ver o bloco acima (issue #191)
export const navSections: NavSection[] = [
  {
    // Núcleo: o que se abre todo dia.
    items: [
      { label: "Dashboard", to: "/", icon: LayoutDashboard, ready: true, module: "cockpit" },
      { label: "Agenda", to: "/agenda", icon: CalendarDays, ready: true, module: "agenda" },
      { label: "CRM & Kanban", to: "/crm", icon: Users, ready: true, module: "crm" },
      // `whatsapp_inbox` usa o mesmo guard de `crm` no backend (mesma dona dos dados).
      { label: "Conversas", to: "/conversas", icon: MessageCircle, ready: true, module: "crm" },
    ],
  },
  {
    // Financeiro operacional: registrar/cobrar/pagar — uso diário. "Financeiro" (Carteira)
    // primeiro porque é onde entra o lançamento de recebimento do dia a dia ("Registrar venda").
    title: "Financeiro",
    items: [
      { label: "Financeiro", to: "/financeiro", icon: Wallet, ready: true, exact: true, module: "wallet" },
      // Story 8.7 — ao lado da Carteira de propósito: o rótulo é "onde está o meu dinheiro", e a
      // vizinhança reforça a distinção dos planos ("na plataforma" × conta bancária). Fica FORA
      // de "Análise & Configuração Financeira" para não ser lido como relatório contábil.
      // ⚠️ A conferência (`/financeiro/conferencia`) NÃO entra aqui, e não é esquecimento: um item
      // "Conciliação bancária" comunicaria "software de contabilidade" a todo usuário — inclusive
      // a quem nunca abre a tela — e viraria a conferência numa obrigação periódica. Ela é resposta
      // a um sinal. Coberto por teste em `navigation.test.ts`.
      { label: "Contas & Saldos", to: "/financeiro/contas", icon: Landmark, ready: true, module: "bank" },
      { label: "Cobranças", to: "/cobrancas", icon: Receipt, ready: true, module: "receivables" },
      { label: "Contas a Pagar", to: "/pagar", icon: CreditCard, ready: true, module: "payables" },
      { label: "Fila de pagamentos", to: "/financeiro/fila-pagamentos", icon: ListChecks, ready: true, module: "payables" },
    ],
  },
  {
    // Relatórios (DRE/projeção/diagnóstico/investimentos) + cadastros de classificação (plano de
    // contas/centro de custo) — tudo consultado/editado periodicamente, não todo dia. O nome cobre
    // os dois perfis (análise E configuração) já que "Relatórios" sozinho não descrevia bem os
    // cadastros.
    title: "Análise & Configuração Financeira",
    items: [
      { label: "DRE", to: "/financeiro/dre", icon: PieChart, ready: true, module: "financial_intelligence" },
      { label: "Lucratividade", to: "/financeiro/lucratividade", icon: Trophy, ready: true, module: "financial_intelligence" },
      { label: "Projeção de caixa", to: "/financeiro/projecao-caixa", icon: LineChart, ready: true, module: "financial_intelligence" },
      { label: "Diagnóstico", to: "/financeiro/diagnostico", icon: Activity, ready: true, module: "financial_intelligence" },
      { label: "Investimentos", to: "/financeiro/investimentos", icon: TrendingUp, ready: true, module: "investments" },
      { label: "Plano de contas", to: "/financeiro/plano-contas", icon: ListTree, ready: true, module: "chart_of_accounts" },
      { label: "Centros de custo", to: "/financeiro/centros-custo", icon: Layers, ready: true, module: "cost_centers" },
    ],
  },
  {
    title: "Ferramentas de Produtividade",
    items: [
      { label: "Orçamentos", to: "/orcamentos", icon: FileText, ready: true, module: "quotes" },
      { label: "Contratos", to: "/contratos", icon: FileSignature, ready: true, module: "contracts" },
      { label: "Produtos", to: "/produtos", icon: ShoppingBag, ready: true, module: "products" },
      { label: "Estoque", to: "/estoque", icon: Package, ready: true, module: "stock" },
      { label: "Marketing", to: "/marketing", icon: Megaphone, ready: true, module: "marketing" },
      { label: "Funil de Vendas", to: "/funis", icon: Workflow, ready: true, module: "funnels" },
      { label: "Sites", to: "/sites", icon: Globe, ready: true, module: "pages" },
      { label: "Jurídico", to: "/juridico", icon: Scale, ready: true, module: "juridico" },
    ],
  },
  {
    // Raramente aberto — fica isolado no fim, longe do que se usa todo dia.
    items: [{ label: "Configurações", to: "/config", icon: Settings, ready: true, module: "settings" }],
  },
];

// Stryker restore all

/**
 * `navSections` recortado para o que ESTE usuário pode abrir (`hasModule`). Item sem `module`
 * nunca é escondido (não é módulo de negócio próprio). Seção que fica sem item nenhum some
 * inteira — senão restaria só o título/divisor, uma seção vazia na tela.
 *
 * `navSections` em si permanece a lista COMPLETA e estática (é o que `navigation.test.ts` já
 * afirma) — o recorte por permissão é uma função pura à parte, para não misturar "o menu que
 * existe" com "o menu que este usuário vê".
 *
 * FORA do bloco `Stryker disable` acima de propósito (issue #191): esta função TEM lógica
 * (`ConditionalExpression`/`LogicalOperator`) — é exatamente o caso que o comentário daquele
 * bloco previu ("função nova nasce fora dele e volta a ser medida").
 */
export function visibleNavSections(
  hasModule: (module: string) => boolean,
): NavSection[] {
  return navSections
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => !item.module || hasModule(item.module)),
    }))
    .filter((section) => section.items.length > 0);
}
