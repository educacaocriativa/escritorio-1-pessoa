import type { Contract, Payable, PayablesPage, PayablesSummary } from "@e1p/shared-types";
import { Copy, Paperclip } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Attachments from "../../components/Attachments";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import GanchoDaVima from "../dna/GanchoDaVima";
import { usePrimaryAction } from "../../store/pageActions";
import ChartAccountSelect from "../financeiro/ChartAccountSelect";
import type { CostCenter } from "../financeiro/costCenters";
import CostCenterSelect from "../financeiro/CostCenterSelect";
import { type ChartAccount, GRUPOS_DRE } from "../financeiro/planoContas";
import { DialogDeBaixa } from "./EscolhaDaBaixa";
import FiltrosDaLista from "./FiltrosDaLista";
import { camposDaCopia, type CamposDaConta } from "./duplicar";
import { formatDay, today } from "../../lib/datetime";
import { useFuso } from "../../store/auth";
import { apenasTexto, daUrl, type FiltroPagar, filtroPadrao, paraQuery, paraUrl } from "./filtros";
import { formatBRL } from "../financeiro/dre";

/** Grupos DRE cabíveis numa DESPESA (Contas a Pagar nunca lança em Receita). */
const EXPENSE_GROUPS = GRUPOS_DRE.filter((g) => g !== "RECEITA");

/** Tamanho da página. 50 cabe numa rolagem curta e mantém o "carregar mais" barato. */
const PAGINA = 50;

/** Seletor "Vincular a contrato" (Story 5.4) — opcional; vazio = bucket "Empresa" (overhead). */
function ContractSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [contracts, setContracts] = useState<Contract[]>([]);
  useEffect(() => {
    api.get<Contract[]>("/contracts").then((r) => setContracts(r.data)).catch(() => setContracts([]));
  }, []);
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">
        Vincular a contrato (opcional)
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
      >
        <option value="">Empresa (sem contrato)</option>
        {contracts.map((c) => (
          <option key={c.id} value={c.id}>
            {c.title}
            {c.client_name ? ` — ${c.client_name}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

const RECUR = [
  ["none", "Não repete"],
  ["weekly", "Semanal"],
  ["monthly", "Mensal"],
  ["yearly", "Anual"],
] as const;

/** "2026-08-20T00:00:00Z" → "20/08". Fatiamento de string, nunca `new Date` (bug de fuso §6.0). */
function diaDoDebito(paidAt: string | null): string {
  if (!paidAt) return "";
  const [, mes, dia] = paidAt.slice(0, 10).split("-");
  return dia && mes ? `${dia}/${mes}` : "";
}

function statusInfo(p: Payable): { label: string; cls: string } {
  if (p.status === "paid") return { label: "Pago", cls: "bg-accent-50 text-accent-700" };
  // ⚠️ **[Story 8.14] `scheduled` tem RÓTULO PRÓPRIO — não é "Pago" nem "A pagar".**
  //
  // Mostrá-la como "Pago" diria que o dinheiro saiu (não saiu); como "A pagar", pediria uma ação
  // que o dono já tomou. O estado existe justamente porque não cabe em nenhum dos dois, e o rótulo
  // tem de refletir isso. A **data do débito** vai junto (ver a coluna Status), porque a pergunta
  // seguinte do dono é sempre *"em que dia sai?"* — e essa data não é o vencimento.
  if (p.status === "scheduled") return { label: "Agendada", cls: "bg-sky-50 text-sky-700" };
  if (p.status === "canceled") return { label: "Cancelado", cls: "bg-neutral-100 text-neutral-500" };
  if (p.is_overdue) return { label: "Atrasado", cls: "bg-red-50 text-danger" };
  return { label: "A pagar", cls: "bg-amber-50 text-amber-700" };
}

export default function PagarPage() {
  const empty: PayablesSummary = {
    open_cents: 0,
    overdue_cents: 0,
    week_cents: 0,
    month_cents: 0,
    paid_month_cents: 0,
    // Story 8.14 — o resumo ganhou o campo; os cinco antigos não mudaram de definição.
    scheduled_cents: 0,
  };
  const [summary, setSummary] = useState<PayablesSummary>(empty);
  const [bills, setBills] = useState<Payable[]>([]);
  const [chartAccounts, setChartAccounts] = useState<ChartAccount[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [open, setOpen] = useState(false);
  const [attach, setAttach] = useState<Payable | null>(null);
  const [edit, setEdit] = useState<Payable | null>(null);
  // A conta que está sendo duplicada. `null` = o formulário de "Nova conta" nasce em branco.
  const [duplicando, setDuplicando] = useState<Payable | null>(null);
  // A conta cuja baixa está sendo confirmada (Story 8.13): "Marcar paga" deixou de ser um clique
  // que comete a ação e passou a abrir a escolha de conta bancária + dia.
  const [pagando, setPagando] = useState<Payable | null>(null);
  // Comprovantes que chegaram pelo celular e ainda não foram vinculados a nenhuma conta.
  const [inbox, setInbox] = useState<{ id: string }[]>([]);
  const fuso = useFuso();
  // ⚠️ **O recorte mora na URL, não em `useState` (#138).** Enquanto ele era estado de React,
  // `/pagar?q=anthropic` era um endereço INERTE (parecia filtrar e não filtrava), F5 apagava o
  // recorte, não havia link para mandar a outra pessoa, e "voltar" saía da tela inteira em vez de
  // desfazer o filtro — porque filtrar nunca criava entrada no histórico. Mesmo padrão de
  // `busca/BuscaPage.tsx`: a barra de endereço é a ÚNICA fonte da verdade, então o botão "voltar"
  // do navegador funciona de graça (ele muda `location.search`, e a lista rerenderiza).
  const [params, setParams] = useSearchParams();
  const padrao = useMemo(() => filtroPadrao(today(fuso)), [fuso]);
  const filtro = useMemo(() => daUrl(params, padrao), [params, padrao]);

  const trocarFiltro = useCallback(
    (novo: FiltroPagar) => {
      // `replace` só quando NADA além do texto mudou: uma entrada de histórico por tecla digitada
      // encheria o "voltar" de estados intermediários. Trocar status ou aplicar período é gesto
      // deliberado e EMPILHA — é ele que dá ao botão "voltar" o que desfazer.
      setParams(paraUrl(novo, padrao), { replace: apenasTexto(filtro, novo) });
    },
    [filtro, padrao, setParams],
  );
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [carregando, setCarregando] = useState(false);

  const load = useCallback(async (proximoOffset = 0) => {
    setCarregando(true);
    let b: { data: PayablesPage };
    try {
      const [s, pagina] = await Promise.all([
        api.get<PayablesSummary>("/payables/summary"),
        api.get<PayablesPage>("/payables/bills", {
          params: paraQuery(filtro, PAGINA, proximoOffset),
        }),
      ]);
      b = pagina;
      setSummary(s.data);
    } finally {
      setCarregando(false);
    }
    // `proximoOffset > 0` é "carregar mais": ANEXA. Substituir aqui é o erro clássico de
    // paginação, e ele passa despercebido porque a primeira página sempre parece certa.
    setBills((antes) => (proximoOffset === 0 ? b.data.items : [...antes, ...b.data.items]));
    setTotal(b.data.total);
    setOffset(proximoOffset);
    // Rótulos são só um complemento de exibição — se o usuário não tiver acesso a esses módulos
    // (require_module), a lista de contas a pagar continua funcionando normalmente.
    const [ca, cc] = await Promise.all([
      api.get<ChartAccount[]>("/chart-of-accounts").catch(() => ({ data: [] as ChartAccount[] })),
      api.get<CostCenter[]>("/cost-centers").catch(() => ({ data: [] as CostCenter[] })),
    ]);
    setChartAccounts(ca.data);
    setCostCenters(cc.data);
    // .catch: a bandeja é um extra da tela; se falhar, Contas a Pagar continua funcionando.
    const pend = await api
      .get<{ id: string }[]>("/payables/receipts")
      .catch(() => ({ data: [] as { id: string }[] }));
    setInbox(pend.data);
  }, [filtro]);

  useEffect(() => {
    let vivo = true;
    // Um filtro de texto sem debounce dispara uma chamada por tecla; `vivo` descarta a resposta de
    // um recorte que o usuário já abandonou e evita a lista "piscar" com dado velho. Mesmo padrão
    // de `AccountModal.tsx`.
    const t = setTimeout(() => {
      if (vivo) load(0);
    }, 300);
    return () => {
      vivo = false;
      clearTimeout(t);
    };
  }, [load]);

  // Rótulo estruturado quando o lançamento tem vínculo; senão cai no texto legado (`category`).
  const accountLabel = useMemo(
    () => Object.fromEntries(chartAccounts.map((a) => [a.id, a.categoria])),
    [chartAccounts],
  );
  const costCenterLabel = useMemo(
    () => Object.fromEntries(costCenters.map((c) => [c.id, c.name])),
    [costCenters],
  );

  // ⚠️ `setDuplicando(null)` aqui não é redundante com o `onClose`: sem ele, duplicar → fechar →
  // "Nova conta" abriria o cadastro preenchido com uma despesa que o dono não pediu.
  usePrimaryAction(
    "Nova conta",
    useCallback(() => {
      setDuplicando(null);
      setOpen(true);
    }, []),
  );

  async function cancel(id: string) {
    if (!confirm("Cancelar esta conta?")) return;
    await api.post(`/payables/bills/${id}/cancel`);
    load();
  }
  /**
   * Estorno — **e o cancelamento de agendamento é a MESMA rota** (Story 8.14 AC9).
   *
   * A confirmação muda de frase porque os dois gestos não são o mesmo fato para o dono: estornar
   * desfaz um pagamento que aconteceu; cancelar um agendamento impede um que ainda vai acontecer.
   * A consequência no sistema, essa sim, é idêntica: a conta volta para "A pagar", reaparece na
   * Fila e o movimento bancário é apagado.
   */
  /**
   * Reativar é rota PRÓPRIA, não `/reverse`.
   *
   * `reverse` apaga movimento bancário — trabalho que aqui não existe, porque cancelar só age
   * sobre conta em aberto, que não tem movimento nenhum. A confirmação avisa do vencimento porque
   * é a única consequência que surpreende: reativada depois do prazo, a conta volta Atrasada, com
   * a data original preservada.
   */
  async function reactivate(id: string) {
    if (
      !confirm(
        'Reativar esta conta? Ela volta para "A pagar" com o vencimento original — se ele já ' +
          "passou, ela aparece como Atrasada e você pode editar a data.",
      )
    )
      return;
    await api.post(`/payables/bills/${id}/reactivate`);
    load();
  }

  async function reverse(id: string, agendada = false) {
    const pergunta = agendada
      ? "Cancelar o agendamento desta conta? O débito programado deixa de ser contado e ela volta " +
        'para "A pagar".'
      : 'Estornar esta conta? Ela volta para "A pagar" e pode ser editada de novo.';
    if (!confirm(pergunta)) return;
    await api.post(`/payables/bills/${id}/reverse`);
    load();
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Contas a Pagar</p>
        <h1 className="text-2xl font-bold text-neutral-800">Despesas</h1>
      </div>

      {inbox.length > 0 && (
        <Link
          to={`/comprovante/${inbox[0].id}`}
          className="block rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-medium text-amber-800 hover:bg-amber-100"
        >
          {inbox.length === 1
            ? "1 comprovante aguardando"
            : `${inbox.length} comprovantes aguardando`}{" "}
          — toque para escolher a conta.
        </Link>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="A pagar" value={formatBRL(summary.open_cents)} tone="text-amber-700" />
        <Stat label="Atrasado" value={formatBRL(summary.overdue_cents)} tone="text-danger" />
        <Stat label="Nesta semana" value={formatBRL(summary.week_cents)} tone="text-neutral-700" />
        <Stat label="Pago no mês" value={formatBRL(summary.paid_month_cents)} tone="text-accent-700" />
      </div>

      <FiltrosDaLista
        valor={filtro}
        onChange={trocarFiltro}
        categorias={chartAccounts}
        centros={costCenters}
      />

      {/* overflow-x-auto (não overflow-hidden): achado de campo — em tela estreita a tabela tem
          7 colunas e ficava CORTADA em vez de rolável, escondendo Status e as ações (Editar/
          Marcar paga/Estornar). Mesmo padrão de DrePage/LucratividadePage. */}
      <div className="overflow-x-auto rounded-2xl bg-white shadow-sm">
        {bills.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhuma conta. Clique em "Nova conta".
          </p>
        ) : (
          <table
            // `min-w-[48rem]`: sem uma largura mínima, `overflow-x-auto` não rola — a tabela se
            // espreme dentro dos 360px e as 7 colunas viram tiras ilegíveis (o mesmo par
            // `overflow-x-auto` + `min-w` que `ContasSaldosPage` usa). Rolar é o comportamento
            // desejado; espremer só troca "cortado" por "ilegível".
            className="w-full min-w-[48rem] text-sm"
          >
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Conta</th>
                <th className="px-4 py-3 font-medium">Categoria</th>
                <th className="px-4 py-3 font-medium">Centro de custo</th>
                <th className="px-4 py-3 font-medium">Vencimento</th>
                <th className="px-4 py-3 font-medium">Valor</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {bills.map((p) => {
                const st = statusInfo(p);
                return (
                  <tr key={p.id} className="border-b border-neutral-50 last:border-0">
                    <td className="px-4 py-3">
                      <span className="text-neutral-800">{p.description || "—"}</span>
                      {p.supplier && (
                        <span className="block text-xs text-neutral-400">{p.supplier}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-neutral-500">
                      {(p.chart_account_id && accountLabel[p.chart_account_id]) || p.category}
                    </td>
                    <td className="px-4 py-3 text-neutral-500">
                      {(p.cost_center_id && costCenterLabel[p.cost_center_id]) || "—"}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-neutral-600">
                      {formatDay(p.due_date)}
                    </td>
                    <td className="px-4 py-3 font-medium tabular-nums">{formatBRL(p.amount_cents)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-pill px-2 py-0.5 text-xs ${st.cls}`}>{st.label}</span>
                      {/* A data do DÉBITO, não o vencimento: numa agendada as duas divergem por
                          construção, e é a do débito que responde "quando o dinheiro sai?". */}
                      {p.status === "scheduled" && p.paid_at && (
                        <span className="block text-[11px] text-neutral-400">
                          sai {diaDoDebito(p.paid_at)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-3">
                        {p.payment_code && (
                          <button title="Copiar código do boleto/Pix" onClick={() => navigator.clipboard?.writeText(p.payment_code)} className="text-neutral-400 hover:text-primary-600">
                            <Copy size={14} />
                          </button>
                        )}
                        {p.status !== "canceled" && (
                          <button onClick={() => setAttach(p)} className="flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-primary-600">
                            <Paperclip size={12} /> Boleto/Pix
                          </button>
                        )}
                        {p.status === "open" && (
                          <>
                            <button onClick={() => setEdit(p)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
                              Editar
                            </button>
                            <button onClick={() => setPagando(p)} className="text-xs font-medium text-accent-600 hover:underline">
                              Marcar paga
                            </button>
                            <button onClick={() => cancel(p.id)} className="text-xs text-neutral-400 hover:text-danger">
                              Cancelar
                            </button>
                          </>
                        )}
                        {p.status === "paid" && (
                          <button onClick={() => reverse(p.id)} className="text-xs font-medium text-neutral-400 hover:text-danger">
                            Estornar
                          </button>
                        )}
                        {/* ⚠️ **[Story 8.14] Mesma ação, rótulo diferente.** No backend é o MESMO
                            `POST /reverse` — não há verbo novo, porque `reverse` sempre significou
                            "esta saída não vai acontecer" e isso serve igualmente para uma saída
                            que ainda não aconteceu. Na tela o nome precisa ser outro: "Estornar"
                            uma conta que nunca foi paga não é frase que o dono reconheça. */}
                        {p.status === "scheduled" && (
                          <button onClick={() => reverse(p.id, true)} className="text-xs font-medium text-neutral-400 hover:text-danger">
                            Cancelar agendamento
                          </button>
                        )}
                        {/* Invisível na visão padrão (que abre em "Em aberto"); chega-se a ela
                            por Status → Cancelado. Reativar é gesto deliberado, não algo em que
                            se tropeça enquanto se dá baixa em contas. */}
                        {p.status === "canceled" && (
                          <button onClick={() => reactivate(p.id)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
                            Reativar
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {/* A contagem aparece SEMPRE, não só quando trunca: é ela que torna o corte visível
            antes de o dono precisar dele. O defeito que esta tela tinha não era ter um teto —
            era o teto não se anunciar. */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-neutral-100 px-4 py-3">
          <p className="text-xs text-neutral-500">
            Mostrando {bills.length} de {total}
          </p>
          {bills.length < total && (
            <button
              onClick={() => load(offset + PAGINA)}
              disabled={carregando}
              className="min-h-[44px] rounded-pill px-4 text-sm font-medium text-primary-600 hover:bg-primary-50 disabled:opacity-50"
            >
              {carregando ? "Carregando…" : "Carregar mais"}
            </button>
          )}
        </div>
      </div>

      {/* O gancho da Vima vive DEPOIS da tabela desde a spec 2026-08-18. Acima do título ele
          ocupava ~200px da primeira dobra e empurrava a lista para fora da tela — disputando o
          espaço mais nobre com o motivo pelo qual a página é aberta. Continua sendo respondido. */}
      <GanchoDaVima gancho="payables.conta.criada" />

      {/* A baixa passa por aqui desde a Story 8.13: a conta bancária de onde o dinheiro saiu é
          obrigatória no backend (8.12) e o dia é escolhido junto, no MESMO container do botão que
          comete a ação. O 409 acionável abre o cadastro de conta embutido e volta para cá. */}
      {pagando && (
        <DialogDeBaixa
          titulo="Dar baixa nesta conta"
          descricao={pagando.description || pagando.supplier || "Conta"}
          valor={`${formatBRL(pagando.amount_cents)} · vence ${formatDay(pagando.due_date)}`}
          dataPadrao={pagando.due_date}
          onClose={() => setPagando(null)}
          onPago={async (corpo) => {
            await api.post(`/payables/bills/${pagando.id}/pay`, corpo);
            setPagando(null);
            load();
          }}
        />
      )}

      <NewBillModal
        // A `key` remonta o formulário quando a conta de origem muda — é o que faz os valores
        // iniciais valerem na segunda duplicação (ver a docstring de `inicial`).
        key={duplicando?.id ?? "nova"}
        open={open}
        inicial={duplicando ? camposDaCopia(duplicando) : undefined}
        onClose={() => {
          setOpen(false);
          setDuplicando(null);
        }}
        onCreated={load}
      />
      {edit && (
        <EditBillModal
          bill={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            load();
          }}
        />
      )}
      {attach && (
        <AttachModal
          bill={attach}
          onDuplicar={() => {
            setDuplicando(attach);
            setAttach(null);
            setOpen(true);
          }}
          onClose={() => setAttach(null)}
          onSaved={() => {
            setAttach(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function EditBillModal({
  bill,
  onClose,
  onSaved,
}: {
  bill: Payable;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [description, setDescription] = useState(bill.description);
  const [chartAccountId, setChartAccountId] = useState(bill.chart_account_id ?? "");
  const [costCenterId, setCostCenterId] = useState(bill.cost_center_id ?? "");
  const [supplier, setSupplier] = useState(bill.supplier);
  const [value, setValue] = useState((bill.amount_cents / 100).toFixed(2).replace(".", ","));
  const [dueDate, setDueDate] = useState(bill.due_date);
  const [recurrence, setRecurrence] = useState(bill.recurrence);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/payables/bills/${bill.id}`, {
        description,
        chart_account_id: chartAccountId,
        cost_center_id: costCenterId,
        supplier,
        amount_cents: Math.round(parseFloat(value.replace(",", ".")) * 100),
        due_date: dueDate,
        recurrence,
      });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Editar conta" open onClose={onClose}>
      <div className="space-y-3">
        <Field label="Descrição" value={description} onChange={setDescription} />
        <Field label="Fornecedor" value={supplier} onChange={setSupplier} />
        <div className="flex gap-2">
          <div className="flex-1">
            <ChartAccountSelect
              value={chartAccountId}
              onChange={setChartAccountId}
              groups={EXPENSE_GROUPS}
              defaultNewGrupo="DESPESA_FIXA"
            />
          </div>
          <div className="flex-1">
            <CostCenterSelect value={costCenterId} onChange={setCostCenterId} />
          </div>
        </div>
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Recorrência</span>
          <select value={recurrence} onChange={(e) => setRecurrence(e.target.value as Payable["recurrence"])} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
            {RECUR.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <p className="text-xs text-neutral-400">Mudar o vencimento move o evento na Agenda.</p>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={save} disabled={saving || !value || !dueDate} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Salvando..." : "Salvar alterações"}
        </button>
      </div>
    </Modal>
  );
}

function AttachModal({
  bill,
  onClose,
  onSaved,
  onDuplicar,
}: {
  bill: Payable;
  onClose: () => void;
  onSaved: () => void;
  /** Avisa que o dono quer repetir esta despesa. O modal não sabe o que isso significa. */
  onDuplicar: () => void;
}) {
  const [paymentCode, setPaymentCode] = useState(bill.payment_code);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function saveCode() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/payables/bills/${bill.id}`, { payment_code: paymentCode });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Boleto / Contrato / Pix" open onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-neutral-500">{bill.description || bill.supplier || "Conta"}</p>

        <div>
          <p className="mb-2 text-xs font-medium text-neutral-600">Anexar arquivos (PDF, JPEG ou PNG)</p>
          <Attachments
            ownerType="payable"
            ownerId={bill.id}
            slots={[
              { key: "boleto", label: "Boleto" },
              { key: "contrato", label: "Contrato" },
              { key: "comprovante", label: "Comprovante" },
            ]}
          />
        </div>

        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Pix copia-e-cola / linha do boleto (opcional)
          </span>
          <textarea value={paymentCode} onChange={(e) => setPaymentCode(e.target.value)} rows={2} placeholder="Cole aqui o código" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={saveCode}
          disabled={saving}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Salvar código"}
        </button>

        {/* Duplicar mora aqui, e não no grid: a coluna de ações da tabela já carrega até cinco
            elementos e rola lateralmente em 360px. Este modal já é alcançável em toda linha não
            cancelada, então a restrição de status vem de graça, pela porta que já existia. */}
        <div className="border-t border-neutral-100 pt-4">
          <button
            onClick={onDuplicar}
            className="w-full rounded-pill border border-neutral-200 py-2.5 font-semibold text-neutral-600 hover:border-primary-300 hover:text-primary-600"
          >
            Duplicar esta conta
          </button>
          <p className="mt-2 text-xs text-neutral-400">
            Abre o cadastro preenchido com os dados desta conta e vencimento no mês seguinte. Os
            anexos não são copiados.
          </p>
        </div>
      </div>
    </Modal>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}

function NewBillModal({
  open,
  onClose,
  onCreated,
  inicial,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  /**
   * Valores de partida quando o formulário nasce de uma duplicação.
   *
   * ⚠️ Lido **só na montagem** — `useState(x)` ignora mudanças de `x` depois disso. Quem monta
   * este componente (`PagarPage`) passa uma `key` derivada da conta duplicada justamente para
   * forçar a remontagem; sem ela, a segunda duplicação mostraria os dados da primeira.
   */
  inicial?: CamposDaConta;
}) {
  const [description, setDescription] = useState(inicial?.description ?? "");
  const [chartAccountId, setChartAccountId] = useState(inicial?.chartAccountId ?? "");
  const [costCenterId, setCostCenterId] = useState(inicial?.costCenterId ?? "");
  const [supplier, setSupplier] = useState(inicial?.supplier ?? "");
  const [value, setValue] = useState(inicial?.value ?? "");
  const [dueDate, setDueDate] = useState(inicial?.dueDate ?? "");
  const [recurrence, setRecurrence] = useState(inicial?.recurrence ?? "none");
  const [recurrenceCount, setRecurrenceCount] = useState(inicial?.recurrenceCount ?? "12");
  const [paymentCode, setPaymentCode] = useState(inicial?.paymentCode ?? "");
  const [contractId, setContractId] = useState(inicial?.contractId ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const amount_cents = Math.round(parseFloat(value.replace(",", ".")) * 100);
      await api.post("/payables/bills", {
        description,
        chart_account_id: chartAccountId || null,
        cost_center_id: costCenterId || null,
        supplier,
        amount_cents,
        due_date: dueDate,
        recurrence,
        recurrence_count: recurrence === "none" ? 1 : Math.max(1, Math.min(60, parseInt(recurrenceCount, 10) || 1)),
        payment_code: paymentCode,
        contract_id: contractId || null,
      });
      onCreated();
      setDescription("");
      setChartAccountId("");
      setCostCenterId("");
      setSupplier("");
      setValue("");
      setDueDate("");
      setPaymentCode("");
      setContractId("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova conta a pagar" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Descrição" value={description} onChange={setDescription} placeholder="Aluguel" />
        <Field label="Fornecedor" value={supplier} onChange={setSupplier} placeholder="Imobiliária" />
        <div className="flex gap-2">
          <div className="flex-1">
            <ChartAccountSelect
              value={chartAccountId}
              onChange={setChartAccountId}
              groups={EXPENSE_GROUPS}
              defaultNewGrupo="DESPESA_FIXA"
            />
          </div>
          <div className="flex-1">
            <CostCenterSelect value={costCenterId} onChange={setCostCenterId} />
          </div>
        </div>
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} placeholder="2500,00" />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Recorrência</span>
            <select value={recurrence} onChange={(e) => setRecurrence(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              {RECUR.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
          {recurrence !== "none" && (
            <Field label="Repetir (vezes)" value={recurrenceCount} onChange={setRecurrenceCount} />
          )}
        </div>
        {recurrence !== "none" && (
          <p className="-mt-1 text-xs text-neutral-400">
            Gera uma conta por período, cada uma com seu vencimento (para anexar o boleto certo).
          </p>
        )}
        <ContractSelect value={contractId} onChange={setContractId} />
        <div className="rounded-lg bg-neutral-50 p-3">
          <p className="mb-2 text-xs font-medium text-neutral-600">Pix copia-e-cola / linha do boleto (opcional)</p>
          <textarea value={paymentCode} onChange={(e) => setPaymentCode(e.target.value)} rows={2} placeholder="Cole o código aqui (os arquivos do boleto/contrato você anexa depois, em Boleto/Pix)" className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400" />
        </div>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !value || !dueDate}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Adicionar conta"}
        </button>
      </div>
    </Modal>
  );
}
