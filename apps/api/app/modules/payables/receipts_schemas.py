"""Schemas da bandeja de comprovantes."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

SEM_CONTA_NA_BAIXA_MSG = (
    "Para dar baixa junto com o comprovante, informe de qual conta bancária o dinheiro saiu "
    "(bank_account_id). Para só anexar o comprovante sem dar baixa, mande mark_paid=false."
)


class ReceiptOut(BaseModel):
    """Um comprovante em staging. Não expõe owner_type/owner_id — são detalhe interno."""

    id: str
    filename: str
    content_type: str
    size: int
    created_at: datetime


class BaixaDoComprovante(BaseModel):
    """Os dois campos da baixa, compartilhados pelos dois corpos da bandeja (Story 8.13, AC3).

    ⚠️ **A obrigatoriedade é CONDICIONAL, e as duas metades da condição importam.**

    - `mark_paid=True` **sem** `bank_account_id` → **422**. A partir da Story 8.12 a baixa escreve o
      movimento bancário, e `apply_paid` não tem (nem pode ter) default de conta: *"opcional
      significa que alguém pula, e a conferência volta a medir o que você esqueceu de preencher"*
      (fundador F7). **Esta story remove o substituto temporário** que a 8.12 deixou em
      `receipts._conta_da_bandeja` (a conta primária, `[SUPOSIÇÃO DO @SM]` + `TODO(8.13)`): a conta
      passa a vir do payload, **sempre** — pré-preencher é papel da tela, não do backend.
    - `mark_paid=False` → o campo é **ignorado**, e isso não é descuido. Anexar um comprovante
      **sem** dar baixa é caso legítimo e frequente (a conta já foi paga antes, ou o dono só quer
      guardar o arquivo); exigir conta bancária ali seria pedir um dado sobre um fato que não está
      sendo afirmado.

    O erro é **422 e não o 409 acionável** de propósito: 409 significa *"o tenant não tem conta
    cadastrada"* (uma situação do mundo, com uma saída — cadastrar), enquanto isto aqui é *"o
    chamador não mandou o campo"* (um erro de requisição). A tela distingue os dois **antes** de
    enviar, porque ela já leu `GET /bank/accounts`.
    """

    # Marcado por padrão: quem compartilha o comprovante acabou de pagar. A tela deixa desmarcar.
    mark_paid: bool = True
    # `None` só é aceito quando `mark_paid=False` (ver o validador abaixo).
    bank_account_id: str | None = None
    # `None` ⇒ default do `apply_paid` (`due_date`). A tela da bandeja manda **hoje** — ver a nota
    # em `receipts.link_receipt`.
    paid_on: date | None = None

    @model_validator(mode="after")
    def _conta_obrigatoria_quando_da_baixa(self) -> BaixaDoComprovante:
        if self.mark_paid and not (self.bank_account_id or "").strip():
            raise ValueError(SEM_CONTA_NA_BAIXA_MSG)
        return self


class ReceiptLinkIn(BaixaDoComprovante):
    bill_id: str


class ReceiptNewBillIn(BaixaDoComprovante):
    """Formulário curto da tela do celular. Deliberadamente MENOR que PayableCreate: sem
    recorrência, sem classificação DRE, sem centro de custo — quem está no celular com o
    comprovante na mão quer registrar rápido e refinar depois no computador."""

    description: str = ""
    category: str = "Geral"
    supplier: str = ""
    amount_cents: int = Field(gt=0)
    due_date: date
