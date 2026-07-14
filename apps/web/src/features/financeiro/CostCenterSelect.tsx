import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import type { CostCenter } from "./costCenters";

/** Mesmo padrão do ChartAccountSelect, para a 2ª dimensão (centro de custo — Story 5.5). Não tem
 * grupo fixo (kind é texto livre sugerido), então é usado igual em Contas a Pagar e Cobranças. */
export default function CostCenterSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [centers, setCenters] = useState<CostCenter[]>([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api
      .get<CostCenter[]>("/cost-centers")
      .catch(() => ({ data: [] as CostCenter[] }));
    setCenters(data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createNow() {
    setError(null);
    if (!newName.trim()) return;
    setSaving(true);
    try {
      const { data } = await api.post<CostCenter>("/cost-centers", { name: newName.trim() });
      await load();
      onChange(data.id);
      setCreating(false);
      setNewName("");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">
        Centro de custo (opcional)
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
          <option value="">Não atribuído</option>
          {centers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
          <option value="__new__">+ Criar novo centro de custo...</option>
        </select>
      ) : (
        <div className="space-y-2 rounded-lg border border-primary-200 bg-primary-50 p-2.5">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Ex.: Sócio João, Unidade Centro"
            className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-xs outline-none focus:border-primary-400"
          />
          {error && <p className="text-xs text-danger">{error}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={createNow}
              disabled={saving || !newName.trim()}
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
