import {
  CalendarDays,
  FileSignature,
  FileText,
  Globe,
  LayoutDashboard,
  type LucideIcon,
  Megaphone,
  Package,
  Receipt,
  Scale,
  Settings,
  ShoppingBag,
  Users,
  Wallet,
} from "lucide-react";

export interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  /** false enquanto o módulo ainda não foi construído (mostra como "em breve"). */
  ready?: boolean;
}

export interface NavSection {
  title?: string;
  items: NavItem[];
}

/** Navegação espelha os módulos do e1p (ver docs/MODULES.md). `ready` liga conforme construímos. */
export const navSections: NavSection[] = [
  {
    items: [
      { label: "Cockpit", to: "/", icon: LayoutDashboard, ready: true },
      { label: "Agenda", to: "/agenda", icon: CalendarDays, ready: true },
      { label: "CRM & Kanban", to: "/crm", icon: Users },
      { label: "Financeiro", to: "/financeiro", icon: Wallet },
    ],
  },
  {
    title: "Comercial",
    items: [
      { label: "Orçamentos", to: "/orcamentos", icon: FileText },
      { label: "Contratos", to: "/contratos", icon: FileSignature },
      { label: "Produtos", to: "/produtos", icon: ShoppingBag },
      { label: "Marketing", to: "/marketing", icon: Megaphone },
    ],
  },
  {
    title: "Operação",
    items: [
      { label: "Estoque", to: "/estoque", icon: Package },
      { label: "Cobranças", to: "/cobrancas", icon: Receipt },
      { label: "Sites", to: "/sites", icon: Globe },
      { label: "Jurídico", to: "/juridico", icon: Scale },
    ],
  },
  {
    title: "Conta",
    items: [{ label: "Configurações", to: "/config", icon: Settings }],
  },
];
