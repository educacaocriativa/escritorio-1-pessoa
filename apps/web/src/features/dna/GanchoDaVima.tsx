import type { DnaPergunta } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import PerguntaDaVima from "./PerguntaDaVima";

/**
 * A pergunta do DNA colada ao contexto que a torna óbvia.
 *
 * **Falha em silêncio, sempre.** Um 403 (sub-usuário sem `settings`) ou uma rede ruim não podem
 * derrubar a tela hospedeira — o DNA é acessório em toda superfície onde aparece. Erro aqui
 * significa "não pergunta hoje", nunca "quebra o briefing".
 *
 * A cadência inteira mora no servidor (`dna/cadencia.py`): uma pergunta por dia no produto
 * inteiro, pulada em quarentena de 7 dias. O componente só mostra o que lhe deram.
 */
export default function GanchoDaVima({ gancho }: { gancho: string }) {
  const [pergunta, setPergunta] = useState<DnaPergunta | null>(null);

  useEffect(() => {
    let vivo = true;
    api
      .get<DnaPergunta | null>("/dna/pendente", { params: { gancho } })
      .then(({ data }) => {
        if (vivo) setPergunta(data ?? null);
      })
      .catch(() => {
        if (vivo) setPergunta(null);
      });
    return () => {
      vivo = false;
    };
  }, [gancho]);

  if (!pergunta) return null;

  return (
    <div className="mt-2">
      <PerguntaDaVima
        pergunta={pergunta}
        source="gancho"
        onPronto={() => setPergunta(null)}
        onPular={() => setPergunta(null)}
      />
    </div>
  );
}
