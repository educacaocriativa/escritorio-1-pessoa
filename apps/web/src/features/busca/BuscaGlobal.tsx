import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ROTULOS, itensEmSequencia } from "./resultado";
import { useBusca } from "./useBusca";

/** Espelha `MIN_CARACTERES` do backend — abaixo disto não há dropdown para mostrar. */
const MIN_CARACTERES = 2;

/**
 * A busca da barra de cima — camada rasa.
 *
 * Oito tipos, até 3 por grupo, agrupados na ordem que o backend manda. O objetivo aqui é "me leva
 * até a Ana" em uma tecla, sem ler nada. Procurar DENTRO de documento e mensagem é a página
 * `/busca`, e o rodapé (e o estado vazio) levam até ela.
 */
export default function BuscaGlobal() {
  const [termo, setTermo] = useState("");
  const [aberto, setAberto] = useState(false);
  const [foco, setFoco] = useState(-1); // -1 = nenhum item focado
  const campo = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { grupos, vazio } = useBusca(termo);
  const sequencia = itensEmSequencia(grupos); // o teclado ATRAVESSA grupos

  useEffect(() => {
    const atalho = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        campo.current?.focus();
      }
    };
    document.addEventListener("keydown", atalho);
    return () => document.removeEventListener("keydown", atalho);
  }, []);

  // O foco volta ao início a cada resultado novo. Manter o índice antigo apontaria para um item
  // que não está mais na lista, e o `Enter` abriria o registro errado — silenciosamente.
  useEffect(() => setFoco(-1), [grupos]);

  function irParaAPagina() {
    setAberto(false);
    navigate(`/busca?q=${encodeURIComponent(termo.trim())}`);
  }

  function abrir(rota: string) {
    setAberto(false);
    navigate(rota);
  }

  function noTeclado(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFoco((i) => Math.min(i + 1, sequencia.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFoco((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (foco >= 0 && sequencia[foco]) abrir(sequencia[foco].route);
      else irParaAPagina();
    } else if (e.key === "Escape") {
      setAberto(false);
      campo.current?.focus();
    }
  }

  const mostrando = aberto && termo.trim().length >= MIN_CARACTERES;
  let indice = -1; // numeração contínua entre grupos, para casar com `sequencia`

  return (
    <div
      className="relative hidden min-w-0 max-w-md flex-1 md:block"
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setAberto(false);
      }}
    >
      <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
      <input
        ref={campo}
        role="combobox"
        aria-expanded={mostrando}
        aria-controls="busca-resultados"
        aria-autocomplete="list"
        placeholder="Buscar cliente, contrato ou documento"
        value={termo}
        onChange={(e) => {
          setTermo(e.target.value);
          setAberto(true);
        }}
        onFocus={() => setAberto(true)}
        onKeyDown={noTeclado}
        className="w-full rounded-pill bg-neutral-50 py-2 pl-9 pr-4 text-sm outline-none focus:ring-2 focus:ring-primary-300"
      />

      {mostrando && (
        <div
          id="busca-resultados"
          role="listbox"
          className="absolute z-20 mt-1 max-h-96 w-full overflow-y-auto rounded-2xl border border-neutral-100 bg-white py-1 shadow-lg"
        >
          {grupos.map((g) => (
            <div key={g.type}>
              <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">
                {ROTULOS[g.type]}
              </p>
              {g.items.map((item) => {
                indice += 1;
                const meu = indice;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="option"
                    aria-selected={foco === meu}
                    // `onMouseDown` e não `onClick`: o `onBlur` do contêiner fecha o dropdown
                    // antes que um `click` chegue a disparar, e o item simplesmente não abriria.
                    onMouseDown={() => abrir(item.route)}
                    className={`flex w-full flex-col px-3 py-2 text-left text-sm ${
                      foco === meu ? "bg-primary-50" : "hover:bg-neutral-50"
                    }`}
                  >
                    <span className="truncate">{item.title}</span>
                    {item.subtitle && (
                      <span className="truncate text-xs text-neutral-400">{item.subtitle}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}

          {vazio ? (
            <div className="px-3 py-3 text-sm text-neutral-500">
              Nada encontrado para «{termo.trim()}».{" "}
              <button
                type="button"
                onMouseDown={irParaAPagina}
                className="text-primary-600 underline"
              >
                procurar em documentos e mensagens
              </button>
            </div>
          ) : (
            grupos.length > 0 && (
              <button
                type="button"
                onMouseDown={irParaAPagina}
                className="mt-1 w-full border-t border-neutral-100 px-3 py-2 text-left text-xs text-primary-600"
              >
                ver todos os resultados
              </button>
            )
          )}
        </div>
      )}
    </div>
  );
}
