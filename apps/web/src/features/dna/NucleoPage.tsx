import type { DnaPergunta } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import PerguntaDaVima from "./PerguntaDaVima";

/** Marca de "o núcleo já foi decidido NESTE aparelho". Espelha `CHAVE_ENTRADA` do briefing. */
export const CHAVE_NUCLEO = "e1p_dna_nucleo";

/**
 * As seis perguntas do primeiro acesso.
 *
 * **Nenhuma é de Calibração, e essa é a inversão central do design.** "Em quanto tempo eu te
 * aviso que ninguém respondeu o Carlos?" é impossível de responder bem antes de ter visto um
 * briefing — a resposta seria um chute que depois vira comportamento errado com aparência de
 * configuração deliberada. Calibração vem por gancho, colada à ausência que a motivou.
 *
 * **É sequência anunciada, não interrogatório:** fim visível ("2 de 6") e saída em um toque. Por
 * isso é a exceção declarada à regra de uma pergunta por dia — o que cansa é a interrupção não
 * anunciada, não a sequência que a pessoa entrou sabendo que ia atravessar.
 */
export default function NucleoPage() {
  const navegar = useNavigate();
  const [perguntas, setPerguntas] = useState<DnaPergunta[] | null>(null);
  const [i, setI] = useState(0);

  useEffect(() => {
    let vivo = true;
    api
      .get<DnaPergunta[]>("/dna/faltantes", { params: { gancho: "nucleo" } })
      .then(({ data }) => {
        if (vivo) setPerguntas(data ?? []);
      })
      .catch(() => {
        // 403 (sub-usuário sem `settings`) ou rede ruim: o núcleo não pode trancar a entrada.
        if (vivo) sair();
      });
    return () => {
      vivo = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function sair() {
    try {
      localStorage.setItem(CHAVE_NUCLEO, "1");
    } catch {
      // Sem a marca, a entrada volta a perguntar ao servidor — mais lento, correto.
    }
    navegar("/", { replace: true });
  }

  function avancar() {
    if (perguntas && i + 1 < perguntas.length) setI(i + 1);
    else sair();
  }

  if (!perguntas) {
    return <div className="py-10 text-center text-sm text-neutral-400">Um instante…</div>;
  }
  if (perguntas.length === 0) {
    sair();
    return null;
  }

  return (
    <div className="mx-auto max-w-md space-y-4 p-4">
      <div>
        <p className="text-sm text-neutral-500">
          {i + 1} de {perguntas.length}
        </p>
        <h1 className="text-xl font-bold text-neutral-800">Me conta do seu negócio</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Leva menos de dois minutos e é o que faz o resumo diário falar a sua língua.
        </p>
      </div>

      <PerguntaDaVima
        key={perguntas[i].key}
        pergunta={perguntas[i]}
        source="nucleo"
        onPronto={avancar}
        onPular={avancar}
      />

      <button
        type="button"
        onClick={sair}
        className="w-full text-center text-xs text-neutral-400 underline"
      >
        Pular por enquanto
      </button>
    </div>
  );
}
