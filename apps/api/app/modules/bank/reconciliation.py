"""**A conferência, bloco 1** (Story 8.5): o saldo do banco × o saldo do sistema, **por conta**,
**na mesma data**. Agregação SOMENTE-LEITURA — o entregável que o fundador pediu:

> *"de saldo batendo é uma conferência para achar possível furos"* (R1)

Quatro coisas precisam ficar ditas em voz alta antes de qualquer manutenção neste arquivo. Nenhuma
delas dá erro quando quebrada: todas dão **um número errado com aparência de fato**, que é o pior
modo de falha possível num relatório cujo único produto é a confiança no número.

---

**(1) A comparação é SEMPRE na MESMA data — e essa data é do CHECKPOINT, não do relatório.**
Para cada conta: `saldo_banco` vem de `latest_checkpoint(on_or_before=end)` e `saldo_sistema` vem de
`derived_balance(until=<reference_date DAQUELE checkpoint>)`. Nunca `end`, nunca `today`. Comparar o
saldo do banco de 15/07 com o saldo do sistema de 31/07 acusaria como divergência **tudo o que
aconteceu no meio** — o erro clássico desta classe de relatório, que o design §5.1 manda
**recusar**, não arredondar. O teste
`test_movimento_posterior_a_referencia_nao_muda_a_divergencia` é divergente-por-construção: ele
**falha** se alguém trocar a data por `end`.

**(2) ⛔ `service.derived_balances_as_of` é PROIBIDA aqui — isto é contrato (AC4b), não estilo.**
Ela recebe **um** `as_of` para todas as contas, e cada conta desta conferência tem a **sua própria**
data de referência. Usá-la reintroduziria exatamente o erro do item (1), com sintoma silencioso e
plausível: o relatório não quebra, ele **mente um número**. A função em lote foi renomeada de
`derived_balances` para `derived_balances_as_of` justamente porque diferia de `derived_balance` por
**um `s`** (ratificação D-4, design §3.1.1), e a proibição está escrita na docstring dela. O
consumidor legítimo dela é a tela de lista "Contas & Saldos" (8.7), onde a data é uma só. Aqui:
**laço de `derived_balance`, com o `until` de cada conta.** Escala em jogo: uma empresa de 1 pessoa
com um punhado de contas — N queries sob índice é ruído, não problema de performance.

**(3) O sinal da divergência tem leitura fixa, e a direção que importa é a negativa.**

    divergencia_cents = saldo_banco_cents − saldo_sistema_cents

- `> 0` → **o banco tem dinheiro que o sistema não conhece.** Provável **entrada** não lançada.
- `< 0` → **o banco está abaixo do que o sistema calculou.** Provável **saída** não lançada — é o
  **achado de maior valor do produto** (REQ-14): receber já tem três testemunhas independentes
  (gateway, webhook, split na Carteira); pagar não tem nenhuma.
- `= 0` → bateu exato.

O sinal mora aqui, escrito, pela mesma disciplina de `payables`/`receivables` com caixa×competência:
a regra fica onde o leitor está prestes a errar. E o critério de sucesso do épico é *"quantos
lançamentos faltantes foram encontrados"*, **nunca** *"fechou em zero"* (REQ-13).

**(4) O consolidado NUNCA existe sem a decomposição por conta.** Decisão do fundador (F3, §3.2):
a topologia real é **várias contas PJ** — corrente + poupança + aplicação, possivelmente em bancos
diferentes. Três contas divergindo +R$ 1.200, −R$ 900 e +R$ 40 dão **+R$ 340 consolidado, que parece
saudável e esconde dois problemas**. Por isso `ConferenciaReport` sempre carrega `contas` e
`contas_fora_da_banda`, e não existe rota, schema nem caminho de código que devolva o total sozinho.
É restrição de **produto**, não preferência de tela.

---

**`None` significa NÃO SEI — e não é a mesma coisa que zero.** Quando não há checkpoint útil na
janela, `divergencia_cents = None` quer dizer **não avaliável**; um `0` ali diria "conferi e está
batendo", que é uma afirmação que o sistema não tem lastro para fazer. **São DOIS os motivos**
(Story 8.20): não houve saldo informado no período, **ou** o saldo informado é da própria data de
abertura da conta — caso em que a comparação seria **tautológica** (ver `_conferir_conta`). O
`saldo_banco_data` distingue os dois; a nota **por conta** diz qual é. Nenhuma superfície agregada
pode afirmar o motivo: um relatório que diz *"sem saldo informado"* sobre uma conta que **tem**
saldo informado só mudou a mentira de lugar. Também é **proibido** cair
para "compara com o saldo de hoje", "compara com o último checkpoint de qualquer data" ou "compara
contra zero" — este último inventaria uma divergência inteira do tamanho do saldo.

**Banda `max(R$ 50,00; 0,5%)`, fixa nesta onda, e SILÊNCIO dentro dela.** Não é falta de
migration: a Onda 1 é um **instrumento de medição** (§3.1) — o número que ela produz é o gate que
libera ou mata as Ondas 3 e 4. Se cada tenant pudesse mover a banda, a régua mudaria junto com o que
ela mede e a leitura do gate perderia sentido. Uma banda fixa e conhecida durante a janela de
observação é **rigor, não limitação**. Dentro da banda o relatório **não acrescenta nota nenhuma**:
uma tela que grita por R$ 3,50 num mês de R$ 25.000 treina o usuário a ignorar o alerta e destrói a
única coisa que o produto está vendendo. Se um dia a banda for persistida, o lugar já está decidido
(§5.1.1): `tenant_profiles`, duas colunas inteiras (`..._floor_cents` + `..._bps`), em **story
e revision próprias** — nunca na migration do `bank_accounts`.

**Regra dos Planos (§1.3):** este módulo **não lê `transactions`** e **não importa `wallet`** — o
saldo comparado é o bancário (plano 3) dos dois lados, e é justamente por isso que compará-los é
legítimo (`saldo_banco_origem` e `saldo_sistema_origem` são ambos `ORIGEM_BANCO`). Todo saldo
viaja com o irmão `*_origem` (§1.3c), e o checkpoint traz também o eixo B (`saldo_banco_fonte` ∈
`{manual, ofx}`, valor **cru**, sem tradução — design §1.3.1).

**Isolamento:** por RLS e só por RLS — nenhuma query aqui filtra `tenant_id` à mão (Regra de Ouro
nº 1). Um vazamento neste arquivo não apareceria como "vi uma linha que não é minha": seria
uma **divergência inventada** contra a verdade externa do vizinho.

**Fora de escopo, de propósito** (epic §5): blocos 2 (`movimentos_sem_contrapartida`) e 3
(`lancamentos_sem_extrato`) dependem de `bank_reconciliations`, que é da Onda 3/4 — os campos **não
existem** aqui e não devem ser preenchidos com zero enganoso. Na Onda 1 **todo** movimento é
`unmatched` por definição (não há conciliação), então o bloco 2 devolveria "todos os movimentos",
que não é informação: é ruído. Nenhuma IA, nenhuma rede, nenhuma escrita.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_BANCO, ORIGEM_INDISPONIVEL
from app.modules.bank import service
from app.modules.bank.models import STATUS_IGNORED, BankAccount, BankTransaction

# ── A banda de tolerância (AC6) ───────────────────────────────────────────────────────────────
# Os defaults do design (D1), ratificados pelo epic. Constantes de módulo, não literais no meio de
# uma expressão: `tolerance_cents` é a ÚNICA implementação da fórmula, e a "costura" da
# configurabilidade futura são os dois parâmetros nomeados dela — ver a nota da docstring do módulo
# sobre por que a banda é FIXA nesta onda.
TOLERANCE_FLOOR_CENTS = 5_000  # R$ 50,00 — o piso, que domina em conta pequena
TOLERANCE_PCT = 0.005  # 0,5% — o componente que domina em conta grande


def tolerance_cents(
    saldo_cents: int,
    *,
    floor_cents: int = TOLERANCE_FLOOR_CENTS,
    pct: float = TOLERANCE_PCT,
) -> int:
    """`max(floor_cents, round(|saldo| * pct))` — a banda, em centavos. Função **pura**, sem I/O.

    O percentual é aplicado sobre o **valor absoluto** do saldo: conta no limite (saldo negativo,
    cheque especial) tem exatamente o mesmo direito à banda proporcional que uma conta positiva de
    mesmo tamanho — o ruído de arredondamento/tarifa não sabe o sinal do saldo.

    `round(...)` devolve **inteiro de centavos**: o `float` do `pct` entra no cálculo e sai dele,
    nunca no resultado nem no banco (Regra de Ouro: dinheiro é `int`/`BigInteger`). Se a banda for
    persistida um dia, o percentual vira **basis points inteiros** e a conta é `abs(s) * bps // ...`
    — a assinatura desta função não muda, só a origem dos dois parâmetros (design §5.1.1).

    A comparação que a usa é `abs(divergencia) <= tolerancia`: a borda `==` é **DENTRO** da banda
    (silêncio), tanto aqui quanto no motor de diagnóstico da 8.6 (design §5.3). Não inverta isso em
    manutenção — há teste dedicado.
    """
    return max(floor_cents, round(abs(saldo_cents) * pct))


# ── O contrato de saída ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConferenciaConta:
    """A conferência de UMA conta. Cada campo de saldo viaja com o irmão `*_origem` (§1.3c).

    **TRÊS** estados possíveis, e a diferença entre eles é o coração da story:

    - **avaliável** — havia checkpoint utilizável na janela: `saldo_banco_cents`,
      `saldo_sistema_cents`, `divergencia_cents` e `dentro_da_tolerancia` são números/booleano;
      `saldo_banco_origem = ORIGEM_BANCO`.
    - **não avaliável, sem declaração** — não houve checkpoint na janela. Os quatro são `None`,
      `saldo_banco_origem = ORIGEM_INDISPONIVEL`, `saldo_banco_fonte = None` (não houve porta de
      entrada), `saldo_banco_data = None` e `tolerancia_cents = 0`. **`None` não é zero**: zero
      afirmaria "conferi e bateu".
    - **declarado, porém não comparável** (Story 8.20) — houve checkpoint na janela, mas o
      `reference_date` dele é a **própria data de abertura da conta**. O estado numérico é
      **idêntico** ao anterior, com **um** desvio deliberado: `saldo_banco_data` fica
      **preenchido**. ⚠️ `saldo_banco_fonte` continua `None` aqui, mas **por outro motivo** que o do
      estado anterior: houve porta de entrada (o checkpoint tem `origin`), e ela é **descartada de
      propósito** — o eixo B qualifica um **valor**, e aqui não há valor (`saldo_banco_cents` é
      `None`). Nomear a porta de um saldo que o payload não carrega é afirmar sobre o que não está
      lá. Quem renderiza guarda por `saldo_banco_fonte is not None` e **omite a linha** — não a
      traduz para um motivo (foi assim que a tela chegou a dizer *"sem saldo informado"* sobre esta
      conta; ver `conferencia.ts::fonteLabel`).
      `saldo_banco_data` é o único discriminador que o consumidor tem entre *"você não me informou
      saldo nenhum"* e *"você me informou, mas nesta data isso não decide nada"* — sem ele a tela
      responderia
      *"declare o saldo para eu conferir"* a quem acabou de declarar, em laço. Por que a comparação
      não vale: `derived_balance(until=opening_date) ≡ opening_balance_cents` para **toda** conta
      (`service._movements_sums` só soma `posted_at > opening_date`), então ela é **tautológica** —
      dá zero por construção quando as duas declarações coincidem e inventa um furo quando elas
      discordam. Por que a declaração mesmo assim é aceita (e não vira 422 em
      `service._validate_reference_date`): ela é **verdadeira** — o degenerado é a **comparação**,
      não a declaração, e recusá-la apagaria uma afirmação legítima do dono (princípio da Onda 0:
      *"suprimir a afirmação, nunca o número"*). Ela continua contando no **bloco 4**.

    `saldo_sistema_origem` é **sempre** `ORIGEM_BANCO`, inclusive no estado não avaliável: a
    procedência do saldo derivado não muda por não haver checkpoint — o que fica desconhecido é o
    **valor**, não a origem. `tolerancia_cents` é `int` não-opcional e vale `0` quando não há saldo
    sobre o qual calcular banda; o consumidor **nunca** deve lê-lo com `divergencia_cents is None`.

    ⚠️ **Os três estados são do BLOCO 1.** O **bloco 4** (`dias_desde_ultima_conferencia`) não os
    acompanha e, desde a Story 8.19, é **sempre um número** nos três — inclusive no primeiro, em que
    a conta não tem checkpoint nenhum: o saldo de **abertura** é uma declaração do dono, e é dela
    que os dias passam a ser contados. Ver o comentário do campo.
    """

    bank_account_id: str
    bank_account_name: str
    bank_account_kind: str

    # ── bloco 1: o saldo bate? ────────────────────────────────────────────────────────────────
    # O que o BANCO diz (checkpoint, §2.4). `None` = não sei.
    saldo_banco_cents: int | None
    # EIXO A (plano de dinheiro): `banco` quando há checkpoint, `indisponivel` quando não há.
    saldo_banco_origem: str
    # EIXO B (porta de entrada do saldo externo): `manual` | `ofx`, valor CRU do checkpoint, sem
    # tradução nenhuma para o eixo A (design §1.3.1). `None` quando não houve porta.
    saldo_banco_fonte: str | None
    # A data do saldo informado — o `reference_date` do checkpoint. No caminho avaliável é também a
    # data em que os DOIS saldos foram apurados. Quando `divergencia_cents is None` e este campo
    # **não** é `None`, houve **declaração** e o que faltou foi a **comparação** (Story 8.20).
    saldo_banco_data: date | None
    # O que o SISTEMA calculou, na MESMA data acima (`derived_balance(until=saldo_banco_data)`).
    saldo_sistema_cents: int | None
    # EIXO A do saldo derivado: SEMPRE `banco`. Ver a docstring da classe.
    saldo_sistema_origem: str
    # banco − sistema. `> 0` entrada não lançada; `< 0` saída não lançada (REQ-14). `None` = não
    # avaliável, que **não** é zero.
    divergencia_cents: int | None
    dentro_da_tolerancia: bool | None
    tolerancia_cents: int

    # ── bloco 4: o sistema declara o que não sabe ─────────────────────────────────────────────
    # Distância até a última DECLARAÇÃO de saldo: o checkpoint mais recente com
    # `reference_date <= end` — **mesmo que ele esteja FORA da janela** (é o que permite a frase
    # honesta *"saldo não confirmado há 47 dias"*) — e, na ausência de checkpoint, a **data de
    # abertura da conta** (Story 8.19).
    # ⚠️ **`None` NÃO é mais alcançável** (Story 8.19, AC5): `opening_date` é `NOT NULL`, então toda
    # conta tem uma data de declaração. O tipo continua `int | None` de propósito — é aditivo e não
    # quebra consumidor que já trate o `None` —, mas nenhum caminho deste módulo o produz. Não
    # escreva regra nova em cima do `None` daqui: ela seria código morto.
    dias_desde_ultima_conferencia: int | None
    # Movimentos que o usuário mandou não contar, no período. Eles JÁ estão fora do saldo derivado
    # (o filtro mora em `service._movements_sums`); esta contagem é transparência, não recálculo.
    movimentos_ignorados: int

    # ── o DENOMINADOR do bloco 1 ──────────────────────────────────────────────────────────────
    # Quanto se moveu NESTA janela, NESTA conta. Existe para que `divergencia_cents` nunca seja
    # lida sem o volume que a produziu: um mês em que nada aconteceu dá divergência zero e não
    # prova nada, e o zero aqui é o que diz isso em voz alta. O sistema não distingue *conta
    # dormente* de *tudo aconteceu e nada foi registrado* — o volume não faz essa distinção
    # tampouco; ele apenas impede que o número seja lido sem ela.
    #
    # **Por conta, e não só no consolidado**, pela razão F3: três contas, duas movimentadas e uma
    # parada, dão volume total saudável e escondem a conta dormente — o mesmo vício do consolidado
    # sem decomposição.
    #
    # ⚠️ **Sem default, de propósito.** São dois sites de construção (os dois `return` de
    # `_conferir_conta`), e um terceiro que esquecesse de passá-los gravaria "não se moveu nada"
    # em silêncio — justamente a afirmação que o campo existe para impedir. Falhar alto é o
    # comportamento certo aqui.
    movimentos_no_periodo: int
    valor_movimentado_cents: int

    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContaForaDaBanda:
    """Uma conta cuja divergência ESTOUROU a banda. É o que permite ao motor da 8.6 dizer **qual**.

    Existe como tipo próprio (e não como um filtro que o consumidor aplica sobre `contas`) porque a
    decomposição é obrigatória (F3): se apontar a conta dependesse de o chamador lembrar de filtrar,
    o primeiro consumidor apressado exibiria o consolidado sozinho.
    """

    bank_account_id: str
    bank_account_name: str
    divergencia_cents: int
    tolerancia_cents: int


@dataclass(frozen=True)
class ConferenciaReport:
    """O relatório do período. **Sempre** com a decomposição por conta ao lado do consolidado.

    `total_divergencia_cents` soma **apenas** as contas avaliáveis, e é `None` quando nenhuma é —
    somar `None` como zero produziria um total que afirma "está tudo batendo" a partir de contas que
    o sistema nem conferiu. Quando `contas_sem_checkpoint > 0`, `notes` diz explicitamente que o
    total **não cobre todas as contas**: um número parcial sem essa ressalva é um número que mente
    por omissão.

    ── **Os contadores da PRÉ-CONDIÇÃO DO GATE (Story 8.16, AC7/AC8)** ──────────────────────────

    Quatro termos decidem se a divergência deste ciclo **pode ser lida** como medida do furo (e não
    como medida da própria incompletude do sistema). Três são contados aqui; o quarto é declarado:

    | # | O que é | Zera na |
    |---|---|---|
    | P1 | baixa de conta a pagar sem conta bancária informada | Onda 2 (por construção) |
    | P2 | recebimento fora da cobrança do e1p sem conta informada | Onda 2 |
    | P3 | rendimento de aplicação sem perna bancária | **Onda 2b** |
    | P4 | payout da Carteira liquidado sem perna bancária | Onda 3 |

    `lancamentos_sem_conta_informada` é **P1 + P2** (as duas populações fecham na MESMA onda e
    pedem a MESMA ação do dono, então uma frase só as cobre); P3 tem contador e nota **próprios**
    porque **não fecha nesta onda** — achatá-lo dentro de P1/P2 prometeria na tela um prazo falso,
    que é a mesma classe de afirmação sem lastro que a Onda 0 removeu da Projeção.

    **P4 é declarado e NÃO é contado**, de propósito: a população é **vazia por construção** hoje
    (o payout só marca a solicitação como sacada — nenhum dinheiro sai de conta real), e contá-la
    exigiria uma dependência deste módulo para o plano da plataforma, proibida pela Regra dos
    Planos, em troca de um contador cosmético sobre conjunto vazio.

    ⚠️ **Os contadores são do RELATÓRIO, e não por conta — e isso é uma DECISÃO, não um esquecimento
    (desvio registrado da redação do AC7).** P1 e P2 são definidos por *"não informa de qual conta
    saiu"*: a conta é justamente o que **falta**, então não existe conta a que atribuí-los. P3 não
    tem perna bancária nenhuma. Um campo por conta aqui seria zero em todas ou o mesmo número
    repetido em todas — as duas formas mentem.

    ⚠️ **ANOTA, NUNCA SUBTRAI:** `divergencia_cents`, `dentro_da_tolerancia`, `tolerancia_cents`,
    `total_divergencia_cents` e `contas_fora_da_banda` **não mudam de valor** por causa destes
    contadores. Descontar o termo conhecido da divergência seria *o checkpoint corrigindo o saldo
    derivado com outra roupa* (Regra 5 do `CLAUDE.md`): a divergência iria a zero por construção
    sempre que o sistema soubesse explicar a diferença, e a métrica primária do épico morreria.
    """

    start: date
    end: date
    contas: list[ConferenciaConta]
    total_divergencia_cents: int | None
    contas_avaliadas: int
    contas_sem_checkpoint: int
    contas_fora_da_banda: list[ContaForaDaBanda]
    notes: list[str] = field(default_factory=list)
    # P1 + P2 — fecham na Onda 2.
    lancamentos_sem_conta_informada: int = 0
    valor_sem_conta_informada_cents: int = 0
    # P3 — fecha na Onda 2b. Contador PRÓPRIO: ele tem outro prazo.
    rendimentos_sem_perna_bancaria: int = 0
    valor_rendimentos_sem_perna_cents: int = 0


# ── A porta de saída dos termos do gate (Story 8.16) ──────────────────────────────────────────
#
# Este relatório precisa **contar** obrigações de negócio (baixas de conta a pagar sem conta
# informada, recebimentos fora da cobrança do e1p, rendimentos de aplicação) — e o gate estrutural
# da Story 8.9 (`tests/test_money_planes.py`) proíbe este módulo de importar os módulos de negócio.
# A regra que decide todas as alternativas está na ratificação §C-5.1:
#
#     **Evadir um gate é pior do que quebrá-lo às claras.** Quebrado às claras, alguém vê no diff;
#     evadido, o gate fica verde e a proibição está morta.
#
# Por isso import lazy dentro da função e SQL cru sobre a tabela do outro módulo estão **reprovados
# por definição**: os dois passam no gate de AST e violam exatamente o que ele protege.
#
# **A forma ratificada é a mesma da Story 8.17: inversão de dependência.** Este módulo declara o
# contrato (o DTO + o `Protocol` + o registrador) e **não sabe** quem o implementa; os módulos de
# negócio implementam (eles **podem** importar `bank`); `app/main.py` liga os dois. Direção final:
# `main → bank`, `main → negócio`, `negócio → bank`. O gate fica verde **porque a dependência
# sumiu**, não porque foi escondida.


@dataclass(frozen=True)
class TermosDoGate:
    """Os três termos CONTADOS da pré-condição do gate, apurados **fora** deste módulo.

    Vocabulário deliberadamente **neutro** ("lançamento", "rendimento de aplicação"), pelo mesmo
    motivo do `referencia_id` opaco de `DuplicataCandidato`: quem monta o DTO é o implementador do
    `TermosDoGateProbe`; este módulo não precisa saber de que entidade cada número veio.

    `lancamentos_sem_conta_informada` = **P1 + P2** (as duas fecham na Onda 2);
    `rendimentos_sem_perna_bancaria` = **P3** (fecha na Onda 2b — outro prazo, contador próprio).
    P4 **não** entra: população vazia por construção hoje, e contá-la exigiria alcançar o plano da
    plataforma a partir daqui. Ver a docstring de `ConferenciaReport`.
    """

    lancamentos_sem_conta_informada: int
    valor_sem_conta_informada_cents: int
    rendimentos_sem_perna_bancaria: int
    valor_rendimentos_sem_perna_cents: int


class TermosDoGateProbe(Protocol):
    """A contagem que este módulo **não** sabe fazer. Recebe o `db` do request; nunca abre sessão.

    ⚠️ **O `db` é parâmetro, e isso é normativo** (mesma regra do `DuplicataProbe`, ratificação
    §C-5.4): a contagem roda na sessão do request, sob RLS, sem nenhum filtro manual de `tenant_id`
    (Regra de Ouro nº 1). Abrir sessão própria dentro do probe escaparia da GUC do tenant e o
    relatório de A passaria a contar lançamentos de B.

    **Somente leitura** — a conferência é read-only e continua sendo (IV5).
    """

    def __call__(self, db: Session, *, start: date, end: date) -> TermosDoGate: ...


_termos_do_gate_probe: TermosDoGateProbe | None = None


def register_termos_do_gate_probe(probe: TermosDoGateProbe) -> None:
    """Liga a implementação concreta. Chamada **uma vez**, na composição (`app/main.py`)."""
    global _termos_do_gate_probe
    _termos_do_gate_probe = probe


def termos_do_gate_probe_registrado() -> bool:
    """A guarda de BOOT pergunta isto — ver `app.main.verifica_fiacao_dos_termos_do_gate`."""
    return _termos_do_gate_probe is not None


def _probe_termos_do_gate(db: Session, *, start: date, end: date) -> TermosDoGate:
    """A **segunda** guarda do fail-closed — inalcançável se a de boot funcionar.

    ⚠️ **Fail-closed, e a hora certa é o BOOT** (ratificação §C-5.2): *"um erro de fiação é condição
    de startup, não de request"*. Cair para `TermosDoGate(0, 0, 0, 0)` seria o pior modo de falha
    possível **desta** story: as notas sumiriam em silêncio e a tela passaria a dizer, por omissão,
    *"nenhum termo pendente — o gate pode ser lido"* — que é exatamente a leitura errada que custou
    a decisão de produto uma vez neste épico. Zero por ausência de medição não é zero.
    """
    if _termos_do_gate_probe is None:
        raise service.BankError(
            "A contagem dos termos da pré-condição do gate não está ligada nesta instância — o "
            "relatório foi recusado em vez de ser devolvido sem as notas. Isto é erro de "
            "configuração do servidor (a composição da aplicação não registrou a contagem), não do "
            "seu pedido. Verifique `liga_os_termos_do_gate` em app/main.py.",
            500,
        )
    return _termos_do_gate_probe(db, start=start, end=end)


def _brl(cents: int) -> str:
    """Centavos → reais legíveis (`312000` → `"R$ 3.120,00"`), com aritmética **inteira**.

    Cópia deliberada da fórmula (a dívida de consolidar as ~9 formatações de moeda do repositório
    está registrada e não é desta story). Não importamos a de `engine.py`: aquela é privada **por
    contrato** — o motor de diagnóstico não pode depender de nada de fora, e um helper compartilhado
    ali dentro seria a primeira brecha na pureza (IV1). `divmod` em vez de `cents / 100` pelo mesmo
    motivo da 8.6: dinheiro é `int` em centavos e um `float` reapareceria justamente no texto que o
    dono vai ler.
    """
    sinal = "-" if cents < 0 else ""
    inteiros, centavos = divmod(abs(cents), 100)
    milhares = format(inteiros, ",").replace(",", ".")
    return f"{sinal}R$ {milhares},{centavos:02d}"


# A nota do estado não avaliável, num lugar só: ela é lida pela UI (8.7) e pelo motor (8.6), e duas
# redações do mesmo fato viram duas frases diferentes na tela conforme o caminho.


def _note_sem_checkpoint(opening_date: date) -> str:
    """A nota do estado **não avaliável, sem declaração no período** (Story 8.19).

    Vira função (e não constante) porque carrega a data — mesmo motivo de `_note_total_parcial` e
    de `_note_comparacao_degenerada`.

    ⚠️ **Ela diz DUAS coisas, e separá-las é o ponto da Story 8.19.** A redação anterior era
    *"Nenhum saldo informado para esta conta dentro do período"* e a tela a renderizava como
    *"esta conta nunca teve saldo informado"* — para uma conta cujo saldo **foi** informado, no
    cadastro. `opening_balance_cents` é `NOT NULL` e `opening_date` também: **toda** conta tem um
    saldo de partida declarado pelo dono. Mandar o dono repetir um ato que ele já fez é a mesma
    classe de afirmação sem lastro que a Onda 0 removeu da Projeção, com o sinal trocado.

    Então: (a) **existe** um saldo de partida, informado em `opening_date`; (b) **dentro deste
    período** não houve saldo novo informado, e é por isso — e só por isso — que não há o que
    comparar. O saldo de abertura sozinho não serve para comparar: `derived_balance(until=
    opening_date) ≡ opening_balance_cents` por definição da fórmula, que é exatamente a comparação
    degenerada que a Story 8.20 recusa (ver `_note_comparacao_degenerada`).

    ⚠️ Vocabulário do UX-001 (8.7): esta nota fala do lado *"o que o banco diz"*; a string
    `"no banco"` pertence à parcela da Projeção e **não** entra aqui, nem sinônimo locacional.
    """
    return (
        "O e1p tem o saldo de partida desta conta, informado por você em "
        f"{opening_date.isoformat()}, no cadastro. Dentro deste período, porém, nenhum saldo novo "
        "foi informado: sem uma verdade externa posterior à abertura não há o que comparar — o e1p "
        "não sabe se está batendo, e não vai fingir que sabe. Informe o saldo de um dia deste "
        "período para o e1p conferir."
    )


def _note_comparacao_degenerada(reference_date: date) -> str:
    """A nota do terceiro estado (Story 8.20): **declarado, porém não comparável**.

    Vira função (e não constante) porque carrega a data — mesmo motivo de `_note_total_parcial`.

    ⚠️ **É proibido reusar `_note_sem_checkpoint` aqui.** Os dois estados são diferentes: lá o dono
    **não informou saldo neste período**; aqui ele informou, e o que não vale é a **comparação**.
    Trocar uma nota pela outra trocaria uma afirmação falsa por outra — o mesmo defeito uma camada
    acima. E o vocabulário é o do UX-001 (8.7): esta nota fala do
    lado *"o que o banco diz"*; a string `"no banco"` pertence à parcela da Projeção e **não** entra
    aqui, nem sinônimo locacional.
    """
    return (
        f"Você informou o saldo desta conta em {reference_date.isoformat()}, o mesmo dia em que a "
        "conta foi aberta no e1p. Nesse dia o e1p ainda não tinha movimento nenhum para somar: a "
        "comparação sairia do saldo de abertura contra ele mesmo e não conseguiria encontrar "
        "lançamento faltante nenhum. Informe o saldo de um dia posterior para o e1p conferir de "
        "verdade."
    )


def _note_total_parcial(sem_checkpoint: int) -> str:
    """⚠️ A substring `"não cobre todas as contas"` é contrato de teste — preserve-a.

    O motivo saiu da frase (Story 8.20): existem **dois** motivos para uma conta não ser avaliada
    (sem saldo informado × declarado na data de abertura), e afirmar aqui o primeiro seria mentir
    sobre o segundo. O motivo de cada conta está na nota **dela**.
    """
    plural = "s" if sem_checkpoint > 1 else ""
    return (
        f"O total não cobre todas as contas: {sem_checkpoint} conta{plural} não avaliada{plural} "
        f"no período — o motivo está na nota de cada conta."
    )


# ── As notas dos termos do gate (Story 8.16 AC7) — bloco 4, "o sistema declara o que não sabe" ──
#
# ⚠️ **UMA REDAÇÃO, UM LUGAR — e TRÊS frases possíveis, cada uma nomeando a ONDA que a fecha.**
# Moram aqui, ao lado de `_note_sem_checkpoint` e `_note_total_parcial`, pelo mesmo motivo delas:
# duas redações do mesmo fato viram duas frases diferentes na tela conforme o caminho.
#
# **Por que P1/P2 e P3 continuam com frases separadas depois da Onda 2b-i:** os dois termos pedem
# ações DIFERENTES do dono. P1/P2 pedem informar a conta em cada lançamento legado, um por um; P3
# pede vincular a aplicação à conta bancária dela, **uma vez**. Achatá-las numa frase só mandaria o
# dono caçar lançamento a lançamento um termo que se resolve num clique.
#
# ⚠️ **Antes da Onda 2b-i a razão era outra, e ela mudou junto com o produto:** P3 não fechava com
# trabalho nenhum, e a frase NOMEAVA A ONDA que o fecharia, para impedir o dono de caçar um termo
# que software nenhum conseguia fechar ainda. Entregue a 2b-i, nomear aquela onda viraria promessa
# sobre coisa já entregue — a nota passou a nomear a AÇÃO. Ver `_note_rendimento_sem_perna`.
#
# **Zero termo não-zero ⇒ zero nota.** Silêncio, mesma disciplina anti-ruído do resto do épico — e
# é exatamente esse silêncio que sinaliza *"agora o gate pode ser lido"*.


def _note_sem_conta_informada(quantidade: int, valor_cents: int) -> str:
    """P1 + P2 — o termo que **fecha na Onda 2**, por construção, quando o legado for corrigido."""
    plural = "s" if quantidade > 1 else ""
    return (
        f"{quantidade} lançamento{plural} deste período não informa{'m' if quantidade > 1 else ''} "
        f"de qual conta saiu ou entrou ({_brl(valor_cents)}). A divergência abaixo **inclui** esse "
        "valor. Este termo fecha na Onda 2: assim que todo lançamento informar a conta, ele vai a "
        "zero sozinho."
    )


def _note_rendimento_sem_perna(quantidade: int, valor_cents: int) -> str:
    """P3 — o termo que a **Onda 2b-i fechou por construção**, e a frase mudou junto.

    Antes da 2b-i esta nota dizia *"este termo só fecha na Onda 2b"*, porque não havia **nada** que
    o dono pudesse fazer. Agora há: `investments.register_yield` recusa (409 acionável) rendimento
    em aplicação sem conta vinculada, então todo rendimento novo nasce com perna e a população é
    vazia. Manter a frase antiga seria prometer na tela uma onda **já entregue** — a mesma classe
    de afirmação sem lastro que a Onda 0 removeu da Projeção, só que ao contrário.

    **A nota fica, mesmo inalcançável no caminho normal.** Se ela disparar, não é mais uma onda
    faltando: é linha legada ou defeito, e ela precisa dizer o que **FAZER**. Apagar contador e
    nota foi a alternativa rejeitada — a 2b-ii mexe justamente nesses dados, e um termo apagado
    não avisa se eles voltarem inconsistentes.
    """
    plural = "s" if quantidade > 1 else ""
    return (
        f"{quantidade} rendimento{plural} de aplicação deste período ({_brl(valor_cents)}) ainda "
        f"não gera{'m' if quantidade > 1 else ''} movimento bancário. A divergência abaixo "
        "**inclui** esse valor. Vincule a aplicação à conta bancária dela para que o rendimento "
        "passe a aparecer no extrato."
    )


# ── Leituras locais deste relatório ───────────────────────────────────────────────────────────


def _today(db: Session, *, now: datetime | None = None) -> date:
    """Hoje NO FUSO DO TENANT — mesma âncora de `projection` e de `bank.service._today`."""
    from app.modules.settings.service import hoje_do_tenant

    return hoje_do_tenant(db, now=now)


def _ignored_counts(
    db: Session, *, accounts: Sequence[BankAccount], start: date, end: date
) -> dict[str, int]:
    """`{bank_account_id: nº de movimentos ignorados em [start, end]}`, em UMA query.

    Contagem em lote (e não um `COUNT` por conta) porque aqui, ao contrário do saldo derivado, a
    janela é **a mesma para todas as contas** — é o período do relatório, não a data de referência
    de cada checkpoint. Não há o risco do AC4b: nada é comparado com nada.

    Leitura **local** deste relatório, de propósito: a instrução da story é que falta nenhuma API
    nova na camada da 8.2/8.3/8.4. E isto **não** é uma segunda implementação de saldo — é uma
    contagem de linhas. Os movimentos ignorados já estão fora do saldo derivado (o filtro
    `status <> 'ignored'` mora dentro de `service._movements_sums` e quem consome o saldo **não
    refiltra**); esta contagem existe só para o relatório poder dizer *"e você mandou ignorar N
    movimentos neste período"*, que é transparência sobre uma decisão do próprio usuário.
    """
    if not accounts:
        return {}
    stmt = (
        select(BankTransaction.bank_account_id, func.count())
        .where(
            BankTransaction.bank_account_id.in_([a.id for a in accounts]),
            BankTransaction.status == STATUS_IGNORED,
            BankTransaction.posted_at >= start,
            BankTransaction.posted_at <= end,
        )
        .group_by(BankTransaction.bank_account_id)
    )
    return {account_id: int(total or 0) for account_id, total in db.execute(stmt).all()}


def _volume_counts(
    db: Session, *, accounts: Sequence[BankAccount], start: date, end: date
) -> dict[str, tuple[int, int]]:
    """`{bank_account_id: (nº de movimentos, Σ|amount_cents|)}` em `[start, end]`, em UMA query.

    **O denominador da divergência.** `divergencia_cents` sozinha não distingue *"nada aconteceu"*
    de *"tudo aconteceu e nada foi registrado"*. O volume não faz essa distinção tampouco — ele
    **impede que o número seja lido sem ela**, que é uma coisa diferente e a única honesta.

    **`func.abs` porque o volume é MOVIMENTAÇÃO, não resultado.** R$ 5.000 entrando e R$ 5.000
    saindo é um mês movimentado; a soma assinada diria `0` e o denominador mentiria exatamente no
    mês em que ele mais precisa dizer que aconteceu coisa ali.

    **`status <> 'ignored'` — o MESMO recorte de `service._movements_sums`**, e não uma escolha
    nova: o volume qualifica aquele saldo derivado, e contar aqui um movimento que o saldo não viu
    diria que houve movimento onde não houve.

    Contagem em lote pelo mesmo motivo de `_ignored_counts`, logo acima: a janela é a mesma para
    todas as contas — é o período do relatório, não a data de referência de cada checkpoint. Nada
    aqui é comparado com nada, então o AC4b não está em jogo.
    """
    if not accounts:
        return {}
    stmt = (
        select(
            BankTransaction.bank_account_id,
            func.count(),
            func.coalesce(func.sum(func.abs(BankTransaction.amount_cents)), 0),
        )
        .where(
            BankTransaction.bank_account_id.in_([a.id for a in accounts]),
            BankTransaction.status != STATUS_IGNORED,
            BankTransaction.posted_at >= start,
            BankTransaction.posted_at <= end,
        )
        .group_by(BankTransaction.bank_account_id)
    )
    return {
        account_id: (int(n or 0), int(total or 0))
        for account_id, n, total in db.execute(stmt).all()
    }


# ── O relatório ───────────────────────────────────────────────────────────────────────────────


def _conferir_conta(
    db: Session,
    account: BankAccount,
    *,
    start: date,
    end: date,
    today: date,
    movimentos_ignorados: int,
    volume: tuple[int, int],
) -> ConferenciaConta:
    """A conferência de UMA conta. Ver os itens (1) a (3) da docstring do módulo.

    **Uma busca de checkpoint, DOIS critérios — e eles não podem ser fundidos.**
    `latest_checkpoint(on_or_before=end)` devolve o mais recente até o fim do período. Dele:

    - o **bloco 1** (AC2) exige que ele esteja **DENTRO** da janela (`reference_date >= start`);
      fora dela, o saldo do banco é `indisponivel` e nada é comparado;
    - o **bloco 4** (AC8) usa esse mesmo checkpoint **mesmo estando fora** da janela — é justamente
      o que permite dizer *"saldo não confirmado há 47 dias"* em vez de simplesmente calar.

    **E o bloco 4 cai para `account.opening_date` quando não há checkpoint NENHUM (Story 8.19).**
    O saldo de abertura **é** uma declaração: `opening_balance_cents` e `opening_date` são
    `NOT NULL`, e `service._validate_opening_date` descreve a data como *"o dia em que você conferiu
    o saldo no app do banco"*. Devolver `None` ali fazia a tela dizer *"esta conta nunca teve saldo
    informado"* a quem informou o saldo no cadastro — mandando o dono repetir um ato já feito.
    Consequências deliberadas: (a) o contador **nunca mais é `None`** (AC5); (b) o motor de
    diagnóstico deixa de escrever o motivo *"nunca confirmado"* e passa a escrever *"confirmado há N
    dias"* apenas quando N estoura o limite de frescor. **O que NÃO muda:** o bloco 1. Sem
    checkpoint na janela, `divergencia_cents` continua `None` e o 🟢 *"está tudo batendo"* continua
    impossível — a guarda que o segura é `divergencia_cents is not None` em
    `engine._completeness_signals`, e ela não é tocada aqui (AC4). ⚠️ E isto **não** reabre a
    Story 8.20: nenhum saldo de abertura é comparado com coisa alguma; ele entra só como **data**,
    no contador de dias. `derived_balance` continua não sendo chamada neste ramo.

    ⚠️ **`service.days_since_last_declared_balance` responde OUTRA pergunta e não deve ser reusada
    aqui** — ela conta **só** checkpoints (*"há quanto tempo o dono não declara um saldo novo?"*) e
    continua devolvendo `None` para "nunca". Nomes vizinhos, conjuntos diferentes; implementar uma
    em cima da outra apagaria justamente a distinção que a Story 8.19 introduziu.

    Uma consulta basta porque, se o mais recente `<= end` já é anterior a `start`, então **todos**
    os checkpoints `<= end` são — não existe um "mais recente dentro da janela" atrás dele.
    O que **não** pode acontecer é os dois critérios virarem um: alguém "simplificando" o filtro de
    janela faria o bloco 1 comparar contra um saldo velho (divergência inflada por tudo o que
    aconteceu desde então); alguém aplicando o filtro de janela ao bloco 4 apagaria exatamente a
    frase que ele existe para produzir.

    O filtro de janela mora **aqui**, e não em `latest_checkpoint`: ele é filtro de relatório, não
    regra de domínio da 8.4 — que só conhece `on_or_before`.

    **A comparação DEGENERADA (Story 8.20).** Um checkpoint com
    `reference_date == account.opening_date` passa no filtro de janela e ainda assim **não decide
    nada**: `derived_balance(until=opening_date) ≡ opening_balance_cents` para toda conta, sempre
    (`service._movements_sums` só soma `posted_at > opening_date`, e `_validate_posted_at` impede
    lançar movimento na própria data de abertura). Comparar os dois lados ali é comparar **duas
    declarações do mesmo dono sobre o mesmo dia**: se elas coincidem, a divergência é zero **por
    construção** e o motor emite o 🟢 *"está tudo batendo"* para um razão bancário vazio; se elas
    discordam, a divergência estoura a banda e o motor manda o dono caçar um lançamento que não
    existe. Por isso o bloco 1 sai como **não avaliável** e `derived_balance` **nem é chamada**.
    A **declaração** continua legítima (ver `service._validate_reference_date`, que a aceita de
    propósito) e continua contando no **bloco 4**: o degenerado é a comparação, não o ato.
    """
    checkpoint = service.latest_checkpoint(
        db, bank_account_id=account.id, on_or_before=end
    )

    # Bloco 4: a distância até a última DECLARAÇÃO de saldo — o checkpoint CRU (pode estar fora da
    # janela) e, quando não há checkpoint nenhum, a **data de abertura da conta** (Story 8.19): o
    # saldo de abertura é uma declaração do dono como qualquer outra, e `opening_date` é `NOT NULL`.
    # Por isso este contador **nunca mais é `None`** (AC5) — ver a docstring da função.
    # `min(end, today)` porque um relatório de um período passado não deve dizer "há 200 dias"
    # quando, no fim daquele período, fazia 3; e `max(0, ...)` protege a borda em que a referência é
    # posterior ao teto (a API recusa data futura, mas o contador não depende dessa guarda para
    # estar correto). As duas guardas valem igual para os dois ramos.
    ultima_declaracao = (
        checkpoint.reference_date if checkpoint is not None else account.opening_date
    )
    dias_desde_ultima_conferencia = max(0, (min(end, today) - ultima_declaracao).days)

    # Bloco 1: o filtro de JANELA desta story (AC2). Checkpoint anterior a `start` não serve para
    # comparar — ele é de outro período.
    na_janela = (
        checkpoint if checkpoint is not None and checkpoint.reference_date >= start else None
    )

    # Story 8.20 — a comparação DEGENERADA (ver a docstring acima). Calculada DEPOIS do `na_janela`
    # e ANTES de qualquer chamada a `derived_balance`: não há o que derivar para comparar.
    degenerada = na_janela is not None and na_janela.reference_date == account.opening_date

    if na_janela is None or degenerada:
        # UMA construção para os DOIS motivos de "não avaliável" — duas quase iguais divergiriam na
        # primeira manutenção. O estado numérico é o mesmo; variam só `saldo_banco_data` (o
        # discriminador do caso degenerado) e a nota, que diz QUAL dos dois motivos é.
        # Dentro deste bloco, `na_janela is not None` ⟺ `degenerada` — a forma abaixo é a mesma
        # condição escrita de um jeito que o type checker acompanha.
        return ConferenciaConta(
            bank_account_id=account.id,
            bank_account_name=account.name,
            bank_account_kind=account.kind,
            saldo_banco_cents=None,
            saldo_banco_origem=ORIGEM_INDISPONIVEL,
            saldo_banco_fonte=None,
            # O ÚNICO desvio entre os dois caminhos: no degenerado houve declaração, e é este campo
            # que impede a tela de mandar o dono repetir o ato que ele acabou de fazer.
            saldo_banco_data=na_janela.reference_date if na_janela is not None else None,
            saldo_sistema_cents=None,
            # A procedência do derivado não muda por não haver checkpoint — o que falta é o VALOR.
            saldo_sistema_origem=ORIGEM_BANCO,
            divergencia_cents=None,
            dentro_da_tolerancia=None,
            tolerancia_cents=0,
            # AC8 (8.20): o bloco 4 NÃO é silenciado no caso degenerado. Ele mede o **ato de
            # declarar**, e o ato aconteceu; o bloco 1 mede a **comparação**. Colapsar os dois é o
            # erro de fundo que esta correção existe para desfazer.
            dias_desde_ultima_conferencia=dias_desde_ultima_conferencia,
            movimentos_ignorados=movimentos_ignorados,
            # ⚠️ O volume sai TAMBÉM no caminho não avaliável, e é decisão: o mês sem saldo
            # declarado mas com R$ 18.000 movimentados é diferente do mês em que nada aconteceu, e
            # zerar aqui apagaria essa diferença justo onde o dono precisa dela para saber se vale
            # a pena declarar o saldo.
            movimentos_no_periodo=volume[0],
            valor_movimentado_cents=volume[1],
            notes=[
                _note_comparacao_degenerada(na_janela.reference_date)
                if na_janela is not None
                else _note_sem_checkpoint(account.opening_date)
            ],
        )

    saldo_banco_cents = na_janela.balance_cents
    # ⛔ `until=na_janela.reference_date` — a data DO CHECKPOINT. Nunca `end`, nunca `today`, e
    # nunca `derived_balances_as_of` (ver o item (2) da docstring do módulo). A soma
    # `opening_balance_cents + Σ movimentos` NÃO é reimplementada aqui: existe UMA implementação
    # dela no repositório (`service.derived_balance`), e é isso que torna a §1.3a auditável.
    saldo_sistema_cents = service.derived_balance(
        db, bank_account_id=account.id, until=na_janela.reference_date
    )
    divergencia_cents = saldo_banco_cents - saldo_sistema_cents
    tolerancia = tolerance_cents(saldo_banco_cents)

    return ConferenciaConta(
        bank_account_id=account.id,
        bank_account_name=account.name,
        bank_account_kind=account.kind,
        saldo_banco_cents=saldo_banco_cents,
        saldo_banco_origem=ORIGEM_BANCO,
        # Valor CRU do eixo B (`manual` nesta onda, `ofx` a partir da Onda 3), sem tradução.
        saldo_banco_fonte=na_janela.origin,
        saldo_banco_data=na_janela.reference_date,
        saldo_sistema_cents=saldo_sistema_cents,
        saldo_sistema_origem=ORIGEM_BANCO,
        divergencia_cents=divergencia_cents,
        # A borda `==` é DENTRO da banda: silêncio. Ver `tolerance_cents`.
        dentro_da_tolerancia=abs(divergencia_cents) <= tolerancia,
        tolerancia_cents=tolerancia,
        dias_desde_ultima_conferencia=dias_desde_ultima_conferencia,
        movimentos_ignorados=movimentos_ignorados,
        movimentos_no_periodo=volume[0],
        valor_movimentado_cents=volume[1],
        # Dentro da banda: NENHUMA nota. Silêncio é o comportamento correto, não omissão — quem
        # grita por R$ 3,50 num mês de R$ 25.000 treina o usuário a ignorar o alerta.
        notes=[],
    )


def _fora_da_banda(contas: Sequence[ConferenciaConta]) -> list[ContaForaDaBanda]:
    """As contas que ESTOURARAM a banda — nomeadas, para a 8.6 poder apontar qual (F3).

    O critério é `dentro_da_tolerancia is False`, **nunca** `not c.dentro_da_tolerancia`: o campo é
    `bool | None` e `None` significa NÃO AVALIÁVEL. Como `not None` é `True`, a forma negada
    acusaria de furo as contas que o sistema **não conferiu** — uma divergência inventada,
    que é o pior modo de falha deste relatório. A guarda de `divergencia_cents` é redundante com o
    booleano por construção, e está aqui para que a redundância seja o que sobra se alguém mexer num
    dos dois.
    """
    return [
        ContaForaDaBanda(
            bank_account_id=c.bank_account_id,
            bank_account_name=c.bank_account_name,
            divergencia_cents=c.divergencia_cents,
            tolerancia_cents=c.tolerancia_cents,
        )
        for c in contas
        if c.dentro_da_tolerancia is False and c.divergencia_cents is not None
    ]


def reconciliation_report(
    db: Session,
    *,
    start: date,
    end: date,
    bank_account_id: str | None = None,
    today: date | None = None,
) -> ConferenciaReport:
    """Compara, **por conta**, o saldo que o banco atesta com o que o e1p calculou. **Read-only.**

    `bank_account_id` omitido → todas as contas **ativas** (`service.list_accounts`, que já esconde
    as arquivadas). Informado → exatamente essa conta, mesmo arquivada: quem pede o relatório de uma
    conta específica está conferindo o estado final dela, e um 404 seria falso (a conta existe).
    Conta inexistente ou de outro tenant → `service.BankError` 404 fail-closed (a RLS esconde a
    linha) — a exceção sobe para o router, que a traduz.

    `today` é injetável (default = hoje em UTC), como em `projection.cash_projection`: ele só entra
    em `dias_desde_ultima_conferencia`, e um relatório cujo contador de abandono depende do relógio
    da máquina não é testável.

    `start`/`end` são datas de calendário, **inclusivas** nas duas pontas — `reference_date` e
    `posted_at` são `DATE`, então não existe aritmética de fuso em nenhum ponto deste caminho
    (design §3.3; a lição que a Agenda aprendeu na marra, `CLAUDE.md` §6.0). A guarda `end < start`
    mora no router (422), mesmo padrão do `financial_intelligence`.

    **Nada aqui escreve.** Nenhum INSERT/UPDATE/DELETE, nenhum checkpoint criado, nenhum `status` de
    movimento recalculado, nenhum "movimento de ajuste" para fechar a diferença — seria a
    intenção mais provável e zeraria a divergência **por construção**, destruindo a métrica que o
    épico inteiro existe para produzir (ver o aviso (c) em `BankBalanceCheckpoint`).
    """
    hoje = today or _today(db)
    accounts = (
        [service.get_account(db, bank_account_id)]
        if bank_account_id
        else service.list_accounts(db)
    )
    ignorados = _ignored_counts(db, accounts=accounts, start=start, end=end)
    volumes = _volume_counts(db, accounts=accounts, start=start, end=end)

    contas = [
        _conferir_conta(
            db,
            account,
            start=start,
            end=end,
            today=hoje,
            movimentos_ignorados=ignorados.get(account.id, 0),
            volume=volumes.get(account.id, (0, 0)),
        )
        for account in accounts
    ]

    avaliaveis = [c for c in contas if c.divergencia_cents is not None]
    contas_sem_checkpoint = len(contas) - len(avaliaveis)

    notes: list[str] = []
    if contas_sem_checkpoint:
        notes.append(_note_total_parcial(contas_sem_checkpoint))

    # Story 8.16 — os termos da pré-condição do gate. Contados FORA deste módulo (inversão de
    # dependência) e **somente anotados**: nenhuma linha abaixo toca em divergência, tolerância ou
    # total. Ver a docstring de `ConferenciaReport` ("ANOTA, NUNCA SUBTRAI").
    termos = _probe_termos_do_gate(db, start=start, end=end)
    if termos.lancamentos_sem_conta_informada:
        notes.append(
            _note_sem_conta_informada(
                termos.lancamentos_sem_conta_informada, termos.valor_sem_conta_informada_cents
            )
        )
    if termos.rendimentos_sem_perna_bancaria:
        notes.append(
            _note_rendimento_sem_perna(
                termos.rendimentos_sem_perna_bancaria, termos.valor_rendimentos_sem_perna_cents
            )
        )

    return ConferenciaReport(
        start=start,
        end=end,
        contas=contas,
        # `None` (e não `0`) quando nenhuma conta é avaliável: um zero aqui afirmaria que está tudo
        # batendo justamente onde nada foi conferido.
        total_divergencia_cents=(
            sum(c.divergencia_cents for c in avaliaveis if c.divergencia_cents is not None)
            if avaliaveis
            else None
        ),
        contas_avaliadas=len(avaliaveis),
        contas_sem_checkpoint=contas_sem_checkpoint,
        contas_fora_da_banda=_fora_da_banda(contas),
        notes=notes,
        lancamentos_sem_conta_informada=termos.lancamentos_sem_conta_informada,
        valor_sem_conta_informada_cents=termos.valor_sem_conta_informada_cents,
        rendimentos_sem_perna_bancaria=termos.rendimentos_sem_perna_bancaria,
        valor_rendimentos_sem_perna_cents=termos.valor_rendimentos_sem_perna_cents,
    )
