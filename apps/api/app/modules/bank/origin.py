"""A **Regra da Origem** — o sincronizador único do movimento bancário (Story 8.9, Onda 2 §3.5).

> **REGRA DA ORIGEM** (design `controle-bancario-onda2-design.md` §2, normativa):
> **(a)** todo evento do e1p que significa *"dinheiro entrou ou saiu de uma conta real do dono"*
> gera **exatamente um** `bank_transaction`, **na mesma transação** do evento, e esse movimento
> **nasce conciliado** (`status='matched'`) — o e1p originou os dois lados, não há julgamento a
> fazer;
> **(b)** o movimento carrega `origin_id` apontando para o lançamento que o gerou, e a relação é
> **1:1**, garantida por índice único;
> **(c)** o ciclo de vida do movimento é **espelho** do lançamento: corrigir a conta ou a data
> **move** o movimento; estornar o lançamento **apaga** o movimento. Nunca duplica, nunca deixa
> órfão;
> **(d)** um movimento de origem do sistema **não é editável nem ignorável** pela tela de
> movimentos — quem quer mudá-lo mexe no lançamento de origem. A única exceção é
> `user_description`, que é rótulo, não fato;
> **(e)** lançamento manual e importação existem para o **resíduo** — o que nenhum evento do
> sistema conhece. Porta manual para algo que já tem porta própria é digitação dupla, e digitação
> dupla é o defeito que este produto promete não impor.

E a **regra irmã**, que preserva a Regra 5 do `CLAUDE.md`:

> **A Regra da Origem alimenta `saldo_sistema`, NUNCA `saldo_banco`.** O checkpoint continua sendo
> a única fonte do lado externo e continua não sendo corrigido por nada. A divergência diminuir
> porque o sistema passou a saber mais é o objetivo; diminuir porque um lado foi ajustado contra o
> outro continua proibido.

---

⚠️ **ESTA STORY ENTREGA O CONTRATO, NÃO O COMPORTAMENTO.** Ao final da 8.9 este módulo existe, é
testado e **não tem um único chamador em produção** — nem `apply_paid`, nem `reverse_payable`, nem
nada. Isso é deliberado (epic §6, critério de corte (iii): *"migration e backend de contrato vêm
antes de qualquer chamador"*). Se a sua implementação parecer precisar chamar `sync_origin_movement`
de um fluxo de negócio para "funcionar", **pare**: isso é a Story 8.12.

⚠️ **DIREÇÃO DE IMPORT (gate estrutural `test_bank_nao_importa_payables`):** `payables` e
`receivables` **podem** importar `app.modules.bank` (e vão, a partir da 8.12); `app.modules.bank`
**nunca** importa `payables`/`receivables`. A dependência é **de negócio para banco, jamais a
volta** — sem isso o primeiro atalho de conveniência recria um ciclo. Consequência prática que esta
story trava: o aviso pró-ativo da Story 8.11 e qualquer leitura de `payables` a partir do módulo
`bank` são **proibidos**; quem precisa cruzar os dois lados faz isso do lado do negócio.

⚠️ **PII de terceiro:** `counterparty_name` e `counterparty_document` são parâmetros desta função e
carregam dado de gente que **nunca contratou com a e1p**. A Onda 2 não chama IA em lugar nenhum
(epic §4.4), então o anonimizador não entra aqui — ele volta a ser obrigatório nas Ondas 4 e 5
(Regra de Ouro nº 2).
"""
from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.modules.bank.models import (
    SOURCE_OFX,
    SOURCES_SISTEMA,
    STATUS_MATCHED,
    STATUS_UNMATCHED,
    BankTransaction,
)
from app.modules.bank.service import (
    BankError,
    _validate_amount,
    get_account,
    validate_posted_at_floor,
)


def origin_dedup_hash(source: str, origin_id: str) -> str:
    """`sha256("{source}|{origin_id}")` — a variante de `dedup_hash` da origem de SISTEMA (§3.2).

    ⚠️ **SEM o `bank_account_id`, e a ausência é deliberada, operacional e testável.** Trocar a
    conta de um lançamento é **UPDATE da mesma linha** (a Regra da Origem (c): *move, nunca
    duplica*). Se o hash carregasse a conta, essa troca exigiria **reidratá-lo** — e o que é uma
    correção viraria uma recriação, com uma janela em que a coluna `NOT NULL` não teria valor
    coerente. O teste `test_hash_de_origem_e_estavel_sob_troca_de_conta` fixa isso.

    ⚠️ **Não confunda com `service._manual_dedup_hash`**, que chaveia na conta **e no UUID da
    própria linha** e continua valendo para `SOURCES_EXTERNA`. São duas variantes com contratos
    diferentes, e **não** se "harmoniza" uma com a outra retroativamente: reescrever `dedup_hash` de
    linhas existentes é migration com backfill sob `FORCE RLS`, a armadilha da 0046.

    ⚠️ **E o `dedup_hash` NÃO é a garantia de idempotência desta onda** — quem garante é o índice
    único parcial `uq_bank_transactions_origin (tenant_id, source, origin_id) WHERE origin_id IS NOT
    NULL`, no banco, fail-closed. O hash existe porque a coluna é `NOT NULL` desde a 0059 e porque
    ele é o que o pipeline de importação da Onda 4 vai consultar.

    Mesma primitiva de `core.security.hash_token`, contrato diferente: aquele existe para que um
    SEGREDO não fique em claro no banco (e a evolução natural dele é virar um KDF com sal, o que
    aqui reescreveria a semântica da constraint única em silêncio).
    """
    return hashlib.sha256(f"{source}|{origin_id}".encode()).hexdigest()


def _validate_source(source: str) -> str:
    """`source ∈ SOURCES_SISTEMA`, senão 422. **Esta função não é porta genérica de escrita.**

    Escrito contra o CONJUNTO e nunca contra um valor solto (regra normativa da Story 8.9 AC3):
    acrescentar uma origem de sistema nova é uma entrada numa tupla, e nenhuma regra muda.
    """
    if source not in SOURCES_SISTEMA:
        raise BankError(
            f"`{source}` não é uma origem de sistema. `sync_origin_movement` escreve apenas "
            f"movimentos originados pelo próprio e1p ({', '.join(SOURCES_SISTEMA)}). Movimento "
            "que veio de fora (manual, ofx, csv) entra por `create_transaction` ou pela "
            "importação — nunca por aqui.",
            422,
        )
    return source


def _validate_origin_id(origin_id: str) -> str:
    """A **INVARIANTE DA ORIGEM** no sentido que esta função pode aplicar sozinha.

    `source ∈ SOURCES_SISTEMA` ⟺ `origin_id IS NOT NULL`. Como esta é a única função que escreve
    `SOURCES_SISTEMA`, recusar `origin_id` vazio aqui fecha a metade "⇒" da invariante na origem; a
    metade "⇐" (nenhum movimento externo tem `origin_id`) é garantida por `create_transaction`
    nunca escrever a coluna, e as **duas** direções são testadas por
    `test_origem_do_sistema_sempre_tem_origin_id`.
    """
    if not origin_id:
        raise BankError(
            "Movimento de origem do sistema exige `origin_id` — é ele que amarra o movimento ao "
            "lançamento que o gerou e é sobre ele que vive a garantia de idempotência (índice "
            "único `uq_bank_transactions_origin`).",
            422,
        )
    return origin_id


def _find(db: Session, *, source: str, origin_id: str) -> BankTransaction | None:
    """O movimento desta origem, se existir. **A RLS recorta por tenant** (Regra de Ouro nº 1).

    Nenhum `WHERE tenant_id` à mão, de propósito: o projeto tem a RLS como ÚNICA garantia de
    isolamento e não adiciona filtro redundante, para não criar o padrão "algumas queries filtram,
    outras não" (onde esquecer uma vira vazamento).
    """
    return db.scalars(
        select(BankTransaction).where(
            BankTransaction.source == source,
            BankTransaction.origin_id == origin_id,
        )
    ).first()


def _desliga_ou_apaga(
    db: Session, *, tx: BankTransaction, tenant_id: str, actor: str
) -> None:
    """O lançamento deixou de estar liquidado. **A guarda da linha PURAMENTE SINTÉTICA** (§4.5).

    **Ramo 1 — linha puramente sintética** (`fitid IS NULL` **e** `import_batch_id IS NULL`):
    **DELETE**. Um movimento bancário é a afirmação *"este dinheiro saiu desta conta"*; estornado o
    lançamento, o sistema **não afirma mais isso**. Marcá-la `ignored` seria manter uma afirmação
    falsa com uma etiqueta — o inverso exato do princípio da Onda 0 (*"suprima a afirmação, nunca o
    número"*; aqui não há número a preservar, só a afirmação). Criar uma contrapartida `+valor`
    seria pior ainda: **fabricaria um crédito que nunca existiu no banco**, e a importação da Onda 4
    encontraria dois órfãos irreconciliáveis. A trilha não se perde — ela mora em `audit_entries`,
    que é a finalidade dela. E apagar é o que permite **repagar** sem colidir com
    `uq_bank_transactions_origin`.

    **Ramo 2 — linha JÁ ENRIQUECIDA pela importação** (`fitid` ou `import_batch_id` preenchidos):
    **não apaga**. Desliga a origem — `origin_id = NULL`, `source = 'ofx'`, `status = 'unmatched'` —
    e a linha volta a ser um movimento órfão do extrato, o que é **verdade**: o dinheiro saiu mesmo;
    o sistema é que não sabe mais por quê. **Degradação honesta.**

    ⚠️ **O ramo 2 é INALCANÇÁVEL hoje** — não existe importação, então nenhuma linha tem `fitid` ou
    `import_batch_id`. Ele entra **agora**, com teste que monta a linha enriquecida à mão, porque
    escrevê-lo na Onda 4 significaria descobrir a regra **depois de já ter perdido dado bancário
    real**. Este é o tipo de código cuja ausência não dá erro: dá um `DELETE` bem-sucedido em cima
    de uma evidência que não voltava.

    Os três campos do ramo 2 são **exatamente** os que o design §4.5 enumera. `transfer_id`
    sobrevive de propósito: ele é metadado do que a linha foi, e reescrevê-lo aqui seria decisão
    nova, não implementação desta.
    """
    puramente_sintetica = tx.fitid is None and tx.import_batch_id is None
    if puramente_sintetica:
        db.delete(tx)
        audit.record(
            db, tenant_id=tenant_id, actor=actor, action="bank.origin.delete", target=tx.id
        )
        return

    tx.origin_id = None
    tx.source = SOURCE_OFX
    tx.status = STATUS_UNMATCHED
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.origin.detach", target=tx.id
    )


def sync_origin_movement(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    source: str,
    origin_id: str,
    bank_account_id: str | None,
    posted_at: date | None,
    amount_cents: int | None,
    description: str,
    counterparty_name: str = "",
    counterparty_document: str = "",
    operation_nature: str | None = None,
    transfer_id: str | None = None,
) -> BankTransaction | None:
    """Deixa o razão bancário coerente com **UM** lançamento de origem. Idempotente. NÃO commita.

    > **É a ÚNICA função do repositório que escreve `source ∈ SOURCES_SISTEMA`; qualquer segundo
    > caminho torna a Regra da Origem inauditável.** Não existe escrita de movimento de origem por
    > `setattr` genérico, por `create_transaction` nem por model direto — se você está prestes a
    > abrir o segundo caminho, o que você precisa é de um parâmetro aqui.

    **Os três ramos, e nada além deles:**

    - **ausente → cria** — `status='matched'` (nasce conciliado), `origin_id` preenchido,
      `raw_description = description`, `fitid=None`, `import_batch_id=None`,
      `dedup_hash = origin_dedup_hash(source, origin_id)`;
    - **presente → atualiza a MESMA linha** (conta, data, valor, descrição, contraparte, hash).
      **Move, nunca duplica** — os dois saldos derivados se corrigem sozinhos porque são derivados;
    - **`bank_account_id is None` → apaga** (ou desliga a origem), sob a guarda de
      `_desliga_ou_apaga`.

    **NÃO COMMITA, e isso é CONTRATO** — mesmo motivo de `build_payable`/`apply_paid`/
    `build_charge`: movimento e lançamento entram na **mesma transação**, e quem chama a fecha.
    Um dos dois sem o outro é exatamente o estado que esta função existe para tornar impossível.
    Faz `db.flush()` antes de `audit.record` porque o `id` tem default **Python-side** — sem o flush
    a trilha nasceria com `target=''` (o defeito MNT-001, que 17 call sites do projeto têm e que o
    módulo `bank` **já evita**).

    **Sobre `raw_description`:** numa linha de `SOURCES_EXTERNA` ela é imutável, porque é a prova
    documental do que **o banco** disse. Numa linha de `SOURCES_SISTEMA` quem "disse" foi o próprio
    e1p, e a Regra da Origem (c) manda o movimento **espelhar** o lançamento — então o sincronizador
    a reescreve, e só ele. A imutabilidade que a invariante (c) do modelo protege é contra o
    **usuário** e contra a IA: os dois continuam escrevendo em `user_description`, que esta função
    **nunca toca** (o rótulo do dono sobrevive a qualquer ressincronização).

    **Sobre `posted_at` futuro:** esta função aplica **só o piso** (`> opening_date`, via
    `service.validate_posted_at_floor`), nunca o teto. O corte é por `source` e por `source` apenas
    (design §4.2.0): `SOURCES_EXTERNA` continua recusando data futura, `SOURCES_SISTEMA` a aceita —
    *"o e1p pode afirmar o futuro do que ele mesmo agendou; não pode afirmar o futuro do que outro
    atestou"*. Quem põe teto em hoje é a **8.12**; quem o libera é a **8.14**. Aqui não há booleano
    `permite_futuro`, e a ausência dele é a decisão.

    Args:
        source: ∈ `SOURCES_SISTEMA` — **422 fora disso**.
        origin_id: a **chave de origem**. Perna única ⇒ o id do lançamento; múltiplas pernas ⇒
            `f"{id}:{perna}"` (Story 8.18, `:out`/`:in`). `VARCHAR(64)`.
        bank_account_id: `None` ⇒ o lançamento **não está mais liquidado** ⇒ apaga o movimento.
        amount_cents: **COM SINAL** — negativo para `payable` (saída), positivo para `charge`
            (entrada). Zero é recusado com 422 (`_validate_amount`).
        transfer_id: pareia pernas irmãs. Só `source='transfer'` usa nesta onda (8.18); a coluna
            **já existe** desde a 0059, então nenhuma migration é necessária para ele.

    Returns:
        O movimento criado/atualizado, ou **`None`** quando não há movimento de origem ao fim da
        chamada — porque foi apagado, porque foi desligado da origem (ramo 2 de
        `_desliga_ou_apaga`) ou porque nunca existiu. Em todos esses casos o chamador grava
        `None` no cache (`payable.bank_transaction_id`), e é assim que o cache **nunca diverge** do
        `origin_id`.
    """
    _validate_source(source)
    _validate_origin_id(origin_id)

    existente = _find(db, source=source, origin_id=origin_id)

    # ── Ramo 3: a origem deixou de estar liquidada ───────────────────────────────────────────
    if bank_account_id is None:
        if existente is not None:
            _desliga_ou_apaga(db, tx=existente, tenant_id=tenant_id, actor=actor)
        # Idempotente: pedir para apagar o que não existe é sucesso, não 404.
        return None

    if posted_at is None or amount_cents is None:
        raise BankError(
            "Movimento de origem com conta informada exige `posted_at` e `amount_cents`. Se o "
            "lançamento deixou de estar liquidado, passe `bank_account_id=None` — é assim que se "
            "pede a remoção do movimento.",
            422,
        )

    # Ordem deliberada: TODA validação antes de qualquer escrita. `get_account` é 404 fail-closed
    # (conta de outro tenant não existe para quem pergunta — a RLS a esconde).
    acc = get_account(db, bank_account_id)
    _validate_amount(amount_cents)
    validate_posted_at_floor(posted_at, acc)

    dedup_hash = origin_dedup_hash(source, origin_id)

    # ── Ramo 2: presente → atualiza a MESMA linha. Move, nunca duplica ───────────────────────
    if existente is not None:
        existente.bank_account_id = acc.id
        existente.posted_at = posted_at
        existente.amount_cents = amount_cents
        existente.raw_description = description
        existente.counterparty_name = counterparty_name
        existente.counterparty_document = counterparty_document
        existente.operation_nature = operation_nature
        existente.transfer_id = transfer_id
        existente.dedup_hash = dedup_hash
        db.flush()
        audit.record(
            db,
            tenant_id=tenant_id,
            actor=actor,
            action="bank.origin.update",
            target=existente.id,
        )
        return existente

    # ── Ramo 1: ausente → cria, já conciliado ────────────────────────────────────────────────
    tx = BankTransaction(
        tenant_id=tenant_id,
        bank_account_id=acc.id,
        posted_at=posted_at,
        amount_cents=amount_cents,
        raw_description=description,
        user_description="",
        # A linha nasce PURAMENTE SINTÉTICA. É o que a guarda de `_desliga_ou_apaga` inspeciona
        # para decidir entre apagar e degradar, e é o que a Onda 4 vai **enriquecer** ao casar
        # esta linha com a linha real do extrato.
        fitid=None,
        import_batch_id=None,
        dedup_hash=dedup_hash,
        counterparty_name=counterparty_name,
        counterparty_document=counterparty_document,
        operation_nature=operation_nature,
        source=source,
        origin_id=origin_id,
        transfer_id=transfer_id,
        # **Nasce `matched`**, e é a única escrita legítima deste status fora do `_refresh_status`
        # da conciliação (Onda 5, ainda inexistente): o e1p originou os dois lados do fato, então
        # não há julgamento de conciliação a fazer. Ver a invariante (d) de `BankTransaction`.
        status=STATUS_MATCHED,
    )
    db.add(tx)
    db.flush()
    audit.record(
        db, tenant_id=tenant_id, actor=actor, action="bank.origin.create", target=tx.id
    )
    return tx
