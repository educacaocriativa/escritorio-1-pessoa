import type { TenantProfile } from "@e1p/shared-types";
import ImageUploadButton from "../../components/ImageUploadButton";
import { Card, Inp } from "./ui";

const FONTS = ["Inter", "Poppins", "Raleway", "Georgia", "Arial"];
const safeSrc = (u: string) => (/^(https?:\/\/|\/)/i.test(u.trim()) ? u.trim() : "");

const COLORS: [string, keyof TenantProfile][] = [
  ["Cor primária", "primary_color"],
  ["Secundária", "secondary_color"],
  ["Destaque", "accent_color"],
  ["Texto", "text_color"],
  ["Fundo", "bg_color"],
];

/**
 * Aba "Empresa": quem a empresa é (perfil) e como ela se apresenta (Brand Kit), com a prévia
 * ao lado. O estado do perfil e o botão Salvar continuam na página — esta aba só edita.
 */
export default function EmpresaTab({ p, set }: {
  p: TenantProfile; set: (patch: Partial<TenantProfile>) => void;
}) {
  return (
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
          <div className="mt-2">
            <ImageUploadButton label="Enviar logo" onUploaded={(url) => set({ logo_url: url })} />
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
            {COLORS.map(([label, key]) => (
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
  );
}
