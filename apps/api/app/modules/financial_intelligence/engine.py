"""Motor de indicadores PURO e DETERMINÍSTICO (Story 5.8, AC1/AC2, IV1/NFR3).

Este módulo é o coração da Story 5.8 e o motivo de toda a iniciativa: **os sinais de
diagnóstico 🟢🟡🔴 são calculados aqui, por regras determinísticas, ANTES de qualquer IA.**
A IA (ver `ai_narrator.py`) só NARRA os sinais já calculados — nunca origina um número.

Regra de design (NÃO NEGOCIÁVEL — IV1/NFR3): este arquivo é ESTRITAMENTE PURO.
  - NÃO importa `Session`, NÃO faz query, NÃO chama `core.ai`, NÃO chama `core.anonymizer`.
  - Recebe estruturas Python já calculadas (dataclasses de entrada abaixo, alimentadas por
    `diagnostics.py` a partir das saídas das Stories 5.4/5.6/5.7) e devolve `list[Signal]`.
  - Puramente funcional, sem efeito colateral. É o que o torna "testável isoladamente": o teste
    (test_financial_intelligence_engine.py) não precisa de banco nem de rede.

[AUTO-DECISION] A Story cita como entrada `DreReportOut`/`ProjectionOut`/etc. Optamos por
dataclasses de entrada PRÓPRIAS e mínimas (definidas aqui) em vez de importar os schemas Pydantic
dos outros módulos. Motivo: manter o motor 100% desacoplado de qualquer outro módulo (o mais forte
possível para a garantia IV1 — o engine não pode nem "ver" a camada de I/O), e tornar o teste
unitário trivial de montar. A adaptação schema-Pydantic → entrada-do-engine vive em `diagnostics`.
Duas entradas (`MarginTrend`, `InvestmentReturn`) carregam o NOME do projeto/aplicação — que os
Out schemas não expõem (só id) mas as explicações numéricas do AC1 exigem (ex.: "Projeto X: ...").

Story 8.6 usou exatamente este ponto de extensão: a regra de **completude** (`CompletenessInput`,
alimentada pela conferência da 8.5 via `diagnostics.py`) entrou como mais uma dataclass de entrada e
mais uma função pura — **sem** uma linha de I/O aqui dentro. É essa a razão prática da regra de
design acima: o motor pôde ganhar a regra de maior peso do Epic 8 sem deixar de ser testável sem
banco. `CompletenessAccountInput.account_name` percorre o MESMO caminho de PII de
`MarginTrend.project_name` (anonimizado pelo narrador na saída, nunca aqui).

Story 8.16 usou o mesmo ponto de extensão duas vezes mais (`OffRailInput` e `DebitoSuspeitoInput`),
e a segunda é a que mais teria puxado I/O para cá: o motor precisa saber **quando** um débito saiu
para escrever "de 15/08" na frase. `data_debito` chega **pronta**, e o motor **não** compara com
hoje — quem decide o que é suspeito é `diagnostics.py`. `DebitoSuspeitoInput.descricao` (nome de
fornecedor) e `.bank_account_name` percorrem o MESMO caminho de PII acima.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# ── Níveis de sinal (🟢🟡🔴). Ordem de prioridade: vermelho > amarelo > verde. ──────────────
VERDE = "verde"
AMARELO = "amarelo"
VERMELHO = "vermelho"

# Rank determinístico para a priorização (AC1 "sinais priorizados"). Menor = mais urgente.
_LEVEL_RANK: dict[str, int] = {VERMELHO: 0, AMARELO: 1, VERDE: 2}

# ── Limiares determinísticos (documentados; extensíveis sem tocar na estrutura) ─────────────
# Margem de contribuição caindo (em pontos percentuais, p.p.):
_MARGIN_DROP_YELLOW_PP = 8.0   # queda ≥ 8 p.p. → 🟡
_MARGIN_DROP_RED_PP = 15.0     # queda ≥ 15 p.p. (ou margem final negativa) → 🔴
# Runway (dias de fôlego de caixa):
_RUNWAY_RED_DAYS = 60          # < 60 dias → 🔴
_RUNWAY_YELLOW_DAYS = 120      # < 120 dias → 🟡
# Completude dos lançamentos (Story 8.6): a partir de quantos dias um saldo confirmado deixa de
# ser prova de que o sistema está completo. `> 45` → 🟡 "e essa medição é de N dias atrás".
_COMPLETENESS_STALE_DAYS = 45
# Casamento entre UM débito e a divergência POSITIVA da conta dele (Story 8.16, ratificação §C-2.3
# ajuste 2): `|valor − divergencia| <= max(R$ 50; 10% da divergência)`.
#
# ⚠️ **É a MESMA FORMA da banda de tolerância da conferência (`max(R$ 50; 0,5%)`) e um percentual
# DIFERENTE DE PROPÓSITO — não "harmonize" os dois números.** A banda responde *"esta diferença é
# ruído estrutural?"* e por isso é generosa; este critério responde *"este débito explica esta
# divergência?"*, que é pergunta muito mais estrita. O intervalo `[0,5×, 2×]` proposto no rascunho
# foi **REJEITADO**: com fator 2, um débito de R$ 5.000 seria nomeado diante de uma divergência de
# R$ 2.500 — e **nomear um débito inocente é pior do que ficar calado**, porque "pode não ter saído"
# sobre um débito que obviamente saiu treina o dono a ignorar a tela.
_DEBITO_MATCH_FLOOR_CENTS = 5_000  # R$ 50,00 — o piso, que domina em divergência pequena
_DEBITO_MATCH_DIVISOR = 10  # 10% — o componente que domina em divergência grande


@dataclass(frozen=True)
class Signal:
    """Um sinal de diagnóstico determinístico. `explanation` SEMPRE traz o número que o justifica
    (AC1 "explicação numérica"). `source` identifica a regra/origem (5.4/5.6/5.7) — a UI rotula."""

    level: str  # VERDE | AMARELO | VERMELHO
    title: str
    explanation: str
    source: str


# ── Entradas do motor (puras — montadas por diagnostics.py) ─────────────────────────────────
@dataclass(frozen=True)
class MarginTrend:
    """Margem de contribuição de UM projeto/contrato em dois períodos consecutivos (Story 5.4).

    `project_name` é o título do contrato (pode conter PII — anonimizado DEPOIS pelo narrador, nunca
    aqui). `margem_pct_antes`/`margem_pct_depois` são FRAÇÕES (ex.: 0.28 = 28%), como a 5.4 expõe
    (`margem_contribuicao_pct`), ou None quando não há receita no período (proteção div/0)."""

    project_name: str
    margem_pct_antes: float | None
    margem_pct_depois: float | None
    period_label: str  # ex.: "1 mês" — a janela de comparação (não é PII)


@dataclass(frozen=True)
class ProjectionWindowInput:
    """Uma janela da projeção de caixa (Story 5.7). `alert` já vem calculado pela 5.7 (saldo
    projetado negativo na janela) — o motor o CONSOME sem recalcular (reuso direto do campo)."""

    days: int
    alert: bool


@dataclass(frozen=True)
class InvestmentReturn:
    """Rentabilidade de UMA aplicação no período (Story 5.6). `name` pode conter PII (anonimizado
    depois). `period_rentability_pct` é FRAÇÃO (ex.: -0.02 = -2%) ou None quando principal == 0."""

    name: str
    period_rentability_pct: float | None


@dataclass(frozen=True)
class CompletenessAccountInput:
    """UMA conta bancária, já conferida (ou não) pelo serviço de conferência (Story 8.5).

    `account_name` pode conter PII → é anonimizado pelo NARRADOR na saída para o Claude, **nunca
      aqui** (exatamente o caminho que `MarginTrend.project_name` já percorre — Regra de Ouro nº 2).
    `divergencia_cents = None` significa **NÃO AVALIÁVEL** (não havia saldo declarado utilizável na
      janela) — jamais "zero". Confundir os dois faz o motor afirmar que está batendo aquilo que o
      sistema nunca conferiu, que é o pior modo de falha deste diagnóstico.
    `tolerancia_cents` chega **pronta** da conferência (`max(R$ 50; 0,5%)`, §5.1): o motor **não
      recalcula banda nenhuma**, só compara `abs(divergencia) > tolerancia`.
    `dias_desde_ultima_conferencia = None` = esta conta nunca teve saldo confirmado (≠ `0`, que é
      "confirmado hoje"). Mora na CONTA, e não no relatório, de propósito: colapsar por `max()`
      perderia *qual* conta está desatualizada — o mesmo vício do consolidado que a decisão do
      fundador F3 proíbe (design §5.3, ratificação D-2 Ajuste 1).
    """

    account_name: str
    divergencia_cents: int | None
    tolerancia_cents: int
    dias_desde_ultima_conferencia: int | None


@dataclass(frozen=True)
class CompletenessInput:
    """Completude dos lançamentos, **por conta** (Story 8.6).

    `contas == []` = nenhuma conta bancária cadastrada (o estado de todos os tenants no dia do
    deploy) — e isso, por si só, é um 🟡: sem conta cadastrada o e1p **não sabe** se os lançamentos
    estão completos, e calar sobre isso seria mentir por omissão.

    `movimentos_sem_contrapartida` nasce **0 por construção** na Onda 1 (não existe conciliação:
    `bank_reconciliations` é da Onda 4) e a regra só acorda na Onda 3. **PROIBIDO** aproximar por
    "movimentos `unmatched`": na Onda 1 *todo* movimento é unmatched por definição, e esse número
    alimenta o gate de decisão do epic §3.1 — inventá-lo aqui custaria ~4,5 ondas de trabalho
    decididas sobre uma métrica falsa (Constitution Art. IV).
    """

    contas: list[CompletenessAccountInput]
    movimentos_sem_contrapartida: int = 0


@dataclass(frozen=True)
class OffRailInput:
    """Recebimentos que entraram **direto na conta do dono**, na janela do relatório (Story 8.16).

    Os dois conjuntos, com membro e não-membro escritos (Regra da Instanciação Obrigatória):

    `recebimentos_fora_do_trilho` (o **N**) — cobranças recebidas na janela **por fora** da cobrança
      do e1p (o dono registrou em qual conta o dinheiro caiu).
      • Membro: um Pix de R$ 1.400 registrado pelo dono em 12/07.
      • Não-membro: uma cobrança paga pelo gateway em 12/07 — ela entrou pelo trilho e está no
        DENOMINADOR, nunca no numerador.
    `recebimentos_total` (o **M**) — todos os recebimentos da janela, pelas **duas** rotas.
      • Membro: as duas do parágrafo acima.
      • Não-membro: o lançamento sintético de rendimento de aplicação — **não é recebimento de
        cliente**, e incluí-lo faria o *"N dos M"* mentir para quem usa Investimentos.
      • Não-membro 2: cobrança em aberto ou cancelada na janela — não foi recebida.

    Quem aplica esses recortes é `diagnostics.py`; aqui os números chegam **prontos**. O motor não
    sabe o que é uma `Charge`, e é isso que o mantém testável sem banco.
    """

    recebimentos_fora_do_trilho: int
    recebimentos_total: int
    valor_fora_do_trilho_cents: int


@dataclass(frozen=True)
class DebitoSuspeitoInput:
    """UM débito cuja **saída da conta pode não ter acontecido**. Já vem filtrado, de fora.

    ⚠️ **`DebitoSuspeitoInput`, e não `AgendamentoSuspeitoInput`** (ratificação §C-2.3, ajuste 1):
    *"o efeito existe; o adjetivo não"*. Depois que o worker promove `scheduled → paid`, **nada no
    dado distingue** *"eu agendei e o banco não executou"* de *"eu paguei no caixa e o banco não
    compensou"* — e um nome que diz uma coisa carregando outra é o defeito que este épico já cometeu
    duas vezes. O valor do sinal está em apontar **qual** débito casa com a divergência, não no
    adjetivo.

    `descricao` (nome de fornecedor) e `bank_account_name` **podem conter PII** → são anonimizados
      pelo NARRADOR na saída para o Claude, **nunca aqui** (o mesmo caminho de
      `MarginTrend.project_name` e de `CompletenessAccountInput.account_name`).
    `data_debito` é a data em que o débito deveria ter saído, e **chega pronta**: o motor não
      calcula "já venceu", não compara com hoje e não importa relógio nenhum (IV1). Quem decide o
      que entra nesta lista é `diagnostics.py`.
    `bank_account_name` é o que liga este débito à conta cuja divergência ele pode explicar — o
      casamento acontece contra `CompletenessAccountInput.account_name`, que é o único
      identificador de conta que o motor conhece (ele não vê ids, por design).
    """

    descricao: str
    valor_cents: int
    data_debito: date
    bank_account_name: str


@dataclass(frozen=True)
class EngineInput:
    """Snapshot de entrada do motor. Tudo já calculado pelas Stories anteriores; o motor só decide
    os sinais. Campos são listas/valores simples → o teste unitário monta à mão, sem I/O.

    `completeness` (8.6), `off_rail` e `debitos_suspeitos` (8.16) são os ÚLTIMOS campos e têm
    default `None`: as chamadas e os testes das Stories 5.8 e 8.6 continuam válidos **sem edição**,
    e `None` produz **zero** sinal em cada uma das três regras."""

    margins: list[MarginTrend]
    runway_days: int | None
    projection_windows: list[ProjectionWindowInput]
    investments: list[InvestmentReturn]
    completeness: CompletenessInput | None = None
    off_rail: OffRailInput | None = None
    debitos_suspeitos: list[DebitoSuspeitoInput] | None = None


def _pct_display(fraction: float) -> int:
    """Fração (0.28) → percentual inteiro para exibição (28). Determinístico."""
    return round(fraction * 100)


def _brl(cents: int) -> str:
    """Centavos → reais legíveis (`234000` → `"R$ 2.340,00"`). Função **pura** e privada.

    Aritmética **inteira** (`divmod`), sem passar por `float` em ponto nenhum: dinheiro é `int` em
    centavos (Regra de Ouro) e um `cents/100` aqui reintroduziria o float justamente no texto que o
    usuário vai ler. Vive no `engine.py` de propósito — importar um helper de fora quebraria a
    pureza do motor (IV1), e a formatação é três linhas.
    """
    sinal = "-" if cents < 0 else ""
    inteiros, centavos = divmod(abs(cents), 100)
    milhares = format(inteiros, ",").replace(",", ".")  # 2340 → "2.340" (separador pt-BR)
    return f"{sinal}R$ {milhares},{centavos:02d}"


def _completeness_signals(data: CompletenessInput | None) -> list[Signal]:
    """Regra 0 — **completude dos lançamentos** (Story 8.6, `source="completude"`).

    É a regra avaliada PRIMEIRO (ver `compute_signals`) porque tem **precedência semântica**: se o
    sistema não sabe se os lançamentos estão completos, margem, runway e rentabilidade estão
    calculados sobre base possivelmente furada — *"não confio nos outros sinais até você fechar
    isto"* (design §5.3).

    | Condição | Nível | Cardinalidade |
    |---|---|---|
    | `data is None` | — | 0 (motor chamado sem a entrada — compatibilidade com a 5.8) |
    | `contas == []` | 🟡 | 1 por relatório |
    | conta com `divergencia is None`/`dias is None`/`dias > 45` | 🟡 | **1 por conta** |
    | conta com `abs(divergencia) > tolerancia` | 🔴 | **1 por conta**, nomeando a conta |
    | `movimentos_sem_contrapartida > 0` | 🟡 | 1 (dormente até a Onda 3) |
    | todas avaliáveis, dentro da banda e frescas | 🟢 | 1 |

    **Uma conta gera no máximo UM 🟡 de "não sei"** (ratificação D-2 Ajuste 2): as duas regras de
    "não sei" do rascunho — *"sem comparação avaliável no período"* e *"não confirmado há N dias"*
    — são **uma só**, cujo texto diz qual dos casos é. Num tenant com 3 contas nenhuma conferida, a
    versão separada produziria **seis** sinais dizendo a mesma coisa: ruído que treina o usuário a
    ignorar a tela — o mesmo vício que a banda de tolerância existe para evitar. Um 🔴 de
    fora-da-banda **pode** coexistir com o 🟡 da mesma conta: são afirmações diferentes (*"está
    fora da banda em R$ X"* e *"e essa medição é de 60 dias atrás"*).

    O motor decide por `abs(divergencia) > tolerancia` e **não** pelo `dentro_da_tolerancia` que a
    conferência já calcula — não porque o booleano esteja errado, mas para não haver **duas
    verdades** sobre a mesma comparação. A borda `abs(divergencia) == tolerancia` é **DENTRO**
    (silêncio), aqui e na 8.5; há teste dedicado para ninguém invertê-la em manutenção.
    """
    if data is None:
        return []

    out: list[Signal] = []

    # Sem conta cadastrada, este é o ÚNICO sinal possível — e o retorno antecipado diz isso em voz
    # alta. Movimento bancário só existe dentro de uma conta, então `movimentos_sem_contrapartida`
    # não teria como ser > 0 aqui; e um 🟢 "está tudo batendo" sobre zero conta seria a mentira que
    # esta regra inteira existe para impedir.
    if not data.contas:
        return [
            Signal(
                AMARELO,
                "Não sei se os lançamentos estão completos",
                "Nenhuma conta bancária cadastrada — não sei se os seus lançamentos estão "
                "completos",
                "completude",
            )
        ]

    for c in data.contas:
        # 🔴 — a conta ESTOUROU a banda. Um sinal POR CONTA, nomeando-a (decisão do fundador F3):
        # o consolidado (+R$ 1.200, −R$ 900 e +R$ 40 = +R$ 340 "saudável") esconderia dois furos.
        if c.divergencia_cents is not None and abs(c.divergencia_cents) > c.tolerancia_cents:
            # `< 0` = o banco está ABAIXO do sistema → provável saída não lançada. É o achado de
            # maior valor do produto (REQ-14): receber já tem três testemunhas (gateway, webhook,
            # split na Carteira); pagar não tem nenhuma.
            falta = (
                "provavelmente faltam lançamentos de saída"
                if c.divergencia_cents < 0
                else "provavelmente faltam lançamentos de entrada"
            )
            out.append(
                Signal(
                    VERMELHO,
                    "Faltam lançamentos",
                    f"Faltam {_brl(abs(c.divergencia_cents))} em lançamentos na conta "
                    f"{c.account_name} (tolerância de {_brl(c.tolerancia_cents)}) — {falta}",
                    "completude",
                )
            )

        # 🟡 — "não sei", no MÁXIMO um por conta, dizendo QUAL dos casos é.
        motivos: list[str] = []
        if c.divergencia_cents is None:
            # Story 8.20: "sem comparação avaliável" e não "sem saldo declarado" — existem DOIS
            # motivos para `divergencia_cents is None` (nenhum saldo declarado no período **ou**
            # saldo declarado na própria data de abertura, cuja comparação é tautológica), e o motor
            # é PURO: ele recebe só o número e não tem como saber qual. A frase nova é verdadeira
            # nos dois; a precisão fica na nota por conta, na tela de Conferência, que é para onde
            # este sinal leva. Distinguir aqui exigiria um campo novo em `CompletenessAccountInput`
            # — é da Story 8.16, que já acrescenta campos ao motor.
            motivos.append("sem comparação avaliável no período")
        if c.dias_desde_ultima_conferencia is None:
            motivos.append("nunca confirmado")
        elif c.dias_desde_ultima_conferencia > _COMPLETENESS_STALE_DAYS:
            motivos.append(f"confirmado há {c.dias_desde_ultima_conferencia} dias")
        if motivos:
            out.append(
                Signal(
                    AMARELO,
                    "Não sei se os lançamentos estão completos",
                    f"Conta {c.account_name}: {' e '.join(motivos)} — não sei se os lançamentos "
                    "dela estão completos",
                    "completude",
                )
            )

    # 🟡 dormente até a Onda 3 (AC6): o campo nasce 0 por construção, então esta linha não dispara
    # na Onda 1. A regra fica escrita para que a Onda 3 só precise alimentar o número.
    if data.movimentos_sem_contrapartida > 0:
        out.append(
            Signal(
                AMARELO,
                "Movimentos sem conta correspondente",
                f"{data.movimentos_sem_contrapartida} movimentos sem conta correspondente",
                "completude",
            )
        )

    # 🟢 — só quando TODAS as contas são avaliáveis, TODAS estão dentro da banda e a conferência é
    # recente. Qualquer conta não avaliável impede o verde: o sistema não afirma que está batendo
    # aquilo que não conferiu.
    todas_batendo = all(
        c.divergencia_cents is not None
        and abs(c.divergencia_cents) <= c.tolerancia_cents
        and c.dias_desde_ultima_conferencia is not None
        and c.dias_desde_ultima_conferencia <= _COMPLETENESS_STALE_DAYS
        for c in data.contas
    )
    if todas_batendo and data.movimentos_sem_contrapartida == 0:
        # A MAIOR divergência absoluta é a que qualifica o verde (a mais próxima de estourar).
        # `max` é estável: com empate, vence a primeira conta da lista → saída determinística.
        pior = max(data.contas, key=lambda c: abs(c.divergencia_cents or 0))
        out.append(
            Signal(
                VERDE,
                "Lançamentos batendo com o banco",
                f"Está tudo batendo: maior divergência de {_brl(abs(pior.divergencia_cents or 0))} "
                f"na conta {pior.account_name}, dentro da tolerância de "
                f"{_brl(pior.tolerancia_cents)}",
                "completude",
            )
        )
    return out


def _off_rail_signals(data: OffRailInput | None) -> list[Signal]:
    """Regra 0b — **recebimento fora da cobrança do e1p** (8.16, `source="recebimento_externo"`).

    | Condição | Nível | Cardinalidade |
    |---|---|---|
    | `data is None` **ou** `recebimentos_fora_do_trilho == 0` | — | **0** (silêncio é o certo) |
    | `recebimentos_fora_do_trilho > 0` | 🟡 | **1 por relatório** |

    **Não 🔴**, porque nada está quebrado — o dinheiro entrou e está na DRE e no saldo. E **não um
    aviso por cobrança**: é a mesma disciplina anti-ruído da banda de tolerância (*"uma tela que
    grita por R$ 3 destrói a confiança no sinal"*) e do Ajuste 2 da ratificação D-2, que fundiu os
    dois 🟡 de completude por conta.

    ⚠️ **Nem uma palavra sobre split, taxa, receita da e1p ou "fora do trilho" como jargão.** Este
    caso é, no estudo interno, vazamento de receita da plataforma — e mesmo assim **toda** a redação
    é sobre o interesse do DONO: aquele cliente não recebe régua de cobrança e aquela cobrança não
    fecha sozinha. A decisão G-D7 foi tomada quando o caso seria *inferido* de um crédito órfão;
    agora o dono **declara**, e *"o dado fica limpo; para quem ele é não muda"*. A proibição de
    construir superfície de plataforma sobre este dado é **normativa** e tem teste próprio
    (`tests/test_admin_nao_expoe_recebimento_fora_do_trilho.py`).

    **Não pode ser desligado pelo dono** (F-D5), pela mesma lógica do 🟡 *"nenhuma conta bancária
    cadastrada"*: o sinal é verdadeiro e é sobre o interesse dele — *"o dono que mais precisa é o
    que desliga"*.
    """
    if data is None or data.recebimentos_fora_do_trilho <= 0:
        return []
    return [
        Signal(
            AMARELO,
            "Recebimentos que entraram direto na sua conta",
            f"{data.recebimentos_fora_do_trilho} dos {data.recebimentos_total} recebimentos deste "
            f"mês ({_brl(data.valor_fora_do_trilho_cents)}) entraram direto na sua conta, fora da "
            "cobrança do e1p. Eles contam na sua DRE e no seu saldo, mas não geram boleto, "
            "lembrete automático nem baixa sozinha.",
            "recebimento_externo",
        )
    ]


def _debito_explica(valor_cents: int, divergencia_cents: int) -> bool:
    """`|valor − divergencia| <= max(R$ 50; 10% da divergência)` — o critério NORMATIVO.

    Ver o bloco de `_DEBITO_MATCH_FLOOR_CENTS` para **por que o percentual difere** do da banda de
    tolerância. Função separada (e não uma expressão inline) para que a borda tenha teste próprio:
    R$ 5.000 × R$ 5.000 **casa**; R$ 5.000 × R$ 2.500 **não casa** — e era exatamente esse segundo
    caso que o intervalo `[0,5×, 2×]` rejeitado deixava passar.
    """
    return abs(valor_cents - divergencia_cents) <= max(
        _DEBITO_MATCH_FLOOR_CENTS, divergencia_cents // _DEBITO_MATCH_DIVISOR
    )


def _debito_suspeito_signals(
    debitos: list[DebitoSuspeitoInput] | None, completeness: CompletenessInput | None
) -> list[Signal]:
    """Regra 0c — **a desambiguação do `divergencia > 0`** (8.16, `source="debito_nao_confirmado"`).

    | Condição | Nível | Cardinalidade |
    |---|---|---|
    | lista vazia / `None` (ou sem completude) | — | 0 |
    | conta com `divergencia > 0` que um débito explica | 🟡 | **1 por conta**, o de maior valor |

    **Por que isto é obrigatório e não detalhe de UX:** `divergencia > 0` é sintoma **tanto** de
    *"um débito que eu registrei não saiu do banco"* **quanto** de *"recebi algo e não registrei"*.
    Entregar só o número faz o dono caçar a coisa errada, e *"números sem pista treinam o dono a
    ignorar a tela"* — que é o risco "abandono da conferência" chegando por outra porta.

    Três regras que **não** podem ser afrouxadas:

    - **"pode não ter saído", nunca "não saiu".** O e1p continua sem ver o extrato; é a mesma
      disciplina de *"suprimir a afirmação, nunca o número"* da Onda 0. O trecho é **verbatim**.
    - **Só quando `divergencia > 0`.** Divergência negativa (o banco ABAIXO do sistema) é o sintoma
      **oposto** — falta lançamento de saída — e nomear um débito ali mandaria o dono para o lado
      errado. `None` (não avaliável) também não emite: não se explica o que não foi medido.
    - **Nenhuma palavra da família "agendado"** (ratificação §C-2.3): depois do worker, nada no dado
      distingue agendamento não executado de pagamento em caixa não compensado. Há varredura de
      texto contra o radical no `tests/test_financial_intelligence_onda2_signals.py`.

    O casamento é por `bank_account_name`: é o único identificador de conta que o motor conhece (ele
    não vê ids, por design — ver `CompletenessAccountInput`). `max` é **estável**: no empate de
    valor vence o primeiro da lista, então a saída é determinística.
    """
    if not debitos or completeness is None:
        return []

    out: list[Signal] = []
    for c in completeness.contas:
        # `> 0` e não `!= 0`: o sinal oposto pede a ação oposta. `None` cai fora por não ser número.
        if c.divergencia_cents is None or c.divergencia_cents <= 0:
            continue
        candidatos = [
            d
            for d in debitos
            if d.bank_account_name == c.account_name
            and _debito_explica(d.valor_cents, c.divergencia_cents)
        ]
        if not candidatos:
            # Sem débito compatível o produto **cala**: devolver o número sem pista é o que ele já
            # faz hoje, e apontar um débito que não casa é pior do que calar.
            continue
        suspeito = max(candidatos, key=lambda d: d.valor_cents)
        dia = f"{suspeito.data_debito.day:02d}/{suspeito.data_debito.month:02d}"
        out.append(
            Signal(
                AMARELO,
                "Um débito pode não ter saído da conta",
                f"O débito de {_brl(suspeito.valor_cents)} de {dia} ({suspeito.descricao}) pode "
                f"não ter saído da conta {c.account_name}: o saldo que você declarou está "
                f"{_brl(c.divergencia_cents)} acima do que o e1p calculou.",
                "debito_nao_confirmado",
            )
        )
    return out


def _margin_signals(margins: list[MarginTrend]) -> list[Signal]:
    """Regra 1 — margem de projeto caindo (Story 5.4). Só avalia projetos com margem nos DOIS
    períodos (a explicação do AC1 exige o formato "{antes}%→{depois}%"). Escalonamento:
    queda ≥ 15 p.p. OU margem final negativa → 🔴; queda ≥ 8 p.p. → 🟡; senão nenhum sinal."""
    out: list[Signal] = []
    for m in margins:
        if m.margem_pct_antes is None or m.margem_pct_depois is None:
            continue  # sem receita em algum período → não há tendência a diagnosticar
        # round(6) neutraliza ruído de ponto flutuante (ex.: 0.30-0.22 = 7.999…) para que os
        # limiares (8/15 p.p.) sejam determinísticos e batam exatamente na borda.
        drop_pp = round((m.margem_pct_antes - m.margem_pct_depois) * 100.0, 6)
        antes = _pct_display(m.margem_pct_antes)
        depois = _pct_display(m.margem_pct_depois)
        explanation = (
            f"Projeto {m.project_name}: margem {antes}%→{depois}% em {m.period_label}"
        )
        if m.margem_pct_depois < 0 or drop_pp >= _MARGIN_DROP_RED_PP:
            out.append(Signal(VERMELHO, "Margem de contribuição em queda forte", explanation,
                              "lucratividade"))
        elif drop_pp >= _MARGIN_DROP_YELLOW_PP:
            out.append(Signal(AMARELO, "Margem de contribuição caindo", explanation,
                              "lucratividade"))
    return out


def _runway_signal(runway_days: int | None) -> list[Signal]:
    """Regra 2 — runway curto (Story 5.7, campo `runway.days` já calculado). None = caixa não está
    sendo queimado (estável) → nenhum sinal. < 60 → 🔴; < 120 → 🟡; senão 🟢."""
    if runway_days is None:
        return []
    if runway_days < _RUNWAY_RED_DAYS:
        return [Signal(VERMELHO, "Runway crítico", f"Runway < {_RUNWAY_RED_DAYS} dias", "projecao")]
    if runway_days < _RUNWAY_YELLOW_DAYS:
        return [Signal(AMARELO, "Runway curto", f"Runway < {_RUNWAY_YELLOW_DAYS} dias", "projecao")]
    return [Signal(VERDE, "Runway saudável", f"Runway de {runway_days} dias", "projecao")]


def _projection_window_signals(windows: list[ProjectionWindowInput]) -> list[Signal]:
    """Regra 3 — janela de projeção negativa (Story 5.7). Reuso DIRETO do campo `alert` por janela:
    qualquer janela com alert=True → 🔴, citando a janela. Não recalcula nada."""
    return [
        Signal(VERMELHO, "Projeção de caixa negativa",
               f"Projeção de caixa negativa em {w.days} dias", "projecao")
        for w in windows
        if w.alert
    ]


def _investment_signals(investments: list[InvestmentReturn]) -> list[Signal]:
    """Regra 4 — investimento sem rendimento no período (Story 5.6). [AUTO-DECISION] Sem benchmark
    de mercado real (fora de escopo, ver 5.6), o único critério objetivo é rentabilidade do período
    ≤ 0 → 🟡. Aplicações com principal 0 (pct None) não são avaliadas (não há base)."""
    out: list[Signal] = []
    for inv in investments:
        if inv.period_rentability_pct is None:
            continue
        if inv.period_rentability_pct <= 0:
            pct = round(inv.period_rentability_pct * 100, 1)
            out.append(Signal(
                AMARELO, "Investimento sem rendimento no período",
                f"{inv.name}: rentabilidade {pct}% no período", "investimento",
            ))
    return out


def compute_signals(data: EngineInput) -> list[Signal]:
    """Ponto de entrada PURO do motor. Avalia as 7 regras determinísticas na ordem documentada
    (**completude → recebimento externo → débito não confirmado** → margem → runway → janela →
    investimento), depois PRIORIZA por nível
    (vermelho > amarelo > verde), mantendo, dentro do mesmo nível, a ordem de avaliação (sort
    ESTÁVEL — critério simples e determinístico, sem heurística subjetiva de "importância" que o
    motor não teria como aferir).

    **A completude é a PRIMEIRA por decisão de produto, não por acaso** (Story 8.6, AC5): como o
    sort é estável, ser avaliada primeiro é o que a faz aparecer **antes dos demais dentro do mesmo
    nível** — a "precedência semântica" do design §5.3 (*"não confio nos outros sinais até você
    fechar isto"*). Note o limite deliberado: a precedência é **dentro** do nível, nunca acima da
    gravidade — um 🟢 de completude não passa à frente de um 🔴 de runway. Uma story futura que
    insira outra regra antes desta quebra a precedência **em silêncio**; o que impede isso é
    `test_sinal_de_completude_vem_antes_dos_demais_no_mesmo_nivel`.

    **As duas regras da Story 8.16 entram LOGO DEPOIS da completude, e antes de margem/runway**, e
    pelo mesmo motivo: as três falam do **que o sistema sabe do dinheiro que passou pela conta**
    — quem lê um 🟡 de "recebimentos entraram direto na sua conta" está lendo por que a base dos
    números seguintes pode estar incompleta. `_debito_suspeito_signals` vem imediatamente após a
    completude também por uma razão de leitura: ele **explica** o 🔴 que a completude acabou de
    emitir para a mesma conta, e ler a explicação antes do número seria estranho — mas os dois são
    🟡 e 🔴 respectivamente, então o sort por nível já os coloca na ordem certa.

    DETERMINISMO (IV1): para o MESMO `data`, retorna SEMPRE a MESMA lista (mesma ordem, mesmos
    valores). Nenhuma dependência de relógio, aleatoriedade, I/O ou IA. É esta pureza que garante
    que a IA (que só entra depois, em ai_narrator.py) não pode ter influenciado nenhum sinal —
    inclusive na completude, cujo `dias_desde_ultima_conferencia` chega **calculado de fora**."""
    signals: list[Signal] = []
    signals.extend(_completeness_signals(data.completeness))
    signals.extend(_off_rail_signals(data.off_rail))
    signals.extend(_debito_suspeito_signals(data.debitos_suspeitos, data.completeness))
    signals.extend(_margin_signals(data.margins))
    signals.extend(_runway_signal(data.runway_days))
    signals.extend(_projection_window_signals(data.projection_windows))
    signals.extend(_investment_signals(data.investments))
    # Sort estável por prioridade de nível: preserva a ordem de avaliação dentro de cada nível.
    signals.sort(key=lambda s: _LEVEL_RANK[s.level])
    return signals
