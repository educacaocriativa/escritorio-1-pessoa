"""Regras do módulo bancário: contas + conta primária + **saldo derivado** (Story 8.2), os
**movimentos** que fazem esse saldo se mover (Story 8.3) e o **saldo declarado** — a verdade
externa contra a qual o derivado é medido (Story 8.4).

**Isolamento:** por RLS, e só por RLS — nenhuma query aqui filtra `tenant_id` à mão (Regra de Ouro
nº 1 do `CLAUDE.md`: defesa-em-profundidade foi considerada e REJEITADA para não criar o padrão
"algumas queries filtram, outras não", onde esquecer uma vira vazamento). Cross-tenant cai em
`db.get(...) is None` → 404 fail-closed, nunca 403 (403 confirmaria a existência da linha).

**Sem FK dura** entre entidades financeiras (padrão do projeto: `charges.client_id`,
`payables.cost_center_id`): a referência é solta e a integridade é validada no service —
`bank_transactions.bank_account_id` é validada chamando `get_account`, sem `ForeignKey`.

**O saldo é derivado, nunca materializado** (design §3.1). Não existe coluna de saldo em
`bank_accounts` e não pode passar a existir; ver o aviso (b) na docstring de `models.py`. A soma
dos movimentos tem **uma** implementação (`_movements_sums`) e é ela que aplica o
`status <> 'ignored'` — quem consome o saldo não refiltra.

**O checkpoint (Story 8.4) NUNCA corrige o saldo derivado.** Nenhuma função desta seção escreve em
`BankTransaction` nem em `BankAccount`: declarar um saldo cria (ou corrige) UMA linha em
`bank_balance_checkpoints` e mais nada. Se o checkpoint passasse a ajustar o derivado — por um
"movimento de ajuste" automático, a boa intenção mais provável aqui —, a divergência iria a zero
por construção e o produto perderia a métrica que vende. Ver o aviso (c) na docstring de
`BankBalanceCheckpoint` e o teste `test_checkpoint_nao_altera_saldo_derivado`.

**O corte de data das superfícies correntes (Story 8.10).** `derived_balance(until=None)` e
`derived_balances_as_of(as_of=None)` significam **hoje**, não "sem limite superior" — fail-closed,
para que o movimento agendado da 8.14 nunca entre num saldo corrente por esquecimento de passar a
data. O histórico inteiro se pede com `SEM_CORTE`; `active_balance_total` **mantém** o default
antigo por decisão declarada. As três docstrings dizem o porquê, cada uma da sua metade.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.db.base import _uuid
from app.modules.bank.models import (
    KIND_INVESTMENT,
    KIND_PLATFORM_WALLET,
    KINDS,
    ORIGIN_MANUAL,
    ORIGIN_OFX,
    ORIGINS,
    SOURCE_MANUAL,
    STATUS_IGNORED,
    STATUS_UNMATCHED,
    STATUSES,
    BankAccount,
    BankBalanceCheckpoint,
    BankTransaction,
)
from app.modules.bank.schemas import (
    BankAccountCreate,
    BankAccountUpdate,
    BankTransactionCreate,
    BankTransactionUpdate,
    CheckpointCreate,
)

_DUPLICATE_MSG = (
    "Já existe uma conta com esta agência e número neste banco. "
    "Edite a conta existente em vez de cadastrar de novo — duas contas para o mesmo número "
    "produziriam divergência crônica na conferência."
)


class BankError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _today() -> date:
    """Hoje em UTC — mesma âncora do Cockpit e da Projeção (`datetime.now(UTC).date()`).

    Para o Brasil (UTC−3) a data UTC nunca fica ATRÁS da local, então a guarda de "data futura"
    é, no pior caso, mais permissiva por algumas horas — nunca bloqueia o usuário de informar o
    dia de hoje, que é o erro que doeria. A dívida geral de fuso por tenant está registrada no
    `CLAUDE.md` §6.1 e não é resolvida aqui.
    """
    return datetime.now(UTC).date()


# ── O corte de data das superfícies de saldo corrente (Story 8.10) ───────────────────────────

SEM_CORTE: Final[date] = date.max
"""*"Sem limite superior"* — o saldo do histórico INTEIRO, inclusive movimento com data futura.

**É feio de propósito, e a feiura é a funcionalidade** (design Onda 2 §4.2.1). Depois da Story 8.10
o default de `derived_balance`/`derived_balances_as_of` é **hoje**; quem quiser o futuro num
saldo precisa dizer `until=SEM_CORTE` — uma decisão **visível no diff**, que um revisor nota, e que
uma busca por `SEM_CORTE` lista em qualquer momento do repositório.

**Por que não existe `incluir_futuro=True`.** Dois campos para a mesma pergunta é o defeito D-3
outra vez — o mesmo que já custou a este épico o achatamento dos dois eixos de proveniência. **Um
campo, um significado.** E um booleano seria *discreto*: passaria despercebido numa revisão, que é
exatamente o que não se quer para "este saldo inclui dinheiro que ainda não saiu da conta".

⚠️ **Hoje ninguém no repositório usa esta constante**, e isso é o estado correto: nenhuma superfície
corrente quer o futuro. Se você está prestes a ser o primeiro, escreva na story **por que**.
"""


def resolve_until(until: date | None) -> date:
    """O corte efetivo de um saldo corrente: `None` → **hoje**. Nunca devolve `None`.

    **A única implementação da normalização**, consumida por `derived_balance`,
    `derived_balances_as_of` e pelo `GET /bank/accounts/{id}/balance` — que precisa devolver no
    payload a data **efetivamente usada** (`BankBalanceOut.until`). Se o router recalculasse "hoje"
    por conta própria, o número e a data do mesmo payload passariam a vir de dois relógios, e um
    saldo cuja data de apuração não é a que ele diz é pior do que um saldo sem data nenhuma.

    Mora **na fronteira pública**, e não dentro de `_movements_sums`: normalizar no privado
    alcançaria também `active_balance_total` (ver a assimetria declarada na docstring dela) e a
    conferência, extrapolando o item 2.5 do epic.
    """
    return _today() if until is None else until


def _validate_kind(kind: str) -> str:
    if kind == KIND_PLATFORM_WALLET:
        raise BankError(
            "A Carteira e1p não pode ser cadastrada como conta bancária. O saldo da Carteira é "
            "derivado das suas vendas (com split), não de um extrato — somar os dois como se "
            "fossem a mesma coisa é justamente o erro que este módulo existe para impedir.",
            422,
        )
    if kind not in KINDS:
        raise BankError(
            f"Tipo de conta inválido: '{kind}'. Use um de: {', '.join(KINDS)}.", 422
        )
    return kind


def _validate_opening_date(opening_date: date) -> date:
    if opening_date > _today():
        raise BankError(
            "A data de abertura não pode ser futura — ela é o dia em que você conferiu o saldo "
            "no app do banco.",
            422,
        )
    return opening_date


def _validate_opening_date_move(db: Session, *, account: BankAccount, nova: date) -> date:
    """Recusa (422) mover a data de abertura **para frente** por cima de movimentos já lançados.

    É a guarda irmã de `_validate_posted_at`, do outro lado da mesma relação. Lá, o movimento é
    recusado quando cai antes da abertura, porque *"aceitar a data e não somar o movimento seria
    pior do que recusar: a linha existiria, o saldo não mudaria, e ninguém entenderia por quê"*.
    Aqui o mesmo estado é alcançado pelo outro lado — não mexendo no movimento, mas mudando a data
    de corte por baixo dele —, e o resultado é ainda pior: o saldo derivado **muda sozinho**
    (`_movements_sums` filtra `posted_at > opening_date`), o movimento **continua na lista**, e a
    conferência da 8.5 passa a comparar um checkpoint correto contra um derivado inflado. O produto
    então relata uma divergência que não existe, e manda o dono caçar um lançamento que está bem
    ali na tela. Divergência inventada é pior que divergência escondida: depois de duas caçadas
    frustradas ele para de confiar no sinal, e o sinal é o produto.

    **Só olha para frente.** `nova <= account.opening_date` passa direto: recuar a data só pode
    **acrescentar** movimentos ao conjunto que soma (o filtro é `posted_at > opening_date`), nunca
    tirar — não há órfão a criar. Recuar é, aliás, o caminho de reparo de quem já moveu a data para
    frente antes desta guarda existir: devolve ao saldo os movimentos que tinham ficado de fora.

    **A borda é `<=`, não `<`.** Um movimento exatamente na nova data de abertura **não** soma
    (`_movements_sums` usa `>`), então ele ficaria órfão igual. É a mesma assimetria que a 8.4
    documentou em `_validate_reference_date`: movimento exige `posted_at > opening_date`, checkpoint
    aceita `reference_date >= opening_date`.

    **Movimento `ignored` conta para a guarda**, apesar de já estar fora do saldo derivado. Hoje ele
    não muda número nenhum — mas `unignore_transaction` promete *"devolve o movimento ao saldo"*, e
    depois da data movida ela não teria como cumprir: o status voltaria para `unmatched` e o saldo
    não se mexeria, em silêncio. Deixar a data passar por cima dele seria armar exatamente o mesmo
    modo de falha, com o gatilho adiado para um clique futuro.

    A contagem é da janela `(opening_date atual, nova]` — os movimentos que **deixariam** de somar.
    Um órfão pré-existente (posted_at antes da abertura atual, só possível em dado anterior a esta
    guarda) já não soma e não é criado por esta edição; incluí-lo na contagem diria ao usuário que
    esta operação causou algo que ela não causou.
    """
    if nova <= account.opening_date:
        return nova

    total, ignorados, mais_antigo = db.execute(
        select(
            func.count(BankTransaction.id),
            func.sum(case((BankTransaction.status == STATUS_IGNORED, 1), else_=0)),
            func.min(BankTransaction.posted_at),
        ).where(
            BankTransaction.bank_account_id == account.id,
            BankTransaction.posted_at > account.opening_date,
            BankTransaction.posted_at <= nova,
        )
    ).one()
    if not total:
        return nova

    # SQLite devolve `DATE` como texto em agregações; o Postgres devolve `date`. Mesma normalização
    # de `days_since_last_declared_balance` — sem ela a mensagem quebraria só em um dos dois bancos.
    if isinstance(mais_antigo, str):
        mais_antigo = date.fromisoformat(mais_antigo)

    # Concordância montada em pedaços, e não com ternários dentro da f-string: a mensagem é a parte
    # do produto que o usuário lê no pior momento dele, e ela precisa ser legível também aqui.
    if total == 1:
        quantos = f"1 movimento lançado em {mais_antigo.isoformat()}"
        efeito = (
            "tiraria esse lançamento do saldo desta conta, mas ele continuaria aparecendo na "
            "lista de movimentos"
        )
        conserto = "Se quem está com a data errada é o movimento, corrija a data dele primeiro."
    else:
        quantos = (
            f"{total} movimentos lançados entre {account.opening_date.isoformat()} e "
            f"{nova.isoformat()} (o mais antigo em {mais_antigo.isoformat()})"
        )
        efeito = (
            "tiraria esses lançamentos do saldo desta conta, mas eles continuariam aparecendo na "
            "lista de movimentos"
        )
        conserto = (
            "Se quem está com a data errada são os movimentos, corrija as datas deles primeiro."
        )

    nota_ignorados = ""
    if ignorados == total:
        alvo = "Ele está ignorado" if total == 1 else "Eles estão ignorados"
        nota_ignorados = f" {alvo}"
    elif ignorados == 1:
        nota_ignorados = " 1 deles está ignorado"
    elif ignorados:
        nota_ignorados = f" {ignorados} deles estão ignorados"
    if nota_ignorados:
        nota_ignorados += (
            ": hoje isso já os deixa fora do saldo, mas depois da mudança desfazer o 'ignorar' "
            "deixaria de devolvê-los a ele, sem avisar."
        )

    raise BankError(
        f"Esta conta tem {quantos}. Mover a data de abertura para {nova.isoformat()} {efeito}: o "
        f"saldo mudaria sozinho e a conferência acusaria uma diferença que não existe."
        f"{nota_ignorados} {conserto} Se a conta recomeçou do zero, arquive-a e cadastre-a de novo "
        "com o saldo de abertura do dia. Se você só quer acertar o valor de partida, altere o "
        "saldo de abertura sem mexer na data.",
        422,
    )


def _validate_opening_date_recuo(
    *, account: BankAccount, nova: date, novo_saldo: int | None
) -> None:
    """Recusa (422) **recuar** a data de abertura sem redeclarar `opening_balance_cents`.

    **É o gêmeo do BANK-001 pela porta oposta** (design Onda 2 §4.3). O BANK-001 era mover a data
    para FRENTE por cima de movimento lançado: o saldo derivado mudava sozinho e a conferência
    relatava um furo inexistente. `_validate_opening_date_move` fechou aquele lado — e deixou este
    aberto de propósito, porque recuar *"é o caminho de reparo"*.

    Só que `opening_balance_cents` é **o saldo do banco NAQUELA data**, e não um número solto. Ao
    recuar a abertura sem trocá-lo, o saldo de partida passa a afirmar que o banco tinha aquele
    valor num dia em que ele não tinha — e a divergência que a conferência da 8.5 relata é
    **inventada**, exatamente da mesma família. Divergência inventada é pior que divergência
    escondida: *"depois de duas caçadas frustradas ele para de confiar no sinal, e o sinal é o
    produto"*.

    **A guarda é sobre AUSÊNCIA, não sobre o valor.** O saldo do dia anterior pode legitimamente
    ser igual ao antigo, então recusar "o mesmo número" seria recusar um fato possível. O que esta
    função exige é que o número venha **no mesmo PATCH** — presença é a única coisa que a API
    consegue distinguir de "não mudou" (`None` = campo ausente, em `BankAccountUpdate`).

    ⚠️ **Por isso ela é necessária e INSUFICIENTE, e a metade que falta é do formulário.** Um
    cliente que reenvie o valor antigo por conta própria — como o `AccountModal` fazia até a Story
    8.11 — passa por aqui com 200 e produz a divergência inventada do mesmo jeito. A API não tem
    como saber se aquele número foi conferido no extrato ou herdado de um campo pré-preenchido.
    Quem garante a **redeclaração** é a UI (AC2b: ao recuar, o campo é limpo e o salvar fica
    desabilitado até haver um valor digitado); esta guarda protege a API contra todo o resto
    (Atalho do iOS, script, curl, cliente futuro).

    **Recuo é `nova < account.opening_date`, estritamente.** Data igual não é recuo (não muda nada)
    e avançar cai na guarda irmã, `_validate_opening_date_move`.
    """
    if nova >= account.opening_date:
        return
    if novo_saldo is not None:
        return
    raise BankError(
        f"O saldo de abertura que você informou era o saldo de "
        f"{account.opening_date.isoformat()}. Para abrir esta conta em {nova.isoformat()}, "
        "informe o saldo daquele dia — o número está no extrato do seu banco. Sem ele, o e1p "
        "partiria de um valor que o banco não tinha naquela data e a conferência acusaria uma "
        "diferença que não existe.",
        422,
    )


# ── Leitura ──────────────────────────────────────────────────────────────────────────────────


def get_account(db: Session, account_id: str) -> BankAccount:
    acc = db.get(BankAccount, account_id)
    if acc is None:
        # Cross-tenant também cai aqui: a RLS esconde a linha → db.get devolve None → 404
        # (fail-closed, mesmo padrão do resto do projeto: 404, não 403).
        raise BankError("Conta bancária não encontrada", 404)
    return acc


def list_accounts(db: Session, *, include_archived: bool = False) -> list[BankAccount]:
    """Contas do tenant, ordenadas por nome. Arquivadas ficam FORA por default.

    Mesmo contrato de `chart_of_accounts.list_accounts`: a conta arquivada continua existindo (o
    histórico de movimentos depende dela), mas some das superfícies do dia a dia.
    """
    stmt = select(BankAccount).order_by(BankAccount.name)
    if not include_archived:
        stmt = stmt.where(BankAccount.archived_at.is_(None))
    return list(db.scalars(stmt).all())


def primary_account(db: Session) -> BankAccount | None:
    """A conta primária ATIVA do tenant, se houver (a Onda 6 — payout — consome isto).

    Devolve `None` de forma explícita quando não há: arquivar a primária **não** elege sucessora
    em silêncio (AC7). Escolher a conta de destino do dinheiro do usuário sem ele pedir é o tipo
    de "ajuda" que só se descobre quando o dinheiro já foi para o lugar errado.
    """
    stmt = (
        select(BankAccount)
        .where(BankAccount.is_primary.is_(True), BankAccount.archived_at.is_(None))
        .order_by(BankAccount.name)
    )
    return db.scalars(stmt).first()


# ── Saldo derivado (design §3.1 / assinaturas canônicas §3.1.1) ──────────────────────────────


def _movements_sums(
    db: Session, *, accounts: Sequence[BankAccount], until: date | None = None
) -> dict[str, int]:
    """Σ dos movimentos de cada conta, em **UMA** query. `{bank_account_id: centavos}`.

    Esta é a **única** implementação da soma de movimentos do repositório (Story 8.3 preencheu o
    ponto de extensão que a 8.2 deixou). `_movements_sum` delega para cá em vez de repetir o
    `WHERE`: duas cópias da mesma fórmula divergiriam no dia em que uma delas ganhasse uma condição
    — e o sintoma seria um saldo que muda conforme a tela que o pede.

        SUM(amount_cents)
        WHERE bank_account_id = :conta
          AND posted_at > <opening_date DAQUELA conta>  -- movimento anterior já está DENTRO do
                                                        -- opening_balance_cents; contá-lo de novo
                                                        -- dobraria o valor
          AND (:until IS NULL OR posted_at <= :until)    -- `until` é DATE e INCLUSIVO
          AND status <> 'ignored'                        -- AC5: ignorar TIRA do saldo

    ⚠️ **O filtro `status <> 'ignored'` mora AQUI, dentro do saldo** — é contrato para as Stories
    8.5 e 8.7: quem consome o saldo derivado **não** refiltra. Ter o filtro em dois lugares é ter
    dois lugares para divergirem.

    A cláusula de conta é um `OR` de pares `(conta, opening_date)` em vez de um `IN (...)` porque
    cada conta tem a **sua** data de corte. Ainda é uma query só — a alternativa (`GROUP BY` com
    `IN` e filtro de data em Python) leria linhas que o índice já sabe descartar, e a alternativa
    "uma query por conta" seria o N+1 que `derived_balances_as_of` existe para evitar.

    Conta sem movimento simplesmente não aparece no dicionário; o chamador usa `.get(id, 0)`.
    """
    if not accounts:
        return {}

    escopo = or_(
        *[
            and_(
                BankTransaction.bank_account_id == a.id,
                BankTransaction.posted_at > a.opening_date,
            )
            for a in accounts
        ]
    )
    stmt = (
        select(
            BankTransaction.bank_account_id,
            func.coalesce(func.sum(BankTransaction.amount_cents), 0),
        )
        .where(escopo, BankTransaction.status != STATUS_IGNORED)
        .group_by(BankTransaction.bank_account_id)
    )
    if until is not None:
        stmt = stmt.where(BankTransaction.posted_at <= until)
    return {account_id: int(total or 0) for account_id, total in db.execute(stmt).all()}


def _movements_sum(db: Session, *, account: BankAccount, until: date | None = None) -> int:
    """Σ dos movimentos de UMA conta. Delega para `_movements_sums` — ver a fórmula lá.

    Recebe a `BankAccount` já carregada (e não o id) porque a soma precisa do `opening_date` dela;
    a assinatura é privada e a 8.2 explicitamente autorizou mudá-la para evitar a releitura.
    """
    return _movements_sums(db, accounts=[account], until=until).get(account.id, 0)


def derived_balance(db: Session, *, bank_account_id: str, until: date | None = None) -> int:
    """Saldo derivado de UMA conta numa data (design §3.1). Centavos.

        saldo = opening_balance_cents + SUM(movimentos até `until`)

    `until` é um `date` (nunca `datetime`) e é **INCLUSIVO**.

    ⚠️ **`until=None` significa HOJE — não "sem limite superior" (Story 8.10).** A assinatura é a
    mesma de antes byte a byte; o que mudou foi o **significado do default**, e a mudança é
    deliberadamente invisível para quem chama. **Fail-closed:** nenhuma superfície de saldo corrente
    pode incluir movimento agendado por esquecimento de passar a data. A partir da 8.14 existirá
    movimento com `posted_at` no futuro (pagamento agendado); sem este corte, o *"Total em contas"*
    passaria a mostrar dinheiro que já tem destino marcado — o gêmeo, pela porta oposta, da máquina
    de falso negativo que a Onda 0 removeu da Projeção.

    Para o histórico completo, **inclusive o futuro**, passe `until=SEM_CORTE` (`date.max`) — feio
    de propósito; ver a docstring da constante.

    A conferência da Story 8.5 **sempre** passa `until` = a data de referência do checkpoint, porque
    comparar saldos apurados em datas diferentes é o erro que o design §5.1 manda recusar. Ela é
    imune a esta mudança por construção: nunca chamou com `None`.

    Movimentos com `status='ignored'` ficam **de fora** — o filtro é aplicado aqui dentro e quem
    consome não refiltra (ver `_movements_sums`).

    Esta é a **única** implementação da fórmula da §3.1 no repositório inteiro. Uma segunda torna a
    Regra dos Planos §1.3a inauditável — se aparecer, o `dedup-checker` deve reprovar.

    Conta inexistente (ou de outro tenant, escondida pela RLS) → `BankError` 404.
    """
    acc = get_account(db, bank_account_id)
    return acc.opening_balance_cents + _movements_sum(
        db, account=acc, until=resolve_until(until)
    )


def derived_balances_as_of(
    db: Session, *, as_of: date | None = None, include_archived: bool = False
) -> dict[str, int]:
    """Saldo de TODAS as contas numa **data comum** (`as_of`), em uma passada. `{id: centavos}`.

    ⚠️ **`as_of=None` significa HOJE — não "sem limite superior" (Story 8.10).** Mesma regra, mesmo
    motivo e mesma saída de emergência de `derived_balance`: `as_of=SEM_CORTE` para o histórico
    inteiro. É o default desta função que a tela "Contas & Saldos" consome (`GET /bank/accounts`),
    então é aqui que o *"Total em contas"* deixa de somar o pagamento agendado da 8.14.

    ⚠️ **Para a 8.14:** o número *"Agendado para sair"* **não** sai daqui — depois da 8.10 esta
    função devolve exatamente o oposto (só até hoje). Ele é a diferença entre o saldo com
    `SEM_CORTE` e o corrente, ou uma soma própria sobre `posted_at > hoje`.

    ⛔ **PROIBIDA na conferência (design §5.1 / Story 8.5).** Lá cada conta tem a **sua própria**
    data de referência — o `reference_date` do checkpoint daquela conta —, e um `as_of` comum
    compararia o saldo do banco de uma data com o saldo do sistema de outra, que é o erro clássico
    desta classe de relatório e que o service da 8.5 deve **recusar**. A conferência usa laço de
    `derived_balance` com o `until` de cada conta; o custo é N queries sob índice para uma empresa
    de 1 pessoa com um punhado de contas, ou seja, ruído.

    ✅ **Use para:** a tela de lista "Contas & Saldos" (Story 8.7), onde a data é uma só porque o
    usuário quer o saldo de hoje de tudo; e como base de `active_balance_total` (Story 8.8).

    O nome carrega o `as_of` de propósito (ratificação D-4): a versão anterior se chamava
    `derived_balances` e diferia de `derived_balance` por **um `s` final**, sendo a função errada
    para o trabalho da conferência. O sintoma de errar era uma divergência **falsa, silenciosa e
    plausível** — o relatório não quebraria, mentiria um número.
    """
    accounts = list_accounts(db, include_archived=include_archived)
    return _balances_for(db, accounts, until=resolve_until(as_of))


def active_balance_total(
    db: Session,
    *,
    until: date | None = None,
    exclude_kinds: Iterable[str] = (KIND_INVESTMENT,),
) -> int:
    """Σ dos saldos derivados das contas ATIVAS, excluindo `investment` por default. Centavos.

    É a parcela "no banco" que a Story 8.8 soma ao `available_cents` da Carteira sob
    `ORIGEM_MISTO` — somando sim, mas com as duas parcelas **rotuladas** na UI: somar é correto
    (é tudo dinheiro do usuário), esconder a composição nunca é.

    Aplicação (`kind='investment'`) fica de fora por default porque dinheiro aplicado não é caixa
    disponível para pagar a conta de amanhã (design §6.1). Contas arquivadas nunca entram.

    ⚠️ **ASSIMETRIA DELIBERADA (Story 8.10 AC6): aqui `until=None` continua significando "SEM LIMITE
    SUPERIOR".** As duas funções acima passaram a normalizar `None` para hoje; esta **não**. Ela não
    delega para nenhuma delas — vai direto em `_balances_for` —, então a mudança não a alcança por
    acidente: a assimetria foi **escolhida**, e os três motivos ficam escritos aqui porque quem
    reencontrar isto na Onda 2b/3 vai achar que foi esquecimento.

    1. O item 2.5 do epic nomeia **apenas** `derived_balance` e `derived_balances_as_of`. O epic diz
       que nenhum item da §5 pode cair fora — não que se pode acrescentar.
    2. **É esta função que semeia a Projeção**, e o `until=today` que o único chamador passa é o que
       impede a **dupla contagem do dia D** que a 8.14 AC6 resolve do outro lado (ratificação
       §C-7.3). Trocar o default aqui reintroduziria a dupla contagem **pela porta oposta**, num
       arquivo que a 8.14 declara não tocar.
    3. O único chamador de produção — `financial_intelligence/projection.py::_saldo_inicial` — **já
       passa `until=today` explicitamente**, com a docstring dizendo *"a MESMA âncora do resto da
       projeção"*. Ou seja: a Projeção **já estava segura** antes da 8.10, e continua.

    ⚠️ **Consequência para quem chamar isto daqui em diante: PASSE `until` EXPLÍCITO.** Chamar sem
    `until` soma movimento com data futura em silêncio — e é exatamente esse silêncio que a 8.10
    removeu das outras duas. O teste de contrato `test_active_balance_total_so_e_chamada_com_until_
    explicito` (em `tests/test_bank_corte_de_data.py`) **falha** se um chamador novo de produção
    omitir o argumento, para que a decisão volte a ser tomada por alguém em vez de herdada.

    **Dívida nomeada, registrada pela 8.10 para o gate da onda:** a assimetria é o corte
    conservador, não o estado final. Uniformizar as três (normalizando também esta) é decisão de
    Onda 2b/3, e exige revisitar o §C-7.3 junto — não é limpeza que se faça de passagem.
    """
    excluded = set(exclude_kinds)
    accounts = [a for a in list_accounts(db) if a.kind not in excluded]
    return sum(_balances_for(db, accounts, until=until).values())


def _balances_for(
    db: Session, accounts: Sequence[BankAccount], *, until: date | None
) -> dict[str, int]:
    """`{id: saldo}` para um conjunto já carregado de contas — UMA consulta de movimentos.

    Conta **sem movimento nenhum** aparece no dicionário com o saldo de abertura: o `GROUP BY` de
    `_movements_sums` sozinho a omitiria (erro clássico), e é o laço sobre `accounts` — não sobre o
    resultado da query — que garante isso.
    """
    sums = _movements_sums(db, accounts=accounts, until=until)
    return {a.id: a.opening_balance_cents + sums.get(a.id, 0) for a in accounts}


# ── Escrita ──────────────────────────────────────────────────────────────────────────────────


def _clear_other_primaries(db: Session, *, keep_id: str | None) -> None:
    """Desmarca `is_primary` de todas as contas do tenant, exceto `keep_id`. Sem commit.

    Percorre as linhas em Python (e não um `UPDATE ... WHERE`) porque são poucas por tenant e
    assim as instâncias já carregadas na sessão ficam consistentes — evitando o clássico "o objeto
    na memória diz uma coisa, o banco diz outra" logo antes de um `refresh`.
    """
    stmt = select(BankAccount).where(BankAccount.is_primary.is_(True))
    for other in db.scalars(stmt).all():
        if other.id != keep_id:
            other.is_primary = False


def create_account(
    db: Session, *, tenant_id: str, actor: str, data: BankAccountCreate
) -> BankAccount:
    """Cria a conta. A PRIMEIRA conta ativa do tenant nasce primária (AC7).

    `opening_balance_cents` pode ser NEGATIVO (conta no limite / cheque especial) — não há guarda
    de sinal aqui de propósito.
    """
    kind = _validate_kind(data.kind)
    opening_date = _validate_opening_date(data.opening_date)

    acc = BankAccount(
        tenant_id=tenant_id,
        name=data.name,
        kind=kind,
        institution=data.institution,
        institution_code=data.institution_code,
        branch=data.branch,
        number=data.number,
        holder_document=data.holder_document,
        pix_key=data.pix_key,
        opening_balance_cents=data.opening_balance_cents,
        opening_date=opening_date,
        # Sem primária ativa (tenant novo, ou a anterior foi arquivada) → esta assume.
        is_primary=primary_account(db) is None,
    )
    db.add(acc)
    try:
        # ⚠️ `flush` ANTES do `audit.record`: `id` tem default Python-side (`_uuid`), que só é
        # aplicado no INSERT — sem o flush, `acc.id` ainda é None e a entrada de auditoria nasceria
        # com `target=''`, ou seja, um rastro que não aponta para nada. (O mesmo padrão em
        # `chart_of_accounts.create_account` grava o target vazio; achado registrado, correção lá
        # é fora do escopo desta story.)
        db.flush()
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="bank.account.create", target=acc.id
        )
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BankError(_DUPLICATE_MSG, 409) from e
    db.refresh(acc)
    return acc


def update_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str, data: BankAccountUpdate
) -> BankAccount:
    """Edita a conta. `is_primary=True` troca a primária na MESMA transação (AC7).

    `archived_at` não é editável por aqui (arquivar tem rota própria, com auditoria própria).

    `opening_date` passa por **três** guardas, uma por direção do movimento da data:

    1. `_validate_opening_date` — data futura (a mesma do cadastro);
    2. `_validate_opening_date_move` — **para frente** por cima de movimento já lançado (BANK-001,
       a guarda irmã de `_validate_posted_at`). Sem ela o saldo derivado muda sozinho com os
       movimentos ainda visíveis na lista, e a conferência relata uma divergência inventada;
    3. `_validate_opening_date_recuo` (Story 8.11) — **para trás** sem redeclarar
       `opening_balance_cents`. O saldo de abertura é o saldo do banco NAQUELA data: recuar sem
       trocá-lo produz a mesma divergência inventada, pela porta oposta.
    """
    acc = get_account(db, account_id)

    # ⚠️ **Nenhuma escrita em `acc` antes das três guardas de data.** Todas comparam contra a data
    # ATUAL da conta (`acc.opening_date`) e contra o saldo que veio NESTE PATCH — escrever qualquer
    # um dos dois antes faria a guarda seguinte se comparar com o valor novo e passar sempre.
    nova_abertura: date | None = None
    if data.opening_date is not None:
        nova_abertura = _validate_opening_date(data.opening_date)
        _validate_opening_date_move(db, account=acc, nova=nova_abertura)
        _validate_opening_date_recuo(
            account=acc, nova=nova_abertura, novo_saldo=data.opening_balance_cents
        )

    if data.kind is not None:
        acc.kind = _validate_kind(data.kind)
    if nova_abertura is not None:
        acc.opening_date = nova_abertura
    for field in (
        "name",
        "institution",
        "institution_code",
        "branch",
        "number",
        "holder_document",
        "pix_key",
        "opening_balance_cents",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(acc, field, value)

    if data.is_primary is not None:
        if data.is_primary:
            if acc.archived_at is not None:
                raise BankError("Conta arquivada não pode ser a conta principal", 422)
            _clear_other_primaries(db, keep_id=acc.id)
            acc.is_primary = True
        else:
            # Desmarcar explicitamente é permitido: "nenhuma conta primária" é um estado válido
            # (é onde o tenant fica ao arquivar a primária) e não elegemos sucessora em silêncio.
            acc.is_primary = False

    audit.record(db, tenant_id=tenant_id, actor=actor, action="bank.account.update", target=acc.id)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise BankError(_DUPLICATE_MSG, 409) from e
    db.refresh(acc)
    return acc


def set_primary(db: Session, *, account_id: str, tenant_id: str, actor: str) -> BankAccount:
    """Marca esta conta como primária e desmarca as demais — **num commit só**.

    Se a troca fosse em dois commits, uma falha no meio deixaria o tenant com duas primárias (ou
    nenhuma), e o consumidor da Onda 6 (payout) escolheria a conta de destino no par ou ímpar.
    """
    acc = get_account(db, account_id)
    if acc.archived_at is not None:
        raise BankError("Conta arquivada não pode ser a conta principal", 422)
    _clear_other_primaries(db, keep_id=acc.id)
    acc.is_primary = True
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.account.set_primary", target=acc.id
    )
    db.commit()
    db.refresh(acc)
    return acc


def archive_account(
    db: Session, *, account_id: str, tenant_id: str, actor: str
) -> BankAccount:
    """Arquiva (lógico): seta `archived_at`, NÃO deleta a linha — conta encerrada não pode levar o
    histórico de movimentos junto (design §2.1). Idempotente: rearquivar mantém o carimbo original.

    Se era a primária, o tenant fica **sem** primária — nenhuma sucessora é eleita em silêncio.
    """
    acc = get_account(db, account_id)
    if acc.archived_at is None:
        acc.archived_at = datetime.now(UTC)
        acc.is_primary = False
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="bank.account.archive", target=acc.id
        )
        db.commit()
        db.refresh(acc)
    return acc


# ── Movimento bancário (Story 8.3) ───────────────────────────────────────────────────────────
#
# **Lançar, editar e ignorar. Nada além disso — e nenhum `DELETE`** (AC6): o par editar/ignorar já
# cobre o erro de digitação e o lançamento indevido, e apagar destruiria a auditoria, que é o
# produto. Um movimento ignorado sai do saldo mas continua visível, com o motivo do lado.


def _manual_dedup_hash(bank_account_id: str, transaction_id: str) -> str:
    """`sha256("{conta}|manual|{id}")` — a variante de `dedup_hash` do lançamento MANUAL (§4.4).

    A coluna é `NOT NULL` e carrega a constraint única `(tenant_id, bank_account_id, dedup_hash)`,
    então a primeira linha inserida já precisa de um valor — mesmo numa story que, por escopo, não
    faz deduplicação nenhuma (epic §6: *"Não inclui: … dedup por `fitid`/`dedup_hash`"*).

    **Por que chavear no próprio UUID da linha.** A variante canônica sem FITID do design §4.4 é
    `sha256("{conta}|c|{posted_at}|{amount}|{normaliza(descrição)}|{ordinal_no_dia}")` e depende do
    ordinal calculado contra o que já existe no banco naquele dia — implementá-la aqui seria
    construir metade do pipeline de importação numa story delimitada como "sem parser". Chavear no
    UUID é único por construção, satisfaz o `NOT NULL` e garante o comportamento que importa desde
    já: **dois lançamentos manuais idênticos no mesmo dia** (dois Pix de R$ 50 para a mesma pessoa)
    **são dois movimentos**, nunca um. Colidir ali seria um furo criado pelo próprio sistema — o
    risco exato que o design §4.4 alerta.

    **Consequência para quem implementar a Onda 3:** um movimento manual nunca colide com uma linha
    importada, e vice-versa. O encontro entre os dois é resolvido pelo passo de **enriquecimento
    antes de inserir** (design §4.5), que é semântico (mesma conta, mesmo valor, `posted_at` em ±3
    dias) — o hash **não** vai ajudar a casar manual × importado. E não tente "harmonizar" as
    variantes retroativamente: reescrever `dedup_hash` de linhas existentes é migration com backfill
    sob FORCE RLS, a armadilha da `0046`.

    ⚠️ Não é `core.security.hash_token`, apesar de ser o mesmo sha256. Aquele helper existe para
    que um SEGREDO não fique em claro no banco, e a evolução natural dele é virar um KDF com sal —
    o que aqui reescreveria a semântica da constraint única em silêncio. Mesma primitiva, contratos
    diferentes.
    """
    return hashlib.sha256(
        f"{bank_account_id}|{SOURCE_MANUAL}|{transaction_id}".encode()
    ).hexdigest()


def _validate_amount(amount_cents: int) -> int:
    if amount_cents == 0:
        raise BankError(
            "O valor do movimento não pode ser zero. Use um valor positivo para entrada "
            "(crédito) e negativo para saída (débito).",
            422,
        )
    return amount_cents


def validate_posted_at_floor(posted_at: date, account: BankAccount) -> date:
    """O **piso** da data do movimento: `posted_at > opening_date`. 422, com o porquê na mensagem.

    A fórmula do saldo derivado (design §3.1) só soma movimento POSTERIOR à data de abertura,
    porque tudo até ali já está dentro de `opening_balance_cents`. Aceitar a data e não somar o
    movimento seria pior do que recusar: a linha existiria, o saldo não mudaria, e ninguém
    entenderia por quê.

    ⚠️ **Extraída de `_validate_posted_at` pela Story 8.9, e é PÚBLICA de propósito.** O piso vale
    para **os dois** conjuntos de `source`, sem exceção (design Onda 2 §4.2.0); o **teto** (recusar
    data futura) vale só para `SOURCES_EXTERNA` e continua morando em `_validate_posted_at`, com o
    caminho manual. `bank/origin.py::sync_origin_movement` chama ESTA função em vez de recopiar a
    comparação — a story manda reusar a guarda existente e **não duplicar a fórmula**, porque duas
    cópias do mesmo predicado divergem no dia em que só uma for corrigida.
    """
    if posted_at <= account.opening_date:
        raise BankError(
            f"A data do movimento precisa ser posterior a {account.opening_date.isoformat()}, "
            "a data de abertura desta conta no e1p. O saldo de abertura já contempla tudo o que "
            "aconteceu até aquele dia — lançar antes disso contaria o mesmo dinheiro duas vezes.",
            422,
        )
    return posted_at


def _validate_posted_at(posted_at: date, account: BankAccount) -> date:
    """As duas guardas de data do lançamento **externo** (`SOURCES_EXTERNA`). Ambas 422.

    1. **`posted_at > opening_date`** — o piso, delegado a `validate_posted_at_floor` (que vale
       para toda origem, inclusive as do sistema).
    2. **Não futura** — extrato bancário é fato passado. Data futura é erro de digitação (ano
       errado é o caso comum), e um movimento no futuro entra no saldo de `until=None` e some do
       saldo de hoje, o que aparece como divergência inexplicável na conferência da 8.5.

    ⚠️ **O teto NÃO se aplica a `SOURCES_SISTEMA`** (design Onda 2 §4.2.0, normativo): *"o e1p pode
    afirmar o futuro do que ele mesmo agendou; não pode afirmar o futuro do que outro atestou"*. Um
    OFX descreve o que já aconteceu; um pagamento agendado no app do banco, não. O corte é por
    `source` — **nunca** por um booleano `permite_futuro` decidido pelo chamador, que é o parâmetro
    que alguém passa `True` no caminho manual, um dia, por conveniência.
    """
    validate_posted_at_floor(posted_at, account)
    if posted_at > _today():
        raise BankError(
            "A data do movimento não pode ser futura: o extrato registra o que já aconteceu.",
            422,
        )
    return posted_at


def _validate_statuses(statuses: Sequence[str]) -> tuple[str, ...]:
    invalidos = [s for s in statuses if s not in STATUSES]
    if invalidos:
        raise BankError(
            f"Status inválido: {', '.join(invalidos)}. Use um de: {', '.join(STATUSES)}.", 422
        )
    return tuple(statuses)


def get_transaction(db: Session, transaction_id: str) -> BankTransaction:
    """404 fail-closed — cross-tenant cai aqui pela RLS (a linha não existe para quem pergunta)."""
    tx = db.get(BankTransaction, transaction_id)
    if tx is None:
        raise BankError("Movimento bancário não encontrado", 404)
    return tx


def list_transactions(
    db: Session,
    *,
    bank_account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    statuses: Sequence[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BankTransaction]:
    """Movimentos do tenant, do mais recente para o mais antigo. Paginação OBRIGATÓRIA.

    `start`/`end` são datas de calendário e **inclusivas** nas duas pontas — `posted_at` é `DATE`,
    então não existe aritmética de fuso em lugar nenhum deste caminho (design §3.3).

    A ordenação desempata por `created_at` desc: dois movimentos no mesmo dia (o caso do AC7) sem
    desempate sairiam em ordem indefinida, e uma lista que muda de ordem entre dois `GET` iguais
    quebra a paginação em silêncio — a linha que estava no fim da página 1 reaparece no topo da 2.

    Paginação obrigatória é padrão do projeto desde a correção de QA da Agenda (`CLAUDE.md`):
    `limit` é grampeado em [1, 500] em vez de rejeitado, mesmo contrato de
    `payables.list_payables`.
    """
    limit = max(1, min(limit, 500))
    stmt = select(BankTransaction).order_by(
        BankTransaction.posted_at.desc(), BankTransaction.created_at.desc()
    )
    if bank_account_id:
        stmt = stmt.where(BankTransaction.bank_account_id == bank_account_id)
    if start is not None:
        stmt = stmt.where(BankTransaction.posted_at >= start)
    if end is not None:
        stmt = stmt.where(BankTransaction.posted_at <= end)
    if statuses:
        stmt = stmt.where(BankTransaction.status.in_(_validate_statuses(statuses)))
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def create_transaction(
    db: Session,
    *,
    bank_account_id: str,
    tenant_id: str,
    actor: str,
    data: BankTransactionCreate,
) -> BankTransaction:
    """Lança um movimento MANUAL na conta. `source` é fixado aqui, nunca vem do payload.

    Validações, todas antes de qualquer escrita: conta existe e é visível (404 fail-closed pela
    RLS), conta **não arquivada** (422 — lançar movimento NOVO numa conta encerrada é quase sempre
    a conta errada selecionada), valor `!= 0` (422) e as duas guardas de data de
    `_validate_posted_at` (422). Note a assimetria deliberada com `update_transaction`, que
    **aceita** editar movimento de conta arquivada: encerrar a conta impede lançar história nova,
    não impede corrigir a história que já estava lá.

    ⚠️ **Desvio documentado do contrato tabelado na story:** a story lista
    `create_transaction(db, *, tenant_id, actor, data)` — sem a conta —, mas a rota que o mesmo
    AC6 fixa recebe a conta no PATH (`POST /bank/accounts/{id}/transactions`). Como
    `BankTransactionCreate` não tem (nem deve ter) `bank_account_id`, a conta entra como parâmetro
    nomeado. É uma ADIÇÃO, não uma quebra: qualquer chamador precisa informar a conta de todo
    jeito, e `update_transaction` já recebe o `transaction_id` do mesmo jeito. Pôr o id no corpo
    criaria duas fontes de verdade para a mesma informação, com a pergunta "qual vence?" a ser
    respondida em 8.7.
    """
    acc = get_account(db, bank_account_id)
    if acc.archived_at is not None:
        raise BankError(
            "Esta conta está arquivada e não recebe lançamentos novos. Se ela voltou a ser usada, "
            "cadastre-a de novo com o saldo de abertura do dia.",
            422,
        )
    amount_cents = _validate_amount(data.amount_cents)
    posted_at = _validate_posted_at(data.posted_at, acc)

    # O id é gerado AQUI (e não pelo default do modelo, que só é aplicado no INSERT) porque o
    # `dedup_hash` é chaveado nele: sem isso seria preciso inserir, ler o id de volta e dar um
    # UPDATE — três idas ao banco e uma janela em que a coluna NOT NULL não teria valor.
    transaction_id = _uuid()
    tx = BankTransaction(
        id=transaction_id,
        tenant_id=tenant_id,
        bank_account_id=acc.id,
        posted_at=posted_at,
        amount_cents=amount_cents,
        # Congela AQUI e nunca mais muda (invariante (c) do modelo).
        raw_description=data.description,
        user_description="",
        fitid=None,
        dedup_hash=_manual_dedup_hash(acc.id, transaction_id),
        counterparty_name=data.counterparty_name,
        counterparty_document=data.counterparty_document,
        operation_nature=data.operation_nature,
        source=SOURCE_MANUAL,
        status=STATUS_UNMATCHED,
    )
    db.add(tx)
    # `flush` ANTES do `audit.record`, mesmo padrão de `create_account`: garante que a linha entrou
    # (a constraint única de dedupe fala aqui) antes de gravar um rastro que a afirma.
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.create", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


def update_transaction(
    db: Session,
    *,
    transaction_id: str,
    tenant_id: str,
    actor: str,
    data: BankTransactionUpdate,
) -> BankTransaction:
    """Corrige um movimento: **só** `posted_at`, `amount_cents` e `user_description`.

    Um movimento `ignored` pode ser editado — corrigir e depois reativar (`unignore`) é o caminho
    normal de quem ignorou por engano. Movimento de conta **arquivada** também pode: ver a nota de
    assimetria em `create_transaction`.

    A guarda contra editar `raw_description`/`source`/`dedup_hash`/`status`/`fitid` é dupla, de
    propósito: os campos não existem em `BankTransactionUpdate` **e** esta função só toca nos três
    campos permitidos, um a um, sem nenhum `setattr` genérico sobre `data.model_dump()`. Um laço
    genérico transformaria "acrescentar um campo ao schema" em "tornar esse campo editável" sem que
    ninguém precisasse decidir isso — que é exatamente como uma coluna imutável deixa de ser.
    """
    tx = get_transaction(db, transaction_id)

    if data.posted_at is not None:
        # Revalida contra a conta ATUAL do movimento (a conta não muda: não há rota para movê-lo).
        tx.posted_at = _validate_posted_at(data.posted_at, get_account(db, tx.bank_account_id))
    if data.amount_cents is not None:
        tx.amount_cents = _validate_amount(data.amount_cents)
    if data.user_description is not None:
        tx.user_description = data.user_description

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.update", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


def ignore_transaction(
    db: Session, *, transaction_id: str, tenant_id: str, actor: str, reason: str = ""
) -> BankTransaction:
    """Tira o movimento do saldo derivado sem apagá-lo. **Idempotente.**

    "Ignorar" é o que o usuário faz com um lançamento que existe no extrato mas não deveria contar
    para ele. A linha continua visível, com o motivo do lado — o oposto de um `DELETE`, que sumiria
    com a evidência e deixaria o saldo mudado sem explicação.

    Já ignorado → no-op silencioso (não re-grava o motivo, não gera segunda auditoria): a resposta é
    a mesma, que é o que idempotente significa para quem chamou duas vezes por causa de um clique
    duplo.
    """
    tx = get_transaction(db, transaction_id)
    if tx.status == STATUS_IGNORED:
        return tx
    tx.status = STATUS_IGNORED
    tx.ignored_reason = reason[:120]
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.ignore", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


def unignore_transaction(
    db: Session, *, transaction_id: str, tenant_id: str, actor: str
) -> BankTransaction:
    """Devolve o movimento ao saldo (`ignored` → `unmatched`) e limpa o motivo. **Idempotente.**

    Existe porque `ignore` sem volta transformaria um clique errado em dado permanentemente fora do
    saldo — e não há `DELETE` para desfazer. Volta sempre para `unmatched`, nunca para `partial`/
    `matched`: reconstruir o estado de conciliação é trabalho do `_refresh_status` da Onda 4, e
    chutá-lo aqui seria escrever na invariante (d) do modelo de fora do dono dela.
    """
    tx = get_transaction(db, transaction_id)
    if tx.status != STATUS_IGNORED:
        return tx
    tx.status = STATUS_UNMATCHED
    tx.ignored_reason = ""
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transaction.unignore", target=tx.id
    )
    db.commit()
    db.refresh(tx)
    return tx


# ── Saldo declarado / checkpoint (Story 8.4) ─────────────────────────────────────────────────
#
# **Nenhuma função desta seção toca em `BankAccount` ou `BankTransaction`.** É a invariante que
# mantém a divergência mensurável: o checkpoint é a verdade EXTERNA, o derivado é o que o sistema
# calculou, e os dois só se encontram na comparação read-only da Story 8.5. Ver o aviso (c) na
# docstring de `BankBalanceCheckpoint`.


# Desempate determinístico de `latest_checkpoint` quando dois `origin` compartilham o MESMO
# `reference_date`: **`ofx` na frente de `manual`**. O `<LEDGERBAL>` do arquivo do banco é a mesma
# verdade externa com um intermediário humano a menos. Só passa a ter efeito na Onda 3 (hoje a API
# escreve apenas `manual`); está aqui para a regra não ser inventada duas vezes.
#
# Um `CASE` explícito, e não `ORDER BY origin DESC`: por acidente alfabético 'ofx' > 'manual', então
# o `DESC` daria o mesmo resultado hoje e o resultado ERRADO no dia em que um terceiro valor entrar
# no vocabulário — uma regra de negócio que depende da ortografia dos valores é uma regra que ainda
# não foi escrita. `else_` maior que os dois conhecidos: valor novo entra por último até que alguém
# decida onde ele fica.
_ORIGIN_RANK = case(
    {ORIGIN_OFX: 0, ORIGIN_MANUAL: 1},
    value=BankBalanceCheckpoint.origin,
    else_=99,
)


def _validate_origin(origin: str) -> str:
    """Só `manual` é escrito nesta onda (AC3). `ofx` é recusado com a explicação, não com um enum.

    A coluna aceita os dois valores desde já (`ORIGINS`) porque o vocabulário do eixo B é fechado no
    design e declará-lo custa zero; o que a Onda 1 não tem é o **caminho de código** que produz um
    `ofx` honesto — ele viria do `<LEDGERBAL>` de um arquivo importado, com `import_batch_id`
    preenchido apontando para o lote. Aceitar `ofx` de um cliente HTTP hoje criaria uma linha que
    diz "o banco atestou isto" sem nenhum arquivo por trás: uma verdade externa forjada, dentro da
    tabela cujo propósito é ser a única coisa que o sistema não inventou.
    """
    if origin == ORIGIN_MANUAL:
        return origin
    if origin in ORIGINS:
        raise BankError(
            f"O saldo de origem '{origin}' ainda não pode ser registrado: ele vem do arquivo do "
            "banco, e a importação de extrato ainda não existe. Informe o saldo desta conta no fim "
            "do dia olhando o app do banco.",
            422,
        )
    raise BankError(
        f"Origem de saldo inválida: '{origin}'. Use um de: {', '.join(ORIGINS)}.", 422
    )


def _validate_reference_date(reference_date: date, account: BankAccount) -> date:
    """As duas guardas de data do saldo declarado. Ambas 422, ambas protegendo a comparação da 8.5.

    1. **Não futura** — não se declara o saldo de amanhã: o número que o usuário está olhando no app
       do banco é sempre de um dia que já terminou (ou do dia corrente). Data futura é erro de
       digitação (ano errado é o caso comum) e produziria uma comparação contra um saldo derivado
       que ainda não terminou de acontecer.
    2. **`reference_date >= account.opening_date`** — antes da data de abertura o e1p não conhece a
       conta e o saldo derivado **não existe** para ser comparado; a conferência apontaria uma
       divergência inteira, inventada, contra um número que o sistema não tinha como calcular.

    ⚠️ Note a assimetria deliberada com `_validate_posted_at` (movimento), que exige
    `posted_at > opening_date`, **estritamente**. Aqui `reference_date == opening_date` é
    **aceito**, e é o caso mais sadio que existe: `opening_balance_cents` é, por definição, o saldo
    ao fim do dia de abertura, então `derived_balance(until=opening_date)` devolve exatamente ele e
    a comparação vale. Para o movimento, o mesmo dia significaria contar duas vezes um dinheiro que
    já está dentro do saldo de abertura — daí um `>` lá e um `>=` aqui.
    """
    if reference_date > _today():
        raise BankError(
            "A data do saldo não pode ser futura: informe o saldo de um dia que já terminou, "
            "olhando o app do banco.",
            422,
        )
    if reference_date < account.opening_date:
        raise BankError(
            f"A data do saldo precisa ser igual ou posterior a "
            f"{account.opening_date.isoformat()}, a data de abertura desta conta no e1p. Antes "
            "desse dia o e1p não conhece a conta e não teria com o que comparar o saldo informado.",
            422,
        )
    return reference_date


# ── Leitura ──────────────────────────────────────────────────────────────────────────────────


def get_checkpoint(db: Session, checkpoint_id: str) -> BankBalanceCheckpoint:
    """404 fail-closed — cross-tenant cai aqui pela RLS (a linha não existe para quem pergunta)."""
    cp = db.get(BankBalanceCheckpoint, checkpoint_id)
    if cp is None:
        raise BankError("Saldo declarado não encontrado", 404)
    return cp


def list_checkpoints(
    db: Session,
    *,
    bank_account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BankBalanceCheckpoint]:
    """Saldos declarados do tenant, do mais recente para o mais antigo. Paginação OBRIGATÓRIA.

    `start`/`end` são datas de calendário e **inclusivas** nas duas pontas, mesmo contrato de
    `list_transactions` — `reference_date` é `DATE`, então não existe aritmética de fuso aqui.

    A ordenação desempata por `created_at` desc: sem desempate, dois checkpoints do mesmo dia (o
    caso `manual` + `ofx` da Onda 3) sairiam em ordem indefinida e a paginação quebraria em
    silêncio — a linha do fim da página 1 reaparece no topo da 2.
    """
    limit = max(1, min(limit, 500))
    stmt = select(BankBalanceCheckpoint).order_by(
        BankBalanceCheckpoint.reference_date.desc(), BankBalanceCheckpoint.created_at.desc()
    )
    if bank_account_id:
        stmt = stmt.where(BankBalanceCheckpoint.bank_account_id == bank_account_id)
    if start is not None:
        stmt = stmt.where(BankBalanceCheckpoint.reference_date >= start)
    if end is not None:
        stmt = stmt.where(BankBalanceCheckpoint.reference_date <= end)
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


def latest_checkpoint(
    db: Session,
    *,
    bank_account_id: str,
    on_or_before: date,
    origins: tuple[str, ...] | None = None,
) -> BankBalanceCheckpoint | None:
    """O saldo declarado mais recente desta conta com `reference_date <= on_or_before`, ou `None`.

    **É a função central que a conferência (Story 8.5) consome** e o contrato mais importante desta
    story. Duas coisas precisam ficar ditas em voz alta:

    **1. `None` é o caminho NORMAL, não um erro.** Quando não há checkpoint na janela, a 8.5 declara
    `saldo_banco_origem = ORIGEM_INDISPONIVEL` (eixo A, `app.core.money_planes`) e o relatório **diz
    que não sabe**, em vez de comparar contra zero — o que seria o pior bug possível aqui: uma
    divergência inteira, inventada, com aparência de fato. Não transforme este `None` em exceção,
    nem em `0`, nem no saldo de abertura.

    **2. A comparação usa o `reference_date` DO CHECKPOINT DEVOLVIDO, não `on_or_before`.** A 8.5
    faz `derived_balance(..., until=cp.reference_date)`, com o mesmo `D` dos dois lados. Se o
    checkpoint encontrado é de 15/07 e o relatório pediu até 31/07, comparar o saldo do banco de
    15/07 com o saldo do sistema de 31/07 acusaria como divergência tudo o que aconteceu no meio —
    o erro clássico desta classe de relatório, que o design §5.1 manda **recusar**.

    `origins` filtra o eixo B (`('manual',)`, `('ofx',)`); `None` = qualquer porta de entrada.
    Desempate no mesmo dia: **`ofx` antes de `manual`** — ver `_ORIGIN_RANK`. `LIMIT 1`.

    Não valida a conta de propósito: é uma função de leitura consumida em laço pela conferência, e a
    RLS já garante que checkpoint de outro tenant não aparece (conta inexistente → nenhuma linha →
    `None`, que é o mesmo estado honesto de "não há verdade externa aqui").
    """
    stmt = (
        select(BankBalanceCheckpoint)
        .where(
            BankBalanceCheckpoint.bank_account_id == bank_account_id,
            BankBalanceCheckpoint.reference_date <= on_or_before,
        )
        .order_by(
            BankBalanceCheckpoint.reference_date.desc(),
            _ORIGIN_RANK.asc(),
            BankBalanceCheckpoint.created_at.desc(),
        )
        .limit(1)
    )
    if origins:
        stmt = stmt.where(BankBalanceCheckpoint.origin.in_(_validate_origins(origins)))
    return db.scalars(stmt).first()


def _validate_origins(origins: Sequence[str]) -> tuple[str, ...]:
    invalidos = [o for o in origins if o not in ORIGINS]
    if invalidos:
        raise BankError(
            f"Origem de saldo inválida: {', '.join(invalidos)}. Use um de: {', '.join(ORIGINS)}.",
            422,
        )
    return tuple(origins)


def days_since_last_declared_balance(
    db: Session, *, bank_account_id: str | None = None, today: date
) -> int | None:
    """Dias desde o ÚLTIMO saldo declarado (da conta, ou do tenant inteiro). `None` = nunca houve.

    É o insumo da frase honesta *"saldo não confirmado há 47 dias"* (design §5.1 bloco 4): o sistema
    **declara que não sabe** em vez de culpar o usuário por não conferir. `None` é "nunca
    declarado", que é diferente de `0` ("declarado hoje") — devolver `0` nos dois casos apagaria
    justamente a distinção que a frase precisa fazer.

    `bank_account_id=None` dá a visão consolidada do tenant; informado, dá a da conta. Os dois
    existem porque um diagnóstico geral quer o consolidado e um relatório por conta precisa apontar
    **qual** conta está desatualizada (epic §9 F3).

    ⚠️ **NÃO é o `dias_desde_ultima_conferencia` da Story 8.5** — semânticas diferentes, e ligar as
    duas ao mesmo campo daria dois números com o mesmo nome. Aqui é `MAX(reference_date)` **sem
    teto**; lá é a distância até o checkpoint que caiu **dentro da janela do relatório**
    (`latest_checkpoint(on_or_before=end)`). Consumidores previstos: a Story 8.7 ("último saldo
    declarado" no cartão da conta) e a Onda 3. ⚠️ **[@dev 8.4] Nenhum consumidor existe ainda no
    repositório** — ela é entregue por AC7 com a semântica que a story fixou, e a assinatura não
    foi ajustada a nenhum chamador imaginado. Quem for consumi-la primeiro deve conferir se é este
    número que quer, e não o da 8.5.

    Agregação no banco, UMA query — nunca carregar linhas para achar o máximo em Python.
    """
    stmt = select(func.max(BankBalanceCheckpoint.reference_date))
    if bank_account_id:
        stmt = stmt.where(BankBalanceCheckpoint.bank_account_id == bank_account_id)
    ultimo = db.scalar(stmt)
    if ultimo is None:
        return None
    # SQLite devolve `DATE` como texto em agregações; o Postgres devolve `date`. Normalizar aqui
    # mantém o contrato (`int | None`) idêntico nos dois bancos — sem isso o subtrair explodiria só
    # na suíte unitária, ou só em produção, conforme quem fosse o primeiro a rodar.
    if isinstance(ultimo, str):
        ultimo = date.fromisoformat(ultimo)
    return (today - ultimo).days


# ── Escrita ──────────────────────────────────────────────────────────────────────────────────


def declare_balance(
    db: Session,
    *,
    bank_account_id: str,
    tenant_id: str,
    actor: str,
    data: CheckpointCreate,
) -> tuple[BankBalanceCheckpoint, bool]:
    """Registra *"o saldo desta conta, no fim deste dia, era X"*. Devolve `(checkpoint, criado)`.

    O `bool` é **"criado agora"**: `True` → o router responde 201, `False` → 200 (AC4).

    **Redeclarar o mesmo dia CORRIGE, não conflita.** Um checkpoint é a declaração de um fato, e
    quem digitou 1.234,00 no lugar de 12.340,00 precisa corrigir com um gesto — não com um ciclo
    apagar→recriar, que é o oposto do teto de simplicidade do design §0. Um 409 aqui seria o sistema
    tratando o próprio erro de digitação do usuário como uma violação de integridade.

    **Este método NÃO cria, altera nem baixa movimento nenhum.** Não existe "movimento de ajuste"
    para fechar a diferença entre o declarado e o derivado, e nunca pode existir: ver o aviso (c) na
    docstring de `BankBalanceCheckpoint`.

    Validações, todas antes de qualquer escrita e nesta ordem (a ordem define o status que o usuário
    recebe quando erra duas coisas ao mesmo tempo): conta visível (404 fail-closed pela RLS) → conta
    não arquivada (422) → `origin` (422) → data não futura (422) → data >= abertura (422).
    `balance_cents` **não** tem guarda de sinal: negativo é um saldo legítimo.
    """
    acc = get_account(db, bank_account_id)
    if acc.archived_at is not None:
        raise BankError(
            "Esta conta está arquivada e não recebe saldos novos. Se ela voltou a ser usada, "
            "cadastre-a de novo com o saldo de abertura do dia.",
            422,
        )
    origin = _validate_origin(data.origin)
    reference_date = _validate_reference_date(data.reference_date, acc)

    existente = db.scalars(
        select(BankBalanceCheckpoint).where(
            BankBalanceCheckpoint.bank_account_id == acc.id,
            BankBalanceCheckpoint.reference_date == reference_date,
            BankBalanceCheckpoint.origin == origin,
        )
    ).first()

    criado = existente is None
    if existente is not None:
        cp = existente
        cp.balance_cents = data.balance_cents
        # Quem corrigiu passa a ser o autor: o rastro de QUEM declarou o número que está valendo é
        # mais útil que o de quem declarou o número que foi substituído — e o histórico completo da
        # correção continua no `audit_entries`, que é onde ele pertence.
        cp.created_by = actor
    else:
        cp = BankBalanceCheckpoint(
            tenant_id=tenant_id,
            bank_account_id=acc.id,
            reference_date=reference_date,
            balance_cents=data.balance_cents,
            origin=origin,
            # Só a importação da Onda 3 preenche.
            import_batch_id=None,
            created_by=actor,
        )
        db.add(cp)

    try:
        # `flush` ANTES do `audit.record`, mesmo padrão de `create_account`/`create_transaction`:
        # `id` tem default Python-side (`_uuid`), aplicado só no INSERT — sem o flush o rastro
        # nasceria com `target=''`, apontando para nada.
        db.flush()
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="bank.checkpoint.declare", target=cp.id
        )
        db.commit()
    except IntegrityError as e:
        # A CORRIDA: duas declarações simultâneas do mesmo dia passam as duas pelo `select` acima
        # sem achar nada e as duas tentam inserir. O `UNIQUE` é a garantia final (fail-closed, no
        # espírito da RLS) e a perdedora recebe 409 — o único caminho em que esta rota devolve 409,
        # e ele não é o de redeclaração, que é o caminho normal acima.
        db.rollback()
        raise BankError(
            "Outro registro para o saldo desta conta neste dia foi gravado ao mesmo tempo. "
            "Recarregue e confira o valor.",
            409,
        ) from e
    db.refresh(cp)
    return cp, criado


def delete_checkpoint(
    db: Session, *, checkpoint_id: str, tenant_id: str, actor: str
) -> None:
    """Remove uma declaração indevida. **O único `DELETE` físico do módulo `bank`.**

    Contas se arquivam e movimentos se ignoram — os dois têm histórico dependente e apagá-los
    destruiria a auditoria, que é o produto. Um checkpoint não tem nada pendurado nele e é uma
    declaração pontual: mantê-lo "arquivado" só poluiria `latest_checkpoint` com um estado a
    filtrar, e um estado a filtrar é um estado que alguém vai esquecer de filtrar. O rastro da
    remoção fica em `audit_entries`.

    404 fail-closed para inexistente e para cross-tenant (a RLS esconde a linha).
    """
    cp = get_checkpoint(db, checkpoint_id)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.checkpoint.delete", target=cp.id
    )
    db.delete(cp)
    db.commit()
