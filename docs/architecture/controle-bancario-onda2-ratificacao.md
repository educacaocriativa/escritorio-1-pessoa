# Onda 2 — Ratificação dos conflitos levantados pelos @sm

> **Autora:** Aria (@architect)
> **Data:** 2026-07-30
> **Objeto:** julgar os 7 conflitos que três @sm encontraram ao expandir a Onda 2 do Epic 8 em 11
> stories (8.9–8.19), e corrigir o design onde eles têm razão.
> **Documentos julgados:** [`controle-bancario-onda2-design.md`](controle-bancario-onda2-design.md)
> (o meu), [`controle-bancario-design.md`](controle-bancario-design.md) (o design-mãe),
> [`0003-controle-bancario-nativo.md`](../decisions/0003-controle-bancario-nativo.md).
> **Não edito `docs/stories/*.md`.** Onde a decisão muda uma story, a instrução está escrita aqui,
> nomeando arquivo, AC e Task.
> **Não implemento, não escrevo migration.**

---

## 0. Placar

| # | Conflito | Veredito | O que muda |
|---|---|---|---|
| **C-1** | A pré-condição do gate nunca é satisfeita (§9.3 × §4.9) | **RATIFICADO COM AJUSTE** | §9.3 reescrita com 4 termos e predicado executável. **A leitura do @sm está certa e ainda assim é insuficiente**: a `Charge` sintética de rendimento reintroduz o mesmo bug (§1.1 abaixo) |
| **C-2** | A regra do agendamento vencido é código morto (§9.2.1 × §4.2.3) | **RATIFICADO COM AJUSTE** | População do @sm aceita; **o texto e o nome do sinal mudam** — o adjetivo "agendado" não sobrevive ao worker e eu não deveria tê-lo vendido |
| **C-3** | `origin_id` estreito para transferência (§8 × §3.2) | **RATIFICADO COM AJUSTE** | Forma `:out`/`:in` ratificada; largura **`VARCHAR(64)`**, não 48; e `origin_id` é redefinido como **chave de origem**, não id do lançamento |
| **C-4** | `bank_audit` NÃO existe | **REJEITADO (a referência), SUBSTITUÍDO** | O script sai dos três documentos como ativo existente. A obrigação da Onda 2 vira **teste**, não script. O script fica como pré-requisito da **Onda 5** |
| **C-5** | `create_transaction` × gate `bank ↛ payables` (§7b × §3.5) | **RATIFICADO COM AJUSTE** | Porta de saída na composição ratificada; **fail-closed migra para boot-time**; e o `Protocol` **não pode devolver `Payable`** |
| **C-6** | Ninguém libera `posted_at` futuro | **RATIFICADO** | Corte por origem confirmado e normativo. Corte por **`source`**, nunca por booleano do chamador. Externo (OFX) **continua recusando futuro** — confirmado com a razão escrita |
| **C-7** | Contagem dupla no dia agendado | **RATIFICADO** | O recorte fecha. Não abre buraco simétrico. Mas ele depende de um acoplamento invisível que precisa virar asserção (§C-7.3) |

**Achados meus, além dos vereditos** (nenhum dos três @sm os tinha):

- **A-1 (grave).** A leitura do @sm para C-1 **não abre o gate para nenhum tenant que use o módulo
  Investimentos** — a `Charge` sintética de rendimento cai na população dele. §C-1.
- **A-2.** O `Protocol` do C-5, como está escrito na 8.17 Task 2, **reprova o próprio gate que ela
  existe para respeitar**. §C-5.
- **A-3.** O 422 de `posted_at` futuro para transferência (8.18 AC7) **não funciona onde a story o
  põe** depois que a 8.14 liberar o futuro para `SOURCES_SISTEMA`. §C-3.4.
- **A-4.** O recorte do C-7 só é correto por causa de uma garantia que ninguém escreveu, e a Story
  **8.19** pode quebrá-la sem saber. §C-7.3.

---

## C-1 — A pré-condição do gate. **RATIFICADO COM AJUSTE.**

### C-1.1 O @sm está certo, e o diagnóstico dele é exato

Lida ao pé da letra, a §9.3 é insatisfazível. `Charge` paga pelo trilho tem `transaction_id` e, pela
minha própria Invariante do Trilho, **nunca** terá `bank_account_id`. O trilho é o caminho normal do
produto. Logo: qualquer janela com uma cobrança normal fecha o gate para sempre.

A leitura do @sm — *"lançamentos que deveriam ter produzido movimento bancário e não produziram"* —
é a substância certa. **Ratifico a substância. Rejeito a redação, a dele e a minha**, pelo motivo da
§C-1.3.

### C-1.2 O que o @sm não viu, e é o mesmo bug de novo — A-1

A população do AC8 da 8.16, termo (b), é:

> `Charge` com `status IN ('paid','scheduled')`, `paid_at` na janela, `transaction_id IS NULL`
> **e** `bank_account_id IS NULL`

A `Charge` sintética de rendimento de aplicação (`investments/service.py:164-177`, Story 5.6) nasce
`status='paid'`, `paid_at=now()`, `transaction_id=NULL` e `bank_account_id=NULL`. **Ela cai inteira
nessa população.** E a perna bancária dela (`source='yield'`) é escopo da **Onda 2b**, que está
declaradamente fora desta onda.

**Consequência: com a redação do @sm, o gate não abre para nenhum tenant que registre rendimento —
nunca, até a Onda 2b.** É exatamente a falha que o C-1 existe para consertar, entrando pela porta ao
lado.

Vale registrar que o outro @sm **viu** essa `Charge`: a Story 8.15 AC3 a exclui explicitamente da
Invariante do Trilho, reusando `_not_investment_yield()` (`receivables/service.py:82-90`). Os dois
@sm não conversam, e o mesmo predicado foi lembrado num lugar e esquecido no outro. **Isso é
argumento para o predicado ter um lugar só** — ver a instrução no fim desta seção.

### C-1.3 A redação nova da pré-condição (normativa)

> **PRÉ-CONDIÇÃO DO GATE (substitui a §9.3 e o epic §3.1.2).**
>
> A leitura do gate é válida num ciclo de conferência **se e somente se**, na janela conferida,
> **não existe evento conhecido pelo e1p que moveu dinheiro numa conta real do dono sem ter gerado o
> `bank_transaction` correspondente.**
>
> Operacionalmente, quatro termos. Cada um tem o predicado que o decide e a onda que o zera:
>
> | # | População | Predicado | Zera na |
> |---|---|---|---|
> | **P1** | Baixa de Contas a Pagar sem conta informada | `Payable`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `bank_account_id IS NULL` | **Onda 2** (8.12 torna a coluna obrigatória ⇒ P1 vai a zero **por construção** assim que o legado for corrigido) |
> | **P2** | Recebimento fora do trilho sem conta informada | `Charge`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `transaction_id IS NULL`, `bank_account_id IS NULL`, **e** `_not_investment_yield()` | **Onda 2** (8.15) |
> | **P3** | Rendimento de aplicação sem perna bancária | `Charge` com `external_ref LIKE 'investment:%'`, `paid_at::date` na janela | **Onda 2b** |
> | **P4** | Payout da Carteira liquidado sem perna bancária | payout com liquidação real na janela | **Onda 3**. ⚠️ **Hoje é vazio por construção**: `request_payout` só marca `withdrawn` (`wallet/service.py:227`) — nenhum dinheiro sai de conta real. Passa a ser contado quando o payout for real |
>
> **Fora da população, por construção e não por omissão:** `Charge` do trilho
> (`transaction_id IS NOT NULL`). O dinheiro dela está na Carteira, **não numa conta do dono**, e ela
> **não deve** gerar `bank_transaction` até o payout. Incluí-la é a leitura que torna a pré-condição
> insatisfazível — e a exclusão é a **Regra dos Planos**, não uma lacuna de preenchimento.
>
> **Membro:** um `Payable` pago em 12/07 com `bank_account_id IS NULL` (uma das 45 legadas) → P1,
> conta.
> **Não-membro:** uma `Charge` paga pelo webhook do Asaas em 12/07 → tem `transaction_id`, **não**
> conta.
>
> **A nota ANOTA; ela NUNCA SUBTRAI.** Inalterado, e é a Regra 5 do `CLAUDE.md`.

### C-1.4 A consequência de roadmap que precisa subir ao fundador

Escrita sem eufemismo, porque muda a leitura do épico:

> **O gate não abre "depois da Onda 2" em geral.** Ele abre depois da Onda 2 **para um tenant cujos
> únicos eventos que movem conta real na janela sejam baixa de Contas a Pagar e recebimento fora do
> trilho.** Um tenant que registra rendimento precisa da **Onda 2b**; quando o payout virar real,
> precisa da **Onda 3**.
>
> Isto **não** é escopo novo — P3 e P4 sempre foram termos da divergência. O que muda é que eu
> escrevia a pré-condição como se a Onda 2 a satisfizesse sozinha, e ela não satisfaz. → §F-D12.

### C-1.5 O que muda, onde

| Arquivo | Mudança |
|---|---|
| `docs/architecture/controle-bancario-onda2-design.md` §9.3 | **FEITO nesta rodada** — redação nova acima |
| `docs/decisions/0003-controle-bancario-nativo.md` | **FEITO** — Adendo 5 |
| `docs/prd/epic-8-controle-bancario.md` §3.1.2 | ⚠️ **@pm:** a pré-condição normativa e a tabela de decisão precisam da redação nova. **Eu não edito o epic.** A linha *"Pré-condição não satisfeita → o gate não abre"* fica; o que muda é **o predicado** e o acréscimo de P3/P4 |
| Story **8.16 AC8** | ⚠️ **@sm/@po:** substituir a população pela tabela P1–P4. **Acrescentar `_not_investment_yield()` ao termo P2** (é o A-1) e **P3 como contador próprio** com nota própria. P4 é declarado e **não** contado nesta onda — contá-lo exigiria `bank → wallet` para um contador cosmético, e a população é vazia hoje |
| Story **8.16 AC7** | a `note` do bloco 4 passa a ser **até três notas**, uma por termo não-zero, cada uma nomeando a onda que a fecha. Uma redação, um lugar (o mesmo bloco de `_NOTE_SEM_CHECKPOINT`) |
| Story **8.16**, novo | o predicado `_not_investment_yield()` **não é reescrito**: é importado de `receivables/service.py`. Duas cópias divergem, e este parecer é a prova de que já divergiram uma vez entre dois @sm |

---

## C-2 — A regra do agendamento vencido. **RATIFICADO COM AJUSTE.**

### C-2.1 O @sm está certo e eu escrevi código morto

`run_sweep` promove `scheduled → paid` quando o dia chega (F-D11). Logo, `payables em scheduled cuja
data já passou` é uma população que existe entre a meia-noite e a varredura, e é quase sempre vazia.
A regra literal da §9.2.1 é código morto.

### C-2.2 A resposta honesta à pergunta do coordenador

> *"Eu vendi esse efeito ao founder com entusiasmo; se ele não existe do jeito que está escrito,
> quero saber."*

**O efeito existe. O adjetivo não.**

O que existe, e continua existindo exatamente como prometido: um débito que o e1p registrou e que o
banco **não executou** entra no saldo derivado na data (o saldo é função da data, sem worker nenhum),
o checkpoint declara um saldo **maior**, e `divergencia > 0` no ciclo seguinte. É uma classe de furo
que hoje ninguém pegaria, e ela é pega. **Isso está de pé.**

O que **não** existe é o e1p saber dizer *"o agendamento de 15/08"*. Depois da varredura, o
`Payable` está `paid` e nada no dado distingue *"eu agendei e o banco não executou"* de *"eu paguei
no caixa e o banco não compensou"*. Eu escrevi "agendamento" porque estava com o `scheduled` na
cabeça, e não perguntei o que sobra dele depois do worker que eu mesma especifiquei duas seções
antes.

**Isso não custa valor ao sinal**, e vale dizer por quê: o valor do sinal está em **apontar um débito
específico cuja ordem de grandeza casa com a divergência**, não no adjetivo. O dono que abre o app do
banco para conferir um débito de R$ 5.000 de 15/08 não precisa que a gente lhe diga que ele o
agendou — ele sabe. Precisa que a gente diga **qual**.

E a disciplina do épico decide o resto: *"suprima a afirmação, nunca o número"*. Não posso afirmar
"agendado"; posso apontar o débito e a divergência.

### C-2.3 O que fica ratificado, e os três ajustes

**RATIFICO a população do @sm** (união de `scheduled AND paid_at::date <= hoje` com `paid AND
bank_account_id IS NOT NULL AND paid_at::date` dentro da janela e `<= reference_date`), sem coluna
nova e sem reabrir F-D11. Os três ajustes:

**(1) O nome e o texto perdem "agendamento".** Um nome que diz uma coisa carregando outra é o defeito
D-3, e eu já o cometi duas vezes neste épico (`*_fonte` com dois eixos, `source` com dois eixos). Não
uma terceira.

| De | Para |
|---|---|
| `AgendamentoSuspeitoInput` | `DebitoSuspeitoInput` |
| `source="agendamento"` | `source="debito_nao_confirmado"` |
| `sourceLabel` → "Agendamentos" | "Saídas" |
| *"O débito de R$ 5.000,00 **agendado para** 15/08 (Aluguel) pode não ter saído…"* | *"O débito de R$ 5.000,00 **de** 15/08 (Aluguel) pode não ter saído da conta: o saldo que você declarou está R$ 5.000,00 acima do que o e1p calculou."* |

O *"pode não ter saído"* fica, verbatim. Ele é a única afirmação que o e1p tem direito de fazer.

**(2) O fator de ordem de grandeza é apertado.** O @sm propôs `0,5× ≤ valor ≤ 2×`
`[SUPOSIÇÃO DO @SM]`, porque eu escrevi "ordem de grandeza" e não dei número. **Rejeito o intervalo,
ratifico a ideia.** Um fator 2 nomeia um débito de R$ 5.000 diante de uma divergência de R$ 2.500 —
e nomear um débito inocente é pior do que ficar calado: *"pode não ter saído"* sobre um débito que
obviamente saiu é o que treina o dono a ignorar a tela. Silêncio só devolve o número que ele já tem
hoje.

> **Critério (normativo):** `|valor_cents − divergencia_cents| <= max(5000, divergencia_cents // 10)`
> — R$ 50 ou 10%, o que for maior. Constante nomeada ao lado de `_COMPLETENESS_STALE_DAYS`.
>
> É a **mesma forma** da banda de tolerância (`max(R$ 50, 0,5%)`) e **um percentual diferente de
> propósito**: a banda absorve resíduo estrutural; este critério responde *"este débito explica esta
> divergência?"*, que é pergunta mais estrita. Uma forma, dois usos, e a diferença escrita.

**(3) A cardinalidade e o silêncio ficam como o @sm escreveu:** 1 sinal por conta, o suspeito de
maior valor, **zero sinal** quando nada casa, **zero sinal** quando a divergência é negativa.
Ratificados os três.

### C-2.4 O que muda, onde

| Arquivo | Mudança |
|---|---|
| `controle-bancario-onda2-design.md` §9.2.1 | **FEITO** — população, nome, texto e critério |
| Story **8.16 AC1, AC5, AC6, AC10, Task 1, Task 2** | ⚠️ **@sm/@po:** renomear a dataclass, o `source` e o `sourceLabel`; trocar o texto do sinal; trocar o fator pelo critério acima. **A população do AC6 fica.** |

---

## C-3 — `origin_id` e a forma canônica da transferência. **RATIFICADO COM AJUSTE.**

### C-3.1 A forma canônica

**RATIFICO a forma do @sm:** `origin_id = f"{transfer.id}:out"` e `f"{transfer.id}:in"`, pareadas
por `transfer_id` (coluna que **já existe**, `bank/models.py:278`), `dedup_hash =
sha256(f"{source}|{origin_id}")` distinto por perna de graça.

As alternativas, julgadas — e duas delas são piores do que o @sm supôs:

| Alternativa | Veredito |
|---|---|
| `origin_id = transfer.id` nas duas + índice relaxado | **Rejeitada.** Destrói a idempotência **na origem onde ela mais importa**: um retry de transferência move o dinheiro duas vezes |
| Coluna discriminadora `leg` no índice `(tenant, source, origin_id, leg)` | **Rejeitada, e por um motivo que o @sm não nomeou:** `leg` seria `NULL` para toda origem de perna única, e no Postgres **`NULL` é distinto de `NULL` em índice único por padrão** — `(t,'payable',id,NULL)` deixaria de colidir consigo mesma. O índice perderia a garantia para **todas** as outras origens, em silêncio. Exigiria `NULLS NOT DISTINCT` (PG15+) ou uma sentinela. Frágil demais para o preço |
| Incluir `bank_account_id` no índice | **Rejeitada.** As duas pernas deixariam de colidir, sim — e o mesmo `payable` passaria a poder gerar movimento em duas contas. Destrói exatamente a invariante 1:1 que o índice existe para garantir |
| Duas linhas-filhas de `bank_transfers` só para ter dois UUIDs | **Rejeitada**, como o @sm rejeitou: tabela inventada (Art. IV) para um problema de chave |

### C-3.2 O que eu errei, e a redefinição que conserta

O conflito não é entre §8 e §3.2. É que eu escrevi as duas seções com **conceitos diferentes de
`origin_id`** e não percebi: na §3.2, `origin_id` é *"a unidade que o sincronizador mantém coerente"*;
na §8, é *"o id do lançamento de origem"*. Para `payable` e `charge` as duas coincidem, então nada
protestou.

> **`origin_id` é a CHAVE DE ORIGEM, não "o id do lançamento" (normativo).**
> Para origens de **perna única** (`payable`, `charge`, `yield`, `payout`) ela **é** exatamente o id
> do lançamento. Para origens de **múltiplas pernas**, ela é `f"{id}:{perna}"`, com `perna` num
> vocabulário fechado por `source`.
> O que `origin_id` garante é a **unicidade da unidade de sincronização** — e a unidade de
> sincronização de uma transferência é **a perna**, não a transferência. O pareamento entre pernas é
> trabalho de `transfer_id`, que existe para isso.

Com essa redefinição, o sufixo deixa de ser gambiarra: é a chave dizendo a verdade sobre o que ela
identifica.

### C-3.3 A largura: **`VARCHAR(64)`**, não 36 e não 48

`uuid4` (36) + `":out"` (4) = **40**. O @sm pediu ≥ 48. **Declaro 64**, e a razão é assimetria de
custo, não conforto:

- Em Postgres, `VARCHAR(n)` é armazenamento variável — 64 e 36 custam **exatamente o mesmo em disco**.
  O `n` é uma restrição, não uma reserva.
- O custo de errar para menos é `ALTER COLUMN` sobre tabela com dado sob `FORCE ROW LEVEL SECURITY`
  — a armadilha que a 0046 documenta e que o ADR 0003 nomeia como o único ponto desse tipo do épico.
- 64 dá 24 caracteres de folga para um vocabulário de perna futuro. 48 dá 8, e 8 é o tipo de folga
  que alguém consome sem perceber.

**Teste normativo, para que o próximo erro seja em CI e não em migration:**
`test_origin_id_cabe_na_coluna` — para cada forma de chave de origem construída no repositório,
`len(chave) <= <largura declarada no model>`. Uma origem de várias pernas nova reprova ali, não no
`ALTER COLUMN`.

### C-3.4 O achado A-3: o 422 de futuro da transferência não funciona onde a 8.18 o põe

A Story 8.18 AC7 decide que `posted_at` futuro numa transferência é **422**, com o argumento de que
transferência agendada é escopo não escrito. **Ratifico a decisão.** É Art. IV: não existe estado de
promoção, nem superfície, nem teste para uma quarta semântica de agendamento.

Mas a mecânica não fecha como a story a descreve. A partir da 8.14 AC4, `_validate_posted_at`
**aceita** futuro para `source ∈ SOURCES_SISTEMA`, e `transfer ∈ SOURCES_SISTEMA`. Logo a guarda de
`bank/service.py` **não** vai recusar a perna futura.

> **Instrução:** o 422 de futuro da transferência é validado em `create_transfer`, **antes** das duas
> chamadas a `sync_origin_movement`, junto das demais guardas do AC7 — nunca por dentro de
> `_validate_posted_at`. E o comentário diz **por que** a exceção existe, senão a Onda 2b copia a
> forma errada para o rendimento.

### C-3.5 O DELETE da transferência (8.18 AC8) — **RATIFICADO**

O @sm o marcou `[SUPOSIÇÃO DO @SM]` porque o design não o especifica. Ratifico, e a razão é que ele
**deriva** do que o design já decidiu: a §4.5 rejeita nominalmente a contrapartida (*"o extrato do
dono tem uma linha; criar duas inventa um crédito que nunca existiu"*). Sem o DELETE, a única
correção de uma transferência errada seria justamente a contrapartida rejeitada. A regra é a mesma
do estorno: **o movimento some, com a guarda de linha puramente sintética**. Não é escopo novo; é a
§4.5 aplicada onde ela já valia.

### C-3.6 O que muda, onde

| Arquivo | Mudança |
|---|---|
| `controle-bancario-onda2-design.md` §3.2 | **FEITO** — `VARCHAR(64)` + a redefinição de `origin_id` |
| `controle-bancario-onda2-design.md` §8 | **FEITO** — forma canônica das pernas + o 422 de futuro em `create_transfer` |
| Story **8.9 AC1** | ⚠️ **@sm/@po:** `bank_transactions.origin_id` passa de `VARCHAR(36)` para **`VARCHAR(64)`**. É a única mudança de schema desta ratificação, e ela **tem de entrar antes de a migration ser escrita** |
| Story **8.9**, novo | acrescentar `test_origin_id_cabe_na_coluna` à Task 7 |
| Story **8.18 AC4** | ⚠️ resolvido: a forma é a do @sm, a largura é 64, e a contradição some porque `origin_id` foi redefinido |
| Story **8.18 AC7**, linha `posted_at` futuro | ⚠️ a guarda vive em `create_transfer`, não em `_validate_posted_at` (A-3) |

---

## C-4 — `bank_audit`. **REJEITADO como referência; SUBSTITUÍDO.**

### C-4.1 O fato

`grep -rn "bank_audit" apps/api` → **zero**. `app/scripts/` tem `migrate_attachments_to_s3.py` e
`scan_orphan_storage.py`. O script nunca foi escrito.

Ele é citado como existente em **três** documentos:

| Documento | Onde | O que diz |
|---|---|---|
| `controle-bancario-design.md` (mãe) | §2.2, §2.3, §linha 1325, §linha 1527 | audita o `status` materializado; `--investments` reporta divergência |
| `0003-controle-bancario-nativo.md` | Consequência 4 | *"auditável por `python -m app.scripts.bank_audit`"* |
| `epic-8-controle-bancario.md` | *"Ativos NOVOS a reusar, entregues pelas Ondas 0 e 1 (**não recriar**)"* | lista `bank_audit` entre eles |

A terceira é a pior: ela instrui explicitamente a **não** criar uma coisa que não existe. A Story 8.9
Task 8 obedeceu e mandou o @dev acrescentar uma varredura a um arquivo inexistente — o @dev criaria
o script inteiro em silêncio (escopo inventado) ou pararia. Nos dois casos, um ciclo perdido.

Isto é a **mesma família** do defeito que o `CLAUDE.md` §6.1 registra sobre validação de CPF/CNPJ,
que induziu a Story 8.2 a especificar validação fraca. Duas vezes o mesmo modo de falha: **uma lista
de ativos é um conjunto de afirmações verificáveis, e nenhuma das duas foi verificada.**

### C-4.2 A decisão: não criar agora, e dizer por quê

O script tem dois trabalhos citados. Julgo os dois separadamente.

**Trabalho (i) — auditar o cache `payables.bank_transaction_id` × `origin_id`.** Este é o trabalho
que a Onda 2 pediria. **Não precisa de script**, e a razão é estrutural:

> A divergência entre o cache e o `origin_id` só é alcançável **por bug**. `sync_origin_movement` é o
> **único** escritor do movimento e devolve a linha na mesma chamada e na mesma transação; o chamador
> grava o cache com o que recebeu. Não há segundo caminho, não há concorrência, não há
> materialização assíncrona.
>
> **Condição alcançável só por bug se prova com teste, não com script.** Um script que ninguém tem
> gatilho para rodar não é garantia; é intenção documentada.

Substituição: `test_cache_de_movimento_nunca_diverge_do_origin_id`, exercitando os **cinco** caminhos
de mutação — baixar, trocar conta, trocar data, estornar, repagar — e afirmando, em cada um,
`payable.bank_transaction_id == <movimento com origin_id = payable.id>.id` ou os dois `NULL`.

**Trabalho (ii) — auditar o `status` materializado (`partial`/`matched`).** Este é território da
**Onda 5** (`_refresh_status` também não existe; `bank/service.py:826` o descreve como *"trabalho da
Onda 4"*). Ali a divergência **é** alcançável sem bug — matcher concorrente, vínculo parcial. **É lá
que o script passa a ser necessário**, e ele fica registrado como **pré-requisito da Onda 5**, não
como ativo existente.

### C-4.3 O que muda, onde

| Arquivo | Mudança |
|---|---|
| `controle-bancario-onda2-design.md` §3.3 | **FEITO** — a citação sai; entra o teste |
| `controle-bancario-design.md` (mãe) §2.2, §2.3 e as duas citações de `--investments` | **FEITO** — marcadas como **NÃO EXISTE**, com o que fica no lugar e quando o script passa a ser necessário |
| `0003-controle-bancario-nativo.md` Consequência 4 | **FEITO** — corrigida + Adendo 5 |
| `epic-8-controle-bancario.md`, *"Ativos NOVOS a reusar"* | ⚠️ **@pm: remover `bank_audit` da lista.** Eu não edito o epic. É a correção mais urgente deste parecer, porque a lista instrui a *"não recriar"* |
| Story **8.9 AC7 (último parágrafo) e Task 8** | ⚠️ **@sm/@po:** substituir *"`bank_audit` ganha uma varredura"* pelo teste da §C-4.2. A **regra de autoridade nas docstrings fica** — ela é correta e é o que importa |

---

## C-5 — A guarda de contagem dupla × o gate estrutural. **RATIFICADO COM AJUSTE.**

### C-5.1 O que ratifico sem reserva

A rejeição do @sm ao **import lazy** e ao **SQL cru** está certa, e eu quero que ela fique escrita
como regra e não como escolha desta story:

> **Evadir um gate é pior do que quebrá-lo às claras.** Quebrado às claras, alguém vê no diff.
> Evadido, o gate fica verde e a proibição está morta — que é literalmente o achado **TEST-001** do
> gate das Ondas 0–1 (`from app.core import ai` passando pela varredura de pureza).
> Qualquer forma que faça o gate passar **sem** que a dependência tenha desaparecido é reprovada
> nesta onda, por definição.

E ratifico a **porta de saída registrada na composição**: `bank` declara um `Protocol` que ele
próprio possui, `payables` implementa, `main.py` liga. Direção final `main → bank`, `main →
payables`, `payables → bank`. `bank` não sabe que `payables` existe. É a inversão de dependência
canônica, e ela **respeita** o gate em vez de contorná-lo.

Alternativas rejeitadas, com uma que o @sm não listou:

| Alternativa | Veredito |
|---|---|
| Import direto | Quebra o gate |
| Import lazy | **Evade** o gate — TEST-001 |
| SQL cru sobre a tabela | Passa no gate e viola o que o gate protege |
| Guarda na rota | Mesmo módulo, mesmo problema |
| Relaxar o gate para este caso | **Rejeitada.** *"Sem isso, o primeiro atalho de conveniência recria um ciclo"* — palavras minhas na §3.5. O gate é o produto |
| **Terceiro módulo coordenador** (não listado pelo @sm) | **Rejeitada.** Resolve, e custa um módulo novo para uma guarda — e o ponto de chamada continua tendo de ser `create_transaction`, então é a porta de saída com uma camada a mais |

### C-5.2 Ajuste 1 — fail-closed migra de request-time para **boot-time**

O @sm especifica: probe não registrado ⇒ **500 explícito** no request. A intenção está certa (a
alternativa, "não valida em silêncio", é a guarda desligada em produção sem ninguém saber). A hora
está errada.

> **Um erro de fiação é condição de startup, não de request.** Um 500 numa ação legítima do dono
> (lançar uma tarifa de R$ 2,90) é o pior lugar para descobrir que o `main.py` não ligou um Protocol.
>
> **A aplicação não sobe sem o probe registrado.** Precedente do próprio projeto: a guarda de boot
> contra `JWT_SECRET` fraco em produção (`CLAUDE.md` §6.1, *"já corrigidos na fundação"*).
>
> A verificação de request-time **fica**, como segunda guarda — inalcançável se a de boot funcionar.
> É a mesma disciplina dupla que o `update_transaction` do módulo `bank` documenta *"de propósito"*.

Isso também torna o teste do @sm mais forte: de *"a fiação registra o probe"* para *"a app não sobe
sem ele"*, que é a versão à prova de mutação.

### C-5.3 Ajuste 2 — o achado A-2: o `Protocol` como está reprova o próprio gate

A Task 2 da 8.17 especifica:

```
probe_pagamento_duplicado(db, *, amount_cents, posted_at) -> Payable | None
```

Se o `Protocol` em `bank/service.py` tem `Payable` na assinatura, então `bank` precisa do **tipo** —
e um `if TYPE_CHECKING: from app.modules.payables.models import Payable` **continua sendo um import
de `payables` dentro de `bank`**. A varredura de texto cru do gate (que existe exatamente porque o
AST sozinho não basta — TEST-001) o pega, e com razão. **A forma proposta reprova o gate que ela
existe para respeitar.**

> **A porta devolve um DTO de `bank`, nunca uma entidade de `payables`.**
>
> ```python
> # bank/service.py — CONTRATO
> @dataclass(frozen=True)
> class DuplicataCandidato:
>     referencia_id: str      # id opaco para o `payable_id` do 409 — bank não sabe do que é id
>     descricao: str
>     valor_cents: int
>     data: date
> ```
>
> `bank` monta o 409 a partir disso e **não sabe** que existe um `Payable`. `payables` monta o DTO.
> O gate fica verde **porque a dependência sumiu**, não porque foi escondida.

O campo se chama `referencia_id` e não `payable_id` de propósito: `bank` não pode nomear um conceito
de `payables` nem no nome de um campo. A rota devolve `{"acao": "baixar_payable", "payable_id": ...}`
— o vocabulário de `payables` aparece só no payload HTTP, montado com o valor opaco.

### C-5.4 Ajuste 3 — o que fica como o @sm escreveu

- **Não estender a `update_transaction`** — **RATIFICADO**. Editar valor/data de um movimento manual
  existente é correção, não criação; o design fala de `create_transaction`; ampliar é Art. IV.
- **O probe roda na sessão do request, sob RLS**, sem filtro manual de `tenant_id` — **RATIFICADO**,
  e o IV5 da story é o teste certo. Reforço: o probe **recebe** o `db`, nunca abre sessão própria —
  abrir sessão própria é escapar da GUC do tenant.
- **Janela ±3 dias e valor exato, iguais aos do enriquecimento** — **RATIFICADO**, um número e não
  dois, como o design já dizia.

### C-5.5 O que muda, onde

| Arquivo | Mudança |
|---|---|
| `controle-bancario-onda2-design.md` §7(b) | **FEITO** — a porta, o DTO, o boot-time |
| Story **8.17 AC6, Task 2** | ⚠️ **@sm/@po:** (a) assinatura do probe devolve `DuplicataCandidato`, **não** `Payable`; (b) fail-closed vira **boot**, com a checagem de request como segunda guarda; (c) o teste vira *"a app não sobe sem o probe"* |

---

## C-6 — Quem libera `posted_at` futuro. **RATIFICADO.**

### C-6.1 A atribuição está certa e é rastreável

Não há buraco. As quatro stories dizem a mesma coisa e apontam para o mesmo lugar:

| Story | O que diz |
|---|---|
| **8.10** AC8 | *"Esta story **não** mexe em `_validate_posted_at` — quem o afrouxa para o caminho de origem é a 8.12/8.14"* |
| **8.11** AC8 | *"Nada em `_validate_posted_at` é tocado… quem libera o futuro é a **8.14**"* |
| **8.12** AC3 | teto em hoje, `[CORTE DO @PM]`, com *"o teto sai na 8.14"* escrito no código |
| **8.14** AC4 | libera, distinguindo `SOURCES_SISTEMA` de `SOURCES_EXTERNA` |

**RATIFICO o corte por origem**, e dou a razão melhor do que o `[AUTO-DECISION]` do @sm a dá:

> A segunda guarda de `_validate_posted_at` tem uma justificativa escrita no código
> (`bank/service.py:614-616`): *"extrato bancário é fato passado. Data futura é erro de digitação"*.
> **Essa justificativa descreve transcrição.** Uma justificativa sobre transcrição não pode governar
> origem.
>
> Portanto a guarda não está sendo enfraquecida — está sendo **devolvida ao próprio escopo**. É
> exatamente o movimento da §1.1(2) deste design (herdei um limite traçado por outro motivo e o
> generalizei), e é bom que o @sm o tenha reencontrado sozinho: o padrão é frequente o bastante para
> ter nome.

### C-6.2 Ajuste único: o corte é por `source`, nunca por booleano do chamador

A Task 2 da 8.14 oferece *"parametrizar por `source` (ou por um booleano `permite_futuro`, decidido
pelo chamador)"*. **Rejeito o booleano.**

Um booleano decidido pelo chamador é o parâmetro que alguém passa `True` no caminho manual, um dia,
por conveniência — e o gate de AST não pega, porque não há import nenhum envolvido. O eixo já
existe, é `source`, e **toda regra desta onda é escrita contra `SOURCES_SISTEMA`/`SOURCES_EXTERNA`,
nunca contra valor solto nem contra um eixo paralelo** (§3.1, normativa). Um eixo, uma pergunta.

### C-6.3 O movimento externo continua recusando futuro — **CONFIRMADO**, com a razão escrita

Sim, e quero a razão no design para que a Onda 4 não a reabra:

> **O e1p pode afirmar o futuro do que ele mesmo agendou; não pode afirmar o futuro do que outro
> atestou.**
>
> Um OFX descreve o que já aconteceu. `posted_at` futuro num arquivo importado é erro de parser ou
> arquivo corrompido — não é fato. E se um dia aparecer um caso legítimo (débito pré-autorizado
> exibido no extrato), o tratamento honesto é **recusar e mandar um humano olhar**, nunca aceitar em
> silêncio uma afirmação sobre o futuro vinda de uma fonte que não pode conhecê-lo.
>
> A proteção contra erro de ano na digitação manual **fica**, e continua valendo a pena.

### C-6.4 O que muda, onde

| Arquivo | Mudança |
|---|---|
| `controle-bancario-onda2-design.md` §4.2 | **FEITO** — corte por `source` normativo + a razão do externo |
| Story **8.14 AC4, Task 2** | ⚠️ **@sm/@po:** remover a opção do booleano `permite_futuro`. O corte é por `source` |

---

## C-7 — Contagem dupla no dia agendado. **RATIFICADO.**

### C-7.1 O achado do @sm é real e o recorte fecha

Verificado no código: `_movements_sums` usa `posted_at <= until` **inclusivo**
(`bank/service.py:302-304`); `_saldo_inicial` usa `active_balance_total(db, until=today)`
(`projection.py:329-331`); `_window_sums` filtra `status == open_status` (`projection.py:370-373`).
As duas afirmações do design juntas produzem, no dia D antes da varredura, a subtração dupla.

O recorte `status == 'scheduled' AND paid_at::date > today` fecha os quatro casos:

| Caso | `saldo_inicial` | `_window_sums` | Total |
|---|---|---|---|
| D > hoje | fora (movimento futuro) | **dentro** | 1× ✔ |
| D == hoje, antes da varredura | **dentro** (`posted_at <= today`) | fora (predicado falso) | 1× ✔ |
| D == hoje, depois da varredura | **dentro** | fora (status é `paid`) | 1× ✔ |
| D < hoje, worker parado há dias | **dentro** | fora (predicado falso) | 1× ✔ |

**E a propriedade que o @sm nomeou é a melhor parte, e vale mais do que o conserto:** com esse
recorte, **a corretude da Projeção deixa de depender da frequência do worker**. O worker vira o que o
F-D11 diz que ele é — cosmética de status para a Fila e o resumo — e não um componente do qual a
aritmética depende. Se ele parar uma semana, a Projeção continua certa. Isso não é um detalhe de
implementação; é o motivo pelo qual o recorte é a forma **certa** e não só a que fecha a conta.

### C-7.2 Não abre buraco simétrico nas entradas

A Story 8.15 AC6 replica o mesmo mecanismo para `Charge`, com o **mesmo** recorte. Espelhado, fecha
igual: crédito agendado para D, antes da varredura em D, entra no `saldo_inicial` (movimento
positivo com `posted_at <= today`) e sai das entradas da janela. Uma vez. ✔

**RATIFICO os dois lados**, com uma condição de forma: o predicado é **um só**, parametrizado, usado
pelos dois. A Task 3 da 8.14 já decide isso (`scheduled_status` explícito em vez de
`isinstance(model, Payable)`) e a decisão está certa — ratifico também o argumento dela: *"um `if`
por tipo dentro de uma função genérica é o começo de duas funções fingindo ser uma"*.

### C-7.3 O achado A-4: o recorte é correto por causa de um acoplamento que ninguém escreveu

O recorte tira a agendada de `_window_sums` quando a data já chegou, **confiando** que o movimento
está no `saldo_inicial`. Ele só é seguro porque duas coisas são verdade ao mesmo tempo:

1. **`_saldo_inicial` passa `until=today`.** Se alguém trocar por `until=None` ou por `SEM_CORTE`, a
   agendada futura passa a contar nos dois lugares e a dupla contagem volta — agora do lado oposto.
2. **Todo movimento de origem está dentro da janela do saldo derivado da sua conta**, isto é,
   `posted_at > opening_date`. Se não estivesse, `_movements_sums` o excluiria (o `>` é estrito) e o
   predicado do recorte também o excluiria: **o dinheiro sumiria por completo da Projeção.** Hoje
   isso é impossível dos dois lados — `apply_paid` valida o piso (422) e
   `_validate_opening_date_move` impede avançar a `opening_date` por cima de movimento (a correção do
   BANK-001). É garantia por construção, e é **invisível**.

> ⚠️ **A Story 8.19 edita `_saldo_inicial`.** Ela mexe na decisão de origem
> (`ORIGEM_MISTO` pela mera existência de conta), não no `until` — verifiquei. Mas nada no repositório
> impede que o conserto encoste no `until`, e o efeito seria a dupla contagem voltar em silêncio, num
> arquivo que a 8.14 declarou não tocar.
>
> **Instrução:** a IV1 da Story 8.14 ganha uma asserção explícita de que `_saldo_inicial` chama
> `active_balance_total` com `until=today`, e a Story 8.19 ganha a instrução de **não** alterar esse
> argumento. O comentário que já existe em `projection.py:327-328` (*"a MESMA âncora do resto da
> projeção"*) diz **por que** ele existe, mas não diz **o que quebra** — e o que quebra agora é outra
> coisa, noutro arquivo.

### C-7.4 O que muda, onde

| Arquivo | Mudança |
|---|---|
| `controle-bancario-onda2-design.md` §4.2.3 | **FEITO** — o recorte, os quatro casos, e o acoplamento da §C-7.3 escrito |
| Story **8.14 AC6** | ✅ **ratificado como está** |
| Story **8.14 IV1** | ⚠️ **@sm/@po:** acrescentar a asserção de que `_saldo_inicial` usa `until=today` |
| Story **8.19** | ⚠️ **@sm/@po:** instrução explícita de **não** alterar o `until` de `_saldo_inicial` (A-4) |
| Story **8.15 AC6** | ✅ **ratificado como está** |

---

## 1. A quarta autocrítica: por que a §3.1/§9.3 é a seção que mais erra

Duas falhas na mesma seção no mesmo dia pedem uma explicação estrutural, e o coordenador tem razão em
recusar dois remendos. A explicação existe, ela é mais ampla do que o gate, e ela é verificável
contra os fatos de hoje.

### 1.1 O padrão: eu descrevo conjuntos e nunca escrevo um membro

Três dos conflitos deste parecer são o **mesmo defeito**:

| Onde | O conjunto que eu descrevi | O membro que teria derrubado tudo | Custo de escrevê-lo |
|---|---|---|---|
| **§9.3** (C-1) | *"toda `Payable` paga e toda `Charge` recebida precisam ter conta bancária informada"* | uma `Charge` paga pelo webhook do Asaas | 5 segundos |
| **§9.2.1** (C-2) | *"payables em `scheduled` cuja data já passou"* | um payable no dia seguinte à varredura que eu especifiquei duas seções antes | 5 segundos |
| **"Ativos a reusar"** (C-4) | *"`bank_audit`, entregue pelas Ondas 0 e 1, não recriar"* | `ls apps/api/app/scripts/` | 2 segundos |

E o de manhã, que o coordenador já cobrou, é o quarto membro da mesma família:

| **§3.1 (versão da manhã)** | *"se a divergência for pequena e estável, as ondas de import são over-engineering"* | a divergência do tenant do fundador **hoje**: razão vazio, número enorme | 5 segundos |

**Quatro vezes, o mesmo movimento: definir um conjunto por descrição e nunca instanciá-lo.** Não é
falta de rigor — os predicados estão bem escritos, as justificativas estão certas, os trade-offs
estão medidos. É que eu paro no ponto em que a *descrição* está boa, e a descrição está boa antes de
o conjunto estar certo.

### 1.2 A hipótese do coordenador: **confirmada**, e ela explica a concentração

> *"critério de gate é escrito no futuro do pretérito ('quando tal coisa for verdade, decida X') e por
> isso nunca é executado enquanto se escreve — diferente de um contrato de função, que alguém chama
> na página seguinte."*

Confirmada, e vou dizer por que ela é mais forte do que parece.

Todo o resto do design tem **consumidor mecânico**: uma função é chamada na página seguinte; um
índice é criado por uma migration; uma invariante ganha um teste que roda no CI; um contrato de
schema é consumido por um schema de saída. Esses consumidores **protestam**. Errei o `origin_id` na
§8 e a §3.2 protestou — não em segundos, mas protestou, através de um @sm, antes de virar código.

O critério de decisão é **o único artefato do design cujo consumidor é um humano num ciclo futuro**.
Não há quem o chame enquanto eu o escrevo. E humanos não levantam `TypeError`: um humano lendo *"toda
`Charge` recebida precisa ter conta bancária informada"* assente, porque a frase é razoável. Ela é
razoável **e** insatisfazível, e não existe nada entre as duas coisas que dispare.

Então a concentração não é coincidência nem descuido. **A §3.1/§9.3 erra mais porque é a única
seção sem ninguém para contradizê-la.** As outras seções não são melhores; elas só são corrigidas
mais cedo, por consumidores que não perdoam.

Isso também explica por que a §3.1 errou **duas vezes de formas diferentes**: de manhã ela media a
própria incompletude (o predicado não discriminava); agora ela é insatisfazível (o predicado não
tinha membro). São dois defeitos distintos, e o único fator comum é a ausência de execução.

### 1.3 A regra que fica — e ela é sobre como escrever, não sobre este épico

> **REGRA DE MÉTODO — INSTANCIAÇÃO OBRIGATÓRIA.**
>
> Todo conjunto definido por descrição num documento de arquitetura — uma pré-condição com "toda X",
> uma população de regra, uma lista de ativos, um critério de gate — **nasce com pelo menos um membro
> escrito e pelo menos um não-membro escrito, no mesmo parágrafo.**
>
> - Se eu não consigo escrever o **membro**, o conjunto é vazio, e eu descobri agora em vez de daqui
>   a três ciclos de conferência.
> - Se não consigo escrever o **não-membro**, a condição é trivial: ela não separa nada e não decide
>   nada.
>
> **Corolário — critério de decisão é onde a regra é obrigatória, não recomendada.** É o único
> artefato do design sem consumidor mecânico. Todos os outros têm quem os contradiga na página
> seguinte; este não tem ninguém até o dia em que alguém precisa decidir com ele na mão — e nesse dia
> a decisão já está sendo tomada.
>
> **Teste da regra contra o dia de hoje:** ela teria pego as quatro falhas. As duas da §3.1, a da
> §9.2.1 e a da lista de ativos. Nenhuma delas exigia mais análise; todas exigiam **um exemplo**.

A §9.3 reescrita nesta rodada traz o par membro/não-membro escrito dentro do bloco normativo. Não
como ilustração — como parte da definição.

### 1.4 O que isso diz sobre as três autocríticas anteriores

As três de hoje foram sobre **conceitos** (*escrevi um campo antes de terminar de modelar o
conceito*; *especifiquei uma supressão em termos de superfície, não de afirmação*; *a metáfora pensou
por mim*). Esta é a primeira sobre **método de escrita**, e é por isso que ela é a mais útil das
quatro: as outras três me dizem o que eu pensei errado naquele dia; esta me dá uma coisa para fazer
em todo parágrafo que começa com "toda".

---

## 2. Alterações já aplicadas por mim nesta rodada

| Arquivo | Seções |
|---|---|
| `docs/architecture/controle-bancario-onda2-design.md` | §1.1 (5ª autocrítica + a regra), §3.2 (`origin_id` chave de origem, `VARCHAR(64)`), §3.3 (`bank_audit` → teste), §4.2 (corte por `source`; externo recusa futuro), §4.2.3 (recorte do dia D + o acoplamento invisível), §7(b) (porta de saída, DTO, boot-time), §8 (forma canônica das pernas; 422 em `create_transfer`), §9.2.1 (população, nome, texto, critério), §9.3 (pré-condição nova, P1–P4), §12 (F-D12) |
| `docs/architecture/controle-bancario-design.md` | §2.2, §2.3 e as duas citações de `bank_audit --investments` |
| `docs/decisions/0003-controle-bancario-nativo.md` | Consequência 4; **Adendo 5** |

**Não editados de propósito:** `docs/stories/*.md` (um @sm ainda revisa a 8.19; o @po valida as 11) e
`docs/prd/epic-8-controle-bancario.md` (fora da minha autorização nesta rodada — as duas correções
que ele precisa estão na §3).

---

## 3. O que precisa de decisão de outra pessoa

### 3.1 @pm — duas correções no epic, e a primeira é urgente

| # | Onde | O quê |
|---|---|---|
| **E-1** | *"Ativos NOVOS a reusar, entregues pelas Ondas 0 e 1 (não recriar)"* | **Remover `bank_audit`.** Ele não existe. A lista instrui explicitamente a *não recriar* uma coisa que nunca foi criada, e a Story 8.9 já obedeceu (Task 8). Urgente porque bloqueia a 8.9 |
| **E-2** | §3.1.2, pré-condição normativa e a tabela de decisão | Substituir pelo predicado da §C-1.3 (P1–P4), com a `Charge` do trilho fora por construção e a consequência de roadmap da §C-1.4 |

### 3.2 @po / @sm — 11 ajustes de story, consolidados

| Story | AC/Task | Ajuste | Bloqueia? |
|---|---|---|---|
| **8.9** | AC1 | `origin_id` → **`VARCHAR(64)`** | **SIM** — antes da migration |
| **8.9** | AC7 §final, Task 8 | `bank_audit` sai; entra `test_cache_de_movimento_nunca_diverge_do_origin_id` | **SIM** |
| **8.9** | Task 7 | +`test_origin_id_cabe_na_coluna` | não |
| **8.14** | AC4, Task 2 | corte por `source`; remover a opção do booleano `permite_futuro` | não |
| **8.14** | AC6 | ✅ ratificado como está | — |
| **8.14** | IV1 | asserção de que `_saldo_inicial` usa `until=today` | não |
| **8.15** | AC6 | ✅ ratificado como está | — |
| **8.16** | AC1/5/6/10, Tasks 1-2 | renomear para `DebitoSuspeitoInput` / `debito_nao_confirmado` / "Saídas"; texto sem "agendado"; critério `max(R$50, 10%)` | não |
| **8.16** | AC7, AC8 | população P1–P4; `_not_investment_yield()` **importado**; P3 com nota própria | **SIM** — sem isso o gate não abre (A-1) |
| **8.17** | AC6, Task 2 | probe devolve `DuplicataCandidato`, não `Payable`; fail-closed no **boot** | **SIM** — a forma atual reprova o gate (A-2) |
| **8.18** | AC4, AC7, AC8 | forma `:out`/`:in` **ratificada**; largura 64; 422 de futuro em `create_transfer` (A-3); DELETE **ratificado** | **SIM** — AC4 |
| **8.19** | — | não alterar o `until` de `_saldo_inicial` (A-4) | não |

### 3.3 Fundador — uma decisão nova

> **F-D12 (NOVA) — o gate não abre depois da Onda 2 em geral, e isso muda a leitura do roadmap.**
>
> A pré-condição do gate tem quatro termos (§C-1.3). A Onda 2 zera dois. O terceiro (rendimento de
> aplicação) só zera na **Onda 2b**; o quarto (payout) na **Onda 3** — e hoje é vazio porque payout
> real não existe.
>
> **Pergunta:** você registra rendimento de aplicação no e1p hoje?
>
> - **Se não:** o gate abre no primeiro ciclo completo pós-Onda 2, como planejado. Nada muda.
> - **Se sim:** a conferência vai dizer, corretamente, que o número ainda não decide, e a leitura do
>   gate espera a **Onda 2b**. O que eu recomendo nesse caso é o que o §F-D7 já recomendava — 2b logo
>   depois da 2 —, agora com uma razão mais forte do que "é barata": **ela é pré-requisito da métrica
>   primária do épico**, não um incremento dela.
>
> **Minha recomendação:** perguntar antes de planejar. É uma consulta ao banco de dados dele, não uma
> decisão de produto — e é exatamente o tipo de coisa que eu deveria ter instanciado em vez de
> descrito.

**Reafirmados sem reabertura, porque este parecer não os toca:** F-D2 (conta obrigatória), F-D9
(`scheduled` junto), F-D10 (rota `PATCH .../payment`), F-D11 (o worker promove), F-D5 (o sinal não
desliga), F-D8 (aceite em ~360px bloqueia release).

---

## 4. Rastreabilidade (Constitution Artigo IV — No Invention)

| Afirmação | Fonte |
|---|---|
| `bank_audit` não existe; `app/scripts/` tem 2 arquivos | `ls apps/api/app/scripts/`; `grep -rn bank_audit apps/api` → 0 |
| `_refresh_status` também não existe; é descrito como trabalho da Onda 4 | `bank/service.py:826`; `bank/models.py:140,186` |
| A `Charge` de rendimento nasce `paid`, `paid_at=now()`, sem `transaction_id` e sem `bank_account_id` | `investments/service.py:163-177` |
| `_not_investment_yield()` existe e é o predicado que o módulo já usa | `receivables/service.py:82-90` |
| `_movements_sums` usa `posted_at <= until` **inclusivo** | `bank/service.py:302-304` (docstring + código) |
| `_saldo_inicial` usa `active_balance_total(db, until=today)` | `projection.py:327-331` |
| `_window_sums` filtra `status == open_status` | `projection.py:370-373` |
| A justificativa da guarda de futuro fala de transcrição | `bank/service.py:614-616`, verbatim |
| `request_payout` só marca `withdrawn` — payout real não existe | `wallet/service.py:227`; `CLAUDE.md` §Carteira |
| `transfer_id` já existe em `bank_transactions` | `bank/models.py:278` |
| `payables.status` e `charges.status` são `String(12)` | `payables/models.py:43`; `receivables/models.py:44` |
| `run_sweep` tem 3 etapas hoje, com isolamento de falha por tenant | `app/worker.py:48-120` |
| No Postgres, `NULL` é distinto de `NULL` em índice único por padrão | comportamento padrão do PG (`NULLS DISTINCT`), base da rejeição da coluna `leg` — **[ANÁLISE minha]** |
| `VARCHAR(n)` no Postgres não reserva espaço; `n` é restrição | **[ANÁLISE minha]**, base da escolha de 64 |
| Precedente de guarda de boot (JWT_SECRET fraco em produção) | `CLAUDE.md` §6.1 |
| TEST-001: `from app.core import ai` evadindo a varredura de pureza | `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` |
| BANK-001: mover `opening_date` produz divergência inventada | mesmo gate |
| A entrada de CPF/CNPJ do `CLAUDE.md` induziu a 8.2 a especificar validação fraca | `CLAUDE.md` §6.1 |
| Critério `max(R$50, 10%)` para o débito suspeito | **[DECISÃO minha]** — a forma vem da banda de tolerância; o percentual é meu, e é parametrizável |
| A quarta autocrítica e a regra de instanciação obrigatória | **[ANÁLISE minha]**, verificada contra as 4 falhas do dia |
