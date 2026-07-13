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

/** Dois grupos, no formato do design "Portal": principal + "Ferramentas de Produtividade". */
export const navSections: NavSection[] = [
  {
    items: [
      { label: "Dashboard", to: "/", icon: LayoutDashboard, ready: true },
      { label: "Agenda", to: "/agenda", icon: CalendarDays, ready: true },
      { label: "CRM & Kanban", to: "/crm", icon: Users, ready: true },
      { label: "Financeiro", to: "/financeiro", icon: Wallet, ready: true, exact: true },
      { label: "Plano de contas", to: "/financeiro/plano-contas", icon: ListTree, ready: true },
      { label: "DRE", to: "/financeiro/dre", icon: PieChart, ready: true },
      { label: "Centros de custo", to: "/financeiro/centros-custo", icon: Layers, ready: true },
      { label: "Investimentos", to: "/financeiro/investimentos", icon: TrendingUp, ready: true },
      { label: "Projeção de caixa", to: "/financeiro/projecao-caixa", icon: LineChart, ready: true },
      { label: "Diagnóstico", to: "/financeiro/diagnostico", icon: Activity, ready: true },
      { label: "Cobranças", to: "/cobrancas", icon: Receipt, ready: true },
      { label: "Contas a Pagar", to: "/pagar", icon: CreditCard, ready: true },
      { label: "Fila de pagamentos", to: "/financeiro/fila-pagamentos", icon: ListChecks, ready: true },
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
      { label: "Configurações", to: "/config", icon: Settings, ready: true },
    ],
  },
];
