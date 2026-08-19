import { Search } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { ROTULOS } from "./resultado";
import { useBusca } from "./useBusca";

/** `0` = sem recorte. Só afeta mensagens — ver a spec §6.2. */
const RECORTES = [
  { valor: 3, rotulo: "3 meses" },
  { valor: 12, rotulo: "12 meses" },
  { valor: 0, rotulo: "tudo" },
];

/**
 * A página de resultados — camada funda.
 *
 * Aqui a busca lê o CORPO: documento jurídico, notas de cliente e orçamento, e o texto das
 * mensagens do WhatsApp. Custa 150-270 ms sobre volume real, e isso não melhora com índice: sob
 * RLS o Postgres não usa trigrama nem tsvector para `ILIKE` (spec §5). A única alavanca é quantas
 * linhas se varre — daí o recorte, que é anunciado em vez de escondido.
 */
export default function BuscaPage() {
  const [params, setParams] = useSearchParams();
  const termo = params.get("q") ?? "";
  const meses = Number(params.get("months") ?? 12);
  const { grupos, carregando, vazio } = useBusca(termo, {
    profundidade: "deep",
    meses,
    limite: 20,
  });

  function trocar(chave: string, valor: string) {
    const novo = new URLSearchParams(params);
    if (valor) novo.set(chave, valor);
    else novo.delete(chave);
    // `replace`: uma entrada de histórico por tecla digitada encheria o botão "voltar" de
    // estados intermediários que ninguém quer revisitar.
    setParams(novo, { replace: true });
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6">
      <h1 className="mb-4 text-xl font-semibold">Busca</h1>

      <div className="relative mb-3">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400" />
        <input
          type="search"
          value={termo}
          onChange={(e) => trocar("q", e.target.value)}
          placeholder="Buscar em tudo, inclusive documentos e mensagens"
          className="w-full rounded-pill bg-neutral-50 py-3 pl-9 pr-4 text-sm outline-none focus:ring-2 focus:ring-primary-300"
        />
      </div>

      <label className="mb-5 flex flex-wrap items-center gap-2 text-sm text-neutral-500">
        {/* O rótulo NOMEIA o que é cortado. Dizer só "últimos 12 meses" faria o dono achar que a
            petição de dois anos atrás também ficou de fora — e ela não fica. */}
        <span>mensagens dos últimos</span>
        <select
          value={meses}
          onChange={(e) => trocar("months", e.target.value)}
          className="rounded-pill border border-neutral-200 bg-white px-3 py-1 text-sm"
        >
          {RECORTES.map((r) => (
            <option key={r.valor} value={r.valor}>
              {r.rotulo}
            </option>
          ))}
        </select>
        <span className="text-neutral-400">— documentos e cadastros não têm recorte de data</span>
      </label>

      {carregando && <p className="text-sm text-neutral-400">procurando…</p>}

      {vazio && (
        <p className="text-sm text-neutral-500">
          Nada encontrado para «{termo.trim()}»
          {meses > 0 && " nas mensagens do período escolhido"}.{" "}
          {meses > 0 && (
            <button
              type="button"
              onClick={() => trocar("months", "0")}
              className="text-primary-600 underline"
            >
              procurar em todo o histórico
            </button>
          )}
        </p>
      )}

      <div className="flex flex-col gap-6">
        {grupos.map((g) => (
          <section key={g.type}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">
              {/* A contagem é EXATA aqui: é ela que impede o recorte de ser silencioso. */}
              {ROTULOS[g.type]} ({g.total ?? g.items.length})
            </h2>
            <ul className="flex flex-col gap-1">
              {g.items.map((item) => (
                <li key={item.id}>
                  <Link
                    to={item.route}
                    className="flex flex-col rounded-2xl px-3 py-2 hover:bg-neutral-50"
                  >
                    <span className="text-sm font-medium">{item.title}</span>
                    {item.subtitle && (
                      <span className="text-xs text-neutral-400">{item.subtitle}</span>
                    )}
                    {item.snippet && (
                      <span className="mt-1 break-words text-xs text-neutral-500">
                        {item.snippet}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
            {g.has_more && (
              <p className="px-3 pt-1 text-xs text-neutral-400">
                mostrando {g.items.length} de {g.total ?? g.items.length}
              </p>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
