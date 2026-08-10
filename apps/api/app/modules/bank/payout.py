"""A perna bancária do payout da Carteira (Epic 8, Onda 3) — o QUINTO chamador da Regra da Origem.

⚠️ **Este módulo é a implementação de um `Protocol` declarado em `wallet/service.py`, e NÃO importa
o módulo da Carteira.** Ele recebe números e ids; o objeto que devolve é tipado do outro lado. É
isso que mantém `test_bank_nao_referencia_transaction` apertado — o gate diz, na própria docstring,
que quem precisar do símbolo *"atualiza este teste com justificativa escrita, nunca o apaga"*, e
**esta onda não precisa**. Um gate que já permite o que ninguém usa não avisa nada quando alguém
começar a usar.

A fiação (quem liga um no outro) mora em `app/main.py`, ao lado das duas travessias irmãs — a
guarda de contagem dupla (Story 8.17 AC6) e os termos do gate (Story 8.16 AC7/AC8).

**O que este módulo NÃO faz:** não commita (contrato de `sync_origin_movement`), não escolhe conta
sozinho quando não há principal, e não formata frase de tela.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.modules.bank.models import SOURCE_PAYOUT
from app.modules.bank.origin import sync_origin_movement
from app.modules.bank.service import BankError, primary_account

_DESCRICAO = "Saque da Carteira e1p"


@dataclass(frozen=True)
class _Destino:
    """Estruturalmente igual a `DestinoDoPayout` do outro lado, **de propósito**.

    Duplicar a forma é o preço de não importar o outro módulo, e é um preço baixo: são três campos
    sem comportamento. Importar o símbolo de lá custaria a direção de dependência que a Regra dos
    Planos §1.3b protege — e é a direção, não a dataclass, que impede o bug que originou o Epic 8.
    """

    bank_account_id: str | None = None
    bank_transaction_id: str | None = None
    recusa_detalhe: str | None = None


def registra_payout(
    db: Session,
    *,
    tenant_id: str,
    actor: str,
    payout_id: str,
    amount_cents: int,
    posted_at: date,
) -> _Destino | None:
    """Credita o saque na conta principal. **NÃO commita.**

    `None` ⇒ não há conta principal ativa. Não é erro: é ausência de destino, e quem transforma
    isso em 409 (com a frase) é a Carteira, que é quem tem o usuário na frente.

    `amount_cents` chega **positivo** — é entrada na conta do dono. Diferente de `payable`, que
    entra negativo. O sinal é responsabilidade de quem chama, e o `_validate_amount` do
    sincronizador recusa zero.
    """
    conta = primary_account(db)
    if conta is None:
        return None

    try:
        movimento = sync_origin_movement(
            db,
            tenant_id=tenant_id,
            actor=actor,
            source=SOURCE_PAYOUT,
            origin_id=payout_id,
            bank_account_id=conta.id,
            posted_at=posted_at,
            amount_cents=amount_cents,
            description=_DESCRICAO,
        )
    except BankError as e:
        # O caso conhecido é o piso de data (`posted_at <= opening_date`). Devolver o texto do
        # próprio módulo em vez de recopiar o predicado é deliberado: **duas cópias do mesmo
        # predicado divergem no dia em que só uma for corrigida** — a razão pela qual
        # `validate_posted_at_floor` foi extraída como função pública na Story 8.9.
        # Exceção que NÃO é `BankError` propaga e vira 500: erro de programação não se disfarça de
        # recusa de negócio.
        return _Destino(recusa_detalhe=str(e))

    return _Destino(bank_account_id=conta.id, bank_transaction_id=movimento.id)
