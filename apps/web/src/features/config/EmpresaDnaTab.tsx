import type { DnaPergunta } from "@e1p/shared-types";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import PerguntaDaVima from "../dna/PerguntaDaVima";

const EIXOS: { key: DnaPergunta["eixo"]; titulo: string; descricao: string }[] = [
  { key: "oferta", titulo: "Oferta", descricao: "O que você vende e como cobra" },
  { key: "cliente", titulo: "Cliente", descricao: "Quem compra e como chega até você" },
  { key: "ritmo", titulo: "Ritmo", descricao: "Como é a sua semana" },
  { key: "dinheiro", titulo: "Dinheiro", descricao: "Como você recebe e reage a atraso" },
  { key: "limites", titulo: "Limites", descricao: "O que você nunca faz" },
];

/**
 * A saída para quem quiser sentar e responder tudo de uma vez.
 *
 * **É a única superfície SEM cadência.** A regra de uma pergunta por dia existe para proteger de
 * interrupção; aqui a pessoa foi procurar, e esconder pergunta de quem foi atrás dela seria
 * hostil. Tudo editável a qualquer momento — inclusive o que já foi respondido.
 */
export default function EmpresaDnaTab() {
  const [catalogo, setCatalogo] = useState<DnaPergunta[]>([]);
  const [respostas, setRespostas] = useState<Record<string, unknown>>({});
  const [reabertas, setReabertas] = useState<string[]>([]);

  const carregar = useCallback(async () => {
    const [{ data: perguntas }, { data: dadas }] = await Promise.all([
      api.get<DnaPergunta[]>("/dna/catalogo"),
      api.get<Record<string, unknown>>("/dna/respostas"),
    ]);
    setCatalogo(perguntas);
    setRespostas(dadas);
    setReabertas([]);
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  if (catalogo.length === 0) {
    return <p className="text-sm text-neutral-400">Carregando…</p>;
  }

  const respondidas = catalogo.filter((p) => p.key in respostas).length;

  return (
    <div className="space-y-8">
      <p className="text-sm text-neutral-500">
        {respondidas} de {catalogo.length} respondidas. Não precisa responder tudo de uma vez — a
        Vima pergunta aos poucos, no momento em que cada resposta faz sentido.
      </p>

      {EIXOS.map((eixo) => {
        const doEixo = catalogo.filter((p) => p.eixo === eixo.key);
        if (doEixo.length === 0) return null;
        return (
          <section key={eixo.key} className="space-y-3">
            <div>
              <h2 className="text-lg font-semibold text-neutral-800">{eixo.titulo}</h2>
              <p className="text-xs text-neutral-500">{eixo.descricao}</p>
            </div>
            {doEixo.map((p) => (
              <div key={p.key}>
                {p.key in respostas && !reabertas.includes(p.key) ? (
                  <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-4">
                    <p className="text-sm text-neutral-600">{p.texto}</p>
                    <p className="mt-1 text-sm font-medium text-neutral-800">
                      {rotulo(p, respostas[p.key])}
                    </p>
                    <button
                      type="button"
                      onClick={() => setReabertas([...reabertas, p.key])}
                      className="mt-2 text-xs text-neutral-400 underline"
                    >
                      Mudar
                    </button>
                  </div>
                ) : (
                  <PerguntaDaVima
                    pergunta={p}
                    source="config"
                    onPronto={carregar}
                    onPular={carregar}
                  />
                )}
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}

/** Mostra o RÓTULO que o dono escolheu, não o valor interno que o sistema guarda. */
function rotulo(pergunta: DnaPergunta, valor: unknown): string {
  if (pergunta.formato === "texto") return String(valor);
  const lista = Array.isArray(valor) ? valor : [valor];
  return lista
    .map((v) => pergunta.opcoes.find((o) => o.valor === v)?.rotulo ?? String(v))
    .join(", ");
}
