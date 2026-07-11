import type { ApiError, AuthToken, GoogleCalendarStatus } from "@e1p/shared-types";
import axios, { AxiosError } from "axios";

/** Cliente HTTP único da aplicação. Em dev o Vite faz proxy de /api -> :8000. */
export const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// Injeta o token salvo em toda requisição.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("e1p_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

/** Cliente para rotas públicas (sem login / sem token) — ex.: proposta compartilhada. */
export const publicApi = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

/**
 * Desliza a sessão no backend (idle timeout LGPD — Story 1.3): reemite um access token com a
 * janela de inatividade renovada. Retorna o novo token, ou `null` se a sessão não pôde ser
 * renovada (401 → o interceptor já cuida do logout). Não lança.
 */
export async function refreshSession(): Promise<string | null> {
  try {
    const { data } = await api.post<{ access_token: string }>("/auth/refresh");
    return data.access_token ?? null;
  } catch {
    return null;
  }
}

// ── Integração Google (Meet/Calendar OAuth — Story 4.1) ──────────────────────
/** Estado da integração Google do tenant (configurado na plataforma? conectado? qual e-mail?). */
export async function getGoogleStatus(): Promise<GoogleCalendarStatus> {
  const { data } = await api.get<GoogleCalendarStatus>("/integrations/google/status");
  return data;
}

/** URL de autorização do Google para redirecionar o usuário (inicia o consent OAuth). */
export async function getGoogleConnectUrl(): Promise<string> {
  const { data } = await api.get<{ url: string }>("/integrations/google/connect");
  return data.url;
}

/** Desconecta a conta Google do tenant (revoga best-effort e apaga a credencial local). */
export async function disconnectGoogle(): Promise<void> {
  await api.post("/integrations/google/disconnect");
}

export function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    return data?.detail ?? err.message;
  }
  return "Erro inesperado";
}

export type { AuthToken };
