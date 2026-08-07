import type { TenantProfile } from "@e1p/shared-types";
import { Building2, Check, Filter, MessageCircle, Workflow } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { formatTime } from "../../lib/datetime";
import { applyBrandTheme } from "../../lib/theme";
import { useFuso } from "../../store/auth";
import CanaisTab from "./CanaisTab";
import EmpresaTab from "./EmpresaTab";
import IntegracoesTab from "./IntegracoesTab";
import VendasTab from "./VendasTab";

type Tab = "empresa" | "canais" | "integracoes" | "vendas";

const TABS: { key: Tab; label: string; icon: typeof Building2 }[] = [
  { key: "empresa", label: "Empresa", icon: Building2 },
  { key: "canais", label: "Canais", icon: MessageCircle },
  { key: "integracoes", label: "Integrações", icon: Workflow },
  { key: "vendas", label: "Vendas", icon: Filter },
];

/** Abas cujo conteúdo edita o perfil do tenant — só nelas o botão Salvar faz sentido. */
const PERFIL_TABS: Tab[] = ["empresa", "vendas"];

export default function ConfiguracoesPage() {
  const fuso = useFuso();
  const [tab, setTab] = useState<Tab>("empresa");
  const [p, setP] = useState<TenantProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const { data } = await api.get<TenantProfile>("/settings/profile");
    setP(data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (!p) return <div className="p-8 text-sm text-neutral-400">Carregando...</div>;

  const set = (patch: Partial<TenantProfile>) => setP({ ...p, ...patch });
  const editandoPerfil = PERFIL_TABS.includes(tab);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.patch<TenantProfile>("/settings/profile", p);
      setP(data);
      applyBrandTheme(data);
      setSavedAt(formatTime(new Date().toISOString(), fuso));
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-neutral-500">Página / Configurações</p>
          <h1 className="text-2xl font-bold text-neutral-800">Configurações</h1>
        </div>
        <div className="flex items-center gap-3">
          {editandoPerfil && savedAt && !error && (
            <span className="text-xs text-neutral-400">Salvo {savedAt}</span>
          )}
          {editandoPerfil && (
            <button onClick={save} disabled={saving} className="flex items-center gap-1.5 rounded-pill bg-accent-400 px-5 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-50">
              <Check size={14} /> {saving ? "Salvando..." : "Salvar"}
            </button>
          )}
        </div>
      </div>
      {editandoPerfil && error && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>
      )}

      {/* Abas — uma área por assunto (menos poluição). */}
      <div className="flex gap-1 overflow-x-auto rounded-xl bg-neutral-100 p-1 lg:w-fit">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex shrink-0 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition ${
                active ? "bg-white text-primary-600 shadow-sm" : "text-neutral-500 hover:text-neutral-700"
              }`}
            >
              <Icon size={16} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "empresa" && <EmpresaTab p={p} set={set} />}
      {tab === "canais" && <CanaisTab />}
      {tab === "integracoes" && <IntegracoesTab />}
      {tab === "vendas" && (
        <VendasTab
          value={p.default_entry_funnel_id}
          onChange={(v) => set({ default_entry_funnel_id: v })}
        />
      )}
    </div>
  );
}
