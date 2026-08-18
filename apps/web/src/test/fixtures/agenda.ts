import type { AgendaEvent } from "@e1p/shared-types";

/**
 * Um `AgendaEvent` completo, para os testes que precisam de um sem se importar com os 21 campos.
 *
 * Existe porque o literal já vivia copiado em vários specs: o 22º campo do tipo obrigaria uma
 * edição por cópia, e as cópias dos testes de e2e nem eram TIPADAS — o TypeScript não avisaria.
 * Tipado como `AgendaEvent` de propósito: é o que faz o compilador cobrar o campo novo aqui, uma
 * vez, em vez de deixar cada spec descobrir sozinho em runtime.
 */
export const agendaEvent = (over: Partial<AgendaEvent> = {}): AgendaEvent =>
  ({
    id: "ev-1",
    tenant_id: "t1",
    title: "Atendimento",
    description: "",
    kind: "atendimento",
    status: "scheduled",
    priority: "normal",
    source: "manual",
    starts_at: "2026-10-10T12:00:00Z",
    ends_at: "2026-10-10T13:00:00Z",
    all_day: false,
    location: "",
    meeting_url: null,
    guests: [],
    amount_cents: null,
    external_ref: null,
    google_event_id: null,
    client_id: null,
    client_name: null,
    created_by_ai: false,
    created_at: "2026-10-01T10:00:00Z",
    ...over,
  }) as AgendaEvent;
