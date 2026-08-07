import type { FunnelSummary } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { Card } from "./ui";

/**
 * Aba "Vendas". O Funil de Vendas em que todo lead novo (source=landing/api) é inscrito
 * automaticamente (auto-enroll). Sem seleção = comportamento atual (sem auto-enroll).
 *
 * O valor faz parte do perfil do tenant, então quem guarda e salva continua sendo a página.
 */
export default function VendasTab({ value, onChange }: {
  value: string | null; onChange: (v: string | null) => void;
}) {
  const [funnels, setFunnels] = useState<FunnelSummary[]>([]);

  useEffect(() => {
    api.get<FunnelSummary[]>("/funnels").then(({ data }) => {
      setFunnels(Array.isArray(data) ? data : []);
    });
  }, []);

  return (
    <Card title="Funil de entrada padrão">
      <p className="mb-3 text-xs text-neutral-400">
        Todo lead novo — de uma landing page publicada em Sites ou de um site externo via chave
        de integração — entra automaticamente neste funil.
      </p>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
      >
        <option value="">Nenhum (não inscrever automaticamente)</option>
        {funnels.map((f) => (
          <option key={f.id} value={f.id}>{f.name}</option>
        ))}
      </select>
    </Card>
  );
}
