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
 * particular já está agendado: a **Story 8.14** remove o teto de hoje (`MAX_DATA`) no mesmo commit
 * em que o estado `scheduled` passa a existir.
 */

/** Só o que estas telas precisam de uma conta bancária. Espelho parcial de `financeiro/contas`. */
export interface ContaDeBaixa {
  id: string;
  name: string;
  is_primary: boolean;
  archived_at: string | null;
}

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
export function rotuloDaAcao(base: string, nomeConta: string): string {
  return nomeConta ? `${base} · sai do ${nomeConta}` : base;
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
 * ⚠️ **O teto de hoje SAI NA STORY 8.14** — não o remova antes, e não o troque por um truncamento
 * silencioso em `hoje` (gravar uma data que o usuário não informou é inventar o fato de caixa).
 *
 * Ele existe para garantir que **nunca exista um `payable` `paid` com data futura** enquanto o
 * estado `scheduled` não existir: separar os dois depois seria uma migration com backfill sob
 * `FORCE RLS`, a armadilha da 0046. Na 8.14 o `max` sai no mesmo commit em que `scheduled` nasce, e
 * o estado passa a ser **derivado da data** (futuro ⇒ `scheduled`; hoje ou passado ⇒ `paid`).
 *
 * Isto é o **espelho** da guarda de `payables.service._valida_data_de_baixa`, não uma segunda
 * implementação dela: o backend continua sendo quem recusa, com a mensagem que nomeia as saídas.
 */
export function tetoDaDataDeBaixa(hoje: string): string {
  return hoje;
}

/**
 * Aviso (não bloqueio) quando a data pré-preenchida cai depois de hoje — o caso de pagar
 * adiantado uma conta com vencimento futuro, em que o default `due_date` do AC1 bate no teto acima.
 *
 * Avisar antes é honesto; **impedir** seria reimplementar no frontend uma guarda que é do backend,
 * e o 422 dele já nomeia as duas saídas ("informe o dia em que ele saiu" / "dê a baixa quando o
 * dinheiro sair"). A tela exibe aquela mensagem como veio.
 */
export function avisoDeDataFutura(data: string, hoje: string): string | null {
  if (!data || data <= hoje) return null;
  return (
    "Esta conta vence depois de hoje. Informe o dia em que o dinheiro saiu da conta — " +
    "pagamento agendado ainda não é acompanhado pelo e1p."
  );
}
