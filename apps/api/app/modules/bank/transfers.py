"""**Transferência entre contas próprias** — um lançamento, duas pernas (Story 8.18, Onda 2 §8).

> **A Regra da NEUTRALIDADE** (design Onda 2 §8, epic §4.2, normativa):
> transferência entre contas do próprio dono é **exclusivamente** evento do **plano 3**. Ela
> **nunca** cria, altera ou baixa `Charge`, `Payable` ou `Transaction`, e por isso **não aparece**
> na DRE, na Lucratividade nem na Projeção como entrada ou saída. Ela **redistribui** saldo entre
> contas; não gera resultado.

**O que este módulo faz, e nada além:** grava o lançamento em `bank_transfers` e pede a
`bank/origin.py::sync_origin_movement` — **duas vezes, na mesma transação** — as duas pernas:

| Perna | Conta | `amount_cents` | `origin_id` | `transfer_id` |
|---|---|---|---|---|
| saída | `from_account_id` | **−** valor | `f"{transfer.id}:out"` | `transfer.id` |
| entrada | `to_account_id` | **+** valor | `f"{transfer.id}:in"` | `transfer.id` |

⚠️ **`origin_id` é a CHAVE DE ORIGEM, não "o id do lançamento"** (ratificação §C-3.3). Para origem
de **perna única** (`payable`, `charge`, `yield`, `payout`) ela **é** o id; para origem de
**múltiplas pernas** é `f"{id}:{perna}"`. A forma rejeitada nominalmente pelo design é *"duas linhas
com o mesmo `origin_id`"*: ela colidiria com o índice único parcial `uq_bank_transactions_origin`
e destruiria a idempotência **na origem onde ela mais importa** — um retry de transferência moveria
o dinheiro duas vezes. O pareamento entre as pernas é trabalho do `transfer_id`, coluna que já
existe desde a 0059 e que é **kwarg** de `sync_origin_movement` desde a 8.9 AC5.

⚠️ **ZERO acoplamento com `investments`** (AC5). `kind ∈ TRANSFER_KINDS` é vocabulário do módulo
`bank`; transferir para uma `bank_account` com `kind='investment'` **já funciona** desde a Onda 1 (o
dinheiro se move e os dois saldos derivados batem). A faceta de produto da aplicação
(rentabilidade, `index_rate_label`, principal derivado, `register_yield`) é **Onda 2b**, e é lá
que mora o único backfill do épico. O gate `test_bank_transfers_nao_importa_investments` reprova
quem antecipar isso.

⚠️ **Direção de import:** este arquivo importa `bank.service` e `bank.origin` e mais nada de
`app.modules`. `payables`/`receivables`/`wallet`/`investments` são **proibidos** aqui pelos gates de
`tests/test_money_planes.py`.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.bank.models import (
    OPERATION_NATURE_TRANSFERENCIA,
    SOURCE_TRANSFER,
    TRANSFER_KINDS,
    BankAccount,
    BankTransfer,
)
from app.modules.bank.origin import sync_origin_movement
from app.modules.bank.schemas import BankTransferCreate
from app.modules.bank.service import (
    BankError,
    _today,  # a MESMA âncora de "hoje" do módulo (fuso do tenant) — nunca um segundo relógio
    get_account,
    validate_posted_at_floor,
)

# ── As duas pernas: o vocabulário FECHADO do sufixo da chave de origem ────────────────────────
#
# Escritos como constantes, e num lugar só, porque são **parte do contrato de dados**: a chave
# `f"{transfer.id}:out"` está gravada em `bank_transactions.origin_id` de produção, e trocar o
# literal aqui órfãnaria toda perna já existente sem nenhum erro na hora. O vocabulário é fechado
# (§C-3.3: *"`perna` num vocabulário fechado por `source`"*) — acrescentar uma terceira perna a uma
# transferência não é edição de string, é decisão de design.
PERNA_SAIDA = "out"
PERNA_ENTRADA = "in"


def origin_id_da_perna(transfer_id: str, perna: str) -> str:
    """`f"{transfer_id}:{perna}"` — a CHAVE DE ORIGEM de uma perna. Uma implementação, dois usos.

    Consumida pela criação (para escrever) e pelo `delete_transfer` (para reencontrar). Duas cópias
    da mesma concatenação divergiriam no dia em que uma fosse corrigida — e o sintoma seria um
    `DELETE` que apaga o lançamento e deixa as duas pernas órfãs no razão, silenciosamente.

    A largura resultante (36 + 1 + 3 = 40) cabe em `VARCHAR(64)` e **não é verificada aqui**: quem
    verifica é `test_origin_id_cabe_na_coluna` (Story 8.9 Task 7), que varre **todas** as formas de
    chave do repositório. Uma segunda verificação de largura neste arquivo seria a segunda fonte de
    verdade que a 8.18 foi instruída a não criar.
    """
    return f"{transfer_id}:{perna}"


# ── Guardas — TODAS antes de qualquer escrita ────────────────────────────────────────────────


def _validate_kind(kind: str) -> str:
    if kind not in TRANSFER_KINDS:
        raise BankError(
            f"Tipo de transferência inválido: '{kind}'. Use um de: {', '.join(TRANSFER_KINDS)}.",
            422,
        )
    return kind


def _validate_amount(amount_cents: int) -> int:
    """O valor da TRANSFERÊNCIA é sempre positivo — o sinal vive nas pernas.

    Não é o `_validate_amount` do movimento (que recusa só o zero, porque lá o sinal **é** o dado):
    aqui o negativo também é recusado, e a mensagem diz por quê. Um valor negativo neste campo seria
    a terceira convenção de sinal do repositório, e a pergunta *"negativo significa 'saiu de A' ou
    'a transferência foi invertida'?"* não teria resposta escrita em lugar nenhum.
    """
    if amount_cents <= 0:
        raise BankError(
            "O valor da transferência precisa ser maior que zero. Quem carrega o sinal são os dois "
            "movimentos que ela gera — saída negativa na conta de origem, entrada positiva na de "
            "destino. Para inverter o sentido, troque as contas.",
            422,
        )
    return amount_cents


def _validate_contas_distintas(from_account_id: str, to_account_id: str) -> None:
    if from_account_id == to_account_id:
        raise BankError(
            "A conta de origem e a de destino são a mesma. Transferir uma conta para ela mesma não "
            "move dinheiro nenhum — geraria duas linhas que se cancelam e sujariam o extrato.",
            422,
        )


def _conta_ativa(db: Session, account_id: str, *, papel: str) -> BankAccount:
    """A conta existe (404 fail-closed pela RLS) e **não está arquivada** (422).

    Mesma mensagem de `create_transaction`: lançar movimento NOVO numa conta encerrada é quase
    sempre a conta errada selecionada. `papel` é "origem"/"destino" e entra na mensagem — numa
    operação com **duas** contas, dizer só *"a conta está arquivada"* obriga o dono a adivinhar
    qual das duas.
    """
    acc = get_account(db, account_id)
    if acc.archived_at is not None:
        raise BankError(
            f"A conta de {papel} ({acc.name}) está arquivada e não recebe lançamentos novos. "
            "Se ela "
            "voltou a ser usada, cadastre-a de novo com o saldo de abertura do dia.",
            422,
        )
    return acc


def _validate_piso(posted_at: date, acc: BankAccount, *, papel: str) -> None:
    """`posted_at > opening_date` **de cada uma das duas contas**, nomeando QUAL falhou.

    ⚠️ **É o ponto mais fácil de esquecer desta story**, e o modo de falha é o pior possível: cada
    conta tem a **sua** `opening_date`, e uma perna aceita com a outra recusada deixaria a
    transferência pela metade — o dinheiro sairia de A e não chegaria em B —, que é exatamente o
    estado que a Regra da Origem existe para tornar impossível. Por isso as duas são validadas
    **antes** da primeira chamada ao sincronizador, e não dentro dela.

    A mensagem é a de `service.validate_posted_at_floor` (uma redação, um lugar: ela já explica que
    o saldo de abertura contempla tudo até aquele dia e que lançar antes contaria o mesmo dinheiro
    duas vezes), **prefixada** com o papel e o nome da conta. Reescrevê-la aqui seria a segunda
    cópia de um texto que já existe.
    """
    try:
        validate_posted_at_floor(posted_at, acc)
    except BankError as e:
        raise BankError(f"Conta de {papel} ({acc.name}): {e}", e.status_code) from e


def _validate_nao_futura(posted_at: date, hoje: date) -> date:
    """**422 para data futura — e esta guarda vive AQUI, NUNCA em `_validate_posted_at`.**

    ⚠️ **LEIA ANTES DE "MOVER PARA O LUGAR COMUM"** (achado **A-3** da ratificação §C-3.4, bloqueio
    5 da onda). A guarda genérica de data do módulo `bank` (`service._validate_posted_at`)
    **aceita** `posted_at` futuro para `source ∈ SOURCES_SISTEMA` desde a Story 8.14 — e `transfer`
    **está dentro de `SOURCES_SISTEMA`**. Uma guarda posta lá seria **silenciosamente inócua**:
    teste verde, 422 nunca disparado, data futura entrando no razão. **Guarda inócua é pior que
    guarda ausente**, porque tem teste verde.

    **E a exceção não é arbitrária — ela existe porque não há estado que a sustente.** Baixa de
    `Payable` com data futura vira `scheduled` (8.14 AC2): existe um estado, uma superfície
    ("Agendado para sair"), e um caminho de promoção. Transferência agendada **não tem nada disso**
    — nem estado, nem superfície, nem teste. Aceitá-la aqui seria inventar uma quarta semântica de
    agendamento sem lugar nenhum onde ela apareça (Art. IV).

    **Membro:** `posted_at = hoje + 1` numa transferência → **422, aqui**.
    **Não-membro:** `posted_at = hoje + 1` numa baixa de conta a pagar → **aceito**, vira
    `scheduled`. São a mesma data, os dois em `SOURCES_SISTEMA`, com respostas **opostas** — e é
    essa assimetria que torna impossível pôr a guarda no lugar comum.

    ⚠️ **Onda 2b, ao ligar o rendimento (`source='yield'`): NÃO copie esta forma sem decidir.** Se o
    rendimento puder ser lançado com data futura, ele precisa do estado que a transferência não tem.
    """
    if posted_at > hoje:
        raise BankError(
            "A data da transferência não pode ser futura. O e1p registra a transferência que já "
            "aconteceu — se você agendou a transferência no app do banco, lance-a aqui no dia em "
            "que ela cair.",
            422,
        )
    return posted_at


# ── Leitura ──────────────────────────────────────────────────────────────────────────────────


def get_transfer(db: Session, transfer_id: str) -> BankTransfer:
    """404 fail-closed — cross-tenant cai aqui pela RLS (a linha não existe para quem pergunta)."""
    t = db.get(BankTransfer, transfer_id)
    if t is None:
        raise BankError("Transferência não encontrada", 404)
    return t


def list_transfers(
    db: Session,
    *,
    bank_account_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BankTransfer]:
    """Transferências do tenant, da mais recente para a mais antiga. Paginação OBRIGATÓRIA.

    `bank_account_id` casa **os dois lados** (origem OU destino): a pergunta que o dono faz é *"o
    que passou por esta conta?"*, e um filtro que casasse só a origem esconderia metade do que ele
    procura, sem dizer que está escondendo.

    `start`/`end` são datas de calendário e **inclusivas** nas duas pontas — `posted_at` é `DATE`,
    então não existe aritmética de fuso em lugar nenhum deste caminho.

    A ordenação desempata por `created_at` desc pelo mesmo motivo de `list_transactions`: duas
    transferências no mesmo dia sem desempate sairiam em ordem indefinida, e uma lista que muda de
    ordem entre dois `GET` iguais quebra a paginação em silêncio.

    `limit` é **grampeado** em [1, 500] em vez de rejeitado — mesmo contrato de `list_transactions`.
    """
    limit = max(1, min(limit, 500))
    stmt = select(BankTransfer).order_by(
        BankTransfer.posted_at.desc(), BankTransfer.created_at.desc()
    )
    if bank_account_id:
        stmt = stmt.where(
            (BankTransfer.from_account_id == bank_account_id)
            | (BankTransfer.to_account_id == bank_account_id)
        )
    if start is not None:
        stmt = stmt.where(BankTransfer.posted_at >= start)
    if end is not None:
        stmt = stmt.where(BankTransfer.posted_at <= end)
    return list(db.scalars(stmt.limit(limit).offset(max(0, offset))).all())


# ── Escrita ──────────────────────────────────────────────────────────────────────────────────


def _descricao_da_perna(base: str, *, preposicao: str, outra_conta: str) -> str:
    """O `raw_description` de uma perna: quem está do outro lado, e o que o dono escreveu.

    Nasce nomeando a **outra** conta porque é isso que falta na tela: no extrato da conta A, "saiu
    R$ 1.000" sem dizer para onde é exatamente a linha órfã que o épico existe para eliminar. É um
    snapshot do fato (o nome da conta naquele dia) — `raw_description` é imutável de propósito, e
    renomear a conta depois **não** reescreve a evidência.
    """
    cabeca = f"Transferência {preposicao} {outra_conta}"
    return f"{cabeca} — {base}" if base else cabeca


def create_transfer(
    db: Session, *, tenant_id: str, actor: str, data: BankTransferCreate
) -> BankTransfer:
    """Registra a transferência e as **duas pernas**, num commit só. Devolve o lançamento.

    **Ordem deliberada: TODAS as guardas antes de QUALQUER escrita** (AC7). Uma perna aceita com a
    outra recusada deixaria o dinheiro fora de qualquer conta — o estado que a Regra da Origem
    existe para tornar impossível.

    1. contas distintas (422) — transferir para si não move dinheiro;
    2. valor > 0 (422) — o sinal vive nas pernas;
    3. `kind ∈ TRANSFER_KINDS` (422);
    4. as duas contas existem (404 fail-closed pela RLS) e **não** estão arquivadas (422);
    5. `posted_at > opening_date` **das duas** (422, nomeando qual);
    6. `posted_at` **não futura** (422) — ver `_validate_nao_futura` e o porquê de a guarda viver
       aqui, e não em `service._validate_posted_at`.

    Depois disso, **duas chamadas** a `sync_origin_movement` — o **único** escritor de
    `source ∈ SOURCES_SISTEMA` do repositório. Nenhum segundo caminho de escrita nasce aqui: as
    pernas não são montadas com `BankTransaction(...)` nem corrigidas por `setattr` depois. Em
    particular, `transfer_id` entra pelo **kwarg** (8.9 AC5) — gravá-lo num segundo passo seria um
    segundo escritor da mesma linha, que é o que torna a Regra da Origem inauditável.

    `db.flush()` **antes** do `audit.record`: o `id` tem default Python-side, e sem o flush a trilha
    nasceria com `target=''` — o defeito MNT-001, que 17 call sites do projeto têm e que o módulo
    `bank` é o único a evitar. **Não replique o erro aqui.**

    **Idempotência:** duas transferências idênticas no mesmo dia são **duas** transferências (é
    legítimo: dois Pix de R$ 500 para a mesma poupança no mesmo dia acontecem). O que o índice único
    de origem garante é outra coisa — que **cada perna** exista uma vez só, porque cada uma tem a
    sua chave `f"{id}:out"`/`f"{id}:in"` derivada de um `id` novo.
    """
    _validate_contas_distintas(data.from_account_id, data.to_account_id)
    amount_cents = _validate_amount(data.amount_cents)
    kind = _validate_kind(data.kind)

    origem = _conta_ativa(db, data.from_account_id, papel="origem")
    destino = _conta_ativa(db, data.to_account_id, papel="destino")

    posted_at = _validate_nao_futura(data.posted_at, _today(db))
    _validate_piso(posted_at, origem, papel="origem")
    _validate_piso(posted_at, destino, papel="destino")

    transfer = BankTransfer(
        tenant_id=tenant_id,
        from_account_id=origem.id,
        to_account_id=destino.id,
        amount_cents=amount_cents,
        posted_at=posted_at,
        kind=kind,
        description=data.description,
    )
    db.add(transfer)
    # O `id` precisa existir ANTES das duas chamadas: ele é a raiz das duas chaves de origem.
    db.flush()

    comum = {
        "tenant_id": tenant_id,
        "actor": actor,
        "source": SOURCE_TRANSFER,
        "posted_at": posted_at,
        # RÓTULO, nunca fato de dinheiro (Story 8.17 AC9): não entra em nenhuma fórmula de saldo.
        # As duas pernas o carregam para que a tela de movimentos saiba dizer o que elas são sem
        # precisar cruzar `transfer_id` com outra tabela.
        "operation_nature": OPERATION_NATURE_TRANSFERENCIA,
        # O que **pareia** as duas pernas. Kwarg desde a 8.9 AC5 — nunca um UPDATE posterior.
        "transfer_id": transfer.id,
    }
    sync_origin_movement(
        db,
        origin_id=origin_id_da_perna(transfer.id, PERNA_SAIDA),
        bank_account_id=origem.id,
        # NEGATIVO: saiu da conta de origem.
        amount_cents=-amount_cents,
        description=_descricao_da_perna(
            data.description, preposicao="para", outra_conta=destino.name
        ),
        **comum,
    )
    sync_origin_movement(
        db,
        origin_id=origin_id_da_perna(transfer.id, PERNA_ENTRADA),
        bank_account_id=destino.id,
        # POSITIVO: entrou na conta de destino.
        amount_cents=amount_cents,
        description=_descricao_da_perna(
            data.description, preposicao="de", outra_conta=origem.name
        ),
        **comum,
    )

    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transfer.create", target=transfer.id
    )
    db.commit()
    db.refresh(transfer)
    return transfer


def delete_transfer(db: Session, *, transfer_id: str, tenant_id: str, actor: str) -> None:
    """Desfaz a transferência: o lançamento **e as duas pernas** somem juntos, num commit só.

    **Por que existe** (ratificação §C-3.5, por derivação da §4.5): o design **rejeita
    nominalmente** a contrapartida (*"o extrato do dono tem uma linha; criar duas inventa um crédito
    que nunca existiu"*). Sem este `DELETE`, a única correção de uma transferência errada seria
    justamente a contrapartida rejeitada. Não é escopo novo; é a §4.5 aplicada onde ela já valia.

    **Por que não existe "corrigir"**: apagar e recriar aqui é barato — duas linhas puramente
    sintéticas, **nenhum evento de Agenda envolvido** —, ao contrário de `payables`/`charges`, onde
    a rota de correção existe justamente porque estornar faz a Agenda piscar.

    **A guarda da linha puramente sintética é REUSADA, não recopiada.** As duas pernas saem por
    `sync_origin_movement(..., bank_account_id=None)`, que é a forma contratual de dizer *"esta
    origem não está mais liquidada"*: linha `fitid IS NULL AND import_batch_id IS NULL` é
    **apagada**:
    linha já enriquecida por importação tem a **origem desligada** (`origin_id=NULL`,
    `source='ofx'`, `status='unmatched'`) e permanece — degradação honesta, porque o dinheiro saiu
    mesmo; o sistema é que não sabe mais por quê. Reimplementar essa decisão aqui seria a segunda
    cópia de uma regra que já tem dono, teste e docstring.

    **Idempotente por perna:** pedir a remoção de uma perna que não existe é sucesso, não 404 (é o
    contrato do sincronizador). Isso importa porque uma transferência cuja perna já foi desligada
    pela importação continua sendo apagável.

    A trilha não se perde: ela mora em `audit_entries` (`bank.transfer.delete` + o
    `bank.origin.delete`/`bank.origin.detach` de cada perna), que é a finalidade dela.
    """
    transfer = get_transfer(db, transfer_id)

    for perna in (PERNA_SAIDA, PERNA_ENTRADA):
        sync_origin_movement(
            db,
            tenant_id=tenant_id,
            actor=actor,
            source=SOURCE_TRANSFER,
            origin_id=origin_id_da_perna(transfer.id, perna),
            # `None` = "a origem deixou de estar liquidada" → apaga (ou desliga) o movimento.
            bank_account_id=None,
            posted_at=None,
            amount_cents=None,
            description="",
        )

    db.delete(transfer)
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.transfer.delete", target=transfer.id
    )
    db.commit()
