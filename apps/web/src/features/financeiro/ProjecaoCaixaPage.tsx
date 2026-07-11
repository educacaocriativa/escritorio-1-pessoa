import { AlertTriangle, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import {
  formatBRL,
  type Projection,
  runwayLabel,
  toPolylinePoints,
  trajectoryPoints,
} from "./projecao";

/**
 * Projeção de fluxo de caixa 30/60/90 dias + runway (Story 5.7) — regime de CAIXA. Read-only: só lê
 * a projeção do backend (não escreve nada). Design "Portal": três cartões (janelas) + runway em
 * destaque + gráfico simples da trajetória do saldo.
 */
export default function ProjecaoCaixaPage() {
  const [projection, setProjection] = useState<Projection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get<Projection>("/financial-intelligence/projection")
      .then((r) => setProjection(r.data))
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Financeiro / Projeção de caixa</p>
        <h1 className="text-2xl font-bold text-neutral-800">Projeção de fluxo de caixa</h1>
        <p className="mt-1 max-w-2xl text-sm text-neutral-500">
          Para onde o caixa caminha em 30, 60 e 90 dias — em regime de caixa (data de pagamento
          prevista dos lançamentos em aberto). Partindo do disponível atual da Carteira.
        </p>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
      {loading && <p className="text-sm text-neutral-400">Carregando projeção…</p>}

      {projection && (
        <>
          <RunwayCard projection={projection} />

          <div className="grid gap-4 sm:grid-cols-3">
            {projection.windows.map((w) => (
              <WindowCard key={w.days} days={w.days} cents={w.saldo_projetado_cents} alert={w.alert} />
            ))}
          </div>

          <TrajectoryChart projection={projection} />

          {(projection.overdue_inflow_cents > 0 || projection.overdue_outflow_cents > 0) && (
            <div className="flex items-start gap-2 rounded-xl bg-amber-50 p-3 text-xs text-amber-700 ring-1 ring-amber-200">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <p>
                A projeção inclui itens <strong>vencidos e ainda em aberto</strong> como caixa
                esperado imediato: {formatBRL(projection.overdue_inflow_cents)} a receber e{" "}
                {formatBRL(projection.overdue_outflow_cents)} a pagar em atraso. Recebíveis vencidos
                podem não se concretizar — leia a projeção com cautela.
              </p>
            </div>
          )}

          {projection.notes.length > 0 && (
            <ul className="space-y-1 text-xs text-neutral-400">
              {projection.notes.map((n) => (
                <li key={n}>• {n}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function RunwayCard({ projection }: { projection: Projection }) {
  const { runway, saldo_inicial_cents } = projection;
  const noRisk = runway.days === null;
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Runway (fôlego de caixa)</p>
          <p
            className={`mt-1 text-3xl font-bold ${noRisk ? "text-emerald-600" : "text-neutral-800"}`}
          >
            {runwayLabel(runway.days)}
          </p>
          <p className="mt-1 text-xs text-neutral-400">
            {noRisk
              ? "O caixa não está sendo queimado no horizonte projetado."
              : `Queima de ${formatBRL(runway.burn_rate_cents_per_day)} por dia no ritmo atual.`}
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm text-neutral-500">Disponível hoje (Carteira)</p>
          <p className="mt-1 text-xl font-semibold text-neutral-800">
            {formatBRL(saldo_inicial_cents)}
          </p>
        </div>
      </div>
    </div>
  );
}

function WindowCard({ days, cents, alert }: { days: number; cents: number; alert: boolean }) {
  return (
    <div
      className={`rounded-2xl p-5 shadow-sm ${
        alert ? "bg-red-50 ring-1 ring-red-200" : "bg-white"
      }`}
    >
      <div className="flex items-center justify-between">
        <p className="text-sm text-neutral-500">Em {days} dias</p>
        {alert ? (
          <AlertTriangle size={18} className="text-danger" />
        ) : cents >= 0 ? (
          <TrendingUp size={18} className="text-emerald-500" />
        ) : (
          <TrendingDown size={18} className="text-neutral-400" />
        )}
      </div>
      <p className={`mt-2 text-2xl font-bold ${alert ? "text-danger" : "text-neutral-800"}`}>
        {formatBRL(cents)}
      </p>
      <p className="mt-1 text-xs text-neutral-400">
        {alert ? "Caixa fica negativo nesta janela" : "Saldo projetado"}
      </p>
    </div>
  );
}

const CHART_W = 640;
const CHART_H = 160;

function TrajectoryChart({ projection }: { projection: Projection }) {
  const points = useMemo(() => trajectoryPoints(projection), [projection]);
  const poly = useMemo(
    () => toPolylinePoints(points, { width: CHART_W, height: CHART_H, padding: 12 }),
    [points],
  );
  // As mesmas coordenadas da polyline, parseadas para desenhar os marcadores nos vértices.
  const coords = useMemo(
    () => (poly ? poly.split(" ").map((p) => p.split(",").map(Number)) : []),
    [poly],
  );
  const anyAlert = projection.windows.some((w) => w.alert);
  const stroke = anyAlert ? "#dc2626" : "#5D44F8"; // vermelho se alguma janela zera; senão cor Portal

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">Trajetória do saldo</p>
      <svg
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        className="mt-3 h-40 w-full"
        role="img"
        aria-label="Gráfico da trajetória do saldo de caixa projetado ao longo de 90 dias"
        preserveAspectRatio="none"
      >
        <polyline points={poly} fill="none" stroke={stroke} strokeWidth={2.5} />
        {coords.map(([x, y], i) => (
          <circle key={points[i].days} cx={x} cy={y} r={3.5} fill={stroke} />
        ))}
      </svg>
      <div className="mt-2 flex justify-between text-xs text-neutral-400">
        <span>Hoje</span>
        <span>30d</span>
        <span>60d</span>
        <span>90d</span>
      </div>
    </div>
  );
}
