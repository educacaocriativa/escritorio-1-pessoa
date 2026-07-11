import type { Carousel, Slide } from "@e1p/shared-types";
import html2canvas from "html2canvas";
import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { forwardRef, useRef, useState } from "react";

const W = 1080;
const H = 1350; // 4:5

// Guarda de esquema de <img src>/background-image (IV3, mesma regra de ConfiguracoesPage/
// ProposalView/PageBuilderPage): só aceita http(s):// ou caminho relativo iniciado por "/"
// (ex.: /api/public-images/{id}). Bloqueia javascript:, data:, etc. Aplicada aqui para
// uniformizar o padrão nos 4 consumidores após o upload real (Story 4.2).
const safeSrc = (u: string) => (/^(https?:\/\/|\/)/i.test(u.trim()) ? u.trim() : "");

export type SlideStyle = Pick<
  Carousel,
  "handle" | "primary_color" | "bg_color" | "text_color" | "accent_color" | "font"
>;

const monthTag = () => {
  const d = new Date();
  const m = d.toLocaleDateString("pt-BR", { month: "long" });
  return `${m.charAt(0).toUpperCase()}${m.slice(1)} ${d.getFullYear()} ®`;
};

/** Destaca a `word` dentro de `text` na cor de acento (1ª ocorrência, case-insensitive). */
function highlighted(text: string, word: string, color: string) {
  if (!word) return text;
  const i = text.toLowerCase().indexOf(word.toLowerCase());
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <span style={{ color, fontWeight: 800, fontStyle: "italic" }}>
        {text.slice(i, i + word.length)}
      </span>
      {text.slice(i + word.length)}
    </>
  );
}

function Header({ s }: { s: SlideStyle }) {
  const c = "rgba(255,255,255,0.55)";
  return (
    <div
      style={{
        position: "absolute", top: 0, left: 0, right: 0, display: "flex",
        justifyContent: "space-between", alignItems: "center", padding: "22px 40px",
        zIndex: 10, fontFamily: "'Space Grotesk', sans-serif",
      }}
    >
      <span style={{ fontSize: 16, color: c, textTransform: "uppercase", letterSpacing: 0.8 }}>Powered by e1p</span>
      <span style={{ fontSize: 16, color: c, textTransform: "uppercase", letterSpacing: 0.8 }}>{s.handle || ""}</span>
      <span style={{ fontSize: 16, color: c, textTransform: "uppercase", letterSpacing: 0.8 }}>{monthTag()}</span>
    </div>
  );
}

function Footer({ s, page }: { s: SlideStyle; page: string }) {
  return (
    <div
      style={{
        position: "absolute", bottom: 0, left: 0, right: 0, display: "flex",
        justifyContent: "space-between", alignItems: "center", padding: "18px 40px",
        background: "rgba(0,0,0,0.5)", zIndex: 10,
      }}
    >
      <span style={{ fontSize: 20, fontWeight: 700, color: "#fff" }}>{s.handle || ""}</span>
      <span style={{ fontSize: 18, color: "rgba(255,255,255,0.6)" }}>{page}</span>
    </div>
  );
}

/** Slide editorial em tamanho real 1080×1350 (para export PNG fiel). */
export const EditorialSlide = forwardRef<
  HTMLDivElement,
  { slide: Slide; style: SlideStyle; index: number; total: number }
>(function EditorialSlide({ slide, style, index, total }, ref) {
  const isCover = slide.kind === "cover";
  const isCta = slide.kind === "cta";
  const isAccent = slide.kind === "accent";
  const photo = safeSrc(slide.photo_url || "");
  const onPhoto = (isCover || isCta) && !!photo;
  const page = index === 0 ? "" : `${index}/${total - 1}`;

  const base: React.CSSProperties = {
    width: W, height: H, position: "relative", overflow: "hidden",
    fontFamily: `'${style.font}', sans-serif`, color: style.text_color,
    display: "flex", flexDirection: "column", justifyContent: "center",
    padding: "100px 56px", boxSizing: "border-box",
  };

  let bg: React.CSSProperties = { background: isAccent ? style.primary_color : style.bg_color };
  if (onPhoto) {
    bg = {
      backgroundImage: `url('${photo}')`,
      backgroundSize: "cover",
      backgroundPosition: "center",
    };
  } else if (isCover || isCta) {
    bg = { background: `linear-gradient(160deg, ${style.bg_color} 0%, ${style.primary_color}55 100%)` };
  }

  return (
    <div ref={ref} style={base}>
      <div style={{ position: "absolute", inset: 0, zIndex: 0, ...bg }} />
      {onPhoto && (
        <div
          style={{
            position: "absolute", inset: 0, zIndex: 1,
            background: "linear-gradient(180deg, rgba(0,0,0,0.25) 0%, rgba(0,0,0,0.78) 100%)",
          }}
        />
      )}
      <Header s={style} />

      <div style={{ position: "relative", zIndex: 2, display: "flex", flexDirection: "column", gap: 28 }}>
        {isCover || isCta ? (
          <>
            {isCover && style.handle && (
              <div style={{ textAlign: "center", fontSize: 26, fontWeight: 700, marginBottom: 8 }}>
                {style.handle}
              </div>
            )}
            <h1
              style={{
                fontSize: isCover ? 64 : 56, fontWeight: 900, lineHeight: 1.08,
                textTransform: "uppercase", letterSpacing: -1,
                textShadow: onPhoto ? "2px 2px 10px rgba(0,0,0,0.85)" : "none",
                textAlign: isCta ? "center" : "left",
              }}
            >
              {highlighted(slide.heading || "", slide.highlight, style.primary_color)}
            </h1>
            {slide.body && (
              <p style={{ fontSize: 26, fontWeight: 500, lineHeight: 1.5, color: "rgba(255,255,255,0.88)", textAlign: isCta ? "center" : "left", textShadow: onPhoto ? "1px 1px 6px rgba(0,0,0,0.85)" : "none" }}>
                {slide.body}
              </p>
            )}
            {isCta && (
              <div style={{ display: "flex", justifyContent: "center", gap: 40, marginTop: 24 }}>
                {[["SALVAR", style.primary_color], ["ENVIAR", "#fff"], ["CURTIR", style.accent_color]].map(([l, c]) => (
                  <span key={l} style={{ fontSize: 22, fontWeight: 700, color: c as string }}>{l}</span>
                ))}
              </div>
            )}
          </>
        ) : (
          <>
            <p style={{ fontSize: 40, fontWeight: 600, lineHeight: 1.45 }}>
              {highlighted(slide.heading || "", slide.highlight, isAccent ? style.accent_color : style.primary_color)}
            </p>
            {photo && (
              <img
                src={photo}
                alt=""
                crossOrigin="anonymous"
                style={{ width: "100%", height: 360, objectFit: "cover", borderRadius: 8 }}
              />
            )}
            {slide.secondary && (
              <p style={{ fontSize: 28, fontWeight: 400, lineHeight: 1.5, color: "rgba(255,255,255,0.9)" }}>
                {slide.secondary}
              </p>
            )}
          </>
        )}
      </div>

      <Footer s={style} page={page} />
    </div>
  );
});

/** Versão reduzida para exibição na UI (escala o slide real). */
function ScaledSlide({ slide, style, index, total, display = 380 }: {
  slide: Slide; style: SlideStyle; index: number; total: number; display?: number;
}) {
  const scale = display / W;
  return (
    <div style={{ width: display, height: H * scale, overflow: "hidden", borderRadius: 12 }}>
      <div style={{ transform: `scale(${scale})`, transformOrigin: "top left" }}>
        <EditorialSlide slide={slide} style={style} index={index} total={total} />
      </div>
    </div>
  );
}

/** Miniatura (1º slide) para listas/cards. */
export function CarouselThumb({ slides, style, display = 240 }: {
  slides: Slide[]; style: SlideStyle; display?: number;
}) {
  if (slides.length === 0) {
    return (
      <div className="flex aspect-[4/5] items-center justify-center text-xs" style={{ background: style.bg_color, color: style.text_color }}>
        Sem slides
      </div>
    );
  }
  return <ScaledSlide slide={slides[0]} style={style} index={0} total={slides.length} display={display} />;
}

async function toPng(el: HTMLElement): Promise<string> {
  const canvas = await html2canvas(el, { width: W, height: H, scale: 1, useCORS: true, backgroundColor: null });
  return canvas.toDataURL("image/png");
}

/** Visualizador navegável + export PNG (substitui o Playwright da skill por html2canvas). */
export default function CarouselViewer({ slides, style }: { slides: Slide[]; style: SlideStyle }) {
  const [i, setI] = useState(0);
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  const [busy, setBusy] = useState(false);
  const total = slides.length;

  async function download(idx: number) {
    const el = refs.current[idx];
    if (!el) return;
    const a = document.createElement("a");
    a.href = await toPng(el);
    a.download = `slide_${String(idx + 1).padStart(2, "0")}.png`;
    a.click();
  }
  async function downloadAll() {
    setBusy(true);
    try {
      for (let idx = 0; idx < total; idx++) await download(idx);
    } finally {
      setBusy(false);
    }
  }

  if (total === 0) {
    return (
      <div className="flex aspect-[4/5] w-full items-center justify-center rounded-xl bg-neutral-100 text-sm text-neutral-400">
        Gere ou adicione slides para ver a prévia.
      </div>
    );
  }

  return (
    <div>
      <div className="flex justify-center">
        <ScaledSlide slide={slides[Math.min(i, total - 1)]} style={style} index={Math.min(i, total - 1)} total={total} />
      </div>

      {/* stack oculto em tamanho real, usado só para exportar PNG */}
      <div style={{ position: "fixed", left: -99999, top: 0, pointerEvents: "none" }} aria-hidden>
        {slides.map((s, idx) => (
          <EditorialSlide key={idx} ref={(el) => (refs.current[idx] = el)} slide={s} style={style} index={idx} total={total} />
        ))}
      </div>

      <div className="mt-3 flex items-center justify-center gap-3">
        <button onClick={() => setI((v) => Math.max(0, v - 1))} disabled={i === 0} className="rounded-full bg-white p-1.5 shadow-sm disabled:opacity-40">
          <ChevronLeft size={16} />
        </button>
        <div className="flex flex-wrap justify-center gap-1.5">
          {slides.map((_, idx) => (
            <button key={idx} onClick={() => setI(idx)} className="h-2 w-2 rounded-full" style={{ background: idx === i ? style.primary_color : "#D1D5DB" }} />
          ))}
        </div>
        <button onClick={() => setI((v) => Math.min(total - 1, v + 1))} disabled={i === total - 1} className="rounded-full bg-white p-1.5 shadow-sm disabled:opacity-40">
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="mt-3 flex justify-center gap-2">
        <button onClick={() => download(i)} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-1.5 text-xs font-semibold text-neutral-600 hover:bg-neutral-200">
          <Download size={13} /> PNG deste slide
        </button>
        <button onClick={downloadAll} disabled={busy} className="flex items-center gap-1.5 rounded-pill bg-primary-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-600 disabled:opacity-60">
          <Download size={13} /> {busy ? "Baixando..." : "Baixar todos"}
        </button>
      </div>
    </div>
  );
}
