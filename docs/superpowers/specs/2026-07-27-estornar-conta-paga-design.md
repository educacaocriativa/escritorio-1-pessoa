# Estornar conta paga (reabrir Contas a Pagar/Receber para edição)

**Data:** 2026-07-27
**Status:** Aprovado para planejamento
**Módulo:** `payables` + `receivables` (backend) / `features/pagar` + `features/cobrancas` (frontend)

## Contexto

Uma vez que uma conta a pagar ou uma cobrança é marcada "Pago", `update_payable`/`update_charge`
bloqueiam edição de descrição/valor/vencimento (409 "Só contas em aberto podem ter os dados
editados") — só boleto/Pix e anexos continuam editáveis a qualquer momento. Não existe hoje
nenhuma ação para desfazer a baixa, então um lançamento pago com dado errado (ex.: valor,
fornecedor, anexo trocado) fica preso.

## Objetivo

Adicionar um botão **"Estornar"** nas linhas com status "Pago" de Contas a Pagar e Contas a
Receber, que desfaz a baixa e devolve o lançamento para "A pagar"/aberto — reabrindo edição
completa (inclusive novos anexos) e revertendo o evento vinculado na Agenda de "concluído" para
pendente.

## Decisões (confirmadas com o usuário)

1. **Escopo: Pagar + Receber**, não só Contas a Pagar.
2. **Confirmação:** o botão pede `confirm()` do navegador antes de chamar a API — mesmo padrão já
   usado pelo botão "Cancelar" existente.
3. **Assimetria Pagar vs. Receber é respeitada, não escondida:**
   - Contas a Pagar não move dinheiro (é só uma despesa registrada) — estornar é uma troca de
     status simples.
   - Contas a Receber, ao ser paga, cria uma `Transaction` na Carteira com split 40/30/20
     (`wallet_service.build_transaction`) que já pode ter mudado de "a receber" para "disponível"
     e, dali, para "sacado" (`request_payout`). Estornar uma cobrança **bloqueia com 409** se a
     `Transaction` vinculada já está `withdrawn` — o valor já saiu fisicamente da carteira (foi
     sacado) e não pode ser desfeito só editando um registro.
   - O ledger global `PlatformEarning` (painel de ganhos do Master) **não é tocado** pelo estorno.
     É um registro histórico imutável por design ("Mantido mesmo após a exclusão de uma conta" —
     ver `wallet/models.py`); reverter os ganhos da plataforma retroativamente é uma decisão maior,
     de produto, fora do escopo deste estorno pontual. Isso é a MESMA lacuna já documentada no
     `CLAUDE.md` ("estorno ainda sem caminho de execução nem reversão do platform_earnings") — este
     estorno resolve o caminho de execução para o dono da conta, não a reversão do ganho da
     plataforma.

## Arquitetura

### Backend — Contas a Pagar (`app/modules/payables`)

Novo endpoint `POST /payables/bills/{id}/reverse` → `service.reverse_payable`:

```python
def reverse_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    p = db.scalar(select(Payable).where(Payable.id == payable_id).with_for_update())
    if p is None:
        raise PayableError("Conta não encontrada", 404)
    if p.status != STATUS_PAID:
        raise PayableError("Só contas pagas podem ser estornadas", 409)
    p.status = STATUS_OPEN
    p.paid_at = None
    if p.agenda_event_id:
        ev = db.get(AgendaEvent, p.agenda_event_id)
        if ev is not None:
            ev.status = STATUS_SCHEDULED
    audit.record(db, tenant_id=tenant_id, actor=actor, action="payable.reverse", target=p.id)
    db.commit()
    db.refresh(p)
    return p
```

`with_for_update` segue o mesmo padrão de `mark_paid` (serializa contra uma baixa concorrente).

### Backend — Contas a Receber (`app/modules/receivables`)

Novo endpoint `POST /receivables/charges/{id}/reverse` → `service.reverse_charge`:

```python
def reverse_charge(db: Session, *, charge_id: str, tenant_id: str, actor: str) -> Charge:
    charge = db.scalar(select(Charge).where(Charge.id == charge_id).with_for_update())
    if charge is None:
        raise ReceivableError("Cobrança não encontrada", 404)
    if charge.status != STATUS_PAID:
        raise ReceivableError("Só cobranças pagas podem ser estornadas", 409)

    tx = db.get(Transaction, charge.transaction_id) if charge.transaction_id else None
    if tx is not None:
        if tx.status == STATUS_WITHDRAWN:
            raise ReceivableError(
                "Não é possível estornar: o valor já foi sacado da carteira", 409
            )
        tx.status = STATUS_REFUNDED

    charge.status = STATUS_OPEN
    charge.paid_at = None
    if charge.agenda_event_id:
        ev = db.get(AgendaEvent, charge.agenda_event_id)
        if ev is not None:
            ev.status = STATUS_SCHEDULED
    audit.record(db, tenant_id=tenant_id, actor=actor, action="receivable.reverse", target=charge.id)
    db.commit()
    db.refresh(charge)
    return charge
```

`STATUS_REFUNDED` já existe em `wallet/models.py` e já é excluído das somas de saldo
(`_sum_net`/`wallet_summary` só somam AVAILABLE/PENDING/WITHDRAWN), então marcar a transação como
`refunded` já remove o valor do saldo disponível sem precisar tocar `wallet_summary`.
`charge.transaction_id` permanece apontando para a transação estornada (rastro histórico); uma
nova baixa futura (`mark_paid`) sobrescreve com uma nova transação — sem constraint de FK, é seguro.

### Frontend

Em `PagarPage.tsx` e `CobrancasPage.tsx`, ao lado do bloco `p.status === "open"` que já mostra
Editar/Marcar paga/Cancelar, um novo bloco condicional:

```tsx
{p.status === "paid" && (
  <button
    onClick={() => reverse(p.id)}
    className="text-xs font-medium text-neutral-400 hover:text-danger"
  >
    Estornar
  </button>
)}
```

```ts
async function reverse(id: string) {
  if (!confirm("Estornar esta conta? Ela volta para \"A pagar\" e pode ser editada de novo."))
    return;
  try {
    await api.post(`/payables/bills/${id}/reverse`); // ou /receivables/charges/{id}/reverse
    load();
  } catch (err) {
    alert(apiErrorMessage(err)); // mesmo padrão de erro já usado nas outras ações da página
  }
}
```

O 409 de "já foi sacado" (Receber) chega como mensagem de erro da API e é mostrado do mesmo jeito
que os outros erros da página (não precisa de tratamento especial de UI).

## Erros e casos de borda

- Estornar conta já aberta/cancelada → 409 (guarda de status).
- Estornar cobrança cujo saldo já foi sacado → 409, bloqueado (documentado acima).
- Estornar duas vezes seguidas (clique duplo) → segunda chamada já vê `status != paid` → 409,
  idempotente na prática (não duplica reversão).
- Evento de Agenda pode não existir mais (deletado) — `db.get` retorna `None`, guard já existente
  (`if ev is not None`) cobre.

## Testes

- `apps/api/tests`: caminho feliz (paga → estorna → volta pra "open", `paid_at` limpo, evento
  volta pra `scheduled`) e 409 em conta/cobrança não-paga, para os dois módulos.
- Receivables: teste específico de 409 quando a `Transaction` vinculada está `withdrawn`.
- Frontend: nenhum teste novo de componente é exigido pelo padrão atual do projeto (as páginas de
  Pagar/Cobranças não têm testes de componente hoje); cobertura fica no backend.
