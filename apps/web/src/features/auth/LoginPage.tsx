import type { AuthToken } from "@e1p/shared-types";
import { useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { useAuth } from "../../store/auth";

export default function LoginPage() {
  const { login } = useAuth();
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
      login(data.access_token, data.user, data.tenant);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-primary-500 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-500 font-bold text-white">
            e1
          </div>
          <span className="text-xl font-bold text-neutral-800">e1p</span>
        </div>

        <h1 className="mb-1 text-2xl font-bold text-neutral-800">Entrar</h1>
        <p className="mb-6 text-sm text-neutral-500">Acesse sua empresa de 1 pessoa.</p>

        <form onSubmit={submit} className="space-y-3">
          <Field label="E-mail" type="email" value={email} onChange={setEmail} required />
          <Field label="Senha" type="password" value={password} onChange={setPassword} required />

          {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
          >
            {loading ? "..." : "Entrar"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-neutral-400">
          O acesso é exclusivo para assinantes. Em breve será possível assinar por aqui.
        </p>
      </div>
    </div>
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
