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
    setFunnels(data);
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
            <button
              key={f.id}
              onClick={() => navigate(`/funis/${f.id}`)}
              className="group flex items-center justify-between rounded-2xl bg-white p-5 text-left shadow-sm transition hover:shadow-md"
            >
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-50 text-primary-600">
                  <Workflow size={18} />
                </span>
                <div>
                  <p className="font-semibold text-neutral-800">{f.name}</p>
                  <p className="text-xs text-neutral-400">{f.node_count} componentes</p>
                </div>
              </div>
              <button onClick={(e) => remove(e, f.id)} className="text-neutral-300 hover:text-danger">
                <Trash2 size={16} />
              </button>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
