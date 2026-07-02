import type { SessionInfo } from "@e1p/shared-types";
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { useAuth } from "../../store/auth";

/** Tela obrigatória no 1º acesso: o usuário define uma nova senha (substitui a temporária). */
export default function FirstAccessPage() {
  const { updateUser, logout } = useAuth();
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (pw !== confirm) {
      setError("As senhas não conferem.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      const { data } = await api.post<SessionInfo>("/auth/change-password", { new_password: pw });
      updateUser(data.user); // must_reset_password agora é false → libera o app
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-7 shadow-card">
        <div className="mb-2 flex items-center gap-2">
          <KeyRound size={20} className="text-primary-600" />
          <h1 className="text-lg font-bold text-neutral-800">Defina sua senha</h1>
        </div>
        <p className="mb-5 text-sm text-neutral-500">
          Este é seu primeiro acesso. Crie uma senha pessoal para substituir a temporária.
        </p>
        <div className="space-y-3">
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            placeholder="Nova senha (mín. 8 caracteres)"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-primary-400"
          />
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Confirme a nova senha"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-primary-400"
          />
          {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
          <button
            onClick={save}
            disabled={saving || pw.length < 8 || !confirm}
            className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
          >
            {saving ? "Salvando..." : "Salvar e entrar"}
          </button>
          <button onClick={logout} className="w-full py-1 text-xs text-neutral-400 hover:text-neutral-600">
            Sair
          </button>
        </div>
      </div>
    </div>
  );
}
