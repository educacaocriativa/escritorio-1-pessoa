# Onda 3 — o payout da Carteira fecha o circuito (o termo P4 zera)

> **Épico:** 8 — Controle Bancário e Conferência
> **Data:** 2026-08-09 · **Base:** `main @ a6e7e9a` (PR #102, Onda 2b-ii) · **head do alembic:** `0076`
> **Docs-mãe:** `docs/architecture/controle-bancario-design.md` §1.2, §1.3, §6.5, §6.6 ·
> `docs/architecture/controle-bancario-onda2-design.md` §1386 (os quatro termos do gate) ·
> `docs/prd/epic-8-controle-bancario.md`
> **Antecessoras diretas:** Onda 2 (a Regra da Origem), Onda 2b-i (P3), Onda 2b-ii (principal derivado)

---

## 0. O que esta onda entrega, em uma frase

O saque da Carteira deixa de ser uma troca de status sem testemunha e passa a **existir como fato**
(tabela `payouts`) que **escreve o movimento bancário na mesma transação** — fechando o último dos
quatro termos da pré-condição do gate do épico.

E, com P4 zerado, a métrica primária — `|divergencia_cents|` por conta — passa a poder ser lida
**assim que houver um ciclo de uso real**. É ela que decide se as Ondas 4 (import OFX) e 5 (matcher)
valem o custo, e a 4 é a onda cara, a única com dependência externa perpétua.

### 0.1 O que esta onda NÃO entrega

- **Não** existe payout real: nenhum TED/Pix sai de lugar nenhum, nenhum KYC é feito. O movimento
  bancário registra o **evento contábil** (§1.2 do design-mãe), não uma transferência executada.
- **Não** existe estorno de payout, e a ausência é assumida (§5.4).
- **Não** toca `platform_earnings`. A dívida do vínculo `platform_earnings → transaction` — que
  bloqueia a Onda 5 e matou o estorno de Contas a Receber — continua exatamente onde está. Esta onda
  não a agrava e não depende dela.
- **Não** implementa a Onda 4 (import OFX). O enriquecimento do movimento sintético pelo crédito real
  do extrato (§6.6 do design-mãe, AC3 da antiga Onda 6) é da Onda 4, e é lá que será verificado.

---

## 1. O achado que define o escopo: o payout não tem identidade

`request_payout` (`apps/api/app/modules/wallet/service.py:228`) hoje:

1. seleciona as `Transaction` com `status='available'` (`FOR UPDATE`),
2. soma `net_cents`,
3. vira todas para `withdrawn`,
4. grava `audit.record(..., action="wallet.payout", target=str(total))` — o **valor**, não um id,
5. commita e devolve `{"amount_cents", "transactions"}`.

**Não sobra linha nenhuma representando "o saque de 04/08".** O dono vê o saldo sumir e não consegue
listar o que sacou, quando, nem para onde.

Isso não é só uma lacuna de produto: é o que **impede** a Onda 3 de existir na forma das outras.
`bank.origin.sync_origin_movement` exige `origin_id` apontando para *"o lançamento que o gerou"*, com
índice único parcial `(tenant_id, source, origin_id)` e ciclo de vida espelho (Regra da Origem (b) e
(c)). Sem entidade, não há para onde apontar.

**Decisão: criar a entidade `Payout`** (§3). As duas alternativas consideradas e recusadas:

| Alternativa | Por que não |
|---|---|
| Um movimento por `Transaction` sacada (`origin_id = transaction.id`, zero migration, 1:1 real) | O banco vê **um** crédito — um TED. O e1p mostraria N linhas no extrato. A divergência nasceria garantida no momento de casar com o OFX (Onda 4), que é exatamente o que o épico existe para evitar. |
| UUID solto, sem entidade (zero migration) | `origin_id` apontaria para lugar nenhum — o defeito **MNT-001** (`audit.record(target='')` em 17 call sites) já registrado como dívida do épico, reintroduzido de propósito. E sem linha de origem os ramos "move" e "apaga" da Regra da Origem (c) ficam inexequíveis. |

---

## 2. Arquitetura: como os dois planos se tocam sem se misturar

### 2.1 O problema, escrito com precisão

A Regra dos Planos (§1.3b) é unidirecional: `bank` **pode** importar `wallet`; `wallet` **nunca**
importa `bank`. O ponto de contato (§1.2) — o payout — é o **único** write que atravessa a fronteira.

O design-mãe §6.6 mandou fazer isso pelo barramento `core/events`. **Essa instrução é anterior à
Onda 2 e não sobrevive ao contato com ela.** Três fatos:

1. `core/events.emit` **engole exceção de assinante por contrato** (`app/core/events.py:29`):
   *"o fato já aconteceu e foi commitado; reações são best-effort"*. O próprio docstring manda:
   *"Reações que PRECISAM ser confiáveis devem ir para a fila durável (SQS), não para este
   barramento."*
2. Os dois assinantes existentes (`notifications/service.py`, `funnels/automation.py`) documentam,
   nos seus próprios cabeçalhos, que recebem o evento **depois** do commit.
3. A Regra da Origem (a) exige *"exatamente um `bank_transaction`, **na mesma transação** do
   evento"*. As quatro origens já ligadas — `payable`, `charge`, `transfer`, `yield` — são chamada
   direta, síncrona, sem commit intermediário.

Pelo barramento como ele é, um payout commitaria com o movimento bancário faltando **e sem erro em
lugar nenhum**. A divergência cresceria sem explicação, contaminando precisamente a métrica que esta
onda existe para tornar legível. É a família de defeito que o épico inteiro combate.

### 2.2 A solução: o padrão de composição que a casa já usa duas vezes

`app/main.py:98-155` resolve duas travessias estruturalmente idênticas:

- **Story 8.17 AC6** — a guarda de contagem dupla: `bank` precisa consultar `payables`, e o gate
  proíbe o import.
- **Story 8.16 AC7/AC8** — os termos do gate: `bank` precisa contar obrigações de negócio, mesmo
  gate, mesma proibição.

Nos dois casos: **quem precisa do serviço declara um `Protocol` e um registrador; quem o implementa
não é importado por ninguém; a fiação mora na composição (`main.py`), com verificação fail-closed no
boot.** O comentário no próprio arquivo diz por que isso não é um truque:

> *"O gate fica verde **porque a dependência sumiu**, não porque foi escondida."*

Esta onda aplica o mesmo padrão com a direção invertida — **quem declara é a Carteira**:

| Peça | Onde vive |
|---|---|
| `RegistradorDePayout` (`Protocol`) + `register_payout_registrar` + `payout_registrar_registrado()` | `app/modules/wallet/service.py` |
| A implementação | `app/modules/bank/payout.py` |
| A fiação + o fail-closed de boot | `app/main.py` (ao lado das duas irmãs) |

**Direção final de dependência:** `main → wallet`, `main → bank`, e **nada** entre os dois.

Consequências, cada uma verificável:

- `POST /wallet/payout` **não se move**. Nenhum router muda de arquivo; o front não muda de endpoint.
- `test_wallet_nao_importa_bank` e `test_wallet_nao_importa_bank_tambem_por_texto_cru` continuam
  intactos **e sem allowlist**.
- `test_bank_nao_referencia_transaction` continua **apertado**. Ele diz, no próprio docstring, que
  quem precisar do símbolo *"atualiza este teste com justificativa escrita — nunca o apaga"*.
  **Esta onda não precisa**: `bank/payout.py` recebe números e ids como argumento e nunca vê
  `Transaction` nem importa `app.modules.wallet`. O teste segue sendo sinal, e não vira allowlist.
- A exceção do registrador **propaga** (ao contrário de `emit`) e derruba a transação inteira: ou o
  saque e o movimento existem, ou nenhum dos dois.

### 2.3 O `Protocol`

```python
class RegistradorDePayout(Protocol):
    def __call__(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor: str,
        payout_id: str,
        amount_cents: int,   # POSITIVO — é entrada na conta do dono
        posted_at: date,
    ) -> DestinoDoPayout | None: ...
```

`DestinoDoPayout` é um par `(bank_account_id, bank_transaction_id)`.

**`None` significa "não há conta principal ativa"**, e é **valor de retorno, não exceção**. A razão é
de produto: assim o texto do 409 pertence à Carteira, que é quem tem o usuário na frente, e o módulo
`bank` não precisa conhecer o vocabulário da tela do outro plano. Exceção continua sendo exceção —
`BankError` de dentro do `sync_origin_movement` propaga normalmente (§5.3).

### 2.4 O fluxo, na ordem exata

```
request_payout(db, tenant_id, actor):
  1. txs = Transaction[status='available'] FOR UPDATE ;  total = Σ net_cents
     └─ total == 0  ⇒  WalletError 409 "não há saldo disponível para saque"
  2. payout_id = _uuid()   ;   paid_on = hoje_do_tenant(db)
  3. destino = registrador(db, payout_id=payout_id, amount_cents=+total, posted_at=paid_on, …)
     └─ None  ⇒  WalletError 409, com a ação nomeada  (§4.1)
  4. payout = Payout(id=payout_id, amount_cents=total, paid_on=paid_on, actor=actor,
                     bank_account_id=destino.bank_account_id,
                     bank_transaction_id=destino.bank_transaction_id)
     db.add(payout) ; db.flush()          ← nasce COMPLETO, nunca num estado que o NOT NULL recuse
  5. for t in txs: t.status = 'withdrawn' ; t.payout_id = payout.id
  6. audit.record(..., action="wallet.payout", target=payout.id)   ← e não mais str(total)
  7. db.commit()                                                   ← o ÚNICO commit
```

**O id é gerado em Python antes do `INSERT` (passo 2), e é isso que sustenta o `NOT NULL` do §3.1.**
Os ids do projeto são `default=_uuid` Python-side, então o `payout_id` existe antes da linha — o
registrador pode escrever `origin_id` apontando para uma linha que ainda não foi inserida, **na mesma
transação**, porque `bank_transactions.origin_id` **não é FK**: é coluna genérica `String(64)` sob um
índice único parcial (`bank/models.py:347-350`), compartilhada por `payable`, `charge`, `transfer`,
`yield` e `payout`. Não há violação de integridade a evitar.

A ordem — destino **antes** de qualquer escrita — não é exigência de correção (tudo está na mesma
transação e um `raise` desfaz o conjunto em qualquer ordem). É exigência de **leitura**: o código
deve deixar óbvio que nada na Carteira muda antes de o destino estar garantido. Ordem que só está
certa porque existe rollback é ordem que a próxima pessoa reordena sem perceber.

`hoje_do_tenant(db)` (`settings/service.py`), nunca `date.today()` — o sistema inteiro vive no fuso do
tenant desde o PR #78.

---

## 3. Modelo de dados — migration `0077`

### 3.1 `payouts`

`Base, TenantMixin, TimestampMixin`, `id: String(36)` UUID Python-side, **RLS `FORCE`** (o padrão de
toda tabela de negócio; ver `infra/docker/initdb/01-rls-enforce.sql` e as migrations da Onda 1).

| Coluna | Tipo | Nota |
|---|---|---|
| `amount_cents` | `BigInteger`, `NOT NULL` | Dinheiro em centavos, como todo o resto. Sempre `> 0` (o caminho de total zero é recusado antes). |
| `paid_on` | `Date`, `NOT NULL` | O dia do tenant. É o `posted_at` do movimento — **o mesmo valor**, não uma segunda data que possa divergir. |
| `bank_account_id` | `String(36)`, `NOT NULL` | A conta que recebeu. **Snapshot**, não referência viva: a conta principal pode mudar depois, e o saque de agosto não pode passar a dizer que caiu na conta que virou principal em outubro. |
| `bank_transaction_id` | `String(36)`, `NOT NULL` | Cache do movimento, mesmo papel de `payable.bank_transaction_id` / `charge.bank_transaction_id` — **mas `NOT NULL`, e a diferença é deliberada.** Lá a coluna é nullable porque a conta pode legitimamente não estar liquidada ainda; aqui não existe payout não liquidado. **É a invariante da onda em forma de DDL** (§5.1). |
| `actor` | `String(36)`, `NOT NULL` | Quem pediu. |

### 3.2 `transactions.payout_id`

`String(36)`, **nullable** (todo saque anterior a esta migration é `NULL` — e continua sendo, para
sempre: não há backfill, ver §3.3).

Sem esta coluna, *"quais vendas compõem este saque"* é irrecuperável e o histórico da §4.2 mostra um
total solto que ninguém consegue conferir.

### 3.3 A migration NÃO faz `UPDATE` — e a ausência é o ponto

`0077` cria uma tabela e acrescenta uma coluna nullable. **Zero `UPDATE` sobre dado existente.**

Isso é dito explicitamente porque a pergunta volta sempre, e porque "não se aplica" só vale quando
está escrito: a armadilha do `FORCE RLS` da **0046** — `UPDATE` filtrado a zero linhas **em silêncio**
porque a migration roda como `e1p_app` sem `app.current_tenant_id`, e o SQLite dos testes não pega —
**não alcança esta migration**. Não há nada a desabilitar e restaurar.

As `Transaction` já sacadas antes desta onda ficam com `payout_id IS NULL` permanentemente. Isso é
correto e não é dívida: elas não têm saque a que pertencer, porque o saque nunca foi registrado. É a
mesma manobra da 2b-ii — **quando um backfill existiria para reconstruir histórico que ninguém pode
reconstruir com honestidade, o backfill é o caminho pior.**

---

## 4. Superfícies

### 4.1 A Carteira — o 409 ganha rosto

`FinanceiroPage.tsx:85` hoje é `await api.post("/wallet/payout")` **sem `try`**. O 409 que esta onda
cria cairia numa promise rejeitada e **nada** apareceria na tela — o botão simplesmente não faria
nada. Sem esta correção, a decisão do §4.1.1 vira um botão quebrado.

#### 4.1.1 Sem conta principal: recusa, com a ação nomeada

> **"Escolha para qual conta o dinheiro vai antes de sacar."** + link para `/financeiro/contas`.

`bank.service.primary_account(db)` devolve `None` **também** quando o tenant tem contas mas nenhuma
marcada como principal — arquivar a principal não elege sucessora em silêncio (Story 8.7 AC7). O
docstring dela já dizia por quê: *"escolher a conta de destino do dinheiro do usuário sem ele pedir é
o tipo de 'ajuda' que só se descobre quando o dinheiro já foi para o lugar errado."*

> ⚠️ **PRÉ-REQUISITO ACHADO NA REVISÃO DO PLANO, e sem ele esta decisão vira um beco sem saída:**
> `bank.service.set_primary` existe desde a Story 8.7, foi escrito explicitamente para este
> consumidor — e **não tem rota, não tem botão e não tem um único chamador**. `ContasSaldosPage`
> apenas exibe o selo `is_primary`. Hoje o dono **não consegue** eleger uma conta principal. A
> frase *"defina sua conta principal em Contas & Saldos"* o mandaria a uma tela onde a ação não
> existe, e o saque ficaria travado para sempre. Expor `POST /bank/accounts/{id}/set-primary` e o
> botão é **Task 2b do plano** e é bloqueante para esta onda.

O design-mãe §6.6 mandava **degradar graciosamente** (sem conta, o consumidor não faz nada). Esta
spec **desvia disso, e o desvio é a decisão central da onda**: um payout sem perna bancária é P4 ≠ 0,
e P4 ≠ 0 devolve a divergência ao estado de medir a própria incompletude do sistema — o erro de
método que o §8 do design-mãe registrou como *"a feature que faltava teria pedido a construção da
feature mais cara."*

O argumento que torna a recusa legítima, e que **não** valia na 2b-ii:

> O resgate bruto da 2b-ii não podia ser recusado porque **já tinha acontecido no banco** — recusar
> um fato consumado é o inverso do princípio da Onda 0. O payout é o oposto: **quem o origina é o
> e1p**, e ele ainda não aconteceu. Recusar um ato que ainda não ocorreu é legítimo; recusar um fato
> que já ocorreu não é.

E o custo real é zero: `request_payout` hoje só marca `withdrawn` — não há integração bancária nem
KYC. Bloqueá-lo não tira do dono nenhuma capacidade que ele tenha de fato.

#### 4.1.2 A borda do piso de data

`bank.service.validate_posted_at_floor` recusa (422) movimento com `posted_at <= account.opening_date`.
Um tenant que cadastra a conta hoje (com `opening_date = hoje`) e saca hoje toma esse 422, vindo de
dentro do módulo `bank`, sobre um conceito que ele não pediu.

**A Carteira traduz**, na mesma superfície do 409:

> *"Esta conta foi aberta no e1p em DD/MM. O saque precisa ser posterior a essa data — o saldo de
> abertura já contempla tudo o que aconteceu até ali."*

Deixar o 422 cru vazar seria expor o vocabulário do plano do banco num botão do plano da plataforma.

### 4.2 Histórico de saques — `GET /wallet/payouts`

Dentro da **própria Carteira** (`/financeiro`), abaixo da lista de transações. **Não** vira item de
menu: a Conferência já estabeleceu que tela nova no menu vira peso de ERP, e o histórico é consulta
episódica, não tarefa de rotina.

Cada linha: data, conta de destino, valor.

**Lista (`<ul>`), não `<table>` — e isto é normativo, não estético.** A lição medida na 2b-ii:

> Em 360px uma tabela de 3 colunas não cabe, e a saída **não** é fazer a rolagem funcionar melhor: é
> não precisar dela. O extrato da 2b-ii nasceu `<table>` com `min-w-[20rem]` dentro de
> `overflow-x-auto` — o `overflow-x` estava certo, o `flex-wrap` estava certo, e a tela mostrava
> `R$ 3.` no lugar de `R$ 3.000,00`. **Nenhuma asserção de classe CSS pega isso.**

Forma: data e conta empilhadas à esquerda num bloco `min-w-0`; valor à direita com `whitespace-nowrap`.

### 4.3 O card do Cockpit

`cockpit/service.py` passa a importar `bank.service` — direção permitida (negócio → banco), e o
módulo já importa `payables`, `receivables`, `wallet` e `crm` pela mesma porta.

`FinanceSummary` ganha `saldo_em_conta_cents: int | None` + `saldo_em_conta_origem: str` (§1.3c: todo
campo de **saldo** declara o plano de onde vem; valor `"banco"`, do vocabulário de
`app/core/money_planes.py`).

Duas correções deliberadas contra a letra do §6.5:

1. **`net_revenue_cents` NÃO ganha `_origem`.** §1.3c fala de *campo de saldo*, e faturamento não é
   saldo — o próprio §6.5 diz que aquele número está correto e não muda. Pendurar procedência nele
   seria aplicar a regra fora do alvo e ensinar a próxima pessoa a fazer o mesmo, o que transforma um
   invariante mecânico em ritual.
2. **O rótulo é a constante existente, não um sinônimo novo.** O card reusa `TOTAL_EM_CONTAS_LABEL`
   de Contas & Saldos, com gate de dois consumidores — exatamente o padrão de `contas.ROTA_MOVIMENTOS`
   da 2b-ii. Inventar "Em conta" ao lado de "Total em contas" recriaria a divergência **D-6 / UX-001**
   numa terceira tela, que é a divergência que o épico já pagou uma vez para separar.
   **`"no banco"` continua proibido fora da Projeção.**

O card mostra **todas as contas ativas** (o recorte de `TOTAL_EM_CONTAS_LABEL`), não "Disponível como
caixa": o Cockpit declara **posição**, não projeta caixa. E **nunca somado** com "Na plataforma" — as
duas parcelas ficam lado a lado, rotuladas, sem total único (§1.3c e §6.5, *"proibido um card único
somando os dois sem decomposição visível"*).

---

## 5. Invariantes, gates e testes

### 5.1 A invariante da onda, como gate de dado

> **Não existe `Payout` sem `bank_transaction_id`.**

É **P4 = 0 escrito de forma auditável**, em vez de prometido em prosa. Garantida em três camadas
independentes:

1. `NOT NULL` na DDL (§3.1) — fail-closed no banco;
2. o caminho de código não tem ramo que crie `Payout` sem destino (§2.4);
3. um teste que percorre `payouts` e falha se achar um órfão.

### 5.2 Fail-closed no boot

`test_app_nao_sobe_sem_o_registrador_de_payout`, espelho literal de
`test_bank_contagem_dupla.py::test_app_nao_sobe_sem_o_probe_de_contagem_dupla`, **mais** o teste
**estrutural** de que `main.py` invoca a verificação no nível do módulo.

O segundo teste não é redundante: *um fail-closed que ninguém invoca é um comentário* — e apagar a
chamada em `main.py` deixaria o primeiro teste verde.

*"Um erro de fiação é condição de startup, não de request"* (ratificação §C-5.2). A alternativa —
deixar o request seguir sem registrador — é a Onda 3 **desligada em produção sem ninguém saber**,
com o payout voltando ao comportamento pré-onda e a divergência crescendo em silêncio.

### 5.3 Os gates estruturais existentes: intactos, e isso vira asserção

Nenhum arquivo desta onda relaxa nenhum gate. Verificado explicitamente:

| Gate | Estado após a onda |
|---|---|
| `test_wallet_nao_importa_bank` (AST) | intacto, sem allowlist |
| `test_wallet_nao_importa_bank_tambem_por_texto_cru` | intacto |
| `test_bank_nao_referencia_transaction` | **intacto e apertado** — `bank/payout.py` não importa `wallet` nem cita `Transaction` |
| `test_bank_nao_importa_payables` / `..._investments` | não tocados |
| `test_chamadores_do_sincronizador_estao_na_allowlist` | **ganha `bank/payout.py`** — é a única mudança de gate da onda, e é uma adição prevista pelo próprio teste |

Acrescentar: assertiva de que `bank/payout.py` não cita `Transaction` — pelo mesmo motivo pelo qual o
gate irmão é redundante por AST **e** por texto cru (a mutação do re-gate da Onda 1, TEST-001, provou
que a forma evasiva passa por um e não pelo outro).

### 5.4 O ramo "apaga" é INALCANÇÁVEL, e isso é declarado

`sync_origin_movement` tem três ramos: cria, move, apaga. **Não existe estorno de payout** — nenhum
caminho leva `bank_account_id` a `None` para `source='payout'`.

Declarado, exatamente como a 2b-i declarou para o `yield`
(`investments/service.py:422`), em vez de fingir cobertura com um teste que exercita um caminho que
o produto não tem. Se um dia existir estorno de payout, ele **reativa** este ramo e precisa de teste
próprio — e da resposta para o que acontece com as `Transaction` que voltam a `available`.

### 5.5 Concorrência e idempotência

Dois payouts simultâneos: o `FOR UPDATE` já existente sobre as `Transaction` serializa (real no
Postgres, no-op no SQLite dos testes). O segundo encontra zero linhas `available` e toma 409 de saldo
zero. O índice único parcial `uq_bank_transactions_origin (tenant_id, source, origin_id)` fecha o
resto, fail-closed no banco.

### 5.6 `rls_e2e`

Um teste `pytest.mark.rls_e2e` (testcontainers, Postgres real, `alembic upgrade head` como o papel
não-superusuário `e1p_app`) que:

- exercita a **0077 de verdade** — não a versão que o SQLite finge entender;
- prova o isolamento: o payout do tenant A não aparece em `GET /wallet/payouts` do tenant B, e o
  movimento não aparece no extrato dele.

Custo medido nesta máquina: ~4s por teste.

### 5.7 Aceite visual em ~360px, medido antes do merge

Duas superfícies novas (histórico de saques, card do Cockpit) e uma alterada (a frase do 409 na
Carteira). Medição com Vite sozinho + `page.route("**/api/**")` do Playwright + `boundingBox` — **sem
backend**, conforme o método que a 2b-ii validou.

O que se mede, e não se assume:
- nenhum valor monetário cortado ou exigindo rolagem lateral para existir;
- `document.scrollWidth` da página — com a ressalva do §6.

Depois de três dívidas abertas na fila (8.13 AC9, 8.21, 2b-i) e três PRs de campo pagos (#56, #58,
#89), a 2b-ii mediu antes de mergear e achou um defeito na primeira medição. Esta onda faz igual.

---

## 6. Riscos e desvios registrados

| # | Risco / desvio | Tratamento |
|---|---|---|
| R-1 | **`request_payout` deixa de sempre funcionar.** Tenant com saldo e sem conta principal passa a ver 409. É mudança **observável** de comportamento. | Decisão do fundador (§4.1.1). Custo real zero (o saque não move dinheiro). **Ganha linha própria no `CLAUDE.md`, não nota de rodapé** — quem ler só a memória precisa saber que o botão agora pode recusar. |
| R-2 | **Desvio declarado do §6.6 do design-mãe** em dois pontos: o mecanismo (composição em vez de `core/events`) e a degradação (recusa em vez de silêncio). | Justificados em §2.1 e §4.1.1. O design-mãe é anterior à Onda 2 e ao que ela estabeleceu. |
| R-3 | O card do Cockpit e o histórico são **superfície nova no mesmo diff** que a regra nova. | Aceito explicitamente pelo fundador ao escolher o escopo. Mitigação: são **aditivos** (campo novo no schema, seção nova na página) e não alteram nenhum caminho existente — diferente do caso do `AppShell`, que era **correção de defeito pré-existente** e por isso ficou fora. |
| R-4 | A conta principal pode ser de `kind='investment'`: `set_primary` não restringe tipo. Um payout cairia numa aplicação. | **Fora de escopo, registrado.** É estranho mas não é incoerente (o dono pode querer que o saque caia na aplicação), e restringir aqui inventaria uma regra que a Story 8.7 não tem. Se virar problema, o lugar da guarda é `set_primary`, não o payout. |
| R-5 | P4 zera **por construção**, mas os outros três termos dependem de **uso real**, e a produção foi zerada em 05/08 para o sócio começar do zero. | **A leitura do gate continua bloqueada por dado, não por código.** Ver §7. |

---

## 7. O que esta onda destrava — e o que ela explicitamente NÃO destrava

Com P4 zerado, **os quatro termos da pré-condição do gate estão fechados**: P1 e P2 pela Onda 2, P3
pela 2b-i (o 409 de `register_yield`), P4 por esta.

**Isso não autoriza ler a divergência ainda.** A produção foi zerada em 2026-08-05 e o gate precisa de
um ciclo de uso real: conta cadastrada, contas pagas com conta informada, saldo declarado.

> ⚠️ **Um número medido sobre base vazia não é gate.** Foi exatamente esse erro que quase liberou a
> Onda 4 em julho (§3.1.1 do PRD, e a correção de 2026-07-30 no design-mãe). A regra de método que
> fica: *antes de usar um número como gate, pergunte o que ele mede quando o sistema está incompleto.
> Se a resposta for "mede a própria incompletude", ele não é gate — é termômetro do que ainda não foi
> construído, e vai sempre pedir mais construção.*

O que muda com esta onda é que a **obstrução deixou de ser de código**. Antes: nenhum ciclo, por mais
disciplinado, produziria número legível. Depois: um ciclo disciplinado produz.

O passo seguinte natural **não é a Onda 4** — é instrumentar/documentar o ciclo mínimo que o fundador
precisa executar para que `|divergencia_cents|` signifique alguma coisa.

---

## 8. Rastreabilidade (Artigo IV — No Invention)

| Afirmação desta spec | Origem |
|---|---|
| O payout é o único ponto de contato entre os planos 1 e 3 | design-mãe §1.2 |
| `bank` pode importar `wallet`; o contrário nunca | design-mãe §1.3b |
| Todo campo de saldo declara procedência | design-mãe §1.3c |
| Card do Cockpit com as duas parcelas, proibida a soma cega | design-mãe §6.5 |
| Payout → movimento na conta principal; degradação sem conta | design-mãe §6.6 (**desviado**, §4.1.1) |
| P4 = "payout da Carteira liquidado sem perna bancária", zera na Onda 3 | onda2-design §1386; `bank/reconciliation.py:264` |
| Regra da Origem (a)–(e) | onda2-design §2; `bank/origin.py` |
| `SOURCE_PAYOUT` já existe em `SOURCES_SISTEMA` | `bank/models.py:139,166` |
| `primary_account()` foi escrita para este consumidor | `bank/service.py:540` |
| `set_primary` num commit só, "senão o payout escolheria no par ou ímpar" | `bank/service.py:1040` |
| O front já conhece `"payout"` no vocabulário de movimentos | `apps/web/src/features/financeiro/contas.ts:207` |
| Padrão `Protocol` + registrador + fiação na composição + fail-closed | `app/main.py:98-155` (Stories 8.17 AC6, 8.16 AC7/AC8) |
| Piso de data do movimento | `bank/service.py:1125` |
| A armadilha do `FORCE RLS` em migration com `UPDATE` | `CLAUDE.md` §Epic 5, migration 0046 |
| Lista em vez de tabela em 360px | `CLAUDE.md` §Onda 2b-ii; PR #102 |
| Backfill que reconstrói o que um ato reconstrói melhor é o caminho pior | `CLAUDE.md` §Onda 2b-ii |
| `hoje_do_tenant`, nunca UTC cru | `CLAUDE.md` §6.0; PR #78 |

---

## 9. Definição de pronto

- [ ] Migration `0077` (`payouts` + `transactions.payout_id`), sem `UPDATE`, RLS `FORCE`.
- [ ] `Protocol` + registrador em `wallet/service.py`; implementação em `bank/payout.py`; fiação e
      fail-closed em `main.py`.
- [ ] `request_payout` cria o `Payout`, chama o registrador, marca as `Transaction` com `payout_id`,
      commita **uma vez**, e grava `audit.record(target=payout.id)`.
- [ ] 409 com ação nomeada sem conta principal; 409 traduzido para o piso de data.
- [ ] `GET /wallet/payouts` + histórico na Carteira, em `<ul>`.
- [ ] Card do Cockpit reusando `TOTAL_EM_CONTAS_LABEL`, com `saldo_em_conta_origem`, sem soma cega.
- [ ] Gates: invariante `Payout` sem órfão; fail-closed de boot (+ estrutural); `bank/payout.py` na
      allowlist do sincronizador; os cinco gates existentes verdes **sem relaxamento**.
- [ ] `rls_e2e` exercitando a 0077 e o isolamento entre tenants.
- [ ] Aceite em ~360px **medido**, com screenshot, antes do merge.
- [ ] `bash scripts/check.sh` — rodando as etapas individualmente (o script mascara falha de vitest
      com `|| true`, dívida conhecida).
- [ ] **Entrada no `CLAUDE.md`** (§5, passo 4 — AC obrigatório), escrita a partir do código que subiu,
      incluindo R-1 em linha própria.
