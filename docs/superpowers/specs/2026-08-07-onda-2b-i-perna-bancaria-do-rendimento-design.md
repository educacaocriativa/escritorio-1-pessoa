# Onda 2b-i — a perna bancária do rendimento (o termo P3 fecha)

> **Data:** 2026-08-07 · **Epic:** 8 (Controle Bancário Nativo) · **Onda:** 2b, primeira metade
> **Precede:** Onda 2b-ii (`principal_cents` derivado + backfill sob `FORCE RLS`)
> **Referência normativa:** `docs/prd/epic-8-controle-bancario.md` §3.1.2 (pré-condição do gate),
> §5 (roadmap), §"Onda 2b" (escopo original de cinco entregáveis)

---

## 1. Por que esta onda existe agora

A métrica primária do Epic 8 é `|divergencia_cents|` por conta, e ela só pode ser **lida** num ciclo
de conferência que satisfaça a pré-condição do gate (§3.1.2): não existe evento conhecido pelo e1p
que moveu dinheiro numa conta real do dono sem ter gerado o `bank_transaction` correspondente.

Quatro termos decidem isso. **P3** — rendimento de aplicação sem perna bancária — é o único que o
dono **não consegue corrigir com trabalho nenhum**. Ele fecha na Onda 2b, e em mais lugar nenhum.

A `Charge` sintética de rendimento (`investments/service.py`, Story 5.6) nasce `status=paid`,
`external_ref="investment:<account_id>"`, e **sem** `transaction_id` e **sem** `bank_account_id` —
ambos NULL por omissão, verificado em `apps/api/app/modules/investments/service.py:164-177`. O
predicado de P3 é o complemento literal do `_not_investment_yield()` de P2, então **todo** rendimento
lançado cai em P3. Enquanto P3 for não-vazio numa janela, o gate daquele ciclo não abre — nenhuma
onda é liberada nem morta.

**A decisão F-D12 (2026-07-30) segue válida e continua frágil.** Ela concluiu que a 2b não é
pré-requisito da leitura do gate, apoiada numa medição de produção: 1 conta de investimento
cadastrada, **0 rendimentos lançados**. O próprio PRD registra a fragilidade: *"no dia em que o
fundador lançar o primeiro rendimento, P3 deixa de ser vazio e a leitura do gate passa a depender da
Onda 2b — sem aviso"*. O contador continua em zero em 2026-08-07 (confirmado pelo fundador; ver
§7, Suposição S1).

**A consequência de oportunidade, e é ela que justifica o "agora":** enquanto P3 for zero, esta onda
**não tem rendimento legado para ligar a movimento nenhum**. O backfill de `yield → bank_transaction`
é vazio hoje e cresce a cada rendimento lançado. Essa janela não reabre.

### 1.1 O que NÃO é verdade, e por que está escrito aqui

A hipótese que originou este design dizia que o termo P3 **falha em silêncio**, anunciando-se ao dono
como *"continue corrigindo lançamentos"*. **Isso é falso, e a proteção foi construída de propósito:**
é a Story 8.16 AC7, em produção. P3 tem contador próprio e frase própria, deliberadamente separada da
de P1/P2 (`apps/api/app/modules/bank/reconciliation.py:508-514`):

> *"N rendimentos de aplicação deste período (R$ X) ainda não geram movimento bancário. A divergência
> abaixo **inclui** esse valor. Este termo só fecha na Onda 2b — não há o que corrigir à mão."*

Amarrada por teste dos dois lados, inclusive por mutação: `apps/api/tests/test_bank_reconciliation_report.py:1433`,
`apps/web/src/features/financeiro/conferencia.test.ts:441`, e `:448` afirmando o contrário para a nota
de P1/P2 (que **não** pode dizer "Onda 2b").

Está registrado porque a spec precisa dizer o que **já** protege, senão a 2b-i o reconstrói.

---

## 2. O achado que muda o escopo desta onda

**O contador de P3 não verifica se existe perna bancária.**
`apps/api/app/modules/receivables/service.py:990-998`:

```python
row = db.execute(
    select(func.count(), func.coalesce(func.sum(Charge.amount_cents), 0)).where(
        ~_not_investment_yield(),
        Charge.paid_at.is_not(None),
        Charge.paid_at >= de,
        Charge.paid_at < ate,
    )
).one()
```

Nenhum join, nenhum `NOT EXISTS` contra `bank_transactions`. A função se chama
`contar_rendimentos_sem_perna_bancaria` e o nome promete um filtro que o corpo não tem.

**Hoje é inofensivo, por uma razão exata:** pré-2b, nenhum rendimento tem perna, então *"todos os
rendimentos"* e *"os rendimentos sem perna"* são o mesmo conjunto. **No dia em que a 2b ligar o
movimento, os dois conjuntos se separam** — e P3 seguiria contando os rendimentos que agora *têm*
perna. O gate não abriria mesmo depois da onda entregue, e a nota continuaria dizendo *"este termo só
fecha na Onda 2b"* sobre uma onda já fechada.

O único teste que toca a função (`test_bank_reconciliation_report.py:1540`) afirma que ela é
`callable`. Nada mata essa mutação, porque o membro que a mataria — um rendimento **com** perna — é
inconstruível antes desta onda.

**Portanto a correção do predicado é entregável desta onda, não da 2b-ii.** Sem ela, os outros dois
entregáveis não produzem o efeito que os justifica.

---

## 3. Escopo

### 3.1 Entra

| # | Entregável |
|---|---|
| **E1** | `investment_accounts.bank_account_id` — ligação 1:1 com a `bank_account` `kind='investment'`, **mais a superfície mínima para o dono criar o vínculo** (campo no formulário da aplicação). `investment_accounts` **não** é absorvida (é faceta de produto) |
| **E2** | `register_yield` chama `sync_origin_movement(source='yield')` — movimento nascido conciliado, mesma transação, sem jamais tocar `mark_paid`/`build_transaction` |
| **E3** | O predicado de P3 passa a honrar o próprio nome (`NOT EXISTS`), e a frase da nota deixa de nomear uma onda |

### 3.2 Não entra — vai para a 2b-ii

`principal_cents` derivado; **o backfill sob `FORCE ROW LEVEL SECURITY`** (o item de maior risco do
épico inteiro, §"Onda 2b" do PRD); `update_account` rejeitando (409) a edição de `principal_cents`;
extrato da aplicação no `InvestimentosPage`.

**Por que partir.** Só E1 e E2 tocam o gate; o item mais arriscado do épico não é nenhum dos dois.
O PRD já separou a 2b da Onda 2 exatamente com esse argumento — *"acoplar os dois adiaria o urgente
pelo arriscado"*. Manter o backfill colado ao destravamento da métrica primária refaz o acoplamento
que o épico desfez uma vez.

### 3.3 Direção de import — pré-decidida, não escolhida aqui

`apps/api/tests/test_money_planes.py:261` já registra que a ligação acontece *"do lado de
`investments`, que **pode** importar `bank`"*. `bank → investments` segue proibido por dois gates
(varredura AST + texto cru). **Esta onda não move nenhum dos dois.**

`receivables → bank` também já é aresta existente (a 8.15 cria movimento pelo mesmo
`sync_origin_movement`), então E3 não abre aresta nova.

---

## 4. Desenho

### 4.1 E1 — a ligação 1:1

**Migration `0075`** (head atual verificado: `0074_bank_opening_balance_is_known`): adiciona
`investment_accounts.bank_account_id` nullable + índice único parcial
(`WHERE bank_account_id IS NOT NULL`), para que duas aplicações não apontem à mesma conta bancária.

> ⚠️ **A migration não executa `UPDATE` nenhum** — só `ADD COLUMN` e `CREATE INDEX`. É o que a mantém
> **fora da armadilha do `FORCE ROW LEVEL SECURITY` da migration 0046** (`UPDATE` sem a GUC filtrado a
> zero linhas, em silêncio, e o SQLite dos testes não pega). O backfill do épico continua sendo um só,
> e ele é da 2b-ii.

> ⚠️ **O head do alembic se reconfere no merge, não só na escrita.** Colisão de revision entre branches
> paralelas já aconteceu neste repositório.

**Validação do alvo:** a `bank_account` apontada precisa existir no tenant, ter `kind='investment'` e
não estar arquivada. Conta arquivada → 409 reaproveitando `_CONTA_ARQUIVADA_MSG`, que já existe e já
diz a coisa certa. Conta de outro tenant → **404** pela RLS fail-closed (`bank_service.get_account`),
nunca 409: 409 confirmaria a existência da linha.

**O vínculo da aplicação que já existe em produção é um clique do dono**, não um backfill — há uma
conta de investimento cadastrada (§7, S2).

### 4.2 E1b — `register_yield` sem vínculo: 409 acionável

`register_yield` sobre uma aplicação com `bank_account_id IS NULL` responde **409** no formato
acionável que a 8.12 fixou:

```python
detail = {"acao": ACAO_CADASTRAR_CONTA, "mensagem": SEM_CONTA_VINCULADA_MSG}
```

**A mensagem, escrita aqui para não ser inventada na implementação** (Art. IV), no molde da
`SEM_CONTA_MSG` de `payables`:

> *"Para registrar o rendimento o e1p precisa saber em qual conta o dinheiro entrou — é isso que faz
> o movimento aparecer no seu extrato e a conferência valer alguma coisa. Vincule esta aplicação à
> conta bancária dela uma vez e o rendimento segue normalmente."*

**Por que 409 e não degradação graciosa.** Isto põe P3 em zero **por construção** — o mesmo mecanismo
pelo qual a 8.12 zerou P1 (a coluna virou obrigatória, a população esvazia sozinha e não depende da
disciplina de ninguém).

A alternativa seria a degradação graciosa da Onda 3 (*"nada acontece, nada quebra"*). Ela é certa
**lá** e errada **aqui**, e a diferença é quem está na sala: o payout é disparado pelo sistema, sem
humano na tela a quem perguntar. O rendimento é o dono digitando um valor agora — existe alguém para
quem pedir a conta, e o 409 acionável é o padrão do épico para pedir. Degradar aqui deixaria P3
dependendo de o dono lembrar de vincular.

**Custo aceito, declarado:** o dono cuja aplicação não está cadastrada como conta bancária é barrado
de lançar rendimento até cadastrá-la. O 409 traz a ação, então é um desvio de um passo, não um beco —
e `kind='investment'` existe desde a Onda 1, não há nada a construir para ele obedecer.

**Terceira cópia de `ACAO_CADASTRAR_CONTA`.** A string já vive duplicada de propósito em `payables` e
`receivables`, com a sincronia garantida **por teste** em vez de import
(`receivables/service.py:97-105`). `investments` vira a terceira, e o teste de sincronia passa a
comparar as três. Mesma decisão registrada, um membro a mais — **não** é acoplamento novo.

### 4.3 E2 — o movimento

```python
sync_origin_movement(
    db, tenant_id=tenant_id, actor=actor,
    source=SOURCE_YIELD,
    origin_id=charge.id,
    bank_account_id=acc.bank_account_id,
    posted_at=date,
    amount_cents=amount_cents,   # crédito: o sinal vem da tabela de origem (Charge = +1)
    description=f"Rendimento de aplicação: {acc.name}",
)
```

Chamado **antes** do `db.commit()` que já existe em `register_yield` — `sync_origin_movement` não
commita, então *"na MESMA transação"* se sustenta sem nada novo. Nasce `status='matched'`, pelo ramo
*ausente → cria*. A garantia **IV1 da Story 5.6** é reafirmada e não relaxada: nunca `mark_paid`,
nunca `build_transaction`, nenhum `Transaction`/`PlatformEarning`.

`SOURCE_YIELD` **já está em `SOURCES_SISTEMA`** (`bank/models.py:161-167`). Como nenhuma regra do
repositório é escrita contra um `source` solto — toda regra pergunta pelo conjunto —, todas elas já
cobrem `yield` sem uma linha de mudança.

**`origin_id = charge.id`, sem sufixo.** Perna única, então o `origin_id` **é** o id
(`bank/transfers.py:18`). A idempotência vem do índice único parcial `uq_bank_transactions_origin`:
um retry não credita duas vezes.

**`posted_at = date` — a escolha com um resíduo declarado.** O `date` do rendimento é documentado como
competência (DRE) e aqui passa a servir também de data de caixa. Fica alguma imprecisão: o dono lança
"rendimento de julho" com competência 31/07 e o banco creditou 01/08 — o movimento cai um dia antes do
extrato.

Conviver com isso é preferível a pedir uma segunda data no formulário. A alternativa `paid_at::date`
(o instante do registro) erra **sempre que o dono lança com qualquer atraso**, e erra mais; um segundo
campo resolveria os dois, mas é atrito mensal num formulário onde o dono copia um número do app do
banco, para um ganho sem consumidor. O desalinhamento de um dia é o **termo 3** da decomposição da
divergência (*"erro de data"*), classificado no PRD como resíduo estrutural e um dos dois que a banda
de tolerância `max(R$ 50, 0,5%)` existe para absorver.

> **E — isto é o que torna a escolha barata — com E3 entregue, a data deixa de ter poder sobre o
> gate.** O `NOT EXISTS` pergunta *"existe perna?"*, não *"a perna caiu nesta janela?"*. Se a data
> fosse o eixo do termo, esta seria uma decisão de gate; do jeito que fica, é só de conferência.

**Data futura: 422.** `bank/transfers.py:185` exige explicitamente que a 2b **decida** isto em vez de
copiar a forma da transferência. A decisão: recusar, e a razão **não** é a mesma da transferência. É
que um rendimento que ainda não caiu não é um rendimento; e, ao contrário de uma `Payable` com data
futura, ele não teria para onde ir — não existe estado `scheduled` para rendimento, nem superfície
onde apareceria, nem caminho de promoção. Aceitá-lo inventaria a quarta semântica de agendamento que
o Art. IV proíbe.

**Fora de escopo, declarado e não esquecido:** o ramo *origem desliquidada → apaga* de
`sync_origin_movement` fica **inalcançável** para `source='yield'`, porque não existe caminho de
estorno ou exclusão de rendimento hoje (`investments/router.py` só expõe `register_yield`). Vai na
docstring, para quem reencontrar o ramo morto na 2b-ii não achar que foi omissão.

### 4.4 E3 — o predicado de P3, e a frase da nota

Acrescentar ao `where` de `contar_rendimentos_sem_perna_bancaria`:

```python
~select(BankTransaction.id).where(
    BankTransaction.source == SOURCE_YIELD,
    BankTransaction.origin_id == Charge.id,
).exists()
```

**A frase da nota deixa de nomear uma onda.** Com o 409 do §4.2, todo rendimento novo nasce com perna;
somado a P3 = 0 hoje, P3 fica **zero por construção**. A nota vira inalcançável — e a frase atual
(*"Este termo só fecha na Onda 2b"*) seria mentira dita depois da 2b entregue.

**Decisão: manter contador e nota, reescrevendo a frase para nomear a causa em vez da onda** — a
ação passa a ser *vincular a aplicação a uma conta bancária*. Se a nota algum dia disparar, não será
mais uma onda faltando: será linha legada ou defeito, e ela tem de dizer o que fazer. Apagar contador
e nota é mais limpo e é a opção rejeitada, porque a 2b-ii mexe justamente nesses dados e um termo
apagado não avisa se eles voltarem inconsistentes.

---

## 5. Como se prova que isto não é vácuo

**O teste central:** *um rendimento COM perna não conta em P3*. Esse membro é hoje **inconstruível**,
e é exatamente por isso que o defeito do §2 existiu — nenhum teste podia pegá-lo. Depois desta onda
ele é construível.

**Mutações que os testes têm de matar:**

| # | Mutação | Teste que deve quebrar |
|---|---|---|
| M1 | Remover o `NOT EXISTS` de `contar_rendimentos_sem_perna_bancaria` | rendimento com perna volta a contar em P3 |
| M2 | Trocar `source == SOURCE_YIELD` por outro `source` no `NOT EXISTS` | idem |
| M3 | Remover o 409 de `register_yield` sem vínculo | rendimento sem perna passa a ser criável |
| M4 | Trocar `posted_at=date` por `posted_at=paid_at::date` | movimento cai na janela errada |
| M5 | Aceitar data futura em `register_yield` | 422 deixa de sair |

**Cobertura de invariante:** `test_invariante_do_trilho.py` e `test_money_planes.py` continuam
passando sem edição — se algum precisar de ajuste, isso é sinal de que a onda passou do escopo, não
de que o gate estava apertado demais.

**E2E RLS no Postgres real** obrigatório para o vínculo cross-tenant (404, não 409).

### 5.1 Alerta de processo — três asserções mudam de propósito

Três testes hoje afirmam que a nota contém `"Onda 2b"`:

- `apps/api/tests/test_bank_reconciliation_report.py:1433`
- `apps/web/src/features/financeiro/conferencia.test.ts:441`
- `apps/web/src/features/financeiro/ConferenciaPage.test.tsx:528`

A reescrita da frase (§4.4) os quebra. **Ajustar asserção para fazer teste passar é a manobra que
esconde regressão**, então a story precisa declarar essas três mudanças **antes** de o `@dev` abrir o
arquivo, com a razão. Sem isso, a mudança é indistinguível de um "consertando os testes".

`conferencia.test.ts:448` — que afirma que a nota de P1/P2 **não** contém "Onda 2b" — permanece
válida e **não** se toca.

---

## 6. Ordem de implementação

**E3 é entregue em duas partes separadas na ordem** — o predicado abre a sequência, a frase da nota a
fecha. Isso é deliberado: o predicado é a definição executável do resultado, e a frase só pode ser
reescrita depois que o comportamento que ela descreve existir.

1. **E3, parte predicado — primeiro, com o teste falhando** — o `NOT EXISTS` e o teste do
   rendimento-com-perna. O teste não tem como passar ainda (o membro é inconstruível), o que o torna a
   definição executável do que E1+E2 precisam produzir.
2. **E1** — migration `0075`, coluna, índice único parcial, validação do alvo, e o campo de vínculo no
   formulário da aplicação.
3. **E1b** — o 409 acionável, a mensagem do §4.2, e a terceira cópia sincronizada por teste.
4. **E2** — a chamada a `sync_origin_movement`, o 422 de data futura, e o teste de (1) passando.
5. **E3, parte nota (§4.4)** — a frase reescrita e as três asserções do §5.1.

---

## 7. Suposições abertas e riscos

| # | Suposição | Se for falsa |
|---|---|---|
| **S1** | **P3 = 0 em produção hoje** (2026-08-07). Vem de confirmação do fundador, **não** de consulta ao banco — ao contrário da medição do F-D12, que foi feita no banco. A produção foi zerada em 2026-08-05 | O desenho **não muda**. Muda o enquadramento (destravar a métrica vs. prevenir) e aparece um backfill de rendimento legado → `bank_transaction` que hoje não existe. **Medir antes de abrir a primeira story fecha isto por R$ 0** |
| **S2** | Existe uma `bank_account` `kind='investment'` cadastrada para vincular | O dono cadastra uma; o 409 acionável já o leva lá. Não muda o desenho |
| **S3** | O head do alembic ainda é `0074` no momento do merge | Renumerar a migration. Reconferir **no merge**, não só na escrita |

**Risco residual:** nenhum código foi executado durante este design — ele é inteiramente leitura de
código. As citações `arquivo:linha` valem para `main` @ `c46b79f`.

---

## 8. Rastreabilidade

| Item | Origem |
|---|---|
| Pré-condição do gate, termos P1..P4 | PRD §3.1.2 |
| P3 fecha na Onda 2b | PRD §3.1.2, tabela dos quatro termos |
| Fragilidade do F-D12 | PRD §3.1.2, bloco F-D12 |
| Escopo original de cinco entregáveis da 2b | PRD §"Onda 2b — Aplicação como conta" |
| Backfill é o item de maior risco do épico | PRD §"Onda 2b", nota ⚠️ |
| Nota do bloco 4 nomeia a onda (AC7) | Story 8.16; `bank/reconciliation.py:479-514` |
| `sync_origin_movement` como ponto único de escrita | Story 8.9; PRD item 2.4 |
| 409 acionável `cadastrar_conta` | Story 8.12 AC9; `payables/service.py:79-119` |
| Ligação se faz do lado de `investments` | `tests/test_money_planes.py:261` |
| "NÃO copie a forma da transferência sem decidir" | `bank/transfers.py:185` |
| IV1 (nunca `mark_paid`/`build_transaction`) | Story 5.6 |
