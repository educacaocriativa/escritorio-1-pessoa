import { useCallback, useEffect, useState } from "react";
import Modal from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import AccountModal from "../financeiro/AccountModal";
import type { BankAccount } from "../financeiro/contas";
import { hojeISO } from "../financeiro/contas";
import {
  acaoCadastrarConta,
  type ContaDeBaixa,
  avisoDeDataFutura,
  contaPreSelecionada,
  contasUtilizaveis,
  nomeDaConta,
  rotuloDaAcao,
  tetoDaDataDeBaixa,
} from "./baixa";

/**
 * **A escolha da baixa** — UM componente, TRÊS telas (Story 8.13, Task 3).
 *
 * `PagarPage`, `ComprovantePage` (bandeja) e `FilaPagamentosPage` fazem a mesma pergunta antes de
 * dar baixa: *de qual conta o dinheiro saiu e em que dia?*. A partir da Story 8.12 o backend exige
 * a resposta (`POST /bills/{id}/pay` com corpo obrigatório), então nenhuma das três pode continuar
 * chamando a rota sem corpo — e as três precisam do mesmo tratamento do **409 acionável**.
 *
 * ⚠️ **O seletor mora no MESMO container do botão que comete a ação.** Não é estilo, é o AC4: dois
 * PRs de fix de campo (#56 e #58) já foram pagos por elemento fora da área visível em ~360px, um
 * deles com uma conta real marcada paga sem o usuário conseguir ver o checkbox. Quem usar este
 * componente numa tela nova (a 8.15 vai) tem de mantê-lo colado ao botão.
 */

/** O que o `useEscolhaDaBaixa` devolve — o estado inteiro da escolha, para as três telas. */
export interface EscolhaDaBaixaState {
  contas: ContaDeBaixa[];
  contaId: string;
  setContaId: (id: string) => void;
  data: string;
  setData: (v: string) => void;
  /** `true` quando o tenant não tem NENHUMA conta ativa — a tela oferece o cadastro embutido. */
  semConta: boolean;
  /** `false` enquanto faltar a escolha obrigatória: a ação fica desabilitada (AC5). */
  pronto: boolean;
  /** Nome da conta escolhida (para o rótulo do botão). */
  nomeConta: string;
  /** Rótulo do botão com a conta colada (AC5). */
  rotulo: (base: string) => string;
  /** Aviso de data futura (não bloqueia — o 422 do backend é quem recusa). */
  aviso: string | null;
  /** Corpo pronto para `POST /pay` e para os dois corpos da bandeja. */
  corpo: () => { bank_account_id: string; paid_on: string };
  /** O cadastro embutido está aberto? */
  cadastrando: boolean;
  abrirCadastro: () => void;
  fecharCadastro: () => void;
  /** Chamar no `catch` de um envio: abre o cadastro se o erro for o 409 acionável. Devolve a
   *  mensagem a exibir (a do backend, sem reescrita) ou `null` se não era esse erro. */
  tratarErro: (err: unknown) => string | null;
  /** Recarrega as contas (usado após o cadastro embutido). */
  recarregar: () => Promise<void>;
  /** Handler do `onSaved` do cadastro: seleciona a conta nova e fecha o formulário. */
  aoCadastrar: (conta?: BankAccount) => void;
}

/**
 * Carrega as contas ativas, pré-seleciona a primária e guarda a data escolhida.
 *
 * @param dataPadrao data inicial do campo. **`PagarPage`/`FilaPagamentos` passam o `due_date` da
 *   conta** (fundador F10: *"deixar habilitado no vencimento, pois se estiver fazendo retroativo,
 *   pq não deu certo no dia"*); **a bandeja passa hoje**, porque o comprovante chega pelo share
 *   sheet no instante do pagamento (ver a nota em `payables/receipts.py::link_receipt`).
 */
export function useEscolhaDaBaixa(dataPadrao: string): EscolhaDaBaixaState {
  const [contas, setContas] = useState<ContaDeBaixa[]>([]);
  const [contaId, setContaId] = useState("");
  const [data, setData] = useState(dataPadrao);
  const [cadastrando, setCadastrando] = useState(false);

  const recarregar = useCallback(async () => {
    try {
      const { data: lista } = await api.get<BankAccount[]>("/bank/accounts");
      const ativas = contasUtilizaveis(lista);
      setContas(ativas);
      // Só pré-seleciona se ainda não houver escolha: recarregar depois do cadastro embutido não
      // pode desfazer a conta que o usuário acabou de escolher a dedo.
      setContaId((atual) => (atual ? atual : contaPreSelecionada(ativas)));
    } catch {
      // Degrada em silêncio: sem a lista, a tela mostra o caminho do cadastro embutido em vez de
      // um erro cru — e o backend continua sendo a autoridade sobre a conta (409/404).
      setContas([]);
    }
  }, []);

  useEffect(() => {
    recarregar();
  }, [recarregar]);

  // A data padrão muda quando a tela troca de conta a pagar (cada uma tem seu vencimento).
  useEffect(() => {
    setData(dataPadrao);
  }, [dataPadrao]);

  const semConta = contas.length === 0;
  const nomeConta = nomeDaConta(contas, contaId);

  return {
    contas,
    contaId,
    setContaId,
    data,
    setData,
    semConta,
    pronto: contaId !== "" && data !== "",
    nomeConta,
    rotulo: (base: string) => rotuloDaAcao(base, nomeConta),
    aviso: avisoDeDataFutura(data, hojeISO()),
    corpo: () => ({ bank_account_id: contaId, paid_on: data }),
    cadastrando,
    abrirCadastro: () => setCadastrando(true),
    fecharCadastro: () => setCadastrando(false),
    tratarErro: (err: unknown) => {
      const acionavel = acaoCadastrarConta(err);
      if (!acionavel) return null;
      setCadastrando(true);
      // A mensagem é a do BACKEND, exibida como veio: ela nomeia as saídas reais (cadastrar a
      // conta, ou escolher outra quando a informada está arquivada). Reescrever no frontend é como
      // se perde a única frase que já foi pensada para esse momento.
      return acionavel.mensagem;
    },
    recarregar,
    aoCadastrar: async (conta?: BankAccount) => {
      setCadastrando(false);
      // ⚠️ **A ordem importa, e um teste a pegou.** A recarga vem PRIMEIRO e a seleção depois:
      // invertido, a lista relida (que pode não trazer a conta recém-criada — leitura atrasada,
      // filtro, qualquer coisa) sobrescreveria a inclusão local e a baixa seria retomada apontando
      // para uma conta que não está entre as opções. O `merge` cobre esse caso: **a conta que o
      // usuário acabou de cadastrar está selecionada e visível, venha ela da recarga ou não.**
      await recarregar();
      // **Retoma a baixa com a conta recém-criada já selecionada** (AC2). Sem o id vindo do modal,
      // "qual é a nova?" viraria palpite no dia em que o dono cadastrar duas contas seguidas.
      if (conta) {
        setContas((atuais) =>
          atuais.some((c) => c.id === conta.id) ? atuais : [...atuais, conta],
        );
        setContaId(conta.id);
      }
    },
  };
}

/**
 * Os dois campos — conta e data. **Sempre dentro do container do botão que comete a ação.**
 *
 * `compact` é a variante da barra fixa do celular: os dois campos dividem uma linha (duas colunas
 * de ~152px em 360px, ver `larguraDoCampo` em `baixa.ts`) para a barra não crescer a ponto
 * de comer a lista atrás dela. No desktop os campos ficam lado a lado com rótulo em cima.
 */
export function EscolhaDaBaixa({
  estado,
  compact = false,
}: {
  estado: EscolhaDaBaixaState;
  compact?: boolean;
}) {
  const campo =
    "w-full rounded-lg border border-neutral-200 px-2 py-2 text-sm outline-none focus:border-primary-400";
  const contas = estado.contas;

  if (estado.semConta) {
    return (
      <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
        <p>
          Para dar baixa, o e1p precisa saber de qual conta bancária o dinheiro saiu — é isso que
          faz o movimento aparecer no seu extrato.
        </p>
        <button
          type="button"
          onClick={estado.abrirCadastro}
          className="mt-2 rounded-pill border border-amber-300 px-3 py-1 text-xs font-semibold text-amber-900 hover:bg-amber-100"
        >
          Cadastrar conta bancária
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* `grid-cols-2` também em ~360px: empilhar aqui deixaria a barra fixa alta demais e ela
          passaria a cobrir a lista de contas atrás. A conta escolhida continua legível porque o
          NOME dela aparece por extenso no rótulo do botão (AC5), não só dentro do `<select>`. */}
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Saiu da conta</span>
          <select
            value={estado.contaId}
            onChange={(e) => estado.setContaId(e.target.value)}
            aria-label="Conta bancária de onde o dinheiro saiu"
            className={campo}
          >
            {/* Sem primária, nada vem escolhido e a ação fica desabilitada: silêncio, nunca um
                palpite sobre para onde vai o dinheiro do dono (AC5). */}
            {estado.contaId === "" && <option value="">Escolha a conta…</option>}
            {contas.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-neutral-600">Dia do pagamento</span>
          <input
            type="date"
            value={estado.data}
            onChange={(e) => estado.setData(e.target.value)}
            // ⚠️ **O `max` SAI na Story 8.14**, junto com o estado `scheduled` — ver
            // `tetoDaDataDeBaixa`. Ele espelha o teto do backend; não é uma segunda guarda.
            max={tetoDaDataDeBaixa(hojeISO())}
            aria-label="Dia em que o dinheiro saiu da conta"
            className={campo}
          />
        </label>
      </div>
      {estado.aviso && (
        <p className={`text-amber-700 ${compact ? "text-[11px]" : "text-xs"}`}>{estado.aviso}</p>
      )}
    </div>
  );
}

/**
 * O cadastro **embutido**: o mesmo `AccountModal` de Contas & Saldos, aberto por cima da tela de
 * pagamento sem tirar o usuário dela.
 *
 * *"Um passo a mais, uma vez na vida do tenant"* — e ao salvar a baixa é **retomada** com a conta
 * nova selecionada, porque a tela por baixo nunca foi desmontada: o usuário não perde de vista qual
 * conta estava pagando.
 */
export function CadastroDeContaEmbutido({ estado }: { estado: EscolhaDaBaixaState }) {
  return (
    <AccountModal
      open={estado.cadastrando}
      editing={null}
      onClose={estado.fecharCadastro}
      onSaved={estado.aoCadastrar}
    />
  );
}

/**
 * A confirmação da baixa no **desktop** — a composição que `PagarPage` e `FilaPagamentosPage`
 * compartilham (a bandeja usa `EscolhaDaBaixa` direto, dentro da barra fixa do celular).
 *
 * Os campos e o botão estão no MESMO container, pelo mesmo motivo do AC4.
 */
export function DialogDeBaixa({
  titulo,
  descricao,
  valor,
  dataPadrao,
  onClose,
  onPago,
}: {
  titulo: string;
  descricao: string;
  valor: string;
  /** Default do campo de data: o `due_date` da conta (AC1/AC7), nunca hoje, nunca `now()`. */
  dataPadrao: string;
  onClose: () => void;
  /** Faz o POST. Devolve a promise para o dialog tratar erro/estado — inclusive o 409 acionável. */
  onPago: (corpo: { bank_account_id: string; paid_on: string }) => Promise<void>;
}) {
  const estado = useEscolhaDaBaixa(dataPadrao);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function confirmar() {
    setErro(null);
    setEnviando(true);
    try {
      await onPago(estado.corpo());
    } catch (err) {
      // 409 acionável → abre o cadastro embutido com a mensagem do backend. Qualquer outro erro
      // (422 do piso/teto, 404, rede) é exibido **como veio** — as mensagens do backend nomeiam as
      // saídas reais e reescrevê-las aqui é perder a única frase pensada para o caso.
      setErro(estado.tratarErro(err) ?? apiErrorMessage(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <Modal title={titulo} open onClose={onClose}>
        <div className="space-y-3">
          <div className="rounded-lg bg-neutral-50 p-3">
            <p className="text-sm font-medium text-neutral-800">{descricao}</p>
            <p className="text-xs text-neutral-500">{valor}</p>
          </div>
          <EscolhaDaBaixa estado={estado} />
          {erro && <p className="rounded-lg bg-red-50 p-2 text-sm text-danger">{erro}</p>}
          <button
            type="button"
            onClick={confirmar}
            disabled={enviando || !estado.pronto}
            className="w-full rounded-pill bg-accent-400 py-2.5 font-semibold text-white transition hover:bg-accent-500 disabled:opacity-60"
          >
            {enviando ? "Dando baixa…" : estado.rotulo("Confirmar baixa")}
          </button>
        </div>
      </Modal>
      <CadastroDeContaEmbutido estado={estado} />
    </>
  );
}
