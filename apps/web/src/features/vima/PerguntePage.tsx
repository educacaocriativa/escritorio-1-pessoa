import { Send } from "lucide-react";
import { useState } from "react";
import type { PerguntaResposta, Turno } from "@e1p/shared-types";
import { api, apiErrorMessage } from "../../lib/api";

interface Mensagem {
  papel: "usuario" | "vima";
  texto: string;
}

export default function PerguntePage() {
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [texto, setTexto] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function enviar() {
    const pergunta = texto.trim();
    if (!pergunta || carregando) return;

    const historico: Turno[] = mensagens.map((m) => ({ papel: m.papel, texto: m.texto }));
    setTexto("");
    setErro(null);
    setMensagens((atual) => [...atual, { papel: "usuario", texto: pergunta }]);
    setCarregando(true);
    try {
      const { data } = await api.post<PerguntaResposta>("/vima/pergunta", {
        texto: pergunta,
        historico,
      });
      setMensagens((atual) => [...atual, { papel: "vima", texto: data.resposta }]);
    } catch (err) {
      setErro(apiErrorMessage(err));
    } finally {
      setCarregando(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <h1 className="mb-3 shrink-0 text-lg font-semibold text-neutral-900">Pergunte à Vima</h1>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-lg border border-neutral-200 bg-white p-3">
        {mensagens.length === 0 && (
          <p className="text-sm text-neutral-400">
            Pergunte sobre o que você tem a receber, a pagar, sua agenda ou um cliente.
          </p>
        )}
        {mensagens.map((m, i) => (
          <div
            key={i}
            className={`max-w-[85%] min-w-0 break-words rounded-xl px-3 py-2 text-sm ${
              m.papel === "usuario"
                ? "ml-auto bg-primary-600 text-white"
                : "mr-auto bg-neutral-100 text-neutral-800"
            }`}
          >
            <p className="whitespace-pre-wrap">{m.texto}</p>
          </div>
        ))}
        {carregando && (
          <div className="mr-auto max-w-[85%] rounded-xl bg-neutral-100 px-3 py-2 text-sm text-neutral-400">
            Consultando...
          </div>
        )}
      </div>
      {erro && <p className="mt-2 shrink-0 text-sm text-red-600">{erro}</p>}
      <div className="mt-3 flex shrink-0 gap-2">
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && enviar()}
          placeholder="Digite sua pergunta..."
          className="min-h-[44px] min-w-0 flex-1 rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
        />
        <button
          onClick={enviar}
          disabled={carregando}
          className="flex min-h-[44px] min-w-[44px] shrink-0 items-center justify-center rounded-pill bg-primary-600 p-2 text-white hover:bg-primary-700 disabled:opacity-50"
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}
