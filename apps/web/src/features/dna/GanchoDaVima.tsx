import type { DnaPergunta } from "@e1p/shared-types";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import PerguntaDaVima from "./PerguntaDaVima";

const CLASSES = ["calibracao", "retrato"] as const;
const FORMATOS = ["escolha", "escolha_multipla", "texto"] as const;

/**
 * A resposta de `/dna/pendente` tem a FORMA de uma pergunta?
 *
 * `data ?? null` só protegia contra `null`/`undefined`. Qualquer outro valor — `[]` de uma
 * consulta vazia, `{}` de um erro serializado, uma mudança de contrato — é *truthy*, passa pela
 * guarda `if (!pergunta)` e renderiza um card FANTASMA: parágrafo sem texto e o botão "Responder
 * depois" pendurado no nada, medido em **101px** de deslocamento acima da dobra de 740px, nas
 * seis telas que montam o gancho (issue #161, causa do flake do #149).
 *
 * A checagem é por FORMA, nunca por veracidade: valida só o que o contrato `PerguntaOut`
 * (`apps/api/app/modules/dna/schemas.py`) declara obrigatório E que o caminho de render consome.
 *
 * - `key`: vira a URL do `PUT /dna/{key}` — sem ela o card existe mas não sabe responder.
 * - `texto`: é o parágrafo. Vazio (ou só espaço) É o card fantasma da issue, com objeto bem
 *   formado em volta — por isso `{ texto: "" }` é REJEITADO, não aceito.
 * - `classe`: escolhe a promessa que a tela faz ao dono ("muda amanhã" vs. "fica guardado"). Um
 *   valor fora do par cai no ramo `retrato` em silêncio — prometer errado é exatamente o erro que
 *   as duas classes existem para impedir (ver `PerguntaDaVima`).
 * - `formato`: fora dos três, o corpo não renderiza e sobra o mesmo card sem conteúdo.
 * - `opcoes`: `PerguntaDaVima` faz `.map` nela. Se não for array, o React ESTOURA no render — e
 *   render não cai no `.catch()` da promise, então derrubaria a tela hospedeira, quebrando o
 *   "falha em silêncio, sempre" que este componente promete.
 *
 * **Exportada porque a classe não mora neste componente** (issue #179): `NucleoPage` renderiza
 * uma LISTA das mesmas perguntas pelo mesmo `PerguntaDaVima`, e lá o payload fora de forma não
 * dava card fantasma, dava TELA BRANCA. Um predicado só, no arquivo que o documenta, em vez de
 * uma segunda convenção parecida a dois diretórios de distância.
 *
 * `eixo` fica de fora de propósito: é obrigatório no contrato, mas nenhum pixel depende dele.
 * Validá-lo só se sustentaria num teste tautológico, e predicado sem consequência é dívida.
 *
 * O acesso é por `p?.`, sem um `typeof data === "object"` na frente: em `null`, `undefined`, `0`
 * ou `""` a cadeia devolve `undefined` e o primeiro predicado já reprova. Uma guarda de tipo
 * separada seria um predicado que nenhum teste consegue matar — o `.catch()` da promise a
 * cobriria em silêncio — e predicado sem rede é dívida, não proteção.
 */
export function ehPergunta(data: unknown): data is DnaPergunta {
  const p = data as Record<string, unknown> | null | undefined;
  return (
    typeof p?.key === "string" &&
    p.key !== "" &&
    typeof p.texto === "string" &&
    p.texto.trim() !== "" &&
    CLASSES.includes(p.classe as DnaPergunta["classe"]) &&
    FORMATOS.includes(p.formato as DnaPergunta["formato"]) &&
    Array.isArray(p.opcoes)
  );
}

/**
 * A pergunta do DNA colada ao contexto que a torna óbvia.
 *
 * **Falha em silêncio, sempre.** Um 403 (sub-usuário sem `settings`) ou uma rede ruim não podem
 * derrubar a tela hospedeira — o DNA é acessório em toda superfície onde aparece. Erro aqui
 * significa "não pergunta hoje", nunca "quebra o briefing". Payload inesperado entra nessa mesma
 * regra: sem forma de pergunta, não há card.
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
        if (vivo) setPergunta(ehPergunta(data) ? data : null);
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
