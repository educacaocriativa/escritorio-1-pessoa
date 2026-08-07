/**
 * Peças visuais compartilhadas pelas abas de `/config`. Vieram inteiras do
 * `ConfiguracoesPage.tsx`, sem alteração — só saíram de lá porque agora têm mais de um dono.
 */
export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <h2 className="mb-3 font-semibold text-neutral-800">{title}</h2>
      {children}
    </div>
  );
}

export function Inp({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (s: string) => void; placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
    </label>
  );
}
