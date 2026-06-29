import type { Contract, ContractsSummary } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const statusInfo: Record<Contract["status"], { label: string; cls: string }> = {
  draft: { label: "Rascunho", cls: "bg-neutral-100 text-neutral-500" },
  sent: { label: "Enviado", cls: "bg-blue-50 text-blue-700" },
  signed: { label: "Assinado", cls: "bg-accent-50 text-accent-700" },
  cancelled: { label: "Cancelado", cls: "bg-red-50 text-danger" },
};

export default function ContratosPage() {
  const navigate = useNavigate();
  const empty: ContractsSummary = { draft_count: 0, sent_count: 0, signed_count: 0 };
  const [summary, setSummary] = useState<ContractsSummary>(empty);
  const [contracts, setContracts] = useState<Contract[]>([]);

  const load = useCallback(async () => {
    const [s, c] = await Promise.all([
      api.get<ContractsSummary>("/contracts/summary"),
      api.get<Contract[]>("/contracts"),
    ]);
    setSummary(s.data);
    setContracts(c.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo contrato", useCallback(() => navigate("/contratos/novo"), [navigate]));

  async function cancel(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    if (!confirm("Cancelar este contrato?")) return;
    await api.post(`/contracts/${id}/cancel`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Contratos</p>
        <h1 className="text-2xl font-bold text-neutral-800">Contratos</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Rascunhos" value={summary.draft_count} tone="text-neutral-700" />
        <Stat label="Aguardando assinatura" value={summary.sent_count} tone="text-blue-700" />
        <Stat label="Assinados" value={summary.signed_count} tone="text-accent-700" />
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {contracts.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhum contrato. Clique em "Novo contrato".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Cliente</th>
                <th className="px-4 py-3 font-medium">Título</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Assinante</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/contratos/${c.id}`)}
                  className="cursor-pointer border-b border-neutral-50 last:border-0 hover:bg-neutral-50"
                >
                  <td className="px-4 py-3 font-medium text-neutral-800">{c.client_name || "—"}</td>
                  <td className="px-4 py-3 text-neutral-600">{c.title}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-pill px-2 py-0.5 text-xs ${statusInfo[c.status].cls}`}>
                      {statusInfo[c.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-neutral-500">
                    {c.signer_name ? (
                      <>
                        {c.signer_name}
                        {c.signed_at && (
                          <span className="block text-neutral-400">
                            {new Date(c.signed_at).toLocaleDateString("pt-BR")}
                          </span>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {c.status !== "signed" && c.status !== "cancelled" && (
                      <button onClick={(e) => cancel(e, c.id)} className="text-xs font-medium text-neutral-400 hover:text-danger">
                        Cancelar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}
