import type { BriefingPreferences } from "@e1p/shared-types";
import { useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

/**
 * Preferências do briefing, DENTRO da tela do briefing.
 *
 * Não mora em `/config` de propósito: aquela rota exige o módulo `settings`, e escolher o próprio
 * horário / ligar o próprio WhatsApp é preferência de PESSOA, não configuração de empresa. Um
 * sub-usuário sem `settings` precisa das duas coisas.
 *
 * 360px primeiro: um controle por linha, alvos de toque altos, nenhuma largura fixa.
 */
export default function PreferenciasSection({
  prefs,
  onSaved,
}: {
  prefs: BriefingPreferences;
  onSaved: (p: BriefingPreferences) => void;
}) {
  const [hora, setHora] = useState(prefs.briefing_hour);
  const [zap, setZap] = useState(prefs.briefing_whatsapp_enabled);
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  const indisponivel = !prefs.briefing_whatsapp_disponivel;

  async function salvar() {
    setBusy(true);
    setErro(null);
    setOk(false);
    try {
      const { data } = await api.patch<BriefingPreferences>("/auth/me/preferences", {
        briefing_hour: hora,
        briefing_whatsapp_enabled: zap,
      });
      onSaved(data);
      setOk(true);
    } catch (err) {
      setErro(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 rounded-lg border border-neutral-200 bg-white p-4">
      <h2 className="text-base font-semibold text-neutral-800">Como você quer receber</h2>

      <div className="mt-4 flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm text-neutral-700">
          <span id="label-hora">Horário do briefing</span>
          <input
            type="time"
            aria-labelledby="label-hora"
            value={hora}
            onChange={(e) => setHora(e.target.value)}
            className="w-full rounded-md border border-neutral-300 px-3 py-2 text-base"
          />
          <span className="text-xs text-neutral-500">
            No seu horário — o do escritório, não o do servidor.
          </span>
        </label>

        <label className="flex items-start gap-3 text-sm text-neutral-700">
          <input
            type="checkbox"
            aria-label="Receber o briefing no WhatsApp"
            checked={zap && !indisponivel}
            disabled={indisponivel}
            onChange={(e) => setZap(e.target.checked)}
            className="mt-1 h-5 w-5 shrink-0 rounded border-neutral-300 disabled:opacity-40"
          />
          <span className="min-w-0">
            Receber também no WhatsApp
            {/*
              A dependência da Meta é EXTERNA ao repositório e demora. Dizer o motivo é o que
              separa "ainda não dá" de "está quebrado" — sem a frase, o switch desligado parece
              defeito nosso.
            */}
            {indisponivel && prefs.briefing_whatsapp_indisponivel_motivo && (
              <span className="mt-1 block text-xs text-amber-700">
                {prefs.briefing_whatsapp_indisponivel_motivo}
              </span>
            )}
            <span className="mt-1 block text-xs text-neutral-500">
              Em dia sem novidade nenhuma o WhatsApp não sai — só a tela.
            </span>
          </span>
        </label>
      </div>

      {erro && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {erro}
        </p>
      )}
      {ok && !erro && <p className="mt-3 text-sm text-accent-700">Preferências salvas.</p>}

      <button
        type="button"
        onClick={salvar}
        disabled={busy}
        className="mt-4 w-full rounded-md bg-primary px-4 py-2.5 text-base font-medium text-white disabled:opacity-60 sm:w-auto"
      >
        {busy ? "Salvando…" : "Salvar"}
      </button>
    </section>
  );
}
