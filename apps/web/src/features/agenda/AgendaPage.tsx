import type { AgendaEvent, Charge, CreateEventResult, Notification, Payable } from "@e1p/shared-types";
import { ChevronLeft, ChevronRight, MapPin, Sparkles, Users, Video } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import Attachments from "../../components/Attachments";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

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
// só a primeira letra maiúscula (ex.: "junho de 2026" -> "Junho de 2026")
const sentenceCase = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

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
  const [selected, setSelected] = useState<AgendaEvent | null>(null);

  const { start, end, days } = useMemo(() => rangeFor(view, anchor), [view, anchor]);

  const load = useCallback(async () => {
    // Fronteiras em UTC-date (meia-noite UTC da data do grid), não o local→UTC: assim os
    // eventos de dia inteiro (gravados à meia-noite UTC) não caem fora do range nas bordas.
    const { data } = await api.get<AgendaEvent[]>("/agenda/events", {
      params: { start: `${ymd(start)}T00:00:00.000Z`, end: `${ymd(end)}T00:00:00.000Z`, limit: 500 },
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

  const title = sentenceCase(
    view === "day"
      ? anchor.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" })
      : view === "week"
        ? `${days[0].toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })} – ${days[6].toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })}`
        : anchor.toLocaleDateString("pt-BR", { month: "long", year: "numeric" }),
  );

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
          <h1 className="ml-2 text-lg font-bold text-neutral-800">{title}</h1>
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
        <MonthGrid
          days={days}
          anchor={anchor}
          events={events}
          onDayClick={openOnDay}
          onEventClick={setSelected}
        />
      )}
      {view === "week" && (
        <WeekView days={days} events={events} onDayClick={openOnDay} onEventClick={setSelected} />
      )}
      {view === "day" && <DayView day={anchor} events={events} onEventClick={setSelected} />}

      <NewEventModal
        open={open}
        initialDate={modalDate}
        onClose={() => setOpen(false)}
        onCreated={load}
      />

      {selected && <EventDetailModal event={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

// ── cor por tipo/situação ──────────────────────────────
// a receber = verde · a pagar = laranja · atrasada (não paga e vencida) = vermelho
function eventColor(e: AgendaEvent): string {
  // Atrasado = não pago/cancelado e com data ANTERIOR a hoje. Compara por data de calendário
  // (eventYmd trata o all-day em UTC sem "voltar" um dia no fuso).
  const overdue =
    e.status !== "done" && e.status !== "cancelled" && eventYmd(e) < ymd(new Date());
  if (e.kind === "cobranca_receber") return overdue ? "bg-red-100 text-red-700" : "bg-accent-100 text-accent-700";
  if (e.kind === "cobranca_pagar") return overdue ? "bg-red-100 text-red-700" : "bg-orange-100 text-orange-700";
  if (e.priority === "critical") return "bg-red-100 text-red-700";
  if (e.kind === "prazo") return "bg-amber-100 text-amber-700";
  return "bg-primary-100 text-primary-700";
}
const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
// Eventos de dia inteiro (cobranças, contas a pagar, prazos) são gravados à meia-noite UTC:
// casamos pela DATA do calendário (sem fuso) para não "voltar" um dia em fuso negativo.
// Eventos com horário usam a data local normalmente.
const eventYmd = (e: AgendaEvent) =>
  e.all_day ? e.starts_at.slice(0, 10) : ymd(new Date(e.starts_at));
const eventsOfDay = (events: AgendaEvent[], d: Date) =>
  events
    .filter((e) => eventYmd(e) === ymd(d))
    .sort((a, b) => +new Date(a.starts_at) - +new Date(b.starts_at));

function MonthGrid({
  days,
  anchor,
  events,
  onDayClick,
  onEventClick,
}: {
  days: Date[];
  anchor: Date;
  events: AgendaEvent[];
  onDayClick: (d: Date) => void;
  onEventClick: (e: AgendaEvent) => void;
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
                  <div
                    key={e.id}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onEventClick(e);
                    }}
                    className={`cursor-pointer truncate rounded px-1 py-0.5 text-[11px] hover:opacity-80 ${eventColor(e)}`}
                  >
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
  onEventClick,
}: {
  days: Date[];
  events: AgendaEvent[];
  onDayClick: (d: Date) => void;
  onEventClick: (e: AgendaEvent) => void;
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
                <div
                  key={e.id}
                  onClick={() => onEventClick(e)}
                  className={`cursor-pointer rounded px-1.5 py-1 text-[11px] hover:opacity-80 ${eventColor(e)}`}
                >
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

function DayView({
  day,
  events,
  onEventClick,
}: {
  day: Date;
  events: AgendaEvent[];
  onEventClick: (e: AgendaEvent) => void;
}) {
  const dayEvents = eventsOfDay(events, day);
  return (
    <div className="rounded-2xl border border-neutral-100 bg-white p-4">
      {dayEvents.length === 0 ? (
        <p className="py-12 text-center text-sm text-neutral-400">Nenhum compromisso neste dia.</p>
      ) : (
        <ul className="divide-y divide-neutral-100">
          {dayEvents.map((e) => (
            <li
              key={e.id}
              onClick={() => onEventClick(e)}
              className="flex cursor-pointer items-center gap-3 py-3 hover:bg-neutral-50"
            >
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

function EventDetailModal({ event, onClose }: { event: AgendaEvent; onClose: () => void }) {
  const isReceber = event.kind === "cobranca_receber" && !!event.external_ref;
  const isPagar = event.kind === "cobranca_pagar" && !!event.external_ref;
  const [charge, setCharge] = useState<Charge | null>(null);
  const [payable, setPayable] = useState<Payable | null>(null);
  const [messages, setMessages] = useState<Notification[]>([]);
  const [newMsg, setNewMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const loadMessages = useCallback(() => {
    if (!event.external_ref) return;
    api
      .get<Notification[]>(`/receivables/charges/${event.external_ref}/messages`)
      .then(({ data }) => setMessages(data));
  }, [event.external_ref]);

  useEffect(() => {
    if (isReceber) {
      api.get<Charge>(`/receivables/charges/${event.external_ref}`).then(({ data }) => setCharge(data));
      loadMessages();
    } else if (isPagar) {
      api.get<Payable>(`/payables/bills/${event.external_ref}`).then(({ data }) => setPayable(data));
    }
  }, [event, isReceber, isPagar, loadMessages]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      loadMessages();
    } finally {
      setBusy(false);
    }
  }

  const when = event.all_day
    ? new Date(event.starts_at).toLocaleDateString("pt-BR")
    : `${new Date(event.starts_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })} – ${hhmm(event.ends_at)}`;

  return (
    <Modal title={event.title} open onClose={onClose}>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2 text-neutral-600">
          <span className="tabular-nums">{when}</span>
          <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs">{event.kind}</span>
        </div>
        {event.location && (
          <p className="flex items-center gap-1 text-neutral-600">
            <MapPin size={14} /> {event.location}
          </p>
        )}
        {event.meeting_url && (
          <a href={event.meeting_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-accent-600 hover:underline">
            <Video size={14} /> Entrar na reunião
          </a>
        )}
        {event.guests.length > 0 && (
          <p className="flex items-center gap-1 text-neutral-500">
            <Users size={14} /> {event.guests.join(", ")}
          </p>
        )}
        {event.amount_cents != null && (
          <p className="text-base font-bold text-neutral-800">{brl(event.amount_cents)}</p>
        )}
        {event.description && <p className="text-neutral-600">{event.description}</p>}

        {isPagar && payable && (
          <div className="rounded-lg bg-neutral-50 p-3">
            <p className="font-medium text-neutral-800">{payable.description || "Conta a pagar"}</p>
            <p className="text-xs text-neutral-500">
              {payable.supplier && `${payable.supplier} · `}
              {payable.category} · vence {new Date(payable.due_date + "T00:00").toLocaleDateString("pt-BR")}
            </p>
            <p className="mt-1 text-xs">
              Status: <strong>{payable.status === "paid" ? "Pago" : payable.is_overdue ? "Atrasado" : "A pagar"}</strong>
            </p>
            {payable.payment_code && (
              <p className="mt-1 break-all text-[11px] text-neutral-500">
                Código: {payable.payment_code}
              </p>
            )}
          </div>
        )}

        {(isPagar || isReceber) && event.external_ref && (
          <div className="border-t border-neutral-100 pt-3">
            <h3 className="mb-2 text-xs font-semibold uppercase text-neutral-400">Anexos</h3>
            <Attachments
              ownerType={isPagar ? "payable" : "charge"}
              ownerId={event.external_ref}
              slots={[{ key: "boleto", label: "Boleto" }, { key: "contrato", label: "Contrato" }]}
            />
          </div>
        )}

        {isReceber && (
          <div className="space-y-3 border-t border-neutral-100 pt-3">
            {charge && (
              <div className="rounded-lg bg-neutral-50 p-3">
                <p className="font-medium text-neutral-800">{charge.client_name ?? "Cobrança"}</p>
                <p className="text-xs text-neutral-500">
                  {charge.description} · vence{" "}
                  {new Date(charge.due_date + "T00:00").toLocaleDateString("pt-BR")} ·{" "}
                  {charge.status === "paid" ? "Recebido" : charge.is_overdue ? "Vencido" : "A vencer"}
                </p>
              </div>
            )}

            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase text-neutral-400">
                Histórico de mensagens
              </h3>
              {messages.length === 0 ? (
                <p className="text-xs text-neutral-400">Nenhuma mensagem enviada ainda.</p>
              ) : (
                <ul className="max-h-40 space-y-2 overflow-y-auto">
                  {messages.map((m) => (
                    <li key={m.id} className="rounded-lg bg-neutral-50 p-2 text-xs text-neutral-700">
                      <p>{m.message}</p>
                      <p className="mt-1 text-[10px] text-neutral-400">
                        {new Date(m.created_at).toLocaleString("pt-BR")} · {m.status}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <button
              onClick={() => act(() => api.post(`/receivables/charges/${event.external_ref}/collect`))}
              disabled={busy}
              className="flex w-full items-center justify-center gap-1.5 rounded-pill bg-primary-500 py-2 text-sm font-semibold text-white hover:bg-primary-600 disabled:opacity-60"
            >
              <Sparkles size={14} /> Cobrar com IA
            </button>

            <div>
              <textarea
                value={newMsg}
                onChange={(e) => setNewMsg(e.target.value)}
                rows={2}
                placeholder="Escrever mensagem manual..."
                className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
              />
              <button
                onClick={() => act(async () => {
                  await api.post(`/receivables/charges/${event.external_ref}/message`, { text: newMsg });
                  setNewMsg("");
                })}
                disabled={busy || !newMsg.trim()}
                className="mt-1 w-full rounded-pill bg-accent-400 py-2 text-sm font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
              >
                Enviar mensagem
              </button>
            </div>
          </div>
        )}
      </div>
    </Modal>
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
