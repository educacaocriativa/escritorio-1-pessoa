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
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { today } from "../../lib/datetime";
import { useFuso } from "../../store/auth";
import { usePrimaryAction } from "../../store/pageActions";
// ⚠️ O cadastro/edição de conta MUDOU DE ARQUIVO na Story 8.13 (`./AccountModal`), sem mudar de
// comportamento: o fluxo "409 acionável → cadastro embutido → retoma a baixa" das telas de baixa
// precisa do mesmo formulário, com o aviso pró-ativo e a guarda do recuo da 8.11 intactos.
import AccountModal from "./AccountModal";
import {
  acaoBaixarPayable,
  avisoDestinoAplicacao,
  type BankAccount,
  type BankBalanceCheckpoint,
  type BankTransaction,
  centsToInput,
  contasAtivas,
  type DuplicataAcionavel,
  formatBRL,
  formatDateBR,
  impedimentoDaTransferencia,
  isIgnored,
  kindDaTransferencia,
  kindLabel,
  motivoDeNaoEditar,
  naturezaParaEnvio,
  operationNatureLabel,
  OPERATION_NATURE_OUTRO,
  ROTA_MOVIMENTOS,
  OPERATION_NATURE_TRANSFERENCIA,
  OPERATION_NATURES,
  origemLabel,
  parseCentsBRL,
  podeEditarOsFatosDoMovimento,
  ponteiroDaTransferencia,
  type ResumoSaldo,
  resumoSaldos,
  saldoApuradoEm,
  signedAmountView,
  SOURCE_TRANSFER,
  statusLabel,
  TRANSFERIR_LABEL,
} from "./contas";
import PeriodPicker from "./PeriodPicker";
import { type PeriodRange, resolvePeriod } from "./periodRange";

/**
 * A classe das ações de uma conta. **Uma constante, sete consumidores.**
 *
 * `min-h-[44px]` não é estética: eram sete links de **16px** de altura, e "Arquivar" (destrutiva)
 * ficava a 4px de "Editar" — a classe de defeito do PR #56, onde um controle pequeno demais fez
 * uma conta real ser marcada como paga sem o dono ver. O padding cresce, a fonte não: o cartão
 * fica mais alto e a rolagem vertical é nativa e gratuita; errar o alvo de "Arquivar" não é.
 */
const ACAO_DA_CONTA =
  "inline-flex min-h-[44px] items-center gap-1 px-1 text-neutral-600 hover:text-primary-600";

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
  // Story 8.18 — a transferência é sobre um PAR de contas, então o estado é "está aberto, com esta
  // conta pré-selecionada como origem" (ou `""` quando o gesto veio do cabeçalho, sem conta).
  const [transferindoDe, setTransferindoDe] = useState<string | null>(null);

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
            // `Array.isArray`, e não `cps.data[0] ?? null` (issue #179): indexar um payload fora
            // do formato devolve lixo *truthy* (numa string, `[0]` é o primeiro CARACTERE), que
            // vira o `checkpoint` do cartão e chega a `formatDateBR`/`formatBRL`.
            return [a.id, Array.isArray(cps.data) ? (cps.data[0] ?? null) : null] as const;
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

  /**
   * Elege a conta principal — o destino do saque da Carteira (Onda 3).
   *
   * ⚠️ Sem confirmação, de propósito: ao contrário de arquivar, isto é reversível num clique e não
   * move dinheiro nenhum. O que ele decide é PARA ONDE o dinheiro vai quando o dono sacar — e a
   * confirmação de verdade acontece lá, no botão de sacar.
   */
  async function tornarPrincipal(a: BankAccount) {
    try {
      await api.post(`/bank/accounts/${a.id}/set-primary`);
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
        <div className="flex flex-wrap items-center gap-4">
          {/* Story 8.18 — a transferência mora AQUI, sem tela nova: ela é sobre onde o dinheiro
              está, que é a pergunta desta página. Só aparece com duas contas ativas, porque com
              uma só não há para onde transferir e o botão seria uma promessa vazia. */}
          {contasAtivas(accounts).length >= 2 && (
            <button
              type="button"
              onClick={() => setTransferindoDe("")}
              className="inline-flex min-h-[44px] items-center gap-1 rounded-pill border border-neutral-200 px-4 py-1.5 text-sm font-medium text-neutral-600 hover:border-primary-300 hover:text-primary-600"
            >
              <ArrowLeftRight size={14} /> {TRANSFERIR_LABEL}
            </button>
          )}
          <label className="flex min-h-[44px] items-center gap-3 text-sm text-neutral-600">
            <input
              type="checkbox"
              className="h-5 w-5 shrink-0"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
            />
            Mostrar arquivadas
          </label>
        </div>
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
                onTransfer={
                  contasAtivas(accounts).length >= 2 ? () => setTransferindoDe(a.id) : null
                }
                onArchive={() => arquivar(a)}
                onSetPrimary={() => tornarPrincipal(a)}
              >
                {/* ⚠️ Os movimentos moram DENTRO do cartão da conta, e não no fim da página.
                    Enquanto o painel era irmão desta lista, abrir a 1ª conta o jogava DEPOIS de
                    todas as outras — e no caminho de volta até ele havia N rodapés "Lançar
                    movimento" de contas diferentes. Em 13/08/2026 o dono clicou no que estava mais
                    perto do painel que estava lendo, e o dinheiro entrou na conta errada. Aqui o
                    único "Lançar movimento" vizinho do painel é o da conta do painel. */}
                {selectedId === a.id && (
                  <AccountDetail
                    account={a}
                    onChanged={load}
                    onDeclare={() => setDeclarando(a)}
                    onLaunch={() => setLancando(a)}
                  />
                )}
              </AccountCard>
            ))}
          </ul>
        </section>
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
      <TransferirModal
        open={transferindoDe !== null}
        accounts={accounts}
        origemInicialId={transferindoDe ?? ""}
        onClose={() => setTransferindoDe(null)}
        onSaved={(origemId) => {
          load();
          // Abre a conta de ORIGEM: é lá que o dono espera ver a saída que ele acabou de registrar.
          setSelectedId(origemId);
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
  // ⚠️ **A data de apuração é a do TENANT** (#136). Era `hojeISO()` — o dia do navegador —, e num
  // dono a leste o card anunciava um saldo "apurado em" um dia que a empresa ainda não vivera.
  const hoje = today(useFuso());
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
        Somas das contas ativas, apuradas em {formatDateBR(hoje)}. A lista abaixo mostra conta
        por conta — o total nunca aparece sozinho.
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
  onTransfer,
  onArchive,
  onSetPrimary,
  children,
}: {
  account: BankAccount;
  checkpoint: BankBalanceCheckpoint | null;
  selected: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDeclare: () => void;
  onLaunch: () => void;
  /** `null` = não há segunda conta ativa, então não há para onde transferir (Story 8.18). */
  onTransfer: (() => void) | null;
  onArchive: () => void;
  onSetPrimary: () => void;
  /** O painel de movimentos da conta, quando ela está aberta — renderizado DENTRO deste cartão. */
  children?: ReactNode;
}) {
  const arquivada = account.archived_at !== null;
  // "Saldo em {dia}" no fuso do TENANT (#136) — o corte de data do saldo derivado é do backend,
  // que já usa `hoje_do_tenant`; rotulá-lo com o dia do navegador dizia um dia diferente do que
  // o número representa.
  const hoje = today(useFuso());
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
          {/* Story 8.10 — a DATA em que este número foi apurado, colada nele pelo mesmo motivo que
              a origem: um saldo sem a data em que foi apurado é um número que não dá para conferir.
              Até a 8.10 não havia data a mostrar, porque o saldo era "todo o histórico". */}
          <p className="text-xs text-neutral-400">{saldoApuradoEm(hoje)}</p>
          <p className="mt-1 text-xs text-neutral-500">
            {checkpoint
              ? `Saldo declarado em ${formatDateBR(checkpoint.reference_date)}: ${formatBRL(checkpoint.balance_cents)}`
              : "Nenhum saldo declarado ainda"}
          </p>
        </div>
      </div>

      {/* `gap-y` saiu: os 44px de `ACAO_DA_CONTA` já dão o respiro vertical entre as linhas. */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 border-t border-neutral-50 pt-3 text-xs font-medium">
        {!arquivada && (
          <>
            <button
              type="button"
              onClick={onDeclare}
              className={ACAO_DA_CONTA}
            >
              <Wallet size={14} /> Declarar saldo
            </button>
            <button
              type="button"
              onClick={onLaunch}
              className={ACAO_DA_CONTA}
            >
              <ArrowLeftRight size={14} /> Lançar movimento
            </button>
            {onTransfer && (
              <button
                type="button"
                onClick={onTransfer}
                className={ACAO_DA_CONTA}
              >
                <ArrowLeftRight size={14} /> {TRANSFERIR_LABEL}
              </button>
            )}
          </>
        )}
        <Link
          to={`/financeiro/conferencia?account_id=${account.id}`}
          className={ACAO_DA_CONTA}
        >
          <ScanSearch size={14} /> Conferir
        </Link>
        <button
          type="button"
          onClick={onToggle}
          className={ACAO_DA_CONTA}
        >
          {selected ? "Ocultar movimentos" : "Ver movimentos"}
        </button>
        {!arquivada && (
          <>
            <button
              type="button"
              onClick={onEdit}
              className={ACAO_DA_CONTA}
            >
              <Pencil size={14} /> Editar
            </button>
            {/* Onda 3 — a conta principal é o destino do saque da Carteira. Só aparece para quem
                ainda NÃO é principal: oferecer "tornar principal" na conta que já é seria uma ação
                sem efeito, e o selo ao lado do nome já diz qual é. */}
            {!account.is_primary && (
              <button
                type="button"
                onClick={onSetPrimary}
                className="inline-flex items-center gap-1 text-neutral-600 hover:text-primary-600"
              >
                <Star size={14} /> Tornar principal
              </button>
            )}
            <button
              type="button"
              onClick={onArchive}
              className={`${ACAO_DA_CONTA} hover:text-danger`}
            >
              <Archive size={14} /> Arquivar
            </button>
          </>
        )}
      </div>
      {children}
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
        api.get<BankTransaction[]>(ROTA_MOVIMENTOS, {
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

  /**
   * Story 8.18 (AC8) — desfazer a transferência a partir de UMA das pernas.
   *
   * ⚠️ **O gesto é sobre o LANÇAMENTO, e a frase diz isso.** As duas pernas somem juntas; oferecer
   * "apagar este movimento" seria prometer algo que a Regra da Origem (c) não permite (o movimento é
   * espelho do lançamento, não uma linha independente). É por isso que a confirmação nomeia as duas
   * contas em vez de dizer "remover linha".
   */
  async function desfazerTransferencia(tx: BankTransaction) {
    if (!tx.transfer_id) return;
    if (
      !confirm(
        "Desfazer esta transferência? As DUAS pernas — a saída na conta de origem e a entrada na " +
          "de destino — são apagadas juntas, e os dois saldos voltam ao que eram. A operação fica " +
          "registrada na trilha de auditoria.",
      )
    ) {
      return;
    }
    setError(null);
    try {
      await api.delete(`/bank/transfers/${tx.transfer_id}`);
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
    // Sem `bg-white`/`shadow-sm`/`rounded-2xl`: isto não é mais um cartão solto no fim da página —
    // é uma seção do cartão da conta, separada das ações dela por uma borda.
    <section className="mt-4 space-y-4 border-t border-neutral-100 pt-4">
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
        //
        // ⚠️ `relative` NÃO é enfeite (#130). O rótulo `sr-only` do valor ("Saída: ") é
        // `position: absolute`, e sem ancestral posicionado o seu bloco contêiner é a página —
        // então ele NÃO é recortado por este deslizador e passa a contar no `scrollWidth` do
        // documento. Medido: a PÁGINA inteira rolando de lado até **879px** numa viewport de 360,
        // por causa de um rótulo que ninguém vê. Com `relative`, o recorte volta a ser este `div`,
        // que é o único lugar onde a rolagem lateral é legítima.
        <div className="relative overflow-x-auto">
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
                  onDesfazerTransferencia={() => desfazerTransferencia(tx)}
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
  onDesfazerTransferencia,
}: {
  tx: BankTransaction;
  onEdit: () => void;
  onIgnore: () => void;
  onUnignore: () => void;
  onDesfazerTransferencia: () => void;
}) {
  const ignorado = isIgnored(tx);
  const valor = signedAmountView(tx.amount_cents);
  // Story 8.18 / AC9 — a tela **lê o `source`**; ela não conhece a regra. O backend recusa com 422
  // de todo jeito (`service._recusa_se_origem_do_sistema`); o que a UI faz é não oferecer um botão
  // que ela sabe que vai falhar — oferecer e falhar treina o dono a ignorar mensagens de erro.
  const editavel = podeEditarOsFatosDoMovimento(tx);
  const motivo = motivoDeNaoEditar(tx);
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
        {/* A finalidade (Story 8.17), quando houver. Movimento legado nasceu com `NULL` e continua
            legítimo: aqui ele simplesmente **não mostra a linha** — nada de "não informado", que
            transformaria um dado ausente num defeito aparente e pediria preenchimento retroativo
            (AC7: nada automático sobre o `source='manual'` que já existe). */}
        {tx.operation_nature && (
          <span className="block text-[11px] text-neutral-400">
            {operationNatureLabel(tx.operation_nature)}
          </span>
        )}
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
      <td className="py-2.5 text-xs font-medium">
        {editavel ? (
          <span className="flex gap-3">
            <button
              type="button"
              onClick={onEdit}
              className="text-neutral-500 hover:text-primary-600"
            >
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
              <button
                type="button"
                onClick={onIgnore}
                className="text-neutral-500 hover:text-danger"
              >
                Ignorar
              </button>
            )}
          </span>
        ) : (
          <span className="flex flex-col gap-1">
            {/* A frase existe porque uma linha SEM botão e SEM explicação é lida como bug da tela.
                Ela diz o porquê e diz o que fazer — a diferença entre restrição e parede. */}
            <span className="max-w-xs font-normal text-[11px] text-neutral-400">{motivo}</span>
            {tx.source === SOURCE_TRANSFER && tx.transfer_id && (
              <button
                type="button"
                onClick={onDesfazerTransferencia}
                className="self-start text-neutral-500 hover:text-danger"
              >
                Desfazer transferência
              </button>
            )}
          </span>
        )}
      </td>
    </tr>
  );
}

// ── Modais ───────────────────────────────────────────────────────────────────────────────────

function DeclararSaldoModal({
  account,
  onClose,
  onSaved,
}: {
  account: BankAccount | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Um relógio só, e é o do tenant (#136): o default do campo e o reset do efeito abaixo.
  const fuso = useFuso();
  const [referenceDate, setReferenceDate] = useState(() => today(fuso));
  const [balance, setBalance] = useState("0,00");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!account) return;
    setReferenceDate(today(fuso));
    setBalance(centsToInput(account.saldo_derivado_cents));
    setError(null);
  }, [account, fuso]);

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
      // Na CAIXA (#123). O nome da conta é digitado pelo dono e entra no título: é a exposição
      // do #119, e recorte no conteúdo deixaria justamente o título fora da medição.
      testId="modal-declarar-saldo"
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
  // Um relógio só, e é o do tenant (#136).
  const fuso = useFuso();
  const [postedAt, setPostedAt] = useState(() => today(fuso));
  const [entrada, setEntrada] = useState(false);
  const [value, setValue] = useState("0,00");
  const [description, setDescription] = useState("");
  // Story 8.17 — *"para que serve este movimento?"*. Obrigatório, com a válvula de texto livre.
  const [natureza, setNatureza] = useState("");
  const [naturezaLivre, setNaturezaLivre] = useState("");
  const [error, setError] = useState<string | null>(null);
  // O 409 acionável da contagem dupla. Enquanto ele existe, o formulário CONTINUA na tela com tudo
  // o que foi digitado (AC8) — um 409 que apaga o formulário treina o usuário a marcar "é outro
  // pagamento" sem ler.
  const [duplicata, setDuplicata] = useState<DuplicataAcionavel | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!account) return;
    setPostedAt(today(fuso));
    // Saída é o default: o foco declarado do épico é achar SAÍDA não lançada (REQ-14).
    setEntrada(false);
    setValue("0,00");
    setDescription("");
    // Nada pré-selecionado: a pergunta é "para que serve", e responder por ele seria inventar.
    setNatureza("");
    setNaturezaLivre("");
    setError(null);
    setDuplicata(null);
  }, [account, fuso]);

  const cents = parseCentsBRL(value);
  // O valor COM SINAL — calculado uma vez e usado tanto no resumo quanto no envio, para que o que
  // o usuário lê antes de clicar seja literalmente o que vai para a API.
  const assinado = entrada ? Math.abs(cents) : -Math.abs(cents);
  const previa = signedAmountView(assinado);
  const operationNature = naturezaParaEnvio(natureza, naturezaLivre);
  // ⚠️ **Obrigatório na TELA, aceito vazio pela API** — e a assimetria é deliberada. O campo é
  // nullable no banco e movimento legado nasceu com `NULL`; forçar preenchimento no backend
  // quebraria a edição de tudo o que já existe (AC7). A curadoria é de UI.
  const naturezaPendente = operationNature === null;
  // Ponteiro para a transferência de verdade. **`true` a partir da Story 8.18**: ela existe agora
  // (`POST /bank/transfers` + o modal desta tela), e a 8.17 deixou escrito que quem a implementasse
  // trocaria o argumento aqui, no único ponto de chamada.
  const ponteiro =
    natureza === OPERATION_NATURE_TRANSFERENCIA ? ponteiroDaTransferencia(true) : null;

  async function save(confirmarAvulso = false) {
    if (!account) return;
    setError(null);
    setSaving(true);
    try {
      await api.post(`/bank/accounts/${account.id}/transactions`, {
        posted_at: postedAt,
        // O SINAL é o dado (8.3): entrada positiva, saída negativa. O backend recusa 0.
        amount_cents: assinado,
        description,
        operation_nature: operationNature,
        // Só viaja como `true` quando o usuário respondeu "é outro pagamento" ao 409 (AC5).
        confirmar_avulso: confirmarAvulso,
      });
      onSaved();
      onClose();
    } catch (err) {
      // Reconhecido pelo `acao`, nunca por substring da mensagem (contrato da 8.12, reusado aqui).
      const acionavel = acaoBaixarPayable(err);
      if (acionavel) setDuplicata(acionavel);
      else setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={account ? `Lançar movimento — ${account.name}` : "Lançar movimento"}
      open={account !== null}
      onClose={onClose}
      // Na CAIXA (#123) — mesmo motivo do `DeclararSaldoModal` acima.
      testId="modal-lancar-movimento"
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
        {/*
          A curadoria (AC1): o formulário deixa de ser "novo movimento" e pergunta a FINALIDADE.
          A lista é curta e sugerida; "Outro (descreva)" é a válvula obrigatória — a API aceita
          texto livre e recusar um fato bancário legítimo é o defeito que esta story combate.
        */}
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Para que serve</span>
          <select
            value={natureza}
            onChange={(e) => setNatureza(e.target.value)}
            aria-label="Para que serve este movimento"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            <option value="">Escolha…</option>
            {OPERATION_NATURES.map(([valor, rotulo]) => (
              <option key={valor} value={valor}>
                {rotulo}
              </option>
            ))}
            <option value={OPERATION_NATURE_OUTRO}>Outro (descreva)</option>
          </select>
        </label>
        {ponteiro && <p className="rounded-lg bg-neutral-50 p-2 text-xs text-neutral-600">{ponteiro}</p>}
        {natureza === OPERATION_NATURE_OUTRO && (
          <Field
            label="Descreva a finalidade"
            value={naturezaLivre}
            onChange={setNaturezaLivre}
            placeholder="Ex.: estorno de tarifa"
          />
        )}
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
        {/*
          O 409 acionável: a frase vem da API (uma redação, um lugar) e as DUAS ações ficam no
          mesmo bloco visível, logo acima do botão — nenhuma pré-selecionada, e o formulário
          preservado atrás (AC8, lições dos PRs #56 e #58 em ~360px).
        */}
        {duplicata && (
          <div className="space-y-2 rounded-lg bg-amber-50 p-3">
            <p className="text-sm text-neutral-800">{duplicata.mensagem}</p>
            <div className="flex flex-col gap-2">
              <Link
                to="/pagar"
                className="rounded-pill bg-primary-500 px-3 py-2 text-center text-sm font-semibold text-white transition hover:bg-primary-600"
              >
                Dar baixa nessa conta
              </Link>
              <button
                type="button"
                onClick={() => save(true)}
                disabled={saving}
                className="rounded-pill border border-neutral-300 px-3 py-2 text-sm font-semibold text-neutral-700 transition hover:bg-neutral-50 disabled:opacity-60"
              >
                É outro pagamento
              </button>
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={() => save()}
          disabled={saving || cents === 0 || naturezaPendente}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {saving ? "Salvando…" : "Lançar movimento"}
        </button>
      </div>
    </Modal>
  );
}

/**
 * **Transferir entre contas** (Story 8.18, AC10) — dentro de Contas & Saldos, sem tela nova.
 *
 * Três decisões de tela que não são estéticas:
 *
 * 1. **Não existe `<select>` de "tipo de transferência".** O `kind` é **derivado** dos tipos das
 *    duas contas (`kindDaTransferencia`): um terceiro campo dizendo o que os dois primeiros já dizem
 *    poderia discordar deles, e não haveria regra escrita em lugar nenhum sobre quem vence.
 * 2. **O aviso da aplicação vem ANTES de confirmar** (`avisoDestinoAplicacao`), e é obrigatório —
 *    transferir para a aplicação derruba o "Disponível como caixa" e o saldo de partida da Projeção.
 *    É correto e é a primeira vez que uma ação do dono encurta o runway sem nada ter sido pago.
 * 3. **O resumo, o aviso e o botão ficam no MESMO bloco visível** (lições dos PRs #56 e #58 em
 *    ~360px): um checkbox/aviso que só aparece depois de rolar é um aviso que não existe.
 */
function TransferirModal({
  open,
  accounts,
  origemInicialId,
  onClose,
  onSaved,
}: {
  open: boolean;
  accounts: BankAccount[];
  origemInicialId: string;
  onClose: () => void;
  onSaved: (origemId: string) => void;
}) {
  const [fromId, setFromId] = useState("");
  const [toId, setToId] = useState("");
  const [value, setValue] = useState("0,00");
  // ⚠️ **O MESMO relógio preenche o campo e valida o campo** (#136). Antes, o default vinha daqui
  // (`hojeISO()`, navegador) e a guarda de data futura vinha de DENTRO de
  // `impedimentoDaTransferencia`, que chamava `hojeISO()` por conta própria: dois relógios numa
  // função "pura". Agora o hoje do tenant é resolvido uma vez e passado adiante.
  const fuso = useFuso();
  const [postedAt, setPostedAt] = useState(() => today(fuso));
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Só contas ATIVAS: a arquivada não recebe lançamento novo (o backend recusa com 422), e
  // oferecê-la no seletor seria montar uma parede um clique adiante.
  const elegiveis = useMemo(() => contasAtivas(accounts), [accounts]);

  useEffect(() => {
    if (!open) return;
    const origem = origemInicialId || elegiveis[0]?.id || "";
    setFromId(origem);
    // O destino nasce na primeira conta que NÃO é a origem — nunca igual a ela, que é 422.
    setToId(elegiveis.find((a) => a.id !== origem)?.id ?? "");
    setValue("0,00");
    setPostedAt(today(fuso));
    setDescription("");
    setError(null);
  }, [open, origemInicialId, elegiveis, fuso]);

  const origem = elegiveis.find((a) => a.id === fromId) ?? null;
  const destino = elegiveis.find((a) => a.id === toId) ?? null;
  const cents = parseCentsBRL(value);
  const impedimento = impedimentoDaTransferencia(origem, destino, cents, postedAt, today(fuso));
  const aviso = avisoDestinoAplicacao(destino);

  async function save() {
    if (!origem || !destino) return;
    setError(null);
    setSaving(true);
    try {
      await api.post("/bank/transfers", {
        from_account_id: origem.id,
        to_account_id: destino.id,
        // SEMPRE POSITIVO: o sinal vive nas pernas, e é o backend quem o aplica.
        amount_cents: cents,
        posted_at: postedAt,
        kind: kindDaTransferencia(origem.kind, destino.kind),
        description,
      });
      onSaved(origem.id);
      onClose();
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={TRANSFERIR_LABEL}
      open={open}
      onClose={onClose}
      // Na CAIXA (#123/#130). Aqui o título é CONSTANTE, então o controle positivo deste modal
      // NÃO é a mutação do `min-w-0` — é a isca no cabeçalho (ver `contas-modais-360.spec.ts`).
      // O que o dono digita e chega à tela são os nomes de conta nos dois seletores.
      testId="modal-transferir"
    >
      <div className="space-y-3">
        <p className="text-sm text-neutral-600">
          Dinheiro que foi de uma conta sua para outra. <strong>Não é receita nem despesa</strong> —
          a sua DRE não muda; o que muda são os saldos das duas contas.
        </p>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Sai de</span>
          <select
            value={fromId}
            onChange={(e) => setFromId(e.target.value)}
            aria-label="Conta de origem"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {elegiveis.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({kindLabel(a.kind)}) — {formatBRL(a.saldo_derivado_cents)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Entra em</span>
          <select
            value={toId}
            onChange={(e) => setToId(e.target.value)}
            aria-label="Conta de destino"
            className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-primary-400"
          >
            {elegiveis.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({kindLabel(a.kind)}) — {formatBRL(a.saldo_derivado_cents)}
              </option>
            ))}
          </select>
        </label>
        <Field label="Valor (R$)" value={value} onChange={setValue} />
        <Field label="Data" value={postedAt} onChange={setPostedAt} type="date" />
        <Field
          label="Descrição (opcional)"
          value={description}
          onChange={setDescription}
          placeholder="Ex.: reserva de emergência"
        />
        {/* ── O bloco fixo: resumo + aviso + impedimento + botão, fisicamente inseparáveis ── */}
        {/* `break-words`: os dois nomes de conta são DIGITADOS pelo dono (120 chars em
            `bank/schemas.py`) e entram aqui em negrito. Sem ele, um nome colado sem espaço não
            tem onde quebrar e a tinta vaza da caixa — medido em 153.8px fora numa viewport de
            360 (#130). É o defeito do #119 pela porta do CORPO do modal, e não do cabeçalho. */}
        <p className="break-words rounded-lg bg-neutral-50 p-2 text-xs text-neutral-600">
          {origem && destino ? (
            <>
              Sai <strong>{formatBRL(cents)}</strong> de <strong>{origem.name}</strong> e entra em{" "}
              <strong>{destino.name}</strong> em {formatDateBR(postedAt)}. Duas linhas nascem
              juntas, uma em cada extrato.
            </>
          ) : (
            "Escolha as duas contas."
          )}
        </p>
        {aviso && <p className="rounded-lg bg-amber-50 p-2 text-xs text-neutral-800">{aviso}</p>}
        {impedimento && (
          <p className="rounded-lg bg-neutral-50 p-2 text-xs text-neutral-500">{impedimento}</p>
        )}
        {error && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{error}</p>}
        <button
          type="button"
          onClick={save}
          disabled={saving || impedimento !== null}
          className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
        >
          {/* Rótulo PRÓPRIO, diferente do da ação que abre o modal (`TRANSFERIR_LABEL`): um botão
              de confirmar com o mesmo nome do gatilho é ambíguo para leitor de tela e para teste —
              "cliquei em Transferir entre contas" passaria a ter duas respostas possíveis. */}
          {saving ? "Registrando…" : "Registrar transferência"}
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
    <Modal
      title="Editar movimento"
      open={tx !== null}
      onClose={onClose}
      // Na CAIXA (#123/#130). Título constante; o texto livre aqui é a `raw_description` vinda do
      // banco — que chega COLADA ("PIXENVIADOCPF…") e é o que este modal precisa provar que cabe.
      testId="modal-editar-movimento"
    >
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
          // `break-words`: a descrição vem do BANCO e chega COLADA ("PIXENVIADOCPF12345678900…").
          // Sem ele não há candidato a quebra, o `<p>` não alarga a caixa e a TINTA vaza — medido
          // em 326px fora numa viewport de 360 (#130). `getBoundingClientRect` não vê tinta;
          // `textoForaDaTela` vê, pelo `scrollWidth`.
          <p className="break-words rounded-lg bg-neutral-50 p-2 text-xs text-neutral-500">
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
    <Modal
      title="Ignorar movimento"
      open={tx !== null}
      onClose={onClose}
      // Na CAIXA (#123/#130) — título constante, controle positivo por isca no cabeçalho.
      testId="modal-ignorar-movimento"
    >
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
