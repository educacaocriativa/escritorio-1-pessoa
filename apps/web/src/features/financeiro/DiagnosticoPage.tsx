import { ChevronLeft, ChevronRight, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import {
  countByLevel,
  currentMonth,
  type Diagnostics,
  monthRange,
  type Signal,
  signalVisual,
  sourceLabel,
} from "./diagnostico";

/**
 * Diagnóstico financeiro (Story 5.8). Mostra PRIMEIRO os sinais determinísticos 🟢🟡🔴 (com a
 * explicação numérica SEMPRE visível, mesmo sem IA) e, num bloco separado e visualmente distinto, a
 * narrativa em linguagem natural — gerada pela IA quando disponível ou por um fallback de template.
 * Read-only: só lê o diagnóstico do backend. Rota /financeiro/diagnostico. Design "Portal".
 */
function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export default function DiagnosticoPage() {
  const [month, setMonth] = useState(currentMonth);
  const [data, setData] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    const { start, end } = monthRange(month);
    try {
      const res = await api.get<Diagnostics>("/financial-intelligence/diagnostics", {
        params: { start, end },
      });
      setData(res.data);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    load();
  }, [load]);

  const counts = useMemo(
    () => (data ? countByLevel(data.signals) : { vermelho: 0, amarelo: 0, verde: 0 }),
    [data],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Diagnóstico</p>
          <h1 className="text-2xl font-bold text-neutral-800">Diagnóstico financeiro</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Sinais de alerta calculados por regras determinísticas — os números vêm primeiro. A
            leitura em linguagem natural, quando disponível, é escrita pela IA a partir dos mesmos
            sinais (nunca inventa dados).
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-pill bg-white p-1 shadow-sm">
          <button
            type="button"
            aria-label="Mês anterior"
            onClick={() => setMonth((mo) => shiftMonth(mo, -1))}
            className="rounded-full p-1.5 text-neutral-500 hover:bg-neutral-100"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="min-w-[5rem] text-center text-sm font-medium text-neutral-700">
            {month}
          </span>
          <button
            type="button"
            aria-label="Próximo mês"
            onClick={() => setMonth((mo) => shiftMonth(mo, 1))}
            className="rounded-full p-1.5 text-neutral-500 hover:bg-neutral-100"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
      {loading && <p className="text-sm text-neutral-400">Carregando diagnóstico…</p>}

      {data && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <CountCard level="vermelho" count={counts.vermelho} />
            <CountCard level="amarelo" count={counts.amarelo} />
            <CountCard level="verde" count={counts.verde} />
          </div>

          {/* Sinais determinísticos — SEMPRE presentes (mesmo sem IA). */}
          <section className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
              Sinais determinísticos
            </h2>
            {data.signals.length === 0 ? (
              <p className="rounded-2xl bg-white p-6 text-center text-sm text-neutral-400 shadow-sm">
                Nenhum sinal de alerta no período — nenhum risco relevante detectado.
              </p>
            ) : (
              <ul className="space-y-2">
                {data.signals.map((s, i) => (
                  <SignalCard key={`${s.source}-${s.title}-${i}`} signal={s} />
                ))}
              </ul>
            )}
          </section>

          {/* Narrativa — bloco visualmente distinto, DEPOIS dos números. */}
          <NarrativeCard narrative={data.narrative} source={data.narrative_source} />
        </>
      )}
    </div>
  );
}

function CountCard({ level, count }: { level: Signal["level"]; count: number }) {
  const v = signalVisual(level);
  return (
    <div className="rounded-2xl bg-white p-4 text-center shadow-sm">
      <p className="text-2xl">{v.emoji}</p>
      <p className="mt-1 text-2xl font-bold text-neutral-800">{count}</p>
      <p className="text-xs text-neutral-500">{v.label}</p>
    </div>
  );
}

function SignalCard({ signal }: { signal: Signal }) {
  const v = signalVisual(signal.level);
  return (
    <li className={`flex items-start gap-3 rounded-2xl p-4 ${v.cardClass}`}>
      <span className="text-xl leading-none">{v.emoji}</span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-semibold text-neutral-800">{signal.title}</p>
          <span className={`rounded-pill px-2 py-0.5 text-[11px] font-medium ${v.badgeClass}`}>
            {v.label}
          </span>
        </div>
        {/* Explicação NUMÉRICA — sempre visível, é a base sólida do diagnóstico. */}
        <p className="mt-1 text-sm text-neutral-700">{signal.explanation}</p>
        <p className="mt-1 text-xs text-neutral-400">{sourceLabel(signal.source)}</p>
      </div>
    </li>
  );
}

function NarrativeCard({ narrative, source }: { narrative: string; source: "ai" | "template" }) {
  const isAi = source === "ai";
  return (
    <section className="rounded-2xl bg-primary-50 p-5 ring-1 ring-primary-100">
      <div className="flex items-center gap-2">
        <Sparkles size={16} className="text-primary-600" />
        <h2 className="text-sm font-semibold text-primary-700">
          {isAi ? "Leitura da IA" : "Resumo (sem IA)"}
        </h2>
      </div>
      <p className="mt-2 whitespace-pre-line text-sm text-neutral-700">{narrative}</p>
      <p className="mt-3 text-xs text-neutral-400">
        {isAi
          ? "Texto escrito pela IA a partir dos sinais acima — os números vêm do motor determinístico, não da IA."
          : "IA indisponível — resumo montado por template a partir dos mesmos sinais determinísticos."}
      </p>
    </section>
  );
}
