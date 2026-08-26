import type { Payable, PaymentQueue } from "@e1p/shared-types";
import {
  AlertTriangle,
  CalendarCheck,
  CalendarClock,
  CalendarDays,
  CalendarRange,
  Check,
  Copy,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { api, apiErrorMessage } from "../../lib/api";
import { DialogDeBaixa } from "../pagar/EscolhaDaBaixa";
import { formatDay } from "../../lib/datetime";
import { formatBRL } from "./dre";

/**
 * Fila de Pagamentos (Story 5.9) — painel único do que pagar hoje e nos próximos dias, com baixa
 * direto daqui. É uma VISÃO nova sobre `Payable` (o mesmo dado de Contas a Pagar): a baixa chama o
 * `mark_paid` já existente, então reflete na tela de Contas a Pagar (mesmo registro, sem duplicar).
 * Sem papéis/permissão nova — qualquer usuário do módulo financeiro vê e paga (AC3).
 *
 * ⚠️ **Story 8.13 — esta tela deixou de pagar "em um clique", e não foi escolha de UX.** A partir da
 * 8.12 `POST /payables/bills/{id}/pay` **exige corpo** (a conta bancária de onde o dinheiro saiu e
 * o dia), e a chamada sem corpo que existia aqui passou a devolver 422: **a Fila ficava quebrada**.
 * Ela não é nomeada em nenhum documento da Onda 2 — foi encontrada por grep de
 * `bills/{id}/pay` — e entrou na 8.13 porque a Integration Verification da onda exige a Fila
 * **intacta**, e "intacta" não é compatível com "quebrada".
 *
 * O fluxo é o MESMO das outras duas telas de baixa, pelo mesmo componente (`DialogDeBaixa`): três
 * cópias divergiriam no primeiro ajuste — e o primeiro já aconteceu (a 8.14 tirou o teto de data,
 * nas três telas de uma vez, sem editar nenhuma delas).
 *
 * ⚠️ **Story 8.14 — o QUINTO balde, "Agendadas".** Uma conta com débito já marcado sai dos quatro
 * baldes de VENCIMENTO (a pergunta deles é *"o que eu preciso pagar?"*, e ela já foi resolvida) e
 * aparece num balde próprio, ordenado pela **data do débito**. **Esconder é erro; misturar
 * também**: sem este balde, uma saída certa de R$ 5.000 sumiria da única tela que responde *"o que
 * sai do meu caixa nos próximos dias"*. Os quatro baldes antigos e os oito campos antigos do
 * `PaymentQueueSummary` **não mudaram de definição** e continuam calculados na leitura.
 */

const EMPTY: PaymentQueue = {
  atrasados: [],
  hoje: [],
  proximos_7_dias: [],
  proximos_30_dias: [],
  summary: {
    atrasados_count: 0,
    atrasados_cents: 0,
    hoje_count: 0,
    hoje_cents: 0,
    proximos_7_dias_count: 0,
    proximos_7_dias_cents: 0,
    proximos_30_dias_count: 0,
    proximos_30_dias_cents: 0,
    agendadas_count: 0,
    agendadas_cents: 0,
  },
  agendadas: [],
};

export default function FilaPagamentosPage() {
  const [queue, setQueue] = useState<PaymentQueue>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // A conta cuja baixa está sendo confirmada (Story 8.13) — antes disso o clique já pagava.
  const [pagando, setPagando] = useState<Payable | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<PaymentQueue>("/payables/queue");
      // Guarda de FORMA (issue #247): `{...EMPTY, ...data}` só cobre um CAMPO AUSENTE (o spread de
      // `data` não sobrescreve a chave que falta) — mas um campo PRESENTE com o tipo errado (ex.:
      // `atrasados: null`, ou um objeto sem `.length`) SOBRESCREVE o default do `EMPTY` e
      // `queue.atrasados.length` (linha ~106) estoura no render. `Array.isArray` por campo, no
      // molde de `CrmPage.tsx` (#225), fecha essa segunda metade; `summary` usa o mesmo TIPO de
      // guarda das telas de resumo escalar (`EMPTY.summary` como fallback).
      setQueue({
        ...EMPTY,
        ...data,
        atrasados: Array.isArray(data?.atrasados) ? data.atrasados : EMPTY.atrasados,
        hoje: Array.isArray(data?.hoje) ? data.hoje : EMPTY.hoje,
        proximos_7_dias: Array.isArray(data?.proximos_7_dias)
          ? data.proximos_7_dias
          : EMPTY.proximos_7_dias,
        proximos_30_dias: Array.isArray(data?.proximos_30_dias)
          ? data.proximos_30_dias
          : EMPTY.proximos_30_dias,
        agendadas: Array.isArray(data?.agendadas) ? data.agendadas : EMPTY.agendadas,
        summary:
          data?.summary && typeof data.summary === "object" && !Array.isArray(data.summary)
            ? { ...EMPTY.summary, ...data.summary }
            : EMPTY.summary,
      });
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Reusa o mesmo endpoint de Contas a Pagar (mark_paid, lock FOR UPDATE) — mesmo registro, mesma
  // baixa. O corpo obrigatório (conta bancária + dia) vem do `DialogDeBaixa`, que é o MESMO
  // componente das outras duas telas, inclusive no 409 acionável → cadastro embutido → retoma.
  const pay = useCallback(
    async (id: string, corpo: { bank_account_id: string; paid_on: string }) => {
      await api.post(`/payables/bills/${id}/pay`, corpo);
      setPagando(null);
      await load();
    },
    [load],
  );

  const s = queue.summary;
  // ⚠️ O agendado fica FORA do "total pendente" de propósito: ele não é pendência — já foi
  // resolvido. Somá-lo aqui devolveria à tela exatamente a mistura que o balde próprio desfaz.
  const totalPendente =
    s.atrasados_cents + s.hoje_cents + s.proximos_7_dias_cents + s.proximos_30_dias_cents;
  const agendadas = queue.agendadas ?? [];
  const nada =
    !loading &&
    queue.atrasados.length === 0 &&
    queue.hoje.length === 0 &&
    queue.proximos_7_dias.length === 0 &&
    queue.proximos_30_dias.length === 0 &&
    agendadas.length === 0;

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Financeiro / Fila de pagamentos</p>
        <h1 className="text-2xl font-bold text-neutral-800">Fila de pagamentos</h1>
        <p className="mt-1 max-w-2xl text-sm text-neutral-500">
          O que pagar hoje e nos próximos dias, tudo junto — a baixa pergunta de qual conta o
          dinheiro saiu e em que dia. É o mesmo dado de Contas a Pagar: marcar pago aqui reflete lá.
        </p>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Atrasados" value={formatBRL(s.atrasados_cents)} count={s.atrasados_count} tone="text-danger" />
        <Stat label="Hoje" value={formatBRL(s.hoje_cents)} count={s.hoje_count} tone="text-amber-700" />
        <Stat label="Próximos 7 dias" value={formatBRL(s.proximos_7_dias_cents)} count={s.proximos_7_dias_count} tone="text-neutral-700" />
        <Stat label="Próximos 30 dias" value={formatBRL(s.proximos_30_dias_cents)} count={s.proximos_30_dias_count} tone="text-neutral-700" />
      </div>

      {loading && <p className="text-sm text-neutral-400">Carregando fila…</p>}

      {nada && (
        <div className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">
          Nada a pagar nos próximos 30 dias. 🎉
        </div>
      )}

      {!loading && !nada && (
        <div className="space-y-5">
          <Bucket
            title="Atrasados"
            hint="venceram e seguem em aberto"
            icon={<AlertTriangle size={16} className="text-danger" />}
            items={queue.atrasados}
            onPay={setPagando}
          />
          <Bucket
            title="Hoje"
            hint="vencem hoje"
            icon={<CalendarDays size={16} className="text-amber-600" />}
            items={queue.hoje}
            onPay={setPagando}
          />
          <Bucket
            title="Próximos 7 dias"
            hint="vencem nesta semana"
            icon={<CalendarClock size={16} className="text-primary-500" />}
            items={queue.proximos_7_dias}
            onPay={setPagando}
          />
          <Bucket
            title="Próximos 30 dias"
            hint="vencem no mês"
            icon={<CalendarRange size={16} className="text-neutral-500" />}
            items={queue.proximos_30_dias}
            onPay={setPagando}
          />
          {/* Sem `onPay`: a conta já foi resolvida, e oferecer "Marcar pago" aqui convidaria a uma
              segunda baixa do mesmo dinheiro. Para desfazer, o gesto é "Cancelar agendamento", em
              Contas a Pagar — um lugar só para a ação destrutiva. */}
          <Bucket
            title="Agendadas"
            hint="o débito já tem dia marcado — o dinheiro ainda não saiu"
            icon={<CalendarCheck size={16} className="text-sky-600" />}
            items={agendadas}
          />
        </div>
      )}

      {!nada && (
        <p className="text-right text-xs text-neutral-400">
          Total pendente na fila (30 dias): <strong>{formatBRL(totalPendente)}</strong>
        </p>
      )}

      {pagando && (
        <DialogDeBaixa
          titulo="Dar baixa nesta conta"
          descricao={pagando.description || pagando.supplier || "Conta"}
          valor={`${formatBRL(pagando.amount_cents)} · vence ${formatDay(pagando.due_date)}`}
          dataPadrao={pagando.due_date}
          onClose={() => setPagando(null)}
          onPago={(corpo) => pay(pagando.id, corpo)}
        />
      )}
    </div>
  );
}

function Bucket({
  title,
  hint,
  icon,
  items,
  onPay,
}: {
  title: string;
  hint: string;
  icon: ReactNode;
  items: Payable[];
  /**
   * Abre a confirmação da baixa — o clique deixou de cometer a ação na Story 8.13.
   *
   * **Opcional desde a 8.14:** o balde "Agendadas" não oferece baixa (a conta já foi resolvida),
   * e a ausência do botão é a informação — não um estado desabilitado a explicar.
   */
  onPay?: (p: Payable) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-neutral-100 px-4 py-3">
        {icon}
        <h2 className="font-semibold text-neutral-800">{title}</h2>
        <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
          {items.length}
        </span>
        <span className="text-xs text-neutral-400">— {hint}</span>
      </div>
      <ul className="divide-y divide-neutral-50">
        {items.map((p) => (
          <li
            key={p.id}
            // `flex-wrap` (auditoria de ~360px, AC9): sem ele, valor + copiar + o botão de baixa
            // somam mais que a largura útil de um celular e o botão sai da área visível — o mesmo
            // defeito que os PRs #56/#58 pagaram duas vezes, aqui pela ponta da linha.
            className="flex flex-wrap items-center gap-3 px-4 py-3"
          >
            {/* `basis-full sm:basis-0` (aceite físico do AC9, 2026-08-06): o `flex-wrap` acima
                sozinho NÃO quebrava a linha. Com base 0 e `min-w-0`, a descrição encolhia até
                caber no que sobrasse de valor + botão — 29px num aparelho de 360px — e o nome da
                conta empilhava uma palavra por linha, 300px de altura, com o valor colidindo no
                meio. Base 100% obriga a descrição a tomar a primeira linha e joga valor + botão
                para a segunda; do `sm` para cima volta a dividir a linha, como no desktop.
                `grow` no lugar de `flex-1` de propósito: o shorthand `flex` reintroduziria
                `flex-basis: 0%` e desfaria isto conforme a ordem das regras do Tailwind. */}
            <div className="min-w-0 grow basis-full sm:basis-0">
              <span className="text-neutral-800">{p.description || p.supplier || "Conta"}</span>
              <span className="block text-xs text-neutral-400">
                {p.supplier ? `${p.supplier} · ` : ""}
                vence {formatDay(p.due_date)}
              </span>
            </div>
            <span className="shrink-0 font-medium tabular-nums text-neutral-800">
              {formatBRL(p.amount_cents)}
            </span>
            {p.payment_code && (
              <button
                title="Copiar código do boleto/Pix"
                onClick={() => navigator.clipboard?.writeText(p.payment_code)}
                className="shrink-0 text-neutral-400 hover:text-primary-600"
              >
                <Copy size={14} />
              </button>
            )}
            {onPay ? (
              <button
                onClick={() => onPay(p)}
                className="flex shrink-0 items-center gap-1.5 rounded-pill bg-accent-400 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
              >
                <Check size={13} />
                Marcar pago
              </button>
            ) : (
              // A data do DÉBITO, não o vencimento: numa agendada as duas divergem por construção.
              p.paid_at && (
                <span className="shrink-0 text-xs font-medium text-sky-700">
                  sai {formatDay(p.paid_at)}
                </span>
              )
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Stat({
  label,
  value,
  count,
  tone,
}: {
  label: string;
  value: string;
  count: number;
  tone: string;
}) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
      <p className="text-xs text-neutral-400">{count} {count === 1 ? "conta" : "contas"}</p>
    </div>
  );
}
