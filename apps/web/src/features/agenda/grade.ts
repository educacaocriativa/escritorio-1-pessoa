import type { AgendaEvent } from "@e1p/shared-types";
import { formatTime, fusoValido, localYmd, today } from "../../lib/datetime";

/**
 * A aritmética de calendário da Agenda — em sua maior parte POSIÇÕES numa grade, não instantes.
 *
 * Vive fora do `AgendaPage.tsx` porque o seletor de horário da ficha 360° (`EscolherHorario`)
 * precisa exatamente da mesma matemática. Duplicar `startOfWeek`/`addDays` em dois lugares é
 * como um dos dois calendários acaba começando a semana num dia diferente do outro.
 *
 * ⚠️ **`instanteNoFuso` e `offsetEmMinutos` são a exceção, e estão aqui provisoriamente.** Eles
 * produzem e manipulam INSTANTE, que pela contabilidade do repo é matéria de `lib/datetime.ts`.
 * Ficaram juntos da grade porque nascem dela (a hora de parede vem de `faixasLivres`), mas quando
 * a terceira espécie — "posição de grade" — for aberta naquele módulo, estes dois vão junto:
 * senão `grade.ts` vira o segundo módulo de fuso do frontend e a porta única deixa de ser única
 * também nesse eixo. Ver a dívida registrada no CLAUDE.md.
 */

// ── posições na grade ──────────────────────────────────
export const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const addDays = (d: Date, n: number) => {
  const r = startOfDay(d);
  r.setDate(r.getDate() + n);
  return r;
};
export const startOfWeek = (d: Date) => addDays(d, -d.getDay()); // semana começa no domingo
export const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/**
 * "Hoje" no fuso do TENANT, como `Date` local — a âncora da grade do calendário.
 *
 * A grade inteira (`startOfDay`, `addDays`, `startOfWeek`, `localYmd`) trabalha em `Date` local,
 * e isso é coerente: são posições numa grade, não instantes. O que NÃO podia continuar local era
 * o ponto de partida — `new Date()` num navegador em UTC começava a grade no dia errado.
 * Montamos o dia certo pelas PARTES, para que a `Date` resultante seja a meia-noite local desse
 * dia e toda a aritmética seguinte continue valendo.
 */
export const hojeDoTenant = (tz: string) => {
  const [a, m, d] = today(tz).split("-").map(Number);
  return new Date(a, m - 1, d);
};

export const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

/**
 * A grade de 6 semanas do mês de `anchor`, começando no domingo anterior ao dia 1 — 42 células,
 * sempre. `start`/`end` são as fronteiras para pedir os eventos à API.
 */
export function gradeDoMes(anchor: Date): { start: Date; end: Date; days: Date[] } {
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const gridStart = startOfWeek(first);
  const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
  return { start: gridStart, end: addDays(gridStart, 42), days };
}

/**
 * Eventos de dia inteiro (cobranças, contas a pagar, prazos) são gravados à meia-noite UTC:
 * casamos pela DATA do calendário (sem fuso) para não "voltar" um dia em fuso negativo.
 * Eventos com horário usam a data local normalmente.
 */
export const eventYmd = (e: AgendaEvent) =>
  e.all_day ? e.starts_at.slice(0, 10) : localYmd(new Date(e.starts_at));

export const eventsOfDay = (events: AgendaEvent[], d: Date) =>
  events
    .filter((e) => eventYmd(e) === localYmd(d))
    .sort((a, b) => +new Date(a.starts_at) - +new Date(b.starts_at));

// ── faixas livres do dia ───────────────────────────────

/**
 * A janela de trabalho assumida pelo seletor de horário. É FIXA de propósito: não existe
 * expediente configurável no backend, e inventar um (migration + endpoint + tela) para oferecer
 * atalhos de horário seria construir um épico para resolver um clique. O botão "Outro horário"
 * do seletor é a válvula de escape para tudo que cai fora daqui.
 */
export const HORA_ABERTURA = 8;
export const HORA_FECHAMENTO = 18;

export type Faixa = { hora: number; inicio: string; fim: string };

/** `14` => `"14:00"`. O `% 24` faz `24` virar `"00:00"` — meia-noite, não "24:00". */
export const horaCheia = (h: number) => `${String(h % 24).padStart(2, "0")}:00`;

const hhmm = (minutos: number) => horaCheia(Math.floor(minutos / 60));

const emMinutos = (hhmmStr: string) => {
  const [h, m] = hhmmStr.split(":").map(Number);
  return h * 60 + m;
};

/** "Que dia é este instante, no fuso do tenant?" — a pergunta tem quatro lugares que a fazem. */
const diaDoInstante = (iso: string, fuso: string) => today(fuso, new Date(iso));

/** A data do evento no fuso do TENANT. Dia inteiro é data de calendário: não passa por fuso. */
const diaDoEvento = (e: AgendaEvent, fuso: string) =>
  e.all_day ? e.starts_at.slice(0, 10) : diaDoInstante(e.starts_at, fuso);

/**
 * Os eventos de `dia`, agrupados pelo fuso do TENANT.
 *
 * Irmão de `eventsOfDay`, e a diferença é o ponto: aquele agrupa por `localYmd(new Date(iso))`,
 * isto é, pelo fuso do NAVEGADOR — convenção antiga do `AgendaPage`, correta na prática porque o
 * dono abre a tela na própria cidade. Aqui não dá para conviver com o desvio: as faixas livres
 * já são calculadas no fuso do tenant, e as duas listas precisam concordar sobre a que dia um
 * compromisso das 23h pertence, senão o seletor mostra uma faixa livre logo abaixo do
 * compromisso que a ocupa.
 */
export function eventosDoDia(eventos: AgendaEvent[], dia: Date, fuso: string): AgendaEvent[] {
  const ymd = localYmd(dia);
  return eventos
    .filter((e) => diaDoEvento(e, fuso) === ymd)
    .sort((a, b) => +new Date(a.starts_at) - +new Date(b.starts_at));
}

/**
 * Quantos compromissos cada dia tem, no fuso do tenant — `YYYY-MM-DD` → contagem.
 *
 * Existe por CUSTO, não por elegância: a grade tem 42 células, e perguntar a cada uma "quantos
 * eventos são seus?" varre a lista inteira 42 vezes. Como `today()` constrói dois
 * `Intl.DateTimeFormat` descartáveis por chamada, isso vira centenas de milissegundos de main
 * thread travada por render num mês movimentado — e o render se repete a cada toque num dia.
 */
export function densidadePorDia(eventos: AgendaEvent[], fuso: string): Map<string, number> {
  const porDia = new Map<string, number>();
  for (const e of eventos) {
    const ymd = diaDoEvento(e, fuso);
    porDia.set(ymd, (porDia.get(ymd) ?? 0) + 1);
  }
  return porDia;
}

/**
 * Os parâmetros de `GET /agenda/events` para uma janela de grade.
 *
 * Fronteiras em UTC-date (meia-noite UTC da data do grid), NÃO o local→UTC: assim os eventos de
 * dia inteiro (gravados à meia-noite UTC) não caem fora do range nas bordas. Mora aqui porque os
 * dois calendários — a tela de Agenda e o seletor da ficha — pedem o mesmo mês, e a regra vivia
 * num comentário copiado nos dois arquivos. Regra que mora em comentário duplicado é regra que
 * deriva.
 */
export const paramsDaGrade = (start: Date, end: Date) => ({
  start: `${localYmd(start)}T00:00:00.000Z`,
  end: `${localYmd(end)}T00:00:00.000Z`,
  limit: 500,
});

type Intervalo = { inicio: number; fim: number };

/**
 * O trecho de `ymd` que este compromisso ocupa, em minutos do fuso do tenant — ou `null` quando
 * ele não encosta no dia.
 *
 * Os três ramos existem porque um compromisso pode ATRAVESSAR a meia-noite: um plantão das 22h às
 * 9h começa num dia e termina no outro. Filtrar só pelo dia de `starts_at` (o que `eventosDoDia`
 * faz, e está certo para LISTAR) deixaria a manhã do dia seguinte inteiramente livre na oferta,
 * em cima de um compromisso existente.
 *
 * Horário ilegível devolve `null` em vez de ocupar até a meia-noite: uma linha estranha não pode
 * varrer nove faixas em silêncio, e o aviso de conflito do `NewEventModal` continua sendo a rede.
 */
function intervaloNoDia(e: AgendaEvent, ymd: string, fuso: string): Intervalo | null {
  // As duas datas primeiro, e a saída antes de qualquer `formatTime`: numa janela de 42 dias, 97%
  // dos eventos não encostam no dia pedido, e formatá-los era o termo dominante do custo.
  const diaInicio = diaDoInstante(e.starts_at, fuso);
  const diaFim = diaDoInstante(e.ends_at, fuso);
  if (ymd < diaInicio || diaFim < ymd) return null;
  if (diaInicio < ymd && ymd < diaFim) return { inicio: 0, fim: 24 * 60 };

  const minInicio = emMinutos(formatTime(e.starts_at, fuso));
  const minFim = emMinutos(formatTime(e.ends_at, fuso));
  if (!Number.isFinite(minInicio) || !Number.isFinite(minFim)) return null;

  if (diaInicio === ymd) return { inicio: minInicio, fim: diaFim === ymd ? minFim : 24 * 60 };
  return { inicio: 0, fim: minFim };
}

/**
 * A hora de parede `minutos` do dia `dia`, no fuso do TENANT, como instante real.
 *
 * Existe porque a faixa oferecida é decidida no fuso do tenant e o `<input type="datetime-local">`
 * do formulário fala no fuso do NAVEGADOR: entregar `"14:00"` como string ingênua faria
 * `new Date(...)` reinterpretá-la na máquina de quem abriu a tela, e um dono viajando marcaria
 * 15:00 achando que marcou 14:00 — a família §6.0 do CLAUDE.md, na costura entre os dois.
 *
 * Duas passadas de propósito: o offset usado na primeira aproximação pode não ser o offset do
 * instante resultante quando o dia tem virada de horário de verão.
 */
export function instanteNoFuso(dia: Date, minutos: number, fuso: string): Date {
  const parede = Date.UTC(dia.getFullYear(), dia.getMonth(), dia.getDate(), 0, minutos);
  const aproximado = new Date(parede - offsetEmMinutos(fuso, new Date(parede)) * 60_000);
  return new Date(parede - offsetEmMinutos(fuso, aproximado) * 60_000);
}

/**
 * Quantos minutos o fuso está à frente do UTC NAQUELE instante (negativo a oeste de Greenwich).
 *
 * ⚠️ **Sem `new Date(string)` em lugar nenhum, e a ausência é a funcionalidade.** O truque comum —
 * `new Date(x.toLocaleString("en-US", { timeZone: … }))` dos dois lados e subtrair — parece
 * cancelar o fuso da MÁQUINA, e cancela, exceto quando as duas strings caem em lados opostos da
 * virada de horário de verão **do navegador**: aí sobram 60 minutos. Medido antes do conserto: com
 * a máquina em `America/New_York`, 52 combinações de (fuso do tenant × dia × hora) devolviam a
 * hora errada — um tenant em Sydney via a faixa "08:00" virar 09:00 no formulário, nos dois dias
 * do ano em que os EUA viram o relógio. O produto é brasileiro e o Brasil não tem horário de
 * verão, mas `tenants.timezone` aceita qualquer zona IANA, e o fuso do NAVEGADOR é de quem abre a
 * tela, não de quem configurou o tenant.
 *
 * `formatToParts` lê as partes de parede direto no fuso alvo, e `Date.UTC` as remonta sem passar
 * por parser nenhum: o fuso da máquina não entra na conta em momento algum.
 */
function offsetEmMinutos(fuso: string, instante: Date): number {
  const partes: Record<string, string> = {};
  for (const { type, value } of formatadorDe(fusoValido(fuso)).formatToParts(instante)) {
    partes[type] = value;
  }
  const comoSeFosseUtc = Date.UTC(
    Number(partes.year),
    Number(partes.month) - 1,
    Number(partes.day),
    // `hour12: false` produz "24" para a meia-noite em alguns ambientes; `% 24` normaliza.
    Number(partes.hour) % 24,
    Number(partes.minute),
    Number(partes.second),
  );
  // As partes têm resolução de SEGUNDO: truncar o instante evita um resto de milissegundos virar
  // um offset quebrado.
  return (comoSeFosseUtc - Math.floor(instante.getTime() / 1000) * 1000) / 60_000;
}

/**
 * Um `Intl.DateTimeFormat` por fuso, reaproveitado.
 *
 * Construir um custa ~90 µs, e `instanteNoFuso` chama `offsetEmMinutos` duas vezes por faixa
 * oferecida. O `Map` é global de propósito: o conjunto de fusos vivos numa sessão é UM (o do
 * tenant), então não há o que expurgar.
 */
const FORMATADORES = new Map<string, Intl.DateTimeFormat>();
const formatadorDe = (tz: string) => {
  const existente = FORMATADORES.get(tz);
  if (existente) return existente;
  const novo = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  FORMATADORES.set(tz, novo);
  return novo;
};

/**
 * Os blocos de 1h ainda livres em `dia`, no fuso do tenant.
 *
 * Três exclusões deliberadas, cada uma um jeito diferente de errar:
 * - **`all_day` não ocupa.** Cobrança, conta a pagar e prazo são TODOS de dia inteiro; se
 *   ocupassem, todo dia com uma parcela vencendo apareceria cheio — o oposto do que o seletor
 *   existe para mostrar.
 * - **Cancelado não ocupa.** Mesma postura do `BlocoDaAgenda`, que pede `exclude_cancelled`.
 * - **No dia de hoje, o que já começou some.** Oferecer 09:00 às 11h da manhã é oferecer erro.
 *
 * Tudo é comparado em minutos DO FUSO DO TENANT (`formatTime`), nunca pelas partes locais de um
 * `Date` — `localYmd`/`getHours()` sobre um instante da API leem o fuso do NAVEGADOR e trocariam
 * as faixas de lugar num notebook em viagem ou num headless em UTC.
 */
export function faixasLivres(
  eventos: AgendaEvent[],
  dia: Date,
  fuso: string,
  agora: Date = new Date(),
): Faixa[] {
  const ymd = localYmd(dia);

  const ocupado = eventos
    .filter((e) => !e.all_day && e.status !== "cancelled")
    .map((e) => intervaloNoDia(e, ymd, fuso))
    .filter((i): i is Intervalo => i !== null);

  // −1 em qualquer outro dia: nada do passado a cortar.
  const corte = today(fuso, agora) === ymd ? emMinutos(formatTime(agora.toISOString(), fuso)) : -1;

  const livres: Faixa[] = [];
  for (let h = HORA_ABERTURA; h < HORA_FECHAMENTO; h++) {
    const inicio = h * 60;
    const fim = inicio + 60;
    // `<=`: às 14:00:00 em ponto a faixa das 14h não tem mais nem um minuto de
    // antecedência. Com `<` estrito ela seria oferecida, contra a própria regra acima.
    if (inicio <= corte) continue;
    if (ocupado.some((o) => o.inicio < fim && o.fim > inicio)) continue;
    livres.push({ hora: h, inicio: hhmm(inicio), fim: hhmm(fim) });
  }
  return livres;
}
