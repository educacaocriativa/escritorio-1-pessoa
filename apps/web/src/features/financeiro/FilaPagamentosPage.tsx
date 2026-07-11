import type { Payable, PaymentQueue } from "@e1p/shared-types";
import { AlertTriangle, CalendarClock, CalendarDays, CalendarRange, Check } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

/**
 * Fila de Pagamentos (Story 5.9) — painel único do que pagar hoje e nos próximos dias, com baixa em
 * um clique. É uma VISÃO nova sobre `Payable` (o mesmo dado de Contas a Pagar): "Marcar pago" chama
 * o `mark_paid` já existente, então reflete na tela de Contas a Pagar (mesmo registro, sem duplicar).
 * Sem papéis/permissão nova — qualquer usuário do módulo financeiro vê e paga (AC3).
 */
const brl = (c: number) =>
  (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const EMPTY: PaymentQueue = {
  atrasados: [],
  hoje: [],
  proximos_7_dias: [],
  proximos_30_dias: [],
  summary: {
    atrasados_count: 0,
    atrasados_cents: 0,
    hoje_count: 0,
    hoje_cents: 0,
    proximos_7_dias_count: 0,
    proximos_7_dias_cents: 0,
    proximos_30_dias_count: 0,
    proximos_30_dias_cents: 0,
  },
};

export default function FilaPagamentosPage() {
  const [queue, setQueue] = useState<PaymentQueue>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<PaymentQueue>("/payables/queue");
      setQueue({ ...EMPTY, ...data });
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pay = useCallback(
    async (id: string) => {
      setPaying(id);
      try {
        // Reusa o mesmo endpoint de Contas a Pagar (mark_paid, lock FOR UPDATE) — sem fluxo novo.
        await api.post(`/payables/bills/${id}/pay`);
        await load();
      } catch (err) {
        setError(apiErrorMessage(err));
      } finally {
        setPaying(null);
      }
    },
    [load],
  );

  const s = queue.summary;
  const totalPendente =
    s.atrasados_cents + s.hoje_cents + s.proximos_7_dias_cents + s.proximos_30_dias_cents;
  const nada =
    !loading &&
    queue.atrasados.length === 0 &&
    queue.hoje.length === 0 &&
    queue.proximos_7_dias.length === 0 &&
    queue.proximos_30_dias.length === 0;

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Financeiro / Fila de pagamentos</p>
        <h1 className="text-2xl font-bold text-neutral-800">Fila de pagamentos</h1>
        <p className="mt-1 max-w-2xl text-sm text-neutral-500">
          O que pagar hoje e nos próximos dias, tudo junto — com baixa em um clique. É o mesmo dado
          de Contas a Pagar: marcar pago aqui reflete lá.
        </p>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Atrasados" value={brl(s.atrasados_cents)} count={s.atrasados_count} tone="text-danger" />
        <Stat label="Hoje" value={brl(s.hoje_cents)} count={s.hoje_count} tone="text-amber-700" />
        <Stat label="Próximos 7 dias" value={brl(s.proximos_7_dias_cents)} count={s.proximos_7_dias_count} tone="text-neutral-700" />
        <Stat label="Próximos 30 dias" value={brl(s.proximos_30_dias_cents)} count={s.proximos_30_dias_count} tone="text-neutral-700" />
      </div>

      {loading && <p className="text-sm text-neutral-400">Carregando fila…</p>}

      {nada && (
        <div className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">
          Nada a pagar nos próximos 30 dias. 🎉
        </div>
      )}

      {!loading && !nada && (
        <div className="space-y-5">
          <Bucket
            title="Atrasados"
            hint="venceram e seguem em aberto"
            icon={<AlertTriangle size={16} className="text-danger" />}
            items={queue.atrasados}
            onPay={pay}
            paying={paying}
          />
          <Bucket
            title="Hoje"
            hint="vencem hoje"
            icon={<CalendarDays size={16} className="text-amber-600" />}
            items={queue.hoje}
            onPay={pay}
            paying={paying}
          />
          <Bucket
            title="Próximos 7 dias"
            hint="vencem nesta semana"
            icon={<CalendarClock size={16} className="text-primary-500" />}
            items={queue.proximos_7_dias}
            onPay={pay}
            paying={paying}
          />
          <Bucket
            title="Próximos 30 dias"
            hint="vencem no mês"
            icon={<CalendarRange size={16} className="text-neutral-500" />}
            items={queue.proximos_30_dias}
            onPay={pay}
            paying={paying}
          />
        </div>
      )}

      {!nada && (
        <p className="text-right text-xs text-neutral-400">
          Total pendente na fila (30 dias): <strong>{brl(totalPendente)}</strong>
        </p>
      )}
    </div>
  );
}

function Bucket({
  title,
  hint,
  icon,
  items,
  onPay,
  paying,
}: {
  title: string;
  hint: string;
  icon: ReactNode;
  items: Payable[];
  onPay: (id: string) => void;
  paying: string | null;
}) {
  if (items.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-3">
        {icon}
        <h2 className="font-semibold text-neutral-800">{title}</h2>
        <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
          {items.length}
        </span>
        <span className="text-xs text-neutral-400">— {hint}</span>
      </div>
      <ul className="divide-y divide-neutral-50">
        {items.map((p) => (
          <li key={p.id} className="flex items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <span className="text-neutral-800">{p.description || p.supplier || "Conta"}</span>
              <span className="block text-xs text-neutral-400">
                {p.supplier ? `${p.supplier} · ` : ""}
                vence {new Date(p.due_date + "T00:00").toLocaleDateString("pt-BR")}
              </span>
            </div>
            <span className="shrink-0 font-medium tabular-nums text-neutral-800">
              {brl(p.amount_cents)}
            </span>
            <button
              onClick={() => onPay(p.id)}
              disabled={paying === p.id}
              className="flex shrink-0 items-center gap-1.5 rounded-pill bg-accent-400 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
            >
              <Check size={13} />
              {paying === p.id ? "Pagando…" : "Marcar pago"}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Stat({
  label,
  value,
  count,
  tone,
}: {
  label: string;
  value: string;
  count: number;
  tone: string;
}) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
      <p className="text-xs text-neutral-400">{count} {count === 1 ? "conta" : "contas"}</p>
    </div>
  );
}
