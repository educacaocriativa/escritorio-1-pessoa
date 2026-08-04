/**
 * **A escolha da baixa** (Story 8.13) — lógica PURA da pergunta *"de qual conta saiu, e em que
 * dia?"*, compartilhada pelas TRÊS telas que dão baixa em conta a pagar: `PagarPage`,
 * `ComprovantePage` (bandeja de comprovantes) e `FilaPagamentosPage`.
 *
 * (Arquivo `baixa.ts`, e não `escolhaDaBaixa.ts`, porque o Windows não distingue maiúsculas em
 * nome de arquivo e o componente vizinho já se chama `EscolhaDaBaixa.tsx` — o `tsc` reprova o par.
 * Mesmo par de nomes de `financeiro/contas.ts` + `ContasSaldosPage.tsx`.)
 *
 * Uma implementação, três telas. Três cópias divergiriam no primeiro ajuste — e o ajuste desta em
 * particular já estava agendado: a **Story 8.14 removeu o teto de hoje** no mesmo commit em que o
 * estado `scheduled` passou a existir. **Ele valeu para as três telas de uma vez**, sem que nenhuma
 * delas fosse editada — que é exatamente o retorno prometido por ter uma implementação só.
 */

/** Só o que estas telas precisam de uma conta bancária. Espelho parcial de `financeiro/contas`. */
export interface ContaDeBaixa {
  id: string;
  name: string;
  is_primary: boolean;
  archived_at: string | null;
}

// ── O VOCABULÁRIO (Story 8.15) ────────────────────────────────────────────────────────────────
//
// A Story 8.15 precisa da MESMA mecânica (seletor colado ao botão, pré-seleção da primária, 409
// acionável → cadastro embutido → retoma) para o lado das ENTRADAS: *"em qual conta o dinheiro
// **caiu**?"*. Reescrever o componente lá seria a segunda cópia da lição dos PRs #56/#58 — e a
// segunda a divergir. Reusar sem parametrizar seria pior: a tela de Cobranças perguntaria "de qual
// conta o dinheiro **saiu**" sobre um recebimento, e o rótulo do botão diria "sai do Itaú PJ"
// sobre dinheiro entrando.
//
// ⚠️ **Só o vocabulário é parâmetro. A mecânica é uma só, e é isso que garante que a próxima
// correção de campo (a terceira, se houver) valha para as quatro telas de uma vez.**

export interface VocabularioDaBaixa {
  /** Rótulo do `<select>` de conta. */
  rotuloConta: string;
  /** `aria-label` do `<select>` — é por ele que os testes (e leitores de tela) o encontram. */
  ariaConta: string;
  /** Rótulo do campo de data. */
  rotuloData: string;
  /** `aria-label` do campo de data. */
  ariaData: string;
  /** Colado ao rótulo do botão: *"Confirmar baixa · **sai do** Itaú PJ"*. */
  preposicao: string;
  /** A frase do estado "tenant sem conta nenhuma" (o caminho do cadastro embutido). */
  semConta: string;
  /** O aviso (não bloqueio) de data futura. */
  avisoFuturo: string;
}

/** Saídas — Contas a Pagar (Story 8.13). Os textos são **exatamente** os de antes desta mudança. */
export const VOCAB_SAIDA: VocabularioDaBaixa = {
  rotuloConta: "Saiu da conta",
  ariaConta: "Conta bancária de onde o dinheiro saiu",
  rotuloData: "Dia do pagamento",
  ariaData: "Dia em que o dinheiro saiu da conta",
  preposicao: "sai do",
  semConta:
    "Para dar baixa, o e1p precisa saber de qual conta bancária o dinheiro saiu — é isso que faz " +
    "o movimento aparecer no seu extrato.",
  avisoFuturo:
    "Esta data é no futuro: a conta será registrada como AGENDADA. O dinheiro ainda não saiu — " +
    "ela entra na Projeção de Caixa pelo dia do débito e sai da fila do que você precisa pagar.",
};

/** Entradas — recebimento fora do trilho (Story 8.15). */
export const VOCAB_ENTRADA: VocabularioDaBaixa = {
  rotuloConta: "Caiu na conta",
  ariaConta: "Conta bancária onde o dinheiro caiu",
  rotuloData: "Dia do recebimento",
  ariaData: "Dia em que o dinheiro caiu na conta",
  preposicao: "caiu no",
  semConta:
    "Para registrar que você recebeu direto na conta, o e1p precisa saber em qual conta bancária " +
    "o dinheiro caiu — é isso que faz o crédito aparecer no seu extrato.",
  avisoFuturo:
    "Esta data é no futuro: o recebimento será registrado como AGENDADO. O dinheiro ainda não " +
    "caiu — ele entra na Projeção de Caixa pelo dia do crédito e a cobrança sai da régua.",
};

// ── O 409 acionável (contrato da Story 8.12) ──────────────────────────────────────────────────

/** A ação que o backend pede quando não há conta utilizável. Contrato, não texto de tela. */
export const ACAO_CADASTRAR_CONTA = "cadastrar_conta";

/**
 * O `detail` estruturado do 409 acionável, quando for ele. `null` para qualquer outro erro.
 *
 * ⚠️ **Reconhecer por `acao`, nunca por substring da mensagem.** O formato
 * `{"acao": "cadastrar_conta", "mensagem": "..."}` é contrato declarado da 8.12 exatamente para
 * que a tela não precise adivinhar pela frase — e a frase muda (hoje já são duas: "não tem conta
 * nenhuma" e "a conta escolhida está arquivada"), enquanto a ação é a mesma nas duas.
 */
export function acaoCadastrarConta(err: unknown): { mensagem: string } | null {
  const detail = (
    err as { response?: { data?: { detail?: { acao?: string; mensagem?: string } } } }
  )?.response?.data?.detail;
  if (!detail || typeof detail !== "object" || detail.acao !== ACAO_CADASTRAR_CONTA) return null;
  return { mensagem: detail.mensagem ?? "" };
}

// ── Pré-seleção ───────────────────────────────────────────────────────────────────────────────

/**
 * A conta que vem pré-selecionada: a **primária ativa**, ou nenhuma.
 *
 * ⚠️ **Sem primária, nada é escolhido — nem "a primeira", nem "a única".** É estado válido (é onde
 * o tenant fica ao arquivar a primária) e a resposta certa ali é o silêncio: escolher o destino do
 * dinheiro do usuário sem ele pedir é o tipo de "ajuda" que só se descobre quando o dinheiro já foi
 * para o lugar errado. Mesma razão de `bank.service.primary_account` devolver `None` explícito em
 * vez de eleger sucessora.
 *
 * E pré-selecionar **não é tornar opcional** (fundador F7): o campo continua obrigatório e sempre
 * gravado. O que o pré-preenchimento evita é **construir**, não **confirmar** — por isso a conta
 * escolhida tem de estar VISÍVEL (ver `rotuloDaAcao`); um default invisível seria, na prática, um
 * campo opcional pulado.
 */
export function contaPreSelecionada(contas: ContaDeBaixa[]): string {
  return contasUtilizaveis(contas).find((c) => c.is_primary)?.id ?? "";
}

/** Contas que podem receber uma baixa: as ATIVAS. Arquivada não recebe lançamento novo (409). */
export function contasUtilizaveis(contas: ContaDeBaixa[]): ContaDeBaixa[] {
  return contas.filter((c) => c.archived_at === null);
}

/** O nome da conta escolhida, ou `""` — para o rótulo do botão e para os testes. */
export function nomeDaConta(contas: ContaDeBaixa[], contaId: string): string {
  return contas.find((c) => c.id === contaId)?.name ?? "";
}

/**
 * O rótulo do botão que comete a ação, dizendo **para onde o dinheiro está indo** (AC5).
 *
 * *"Anexar e dar baixa · sai do Itaú PJ"*. O nome da conta precisa ser legível **sem interação
 * adicional** — dentro do `<select>` não basta, porque em ~360px o `<select>` é o elemento mais
 * espremido da barra e o nome é o primeiro a ser truncado.
 */
export function rotuloDaAcao(
  base: string,
  nomeConta: string,
  preposicao: string = VOCAB_SAIDA.preposicao,
): string {
  return nomeConta ? `${base} · ${preposicao} ${nomeConta}` : base;
}

// ── Geometria da barra fixa em ~360px (AC9, auditoria estrutural) ─────────────────────────────
//
// jsdom não faz layout, então a régua aqui é aritmética explícita sobre as classes Tailwind que a
// barra realmente usa. Os números vêm do tema padrão: `p-4` = 16px, `gap-2` = 8px, `space-y-3` =
// 12px. Se as classes mudarem sem que estas constantes mudem, o teste que lê o `className` real da
// barra (`ComprovantePage.test.tsx`) reprova — é ele que amarra a aritmética ao DOM.

/** A largura de tela que esta story tem de sustentar (Moto E / Galaxy A0x são 360px CSS). */
export const VIEWPORT_ALVO = 360;
/** `p-4` nas duas laterais. */
export const PADDING_DA_BARRA = 16;
/** `gap-2` entre as duas colunas de campo. */
export const GAP_ENTRE_CAMPOS = 8;
/**
 * Largura mínima utilizável de um `<input type="date">` no Chrome Android: o texto "dd/mm/aaaa"
 * (~90px em 14px/`text-sm`) mais o ícone do calendário e o padding horizontal do campo.
 */
export const LARGURA_MINIMA_DO_CAMPO = 130;

/** Largura de cada campo quando a barra divide a linha em `colunas` colunas iguais. */
export function larguraDoCampo(viewport: number, colunas: number): number {
  const util = viewport - PADDING_DA_BARRA * 2 - GAP_ENTRE_CAMPOS * (colunas - 1);
  return Math.floor(util / colunas);
}

/**
 * Altura da barra fixa com todos os elementos empilhados, para conferir contra o `padding-bottom`
 * da página: o último cartão da lista **não pode** ficar embaixo da barra (era assim que o
 * checkbox de baixa ficava inalcançável antes do PR #58 — só que pela outra ponta).
 *
 * Composição (a barra é um `space-y-3` dentro de um `p-4`):
 *   resumo da conta + checkbox (40) + campos conta/data (38) + botão (46) + 2 gaps (24) + p-4 (32).
 */
export const ALTURA_DA_BARRA = 40 + 38 + 46 + 12 * 2 + PADDING_DA_BARRA * 2;
/** `pb-52` = 13rem = 208px. Tem de ser ≥ `ALTURA_DA_BARRA`. */
export const PADDING_INFERIOR_DA_PAGINA = 208;

// ── A data da baixa ───────────────────────────────────────────────────────────────────────────

/**
 * ⚠️ **[Story 8.14] O TETO SAIU — e a remoção fecha um ciclo que a 8.13 abriu de propósito.**
 *
 * Até a 8.13 esta função devolvia `hoje` e o `<input type="date">` levava `max={...}`. Aquilo era
 * **faseamento**, não regra de produto: o teto garantia que nunca existisse um `payable` `paid`
 * com data futura *enquanto o estado `scheduled` não existisse* — separar os dois depois seria uma
 * migration com backfill sob `FORCE RLS`, a armadilha da 0046.
 *
 * Agora `scheduled` existe e o estado é **derivado da data** no backend (futuro ⇒ `scheduled`;
 * hoje ou passado ⇒ `paid`). Devolver `undefined` remove o `max` do campo **sem** o componente
 * precisar de um `if`: o atributo simplesmente não é renderizado.
 *
 * **Não reintroduza o teto**, e não o troque por um truncamento silencioso em `hoje` — que
 * continua sendo a "correção" tentadora: gravar uma data que o usuário não informou é inventar o
 * fato de caixa.
 *
 * A função **fica** (em vez de sumir junto com a chamada) porque ela é o lugar onde esta decisão
 * está escrita, e é a ela que o `<input>` pergunta. Um `max` some do JSX sem deixar rastro; uma
 * função que devolve `undefined` com este comentário em cima, não.
 */
export function tetoDaDataDeBaixa(_hoje: string): string | undefined {
  return undefined;
}

/**
 * Aviso (não bloqueio) quando a data escolhida cai depois de hoje.
 *
 * ⚠️ **[Story 8.14] O TEXTO MUDOU, e a frase antiga virou mentira.** Ela dizia *"pagamento
 * agendado ainda não é acompanhado pelo e1p"* — verdade até a 8.13, falso a partir daqui. Deixá-la
 * seria pior do que não avisar nada: mandaria o dono desfazer exatamente o que o produto passou a
 * fazer certo.
 *
 * O aviso continua existindo porque a informação continua sendo útil, só que agora ela **confirma**
 * em vez de alertar: o dono precisa saber que o registro vai nascer como *agendado* e que o
 * dinheiro ainda não saiu. Avisar antes é honesto; **impedir** seria reimplementar no frontend uma
 * guarda que nem existe mais no backend.
 *
 * ⚠️ **[Story 8.15] O texto virou parâmetro** (`vocab`), com o da SAÍDA como default: do lado das
 * entradas a mesma frase estaria errada em cada substantivo ("o dinheiro ainda não saiu", "a fila
 * do que você precisa pagar"). A mecânica — avisar sem impedir — é a mesma nos dois.
 */
export function avisoDeDataFutura(
  data: string,
  hoje: string,
  vocab: VocabularioDaBaixa = VOCAB_SAIDA,
): string | null {
  if (!data || data <= hoje) return null;
  return vocab.avisoFuturo;
}
