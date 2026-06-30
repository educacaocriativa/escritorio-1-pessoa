import type { Carousel, CarouselTemplate, Slide } from "@e1p/shared-types";
import { ArrowLeft, ChevronDown, ChevronUp, Copy, Plus, Save, Sparkles, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import CarouselViewer from "./CarouselSlideView";

const FONTS = ["Raleway", "Inter", "Poppins", "Georgia", "Arial"];
const KINDS: Slide["kind"][] = ["cover", "editorial", "accent", "cta"];
const KIND_LABEL: Record<Slide["kind"], string> = {
  cover: "Capa", editorial: "Editorial", accent: "Destaque", cta: "CTA",
};

const blankSlide = (): Slide => ({
  kind: "editorial", heading: "", body: "", secondary: "", highlight: "",
  photo_url: "", photo_position: "mid",
});

export default function CarrosselBuilderPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id || id === "novo";

  const [carouselId, setCarouselId] = useState<string | null>(isNew ? null : id!);
  const [topic, setTopic] = useState("");
  const [handle, setHandle] = useState("");
  const [slides, setSlides] = useState<Slide[]>([]);
  const [caption, setCaption] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [template, setTemplate] = useState("editorial");
  const [primary, setPrimary] = useState("#B078FF");
  const [bg, setBg] = useState("#292A25");
  const [text, setText] = useState("#FFFFFF");
  const [accent, setAccent] = useState("#3CD3A4");
  const [font, setFont] = useState("Raleway");
  const [count, setCount] = useState(7);
  const [templates, setTemplates] = useState<CarouselTemplate[]>([]);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    api.get<CarouselTemplate[]>("/marketing/carousels/templates").then(({ data }) => setTemplates(data));
  }, []);

  // Carrossel novo herda a cor da marca + fonte do Brand Kit (mantém o fundo editorial).
  useEffect(() => {
    if (!isNew) return;
    api.get("/settings/profile").then(({ data }) => {
      setPrimary(data.primary_color);
      setAccent(data.accent_color);
      setFont(data.font);
      if (!handle && data.website) setHandle(data.website);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isNew]);

  const hydrate = useCallback((c: Carousel) => {
    setCarouselId(c.id);
    setTopic(c.topic);
    setHandle(c.handle);
    setSlides(c.slides.map((s) => ({ ...blankSlide(), ...s })));
    setCaption(c.caption);
    setHashtags(c.hashtags);
    setTemplate(c.template);
    setPrimary(c.primary_color);
    setBg(c.bg_color);
    setText(c.text_color);
    setAccent(c.accent_color);
    setFont(c.font);
  }, []);

  useEffect(() => {
    if (!isNew && id) api.get<Carousel>(`/marketing/carousels/${id}`).then(({ data }) => hydrate(data));
  }, [isNew, id, hydrate]);

  const style = {
    handle, primary_color: primary, bg_color: bg, text_color: text, accent_color: accent, font,
  };

  function applyTemplate(t: CarouselTemplate) {
    setTemplate(t.key);
    setPrimary(t.primary_color);
    setBg(t.bg_color);
    setText(t.text_color);
    setAccent(t.accent_color);
    setFont(t.font);
  }

  async function generate() {
    if (topic.trim().length < 3) {
      setError("Escreva um tema para a IA gerar o carrossel.");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      const { data } = await api.post<{ slides: Slide[]; caption: string; hashtags: string }>(
        "/marketing/carousels/generate",
        { topic, slides: count },
      );
      setSlides(data.slides.map((s) => ({ ...blankSlide(), ...s })));
      setCaption(data.caption);
      setHashtags(data.hashtags);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setGenerating(false);
    }
  }

  function setSlide(i: number, patch: Partial<Slide>) {
    setSlides((s) => s.map((sl, idx) => (idx === i ? { ...sl, ...patch } : sl)));
  }
  function move(i: number, dir: -1 | 1) {
    setSlides((s) => {
      const j = i + dir;
      if (j < 0 || j >= s.length) return s;
      const next = [...s];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  async function save() {
    if (topic.trim().length < 3) {
      setError("Informe um tema.");
      return;
    }
    setSaving(true);
    setError(null);
    const payload = {
      topic, handle, slides, caption, hashtags, template,
      primary_color: primary, bg_color: bg, text_color: text, accent_color: accent, font,
    };
    try {
      let c: Carousel;
      if (carouselId) {
        c = (await api.patch<Carousel>(`/marketing/carousels/${carouselId}`, payload)).data;
      } else {
        c = (await api.post<Carousel>("/marketing/carousels", payload)).data;
        window.history.replaceState(null, "", `/marketing/${c.id}`);
      }
      hydrate(c);
      setSavedAt(new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }));
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <button onClick={() => navigate("/marketing")} className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-700">
          <ArrowLeft size={16} /> Marketing
        </button>
        <button onClick={save} disabled={saving} className="flex items-center gap-1.5 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-50">
          <Save size={14} /> {saving ? "Salvando..." : "Salvar"}
        </button>
      </div>
      {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
      {savedAt && !error && <div className="mb-3 text-xs text-neutral-400">Salvo às {savedAt}.</div>}

      <div className="grid flex-1 grid-cols-1 gap-6 overflow-hidden lg:grid-cols-2">
        {/* Editor */}
        <div className="flex flex-col gap-4 overflow-auto rounded-2xl bg-white p-4 shadow-sm">
          {/* Gerar com IA */}
          <div className="rounded-xl bg-primary-50 p-3">
            <label className="mb-1 block text-xs font-medium text-primary-700">Tema do carrossel</label>
            <textarea value={topic} onChange={(e) => setTopic(e.target.value)} rows={2} placeholder="ex: o lado oculto da IA no mercado de trabalho" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
            <div className="mt-2 flex items-center gap-2">
              <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@seu_perfil" className="w-32 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
              <label className="text-xs text-neutral-500">Slides:</label>
              <input type="number" min={3} max={10} value={count} onChange={(e) => setCount(Math.min(10, Math.max(3, parseInt(e.target.value, 10) || 7)))} className="w-14 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
              <button onClick={generate} disabled={generating} className="ml-auto flex items-center gap-1.5 rounded-pill bg-primary-500 px-4 py-1.5 text-sm font-semibold text-white hover:bg-primary-600 disabled:opacity-60">
                <Sparkles size={14} /> {generating ? "Gerando..." : "Gerar com IA"}
              </button>
            </div>
          </div>

          {/* Templates */}
          <div>
            <p className="mb-2 text-xs font-medium text-neutral-600">Template (clique e depois personalize)</p>
            <div className="flex flex-wrap gap-2">
              {templates.map((t) => (
                <button key={t.key} onClick={() => applyTemplate(t)} className={`flex items-center gap-1.5 rounded-pill border px-3 py-1.5 text-xs font-medium ${template === t.key ? "border-primary-400 ring-2 ring-primary-100" : "border-neutral-200"}`}>
                  <span className="h-3 w-3 rounded-full" style={{ background: t.primary_color }} />
                  <span className="h-3 w-3 rounded-full" style={{ background: t.bg_color }} />
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {/* Cores + fonte */}
          <div className="grid grid-cols-2 gap-3">
            {([["Acento", primary, setPrimary], ["Fundo", bg, setBg], ["Texto", text, setText], ["Destaque 2", accent, setAccent]] as [string, string, (s: string) => void][]).map(([label, val, set]) => (
              <div key={label}>
                <span className="mb-1 block text-xs font-medium text-neutral-600">{label}</span>
                <div className="flex items-center gap-2">
                  <input type="color" value={val} onChange={(e) => set(e.target.value)} className="h-9 w-10 cursor-pointer rounded border border-neutral-200" />
                  <input value={val} onChange={(e) => set(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm uppercase outline-none" />
                </div>
              </div>
            ))}
            <div className="col-span-2">
              <span className="mb-1 block text-xs font-medium text-neutral-600">Fonte</span>
              <select value={font} onChange={(e) => setFont(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
                {FONTS.map((f) => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
          </div>

          {/* Slides */}
          <div className="space-y-2">
            <p className="text-xs font-medium text-neutral-600">Slides ({slides.length})</p>
            {slides.map((s, i) => (
              <div key={i} className="rounded-xl border border-neutral-100 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <select value={s.kind} onChange={(e) => setSlide(i, { kind: e.target.value as Slide["kind"] })} className="rounded-lg border border-neutral-200 px-2 py-1 text-xs font-medium outline-none">
                    {KINDS.map((k) => <option key={k} value={k}>{i + 1}. {KIND_LABEL[k]}</option>)}
                  </select>
                  <div className="flex items-center gap-1 text-neutral-300">
                    <button onClick={() => move(i, -1)} disabled={i === 0} className="hover:text-neutral-600 disabled:opacity-30"><ChevronUp size={14} /></button>
                    <button onClick={() => move(i, 1)} disabled={i === slides.length - 1} className="hover:text-neutral-600 disabled:opacity-30"><ChevronDown size={14} /></button>
                    <button onClick={() => setSlides((sl) => sl.filter((_, idx) => idx !== i))} className="hover:text-danger"><Trash2 size={14} /></button>
                  </div>
                </div>
                <input value={s.heading} onChange={(e) => setSlide(i, { heading: e.target.value })} placeholder={s.kind === "cover" || s.kind === "cta" ? "Título (CAIXA ALTA)" : "Frase principal"} className="mb-1 w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm font-medium outline-none" />
                {(s.kind === "editorial" || s.kind === "accent") && (
                  <textarea value={s.secondary} onChange={(e) => setSlide(i, { secondary: e.target.value })} rows={2} placeholder="Texto complementar (dado/exemplo)" className="mb-1 w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
                )}
                {(s.kind === "cover" || s.kind === "cta") && (
                  <input value={s.body} onChange={(e) => setSlide(i, { body: e.target.value })} placeholder="Subtítulo" className="mb-1 w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none" />
                )}
                <div className="flex gap-2">
                  <input value={s.highlight} onChange={(e) => setSlide(i, { highlight: e.target.value })} placeholder="Palavra em destaque" className="w-1/2 rounded-lg border border-neutral-200 px-2 py-1.5 text-xs outline-none" />
                  <input value={s.photo_url} onChange={(e) => setSlide(i, { photo_url: e.target.value })} placeholder="URL da foto (opcional)" className="w-1/2 rounded-lg border border-neutral-200 px-2 py-1.5 text-xs outline-none" />
                </div>
              </div>
            ))}
            <button onClick={() => setSlides((s) => [...s, blankSlide()])} className="flex items-center gap-1 text-sm font-medium text-primary-600">
              <Plus size={14} /> Adicionar slide
            </button>
          </div>

          {/* Legenda + hashtags */}
          <div className="space-y-2 border-t border-neutral-100 pt-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-neutral-600">Legenda</span>
              <button onClick={() => navigator.clipboard?.writeText(`${caption}\n\n${hashtags}`)} className="flex items-center gap-1 text-xs text-primary-600">
                <Copy size={12} /> Copiar legenda + hashtags
              </button>
            </div>
            <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} placeholder="Legenda do post" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
            <input value={hashtags} onChange={(e) => setHashtags(e.target.value)} placeholder="#hashtags" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm text-primary-600 outline-none focus:border-primary-400" />
          </div>
        </div>

        {/* Prévia */}
        <div className="overflow-auto rounded-2xl border border-neutral-100 bg-neutral-50 p-4">
          <p className="mb-3 text-center text-xs uppercase tracking-wide text-neutral-400">Pré-visualização (Instagram 4:5) — baixe em PNG</p>
          <CarouselViewer slides={slides} style={style} />
        </div>
      </div>
    </div>
  );
}
