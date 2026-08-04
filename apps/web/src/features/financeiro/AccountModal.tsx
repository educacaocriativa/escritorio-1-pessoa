import { useEffect, useState } from "react";
import Modal, { Field } from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import {
  avisoContasPagasAnteriores,
  type BankAccount,
  BANK_ACCOUNT_KINDS,
  centsToInput,
  diaAnteriorISO,
  formatDateBR,
  hojeISO,
  KIND_CHECKING,
  parseCentsBRL,
  type PayablesPaidBefore,
} from "./contas";

/**
 * Cadastro/edição de conta bancária — e as **duas metades** da guarda do `opening_date` (8.11).
 *
 * ⚠️ **Extraído de `ContasSaldosPage.tsx` pela Story 8.13, sem uma linha de comportamento mudada.**
 * O motivo do arquivo próprio: o fluxo *"409 acionável → cadastro embutido → retoma a baixa"* (8.13
 * AC2) precisa do MESMO cadastro em três telas de pagamento, e o AC2 é explícito — *"não
 * reimplemente nem contorne"* o aviso pró-ativo nem a exigência de saldo no recuo. Um formulário
 * "mínimo equivalente" seria uma segunda implementação das duas guardas, que divergiria da primeira
 * no dia em que só uma delas fosse corrigida. A 8.15 (recebimento fora do trilho) reusa este mesmo
 * componente.
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
 * E o aviso pró-ativo (8.11 AC3): antes de salvar, o e1p diz quantas contas **pagas** ficariam fora
 * do extrato com a data escolhida, e oferece a data que as cobre. **Ele oferece a DATA, nunca o
 * saldo** — o saldo é um fato sobre o banco e o e1p confirma, não deriva (AC4 / Regra 5).
 */
export default function AccountModal({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean;
  editing: BankAccount | null;
  onClose: () => void;
  /**
   * `conta` é a conta **gravada** (criada ou editada), quando a API a devolveu.
   *
   * Story 8.13: quem abre este modal a partir do 409 acionável precisa **retomar a baixa com a
   * conta recém-criada já selecionada** — e para isso precisa do `id`. Recarregar a lista e
   * "adivinhar" qual é a nova (a mais recente? a primária?) seria um palpite que erra no dia em
   * que o dono cadastra duas contas seguidas. O argumento é opcional: `ContasSaldosPage` passa um
   * `onSaved` sem parâmetro e segue idêntica.
   */
  onSaved: (conta?: BankAccount) => void;
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
      let gravada: BankAccount | undefined;
      if (editing) {
        const res = await api.patch<BankAccount>(`/bank/accounts/${editing.id}`, {
          ...body,
          is_primary: isPrimary,
        });
        gravada = res.data;
      } else {
        const res = await api.post<BankAccount>("/bank/accounts", body);
        gravada = res.data;
        // `is_primary` não existe no corpo de criação (8.2): quando pedido, é um PATCH logo depois.
        if (isPrimary) {
          const patch = await api.patch<BankAccount>(`/bank/accounts/${res.data.id}`, {
            is_primary: true,
          });
          gravada = patch.data;
        }
      }
      onSaved(gravada);
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
