// apps/web/src/features/financeiro/LucratividadePage.tsx
import { useCallback, useEffect, useState } from "react";
import Drawer from "../../components/Drawer";
import { api, apiErrorMessage } from "../../lib/api";
import { formatBRL } from "./dre";
import { sortDescending, statusLabel, type LedgerEntry } from "./ledger";
import { computeTotals, sortByMargin, type ContractDreSummary } from "./lucratividade";
import PeriodPicker from "./PeriodPicker";
import { resolvePeriod, type PeriodRange } from "./periodRange";

/**
 * Lucratividade por Contrato (Story 5.12) — ranking de todos os contratos ASSINADOS por margem
 * de contribuição, com "Detalhes" abrindo o extrato cronológico de lançamentos do contrato.
 * Read-only: só lê agregações do backend, não altera nada. Design "Portal".
 */
export default function LucratividadePage() {
  const [period, setPeriod] = useState<PeriodRange>(() => resolvePeriod("this_year"));
  const [includeOverhead, setIncludeOverhead] = useState(false);
  const [rows, setRows] = useState<ContractDreSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailContract, setDetailContract] = useState<ContractDreSummary | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const { data } = await api.get<ContractDreSummary[]>("/financial-intelligence/contracts-dre", {
        params: { start: period.start, end: period.end, include_overhead: includeOverhead },
      });
      setRows(sortByMargin(data));
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [period, includeOverhead]);

  useEffect(() => {
    load();
  }, [load]);

  const openDetails = useCallback(
    async (row: ContractDreSummary) => {
      setDetailContract(row);
      setLedgerLoading(true);
      try {
        const { data } = await api.get<LedgerEntry[]>(
          `/financial-intelligence/contracts/${row.contract_id}/ledger`,
          { params: { start: period.start, end: period.end } },
        );
        setLedger(sortDescending(data));
      } catch (err) {
        setError(apiErrorMessage(err));
      } finally {
        setLedgerLoading(false);
      }
    },
    [period],
  );

  const totals = computeTotals(rows);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Lucratividade</p>
          <h1 className="text-2xl font-bold text-neutral-800">Lucratividade por Contrato</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Ranking dos contratos assinados por margem de contribuição, em regime de competência.
          </p>
        </div>
        <PeriodPicker value={period} onChange={setPeriod} />
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <KpiCard label="Receita total" value={formatBRL(totals.receita_cents)} />
        <KpiCard label="Custo direto" value={formatBRL(totals.custo_direto_cents)} />
        <KpiCard
          label="Margem % média"
          value={
            totals.margem_pct_media === null
              ? "—"
              : `${(totals.margem_pct_media * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`
          }
        />
        <KpiCard label="Overhead" value={formatBRL(totals.overhead_cents)} />
        <KpiCard label="Resultado" value={formatBRL(totals.resultado_cents)} />
      </div>

      <label className="flex items-center gap-2 text-sm text-neutral-600">
        <input
          type="checkbox"
          checked={includeOverhead}
          onChange={(e) => setIncludeOverhead(e.target.checked)}
          className="h-4 w-4 rounded border-neutral-300"
        />
        Ratear overhead da empresa em todas as linhas
      </label>

      <div className="overflow-x-auto rounded-2xl bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
              <th className="px-4 py-3">Contrato</th>
              <th className="px-4 py-3 text-right">Receita</th>
              <th className="px-4 py-3 text-right">Custo direto</th>
              <th className="px-4 py-3 text-right">Margem</th>
              <th className="px-4 py-3 text-right">Margem %</th>
              <th className="px-4 py-3 text-right">Overhead</th>
              <th className="px-4 py-3 text-right">Resultado</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className="px-4 py-3 text-neutral-400" colSpan={8}>Carregando…</td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td className="px-4 py-3 text-neutral-400" colSpan={8}>Nenhum contrato assinado.</td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.contract_id} className="border-b border-neutral-50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-neutral-800">{r.title}</div>
                    {r.client_name && <div className="text-xs text-neutral-400">{r.client_name}</div>}
                  </td>
                  <td className="px-4 py-3 text-right">{formatBRL(r.receita_cents)}</td>
                  <td className="px-4 py-3 text-right">{formatBRL(r.custo_direto_cents)}</td>
                  <td className={`px-4 py-3 text-right ${r.margem_contribuicao_cents < 0 ? "text-danger" : ""}`}>
                    {formatBRL(r.margem_contribuicao_cents)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {r.margem_contribuicao_pct === null
                      ? "—"
                      : `${(r.margem_contribuicao_pct * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`}
                  </td>
                  <td className="px-4 py-3 text-right">{formatBRL(r.overhead_allocated_cents)}</td>
                  <td className={`px-4 py-3 text-right font-semibold ${r.resultado_cents < 0 ? "text-danger" : ""}`}>
                    {formatBRL(r.resultado_cents)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => openDetails(r)}
                      className="rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50"
                    >
                      Detalhes
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Drawer
        title={detailContract?.title ?? ""}
        subtitle={detailContract ? `${period.start} a ${period.end}` : undefined}
        open={detailContract !== null}
        onClose={() => setDetailContract(null)}
      >
        {ledgerLoading ? (
          <p className="text-sm text-neutral-400">Carregando…</p>
        ) : ledger.length === 0 ? (
          <p className="text-sm text-neutral-400">Sem lançamentos neste período.</p>
        ) : (
          <ul className="divide-y divide-neutral-50">
            {ledger.map((e) => (
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
                <p className="text-xs text-neutral-400">{e.date} · {e.categoria}</p>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <p className="text-xs uppercase text-neutral-400">{label}</p>
      <p className="mt-1 text-lg font-bold text-neutral-800">{value}</p>
    </div>
  );
}
