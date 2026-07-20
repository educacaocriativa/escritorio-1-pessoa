import {
  Activity,
  CalendarDays,
  CreditCard,
  FileSignature,
  FileText,
  Globe,
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
export const navSections: NavSection[] = [
  {
    // Núcleo: o que se abre todo dia.
    items: [
      { label: "Dashboard", to: "/", icon: LayoutDashboard, ready: true },
      { label: "Agenda", to: "/agenda", icon: CalendarDays, ready: true },
      { label: "CRM & Kanban", to: "/crm", icon: Users, ready: true },
      { label: "Conversas", to: "/conversas", icon: MessageCircle, ready: true },
    ],
  },
  {
    // Financeiro operacional: registrar/cobrar/pagar — uso diário. "Financeiro" (Carteira)
    // primeiro porque é onde entra o lançamento de recebimento do dia a dia ("Registrar venda").
    title: "Financeiro",
    items: [
      { label: "Financeiro", to: "/financeiro", icon: Wallet, ready: true, exact: true },
      { label: "Cobranças", to: "/cobrancas", icon: Receipt, ready: true },
      { label: "Contas a Pagar", to: "/pagar", icon: CreditCard, ready: true },
      { label: "Fila de pagamentos", to: "/financeiro/fila-pagamentos", icon: ListChecks, ready: true },
    ],
  },
  {
    // Relatórios (DRE/projeção/diagnóstico/investimentos) + cadastros de classificação (plano de
    // contas/centro de custo) — tudo consultado/editado periodicamente, não todo dia. O nome cobre
    // os dois perfis (análise E configuração) já que "Relatórios" sozinho não descrevia bem os
    // cadastros.
    title: "Análise & Configuração Financeira",
    items: [
      { label: "DRE", to: "/financeiro/dre", icon: PieChart, ready: true },
      { label: "Projeção de caixa", to: "/financeiro/projecao-caixa", icon: LineChart, ready: true },
      { label: "Diagnóstico", to: "/financeiro/diagnostico", icon: Activity, ready: true },
      { label: "Investimentos", to: "/financeiro/investimentos", icon: TrendingUp, ready: true },
      { label: "Plano de contas", to: "/financeiro/plano-contas", icon: ListTree, ready: true },
      { label: "Centros de custo", to: "/financeiro/centros-custo", icon: Layers, ready: true },
    ],
  },
  {
    title: "Ferramentas de Produtividade",
    items: [
      { label: "Orçamentos", to: "/orcamentos", icon: FileText, ready: true },
      { label: "Contratos", to: "/contratos", icon: FileSignature, ready: true },
      { label: "Produtos", to: "/produtos", icon: ShoppingBag, ready: true },
      { label: "Estoque", to: "/estoque", icon: Package, ready: true },
      { label: "Marketing", to: "/marketing", icon: Megaphone, ready: true },
      { label: "Funil de Vendas", to: "/funis", icon: Workflow, ready: true },
      { label: "Sites", to: "/sites", icon: Globe, ready: true },
      { label: "Jurídico", to: "/juridico", icon: Scale, ready: true },
    ],
  },
  {
    // Raramente aberto — fica isolado no fim, longe do que se usa todo dia.
    items: [{ label: "Configurações", to: "/config", icon: Settings, ready: true }],
  },
];
