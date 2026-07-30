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
batendo", que é uma afirmação que o sistema não tem lastro para fazer. Também é **proibido** cair
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
from datetime import UTC, date, datetime

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

    Dois estados possíveis, e a diferença entre eles é o coração da story:

    - **avaliável** — havia checkpoint utilizável na janela: `saldo_banco_cents`,
      `saldo_sistema_cents`, `divergencia_cents` e `dentro_da_tolerancia` são números/booleano;
      `saldo_banco_origem = ORIGEM_BANCO`.
    - **não avaliável** — os quatro são `None`, `saldo_banco_origem = ORIGEM_INDISPONIVEL`,
      `saldo_banco_fonte = None` (não houve porta de entrada) e `tolerancia_cents = 0`. **`None` não
      é zero**: zero afirmaria "conferi e bateu".

    `saldo_sistema_origem` é **sempre** `ORIGEM_BANCO`, inclusive no estado não avaliável: a
    procedência do saldo derivado não muda por não haver checkpoint — o que fica desconhecido é o
    **valor**, não a origem. `tolerancia_cents` é `int` não-opcional e vale `0` quando não há saldo
    sobre o qual calcular banda; o consumidor **nunca** deve lê-lo com `divergencia_cents is None`.
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
    # A data em que os DOIS saldos foram apurados. É o `reference_date` do checkpoint.
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
    # Distância até o checkpoint mais recente com `reference_date <= end` — **mesmo que ele esteja
    # FORA da janela**: é o que permite a frase honesta *"saldo não confirmado há 47 dias"*.
    # `None` = esta conta nunca teve saldo declarado (diferente de `0` = declarado hoje).
    dias_desde_ultima_conferencia: int | None
    # Movimentos que o usuário mandou não contar, no período. Eles JÁ estão fora do saldo derivado
    # (o filtro mora em `service._movements_sums`); esta contagem é transparência, não recálculo.
    movimentos_ignorados: int
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
    """

    start: date
    end: date
    contas: list[ConferenciaConta]
    total_divergencia_cents: int | None
    contas_avaliadas: int
    contas_sem_checkpoint: int
    contas_fora_da_banda: list[ContaForaDaBanda]
    notes: list[str] = field(default_factory=list)


# A nota do estado não avaliável, num lugar só: ela é lida pela UI (8.7) e pelo motor (8.6), e duas
# redações do mesmo fato viram duas frases diferentes na tela conforme o caminho.
_NOTE_SEM_CHECKPOINT = (
    "Nenhum saldo informado para esta conta dentro do período. Sem a verdade externa não há o que "
    "comparar — o e1p não sabe se está batendo, e não vai fingir que sabe."
)


def _note_total_parcial(sem_checkpoint: int) -> str:
    plural = "s" if sem_checkpoint > 1 else ""
    return (
        f"O total não cobre todas as contas: {sem_checkpoint} conta{plural} sem saldo informado no "
        f"período (não avaliada{plural})."
    )


# ── Leituras locais deste relatório ───────────────────────────────────────────────────────────


def _today() -> date:
    """Hoje em UTC — mesma âncora de `projection.cash_projection` e de `bank.service._today`."""
    return datetime.now(UTC).date()


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


# ── O relatório ───────────────────────────────────────────────────────────────────────────────


def _conferir_conta(
    db: Session,
    account: BankAccount,
    *,
    start: date,
    end: date,
    today: date,
    movimentos_ignorados: int,
) -> ConferenciaConta:
    """A conferência de UMA conta. Ver os itens (1) a (3) da docstring do módulo.

    **Uma busca de checkpoint, DOIS critérios — e eles não podem ser fundidos.**
    `latest_checkpoint(on_or_before=end)` devolve o mais recente até o fim do período. Dele:

    - o **bloco 1** (AC2) exige que ele esteja **DENTRO** da janela (`reference_date >= start`);
      fora dela, o saldo do banco é `indisponivel` e nada é comparado;
    - o **bloco 4** (AC8) usa esse mesmo checkpoint **mesmo estando fora** da janela — é justamente
      o que permite dizer *"saldo não confirmado há 47 dias"* em vez de simplesmente calar.

    Uma consulta basta porque, se o mais recente `<= end` já é anterior a `start`, então **todos**
    os checkpoints `<= end` são — não existe um "mais recente dentro da janela" atrás dele.
    O que **não** pode acontecer é os dois critérios virarem um: alguém "simplificando" o filtro de
    janela faria o bloco 1 comparar contra um saldo velho (divergência inflada por tudo o que
    aconteceu desde então); alguém aplicando o filtro de janela ao bloco 4 apagaria exatamente a
    frase que ele existe para produzir.

    O filtro de janela mora **aqui**, e não em `latest_checkpoint`: ele é filtro de relatório, não
    regra de domínio da 8.4 — que só conhece `on_or_before`.
    """
    checkpoint = service.latest_checkpoint(
        db, bank_account_id=account.id, on_or_before=end
    )

    # Bloco 4: o checkpoint CRU (pode estar fora da janela). `min(end, today)` porque um relatório
    # de um período passado não deve dizer "há 200 dias" quando, no fim daquele período, fazia 3;
    # e `max(0, ...)` protege a borda em que a referência é posterior ao teto (a API recusa data
    # futura, mas o contador não depende dessa guarda para estar correto).
    dias_desde_ultima_conferencia = (
        max(0, (min(end, today) - checkpoint.reference_date).days)
        if checkpoint is not None
        else None
    )

    # Bloco 1: o filtro de JANELA desta story (AC2). Checkpoint anterior a `start` não serve para
    # comparar — ele é de outro período.
    na_janela = (
        checkpoint if checkpoint is not None and checkpoint.reference_date >= start else None
    )

    if na_janela is None:
        # AC3 — o relatório DIZ que não sabe. Nenhum número de divergência é produzido aqui.
        return ConferenciaConta(
            bank_account_id=account.id,
            bank_account_name=account.name,
            bank_account_kind=account.kind,
            saldo_banco_cents=None,
            saldo_banco_origem=ORIGEM_INDISPONIVEL,
            saldo_banco_fonte=None,
            saldo_banco_data=None,
            saldo_sistema_cents=None,
            # A procedência do derivado não muda por não haver checkpoint — o que falta é o VALOR.
            saldo_sistema_origem=ORIGEM_BANCO,
            divergencia_cents=None,
            dentro_da_tolerancia=None,
            tolerancia_cents=0,
            dias_desde_ultima_conferencia=dias_desde_ultima_conferencia,
            movimentos_ignorados=movimentos_ignorados,
            notes=[_NOTE_SEM_CHECKPOINT],
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
    hoje = today or _today()
    accounts = (
        [service.get_account(db, bank_account_id)]
        if bank_account_id
        else service.list_accounts(db)
    )
    ignorados = _ignored_counts(db, accounts=accounts, start=start, end=end)

    contas = [
        _conferir_conta(
            db,
            account,
            start=start,
            end=end,
            today=hoje,
            movimentos_ignorados=ignorados.get(account.id, 0),
        )
        for account in accounts
    ]

    avaliaveis = [c for c in contas if c.divergencia_cents is not None]
    contas_sem_checkpoint = len(contas) - len(avaliaveis)

    notes: list[str] = []
    if contas_sem_checkpoint:
        notes.append(_note_total_parcial(contas_sem_checkpoint))

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
    )
