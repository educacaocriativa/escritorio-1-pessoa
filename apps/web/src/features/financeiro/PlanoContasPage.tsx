import { Archive, ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import {
  type ChartAccount,
  type GrupoDre,
  buildHierarchy,
  GRUPO_LABEL,
  GRUPOS_DRE,
} from "./planoContas";

/**
 * Plano de contas hierárquico por grupo DRE (Story 5.1). Lista agrupada (accordion) por grupo,
 * criação de categoria (grupo fixo via select + nome livre), arquivar (lógico, sem delete) e
 * "usar categorias sugeridas" (seed). Design "Portal", PT-BR.
 */
export default function PlanoContasPage() {
  const [accounts, setAccounts] = useState<ChartAccount[]>([]);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [open, setOpen] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<ChartAccount[]>("/chart-of-accounts", {
      params: { include_archived: includeArchived },
    });
    setAccounts(data);
  }, [includeArchived]);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Nova categoria", useCallback(() => setOpen(true), []));

  const groups = buildHierarchy(accounts);

  async function archive(id: string) {
    if (!confirm("Arquivar esta categoria? O histórico já classificado é preservado.")) return;
    await api.post(`/chart-of-accounts/${id}/archive`);
    load();
  }

  async function seed() {
    setError(null);
    setSeeding(true);
    try {
      await api.post("/chart-of-accounts/seed");
      await load();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSeeding(false);
    }
  }

  const hasAny = accounts.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Plano de contas</p>
          <h1 className="text-2xl font-bold text-neutral-800">Plano de contas</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Classifique seus lançamentos por grupo DRE (Receita, Custo direto, Despesa fixa,
            Tributos, Financeiro, Investimento) com categorias livres dentro de cada grupo.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-neutral-600">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
            />
            Mostrar arquivadas
          </label>
          <button
            onClick={seed}
            disabled={seeding}
            className="inline-flex items-center gap-1.5 rounded-pill border border-primary-200 bg-primary-50 px-3 py-2 text-sm font-medium text-primary-700 hover:bg-primary-100 disabled:opacity-60"
          >
            <Sparkles size={15} />
            {seeding ? "Adicionando..." : "Usar categorias sugeridas"}
          </button>
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {!hasAny && (
        <p className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">
          Nenhuma categoria ainda. Clique em "Nova categoria" ou use as categorias sugeridas.
        </p>
      )}

      <div className="space-y-3">
        {groups.map((g) => (
          <GroupCard key={g.grupo_dre} group={g} onArchive={archive} />
        ))}
      </div>

      <NewCategoryModal open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
  );
}

function GroupCard({
  group,
  onArchive,
}: {
  group: ReturnType<typeof buildHierarchy>[number];
  onArchive: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-neutral-50"
      >
        <span className="flex items-center gap-2">
          {expanded ? (
            <ChevronDown size={18} className="text-neutral-400" />
          ) : (
            <ChevronRight size={18} className="text-neutral-400" />
          )}
          <span className="font-semibold text-neutral-800">{group.label}</span>
          <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
            {group.categorias.length}
          </span>
        </span>
      </button>
      {expanded && (
        <div className="border-t border-neutral-100">
          {group.categorias.length === 0 ? (
            <p className="px-5 py-3 text-sm text-neutral-400">Nenhuma categoria neste grupo.</p>
          ) : (
            <ul className="divide-y divide-neutral-50">
              {group.categorias.map((c) => (
                <li key={c.id} className="flex items-center justify-between px-5 py-2.5">
                  <span
                    className={
                      c.archived_at
                        ? "text-sm text-neutral-400 line-through"
                        : "text-sm text-neutral-700"
                    }
                  >
                    {c.categoria}
                    {c.archived_at && (
                      <span className="ml-2 rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                        Arquivada
                      </span>
                    )}
                  </span>
                  {!c.archived_at && (
                    <button
                      onClick={() => onArchive(c.id)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-danger"
                    >
                      <Archive size={14} />
                      Arquivar
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function NewCategoryModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [grupo, setGrupo] = useState<GrupoDre>("RECEITA");
  const [categoria, setCategoria] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.post("/chart-of-accounts", { grupo_dre: grupo, categoria });
      onCreated();
      setCategoria("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova categoria" open={open} onClose={onClose}>
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Grupo DRE</span>
          <select
            value={grupo}
            onChange={(e) => setGrupo(e.target.value as GrupoDre)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {GRUPOS_DRE.map((g) => (
              <option key={g} value={g}>
                {GRUPO_LABEL[g]}
              </option>
            ))}
          </select>
        </label>
        <Field
          label="Categoria"
          value={categoria}
          onChange={setCategoria}
          placeholder="Ex.: Vendas de serviço"
        />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !categoria.trim()}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Criar categoria"}
        </button>
      </div>
    </Modal>
  );
}
