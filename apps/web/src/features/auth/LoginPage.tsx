import type { AuthToken } from "@e1p/shared-types";
import { useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { useAuth } from "../../store/auth";

type Mode = "login" | "forgot" | "reset";

export default function LoginPage() {
  const { login } = useAuth();
  const [mode, setMode] = useState<Mode>("login");

  return (
    <div className="flex min-h-screen items-center justify-center bg-primary-500 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-500 font-bold text-white">
            e1
          </div>
          <span className="text-xl font-bold text-neutral-800">e1p</span>
        </div>

        {mode === "login" && <LoginForm onLogin={login} onForgot={() => setMode("forgot")} />}
        {mode === "forgot" && (
          <ForgotForm onBack={() => setMode("login")} onHaveToken={() => setMode("reset")} />
        )}
        {mode === "reset" && <ResetForm onDone={() => setMode("login")} />}
      </div>
    </div>
  );
}

function LoginForm({
  onLogin,
  onForgot,
}: {
  onLogin: (t: string, u: AuthToken["user"], tn: AuthToken["tenant"]) => void;
  onForgot: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.post<AuthToken>("/auth/login", { email, password });
      onLogin(data.access_token, data.user, data.tenant);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-bold text-neutral-800">Entrar</h1>
      <p className="mb-6 text-sm text-neutral-500">Acesse sua empresa de 1 pessoa.</p>
      <form onSubmit={submit} className="space-y-3">
        <Field label="E-mail" type="email" value={email} onChange={setEmail} required />
        <Field label="Senha" type="password" value={password} onChange={setPassword} required />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <Submit loading={loading}>Entrar</Submit>
      </form>
      <button onClick={onForgot} className="mt-4 w-full text-center text-sm text-primary-600 hover:underline">
        Esqueci minha senha
      </button>
      <p className="mt-6 text-center text-xs text-neutral-400">
        O acesso é exclusivo para assinantes.
      </p>
    </>
  );
}

function ForgotForm({ onBack, onHaveToken }: { onBack: () => void; onHaveToken: () => void }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await api.post<{ message: string; dev_reset_token?: string }>(
        "/auth/forgot-password",
        { email },
      );
      setSent(true);
      setDevToken(data.dev_reset_token ?? null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-bold text-neutral-800">Recuperar senha</h1>
      <p className="mb-6 text-sm text-neutral-500">
        Informe seu e-mail e enviaremos um link de redefinição.
      </p>
      {sent ? (
        <div className="space-y-3">
          <p className="rounded-lg bg-accent-50 p-3 text-sm text-accent-700">
            Se o e-mail existir, enviaremos instruções de redefinição.
          </p>
          {devToken && (
            <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-700">
              <p className="mb-1 font-semibold">Modo desenvolvimento (sem e-mail ainda):</p>
              <p className="mb-2 break-all">
                token: <code>{devToken}</code>
              </p>
              <button
                onClick={onHaveToken}
                className="rounded-pill bg-amber-500 px-3 py-1 font-semibold text-white"
              >
                Redefinir agora
              </button>
            </div>
          )}
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <Field label="E-mail" type="email" value={email} onChange={setEmail} required />
          <Submit loading={loading}>Enviar link</Submit>
        </form>
      )}
      <button onClick={onBack} className="mt-4 w-full text-center text-sm text-primary-600 hover:underline">
        Voltar ao login
      </button>
    </>
  );
}

function ResetForm({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, password });
      setOk(true);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1 className="mb-1 text-2xl font-bold text-neutral-800">Definir nova senha</h1>
      <p className="mb-6 text-sm text-neutral-500">Cole o token recebido e escolha uma nova senha.</p>
      {ok ? (
        <div className="space-y-3">
          <p className="rounded-lg bg-accent-50 p-3 text-sm text-accent-700">
            Senha redefinida com sucesso.
          </p>
          <button
            onClick={onDone}
            className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white"
          >
            Ir para o login
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <Field label="Token" value={token} onChange={setToken} required />
          <Field label="Nova senha" type="password" value={password} onChange={setPassword} required />
          {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
          <Submit loading={loading}>Redefinir senha</Submit>
        </form>
      )}
    </>
  );
}

function Submit({ loading, children }: { loading: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
    >
      {loading ? "..." : children}
    </button>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
      />
    </label>
  );
}
