import type { CreateEventResult } from "@e1p/shared-types";
import { Video } from "lucide-react";
import { useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage, getGoogleStatus } from "../../lib/api";
import { localYmd } from "../../lib/datetime";
import { useFuso } from "../../store/auth";
import { instanteNoFuso } from "./grade";

// Tipos de evento que geram Meet automaticamente quando o Google está conectado (Story 4.1).
const MEET_KINDS = new Set(["reuniao", "atendimento", "audiencia"]);

/**
 * Instante -> o que o `<input type="datetime-local">` espera: `"YYYY-MM-DDTHH:mm"` nas partes
 * LOCAIS do navegador. E o inverso exato do `new Date(valor)` que o `save()` faz, entao o
 * instante que entra e o instante que sai.
 */
const paraInputLocal = (d: Date) =>
  `${localYmd(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

const KINDS = [
  ["atendimento", "Atendimento"],
  ["reuniao", "Reunião"],
  ["audiencia", "Audiência"],
  ["prazo", "Prazo"],
  ["lembrete", "Lembrete"],
  ["bloqueio", "Bloqueio"],
] as const;

export default function NewEventModal({
  open,
  initialDate,
  initialHour,
  onClose,
  onCreated,
  clientId,
}: {
  open: boolean;
  initialDate: Date | null;
  /** Hora cheia escolhida no `EscolherHorario` (14 => 14:00–15:00). Ausente = 09:00–10:00, o
   *  default de quem clicou num dia da Agenda sem dizer a que horas. */
  initialHour?: number | null;
  onClose: () => void;
  onCreated: () => void;
  /** Quando presente, o evento nasce ligado a este contato. A ficha 360° usa isto; a tela de
   *  Agenda não passa nada e segue criando evento solto. */
  clientId?: string;
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
  const [googleConnected, setGoogleConnected] = useState(false);
  const fuso = useFuso();

  // Descobre se o Google está conectado (para a dica de "Meet automático"). Silencioso em falha.
  useEffect(() => {
    if (!open) return;
    getGoogleStatus()
      .then((s) => setGoogleConnected(s.connected))
      .catch(() => setGoogleConnected(false));
  }, [open]);

  const autoMeet = googleConnected && MEET_KINDS.has(kind);

  // Pré-preenche a data ao abrir num dia do calendário — e a HORA quando ela veio junto.
  //
  // ⚠️ A hora é de PAREDE DO TENANT, não do navegador. O seletor decide as faixas no fuso do
  // tenant (`faixasLivres`) e o `<input type="datetime-local">` fala no fuso da máquina: escrever
  // `"14:00"` direto fazia o `new Date(...)` do `save()` reinterpretá-la localmente, e um dono com
  // o navegador em outro fuso marcava um horário diferente do que apontou na tela — a família §6.0
  // do CLAUDE.md, na costura entre os dois componentes. Quando os dois fusos coincidem (o caso
  // normal) o resultado é byte a byte o de antes.
  useEffect(() => {
    if (open && initialDate) {
      const d = localYmd(initialDate);
      setStartDate(d);
      setEndDate(d);
      const h = initialHour ?? 9;
      setStart(paraInputLocal(instanteNoFuso(initialDate, h * 60, fuso)));
      setEnd(paraInputLocal(instanteNoFuso(initialDate, (h + 1) * 60, fuso)));
    }
  }, [open, initialDate, initialHour, fuso]);

  async function save() {
    setError(null);
    setConflict(null);
    setSaving(true);
    try {
      // Eventos com horário: o input datetime-local devolve uma string "naive" (sem fuso,
      // ex. "2026-07-13T09:00"). Enviá-la crua fazia o backend tratá-la como UTC (grava
      // "...T09:00:00Z"), exibindo 3h a menos no fuso do Brasil (bug #23). new Date(x) a
      // interpreta como horário LOCAL e .toISOString() serializa para UTC real (local→UTC).
      // O ramo all_day é intencionalmente meia-noite UTC da data de calendário (ver CLAUDE.md
      // §6.0) — NÃO converter, sob pena de reintroduzir o bug antigo de sumiço na agenda.
      const starts_at = allDay ? `${startDate}T00:00:00` : new Date(start).toISOString();
      const ends_at = allDay ? `${endDate || startDate}T23:59:00` : new Date(end).toISOString();
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
        client_id: clientId ?? null,
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
              placeholder={
                autoMeet ? "Deixe em branco para gerar o Meet automaticamente" : "Cole o link da reunião"
              }
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
          {autoMeet && !meetingUrl && (
            <p className="mt-1 text-xs text-primary-600">
              Um link do Meet será gerado automaticamente ao salvar (Google conectado).
            </p>
          )}
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
