/**
 * Conferência de saldos (Story 8.7) — tipos + a FRASE. Lógica PURA da `ConferenciaPage`.
 *
 * Espelho de `ConferenciaReportOut` (Story 8.5, `bank/schemas.py`). Read-only: esta tela não
 * escreve nada, e o relatório que ela lê também não.
 *
 * **A frase vem antes da tabela.** O caminho principal do produto é *a divergência em uma frase*;
 * o detalhamento é o que se alcança quando a frase incomoda. Uma tela que abre com 43 linhas é uma
 * planilha; uma que abre com "faltam R$ 2.340 na conta Itaú PJ, provavelmente lançamentos de saída"
 * é um diagnóstico. Por isso `fraseConferencia` é uma função pura testada, e não um `<p>` montado
 * dentro do `.tsx`.
 */
import { formatDateBR } from "./contas";
import { formatBRL } from "./dre";

// ── Tipos (espelho de `ConferenciaReportOut`, Story 8.5) ─────────────────────────────────────

/**
 * A conferência de UMA conta.
 *
 * **`null` significa "não sei", jamais zero.** Sem saldo informado dentro do período,
 * `saldo_banco_cents`, `saldo_sistema_cents`, `divergencia_cents` e `dentro_da_tolerancia` vêm
 * `null` e `saldo_banco_origem` vem `indisponivel`. Um `0` em `divergencia_cents` afirmaria
 * "conferi e está batendo" — coisa que o e1p não tem lastro para dizer.
 */
export interface ConferenciaConta {
  bank_account_id: string;
  bank_account_name: string;
  bank_account_kind: string;
  saldo_banco_cents: number | null;
  /** Eixo A (plano): `banco` | `indisponivel`. Rótulo em `ORIGEM_LABEL` (`projecao.ts`). */
  saldo_banco_origem: string;
  /** Eixo B (porta de entrada): `manual` | `ofx` | `null`. Rótulo em `FONTE_LABEL`, aqui. */
  saldo_banco_fonte: string | null;
  /**
   * Data do saldo informado (o `reference_date` do checkpoint); no caminho avaliável é também a
   * data em que os DOIS saldos foram apurados. **Não-`null` com `divergencia_cents === null`
   * significa: houve declaração, o que faltou foi a comparação** (Story 8.20 — o saldo foi
   * informado na própria data de abertura da conta, e ali a comparação é tautológica).
   */
  saldo_banco_data: string | null;
  saldo_sistema_cents: number | null;
  /** Eixo A do derivado: SEMPRE `banco`, inclusive quando o valor é `null`. */
  saldo_sistema_origem: string;
  /** `banco − sistema`. `> 0` = falta ENTRADA no e1p; `< 0` = falta SAÍDA (REQ-14). */
  divergencia_cents: number | null;
  dentro_da_tolerancia: boolean | null;
  /** `max(R$ 50; 0,5%)`. `0` no caminho não avaliável — não leia quando a divergência é `null`. */
  tolerancia_cents: number;
  /** `null` = esta conta NUNCA teve saldo informado (diferente de `0` = informado hoje). */
  dias_desde_ultima_conferencia: number | null;
  movimentos_ignorados: number;
  notes: string[];
}

export interface ContaForaDaBanda {
  bank_account_id: string;
  bank_account_name: string;
  divergencia_cents: number;
  tolerancia_cents: number;
}

export interface ConferenciaReport {
  start: string;
  end: string;
  contas: ConferenciaConta[];
  /** Soma SÓ das contas avaliáveis; `null` quando nenhuma é. Nunca exibido sozinho (AC6). */
  total_divergencia_cents: number | null;
  contas_avaliadas: number;
  contas_sem_checkpoint: number;
  contas_fora_da_banda: ContaForaDaBanda[];
  notes: string[];
  /**
   * Story 8.16 — os termos da **pré-condição do gate**: o que o e1p sabe que moveu dinheiro numa
   * conta real e ainda não virou movimento bancário no período.
   *
   * ⚠️ **ANOTAM, NUNCA SUBTRAEM.** Nenhum deles entra em `divergencia_cents`, `tolerancia_cents`,
   * `dentro_da_tolerancia`, `total_divergencia_cents` nem `contas_fora_da_banda` — descontá-los
   * levaria a divergência a zero por construção sempre que o sistema soubesse explicar a diferença,
   * e a métrica primária do épico morreria. A tela **não recalcula nada** com estes números: a
   * frase de cada termo já vem pronta em `notes`, do backend (uma redação, um lugar).
   *
   * São do RELATÓRIO e não por conta porque a conta é justamente o que falta nas duas primeiras
   * populações ("não informa de qual conta saiu").
   */
  lancamentos_sem_conta_informada: number;
  valor_sem_conta_informada_cents: number;
  /** Fechou na **Onda 2b-i** (o rendimento passou a gerar movimento). Contador e frase próprios
   *  continuam: P1/P2 e P3 pedem AÇÕES diferentes do dono. */
  rendimentos_sem_perna_bancaria: number;
  valor_rendimentos_sem_perna_cents: number;
}

// ── Eixo B: a PORTA por onde o saldo externo entrou ──────────────────────────────────────────

/**
 * Rótulo do **eixo B** (`saldo_banco_fonte` ∈ `{manual, ofx}`), mapa SEPARADO do `ORIGEM_LABEL`.
 *
 * Os dois eixos respondem perguntas diferentes e não se traduzem um no outro (design §1.3.1):
 * o eixo A diz *de qual PLANO de dinheiro o número vem* (`banco` × `plataforma`), o eixo B diz
 * *por qual PORTA o saldo externo entrou* (o usuário digitou × veio do extrato). Achatar os dois
 * num mapa só foi exatamente o que produziu três vocabulários incompatíveis no design e uma camada
 * de tradução inútil na Story 8.4 — não refaça.
 */
export const FONTE_LABEL: Record<string, string> = {
  manual: "informado por você",
  ofx: "lido do extrato",
};

/**
 * Rótulo do eixo B. **O parâmetro NÃO aceita `null`, e isso é a correção — não estilo.**
 *
 * A forma anterior era `fonteLabel(fonte: string | null)` e devolvia **`"sem saldo informado"`**
 * para `null`. `saldo_banco_fonte` é `null` nos **dois** estados não avaliáveis, e nos dois a frase
 * era falsa:
 *
 * - **declarado, porém não comparável** (Story 8.20): o dono informou o saldo, e a célula ao lado
 *   exibia a data dele (`em 30/07/2026`) enquanto esta linha dizia que não havia saldo informado —
 *   a mesma linha se contradizia. É a quarta superfície agregada, que o AC5 da 8.20 não enumerou.
 * - **sem checkpoint na janela** (Story 8.19): a conta **tem** saldo de partida, informado no
 *   cadastro; `opening_balance_cents` e `opening_date` são `NOT NULL`. Dizer "sem saldo informado"
 *   é a mesma afirmação sem lastro que a 8.19 removeu da nota do bloco 4.
 *
 * **O eixo B qualifica um VALOR** — ele diz por qual porta *aquele saldo* entrou. Onde o valor é
 * `null` (a célula mostra "Não sei"), não há porta a nomear, e o consumidor **não renderiza a
 * linha** em vez de inventar um motivo. O tipo estreito é a guarda mecânica: a frase falsa não pode
 * voltar sem o `tsc` reprovar.
 */
export function fonteLabel(fonte: string): string {
  return FONTE_LABEL[fonte] ?? fonte;
}

// ── Os DOIS lados da comparação (UX-001) ─────────────────────────────────────────────────────

/**
 * Os nomes dos **dois lados da conferência** — o par que o UX-001 (gate do Epic 8) exigiu.
 *
 * **O defeito que este par corrige.** Esta tela chamava o checkpoint de *"Saldo no banco"* enquanto
 * a Projeção de Caixa chama de **"no banco"** (`ROTULO_BANCO`, em `projecao.ts`) o saldo
 * **derivado** — o lado OPOSTO desta mesma subtração. As duas pontas exatas da comparação cujo
 * produto é a diferença entre elas, com a mesma palavra. Num produto cujo valor inteiro é ser
 * testemunha confiável do dado, dois conceitos opostos com o mesmo nome não é detalhe de UI.
 *
 * **Por que ESTE par e não "Saldo A" × "Saldo B".** O verbo carrega a diferença conceitual:
 * **"diz"** é uma afirmação externa (o extrato, que o e1p não produziu e não pode conferir sozinho)
 * e **"calculou"** é uma derivação interna (a soma dos movimentos lançados). Nomes meramente
 * distintos teriam removido a colisão sem ensinar a diferença.
 *
 * ⚠️ **Invariantes travadas em `conferencia.test.ts` — não relaxe nenhuma:**
 *  - o lado do **e1p nunca contém a palavra "banco"** — foi essa metade que produziu o defeito;
 *  - o lado do **banco nunca fala em cálculo/derivação** — é justamente o número que o e1p *não*
 *    produziu;
 *  - nenhum dos dois é, nem contém, `ROTULO_BANCO` / `TOTAL_EM_CONTAS_LABEL` /
 *    `DISPONIVEL_CAIXA_LABEL` — os outros três rótulos de saldo já em uso no produto.
 */
export const LADO_BANCO_LABEL = "O que o banco diz";
export const LADO_E1P_LABEL = "O que o e1p calculou";

/**
 * Legenda que cobre as duas colunas acima. É o que torna o par **visualmente** um par: sem ela, os
 * dois rótulos são só duas colunas vizinhas entre sete, e a tela não diz que a leitura é uma
 * comparação entre elas (a `Divergência`, três colunas adiante, é o resultado desta subtração).
 */
export const LADOS_GRUPO_LABEL = "Os dois lados da conferência";

// ── A frase ──────────────────────────────────────────────────────────────────────────────────

/**
 * Tom da frase de uma conta.
 *
 * - `ok` — dentro da banda. **🟢 e silêncio**: nenhum ícone de alerta, nenhuma cor de erro.
 * - `atencao` — fora da banda, banco ACIMA do sistema (falta lançamento de ENTRADA). Amarelo:
 *   dinheiro a mais na conta do que o e1p registrou é falha de registro, não buraco no caixa.
 * - `alerta` — fora da banda, banco ABAIXO do sistema (falta lançamento de SAÍDA). Vermelho: é o
 *   achado de maior valor do épico (REQ-14) — o dinheiro saiu e o e1p não sabe.
 * - `desconhecido` — a comparação não é avaliável (sem saldo informado na janela **ou** saldo
 *   informado na data de abertura da conta). Não é erro nem sucesso: é "não dá para conferir".
 */
export type TomConferencia = "ok" | "atencao" | "alerta" | "desconhecido";

export interface FraseConferencia {
  tom: TomConferencia;
  texto: string;
}

/**
 * A frase de UMA conta — o produto desta tela. PURA.
 *
 * Quatro casos, e o texto **sempre nomeia a conta**. Três deles trazem o número; o quarto
 * (`desconhecido`) não traz **nenhum**, de propósito: inventar um "R$ 0,00 de divergência" para
 * uma conta que nunca foi conferida seria afirmar que está batendo. A ausência do número é a
 * informação.
 *
 * O caso `desconhecido` tem **dois ramos** (Story 8.20), porque tem dois motivos: *nenhum saldo
 * informado* (o comum, e o texto convida a declarar) × *saldo informado na própria data de abertura
 * da conta*, em que a comparação seria tautológica e pedir "declare o saldo" mandaria o dono repetir
 * o ato que ele acabou de fazer. O discriminador é `saldo_banco_data`, que o backend mantém
 * preenchido no segundo caso.
 *
 * A frase é **acionável**, não apenas numérica: divergência negativa diz *"provavelmente faltam
 * lançamentos de saída"*, porque o critério de sucesso do fundador é *"quantos lançamentos
 * faltantes foram encontrados"*, nunca *"fechou em zero"* (REQ-13/REQ-14).
 *
 * O caminho `ok` NÃO grita. `max(R$ 50; 0,5%)` é a banda, e dentro dela a resposta é que está tudo
 * batendo — alertar sobre R$ 3,50 num saldo de R$ 25.000 treina o usuário a ignorar o alerta, e o
 * alerta é o produto (REQ-16).
 */
export function fraseConferencia(c: ConferenciaConta): FraseConferencia {
  // Guarda pelos DOIS campos (e não `!c.divergencia_cents`): `0` é uma divergência avaliada e
  // legítima — "conferi, bateu exatamente" — e a forma negada a mandaria para o caso "não sei".
  if (c.divergencia_cents === null || c.dentro_da_tolerancia === null) {
    // Story 8.20 — DOIS motivos para "não avaliável", e eles pedem ações diferentes. O
    // discriminador é `saldo_banco_data` (o backend o mantém preenchido quando houve declaração):
    // sem ele, a tela mandaria "declare o saldo" para quem acabou de declarar, em laço. Os dois
    // ramos continuam com o tom `desconhecido` — nenhum tom novo, nenhuma cor nova, nenhum alerta.
    if (c.saldo_banco_data !== null) {
      return {
        tom: "desconhecido",
        texto:
          `Você informou o saldo da conta ${c.bank_account_name} em ` +
          `${formatDateBR(c.saldo_banco_data)}, o mesmo dia em que ela foi aberta no e1p — ` +
          "nesse dia ainda não havia movimento para somar, então essa comparação não decide " +
          "nada. Informe o saldo de um dia posterior para eu conferir de verdade.",
      };
    }
    return {
      tom: "desconhecido",
      texto:
        `Não sei o saldo da conta ${c.bank_account_name} nesta janela — ` +
        "declare o saldo para eu conferir.",
    };
  }

  const diferenca = formatBRL(Math.abs(c.divergencia_cents));

  if (c.dentro_da_tolerancia) {
    return {
      tom: "ok",
      texto:
        `Está tudo batendo na conta ${c.bank_account_name} ` +
        `(diferença de ${diferenca}, dentro da tolerância de ${formatBRL(c.tolerancia_cents)}).`,
    };
  }

  const abaixo = c.divergencia_cents < 0;
  // UX-001: a frase nomeia os dois lados com o MESMO par das colunas — "o banco diz" (afirmação
  // externa) × "eu calculei" (derivação do e1p; o "eu" desta tela é o próprio e1p, como em "Não sei
  // o saldo…"). A forma anterior — "Seu saldo no banco está X abaixo do que eu calculei" — chamava
  // de "no banco" o checkpoint, exatamente a string que a Projeção usa para o número DERIVADO.
  return {
    tom: abaixo ? "alerta" : "atencao",
    texto:
      `O banco diz que a conta ${c.bank_account_name} está ${diferenca} ` +
      `${abaixo ? "abaixo" : "acima"} do que eu calculei. Provavelmente faltam lançamentos de ` +
      `${abaixo ? "saída" : "entrada"}.`,
  };
}

export interface TomVisual {
  emoji: string;
  rotulo: string;
  /** Classes do cartão da frase. O tom `ok` **não** tem cor de erro nem anel de alerta. */
  cardClass: string;
  /** `true` só nos tons que autorizam um ícone de alerta na tela (AC5). */
  alerta: boolean;
}

/**
 * Config visual por tom. Mesmo formato de `signalVisual` (`diagnostico.ts`).
 *
 * ⚠️ `ok.alerta === false` e `desconhecido.alerta === false` são o AC5 em forma de dado: a página
 * só renderiza ícone de alerta quando `alerta` é `true`. Trocar isto por um "amarelinho quando não
 * é exatamente zero" é a regressão mais fácil e mais cara desta story.
 */
export const TOM_VISUAL: Record<TomConferencia, TomVisual> = {
  ok: {
    emoji: "🟢",
    rotulo: "Batendo",
    cardClass: "bg-emerald-50 ring-1 ring-emerald-200",
    alerta: false,
  },
  atencao: {
    emoji: "🟡",
    rotulo: "Falta entrada",
    cardClass: "bg-amber-50 ring-1 ring-amber-200",
    alerta: true,
  },
  alerta: {
    emoji: "🔴",
    rotulo: "Falta saída",
    cardClass: "bg-red-50 ring-1 ring-red-200",
    alerta: true,
  },
  desconhecido: {
    emoji: "⚪",
    rotulo: "Não sei",
    cardClass: "bg-neutral-50 ring-1 ring-neutral-200",
    alerta: false,
  },
};

export function tomVisual(tom: TomConferencia): TomVisual {
  return TOM_VISUAL[tom];
}

/**
 * Ordem de leitura das contas: **o que dói primeiro**. PURA.
 *
 * Avaliáveis por `|divergência|` decrescente; as não avaliáveis ("não sei") **por último** — elas
 * pedem uma ação diferente (declarar o saldo) e, no topo, empurrariam para baixo justamente a
 * conta que tem um furo mensurável. `Array.prototype.sort` é estável, então contas empatadas
 * mantêm a ordem em que o backend as devolveu.
 */
export function ordenarContas(contas: ConferenciaConta[]): ConferenciaConta[] {
  const avaliaveis = contas.filter((c) => c.divergencia_cents !== null);
  const naoAvaliaveis = contas.filter((c) => c.divergencia_cents === null);
  const porDor = [...avaliaveis].sort(
    (a, b) => Math.abs(b.divergencia_cents ?? 0) - Math.abs(a.divergencia_cents ?? 0),
  );
  return [...porDor, ...naoAvaliaveis];
}

/**
 * Aviso obrigatório quando o consolidado **não cobre todas as contas** (AC6). PURA.
 *
 * `null` quando cobre todas — nesse caso não há nada a ressalvar e um aviso permanente viraria
 * decoração. O consolidado nunca aparece sem a decomposição ao lado; quando ele além disso é
 * PARCIAL, dizer isso em texto é o mínimo.
 */
export function avisoTotalParcial(report: ConferenciaReport): string | null {
  const n = report.contas_sem_checkpoint;
  if (n <= 0) return null;
  // Story 8.20 — "não avaliada", e não "sem saldo informado": há DOIS motivos para uma conta ficar
  // de fora do total, e afirmar aqui o primeiro seria mentir sobre o segundo. O motivo de cada
  // conta está na nota dela, logo acima nesta mesma tela.
  return n === 1
    ? "Esta soma não cobre todas as suas contas: 1 conta não foi avaliada no período e ficou de fora."
    : `Esta soma não cobre todas as suas contas: ${n} contas não foram avaliadas no período e ficaram de fora.`;
}

/**
 * Frase do contador de abandono (bloco 4 da 8.5), quando houver. PURA.
 *
 * `null` (nunca declarado) vira um convite, não um número — e `0` (declarado hoje) não vira frase
 * nenhuma: dizer "conferido há 0 dias" é ruído.
 */
export function avisoUltimaConferencia(c: ConferenciaConta): string | null {
  const dias = c.dias_desde_ultima_conferencia;
  if (dias === null) return "Esta conta nunca teve saldo informado.";
  if (dias <= 0) return null;
  return `Saldo não confirmado há ${dias} ${dias === 1 ? "dia" : "dias"}.`;
}
