import type { AuthToken } from "@e1p/shared-types";
import { useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { useAuth } from "../../store/auth";

type Mode = "login" | "register";

export default function LoginPage() {
  const { login } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // campos
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [legalName, setLegalName] = useState("");
  const [slug, setSlug] = useState("");
  const [document, setDocument] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const body =
        mode === "login"
          ? { email, password }
          : { email, password, name, legal_name: legalName, slug, document };
      const { data } = await api.post<AuthToken>(`/auth/${mode}`, body);
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

        <h1 className="mb-1 text-2xl font-bold text-neutral-800">
          {mode === "login" ? "Entrar" : "Criar sua conta"}
        </h1>
        <p className="mb-6 text-sm text-neutral-500">
          {mode === "login"
            ? "Acesse sua empresa de 1 pessoa."
            : "Cadastre sua empresa e seu subdomínio."}
        </p>

        <form onSubmit={submit} className="space-y-3">
          {mode === "register" && (
            <>
              <Field label="Nome da empresa" value={legalName} onChange={setLegalName} required />
              <div className="flex gap-2">
                <Field label="Subdomínio" value={slug} onChange={setSlug} placeholder="suaempresa" required />
                <Field label="CPF/CNPJ" value={document} onChange={setDocument} required />
              </div>
              <Field label="Seu nome" value={name} onChange={setName} required />
            </>
          )}
          <Field label="E-mail" type="email" value={email} onChange={setEmail} required />
          <Field label="Senha" type="password" value={password} onChange={setPassword} required />

          {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
          >
            {loading ? "..." : mode === "login" ? "Entrar" : "Criar conta"}
          </button>
        </form>

        <button
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
          className="mt-4 w-full text-center text-sm text-primary-600 hover:underline"
        >
          {mode === "login" ? "Não tem conta? Criar agora" : "Já tenho conta — entrar"}
        </button>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="block flex-1">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      <input
        type={type}
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
      />
    </label>
  );
}
