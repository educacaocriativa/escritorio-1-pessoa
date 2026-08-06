/**
 * Data e hora na tela — SEMPRE no fuso do tenant, nunca no do navegador.
 *
 * Antes deste módulo, cada tela chamava `toLocaleDateString("pt-BR")` do seu jeito. Isso formata
 * no fuso de QUEM ABRE a página: certo por acidente num PC brasileiro, errado num notebook em
 * viagem e errado num servidor/headless em UTC — que é exatamente onde os horários apareciam
 * "em Greenwich". Aqui o fuso é sempre explícito.
 *
 * ## As duas espécies de data, que NÃO se misturam
 *
 * - **Instante** (`created_at`, `starts_at`, `paid_at`): um ponto no tempo, serializado em UTC.
 *   Converter para o fuso do tenant é obrigatório. Use `formatDateTime` / `formatTime` /
 *   `formatDate`.
 * - **Data de calendário** (`due_date`, `competence_date`, `opening_date`): `"2026-08-05"`, sem
 *   hora. NÃO tem fuso. `new Date("2026-08-05")` a interpreta como meia-noite UTC e, em UTC−3,
 *   `toLocaleDateString` devolve **04/08** — o off-by-one clássico do `CLAUDE.md` §6.0. Use
 *   `formatDay`, que trabalha na string e nunca constrói um `Date`.
 *
 * Escolher a função errada é o bug; por isso os nomes são diferentes e nenhuma delas aceita as
 * duas espécies.
 */

/** Fallback quando a sessão ainda não trouxe o fuso (sessão antiga em localStorage). */
export const FUSO_PADRAO = "America/Sao_Paulo";

/**
 * Um `timeZone` inválido faz `Intl.DateTimeFormat` **lançar** — e uma tela inteira em branco por
 * causa de um fuso corrompido seria um preço absurdo. Valida uma vez e cai no padrão.
 */
export function fusoValido(tz: string | null | undefined): string {
  if (!tz) return FUSO_PADRAO;
  try {
    new Intl.DateTimeFormat("pt-BR", { timeZone: tz });
    return tz;
  } catch {
    return FUSO_PADRAO;
  }
}

function fmt(iso: string, tz: string, opts: Intl.DateTimeFormatOptions): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("pt-BR", { ...opts, timeZone: fusoValido(tz) });
}

/**
 * Instante → `05/08/2026 22:30`.
 *
 * Composto a partir das duas metades em vez de `dateStyle`+`timeStyle`, que em pt-BR intercala
 * uma vírgula (`05/08/2026, 22:30`). Sem a vírgula, a mesma data sai idêntica aqui e no backend
 * (`core/tz.format_datetime_br`) — e o usuário nunca vê dois formatos para a mesma coisa.
 */
export function formatDateTime(iso: string | null | undefined, tz: string): string {
  if (!iso) return "";
  const dia = formatDate(iso, tz);
  return dia ? `${dia} ${formatTime(iso, tz)}` : "";
}

/** Instante → `05/08/2026`. */
export function formatDate(iso: string | null | undefined, tz: string): string {
  return iso ? fmt(iso, tz, { day: "2-digit", month: "2-digit", year: "numeric" }) : "";
}

/**
 * Instante → `05/08`. Sem o ano, para caber no card do Kanban.
 *
 * Existe para que o card não precise chamar `toLocaleDateString` na mão: `lib/datetime.ts` é a
 * única porta de formatação, e a compactação é uma escolha de exibição, não um motivo para
 * sair por fora.
 */
export function formatDateShort(iso: string | null | undefined, tz: string): string {
  return iso ? fmt(iso, tz, { day: "2-digit", month: "2-digit" }) : "";
}

/** Instante → `22:30`. */
export function formatTime(iso: string | null | undefined, tz: string): string {
  return iso ? fmt(iso, tz, { hour: "2-digit", minute: "2-digit" }) : "";
}

/** Instante → `terça-feira, 05 de agosto`. */
export function formatWeekday(iso: string | null | undefined, tz: string): string {
  return iso ? fmt(iso, tz, { weekday: "long", day: "2-digit", month: "long" }) : "";
}

/**
 * Data de calendário (`"2026-08-05"` ou o prefixo de um ISO) → `05/08/2026`.
 *
 * Puramente textual **de propósito**: não existe `Date` aqui, então não existe fuso para errar.
 */
export function formatDay(ymd: string | null | undefined): string {
  if (!ymd) return "";
  const [y, m, d] = ymd.slice(0, 10).split("-");
  return y && m && d ? `${d}/${m}/${y}` : "";
}

/**
 * "Hoje" no fuso do tenant, como `YYYY-MM-DD` — o que se manda para a API.
 *
 * Substitui `new Date().toISOString().slice(0, 10)`, que devolve o dia em **UTC**: das 21h à
 * meia-noite em UTC−3 o app pedia ao servidor o resumo do dia SEGUINTE.
 *
 * `en-CA` porque é o locale cujo formato numérico curto já é `YYYY-MM-DD` — evita remontar a
 * string a partir das partes.
 */
export function today(tz: string, now: Date = new Date()): string {
  return now.toLocaleDateString("en-CA", { timeZone: fusoValido(tz) });
}
