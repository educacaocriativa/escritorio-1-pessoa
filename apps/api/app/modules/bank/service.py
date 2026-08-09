"""Regras do módulo bancário: contas + conta primária + **saldo derivado** (Story 8.2), os
**movimentos** que fazem esse saldo se mover (Story 8.3) e o **saldo declarado** — a verdade
externa contra a qual o derivado é medido (Story 8.4).

**Isolamento:** por RLS, e só por RLS — nenhuma query aqui filtra `tenant_id` à mão (Regra de Ouro
nº 1 do `CLAUDE.md`: defesa-em-profundidade foi considerada e REJEITADA para não criar o padrão
"algumas queries filtram, outras não", onde esquecer uma vira vazamento). Cross-tenant cai em
`db.get(...) is None` → 404 fail-closed, nunca 403 (403 confirmaria a existência da linha).

**Sem FK dura** entre entidades financeiras (padrão do projeto: `charges.client_id`, e o mesmo
`cost_center_id` do módulo de contas a pagar): a referência é solta e a integridade é validada no
service — `bank_transactions.bank_account_id` é validada chamando `get_account`, sem `ForeignKey`.

⚠️ **Este arquivo não NOMEIA os módulos de negócio, e isso é gate, não estilo** (Story 8.17,
achado A-2): `tests/test_money_planes.py::test_bank_service_nao_nomeia_a_entidade_de_negocio`
reprova as strings do módulo de contas a pagar/a receber aqui — em qualquer posição, inclusive em
prosa e em anotação sob `TYPE_CHECKING`. O custo é escrever *"o módulo de negócio"* em vez do nome
dele; o ganho é que **não existe forma de reintroduzir a dependência proibida que passe daqui**.
Duas citações desta docstring foram reescritas por causa disso, sem mudar o que elas dizem.

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
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, Protocol

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.money_planes import ORIGEM_BANCO, ORIGEM_INDISPONIVEL
from app.db.base import _uuid
from app.modules.bank.models import (
    KIND_INVESTMENT,
    KIND_PLATFORM_WALLET,
    KINDS,
    ORIGIN_MANUAL,
    ORIGIN_OFX,
    ORIGINS,
    SOURCE_MANUAL,
    SOURCES_EXTERNA,
    SOURCES_SISTEMA,
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
        # `None` = o router serializa `str(e)`, como sempre. Só o erro ACIONÁVEL preenche — mesmo
        # contrato do erro do módulo de contas a pagar, para que exista **um** formato de erro
        # acionável no repositório e não dois (Story 8.17 AC5, alinhado com a 8.12 AC2).
        self.detail: dict | None = None


# ── A porta de saída da guarda de contagem dupla (Story 8.17 AC6) ────────────────────────────
#
# ⚠️ **LEIA ISTO ANTES DE "SIMPLIFICAR" O QUE VEM ABAIXO.** Este bloco existe porque a guarda do
# AC5 precisa perguntar *"já existe uma obrigação de negócio para este mesmo dinheiro?"* de dentro
# do caminho de escrita de `bank` — e o gate estrutural da Story 8.9
# (a asserção positiva de `tests/test_money_planes.py`) proíbe `bank` de importar o módulo
# de negócio. A regra que decide todas as alternativas está na ratificação §C-5.1:
#
#     **Evadir um gate é pior do que quebrá-lo às claras.** Quebrado às claras, alguém vê no diff;
#     evadido, o gate fica verde e a proibição está morta — que é literalmente o achado TEST-001.
#
# Por isso **import lazy dentro da função e SQL cru sobre a tabela do outro módulo estão reprovados
# por definição** nesta onda (os dois passam no gate de AST e violam exatamente o que ele protege).
#
# **A forma ratificada: inversão de dependência.** `bank` declara o contrato (o DTO + o `Protocol`
# + o registrador) e **não sabe** quem o implementa; o módulo de negócio implementa (ele **pode**
# importar `bank`); `app/main.py` liga os dois. Direção final: `main → bank`, `main → negócio`,
# `negócio → bank`. O gate fica verde **porque a dependência sumiu**, não porque foi escondida.
#
# ⚠️ **E é por isso que NADA neste arquivo nomeia a entidade do outro lado — nem sob
# `TYPE_CHECKING`, nem no nome de um campo.** Um `Protocol` que devolvesse a entidade do módulo de
# negócio obrigaria este arquivo a importar o TIPO, e `if TYPE_CHECKING: from app.modules...`
# continua sendo um import que a varredura de **texto cru** do gate pega, com razão (achado A-2 da
# ratificação: *"a forma proposta reprovava o próprio gate que ela existe para respeitar"*).
# `test_money_planes.py::test_bank_service_nao_nomeia_a_entidade_de_negocio` trava isto.


@dataclass(frozen=True)
class DuplicataCandidato:
    """Uma obrigação de negócio que **pode ser o mesmo dinheiro** de um movimento manual de saída.

    O DTO é de `bank` e é **opaco de propósito**: `referencia_id` não se chama nada mais específico
    porque este módulo não pode nomear um conceito do outro lado nem em nome de campo. Quem monta o
    DTO é o implementador do `DuplicataProbe`; quem traduz o `referencia_id` para o vocabulário do
    payload HTTP é a **rota** (`bank/router.py`), nunca este service.
    """

    referencia_id: str
    """Id opaco. `bank` não sabe de que entidade é — só o devolve para quem sabe."""
    descricao: str
    """Como a obrigação se chama para o usuário ("Enel", "Aluguel"). Pode ser vazio."""
    valor_cents: int
    """Valor ABSOLUTO em centavos (BigInteger, Regra de Ouro: dinheiro nunca é float)."""
    data: date
    """A data de calendário que identifica a obrigação para o usuário (o vencimento)."""


class DuplicataProbe(Protocol):
    """A consulta que `bank` **não** sabe fazer. Recebe o `db` do request; nunca abre sessão.

    ⚠️ **O `db` é parâmetro, e isso é normativo** (ratificação §C-5.4): a busca roda na sessão do
    request, sob RLS, sem nenhum filtro manual de `tenant_id` (Regra de Ouro nº 1). Abrir sessão
    própria dentro do probe seria escapar da GUC do tenant — e a guarda passaria a enxergar
    obrigação de OUTRO tenant, que é o cenário do IV5 da Story 8.17.
    """

    def __call__(
        self, db: Session, *, amount_cents: int, posted_at: date
    ) -> DuplicataCandidato | None: ...


_duplicata_probe: DuplicataProbe | None = None


def register_duplicata_probe(probe: DuplicataProbe) -> None:
    """Liga a implementação concreta. Chamado **uma vez**, na composição (`app/main.py`)."""
    global _duplicata_probe
    _duplicata_probe = probe


def duplicata_probe_registrado() -> bool:
    """A guarda de BOOT pergunta isto — ver `app.main.verifica_fiacao_da_guarda`."""
    return _duplicata_probe is not None


# A janela e o critério de valor da guarda, em **constantes nomeadas e num lugar só**.
#
# ⚠️ **±3 dias e valor EXATO são deliberadamente os MESMOS do enriquecimento** do design-mãe §4.5 —
# *"um número, não dois"* (design Onda 2 §7(b), `[SUPOSIÇÃO do design, parametrizável]`). Dois
# números diferentes para a mesma pergunta ("estas duas linhas são o mesmo dinheiro?") seriam o
# começo de duas respostas diferentes quando o matcher da Onda 4 chegar.
#
# Moram AQUI, e não no implementador, pelo mesmo motivo: quem define a pergunta é o contrato. O
# implementador importa daqui (a direção `negócio → bank` é a permitida), e por isso a constante é
# pública apesar de a Story 8.17 tê-la escrito com underscore — **desvio deliberado**: um nome
# privado importado de fora seria a forma de ter dois números sem parecer que se tem.
DUPLICATA_JANELA_DIAS: Final[int] = 3


class DuplicataDePagamento(BankError):
    """**409 com ESCOLHA, não bloqueio mudo** (Story 8.17 AC5). Carrega o DTO; a rota o traduz.

    O usuário tem duas saídas, e nenhuma delas vem pré-selecionada: dar baixa na obrigação (e aí o
    movimento *nasce sozinho*, pela Regra da Origem) ou repetir a requisição com
    `confirmar_avulso=true` para afirmar que é mesmo outro pagamento.

    ⚠️ **A mensagem NÃO é montada aqui.** Ela nomeia o conceito do outro módulo ("conta a pagar"),
    e este arquivo não pode nomeá-lo — ver o aviso no topo deste bloco. Quem redige é a rota, num
    lugar só (mesma disciplina de `_NOTE_SEM_CHECKPOINT` na conferência).
    """

    def __init__(self, candidato: DuplicataCandidato):
        super().__init__(
            "Este movimento pode ser o mesmo dinheiro de um lançamento que o e1p já conhece.", 409
        )
        self.candidato = candidato


def _probe_duplicata(
    db: Session, *, amount_cents: int, posted_at: date
) -> DuplicataCandidato | None:
    """A **segunda** guarda do fail-closed — inalcançável se a de boot funcionar.

    ⚠️ **Fail-closed, e a hora certa é o BOOT** (ratificação §C-5.2): *"um erro de fiação é condição
    de startup, não de request"*. Quem impede a app de subir sem probe é
    `app.main.verifica_fiacao_da_guarda` (precedente: a guarda de boot do `JWT_SECRET` fraco). Esta
    checagem fica como segunda linha, com a mesma disciplina dupla que `update_transaction`
    documenta *"de propósito"* — e **nunca** silencia: "não valida em silêncio" seria a guarda
    desligada em produção sem ninguém saber, que é o pior modo de falha da onda.
    """
    if _duplicata_probe is None:
        raise BankError(
            "A guarda de contagem dupla não está ligada nesta instância — o lançamento foi "
            "recusado em vez de ser aceito sem verificação. Isto é erro de configuração do "
            "servidor (a composição da aplicação não registrou a consulta), não do seu "
            "lançamento.",
            500,
        )
    return _duplicata_probe(db, amount_cents=amount_cents, posted_at=posted_at)


def _today(db: Session, *, now: datetime | None = None) -> date:
    """Hoje NO FUSO DO TENANT — mesma âncora do Cockpit e da Projeção.

    Era `datetime.now(UTC).date()`. O comentário antigo argumentava que, para UTC−3, a data UTC
    nunca fica ATRÁS da local e portanto a guarda de "data futura" só erraria para o lado
    permissivo. Verdade — e insuficiente: `resolve_until` e `agendado_sums` usam a MESMA âncora
    para decidir o que já é passado, e ali um dia a mais **antecipa saldo e agendamento**. A
    dívida do `CLAUDE.md` §6.1 morre aqui.
    """
    from app.modules.settings.service import hoje_do_tenant

    return hoje_do_tenant(db, now=now)


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


def resolve_until(until: date | None, hoje: date) -> date:
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
    return hoje if until is None else until


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


def _validate_opening_date(opening_date: date, hoje: date) -> date:
    if opening_date > hoje:
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


def _validate_saldo_conhecido(
    *, account: BankAccount, novo_conhecido: bool | None, novo_saldo: int | None
) -> None:
    """Recusa (422) as duas formas de o par (valor, ato) sair incoerente num PATCH — Story 8.21.

    **É a mesma família de `_validate_opening_date_recuo`**, e pela mesma razão: um saldo de
    partida que o dono não afirmou produz uma **divergência inventada** na conferência, e
    divergência inventada é pior que divergência escondida — depois de duas caçadas frustradas ele
    para de confiar no sinal, e o sinal é o produto.

    **Ramo 1 — `false → true` sem informar o saldo.** Afirmar *"agora eu sei"* mantendo o
    placeholder `0` é declarar que o banco tinha zero num dia em que ninguém olhou. O número tem de
    vir no MESMO PATCH.

    **Ramo 2 — informar saldo numa conta `is_known=false` sem declarar o ato.** ⚠️ **Este é o que
    fecha a armadilha real**, e ele existe porque a tela é UMA das portas, não a única. O
    `AccountModal` envia `opening_balance_cents` em quase todo salvamento; aceitar isso em silêncio
    gravaria o número certo com a conta ainda "não sei" e a **Projeção continuaria suprimida sem
    explicação** — o dono faria exatamente o que a nota mandou e nada mudaria. Pior que não ter
    saída: é uma saída que parece funcionar. A guarda protege a API contra todo o resto (Atalho do
    iOS, script, `curl`, cliente futuro), exatamente como a docstring da guarda irmã argumenta.

    **O caminho `true → false` é livre** e **não apaga** `opening_balance_cents`: o número volta a
    valer se o dono voltar atrás, e apagá-lo destruiria uma afirmação que foi verdadeira.
    """
    virou_conhecido = novo_conhecido is True and not account.opening_balance_is_known
    if virou_conhecido and novo_saldo is None:
        raise BankError(
            "Para dizer que você sabe o saldo desta conta, informe o valor no mesmo passo. Sem "
            "ele, o e1p partiria do zero que ficou guardado como marcador e a conferência "
            "acusaria uma diferença que não existe.",
            422,
        )
    informou_valor_sem_declarar_ato = (
        novo_saldo is not None
        and novo_conhecido is None
        and not account.opening_balance_is_known
    )
    if informou_valor_sem_declarar_ato:
        raise BankError(
            "Esta conta está marcada como 'não sei o saldo'. Informar o valor sem mudar essa "
            "marca gravaria o número e manteria a Projeção de Caixa calada, sem explicação — "
            "declare também que você passou a saber o saldo.",
            422,
        )
    # **Ramo 3 — valor NOVO junto de "não sei", no mesmo PATCH.** [Achado do @qa no gate desta
    # story.] `create_account` já recusa isto (força `0`, com o comentário de que aceitar guardaria
    # duas afirmações contraditórias na mesma linha), e o argumento não muda por ser edição — a
    # assimetria era só do laço genérico de `update_account`, que escrevia os dois campos sem
    # olhar um para o outro.
    # ⚠️ **Recusar não é o mesmo que APAGAR.** O caminho `true → false` sozinho continua livre e
    # PRESERVA `opening_balance_cents` (AC7): o número volta a valer se o dono voltar atrás, e
    # apagá-lo destruiria uma afirmação que foi verdadeira. O que se recusa é a instrução
    # **contraditória**, não o esquecimento.
    if novo_conhecido is False and novo_saldo is not None:
        raise BankError(
            "Você marcou que não sabe o saldo desta conta e informou um valor no mesmo passo — "
            "as duas coisas não podem ser verdade. Escolha uma: informe o saldo, ou marque que "
            "não sabe (o valor que já estava guardado é preservado).",
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
    db: Session,
    *,
    accounts: Sequence[BankAccount],
    until: date | None = None,
    since: date | None = None,
    sign: int | None = None,
    exclude_sources: frozenset[str] = frozenset(),
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
          AND (:since IS NULL OR posted_at >  :since)    -- `since` é DATE e EXCLUSIVO (8.14)
          AND (:sign  IS NULL OR sinal(amount_cents) = :sign)
          AND (:exclude_sources vazio OR source NOT IN :exclude_sources)  -- Onda 2b-ii
          AND status <> 'ignored'                        -- AC5: ignorar TIRA do saldo

    ⚠️ **O filtro `status <> 'ignored'` mora AQUI, dentro do saldo** — é contrato para as Stories
    8.5 e 8.7: quem consome o saldo derivado **não** refiltra. Ter o filtro em dois lugares é ter
    dois lugares para divergirem.

    ⚠️ **[Story 8.14] `since` e `sign` existem para que "Agendado para sair" NÃO seja uma segunda
    fórmula.** O número da tela é a Σ dos movimentos com `posted_at > hoje`, separada por sinal —
    o mesmo `WHERE` do saldo com o **recorte de data invertido**. Escrever aquela soma noutro lugar
    duplicaria o piso (`posted_at > opening_date`) e o `status <> 'ignored'`, e o dia em que um dos
    dois fosse corrigido só de um lado o "Agendado para sair" passaria a divergir do saldo por um
    motivo que ninguém acharia. Ver `agendado_sums`.

    `since` é **exclusivo** (`>`) para casar exatamente com o `<=` de `until`: os dois recortes
    particionam o eixo do tempo em `(…, hoje]` e `(hoje, …)` sem sobreposição e sem buraco. Um
    movimento **de hoje** está no saldo corrente e **não** está no agendado — que é a invariante
    de que o AC6 da Projeção depende.

    `sign` é `+1` (só entradas), `-1` (só saídas) ou `None` (líquido, o comportamento do saldo).
    Nunca `0`: `_validate_amount` recusa movimento de valor zero, então esse conjunto é vazio por
    construção e aceitá-lo seria oferecer um filtro que nunca soma nada.

    ⚠️ **[Onda 2b-ii] `exclude_sources` existe para que o principal derivado NÃO seja uma segunda
    fórmula.** O principal de uma aplicação é a soma dos movimentos da conta dela **menos os de
    rendimento** (que já são contados por `accrued_yield_cents`). Escrever essa soma noutro lugar
    duplicaria o piso `posted_at > opening_date` e o `status <> 'ignored'`, e o dia em que um dos
    dois fosse corrigido só de um lado o principal passaria a divergir do saldo por um motivo que
    ninguém acharia. Default vazio: todo chamador anterior a esta onda segue idêntico.

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
    if since is not None:
        stmt = stmt.where(BankTransaction.posted_at > since)
    if sign is not None:
        if sign > 0:
            stmt = stmt.where(BankTransaction.amount_cents > 0)
        else:
            stmt = stmt.where(BankTransaction.amount_cents < 0)
    if exclude_sources:
        stmt = stmt.where(BankTransaction.source.notin_(exclude_sources))
    return {account_id: int(total or 0) for account_id, total in db.execute(stmt).all()}


def _movements_sum(db: Session, *, account: BankAccount, until: date | None = None) -> int:
    """Σ dos movimentos de UMA conta. Delega para `_movements_sums` — ver a fórmula lá.

    Recebe a `BankAccount` já carregada (e não o id) porque a soma precisa do `opening_date` dela;
    a assinatura é privada e a 8.2 explicitamente autorizou mudá-la para evitar a releitura.
    """
    return _movements_sums(db, accounts=[account], until=until).get(account.id, 0)


def movement_sums(
    db: Session,
    *,
    accounts: Sequence[BankAccount],
    until: date | None = None,
    exclude_sources: frozenset[str] = frozenset(),
) -> dict[str, int]:
    """A porta PÚBLICA da soma de movimentos — `{bank_account_id: centavos}`.

    Fina de propósito: delega para `_movements_sums`, que continua sendo a **única** implementação
    da fórmula. Ela existe porque `investments` precisa da soma com `exclude_sources` (Onda 2b-ii) e
    importar um símbolo `_` de outro módulo é o tipo de acesso que ninguém encontra depois — e que o
    `dedup-checker` não consegue julgar.

    `until=None` significa **hoje**, como em `derived_balance` (Story 8.10). Conta sem movimento não
    aparece no dicionário; use `.get(id, 0)`.
    """
    return _movements_sums(
        db,
        accounts=accounts,
        until=resolve_until(until, _today(db)),
        exclude_sources=exclude_sources,
    )


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
        db, account=acc, until=resolve_until(until, _today(db))
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
    return _balances_for(db, accounts, until=resolve_until(as_of, _today(db)))


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


@dataclass(frozen=True)
class AgendadoDaConta:
    """O que já tem dia marcado para sair/entrar desta conta e **ainda não saiu/entrou**.

    Os dois valores são **ABSOLUTOS** (nunca negativos): o sinal já foi consumido pela separação
    em dois campos, e devolver `-500_00` num campo chamado `saida` obrigaria cada consumidor a
    lembrar de qual convenção usar. O sinal continua sendo o dado dentro de `bank_transactions`
    (invariante (b) do modelo) — aqui ele virou **estrutura**, que é o que a tela precisa.
    """

    saida_cents: int
    entrada_cents: int


def agendado_sums(
    db: Session, *, accounts: Sequence[BankAccount], today: date | None = None
) -> dict[str, AgendadoDaConta]:
    """Σ dos movimentos **FUTUROS** (`posted_at > hoje`) de cada conta, separada por sinal.

    É a origem do terceiro número da tela "Contas & Saldos" — *"Agendado para sair"* (Story 8.14
    AC12/AC13) — e, a partir da Story 8.15, do irmão *"Agendado para entrar"*.

    ⚠️ **NÃO é uma segunda fórmula de soma.** Reusa `_movements_sums`, a única implementação do
    repositório, com o **recorte de data invertido** (`since=hoje` em vez de `until=hoje`). Por
    tabela, isso significa que o piso da conta (`posted_at > opening_date`) e o
    `status <> 'ignored'` valem aqui exatamente como valem no saldo, sem que ninguém precise
    lembrar de repeti-los. Escrever a soma noutro lugar é o que a Regra 4 do `CLAUDE.md` proíbe.

    ⚠️ **É o COMPLEMENTO EXATO do saldo corrente, e essa é a propriedade que importa.** Depois da
    Story 8.10, `derived_balance(until=None)` soma `posted_at <= hoje`; esta função soma
    `posted_at > hoje`. Juntas elas cobrem o histórico inteiro **uma vez só** — nem um movimento
    fica de fora dos dois, nem um entra nos dois. É por isso que o dono pode ler os números lado a
    lado sem ninguém explicar como somá-los.

    ⚠️ **Duas queries, CONSTANTES — não N+1.** Uma para as saídas, outra para as entradas: os dois
    recortes são exclusivos e um `SUM(CASE ...)` único devolveria uma linha com duas colunas ao
    preço de duplicar o `WHERE` dentro do `_movements_sums`, que é justamente o que se está
    evitando. Duas agregações para a lista inteira de contas continuam sendo O(1) em número de
    contas, que é a razão de `derived_balances_as_of` existir.

    Conta sem movimento futuro vem com `(0, 0)` — nunca ausente do dicionário; o laço é sobre
    `accounts`, não sobre o resultado da query (o mesmo erro clássico que `_balances_for` evita).
    """
    corte = _today(db) if today is None else today
    saidas = _movements_sums(db, accounts=accounts, since=corte, sign=-1)
    entradas = _movements_sums(db, accounts=accounts, since=corte, sign=1)
    return {
        a.id: AgendadoDaConta(
            saida_cents=abs(saidas.get(a.id, 0)),
            entrada_cents=entradas.get(a.id, 0),
        )
        for a in accounts
    }


def origem_do_saldo_derivado(account: BankAccount) -> str:
    """A procedência do saldo derivado de UMA conta — **o único lugar que decide isso**.

    [Achado do `dedup-checker` no gate da Story 8.21.] A regra estava escrita duas vezes no
    `router.py`, uma por rota que expõe saldo derivado (`BankAccountOut` e `BankBalanceOut`). São
    a **mesma conta** vista por duas portas: se as cópias divergissem, `GET /bank/accounts` diria
    `banco` e `GET /bank/accounts/{id}/balance` diria `indisponivel` para a mesma linha, e a falha
    apareceria longe de quem pudesse relacionar as duas decisões.

    É exatamente a classe que este repo já pagou uma vez: `core/whatsapp/__init__.py::_resolve`
    foi feito **derivar** de `capabilities.for_profile` em vez de repetir a comparação, pelo mesmo
    motivo (`CLAUDE.md`, WhatsApp item 12). Uma superfície nova nasce chamando esta função; não
    copiando o ternário.

    **`indisponivel` quando o dono não declarou o saldo de abertura** (Story 8.21): o saldo
    derivado dessa conta parte de um `0` que é placeholder, não afirmação. O NÚMERO continua
    existindo e sendo exposto — princípio da Onda 0, *suprimir a afirmação, nunca o número* —;
    quem diz "não sei" é a procedência.
    """
    return ORIGEM_BANCO if account.opening_balance_is_known else ORIGEM_INDISPONIVEL


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
    opening_date = _validate_opening_date(data.opening_date, _today(db))

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
        # Story 8.21 — quando o dono diz que NÃO SABE, o valor é IGNORADO e gravado como `0`.
        # Aceitar um número junto de "não sei" guardaria duas afirmações contraditórias na mesma
        # linha, e a segunda venceria em silêncio na primeira leitura.
        opening_balance_cents=(
            data.opening_balance_cents if data.opening_balance_is_known else 0
        ),
        opening_balance_is_known=data.opening_balance_is_known,
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
        nova_abertura = _validate_opening_date(data.opening_date, _today(db))
        _validate_opening_date_move(db, account=acc, nova=nova_abertura)
        _validate_opening_date_recuo(
            account=acc, nova=nova_abertura, novo_saldo=data.opening_balance_cents
        )

    # Story 8.21 — a quarta guarda, e ela também compara contra o estado ATUAL da conta, então
    # entra ANTES de qualquer escrita, junto das três de data.
    _validate_saldo_conhecido(
        account=acc,
        novo_conhecido=data.opening_balance_is_known,
        novo_saldo=data.opening_balance_cents,
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
        "opening_balance_is_known",
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


def _validate_posted_at(
    posted_at: date, account: BankAccount, hoje: date, *, source: str = SOURCE_MANUAL
) -> date:
    """As duas guardas de data do movimento — e **o teto é cortado por `source`** (Story 8.14 AC4).

    1. **`posted_at > opening_date`** — o piso, delegado a `validate_posted_at_floor`. Vale para
       **toda** origem, sem exceção, e é a metade que não muda nunca.
    2. **Não futura — só para `SOURCES_EXTERNA`** (`manual`, `ofx`, `csv`). Ali data futura é erro
       de digitação (ano errado é o caso comum) e um movimento no futuro entraria no histórico sem
       aparecer no saldo de hoje, o que vira divergência inexplicável na conferência da 8.5.

    ⚠️ **O teto NÃO se aplica a `SOURCES_SISTEMA`** (design Onda 2 §4.2.0, normativo): *"o e1p pode
    afirmar o futuro do que ele mesmo agendou; não pode afirmar o futuro do que outro atestou"*. Um
    OFX **descreve** o que já aconteceu; um pagamento agendado no app do banco é fato que o e1p
    conhece em primeira mão, porque foi ele quem o registrou. A justificativa antiga desta guarda
    (*"extrato bancário é fato passado"*) descrevia **transcrição** — e continua verdadeira para o
    que é transcrito. Ela nunca descreveu origem de sistema.

    ⚠️ **O corte é por `source`, e por `source` APENAS.** Nada de booleano `permite_futuro`
    decidido pelo chamador: *"é o parâmetro que alguém passa `True` no caminho manual, um dia, por
    conveniência — e nenhum gate de AST o pega, porque não há import envolvido"* (ratificação
    §C-6.2). O eixo já existe e é `source`; **um eixo, uma pergunta**.

    ⚠️ **`source` desconhecido é 422, não "passa".** A partição é escrita nas DUAS metades
    (`in SOURCES_SISTEMA` … `not in SOURCES_EXTERNA` → 422), e nunca como a negação de uma só. Um
    `if source not in SOURCES_SISTEMA` sozinho faria valor novo herdar o teto sem ninguém decidir;
    um `if source in SOURCES_EXTERNA` sozinho o faria herdar a **isenção** — que é o lado caro. O
    valor novo tem de entrar por um dos dois conjuntos, e é isso que esta forma obriga.

    ⚠️ **Esta função continua sendo chamada apenas pela porta MANUAL** (`create_transaction`,
    `update_transaction`), e `sync_origin_movement` continua chamando só o piso. O corte por
    `source` aqui **não é redundante**: ele torna a regra da §4.2.0 escrita, testável e
    localizável em um lugar só, em vez de emergente de *qual função alguém escolheu chamar* —
    que é uma regra que ninguém consegue citar e que o próximo caminho de escrita não herda.
    """
    validate_posted_at_floor(posted_at, account)
    if source in SOURCES_SISTEMA:
        # O e1p originou o fato — ele pode afirmar o futuro do que ele mesmo agendou.
        return posted_at
    if source not in SOURCES_EXTERNA:
        raise BankError(
            f"Origem de movimento inválida: '{source}'. Use um de: "
            f"{', '.join(SOURCES_EXTERNA + SOURCES_SISTEMA)}.",
            422,
        )
    if posted_at > hoje:
        raise BankError(
            "A data do movimento não pode ser futura: o extrato registra o que já aconteceu.",
            422,
        )
    return posted_at


def _recusa_se_origem_do_sistema(tx: BankTransaction, *, gesto: str) -> None:
    """**A Regra da Origem (d), aplicada.** Movimento de sistema não é editado nem ignorado aqui.

    > *"Um movimento de origem do sistema **não é editável nem ignorável** pela tela de movimentos —
    > quem quer mudá-lo mexe no lançamento de origem. A única exceção é `user_description`, que é
    > rótulo, não fato."* (design Onda 2 §2, epic §4.8(d))

    ⚠️ **DESVIO DOCUMENTADO — a premissa da Story 8.18 AC9 era falsa.** O AC9 diz que as pernas da
    transferência *"herdam a guarda que a Story 8.9 implementa"*. Ao implementar a 8.18 verificou-se
    que a 8.9 **escreveu a regra (na docstring de `bank/origin.py`) e não a implementou**: nem
    `update_transaction` nem `ignore_transaction` olhavam para `tx.source`, e o comentário em
    `update_transaction` já afirmava que a edição *"é impedida antes, pela Regra da Origem (d)"* —
    afirmação que não tinha código por trás. Seguindo o repo e documentando (a lição do `CLAUDE.md`
    §6.1: *"quando uma instrução se apoiar em premissa que você verificar ser falsa, siga o repo e
    documente"*), a guarda entra **aqui**, uma vez, para todo `SOURCES_SISTEMA` — nunca uma por
    origem.

    **Escrita contra o CONJUNTO, jamais contra `'transfer'`** (regra normativa da 8.9 AC3): fosse
    contra o valor solto, `payable` e `charge` continuariam editáveis e a regra teria exceções que
    ninguém decidiu. Acrescentar uma origem de sistema nova continua sendo uma entrada numa tupla.

    **Por que ignorar uma perna é pior do que parece:** `ignore` tira o movimento do saldo derivado.
    Numa transferência, ignorar **uma** das duas pernas quebra a simetria — o dinheiro sai de uma
    conta e não entra em lugar nenhum —, e o resultado é uma divergência na conferência com a
    aparência exata de um lançamento faltante. O produto mandaria o dono caçar um furo que ele mesmo
    criou com um clique, e divergência inventada é pior que divergência escondida.

    A saída é dita na mensagem: quem quer desfazer mexe no **lançamento** (estornar a conta a pagar,
    desfazer a baixa, apagar a transferência), e o movimento acompanha — Regra da Origem (c).
    """
    if tx.source not in SOURCES_SISTEMA:
        return
    raise BankError(
        f"Este movimento foi criado pelo próprio e1p a partir de um lançamento seu "
        f"(origem: {tx.source}) e por isso não pode ser {gesto} por aqui — quem manda nele é o "
        "lançamento que o gerou. Desfaça ou corrija o lançamento e o movimento acompanha. "
        "Você pode "
        "editar a descrição dele, que é rótulo, não fato.",
        422,
    )


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
    `limit` é grampeado em [1, 500] em vez de rejeitado, mesmo contrato da listagem do módulo de
    contas a pagar (ver a nota do topo sobre por que este arquivo não nomeia aquele módulo).
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

    ⚠️ **A guarda de contagem dupla (Story 8.17 AC5) mora aqui, e SÓ aqui.** Ela roda depois de
    todas as validações e **antes de qualquer escrita**, como as demais. Ela **não** foi estendida a
    `update_transaction` de propósito (ratificação §C-5.4): editar valor/data de um movimento manual
    já existente é **correção**, não criação, e pôr o 409 ali transformaria uma correção legítima
    numa parede.
    """
    acc = get_account(db, bank_account_id)
    if acc.archived_at is not None:
        raise BankError(
            "Esta conta está arquivada e não recebe lançamentos novos. Se ela voltou a ser usada, "
            "cadastre-a de novo com o saldo de abertura do dia.",
            422,
        )
    amount_cents = _validate_amount(data.amount_cents)
    # `SOURCE_MANUAL` explícito, e não o default: é a mesma constante que a linha vai gravar em
    # `source` logo abaixo, e escrevê-la aqui deixa visível no diff que esta porta é a EXTERNA —
    # a que continua recusando data futura depois da Story 8.14.
    posted_at = _validate_posted_at(data.posted_at, acc, _today(db), source=SOURCE_MANUAL)

    # ── A guarda de contagem dupla (AC5) ──────────────────────────────────────────────────────
    #
    # **Só SAÍDA, e só quando o usuário ainda não insistiu.** Movimento POSITIVO nunca dispara: um
    # recebimento não pode ser a mesma linha de uma obrigação a pagar, e disparar ali seria ruído
    # num formulário que já é a porta primária.
    #
    # ⚠️ **Saída manual continua LEGÍTIMA** (AC4): tarifa, IOF e taxa de TED são saídas que não têm
    # — e nunca terão — obrigação de negócio correspondente (*"criar uma conta a pagar de R$ 2,90
    # para uma tarifa é a ERP-ificação que o produto recusa"*). Por isso a guarda é **por
    # candidato encontrado**, e não uma proibição de saída manual: sem candidato, 201 e silêncio.
    #
    # `confirmar_avulso` é confirmação de INTENÇÃO e **não é persistida** — não há coluna e não
    # deve haver: ela descreve o que o usuário respondeu a uma pergunta, não um fato sobre o
    # movimento. Ver `BankTransactionCreate.confirmar_avulso`.
    if amount_cents < 0 and not data.confirmar_avulso:
        candidato = _probe_duplicata(db, amount_cents=amount_cents, posted_at=posted_at)
        if candidato is not None:
            raise DuplicataDePagamento(candidato)

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

    # ── A Regra da Origem (d) — a exceção é `user_description`, e SÓ ela ─────────────────────
    #
    # A checagem é por CAMPO, e não pelo movimento inteiro, porque a regra tem uma exceção nomeada:
    # o rótulo do dono sobrevive a qualquer origem (*"é rótulo, não fato"*). Recusar o PATCH inteiro
    # tiraria dele a única edição que ele legitimamente tem sobre uma perna de transferência.
    if data.posted_at is not None or data.amount_cents is not None:
        _recusa_se_origem_do_sistema(tx, gesto="editado")

    if data.posted_at is not None:
        # Revalida contra a conta ATUAL do movimento (a conta não muda: não há rota para movê-lo)
        # e contra o **`source` da própria linha** (Story 8.14 AC4) — não contra um valor fixo.
        # Editar a data de um movimento de origem de sistema por esta rota é impedido antes, pela
        # Regra da Origem (d): quem quer mudá-lo mexe no lançamento. Passar `tx.source` mantém as
        # duas guardas coerentes se essa porta um dia se abrir, em vez de deixar um `manual`
        # hard-coded decidindo sobre uma linha que não é manual.
        tx.posted_at = _validate_posted_at(
            data.posted_at, get_account(db, tx.bank_account_id), _today(db), source=tx.source
        )
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
    # Regra da Origem (d): movimento de sistema não é ignorável. A guarda vem ANTES do no-op de
    # idempotência de propósito — uma perna nunca chega a `ignored` por este caminho, então o
    # `return tx` antecipado só poderia mascarar um estado que outro caminho tivesse criado.
    _recusa_se_origem_do_sistema(tx, gesto="ignorado")
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


def _validate_reference_date(reference_date: date, account: BankAccount, hoje: date) -> date:
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
    **aceito** — e o que essa aceitação significa precisa ficar escrito com o sinal certo, porque a
    versão anterior desta docstring afirmava o **oposto** da própria premissa dela e foi por isso
    que o defeito da Story 8.20 sobreviveu a 36 testes:

    - **premissa (correta):** `opening_balance_cents` é, por definição, o saldo ao fim do dia de
      abertura, então `derived_balance(until=opening_date)` devolve **exatamente ele** — sempre,
      para toda conta (`_movements_sums` só soma `posted_at > opening_date`).
    - **conclusão (o oposto do que estava aqui):** justamente por isso a comparação resultante é
      **tautológica**. Ela não tem poder de detectar lançamento faltante nenhum: coincidindo as duas
      declarações, a divergência é zero **por construção**; discordando, ela inventa um furo que não
      existe. Por isso o bloco 1 da conferência a trata como **NÃO AVALIÁVEL** — ver
      `app/modules/bank/reconciliation.py::_conferir_conta`.
    - **e mesmo assim a data continua aceita**, sem 422: o saldo da conta no dia em que ela abriu é
      uma **declaração legítima**, e recusá-la apagaria uma afirmação verdadeira do dono (o inverso
      exato do princípio da Onda 0, *"suprimir a afirmação, nunca o número"*). O degenerado é a
      **comparação**, não a declaração — que segue contando como conferência recente no bloco 4.

    Para o **movimento** a assimetria permanece por outro motivo, e ele não mudou: o mesmo dia
    significaria contar duas vezes um dinheiro que já está dentro do saldo de abertura — isso
    **corrompe um número**, e corromper número é motivo para 422. Concordar por construção não é.
    Daí um `>` lá e um `>=` aqui.

    **Lição de método (não reintroduza a frase antiga):** *"o valor é bem definido"* e *"o valor
    é informativo"* são afirmações diferentes, e a primeira não implica a segunda. Esta função
    responde *"posso gravar?"*; quem responde *"isto serve para conferir?"* é o
    `reconciliation.py`.
    """
    if reference_date > hoje:
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
    reference_date = _validate_reference_date(data.reference_date, acc, _today(db))

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
