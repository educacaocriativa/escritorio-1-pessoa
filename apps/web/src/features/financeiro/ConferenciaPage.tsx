import { AlertTriangle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../lib/api";
import {
  avisoTotalParcial,
  avisoUltimaConferencia,
  type ConferenciaConta,
  type ConferenciaReport,
  fonteLabel,
  fraseConferencia,
  LADO_BANCO_LABEL,
  LADO_E1P_LABEL,
  LADOS_GRUPO_LABEL,
  ordenarContas,
  tomVisual,
} from "./conferencia";
import { formatBRL, formatDateBR, kindLabel, origemLabel } from "./contas";
import PeriodPicker from "./PeriodPicker";
import { type PeriodRange, resolvePeriod } from "./periodRange";

/**
 * **Conferência de saldos** (Story 8.7) — a tela que responde *"meu saldo bate?"*.
 *
 * ⚠️ **Esta rota NÃO está na sidebar, e isso é uma decisão de produto, não um esquecimento.**
 * O menu tem "Contas & Saldos" — *onde está o meu dinheiro*. Um item "Conciliação bancária"
 * comunicaria "software de contabilidade" para todo usuário, inclusive quem nunca abre a tela, e o
 * epic registra "produto virar ERP contábil e perder o público" como risco **existencial para a
 * tese**. Virar item de menu transformaria a conferência numa **obrigação periódica** — exatamente
 * o peso de ERP que este produto recusa. Ela é **resposta a um sinal**: chega-se aqui pelo cartão
 * de completude do `/financeiro/diagnostico` ou pela ação "Conferir" de uma conta.
 *
 * **A frase vem ANTES da tabela.** Primeiro o dono lê o que o número significa ("faltam R$ 2.340 na
 * conta Itaú PJ, provavelmente lançamentos de saída"); só depois, se a frase incomodar, ele desce
 * para a decomposição. A ordem inversa é uma planilha.
 *
 * **Dentro da banda: 🟢 e silêncio.** Nenhum ícone de alerta, nenhuma cor de erro, nenhum ponto de
 * exclamação. Gritar por R$ 3,50 num saldo de R$ 25.000 treina o usuário a ignorar o alerta — e o
 * alerta é o produto (REQ-16).
 *
 * **Os dois lados têm nomes próprios (UX-001).** `LADO_BANCO_LABEL` × `LADO_E1P_LABEL`, sob uma
 * legenda comum e numa faixa visual compartilhada. Esta tela **não** usa (e um teste garante que
 * não volta a usar) a string `"no banco"`: ela é o nome da parcela DERIVADA na Projeção de Caixa,
 * isto é, o lado oposto do que ela nomeava aqui.
 *
 * Read-only: `GET /bank/reconciliation-report`. Nada nesta tela escreve.
 */
export default function ConferenciaPage() {
  const [params] = useSearchParams();
  const accountId = params.get("account_id") ?? "";
  const [range, setRange] = useState<PeriodRange>(() => resolvePeriod("this_year"));
  const [report, setReport] = useState<ConferenciaReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await api.get<ConferenciaReport>("/bank/reconciliation-report", {
        params: {
          start: range.start,
          end: range.end,
          ...(accountId ? { bank_account_id: accountId } : {}),
        },
      });
      setReport(res.data);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [range.start, range.end, accountId]);

  useEffect(() => {
    load();
  }, [load]);

  const contas = useMemo(() => (report ? ordenarContas(report.contas) : []), [report]);
  const avisoParcial = useMemo(() => (report ? avisoTotalParcial(report) : null), [report]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Conferência</p>
          <h1 className="text-2xl font-bold text-neutral-800">Conferência de saldos</h1>
          {/* UX-001: a frase de abertura ENSINA o par de rótulos que a tabela usa, e diz de onde
              vem cada lado — o do banco é o que você leu no extrato; o do e1p é derivado dos
              lançamentos. Sem isso, "O que o banco diz" pareceria um número que o e1p buscou. */}
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Compara, conta por conta, o que o banco diz (o saldo que você declarou lendo o extrato)
            com o que o e1p calculou a partir dos seus lançamentos. Serve para achar lançamento
            faltando — não para fechar em zero.
          </p>
        </div>
        <PeriodPicker value={range} onChange={setRange} />
      </div>

      {accountId && (
        <p className="text-sm text-neutral-500">
          Conferindo apenas uma conta.{" "}
          <Link to="/financeiro/conferencia" className="font-medium text-primary-600 underline">
            Ver todas as contas
          </Link>
        </p>
      )}

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
      {loading && <p className="text-sm text-neutral-400">Conferindo…</p>}

      {report && report.contas.length === 0 && (
        <div className="rounded-2xl bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-neutral-500">
            Você ainda não tem conta bancária cadastrada — não há o que conferir.
          </p>
          <Link
            to="/financeiro/contas"
            className="mt-4 inline-block rounded-pill bg-accent-400 px-5 py-2 text-sm font-semibold text-white hover:bg-accent-500"
          >
            Cadastrar uma conta
          </Link>
        </div>
      )}

      {report && report.contas.length > 0 && (
        <>
          {/* 1) AS FRASES — uma por conta, antes de qualquer tabela. */}
          <ul className="space-y-3">
            {contas.map((c) => (
              <FraseCard key={c.bank_account_id} conta={c} />
            ))}
          </ul>

          {/* 2) O consolidado, SEMPRE depois da decomposição e nunca como veredito. */}
          <ConsolidadoCard report={report} aviso={avisoParcial} />

          {/* 3) O detalhamento. */}
          <TabelaContas contas={contas} />

          {report.notes.length > 0 && (
            <ul className="space-y-1 text-xs text-neutral-400">
              {report.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/**
 * A frase de uma conta. O tom vem de `fraseConferencia`; o ícone de alerta só aparece quando o
 * tom **autoriza** (`tomVisual().alerta`) — é assim que o AC5 fica difícil de quebrar por engano
 * num ajuste de estilo.
 */
function FraseCard({ conta }: { conta: ConferenciaConta }) {
  const frase = fraseConferencia(conta);
  const v = tomVisual(frase.tom);
  const abandono = avisoUltimaConferencia(conta);
  return (
    <li className={`flex items-start gap-3 rounded-2xl p-4 ${v.cardClass}`}>
      <span className="text-xl leading-none" aria-hidden="true">
        {v.emoji}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-neutral-800">{frase.texto}</p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-500">
          <span>{kindLabel(conta.bank_account_kind)}</span>
          {abandono && <span>{abandono}</span>}
          {conta.movimentos_ignorados > 0 && (
            <span>
              {conta.movimentos_ignorados}{" "}
              {conta.movimentos_ignorados === 1 ? "movimento ignorado" : "movimentos ignorados"} no
              período (fora do saldo)
            </span>
          )}
          {frase.tom === "desconhecido" && (
            <Link to="/financeiro/contas" className="font-medium text-primary-600 underline">
              Declarar o saldo desta conta
            </Link>
          )}
        </div>
      </div>
      {v.alerta && (
        <AlertTriangle
          size={18}
          className="mt-0.5 shrink-0 text-danger"
          aria-label="Divergência fora da tolerância"
        />
      )}
    </li>
  );
}

/**
 * O consolidado — que **nunca** é um veredito (epic §3.2, decisão do fundador F3).
 *
 * +R$ 1.200, −R$ 900 e +R$ 40 somam +R$ 340: parece saudável e esconde dois problemas. O número só
 * é exibido acompanhado da decomposição (as frases acima e a tabela abaixo, na mesma tela, sem
 * "expandir") e do aviso quando ele não cobre todas as contas.
 */
function ConsolidadoCard({
  report,
  aviso,
}: {
  report: ConferenciaReport;
  aviso: string | null;
}) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">
            Soma das divergências
          </p>
          <p className="mt-0.5 text-2xl font-bold tabular-nums text-neutral-800">
            {report.total_divergencia_cents === null
              ? "Não sei"
              : formatBRL(report.total_divergencia_cents)}
          </p>
        </div>
        <p className="text-xs text-neutral-500">
          {report.contas_avaliadas}{" "}
          {report.contas_avaliadas === 1 ? "conta conferida" : "contas conferidas"} ·{" "}
          {/* Story 8.20 — "não avaliada(s)": há dois motivos para a conta ficar fora do total
              (nenhum saldo informado × saldo informado na data de abertura), e afirmar aqui o
              primeiro seria falso para o segundo. O motivo está na nota de cada conta. */}
          {report.contas_sem_checkpoint}{" "}
          {report.contas_sem_checkpoint === 1 ? "não avaliada" : "não avaliadas"}
        </p>
      </div>
      <p className="mt-3 max-w-2xl text-xs text-neutral-500">
        Este número <strong>não é um veredito</strong>: contas que divergem em sentidos opostos se
        anulam nele. Uma soma perto de zero pode esconder duas contas com problema — a leitura que
        vale é conta por conta, acima.
      </p>
      {aviso && (
        <p className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">{aviso}</p>
      )}
    </div>
  );
}

/**
 * Classes das duas colunas do par (UX-001). A mesma faixa clara e as mesmas bordas laterais no
 * cabeçalho e em TODAS as células do corpo: é o que faz os dois lados serem lidos como **uma
 * comparação**, e não como duas colunas quaisquer entre sete. Tom neutro de propósito — cor
 * semântica nesta tela é reservada ao veredito (AC5: dentro da banda é 🟢 e silêncio).
 */
const PAR_CELL = "bg-neutral-50/70 border-x border-neutral-100";

/** Detalhamento por conta. `overflow-x-auto` (AC8) — cortar esconderia as colunas da direita. */
function TabelaContas({ contas }: { contas: ConferenciaConta[] }) {
  return (
    <div className="overflow-x-auto rounded-2xl bg-white shadow-sm">
      <table className="w-full min-w-[56rem] text-sm">
        <thead>
          {/* UX-001 — os dois lados sob uma legenda comum. A `Divergência` (coluna seguinte) é a
              subtração DESTE par; separá-los visualmente escondia essa relação. */}
          <tr className="text-left text-xs uppercase text-neutral-400">
            <th className="px-5 pt-3 font-medium" rowSpan={2} scope="col">
              Conta
            </th>
            <th
              className={`px-5 pt-3 pb-1 text-center text-[0.65rem] font-semibold tracking-wide text-neutral-500 ${PAR_CELL}`}
              colSpan={2}
              scope="colgroup"
            >
              {LADOS_GRUPO_LABEL}
            </th>
            <th className="px-5 pt-3 text-right font-medium" rowSpan={2} scope="col">
              Divergência
            </th>
            <th className="px-5 pt-3 text-right font-medium" rowSpan={2} scope="col">
              Tolerância
            </th>
            <th className="px-5 pt-3 font-medium" rowSpan={2} scope="col">
              Última conferência
            </th>
            <th className="px-5 pt-3 text-right font-medium" rowSpan={2} scope="col">
              Ignorados
            </th>
          </tr>
          <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
            <th className={`px-5 pb-2 text-right font-medium ${PAR_CELL}`} scope="col">
              {LADO_BANCO_LABEL}
            </th>
            <th className={`px-5 pb-2 text-right font-medium ${PAR_CELL}`} scope="col">
              {LADO_E1P_LABEL}
            </th>
          </tr>
        </thead>
        <tbody>
          {contas.map((c) => (
            <LinhaConta key={c.bank_account_id} conta={c} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LinhaConta({ conta: c }: { conta: ConferenciaConta }) {
  const avaliavel = c.divergencia_cents !== null;
  const foraDaBanda = c.dentro_da_tolerancia === false;
  return (
    <tr className="border-b border-neutral-50 align-top last:border-0">
      <td className="px-5 py-3">
        <p className="font-medium text-neutral-800">{c.bank_account_name}</p>
        <p className="text-xs text-neutral-400">{kindLabel(c.bank_account_kind)}</p>
      </td>
      {/* O par do UX-001 — mesma faixa do cabeçalho, para a comparação se ler linha a linha. */}
      <td className={`px-5 py-3 text-right ${PAR_CELL}`}>
        <p className="tabular-nums text-neutral-800">
          {c.saldo_banco_cents === null ? "Não sei" : formatBRL(c.saldo_banco_cents)}
        </p>
        {/* Os DOIS eixos, lado a lado e sem se misturarem: A = plano, B = porta de entrada. */}
        <p className="text-xs text-neutral-400">{origemLabel(c.saldo_banco_origem)}</p>
        {/* O eixo B qualifica o VALOR acima. Sem valor não há porta a nomear: a linha some, em vez
            de afirmar um motivo. O rótulo antigo dizia "sem saldo informado" também na conta que
            declarou o saldo na data de abertura (8.20) e na que tem saldo de partida do cadastro
            (8.19) — ver `fonteLabel`. */}
        {c.saldo_banco_fonte !== null && (
          <p className="text-xs text-neutral-400">{fonteLabel(c.saldo_banco_fonte)}</p>
        )}
        {c.saldo_banco_data && (
          <p className="text-xs text-neutral-400">em {formatDateBR(c.saldo_banco_data)}</p>
        )}
      </td>
      <td className={`px-5 py-3 text-right ${PAR_CELL}`}>
        <p className="tabular-nums text-neutral-800">
          {c.saldo_sistema_cents === null ? "Não sei" : formatBRL(c.saldo_sistema_cents)}
        </p>
        <p className="text-xs text-neutral-400">{origemLabel(c.saldo_sistema_origem)}</p>
      </td>
      <td
        className={`px-5 py-3 text-right tabular-nums font-medium ${
          foraDaBanda ? "text-danger" : "text-neutral-700"
        }`}
      >
        {avaliavel && c.divergencia_cents !== null ? formatBRL(c.divergencia_cents) : "—"}
      </td>
      <td className="px-5 py-3 text-right tabular-nums text-neutral-500">
        {avaliavel ? formatBRL(c.tolerancia_cents) : "—"}
      </td>
      <td className="px-5 py-3 text-xs text-neutral-500">
        {c.dias_desde_ultima_conferencia === null
          ? "Nunca"
          : c.dias_desde_ultima_conferencia === 0
            ? "Hoje"
            : `Há ${c.dias_desde_ultima_conferencia} dias`}
        {c.notes.length > 0 && (
          <span className="mt-1 block text-neutral-400">{c.notes.join(" ")}</span>
        )}
      </td>
      <td className="px-5 py-3 text-right tabular-nums text-neutral-500">
        {c.movimentos_ignorados}
      </td>
    </tr>
  );
}
