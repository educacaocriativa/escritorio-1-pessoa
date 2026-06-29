import type { Quote, QuotesSummary } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const statusInfo: Record<Quote["status"], { label: string; cls: string }> = {
  draft: { label: "Rascunho", cls: "bg-neutral-100 text-neutral-500" },
  sent: { label: "Enviado", cls: "bg-blue-50 text-blue-700" },
  approved: { label: "Aprovado", cls: "bg-accent-50 text-accent-700" },
  rejected: { label: "Recusado", cls: "bg-red-50 text-danger" },
};

export default function OrcamentosPage() {
  const navigate = useNavigate();
  const empty: QuotesSummary = { draft_count: 0, sent_cents: 0, approved_cents: 0, approved_count: 0 };
  const [summary, setSummary] = useState<QuotesSummary>(empty);
  const [quotes, setQuotes] = useState<Quote[]>([]);

  const load = useCallback(async () => {
    const [s, q] = await Promise.all([
      api.get<QuotesSummary>("/quotes/summary"),
      api.get<Quote[]>("/quotes"),
    ]);
    setSummary(s.data);
    setQuotes(q.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo orçamento", useCallback(() => navigate("/orcamentos/novo"), [navigate]));

  async function act(e: React.MouseEvent, id: string, action: "send" | "approve" | "reject") {
    e.stopPropagation();
    if (action === "approve" && !confirm("Aprovar gera a cobrança automaticamente. Confirmar?"))
      return;
    await api.post(`/quotes/${id}/${action}`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Orçamentos</p>
        <h1 className="text-2xl font-bold text-neutral-800">Orçamentos</h1>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Rascunhos" value={String(summary.draft_count)} tone="text-neutral-700" />
        <Stat label="Enviados (aguardando)" value={brl(summary.sent_cents)} tone="text-blue-700" />
        <Stat label="Aprovados" value={brl(summary.approved_cents)} tone="text-accent-700" />
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {quotes.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhum orçamento. Clique em "Novo orçamento".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Cliente</th>
                <th className="px-4 py-3 font-medium">Título</th>
                <th className="px-4 py-3 font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {quotes.map((q) => (
                <tr
                  key={q.id}
                  onClick={() => navigate(`/orcamentos/${q.id}`)}
                  className="cursor-pointer border-b border-neutral-50 last:border-0 hover:bg-neutral-50"
                >
                  <td className="px-4 py-3 font-medium text-neutral-800">{q.client_name || "—"}</td>
                  <td className="px-4 py-3 text-neutral-600">{q.title}</td>
                  <td className="px-4 py-3 font-medium tabular-nums">{brl(q.total_cents)}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-pill px-2 py-0.5 text-xs ${statusInfo[q.status].cls}`}>
                      {statusInfo[q.status].label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-3 text-xs font-medium">
                      {(q.status === "draft" || q.status === "sent") && (
                        <button onClick={(e) => act(e, q.id, "send")} className="text-blue-600 hover:underline">
                          Enviar
                        </button>
                      )}
                      {q.status !== "approved" && q.status !== "rejected" && (
                        <button onClick={(e) => act(e, q.id, "approve")} className="text-accent-600 hover:underline">
                          Aprovar
                        </button>
                      )}
                      {q.status !== "approved" && q.status !== "rejected" && (
                        <button onClick={(e) => act(e, q.id, "reject")} className="text-neutral-400 hover:text-danger">
                          Recusar
                        </button>
                      )}
                    </div>
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

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}
