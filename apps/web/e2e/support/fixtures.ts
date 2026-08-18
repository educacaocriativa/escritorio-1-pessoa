import type { AgendaEvent } from "@e1p/shared-types";
import { agendaEvent as base } from "../../src/test/fixtures/agenda";

/**
 * Payload de `AgendaEvent` para os specs de layout — na forma real de `packages/shared-types`.
 *
 * DERIVA da fixture de `src/`, e não a copia: `apps/web/tsconfig.json` é único e inclui
 * `["src", "e2e", "playwright.config.ts"]`, então os dois lados compartilham compilador, `strict`
 * e `paths` — não havia barreira nenhuma, e uma segunda lista dos 21 campos só devolveria o
 * problema que a extração veio resolver.
 *
 * O que muda aqui são os VALORES, e isso é a régua de 360px falando (§5.1): as fixtures de layout
 * são de **pior caso plausível** — título de casamento, contato vinculado —, porque dado curto
 * sempre cabe e medir com ele é medir uma tela que não existe.
 */
export const agendaEvent = (over: Partial<AgendaEvent> = {}): AgendaEvent =>
  base({
    title: "Prova do vestido",
    starts_at: "2026-08-20T13:00:00Z",
    ends_at: "2026-08-20T14:00:00Z",
    client_id: "c1",
    client_name: "Ju",
    created_at: "2026-08-15T10:00:00Z",
    ...over,
  });
