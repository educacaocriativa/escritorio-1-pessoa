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

export function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    return data?.detail ?? err.message;
  }
  return "Erro inesperado";
}

export type { AuthToken };
