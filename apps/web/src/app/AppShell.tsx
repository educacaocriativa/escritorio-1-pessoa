import type { TenantProfile } from "@e1p/shared-types";
import clsx from "clsx";
import { Bell, ChevronDown, LogOut, Menu, Plus, Search, ShieldCheck, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import BuscaGlobal from "../features/busca/BuscaGlobal";
import { api } from "../lib/api";
import { applyBrandTheme } from "../lib/theme";
import { useAuth } from "../store/auth";
import { usePageActions } from "../store/pageActions";
import { navSections } from "./navigation";

/** Largura a partir da qual a sidebar cabe ao lado do conteúdo (= breakpoint `md` do Tailwind). */
const DESKTOP_MIN_WIDTH = 768;

/** `true` quando há largura para a sidebar conviver com o conteúdo. Fora do browser, assume desktop. */
function isDesktopWidth(): boolean {
  return typeof window === "undefined" || window.innerWidth >= DESKTOP_MIN_WIDTH;
}

/**
 * Shell visual do e1p — sidebar violeta (#5D44F8) + topbar, conforme o design Figma "Portal".
 * Item ativo é um pill branco que "vaza" para a direita.
 *
 * **Responsivo:** a sidebar tem 256px FIXOS (`w-64 shrink-0`). Num aparelho de 360px isso deixava
 * ~100px de conteúdo — títulos viravam "Desp", cartões espremidos. Por isso, abaixo de
 * `DESKTOP_MIN_WIDTH` ela nasce fechada e abre SOBREPOSTA (`fixed`, fora do fluxo), com fundo
 * escurecido; no desktop segue no fluxo (`md:sticky`) como sempre foi.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(isDesktopWidth);

  // Aplica o Brand Kit do tenant como tema do app (sidebar/botões) uma vez por sessão — as
  // classes Tailwind já apontam pra CSS vars com fallback estático, então sem tema custom nada
  // muda visualmente (ver packages/design-tokens/src/tailwind-preset.ts).
  useEffect(() => {
    api
      .get<TenantProfile>("/settings/profile")
      .then(({ data }) => applyBrandTheme(data))
      .catch(() => {
        /* tema é só um complemento visual — sem acesso/erro, fica no fallback estático padrão */
      });
  }, []);

  return (
    <div className="flex min-h-screen bg-neutral-50">
      {open && (
        <>
          {/* Fundo escurecido: só existe no celular, onde a sidebar cobre o conteúdo. Tocar
              fora fecha — sem isso a gaveta engoliria a tela sem saída óbvia no polegar. */}
          <button
            type="button"
            aria-label="Fechar menu"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 bg-black/40 md:hidden"
          />
          <Sidebar onClose={() => setOpen(false)} />
        </>
      )}
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
  // No celular a gaveta cobre a tela: navegar sem fechá-la deixaria o usuário olhando para o
  // menu em vez da página que acabou de escolher. No desktop ela é parte do layout, então fica.
  const closeIfMobile = () => {
    if (!isDesktopWidth()) onClose();
  };
  return (
    <aside
      className="fixed inset-y-0 left-0 z-40 flex h-screen w-64 shrink-0 flex-col overflow-y-auto bg-primary-500 py-6 pl-4 text-white md:sticky md:top-0 md:z-auto md:self-start"
    >
      {/* Botão de fechar/colapsar (como no anexo) */}
      <button
        onClick={onClose}
        aria-label="Fechar menu"
        className="mb-8 flex h-10 w-10 items-center justify-center rounded-full border-2 border-white/80 text-white transition hover:bg-white/10"
      >
        <X size={20} />
      </button>

      <nav className="flex flex-1 flex-col gap-7 overflow-x-hidden overflow-y-auto pr-1">
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
                    end={item.to === "/" || item.exact === true}
                    onClick={closeIfMobile}
                    className={({ isActive }) =>
                      clsx(
                        "flex min-w-0 items-center gap-3 py-3 pl-4 text-[15px] font-medium transition",
                        isActive
                          ? // pill branco que vaza para a direita (cancela o padding com -mr-4)
                            "-mr-4 rounded-l-full bg-white text-primary-700 shadow-sm"
                          : "mr-4 rounded-l-full text-white/90 hover:bg-white/10",
                        !item.ready && "opacity-60",
                      )
                    }
                  >
                    <item.icon size={20} strokeWidth={2} className="shrink-0" />
                    <span className="truncate">{item.label}</span>
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
              onClick={closeIfMobile}
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
  const navigate = useNavigate();

  return (
    // `flex-wrap` + `order-last` abaixo de `sm`: a ação primária desce para uma linha própria, de
    // largura inteira, em vez de espremer os vizinhos até a linha estourar a viewport. Reflui, não
    // corta — a mesma escolha do PR #58, aplicada ao eixo em que esta barra falhava.
    <header className="flex flex-wrap items-center gap-3 border-b border-neutral-100 bg-white px-4 py-3 sm:px-6">
      {!sidebarOpen && (
        <button
          onClick={onOpen}
          aria-label="Abrir menu"
          // `shrink-0` é o que impede a espremida: sem ele este botão ia a 16px de largura em
          // `/financeiro/investimentos`, e a navegação inteira do celular ficava atrás de um alvo
          // que o polegar não acerta.
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-pill bg-primary-50 text-primary-600"
        >
          {/* `Menu`, e não `Search`: este botão sempre abriu o menu (`aria-label` acima), mas
              usava uma lupa. Com a lupa DE VERDADE agora ao lado dele, seriam dois ícones iguais
              com significados diferentes — e o de baixo é o que o polegar procura no celular. */}
          <Menu size={16} />
        </button>
      )}

      {/* Abaixo de `md` o campo sai da frente e devolve 152px à linha: a medição do PR #58 achou
          que ali ele vira um bolo cinza de 52px sem placeholder legível. O acesso no celular é a
          lupa abaixo, que leva à página `/busca` — já desenhada para caber num telefone. */}
      <BuscaGlobal />

      <button
        onClick={() => navigate("/busca")}
        aria-label="Buscar"
        className="flex h-11 w-11 shrink-0 items-center justify-center rounded-pill text-neutral-500 hover:text-neutral-800 md:hidden"
      >
        <Search size={20} />
      </button>

      {/* `min-h-[44px]`: com `py-2` puro a altura dava 40px e o teste desta task pegaria. */}
      {action && (
        <button
          onClick={action.onClick}
          className="order-last flex min-h-[44px] w-full shrink-0 items-center justify-center gap-2 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-500 sm:order-none sm:w-auto"
        >
          <Plus size={16} className="shrink-0" />
          {action.label}
        </button>
      )}

      {/* `ml-auto` mantém este grupo à direita mesmo quando a busca está escondida — sem ele os
          ícones se amontoariam ao lado do menu. */}
      <div className="ml-auto flex shrink-0 items-center gap-1">
        <button
          className="flex h-11 w-11 items-center justify-center rounded-pill text-neutral-500 hover:text-neutral-800"
          aria-label="Notificações"
        >
          <Bell size={20} />
        </button>

        <button
          onClick={logout}
          className="flex h-11 items-center gap-1 rounded-pill px-1"
          title={tenant ? `${tenant.legal_name} — sair` : "Sair"}
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-200 text-xs font-bold text-primary-700">
            {(user?.name ?? "?").slice(0, 1).toUpperCase()}
          </div>
          <ChevronDown size={16} className="shrink-0 text-neutral-500" />
        </button>
      </div>
    </header>
  );
}
