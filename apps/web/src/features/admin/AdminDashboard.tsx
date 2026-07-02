import type { PlatformEarningsSummary, SplitRates } from "@e1p/shared-types";
import { Building2, GraduationCap, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import PlatformCustomers from "./PlatformCustomers";
import PlatformUsers from "./PlatformUsers";

const brl = (cents: number) =>
  (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

type Tab = "offices" | "customers" | "settings";

const TABS: { key: Tab; label: string; icon: typeof Building2 }[] = [
  { key: "offices", label: "Escritórios", icon: Building2 },
  { key: "customers", label: "Clientes", icon: GraduationCap },
  { key: "settings", label: "Configurações", icon: SlidersHorizontal },
];

export default function AdminDashboard() {
  const [tab, setTab] = useState<Tab>("offices");

  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-neutral-500">Página / Administração</p>
        <h1 className="text-2xl font-bold text-neutral-800">Plataforma</h1>
      </div>

      {/* Abas — uma seção por responsabilidade (menos poluição). */}
      <div className="flex gap-1 rounded-xl bg-neutral-100 p-1">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm font-semibold transition ${
                active ? "bg-white text-primary-600 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
              }`}
            >
              <Icon size={16} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "offices" && <PlatformUsers />}
      {tab === "customers" && <PlatformCustomers />}
      {tab === "settings" && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SplitRatesCard />
          <PlatformEarningsCard />
        </div>
      )}
    </div>
  );
}

function SplitRatesCard() {
  const [rates, setRates] = useState<SplitRates>({
    product_pct: 40,
    service_pct: 30,
    recurring_pct: 20,
  });
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<SplitRates>("/wallet/split-rates").then(({ data }) => setRates(data));
  }, []);

  function set(key: keyof SplitRates, v: string) {
    setSaved(false);
    setRates((r) => ({ ...r, [key]: Number(v) }));
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const { data } = await api.put<SplitRates>("/wallet/split-rates", rates);
      setRates(data);
      setSaved(true);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const row = (label: string, key: keyof SplitRates) => (
    <div className="flex items-center justify-between">
      <span className="text-sm text-neutral-600">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          min={0}
          max={95}
          value={rates[key]}
          onChange={(e) => set(key, e.target.value)}
          className="w-16 rounded-lg border border-neutral-200 px-2 py-1 text-right text-sm outline-none focus:border-primary-400"
        />
        <span className="text-sm text-neutral-400">%</span>
      </div>
    </div>
  );

  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h3 className="mb-1 font-semibold text-neutral-800">Taxas de split</h3>
      <p className="mb-4 text-xs text-neutral-400">
        Percentual retido pela plataforma por tipo de venda.
      </p>
      <div className="space-y-3">
        {row("Produtos", "product_pct")}
        {row("Serviços", "service_pct")}
        {row("Recorrentes", "recurring_pct")}
      </div>
      {error && <p className="mt-3 rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
      <button
        onClick={save}
        disabled={saving}
        className="mt-4 w-full rounded-pill bg-accent-400 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
      >
        {saving ? "Salvando..." : saved ? "Salvo ✓" : "Salvar taxas"}
      </button>
    </div>
  );
}

function PlatformEarningsCard() {
  const [e, setE] = useState<PlatformEarningsSummary | null>(null);
  useEffect(() => {
    api.get<PlatformEarningsSummary>("/wallet/platform-earnings").then(({ data }) => setE(data));
  }, []);
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h3 className="mb-4 font-semibold text-neutral-800">Ganhos da plataforma</h3>
      <div className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-neutral-500">Volume transacionado (GMV)</span>
          <span className="font-medium tabular-nums">{e ? brl(e.gmv_cents) : "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">Taxas retidas</span>
          <span className="font-bold tabular-nums text-accent-700">
            {e ? brl(e.fees_cents) : "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-neutral-500">Transações</span>
          <span className="tabular-nums">{e?.transaction_count ?? "—"}</span>
        </div>
      </div>
    </div>
  );
}
