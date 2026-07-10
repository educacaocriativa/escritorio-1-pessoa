import { useCallback, useEffect, useRef, useState } from "react";
import { refreshSession } from "../lib/api";
import {
  IDLE_REFRESH_INTERVAL_MINUTES,
  IDLE_TIMEOUT_MINUTES,
  IDLE_WARNING_MINUTES,
  IdleTimer,
} from "../lib/idleTimer";
import { useAuth } from "./auth";

const ACTIVITY_EVENTS = [
  "mousedown",
  "mousemove",
  "keydown",
  "touchstart",
  "scroll",
  "click",
] as const;

const MIN = 60_000;

/**
 * Idle timeout LGPD (Story 1.3). Enquanto o usuário está logado:
 * - conta 30 min de inatividade (qualquer interação — não só requests — reinicia a contagem,
 *   cobrindo formulários longos sem quebrar fluxos ativos legítimos — AC2);
 * - desliza a sessão no backend (`/auth/refresh`, com throttle) enquanto há atividade;
 * - avisa 1 min antes e, ao esgotar, faz logout limpo.
 *
 * O backend é a proteção real (token expira por inatividade → 401 → interceptor desloga); este
 * hook é a experiência amigável em cima disso.
 */
export function useIdleTimeout(): { showWarning: boolean; stayConnected: () => void } {
  const { isAuthenticated, updateToken, logout } = useAuth();
  const [showWarning, setShowWarning] = useState(false);
  const timerRef = useRef<IdleTimer | null>(null);
  const lastRefreshRef = useRef(0);

  // Reemite o token no backend (throttle), atualizando a credencial guardada.
  const doRefresh = useCallback(
    async (force: boolean) => {
      const now = Date.now();
      if (!force && now - lastRefreshRef.current < IDLE_REFRESH_INTERVAL_MINUTES * MIN) return;
      lastRefreshRef.current = now;
      const token = await refreshSession();
      if (token) updateToken(token);
    },
    [updateToken],
  );

  useEffect(() => {
    if (!isAuthenticated) {
      setShowWarning(false);
      return;
    }

    const timer = new IdleTimer({
      idleMs: IDLE_TIMEOUT_MINUTES * MIN,
      warningMs: IDLE_WARNING_MINUTES * MIN,
      onWarn: () => setShowWarning(true),
      onTimeout: () => {
        setShowWarning(false);
        // Fail-closed: sessão ociosa é encerrada (o token do backend já expirou em paralelo).
        logout();
      },
      onActive: () => setShowWarning(false),
    });
    timerRef.current = timer;
    timer.start();

    const onActivity = () => {
      timer.activity();
      void doRefresh(false);
    };
    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, onActivity, { passive: true });
    }

    return () => {
      timer.stop();
      timerRef.current = null;
      for (const evt of ACTIVITY_EVENTS) window.removeEventListener(evt, onActivity);
    };
  }, [isAuthenticated, doRefresh, logout]);

  // Botão "Continuar conectado": reinicia a contagem e força uma reemissão imediata.
  const stayConnected = useCallback(() => {
    setShowWarning(false);
    timerRef.current?.activity();
    void doRefresh(true);
  }, [doRefresh]);

  return { showWarning, stayConnected };
}
