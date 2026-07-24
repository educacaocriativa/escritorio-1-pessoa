// apps/web/src/features/financeiro/DrePage.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import Drawer from "../../components/Drawer";
import { api, apiErrorMessage } from "../../lib/api";
import { formatBRL } from "./dre";
import {
  investmentTotals,
  matrixGroupLabel,
  splitGroupsAroundInvestment,
  type DreMatrixGroup,
  type DreMatrixReport,
  type DreMatrixRow,
  type GroupBy,
} from "./dreMatrix";
import { sortDescending, type DreMatrixEntry } from "./dreMatrixEntries";
import { statusLabel } from "./ledger";
import PeriodPicker from "./PeriodPicker";
import { monthKeyToRange, resolvePeriod, type PeriodRange } from "./periodRange";

interface CellSelection {
  row: DreMatrixRow;
  group: DreMatrixGroup;
  month: string;
}

/**
 * DRE em matriz mensal (Story 5.11) — meses nas colunas, categorias nas linhas, agrupável por
 * grupo DRE ou por centro de custo. Substitui a DRE de período único (Story 5.3). Read-only: só
 * lê a agregação do backend, não altera nada. Design "Portal".
 */
export default function DrePage() {
  const [period, setPeriod] = useState<PeriodRange>(() => resolvePeriod("this_year"));
  const [groupBy, setGroupBy] = useState<GroupBy>("dre");
  const [report, setReport] = useState<DreMatrixReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [cell, setCell] = useState<CellSelection | null>(null);
  const [entries, setEntries] = useState<DreMatrixEntry[]>([]);
  const [entriesLoading, setEntriesLoading] = useState(false);
  const [entriesError, setEntriesError] = useState<string | null>(null);
  const entriesSeq = useRef(0);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.get<DreMatrixReport>("/financial-intelligence/dre/matrix", {
        params: { start: period.start, end: period.end, group_by: groupBy },
      });
      setReport(data);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [period, groupBy]);

  useEffect(() => {
    load();
  }, [load]);

  const openCell = useCallback(
    async (selection: CellSelection) => {
      const seq = ++entriesSeq.current;
      setCell(selection);
      setEntriesError(null);
      setEntriesLoading(true);
      try {
        const { start, end } = monthKeyToRange(selection.month);
        const { data } = await api.get<DreMatrixEntry[]>(
          "/financial-intelligence/dre/matrix/entries",
          {
            params: {
              start,
              end,
              categoria: selection.row.label,
              grupo_dre: selection.row.grupo_dre ?? undefined,
              cost_center_id: groupBy === "cost_center" ? selection.group.key : undefined,
            },
          },
        );
        if (seq !== entriesSeq.current) return; // resposta obsoleta — outra célula já foi aberta
        setEntries(sortDescending(data));
      } catch (err) {
        if (seq !== entriesSeq.current) return;
        setEntriesError(apiErrorMessage(err));
      } finally {
        if (seq === entriesSeq.current) setEntriesLoading(false);
      }
    },
    [groupBy],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / DRE</p>
          <h1 className="text-2xl font-bold text-neutral-800">DRE por categoria</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Demonstrativo de resultado mês a mês, em regime de competência. Agrupe por grupo DRE
            ou por centro de custo e escolha o período.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            aria-label="Agrupar por"
            className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="dre">Por grupo DRE</option>
            <option value="cost_center">Por centro de custo</option>
          </select>
          <PeriodPicker value={period} onChange={setPeriod} />
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {report && (
        <div className="rounded-2xl bg-white p-5 shadow-sm">
          <p className="text-sm text-neutral-500">Resultado do período</p>
          <p className={`mt-1 text-3xl font-bold ${report.grand_total >= 0 ? "text-emerald-600" : "text-danger"}`}>
            {loading ? "…" : formatBRL(report.grand_total)}
          </p>
        </div>
      )}

      {report && (
        <div className="overflow-x-auto rounded-2xl bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="sticky left-0 bg-white px-4 py-3">Categoria</th>
                {report.months.map((m) => (
                  <th key={m} className="px-4 py-3 text-right">{m}</th>
                ))}
                <th className="px-4 py-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                const { before, after } = splitGroupsAroundInvestment(report.groups, groupBy);
                const investment = investmentTotals(report);
                const combinedMonthly = report.grand_total_cents.map((c, i) => c + investment.monthly[i]);
                const combinedTotal = report.grand_total + investment.total;
                return (
                  <>
                    {before.map((g) => (
                      <MatrixGroupRows key={g.key} group={g} groupBy={groupBy} months={report.months} onCellClick={openCell} />
                    ))}
                    <tr className="border-t-2 border-neutral-200 font-bold">
                      <td className="sticky left-0 bg-white px-4 py-3">TOTAL GERAL</td>
                      {report.grand_total_cents.map((c, i) => (
                        <td key={i} className="px-4 py-3 text-right">{formatBRL(c)}</td>
                      ))}
                      <td className="px-4 py-3 text-right">{formatBRL(report.grand_total)}</td>
                    </tr>
                    {after.map((g) => (
                      <MatrixGroupRows key={g.key} group={g} groupBy={groupBy} months={report.months} onCellClick={openCell} />
                    ))}
                    <tr className="border-t-2 border-neutral-800 bg-neutral-50 font-bold">
                      <td className="sticky left-0 bg-neutral-50 px-4 py-3">TOTAL GERAL + INVESTIMENTO</td>
                      {combinedMonthly.map((c, i) => (
                        <td key={i} className="px-4 py-3 text-right">{formatBRL(c)}</td>
                      ))}
                      <td className="px-4 py-3 text-right">{formatBRL(combinedTotal)}</td>
                    </tr>
                  </>
                );
              })()}
            </tbody>
          </table>
        </div>
      )}

      {report && report.notes.length > 0 && (
        <ul className="space-y-1 text-xs text-neutral-400">
          {report.notes.map((n) => (
            <li key={n}>• {n}</li>
          ))}
        </ul>
      )}

      <Drawer
        title={cell ? cell.row.label : ""}
        subtitle={cell ? `${matrixGroupLabel(cell.group, groupBy)} · ${cell.month}` : undefined}
        open={cell !== null}
        onClose={() => setCell(null)}
      >
        {entriesError && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{entriesError}</p>}
        {entriesLoading ? (
          <p className="text-sm text-neutral-400">Carregando…</p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-neutral-400">Sem lançamentos neste período.</p>
        ) : (
          <ul className="divide-y divide-neutral-50">
            {entries.map((e) => (
              <li key={e.id} className="py-3">
                <div className="flex items-center justify-between">
                  <span className={`font-semibold ${e.amount_cents < 0 ? "text-danger" : "text-emerald-600"}`}>
                    {formatBRL(e.amount_cents)}
                  </span>
                  <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                    {statusLabel(e.status)}
                  </span>
                </div>
                <p className="mt-1 text-sm text-neutral-700">{e.description}</p>
                <p className="text-xs text-neutral-400">{e.date}</p>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  );
}

function MatrixGroupRows({
  group,
  groupBy,
  months,
  onCellClick,
}: {
  group: DreMatrixGroup;
  groupBy: GroupBy;
  months: string[];
  onCellClick: (selection: CellSelection) => void;
}) {
  const monthsCount = group.subtotal_cents.length;
  const isUncategorized = group.rows.length > 0 && group.rows.every((r) => r.kind === "uncategorized");
  return (
    <>
      <tr className={isUncategorized ? "bg-amber-50" : "bg-neutral-50/60"}>
        <td
          className="sticky left-0 bg-inherit px-4 py-2 font-semibold text-neutral-800"
          colSpan={2 + monthsCount}
        >
          {matrixGroupLabel(group, groupBy)}
        </td>
      </tr>
      {group.rows.map((r) => (
        <tr key={r.label} className={r.kind === "informational" ? "text-neutral-400" : ""}>
          <td className="sticky left-0 bg-white px-4 py-2 pl-8">{r.label}</td>
          {r.monthly_cents.map((c, i) => (
            <td key={i} className="px-4 py-2 text-right">
              <button
                type="button"
                onClick={() => onCellClick({ row: r, group, month: months[i] })}
                className={`w-full text-right hover:underline ${c < 0 ? "text-danger" : ""}`}
              >
                {formatBRL(c)}
              </button>
            </td>
          ))}
          <td className={`px-4 py-2 text-right font-medium ${r.total_cents < 0 ? "text-danger" : ""}`}>
            {formatBRL(r.total_cents)}
          </td>
        </tr>
      ))}
      <tr className="font-semibold">
        <td className="sticky left-0 bg-white px-4 py-2 pl-8">Subtotal</td>
        {group.subtotal_cents.map((c, i) => (
          <td key={i} className="px-4 py-2 text-right">{formatBRL(c)}</td>
        ))}
        <td className="px-4 py-2 text-right">{formatBRL(group.subtotal_total)}</td>
      </tr>
    </>
  );
}
