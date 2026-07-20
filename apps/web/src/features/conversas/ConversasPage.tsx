import type {
  ConversationSummary, TimelineEntry, WhatsappTemplate,
} from "@e1p/shared-types";
import { Paperclip, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

const POLL_MS = 7000;

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
              key={c.client_id}
              onClick={() => setSelected(c.client_id)}
              className={`block w-full border-b border-neutral-50 px-4 py-3 text-left hover:bg-neutral-50 ${
                selected === c.client_id ? "bg-primary-50" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-neutral-800">{c.client_name}</span>
                {c.unread && <span className="h-2 w-2 rounded-full bg-primary-600" />}
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
          <ConversationThread clientId={selected} onSent={loadConversations} />
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
  clientId, onSent,
}: { clientId: string; onSent: () => void }) {
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [withinWindow, setWithinWindow] = useState(true);
  const [approvedTemplates, setApprovedTemplates] = useState<WhatsappTemplate[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [tl, win] = await Promise.all([
      api.get<TimelineEntry[]>(`/whatsapp-conversations/${clientId}/timeline`),
      api.get<{ within_session_window: boolean }>(`/whatsapp-conversations/${clientId}/window`),
    ]);
    setTimeline(tl.data);
    setWithinWindow(win.data.within_session_window);
    if (!win.data.within_session_window) {
      const { data } = await api.get<WhatsappTemplate[]>("/whatsapp-templates", {
        params: { status: "APPROVED" },
      });
      setApprovedTemplates(data);
    }
    await api.post(`/whatsapp-conversations/${clientId}/read`);
  }, [clientId]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  async function sendText() {
    if (!text.trim()) return;
    setError(null);
    try {
      await api.post(`/whatsapp-conversations/${clientId}/messages/text`, { text });
      setText("");
      await load();
      onSent();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function sendMedia(file: File) {
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      await api.post(`/whatsapp-conversations/${clientId}/messages/media`, form, {
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
      <div className="flex-1 space-y-2 overflow-y-auto p-4">
        {timeline.map((entry, i) => (
          <div
            key={i}
            className={`max-w-md rounded-xl px-3 py-2 text-sm ${
              entry.source === "automated"
                ? "mx-auto bg-neutral-100 text-neutral-500"
                : entry.direction === "out"
                  ? "ml-auto bg-primary-600 text-white"
                  : "bg-neutral-100 text-neutral-800"
            }`}
          >
            {entry.source === "automated" && (
              <p className="mb-0.5 text-xs font-semibold">🤖 {entry.purpose_label}</p>
            )}
            <p>{entry.text_body || `[${entry.kind}]`}</p>
          </div>
        ))}
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
            clientId={clientId}
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
  clientId, templates, onSent,
}: { clientId: string; templates: WhatsappTemplate[]; onSent: () => void }) {
  const [templateId, setTemplateId] = useState("");
  const [variables, setVariables] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const selected = templates.find((t) => t.id === templateId) ?? null;

  async function send() {
    setError(null);
    try {
      await api.post(`/whatsapp-conversations/${clientId}/messages/template`, {
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
