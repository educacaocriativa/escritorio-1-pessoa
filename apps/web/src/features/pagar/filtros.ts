import type { PayableStatus } from "@e1p/shared-types";

/** O recorte da lista de Contas a Pagar. `de`/`ate` são YYYY-MM-DD ou `null` (sem limite). */
export type FiltroPagar = {
  status: PayableStatus[];
  de: string | null;
  ate: string | null;
  q: string;
  centroDeCusto: string;
  categoria: string;
};

const DIAS_NO_MES = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function bissexto(ano: number): boolean {
  return (ano % 4 === 0 && ano % 100 !== 0) || ano % 400 === 0;
}

/**
 * Último dia do mês SEGUINTE ao de `hojeYmd`, também em YYYY-MM-DD.
 *
 * Aritmética de string, nunca `new Date`: o `hojeYmd` já chega no fuso do tenant (via
 * `today(useFuso())`), e reconstruir um `Date` a partir dele devolveria o cálculo ao fuso do
 * navegador — em UTC-3, das 21h à meia-noite o horizonte pularia um dia inteiro.
 */
export function fimDoMesSeguinte(hojeYmd: string): string {
  const [ano0, mes0] = hojeYmd.split("-").map(Number);
  // `mes0` é 1-based; usá-lo como índice 0-based já aponta para o mês seguinte.
  const ano = ano0 + Math.floor(mes0 / 12);
  const mes = (mes0 % 12) + 1;
  const dias = mes === 2 && bissexto(ano) ? 29 : DIAS_NO_MES[mes - 1];
  return `${ano}-${String(mes).padStart(2, "0")}-${String(dias).padStart(2, "0")}`;
}

/**
 * A visão padrão: "o que eu devo".
 *
 * `de: null` é deliberado e não é esquecimento. Atrasado tem vencimento no passado; qualquer piso
 * de data esconde exatamente a conta mais urgente que existe. O que o horizonte corta é só o
 * futuro distante — e o lugar de olhar longe é a Projeção de caixa.
 */
export function filtroPadrao(hojeYmd: string): FiltroPagar {
  return {
    status: ["open", "scheduled"],
    de: null,
    ate: fimDoMesSeguinte(hojeYmd),
    q: "",
    centroDeCusto: "",
    categoria: "",
  };
}

/** Histórico se lê do mais recente para o mais antigo; o que se deve, do mais próximo em diante. */
function ordem(status: PayableStatus[]): "asc" | "desc" {
  const olhandoParaTras = status.every((s) => s === "paid" || s === "canceled");
  return status.length > 0 && olhandoParaTras ? "desc" : "asc";
}

/** Serializa para os `params` do axios. Chave vazia é OMITIDA, nunca mandada como null. */
export function paraQuery(
  f: FiltroPagar,
  limit: number,
  offset: number,
): Record<string, unknown> {
  const q: Record<string, unknown> = { order: ordem(f.status), limit, offset };
  if (f.status.length > 0) q.status = f.status;
  if (f.de) q.from = f.de;
  if (f.ate) q.to = f.ate;
  if (f.q.trim()) q.q = f.q.trim();
  if (f.centroDeCusto) q.cost_center_id = f.centroDeCusto;
  if (f.categoria) q.chart_account_id = f.categoria;
  return q;
}

/** Os quatro status que existem. Tudo o que chega da URL fora desta lista é lixo e é descartado. */
const STATUS_VALIDOS: readonly string[] = ["open", "scheduled", "paid", "canceled"];

function mesmoStatus(a: PayableStatus[], b: PayableStatus[]): boolean {
  return a.length === b.length && a.every((s, i) => s === b[i]);
}

/**
 * As chaves do recorte na BARRA DE ENDEREÇO — e ela fala a língua da TELA, não a da API.
 *
 * `de`/`ate`/`centro`/`categoria`, e **não** `from`/`to`/`cost_center_id`/`chart_account_id`. As
 * duas serializações existem de propósito e não devem convergir:
 *
 * - `paraQuery` fala com o FastAPI. Aqueles nomes são contrato de servidor: mudam quando a rota
 *   muda, e devem mesmo.
 * - `paraUrl` fala com o DONO. O endereço é digitado à mão, mandado por WhatsApp e virado favorito.
 *   Um link salvo hoje não pode quebrar porque a API renomeou um parâmetro interno, e ninguém
 *   escreve `chart_account_id=` na barra de endereço de propósito.
 *
 * As chaves são exatamente os campos de `FiltroPagar` (com `centro`/`categoria` pelos nomes curtos
 * que a tela já usa nos rótulos), o que torna a ida e volta uma CÓPIA, não uma tradução: não há
 * tabela de-para para sair de sincronia entre as duas direções.
 */

/**
 * `FiltroPagar` → query string, **omitindo tudo o que é igual ao padrão**.
 *
 * Só o que o dono realmente escolheu aparece no endereço: `/pagar` limpo é a visão padrão, e um
 * `?status=open&status=scheduled&ate=2026-09-30` que só repete o default seria poluição que o dono
 * teria de ler toda vez.
 *
 * ⚠️ Isso também é o que mantém o favorito VIVO: `ate` omitido acompanha o horizonte móvel
 * ("fim do mês que vem", recalculado no fuso do tenant a cada abertura), enquanto um `ate=` escrito
 * na URL é uma data FIXA que o dono pediu. Escrever o default congelaria o favorito na data do dia
 * em que ele foi salvo.
 *
 * Três campos de texto (`q`, `centro`, `categoria`) têm `""` como padrão: para eles vazio é o
 * default e a chave é OMITIDA, nunca mandada como `?q=`. Já `status: []` ("todos") e `de`/`ate`
 * `null` ("sem limite") são VALORES escolhidos, não vazio — quando diferem do padrão eles viram
 * chave presente de valor vazio (`?ate=`), que é o único jeito de a volta ser fiel.
 */
export function paraUrl(f: FiltroPagar, padrao: FiltroPagar): URLSearchParams {
  const u = new URLSearchParams();
  if (!mesmoStatus(f.status, padrao.status)) {
    // Repetível: `?status=open&status=scheduled`. Nunca `status[]` nem `status=open,scheduled` —
    // o primeiro o FastAPI ignora em silêncio (#125), o segundo obrigaria a inventar um separador.
    if (f.status.length === 0) u.set("status", "");
    else for (const s of f.status) u.append("status", s);
  }
  if (f.de !== padrao.de) u.set("de", f.de ?? "");
  if (f.ate !== padrao.ate) u.set("ate", f.ate ?? "");
  if (f.q !== padrao.q) u.set("q", f.q);
  if (f.centroDeCusto !== padrao.centroDeCusto) u.set("centro", f.centroDeCusto);
  if (f.categoria !== padrao.categoria) u.set("categoria", f.categoria);
  return u;
}

/**
 * Query string → `FiltroPagar`. O que a URL não diz, o `padrao` diz — URL vazia é o filtro padrão.
 *
 * ⚠️ **Nenhuma data é reconstruída aqui.** `de`/`ate` chegam como string `YYYY-MM-DD` e seguem
 * string até o axios. Passar por `new Date` devolveria a conta ao relógio do NAVEGADOR, e o e1p
 * vive no fuso do tenant desde o #78 — o mesmo motivo pelo qual `fimDoMesSeguinte` faz aritmética
 * de string ali em cima.
 */
export function daUrl(params: URLSearchParams, padrao: FiltroPagar): FiltroPagar {
  const status = params.has("status")
    ? (params.getAll("status").filter((s) => STATUS_VALIDOS.includes(s)) as PayableStatus[])
    : padrao.status;
  const data = (chave: string, queda: string | null) =>
    params.has(chave) ? params.get(chave) || null : queda;
  return {
    status,
    de: data("de", padrao.de),
    ate: data("ate", padrao.ate),
    q: params.get("q") ?? padrao.q,
    centroDeCusto: params.get("centro") ?? padrao.centroDeCusto,
    categoria: params.get("categoria") ?? padrao.categoria,
  };
}

/**
 * Nenhum campo além do `q` mudou? Então foi digitação, e a URL se REESCREVE em vez de empilhar.
 *
 * É esta função que decide se o botão "voltar" tem o que desfazer. Uma entrada de histórico por
 * tecla digitada obrigaria o dono a apertar "voltar" nove vezes para sair de «anthropic»; já trocar
 * o status ou aplicar um período é um gesto deliberado, e desfazê-lo é exatamente o que ele espera
 * do botão. Sem essa distinção, "voltar" ou sai da tela inteira ou não sai nunca.
 */
export function apenasTexto(antes: FiltroPagar, depois: FiltroPagar): boolean {
  return (
    mesmoStatus(antes.status, depois.status) &&
    antes.de === depois.de &&
    antes.ate === depois.ate &&
    antes.centroDeCusto === depois.centroDeCusto &&
    antes.categoria === depois.categoria
  );
}
