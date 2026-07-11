import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import type { CostCenter } from "./costCenters";
import { buildDreView, type DreReport, type DreRow, formatBRL } from "./dre";

/**
 * DRE por categoria (Story 5.3) — relatório hierárquico (grupo DRE → categoria) por período, em
 * regime de COMPETÊNCIA. Read-only: só lê a agregação do backend, não altera nada. Design "Portal".
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

export default function DrePage() {
  const [month, setMonth] = useState(currentMonth);
  const [costCenterId, setCostCenterId] = useState(""); // "" = todos os centros de custo
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [report, setReport] = useState<DreReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

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
      // visão padrão IDÊNTICA à da Story 5.3 (não quebra quem não usa a 2ª dimensão).
      const params: Record<string, string> = { start, end };
      if (costCenterId) params.cost_center_id = costCenterId;
      const { data } = await api.get<DreReport>("/financial-intelligence/dre", { params });
      setReport(data);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [month, costCenterId]);

  useEffect(() => {
    load();
  }, [load]);

  const view = useMemo(() => (report ? buildDreView(report) : null), [report]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / DRE</p>
          <h1 className="text-2xl font-bold text-neutral-800">DRE por categoria</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Demonstrativo de resultado por grupo (Receita, Custos, Despesas, Tributos, Financeiro)
            em regime de competência. Clique num grupo para ver as categorias.
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
        <ResultCard
          resultadoCents={view.resultado_cents}
          loading={loading}
        />
      )}

      <div className="space-y-3">
        {view?.rows.map((row) => (
          <GroupRow key={row.grupo_dre} row={row} />
        ))}
      </div>

      {report && report.notes.length > 0 && (
        <ul className="space-y-1 text-xs text-neutral-400">
          {report.notes.map((n) => (
            <li key={n}>• {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ResultCard({ resultadoCents, loading }: { resultadoCents: number; loading: boolean }) {
  const positive = resultadoCents >= 0;
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">Resultado do período</p>
      <p
        className={`mt-1 text-3xl font-bold ${positive ? "text-emerald-600" : "text-danger"}`}
      >
        {loading ? "…" : formatBRL(resultadoCents)}
      </p>
      <p className="mt-1 text-xs text-neutral-400">
        Receita − Custos − Despesas − Tributos ± Financeiro (Investimento e lançamentos sem
        categoria ficam de fora).
      </p>
    </div>
  );
}

function GroupRow({ row }: { row: DreRow }) {
  const [expanded, setExpanded] = useState(false);
  const negative = row.total_cents < 0;
  const isUncategorized = row.kind === "uncategorized";
  const isInformational = row.kind === "informational";
  const totalCount = row.categorias.reduce((s, c) => s + c.count, 0);

  return (
    <div
      className={`overflow-hidden rounded-2xl shadow-sm ${
        isUncategorized ? "bg-amber-50 ring-1 ring-amber-200" : "bg-white"
      }`}
    >
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-neutral-50/60"
      >
        <span className="flex items-center gap-2">
          <ChevronDown
            size={18}
            className={`text-neutral-400 transition-transform ${expanded ? "" : "-rotate-90"}`}
          />
          <span className="font-semibold text-neutral-800">{row.label}</span>
          {totalCount > 0 && (
            <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
              {totalCount}
            </span>
          )}
          {isInformational && (
            <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
              fora do resultado
            </span>
          )}
          {isUncategorized && (
            <span className="rounded-pill bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
              classifique no plano de contas
            </span>
          )}
        </span>
        <span className={`font-semibold ${negative ? "text-danger" : "text-neutral-800"}`}>
          {formatBRL(row.total_cents)}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-neutral-100">
          {row.categorias.length === 0 ? (
            <p className="px-5 py-3 text-sm text-neutral-400">Sem lançamentos neste período.</p>
          ) : (
            <ul className="divide-y divide-neutral-50">
              {row.categorias.map((c) => (
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
