import clsx from "clsx";
import { Bell, ChevronDown, LogOut, Plus, Search, ShieldCheck, X } from "lucide-react";
import { type ReactNode, useState } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../store/auth";
import { usePageActions } from "../store/pageActions";
import { navSections } from "./navigation";

/**
 * Shell visual do e1p — sidebar violeta (#5D44F8) + topbar, conforme o design Figma "Portal".
 * Sidebar colapsável pelo botão X. Item ativo é um pill branco que "vaza" para a direita.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(true);

  return (
    <div className="flex min-h-screen bg-neutral-50">
      {open && <Sidebar onClose={() => setOpen(false)} />}
      {/* min-w-0 impede o flex-child de estourar e empurrar a sidebar quando o Kanban
          rola na horizontal — o scroll fica contido no conteúdo. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpen={() => setOpen(true)} sidebarOpen={open} />
        <main className="min-w-0 flex-1 overflow-x-hidden p-6">{children}</main>
      </div>
    </div>
  );
}

function Sidebar({ onClose }: { onClose: () => void }) {
  const { logout, user } = useAuth();
  return (
    <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col self-start bg-primary-500 py-6 pl-4 text-white">
      {/* Botão de fechar/colapsar (como no anexo) */}
      <button
        onClick={onClose}
        aria-label="Fechar menu"
        className="mb-8 flex h-10 w-10 items-center justify-center rounded-full border-2 border-white/80 text-white transition hover:bg-white/10"
      >
        <X size={20} />
      </button>

      <nav className="flex flex-1 flex-col gap-7 overflow-y-auto pr-1">
        {navSections.map((section, i) => (
          <div key={i}>
            {i > 0 && (
              <div className="mb-5 mr-4 border-t border-dashed border-white/35" />
            )}
            {section.title && (
              <p className="mb-3 text-sm font-bold tracking-wide text-white">{section.title}</p>
            )}
            <ul className="flex flex-col gap-2">
              {section.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      clsx(
                        "flex items-center gap-3 py-3 pl-4 text-[15px] font-medium transition",
                        isActive
                          ? // pill branco que vaza para a direita (cancela o padding com -mr-4)
                            "-mr-4 rounded-l-full bg-white text-primary-700 shadow-sm"
                          : "mr-4 rounded-l-full text-white/90 hover:bg-white/10",
                        !item.ready && "opacity-60",
                      )
                    }
                  >
                    <item.icon size={20} strokeWidth={2} />
                    <span>{item.label}</span>
                    {!item.ready && (
                      <span className="ml-auto mr-3 text-[10px] uppercase tracking-wide opacity-70">
                        em breve
                      </span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}

        {user?.is_platform_admin && (
          <div>
            <div className="mb-5 mr-4 border-t border-dashed border-white/35" />
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 py-3 pl-4 text-[15px] font-medium transition",
                  isActive
                    ? "-mr-4 rounded-l-full bg-white text-primary-700 shadow-sm"
                    : "mr-4 rounded-l-full text-white/90 hover:bg-white/10",
                )
              }
            >
              <ShieldCheck size={20} strokeWidth={2} />
              <span>Admin</span>
            </NavLink>
          </div>
        )}
      </nav>

      <button
        onClick={logout}
        className="mr-4 mt-4 flex items-center gap-3 rounded-l-full py-3 pl-4 text-[15px] font-medium text-white/90 transition hover:bg-white/10"
      >
        <LogOut size={20} strokeWidth={2} />
        <span>Sair</span>
      </button>
    </aside>
  );
}

function Topbar({ onOpen, sidebarOpen }: { onOpen: () => void; sidebarOpen: boolean }) {
  const { user, tenant, logout } = useAuth();
  const { action } = usePageActions();

  return (
    <header className="flex items-center gap-4 border-b border-neutral-100 bg-white px-6 py-3">
      {!sidebarOpen && (
        <button
          onClick={onOpen}
          aria-label="Abrir menu"
          className="flex h-9 w-9 items-center justify-center rounded-pill bg-primary-50 text-primary-600"
        >
          <Search size={16} />
        </button>
      )}

      <div className="relative max-w-md flex-1">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
        <input
          placeholder="Buscar cliente, projeto ou processo"
          className="w-full rounded-pill bg-neutral-50 py-2 pl-9 pr-4 text-sm outline-none focus:ring-2 focus:ring-primary-300"
        />
      </div>

      {action && (
        <button
          onClick={action.onClick}
          className="flex items-center gap-2 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-500"
        >
          <Plus size={16} />
          {action.label}
        </button>
      )}

      <button className="text-neutral-500 hover:text-neutral-800" aria-label="Notificações">
        <Bell size={20} />
      </button>

      <button
        onClick={logout}
        className="flex items-center gap-2"
        title={tenant ? `${tenant.legal_name} — sair` : "Sair"}
      >
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-200 text-xs font-bold text-primary-700">
          {(user?.name ?? "?").slice(0, 1).toUpperCase()}
        </div>
        <ChevronDown size={16} className="text-neutral-500" />
      </button>
    </header>
  );
}
