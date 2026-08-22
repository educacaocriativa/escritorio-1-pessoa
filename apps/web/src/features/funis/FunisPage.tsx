import type { FunnelSummary } from "@e1p/shared-types";
import { Trash2, Workflow } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

export default function FunisPage() {
  const navigate = useNavigate();
  const [funnels, setFunnels] = useState<FunnelSummary[]>([]);

  const load = useCallback(async () => {
    const { data } = await api.get<FunnelSummary[]>("/funnels");
    // `Array.isArray`, e aqui não havia operador nenhum: `funnels.map` É a tela, e o `.length === 0`
    // logo acima não protege — em objeto `.length` é `undefined`, e `undefined === 0` é falso, então
    // o fluxo cai justamente no ramo que faz o `.map`.
    setFunnels(Array.isArray(data) ? data : []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo funil", useCallback(() => navigate("/funis/novo"), [navigate]));

  async function remove(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm("Excluir este funil?")) return;
    await api.delete(`/funnels/${id}`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Funil de Vendas</p>
        <h1 className="text-2xl font-bold text-neutral-800">Funis de Vendas</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Monte o fluxo da sua operação arrastando gatilhos, ações, comunicação e tráfego.
        </p>
      </div>

      {funnels.length === 0 ? (
        <div className="rounded-2xl bg-white p-10 text-center text-sm text-neutral-400 shadow-sm">
          Nenhum funil ainda. Clique em "Novo funil".
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {funnels.map((f) => (
            // ⚠️ A lixeira é IRMÃ do card, nunca filha (#160). `<button>` dentro de `<button>` não
            // é só HTML inválido: quando dois alvos clicáveis são aninhados, o navegador emite o
            // `click` no ANCESTRAL COMUM de `mousedown` e `mouseup`, e **10px de deslocamento já
            // bastam** (limiar medido no #149) para o toque na lixeira virar NAVEGAÇÃO. Aqui o
            // ancestral comum é esta `<div>` sem handler, então o escorregão não faz nada — que é
            // a troca que a issue compra. Medido em `e2e/aninhamento-clicavel-360.spec.ts`.
            //
            // ⚠️ Trocar o `<button>` de fora por `<div role="button">` NÃO resolveria: o `click`
            // continuaria caindo nele e o `onClick` continuaria disparando. O que desarma o
            // mecanismo é o parentesco, não a tag.
            <div key={f.id} className="relative">
              <button
                data-testid={`abrir-funil-${f.id}`}
                onClick={() => navigate(`/funis/${f.id}`)}
                className="group flex w-full items-center rounded-2xl bg-white p-5 pr-14 text-left shadow-sm transition hover:shadow-md"
              >
                {/* ⚠️ `min-w-0` nos DOIS níveis, e `break-words` só depois (#182). Item de flex
                    nasce com `min-width: auto`: ele NÃO encolhe abaixo do próprio min-content, e o
                    min-content de um nome sem espaço é o nome inteiro. Medido em 360×740 com um
                    título de 74 chars: a caixa do `<button w-full>` continuava em 312px (cabe), e
                    a tinta ia para x=676 — **316px além da borda** — enquanto
                    `documentElement.scrollWidth` seguia em 360, porque `main` é `overflow-x-hidden`
                    e recorta. `break-words` sozinho não muda número nenhum aqui: ele quebra a
                    palavra DENTRO da caixa, e a caixa é que estava larga demais (§5.4). */}
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                    <Workflow size={18} />
                  </span>
                  <div className="min-w-0">
                    <p className="break-words font-semibold text-neutral-800">{f.name}</p>
                    <p className="text-xs text-neutral-400">{f.node_count} componentes</p>
                  </div>
                </div>
              </button>
              <button
                data-testid={`excluir-funil-${f.id}`}
                aria-label={`Excluir ${f.name}`}
                onClick={(e) => remove(e, f.id)}
                className="absolute right-5 top-1/2 -translate-y-1/2 text-neutral-300 hover:text-danger"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
