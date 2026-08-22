import type { Briefing, BriefingLinha, BriefingPreferences } from "@e1p/shared-types";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import { formatTime } from "../../lib/datetime";
import { useFuso } from "../../store/auth";
import GanchoDaVima from "../dna/GanchoDaVima";
import PreferenciasSection from "./PreferenciasSection";

/**
 * A tela do briefing — a porta de entrada do dia.
 *
 * **360px primeiro.** O dono lê isto no celular, de manhã, antes de sentar. Nenhuma largura fixa:
 * tudo em `max-w-prose` com padding responsivo, um alvo de toque por linha. Este repositório já
 * pagou caro por esquecer isso — o `AppShell` sem breakpoint fez uma conta real ser marcada como
 * paga sem o dono conseguir ver o checkbox (PR #56).
 *
 * A prosa vem primeiro e as linhas são APOIO. O texto é para ler; as linhas existem para conferir
 * um item sem reler o parágrafo inteiro.
 */
export default function BriefingPage() {
  const fuso = useFuso();
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [prefs, setPrefs] = useState<BriefingPreferences | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [verPrefs, setVerPrefs] = useState(false);
  // A marcação de leitura acontece UMA vez por montagem. Sem a trava, um re-render entre a
  // resposta do POST e a atualização do estado dispararia um segundo POST — e é `read_at` que
  // decide a janela do briefing de amanhã (`service._inicio_da_janela`).
  const marcado = useRef(false);

  const carregar = useCallback(async () => {
    try {
      const { data } = await api.get<Briefing>("/vima/briefing");
      setBriefing(data);
    } catch (err) {
      setErro(apiErrorMessage(err));
    }
    try {
      const { data } = await api.get<BriefingPreferences>("/auth/me/preferences");
      setPrefs(data);
    } catch {
      // Preferência é acessório: não poder carregá-la não pode esconder o briefing do dia.
      setPrefs(null);
    }
  }, []);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  useEffect(() => {
    if (!briefing || briefing.read_at || marcado.current) return;
    marcado.current = true;
    void api
      .post<Briefing>(`/vima/briefing/${briefing.id}/read`)
      .then(({ data }) => setBriefing(data))
      // Falhar em marcar como lido não pode derrubar a leitura: o pior efeito é a janela do
      // briefing de amanhã ficar mais larga, e ele repetir um item. Ruído, não perda.
      .catch(() => undefined);
  }, [briefing]);

  if (erro && !briefing) {
    return (
      <div className="mx-auto w-full max-w-prose">
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-danger">
          {erro}
        </p>
        <VoltarAoPainel />
      </div>
    );
  }

  if (!briefing) {
    return (
      <div className="mx-auto w-full max-w-prose py-10 text-center text-sm text-neutral-500">
        Preparando seu resumo…
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-prose pb-10">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-sm font-medium uppercase tracking-wide text-neutral-500">
          Seu dia
        </h1>
        <span className="text-xs text-neutral-400">{formatTime(briefing.created_at, fuso)}</span>
      </header>

      {/*
        A narração. Tipografia grande porque é o que se lê, não o que se consulta.

        `break-words` não é enfeite (#178): este texto repete nomes DIGITADOS pelo dono —
        fornecedor, título do prazo, nome da conversa (`vima/absences.py` monta o `title` da
        ausência com eles) — e um token sem espaço não tem onde quebrar. Medido em 360×740 com a
        fixture de pior caso: sem a classe, a PÁGINA INTEIRA rola até **649px**. E aqui não há
        `main.overflow-x-hidden` para recortar nada: `/vima` mora no `ProtectedBareLayout`
        (sem shell), então o que não cabe vaza para fora da tela em vez de ficar preso.
      */}
      <p className="mt-3 whitespace-pre-line break-words text-lg leading-relaxed text-neutral-800 sm:text-xl">
        {briefing.texto}
      </p>

      {/*
        Rastro da IA (Regra de Ouro nº 3) — e só quando foi a IA mesmo. Sem chave configurada o
        briefing sai íntegro pelo template, e rotular esse texto como escrito pela IA seria falso.
      */}
      {briefing.por_ia && (
        <p className="mt-2 text-xs text-neutral-400">Escrito pela IA a partir dos seus dados.</p>
      )}

      <Secoes linhas={briefing.linhas} excedente={briefing.excedente} />

      <VoltarAoPainel />

      <div className="mt-6 border-t border-neutral-200 pt-4">
        <button
          type="button"
          onClick={() => setVerPrefs((v) => !v)}
          className="text-sm text-neutral-500 underline underline-offset-2"
        >
          {verPrefs ? "Fechar preferências" : "Preferências do briefing"}
        </button>
        {verPrefs && prefs && (
          <PreferenciasSection prefs={prefs} onSaved={(p) => setPrefs(p)} />
        )}
      </div>
    </div>
  );
}

/** O caminho de volta é sempre visível — o briefing é porta de entrada, não pedágio. */
function VoltarAoPainel() {
  return (
    <Link
      to="/"
      className="mt-8 block w-full rounded-md bg-primary px-4 py-3 text-center text-base font-medium text-white"
    >
      Ir para o painel
    </Link>
  );
}

const TITULO_DA_SECAO: Record<string, string> = {
  PENDENTE: "Esperando você",
  ACONTECEU: "O que aconteceu",
  NÚMEROS: "Números",
};
// Mesma ordem do compositor (`vima/composer._ORDEM_DAS_SECOES`): ausência primeiro, porque pede
// ação; número por último, porque é contexto e não notícia.
const ORDEM = ["PENDENTE", "ACONTECEU", "NÚMEROS"];

/** O `kind` da primeira pendência com um — é nele que a pergunta de calibração se ancora. */
function primeiroKind(linhas: BriefingLinha[]): string | null {
  return linhas.find((l) => l.secao === "PENDENTE" && l.kind)?.kind ?? null;
}

function Secoes({ linhas, excedente }: { linhas: BriefingLinha[]; excedente: number }) {
  const presentes = ORDEM.filter((s) => linhas.some((l) => l.secao === s));
  if (presentes.length === 0) return null;
  return (
    <div className="mt-8 flex flex-col gap-6">
      {presentes.map((secao) => (
        <section key={secao}>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
            {TITULO_DA_SECAO[secao] ?? secao}
          </h2>
          <ul className="mt-2 flex flex-col gap-2">
            {linhas
              .filter((l) => l.secao === secao)
              .map((l, i) => (
                // `break-words` pela mesma razão do parágrafo da narração, e medida à parte:
                // só estas linhas, sem a classe, já levam a página a **525px** em 360 (#178).
                <li
                  key={`${secao}-${i}`}
                  className="break-words rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-700"
                >
                  {l.texto}
                </li>
              ))}
          </ul>
          {/* A pergunta de calibração vem colada à PRIMEIRA pendência da seção, e só ali: é o
              único instante em que "esse é o tempo certo para você?" é óbvia. O componente
              decide sozinho se aparece — a cadência mora no servidor. Linhas gravadas antes do
              V2 não têm `kind`, e sem ele não há gancho. */}
          {secao === "PENDENTE" && primeiroKind(linhas) && (
            <GanchoDaVima gancho={`briefing.ausencia.${primeiroKind(linhas)}`} />
          )}
        </section>
      ))}
      {excedente > 0 && (
        <p className="text-xs text-neutral-400">
          e mais {excedente} {excedente === 1 ? "item" : "itens"} de menor peso.
        </p>
      )}
    </div>
  );
}
