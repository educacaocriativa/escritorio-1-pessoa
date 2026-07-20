import type { Page, PageBlock } from "@e1p/shared-types";
import { ArrowLeft, ChevronDown, ChevronUp, Eye, Globe, Plus, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ImageUploadButton from "../../components/ImageUploadButton";
import { api, apiErrorMessage } from "../../lib/api";
import PageBlocks, { type ExtraField } from "./PageBlocks";

const BLOCK_TYPES: [string, string][] = [
  ["heading", "Título"], ["text", "Texto"], ["image", "Imagem"], ["button", "Botão"],
  ["form", "Formulário"], ["video", "Vídeo"], ["divider", "Divisor"],
];
const FONTS = ["Inter", "Poppins", "Raleway", "Georgia", "Arial"];

function blankBlock(type: string): PageBlock {
  switch (type) {
    case "heading": return { type, text: "Novo título" };
    case "text": return { type, text: "Novo texto" };
    case "image": return { type, url: "" };
    case "button": return { type, label: "Clique aqui", url: "" };
    case "form":
      return { type, button: "Enviar", showEmail: true, extraFields: [] as ExtraField[], disclaimer: "" };
    case "video": return { type, url: "" };
    default: return { type: "divider" };
  }
}

export default function PageBuilderPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [page, setPage] = useState<Page | null>(null);
  const [blocks, setBlocks] = useState<PageBlock[]>([]);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get<Page>(`/pages/${id}`);
    setPage(data);
    setBlocks(data.blocks);
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!page) return <div className="p-8 text-sm text-neutral-400">Carregando...</div>;

  const setStyle = (patch: Partial<Page>) => setPage({ ...page, ...patch });
  const setBlock = (i: number, patch: Partial<PageBlock>) =>
    setBlocks((bs) => bs.map((b, idx) => (idx === i ? { ...b, ...patch } : b)));
  function move(i: number, dir: -1 | 1) {
    setBlocks((bs) => {
      const j = i + dir;
      if (j < 0 || j >= bs.length) return bs;
      const next = [...bs];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  const save = async (): Promise<Page | null> => {
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.patch<Page>(`/pages/${id}`, {
        title: page.title, blocks,
        primary_color: page.primary_color, bg_color: page.bg_color, text_color: page.text_color,
        accent_color: page.accent_color, font: page.font, logo_url: page.logo_url,
      });
      setPage(data);
      setBlocks(data.blocks);
      setSavedAt(new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }));
      return data;
    } catch (err) {
      setError(apiErrorMessage(err));
      return null;
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    const saved = await save();
    if (!saved) return;
    try {
      const { data } = await api.post<Page>(`/pages/${id}/publish`);
      setPage(data);
      setSavedAt("publicada");
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  };
  const view = async () => {
    await save();
    if (page.public_slug) window.open(`/p/${page.public_slug}`, "_blank");
  };

  const published = page.status === "published";

  return (
    <div className="flex h-full flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <button onClick={() => navigate("/sites")} className="flex items-center gap-1 text-sm text-neutral-500 hover:text-neutral-700">
          <ArrowLeft size={16} /> Sites
        </button>
        <input value={page.title} onChange={(e) => setStyle({ title: e.target.value })} className="rounded-lg border border-neutral-200 px-3 py-1.5 text-sm font-medium outline-none focus:border-primary-400" />
        <div className="flex items-center gap-2">
          {savedAt && <span className="text-xs text-neutral-400">{savedAt === "publicada" ? "Publicada" : `Salvo ${savedAt}`}</span>}
          <button onClick={view} className="flex items-center gap-1.5 rounded-pill bg-neutral-100 px-3 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-200">
            <Eye size={14} /> Ver
          </button>
          <button onClick={publish} className="flex items-center gap-1.5 rounded-pill bg-primary-500 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-600">
            <Globe size={14} /> {published ? "Republicar" : "Publicar"}
          </button>
          <button onClick={save} disabled={saving} className="flex items-center gap-1.5 rounded-pill bg-accent-400 px-4 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-50">
            <Save size={14} /> {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
      {error && <div className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}

      <div className="grid flex-1 grid-cols-1 gap-6 overflow-hidden lg:grid-cols-2">
        {/* Editor */}
        <div className="flex flex-col gap-3 overflow-auto rounded-2xl bg-white p-4 shadow-sm">
          {/* Aparência */}
          <div className="grid grid-cols-2 gap-2 rounded-xl bg-neutral-50 p-3">
            {([["Primária", "primary_color"], ["Fundo", "bg_color"], ["Texto", "text_color"], ["Destaque", "accent_color"]] as [string, keyof Page][]).map(([label, key]) => (
              <div key={key} className="flex items-center gap-1.5">
                <input type="color" value={page[key] as string} onChange={(e) => setStyle({ [key]: e.target.value } as Partial<Page>)} className="h-7 w-8 cursor-pointer rounded border border-neutral-200" />
                <span className="text-xs text-neutral-500">{label}</span>
              </div>
            ))}
            <select value={page.font} onChange={(e) => setStyle({ font: e.target.value })} className="col-span-2 rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none">
              {FONTS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <div className="col-span-2 space-y-1">
              <span className="text-xs text-neutral-500">Logo</span>
              <input value={page.logo_url} onChange={(e) => setStyle({ logo_url: e.target.value })} placeholder="URL do logo (https://...)" className="w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none focus:border-primary-400" />
              <ImageUploadButton label="Enviar logo" onUploaded={(url) => setStyle({ logo_url: url })} />
            </div>
          </div>

          {/* Blocos */}
          {blocks.map((b, i) => (
            <div key={i} className="rounded-xl border border-neutral-100 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wide text-neutral-400">
                  {BLOCK_TYPES.find(([t]) => t === b.type)?.[1] ?? b.type}
                </span>
                <div className="flex items-center gap-1 text-neutral-300">
                  <button onClick={() => move(i, -1)} disabled={i === 0} className="hover:text-neutral-600 disabled:opacity-30"><ChevronUp size={14} /></button>
                  <button onClick={() => move(i, 1)} disabled={i === blocks.length - 1} className="hover:text-neutral-600 disabled:opacity-30"><ChevronDown size={14} /></button>
                  <button onClick={() => setBlocks((bs) => bs.filter((_, idx) => idx !== i))} className="hover:text-danger"><Trash2 size={14} /></button>
                </div>
              </div>
              <BlockFields block={b} onChange={(patch) => setBlock(i, patch)} />
            </div>
          ))}

          <div className="relative">
            <button onClick={() => setShowAdd((v) => !v)} className="flex items-center gap-1 text-sm font-medium text-primary-600">
              <Plus size={14} /> Adicionar bloco
            </button>
            {showAdd && (
              <div className="absolute z-10 mt-1 grid grid-cols-2 gap-1 rounded-xl border border-neutral-100 bg-white p-2 shadow-card">
                {BLOCK_TYPES.map(([t, label]) => (
                  <button
                    key={t}
                    onClick={() => { setBlocks((bs) => [...bs, blankBlock(t)]); setShowAdd(false); }}
                    className="rounded-lg px-3 py-1.5 text-left text-sm hover:bg-neutral-50"
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Prévia */}
        <div className="overflow-auto rounded-2xl border border-neutral-100 bg-neutral-100 p-4">
          <p className="mb-2 text-center text-xs uppercase tracking-wide text-neutral-400">Pré-visualização</p>
          <div className="overflow-hidden rounded-xl shadow-sm">
            <PageBlocks blocks={blocks} style={page} />
          </div>
        </div>
      </div>
    </div>
  );
}

function BlockFields({ block, onChange }: { block: PageBlock; onChange: (p: Partial<PageBlock>) => void }) {
  const v = (k: string) => (typeof block[k] === "string" ? (block[k] as string) : "");
  const inp = "w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none focus:border-primary-400";
  switch (block.type) {
    case "heading":
    case "text":
      return <textarea value={v("text")} onChange={(e) => onChange({ text: e.target.value })} rows={block.type === "text" ? 3 : 2} className={inp} />;
    case "image":
      return (
        <div className="space-y-1.5">
          <input value={v("url")} onChange={(e) => onChange({ url: e.target.value })} placeholder="URL (https://...)" className={inp} />
          <ImageUploadButton label="Enviar imagem" onUploaded={(url) => onChange({ url })} />
        </div>
      );
    case "video":
      return <input value={v("url")} onChange={(e) => onChange({ url: e.target.value })} placeholder="URL (https://...)" className={inp} />;
    case "button":
      return (
        <div className="space-y-1.5">
          <input value={v("label")} onChange={(e) => onChange({ label: e.target.value })} placeholder="Texto do botão" className={inp} />
          <input value={v("url")} onChange={(e) => onChange({ url: e.target.value })} placeholder="Link (URL)" className={inp} />
        </div>
      );
    case "form":
      return <FormBlockFields block={block} onChange={onChange} />;
    default:
      return <p className="text-xs text-neutral-400">Linha divisória</p>;
  }
}

function FormBlockFields({ block, onChange }: { block: PageBlock; onChange: (p: Partial<PageBlock>) => void }) {
  const v = (k: string) => (typeof block[k] === "string" ? (block[k] as string) : "");
  const extraFields: ExtraField[] = Array.isArray(block.extraFields) ? (block.extraFields as ExtraField[]) : [];
  const inp = "w-full rounded-lg border border-neutral-200 px-2 py-1.5 text-sm outline-none focus:border-primary-400";

  function setFields(next: ExtraField[]) {
    onChange({ extraFields: next });
  }
  function addField() {
    setFields([
      ...extraFields,
      { key: `campo_${Date.now()}`, label: "Nova pergunta", kind: "text", placeholder: "" },
    ]);
  }
  function patchField(i: number, patch: Partial<ExtraField>) {
    setFields(extraFields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  }
  function removeField(i: number) {
    setFields(extraFields.filter((_, idx) => idx !== i));
  }

  return (
    <div className="space-y-2">
      <input value={v("button")} onChange={(e) => onChange({ button: e.target.value })} placeholder="Texto do botão" className={inp} />
      <label className="flex items-center gap-1.5 text-xs text-neutral-500">
        <input type="checkbox" checked={block.showEmail !== false} onChange={(e) => onChange({ showEmail: e.target.checked })} />
        Mostrar campo de e-mail
      </label>
      <input value={v("phoneHelper")} onChange={(e) => onChange({ phoneHelper: e.target.value })} placeholder="Texto de ajuda abaixo do WhatsApp (opcional)" className={inp} />
      <textarea value={v("disclaimer")} onChange={(e) => onChange({ disclaimer: e.target.value })} placeholder="Aviso abaixo do botão (opcional)" rows={2} className={inp} />

      <div className="space-y-2 rounded-lg bg-neutral-50 p-2">
        <p className="text-xs font-semibold text-neutral-500">Campos extras</p>
        {extraFields.map((f, i) => (
          <div key={i} className="space-y-1 rounded-lg border border-neutral-200 bg-white p-2">
            <div className="flex items-center gap-1">
              <input value={f.label} onChange={(e) => patchField(i, { label: e.target.value })} placeholder="Pergunta (rótulo)" className={`${inp} flex-1`} />
              <button onClick={() => removeField(i)} className="text-neutral-300 hover:text-danger"><Trash2 size={14} /></button>
            </div>
            <div className="flex items-center gap-1.5">
              <select value={f.kind} onChange={(e) => patchField(i, { kind: e.target.value as ExtraField["kind"] })} className={inp}>
                <option value="text">Texto livre</option>
                <option value="select">Lista de opções</option>
              </select>
              <label className="flex items-center gap-1 whitespace-nowrap text-xs text-neutral-500">
                <input type="checkbox" checked={!!f.fullWidth} onChange={(e) => patchField(i, { fullWidth: e.target.checked })} />
                Largura total
              </label>
            </div>
            {f.kind === "select" ? (
              <input
                value={(f.options ?? []).join(", ")}
                onChange={(e) => patchField(i, { options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                placeholder="Opções separadas por vírgula"
                className={inp}
              />
            ) : (
              <input value={f.placeholder ?? ""} onChange={(e) => patchField(i, { placeholder: e.target.value })} placeholder="Placeholder" className={inp} />
            )}
            <input value={f.helper ?? ""} onChange={(e) => patchField(i, { helper: e.target.value })} placeholder="Texto de ajuda abaixo do campo (opcional)" className={inp} />
          </div>
        ))}
        <button onClick={addField} className="flex items-center gap-1 text-xs font-medium text-primary-600">
          <Plus size={12} /> Adicionar campo
        </button>
      </div>
    </div>
  );
}
