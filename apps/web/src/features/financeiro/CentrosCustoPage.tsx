import { Archive, Pencil } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import {
  type CostCenter,
  type CostCenterBucket,
  type CostCenterReport,
  COST_CENTER_KINDS,
  formatBRL,
  kindLabel,
} from "./costCenters";

/**
 * Centros de custo (Story 5.5) — 2ª dimensão de análise. CRUD (criar/editar/arquivar) + um
 * comparativo do mês por centro de custo (cruza o resultado lado a lado, incl. "Não atribuído").
 * A dimensão é sempre opcional; quem não usa não é obrigado. Design "Portal", PT-BR.
 */

/** Primeiro/último dia do mês corrente (bordas de data de calendário, sem depender de fuso). */
function currentMonthRange(): { start: string; end: string } {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth();
  const lastDay = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const mm = String(m + 1).padStart(2, "0");
  return { start: `${y}-${mm}-01`, end: `${y}-${mm}-${String(lastDay).padStart(2, "0")}` };
}

export default function CentrosCustoPage() {
  const [centers, setCenters] = useState<CostCenter[]>([]);
  const [report, setReport] = useState<CostCenterReport | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CostCenter | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const { start, end } = currentMonthRange();
    try {
      const [c, r] = await Promise.all([
        api.get<CostCenter[]>("/cost-centers", {
          params: { include_archived: includeArchived },
        }),
        api.get<CostCenterReport>("/financial-intelligence/by-cost-center", {
          params: { start, end },
        }),
      ]);
      setCenters(c.data);
      setReport(r.data);
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }, [includeArchived]);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo centro de custo", useCallback(() => setOpen(true), []));

  async function archive(id: string) {
    if (!confirm("Arquivar este centro de custo? O histórico já vinculado é preservado.")) return;
    await api.post(`/cost-centers/${id}/archive`);
    load();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Centros de custo</p>
          <h1 className="text-2xl font-bold text-neutral-800">Centros de custo</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Uma 2ª dimensão opcional (por sócio, área ou unidade) para cruzar o financeiro. Quem não
            usa não é obrigado — lançamentos sem centro aparecem como "Não atribuído".
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-neutral-600">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          Mostrar arquivados
        </label>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {centers.length === 0 ? (
        <p className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">
          Nenhum centro de custo ainda. Clique em "Novo centro de custo".
        </p>
      ) : (
        <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
          <ul className="divide-y divide-neutral-50">
            {centers.map((c) => (
              <li key={c.id} className="flex items-center justify-between px-5 py-3">
                <span className="flex items-center gap-2">
                  <span
                    className={
                      c.archived_at
                        ? "text-sm text-neutral-400 line-through"
                        : "text-sm font-medium text-neutral-800"
                    }
                  >
                    {c.name}
                  </span>
                  <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                    {kindLabel(c.kind)}
                  </span>
                  {c.archived_at && (
                    <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                      Arquivado
                    </span>
                  )}
                </span>
                {!c.archived_at && (
                  <span className="flex items-center gap-3">
                    <button
                      onClick={() => setEditing(c)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-primary-600"
                    >
                      <Pencil size={14} />
                      Editar
                    </button>
                    <button
                      onClick={() => archive(c.id)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-danger"
                    >
                      <Archive size={14} />
                      Arquivar
                    </button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report && report.buckets.length > 0 && <ComparativeCard report={report} />}

      <CostCenterModal
        open={open || editing !== null}
        editing={editing}
        onClose={() => {
          setOpen(false);
          setEditing(null);
        }}
        onSaved={load}
      />
    </div>
  );
}

/** Comparativo do mês: resultado por centro de custo lado a lado (inclui "Não atribuído"). */
function ComparativeCard({ report }: { report: CostCenterReport }) {
  return (
    <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
      <div className="border-b border-neutral-100 px-5 py-3">
        <h2 className="font-semibold text-neutral-800">Resultado por centro de custo (este mês)</h2>
        <p className="text-xs text-neutral-400">
          Mesma fórmula/exclusões da DRE (regime de competência). Compare sócios/áreas lado a lado.
        </p>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
            <th className="px-5 py-2 font-medium">Centro de custo</th>
            <th className="px-5 py-2 font-medium">Receita</th>
            <th className="px-5 py-2 font-medium">Resultado</th>
            <th className="px-5 py-2 font-medium">Lançamentos</th>
          </tr>
        </thead>
        <tbody>
          {report.buckets.map((b) => (
            <Row key={b.cost_center_id ?? "__nao_atribuido__"} bucket={b} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Row({ bucket }: { bucket: CostCenterBucket }) {
  const unassigned = bucket.cost_center_id === null;
  const negative = bucket.resultado_cents < 0;
  return (
    <tr className={`border-b border-neutral-50 last:border-0 ${unassigned ? "bg-amber-50" : ""}`}>
      <td className="px-5 py-2.5 text-neutral-800">
        {bucket.name}
        {bucket.kind && !unassigned && (
          <span className="ml-2 rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
            {kindLabel(bucket.kind)}
          </span>
        )}
      </td>
      <td className="px-5 py-2.5 tabular-nums text-neutral-600">{formatBRL(bucket.receita_cents)}</td>
      <td className={`px-5 py-2.5 tabular-nums font-medium ${negative ? "text-danger" : "text-emerald-600"}`}>
        {formatBRL(bucket.resultado_cents)}
      </td>
      <td className="px-5 py-2.5 tabular-nums text-neutral-500">{bucket.lancamentos}</td>
    </tr>
  );
}

function CostCenterModal({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: CostCenter | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("socio");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(editing?.name ?? "");
      setKind(editing?.kind ?? "socio");
      setError(null);
    }
  }, [open, editing]);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/cost-centers/${editing.id}`, { name, kind });
      } else {
        await api.post("/cost-centers", { name, kind });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={editing ? "Editar centro de custo" : "Novo centro de custo"} open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome" value={name} onChange={setName} placeholder="Ex.: Sócio João, Unidade Centro" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {COST_CENTER_KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !name.trim()}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : editing ? "Salvar" : "Criar centro de custo"}
        </button>
      </div>
    </Modal>
  );
}
