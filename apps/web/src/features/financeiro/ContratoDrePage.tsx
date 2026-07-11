import type { Contract } from "@e1p/shared-types";
import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import {
  buildContractDreView,
  type ContractDre,
  type DreGroup,
  formatBRL,
} from "./contratoDre";
import type { CostCenter } from "./costCenters";

/**
 * DRE por contrato / lucratividade (Story 5.4) — margem de contribuição (R$/%), break-even e
 * rateio de overhead (opcional, só na visão analítica). Regime de COMPETÊNCIA. Read-only: só lê a
 * agregação do backend, não altera nada (o rateio de overhead NUNCA é gravado). Design "Portal".
 */

/** Primeiro/último dia do mês "YYYY-MM" (bordas de data de calendário, sem depender de fuso). */
function monthRange(month: string): { start: string; end: string } {
  const [y, m] = month.split("-").map(Number);
  const lastDay = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return { start: `${month}-01`, end: `${month}-${String(lastDay).padStart(2, "0")}` };
}

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export default function ContratoDrePage() {
  const { id = "" } = useParams();
  const [month, setMonth] = useState(currentMonth);
  const [includeOverhead, setIncludeOverhead] = useState(false);
  const [costCenterId, setCostCenterId] = useState(""); // "" = todos os centros de custo
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [contract, setContract] = useState<Contract | null>(null);
  const [dre, setDre] = useState<ContractDre | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api
      .get<Contract>(`/contracts/${id}`)
      .then((r) => setContract(r.data))
      .catch(() => setContract(null));
  }, [id]);

  // Centros de custo do tenant (2ª dimensão, Story 5.5) para o filtro opcional.
  useEffect(() => {
    api
      .get<CostCenter[]>("/cost-centers")
      .then((r) => setCostCenters(r.data))
      .catch(() => setCostCenters([]));
  }, []);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    const { start, end } = monthRange(month);
    try {
      // cost_center_id só entra quando um centro específico é escolhido — "Todos" (vazio) mantém a
      // visão da Story 5.4 IDÊNTICA (não quebra quem não usa a 2ª dimensão).
      const params: Record<string, string | boolean> = {
        start,
        end,
        include_overhead: includeOverhead,
      };
      if (costCenterId) params.cost_center_id = costCenterId;
      const { data } = await api.get<ContractDre>(
        `/financial-intelligence/contracts/${id}/dre`,
        { params },
      );
      setDre(data);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [id, month, includeOverhead, costCenterId]);

  useEffect(() => {
    load();
  }, [load]);

  const view = useMemo(() => (dre ? buildContractDreView(dre) : null), [dre]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Contratos / DRE</p>
          <h1 className="text-2xl font-bold text-neutral-800">
            Lucratividade {contract ? `— ${contract.title}` : ""}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Receita → Custo Direto → Margem de Contribuição → resultado, em regime de competência.
            O overhead da empresa é rateado apenas nesta análise — nunca no lançamento.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {costCenters.length > 0 && (
            <select
              value={costCenterId}
              onChange={(e) => setCostCenterId(e.target.value)}
              aria-label="Filtrar por centro de custo"
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
            >
              <option value="">Todos os centros de custo</option>
              {costCenters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={() => setMonth((mo) => shiftMonth(mo, -1))}
            aria-label="Mês anterior"
            className="rounded-lg border border-neutral-200 p-2 text-neutral-500 hover:bg-neutral-50"
          >
            <ChevronLeft size={16} />
          </button>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value || currentMonth())}
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
          <button
            onClick={() => setMonth((mo) => shiftMonth(mo, 1))}
            aria-label="Próximo mês"
            className="rounded-lg border border-neutral-200 p-2 text-neutral-500 hover:bg-neutral-50"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {view && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard
              label="Margem de contribuição"
              value={loading ? "…" : formatBRL(view.margemCents)}
              hint={`${view.marginPct} da receita`}
              tone={view.margemCents >= 0 ? "text-emerald-600" : "text-danger"}
            />
            <MetricCard
              label="Break-even (receita p/ empatar)"
              value={loading ? "…" : view.breakEven}
              hint="Ponto em que a margem cobre os custos fixos"
              tone={view.breakEvenReachable ? "text-neutral-800" : "text-amber-600"}
              small={!view.breakEvenReachable}
            />
            <MetricCard
              label="Resultado do período"
              value={loading ? "…" : formatBRL(view.resultadoCents)}
              hint={
                view.overheadCents > 0
                  ? `Inclui overhead rateado de ${formatBRL(view.overheadCents)}`
                  : "Margem + outros grupos atribuídos − custos fixos"
              }
              tone={view.resultadoCents >= 0 ? "text-emerald-600" : "text-danger"}
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-neutral-600">
            <input
              type="checkbox"
              checked={includeOverhead}
              onChange={(e) => setIncludeOverhead(e.target.checked)}
              className="h-4 w-4 rounded border-neutral-300"
            />
            Ratear overhead da empresa (bucket "Empresa") por proporção de receita
          </label>

          <div className="space-y-3">
            <GroupRow group={view.receita} />
            <GroupRow group={view.custoDireto} />
            {view.outrosResultadoCents !== 0 && (
              <FixedRow
                label="Outros grupos atribuídos (Despesa Fixa/Tributos/Financeiro)"
                cents={view.outrosResultadoCents}
              />
            )}
            <FixedRow label="Custos fixos atribuídos" cents={-view.fixedCents} />
            {view.overheadCents > 0 && (
              <FixedRow label="Overhead rateado (análise)" cents={-view.overheadCents} />
            )}
          </div>

          {view.notes.length > 0 && (
            <ul className="space-y-1 text-xs text-neutral-400">
              {view.notes.map((n) => (
                <li key={n}>• {n}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  tone,
  small,
}: {
  label: string;
  value: string;
  hint: string;
  tone: string;
  small?: boolean;
}) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`mt-1 font-bold ${small ? "text-sm" : "text-2xl"} ${tone}`}>{value}</p>
      <p className="mt-1 text-xs text-neutral-400">{hint}</p>
    </div>
  );
}

/** Linha de custo fixo/overhead (não é um grupo com categorias — valor único, sempre negativo). */
function FixedRow({ label, cents }: { label: string; cents: number }) {
  return (
    <div className="flex items-center justify-between rounded-2xl bg-white px-5 py-3 shadow-sm">
      <span className="font-semibold text-neutral-800">{label}</span>
      <span className={`font-semibold ${cents < 0 ? "text-danger" : "text-neutral-800"}`}>
        {formatBRL(cents)}
      </span>
    </div>
  );
}

function GroupRow({ group }: { group: DreGroup }) {
  const [expanded, setExpanded] = useState(false);
  const negative = group.total_cents < 0;
  const label = group.grupo_dre === "RECEITA" ? "Receita" : "Custo Direto";
  const totalCount = group.categorias.reduce((s, c) => s + c.count, 0);

  return (
    <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-neutral-50/60"
      >
        <span className="flex items-center gap-2">
          <ChevronDown
            size={18}
            className={`text-neutral-400 transition-transform ${expanded ? "" : "-rotate-90"}`}
          />
          <span className="font-semibold text-neutral-800">{label}</span>
          {totalCount > 0 && (
            <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
              {totalCount}
            </span>
          )}
        </span>
        <span className={`font-semibold ${negative ? "text-danger" : "text-neutral-800"}`}>
          {formatBRL(group.total_cents)}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-neutral-100">
          {group.categorias.length === 0 ? (
            <p className="px-5 py-3 text-sm text-neutral-400">Sem lançamentos neste período.</p>
          ) : (
            <ul className="divide-y divide-neutral-50">
              {group.categorias.map((c) => (
                <li
                  key={c.categoria}
                  className="flex items-center justify-between px-5 py-2.5 text-sm"
                >
                  <span className="text-neutral-700">
                    {c.categoria}
                    <span className="ml-2 text-xs text-neutral-400">
                      {c.count} {c.count === 1 ? "lançamento" : "lançamentos"}
                    </span>
                  </span>
                  <span className={c.amount_cents < 0 ? "text-danger" : "text-neutral-700"}>
                    {formatBRL(c.amount_cents)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
