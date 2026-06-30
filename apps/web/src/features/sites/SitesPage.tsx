import type { PageSummary } from "@e1p/shared-types";
import { ExternalLink, Globe, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const MODELS: [string, string][] = [
  ["vendas", "Vendas"], ["captura", "Captura de leads"], ["obrigado", "Obrigado"],
  ["checkout", "Checkout"], ["download", "Download"], ["webinar", "Webinar"],
  ["conteudo", "Conteúdo (em branco)"],
];

export default function SitesPage() {
  const navigate = useNavigate();
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const { data } = await api.get<PageSummary[]>("/pages");
    setPages(data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Nova página", useCallback(() => setOpen(true), []));

  async function remove(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm("Excluir esta página?")) return;
    await api.delete(`/pages/${id}`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Sites</p>
        <h1 className="text-2xl font-bold text-neutral-800">Sites & Páginas</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Crie páginas de vendas, captura e obrigado — publicadas com link próprio.
        </p>
      </div>

      {pages.length === 0 ? (
        <div className="rounded-2xl bg-white p-10 text-center text-sm text-neutral-400 shadow-sm">
          Nenhuma página ainda. Clique em "Nova página".
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {pages.map((p) => (
            <div
              key={p.id}
              onClick={() => navigate(`/sites/${p.id}`)}
              className="cursor-pointer rounded-2xl bg-white p-5 shadow-sm transition hover:shadow-md"
            >
              <div className="mb-2 flex items-start justify-between">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                  <Globe size={16} />
                </span>
                <span
                  className={`rounded-pill px-2 py-0.5 text-xs ${p.status === "published" ? "bg-accent-50 text-accent-700" : "bg-neutral-100 text-neutral-500"}`}
                >
                  {p.status === "published" ? "Publicada" : "Rascunho"}
                </span>
              </div>
              <p className="font-semibold text-neutral-800">{p.title}</p>
              <p className="text-xs text-neutral-400">{MODELS.find(([m]) => m === p.model)?.[1] ?? p.model}</p>
              <div className="mt-3 flex items-center justify-between">
                {p.status === "published" && p.public_slug ? (
                  <a
                    href={`/p/${p.public_slug}`}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary-600"
                  >
                    abrir link <ExternalLink size={11} />
                  </a>
                ) : (
                  <span className="text-xs text-neutral-300">não publicada</span>
                )}
                <button onClick={(e) => remove(e, p.id)} className="text-neutral-300 hover:text-danger">
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <NewPageModal open={open} onClose={() => setOpen(false)} />
    </div>
  );
}

function NewPageModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [model, setModel] = useState("vendas");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function create() {
    setError(null);
    setSaving(true);
    try {
      const { data } = await api.post<{ id: string }>("/pages", { title, model });
      navigate(`/sites/${data.id}`);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova página" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Título" value={title} onChange={setTitle} placeholder="Minha landing page" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Modelo</span>
          <select value={model} onChange={(e) => setModel(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
            {MODELS.map(([m, label]) => <option key={m} value={m}>{label}</option>)}
          </select>
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={create} disabled={saving || !title} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Criando..." : "Criar página"}
        </button>
      </div>
    </Modal>
  );
}
