import type { AgendaEvent, Charge, Notification, Payable } from "@e1p/shared-types";
import { ChevronLeft, ChevronRight, MapPin, Sparkles, Users, Video } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import Attachments from "../../components/Attachments";
import Modal from "../../components/Modal";
import { api } from "../../lib/api";
import GanchoDaVima from "../dna/GanchoDaVima";
import { usePrimaryAction } from "../../store/pageActions";
import { formatDateTime, formatDay, formatTime, localYmd } from "../../lib/datetime";
import { sentenceCase } from "../../lib/texto";
import {
  WEEKDAYS,
  addDays,
  eventYmd,
  eventsOfDay,
  gradeDoMes,
  paramsDaGrade,
  hojeDoTenant,
  sameDay,
  startOfDay,
  startOfWeek,
} from "./grade";
import { useFuso } from "../../store/auth";
import NewEventModal from "./NewEventModal";

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

type View = "month" | "week" | "day";

function rangeFor(view: View, anchor: Date): { start: Date; end: Date; days: Date[] } {
  if (view === "day") {
    return { start: startOfDay(anchor), end: addDays(anchor, 1), days: [startOfDay(anchor)] };
  }
  if (view === "week") {
    const s = startOfWeek(anchor);
    const days = Array.from({ length: 7 }, (_, i) => addDays(s, i));
    return { start: s, end: addDays(s, 7), days };
  }
  return gradeDoMes(anchor);
}

export default function AgendaPage() {
  const fuso = useFuso();
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(() => hojeDoTenant(fuso));
  const [events, setEvents] = useState<AgendaEvent[]>([]);
  const [modalDate, setModalDate] = useState<Date | null>(null);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<AgendaEvent | null>(null);

  const { start, end, days } = useMemo(() => rangeFor(view, anchor), [view, anchor]);

  const load = useCallback(async () => {
    const { data } = await api.get<AgendaEvent[]>("/agenda/events", {
      params: paramsDaGrade(start, end),
    });
    // `Array.isArray`, e aqui não havia operador nenhum: a grade chama `eventsOfDay(events, d)`
    // para CADA dia visível, e `eventsOfDay` abre com `events.filter` (`grade.ts`). Payload fora de
    // forma estoura no primeiro dia do mês — antes de qualquer célula existir, com a tela em branco.
    setEvents(Array.isArray(data) ? data : []);
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
      <GanchoDaVima gancho="agenda.evento.criado" />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button onClick={() => nav(-1)} className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <ChevronLeft size={18} />
          </button>
          <button onClick={() => nav(1)} className="rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
            <ChevronRight size={18} />
          </button>
          <button
            onClick={() => setAnchor(hojeDoTenant(fuso))}
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
function eventColor(e: AgendaEvent, hoje: string): string {
  // Atrasado = não pago/cancelado e com data ANTERIOR a hoje. Compara por data de calendário
  // (eventYmd trata o all-day em UTC sem "voltar" um dia no fuso).
  const overdue =
    e.status !== "done" && e.status !== "cancelled" && eventYmd(e) < hoje;
  if (e.kind === "cobranca_receber") return overdue ? "bg-red-100 text-red-700" : "bg-accent-100 text-accent-700";
  if (e.kind === "cobranca_pagar") return overdue ? "bg-red-100 text-red-700" : "bg-orange-100 text-orange-700";
  if (e.priority === "critical") return "bg-red-100 text-red-700";
  if (e.kind === "prazo") return "bg-amber-100 text-amber-700";
  return "bg-primary-100 text-primary-700";
}
const hhmm = (iso: string, tz: string) => formatTime(iso, tz);
// O atalho (nome no lugar do título) é só para os kinds FINANCEIROS. O título deles é
// AUTO-GERADO pelo backend ("A receber: Fulano"), então mostrar o nome puro é um encurtamento
// inofensivo — mesma informação, mais curta.
// Desde que `client_id`/`client_name` passaram a ser resolvidos para QUALQUER kind com contato
// vinculado (Onda 2, Task 3 — join direto em `_events_out`), uma reunião ou atendimento ligado a
// um contato também ganhou `client_name`. Mas o título desses eventos foi DIGITADO pelo dono
// ("Alinhamento do casamento 12/12") e carrega informação que o nome do contato não tem — no
// calendário, que é o lugar de bater o olho e saber do que se trata, trocar por nome perderia
// isso. Por isso a restrição por kind abaixo: NÃO simplificar de volta para `client_name || title`.
const FINANCIAL_KINDS = new Set(["cobranca_receber", "cobranca_pagar"]);
const chipLabel = (e: AgendaEvent) =>
  FINANCIAL_KINDS.has(e.kind) && e.client_name ? e.client_name : e.title;

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
  const fuso = useFuso();
  const today = hojeDoTenant(fuso);
  const hoje = localYmd(today);
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
            // ⚠️ **O chip é IRMÃO da célula, nunca filho (#183).** Ele morava DENTRO do `<button>` do
            // dia, e os dois abrem modais DIFERENTES (chip → detalhe · célula → "Novo evento").
            // Com dois alvos clicáveis aninhados o navegador emite o `click` no ANCESTRAL COMUM de
            // `mousedown` e `mouseup`: medido em 21/08/2026, chip de 31,3×20,5 numa célula de
            // 44,3×92, **12px de deslocamento** já bastam para o toque no chip virar "Novo evento"
            // — 8/10/11px ainda caem no chip, 12/14/16/20px caem na célula. O limiar é a meia-altura
            // do chip (10,25px), e por isso ele é 12 aqui e 10 nas listas do #160.
            //
            // ⚠️ O `data-testid` + `stopPropagation` do #149 CONTORNARAM o sintoma sem desfazer o
            // aninhamento: o alvo nunca foi ambíguo (`count() === 1`, medido), ambíguo era o PONTO.
            // `stopPropagation` só age quando o `click` nasce no chip — escorregando, ele nasce na
            // célula, e não há o que parar.
            //
            // ⚠️ **A correção é o PARENTESCO, não a tag.** O ancestral comum passa a ser esta `<div>`
            // sem handler, então o escorregão não faz NADA. A célula vira uma camada `absolute
            // inset-0` ATRÁS do conteúdo, e o conteúdo é `pointer-events-none` com os chips
            // reabilitados — assim a geometria da grade (42 células de 44,3×92 em 360px) fica
            // idêntica à de antes, medido antes e depois. Trocar o `<button>` de fora por
            // `<div role="button">` NÃO resolveria: o `click` continuaria caindo nele.
            //
            // ⚠️ E o NOME ACESSÍVEL deixa de engolir o compromisso. Aninhado, o snapshot do CI do
            // #149 anunciava dia e evento como um controle só: `button "18 10:00 Alinhamento…"`.
            // Medido em `e2e/agenda-chip-aninhamento-360.spec.ts`.
            <div
              key={d.toISOString()}
              className={`relative min-h-[92px] border-b border-r border-neutral-50 ${
                inMonth ? "" : "bg-neutral-50/50 text-neutral-300"
              }`}
            >
              <button
                data-testid={`celula-dia-${localYmd(d)}`}
                aria-label={`Novo evento em ${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "long" })}`}
                onClick={() => onDayClick(d)}
                className="absolute inset-0 h-full w-full hover:bg-neutral-50"
              />
              <div className="pointer-events-none relative p-1.5 text-left">
                <span
                  className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs ${
                    sameDay(d, today) ? "bg-primary-500 font-bold text-white" : "text-neutral-500"
                  }`}
                >
                  {d.getDate()}
                </span>
                <div className="mt-1 space-y-0.5">
                  {dayEvents.slice(0, 3).map((e) => (
                    <button
                      key={e.id}
                      data-testid={`chip-evento-${e.id}`}
                      onClick={() => onEventClick(e)}
                      className={`pointer-events-auto block w-full truncate rounded px-1 py-0.5 text-left text-[11px] hover:opacity-80 ${eventColor(e, hoje)}`}
                    >
                      {!e.all_day && <span className="tabular-nums">{hhmm(e.starts_at, fuso)} </span>}
                      {chipLabel(e)}
                    </button>
                  ))}
                  {dayEvents.length > 3 && (
                    <div className="text-[10px] text-neutral-400">+{dayEvents.length - 3} mais</div>
                  )}
                </div>
              </div>
            </div>
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
  const fuso = useFuso();
  const today = hojeDoTenant(fuso);
  const hoje = localYmd(today);
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
                  className={`cursor-pointer rounded px-1.5 py-1 text-[11px] hover:opacity-80 ${eventColor(e, hoje)}`}
                >
                  {!e.all_day && <div className="tabular-nums opacity-70">{hhmm(e.starts_at, fuso)}</div>}
                  <div className="truncate font-medium">{chipLabel(e)}</div>
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
  const fuso = useFuso();
  const hoje = localYmd(hojeDoTenant(fuso));
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
                {e.all_day ? "Dia inteiro" : `${hhmm(e.starts_at, fuso)}–${hhmm(e.ends_at, fuso)}`}
              </span>
              <div className="min-w-0 flex-1">
                <span className="font-medium text-neutral-800">{chipLabel(e)}</span>
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
              <span className={`rounded-pill px-2 py-0.5 text-xs ${eventColor(e, hoje)}`}>{e.kind}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EventDetailModal({ event, onClose }: { event: AgendaEvent; onClose: () => void }) {
  const fuso = useFuso();
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

  // all_day é DATA DE CALENDÁRIO (gravada à meia-noite UTC): formata pela string, sem `Date`.
  // Com horário é INSTANTE: converte para o fuso do tenant.
  const when = event.all_day
    ? formatDay(event.starts_at)
    : `${formatDateTime(event.starts_at, fuso)} – ${hhmm(event.ends_at, fuso)}`;

  return (
    // `testId` na CAIXA (#123): o título aqui é DIGITADO pelo dono, a mesma exposição do #119.
    <Modal title={event.title} open onClose={onClose} testId="modal-evento">
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
              {payable.category} · vence {formatDay(payable.due_date)}
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
                  {formatDay(charge.due_date)} ·{" "}
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
                        {formatDateTime(m.created_at, fuso)} · {m.status}
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
