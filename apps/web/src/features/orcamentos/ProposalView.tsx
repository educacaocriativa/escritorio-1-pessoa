import type { PublicProposal } from "@e1p/shared-types";
import { CalendarClock, Check, FileText, Image as ImageIcon } from "lucide-react";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
// só permite http(s) ou caminho relativo como origem de imagem (defesa contra src maliciosa)
const safeSrc = (u: string) => (/^(https?:\/\/|\/)/i.test(u.trim()) ? u.trim() : "");

/** Render temático da proposta — usado na prévia do construtor e na página pública. */
export default function ProposalView({
  p,
  onAccept,
  accepting,
  accepted,
}: {
  p: PublicProposal;
  onAccept?: () => void;
  accepting?: boolean;
  accepted?: boolean;
}) {
  const closed = p.status === "approved" || p.status === "rejected" || accepted;
  return (
    <div className="mx-auto max-w-2xl" style={{ background: p.bg_color, color: p.text_color }}>
      {/* Cabeçalho */}
      <div className="px-6 py-8 text-center" style={{ borderTop: `4px solid ${p.primary_color}` }}>
        {safeSrc(p.logo_url) ? (
          <img src={safeSrc(p.logo_url)} alt="logo" className="mx-auto mb-3 max-h-14 object-contain" />
        ) : null}
        <h1 className="text-2xl font-bold" style={{ color: p.primary_color }}>
          {p.title}
        </h1>
        {p.client_name && (
          <p className="mt-1 text-sm opacity-70">Proposta para {p.client_name}</p>
        )}
      </div>

      {/* Serviços */}
      <div className="space-y-3 px-6">
        {p.items.map((it, i) => (
          <div key={i} className="flex items-start justify-between rounded-xl border border-black/5 p-4">
            <div className="pr-3">
              <p className="font-semibold">{it.description}</p>
              {it.subtitle && <p className="text-sm opacity-60">{it.subtitle}</p>}
              {it.quantity > 1 && (
                <p className="mt-1 text-xs opacity-50">
                  {it.quantity} × {brl(it.unit_price_cents)}
                </p>
              )}
            </div>
            <p className="shrink-0 font-semibold tabular-nums">
              {brl(it.quantity * it.unit_price_cents)}
            </p>
          </div>
        ))}
      </div>

      {/* Totais */}
      <div className="mt-4 space-y-1 px-6 text-sm">
        <div className="flex justify-between opacity-70">
          <span>Subtotal</span>
          <span className="tabular-nums">{brl(p.subtotal_cents)}</span>
        </div>
        {p.discount_cents > 0 && (
          <div className="flex justify-between opacity-70">
            <span>Desconto</span>
            <span className="tabular-nums">- {brl(p.discount_cents)}</span>
          </div>
        )}
        <div className="flex justify-between border-t border-black/10 pt-2 text-lg font-bold">
          <span>Total</span>
          <span className="tabular-nums" style={{ color: p.primary_color }}>
            {brl(p.total_cents)}
          </span>
        </div>
      </div>

      {/* Condições de pagamento */}
      {p.payment_terms && (
        <Section title="Condições de pagamento">
          <p className="whitespace-pre-line text-sm opacity-80">{p.payment_terms}</p>
        </Section>
      )}

      {/* Galeria */}
      {p.show_gallery && p.gallery.length > 0 && (
        <Section title="Galeria" icon={<ImageIcon size={15} />}>
          <div className="grid grid-cols-2 gap-2">
            {p.gallery.map((g, i) => (
              <figure key={i}>
                <img src={safeSrc(g.url)} alt={g.caption || ""} className="h-32 w-full rounded-lg object-cover" />
                {g.caption && <figcaption className="mt-1 text-xs opacity-60">{g.caption}</figcaption>}
              </figure>
            ))}
          </div>
        </Section>
      )}

      {/* Cronograma */}
      {p.show_schedule && p.schedule.length > 0 && (
        <Section title="Cronograma" icon={<CalendarClock size={15} />}>
          <ol className="space-y-2">
            {p.schedule.map((s, i) => (
              <li key={i} className="flex gap-3">
                <span
                  className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                  style={{ background: p.primary_color }}
                >
                  {i + 1}
                </span>
                <div>
                  <p className="text-sm font-medium">
                    {s.title}
                    {s.when && <span className="ml-2 text-xs opacity-50">{s.when}</span>}
                  </p>
                  {s.description && <p className="text-xs opacity-60">{s.description}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {/* Contrato */}
      {p.show_contract && (
        <Section title="Prévia do contrato" icon={<FileText size={15} />}>
          <div className="max-h-48 overflow-auto rounded-lg bg-black/5 p-3 text-xs leading-relaxed opacity-80">
            {p.contract_text ? (
              <p className="whitespace-pre-line">{p.contract_text}</p>
            ) : (
              <p className="italic opacity-60">
                O contrato completo será disponibilizado após o aceite.
              </p>
            )}
          </div>
        </Section>
      )}

      {/* Aceite */}
      <div className="px-6 py-8">
        {closed ? (
          <div
            className="flex items-center justify-center gap-2 rounded-pill py-3 text-sm font-semibold"
            style={{ background: `${p.accent_color}22`, color: p.accent_color }}
          >
            <Check size={16} />
            {p.status === "approved" || accepted ? "Proposta aceita" : "Proposta encerrada"}
          </div>
        ) : onAccept ? (
          <button
            onClick={onAccept}
            disabled={accepting}
            className="w-full rounded-pill py-3 font-semibold text-white transition hover:opacity-90 disabled:opacity-60"
            style={{ background: p.accent_color }}
          >
            {accepting ? "Enviando..." : "Aceitar proposta"}
          </button>
        ) : (
          <div
            className="rounded-pill py-3 text-center text-sm font-semibold text-white opacity-90"
            style={{ background: p.accent_color }}
          >
            Aceitar proposta
          </div>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-6 px-6">
      <h2 className="mb-2 flex items-center gap-1.5 text-sm font-bold uppercase tracking-wide opacity-70">
        {icon}
        {title}
      </h2>
      {children}
    </div>
  );
}
