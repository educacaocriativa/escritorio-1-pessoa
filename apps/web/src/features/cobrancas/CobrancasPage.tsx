import type { Charge, ChargesSummary, Client, Contract } from "@e1p/shared-types";
import { Copy, Paperclip } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import Attachments from "../../components/Attachments";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage, publicApi } from "../../lib/api";
import { pluralize } from "../../lib/pluralize";
import GanchoDaVima from "../dna/GanchoDaVima";
import { usePrimaryAction } from "../../store/pageActions";
import ChartAccountSelect from "../financeiro/ChartAccountSelect";
import { AGENDADO_ENTRADA_LABEL, parseCentsBRL, type BankAccount } from "../financeiro/contas";
import type { CostCenter } from "../financeiro/costCenters";
import CostCenterSelect from "../financeiro/CostCenterSelect";
import { type ChartAccount, GRUPOS_DRE } from "../financeiro/planoContas";
import { VOCAB_ENTRADA } from "../pagar/baixa";
import { DialogDeBaixa, HOJE_DO_TENANT } from "../pagar/EscolhaDaBaixa";
import { rotuloDaRota } from "./rota";
import { formatDay } from "../../lib/datetime";
import { formatBRL } from "../financeiro/dre";

/** Grupos DRE cabíveis numa RECEITA (Cobranças nunca lança em Despesa/Tributo/Investimento). */
const REVENUE_GROUPS = GRUPOS_DRE.filter((g) => g === "RECEITA");

const KINDS = [
  ["service", "Serviço"],
  ["product", "Produto"],
  ["recurring", "Recorrente"],
] as const;
const METHODS = [
  ["pix", "Pix"],
  ["boleto", "Boleto"],
  ["card", "Link de cartão"],
] as const;

function statusInfo(c: Charge): { label: string; cls: string } {
  if (c.status === "paid") return { label: "Recebido", cls: "bg-accent-50 text-accent-700" };
  // ⚠️ **[Story 8.15] `scheduled` tem RÓTULO PRÓPRIO — não é "Recebido" nem "A vencer".**
  // "Recebido" diria que o dinheiro caiu (não caiu); "A vencer" pediria uma cobrança que o dono já
  // sabe que está resolvida — e a régua voltaria a alcançar quem já pagou, que é o defeito inteiro
  // que esta story fecha.
  if (c.status === "scheduled") return { label: "Agendado", cls: "bg-amber-50 text-amber-700" };
  if (c.status === "canceled") return { label: "Cancelado", cls: "bg-neutral-100 text-neutral-500" };
  if (c.is_overdue) return { label: "Vencido", cls: "bg-red-50 text-danger" };
  return { label: "A vencer", cls: "bg-blue-50 text-blue-700" };
}

const EMPTY_SUMMARY: ChargesSummary = {
  open_cents: 0,
  overdue_cents: 0,
  paid_cents: 0,
  open_count: 0,
  overdue_count: 0,
  scheduled_cents: 0,
};

export default function CobrancasPage() {
  const [summary, setSummary] = useState<ChargesSummary>(EMPTY_SUMMARY);
  const [charges, setCharges] = useState<Charge[]>([]);
  const [chartAccounts, setChartAccounts] = useState<ChartAccount[]>([]);
  const [costCenters, setCostCenters] = useState<CostCenter[]>([]);
  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([]);
  const [open, setOpen] = useState(false);
  const [docs, setDocs] = useState<Charge | null>(null);
  const [edit, setEdit] = useState<Charge | null>(null);
  // [8.15] A cobrança para a qual o dono está declarando "recebi direto na conta".
  const [recebendo, setRecebendo] = useState<Charge | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "ok" | "err" } | null>(null);

  const notify = useCallback((msg: string, type: "ok" | "err" = "ok") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2600);
  }, []);

  const load = useCallback(async () => {
    const [s, c] = await Promise.all([
      api.get<ChargesSummary>("/receivables/summary"),
      api.get<Charge[]>("/receivables/charges"),
    ]);
    // Guarda de FORMA (issue #247): `summary.open_cents`/`overdue_count`/etc. são lidos direto no
    // render (cartões acima da tabela) sem `?.`. Um payload fora de forma — envelope de erro
    // devolvido com 200, array em vez de objeto, corpo vazio — não pode quebrar os TRÊS cartões
    // por causa de uma resposta malformada; degrada para o resumo zerado (`EMPTY_SUMMARY`), o mesmo
    // que já é o estado inicial.
    setSummary(
      s.data && typeof s.data === "object" && !Array.isArray(s.data) ? s.data : EMPTY_SUMMARY,
    );
    // Guarda de FORMA (issue #252): `charges.map`/`.length` rodam direto no render, sem checar o
    // payload. `Array.isArray`, no molde de `CrmPage.tsx`/`ClientTimeline.tsx` (#225): um payload
    // fora de forma (envelope de erro devolvido com 200, corpo vazio) faz `charges.map` estourar.
    setCharges(Array.isArray(c.data) ? c.data : []);
    // Rótulos são só um complemento de exibição — se o usuário não tiver acesso a esses módulos
    // (require_module), a lista de cobranças continua funcionando normalmente.
    const [ca, cc, ba] = await Promise.all([
      api.get<ChartAccount[]>("/chart-of-accounts").catch(() => ({ data: [] as ChartAccount[] })),
      api.get<CostCenter[]>("/cost-centers").catch(() => ({ data: [] as CostCenter[] })),
      // [8.15] Só para NOMEAR a conta que recebeu na linha liquidada fora do trilho. A escolha da
      // conta no registro é do `DialogDeBaixa`, que carrega a própria lista.
      api.get<BankAccount[]>("/bank/accounts").catch(() => ({ data: [] as BankAccount[] })),
    ]);
    // Guarda de FORMA (issue #252): os três alimentam `.map`/objectFromEntries usados nos rótulos
    // (accountLabel/costCenterLabel/nomeDaContaBancaria) sem checar o payload.
    setChartAccounts(Array.isArray(ca.data) ? ca.data : []);
    setCostCenters(Array.isArray(cc.data) ? cc.data : []);
    setBankAccounts(Array.isArray(ba.data) ? ba.data : []);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const accountLabel = useMemo(
    () => Object.fromEntries(chartAccounts.map((a) => [a.id, a.categoria])),
    [chartAccounts],
  );
  const costCenterLabel = useMemo(
    () => Object.fromEntries(costCenters.map((c) => [c.id, c.name])),
    [costCenters],
  );
  const nomeDaContaBancaria = useMemo(() => {
    const mapa = Object.fromEntries(bankAccounts.map((a) => [a.id, a.name]));
    return (id: string) => mapa[id] ?? "";
  }, [bankAccounts]);

  usePrimaryAction("Nova cobrança", useCallback(() => setOpen(true), []));

  // Em produção, o pagamento é reconhecido pelo gateway (webhook). Aqui é só simulação de teste
  // do gateway (Pix/cartão/boleto) — o dono NÃO marca pago manualmente.
  async function simulatePayment(c: Charge) {
    if (!confirm("Simular o pagamento do cliente (gateway de teste)?")) return;
    try {
      await publicApi.post("/receivables/webhook", {
        tenant_id: c.tenant_id,
        charge_id: c.id,
        status: "paid",
      });
      load();
    } catch (err) {
      notify(apiErrorMessage(err), "err");
    }
  }
  async function cancel(id: string) {
    if (!confirm("Cancelar esta cobrança?")) return;
    try {
      await api.post(`/receivables/charges/${id}/cancel`);
      load();
    } catch (err) {
      notify(apiErrorMessage(err), "err");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm text-neutral-500">Página / Cobranças</p>
        <h1 className="text-2xl font-bold text-neutral-800">Contas a Receber</h1>
        <p className="mt-1 text-sm text-neutral-500">
          O pagamento é reconhecido automaticamente (Pix/cartão/boleto). Você saca o que entra no
          Financeiro.
        </p>
      </div>

      <GanchoDaVima gancho="receivables.cobranca.criada" />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="A vencer" value={formatBRL(summary.open_cents)} hint={`${summary.open_count} ${pluralize(summary.open_count, "cobrança", "cobranças")}`} tone="text-blue-700" />
        <Stat label="Vencido" value={formatBRL(summary.overdue_cents)} hint={`${summary.overdue_count} em atraso`} tone="text-danger" />
        <Stat label="Recebido" value={formatBRL(summary.paid_cents)} hint="total" tone="text-accent-700" />
        {/* [8.15] O agendado tem cartão PRÓPRIO e **some quando é zero** — mesmo tratamento do
            agendado da 8.14. Sem ele, a cobrança agendada não apareceria em nenhum dos três
            cartões (nem "a vencer", nem "vencido", nem "recebido"): o modo de falha "o dinheiro
            some da tela" que esta onda existe para eliminar.
            ⚠️ [#186] O rótulo vem de `AGENDADO_ENTRADA_LABEL` (`financeiro/contas.ts`) e não de um
            literal: `ContasSaldosPage` e `crm/ClientDetailPage` mostram o MESMO estado e têm de
            mudar de nome junto com este cartão. Escrito solto, um rename desincronizava as três
            com a suíte inteira verde. */}
        {summary.scheduled_cents > 0 && (
          <Stat
            label={AGENDADO_ENTRADA_LABEL}
            value={formatBRL(summary.scheduled_cents)}
            hint="recebido fora do trilho, com dia marcado"
            tone="text-amber-700"
          />
        )}
      </div>

      <div className="overflow-hidden rounded-2xl bg-white shadow-sm">
        {charges.length === 0 ? (
          <p className="p-8 text-center text-sm text-neutral-400">
            Nenhuma cobrança. Clique em "Nova cobrança".
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="px-4 py-3 font-medium">Cliente</th>
                <th className="px-4 py-3 font-medium">Descrição</th>
                <th className="px-4 py-3 font-medium">Categoria</th>
                <th className="px-4 py-3 font-medium">Centro de custo</th>
                <th className="px-4 py-3 font-medium">Vencimento</th>
                <th className="px-4 py-3 font-medium">Valor</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {charges.map((c) => {
                const st = statusInfo(c);
                return (
                  <tr key={c.id} className="border-b border-neutral-50 last:border-0">
                    <td className="px-4 py-3 font-medium text-neutral-800">
                      {c.client_name ?? <span className="text-neutral-300">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-neutral-800">{c.description || "—"}</span>
                      <span className="ml-2 inline-flex items-center gap-1 text-xs text-neutral-400">
                        {c.method}
                        <button
                          title="Copiar código de pagamento"
                          onClick={() => navigator.clipboard?.writeText(c.payment_code)}
                          className="hover:text-neutral-600"
                        >
                          <Copy size={11} />
                        </button>
                      </span>
                    </td>
                    <td className="px-4 py-3 text-neutral-500">
                      {(c.chart_account_id && accountLabel[c.chart_account_id]) || "—"}
                    </td>
                    <td className="px-4 py-3 text-neutral-500">
                      {(c.cost_center_id && costCenterLabel[c.cost_center_id]) || "—"}
                    </td>
                    <td className="px-4 py-3 tabular-nums text-neutral-600">
                      {formatDay(c.due_date)}
                    </td>
                    <td className="px-4 py-3 font-medium tabular-nums">{formatBRL(c.amount_cents)}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-pill px-2 py-0.5 text-xs ${st.cls}`}>{st.label}</span>
                      {/* [8.15] A linha liquidada FORA DO TRILHO diz QUAL conta recebeu e QUANDO.
                          O rótulo é DERIVADO dos dois ponteiros (`rota.ts`), nunca persistido. */}
                      {rotuloDaRota(c, nomeDaContaBancaria) && (
                        <span className="mt-0.5 block text-[11px] text-neutral-400">
                          {rotuloDaRota(c, nomeDaContaBancaria)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <button onClick={() => setDocs(c)} className="flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-primary-600">
                          <Paperclip size={12} /> Contrato
                        </button>
                        {c.status === "open" && (
                          <>
                            <button onClick={() => setEdit(c)} className="text-xs font-medium text-neutral-500 hover:text-primary-600">
                              Editar
                            </button>
                            {/* ⚠️ **[Story 8.15] O rótulo é o FATO, não o mecanismo — e NÃO é
                                "Marcar paga".** Aquele botão foi removido de propósito (só o
                                webhook do gateway marca pago) e a diferença importa: aqui o dono
                                declara um fato sobre a conta bancária DELE. Convive com o
                                "simular pgto" ao lado sem ambiguidade: aquele finge o gateway,
                                este registra o que aconteceu fora dele. */}
                            <button
                              onClick={() => setRecebendo(c)}
                              title="Recebi este valor direto na minha conta bancária, fora da cobrança do e1p"
                              className="text-xs font-medium text-neutral-500 hover:text-accent-600"
                            >
                              Recebi direto na conta
                            </button>
                            <button onClick={() => simulatePayment(c)} title="Apenas teste do gateway — em produção o pagamento entra sozinho" className="text-[11px] text-neutral-300 hover:text-accent-600">
                              simular pgto
                            </button>
                            <button onClick={() => cancel(c.id)} className="text-xs text-neutral-400 hover:text-danger">
                              Cancelar
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* [8.15] O MESMO componente da baixa de Contas a Pagar (8.13), com o vocabulário das
          ENTRADAS: seletor de conta e dia **dentro do container do botão** que comete a ação, 409
          acionável abrindo o cadastro embutido e retomando o registro. A lição dos PRs #56/#58
          vale igual aqui — terceira vez seria imperdoável. */}
      {recebendo && (
        <DialogDeBaixa
          titulo="Recebi direto na conta"
          descricao={recebendo.client_name || recebendo.description || "Cobrança"}
          valor={`${formatBRL(recebendo.amount_cents)} · vence ${formatDay(recebendo.due_date)}`}
          // Default = HOJE (não o vencimento): o gesto aqui é "caiu na minha conta", um fato que o
          // dono está observando agora — a assimetria com a baixa de Contas a Pagar é deliberada.
          // ⚠️ **`HOJE_DO_TENANT`, não um hoje montado aqui** (#136). Esta tela passava
          // `hojeISO()`, que monta a data pelas partes locais de um `new Date()` — o dia de quem
          // abriu o NAVEGADOR. Para um dono em viagem, o "dia em que o dinheiro caiu" vinha do
          // fuso do hotel, e perto da virada sempre vinha errado. Quem resolve o hoje agora é o
          // `useEscolhaDaBaixa`, no fuso do tenant e no MESMO ponto em que valida a data.
          dataPadrao={HOJE_DO_TENANT}
          vocab={VOCAB_ENTRADA}
          acao="Confirmar recebimento"
          acaoEmCurso="Registrando…"
          onClose={() => setRecebendo(null)}
          onPago={async (corpo) => {
            await api.post(`/receivables/charges/${recebendo.id}/settle-externally`, {
              bank_account_id: corpo.bank_account_id,
              received_on: corpo.paid_on,
            });
            setRecebendo(null);
            load();
          }}
        />
      )}

      <NewChargeModal open={open} onClose={() => setOpen(false)} onCreated={load} />
      {edit && (
        <EditChargeModal
          charge={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            load();
          }}
        />
      )}
      {docs && (
        <Modal title="Contrato / documentos da cobrança" open onClose={() => setDocs(null)}>
          <div className="space-y-3">
            <p className="text-sm text-neutral-500">
              {docs.client_name ?? docs.description ?? "Cobrança"} — {formatBRL(docs.amount_cents)}
            </p>
            <p className="text-xs font-medium text-neutral-600">Anexar arquivos (PDF, JPEG ou PNG)</p>
            <Attachments
              ownerType="charge"
              ownerId={docs.id}
              slots={[{ key: "contrato", label: "Contrato" }, { key: "boleto", label: "Boleto" }]}
            />
          </div>
        </Modal>
      )}

      {toast && (
        <div
          className={`fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-pill px-4 py-2 text-sm font-semibold text-white shadow-lg ${toast.type === "err" ? "bg-danger" : "bg-neutral-800"}`}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-neutral-500">{label}</p>
      <p className={`text-xl font-bold ${tone}`}>{value}</p>
      <p className="text-xs text-neutral-400">{hint}</p>
    </div>
  );
}

function EditChargeModal({
  charge,
  onClose,
  onSaved,
}: {
  charge: Charge;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [description, setDescription] = useState(charge.description);
  const [chartAccountId, setChartAccountId] = useState(charge.chart_account_id ?? "");
  const [costCenterId, setCostCenterId] = useState(charge.cost_center_id ?? "");
  const [value, setValue] = useState((charge.amount_cents / 100).toFixed(2).replace(".", ","));
  const [dueDate, setDueDate] = useState(charge.due_date);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.patch(`/receivables/charges/${charge.id}`, {
        description,
        chart_account_id: chartAccountId,
        cost_center_id: costCenterId,
        amount_cents: parseCentsBRL(value),
        due_date: dueDate,
      });
      onSaved();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Editar cobrança" open onClose={onClose}>
      <div className="space-y-3">
        <Field label="Descrição" value={description} onChange={setDescription} />
        <div className="flex gap-2">
          <div className="flex-1">
            <ChartAccountSelect
              value={chartAccountId}
              onChange={setChartAccountId}
              groups={REVENUE_GROUPS}
              defaultNewGrupo="RECEITA"
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
        <p className="text-xs text-neutral-400">Mudar o vencimento move o evento na Agenda.</p>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button onClick={save} disabled={saving || !value || !dueDate} className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white hover:bg-accent-500 disabled:opacity-60">
          {saving ? "Salvando..." : "Salvar alterações"}
        </button>
      </div>
    </Modal>
  );
}

function NewChargeModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState("service");
  const [method, setMethod] = useState("pix");
  const [value, setValue] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [description, setDescription] = useState("");
  const [clientId, setClientId] = useState("");
  const [chartAccountId, setChartAccountId] = useState("");
  const [costCenterId, setCostCenterId] = useState("");
  const [recurrence, setRecurrence] = useState("none");
  const [recurrenceCount, setRecurrenceCount] = useState("12");
  const [clients, setClients] = useState<Client[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [contractId, setContractId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      api.get<Client[]>("/crm/clients").then(({ data }) => setClients(Array.isArray(data) ? data : []));
      api
        .get<Contract[]>("/contracts")
        .then(({ data }) => setContracts(Array.isArray(data) ? data : []))
        .catch(() => setContracts([]));
    }
  }, [open]);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const amount_cents = parseCentsBRL(value);
      await api.post("/receivables/charges", {
        kind,
        method,
        amount_cents,
        due_date: dueDate,
        description,
        client_id: clientId || null,
        chart_account_id: chartAccountId || null,
        cost_center_id: costCenterId || null,
        contract_id: contractId || null,
        recurrence,
        recurrence_count: recurrence === "none" ? 1 : Math.max(1, Math.min(60, parseInt(recurrenceCount, 10) || 1)),
      });
      onCreated();
      setValue("");
      setDueDate("");
      setDescription("");
      setChartAccountId("");
      setCostCenterId("");
      setContractId("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova cobrança" open={open} onClose={onClose}>
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Cliente</span>
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="">Sem cliente</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
            <select value={kind} onChange={(e) => setKind(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              {KINDS.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Forma</span>
            <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              {METHODS.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="flex gap-2">
          <Field label="Valor (R$)" value={value} onChange={setValue} placeholder="150,00" />
          <Field label="Vencimento" type="date" value={dueDate} onChange={setDueDate} />
        </div>
        <Field label="Descrição" value={description} onChange={setDescription} placeholder="Mensalidade" />
        <div className="flex gap-2">
          <div className="flex-1">
            <ChartAccountSelect
              value={chartAccountId}
              onChange={setChartAccountId}
              groups={REVENUE_GROUPS}
              defaultNewGrupo="RECEITA"
            />
          </div>
          <div className="flex-1">
            <CostCenterSelect value={costCenterId} onChange={setCostCenterId} />
          </div>
        </div>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Vincular a contrato (opcional)
          </span>
          <select
            value={contractId}
            onChange={(e) => setContractId(e.target.value)}
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
        <div className="flex gap-2">
          <label className="flex-1">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Recorrência</span>
            <select value={recurrence} onChange={(e) => setRecurrence(e.target.value)} className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400">
              <option value="none">Não repete</option>
              <option value="weekly">Semanal</option>
              <option value="monthly">Mensal</option>
              <option value="yearly">Anual</option>
            </select>
          </label>
          {recurrence !== "none" && (
            <Field label="Repetir (vezes)" value={recurrenceCount} onChange={setRecurrenceCount} />
          )}
        </div>
        {recurrence !== "none" && (
          <p className="-mt-1 text-xs text-neutral-400">
            Gera uma cobrança por período, cada uma com seu vencimento e boleto.
          </p>
        )}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !value || !dueDate}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Gerando..." : method === "boleto" ? "Gerar boleto" : "Gerar cobrança"}
        </button>
      </div>
    </Modal>
  );
}
