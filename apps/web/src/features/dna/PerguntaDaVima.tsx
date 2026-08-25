import type { DnaPergunta } from "@e1p/shared-types";
import { useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";

type Props = {
  pergunta: DnaPergunta;
  source: "nucleo" | "gancho" | "config";
  onPronto: () => void;
  onPular?: () => void;
};

/**
 * A pergunta do DNA, em um único componente para todas as superfícies (núcleo, gancho, config).
 *
 * **A tela DIZ o que cada classe faz.** Calibração vale a partir de amanhã — o briefing de hoje
 * é idempotente e já foi narrado, e mentir sobre isso custa mais que explicar. Retrato é
 * guardado, e prometer efeito imediato a ele seria exatamente o erro que as duas classes
 * existem para impedir: um produto que finge ouvir é pior que um que não pergunta.
 *
 * Desenhado para 360px: opções são blocos de largura inteira, não uma linha de pílulas.
 */
export default function PerguntaDaVima({ pergunta, source, onPronto, onPular }: Props) {
  const [texto, setTexto] = useState("");
  const [marcadas, setMarcadas] = useState<(string | number | null)[]>([]);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function responder(valor: unknown) {
    setSalvando(true);
    setErro(null);
    try {
      await api.put(`/dna/${pergunta.key}`, { valor, source });
      onPronto();
    } catch (e) {
      setErro(apiErrorMessage(e));
    } finally {
      setSalvando(false);
    }
  }

  async function pular() {
    setSalvando(true);
    setErro(null);
    try {
      await api.post(`/dna/${pergunta.key}/pular`, { source });
      (onPular ?? onPronto)();
    } catch (e) {
      setErro(apiErrorMessage(e));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-4">
      {/* ⚠️ **`break-words` não é enfeite** (#208, medido em 360×740). O catálogo do DNA mora no
          servidor (`dna/catalog.py`) e o front não tem cópia dele: um `texto` sem espaço para
          quebrar não tem onde quebrar. Em `/dna/nucleo` isso vale `documentElement.scrollWidth`
          = **636px** numa viewport de 360 — sozinho, com os botões já quebrando. E ali não há
          `main.overflow-x-hidden` que recorte (`ProtectedBareLayout`): o que não cabe VAZA e a
          PÁGINA inteira rola. É o mesmo defeito e o mesmo conserto do #178 na `/vima`. */}
      <p className="break-words text-base font-medium text-neutral-800">{pergunta.texto}</p>
      <p className="mt-1 text-xs text-neutral-500">
        {pergunta.classe === "calibracao"
          ? "Isso muda o seu resumo a partir de amanhã."
          : "Fica guardado para a Vima te conhecer melhor."}
      </p>

      {pergunta.formato === "escolha" && (
        <div className="mt-3 space-y-2">
          {pergunta.opcoes.map((o) => (
            <button
              key={o.rotulo}
              type="button"
              disabled={salvando}
              onClick={() => responder(o.valor)}
              // `break-words`: o rótulo da opção vem do mesmo catálogo do servidor que o
              // `texto` acima. Medido no #208: as opções sozinhas valem 559px em 360.
              className="w-full break-words rounded-lg border border-neutral-200 px-4 py-3 text-left text-sm text-neutral-700 hover:border-neutral-400 disabled:opacity-50"
            >
              {o.rotulo}
            </button>
          ))}
        </div>
      )}

      {pergunta.formato === "escolha_multipla" && (
        <div className="mt-3 space-y-2">
          {pergunta.opcoes.map((o) => {
            const ativa = marcadas.includes(o.valor);
            return (
              <button
                key={o.rotulo}
                type="button"
                disabled={salvando}
                onClick={() =>
                  setMarcadas(
                    ativa ? marcadas.filter((v) => v !== o.valor) : [...marcadas, o.valor],
                  )
                }
                // `break-words` pelo mesmo motivo do ramo `escolha` acima (#208).
                className={`w-full break-words rounded-lg border px-4 py-3 text-left text-sm disabled:opacity-50 ${
                  ativa
                    ? "border-neutral-800 bg-neutral-800 text-white"
                    : "border-neutral-200 text-neutral-700 hover:border-neutral-400"
                }`}
              >
                {o.rotulo}
              </button>
            );
          })}
          <button
            type="button"
            disabled={salvando || marcadas.length === 0}
            onClick={() => responder(marcadas)}
            className="w-full rounded-lg bg-neutral-900 px-4 py-3 text-sm font-medium text-white disabled:opacity-40"
          >
            Confirmar
          </button>
        </div>
      )}

      {pergunta.formato === "texto" && (
        <div className="mt-3 space-y-2">
          <textarea
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            rows={3}
            maxLength={2000}
            className="w-full rounded-lg border border-neutral-200 p-3 text-sm text-neutral-700"
            placeholder="Escreva do seu jeito"
          />
          <button
            type="button"
            disabled={salvando || texto.trim() === ""}
            onClick={() => responder(texto.trim())}
            className="w-full rounded-lg bg-neutral-900 px-4 py-3 text-sm font-medium text-white disabled:opacity-40"
          >
            Salvar
          </button>
        </div>
      )}

      {erro && <p className="mt-2 text-xs text-red-600">{erro}</p>}

      <button
        type="button"
        disabled={salvando}
        onClick={pular}
        className="mt-3 text-xs text-neutral-400 underline disabled:opacity-50"
      >
        Responder depois
      </button>
    </div>
  );
}
