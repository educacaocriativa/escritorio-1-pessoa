# Quality Gate — Epic 8, Onda 2 (a origem do movimento)

> **Agente:** Quinn (@qa) · **Data:** 2026-08-04
> **Branch:** `feat/onda2-origem-do-movimento` (18 commits à frente de `origin/main`)
> **Base da revisão:** `7dba286` (merge da Onda 1, PR #61)
> **Escopo:** 13 stories — 8.9 a 8.20 + o fix de overflow do `Modal`
> **Migrations:** 0061 (Regra da Origem) e 0062 (`bank_transfers`)

---

## Veredito

# CONCERNS

**Não é PASS** por causa de **um defeito de integridade de dado confirmado por reprodução** (BANK-002)
e de **uma decisão de escopo pendente do fundador** (o AC9/360px da 8.13), esta última já declarada
como bloqueante por ele mesmo (F-D8) e com duas leituras contraditórias no repositório sobre *o que* ela
bloqueia.

**Não é FAIL** porque nada do que foi construído está errado na sua própria disciplina: as invariantes
declaradas resistiram a todos os ataques diretos de API, os três gates críticos mataram os mutantes que
lhes cabem, o gate P1–P4 é fiel ao §3.1.2 e as três suítes estão verdes sem exceção. O defeito achado é
uma **costura que faltou entre a 8.14 e a 8.15**, não uma falha do desenho.

---

## Os 7 quality checks

| # | Check | Veredito | Evidência |
|---|---|---|---|
| 1 | **Suítes verdes** | ✅ PASS | backend `1451 passed, 1 skipped, 38 deselected` (323,67s); `rls_e2e` `38 passed` (54,62s); frontend `476 passed / 53 files` (21,13s) |
| 2 | **Lint / types** | ✅ PASS | `ruff check .` → *All checks passed!*; `tsc --noEmit` → sem saída; `eslint . --max-warnings 0` → sem saída |
| 3 | **ACs implementados** | ⚠️ CONCERNS | Todos verificados por leitura + sonda, **exceto o AC9 da 8.13** (aceite físico em ~360px), declarado NÃO satisfeito pelo próprio @dev e bloqueante por F-D8 |
| 4 | **Invariantes de domínio** | ⚠️ CONCERNS | Invariante do Trilho, Regra da Origem (a),(b),(d),(e) e o gate P1–P4 **resistiram a ataque direto de API**. A Regra da Origem **(c)** — *"nunca deixa órfão"* — **foi violada** (BANK-002) |
| 5 | **Migrations / RLS** | ✅ PASS | `alembic heads` → **`0062 (head)`**, um único head; cadeia `0060 → 0061 → 0062` sem ambiguidade; 0062 cria `bank_transfers` com `ENABLE` + `FORCE` + policy `tenant_isolation` (cópia literal de `0049_investments::_enable_rls`); 0061 é estritamente aditiva (colunas nullable + índices), sem backfill |
| 6 | **Teste de mutação** | ✅ PASS | 5 mutantes aplicados nos 3 gates críticos, **4 mortos**. O sobrevivente é ofuscação deliberada (`"app.modules." + "pay" + "ables"`) — teto conhecido de qualquer gate estático, registrado como INFO |
| 7 | **Revisão automatizada** | ⚠️ CONCERNS | CodeRabbit CLI, `review --agent --committed --base-commit 7dba286`: **18 achados — 0 critical, 2 major, 16 minor**. Sem o falso positivo de CRLF (o `--committed` o evita). Os 2 major são reais e estão promovidos abaixo |

---

## BANK-002 — o defeito novo, com reprodução

### `POST /payables/bills/{id}/cancel` sobre uma conta `scheduled` deixa o movimento bancário órfão

**Severidade: HIGH.** `apps/api/app/modules/payables/service.py:665-673`.

```python
def cancel_payable(db: Session, *, payable_id: str, tenant_id: str, actor: str) -> Payable:
    p = get_payable(db, payable_id)
    if p.status == STATUS_PAID:
        raise PayableError("Conta paga não pode ser cancelada", 409)
    p.status = STATUS_CANCELED          # ← `scheduled` passa direto
    ...
```

`scheduled` não está na guarda, e nada nesta função chama `_sincroniza_movimento`. Resultado
reproduzido (sonda de QA, saída real):

```
[SONDA1] POST /cancel em payable scheduled -> 200: {... "status":"canceled",
         "bank_account_id":"83086484-...","bank_transaction_id":"80a1af81-..."}
[SONDA1] payable.status=canceled bank_account_id=83086484-... bank_transaction_id=80a1af81-... movimentos=1
AssertionError: REGRA DA ORIGEM (c) VIOLADA: cancelar uma conta a pagar AGENDADA deixou
                1 bank_transaction(s) orfao(s) afirmando um debito futuro que nao existe mais.
```

**O que isso custa, e por que é a pior classe de defeito desta onda:**

1. O `bank_transaction` de débito futuro **sobrevive** e entra no saldo derivado no dia agendado,
   porque o saldo é função da data — sem worker nenhum. A conta fica permanentemente R$ X abaixo
   da realidade.
2. Na conferência, isso vira **divergência positiva** (banco acima do sistema) — a assinatura exata
   de *"você recebeu algo e não registrou"*. O produto manda o dono caçar um furo **que o próprio
   sistema criou**. É o modo de falha do BANK-001 pela porta oposta.
3. **O gate P1–P4 não vê.** `contar_saidas_sem_conta_informada` filtra
   `status IN ('paid','scheduled')`; uma `Payable` `canceled` sai da população. A pré-condição do
   §3.1.2 diz *"nenhum evento conhecido moveu dinheiro sem gerar o `bank_transaction`"* — e aqui o
   inverso aconteceu: existe `bank_transaction` sem evento. **A pré-condição fica satisfeita e o
   razão está sujo.** Este é literalmente o item 3 do foco deste gate ("o gate não mente").
4. `payables.bank_transaction_id` continua apontando para uma linha viva numa conta cancelada.
   `test_cache_de_movimento_nunca_diverge_do_origin_id` **passa** (o `origin_id` casa), porque o
   teste cobre os cinco caminhos de mutação enumerados no design — *baixar, trocar conta, trocar
   data, estornar, repagar* — e **cancelar não está entre eles**.

**A assimetria é a prova de que é lacuna, não decisão.** A Story 8.15 pôs exatamente esta guarda no
lado das cobranças, com a justificativa escrita (`receivables/service.py:1074-1098`):

> *"cancelá-la sem tocar no movimento deixaria o razão bancário afirmando 'este dinheiro vai entrar
> nesta conta' sobre uma cobrança que não existe mais — a violação (c) da Regra da Origem"*

O lado `payables` — que é o fluxo **principal** do épico — não recebeu a irmã. Verificado por sonda:
`cancel` em `Charge scheduled` → **409**; `cancel` em `Payable scheduled` → **200 + órfão**.

**Alcançabilidade hoje.** A UI **não** expõe o gesto: `PagarPage.tsx:256` só mostra "Cancelar" para
`status === "open"`, e para `scheduled` mostra "Cancelar agendamento" → `POST /reverse`, que está
correto e apaga o movimento. Mas:
- a rota HTTP está aberta e sem guarda — e a instrução deste gate é justamente não confiar no
  frontend impedir;
- há um caminho **realista sem má-fé**: a lista de `PagarPage` é renderizada de estado carregado por
  `load()`. Uma conta que estava `open` na tela e foi agendada em outro dispositivo (a bandeja de
  comprovantes do celular chama `apply_paid` com `paid_on` futuro) continua exibindo o botão
  "Cancelar" da linha velha. Um clique produz o órfão, com 200 e sem aviso.

**Correção recomendada (não aplicada — não altero código de produção):** espelhar a 8.15.
`cancel_payable` recusa `scheduled` com 409 apontando a saída certa (*"esta conta tem um pagamento
agendado; para desfazê-lo use Cancelar agendamento"*), ou — se o produto preferir permitir — chamar
`_sincroniza_movimento(..., bank_account_id=None)` na mesma transação. **Recomendo o 409**, pelo mesmo
argumento que a 8.15 usou: já existe verbo para isso (`reverse`), e dois caminhos para a mesma mecânica
é como uma delas fica para trás — que é exatamente o que aconteceu aqui.

**Regressão a acrescentar junto do fix:** `test_cache_de_movimento_nunca_diverge_do_origin_id` precisa
de um **sexto** caminho de mutação — *cancelar* —, e a lista dos cinco em
`docs/architecture/controle-bancario-onda2-design.md` §3.3 precisa virar seis. A lista era a garantia,
e ela estava incompleta.

---

## Status confirmado dos 9 achados abertos herdados

| # | Achado | Status | Evidência |
|---|---|---|---|
| **1** | **AC9 da 8.13 — aceite em ~360px** | 🔴 **ABERTO — o item que precisa do fundador** | `docs/stories/8.13.story.md:4` (`Status: InReview`), §"Evidência do aceite em ~360px": *"NÃO CAPTURADA"*, itens (b), (c), (e) não verificados. Nenhuma sessão teve dispositivo real nem stack de dev viva. Ver §"Decisões do fundador" |
| **2** | **Movimento de sistema com `posted_at` futuro sem guarda em `update`/`ignore`** | ✅ **FECHADO — e cobre os dois casos, não só transferência** | `bank/service.py:1063` — `_recusa_se_origem_do_sistema` testa `tx.source not in SOURCES_SISTEMA`, ou seja, **contra o conjunto**, nunca contra `'transfer'`. Chamada em `update_transaction:1285` (só quando `posted_at`/`amount_cents` vêm no PATCH — `user_description` continua livre, que é a exceção nomeada da Regra (d)) e em `ignore_transaction:1327`, **antes** do no-op de idempotência. Sonda: PATCH `amount_cents` → 422, PATCH `posted_at` → 422, `ignore` → 422, todos com `origem: payable` na mensagem |
| **3** | **Cancelamento de `scheduled` deixa movimento órfão** | 🟠 **PARCIAL — fechado nas cobranças, ABERTO nas contas a pagar** | `cancel_charge` (`receivables/service.py:1092`) recusa `scheduled` com 409 → sonda confirma. `cancel_payable` (`payables/service.py:667`) só guarda `paid` → **BANK-002 acima**. Nenhum commit posterior (8.16/8.18/8.19) fechou o lado `payables` |
| **4** | **Docstring OpenAPI do `indisponivel`** | ✅ **FECHADO** | `bank/router.py:742-748`: *"`indisponivel` é resposta legítima, não um erro, e tem **DOIS motivos** (Story 8.20)"*, com os dois nomeados e com o discriminador explicitado (`saldo_banco_data`, preenchido só no degenerado). A 8.16 fez o que disse |
| **5** | **`contas_sem_checkpoint` — nome impreciso** | 🟡 **ABERTO — dívida aceitável** | `reconciliation.py:781`: `contas_sem_checkpoint = len(contas) - len(avaliaveis)`, e `avaliaveis` é `divergencia_cents is not None`, que inclui o caso degenerado. O nome mente para quem lê só o campo. **Mas:** `schemas.py:546` documenta que o par `contas_avaliadas`/`contas_sem_checkpoint` existe *"para que o consumidor saiba o que o total cobre"*, e `notes` traz a nota por conta dizendo qual dos dois motivos é. **Recomendação: manter.** Renomear um campo de contrato de API por precisão semântica, com a nota já dizendo a verdade na tela, custa mais do que ganha. Registrar como dívida nomeada (MNT) |
| **6** | **Código morto em `conferencia.ts:331`** | 🟢 **ABERTO — LOW, e não esconde nada** | `reconciliation.py:625-628`: `ultima_declaracao = checkpoint.reference_date if checkpoint is not None else account.opening_date`, e `opening_date` é `NOT NULL` → o contador **nunca mais é `None`** (documentado na linha 620 como AC5 da 8.19). Os dois pontos de construção de `ConferenciaConta` passam o `int`. Logo o ramo `dias === null` de `conferencia.ts:331` é inalcançável, **e o ramo gêmeo `engine.py:332` também**. Auditado: nenhum dos dois mascara outro caso — o tipo é que ficou largo (`int \| None` em `reconciliation.py:215`, `schemas.py:528` e `conferencia.ts:51`). Fechar é estreitar o tipo nos três lugares |
| **7** | **`charges.bank_account_id` sem índice** | 🔴 **ABERTO — MEDIUM** | `0061_origin_movement.py:99` cria `ix_payables_bank_account (tenant_id, bank_account_id)`; a linha 104 adiciona `charges.bank_account_id` **sem índice irmão**. `receivables/models.py` indexa `client_id`, `contract_id` e `cost_center_id`, e não este. O caminho de leitura do gate (`contar_entradas_sem_conta_informada`, `receivables/service.py:895`) filtra por essa coluna, e a Invariante do Trilho vai passar a ser varrida por ela. Assimetria sem justificativa escrita |
| **8** | **Casamento do "débito suspeito" por `bank_account_name`** | 🔴 **ABERTO — MEDIUM, bug latente** | `engine.py:480`: `if d.bank_account_name == c.account_name`. A docstring (`engine.py:465`) declara que é *"o único identificador de conta que o motor conhece"*, por design. `bank/models.py:75-84`: o único índice único de `bank_accounts` é `(tenant_id, institution_code, branch, number) WHERE number <> ''` — **`name` não tem unicidade por tenant**. Duas contas "Itaú" no mesmo tenant fazem o débito de uma explicar a divergência da outra, e o produto nomeia o débito errado — o modo de falha que a §9.2.1 diz ser *"pior do que ficar calado"*. **Compõe com o achado do CodeRabbit sobre o `AccountModal`** (abaixo), que é justamente uma forma de o tenant acabar com duas contas de mesmo nome |
| **9** | **`generated.ts` defasado** | 🔴 **ABERTO — LOW, sem caminho de produto dependente** | `packages/shared-types/src/generated.ts`: 12.306 linhas, **5 símbolos exportados**, **zero** ocorrências de `bank`/`Bank`. Confirmado que **nenhum caminho de produto depende dele**: `apps/web` importa exclusivamente de `@e1p/shared-types` (o `index.ts` mantido à mão), e o `index.ts` só cita `generated.ts` em prosa — não reexporta. Continua sem check de drift no CI. Dívida documental, não risco funcional |

---

## Foco do gate — os 6 itens, com evidência

### 1. A Invariante do Trilho não vaza ✅

Atacada **por API direta**, não pela tela. Quatro vetores, saída real das sondas:

| Ataque | Resultado |
|---|---|
| `/pay` (trilho) → `settle-externally` | **409** *"Esta cobrança já foi paga pelo trilho do e1p…"*; `transaction_id` preenchido, `bank_account_id=None`, **0** `bank_transaction` |
| `settle-externally` → `/pay` | **200 no-op** (idempotência de status); `transaction_id=None`, `bank_account_id` preenchido |
| `settle-externally` → `POST /receivables/webhook` (payload interno) | **200 `{"status":"paid"}` no-op**; ponteiros inalterados |
| `settle-externally` com data futura (`scheduled`) → `cancel` | **409**, com a mensagem que explica o crédito anunciado |

Em nenhum caminho a `Charge` ficou com dois ponteiros ou com nenhum.

### 2. A Regra da Origem não permite contornar ✅ (com um teto declarado)

**Escritor único.** `sync_origin_movement` é o único que escreve `SOURCES_SISTEMA`, e a allowlist
`_CHAMADORES_PERMITIDOS` (`tests/test_bank_origin.py:808`) tem exatamente os 4 chamadores reais —
`bank/origin.py`, `payables/service.py`, `receivables/service.py`, `bank/transfers.py` — com
justificativa por entrada, mais um teste que reprova entrada morta.

**Porta manual não é segundo caminho.** Sonda: `POST /bank/accounts/{id}/transactions` com
`source ∈ {payable, charge, transfer, yield, payout}` → **201 nos cinco casos, e as cinco linhas
gravadas com `source='manual'`**. O `source` do cliente é ignorado e fixado no service.

**Os quatro vetores de evasão, testados por mutação** (backup e restauração por **cópia de arquivo**,
nunca `git checkout`; md5 conferido antes e depois):

| Mutante | Forma | Veredito | Quem matou |
|---|---|---|---|
| **A** | `from app.modules import payables` (alias — evade o grep literal) | **MORTO** | `test_bank_nao_importa_payables` (AST com alias apenso) + `test_bank_service_nao_nomeia_a_entidade_de_negocio` |
| **B1** | `importlib.import_module("app.modules.payables")` (evade o AST) | **MORTO** | `test_bank_nao_importa_payables_tambem_por_texto_cru` + o teste de nome |
| **B2** | `importlib.import_module("app.modules." + "pay" + "ables")` | **SOBREVIVEU** — 14 passed | — |
| **C** | `def _mut(x) -> "Payable \| None"` — anotação em string, **sem import real** | **MORTO** | `test_bank_service_nao_nomeia_a_entidade_de_negocio` |

**O buraco que a 8.17 fechou continua fechado** depois de 6 stories mexerem no mesmo arquivo: o
mutante C é exatamente a forma que reprovava o `Protocol` original, e o teste de nome — que varre
`payables`/`Payable`/`payable_id` como substring em qualquer posição de `bank/service.py`, inclusive
docstring — o mata sem depender de import nenhum.

**Sobre o B2 (INFO, não achado):** concatenar o nome do módulo evade AST **e** grep literal por
construção. Nenhum gate estático de texto pega isso, e o próprio design reconhece o limite quando
escreve *"evadir um gate é pior do que quebrá-lo às claras"* — a defesa contra o B2 não é técnica, é
o code review vendo `importlib` num módulo que não deveria ter nenhum. Registro para que ninguém leia
"4 mutantes mortos" como "impossível evadir".

### 3. O gate P1–P4 não mente ✅ (com a ressalva do BANK-002)

Cenário montado com os três casos que o §3.1.2 nomeia — **membro, não-membro e o não-membro 2**:

```
[SONDA3] P1+P2 count=1 valor=38000 | P3 count=1 valor=12000
[SONDA3] notes=[
  'O total não cobre todas as contas: 1 conta não avaliada no período — o motivo está na nota de cada conta.',
  '1 lançamento deste período não informa de qual conta saiu ou entrou (R$ 380,00). A divergência
   abaixo **inclui** esse valor. Este termo fecha na Onda 2: assim que todo lançamento informar a
   conta, ele vai a zero sozinho.',
  '1 rendimento de aplicação deste período (R$ 120,00) ainda não gera movimento bancário. A
   divergência abaixo **inclui** esse valor. Este termo só fecha na Onda 2b — não há o que corrigir à mão.'
]
```

- **`Payable` paga sem conta** (uma das 45 legadas, escrita direta porque a 8.12 tornou a coluna
  obrigatória) → contou em **P1**, R$ 380,00. ✅
- **`Charge` de rendimento** (`register_yield` → `external_ref='investment:…'`) → **excluída de P2**,
  contada em **P3** com contador e nota próprios. ✅ O `_not_investment_yield()` é **importado** de
  `receivables/service.py:154`, e o P3 é a **negação do mesmo predicado** (`~_not_investment_yield()`),
  não uma segunda escrita do `LIKE` — a divergência entre cópias que a ratificação temia é impossível
  por construção.
- **`Charge` do trilho** paga por `/pay` na mesma janela → **não contou em lugar nenhum**. ✅
- As notas **nomeiam a onda que fecha cada termo** (AC7 da 8.16) e **anotam sem subtrair**: nenhum dos
  quatro campos toca `divergencia_cents`, `tolerancia_cents`, `dentro_da_tolerancia`,
  `total_divergencia_cents` ou `contas_fora_da_banda`.

**A ressalva:** o gate é fiel ao §3.1.2 **como escrito**. O §3.1.2 enumera eventos que moveram dinheiro
**sem** gerar movimento; ele não tem termo para o simétrico — **movimento sem evento**, que é o que o
BANK-002 produz. Não é falha da implementação; é um buraco da pré-condição que só ficou visível
quando o defeito apareceu.

### 4. `scheduled` não produz contagem dupla em nenhuma combinação ✅

**Transferência agendada não existe** — e é decisão, não lacuna (§8): `create_transfer` recusa data
futura com 422 (*"O e1p registra a transferência que já aconteceu…"*), confirmado por sonda. Então a
combinação pedida vira **transferência hoje + conta agendada na mesma janela**:

```
[SONDA4] saldo derivado conta1 (hoje) = 9.830.000  (10.000.000 −100.000 transferência −70.000 conta paga hoje)
[SONDA4] saldo_inicial=9.930.000 origem=misto banco=9.930.000 plataforma=0   (as duas pernas da transferência somam zero)
[SONDA4] janela 30d saldo_projetado=9.730.000      (= saldo_inicial − 200.000 da agendada, UMA vez)
```

**O dia da transição, com o worker parado** — a combinação mais delicada, montada à mão
(`Payable` ainda `scheduled`, `paid_at::date == hoje`, movimento com `posted_at == hoje`):

```
[SONDA8] status=scheduled paid_at=2026-08-04 saldo_derivado=9.700.000
         saldo_inicial=9.700.000 janela30d=9.700.000
```

A agendada está no saldo inicial **uma vez** e **não** volta a sair na janela. O recorte
`status == 'scheduled' AND paid_at::date > hoje` funciona, e a aritmética não depende do worker.

**Mutante D** — remover a metade da data do recorte (`scheduled_at >= hoje+1` → `hoje−3650`):
**MORTO por 4 testes**:
`test_AC6_a_agendada_no_DIA_DO_DEBITO_nao_conta_duas_vezes`,
`test_AC6_o_numero_e_IDENTICO_com_e_sem_o_worker`,
`test_AC6_o_recebimento_agendado_no_DIA_DO_CREDITO_nao_conta_duas_vezes`,
`test_AC6_ENTRADAS_o_numero_e_IDENTICO_com_e_sem_o_worker`.

### 5. Migrations encadeiam sem ambiguidade ✅

```
$ alembic heads
0062 (head)

$ alembic history | head -2
0061 -> 0062 (head), bank_transfers: transferência entre contas próprias (duas pernas, um lançamento) — Story 8.18
0060 -> 0061, A Regra da Origem: chave de origem + os ponteiros de negócio (plano 3) — Story 8.9
```

Um único head. 0062 aplica `ENABLE` + `FORCE ROW LEVEL SECURITY` + policy `tenant_isolation` em
`bank_transfers`, por cópia literal de `0049_investments::_enable_rls`. 0061 é **estritamente
aditiva** — colunas nullable em `bank_transactions`, `payables` e `charges`, mais o único parcial
`uq_bank_transactions_origin (tenant_id, source, origin_id) WHERE origin_id IS NOT NULL` — **sem
backfill**, portanto fora da armadilha da 0046. A suíte `rls_e2e` (38 testes, Postgres real via
testcontainers, `alembic upgrade head` como `e1p_app`) exercita as duas migrations de fato.

### 6. Teste de mutação em 3 gates críticos ✅

| Gate | Mutante | Veredito |
|---|---|---|
| `bank ↛ payables/receivables` | A, B1, C (3 formas) | **3 mortos** |
| Guarda de contagem dupla no dia da transição | D (`_window_sums` perde a metade da data) | **MORTO por 4 testes** |
| Comparação degenerada da 8.20 | E (`if na_janela is None or degenerada` → `if na_janela is None`) | **MORTO por 3 testes**: `test_checkpoint_na_data_de_abertura_nao_e_conferencia`, `test_checkpoint_na_data_de_abertura_que_DISCORDA_nao_inventa_furo`, `test_saldo_declarado_na_data_de_abertura_nao_produz_verde_de_completude` |

**E a verificação direta do cenário da 8.20** (declarar checkpoint na data de abertura de uma conta
nova, exatamente como pedido):

```
[SONDA5] declarar checkpoint na data de abertura -> 201
[SONDA5] saldo_banco_origem=indisponivel  divergencia=None  dentro_da_tolerancia=None  saldo_banco_data=2026-06-05
[SONDA5] notes da conta = ['Você informou o saldo desta conta em 2026-06-05, o mesmo dia em que a conta
         foi aberta no e1p. Nesse dia o e1p ainda não tinha movimento nenhum para somar: a comparação
         sairia do saldo de abertura contra ele mesmo…']
[SONDA5] níveis dos sinais do Diagnóstico = ['amarelo']
```

**Não produz 🟢.** A declaração continua legítima e continua contando no bloco 4 — o degenerado é a
comparação, não o ato. Restauração dos três arquivos mutados verificada por md5 idêntico ao original,
e `202 passed` nas suítes tocadas depois da reversão.

---

## CodeRabbit — 18 achados

`coderabbit review --agent --committed --base-commit 7dba286` · 104 arquivos revisados ·
**0 critical, 2 major, 16 minor**. Sem o falso positivo de CRLF (o `--committed` o evita — registrado
para a próxima rodada).

### Os 2 major, ambos reais e promovidos

**CR-1 · `tests/test_admin_nao_expoe_recebimento_fora_do_trilho.py:83` — o teste de presença mede o
vazio. MEDIUM.**

```python
donos = {rota.path.split("/")[1] for rota in app.routes if rota.path.startswith("/admin/")}
assert donos == {"admin"}
```

O conjunto é `{"admin"}` por construção — a asserção é tautológica. E
`assert any('prefix="/admin"' in f for f in fontes)` prova que `platform` declara o prefixo, **não que
seja o único**. Importa porque este arquivo é o gate de uma **proibição normativa de produto** (§6:
*"nenhuma superfície da plataforma pode ser construída sobre `charges.bank_account_id`"*), e a varredura
só olha `app/modules/platform/`. Um módulo novo montando `APIRouter(prefix="/admin")` com um agregado
sobre a coluna passaria batido, e o gate continuaria verde. É o defeito que a própria docstring do
teste diz existir para evitar. **Correção: varrer todos os `.py` fora de `platform/` procurando
`prefix="/admin"`** (o CodeRabbit já traz o patch).

**CR-2 · `CLAUDE.md:229` — a pré-condição do gate no CLAUDE.md não menciona P3. LOW-MEDIUM.**
Quem ler só o `CLAUDE.md` conclui que a Onda 2 zera a pré-condição sozinha. O epic §3.1.2 e o design
§9.3 estão certos e completos; é a memória do projeto que ficou com a versão curta. Dado que o F-D12
foi fechado com *"0 rendimentos lançados hoje"* — decisão declaradamente **frágil**, que muda sozinha
no dia do primeiro rendimento — esta é a linha que mais precisa estar certa no arquivo que todo
mundo lê.

### Os minor que merecem virar dívida nomeada (não bloqueiam)

| Arquivo | Achado |
|---|---|
| `apps/web/src/features/financeiro/AccountModal.tsx:173-183` | **O mais relevante dos minor.** Se o `POST /bank/accounts` sucede e o `PATCH is_primary` falha, o `catch` faz `setError` e **nunca chama `onSaved`/`onClose`**. A conta **existe**. No fluxo do 409 acionável da 8.13 (erro → cadastro embutido → volta à baixa) o usuário reenvia e cria **uma segunda conta com o mesmo nome** — e nada impede, porque o único índice único de `bank_accounts` é sobre `(institution_code, branch, number) WHERE number <> ''`, campos que o cadastro mínimo não preenche. **Compõe diretamente com o achado #8**: contas de mesmo nome são o que quebra o casamento do "débito suspeito" |
| `apps/api/app/modules/financial_intelligence/engine.py:413-423` | O sinal de recebimento fora do trilho diz *"deste mês"* com janela arbitrária. O motor é puro e recebe `start`/`end`; a frase mente para qualquer janela que não seja o mês |
| `apps/api/app/modules/payables/schemas.py:82` e `payables/service.py:826` | Docstrings ainda descrevem o teto em hoje (revogado pela 8.14) e dizem que `scheduled` "não existe ainda" (existe desde a 8.14). Documentação atrás do código — a mesma classe de defeito que induziu a Story 8.2 a especificar validação fraca de CPF |
| `packages/shared-types/src/index.ts:380` | `ChargesSummary.scheduled_cents` obrigatório enquanto `PayablesSummary.scheduled_cents` é opcional; assimetria que quebra o front contra backend antigo |
| `docs/prd/index.md:88` | As stories 8.19 e 8.20 não entraram na tabela nem na ordem de merge do Epic 8 |
| `docs/…/controle-bancario-onda2-design.md:1258` | O cabeçalho da §9.2 diz "quatro termos" e a lista tem cinco (o epic §3.1.2 já diz cinco) |
| `docs/stories/8.14.story.md:613`, `8.19.story.md:388` | Contagem e numeração de mutantes na evidência não batem com as tabelas |

---

## Achados novos deste gate, por severidade

| ID | Severidade | Achado |
|---|---|---|
| **BANK-002** | **HIGH** | `cancel_payable` não guarda `scheduled` → `bank_transaction` órfão, divergência inventada, e **o gate P1–P4 não o vê**. Reproduzido |
| **GATE-001** | **MEDIUM** | A pré-condição do §3.1.2 tem termos só para *"evento sem movimento"*. Não tem termo para *"movimento de origem sem evento"* — o estado que o BANK-002 produz. Uma varredura barata (`bank_transaction` com `source ∈ SOURCES_SISTEMA` cujo `origin_id` não resolve para um lançamento vivo) fecharia a simetria e valeria também como rede para bugs futuros da Regra da Origem (c) |
| **TEST-002** | **MEDIUM** | A lista dos **cinco** caminhos de mutação de `test_cache_de_movimento_nunca_diverge_do_origin_id` (design §3.3) não inclui **cancelar**. A lista era a garantia, e ela estava incompleta — mesma família do TEST-001 do gate anterior |
| **CR-1** | **MEDIUM** | `test_platform_e_o_unico_router_com_prefixo_admin` é tautológico; o gate da proibição §6 mede o vazio |
| **UX-002** | **MEDIUM** | `AccountModal`: falha parcial no `PATCH is_primary` produz conta duplicada no fluxo do 409 acionável; alimenta o achado #8 |
| **IDX-001** | **MEDIUM** | `charges.bank_account_id` sem índice, ao contrário de `payables` (achado #7) |
| **SIG-002** | **MEDIUM** | Casamento do "débito suspeito" por `bank_account_name` sem unicidade de nome por tenant (achado #8) |
| **DOC-002** | **LOW-MEDIUM** | `CLAUDE.md:229` — pré-condição do gate sem P3 (CR-2) |
| **MNT-002** | **LOW** | `contas_sem_checkpoint` — nome impreciso, dívida aceitável (achado #5) |
| **DEAD-001** | **LOW** | `conferencia.ts:331` e `engine.py:332` — ramos `dias === null` inalcançáveis; o tipo é que ficou largo em 3 lugares (achado #6) |
| **DOC-003** | **LOW** | `generated.ts` sem `bank`, sem check de drift no CI, **sem consumidor de produto** (achado #9) |
| **INFO-001** | INFO | Gate estático não pega nome de módulo concatenado (`"pay" + "ables"`). Teto conhecido; a defesa é o code review |

**Dívidas herdadas que esta onda não reabriu e continuam abertas:** MNT-001 (`audit.record(target='')`
em 17 call sites — o módulo `bank` faz `db.flush()` antes e está correto, inclusive em
`origin.py:230`), SIG-001 (a virada de mês apaga uma conferência recente), `scripts/check.sh` mascarando
falha de frontend com `|| true` (por isso rodei cada etapa individualmente neste gate).

---

## O que precisa de decisão do fundador antes do PR

### 1. AC9 / 360px — **e há uma contradição no repositório sobre o que ele bloqueia**

Três documentos, duas leituras:

| Fonte | Diz |
|---|---|
| `controle-bancario-onda2-design.md` §12, **F-D8** | *"**Bloquear o release** desta onda no aceite em 360px"* |
| `CLAUDE.md`, dívida da Onda 1 | *"aceite manual pendente; **bloqueia release, não bloqueia merge**"* |
| `docs/stories/8.13.story.md` §0.2, validação do @po | *"O AC9 permanece **bloqueante de merge** — é o veredito F-D8 do fundador, não recomendação"* |

O @po leu "release" como "merge". **A decisão precisa ser dele, e é binária:**

- **(a) Merge com pendência declarada.** O código foi auditado estruturalmente pelo @dev
  (`EscolhaDaBaixa compact` está dentro do `<div className="fixed inset-x-0 bottom-0 …">`;
  `overflow-x-auto` preservado em `PagarPage`), a suíte de co-localização passa, e o F-D8 literal fala
  de **release**. O aceite físico vira gate de deploy, não de merge.
- **(b) Bloquear o merge.** Foi o que o @po escreveu, e o histórico dá razão a ele: **dois PRs de fix
  de campo (#56, #58) já foram pagos por exatamente esta lacuna**, um deles com uma conta real marcada
  paga sem o dono conseguir ver o checkbox.

**Minha recomendação: (a), com condição.** O aceite físico é irreproduzível neste ambiente (sem
aparelho, sem stack de dev viva) e nenhuma sessão futura de agente vai resolvê-lo — adiar o merge
adia por tempo indeterminado uma onda de 18 commits que corrige um bug real em produção (a comparação
degenerada da 8.20). Mas **(a) só é honesto se o aceite virar gate de deploy com dono e data**, e não
mais uma linha de dívida no `CLAUDE.md`. Se não houver esse compromisso, **(b)** é a leitura certa e
eu a apoio.

**E, seja qual for a escolha, os três documentos precisam passar a dizer a mesma coisa.** A
contradição atual é o defeito que a própria onda batizou: *"quando o mesmo conceito aparece com dois
vocabulários, o problema quase nunca é redação"*.

### 2. BANK-002 — corrigir antes do merge?

**Recomendo sim, e é barato:** é uma linha de guarda + um teste, espelhando o que a 8.15 já fez do
outro lado. Deixá-lo para depois significa mergear uma onda cuja métrica primária pode ser
silenciosamente corrompida por uma rota HTTP aberta — na janela em que o fundador vai rodar o mutirão
das 45 e começar a agendar pagamentos.

Se o fundador preferir mergear e corrigir em seguida, o risco é contido enquanto a UI não expuser o
gesto (hoje não expõe) — mas o caminho da lista velha (§BANK-002, "alcançabilidade") continua aberto e
não deixa rastro visível para o dono.

### 3. F-D12 continua frágil, e agora tem um lugar para ser visto

O gate abre no primeiro ciclo pós-Onda 2 **porque hoje há 0 rendimentos lançados** — um contador em
zero, não uma propriedade estrutural. O produto já degrada com honestidade (a nota do bloco 4 nomeia
a Onda 2b, verificado por sonda). **Nenhuma ação necessária agora**; registrado para que a leitura do
primeiro ciclo não seja feita sem olhar `rendimentos_sem_perna_bancaria`.

---

## Ambiente e reprodutibilidade

Todos os números deste artefato foram **executados nesta sessão**, não copiados:

```
apps/api $ .venv/Scripts/python.exe -m pytest -q -m "not rls_e2e"
1451 passed, 1 skipped, 38 deselected, 3428 warnings in 323.67s (0:05:23)

apps/api $ .venv/Scripts/python.exe -m pytest -q -m "rls_e2e"
38 passed, 1452 deselected in 54.62s

$ pnpm --filter @e1p/web test -- --run
Test Files  53 passed (53)
     Tests  476 passed (476)
  Duration  21.13s

apps/api $ .venv/Scripts/python.exe -m ruff check .
All checks passed!

$ pnpm --filter @e1p/web exec tsc --noEmit        # sem saída
$ pnpm --filter @e1p/web lint                      # sem saída

apps/api $ .venv/Scripts/python.exe -m alembic heads
0062 (head)
```

**Sondas adversariais.** 11 testes de ataque foram escritos, executados (10 passaram, 1 falhou
expondo o BANK-002) e **removidos do repositório** — um teste que documenta um bug em aberto deixaria
a suíte vermelha. O arquivo está preservado fora do repo; a reprodução do BANK-002 está transcrita
integralmente na seção correspondente e cabe num teste de ~20 linhas quando o fix entrar.

**Mutações.** Os três arquivos mutados (`bank/service.py`, `financial_intelligence/projection.py`,
`bank/reconciliation.py`) foram salvos por **cópia** antes e restaurados por **cópia** depois — nunca
`git checkout`, pela lição registrada nesta sessão. Hashes conferidos:
`de88b176…`, `5aee059e…`, `d689d2df…`, idênticos aos originais. `git status --short` limpo ao fim.

**Não foi feito, e é limitação declarada:** validação visual em ~360px (sem dispositivo e sem stack de
dev viva neste ambiente); os 3 agentes de QA do `CLAUDE.md` §5 (sem ferramenta de spawn); nenhum
código de produção foi alterado.

---

## Condições para virar PASS

1. **BANK-002 corrigido** — guarda em `cancel_payable` + teste de regressão + o sexto caminho de
   mutação na lista do design §3.3.
2. **AC9/360px decidido pelo fundador** — e os três documentos alinhados na mesma leitura.
3. **CR-1 corrigido** — o gate da proibição §6 precisa medir alguma coisa.

Os demais achados (IDX-001, SIG-002, UX-002, DOC-002, MNT-002, DEAD-001, DOC-003) são **dívida
nomeada** e não bloqueiam, desde que entrem no `CLAUDE.md` com o mesmo grau de detalhe das dívidas da
Onda 1 — em particular **SIG-002 + UX-002 juntos**, porque um cria a condição que o outro explora.
