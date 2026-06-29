import clsx from "clsx";
import { Bell, ChevronDown, Plus, Search } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { navSections } from "./navigation";

/**
 * Shell visual do e1p — sidebar índigo + topbar, conforme o design Figma "Portal".
 * Envolve todas as páginas autenticadas.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen bg-neutral-50">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Topbar />
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

function Sidebar() {
  return (
    <aside className="flex w-64 flex-col bg-primary-500 px-4 py-6 text-white">
      <div className="mb-8 flex items-center gap-2 px-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/15 font-bold">
          e1
        </div>
        <span className="text-xl font-bold">e1p</span>
      </div>

      <nav className="flex flex-1 flex-col gap-6 overflow-y-auto">
        {navSections.map((section, i) => (
          <div key={i}>
            {section.title && (
              <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wide text-white/50">
                {section.title}
              </p>
            )}
            <ul className="flex flex-col gap-1">
              {section.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      clsx(
                        "flex items-center gap-3 rounded-pill px-3 py-2 text-sm font-medium transition",
                        isActive
                          ? "bg-white text-primary-700"
                          : "text-white/85 hover:bg-white/10",
                        !item.ready && "opacity-50",
                      )
                    }
                  >
                    <item.icon size={18} />
                    <span>{item.label}</span>
                    {!item.ready && (
                      <span className="ml-auto text-[10px] uppercase text-white/60">em breve</span>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}

function Topbar() {
  return (
    <header className="flex items-center gap-4 border-b border-neutral-100 bg-white px-6 py-3">
      <div className="relative flex-1 max-w-md">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400"
        />
        <input
          placeholder="Buscar cliente, projeto ou processo"
          className="w-full rounded-pill bg-neutral-50 py-2 pl-9 pr-4 text-sm outline-none focus:ring-2 focus:ring-primary-300"
        />
      </div>

      <button className="flex items-center gap-2 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-500">
        <Plus size={16} />
        Novo
      </button>

      <button className="text-neutral-500 hover:text-neutral-800" aria-label="Notificações">
        <Bell size={20} />
      </button>

      <button className="flex items-center gap-2">
        <div className="h-8 w-8 rounded-full bg-primary-200" />
        <ChevronDown size={16} className="text-neutral-500" />
      </button>
    </header>
  );
}
