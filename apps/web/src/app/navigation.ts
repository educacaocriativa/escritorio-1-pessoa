import {
  CalendarDays,
  Globe,
  LayoutDashboard,
  type LucideIcon,
  Megaphone,
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

/** Dois grupos, no formato do design "Portal": principal + "Extra Section". */
export const navSections: NavSection[] = [
  {
    items: [
      { label: "Dashboard", to: "/", icon: LayoutDashboard, ready: true },
      { label: "Agenda", to: "/agenda", icon: CalendarDays, ready: true },
      { label: "CRM & Kanban", to: "/crm", icon: Users, ready: true },
      { label: "Financeiro", to: "/financeiro", icon: Wallet },
    ],
  },
  {
    title: "Extra Section",
    items: [
      { label: "Produtos", to: "/produtos", icon: ShoppingBag },
      { label: "Marketing", to: "/marketing", icon: Megaphone },
      { label: "Sites", to: "/sites", icon: Globe },
      { label: "Jurídico", to: "/juridico", icon: Scale },
      { label: "Configurações", to: "/config", icon: Settings },
    ],
  },
];
