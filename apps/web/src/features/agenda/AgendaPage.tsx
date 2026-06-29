import type { AgendaEvent, CreateEventResult } from "@e1p/shared-types";
import { ChevronLeft, ChevronRight, Video } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

type View = "month" | "week" | "day";

const KINDS = [
  ["atendimento", "Atendimento"],
  ["reuniao", "Reunião"],
  ["audiencia", "Audiência"],
  ["prazo", "Prazo"],
  ["lembrete", "Lembrete"],
  ["bloqueio", "Bloqueio"],
] as const;

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

// ── helpers de data (sem lib) ──────────────────────────
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d: Date, n: number) => {
  const r = startOfDay(d);
  r.setDate(r.getDate() + n);
  return r;
};
const startOfWeek = (d: Date) => addDays(d, -d.getDay()); // semana começa no domingo
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function rangeFor(view: View, anchor: Date): { start: Date; end: Date; days: Date[] } {
  if (view === "day") {
    return { start: startOfDay(anchor), end: addDays(anchor, 1), days: [startOfDay(anchor)] };
  }
  if (view === "week") {
    const s = startOfWeek(anchor);
    const days = Array.from({ length: 7 }, (_, i) => addDays(s, i));
    return { start: s, end: addDays(s, 7), days };
  }
  // month: grade de 6 semanas a partir do domingo anterior ao dia 1
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const gridStart = startOfWeek(first);
  const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
  return { start: gridStart, end: addDays(gridStart, 42), days };
}

export default function AgendaPage() {
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(() => new Date());
  const [events, setEvents] = useState<AgendaEvent[]>([]);
  const [modalDate, setModalDate] = useState<Date | null>(null);
  const [open, setOpen] = useState(false);

  const { start, end, days } = useMemo(() => rangeFor(view, anchor), [view, anchor]);

  const load = useCallback(async () => {
    const { data } = await api.get<AgendaEvent[]>("/agenda/events", {
      params: { start: start.toISOString(), end: end.toISOString(), limit: 500 },
    });
    setEvents(data);
  }, [start, end]);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction(
    "Novo evento",
    useCallback(() => {
      setModalDate(null);
      setOpen(true);
    }, []),
  );

  const step = view === "month" ? "month" : view === "week" ? 7 : 1;
  function nav(dir: number) {
    if (step === "month") setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1));
    else setAnchor(addDays(anchor, dir * (step as number)));
  }

  const title =
    view === "day"
      ? anchor.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" })
      : view === "week"
        ? `${days[0].toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })} – ${days[6].toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })}`
        : anchor.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });

  function openOnDay(d: Date) {
    setModalDate(d);
    setOpen(true);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button onClick={() => nav(-1)} className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <ChevronLeft size={18} />
          </button>
          <button onClick={() => nav(1)} className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <ChevronRight size={18} />
          </button>
          <button
            onClick={() => setAnchor(new Date())}
            className="rounded-pill border border-neutral-200 px-3 py-1 text-sm text-neutral-600 hover:bg-neutral-50"
          >
            Hoje
          </button>
          <h1 className="ml-2 text-lg font-bold capitalize text-neutral-800">{title}</h1>
        </div>
        <div className="flex rounded-pill bg-neutral-100 p-1 text-sm">
          {(["month", "week", "day"] as View[]).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`rounded-pill px-3 py-1 font-medium transition ${
                view === v ? "bg-white text-primary-700 shadow-sm" : "text-neutral-500"
              }`}
            >
              {v === "month" ? "Mês" : v === "week" ? "Semana" : "Dia"}
            </button>
          ))}
        </div>
      </div>

      {view === "month" && (
        <MonthGrid days={days} anchor={anchor} events={events} onDayClick={openOnDay} />
      )}
      {view === "week" && <WeekView days={days} events={events} onDayClick={openOnDay} />}
      {view === "day" && <DayView day={anchor} events={events} />}

      <NewEventModal
        open={open}
        initialDate={modalDate}
        onClose={() => setOpen(false)}
        onCreated={load}
      />
    </div>
  );
}

// ── cor por prioridade/tipo ────────────────────────────
function eventColor(e: AgendaEvent): string {
  if (e.priority === "critical") return "bg-red-100 text-red-700";
  if (e.kind === "prazo") return "bg-amber-100 text-amber-700";
  if (e.kind === "cobranca_receber" || e.kind === "cobranca_pagar") return "bg-blue-100 text-blue-700";
  return "bg-primary-100 text-primary-700";
}
const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const eventsOfDay = (events: AgendaEvent[], d: Date) =>
  events
    .filter((e) => sameDay(new Date(e.starts_at), d))
    .sort((a, b) => +new Date(a.starts_at) - +new Date(b.starts_at));

function MonthGrid({
  days,
  anchor,
  events,
  onDayClick,
}: {
  days: Date[];
  anchor: Date;
  events: AgendaEvent[];
  onDayClick: (d: Date) => void;
}) {
  const today = new Date();
  return (
    <div className="overflow-hidden rounded-2xl border border-neutral-100 bg-white">
      <div className="grid grid-cols-7 border-b border-neutral-100 text-center text-xs font-medium text-neutral-400">
        {WEEKDAYS.map((w) => (
          <div key={w} className="py-2">
            {w}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const inMonth = d.getMonth() === anchor.getMonth();
          const dayEvents = eventsOfDay(events, d);
          return (
            <button
              key={d.toISOString()}
              onClick={() => onDayClick(d)}
              className={`min-h-[92px] border-b border-r border-neutral-50 p-1.5 text-left align-top hover:bg-neutral-50 ${
                inMonth ? "" : "bg-neutral-50/50 text-neutral-300"
              }`}
            >
              <span
                className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                  sameDay(d, today) ? "bg-primary-500 font-bold text-white" : "text-neutral-500"
                }`}
              >
                {d.getDate()}
              </span>
              <div className="mt-1 space-y-0.5">
                {dayEvents.slice(0, 3).map((e) => (
                  <div key={e.id} className={`truncate rounded px-1 py-0.5 text-[11px] ${eventColor(e)}`}>
                    {!e.all_day && <span className="tabular-nums">{hhmm(e.starts_at)} </span>}
                    {e.title}
                  </div>
                ))}
                {dayEvents.length > 3 && (
                  <div className="text-[10px] text-neutral-400">+{dayEvents.length - 3} mais</div>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function WeekView({
  days,
  events,
  onDayClick,
}: {
  days: Date[];
  events: AgendaEvent[];
  onDayClick: (d: Date) => void;
}) {
  const today = new Date();
  return (
    <div className="grid grid-cols-7 gap-2">
      {days.map((d) => {
        const dayEvents = eventsOfDay(events, d);
        return (
          <div key={d.toISOString()} className="rounded-2xl border border-neutral-100 bg-white p-2">
            <button
              onClick={() => onDayClick(d)}
              className="mb-2 w-full text-center text-xs font-medium text-neutral-500 hover:text-primary-600"
            >
              <div>{WEEKDAYS[d.getDay()]}</div>
              <div
                className={`mx-auto mt-0.5 flex h-6 w-6 items-center justify-center rounded-full ${
                  sameDay(d, today) ? "bg-primary-500 font-bold text-white" : ""
                }`}
              >
                {d.getDate()}
              </div>
            </button>
            <div className="space-y-1">
              {dayEvents.map((e) => (
                <div key={e.id} className={`rounded px-1.5 py-1 text-[11px] ${eventColor(e)}`}>
                  {!e.all_day && <div className="tabular-nums opacity-70">{hhmm(e.starts_at)}</div>}
                  <div className="truncate font-medium">{e.title}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DayView({ day, events }: { day: Date; events: AgendaEvent[] }) {
  const dayEvents = eventsOfDay(events, day);
  return (
    <div className="rounded-2xl border border-neutral-100 bg-white p-4">
      {dayEvents.length === 0 ? (
        <p className="py-12 text-center text-sm text-neutral-400">Nenhum compromisso neste dia.</p>
      ) : (
        <ul className="divide-y divide-neutral-100">
          {dayEvents.map((e) => (
            <li key={e.id} className="flex items-center gap-3 py-3">
              <span className="w-28 shrink-0 text-sm tabular-nums text-neutral-500">
                {e.all_day ? "Dia inteiro" : `${hhmm(e.starts_at)}–${hhmm(e.ends_at)}`}
              </span>
              <div className="min-w-0 flex-1">
                <span className="font-medium text-neutral-800">{e.title}</span>
                {e.location && <span className="ml-2 text-xs text-neutral-400">· {e.location}</span>}
              </div>
              {e.meeting_url && (
                <a
                  href={e.meeting_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs text-accent-600 hover:underline"
                >
                  <Video size={12} /> Entrar
                </a>
              )}
              <span className={`rounded-pill px-2 py-0.5 text-xs ${eventColor(e)}`}>{e.kind}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NewEventModal({
  open,
  initialDate,
  onClose,
  onCreated,
}: {
  open: boolean;
  initialDate: Date | null;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("atendimento");
  const [allDay, setAllDay] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [location, setLocation] = useState("");
  const [guests, setGuests] = useState("");
  const [meetingUrl, setMeetingUrl] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // pré-preenche a data ao abrir num dia do calendário
  useEffect(() => {
    if (open && initialDate) {
      const d = ymd(initialDate);
      setStartDate(d);
      setEndDate(d);
      setStart(`${d}T09:00`);
      setEnd(`${d}T10:00`);
    }
  }, [open, initialDate]);

  async function save() {
    setError(null);
    setConflict(null);
    setSaving(true);
    try {
      const starts_at = allDay ? `${startDate}T00:00:00` : start;
      const ends_at = allDay ? `${endDate || startDate}T23:59:00` : end;
      const { data } = await api.post<CreateEventResult>("/agenda/events", {
        title,
        kind,
        all_day: allDay,
        starts_at,
        ends_at,
        location,
        meeting_url: meetingUrl || null,
        guests: guests ? guests.split(",").map((g) => g.trim()) : [],
        description,
      });
      if (data.conflicts.length > 0) {
        setConflict(`⚠ Conflito de horário com: ${data.conflicts.map((c) => c.title).join(", ")}`);
      }
      onCreated();
      if (data.conflicts.length === 0) onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const valid = title && (allDay ? startDate : start && end);

  return (
    <Modal title="Novo evento" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Título" value={title} onChange={setTitle} placeholder="Atendimento cliente" />
        <div className="flex items-end gap-3">
          <label className="flex-1">
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
          <label className="flex items-center gap-2 pb-2 text-sm text-neutral-600">
            <input type="checkbox" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} />
            Dia inteiro
          </label>
        </div>

        {allDay ? (
          <div className="flex gap-2">
            <Field label="Data início" type="date" value={startDate} onChange={setStartDate} />
            <Field label="Data fim" type="date" value={endDate} onChange={setEndDate} />
          </div>
        ) : (
          <div className="flex gap-2">
            <Field label="Início" type="datetime-local" value={start} onChange={setStart} />
            <Field label="Fim" type="datetime-local" value={end} onChange={setEnd} />
          </div>
        )}

        <Field label="Local" value={location} onChange={setLocation} placeholder="Escritório ou endereço" />
        <div>
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Reunião (Google Meet / Zoom)
          </span>
          <div className="flex gap-2">
            <input
              value={meetingUrl}
              onChange={(e) => setMeetingUrl(e.target.value)}
              placeholder="Cole o link da reunião"
              className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
            />
            <a
              href="https://meet.google.com/new"
              target="_blank"
              rel="noreferrer"
              className="flex shrink-0 items-center gap-1 rounded-lg bg-primary-50 px-3 text-sm font-medium text-primary-700 hover:bg-primary-100"
            >
              <Video size={15} /> Meet
            </a>
          </div>
        </div>
        <Field label="Convidados (e-mails, separados por vírgula)" value={guests} onChange={setGuests} />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Descrição</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          />
        </label>

        {conflict && <p className="rounded-lg bg-amber-50 p-2 text-sm text-amber-700">{conflict}</p>}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

        <button
          onClick={save}
          disabled={saving || !valid}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Criar evento"}
        </button>
      </div>
    </Modal>
  );
}
