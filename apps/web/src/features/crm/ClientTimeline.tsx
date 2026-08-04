import type { ClientTimelineEntry, ClientTimelineOut } from "@e1p/shared-types";
import {
  ArrowRightLeft, FileText, MessageSquarePlus, Receipt, RotateCcw,
  Sparkles, UserPlus, Workflow,
} from "lucide-react";
import type { JSX } from "react";
import { useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

/** Ícone e cor por tipo de fato. Um `kind` novo vindo de um backend mais recente cai no
 *  neutro em vez de sumir da tela. */
const APARENCIA: Record<string, { icon: JSX.Element; cor: string }> = {
  lead_created: { icon: <UserPlus size={14} />, cor: "bg-primary-50 text-primary-700" },
  lead_return: { icon: <RotateCcw size={14} />, cor: "bg-primary-50 text-primary-700" },
  stage_move: { icon: <ArrowRightLeft size={14} />, cor: "bg-neutral-100 text-neutral-600" },
  reopened: { icon: <RotateCcw size={14} />, cor: "bg-amber-50 text-amber-700" },
  note: { icon: <MessageSquarePlus size={14} />, cor: "bg-emerald-50 text-emerald-700" },
  funnel: { icon: <Workflow size={14} />, cor: "bg-neutral-100 text-neutral-600" },
  quote: { icon: <FileText size={14} />, cor: "bg-sky-50 text-sky-700" },
  charge: { icon: <Receipt size={14} />, cor: "bg-sky-50 text-sky-700" },
  payment: { icon: <Receipt size={14} />, cor: "bg-emerald-50 text-emerald-700" },
};

const NEUTRO = { icon: <Sparkles size={14} />, cor: "bg-neutral-100 text-neutral-600" };

/** `at` é um INSTANTE (timestamptz), não uma data de negócio — formata no fuso local, mesma
 *  convenção da ConversasPage (e o oposto da regra all-day da Agenda). */
const quando = (iso: string) =>
  new Date(iso).toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });

export default function ClientTimeline({ clientId }: { clientId: string }) {
  const [entries, setEntries] = useState<ClientTimelineEntry[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [nota, setNota] = useState("");
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  const load = useCallback(async () => {
    // Falha aqui NÃO pode derrubar quem hospeda o painel. Na tela de Conversas este
    // componente é uma coluna lateral: se ele estourasse, levaria junto a leitura e a
    // resposta de mensagens — o trabalho principal da tela — por causa de um histórico que
    // não carregou. Degrada para um aviso e mantém o resto de pé.
    try {
      const { data } = await api.get<ClientTimelineOut>(`/crm/clients/${clientId}/timeline`);
      // `Array.isArray`, e não `data?.entries ?? []`: se a resposta vier como um array (por
      // exemplo de um endpoint que mudou de contrato), `data.entries` NÃO é `undefined` — é
      // `Array.prototype.entries`, uma função. O `??` deixaria passar, e um setter de estado
      // que recebe função a trata como updater e a EXECUTA, estourando dentro do React.
      setEntries(Array.isArray(data?.entries) ? data.entries : []);
      setTruncated(data?.truncated === true);
      setErro("");
    } catch (e) {
      setEntries([]);
      setTruncated(false);
      setErro(apiErrorMessage(e));
    }
  }, [clientId]);

  useEffect(() => {
    load();
  }, [load]);

  async function registrar() {
    const titulo = nota.trim();
    if (!titulo) return;
    setSalvando(true);
    setErro("");
    try {
      await api.post(`/crm/clients/${clientId}/notes`, { title: titulo, body: "" });
      setNota("");
      await load();
    } catch (e) {
      setErro(apiErrorMessage(e));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex gap-2">
        <input
          value={nota}
          onChange={(e) => setNota(e.target.value)}
          placeholder="Registrar uma decisão..."
          className="min-w-0 flex-1 rounded-xl border border-neutral-200 px-3 py-2 text-sm"
        />
        <button
          onClick={registrar}
          disabled={salvando || !nota.trim()}
          className="shrink-0 rounded-xl bg-primary-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          Registrar
        </button>
      </div>
      {erro && <p className="text-sm text-rose-600">{erro}</p>}

      {truncated && (
        <p className="text-[11px] text-neutral-400">
          Mostrando os 100 registros mais recentes.
        </p>
      )}

      {entries.length === 0 ? (
        <p className="text-sm text-neutral-400">Nenhum registro ainda.</p>
      ) : (
        <ol className="flex flex-col gap-3 overflow-y-auto">
          {entries.map((e) => {
            const look = APARENCIA[e.kind] ?? NEUTRO;
            return (
              <li key={e.id} className="flex gap-2">
                <span className={`mt-0.5 shrink-0 rounded-lg p-1.5 ${look.cor}`}>
                  {look.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <p
                    data-testid="timeline-title"
                    className="text-sm font-medium text-neutral-800"
                  >
                    {e.title}
                  </p>
                  {e.body && (
                    <p className="whitespace-pre-wrap text-sm text-neutral-600">{e.body}</p>
                  )}
                  <p className="text-[11px] text-neutral-400">
                    {quando(e.at)}
                    {e.is_ai && " · IA"}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
