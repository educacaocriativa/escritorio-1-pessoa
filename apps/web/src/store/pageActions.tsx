import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

/** Ação primária da página, exibida como o botão "Novo" na topbar. */
export interface PrimaryAction {
  label: string;
  onClick: () => void;
}

interface PageActionsValue {
  action: PrimaryAction | null;
  setAction: (a: PrimaryAction | null) => void;
}

const PageActionsContext = createContext<PageActionsValue | null>(null);

export function PageActionsProvider({ children }: { children: ReactNode }) {
  const [action, setAction] = useState<PrimaryAction | null>(null);
  const value = useMemo(() => ({ action, setAction }), [action]);
  return <PageActionsContext.Provider value={value}>{children}</PageActionsContext.Provider>;
}

/** Lido pela topbar para renderizar (ou esconder) o botão "Novo". */
export function usePageActions(): PageActionsValue {
  const ctx = useContext(PageActionsContext);
  if (!ctx) throw new Error("usePageActions deve ser usado dentro de PageActionsProvider");
  return ctx;
}

/** Registra a ação primária da página atual (limpa ao desmontar). */
export function usePrimaryAction(label: string, onClick: () => void) {
  const { setAction } = usePageActions();
  useEffect(() => {
    setAction({ label, onClick });
    return () => setAction(null);
  }, [label, onClick, setAction]);
}
