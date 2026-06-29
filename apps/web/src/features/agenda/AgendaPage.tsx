import type { AgendaEvent } from "@e1p/shared-types";
import { AlertTriangle, Clock } from "lucide-react";

/**
 * Agenda — visão do dia. Esqueleto da UI; o fetch real entra junto com o fluxo de login.
 * O backend (módulo agenda) já expõe /agenda/events com detecção de conflitos.
 */
export default function AgendaPage() {
  const events: AgendaEvent[] = []; // virá de GET /agenda/events?start&end

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Agenda</p>
        <h1 className="text-2xl font-bold text-neutral-800">Agenda do dia</h1>
      </div>

      <div className="rounded-2xl bg-white p-5 shadow-sm">
        {events.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-12 text-neutral-400">
            <Clock size={28} />
            <p>Nenhum compromisso carregado.</p>
            <p className="text-xs">
              O backend já cria, lista e detecta conflitos de eventos. A ligação com a tela entra
              com o login.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {events.map((ev) => (
              <EventRow key={ev.id} event={ev} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

const priorityDot: Record<AgendaEvent["priority"], string> = {
  normal: "bg-neutral-300",
  high: "bg-warning",
  critical: "bg-danger",
};

function EventRow({ event }: { event: AgendaEvent }) {
  const time = new Date(event.starts_at).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <li className="flex items-center gap-3 py-3">
      <span className={`h-2 w-2 rounded-full ${priorityDot[event.priority]}`} />
      <span className="w-16 text-sm tabular-nums text-neutral-500">{time}</span>
      <span className="flex-1 font-medium text-neutral-800">{event.title}</span>
      {event.priority === "critical" && <AlertTriangle size={16} className="text-danger" />}
    </li>
  );
}
