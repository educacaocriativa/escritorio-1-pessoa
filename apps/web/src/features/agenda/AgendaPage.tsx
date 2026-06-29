import type { AgendaEvent, CreateEventResult } from "@e1p/shared-types";
import { AlertTriangle, Clock } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const KINDS = [
  ["atendimento", "Atendimento"],
  ["reuniao", "Reunião"],
  ["audiencia", "Audiência"],
  ["prazo", "Prazo"],
  ["lembrete", "Lembrete"],
  ["bloqueio", "Bloqueio"],
] as const;

export default function AgendaPage() {
  const [events, setEvents] = useState<AgendaEvent[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<AgendaEvent[]>("/agenda/events");
      setEvents(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Novo evento", useCallback(() => setOpen(true), []));

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Agenda</p>
        <h1 className="text-2xl font-bold text-neutral-800">Agenda</h1>
      </div>

      <div className="rounded-2xl bg-white p-5 shadow-sm">
        {loading ? (
          <Empty text="Carregando..." />
        ) : events.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-neutral-400">
            <Clock size={28} />
            <p>Nenhum compromisso. Clique em "Novo" para criar.</p>
          </div>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {events.map((ev) => (
              <EventRow key={ev.id} event={ev} />
            ))}
          </ul>
        )}
      </div>

      <NewEventModal open={open} onClose={() => setOpen(false)} onCreated={load} />
    </div>
  );
}

const priorityDot: Record<AgendaEvent["priority"], string> = {
  normal: "bg-neutral-300",
  high: "bg-warning",
  critical: "bg-danger",
};

function EventRow({ event }: { event: AgendaEvent }) {
  const start = new Date(event.starts_at);
  const when = start.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <li className="flex items-center gap-3 py-3">
      <span className={`h-2 w-2 rounded-full ${priorityDot[event.priority]}`} />
      <span className="w-32 text-sm tabular-nums text-neutral-500">{when}</span>
      <span className="flex-1 font-medium text-neutral-800">{event.title}</span>
      <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
        {event.kind}
      </span>
      {event.priority === "critical" && <AlertTriangle size={16} className="text-danger" />}
    </li>
  );
}

function NewEventModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("atendimento");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setConflict(null);
    setSaving(true);
    try {
      const { data } = await api.post<CreateEventResult>("/agenda/events", {
        title,
        kind,
        starts_at: start,
        ends_at: end,
      });
      if (data.conflicts.length > 0) {
        setConflict(`⚠ Conflito com: ${data.conflicts.map((c) => c.title).join(", ")}`);
      }
      onCreated();
      setTitle("");
      setStart("");
      setEnd("");
      if (data.conflicts.length === 0) onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Novo evento" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Título" value={title} onChange={setTitle} placeholder="Atendimento cliente" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <Field label="Início" type="datetime-local" value={start} onChange={setStart} />
        <Field label="Fim" type="datetime-local" value={end} onChange={setEnd} />

        {conflict && <p className="rounded-lg bg-amber-50 p-2 text-sm text-amber-700">{conflict}</p>}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

        <button
          onClick={save}
          disabled={saving || !title || !start || !end}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Criar evento"}
        </button>
      </div>
    </Modal>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="py-8 text-center text-sm text-neutral-400">{text}</p>;
}
