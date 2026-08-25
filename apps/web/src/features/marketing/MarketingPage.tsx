import type { Carousel } from "@e1p/shared-types";
import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import { CarouselThumb } from "./CarouselSlideView";

export default function MarketingPage() {
  const navigate = useNavigate();
  const [carousels, setCarousels] = useState<Carousel[]>([]);

  const load = useCallback(async () => {
    const { data } = await api.get<Carousel[]>("/marketing/carousels");
    // `Array.isArray`, e aqui não havia operador nenhum: `carousels.map` É a tela, e o
    // `.length === 0` acima não desvia — em objeto `.length` é `undefined`, nunca `0`.
    setCarousels(Array.isArray(data) ? data : []);
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
            // ⚠️ A lixeira é IRMÃ do card, nunca filha (#160) — ver o comentário longo em
            // `funis/FunisPage.tsx`. Resumo: com os dois alvos aninhados, 10px de deslocamento
            // entre `mousedown` e `mouseup` fazem o navegador emitir o `click` no ancestral
            // comum, e o toque na lixeira vira navegação (#149). Esta era a ÚNICA das três telas
            // em que o defeito já aparecia com um título de tamanho comum — nas outras duas a
            // lixeira ia parar fora da viewport de 360px antes de o escorregão poder acontecer.
            <div key={c.id} className="relative">
              <button
                data-testid={`abrir-carrossel-${c.id}`}
                onClick={() => navigate(`/marketing/${c.id}`)}
                className="group block w-full text-left"
              >
                <div className="flex justify-center overflow-hidden rounded-2xl shadow-sm transition group-hover:shadow-md">
                  <CarouselThumb slides={c.slides} style={c} display={240} />
                </div>
                <div className="mt-2 min-w-0 pr-6">
                  <p className="truncate text-sm font-medium text-neutral-700">{c.topic}</p>
                  <p className="text-xs text-neutral-400">
                    {c.slides.length} slides · {c.status === "ready" ? "Pronto" : "Rascunho"}
                  </p>
                </div>
              </button>
              <button
                data-testid={`excluir-carrossel-${c.id}`}
                aria-label={`Excluir ${c.topic}`}
                onClick={(e) => remove(e, c.id)}
                className="absolute bottom-0 right-0 text-neutral-300 hover:text-danger"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
