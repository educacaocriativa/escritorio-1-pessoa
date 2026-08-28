import type { ConversationSummary, TenantProfile, TimelineEntry } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { formatTime } from "../../lib/datetime";
import { capabilitiesFor } from "../../lib/whatsappCapabilities";
import { useFuso } from "../../store/auth";

/** Quantas falas cabem sem a ficha virar uma segunda tela de Conversas. */
const ULTIMAS = 5;

/**
 * O teor da conversa na ficha 360° — uma JANELA, não um posto de trabalho.
 *
 * Mostra e leva para lá; responder continua sendo trabalho da tela de Conversas. A regra da
 * janela de 24h da Meta e a escolha de template vivem lá, e duplicá-las aqui criaria um
 * segundo lugar para o envio falhar de um jeito diferente.
 *
 * Não confundir com o `ClientTimeline` logo acima na ficha: aquele é a NARRATIVA do
 * relacionamento (chegou, moveu, pagou, escreveu); este é o TEOR, o que foi dito.
 */
export default function BlocoDaConversa(
  { clientId, clientPhone }: { clientId: string; clientPhone?: string | null },
) {
  const fuso = useFuso();
  const [conversas, setConversas] = useState<ConversationSummary[]>([]);
  const [mensagens, setMensagens] = useState<TimelineEntry[]>([]);
  const [erro, setErro] = useState(false);
  const [carregando, setCarregando] = useState(true);
  // Só a Evolution (QR code) permite abrir conversa do zero — a Meta exige template aprovado
  // (ver app/core/whatsapp/capabilities.py). Busca própria, à parte do `load()`: uma falha aqui
  // só deve esconder o compositor, nunca derrubar o resto do bloco.
  const [podeIniciar, setPodeIniciar] = useState(false);
  const [mensagemNova, setMensagemNova] = useState("");
  const [enviando, setEnviando] = useState(false);

  const load = useCallback(async () => {
    // Falha aqui NÃO pode derrubar a ficha — mesma postura do `ClientTimeline`, que degrada
    // para um aviso em vez de levar junto cobranças, contratos e o resto da tela.
    try {
      const { data } = await api.get<ConversationSummary[]>(
        `/whatsapp-conversations?client_id=${encodeURIComponent(clientId)}`,
      );
      const lista = Array.isArray(data) ? data : [];
      setConversas(lista);
      const recente = maisRecente(lista);
      if (recente) {
        // `limit` corta no SERVIDOR — sem isto a ficha baixava a conversa inteira (podem ser
        // milhares de mensagens num cliente ativo) só para mostrar cinco bolhas. O backend já
        // devolve na ordem ascendente que este componente espera; nada a reordenar aqui.
        const t = await api.get<TimelineEntry[]>(
          `/whatsapp-conversations/${recente.chat_id}/timeline?limit=${ULTIMAS}`,
        );
        setMensagens(Array.isArray(t.data) ? t.data : []);
      } else {
        setMensagens([]);
      }
      setErro(false);
    } catch {
      setErro(true);
      setConversas([]);
      setMensagens([]);
    } finally {
      setCarregando(false);
    }
  }, [clientId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api
      .get<TenantProfile>("/settings/profile")
      .then(({ data }) => setPodeIniciar(!capabilitiesFor(data.whatsapp_provider).sessionWindow))
      .catch(() => setPodeIniciar(false));
  }, []);

  const iniciar = useCallback(async () => {
    const texto = mensagemNova.trim();
    if (!texto) return;
    setEnviando(true);
    try {
      await api.post("/whatsapp-conversations/start", { client_id: clientId, text: texto });
      setMensagemNova("");
      await load();
    } finally {
      setEnviando(false);
    }
  }, [clientId, mensagemNova, load]);

  if (carregando) return <p className="py-4 text-sm text-neutral-400">Carregando conversa...</p>;
  if (erro) {
    return (
      <p className="py-4 text-sm text-amber-700">
        Não foi possível carregar a conversa.
      </p>
    );
  }

  const recente = maisRecente(conversas);
  if (!recente) {
    if (podeIniciar && clientPhone) {
      return (
        <div className="space-y-2">
          <textarea
            className="w-full resize-none rounded-lg border border-neutral-200 p-2 text-sm text-neutral-800 focus:border-primary-400 focus:outline-none"
            rows={2}
            placeholder="Escreva a primeira mensagem..."
            value={mensagemNova}
            onChange={(e) => setMensagemNova(e.target.value)}
          />
          <button
            type="button"
            onClick={iniciar}
            disabled={!mensagemNova.trim() || enviando}
            className="w-full rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {enviando ? "Enviando..." : "Iniciar conversa"}
          </button>
        </div>
      );
    }
    // Meta exige template aprovado pra abrir conversa do zero (janela de 24h da Cloud API) — um
    // botão que sempre falha é pior que nenhum. `capabilitiesFor` decide isso; ver o comentário
    // no `useEffect` de `podeIniciar` acima.
    return <p className="py-4 text-center text-sm text-neutral-400">Nenhuma conversa no WhatsApp.</p>;
  }

  const outras = conversas.length - 1;

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-1.5">
        {mensagens.length === 0 ? (
          <p className="text-sm text-neutral-400">Conversa ainda sem mensagens.</p>
        ) : (
          mensagens.map((m, i) => (
            <div
              key={`${m.created_at}-${i}`}
              className={`max-w-[85%] break-words rounded-2xl px-3 py-2 text-sm ${
                m.direction === "out"
                  ? "self-end bg-primary-50 text-neutral-800"
                  : "self-start bg-neutral-100 text-neutral-700"
              }`}
            >
              <p className="whitespace-pre-wrap">{m.text_body || `[${m.kind}]`}</p>
              <p className="mt-0.5 text-[10px] text-neutral-400">{formatTime(m.created_at, fuso)}</p>
            </div>
          ))
        )}
      </div>

      <div className="flex items-center justify-between gap-2">
        <Link
          to={`/conversas/${recente.chat_id}`}
          className="text-sm font-medium text-primary-600 hover:text-primary-700"
        >
          Abrir conversa
        </Link>
        {/* Um contato pode ter MAIS DE UMA conversa (`@lid` + telefone — ver o comentário em
            whatsapp_inbox/models.py). Mostrar só a mais recente sem dizer que há outra
            esconderia mensagem do dono. */}
        {outras > 0 && (
          <Link to="/conversas" className="text-xs text-neutral-400 hover:text-neutral-600">
            +{outras} outra{outras > 1 ? "s" : ""} conversa{outras > 1 ? "s" : ""}
          </Link>
        )}
      </div>
    </div>
  );
}

/** A conversa mais recente do contato — por data, não pela ordem em que a API devolveu. */
function maisRecente(lista: ConversationSummary[]): ConversationSummary | null {
  return lista.reduce<ConversationSummary | null>((melhor, c) => {
    if (!melhor) return c;
    if (!c.last_message_at) return melhor;
    if (!melhor.last_message_at) return c;
    return c.last_message_at > melhor.last_message_at ? c : melhor;
  }, null);
}
