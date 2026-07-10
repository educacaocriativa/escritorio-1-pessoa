import type { ApiError, AuthToken } from "@e1p/shared-types";
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

export function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    return data?.detail ?? err.message;
  }
  return "Erro inesperado";
}

export type { AuthToken };
