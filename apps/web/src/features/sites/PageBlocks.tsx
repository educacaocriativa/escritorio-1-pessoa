import type { PageBlock, PageStyle } from "@e1p/shared-types";
import { useState } from "react";

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
  onLead?: (lead: { name: string; email: string; phone: string }) => Promise<void>;
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
  onLead?: (lead: { name: string; email: string; phone: string }) => Promise<void>;
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
      return <LeadForm button={s("button") || "Enviar"} style={style} onLead={onLead} />;
    case "divider":
      return <hr className="border-black/10" />;
    default:
      return null;
  }
}

function LeadForm({
  button,
  style,
  onLead,
}: {
  button: string;
  style: PageStyle;
  onLead?: (lead: { name: string; email: string; phone: string }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim() || !onLead) return;
    setBusy(true);
    try {
      await onLead({ name, email, phone });
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

  const inp = "w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm text-neutral-800 outline-none";
  return (
    <div className="space-y-2 rounded-xl bg-black/5 p-4">
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Seu nome" className={inp} />
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Seu e-mail" className={inp} />
      <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Seu WhatsApp" className={inp} />
      <button
        onClick={submit}
        disabled={busy || !name.trim() || !onLead}
        className="w-full rounded-pill py-2.5 font-bold text-white disabled:opacity-60"
        style={{ background: style.accent_color }}
      >
        {busy ? "Enviando..." : button}
      </button>
    </div>
  );
}
