import type { GoogleCalendarStatus } from "@e1p/shared-types";
import { Video } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  apiErrorMessage,
  disconnectGoogle,
  getGoogleConnectUrl,
  getGoogleStatus,
} from "../../lib/api";
import CelularSection from "./CelularSection";
import IntegrationsSection from "./IntegrationsSection";
import { Card } from "./ui";

/** Aba "Integrações": o que o e1p conversa com o mundo fora dele. */
export default function IntegracoesTab() {
  return (
    <div className="space-y-6">
      <IntegrationsSection />
      <GoogleSection />
      <CelularSection />
    </div>
  );
}

/**
 * Seção "Google Calendar": conectar/desconectar a conta Google do owner para gerar Meet
 * automaticamente na Agenda (Story 4.1). O botão "Conectar" só aparece se a plataforma tiver o
 * app OAuth configurado (`configured=true`). Trata o retorno do OAuth via `?google=connected|error`.
 */
function GoogleSection() {
  const [status, setStatus] = useState<GoogleCalendarStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await getGoogleStatus());
    } catch {
      setStatus({ configured: false, connected: false, email: null });
    }
  }, []);

  useEffect(() => {
    // Feedback do retorno do OAuth (?google=connected|error) e limpeza da query string.
    const params = new URLSearchParams(window.location.search);
    const g = params.get("google");
    if (g === "connected") setMsg({ kind: "ok", text: "Conta Google conectada com sucesso." });
    else if (g === "error") setMsg({ kind: "err", text: "Não foi possível conectar ao Google." });
    if (g) {
      params.delete("google");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : ""));
    }
    load();
  }, [load]);

  async function connect() {
    setBusy(true);
    setMsg(null);
    try {
      window.location.href = await getGoogleConnectUrl();
    } catch (err) {
      setMsg({ kind: "err", text: apiErrorMessage(err) });
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setMsg(null);
    try {
      await disconnectGoogle();
      await load();
      setMsg({ kind: "ok", text: "Conta Google desconectada." });
    } catch (err) {
      setMsg({ kind: "err", text: apiErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Google Calendar">
      <p className="mb-3 text-xs text-neutral-400">
        Conecte sua conta Google para gerar links do Meet automaticamente ao criar reuniões na
        Agenda. Enquanto não conectar, você continua colando o link manualmente.
      </p>
      {msg && (
        <div
          className={`mb-3 rounded-lg px-3 py-2 text-sm ${
            msg.kind === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-danger"
          }`}
        >
          {msg.text}
        </div>
      )}
      {status === null ? (
        <p className="text-sm text-neutral-400">Carregando...</p>
      ) : !status.configured ? (
        <p className="text-sm text-neutral-500">
          Integração Google não configurada nesta plataforma.
        </p>
      ) : status.connected ? (
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm text-neutral-700">
            <Video size={16} className="text-primary-600" />
            Conectado{status.email ? ` como ${status.email}` : ""}
          </div>
          <button
            onClick={disconnect}
            disabled={busy}
            className="rounded-pill border border-neutral-200 px-4 py-2 text-sm font-semibold text-neutral-600 hover:bg-neutral-50 disabled:opacity-50"
          >
            Desconectar
          </button>
        </div>
      ) : (
        <button
          onClick={connect}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-pill bg-primary-600 px-5 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
        >
          <Video size={14} /> {busy ? "Redirecionando..." : "Conectar Google"}
        </button>
      )}
    </Card>
  );
}
