import type { PageBlock, PageStyle } from "@e1p/shared-types";
import { useState } from "react";

export type LeadPayload = { name: string; email: string; phone: string; fields: Record<string, string> };

export type ExtraField = {
  key: string;
  label: string;
  kind: "text" | "select";
  placeholder?: string;
  helper?: string;
  options?: string[];
  fullWidth?: boolean;
};

const safeSrc = (u: unknown) =>
  typeof u === "string" && /^(https?:\/\/|\/)/i.test(u.trim()) ? u.trim() : "";

/** Renderiza os blocos de uma página com o estilo (Brand Kit). */
export default function PageBlocks({
  blocks,
  style,
  onLead,
}: {
  blocks: PageBlock[];
  style: PageStyle;
  onLead?: (lead: LeadPayload) => Promise<void>;
}) {
  return (
    <div
      className="mx-auto max-w-xl space-y-5 px-6 py-10"
      style={{ background: style.bg_color, color: style.text_color, fontFamily: style.font }}
    >
      {safeSrc(style.logo_url) && (
        <img src={safeSrc(style.logo_url)} alt="logo" className="mx-auto max-h-12 object-contain" />
      )}
      {blocks.map((b, i) => (
        <Block key={i} block={b} style={style} onLead={onLead} />
      ))}
    </div>
  );
}

function Block({
  block,
  style,
  onLead,
}: {
  block: PageBlock;
  style: PageStyle;
  onLead?: (lead: LeadPayload) => Promise<void>;
}) {
  const s = (k: string) => (typeof block[k] === "string" ? (block[k] as string) : "");
  switch (block.type) {
    case "heading":
      return (
        <h1 className="text-center text-3xl font-extrabold" style={{ color: style.primary_color }}>
          {s("text")}
        </h1>
      );
    case "text":
      return <p className="whitespace-pre-line text-center text-base leading-relaxed opacity-90">{s("text")}</p>;
    case "image":
      return safeSrc(block.url) ? (
        <img src={safeSrc(block.url)} alt="" className="w-full rounded-xl object-cover" />
      ) : (
        <div className="flex h-40 items-center justify-center rounded-xl bg-black/5 text-sm opacity-40">
          imagem
        </div>
      );
    case "button":
      return (
        <div className="text-center">
          <a
            href={safeSrc(block.url) || "#"}
            className="inline-block rounded-pill px-8 py-3 text-base font-bold text-white"
            style={{ background: style.accent_color }}
          >
            {s("label") || "Botão"}
          </a>
        </div>
      );
    case "video":
      return safeSrc(block.url) ? (
        <div className="aspect-video w-full overflow-hidden rounded-xl">
          <iframe src={safeSrc(block.url)} title="vídeo" className="h-full w-full" allowFullScreen />
        </div>
      ) : (
        <div className="flex aspect-video items-center justify-center rounded-xl bg-neutral-800 text-2xl text-white">
          ▶
        </div>
      );
    case "form":
      return <LeadForm block={block} style={style} onLead={onLead} />;
    case "divider":
      return <hr className="border-black/10" />;
    default:
      return null;
  }
}

function LeadForm({
  block,
  style,
  onLead,
}: {
  block: PageBlock;
  style: PageStyle;
  onLead?: (lead: LeadPayload) => Promise<void>;
}) {
  const s = (k: string) => (typeof block[k] === "string" ? (block[k] as string) : "");
  const showEmail = block.showEmail === true;
  const extraFields: ExtraField[] = Array.isArray(block.extraFields) ? (block.extraFields as ExtraField[]) : [];
  const button = s("button") || "Enviar";
  const disclaimer = s("disclaimer");

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim() || !phone.trim() || !onLead) return;
    setBusy(true);
    try {
      const fields: Record<string, string> = {};
      for (const f of extraFields) {
        const v = values[f.key];
        if (v && v.trim()) fields[f.label] = v.trim();
      }
      await onLead({ name, email, phone, fields });
      setDone(true);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="rounded-xl p-4 text-center font-semibold" style={{ background: `${style.accent_color}22`, color: style.accent_color }}>
        Recebemos seu contato. Obrigado! 🎉
      </div>
    );
  }

  const border = `${style.text_color}33`;
  const inputBg = `${style.text_color}0d`;
  const mutedText = `${style.text_color}99`;
  const label = "mb-1 block text-sm font-semibold";
  const inp = "w-full rounded-lg px-3 py-2.5 text-sm outline-none";
  const inpStyle = { background: inputBg, border: `1px solid ${border}`, color: style.text_color };

  return (
    <div
      className="rounded-2xl p-6 sm:p-7"
      style={{ background: `${style.accent_color}14`, border: `1px solid ${border}` }}
    >
      <div className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2">
        <div>
          <span className={label}>{s("nameLabel") || "Seu nome"}</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={s("namePlaceholder") || "Como podemos te chamar?"}
            className={inp}
            style={inpStyle}
          />
        </div>
        <div>
          <span className={label}>{s("phoneLabel") || "Seu WhatsApp"}</span>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder={s("phonePlaceholder") || "(43) 9 9999-9999"}
            className={inp}
            style={inpStyle}
          />
          {s("phoneHelper") && (
            <p className="mt-1 text-xs" style={{ color: mutedText }}>{s("phoneHelper")}</p>
          )}
        </div>
        {showEmail && (
          <div className="sm:col-span-2">
            <span className={label}>{s("emailLabel") || "Seu e-mail"}</span>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={s("emailPlaceholder") || "seu@email.com"}
              className={inp}
              style={inpStyle}
            />
          </div>
        )}
        {extraFields.map((f) => (
          <div key={f.key} className={f.fullWidth ? "sm:col-span-2" : undefined}>
            <span className={label}>{f.label}</span>
            {f.kind === "select" ? (
              <select
                value={values[f.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                className={inp}
                style={inpStyle}
              >
                <option value="">{f.placeholder || "Selecione"}</option>
                {(f.options ?? []).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            ) : (
              <input
                value={values[f.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                className={inp}
                style={inpStyle}
              />
            )}
            {f.helper && <p className="mt-1 text-xs" style={{ color: mutedText }}>{f.helper}</p>}
          </div>
        ))}
      </div>
      <button
        onClick={submit}
        disabled={busy || !name.trim() || !phone.trim() || !onLead}
        className="mt-5 w-full rounded-pill py-3 text-base font-bold disabled:opacity-60"
        style={{ background: style.accent_color, color: style.primary_color }}
      >
        {busy ? "Enviando..." : button}
      </button>
      {disclaimer && (
        <p className="mt-3 text-center text-xs" style={{ color: mutedText }}>{disclaimer}</p>
      )}
    </div>
  );
}
