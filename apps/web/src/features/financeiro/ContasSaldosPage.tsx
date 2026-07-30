import {
  Archive,
  ArrowLeftRight,
  Landmark,
  Pencil,
  ScanSearch,
  Star,
  Trash2,
  Wallet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { usePrimaryAction } from "../../store/pageActions";
import {
  avisoContasPagasAnteriores,
  type BankAccount,
  type BankBalanceCheckpoint,
  type BankTransaction,
  BANK_ACCOUNT_KINDS,
  centsToInput,
  diaAnteriorISO,
  formatBRL,
  formatDateBR,
  hojeISO,
  isIgnored,
  KIND_CHECKING,
  kindLabel,
  origemLabel,
  parseCentsBRL,
  type PayablesPaidBefore,
  type ResumoSaldo,
  resumoSaldos,
  signedAmountView,
  statusLabel,
} from "./contas";
import PeriodPicker from "./PeriodPicker";
import { type PeriodRange, resolvePeriod } from "./periodRange";

/**
 * **Contas & Saldos** (Story 8.7) — a tela onde o dono vê **onde está o dinheiro dele**.
 *
 * O rótulo é deliberado: o menu diz *onde está meu dinheiro*, não *tarefa contábil*. O item
 * "Conciliação bancária" **não existe** e não deve passar a existir — ele comunica "software de
 * contabilidade" para todo usuário, inclusive quem nunca abre a tela (design §5.4). A conferência
 * mora fora do menu e é alcançada a partir de um sinal (o do diagnóstico) ou da ação "Conferir"
 * de uma conta, aqui.
 *
 * As quatro coisas da Onda 1, sempre **por conta**: cadastrar/editar/arquivar, ver o saldo derivado
 * com a procedência colada, declarar o saldo de um dia e lançar/corrigir/ignorar um movimento.
 *
 * ⚠️ **Não existe `DELETE` de conta nem de movimento** (nem aqui, nem na API): conta encerrada é
 * arquivada e movimento errado é editado ou ignorado — o histórico é o produto. O único "remover"
 * desta tela é o do saldo declarado (`DELETE /bank/checkpoints/{id}`), que não tem histórico
 * dependente.
 */
const PAGE_SIZE = 25;

export default function ContasSaldosPage() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [ultimoSaldo, setUltimoSaldo] = useState<Record<string, BankBalanceCheckpoint | null>>({});
  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Modais (um estado por gesto — nenhum deles compartilha formulário com outro).
  const [novaConta, setNovaConta] = useState(false);
  const [editando, setEditando] = useState<BankAccount | null>(null);
  const [declarando, setDeclarando] = useState<BankAccount | null>(null);
  const [lancando, setLancando] = useState<BankAccount | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await api.get<BankAccount[]>("/bank/accounts", {
        params: { include_archived: includeArchived },
      });
      setAccounts(res.data);
      // Último saldo declarado por conta: `limit=1` numa rota já paginada e ordenada por
      // `reference_date` desc (8.4). São N chamadas, mas N é o número de contas do dono (poucas) e
      // saem em paralelo — não existe rota em lote e a IV3 proíbe criar uma aqui.
      const pares = await Promise.all(
        res.data.map(async (a) => {
          try {
            const cps = await api.get<BankBalanceCheckpoint[]>(
              `/bank/accounts/${a.id}/checkpoints`,
              { params: { limit: 1 } },
            );
            return [a.id, cps.data[0] ?? null] as const;
          } catch {
            // Falha em UM cartão não derruba a lista inteira: a tela mostra "—" naquele campo.
            return [a.id, null] as const;
          }
        }),
      );
      setUltimoSaldo(Object.fromEntries(pares));
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [includeArchived]);

  useEffect(() => {
    load();
  }, [load]);

  usePrimaryAction(
    "Nova conta",
    useCallback(() => setNovaConta(true), []),
  );

  const resumo = useMemo(() => resumoSaldos(accounts), [accounts]);
  const selecionada = accounts.find((a) => a.id === selectedId) ?? null;

  async function arquivar(a: BankAccount) {
    if (
      !confirm(
        `Arquivar a conta ${a.name}? Os movimentos e saldos declarados dela são preservados — ` +
          "arquivar só a tira das somas e da conferência. Não é possível desarquivar.",
      )
    ) {
      return;
    }
    try {
      await api.post(`/bank/accounts/${a.id}/archive`);
      if (selectedId === a.id) setSelectedId(null);
      load();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-neutral-500">Página / Financeiro / Contas &amp; Saldos</p>
          <h1 className="text-2xl font-bold text-neutral-800">Contas &amp; Saldos</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">
            Onde está o seu dinheiro, conta por conta. Não é fechamento contábil: você confirma o
            saldo que o app do seu banco já mostra, e o e1p diz se está batendo.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-neutral-600">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          Mostrar arquivadas
        </label>
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
      {loading && <p className="text-sm text-neutral-400">Carregando contas…</p>}

      {accounts.length === 0 && !loading ? (
        <div className="rounded-2xl bg-white p-8 text-center shadow-sm">
          <Landmark size={28} className="mx-auto text-neutral-300" />
          <p className="mt-3 text-sm text-neutral-500">
            Nenhuma conta cadastrada ainda. Cadastre a sua conta com o saldo que o app do banco
            mostra hoje — é confirmação, não construção de histórico.
          </p>
          <button
            type="button"
            onClick={() => setNovaConta(true)}
            className="mt-4 rounded-pill bg-accent-400 px-5 py-2 text-sm font-semibold text-white hover:bg-accent-500"
          >
            Cadastrar primeira conta
          </button>
        </div>
      ) : (
        <section className="space-y-3">
          {/* O total mora no TOPO DA PRÓPRIA LISTA: a decomposição por conta está logo abaixo,
              sempre visível, nunca atrás de um "expandir" (AC6 / decisão do fundador F3). */}
          <TotaisCard resumo={resumo} />

          <ul className="space-y-3">
            {accounts.map((a) => (
              <AccountCard
                key={a.id}
                account={a}
                checkpoint={ultimoSaldo[a.id] ?? null}
                selected={selectedId === a.id}
                onToggle={() => setSelectedId(selectedId === a.id ? null : a.id)}
                onEdit={() => setEditando(a)}
                onDeclare={() => setDeclarando(a)}
                onLaunch={() => setLancando(a)}
                onArchive={() => arquivar(a)}
              />
            ))}
          </ul>
        </section>
      )}

      {selecionada && (
        <AccountDetail
          account={selecionada}
          onChanged={load}
          onDeclare={() => setDeclarando(selecionada)}
          onLaunch={() => setLancando(selecionada)}
        />
      )}

      <AccountModal
        open={novaConta || editando !== null}
        editing={editando}
        onClose={() => {
          setNovaConta(false);
          setEditando(null);
        }}
        onSaved={load}
      />
      <DeclararSaldoModal
        account={declarando}
        onClose={() => setDeclarando(null)}
        onSaved={load}
      />
      <LancarMovimentoModal
        account={lancando}
        onClose={() => setLancando(null)}
        onSaved={() => {
          load();
          // Abre a conta lançada para o movimento novo aparecer sem um segundo clique.
          if (lancando) setSelectedId(lancando.id);
        }}
      />
    </div>
  );
}

/**
 * Os totais — **dois rótulos, nunca um número ambíguo** (divergência D-6).
 *
 * A Projeção de Caixa chama de "no banco" uma parcela que exclui as aplicações. Se esta tela
 * chamasse a soma de todas as contas pelo mesmo nome, o dono veria dois números diferentes com o
 * mesmo rótulo em duas telas — e o valor inteiro deste produto é ser testemunha confiável do dado.
 * Aqui os recortes têm nomes próprios e cada um diz o que inclui.
 */
function TotaisCard({ resumo }: { resumo: ResumoSaldo[] }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <div className="flex flex-wrap gap-x-10 gap-y-4">
        {resumo.map((r) => (
          <div key={r.rotulo} className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">
              {r.rotulo}
            </p>
            <p className="mt-0.5 text-2xl font-bold tabular-nums text-neutral-800">
              {formatBRL(r.cents)}
            </p>
            <p className="mt-0.5 max-w-xs text-xs text-neutral-500">{r.explicacao}</p>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-neutral-400">
        Somas das contas ativas. A lista abaixo mostra conta por conta — o total nunca aparece
        sozinho.
      </p>
    </div>
  );
}

function AccountCard({
  account,
  checkpoint,
  selected,
  onToggle,
  onEdit,
  onDeclare,
  onLaunch,
  onArchive,
}: {
  account: BankAccount;
  checkpoint: BankBalanceCheckpoint | null;
  selected: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDeclare: () => void;
  onLaunch: () => void;
  onArchive: () => void;
}) {
  const arquivada = account.archived_at !== null;
  return (
    <li
      className={`rounded-2xl bg-white p-5 shadow-sm ${selected ? "ring-2 ring-primary-200" : ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={
                arquivada
                  ? "font-semibold text-neutral-400 line-through"
                  : "font-semibold text-neutral-800"
              }
            >
              {account.name}
            </span>
            <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
              {kindLabel(account.kind)}
            </span>
            {account.is_primary && (
              <span className="inline-flex items-center gap-1 rounded-pill bg-primary-50 px-2 py-0.5 text-xs text-primary-700">
                <Star size={11} /> Principal
              </span>
            )}
            {arquivada && (
              <span className="rounded-pill bg-neutral-100 px-2 py-0.5 text-xs text-neutral-500">
                Arquivada
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-neutral-500">
            {[account.institution, account.branch && `Ag. ${account.branch}`, account.number]
              .filter(Boolean)
              .join(" · ") || "Sem dados bancários informados"}
          </p>
        </div>

        <div className="text-right">
          <p className="text-xl font-bold tabular-nums text-neutral-800">
            {formatBRL(account.saldo_derivado_cents)}
          </p>
          {/* Procedência COLADA ao número (Regra dos Planos §1.3c) — nenhum saldo sem origem. */}
          <p className="text-xs text-neutral-400">{origemLabel(account.saldo_derivado_origem)}</p>
          <p className="mt-1 text-xs text-neutral-500">
            {checkpoint
              ? `Saldo declarado em ${formatDateBR(checkpoint.reference_date)}: ${formatBRL(checkpoint.balance_cents)}`
              : "Nenhum saldo declarado ainda"}
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-neutral-50 pt-3 text-xs font-medium">
        {!arquivada && (
          <>
            <button
              type="button"
              onClick={onDeclare}
              className="inline-flex items-center gap-1 text-neutral-600 hover:text-primary-600"
            >
              <Wallet size={14} /> Declarar saldo
            </button>
            <button
              type="button"
              onClick={onLaunch}
              className="inline-flex items-center gap-1 text-neutral-600 hover:text-primary-600"
            >
              <ArrowLeftRight size={14} /> Lançar movimento
            </button>
          </>
        )}
        <Link
          to={`/financeiro/conferencia?account_id=${account.id}`}
          className="inline-flex items-center gap-1 text-neutral-600 hover:text-primary-600"
        >
          <ScanSearch size={14} /> Conferir
        </Link>
        <button
          type="button"
          onClick={onToggle}
          className="inline-flex items-center gap-1 text-neutral-600 hover:text-primary-600"
        >
          {selected ? "Ocultar movimentos" : "Ver movimentos"}
        </button>
        {!arquivada && (
          <>
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex items-center gap-1 text-neutral-600 hover:text-primary-600"
            >
              <Pencil size={14} /> Editar
            </button>
            <button
              type="button"
              onClick={onArchive}
              className="inline-flex items-center gap-1 text-neutral-600 hover:text-danger"
            >
              <Archive size={14} /> Arquivar
            </button>
          </>
        )}
      </div>
    </li>
  );
}

/** Movimentos + saldos declarados da conta aberta. */
function AccountDetail({
  account,
  onChanged,
  onDeclare,
  onLaunch,
}: {
  account: BankAccount;
  onChanged: () => void;
  onDeclare: () => void;
  onLaunch: () => void;
}) {
  const [range, setRange] = useState<PeriodRange>(() => resolvePeriod("this_year"));
  const [txs, setTxs] = useState<BankTransaction[]>([]);
  const [checkpoints, setCheckpoints] = useState<BankBalanceCheckpoint[]>([]);
  const [page, setPage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [editando, setEditando] = useState<BankTransaction | null>(null);
  const [ignorando, setIgnorando] = useState<BankTransaction | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [t, c] = await Promise.all([
        api.get<BankTransaction[]>("/bank/transactions", {
          params: {
            bank_account_id: account.id,
            start: range.start,
            end: range.end,
            limit: PAGE_SIZE,
            offset: page * PAGE_SIZE,
          },
        }),
        api.get<BankBalanceCheckpoint[]>(`/bank/accounts/${account.id}/checkpoints`, {
          params: { limit: 12 },
        }),
      ]);
      setTxs(t.data);
      setCheckpoints(c.data);
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }, [account.id, range.start, range.end, page]);

  useEffect(() => {
    load();
  }, [load]);

  // Trocar de conta ou de período recomeça a paginação — senão a página 3 de uma conta abriria
  // vazia na conta seguinte, parecendo "sem movimentos".
  useEffect(() => {
    setPage(0);
  }, [account.id, range.start, range.end]);

  // ⚠️ **As três ações abaixo mexem no saldo calculado, então falhar em silêncio é pior aqui do
  // que numa tela de cadastro** (REL-001, gate da Onda 0+1). Sem o `catch`, a promise rejeitada
  // não rodava `load()` e NADA mudava na tela: o usuário concluía que o clique não pegou — ou,
  // pior, que pegou. "Ignorar" tira dinheiro do saldo derivado; achar que ignorou quando não
  // ignorou é conferir depois um número que não bate, sem ter como saber por quê. Mesmo padrão do
  // resto do arquivo (`AccountModal.save()`): `setError(apiErrorMessage(err))`, e a mensagem é
  // renderizada na seção logo abaixo do cabeçalho.

  async function ignorar(tx: BankTransaction, reason: string) {
    setError(null);
    // Fecha o modal ANTES de saber o desfecho: a mensagem de erro vive na seção, ATRÁS do overlay
    // do modal — mantê-lo aberto numa falha mostraria exatamente o nada de antes. O motivo digitado
    // se perde, e esse é o preço menor: ele é opcional e curto, a informação de que a ação não
    // aconteceu não é.
    setIgnorando(null);
    try {
      await api.post(`/bank/transactions/${tx.id}/ignore`, { reason });
      load();
      onChanged();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function desfazerIgnorar(tx: BankTransaction) {
    setError(null);
    try {
      await api.post(`/bank/transactions/${tx.id}/unignore`);
      load();
      onChanged();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  async function removerDeclaracao(cp: BankBalanceCheckpoint) {
    if (
      !confirm(
        `Remover o saldo declarado de ${formatDateBR(cp.reference_date)} (${formatBRL(cp.balance_cents)})? ` +
          "Isso não altera o saldo calculado — só apaga a declaração que serve de referência.",
      )
    ) {
      return;
    }
    setError(null);
    try {
      await api.delete(`/bank/checkpoints/${cp.id}`);
      load();
      onChanged();
    } catch (err) {
      setError(apiErrorMessage(err));
    }
  }

  return (
    <section className="space-y-4 rounded-2xl bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-neutral-800">Movimentos — {account.name}</h2>
          <p className="text-xs text-neutral-500">
            Movimento ignorado fica fora do saldo calculado, mas não é apagado — "Desfazer ignorar"
            devolve.
          </p>
        </div>
        <PeriodPicker value={range} onChange={setRange} />
      </div>

      {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}

      {txs.length === 0 ? (
        <div className="rounded-xl bg-neutral-50 p-6 text-center">
          <p className="text-sm text-neutral-500">
            Nenhum movimento nesta conta no período selecionado.
          </p>
          <button
            type="button"
            onClick={onLaunch}
            className="mt-3 rounded-pill bg-accent-400 px-4 py-1.5 text-xs font-semibold text-white hover:bg-accent-500"
          >
            Lançar movimento
          </button>
        </div>
      ) : (
        // ⚠️ `overflow-x-auto`, NUNCA `overflow-hidden` (AC8): em tela estreita, cortar a tabela
        // esconde a coluna de ações — foi assim que "Estornar" ficou inalcançável no PR #58.
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="border-b border-neutral-100 text-left text-xs uppercase text-neutral-400">
                <th className="py-2 pr-3 font-medium">Data</th>
                <th className="py-2 pr-3 font-medium">Descrição</th>
                <th className="py-2 pr-3 text-right font-medium">Valor</th>
                <th className="py-2 pr-3 font-medium">Situação</th>
                <th className="py-2 font-medium">Ações</th>
              </tr>
            </thead>
            <tbody>
              {txs.map((tx) => (
                <TransactionRow
                  key={tx.id}
                  tx={tx}
                  onEdit={() => setEditando(tx)}
                  onIgnore={() => setIgnorando(tx)}
                  onUnignore={() => desfazerIgnorar(tx)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-neutral-500">
        <span>Página {page + 1}</span>
        <span className="flex gap-2">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="rounded-pill border border-neutral-200 px-3 py-1 disabled:opacity-40"
          >
            Anteriores
          </button>
          <button
            type="button"
            disabled={txs.length < PAGE_SIZE}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-pill border border-neutral-200 px-3 py-1 disabled:opacity-40"
          >
            Próximos
          </button>
        </span>
      </div>

      <div className="border-t border-neutral-100 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-neutral-800">Saldos declarados</h3>
          <button
            type="button"
            onClick={onDeclare}
            className="rounded-pill border border-neutral-200 px-3 py-1 text-xs font-medium text-neutral-600 hover:border-primary-300 hover:text-primary-600"
          >
            Declarar saldo
          </button>
        </div>
        {checkpoints.length === 0 ? (
          <p className="mt-2 text-xs text-neutral-500">
            Nenhum saldo declarado. Sem ele o e1p não tem contra o que conferir e diz "não sei" — em
            vez de comparar contra zero e inventar uma divergência.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-neutral-50">
            {checkpoints.map((cp) => (
              <li key={cp.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="text-sm text-neutral-700">
                  {formatDateBR(cp.reference_date)} —{" "}
                  <span className="tabular-nums font-medium">{formatBRL(cp.balance_cents)}</span>
                </span>
                <button
                  type="button"
                  onClick={() => removerDeclaracao(cp)}
                  className="inline-flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-danger"
                >
                  <Trash2 size={13} /> Remover declaração
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <EditarMovimentoModal
        tx={editando}
        onClose={() => setEditando(null)}
        onSaved={() => {
          load();
          onChanged();
        }}
      />
      <IgnorarModal
        tx={ignorando}
        onClose={() => setIgnorando(null)}
        onConfirm={(reason) => ignorando && ignorar(ignorando, reason)}
      />
    </section>
  );
}

function TransactionRow({
  tx,
  onEdit,
  onIgnore,
  onUnignore,
}: {
  tx: BankTransaction;
  onEdit: () => void;
  onIgnore: () => void;
  onUnignore: () => void;
}) {
  const ignorado = isIgnored(tx);
  const valor = signedAmountView(tx.amount_cents);
  return (
    <tr className={`border-b border-neutral-50 last:border-0 ${ignorado ? "bg-neutral-50" : ""}`}>
      <td className="whitespace-nowrap py-2.5 pr-3 tabular-nums text-neutral-600">
        {formatDateBR(tx.posted_at)}
      </td>
      {/* `description` vem derivada do backend (`user_description or raw_description`) — a regra
          NÃO é reimplementada aqui (8.3 Task 6). Este texto carrega PII: não copiar para log,
          título de modal nem query string. */}
      <td className={`py-2.5 pr-3 ${ignorado ? "text-neutral-400 line-through" : "text-neutral-800"}`}>
        {tx.description || "—"}
      </td>
      <td
        className={`whitespace-nowrap py-2.5 pr-3 text-right tabular-nums font-medium ${
          ignorado ? "text-neutral-400 line-through" : valor.className
        }`}
      >
        <span className="sr-only">{valor.rotulo}: </span>
        {valor.texto}
      </td>
      <td className="whitespace-nowrap py-2.5 pr-3 text-xs text-neutral-500">
        {statusLabel(tx.status)}
        {ignorado && tx.ignored_reason && (
          <span className="block text-[11px] text-neutral-400">{tx.ignored_reason}</span>
        )}
      </td>
      <td className="whitespace-nowrap py-2.5 text-xs font-medium">
        <span className="flex gap-3">
          <button type="button" onClick={onEdit} className="text-neutral-500 hover:text-primary-600">
            Editar
          </button>
          {ignorado ? (
            <button
              type="button"
              onClick={onUnignore}
              className="text-neutral-500 hover:text-primary-600"
            >
              Desfazer ignorar
            </button>
          ) : (
            <button type="button" onClick={onIgnore} className="text-neutral-500 hover:text-danger">
              Ignorar
            </button>
          )}
        </span>
      </td>
    </tr>
  );
}

// ── Modais ───────────────────────────────────────────────────────────────────────────────────

/**
 * Cadastro/edição de conta — e as **duas metades** da guarda do `opening_date` (Story 8.11).
 *
 * ⚠️ **A metade de backend (422 quando o recuo vem sem `opening_balance_cents`) é necessária e
 * INSUFICIENTE, e a razão está neste arquivo.** Até a 8.11, `save()` mandava
 * `opening_balance_cents` **sempre**, pré-preenchido com o valor antigo (`centsToInput(editing
 * ?.opening_balance_cents ?? 0)`) — nos dois caminhos, POST e PATCH. Pela UI real o campo nunca
 * chegava ausente, o 422 nunca disparava, e recuar a data gravava o **saldo antigo na data nova**:
 * exatamente a divergência inventada que a guarda existe para impedir, o gêmeo do BANK-001 pela
 * porta oposta. Um 422 "obrigatório se ausente" seria, do ponto de vista do usuário do produto,
 * código morto.
 *
 * Por isso, ao **recuar** a data de abertura:
 *  1. o campo de saldo é **limpo** (reaproveitar o valor antigo é proibido — ele era o saldo de
 *     OUTRO dia);
 *  2. o salvar fica **desabilitado** até haver um valor digitado;
 *  3. a frase diz de **qual dia** é o saldo pedido;
 *  4. se ainda assim o campo estiver vazio, ele é **omitido** do PATCH — a UI nunca fabrica um `0`,
 *     e o 422 do backend é quem responde.
 *
 * E o aviso pró-ativo (AC3): antes de salvar, o e1p diz quantas contas **pagas** ficariam fora do
 * extrato com a data escolhida, e oferece a data que as cobre. **Ele oferece a DATA, nunca o
 * saldo** — o saldo é um fato sobre o banco e o e1p confirma, não deriva (AC4 / Regra 5).
 */
function AccountModal({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: BankAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState(KIND_CHECKING);
  const [institution, setInstitution] = useState("");
  const [branch, setBranch] = useState("");
  const [number, setNumber] = useState("");
  const [opening, setOpening] = useState("0,00");
  const [openingDate, setOpeningDate] = useState(hojeISO);
  const [isPrimary, setIsPrimary] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [pagasAntes, setPagasAntes] = useState<PayablesPaidBefore | null>(null);

  useEffect(() => {
    if (!open) return;
    setName(editing?.name ?? "");
    setKind(editing?.kind ?? KIND_CHECKING);
    setInstitution(editing?.institution ?? "");
    setBranch(editing?.branch ?? "");
    setNumber(editing?.number ?? "");
    setOpening(centsToInput(editing?.opening_balance_cents ?? 0));
    setOpeningDate(editing?.opening_date ?? hojeISO());
    setIsPrimary(editing?.is_primary ?? false);
    setError(null);
    setPagasAntes(null);
  }, [open, editing]);

  // **Recuo** = a data escolhida é ANTERIOR à data de abertura atual da conta. Estritamente: data
  // igual não é recuo (o formulário reenvia o corpo inteiro a cada salvamento, e exigir
  // redeclaração para editar o nome seria uma parede no caminho mais banal do produto).
  const recuou = editing !== null && openingDate < editing.opening_date;

  // Ao ENTRAR no estado de recuo, o saldo herdado é apagado — ele era o saldo de OUTRO dia. Ao
  // SAIR, o valor original da conta é restaurado: sem isso, voltar a data para o lugar deixaria o
  // campo vazio e `parseCentsBRL("")` mandaria **0** para a API, zerando o saldo de abertura em
  // silêncio — trocar um bug de saldo por outro.
  useEffect(() => {
    if (!editing) return;
    setOpening(recuou ? "" : centsToInput(editing.opening_balance_cents));
  }, [recuou, editing]);

  const saldoRedeclarado = opening.trim() !== "";

  // Aviso pró-ativo: quantas contas PAGAS ficariam fora do extrato com esta data de abertura.
  //
  // Roda no cadastro (AC3) e também na edição **quando a data recua** — que é justamente o passo 1
  // do mutirão do epic §7.2, onde o dono precisa saber até onde recuar. Na edição sem recuo fica
  // calado: a conta já existe com aquela data, e repetir o aviso a cada abertura do modal seria
  // ruído sobre uma decisão já tomada.
  //
  // ⚠️ **Degrada em SILÊNCIO** (rede, 401, módulo `payables` não permitido): o aviso simplesmente
  // não aparece. Cadastrar conta nunca pode ficar bloqueado por causa dele.
  const querAviso = !editing || recuou;
  useEffect(() => {
    if (!open || !querAviso || !openingDate) {
      setPagasAntes(null);
      return;
    }
    let vivo = true;
    // `type="date"` dispara a cada tecla em alguns navegadores — o debounce evita uma chamada por
    // dígito, e o `vivo` descarta a resposta de uma data que o usuário já abandonou.
    const t = setTimeout(async () => {
      try {
        const res = await api.get<PayablesPaidBefore>("/payables/bills/paid-before", {
          params: { date: openingDate },
        });
        if (vivo) setPagasAntes(res.data);
      } catch {
        if (vivo) setPagasAntes(null);
      }
    }, 300);
    return () => {
      vivo = false;
      clearTimeout(t);
    };
  }, [open, querAviso, openingDate]);

  const aviso = querAviso ? avisoContasPagasAnteriores(pagasAntes, openingDate) : null;
  const dataSugerida =
    aviso && pagasAntes?.oldest_paid_on ? diaAnteriorISO(pagasAntes.oldest_paid_on) : null;

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const body = {
        name,
        kind,
        institution,
        branch,
        number,
        opening_date: openingDate,
        // Ao recuar sem redeclarar, o campo é OMITIDO em vez de mandar um `0` fabricado: quem
        // responde é o 422 do backend, com a mensagem que nomeia as duas datas.
        ...(recuou && !saldoRedeclarado
          ? {}
          : { opening_balance_cents: parseCentsBRL(opening) }),
      };
      if (editing) {
        await api.patch(`/bank/accounts/${editing.id}`, { ...body, is_primary: isPrimary });
      } else {
        const res = await api.post<BankAccount>("/bank/accounts", body);
        // `is_primary` não existe no corpo de criação (8.2): quando pedido, é um PATCH logo depois.
        if (isPrimary) await api.patch(`/bank/accounts/${res.data.id}`, { is_primary: true });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={editing ? "Editar conta" : "Nova conta"} open={open} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome da conta" value={name} onChange={setName} placeholder="Ex.: Itaú PJ" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            aria-label="Tipo de conta"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {BANK_ACCOUNT_KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <Field label="Instituição" value={institution} onChange={setInstitution} placeholder="Itaú" />
        {/* ⚠️ `grid-cols-1` abaixo de `sm`: em ~360px duas colunas espremem o campo de saldo e a
            data de abertura a ponto de o valor digitado ficar ilegível (lição dos PRs #56/#58 —
            elemento fora da área visível já custou duas correções pós-deploy). */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Agência" value={branch} onChange={setBranch} />
          <Field label="Conta" value={number} onChange={setNumber} />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field
            label={
              recuou
                ? `Saldo em ${formatDateBR(openingDate)} (R$) — obrigatório`
                : "Saldo de abertura (R$)"
            }
            value={opening}
            onChange={setOpening}
            placeholder={recuou ? "Informe o saldo daquele dia" : undefined}
          />
          <Field label="Data de abertura" value={openingDate} onChange={setOpeningDate} type="date" />
        </div>

        {/* Metade (b) da guarda: a frase que diz de QUAL dia é o saldo pedido, colada ao campo. */}
        {recuou && editing && (
          <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
            O saldo que você informou era o saldo de{" "}
            <strong>{formatDateBR(editing.opening_date)}</strong>. Para abrir esta conta em{" "}
            <strong>{formatDateBR(openingDate)}</strong>, informe o saldo daquele dia — o número
            está no extrato do seu banco. O e1p não calcula esse valor: ele é a referência externa
            contra a qual tudo o mais é conferido.
          </p>
        )}

        {/* Aviso pró-ativo (AC3): o e1p diz QUAL número ir buscar, e não inventa nenhum. */}
        {aviso && (
          <div className="rounded-lg bg-primary-50 p-2 text-xs text-primary-700">
            <p>{aviso}</p>
            {dataSugerida && dataSugerida < openingDate && (
              <button
                type="button"
                onClick={() => setOpeningDate(dataSugerida)}
                className="mt-2 rounded-pill border border-primary-300 px-3 py-1 text-xs font-semibold text-primary-700 hover:bg-primary-100"
              >
                Abrir em {formatDateBR(dataSugerida)} e informar o saldo daquele dia
              </button>
            )}
          </div>
        )}

        {/* A dica genérica sai de cena durante o recuo: ela manda usar "o saldo de hoje e a data
            de hoje", que é o CONTRÁRIO do que o usuário está fazendo. Duas instruções opostas na
            mesma tela é como se perde a confiança na que está certa — e é altura a menos num modal
            que já tem 9 campos (ver a auditoria de ~360px no Dev Agent Record da 8.11). */}
        {!recuou && (
          <p className="rounded-lg bg-primary-50 p-2 text-xs text-primary-700">
            Use <strong>o saldo que o app do seu banco mostra hoje</strong> e a data de hoje. É
            confirmação, não reconstrução de histórico — você não precisa lançar o passado.
          </p>
        )}
        <label className="flex items-center gap-2 text-sm text-neutral-600">
          <input
            type="checkbox"
            checked={isPrimary}
            onChange={(e) => setIsPrimary(e.target.checked)}
          />
          Conta principal
        </label>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          type="button"
          onClick={save}
          disabled={saving || !name.trim() || (recuou && !saldoRedeclarado)}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando…" : editing ? "Salvar" : "Cadastrar conta"}
        </button>
      </div>
    </Modal>
  );
}

function DeclararSaldoModal({
  account,
  onClose,
  onSaved,
}: {
  account: BankAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [referenceDate, setReferenceDate] = useState(hojeISO);
  const [balance, setBalance] = useState("0,00");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!account) return;
    setReferenceDate(hojeISO());
    setBalance(centsToInput(account.saldo_derivado_cents));
    setError(null);
  }, [account]);

  async function save() {
    if (!account) return;
    setError(null);
    setSaving(true);
    try {
      await api.post(`/bank/accounts/${account.id}/checkpoints`, {
        reference_date: referenceDate,
        balance_cents: parseCentsBRL(balance),
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={account ? `Declarar saldo — ${account.name}` : "Declarar saldo"}
      open={account !== null}
      onClose={onClose}
    >
      <div className="space-y-3">
        <p className="text-sm text-neutral-600">
          O saldo desta conta <strong>no fim deste dia</strong> era…
        </p>
        <Field label="Dia" value={referenceDate} onChange={setReferenceDate} type="date" />
        <Field label="Saldo (R$)" value={balance} onChange={setBalance} />
        <p className="text-xs text-neutral-500">
          Este número não muda o saldo que o e1p calculou — ele é a referência externa contra a qual
          esse cálculo é conferido. Declarar o mesmo dia de novo corrige a declaração anterior.
        </p>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando…" : "Declarar saldo"}
        </button>
      </div>
    </Modal>
  );
}

function LancarMovimentoModal({
  account,
  onClose,
  onSaved,
}: {
  account: BankAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [postedAt, setPostedAt] = useState(hojeISO);
  const [entrada, setEntrada] = useState(false);
  const [value, setValue] = useState("0,00");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!account) return;
    setPostedAt(hojeISO());
    // Saída é o default: o foco declarado do épico é achar SAÍDA não lançada (REQ-14).
    setEntrada(false);
    setValue("0,00");
    setDescription("");
    setError(null);
  }, [account]);

  const cents = parseCentsBRL(value);
  // O valor COM SINAL — calculado uma vez e usado tanto no resumo quanto no envio, para que o que
  // o usuário lê antes de clicar seja literalmente o que vai para a API.
  const assinado = entrada ? Math.abs(cents) : -Math.abs(cents);
  const previa = signedAmountView(assinado);

  async function save() {
    if (!account) return;
    setError(null);
    setSaving(true);
    try {
      await api.post(`/bank/accounts/${account.id}/transactions`, {
        posted_at: postedAt,
        // O SINAL é o dado (8.3): entrada positiva, saída negativa. O backend recusa 0.
        amount_cents: assinado,
        description,
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={account ? `Lançar movimento — ${account.name}` : "Lançar movimento"}
      open={account !== null}
      onClose={onClose}
    >
      <div className="space-y-3">
        <Field label="Data" value={postedAt} onChange={setPostedAt} type="date" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
          <select
            value={entrada ? "entrada" : "saida"}
            onChange={(e) => setEntrada(e.target.value === "entrada")}
            aria-label="Entrada ou saída"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="saida">Saída (dinheiro saiu da conta)</option>
            <option value="entrada">Entrada (dinheiro entrou na conta)</option>
          </select>
        </label>
        <Field label="Valor (R$)" value={value} onChange={setValue} />
        <Field
          label="Descrição"
          value={description}
          onChange={setDescription}
          placeholder="Ex.: Pagamento fornecedor"
        />
        {/* Resumo do que será gravado, colado ao botão que o efetiva (AC8 / lição do PR #58). */}
        <p className="rounded-lg bg-neutral-50 p-2 text-xs text-neutral-600">
          Será lançado como{" "}
          <strong>
            {previa.rotulo} {previa.texto}
          </strong>{" "}
          em {formatDateBR(postedAt)}.
        </p>
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          type="button"
          onClick={save}
          disabled={saving || cents === 0}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando…" : "Lançar movimento"}
        </button>
      </div>
    </Modal>
  );
}

function EditarMovimentoModal({
  tx,
  onClose,
  onSaved,
}: {
  tx: BankTransaction | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [postedAt, setPostedAt] = useState("");
  const [entrada, setEntrada] = useState(false);
  const [value, setValue] = useState("0,00");
  const [userDescription, setUserDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!tx) return;
    setPostedAt(tx.posted_at);
    setEntrada(tx.amount_cents >= 0);
    setValue(centsToInput(Math.abs(tx.amount_cents)));
    setUserDescription(tx.user_description);
    setError(null);
  }, [tx]);

  async function save() {
    if (!tx) return;
    setError(null);
    setSaving(true);
    try {
      const cents = parseCentsBRL(value);
      await api.patch(`/bank/transactions/${tx.id}`, {
        posted_at: postedAt,
        amount_cents: entrada ? Math.abs(cents) : -Math.abs(cents),
        user_description: userDescription,
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Editar movimento" open={tx !== null} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Data" value={postedAt} onChange={setPostedAt} type="date" />
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Tipo</span>
          <select
            value={entrada ? "entrada" : "saida"}
            onChange={(e) => setEntrada(e.target.value === "entrada")}
            aria-label="Entrada ou saída do movimento"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="saida">Saída</option>
            <option value="entrada">Entrada</option>
          </select>
        </label>
        <Field label="Valor (R$)" value={value} onChange={setValue} />
        <Field label="Descrição" value={userDescription} onChange={setUserDescription} />
        {/* `raw_description` é imutável — é a prova documental do que o banco (ou você) disse. */}
        {tx?.raw_description && (
          <p className="rounded-lg bg-neutral-50 p-2 text-xs text-neutral-500">
            Descrição original (não editável): {tx.raw_description}
          </p>
        )}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando…" : "Salvar"}
        </button>
      </div>
    </Modal>
  );
}

function IgnorarModal({
  tx,
  onClose,
  onConfirm,
}: {
  tx: BankTransaction | null;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (tx) setReason("");
  }, [tx]);

  return (
    <Modal title="Ignorar movimento" open={tx !== null} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-neutral-600">
          O movimento sai do saldo calculado, mas <strong>continua no histórico</strong>. Dá para
          desfazer a qualquer momento com "Desfazer ignorar".
        </p>
        <Field
          label="Motivo (opcional)"
          value={reason}
          onChange={setReason}
          placeholder="Ex.: transferência entre contas minhas"
        />
        <button
          type="button"
          onClick={() => onConfirm(reason)}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500"
        >
          Ignorar movimento
        </button>
      </div>
    </Modal>
  );
}
