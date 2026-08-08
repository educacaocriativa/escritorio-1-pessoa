import type { Briefing } from "@e1p/shared-types";
import { type ReactNode, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../../lib/api";
import { today } from "../../lib/datetime";
import { useFuso } from "../../store/auth";

/**
 * Marca de "a entrada de hoje já foi decidida NESTE aparelho", no formato `YYYY-MM-DD` do fuso do
 * TENANT.
 *
 * Existe por dois motivos, e o segundo é o que importa: (1) poupa uma ida ao servidor em toda
 * visita ao painel depois da primeira do dia; (2) quebra o laço — quem é mandado à Vima e toca
 * "Ir para o painel" antes de a marcação de leitura chegar ao servidor voltaria à Vima
 * indefinidamente. A AUTORIDADE continua sendo `read_at` no servidor; isto é só cache do dia.
 */
export const CHAVE_ENTRADA = "e1p_briefing_dia";

/**
 * Marca de "o núcleo do DNA já foi decidido NESTE aparelho" — respondido ou pulado, tanto faz.
 *
 * Não carrega data, ao contrário de `CHAVE_ENTRADA`: o núcleo é de uma vez na vida, não de uma
 * vez por dia.
 */
export const CHAVE_NUCLEO = "e1p_dna_nucleo";

type Decisao = "perguntando" | "nucleo" | "vima" | "cockpit";

/**
 * Decide qual é a porta de entrada do dia.
 *
 * **O briefing aparece UMA VEZ POR DIA, não a cada login.** Quem entra cinco vezes veria cinco
 * vezes, e a porta de entrada viraria obstáculo. O mecanismo é `read_at`: primeiro acesso do dia
 * → a Vima; já lido → o Cockpit, com o caminho de volta à Vima na própria tela dela.
 *
 * Falha de rede cai no Cockpit e **não** grava a marca: o produto não fica trancado por causa do
 * briefing, e a tentativa seguinte ainda pode entregá-lo.
 */
export default function EntradaDoDia({ children }: { children: ReactNode }) {
  const fuso = useFuso();
  const hoje = today(fuso);
  const [decisao, setDecisao] = useState<Decisao>(() =>
    lerMarca() === hoje ? "cockpit" : "perguntando",
  );

  useEffect(() => {
    if (decisao !== "perguntando") return;
    let vivo = true;

    function decidirPeloBriefing() {
      api
        .get<Briefing>("/vima/briefing")
        .then(({ data }) => {
          if (!vivo) return;
          gravarMarca(hoje);
          setDecisao(data?.read_at ? "cockpit" : "vima");
        })
        .catch(() => {
          if (vivo) setDecisao("cockpit");
        });
    }

    // O núcleo do DNA vem ANTES do briefing, e só no primeiro acesso: um dono que nunca
    // respondeu nada recebe um briefing que fala com todo mundo do mesmo jeito. Perguntar
    // primeiro é o que faz a leitura dele já nascer calibrada — de amanhã em diante.
    if (lerMarcaNucleo() === null) {
      api
        .get<unknown[]>("/dna/faltantes", { params: { gancho: "nucleo" } })
        .then(({ data }) => {
          if (!vivo) return;
          if (data?.length) {
            setDecisao("nucleo");
            return;
          }
          gravarMarcaNucleo();
          decidirPeloBriefing();
        })
        // 403 = sub-usuário sem `settings`. O DNA é da empresa e não é dele: segue para o
        // briefing normalmente, sem nunca ver a pergunta.
        .catch(() => {
          if (vivo) decidirPeloBriefing();
        });
      return () => {
        vivo = false;
      };
    }

    decidirPeloBriefing();
    return () => {
      vivo = false;
    };
  }, [decisao, hoje]);

  if (decisao === "perguntando") {
    return <div className="py-10 text-center text-sm text-neutral-400">Um instante…</div>;
  }
  if (decisao === "nucleo") return <Navigate to="/dna/nucleo" replace />;
  if (decisao === "vima") return <Navigate to="/vima" replace />;
  return <>{children}</>;
}

function lerMarcaNucleo(): string | null {
  try {
    return localStorage.getItem(CHAVE_NUCLEO);
  } catch {
    return null;
  }
}

function gravarMarcaNucleo(): void {
  try {
    localStorage.setItem(CHAVE_NUCLEO, "1");
  } catch {
    // Sem a marca, a entrada consulta o servidor toda visita — mais lento, correto.
  }
}

/** `localStorage` pode lançar (modo privativo do Safari, cota) — e isso não pode derrubar a app. */
function lerMarca(): string | null {
  try {
    return localStorage.getItem(CHAVE_ENTRADA);
  } catch {
    return null;
  }
}

function gravarMarca(dia: string): void {
  try {
    localStorage.setItem(CHAVE_ENTRADA, dia);
  } catch {
    // Sem cache do dia a entrada volta a perguntar ao servidor toda visita — mais lento, correto.
  }
}
