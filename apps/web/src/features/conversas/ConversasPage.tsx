import type {
  ConversationSummary, TimelineEntry, WhatsappTemplate,
} from "@e1p/shared-types";
import { Paperclip, Send, Users } from "lucide-react";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

const POLL_MS = 7000;

// ── Datas ───────────────────────────────────────────────────────────────────
// Tudo abaixo trabalha no fuso LOCAL do usuário de propósito: `created_at` é um INSTANTE
// (timestamptz, ver TimestampMixin), não uma data de negócio — então a regra da Agenda
// ("compare all-day por data de calendário UTC") não vale aqui; é o caso oposto. Agrupar por
// `created_at.slice(0,10)` colocaria uma mensagem das 22h de Brasília no dia seguinte.

const dayKey = (iso: string) => new Date(iso).toLocaleDateString("pt-BR");

const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

function dayLabel(iso: string): string {
  const key = dayKey(iso);
  const hoje = new Date();
  const ontem = new Date(hoje);
  ontem.setDate(hoje.getDate() - 1);
  if (key === dayKey(hoje.toISOString())) return "Hoje";
  if (key === dayKey(ontem.toISOString())) return "Ontem";
  return new Date(iso).toLocaleDateString("pt-BR", {
    weekday: "short", day: "2-digit", month: "2-digit", year: "numeric",
  });
}

/** Carimbo da lista de conversas: horário se foi hoje, senão a data (critério do WhatsApp). */
function listStamp(iso: string | null): string {
  if (!iso) return "";
  return dayKey(iso) === dayKey(new Date().toISOString()) ? hhmm(iso) : dayKey(iso);
}

export default function ConversasPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const loadConversations = useCallback(async () => {
    const { data } = await api.get<ConversationSummary[]>("/whatsapp-conversations");
    setConversations(data);
  }, []);

  useEffect(() => {
    loadConversations();
    const id = setInterval(loadConversations, POLL_MS);
    return () => clearInterval(id);
  }, [loadConversations]);

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4">
      <div className="w-80 shrink-0 overflow-y-auto rounded-2xl bg-white shadow-sm">
        <div className="border-b border-neutral-100 p-4">
          <h1 className="font-semibold text-neutral-800">Conversas</h1>
        </div>
        {conversations.length === 0 ? (
          <p className="p-4 text-sm text-neutral-400">Nenhuma conversa ainda.</p>
        ) : (
          conversations.map((c) => (
            <button
              key={c.chat_id}
              onClick={() => setSelected(c.chat_id)}
              className={`block w-full border-b border-neutral-50 px-4 py-3 text-left hover:bg-neutral-50 ${
                selected === c.chat_id ? "bg-primary-50" : ""
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5">
                  {c.kind === "group" && (
                    <Users size={13} className="shrink-0 text-neutral-400" aria-label="Grupo" />
                  )}
                  <span className="truncate text-sm font-semibold text-neutral-800">
                    {c.title}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-neutral-400">
                  {listStamp(c.last_message_at)}
                  {c.unread && <span className="h-2 w-2 rounded-full bg-primary-600" />}
                </span>
              </div>
              <p className="mt-0.5 truncate text-xs text-neutral-400">
                {c.last_message_preview}
              </p>
            </button>
          ))
        )}
      </div>
      <div className="flex-1 rounded-2xl bg-white shadow-sm">
        {selected ? (
          <ConversationThread
            key={selected}
            chatId={selected}
            chat={conversations.find((c) => c.chat_id === selected) ?? null}
            onSent={loadConversations}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-neutral-400">
            Selecione uma conversa
          </div>
        )}
      </div>
    </div>
  );
}

function ConversationThread({
  chatId, chat, onSent,
}: { chatId: string; chat: ConversationSummary | null; onSent: () => void }) {
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [withinWindow, setWithinWindow] = useState(true);
  const [approvedTemplates, setApprovedTemplates] = useState<WhatsappTemplate[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [imageUrls, setImageUrls] = useState<Record<string, string>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [tl, win] = await Promise.all([
      api.get<TimelineEntry[]>(`/whatsapp-conversations/${chatId}/timeline`),
      api.get<{ within_session_window: boolean }>(`/whatsapp-conversations/${chatId}/window`),
    ]);
    setTimeline(tl.data);
    setWithinWindow(win.data.within_session_window);
    if (!win.data.within_session_window) {
      const { data } = await api.get<WhatsappTemplate[]>("/whatsapp-templates", {
        params: { status: "APPROVED" },
      });
      setApprovedTemplates(data);
    }
    await api.post(`/whatsapp-conversations/${chatId}/read`);
  }, [chatId]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const missing = timeline.filter(
      (e) => e.kind === "image" && e.media_attachment_id && !imageUrls[e.media_attachment_id],
    );
    if (missing.length === 0) return;
    let cancelled = false;
    Promise.all(
      missing.map(async (e) => {
        const { data } = await api.get(`/attachments/${e.media_attachment_id}/download`, {
          responseType: "blob",
        });
        return [e.media_attachment_id as string, URL.createObjectURL(data as Blob)] as const;
      }),
    ).then((pairs) => {
      if (cancelled) return;
      setImageUrls((prev) => ({ ...prev, ...Object.fromEntries(pairs) }));
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeline]);

  useEffect(() => {
    // Revoga os object URLs ao desmontar (troca de conversa) — evita vazar memória.
    return () => {
      Object.values(imageUrls).forEach((url) => URL.revokeObjectURL(url));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  async function sendText() {
    if (!text.trim()) return;
    setError(null);
    try {
      await api.post(`/whatsapp-conversations/${chatId}/messages/text`, { text });
      setText("");
      await load();
      onSent();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function openAttachment(attachmentId: string) {
    const { data } = await api.get(`/attachments/${attachmentId}/download`, {
      responseType: "blob",
    });
    window.open(URL.createObjectURL(data as Blob), "_blank");
  }

  async function sendMedia(file: File) {
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      await api.post(`/whatsapp-conversations/${chatId}/messages/media`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await load();
      onSent();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-neutral-100 px-4 py-3">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-neutral-800">
          {chat?.kind === "group" && <Users size={14} className="text-neutral-400" />}
          {chat?.title ?? "Conversa"}
        </p>
        <p className="text-xs text-neutral-400">
          {chat?.kind === "group" ? "Grupo" : chat?.phone}
        </p>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto p-4">
        {timeline.map((entry, i) => {
          // Três tons, não dois: "automated" também é `direction="out"` (aviso que a plataforma
          // mandou), mas vive centralizado em fundo claro — tratá-lo como "out" pintaria texto
          // branco sobre cinza claro.
          const tone =
            entry.source === "automated" ? "auto"
              : entry.direction === "out" ? "out"
                : "in";
          const showDay =
            i === 0 || dayKey(entry.created_at) !== dayKey(timeline[i - 1].created_at);
          return (
            <Fragment key={i}>
              {showDay && (
                <div className="flex justify-center py-2">
                  <span className="rounded-pill bg-neutral-100 px-3 py-1 text-[11px] font-medium text-neutral-500">
                    {dayLabel(entry.created_at)}
                  </span>
                </div>
              )}
              <div
                className={`max-w-md rounded-xl px-3 py-2 text-sm ${
                  tone === "auto"
                    ? "mx-auto bg-neutral-100 text-neutral-500"
                    : tone === "out"
                      ? "ml-auto bg-primary-600 text-white"
                      : "mr-auto bg-neutral-100 text-neutral-800"
                }`}
              >
                {tone === "auto" && (
                  <p className="mb-0.5 text-xs font-semibold">🤖 {entry.purpose_label}</p>
                )}
                {/* Em grupo, sem isto todas as bolhas recebidas são anônimas — não dá pra saber
                    quem falou. O backend só manda `sender_name` quando ele acrescenta algo:
                    nunca em conversa direta, nunca numa mensagem nossa. */}
                {entry.sender_name && (
                  <p className="mb-0.5 text-xs font-semibold text-primary-600">
                    {entry.sender_name}
                  </p>
                )}
                {entry.kind === "image" && entry.media_attachment_id && (
                  imageUrls[entry.media_attachment_id] ? (
                    <img
                      src={imageUrls[entry.media_attachment_id]}
                      onClick={() => openAttachment(entry.media_attachment_id!)}
                      alt={entry.text_body || "Imagem"}
                      className="mb-1 max-h-72 w-full cursor-pointer rounded-lg object-cover"
                    />
                  ) : (
                    <div className="mb-1 flex h-40 w-full items-center justify-center rounded-lg bg-black/10 text-xs">
                      Carregando imagem...
                    </div>
                  )
                )}
                {entry.kind !== "image" && entry.media_attachment_id && (
                  <button
                    onClick={() => openAttachment(entry.media_attachment_id!)}
                    className={`mb-1 flex items-center gap-1 text-xs font-semibold underline ${
                      tone === "out" ? "text-white" : "text-primary-600"
                    }`}
                  >
                    <Paperclip size={12} />
                    Baixar anexo
                  </button>
                )}
                {(entry.text_body || !entry.media_attachment_id) && (
                  <p className="whitespace-pre-wrap">
                    {entry.text_body || `[${entry.kind}]`}
                  </p>
                )}
                {/* Autoria em TEXTO, não só por cor/lado: quem chega numa conversa espelhada do
                    celular precisa conseguir dizer quem escreveu sem depender do layout. */}
                <p
                  className={`mt-1 text-[11px] ${
                    tone === "out" ? "text-right text-white/70" : "text-neutral-400"
                  }`}
                >
                  {tone === "out" ? "Você · " : ""}{hhmm(entry.created_at)}
                </p>
              </div>
            </Fragment>
          );
        })}
      </div>
      {error && <div className="mx-4 mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
      <div className="border-t border-neutral-100 p-3">
        {withinWindow ? (
          <div className="flex items-center gap-2">
            <button
              onClick={() => fileInputRef.current?.click()}
              className="rounded-lg border border-neutral-200 p-2 text-neutral-500 hover:bg-neutral-50"
              title="Anexar arquivo"
            >
              <Paperclip size={16} />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) sendMedia(file);
                e.target.value = "";
              }}
            />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendText()}
              placeholder="Digite uma mensagem..."
              className="flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
            />
            <button
              onClick={sendText}
              className="rounded-pill bg-primary-600 p-2 text-white hover:bg-primary-700"
            >
              <Send size={16} />
            </button>
          </div>
        ) : (
          <TemplateReplyBox
            chatId={chatId}
            templates={approvedTemplates}
            onSent={async () => {
              await load();
              onSent();
            }}
          />
        )}
      </div>
    </div>
  );
}

function TemplateReplyBox({
  chatId, templates, onSent,
}: { chatId: string; templates: WhatsappTemplate[]; onSent: () => void }) {
  const [templateId, setTemplateId] = useState("");
  const [variables, setVariables] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const selected = templates.find((t) => t.id === templateId) ?? null;

  async function send() {
    setError(null);
    try {
      await api.post(`/whatsapp-conversations/${chatId}/messages/template`, {
        template_id: templateId, variables,
      });
      setTemplateId("");
      setVariables([]);
      onSent();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-neutral-400">
        Fora da janela de 24h — selecione um template aprovado para responder.
      </p>
      {templates.length === 0 ? (
        <p className="text-sm text-neutral-400">Nenhum template aprovado ainda.</p>
      ) : (
        <>
          <select
            value={templateId}
            onChange={(e) => {
              setTemplateId(e.target.value);
              const tpl = templates.find((t) => t.id === e.target.value);
              setVariables(tpl ? Array(tpl.variable_count).fill("") : []);
            }}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm"
          >
            <option value="">Selecione um template</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>{t.name} ({t.language})</option>
            ))}
          </select>
          {selected && (
            <>
              {Array.from({ length: selected.variable_count }, (_, i) => (
                <input
                  key={i}
                  value={variables[i] ?? ""}
                  onChange={(e) => {
                    const next = [...variables];
                    next[i] = e.target.value;
                    setVariables(next);
                  }}
                  placeholder={selected.variable_examples[i] ?? `Variável ${i + 1}`}
                  className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm"
                />
              ))}
              {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-danger">{error}</div>}
              <button
                onClick={send}
                className="w-full rounded-pill bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700"
              >
                Enviar
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
