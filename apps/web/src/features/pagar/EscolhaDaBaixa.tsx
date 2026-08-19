import { useCallback, useEffect, useState } from "react";
import Modal from "../../components/Modal";
import { api, apiErrorMessage } from "../../lib/api";
import { today } from "../../lib/datetime";
import { useFuso } from "../../store/auth";
import AccountModal from "../financeiro/AccountModal";
import type { BankAccount } from "../financeiro/contas";
import {
  acaoCadastrarConta,
  type ContaDeBaixa,
  VOCAB_SAIDA,
  type VocabularioDaBaixa,
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
 *
 * ── ⚠️ **[Story 8.15] UM componente, agora CINCO telas — e dois vocabulários.**
 *
 * O recebimento fora do trilho (`CobrancasPage`, `ClientDetailPage`) faz a mesma pergunta com o
 * dinheiro andando na direção oposta: *"em qual conta o dinheiro **caiu**, e em que dia?"*. O que
 * mudou aqui foi **só o vocabulário** (`VocabularioDaBaixa`, em `baixa.ts`) — a mecânica inteira é
 * a mesma instância: pré-seleção da primária, ação desabilitada sem escolha, nome da conta colado
 * ao botão, 409 acionável → cadastro embutido → **retoma**. Uma cópia para as entradas seria a
 * segunda a divergir na próxima correção de campo.
 */

/** O que o `useEscolhaDaBaixa` devolve — o estado inteiro da escolha, para as cinco telas. */
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
  /** "Hoje" no fuso do TENANT — o ÚNICO relógio desta escolha (#136). Ver `HOJE_DO_TENANT`. */
  hoje: string;
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
  /** Os textos desta direção do dinheiro (saída = default; entrada = Story 8.15). */
  vocab: VocabularioDaBaixa;
}

/**
 * O `dataPadrao` de quem quer que o campo nasça em **hoje**.
 *
 * ⚠️ **Não é "sem default": é "o default é hoje, e quem resolve o hoje é este componente"** — que é
 * o conserto do defeito 2 da #136. Antes, cada tela montava o próprio hoje e o passava pronto,
 * enquanto a validação (`avisoDeDataFutura`, `tetoDaDataDeBaixa`) resolvia o dela por dentro: dois
 * relógios num componente só. Com o tenant em Tóquio a bandeja abria já acusando *"Esta data é no
 * futuro… será registrada como AGENDADA"* sobre o valor que ela mesma acabara de preencher.
 *
 * Passar o sentinela em vez de uma string faz com que **exista uma chamada só** de `today(fuso)`
 * para o default E para a validação. Não é convenção: é impossível divergir, porque não há um
 * segundo lugar de onde divergir. Quem passa uma STRING está declarando outra coisa (o `due_date`
 * da conta, em `PagarPage`/`FilaPagamentos`) — e essa continua sendo uma escolha explícita.
 */
export const HOJE_DO_TENANT = null;

/**
 * Carrega as contas ativas, pré-seleciona a primária e guarda a data escolhida.
 *
 * @param dataPadrao data inicial do campo. **`PagarPage`/`FilaPagamentos` passam o `due_date` da
 *   conta** (fundador F10: *"deixar habilitado no vencimento, pois se estiver fazendo retroativo,
 *   pq não deu certo no dia"*); **a bandeja, as Cobranças e a ficha do cliente passam
 *   `HOJE_DO_TENANT`**, porque ali o gesto é um fato observado AGORA (o comprovante chega pelo
 *   share sheet no instante do pagamento — ver a nota em `payables/receipts.py::link_receipt`).
 */
export function useEscolhaDaBaixa(
  dataPadrao: string | typeof HOJE_DO_TENANT,
  vocab: VocabularioDaBaixa = VOCAB_SAIDA,
): EscolhaDaBaixaState {
  // ⚠️ **UM relógio, e ele é o do TENANT** (#136, régua do PR #78 e do CLAUDE.md §5.2). Este é o
  // único ponto do fluxo de baixa que resolve "hoje": o default do campo, o `aviso` e o teto do
  // `max` bebem todos daqui. Trocar por `new Date()` local, ou por `toISOString()` (UTC), é
  // regressão — e os testes de `ComprovantePage`/`CobrancasPage` rodam com o tenant em Tóquio
  // justamente para que essa troca fique VERMELHA em vez de invisível.
  const hoje = today(useFuso());
  const inicial = dataPadrao ?? hoje;

  const [contas, setContas] = useState<ContaDeBaixa[]>([]);
  const [contaId, setContaId] = useState("");
  const [data, setData] = useState(inicial);
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

  // A data padrão muda quando a tela troca de conta a pagar (cada uma tem seu vencimento). Com
  // `HOJE_DO_TENANT`, `inicial` é o próprio `hoje` — string estável dentro do dia, então o efeito
  // não redispara a cada render.
  useEffect(() => {
    setData(inicial);
  }, [inicial]);

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
    vocab,
    rotulo: (base: string) => rotuloDaAcao(base, nomeConta, vocab.preposicao),
    aviso: avisoDeDataFutura(data, hoje, vocab),
    hoje,
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
        <p>{estado.vocab.semConta}</p>
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
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            {estado.vocab.rotuloConta}
          </span>
          <select
            value={estado.contaId}
            onChange={(e) => estado.setContaId(e.target.value)}
            aria-label={estado.vocab.ariaConta}
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
          <span className="mb-1 block text-xs font-medium text-neutral-600">
            {estado.vocab.rotuloData}
          </span>
          <input
            type="date"
            value={estado.data}
            onChange={(e) => estado.setData(e.target.value)}
            // ⚠️ **[Story 8.14] `tetoDaDataDeBaixa` passou a devolver `undefined`**, e com isso o
            // atributo `max` deixa de ser renderizado — o campo aceita data futura, e o backend
            // grava a conta como `scheduled`. A chamada FICA (em vez de a linha sumir) porque é
            // ela que documenta a decisão e é a ela que se volta se o teto precisar retornar; um
            // `max` apagado do JSX não deixa rastro nenhum.
            max={tetoDaDataDeBaixa(estado.hoje)}
            aria-label={estado.vocab.ariaData}
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
  vocab = VOCAB_SAIDA,
  acao = "Confirmar baixa",
  acaoEmCurso = "Dando baixa…",
}: {
  titulo: string;
  descricao: string;
  valor: string;
  /** Default do campo de data: o `due_date` da conta (AC1/AC7), nunca hoje, nunca `now()`.
   *  No recebimento fora do trilho (8.15) é **hoje** — o dono está olhando o extrato agora —, e aí
   *  se passa `HOJE_DO_TENANT`, nunca um hoje montado pela tela (#136). */
  dataPadrao: string | typeof HOJE_DO_TENANT;
  onClose: () => void;
  /** Faz o POST. Devolve a promise para o dialog tratar erro/estado — inclusive o 409 acionável. */
  onPago: (corpo: { bank_account_id: string; paid_on: string }) => Promise<void>;
  /** Story 8.15: `VOCAB_ENTRADA` no recebimento fora do trilho. */
  vocab?: VocabularioDaBaixa;
  /** ⚠️ Rótulo do botão que comete a ação. **Nunca "Marcar paga"** do lado das cobranças: aquele
   *  botão foi removido de propósito, e a diferença importa — aqui o dono declara um fato sobre a
   *  conta bancária dele, não confirma um pagamento do trilho. */
  acao?: string;
  acaoEmCurso?: string;
}) {
  const estado = useEscolhaDaBaixa(dataPadrao, vocab);
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
            {enviando ? acaoEmCurso : estado.rotulo(acao)}
          </button>
        </div>
      </Modal>
      <CadastroDeContaEmbutido estado={estado} />
    </>
  );
}
