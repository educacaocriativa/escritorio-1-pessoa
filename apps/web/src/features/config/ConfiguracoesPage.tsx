import type { GoogleCalendarStatus, TenantProfile } from "@e1p/shared-types";
import { Check, Video } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  apiErrorMessage,
  disconnectGoogle,
  getGoogleConnectUrl,
  getGoogleStatus,
} from "../../lib/api";

const FONTS = ["Inter", "Poppins", "Raleway", "Georgia", "Arial"];
const safeSrc = (u: string) => (/^(https?:\/\/|\/)/i.test(u.trim()) ? u.trim() : "");

export default function ConfiguracoesPage() {
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

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.patch<TenantProfile>("/settings/profile", p);
      setP(data);
      setSavedAt(new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }));
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const colors: [string, keyof TenantProfile][] = [
    ["Cor primária", "primary_color"],
    ["Secundária", "secondary_color"],
    ["Destaque", "accent_color"],
    ["Texto", "text_color"],
    ["Fundo", "bg_color"],
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-neutral-500">Página / Configurações</p>
          <h1 className="text-2xl font-bold text-neutral-800">Configurações</h1>
        </div>
        <div className="flex items-center gap-3">
          {savedAt && !error && <span className="text-xs text-neutral-400">Salvo {savedAt}</span>}
          <button onClick={save} disabled={saving} className="flex items-center gap-1.5 rounded-pill bg-accent-400 px-5 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-50">
            <Check size={14} /> {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
      {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Formulário */}
        <div className="space-y-6 lg:col-span-2">
          <Card title="Perfil da empresa">
            <div className="grid grid-cols-2 gap-3">
              <Inp label="Nome de exibição" value={p.display_name} onChange={(v) => set({ display_name: v })} />
              <Inp label="CPF/CNPJ" value={p.document} onChange={(v) => set({ document: v })} />
              <Inp label="E-mail" value={p.email} onChange={(v) => set({ email: v })} />
              <Inp label="Telefone" value={p.phone} onChange={(v) => set({ phone: v })} />
              <Inp label="Site" value={p.website} onChange={(v) => set({ website: v })} />
              <Inp label="Endereço" value={p.address} onChange={(v) => set({ address: v })} />
            </div>
            <label className="mt-3 block">
              <span className="mb-1 block text-xs font-medium text-neutral-600">Sobre</span>
              <textarea value={p.about} onChange={(e) => set({ about: e.target.value })} rows={2} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
            </label>
          </Card>

          <Card title="Brand Kit">
            <p className="mb-3 text-xs text-neutral-400">
              Usado como padrão em propostas, contratos e carrosséis.
            </p>
            <Inp label="Logo (URL)" value={p.logo_url} onChange={(v) => set({ logo_url: v })} placeholder="https://.../logo.png" />
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {colors.map(([label, key]) => (
                <div key={key}>
                  <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
                  <div className="flex items-center gap-2">
                    <input type="color" value={p[key] as string} onChange={(e) => set({ [key]: e.target.value } as Partial<TenantProfile>)} className="h-9 w-10 cursor-pointer rounded border border-neutral-200" />
                    <input value={p[key] as string} onChange={(e) => set({ [key]: e.target.value } as Partial<TenantProfile>)} className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm uppercase outline-none" />
                  </div>
                </div>
              ))}
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-neutral-600">Fonte</span>
                <select value={p.font} onChange={(e) => set({ font: e.target.value })} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
                  {FONTS.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </label>
            </div>
          </Card>

          <GoogleSection />
        </div>

        {/* Prévia do Brand Kit */}
        <div className="lg:col-span-1">
          <Card title="Prévia">
            <div className="overflow-hidden rounded-xl" style={{ background: p.bg_color, fontFamily: p.font }}>
              <div className="px-5 py-6 text-center" style={{ borderTop: `4px solid ${p.primary_color}` }}>
                {safeSrc(p.logo_url) ? (
                  <img src={safeSrc(p.logo_url)} alt="logo" className="mx-auto mb-3 max-h-12 object-contain" />
                ) : (
                  <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full text-lg font-bold text-white" style={{ background: p.primary_color }}>
                    {(p.display_name || "E")[0]}
                  </div>
                )}
                <p className="text-lg font-bold" style={{ color: p.primary_color }}>
                  {p.display_name || "Sua empresa"}
                </p>
                <p className="mt-1 text-sm" style={{ color: p.text_color, opacity: 0.7 }}>
                  {p.about || "Identidade visual da sua marca"}
                </p>
                <div className="mt-4 inline-block rounded-pill px-5 py-2 text-sm font-bold text-white" style={{ background: p.accent_color }}>
                  Botão de ação
                </div>
              </div>
            </div>
            <div className="mt-3 flex gap-1.5">
              {[p.primary_color, p.secondary_color, p.accent_color, p.text_color].map((c, i) => (
                <span key={i} className="h-6 flex-1 rounded" style={{ background: c }} title={c} />
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

/**
 * Seção "Google Calendar": conectar/desconectar a conta Google do owner para gerar Meet
 * automaticamente na Agenda (Story 4.1). O botão "Conectar" só aparece se a plataforma tiver o
 * app OAuth configurado (`configured=true`). Trata o retorno do OAuth via `?google=connected|error`.
 */
function GoogleSection() {
  const [status, setStatus] = useState<GoogleCalendarStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await getGoogleStatus());
    } catch {
      setStatus({ configured: false, connected: false, email: null });
    }
  }, []);

  useEffect(() => {
    // Feedback do retorno do OAuth (?google=connected|error) e limpeza da query string.
    const params = new URLSearchParams(window.location.search);
    const g = params.get("google");
    if (g === "connected") setMsg({ kind: "ok", text: "Conta Google conectada com sucesso." });
    else if (g === "error") setMsg({ kind: "err", text: "Não foi possível conectar ao Google." });
    if (g) {
      params.delete("google");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }
    load();
  }, [load]);

  async function connect() {
    setBusy(true);
    setMsg(null);
    try {
      window.location.href = await getGoogleConnectUrl();
    } catch (err) {
      setMsg({ kind: "err", text: apiErrorMessage(err) });
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setMsg(null);
    try {
      await disconnectGoogle();
      await load();
      setMsg({ kind: "ok", text: "Conta Google desconectada." });
    } catch (err) {
      setMsg({ kind: "err", text: apiErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Google Calendar">
      <p className="mb-3 text-xs text-neutral-400">
        Conecte sua conta Google para gerar links do Meet automaticamente ao criar reuniões na
        Agenda. Enquanto não conectar, você continua colando o link manualmente.
      </p>
      {msg && (
        <div
          className={`mb-3 rounded-lg px-3 py-2 text-sm ${
            msg.kind === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-danger"
          }`}
        >
          {msg.text}
        </div>
      )}
      {status === null ? (
        <p className="text-sm text-neutral-400">Carregando...</p>
      ) : !status.configured ? (
        <p className="text-sm text-neutral-500">
          Integração Google não configurada nesta plataforma.
        </p>
      ) : status.connected ? (
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm text-neutral-700">
            <Video size={16} className="text-primary-600" />
            Conectado{status.email ? ` como ${status.email}` : ""}
          </div>
          <button
            onClick={disconnect}
            disabled={busy}
            className="rounded-pill border border-neutral-200 px-4 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-50 disabled:opacity-50"
          >
            Desconectar
          </button>
        </div>
      ) : (
        <button
          onClick={connect}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-pill bg-primary-600 px-5 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
        >
          <Video size={14} /> {busy ? "Redirecionando..." : "Conectar Google"}
        </button>
      )}
    </Card>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h2 className="mb-3 font-semibold text-neutral-800">{title}</h2>
      {children}
    </div>
  );
}

function Inp({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (s: string) => void; placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
    </label>
  );
}
