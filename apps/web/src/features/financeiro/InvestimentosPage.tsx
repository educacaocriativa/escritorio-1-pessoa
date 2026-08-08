import { TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import { type ChartAccount } from "./planoContas";
import type { BankAccount } from "./contas";
import {
  contasDeAplicacao,
  formatBRL,
  formatPct,
  type InvestmentAccount,
  type Rentability,
  rotuloDoVinculo,
  SUGGESTED_KINDS,
} from "./investimentos";

/**
 * Contas de investimento (Story 5.6): lista de aplicações com principal, rendimento acumulado e
 * rentabilidade (total e do período), e o botão "registrar rendimento" (data/valor/conta do plano
 * de contas FINANCEIRO). O rendimento vira receita financeira na DRE — NÃO é venda com split de
 * Carteira. Design "Portal", PT-BR. Mesma organização de features/financeiro das stories 5.1/5.5.
 */
export default function InvestimentosPage() {
  const [accounts, setAccounts] = useState<InvestmentAccount[]>([]);
  const [rentability, setRentability] = useState<Record<string, Rentability>>({});
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [open, setOpen] = useState(false);
  const [yieldFor, setYieldFor] = useState<InvestmentAccount | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Onda 2b-i: as contas de aplicação disponíveis para vínculo. Carregadas UMA vez aqui e passadas
  // aos dois modais — refazer o GET dentro de cada um daria duas listas que podem divergir.
  const [contas, setContas] = useState<BankAccount[]>([]);

  const hasPeriod = Boolean(start && end);

  const load = useCallback(async () => {
    const { data } = await api.get<InvestmentAccount[]>("/investments");
    setAccounts(data);
    const { data: bancarias } = await api.get<BankAccount[]>("/bank/accounts");
    setContas(contasDeAplicacao(bancarias));
    const params = hasPeriod ? { start, end } : undefined;
    const entries = await Promise.all(
      data.map(async (a) => {
        const { data: r } = await api.get<Rentability>(`/investments/${a.id}/rentability`, {
          params,
        });
        return [a.id, r] as const;
      }),
    );
    setRentability(Object.fromEntries(entries));
  }, [hasPeriod, start, end]);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction("Nova conta de investimento", useCallback(() => setOpen(true), []));

  const hasAny = accounts.length > 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Investimentos</p>
          <h1 className="text-2xl font-bold text-neutral-800">Investimentos</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Acompanhe suas aplicações (principal, rendimento e rentabilidade). O rendimento entra
            como receita financeira na DRE — não é venda com split.
          </p>
        </div>
        <div className="flex items-end gap-2">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">De</span>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-neutral-600">Até</span>
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
            />
          </label>
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {!hasAny && (
        <p className="rounded-2xl bg-white p-8 text-center text-sm text-neutral-400 shadow-sm">
          Nenhuma conta de investimento ainda. Clique em "Nova conta de investimento".
        </p>
      )}

      <div className="space-y-3">
        {accounts.map((a) => {
          const r = rentability[a.id];
          return (
            <div key={a.id} className="rounded-2xl bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold text-neutral-800">{a.name}</h2>
                  <p className="text-xs text-neutral-500">
                    {[a.kind, a.index_rate_label].filter(Boolean).join(" · ") || "Aplicação"}
                  </p>
                </div>
                <button
                  onClick={() => setYieldFor(a)}
                  className="inline-flex items-center gap-1.5 rounded-pill border border-accent-200 bg-accent-50 px-3 py-2 text-sm font-medium text-accent-700 hover:bg-accent-100"
                >
                  <TrendingUp size={15} />
                  Registrar rendimento
                </button>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-5">
                <Stat
                  label="Conta bancária"
                  value={rotuloDoVinculo(a, contas)}
                  tone={a.bank_account_id ? undefined : "text-amber-700"}
                />
                <Stat label="Principal" value={formatBRL(a.principal_cents)} />
                <Stat label="Rendimento acumulado" value={formatBRL(a.accrued_yield_cents)} />
                <Stat
                  label="Rentabilidade total"
                  value={formatPct(r ? r.total_rentability_pct : null)}
                  tone="text-accent-700"
                />
                <Stat
                  label={hasPeriod ? "Rentabilidade no período" : "Rendimento no período"}
                  value={
                    hasPeriod
                      ? formatPct(r ? r.period_rentability_pct : null)
                      : formatBRL(r ? r.period_yield_cents : 0)
                  }
                  tone="text-primary-700"
                />
              </div>
            </div>
          );
        })}
      </div>

      <NewAccountModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={load}
        contas={contas}
      />
      <RegisterYieldModal
        account={yieldFor}
        onClose={() => setYieldFor(null)}
        onDone={load}
        onError={setError}
        contas={contas}
      />
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <p className="text-xs text-neutral-500">{label}</p>
      <p className={`text-lg font-semibold ${tone ?? "text-neutral-800"}`}>{value}</p>
    </div>
  );
}

/**
 * O seletor da conta bancária da aplicação (Onda 2b-i). UM componente, dois consumidores — o
 * cadastro e o caminho de recuperação do 409. Duas cópias divergiriam no primeiro ajuste.
 *
 * A lista já chega filtrada por `contasDeAplicacao`: conta corrente não aparece, porque escolhê-la
 * levaria a um 422 depois de o dono já ter decidido.
 */
function SeletorDeConta({
  contas,
  value,
  onChange,
}: {
  contas: BankAccount[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-neutral-600">
        Conta bancária da aplicação
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
      >
        <option value="">Escolha a conta…</option>
        {contas.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {contas.length === 0 && (
        <span className="mt-1 block text-xs text-amber-700">
          Nenhuma conta do tipo aplicação cadastrada. Cadastre-a em Contas &amp; Saldos.
        </span>
      )}
    </label>
  );
}

function NewAccountModal({
  open,
  onClose,
  onCreated,
  contas,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  contas: BankAccount[];
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<string>(SUGGESTED_KINDS[0]);
  const [indexLabel, setIndexLabel] = useState("");
  const [principal, setPrincipal] = useState("");
  const [openedAt, setOpenedAt] = useState("");
  const [bankAccountId, setBankAccountId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      await api.post("/investments", {
        name,
        kind,
        index_rate_label: indexLabel,
        principal_cents: Math.round(Number(principal.replace(",", ".")) * 100) || 0,
        opened_at: openedAt,
        // Onda 2b-i: a aplicação nasce vinculada. Sem isso o dono cadastra e leva um 409 no
        // primeiro rendimento — o beco que o 409 acionável existe justamente para evitar.
        bank_account_id: bankAccountId || null,
      });
      onCreated();
      setName("");
      setIndexLabel("");
      setPrincipal("");
      setOpenedAt("");
      setBankAccountId("");
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Nova conta de investimento" open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome" value={name} onChange={setName} placeholder="Ex.: CDB Banco X" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo de aplicação</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {SUGGESTED_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <Field
          label="Indexador / taxa (rótulo)"
          value={indexLabel}
          onChange={setIndexLabel}
          placeholder="Ex.: CDI 110%"
        />
        <Field
          label="Principal aplicado (R$)"
          value={principal}
          onChange={setPrincipal}
          type="text"
          placeholder="Ex.: 10000,00"
        />
        <Field label="Data de aplicação" value={openedAt} onChange={setOpenedAt} type="date" />
        <SeletorDeConta contas={contas} value={bankAccountId} onChange={setBankAccountId} />
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !name.trim() || !openedAt}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando..." : "Criar conta"}
        </button>
      </div>
    </Modal>
  );
}

function RegisterYieldModal({
  account,
  onClose,
  onDone,
  onError,
  contas,
}: {
  account: InvestmentAccount | null;
  onClose: () => void;
  onDone: () => void;
  onError: (msg: string) => void;
  contas: BankAccount[];
}) {
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [chartAccountId, setChartAccountId] = useState("");
  const [financeiro, setFinanceiro] = useState<ChartAccount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Onda 2b-i: ligado pelo 409 acionável do backend (`detail.acao === "cadastrar_conta"`).
  const [precisaVincular, setPrecisaVincular] = useState(false);
  const [bankAccountId, setBankAccountId] = useState("");

  // Carrega só as contas do grupo FINANCEIRO (o rendimento é receita financeira — AC2).
  useEffect(() => {
    if (!account) return;
    api
      .get<ChartAccount[]>("/chart-of-accounts", { params: { grupo: "FINANCEIRO" } })
      .then(({ data }) => {
        setFinanceiro(data);
        if (data.length > 0) setChartAccountId(data[0].id);
      });
  }, [account]);

  async function save() {
    if (!account) return;
    setError(null);
    setSaving(true);
    try {
      // Se o 409 pediu o vínculo e o dono acabou de escolher a conta, vincula ANTES de reenviar —
      // assim ele não perde o valor e a data que já digitou. É o que transforma o 409 num desvio
      // de um passo em vez de um beco.
      if (precisaVincular && bankAccountId) {
        await api.patch(`/investments/${account.id}`, { bank_account_id: bankAccountId });
        setPrecisaVincular(false);
      }
      await api.post(`/investments/${account.id}/yield`, {
        amount_cents: Math.round(Number(amount.replace(",", ".")) * 100),
        date,
        chart_account_id: chartAccountId || null,
      });
      onDone();
      setAmount("");
      setDate("");
      setBankAccountId("");
      onClose();
    } catch (err) {
      // O 409 acionável não é erro de tela: é um pedido de dado que falta, com o caminho junto.
      // Por isso ele NÃO sobe para `onError` (a faixa vermelha da página) — fica no modal, ao
      // lado do campo que o resolve.
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data
        ?.detail;
      if (
        typeof detail === "object" &&
        detail !== null &&
        (detail as { acao?: string }).acao === "cadastrar_conta"
      ) {
        setPrecisaVincular(true);
        setError((detail as { mensagem?: string }).mensagem ?? null);
        return;
      }
      const msg = apiErrorMessage(err);
      setError(msg);
      onError(msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Registrar rendimento" open={Boolean(account)} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-neutral-500">
          O rendimento entra como receita no grupo Financeiro (DRE), sem split de Carteira.
        </p>
        <Field
          label="Valor do rendimento (R$)"
          value={amount}
          onChange={setAmount}
          placeholder="Ex.: 120,00"
        />
        <Field label="Data (competência)" value={date} onChange={setDate} type="date" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            Categoria (grupo Financeiro)
          </span>
          <select
            value={chartAccountId}
            onChange={(e) => setChartAccountId(e.target.value)}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {financeiro.length === 0 && <option value="">(crie uma categoria no plano de contas)</option>}
            {financeiro.map((c) => (
              <option key={c.id} value={c.id}>
                {c.categoria}
              </option>
            ))}
          </select>
        </label>
        {precisaVincular && (
          <SeletorDeConta contas={contas} value={bankAccountId} onChange={setBankAccountId} />
        )}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          onClick={save}
          disabled={saving || !amount.trim() || !date || (precisaVincular && !bankAccountId)}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Registrando..." : "Registrar rendimento"}
        </button>
      </div>
    </Modal>
  );
}
