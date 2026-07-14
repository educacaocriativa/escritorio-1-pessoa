import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { type ChartAccount, type GrupoDre, GRUPO_LABEL } from "./planoContas";

/**
 * Seletor "Categoria (plano de contas)" — cadastro estruturado por trás de um combo simples:
 * escolhe entre categorias já cadastradas (agrupadas por grupo DRE) ou cria uma nova sem sair da
 * tela. `groups` restringe a lista/criação aos grupos cabíveis no lançamento (Contas a Pagar
 * exclui RECEITA; Cobranças mostra só RECEITA) — DRE/lucratividade agrupam por `chart_account_id`,
 * nunca por texto livre, então este seletor substitui qualquer campo de categoria digitado à mão.
 */
export default function ChartAccountSelect({
  value,
  onChange,
  groups,
  defaultNewGrupo,
}: {
  value: string;
  onChange: (v: string) => void;
  groups: readonly GrupoDre[];
  defaultNewGrupo: GrupoDre;
}) {
  const [accounts, setAccounts] = useState<ChartAccount[]>([]);
  const [creating, setCreating] = useState(false);
  const [newGrupo, setNewGrupo] = useState<GrupoDre>(defaultNewGrupo);
  const [newCategoria, setNewCategoria] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api
      .get<ChartAccount[]>("/chart-of-accounts")
      .catch(() => ({ data: [] as ChartAccount[] }));
    setAccounts(data.filter((a) => groups.includes(a.grupo_dre)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups]);

  useEffect(() => {
    load();
  }, [load]);

  async function createNow() {
    setError(null);
    if (!newCategoria.trim()) return;
    setSaving(true);
    try {
      const { data } = await api.post<ChartAccount>("/chart-of-accounts", {
        grupo_dre: newGrupo,
        categoria: newCategoria.trim(),
      });
      await load();
      onChange(data.id);
      setCreating(false);
      setNewCategoria("");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">
        Categoria (plano de contas)
      </span>
      {!creating ? (
        <select
          value={value}
          onChange={(e) => {
            if (e.target.value === "__new__") {
              setCreating(true);
              return;
            }
            onChange(e.target.value);
          }}
          className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
        >
          <option value="">Sem categoria</option>
          {groups.map((g) => {
            const items = accounts.filter((a) => a.grupo_dre === g);
            return items.length > 0 ? (
              <optgroup key={g} label={GRUPO_LABEL[g]}>
                {items.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.categoria}
                  </option>
                ))}
              </optgroup>
            ) : null;
          })}
          <option value="__new__">+ Criar nova categoria...</option>
        </select>
      ) : (
        <div className="space-y-2 rounded-lg border border-primary-200 bg-primary-50 p-2.5">
          <div className="flex gap-2">
            <select
              value={newGrupo}
              onChange={(e) => setNewGrupo(e.target.value as GrupoDre)}
              className="rounded-lg border border-neutral-200 px-2 py-1.5 text-xs outline-none focus:border-primary-400"
            >
              {groups.map((g) => (
                <option key={g} value={g}>
                  {GRUPO_LABEL[g]}
                </option>
              ))}
            </select>
            <input
              value={newCategoria}
              onChange={(e) => setNewCategoria(e.target.value)}
              placeholder="Nome da categoria"
              className="flex-1 rounded-lg border border-neutral-200 px-2 py-1.5 text-xs outline-none focus:border-primary-400"
            />
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={createNow}
              disabled={saving || !newCategoria.trim()}
              className="rounded-pill bg-accent-400 px-3 py-1 text-xs font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
            >
              {saving ? "Criando..." : "Criar e usar"}
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="text-xs text-neutral-500 hover:underline"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}
    </label>
  );
}
