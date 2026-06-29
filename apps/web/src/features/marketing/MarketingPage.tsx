import type { Carousel } from "@e1p/shared-types";
import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import { SlideCard } from "./CarouselSlideView";

export default function MarketingPage() {
  const navigate = useNavigate();
  const [carousels, setCarousels] = useState<Carousel[]>([]);

  const load = useCallback(async () => {
    const { data } = await api.get<Carousel[]>("/marketing/carousels");
    setCarousels(data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo carrossel", useCallback(() => navigate("/marketing/novo"), [navigate]));

  async function remove(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm("Excluir este carrossel?")) return;
    await api.delete(`/marketing/carousels/${id}`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Marketing</p>
        <h1 className="text-2xl font-bold text-neutral-800">Carrosséis</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Gere carrosséis com IA e personalize cores, fontes e template.
        </p>
      </div>

      {carousels.length === 0 ? (
        <div className="rounded-2xl bg-white p-10 text-center text-sm text-neutral-400 shadow-sm">
          Nenhum carrossel ainda. Clique em "Novo carrossel".
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {carousels.map((c) => (
            <button
              key={c.id}
              onClick={() => navigate(`/marketing/${c.id}`)}
              className="group text-left"
            >
              <div className="overflow-hidden rounded-2xl shadow-sm transition group-hover:shadow-md">
                {c.slides.length > 0 ? (
                  <SlideCard slide={c.slides[0]} style={c} index={0} total={c.slides.length} />
                ) : (
                  <div
                    className="flex aspect-square items-center justify-center text-sm"
                    style={{ background: c.bg_color, color: c.text_color }}
                  >
                    Sem slides
                  </div>
                )}
              </div>
              <div className="mt-2 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-neutral-700">{c.topic}</p>
                  <p className="text-xs text-neutral-400">
                    {c.slides.length} slides · {c.status === "ready" ? "Pronto" : "Rascunho"}
                  </p>
                </div>
                <button onClick={(e) => remove(e, c.id)} className="shrink-0 text-neutral-300 hover:text-danger">
                  <Trash2 size={14} />
                </button>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
