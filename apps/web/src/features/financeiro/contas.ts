/**
 * Contas & Saldos (Story 8.7) — tipos + lógica PURA consumida pela `ContasSaldosPage`.
 *
 * Espelho manual dos schemas de `apps/api/app/modules/bank/schemas.py` (Stories 8.2/8.3/8.4).
 * `packages/shared-types` é mantido à mão e está defasado desde o PR #45; o padrão vigente do
 * módulo `financeiro` é declarar o tipo localmente no `.ts` da feature (`projecao.ts`,
 * `diagnostico.ts`, `investimentos.ts`) — é o que seguimos aqui.
 *
 * **Nenhum saldo sem procedência** (Regra dos Planos §1.3c): todo campo `saldo_*_cents` do backend
 * viaja com o irmão `saldo_*_origem`, e a tela é obrigada a exibir o rótulo do irmão colado ao
 * número. O vocabulário do eixo A vive num mapa só — `ORIGEM_LABEL`, em `projecao.ts` (Story 8.1) —
 * e é RE-EXPORTADO aqui de propósito: quem for mexer nesta feature encontra o rótulo pronto e não
 * cria um segundo mapa. O eixo B (`*_fonte`: manual/ofx) é outra pergunta e tem mapa próprio em
 * `conferencia.ts`. Os dois nunca se misturam.
 */
export { formatBRL } from "./dre";
// RE-EXPORT, não uma segunda implementação: existe UM mapa de rótulo de origem no frontend
// (`projecao.ts`, Story 8.1) e ele cobre os 4 valores do vocabulário (`plataforma`, `banco`,
// `misto`, `indisponivel`). Se faltar um valor novo, acrescente LÁ.
export { ORIGEM_LABEL, origemLabel } from "./projecao";

import { formatBRL } from "./dre";

// ── Tipos (espelho do backend) ───────────────────────────────────────────────────────────────

/** `BankAccountOut` (Story 8.2). Datas são datas de CALENDÁRIO (`YYYY-MM-DD`), nunca instantes. */
export interface BankAccount {
  id: string;
  name: string;
  kind: string;
  institution: string;
  institution_code: string;
  branch: string;
  number: string;
  holder_document: string;
  pix_key: string;
  opening_balance_cents: number;
  /**
   * Story 8.21 — o ATO de declarar, ao lado do VALOR acima. `false` significa que o dono disse
   * que **não sabe** o saldo de partida; nesse caso `opening_balance_cents` é `0` e é
   * **placeholder, não afirmação**, e a Projeção de Caixa cala runway e alerta.
   * É este campo que o `AccountModal` lê para renderizar a escolha em modo EDIÇÃO — sem ele o
   * caminho "descobri o saldo depois" não teria como existir na tela.
   */
  opening_balance_is_known: boolean;
  opening_date: string;
  is_primary: boolean;
  /** ISO datetime ou `null`. Conta arquivada nunca entra em soma nenhuma. */
  archived_at: string | null;
  /** Derivado a cada leitura: abertura + Σ movimentos não ignorados. Não existe coluna de saldo. */
  saldo_derivado_cents: number;
  /** Eixo A do saldo acima — sempre `banco`. Exibido colado ao número. */
  saldo_derivado_origem: string;
  /**
   * Story 8.14 — Σ dos movimentos com `posted_at > hoje`, separada por sinal e **em módulo**.
   *
   * ⚠️ **É o COMPLEMENTO EXATO de `saldo_derivado_cents`, não uma parcela dele:** aquele soma até
   * hoje (inclusive), este soma depois de hoje. Nenhum movimento entra nos dois, nenhum fica de
   * fora dos dois. **Nunca some os dois num total** sem rotular o resultado — seria uma terceira
   * afirmação sobre saldo, e afirmação de saldo sem rótulo próprio é a divergência D-6 outra vez.
   *
   * `agendado_entrada_cents` é estruturalmente `0` até a Story 8.15 (nada produz entrada futura
   * hoje); ele existe desde já porque o par simétrico é o contrato que aquela story consome.
   *
   * Opcionais no TS para que a tela não quebre contra um backend anterior à 8.14.
   */
  agendado_saida_cents?: number;
  agendado_entrada_cents?: number;
  /** Eixo A dos dois números acima — sempre `banco`. Um só, porque vêm da mesma soma. */
  agendado_origem?: string;
  created_at: string;
}

/** `BankTransactionOut` (Story 8.3). */
/**
 * A rota dos movimentos — **uma constante, dois consumidores** (Onda 2b-ii).
 *
 * `ContasSaldosPage` ("Ver movimentos") e `InvestimentosPage` (o extrato da aplicação) exibem o
 * MESMO razão em superfícies diferentes. A duplicação de superfície foi uma decisão; a de
 * CONSULTA não é: duas telas com filtros próprios sobre o mesmo dado divergem, e a que diverge é
 * a que ninguém olha. A constante é o que torna isso estrutural em vez de disciplina, e o gate
 * `nenhuma tela escreve a rota de movimentos à mão` (investimentos.test.ts) o mantém assim.
 */
export const ROTA_MOVIMENTOS = "/bank/transactions";

export interface BankTransaction {
  id: string;
  bank_account_id: string;
  posted_at: string;
  /** COM SINAL: `+` entrada, `−` saída. Nunca `0` (o backend recusa com 422). */
  amount_cents: number;
  /** O que o banco/usuário disse, congelado. Carrega PII — ver a nota de PII no fim deste módulo. */
  raw_description: string;
  user_description: string;
  /** `user_description or raw_description` — a regra JÁ vem resolvida do backend (8.3 Task 6). */
  description: string;
  counterparty_name: string;
  counterparty_document: string;
  operation_nature: string | null;
  source: string;
  /**
   * Story 8.18 — pareia as duas pernas irmãs de uma transferência; `null` em todo o resto.
   *
   * Opcional no TS para que a tela não quebre contra um backend anterior à 8.18. É ele que permite
   * oferecer "desfazer transferência" a partir de uma perna **sem** a UI precisar conhecer o
   * formato da chave de origem (`"{id}:out"`) — que é do backend e deve continuar sendo.
   */
  transfer_id?: string | null;
  status: string;
  ignored_reason: string;
  created_at: string;
  updated_at: string;
}

/** `CheckpointOut` (Story 8.4) — "o saldo desta conta, no fim deste dia, era X". */
export interface BankBalanceCheckpoint {
  id: string;
  bank_account_id: string;
  reference_date: string;
  balance_cents: number;
  /** Eixo A (plano) — sempre `banco`. */
  balance_origem: string;
  /** Eixo B (porta de entrada) — `manual`|`ofx`, cru. Rótulo em `conferencia.ts`. */
  origin: string;
  created_by: string | null;
  created_at: string;
}

// ── Tipo de conta (`models.KINDS`) ───────────────────────────────────────────────────────────

export const KIND_CHECKING = "checking";
export const KIND_SAVINGS = "savings";
export const KIND_INVESTMENT = "investment";
export const KIND_CASH = "cash";

/**
 * Vocabulário de TIPO de conta. Não confundir com o `kindLabel` de `costCenters.ts`: aquele
 * traduz tipos de centro de custo (sócio/área/unidade) e não tem nenhum valor em comum com este.
 * São dois vocabulários distintos de dois domínios distintos, e fundi-los num mapa só produziria
 * exatamente o achatamento que o design §1.3.1 proíbe para os eixos de procedência.
 */
export const KIND_LABEL: Record<string, string> = {
  [KIND_CHECKING]: "Conta corrente",
  [KIND_SAVINGS]: "Poupança",
  [KIND_INVESTMENT]: "Aplicação",
  [KIND_CASH]: "Caixa",
};

/** Pares [valor, rótulo] na ordem do `<select>` de cadastro. */
export const BANK_ACCOUNT_KINDS: ReadonlyArray<readonly [string, string]> = [
  [KIND_CHECKING, KIND_LABEL[KIND_CHECKING]],
  [KIND_SAVINGS, KIND_LABEL[KIND_SAVINGS]],
  [KIND_INVESTMENT, KIND_LABEL[KIND_INVESTMENT]],
  [KIND_CASH, KIND_LABEL[KIND_CASH]],
];

/** Rótulo do tipo, tolerante a um valor novo do backend (mostra o cru em vez de sumir). */
export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

// ── Status do movimento (`models.STATUSES`) ──────────────────────────────────────────────────

export const STATUS_UNMATCHED = "unmatched";
export const STATUS_PARTIAL = "partial";
export const STATUS_MATCHED = "matched";
export const STATUS_IGNORED = "ignored";

/**
 * Rótulo do status **do ponto de vista do saldo**, que é a única pergunta que a Onda 1 responde:
 * o movimento conta ou não conta. "Conciliado"/"Parcial" existem no vocabulário do backend para a
 * Onda 4 e são traduzidos aqui só para não aparecerem crus se chegarem.
 */
export const STATUS_LABEL: Record<string, string> = {
  [STATUS_UNMATCHED]: "No saldo",
  [STATUS_PARTIAL]: "Parcialmente vinculado",
  [STATUS_MATCHED]: "Vinculado",
  [STATUS_IGNORED]: "Ignorado (fora do saldo)",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

/** Movimento fora do saldo derivado. `ignore`/`unignore` são o par — não existe `DELETE`. */
export function isIgnored(tx: BankTransaction): boolean {
  return tx.status === STATUS_IGNORED;
}

// ── Origem do movimento (`models.SOURCES_*`) — Story 8.18 ────────────────────────────────────
//
// ⚠️ **A tela não sabe a REGRA; ela lê o `source`.** A Regra da Origem (d) diz que *"um movimento de
// origem do sistema não é editável nem ignorável pela tela de movimentos — quem quer mudá-lo mexe no
// lançamento de origem. A única exceção é `user_description`, que é rótulo, não fato"*. Quem a
// **aplica** é o backend (422); o que a tela faz é não oferecer um botão que ela sabe que vai
// recusar — oferecer e falhar treina o dono a ignorar mensagens de erro.
//
// A lista é **espelho manual** de `bank/models.py::SOURCES_SISTEMA`, e é escrita contra o CONJUNTO,
// nunca contra `'transfer'` solto: quando a Onda 2b ligar `yield` e a Onda 3 ligar `payout`, a tela
// herda o comportamento sem que ninguém edite um `if`.

export const SOURCE_MANUAL = "manual";
export const SOURCE_PAYABLE = "payable";
export const SOURCE_CHARGE = "charge";
export const SOURCE_TRANSFER = "transfer";
export const SOURCE_YIELD = "yield";
export const SOURCE_PAYOUT = "payout";

/** Espelho de `SOURCES_SISTEMA` — as origens que o próprio e1p escreve. */
export const SOURCES_SISTEMA: readonly string[] = [
  SOURCE_PAYABLE,
  SOURCE_CHARGE,
  SOURCE_TRANSFER,
  SOURCE_YIELD,
  SOURCE_PAYOUT,
];

/**
 * O movimento nasceu de um lançamento do e1p (e não de digitação/importação)? PURA.
 *
 * Um `source` desconhecido (vindo de um backend mais novo) cai no lado **externo** de propósito: a
 * consequência é a tela oferecer um botão que o backend pode recusar — barulhento e corrigível.
 * O erro oposto (assumir "de sistema") **esconderia** silenciosamente a edição de um movimento
 * manual legítimo, e ninguém abre um chamado para um botão que nunca esteve lá.
 */
export function isOrigemDoSistema(tx: BankTransaction): boolean {
  return SOURCES_SISTEMA.includes(tx.source);
}

/**
 * O movimento aceita `PATCH` de data/valor e `ignore`? PURA. `false` para origem de sistema.
 *
 * ⚠️ **`user_description` continua editável em qualquer origem** — é a exceção nomeada da regra. Por
 * isso o nome desta função fala de *fato*, não de *edição*: quem a usar para esconder o campo de
 * rótulo estará tirando do dono a única coisa que ele legitimamente pode mudar numa perna de
 * transferência.
 */
export function podeEditarOsFatosDoMovimento(tx: BankTransaction): boolean {
  return !isOrigemDoSistema(tx);
}

/**
 * A frase que substitui os botões ausentes. `null` quando o movimento é editável normalmente.
 *
 * Uma linha sem botão e sem explicação é lida como bug da tela. Esta frase diz **por que** e diz
 * **o que fazer** — que é a diferença entre uma restrição e uma parede.
 */
export function motivoDeNaoEditar(tx: BankTransaction): string | null {
  if (!isOrigemDoSistema(tx)) return null;
  if (tx.source === SOURCE_TRANSFER) {
    return "Gerado por uma transferência entre suas contas. Para desfazer, apague a transferência — as duas pernas somem juntas.";
  }
  return "Gerado por um lançamento seu. Para mudar, corrija o lançamento de origem — o movimento acompanha.";
}

// ── Natureza da operação (`models.OPERATION_NATURES`) — Story 8.17 ───────────────────────────
//
// *"Para que serve este movimento?"* — a curadoria que transforma "Novo movimento" (que parece o
// jeito de registrar qualquer coisa, inclusive um pagamento) num formulário que pergunta a
// finalidade. É **RÓTULO**, nunca fato de dinheiro: não entra em nenhuma soma de saldo.
//
// ⚠️ **Curadoria de UI, NUNCA whitelist.** O backend aceita qualquer texto de até 24 caracteres
// (`operation_nature` é `String(24)`, vocabulário aberto — design-mãe §7.2). A lista abaixo é
// SUGESTÃO, e a válvula *"Outro (descreva)"* é obrigatória: *"o extrato está cheio de coisas que
// não imaginamos (estorno de tarifa, crédito de convênio, débito de seguro, cashback). Recusar um
// fato bancário legítimo porque ele não está na lista recria a incompletude que a onda combate."*
// Quem transformar isto num `<select>` sem a válvula quebra o AC3 da Story 8.17.

export const OPERATION_NATURE_TARIFA = "tarifa_bancaria";
export const OPERATION_NATURE_TRIBUTO = "tributo";
export const OPERATION_NATURE_TRANSFERENCIA = "transferencia_propria";
export const OPERATION_NATURE_RECEITA_FINANCEIRA = "receita_financeira";

/**
 * O valor sentinela do `<select>` para *"Outro (descreva)"*. **Nunca é enviado à API** — quando ele
 * está escolhido, o que viaja é o texto que o usuário digitou. Começa com `_` justamente para não
 * poder colidir com um valor real do vocabulário do backend.
 */
export const OPERATION_NATURE_OUTRO = "_outro";

/**
 * Pares [valor, rótulo] na ordem do `<select>`. **Espelho manual** de
 * `bank/models.py::OPERATION_NATURES` — o pareamento entre as duas listas tem teste dos dois lados
 * (aqui e em `apps/api/tests/test_bank_contagem_dupla.py`), mesmo padrão de `BANK_ACCOUNT_KINDS`.
 *
 * ⚠️ Nenhum destes rótulos pode colidir com `ROTULO_BANCO` ("no banco", que na Projeção nomeia uma
 * parcela de saldo), `TOTAL_EM_CONTAS_LABEL` nem `DISPONIVEL_CAIXA_LABEL` — a colisão D-6/UX-001
 * que o épico já pagou para separar. Há teste fixando isso.
 */
export const OPERATION_NATURES: ReadonlyArray<readonly [string, string]> = [
  [OPERATION_NATURE_TARIFA, "Tarifa / juros"],
  [OPERATION_NATURE_TRIBUTO, "IOF / imposto"],
  [OPERATION_NATURE_TRANSFERENCIA, "Transferência entre minhas contas"],
  [OPERATION_NATURE_RECEITA_FINANCEIRA, "Rendimento"],
];

/** Rótulo da natureza, tolerante a valor livre do backend (mostra o cru em vez de sumir). */
export function operationNatureLabel(nature: string | null): string {
  if (!nature) return "";
  return OPERATION_NATURES.find(([v]) => v === nature)?.[1] ?? nature;
}

/**
 * O que sai do formulário para o campo `operation_nature` da API. PURA.
 *
 * `escolha` é o valor do `<select>`; `livre` é o que foi digitado no campo de *"Outro"*. Vazio →
 * `null` (o backend normaliza `strip() or None` do mesmo jeito), porque **movimento legado nasceu
 * com `NULL` e continua válido** — a UI nunca força preenchimento retroativo (AC7).
 */
export function naturezaParaEnvio(escolha: string, livre: string): string | null {
  const valor = escolha === OPERATION_NATURE_OUTRO ? livre.trim() : escolha.trim();
  return valor || null;
}

/**
 * O ponteiro para a **transferência de verdade** (Story 8.18), ao lado de *"Transferência entre
 * minhas contas"*: lançar as duas pernas à mão é a digitação dupla que a Regra da Origem §4.8(e)
 * manda evitar.
 *
 * ⚠️ **Condicional de propósito.** A Story 8.17 o escreveu com o argumento fixo em `false` porque a
 * 8.18 ainda não existia e apontar para ela mandaria o usuário para lugar nenhum. **A 8.18 subiu**
 * (`bank_transfers`, `POST /bank/transfers` e o modal desta tela), então o único ponto de chamada
 * passa `true` — que é literalmente a instrução deixada aqui pela 8.17.
 *
 * **A condicional FICA**, e não vira texto solto: ela é o registro de que este ponteiro depende de
 * uma superfície existir, e a próxima onda que mexer no formulário vai reler esta decisão em vez de
 * herdá-la sem saber.
 */
export function ponteiroDaTransferencia(transferenciaDisponivel: boolean): string | null {
  if (!transferenciaDisponivel) return null;
  return (
    "Se o dinheiro foi de uma conta sua para outra, use a transferência entre contas — " +
    "as duas pernas nascem juntas e você não digita duas vezes."
  );
}

// ── Transferência entre contas próprias (Story 8.18) ─────────────────────────────────────────

/** `BankTransferOut` — o LANÇAMENTO. As duas pernas viajam como `BankTransaction`, à parte. */
export interface BankTransfer {
  id: string;
  from_account_id: string;
  to_account_id: string;
  /** SEMPRE POSITIVO — o sinal vive nas pernas (invariante do modelo). */
  amount_cents: number;
  posted_at: string;
  kind: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export const TRANSFER_KIND_OWN = "own_transfer";
export const TRANSFER_KIND_INVESTMENT_IN = "investment_in";
export const TRANSFER_KIND_INVESTMENT_OUT = "investment_out";

/**
 * O `kind` da transferência **DERIVADO** dos tipos das duas contas. PURA.
 *
 * ⚠️ **Derivado, e não perguntado.** Um `<select>` de "tipo de transferência" ao lado dos dois
 * seletores de conta seria um terceiro campo dizendo o que os dois primeiros já dizem — e o dia em
 * que os três discordassem (aplicação escolhida no destino, "entre minhas contas" no tipo) não
 * haveria regra escrita em lugar nenhum sobre quem vence. É o defeito D-3 na camada de formulário.
 *
 * O backend valida contra a lista de todo jeito: derivar aqui é conveniência da tela, não a guarda.
 */
export function kindDaTransferencia(origemKind: string, destinoKind: string): string {
  if (destinoKind === KIND_INVESTMENT) return TRANSFER_KIND_INVESTMENT_IN;
  if (origemKind === KIND_INVESTMENT) return TRANSFER_KIND_INVESTMENT_OUT;
  return TRANSFER_KIND_OWN;
}

/**
 * O rótulo da AÇÃO na tela de Contas & Saldos.
 *
 * ⚠️ **Vocabulário de MOVIMENTO, deliberadamente distante do vocabulário de SALDO.** Ele não pode
 * ser nem conter `ROTULO_BANCO` ("no banco"), `TOTAL_EM_CONTAS_LABEL` nem `DISPONIVEL_CAIXA_LABEL`
 * — a colisão D-6/UX-001 que o épico já pagou para separar. O teste que fixa isso é o **mesmo** de
 * `contas.test.ts`, estendido, nunca um paralelo: um teste por story faria cada rótulo novo ser
 * conferido contra um subconjunto diferente dos antigos, que é como a colisão volta.
 */
export const TRANSFERIR_LABEL = "Transferir entre contas";

/**
 * O aviso, antes de confirmar, quando o destino é uma conta de **aplicação**. PURA.
 *
 * ⚠️ **Obrigatório, não polimento** (decisão do @po). Transferir para a aplicação **derruba** o
 * `DISPONIVEL_CAIXA_LABEL` e, por consequência, o saldo inicial da Projeção de Caixa — que exclui
 * aplicação (design §6.1: dinheiro aplicado não é caixa para pagar a conta de amanhã). É **correto**
 * (o dinheiro deixou de ser caixa), e é a **primeira vez** no produto que uma ação do dono encurta o
 * runway sem que nada tenha sido pago. Sem o aviso, ele veria o número cair e procuraria um furo.
 *
 * `null` quando não há o que dizer — **silêncio é o default**, a mesma disciplina anti-ruído da
 * banda de tolerância da conferência. Um aviso que aparece sempre deixa de ser lido.
 *
 * A frase nomeia o recorte pela constante (`DISPONIVEL_CAIXA_LABEL`), nunca por uma cópia do texto:
 * se o rótulo mudar um dia, o aviso muda junto em vez de passar a citar uma tela que não existe.
 */
export function avisoDestinoAplicacao(destino: BankAccount | null): string | null {
  if (!destino || destino.kind !== KIND_INVESTMENT) return null;
  return (
    `${destino.name} é uma conta de aplicação: este valor sai do "${DISPONIVEL_CAIXA_LABEL}" ` +
    "(e do saldo de partida da Projeção de Caixa) assim que a transferência for registrada. " +
    "O dinheiro continua seu e continua no \"" +
    TOTAL_EM_CONTAS_LABEL +
    '" — ele só deixa de ser caixa disponível.'
  );
}

/**
 * O que impede o botão de confirmar, ou `null` quando está tudo pronto. PURA.
 *
 * Espelha as guardas do backend que a tela **consegue** antecipar (contas distintas, valor > 0, data
 * não futura) — e **só** essas. As demais (conta arquivada, data anterior à abertura) dependem de
 * dado que a tela tem, mas cuja mensagem o backend escreve melhor: duplicar a redação aqui criaria
 * duas frases para a mesma regra, e a daqui envelheceria primeiro.
 *
 * ⚠️ **`hojeYmd` é PARÂMETRO, e isso é o conserto da #136.** Até então esta função chamava
 * `hojeISO()` por dentro — ou seja, uma função "pura" lia o relógio do NAVEGADOR escondida atrás da
 * assinatura. O `postedAt` que a tela oferece já nasce no fuso do tenant; comparar contra o dia da
 * máquina de quem abriu a página é o mesmo defeito de dois relógios da bandeja de comprovantes, só
 * que na camada de baixo — e, num tenant a leste, ele barra com "a data não pode ser futura" o
 * valor que a própria tela acabou de preencher. Recebendo o hoje de fora, o teste consegue afirmar
 * sobre fuso. Mesmo precedente de `filtroPadrao(hojeYmd)` em `pagar/filtros.ts`.
 */
export function impedimentoDaTransferencia(
  origem: BankAccount | null,
  destino: BankAccount | null,
  cents: number,
  postedAt: string,
  hojeYmd: string,
): string | null {
  if (!origem || !destino) return "Escolha a conta de origem e a de destino.";
  if (origem.id === destino.id) {
    return "A conta de origem e a de destino são a mesma — isso não moveria dinheiro nenhum.";
  }
  if (cents <= 0) return "Informe um valor maior que zero.";
  if (postedAt > hojeYmd) {
    return "A data não pode ser futura: registre a transferência no dia em que ela cair.";
  }
  return null;
}

// ── O 409 acionável da contagem dupla (contrato da Story 8.17, formato da 8.12) ───────────────

/** A ação que o backend pede quando a saída manual casa com uma conta a pagar. Contrato. */
export const ACAO_BAIXAR_PAYABLE = "baixar_payable";

export interface DuplicataAcionavel {
  payableId: string;
  mensagem: string;
}

/**
 * O `detail` estruturado do 409 da contagem dupla, quando for ele. `null` para qualquer outro erro.
 *
 * ⚠️ **Reconhecer por `acao`, nunca por substring da mensagem** — mesma disciplina de
 * `pagar/baixa.ts::acaoCadastrarConta`, e **o mesmo formato**: `{"detail": {"acao", ...}}`, com o
 * `acao` DENTRO de `detail`. Dois formatos de erro acionável obrigariam cada tela a saber, por
 * rota, onde procurar — que é como um contrato de erro deixa de ser contrato.
 */
export function acaoBaixarPayable(err: unknown): DuplicataAcionavel | null {
  const detail = (
    err as {
      response?: { data?: { detail?: { acao?: string; payable_id?: string; mensagem?: string } } };
    }
  )?.response?.data?.detail;
  if (!detail || typeof detail !== "object" || detail.acao !== ACAO_BAIXAR_PAYABLE) return null;
  return { payableId: detail.payable_id ?? "", mensagem: detail.mensagem ?? "" };
}

// ── Exibição do valor assinado ───────────────────────────────────────────────────────────────

export interface SignedAmountView {
  entrada: boolean;
  /** "Entrada" | "Saída" — derivado do SINAL, nunca de um campo `kind` inventado pela UI. */
  rotulo: string;
  /** Valor absoluto formatado com o sinal explícito na frente ("+ R$ 10,00" / "− R$ 10,00"). */
  texto: string;
  /** Classe Tailwind da cor do número (verde entrada / neutro escuro saída). */
  className: string;
}

/**
 * Exibição de um `amount_cents` **assinado**.
 *
 * O extrato bancário é uma sequência assinada e o backend a preserva assim (8.3). A UI **não**
 * inventa um par `kind` + valor absoluto: se ela o fizesse, existiriam duas representações do
 * mesmo fato e o dia em que uma delas fosse gravada de volta com o sinal trocado seria o dia em
 * que o saldo derivado passaria a mentir. Aqui só derivamos a APRESENTAÇÃO.
 *
 * `0` não é produzível pelo backend (422); se chegar, é tratado como entrada e exibido como
 * `+ R$ 0,00` — visível e estranho, em vez de silenciosamente classificado como saída.
 */
export function signedAmountView(cents: number): SignedAmountView {
  const entrada = cents >= 0;
  return {
    entrada,
    rotulo: entrada ? "Entrada" : "Saída",
    // "−" é o sinal de menos tipográfico (U+2212), não o hífen: alinha melhor em `tabular-nums`.
    texto: `${entrada ? "+" : "−"} ${formatBRL(Math.abs(cents))}`,
    className: entrada ? "text-emerald-600" : "text-neutral-800",
  };
}

// ── Os DOIS totais, num cálculo só ───────────────────────────────────────────────────────────

/**
 * ⚠️ **A divergência D-6 e como ela foi resolvida.**
 *
 * A Projeção de Caixa (Story 8.8) chama de **"no banco"** (`ROTULO_BANCO`, em `projecao.ts`) uma
 * parcela que vem de `bank.service.active_balance_total`, que **exclui `kind='investment'`**
 * (design §6.1: dinheiro aplicado não é caixa para pagar a conta de amanhã). Se esta tela chamasse
 * a soma de TODAS as contas com o mesmo nome, o dono veria dois números diferentes com o mesmo
 * rótulo em duas telas — e num produto cujo valor inteiro é ser testemunha confiável do dado, isso
 * não é um detalhe de UI: é a perda da confiança no número.
 *
 * A solução: **dois rótulos distintos, nenhum deles "no banco"**, e um só cálculo. `ROTULO_BANCO`
 * continua sendo exclusivamente o nome da parcela da Projeção.
 */
export const TOTAL_EM_CONTAS_LABEL = "Total em contas";
export const DISPONIVEL_CAIXA_LABEL = "Disponível como caixa";

/**
 * ⚠️ **Story 8.14 — o TERCEIRO número, e ele passa pelos MESMOS testes de colisão do UX-001.**
 *
 * *"Agendado para sair"* nomeia dinheiro que **ainda está na conta** e **já tem destino marcado**.
 * Ele não é saldo (não entra em `TOTAL_EM_CONTAS_LABEL`) e não é dívida (a conta já foi resolvida):
 * é a única coisa que o dono precisa saber para não contar duas vezes com o mesmo dinheiro.
 *
 * O rótulo **não pode ser nem conter** `ROTULO_BANCO` (`"no banco"`, que na Projeção nomeia uma
 * parcela de saldo), `TOTAL_EM_CONTAS_LABEL` nem `DISPONIVEL_CAIXA_LABEL` — a colisão D-6/UX-001
 * que o épico já pagou para separar. O teste que fixa isso é o **mesmo** de `contas.test.ts`,
 * estendido, nunca um paralelo (instrução da story para a 8.15 e a 8.18 também).
 *
 * "sair"/"entrar" é vocabulário de **movimento**, deliberadamente distante de "total"/"disponível"/
 * "no banco", que são vocabulário de **saldo**. Não são sinônimos e a tela não pode sugerir que são.
 */
export const AGENDADO_SAIDA_LABEL = "Agendado para sair";
/**
 * O par simétrico. Só passa a ter valor com a Story 8.15 (recebimento com data futura).
 *
 * ⚠️ **[#186] FONTE ÚNICA do rótulo — três telas o exibem e NENHUMA o escreve solto.**
 *
 * As três leem o número de origens diferentes e mesmo assim usam esta string, porque para o dono
 * elas nomeiam **a mesma ideia**: dinheiro com dia marcado que ainda não caiu.
 *
 * | Tela | De onde vem o número |
 * |---|---|
 * | `financeiro/ContasSaldosPage` | `resumoSaldos()`, sobre `agendado_entrada_cents` da conta |
 * | `cobrancas/CobrancasPage` | `summary.scheduled_cents` (cobranças `scheduled`) |
 * | `crm/ClientDetailPage` | as cobranças `scheduled` **do cliente** (issue #154) |
 *
 * Até o #186 as duas últimas escreviam o literal. A medição que fechou a questão: renomear esta
 * constante deixava **183 testes verdes** e as telas passavam a exibir DOIS nomes para o mesmo
 * estado — desincronia silenciosa, sem nenhum teste para denunciá-la. Importar daqui amarra as
 * três e **não inventa convenção nova**: é a mesma forma do `VOCAB_ENTRADA` (`pagar/baixa.ts`),
 * que essas duas telas já importam. Um módulo neutro só para duas strings, esse sim, seria a
 * terceira convenção que o PR #171 recusou com razão.
 */
export const AGENDADO_ENTRADA_LABEL = "Agendado para entrar";

/** Tipos que NÃO são caixa imediato — espelha o default de `active_balance_total` (design §6.1). */
export const KINDS_FORA_DO_CAIXA: readonly string[] = [KIND_INVESTMENT];

/** Conta que entra em soma: ativa (não arquivada). Arquivada nunca entra, em nenhum recorte. */
export function contasAtivas(accounts: BankAccount[]): BankAccount[] {
  return accounts.filter((a) => a.archived_at === null);
}

/**
 * Σ dos saldos derivados das contas **ativas**, com recorte opcional por tipo. Centavos. PURA.
 *
 * Um cálculo, dois rótulos (ver `resumoSaldos`) — **não** duas funções: duas implementações da
 * mesma soma divergiriam no primeiro dia em que alguém corrigisse só uma delas.
 */
export function totalSaldoCents(
  accounts: BankAccount[],
  opts: { excludeKinds?: readonly string[] } = {},
): number {
  const excluded = new Set(opts.excludeKinds ?? []);
  return contasAtivas(accounts)
    .filter((a) => !excluded.has(a.kind))
    .reduce((acc, a) => acc + a.saldo_derivado_cents, 0);
}

export interface ResumoSaldo {
  rotulo: string;
  cents: number;
  /** Texto curto que diz o que ESTE recorte inclui — o total nunca aparece sem ele. */
  explicacao: string;
}

/**
 * Σ do que já tem dia marcado para SAIR das contas ativas (Story 8.14). Centavos, absoluto. PURA.
 *
 * O backend já entrega o número por conta (`agendado_saida_cents`), somado com a mesma fórmula do
 * saldo (`_movements_sums`, recorte de data invertido) — a tela **soma as contas**, nunca deriva o
 * valor por diferença entre dois saldos. Derivar aqui seria uma segunda fórmula de saldo na camada
 * mais frágil, e a Regra 4 do `CLAUDE.md` manda o saldo ser derivado num lugar só.
 */
export function totalAgendadoCents(
  accounts: BankAccount[],
  campo: "agendado_saida_cents" | "agendado_entrada_cents",
): number {
  return contasAtivas(accounts).reduce((acc, a) => acc + (a[campo] ?? 0), 0);
}

/**
 * Os totais a exibir no topo da lista de contas, já rotulados. PURA.
 *
 * - **"Total em contas"** — sempre presente;
 * - **"Disponível como caixa"** — só quando há conta de aplicação ativa (senão os dois recortes
 *   coincidem e a segunda linha é ruído);
 * - **"Agendado para sair"** / **"Agendado para entrar"** (Story 8.14) — **omitidos quando o valor
 *   é zero**, pela mesma disciplina anti-ruído: um número que é sempre zero na tela do dono que
 *   nunca agenda nada é exatamente o tipo de peso de ERP que este produto recusa. "Agendado para
 *   entrar" nasce, na prática, sempre omitido — ele só passa a ter valor com a Story 8.15.
 *
 * Nunca devolve um total ambíguo, e nenhum dos rótulos é o da parcela da Projeção (`ROTULO_BANCO`).
 */
export function resumoSaldos(accounts: BankAccount[]): ResumoSaldo[] {
  const total = totalSaldoCents(accounts);
  const temAplicacao = contasAtivas(accounts).some((a) => KINDS_FORA_DO_CAIXA.includes(a.kind));
  const resumo: ResumoSaldo[] = [
    {
      rotulo: TOTAL_EM_CONTAS_LABEL,
      cents: total,
      explicacao: "Soma de todas as suas contas ativas, incluindo aplicações.",
    },
  ];
  if (temAplicacao) {
    resumo.push({
      rotulo: DISPONIVEL_CAIXA_LABEL,
      cents: totalSaldoCents(accounts, { excludeKinds: KINDS_FORA_DO_CAIXA }),
      explicacao:
        "Exclui as aplicações — é esta parcela que a Projeção de Caixa soma ao disponível da Carteira e1p.",
    });
  }
  const saida = totalAgendadoCents(accounts, "agendado_saida_cents");
  if (saida > 0) {
    resumo.push({
      rotulo: AGENDADO_SAIDA_LABEL,
      cents: saida,
      explicacao:
        "Débitos já agendados, com data futura — o dinheiro ainda está aí, mas não está no Total em contas por engano: ele já tem destino.",
    });
  }
  const entrada = totalAgendadoCents(accounts, "agendado_entrada_cents");
  if (entrada > 0) {
    resumo.push({
      rotulo: AGENDADO_ENTRADA_LABEL,
      cents: entrada,
      explicacao: "Recebimentos já marcados para uma data futura — ainda não estão na sua conta.",
    });
  }
  return resumo;
}

// ── Entrada de dinheiro e datas ──────────────────────────────────────────────────────────────

/**
 * "1.234,56" / "1234.56" / "1234" → centavos. Vazio ou inválido → `0`. Aceita sinal negativo
 * (saldo de abertura de conta no limite é legítimo).
 *
 * ✅ **Consolidada (#224).** As 12 conversões inline (`Math.round(parseFloat(v.replace(",", "."))
 * * 100)`) espalhadas por `CobrancasPage`, `PagarPage`, `ProdutosPage`, `FunnelBuilderPage`,
 * `EstoquePage`, `FinanceiroPage`, `FunnelAutomation` e o `toCents` local de `QuoteBuilderPage`
 * agora chamam esta função — nenhuma delas tratava o ponto de milhar ("1.234,56" virava 1,23).
 * `ComprovantePage.toCents` (que já trata milhar de outro jeito) ficou fora: não estava na lista
 * de 12 sites da #224.
 */
export function parseCentsBRL(raw: string): number {
  const s = raw.trim().replace(/\s/g, "");
  let clean: string;
  if (s.includes(",")) {
    // Formato pt-BR: a vírgula é o decimal, todo ponto é separador de milhar.
    clean = s.replace(/\./g, "").replace(",", ".");
  } else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) {
    // Sem vírgula, mas com grupos de 3 dígitos ("1.234", "1.234.567"): milhar, não decimal.
    clean = s.replace(/\./g, "");
  } else {
    // Sem vírgula e sem cara de milhar ("1234.56", "1234"): o ponto é decimal.
    clean = s;
  }
  const n = Number.parseFloat(clean);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

/** Centavos → valor editável em `<input>` ("1234,56"), sem símbolo de moeda nem milhar. */
export function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2).replace(".", ",");
}

// ── `hojeISO()` foi REMOVIDA (#136) — a explicação que ela carregava ficou falsa ──────────────
//
// A função montava `YYYY-MM-DD` pelas partes locais de um `new Date()`, e o comentário dela dizia
// que "local (e não UTC)" era de propósito, porque "o usuário está declarando o saldo de HOJE
// olhando para o calendário DELE". Essa frase foi escrita antes do PR #78 e opunha as duas únicas
// opções que existiam então: o relógio do navegador e o UTC cru. Ela nunca considerou a terceira,
// que desde o #78 é a régua do e1p — o relógio do **tenant** (`hoje_do_tenant(db)` no backend,
// `today(fuso)` de `lib/datetime.ts` no frontend).
//
// Com a régua nova, "o calendário DELE" deixou de ser o do navegador: o dono viajando lê o dia do
// hotel, e o dia da empresa é o do fuso do tenant. Por isso a função não vira `@deprecated` nem
// sobra "para usos legítimos": não restou nenhum. Todos os seus 15 call sites eram default ou
// validação de campo de data em tela de dinheiro — exatamente a classe que o #78 moveu. Um alias
// depreciado seria um convite a reintroduzir o defeito com o autocomplete, e o defeito 2 da #136
// (default preenchido por um relógio e validado por outro) nasceu de exatamente esse tipo de
// segunda porta.
//
// Quem precisar de "hoje" numa tela: `today(useFuso())`. Quem precisar dele numa função PURA:
// receba-o como argumento (ver `impedimentoDaTransferencia` acima e `filtroPadrao(hojeYmd)` em
// `pagar/filtros.ts`), nunca o busque por dentro.

// ── Story 8.10 — a data em que o saldo foi apurado ───────────────────────────────────────────

/**
 * O prefixo da data de apuração do saldo **derivado**. Constante para o teste de colisão poder
 * afirmar sobre ele sem repetir a string.
 *
 * ⚠️ **Não confundir com "Saldo declarado em"**, que é o checkpoint. São as duas pontas exatas da
 * comparação da Conferência: aqui é *o que o e1p calculou*; lá é *o que o banco diz*. A distinção
 * de vocabulário é a mesma que o UX-001 instituiu — e é por isso que os dois prefixos são
 * diferentes na origem, e não só por acaso de redação.
 */
export const SALDO_APURADO_PREFIXO = "Saldo em";

/**
 * `"2026-07-30"` → `"Saldo em 30/07"`. PURA.
 *
 * Existe porque, desde a Story 8.10, o saldo derivado tem **um corte de data** (hoje) em vez de
 * "todo o histórico" — e um saldo sem a data em que foi apurado é um número que não dá para
 * conferir. Dia/mês, sem ano: é sempre um saldo corrente, e o ano seria ruído numa linha que fica
 * ao lado do número.
 */
export function saldoApuradoEm(iso: string): string {
  const [, mes, dia] = iso.slice(0, 10).split("-");
  if (!dia || !mes) return `${SALDO_APURADO_PREFIXO} ${iso}`;
  return `${SALDO_APURADO_PREFIXO} ${dia}/${mes}`;
}

/** "2026-07-30" → "30/07/2026". Fatiamento de string: nunca `new Date(...)` (bug de fuso). */
export function formatDateBR(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return d && m && y ? `${d}/${m}/${y}` : iso;
}

// ── Story 8.11 — o aviso pró-ativo do cadastro ───────────────────────────────────────────────

/**
 * `PayablesPaidBeforeOut` — o agregado de `GET /payables/bills/paid-before?date=` (Story 8.11).
 *
 * ⚠️ **Nada aqui é, vira ou sugere um saldo de abertura** (AC4 / `CLAUDE.md` Regra 5).
 * `total_cents` é o total **pago** e é rotulado como tal. O saldo de abertura é um fato *sobre o
 * banco*, que o sistema por definição não conhece — derivá-lo daqui seria somar o que o sistema
 * sabe e chamar de "o que o banco diz", a circularidade que faria a divergência ir a zero por
 * construção no dia um. **O e1p não inventa o número: ele diz qual número ir buscar.**
 */
export interface PayablesPaidBefore {
  count: number;
  total_cents: number;
  oldest_paid_on: string | null;
  newest_paid_on: string | null;
}

/**
 * O dia ANTERIOR a uma data ISO. PURA. `"2026-03-01"` → `"2026-02-28"`.
 *
 * ⚠️ **Por que o dia anterior, e não o mesmo dia.** O saldo derivado soma `posted_at >
 * opening_date`, **estritamente**, e `_validate_posted_at` recusa `posted_at <= opening_date` com
 * 422: uma conta paga exatamente na data de abertura fica de fora do saldo do mesmo jeito. Abrir a
 * conta no dia da conta mais antiga deixaria justamente ela para trás — a parede uma casa adiante.
 *
 * Aritmética em UTC (`Date.UTC`) para não pegar o bug de fuso do `CLAUDE.md` §6.0: com `new
 * Date("2026-03-01")` + hora local negativa, o dia anterior sairia dois dias antes.
 */
export function diaAnteriorISO(iso: string): string {
  const partes = iso.slice(0, 10).split("-").map(Number);
  if (partes.length !== 3 || partes.some((n) => !Number.isFinite(n))) return iso;
  const [y, m, d] = partes;
  return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10);
}

/**
 * A frase do aviso pró-ativo (AC3), ou `null` quando não há o que dizer. PURA.
 *
 * **Silêncio é o default.** Zero contas pagas anteriores → `null` → nenhum aviso na tela. É a mesma
 * disciplina anti-ruído da banda de tolerância da conferência: *"dentro da banda, verde e
 * SILÊNCIO"*. Uma tela que avisa sobre um conjunto vazio destrói a confiança no aviso.
 *
 * ⚠️ **Vocabulário:** esta frase é texto de FORMULÁRIO e não pode conter `ROTULO_BANCO`
 * ("no banco", que na Projeção nomeia uma parcela de saldo), `TOTAL_EM_CONTAS_LABEL` nem
 * `DISPONIVEL_CAIXA_LABEL` — reusá-los aqui recriaria a colisão D-6/UX-001 que o épico já pagou
 * para separar. Há teste fixando isso.
 */
export function avisoContasPagasAnteriores(
  dados: PayablesPaidBefore | null,
  openingDate: string,
): string | null {
  if (!dados || dados.count <= 0 || !dados.oldest_paid_on) return null;
  const total = formatBRL(dados.total_cents);
  const quando =
    dados.newest_paid_on && dados.newest_paid_on !== dados.oldest_paid_on
      ? `entre ${formatDateBR(dados.oldest_paid_on)} e ${formatDateBR(dados.newest_paid_on)}`
      : `em ${formatDateBR(dados.oldest_paid_on)}`;
  const quantas =
    dados.count === 1 ? "1 conta paga" : `${dados.count} contas pagas`;
  const elas = dados.count === 1 ? "ela não vai" : "elas não vão";
  return (
    `Você tem ${quantas} ${quando} (${total} pagos). Se esta conta abrir em ` +
    `${formatDateBR(openingDate)}, ${elas} entrar no extrato do e1p.`
  );
}

// ── ⚠️ PII nesta superfície (registro para a Onda 3/4) ───────────────────────────────────────
//
// `BankTransaction.raw_description` e `user_description` — e, a partir da Onda 3,
// `counterparty_name` e `counterparty_document` — carregam **PII de terceiro que nunca contratou
// com a e1p** (nome e CPF/CNPJ de quem pagou/recebeu, coletados por via indireta). A tela de
// movimentos desta story JÁ exibe os dois primeiros; os de contraparte são preenchíveis à mão no
// modal de lançamento e, portanto, também exibíveis.
//
// Consequências para quem vier depois:
//  1. **Onda 4 exige o anonimizador** (`core/anonymizer`, Regra de Ouro nº 2) antes de QUALQUER
//     chamada a `core/ai` que toque esses campos — inclusive na classificação automática. Mandar a
//     descrição crua "porque é só uma categoria" é exatamente o caminho pelo qual PII vaza.
//  2. **Não copiar** esses valores para lugar novo: log, `document.title`, query string, título de
//     modal ou telemetria. Minimização é regra (REQ-18) — nesta tela eles aparecem na célula da
//     tabela e no campo do formulário, e em nenhum outro lugar.
//  3. Nada de IA nesta onda: sugestão de match e classificação são Onda 4.
