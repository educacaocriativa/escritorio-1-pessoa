import type { Carousel, Slide } from "@e1p/shared-types";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

type Style = Pick<
  Carousel,
  "primary_color" | "bg_color" | "text_color" | "accent_color" | "font"
>;

/** Um slide quadrado (1:1) renderizado com o template escolhido. */
export function SlideCard({
  slide,
  style,
  index,
  total,
}: {
  slide: Slide;
  style: Style;
  index: number;
  total: number;
}) {
  const isFirst = index === 0;
  const isLast = index === total - 1;
  return (
    <div
      className="relative flex aspect-square w-full flex-col justify-center overflow-hidden rounded-2xl p-8 text-center"
      style={{ background: style.bg_color, color: style.text_color, fontFamily: style.font }}
    >
      {/* faixa decorativa */}
      <div className="absolute inset-x-0 top-0 h-2" style={{ background: style.primary_color }} />
      <span
        className="absolute right-4 top-4 text-xs font-bold opacity-60"
        style={{ color: style.accent_color }}
      >
        {index + 1}/{total}
      </span>

      <h2
        className={`font-extrabold leading-tight ${isFirst ? "text-3xl" : "text-2xl"}`}
        style={{ color: isFirst || isLast ? style.primary_color : style.text_color }}
      >
        {slide.heading || (isFirst ? "Seu gancho aqui" : "Título do slide")}
      </h2>
      {slide.body && <p className="mt-4 text-base leading-relaxed opacity-90">{slide.body}</p>}

      {isLast && (
        <div
          className="mx-auto mt-6 rounded-pill px-5 py-2 text-sm font-bold"
          style={{ background: style.accent_color, color: style.bg_color }}
        >
          Salvar · Compartilhar
        </div>
      )}
      {isFirst && !isLast && (
        <span className="absolute bottom-5 right-6 text-sm font-semibold opacity-70">
          arraste →
        </span>
      )}
    </div>
  );
}

/** Visualizador navegável (setas + bolinhas) usado na prévia do construtor. */
export default function CarouselViewer({ slides, style }: { slides: Slide[]; style: Style }) {
  const [i, setI] = useState(0);
  const total = slides.length || 1;
  useEffect(() => {
    if (i > slides.length - 1) setI(Math.max(0, slides.length - 1));
  }, [slides.length, i]);

  if (slides.length === 0) {
    return (
      <div className="flex aspect-square w-full items-center justify-center rounded-2xl bg-neutral-100 text-sm text-neutral-400">
        Gere ou adicione slides para ver a prévia.
      </div>
    );
  }

  return (
    <div>
      <SlideCard slide={slides[i]} style={style} index={i} total={total} />
      <div className="mt-3 flex items-center justify-center gap-3">
        <button
          onClick={() => setI((v) => Math.max(0, v - 1))}
          disabled={i === 0}
          className="rounded-full bg-white p-1.5 shadow-sm disabled:opacity-40"
        >
          <ChevronLeft size={16} />
        </button>
        <div className="flex gap-1.5">
          {slides.map((_, idx) => (
            <button
              key={idx}
              onClick={() => setI(idx)}
              className="h-2 w-2 rounded-full transition"
              style={{ background: idx === i ? style.primary_color : "#D1D5DB" }}
            />
          ))}
        </div>
        <button
          onClick={() => setI((v) => Math.min(total - 1, v + 1))}
          disabled={i === total - 1}
          className="rounded-full bg-white p-1.5 shadow-sm disabled:opacity-40"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
