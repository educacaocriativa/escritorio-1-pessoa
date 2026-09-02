import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { CONTROLADOR, VIGENCIA } from "./controlador";

/**
 * Moldura das duas páginas legais (`/privacidade` e `/termos`).
 *
 * São PÚBLICAS por obrigação, não por conveniência: o Google exige que o link da Política de
 * Privacidade abra sem login para publicar o app OAuth (ver `docs/GO-LIVE-CHECKLIST.md` §5).
 * Por isso ficam fora do `ProtectedLayout` e não tocam em `useAuth` — uma pessoa que nunca
 * teve conta precisa conseguir ler.
 */
export default function LegalLayout({
  titulo,
  subtitulo,
  outroDocumento,
  children,
}: {
  titulo: string;
  subtitulo: string;
  /** Link cruzado para o documento irmão: quem lê um quase sempre quer o outro. */
  outroDocumento: { to: string; label: string };
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-neutral-50">
      <header className="border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-4">
          <Link to="/login" className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-500 font-bold text-white">
              e1
            </div>
            <span className="text-xl font-bold text-neutral-800">e1p</span>
          </Link>
          <Link to={outroDocumento.to} className="text-sm text-primary-600 hover:underline">
            {outroDocumento.label}
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-2xl font-bold text-neutral-800 sm:text-3xl">{titulo}</h1>
        <p className="mt-2 text-sm text-neutral-500">{subtitulo}</p>
        <p className="mt-1 text-sm text-neutral-500">Última atualização: {VIGENCIA}.</p>

        <article className="mt-8 space-y-8">{children}</article>

        <footer className="mt-12 border-t border-neutral-200 pt-6 text-xs text-neutral-500">
          <p>
            {CONTROLADOR.razaoSocial} — CNPJ {CONTROLADOR.cnpj}. Contato:{" "}
            <a className="text-primary-600 hover:underline" href={`mailto:${CONTROLADOR.email}`}>
              {CONTROLADOR.email}
            </a>
            .
          </p>
          <p className="mt-2">
            <Link to={outroDocumento.to} className="text-primary-600 hover:underline">
              {outroDocumento.label}
            </Link>
            {" · "}
            <Link to="/login" className="text-primary-600 hover:underline">
              Entrar no e1p
            </Link>
          </p>
        </footer>
      </main>
    </div>
  );
}

/** Seção numerada. O `id` permite citar um trecho específico por link (`/termos#responsabilidades`). */
export function Secao({ id, titulo, children }: { id: string; titulo: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-4">
      <h2 className="text-lg font-bold text-neutral-800">{titulo}</h2>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-neutral-700">{children}</div>
    </section>
  );
}

/** Lista de itens do corpo de uma seção. */
export function Lista({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-2 pl-5">{children}</ul>;
}

/**
 * Tabela de um documento legal. `overflow-x-auto` porque a tela mais estreita suportada é 360px
 * e uma tabela de 3 colunas não cabe nela — rolar a tabela é melhor que rolar a página inteira.
 */
export function Tabela({ cabecalho, linhas }: { cabecalho: string[]; linhas: string[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[32rem] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-neutral-300">
            {cabecalho.map((c) => (
              <th key={c} className="py-2 pr-4 font-semibold text-neutral-800">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {linhas.map((linha) => (
            <tr key={linha.join("|")} className="border-b border-neutral-200 align-top">
              {linha.map((celula, i) => (
                <td key={i} className="py-2 pr-4 text-neutral-700">
                  {celula}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
