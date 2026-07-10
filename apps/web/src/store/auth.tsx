import type { Tenant, User } from "@e1p/shared-types";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";

interface AuthContextValue {
  token: string | null;
  user: User | null;
  tenant: Tenant | null;
  isAuthenticated: boolean;
  login: (token: string, user: User, tenant: Tenant) => void;
  updateUser: (user: User) => void;
  updateToken: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const TOKEN_KEY = "e1p_token";
const USER_KEY = "e1p_user";
const TENANT_KEY = "e1p_tenant";

function readJSON<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<User | null>(() => readJSON<User>(USER_KEY));
  const [tenant, setTenant] = useState<Tenant | null>(() => readJSON<Tenant>(TENANT_KEY));

  const login = useCallback((t: string, u: User, tn: Tenant) => {
    localStorage.setItem(TOKEN_KEY, t);
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    localStorage.setItem(TENANT_KEY, JSON.stringify(tn));
    setToken(t);
    setUser(u);
    setTenant(tn);
  }, []);

  const updateUser = useCallback((u: User) => {
    localStorage.setItem(USER_KEY, JSON.stringify(u));
    setUser(u);
  }, []);

  // Substitui só a credencial (usado ao deslizar a sessão via /auth/refresh — idle timeout LGPD).
  const updateToken = useCallback((t: string) => {
    localStorage.setItem(TOKEN_KEY, t);
    setToken(t);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(TENANT_KEY);
    setToken(null);
    setUser(null);
    setTenant(null);
  }, []);

  // Desloga automaticamente se a API responder 401 (token expirado/inválido).
  useEffect(() => {
    const id = api.interceptors.response.use(
      (r) => r,
      (err) => {
        if (err?.response?.status === 401 && localStorage.getItem(TOKEN_KEY)) logout();
        return Promise.reject(err);
      },
    );
    return () => api.interceptors.response.eject(id);
  }, [logout]);

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        tenant,
        isAuthenticated: Boolean(token),
        login,
        updateUser,
        updateToken,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth deve ser usado dentro de AuthProvider");
  return ctx;
}
