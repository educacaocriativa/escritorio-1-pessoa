import type { SearchGroup, SearchResponse } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { semVazios } from "./resultado";

const DEBOUNCE_MS = 250;

/** Espelha `MIN_CARACTERES` do serviço: abaixo disto o backend não consulta o banco. */
const MIN_CARACTERES = 2;

export interface OpcoesDaBusca {
  profundidade?: "shallow" | "deep";
  /** `0` = sem recorte. Só afeta mensagens — ver a spec §6.2. */
  meses?: number;
  limite?: number;
}

export function useBusca(q: string, opcoes: OpcoesDaBusca = {}) {
  const { profundidade = "shallow", meses = 12, limite = 3 } = opcoes;
  const [grupos, setGrupos] = useState<SearchGroup[]>([]);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    const termo = q.trim();
    if (termo.length < MIN_CARACTERES) {
      setGrupos([]);
      setCarregando(false);
      return;
    }

    // O `AbortController` não é enfeite: sem ele, a resposta de uma consulta ANTERIOR chega
    // depois e sobrescreve a atual. O sintoma é "o resultado pisca errado" — nunca um erro,
    // que é o que torna esse defeito difícil de achar depois que ele já está em produção.
    const controle = new AbortController();
    const timer = setTimeout(() => {
      setCarregando(true);
      api
        .get<SearchResponse>("/search", {
          params: { q: termo, depth: profundidade, months: meses, limit: limite },
          signal: controle.signal,
        })
        .then((r) => {
          setGrupos(semVazios(r.data.groups));
          setCarregando(false);
        })
        .catch(() => {
          // Requisição cancelada é o caso NORMAL aqui (o usuário continuou digitando), não erro
          // de produto. Deixar `carregando` ligado seria mostrar um esqueleto que nunca sai.
          if (!controle.signal.aborted) {
            setGrupos([]);
            setCarregando(false);
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
      controle.abort();
    };
  }, [q, profundidade, meses, limite]);

  return {
    grupos,
    carregando,
    /** Só é "vazio" depois que a resposta chegou — antes disso é "ainda não sei". */
    vazio: !carregando && q.trim().length >= MIN_CARACTERES && grupos.length === 0,
  };
}
