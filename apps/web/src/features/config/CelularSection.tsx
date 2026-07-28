import type { DeviceToken } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

/**
 * Configuração das duas portas de entrada do comprovante pelo celular.
 *
 * Android não precisa de token: o PWA instalado já vira destino do compartilhamento. iOS
 * precisa, porque o Atalho não tem sessão de navegador — e é por isso que esse token só
 * autoriza o upload do comprovante, nada mais.
 */
export default function CelularSection() {
  const [tokens, setTokens] = useState<DeviceToken[]>([]);
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<DeviceToken[]>("/settings/device-tokens");
    setTokens(data);
  }, []);

  useEffect(() => {
    load().catch((err) => setError(apiErrorMessage(err)));
  }, [load]);

  async function create() {
    setError(null);
    try {
      const { data } = await api.post<{ token: string }>("/settings/device-tokens", {
        name: name.trim() || "Meu iPhone",
      });
      setFresh(data.token);
      setName("");
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function revoke(id: string) {
    await api.delete(`/settings/device-tokens/${id}`);
    await load();
  }

  const origin = typeof window === "undefined" ? "" : window.location.origin;

  return (
    <section className="space-y-4 rounded-2xl bg-white p-5 shadow-sm">
      <div>
        <h2 className="font-semibold text-neutral-800">Celular — anexar comprovante</h2>
        <p className="text-sm text-neutral-500">
          Compartilhe o comprovante direto do app do banco para o e1p.
        </p>
      </div>

      <div className="rounded-xl bg-neutral-50 p-4 text-sm text-neutral-700">
        <p className="mb-1 font-semibold">Android</p>
        <p>
          Abra <code>{origin}</code> no Chrome, toque no menu e escolha{" "}
          <strong>Instalar app</strong>. Depois disso o e1p aparece na lista de compartilhamento
          do app do banco. Não precisa de token.
        </p>
      </div>

      <div className="rounded-xl bg-neutral-50 p-4 text-sm text-neutral-700">
        <p className="mb-1 font-semibold">iPhone</p>
        <p className="mb-2">
          Crie um atalho no app <strong>Atalhos</strong> com estes 4 passos e gere um token abaixo:
        </p>
        <ol className="list-decimal space-y-1 pl-5 text-xs">
          <li>Ação <strong>Receber</strong> imagens e PDFs da folha de compartilhamento.</li>
          <li>
            <strong>Obter conteúdo do URL</strong> — POST em{" "}
            <code>{origin}/api/payables/receipts</code>, corpo <code>Formulário</code> com o campo{" "}
            <code>file</code> = Entrada do Atalho, e cabeçalho{" "}
            <code>X-E1P-Device-Token</code> = seu token.
          </li>
          <li><strong>Obter valor do dicionário</strong> — chave <code>id</code>.</li>
          <li><strong>Abrir URL</strong> — <code>{origin}/comprovante/</code> + o valor do passo 3.</li>
        </ol>
      </div>

      {fresh && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-xs font-semibold text-amber-800">
            Copie agora — o token só aparece uma vez.
          </p>
          <p className="mt-1 break-all rounded bg-white p-2 font-mono text-xs">{fresh}</p>
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Nome do aparelho (ex.: meu iPhone)"
          className="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
        />
        <button
          onClick={create}
          className="shrink-0 rounded-pill bg-primary-500 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-600"
        >
          Gerar token
        </button>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {tokens.length > 0 && (
        <ul className="divide-y divide-neutral-100 rounded-lg border border-neutral-100">
          {tokens.map((t) => (
            <li key={t.id} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate text-neutral-700">{t.name}</span>
              <span className="shrink-0 text-xs text-neutral-400">
                {t.last_used_at
                  ? `usado em ${new Date(t.last_used_at).toLocaleDateString("pt-BR")}`
                  : "nunca usado"}
              </span>
              <button
                onClick={() => revoke(t.id)}
                className="shrink-0 text-xs font-semibold text-neutral-400 hover:text-danger"
              >
                Revogar
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
