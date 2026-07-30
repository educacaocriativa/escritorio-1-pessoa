# Onda 2 — A origem do movimento bancário

> **Autora:** Aria (@architect)
> **Data:** 2026-07-30
> **Status:** Proposta de design. **NÃO é** implementação, story nem migration. Blocos de schema são
> **ilustrativos**, exceto os marcados `CONTRATO`.
> **Objeto:** corrigir uma falha de escopo do design anterior — o e1p modelou o fluxo
> **extrato → sistema** e nunca modelou **sistema → banco**, embora seja o segundo que já tem os
> dados. Este documento desenha a segunda direção, reordena o roadmap e diz por que a primeira
> versão só enxergou uma das duas.
> **Documento-mãe:** [`controle-bancario-design.md`](controle-bancario-design.md) (ratificado) +
> [`controle-bancario-design-ratificacao.md`](controle-bancario-design-ratificacao.md).
> **ADR:** [`0003-controle-bancario-nativo.md`](../decisions/0003-controle-bancario-nativo.md) —
> ganha o **Adendo 4** por causa deste documento, e o **Adendo 5** pela ratificação abaixo.
> **Ratificação (2026-07-30):**
> [`controle-bancario-onda2-ratificacao.md`](controle-bancario-onda2-ratificacao.md) — julga os 7
> conflitos que três @sm encontraram ao expandir esta onda em 11 stories (8.9–8.19). **As seções
> §1.1(5), §3.2, §3.3, §4.2.0, §4.2.3.1, §7(b), §8, §9.2.1, §9.2.2, §9.3 e o F-D12 foram corrigidos
> por ela** e estão marcados no corpo.
> **Em produção:** `7dba286` (PR #61), migrations 0058/0059/0060, `e1p.doroeventos.com.br`.

---

## 0. Documento novo, e por quê

O design-mãe tem 1.685 linhas, está **ratificado**, e três stories já foram implementadas contra ele.
Editá-lo cirurgicamente para inverter uma premissa fundadora produziria um documento em que a
premissa antiga e a nova convivem sem que o leitor saiba qual está valendo — que é exatamente o
defeito D-3 (dois conceitos no mesmo campo) em escala de documento.

**Decisão: documento novo + duas marcas de supersede no documento-mãe** (cabeçalho e §8), para que
ninguém leia a ordem antiga das ondas como corrente. O que o documento-mãe decidiu e continua
valendo — Regra dos Planos, dois eixos de proveniência, saldo derivado, checkpoint que nunca
corrige, conferência por conta, banda de tolerância — **não é reaberto aqui**. Este documento
acrescenta **quem escreve** `bank_transactions`, e reordena.

**As 7 regras invariantes do `CLAUDE.md` continuam de pé.** Este design não pede exceção a nenhuma.
Onde ele chega perto de uma, a §9.3 diz em voz alta.

---

## 1. A falha de escopo — autocrítica antes do desenho

Isto vem primeiro de propósito. O desenho novo vale uma onda; entender por que o antigo não o
enxergou vale as próximas.

### 1.1 Por que o design mapeou só uma direção

**(1) A metáfora fez o trabalho de pensar por mim: "o banco é a testemunha que faltava".**

A frase está no `CLAUDE.md`, no epic §1 e na mensagem de commit da Onda 1. Ela é boa e é verdadeira —
e ela carrega um pressuposto que eu nunca escrevi e nunca examinei: **testemunha depõe de fora**.
Uma vez que o plano 3 virou "prova externa", escrever nele a partir do próprio sistema passou a
parecer *fabricação de prova* — irmã da tentação que a Regra 5 proíbe (o checkpoint corrigindo o
saldo derivado). Então todo caminho que eu desenhei para dentro de `bank_transactions` veio de fora:
OFX, CSV, digitação. O eixo de proveniência que eu mesma criei (`*_fonte` ∈ `manual|ofx`) **é o
retrato desse pressuposto**: eu enumerei portas de entrada externas e não me ocorreu que faltava a
categoria "o e1p originou".

O pressuposto é falso, e a distinção que o desfaz é simples: **o checkpoint é prova sobre o saldo; o
movimento é o fato**. Um pagamento que o dono deu baixa dentro do e1p não é a testemunha depondo
sobre si mesma — é um fato que o sistema conhece em primeira mão, e que ele estava jogando fora.
A circularidade que a Regra 5 previne continua prevenida: `saldo_banco` (checkpoint) continua vindo
100% de fora e continua **nunca** derivado de movimento. O que muda é que `saldo_sistema` fica mais
completo — e uma divergência que diminui **porque o sistema passou a saber mais** é o objetivo
declarado do épico, não uma contaminação dele.

**(2) Eu herdei um limite que tinha sido traçado por outro motivo.**

`payables/models.py:4`: *"NÃO mexe na Carteira (é saída, não receita)."* Eu li isso como "`payables`
é isolado dos planos de dinheiro" e generalizei. A docstring diz **plano 1**. Ela não diz nada sobre
o plano 3 — não podia, porque o plano 3 não existia quando ela foi escrita. Generalizei uma
restrição de split para uma restrição de arquitetura, e o resultado foi tratar `payables` como
território proibido.

**(3) A repetição do D-3, e esta é a pior: eu escrevi o campo certo com o conceito errado, e o
conceito errado o rebaixou.**

Design-mãe §6.7, verbatim:

> *"**Opcional (onda posterior):** `payables.bank_account_id` nullable = 'de qual conta pretendo
> pagar'. **Melhora a sugestão de match** (restringe candidatos à conta certa) e a projeção por
> conta. Fica **fora** das ondas 0–6 para não inflar escopo."*

Eu **vi a coluna**. Escrevi-a com a semântica de **intenção** ("de qual conta pretendo pagar") e a
justifiquei como **otimização de matching**. Com essa moldura, ela é obviamente adiável: otimização
espera. Com a moldura certa — *"de qual conta o dinheiro saiu"*, um **fato** — ela é obrigatória no
dia em que o fato acontece, e a ausência dela é a razão de o razão bancário nascer vazio.

Na ratificação eu escrevi: *"quando o mesmo conceito aparece com dois vocabulários em duas seções, o
problema quase nunca é redação — é que são dois conceitos"*. A regra irmã, que eu deveria ter tirado
dali e não tirei:

> **Quando um design cria uma coluna nullable e a justifica com "melhora X", pergunte se o que ela
> guarda é um FATO ou uma PREFERÊNCIA. Preferência é otimização e pode esperar. Fato tem hora
> marcada: o instante em que ele acontece. Perdido esse instante, ele não volta — e nenhum matcher o
> reconstrói.**

**(4) E a moldura de método, que é a crítica do fundador e é a maior das quatro:**
*"é um sistema integrado, não tem o motivo de tudo começar do zero."*

Eu desenhei o módulo `bank` como um subsistema **a ser populado**, com portas próprias, e planejei
plugar os eventos existentes depois (payout na Onda 6, rendimento na §3.4b). A ordem certa era a
inversa, e ela é enunciável como procedimento:

> **Antes de desenhar a porta de entrada de um plano de dados novo, enumere TODOS os eventos que o
> sistema já emite e que significam um fato desse plano. Ligue-os primeiro. A porta manual e a
> importação existem para o resíduo — o que ninguém no sistema sabe — e só o resíduo justifica o
> custo delas.**

Aplicado agora, o inventário fica assim (§1.2). Aplicado antes, a Onda 1 teria nascido com o razão
cheio e a Onda 3 nunca teria sido a onda seguinte.

**(5) A quinta, escrita depois de os @sm expandirem esta onda em 11 stories, e é a que mais me
serve: eu descrevo conjuntos e nunca escrevo um membro.**

Num único dia, quatro falhas minhas são o **mesmo defeito**:

| Onde | O conjunto que eu descrevi | O membro que teria derrubado tudo | Custo |
|---|---|---|---|
| **§9.3** | *"toda `Payable` paga e toda `Charge` recebida precisam ter conta bancária informada"* | uma `Charge` paga pelo webhook do Asaas — tem `transaction_id`, nunca terá conta | 5s |
| **§9.2.1** | *"payables em `scheduled` cuja data já passou"* | um payable no dia seguinte à varredura que eu especifiquei duas seções antes | 5s |
| **epic, "Ativos a reusar"** | *"`bank_audit`, entregue pelas Ondas 0 e 1, não recriar"* | `ls apps/api/app/scripts/` | 2s |
| **§3.1 do epic (versão da manhã)** | *"se a divergência for pequena, as ondas de import são over-engineering"* | a divergência do tenant do fundador **hoje**: razão vazio, número enorme | 5s |

Não é falta de rigor: os predicados estão bem escritos, as justificativas estão certas, os trade-offs
estão medidos. É que **eu paro no ponto em que a descrição está boa, e a descrição fica boa antes de
o conjunto estar certo.**

**Por que isso se concentra no critério de decisão.** Todo o resto deste design tem **consumidor
mecânico**: uma função é chamada na página seguinte, um índice é criado por uma migration, uma
invariante ganha teste no CI, um contrato de schema é consumido por um schema de saída. Esses
consumidores **protestam** — errei o `origin_id` na §8 e a §3.2 protestou, através de um @sm, antes de
virar código.

O critério de decisão é **o único artefato do design cujo consumidor é um humano num ciclo futuro**.
Não há quem o chame enquanto eu o escrevo, e humanos não levantam `TypeError`: quem lê *"toda `Charge`
recebida precisa ter conta bancária informada"* assente, porque a frase é razoável. Ela é razoável
**e** insatisfazível, e não existe nada entre as duas coisas que dispare. A §3.1/§9.3 não erra mais
porque seja mais difícil — **erra mais porque é a única seção sem ninguém para contradizê-la.**

> **REGRA DE MÉTODO — INSTANCIAÇÃO OBRIGATÓRIA.**
>
> Todo conjunto definido por descrição num documento de arquitetura — uma pré-condição com "toda X",
> uma população de regra, uma lista de ativos, um critério de gate — **nasce com pelo menos um membro
> escrito e pelo menos um não-membro escrito, no mesmo parágrafo.**
>
> - Sem conseguir escrever o **membro**, o conjunto é vazio — e eu descobri agora, não daqui a três
>   ciclos de conferência.
> - Sem conseguir escrever o **não-membro**, a condição é trivial: não separa nada e não decide nada.
>
> **Corolário:** em critério de decisão a regra é **obrigatória**, não recomendada. É o único
> artefato sem consumidor mecânico; todos os outros têm quem os contradiga na página seguinte, e este
> não tem ninguém até o dia em que alguém precisa decidir com ele na mão — e nesse dia a decisão já
> está sendo tomada.
>
> **Teste da regra contra o dia de hoje:** ela teria pego as quatro. Nenhuma exigia mais análise;
> todas exigiam **um exemplo**.

A §9.3 reescrita traz o par membro/não-membro dentro do bloco normativo — não como ilustração, como
parte da definição.

### 1.2 A varredura pedida: o que MAIS na Onda 1 pede o que o sistema já sabe

Eventos que já existem no e1p e significam *"dinheiro se moveu numa conta real"*:

| Evento | Código | O sistema já sabe | Onda 1 gera movimento? |
|---|---|---|---|
| Baixa de Contas a Pagar | `payables.apply_paid:241` | valor, data, fornecedor, plano de contas, centro de custo | **Não** — o buraco principal |
| Comprovante vinculado com baixa | `payables/receipts.link_receipt:191` → `apply_paid` | tudo acima + o arquivo, capturado no ato | **Não** (herda o de cima) |
| Cobrança paga pelo trilho | `receivables.mark_paid:380` | valor, data, cliente | **Não — e está certo.** O dinheiro cai na carteira, não no banco |
| Cobrança paga **fora** do trilho | **não existe caminho nenhum** | — | Não há o que gerar: a porta não existe |
| Rendimento de aplicação | `investments.register_yield` | valor, data, conta | **Não** (adiado para a Onda 2 original, §3.4b) |
| Payout da Carteira | `wallet.request_payout:227` | valor, data | **Não** (adiado para a Onda 6) |
| Transferência entre contas próprias | não existe | — | Não modelado |

**Cinco eventos que o sistema conhece; zero ligados.** E a única porta construída pede digitação.
A crítica do fundador está certa e é mais ampla do que o gap `payables → bank`: **a Onda 1 entregou
o plano 3 sem nenhum afluente.**

Os três candidatos que o coordenador levantou, julgados:

**(a) A bandeja de comprovantes / REQ-12 / conflito C3 — o conflito muda de natureza, e a metade que
sobra fica decidida.**

O REQ-12 é sobre a **porta de entrada do arquivo**; a Onda 1 não importa arquivo nenhum, então o C3
não era acionável. Com a Onda 2, a relação **inverte**: a bandeja deixa de ser uma porta paralela e
passa a ser **a porta que já carrega o evento de pagamento**. `link_receipt(mark_paid=True)` chama
`apply_paid`. Se `apply_paid` passa a gerar o movimento, então o share sheet do Android e o Atalho do
iOS — a captura mais barata do produto inteiro, fisicamente no instante do pagamento — **começam a
alimentar o razão bancário de graça, com zero tela nova.** Isso é, sozinho, o argumento mais forte
para a conta ser obrigatória **em `apply_paid`** e não numa tela nova qualquer: é o único lugar por
onde todos os caminhos de baixa já passam.

E fecho a metade que sobra do C3, agora, porque escrevê-la depois custa mais: **`POST
/bank/accounts/{id}/imports` fica revogado como porta primária.** Se a importação for liberada
(agora Onda 4), o arquivo entra pela infraestrutura de anexo/bandeja já existente
(`owner_type='bank_import'`), com a conta escolhida **depois** do upload — que é o que o REQ-12
pede. A rota dedicada sobrevive como caminho de desktop, não como o caminho.

**(b) `register_yield` / conflito C2 — resolvido, e agora por princípio em vez de por julgamento.**

O C2 opunha REQ-24 (*"`register_yield` não muda"*) ao design §3.4b (passa a criar também um
movimento). Sob a Regra da Origem (§2), não há mais um caso a julgar: rendimento é um evento que o
sistema originou, logo gera movimento, **pela mesma regra e pelo mesmo helper** que a baixa de
`payable`. A garantia IV1 da Story 5.6 (nunca chamar `mark_paid`/`build_transaction`) permanece
intacta — o movimento é do plano 3 e não encosta na Carteira. **C2 fica resolvido em favor do
design.** Mas ele *depende* de `investment_accounts.bank_account_id`, então viaja com a Onda 2b
(§8), não com esta.

**(c) O saldo de abertura — NÃO, e a distinção importa.**

O saldo de abertura é *o saldo do banco numa data*: um fato **sobre o banco**, que o sistema por
definição não conhece (é a premissa inteira do plano 3). Derivá-lo do histórico de `payables` seria
somar o que o sistema sabe e chamar de "o que o banco diz" — a circularidade da Regra 5, com a
divergência indo a zero por construção **no dia um**. É também o pedido mais barato do produto
(5 segundos no app do banco, uma vez por conta). **Confirmar, não derivar.**

**Mas há uma coisa adjacente que o sistema pode e deve fazer, e ela é o princípio do fundador
aplicado sem violar a regra:** quando o dono cadastra a conta, o e1p **já sabe** a data da conta a
pagar mais antiga que ele vai querer trazer. Se a `opening_date` for hoje, todas as 45 baixas
históricas ficam impossíveis de lançar (§4.3). O sistema tem essa informação e deve dizê-la:

> *"Você tem 45 contas pagas entre 12/03 e ontem. Se esta conta abrir hoje, elas não vão entrar no
> extrato do e1p. Quer abrir em 11/03 e informar o saldo daquele dia?"*

O e1p não inventa o número — ele diz **qual número ir buscar**. Essa é a forma correta de "sistema
integrado" para um dado externo.

**Resposta honesta e curta à pergunta do coordenador:** sim, em mais de um lugar a Onda 1 pediu o que
o sistema já sabia — cinco eventos e a porta de entrada do arquivo. O saldo de abertura **não** é um
desses casos, e confundi-lo com eles quebraria a Regra 5.

Um sexto, menor, na mesma família: o formulário de movimento manual pede `counterparty_name` e
`counterparty_document`. Num movimento gerado por `payable`, eles vêm de `supplier` (e, quando houver
`contract_id → client`, do documento do cliente). O caminho gerado preenche; o manual continua
perguntando, porque ali não há de onde tirar.

### 1.3 O que fazer com o que já está em produção

**Nada é removido, nada é reescrito, nenhuma linha de dado é migrada.** As três tabelas, o saldo
derivado, o checkpoint, a conferência, os gates da Regra dos Planos e as duas telas são o substrato
**correto** e são reusados inteiros. A Onda 1 não errou o que construiu; ela deixou de construir os
afluentes.

O que muda é **quem escreve** `bank_transactions`: de *"só o usuário, à mão"* para *"o sistema, a
partir dos eventos que ele já tem — e o usuário para o que só existe no banco"*. Isso é aditivo:
`source='manual'` continua legal e continua funcionando; o formulário manual é **curado**, não
removido (§7). Uma migration aditiva (colunas nullable), zero backfill de dado existente.

---

## 2. A Regra da Origem (normativa, testável)

> **REGRA DA ORIGEM.**
> **(a)** Todo evento do e1p que significa *"dinheiro entrou ou saiu de uma conta real do dono"*
> gera **exatamente um** `bank_transaction`, **na mesma transação** do evento, e esse movimento
> **nasce conciliado** (`status='matched'`) — o e1p originou os dois lados, não há julgamento a
> fazer.
> **(b)** Esse movimento carrega `origin_id` apontando para o lançamento que o gerou, e a relação é
> **1:1**: um lançamento de origem produz no máximo um movimento, garantido por índice único.
> **(c)** O ciclo de vida do movimento é **espelho** do lançamento de origem: corrigir a conta ou a
> data **move** o movimento; estornar o lançamento **apaga** o movimento. Nunca duplica, nunca
> deixa órfão.
> **(d)** Um movimento de origem do sistema **não é editável nem ignorável** pela tela de
> movimentos: quem quer mudá-lo mexe no lançamento de origem. A única exceção é
> `user_description`, que é rótulo, não fato.
> **(e)** Lançamento manual e importação existem para o **resíduo** — o que nenhum evento do sistema
> conhece. Uma porta manual para algo que já tem porta própria é digitação dupla, e digitação dupla
> é o defeito que este produto promete não impor.

E a regra irmã, que preserva a Regra 5:

> **A Regra da Origem alimenta `saldo_sistema`, NUNCA `saldo_banco`.** O checkpoint continua sendo a
> única fonte do lado externo e continua não sendo corrigido por nada. A divergência diminuir porque
> o sistema passou a saber mais é o objetivo; a divergência diminuir porque um lado foi ajustado
> contra o outro continua proibido.

---

## 3. Modelo de dados

Convenções herdadas sem exceção: `tenant_id` + RLS `FORCE`, referência solta sem FK dura, dinheiro em
centavos `BigInteger`, migration aditiva encadeada **após o head real no momento da implementação**
(head hoje: `0060_bank_balance_checkpoints`; o design **não** fixa número).

### 3.1 `source` ganha `payable` e `charge` — e a mancha que eu assumo em vez de esconder

```python
# bank/models.py — CONTRATO
SOURCE_MANUAL   = "manual"     # o usuário transcreveu um fato do banco
SOURCE_OFX      = "ofx"        # arquivo (Onda 4)
SOURCE_CSV      = "csv"        # arquivo (Onda 4)
SOURCE_PAYABLE  = "payable"    # NOVO — baixa de Contas a Pagar
SOURCE_CHARGE   = "charge"     # NOVO — recebimento fora do trilho
SOURCE_TRANSFER = "transfer"   # perna de transferência entre contas próprias
SOURCE_YIELD    = "yield"      # rendimento de aplicação (Onda 2b)
SOURCE_PAYOUT   = "payout"     # payout da Carteira (Onda 3 na ordem nova)

# Os DOIS conjuntos contra os quais TODA regra deste design é escrita.
SOURCES_SISTEMA = (SOURCE_PAYABLE, SOURCE_CHARGE, SOURCE_TRANSFER, SOURCE_YIELD, SOURCE_PAYOUT)
SOURCES_EXTERNA = (SOURCE_MANUAL, SOURCE_OFX, SOURCE_CSV)
```

**Dito em voz alta, porque é o defeito D-3 numa forma que eu decidi não consertar:** `source` já
mistura dois eixos. `manual|ofx|csv` são **portas de entrada**; `transfer|yield|payout` são **origens
de lançamento**. Eu criei essa mistura no design-mãe §2.2 e ela foi para produção na migration 0059.

Por que **não** conserto agora: consertar exige reescrever uma coluna com dado em produção, sob
`FORCE RLS` (a armadilha da 0046), para benefício conceitual e zero benefício de usuário. O custo é
real e o ganho é estético.

Por que a mancha **não infecta**: nenhuma regra deste design é escrita contra um valor individual de
`source`. Todas são escritas contra `SOURCES_SISTEMA` / `SOURCES_EXTERNA`, e a pergunta que esses
dois conjuntos respondem é única e limpa — *"o e1p conhece o lançamento de negócio que corresponde a
esta linha?"*. Acrescentar uma origem nova no futuro é **uma entrada numa tupla**, e nenhuma regra
muda. É a mitigação que a §1.1(3) me obriga a escrever em vez de deixar implícita.

**A invariante que amarra os dois campos:**

> **INVARIANTE DA ORIGEM:** `source ∈ SOURCES_SISTEMA` ⟺ `origin_id IS NOT NULL`.
> Teste: `test_origem_do_sistema_sempre_tem_origin_id` (as duas direções).

### 3.2 `bank_transactions` — duas colunas

```sql
-- ILUSTRATIVO
ALTER TABLE bank_transactions ADD COLUMN origin_id VARCHAR(64) NULL;   -- CHAVE DE ORIGEM (ver abaixo)

-- ÚNICO PARCIAL: "uma unidade de sincronização gera no máximo UM movimento".
-- tenant_id primeiro (índice único é global e não respeita RLS — mesmo motivo de todos os outros).
CREATE UNIQUE INDEX uq_bank_transactions_origin
    ON bank_transactions (tenant_id, source, origin_id)
    WHERE origin_id IS NOT NULL;
```

> ⚠️ **CORRIGIDO EM 2026-07-30 (ratificação, C-3):** a largura era `VARCHAR(36)` e o conceito era
> *"id do lançamento de origem"*. As duas coisas colidiam com a §8 (transferência = duas pernas). O
> conflito não era entre as seções; era que eu escrevi as duas com **conceitos diferentes de
> `origin_id`** e nunca percebi, porque para `payable` e `charge` os dois coincidem.

> **`origin_id` é a CHAVE DE ORIGEM, não "o id do lançamento" (normativo).**
>
> Para origens de **perna única** (`payable`, `charge`, `yield`, `payout`) ela **é** exatamente o id
> do lançamento. Para origens de **múltiplas pernas**, ela é `f"{id}:{perna}"`, com `perna` num
> vocabulário fechado por `source` (hoje: `out`/`in`, só para `transfer` — §8).
>
> O que `origin_id` garante é a **unicidade da unidade de sincronização** — e a unidade de
> sincronização de uma transferência é **a perna**, não a transferência. O pareamento entre pernas é
> trabalho de `transfer_id` (`bank/models.py:278`), que existe exatamente para isso.

**Largura `VARCHAR(64)`, e a razão é assimetria de custo:** `uuid4` (36) + `":out"` (4) = 40, e o
vocabulário de perna pode crescer. Em Postgres, `VARCHAR(n)` é armazenamento **variável** — 64 e 36
custam o mesmo em disco, e o `n` é uma restrição, não uma reserva. O custo de errar para menos é
`ALTER COLUMN` sobre tabela com dado sob `FORCE ROW LEVEL SECURITY`: a armadilha da 0046, que o ADR
0003 nomeia como o único ponto desse tipo do épico. **Teste normativo:**
`test_origin_id_cabe_na_coluna` — para cada forma de chave construída no repositório,
`len(chave) <= <largura declarada no model>`. Uma origem de várias pernas nova reprova em CI, não no
`ALTER COLUMN`.

Formas de discriminação **rejeitadas**, com o motivo:

| Alternativa | Veredito |
|---|---|
| Coluna `leg` no índice `(tenant, source, origin_id, leg)` | **Rejeitada.** `leg` seria `NULL` para toda origem de perna única, e no Postgres **`NULL` é distinto de `NULL` em índice único por padrão** — `(t,'payable',id,NULL)` deixaria de colidir consigo mesma e o índice perderia a garantia para **todas** as outras origens, em silêncio. Exigiria `NULLS NOT DISTINCT` (PG15+) ou uma sentinela |
| Incluir `bank_account_id` no índice | **Rejeitada.** As pernas deixariam de colidir, e o mesmo `payable` passaria a poder gerar movimento em duas contas — destrói a invariante 1:1 que o índice existe para garantir |
| `origin_id = transfer.id` nas duas + índice relaxado | **Rejeitada.** Destrói a idempotência na origem onde ela mais importa: um retry move o dinheiro duas vezes |

**É este índice — e não o `dedup_hash` — a garantia de idempotência que o requisito do fundador
pede.** Preencher a conta duas vezes, reprocessar a mesma baixa, um retry de request: o banco recusa
a segunda linha. Fail-closed, no espírito da RLS. `dedup_hash` continua `NOT NULL` e, para origem de
sistema, vale `sha256(f"{source}|{origin_id}")` — **sem o `bank_account_id`**, deliberadamente, para
que **trocar a conta não exija reidratar o hash**: é a mesma linha mudando de conta, não uma linha
nova.

`origin_type` **não é criado**: para todo valor de `SOURCES_SISTEMA`, `source` já responde "qual tipo
de lançamento". Um segundo campo dizendo a mesma coisa seria a terceira encarnação do D-3.

### 3.3 `payables` — duas colunas

```sql
-- ILUSTRATIVO
ALTER TABLE payables ADD COLUMN bank_account_id      VARCHAR(36) NULL;  -- de qual conta o dinheiro SAIU
ALTER TABLE payables ADD COLUMN bank_transaction_id  VARCHAR(36) NULL;  -- o movimento gerado (1:1)
CREATE INDEX ix_payables_bank_account ON payables (tenant_id, bank_account_id);
```

**Por que dos DOIS lados, e por que não é redundância:**

| Pergunta | Quem responde | Existe quando |
|---|---|---|
| *"De qual conta este pagamento saiu?"* | `payables.bank_account_id` | Desde a baixa — **inclusive quando o movimento ainda não pôde ser gerado** (§4.3) |
| *"Este movimento é sintético? De quem?"* | `bank_transactions.source` + `origin_id` | Sempre que o movimento existe |
| *"Qual é o movimento desta conta paga?"* | `payables.bank_transaction_id` | Conveniência de leitura |

**Regra de autoridade, para não haver duas verdades:** `payables.bank_account_id` é a **decisão do
usuário** e é autoritativa. `bank_transactions.bank_account_id` é **derivada** dela pelo sincronizador
(§3.5) e nunca é escrita por outro caminho. `payables.bank_transaction_id` é **cache de leitura**: se
divergir do movimento com `origin_id = payable.id`, **quem manda é o `origin_id`**.

> ⚠️ **CORRIGIDO EM 2026-07-30 (ratificação, C-4).** Esta seção citava
> `python -m app.scripts.bank_audit` como quem reporta a divergência. **Esse script NÃO EXISTE** —
> `grep` em `apps/api` devolve zero, e `app/scripts/` tem só `migrate_attachments_to_s3.py` e
> `scan_orphan_storage.py`. A citação vinha do design-mãe §2.2 e foi propagada ao ADR e ao epic (que
> chegou a listá-lo entre os *"ativos entregues pelas Ondas 0 e 1 — não recriar"*). Nenhuma story
> pode citá-lo como existente.

**O que fica no lugar, e por que um teste basta aqui:**

> A divergência entre o cache e o `origin_id` só é alcançável **por bug**. `sync_origin_movement`
> (§3.5) é o **único** escritor do movimento e devolve a linha na mesma chamada e na mesma transação;
> o chamador grava o cache com o que recebeu. Não há segundo caminho, não há concorrência, não há
> materialização assíncrona.
>
> **Condição alcançável só por bug se prova com teste, não com script.** Um script que ninguém tem
> gatilho para rodar não é garantia; é intenção documentada.
>
> Obrigação da Onda 2: `test_cache_de_movimento_nunca_diverge_do_origin_id`, exercitando os **cinco**
> caminhos de mutação — baixar, trocar conta, trocar data, estornar, repagar — e afirmando em cada um
> que `payable.bank_transaction_id` aponta para o movimento com `origin_id = payable.id`, ou que os
> dois são `NULL`.

O **script** volta a ser necessário na **Onda 5**, e aí como pré-requisito dela: é lá que existe
`_refresh_status` (hoje também inexistente — `bank/service.py:826` o descreve como trabalho da onda
de conciliação) e é lá que a divergência passa a ser alcançável **sem bug**, por matcher concorrente
e vínculo parcial.

**Sem FK dura**, padrão do projeto (`charges.client_id`, `payables.cost_center_id`).

**Por que coluna e não `bank_reconciliations` — e por que isso NÃO contradiz a §2.3 do design-mãe.**
A §2.3 rejeitou a coluna por causa de N:N (um Pix quitando duas contas) e do estado
sugestão/confirmação. Ambos são propriedades de **casar uma linha externa contra registros
internos**. Um movimento originado pelo sistema é 1:1 por construção, nasce confirmado e não tem
ambiguidade nenhuma. Usar a tabela de ligação aqui obrigaria a construir a tabela inteira da Onda 5
agora, a inventar um `confirmed_at` para algo que ninguém confirma, e a pôr um join no caminho mais
quente do módulo. **A §2.3 continua valendo para o que ela decidiu; este caso não é ele.**

### 3.4 `charges` — uma coluna, e a invariante que separa os planos

```sql
-- ILUSTRATIVO
ALTER TABLE charges ADD COLUMN bank_account_id     VARCHAR(36) NULL;  -- conta onde o Pix caiu
ALTER TABLE charges ADD COLUMN bank_transaction_id VARCHAR(36) NULL;
```

> **INVARIANTE DO TRILHO (normativa, testável).** Para toda `Charge` com `status='paid'`,
> **exatamente um** de `transaction_id` e `bank_account_id` é não-nulo. Nunca os dois, nunca nenhum.
>
> - `transaction_id IS NOT NULL` → entrou pelo **trilho**: plano 1, split aplicado,
>   `PlatformEarning` criado, **nenhum** `bank_transaction`.
> - `bank_account_id IS NOT NULL` → entrou **fora do trilho**: plano 3, **nenhuma** `Transaction`,
>   **nenhum** `PlatformEarning`, um `bank_transaction` de crédito.
>
> Testes: `test_invariante_do_trilho` (varre todas as charges pagas de um cenário completo) +
> `test_recebimento_fora_do_trilho_nao_cria_platform_earning`.

**Não existe coluna `payment_route`.** A rota é **derivada** dos dois ponteiros
(`charge.route == "trilho" if transaction_id else "banco"`), porque um rótulo separado pode divergir
do fato e vira a terceira fonte de verdade. É a lição D-3 aplicada preventivamente desta vez.

### 3.5 O sincronizador — uma função, um lugar

```python
# app/modules/bank/origin.py — CONTRATO
def sync_origin_movement(
    db: Session, *, tenant_id: str, actor: str,
    source: str,                    # ∈ SOURCES_SISTEMA
    origin_id: str,
    bank_account_id: str | None,    # None ⇒ o lançamento não está mais liquidado
    posted_at: date | None,
    amount_cents: int | None,       # COM SINAL: − para payable, + para charge
    description: str,
    counterparty_name: str = "",
    counterparty_document: str = "",
    operation_nature: str | None = None,
) -> BankTransaction | None:
    """Deixa o razão bancário coerente com UM lançamento de origem. Idempotente. NÃO commita.

    Ausente → cria. Presente → atualiza (conta, data, valor, hash). Origem desliquidada
    (bank_account_id=None) → apaga. É a ÚNICA função do repositório que escreve
    `source ∈ SOURCES_SISTEMA`; qualquer segundo caminho torna a Regra da Origem inauditável.
    """
```

**Não commita**, pelo mesmo motivo de `build_payable`/`apply_paid`/`build_charge`: o movimento e a
baixa entram na **mesma transação**. Um dos dois sem o outro é o estado que este design existe para
tornar impossível.

**Direção de import:** `payables` e `receivables` passam a importar `app.modules.bank`. A Regra dos
Planos §1.3b proíbe **`wallet` → `bank`**, e só isso; `bank → wallet` é permitido e
`payables/receivables → bank` nunca foi restrito. Ainda assim, o gate estrutural
`tests/test_money_planes.py` deve ganhar a asserção positiva: **`bank` continua sem importar
`payables`/`receivables`** — a dependência é de negócio para banco, nunca a volta. Sem isso, o
primeiro atalho de conveniência recria um ciclo.

---

## 4. Baixa de Contas a Pagar gera o movimento

### 4.1 Conta obrigatória — e o que isso quebra, dito sem eufemismo

```python
# payables/service.py — CONTRATO
def apply_paid(
    db, *, payable_id: str, tenant_id: str, actor: str,
    bank_account_id: str,          # OBRIGATÓRIO — sem default
    paid_on: date | None = None,   # None ⇒ default da §4.2
) -> Payable: ...
```

Chamadores existentes que **têm** de mudar (grep completo — são todos):
`payables/router.py:108` (`POST /bills/{id}/pay`), `payables/receipts.link_receipt:191`,
`payables/receipts.new_bill_from_receipt:218`.

**O custo que a decisão do fundador carrega, e que precisa estar escrito:** a partir desta onda,
**um tenant sem conta bancária cadastrada não consegue dar baixa em conta a pagar.** Isso torna
`bank_accounts` pré-requisito de um fluxo central que hoje funciona sozinho — é mudança de
onboarding, não só de formulário.

Três saídas foram consideradas:

| Saída | Veredito |
|---|---|
| **409 acionável** — recusa a baixa e devolve `{"acao": "cadastrar_conta"}`, a UI abre o cadastro embutido e volta para o pagamento | **ESCOLHIDA.** Um passo a mais, uma vez na vida do tenant. É a única que preserva a completude que o épico existe para produzir |
| Criar sozinho uma conta `kind='cash'` chamada "Caixa" | Rejeitada: inventa dado (Art. IV) e produz conta-fantasma que ninguém sabe explicar |
| Permitir nulo quando o tenant tem zero contas | Rejeitada: é "opcional" com outro nome — *"opcional significa que alguém pula"* (fundador). E cria um terceiro estado de "não sei" que a conferência teria de aprender a reportar |

Precedente que sustenta a escolha: o 🟡 *"nenhuma conta bancária cadastrada"* já aparece para
**todos** os tenants, sem opt-in e sem dispensa, por decisão do fundador na Onda 1. Tornar a conta
pré-requisito é o passo consistente com aquela decisão, não uma imposição nova.

### 4.2 A data da baixa — `due_date` como default, e a data futura liberada

> **Decisão do fundador (2026-07-30), que REJEITA a recomendação anterior deste documento:**
> *"deixar habilitado no vencimento, pois se estiver fazendo retroativo, pq não deu certo no dia — e
> no futuro também permitir, pq posso estar **agendando**."*
>
> Meu `min(due_date, hoje)` estava resolvendo o problema errado. Ele existia só para não colidir com
> a guarda `posted_at > hoje` — ou seja, **eu estava desenhando o produto em volta de uma limitação
> do meu próprio modelo**, e o preço era mutilar o default no caso que ele mais usa. E o caso de uso
> que ele trouxe — **agendamento de pagamento no app do banco** — não estava em lugar nenhum do Epic
> 8. Não é ele ignorando o argumento; é o desenho não conhecendo o fluxo real.

Estado atual: `payables/service.py:258` → `p.paid_at = datetime.now(UTC)`, cravado.

**Contrato:** `paid_on` default = `due_date`, sempre visível, sempre editável, **sem teto superior** e
com piso no `opening_date` da conta (§4.3).

O coordenador leu certo: o defeito não é a data futura, é **existir superfície de saldo sem corte de
data**. A guarda muda de forma:

> **De:** *"recuse `posted_at` futuro"* (`_validate_posted_at`).
> **Para:** **nenhuma superfície de saldo corrente inclui o futuro.** Um movimento agendado é
> registrado com verdade — o dinheiro *vai* sair no dia 15 — e simplesmente **não conta até lá**.

#### 4.2.0 Onde fica o corte da guarda — e por que o externo continua recusando o futuro

> **ACRESCENTADO EM 2026-07-30 (ratificação, C-6).** O design enunciava a mudança de *forma* da
> guarda e não dizia **onde** fica o corte. Sem isso, nenhuma story libera o futuro e o agendamento
> leva 422. A atribuição está correta e é rastreável: a **8.10** declara que não mexe, a **8.11**
> declara que não mexe, a **8.12** põe teto em hoje `[CORTE DO @PM]`, e a **8.14** libera. Ratificado.

> **O corte é por `source`, e por `source` apenas (normativo).**
>
> - `source ∈ SOURCES_EXTERNA` (`manual`, `ofx`, `csv`) → **continua recusando** `posted_at` futuro,
>   com a mensagem inalterada;
> - `source ∈ SOURCES_SISTEMA` (o caminho de `sync_origin_movement`) → **aceita** futuro;
> - o **piso** (`posted_at > opening_date`) vale para os dois, sem exceção.
>
> ⚠️ **Não existe um booleano `permite_futuro` decidido pelo chamador.** Um booleano é o parâmetro
> que alguém passa `True` no caminho manual, um dia, por conveniência — e nenhum gate de AST o pega,
> porque não há import envolvido. O eixo já existe e é `source`; **toda regra desta onda é escrita
> contra `SOURCES_SISTEMA`/`SOURCES_EXTERNA`** (§3.1). Um eixo, uma pergunta.

**Por que a guarda não está sendo enfraquecida — está sendo devolvida ao próprio escopo.** A
justificativa dela está escrita no código (`bank/service.py:614-616`): *"extrato bancário é fato
passado. Data futura é erro de digitação"*. **Isso descreve transcrição.** Uma justificativa sobre
transcrição não pode governar origem — é exatamente o defeito que a §1.1(2) deste documento nomeia
(herdei um limite traçado por outro motivo e o generalizei).

**E o movimento externo continua recusando o futuro na Onda 4 — normativo, para não ser reaberto:**

> **O e1p pode afirmar o futuro do que ele mesmo agendou; não pode afirmar o futuro do que outro
> atestou.**
>
> Um OFX descreve o que já aconteceu. `posted_at` futuro num arquivo importado é erro de parser ou
> arquivo corrompido — não é fato. Se um dia aparecer um caso legítimo (débito pré-autorizado exibido
> no extrato), o tratamento honesto é **recusar e mandar um humano olhar**, nunca aceitar em silêncio
> uma afirmação sobre o futuro vinda de uma fonte que não pode conhecê-lo. E a proteção contra erro
> de ano na digitação manual fica, e continua valendo a pena.

#### 4.2.1 A varredura: o que quebra de fato com `posted_at` futuro

Verifiquei todos os consumidores. **Duas surpresas boas e um defeito concentrado.**

| Superfície | Chamada real | Veredito |
|---|---|---|
| Projeção — `saldo_inicial` | `active_balance_total(db, until=today, …)` — `projection.py:329` | ✅ **JÁ SEGURA.** O `until=today` já está lá, com docstring dizendo *"a MESMA âncora do resto da projeção"* |
| Conferência | `derived_balance(until=saldo_banco_data)` — `reconciliation.py:358` | ✅ **JÁ SEGURA por construção.** A regra 6 do `CLAUDE.md` (mesma data dos dois lados) faz o trabalho: movimento posterior ao `reference_date` já fica de fora |
| Checkpoint | `_validate_reference_date:909` recusa data futura | ✅ segura — não existe checkpoint depois de um agendamento |
| DRE / Lucratividade | competência, `status != canceled` (`dre.py:124,290,437,634`) | ✅ **zero impacto**, verificado nas 4 agregações |
| **`GET /bank/accounts`** (lista da 8.7) | `derived_balances_as_of(db, include_archived=…)` — `router.py:128`, **sem `as_of`** | ❌ **QUEBRA** |
| **"Total em contas" / "Disponível como caixa"** | `contas.ts:219,240,248` somam o `saldo_derivado_cents` da lista acima | ❌ **QUEBRA** (derivado do anterior) |
| **CRUD de conta** (4 respostas) | `derived_balance(db, bank_account_id=acc.id)` — `router.py:140,153,169,184` | ❌ **QUEBRA** |
| **`GET /accounts/{id}/balance`** | `until` de query, default `None` — `router.py:202` | ❌ **QUEBRA por default** |

**A leitura do coordenador se sustenta, e sai mais barata do que ele supôs:** as duas superfícies que
mais importam já passam `until` explícito. O defeito está **concentrado em `bank/router.py`, em 6
chamadas do mesmo módulo**, todas resolvidas pelo mesmo movimento.

**A correção — um parâmetro, um significado, e o significado seguro é o default:**

```python
# bank/service.py — CONTRATO (mudança de SIGNIFICADO do default, não de assinatura)
def derived_balance(db, *, bank_account_id: str, until: date | None = None) -> int:
    """`until=None` significa **HOJE**, não "sem limite superior".

    Fail-closed: nenhuma superfície corrente pode incluir movimento agendado por esquecimento de
    passar a data. Para o histórico completo (inclusive futuro), passe `date.max` — feio de
    propósito, para que incluir o futuro seja sempre decisão explícita e visível no diff.
    """
```

**Não** invento um segundo parâmetro (`incluir_futuro=True`): dois campos para a mesma pergunta é o
defeito D-3 outra vez. Um campo, um significado. Os 6 chamadores querem "hoje"; nenhum quer o
comportamento antigo.

**Bônus que o contrato já previa:** `BankBalanceOut` devolve `until` no payload porque *"um saldo sem
a data em que foi apurado é um número que não dá para conferir"* (`router.py:189-206`). Com o default
virando hoje, esse campo **para de vir `null`** e a tela ganha *"saldo em 30/07"* de graça.

**A tela 8.7 ganha um terceiro número:** **"Agendado para sair"** (e "Agendado para entrar", quando
houver recebimento agendado), ao lado dos dois totais. Sem ele o dono agenda um pagamento e não o vê
em lugar nenhum. ⚠️ O rótulo novo passa pelos **mesmos testes de colisão** que o UX-001 instituiu
(`contas.test.ts:157-168`): não pode ser, nem conter, `ROTULO_BANCO`, `TOTAL_EM_CONTAS_LABEL` nem
`DISPONIVEL_CAIXA_LABEL`.

#### 4.2.2 `paid` NÃO é o estado certo para uma conta agendada — e há um bug que prova isso

**Resposta direta: estado próprio, `scheduled`.** Dois argumentos de princípio e um bug que apareceu
na varredura e que decide a questão sozinho.

**Princípio 1 — a disciplina do épico.** `status='paid'` é uma **afirmação**: *"esta conta foi
paga"*. Com data futura ela é falsa hoje e pode nunca virar verdade (saldo insuficiente, banco
recusou, agendamento cancelado no app). Um estado que afirma o que não aconteceu é literalmente o que
a Onda 0 removeu da Projeção — *"suprima a afirmação, nunca o número"*. Aqui o **número** é a data
agendada e pode ser exibido à vontade; o que não se pode é **afirmar a baixa**.

**Princípio 2 — a pergunta que o modelo precisa responder.** *"Esta conta ainda vai sair da minha
conta?"* Com `scheduled` é `status == 'scheduled'`. Com `paid` é `status == 'paid' AND paid_at >
today` — um predicado que se lê **"pago no futuro"**, contradição em termos, e que teria de ser
replicado em cinco lugares (`payment_queue`, `summary`, `_window_sums`, `list_candidates`, a regra do
Diagnóstico). Cinco cópias de um predicado autocontraditório é a definição de o modelo estar errado.

**E o bug, que fecha o argumento — ele existe nas DUAS opções se ninguém mexer:**

- `projection._window_sums:370-373` filtra `model.status == open_status` (= `'open'`);
- `projection._saldo_inicial:329` usa `active_balance_total(until=today)`.

Logo, uma conta agendada para o dia 15, marcada `paid` com data futura:
1. **sai dos fluxos de saída** da projeção (não é `open`);
2. **o movimento não entra no saldo inicial** (é futuro).

> **Resultado: os R$ 5.000 agendados somem por completo da Projeção.** O saldo diz que você os tem, e
> nada diz que vão sair. É a **máquina de falso negativo da Onda 0 ressuscitada**, na mesma
> superfície que a Onda 0 existiu para consertar.

Com `scheduled` a correção é legível: `status IN ('open', 'scheduled')`, e para as agendadas a data de
caixa é a **data do débito**, não o `due_date` — o que torna a projeção *mais* precisa do que é hoje.
Com `paid` + futuro, a correção é o predicado contraditório acima, cinco vezes.

#### 4.2.3 O custo do estado próprio, medido no código

| Item | Custo verificado |
|---|---|
| `ALL_STATUSES` (`payables/models.py:23`) | +1 valor. Coluna é `String(12)` e `"scheduled"` tem 9 → **sem migration de tipo** |
| **DRE / Lucratividade** | **Zero.** `dre.py` filtra `status != canceled` nas 4 agregações — status novo passa direto. Verificado |
| `is_overdue` (`service.py:44`) | **Zero.** Já exige `status == STATUS_OPEN`; agendada não é atrasada (foi resolvida) |
| `payment_queue` | +1 balde **"Agendadas"** (com a data do débito) + 2 campos no `PaymentQueueSummary`. **Não some da Fila** — sai dos baldes de *vencimento*, porque a pergunta da Fila é *"o que preciso pagar"* e uma agendada já foi resolvida. Esconder é erro; misturar também |
| `summary()` | +1 campo `scheduled_cents`. Fora de `open_cents` (não é "a pagar") e fora de `paid_month_cents` (não saiu) |
| `projection._window_sums` | ~15 linhas: incluir agendadas pela **data do débito**. É a mudança mais delicada e é a que conserta o bug da §4.2.2 |
| `reverse_payable:291` | Passa a aceitar `scheduled` (cancelar agendamento), além de `paid` |
| `apply_paid:253` | Trata a transição `scheduled → paid` além da idempotência atual |
| `receipts.list_candidates:146` | Decidir se agendada entra em "pagas recentes" da bandeja. **Recomendo sim** — o comprovante do agendamento existe e é o que o dono tem na mão |
| **Promoção `scheduled → paid`** | O worker **já existe**: `app.worker.run_sweep` itera tenants sob `tenant_session`, é idempotente e roda em réplica única. +1 varredura de ~20 linhas |

**E o ponto que barateia tudo: o saldo derivado NÃO precisa do worker.** O movimento nasce com
`posted_at` = data agendada, e o saldo é **função da data** — ele entra sozinho quando o dia chega,
sem job nenhum. O worker só move o `status` do `Payable`, para a Fila e o resumo pararem de mostrá-lo
como agendado.

#### 4.2.3.1 O recorte que impede a contagem dupla no dia D — e o acoplamento invisível que o sustenta

> **ACRESCENTADO EM 2026-07-30 (ratificação, C-7).** Achado do @sm da Story 8.14, e ele não estava em
> nenhum documento desta onda. **Ratificado.**

As duas afirmações acima — *"o saldo derivado não precisa do worker"* e *"`_window_sums` soma
`status IN ('open','scheduled')`"* — estão as duas certas e, **juntas**, produzem uma subtração
dupla. No dia D, entre a meia-noite e a varredura: o movimento já tem `posted_at <= hoje`, logo já
entra em `active_balance_total(until=today)` (`_movements_sums` usa `posted_at <= until`,
**inclusivo** — `bank/service.py:302-304`); e o `Payable` ainda está `scheduled`, logo contaria de
novo nos fluxos de saída.

> **Recorte (normativo):** a população das agendadas em `_window_sums` é
> `status == 'scheduled'` **AND** `paid_at::date > today`. **A data manda, não o status
> materializado** — o mesmo princípio que faz `payment_queue` calcular seus baldes na leitura,
> *"sem precisar de job/cron"* (`payables/service.py:361-363`).

| Caso | `saldo_inicial` | `_window_sums` | Total |
|---|---|---|---|
| D > hoje | fora (movimento futuro) | **dentro** | 1× |
| D == hoje, antes da varredura | **dentro** | fora (predicado falso) | 1× |
| D == hoje, depois da varredura | **dentro** | fora (status é `paid`) | 1× |
| D < hoje, worker parado há dias | **dentro** | fora (predicado falso) | 1× |

**E a propriedade que isto compra vale mais do que o conserto:** com esse recorte, **a corretude da
Projeção deixa de depender da frequência do worker**. O worker vira o que o F-D11 diz que ele é —
cosmética de status para a Fila e o resumo — e não um componente do qual a aritmética depende. Se ele
parar uma semana, a Projeção continua certa.

O mesmo recorte vale, espelhado, para `Charge` no lado das entradas (§5, recebimento agendado). Um
predicado só, parametrizado, usado pelos dois — nunca um `if` por tipo dentro da função genérica, que
é o começo de duas funções fingindo ser uma.

> ⚠️ **O acoplamento invisível, escrito porque ele é a única forma de o recorte perder dinheiro.**
> O recorte tira a agendada de `_window_sums` quando a data chegou, **confiando** que o movimento
> está no `saldo_inicial`. Isso só é verdade porque:
>
> 1. **`_saldo_inicial` passa `until=today`** (`projection.py:327-331`). Trocado por `None` ou por
>    `SEM_CORTE`, a agendada futura passa a contar nos dois lugares e a dupla contagem volta, pelo
>    lado oposto. ⚠️ A Story **8.19** edita `_saldo_inicial` (a decisão de origem, não o `until`) —
>    **ela não pode alterar esse argumento**, e a Story 8.14 deve afirmá-lo por teste.
> 2. **Todo movimento de origem está dentro da janela do saldo derivado da sua conta**
>    (`posted_at > opening_date`). Se não estivesse, `_movements_sums` o excluiria (o `>` é estrito) e
>    o predicado do recorte também — **o dinheiro sumiria por completo da Projeção**. Hoje é
>    impossível dos dois lados: `apply_paid` valida o piso (422, §4.3) e `_validate_opening_date_move`
>    impede avançar a `opening_date` por cima de movimento (a correção do BANK-001). Garantia **por
>    construção**, e invisível — por isso está escrita.

Isso segue um precedente escrito do próprio projeto: `payment_queue` calcula os baldes **na leitura**,
*"nunca gravados — assim o balde de um item nunca fica desatualizado com a passagem do tempo, sem
precisar de job/cron"* (`payables/service.py:361-363`).

#### 4.2.4 Faseamento: `scheduled` entra JUNTO, não depois

Considerei entregar `paid` + data futura agora e o estado próprio depois. **Recomendo contra**, por
razão mecânica: se `paid`+futuro entrar primeiro, o backfill das 45 e os agendamentos ficam **no mesmo
status**, indistinguíveis a não ser por um predicado sobre a data — e separá-los depois é uma
**migration com backfill sobre dado existente, sob `FORCE RLS`**, a armadilha da 0046 que o próprio
ADR nomeia como o único ponto desse tipo no épico.

Custo de fazer junto: **~1/3 de onda a mais.** Custo de fazer depois: uma migration de dados que
ninguém quer escrever, mais o período em que a Projeção mente (§4.2.2).

**Guardas finais.** `paid_on` não tem teto; o piso é `> opening_date` da conta (§4.3). E o estado é
**derivado da data, não escolhido pelo usuário**: `paid_on` no futuro ⇒ `status='scheduled'`;
`paid_on` hoje ou no passado ⇒ `status='paid'`. Assim não existe o estado incoerente "agendada com
data de ontem" nem "paga para semana que vem". Invariante testável:
`status == 'scheduled' ⟺ paid_at.date() > hoje` **no momento da escrita** (depois disso, quem move é
o worker).

**`competence_date` NÃO muda junto.** Regra dura do projeto: caixa = `paid_at`, competência =
`competence_date`, nunca invertidos (`payables/models.py:6-9`). `paid_on` move fluxo de caixa,
projeção e o `bank_transaction`; **não** move a DRE nem a Lucratividade.
Teste: `test_alterar_data_de_baixa_nao_altera_dre` (snapshot antes/depois, idêntico campo a campo).

**Cobranças, com uma assimetria explícita:** o recebimento **fora do trilho** ganha `received_on` com
as mesmas regras — inclusive futuro ⇒ `scheduled`, para o Pix agendado que o cliente avisou. O caminho
do **gateway** mantém `paid_at = now()` do webhook e **não é editável**: é fato externo, atestado por
terceiro, e editá-lo transformaria uma testemunha em opinião. A simetria vale onde a semântica é
simétrica; aqui ela não é, e a assimetria é a informação.

### 4.3 A parede do backfill: `opening_date`

`_movements_sums` só soma `posted_at > opening_date`, e `_validate_posted_at` recusa `posted_at <=
opening_date` com 422 — porque o que aconteceu até a abertura **já está dentro** de
`opening_balance_cents` e contar de novo dobraria o valor. As duas guardas estão certas.

**Consequência CERTA, não provável, para o plano do fundador:** ele cadastrou o **C6 hoje**
(2026-07-30). As 45 baixas com `paid_on = due_date` anterior a hoje **serão todas recusadas** até que
a abertura recue. E recuar a abertura exige **o saldo do C6 naquela data** — número que só existe no
app do banco dele. **Este é o primeiro passo operacional da onda, antes de qualquer estorno**, e vale
avisá-lo agora: ele vai precisar abrir o extrato do C6 e anotar o saldo do dia anterior à conta mais
antiga que quiser trazer.

**Decisão: 422, e não "paga sem gerar movimento".** Aceitar a baixa sem o movimento é exatamente a
incompletude que a onda existe para eliminar, com o agravante de criar um terceiro estado de "não
sei" que a conferência teria de aprender a reportar. A mensagem nomeia as duas datas e as duas
saídas: *"mova a abertura desta conta para antes de DD/MM e informe o saldo daquele dia, ou escolha
outra conta"*.

**A saída existe e funciona:** `_validate_opening_date_move` só barra mover a data **para frente**;
recuar é permitido e é descrito na própria docstring como *"o caminho de reparo"*.

⚠️ **Mas há um buraco no caminho de reparo, e ele fica muito mais provável a partir desta onda:**
`update_account` permite recuar `opening_date` **sem exigir um novo `opening_balance_cents`** — e o
saldo de abertura antigo era o saldo *na data antiga*. Recuar sozinho produz um saldo de partida
errado e, portanto, uma divergência inventada — a mesma classe do BANK-001, pela porta oposta.

> **Guarda a incluir nesta onda:** quando `opening_date` recua, `opening_balance_cents` é
> **obrigatório no mesmo PATCH** (422 se ausente). Mensagem: *"o saldo de abertura que você
> informou era o saldo de DD/MM; para abrir a conta em DD/MM anterior, informe o saldo daquele
> dia"*. +2 testes (recuo com saldo → 200; recuo sem saldo → 422).

E o aviso pró-ativo da §1.2(c) no cadastro da conta, que evita a parede antes de bater nela.

### 4.4 A rota de pagamento — o retroativo saiu, o **agendamento** entrou no lugar

> **Decisão do fundador (F-D3): ele escolheu ESTORNAR E REPAGAR as 45.** Motivo dado: *rever conta a
> conta pode ser desejável para conferir valores*. Isso é legítimo e é mais do que operação — é
> auditoria manual, e ele conhece o custo (Agenda balançando) e aceitou.
>
> **Consequência: o argumento do retroativo para esta rota morreu.** Mas a rota **não morre com ele**,
> porque o `scheduled` da §4.2.2 lhe deu um caso de uso melhor.

O 409 de `update_payable` protege os **fatos de negócio** de um registro liquidado (valor,
vencimento, fornecedor, recorrência). `bank_account_id` e `paid_on` não são fatos de negócio: são
fatos **sobre o pagamento**, e o pagamento é justamente o que está sendo corrigido.

```
PATCH /payables/bills/{id}/payment    {bank_account_id?: str, paid_on?: date}
```

**O argumento novo — reagendamento é evento normal, não excepcional.** O dono agenda para 15/08 no
Itaú; o banco recusa por saldo, ou ele decide pagar pelo C6, ou empurra para 20/08. Sem esta rota,
**reagendar = estornar + repagar**, o que agora significa **apagar o movimento e recriá-lo**, com o
evento da Agenda indo e voltando. Isso é a operação pesada para um evento leve, e o evento leve
acontece todo mês.

Ou seja: a rota deixou de ser código de mutirão pontual (que era a objeção justa do coordenador) e
virou o caminho normal de uma coisa recorrente. **Recomendo manter.**

Se o coordenador quiser cortá-la mesmo assim, o custo é conhecido e tolerável: reagendar passa a ser
estorno + nova baixa, com delete + recreate do movimento. Funciona; só é caro e faz a Agenda piscar.
**Decisão dele** (F-D9).

- Aceita `status='paid'` **e `status='scheduled'`** (409 em conta aberta — não há pagamento a
  corrigir). Mudar `paid_on` pode **mover o estado** entre os dois, pela regra derivada da §4.2.4.
- **`PayableUpdate` não é tocado.** Isso importa: o `update_transaction` do módulo `bank` documenta
  que a guarda contra editar campo imutável é dupla *"de propósito"* — o campo não existe no schema
  **e** a função não faz `setattr` genérico. Mesma disciplina aqui: mantendo o schema do PATCH
  genérico intacto, ninguém torna um campo editável em conta paga por acidente, só acrescentando
  uma linha ao schema.
- Chama o **mesmo** `sync_origin_movement`. Zero segundo caminho.

**Precedente que mostra que isto é o padrão do projeto e não uma exceção nova:** o 409 de
`update_payable` **nunca foi absoluto**. `service.py:162` só dispara para
`(description, category, supplier, amount_cents, due_date, recurrence)`; `competence_date` e
`chart_account_id` **já são editáveis em conta paga** hoje, com a justificativa escrita na linha 170:
*"metadado contábil, não toca no caminho de dinheiro; ajustável a qualquer momento"*. A rota nova
estende o mesmo raciocínio para o eixo de caixa — com a diferença de que este **toca** dinheiro, e
por isso ganha rota nomeada em vez de entrar no PATCH genérico.

**Idempotência, troca e estorno — a mecânica completa:**

| Operação | O que acontece com o movimento |
|---|---|
| Baixar | `sync` cria. Índice único `(tenant, source, origin_id)` impede o segundo |
| Baixar de novo (retry, request duplicado) | `apply_paid` já é idempotente (`if status == PAID: return`); `sync` é upsert. **Nada muda** |
| Trocar a conta | **UPDATE** de `bank_account_id` na **mesma linha**. Move, não duplica. Os dois saldos derivados se corrigem sozinhos porque são derivados |
| Trocar a data | UPDATE de `posted_at`, revalidado contra a `opening_date` da conta destino. Pode mover `paid ⇄ scheduled` (regra derivada, §4.2.4) |
| Estornar (`POST /bills/{id}/reverse`) | **DELETE** do movimento, na mesma transação (§4.5) |
| Cancelar um agendamento | é o mesmo `reverse`, agora aceito também em `scheduled` (§4.5) |

**Os 45 estornos do fundador são seguros — confirmado, e vale registrar por quê.** Como **ainda não
existe movimento gerado**, o estorno hoje é uma troca de status pura, exatamente como o `CLAUDE.md`
descreve. O custo aceito por ele é a agitação da Agenda (45 eventos de `done` → `scheduled` → `done`,
90 escritas, com uma janela em que a Agenda mostra 45 contas vencidas) e o fato de que contas com
comprovante vinculado (`link_receipt`) ficam com o anexo intacto e o status piscando.

⚠️ **Ordem obrigatória do mutirão, porque a §4.3 é uma parede:** *(1)* recuar o `opening_date` do C6 e
declarar o saldo daquela data; *(2)* só então estornar; *(3)* repagar informando conta e data.
Invertendo a ordem, cada repagamento leva 422 e ele terá 45 contas estornadas e nenhuma repaga.

### 4.5 Estorno: o movimento **some**

Três opções foram consideradas para `reverse_payable`:

| Opção | Veredito |
|---|---|
| **Contrapartida** (movimento `+valor` compensando o `−valor`) | **Rejeitada.** O extrato do dono tem **uma** linha. Criar duas inventa um crédito que nunca existiu no banco — e, na Onda 4, a importação encontraria dois órfãos irreconciliáveis. **Fabricar fato bancário é o pecado que a Regra 5 previne, pela porta de trás** |
| **`ignored`** | **Rejeitada.** (i) `ignored` significa *"o usuário disse que isto não deve contar"* — é estado de julgamento do dono, não de sistema; (ii) a linha ficaria visível na lista com um "motivo" que é ruído, não evidência; (iii) colide com o índice único quando o pagamento é refeito |
| **DELETE** | **ESCOLHIDA** |

Justificativa: um movimento bancário é a afirmação *"este dinheiro saiu desta conta"*. Estornado o
pagamento, o sistema **não afirma mais isso**. Manter a linha marcada "não conte" é manter uma
afirmação falsa com uma etiqueta — o inverso exato do princípio da Onda 0 (*"suprima a afirmação,
nunca o número"*): aqui não há número a preservar, só a afirmação. E a trilha de auditoria não se
perde: ela mora em `audit_entries` (`payable.reverse` já é gravado), que é a finalidade dela.

⚠️ **A guarda que evita perda de dado real, escrita agora porque escrevê-la depois é tarde:** o
DELETE só acontece enquanto a linha for **puramente sintética** — `source='payable'`, `fitid IS NULL`,
`import_batch_id IS NULL`. Se a Onda 4 já tiver **enriquecido** essa linha com a linha real do OFX
(design-mãe §4.5), o estorno **não apaga**: ele **desliga a origem** (`origin_id = NULL`,
`source = 'ofx'`, `status = 'unmatched'`) e a linha volta a ser um movimento órfão do extrato — o que
é **verdade**: o dinheiro saiu mesmo, e agora o sistema não sabe por quê. Degradação honesta.

Hoje isso é inalcançável (não há importação), e é por isso que os 45 estornos do fundador são
seguros.

**`reverse_payable` passa a aceitar `scheduled` além de `paid`** (`service.py:291` hoje exige
`status != STATUS_PAID → 409`). Cancelar um agendamento é, do ponto de vista do razão bancário,
idêntico a estornar: o movimento futuro **some**, e o saldo de amanhã volta ao que era. Não é preciso
rota nova nem verbo novo — o significado de `reverse` já é *"esta saída não vai acontecer"*, e ele
serve igualmente bem para uma saída que ainda não aconteceu. A conta volta para `open` e reaparece na
Fila, que é o comportamento certo: se o agendamento foi cancelado, a conta voltou a ser um problema.

### 4.6 A bandeja de comprovantes ganha isso de graça (fecha REQ-12 / C3)

`link_receipt` e `new_bill_from_receipt` chamam `apply_paid` e passam a gerar o movimento **sem uma
linha de tela nova**. O share sheet do Android e o Atalho do iOS — a captura mais barata do produto,
no instante do pagamento — viram o afluente principal do razão bancário.

O que muda na superfície: as duas rotas ganham `bank_account_id` (obrigatório quando
`mark_paid=True`) e `paid_on` (opcional). Na barra fixa do celular, a conta primária vem
**pré-selecionada e visível no próprio botão** — *"Anexar e dar baixa · sai do Itaú PJ"* — com troca a
um toque. Isso não é o "opcional com default" que o fundador recusou: o campo é obrigatório e é
sempre gravado; o que o pré-preenchimento evita é **construir**, não **confirmar** (teto de
simplicidade, design-mãe §0).

⚠️ **Herda a lição dos PRs #56 e #58:** o seletor de conta precisa estar **dentro da mesma barra
fixa** do botão, fisicamente inseparável da ação que o torna efetivo. Foi exatamente essa separação
que fez uma conta real ser marcada paga sem o dono conseguir ver o checkbox. O `CLAUDE.md` registra
duas rodadas de fix de campo por isso; a terceira seria imperdoável.

---

## 5. Recebimento fora do trilho

### 5.1 A assimetria, e por que ela não é simetria de Contas a Pagar

Contas a Pagar é simétrico: paga → sai da conta → movimento. Cobranças tem **dois destinos
diferentes**:

| | Pelo trilho (Asaas) | Fora do trilho (Pix direto) |
|---|---|---|
| Onde o dinheiro cai | **Carteira da e1p**, com split retido | **Conta bancária do dono** |
| Tabelas | `transactions` + `platform_earnings` | `bank_transactions` |
| Plano | 1 (plataforma) | 3 (banco) |
| Split | retido | **nenhum** — o dinheiro nunca passou pela e1p |
| Encosta na conta do dono | **Não** — só depois, no payout (Onda 3 na ordem nova) | Sim, imediatamente |

Tornar "conta bancária" obrigatória na cobrança **sem separar os dois** faria dinheiro de plataforma
parecer dinheiro de banco: o cruzamento de planos que originou o épico.

**E o buraco que o requisito expõe:** hoje **não existe** caminho para o dono dizer *"esta cobrança
caiu direto no meu banco"*. O botão "Marcar paga" foi removido de propósito (`CLAUDE.md` §Financeiro);
pagamento entra só por `POST /receivables/webhook`. Então a cobrança paga por fora fica **em aberto
para sempre**, o dinheiro que entrou **não aparece em lugar nenhum**, e a régua de cobrança segue
mandando lembrete para quem já pagou.

### 5.2 A porta

```
POST /receivables/charges/{id}/settle-externally
     {bank_account_id: str, received_on?: date}
```

```python
# receivables/service.py — CONTRATO
def settle_off_rail(db, *, charge_id, tenant_id, actor, bank_account_id, received_on=None) -> Charge:
    """Registra que a cobrança foi recebida DIRETO na conta do dono, fora do trilho.

    NUNCA chama wallet. NUNCA cria Transaction nem PlatformEarning. Gera um bank_transaction de
    CRÉDITO via sync_origin_movement(source='charge'), na mesma transação. `transaction_id`
    permanece NULL — é a metade "banco" da INVARIANTE DO TRILHO (§3.4).
    """
```

Comportamento, item a item:

- `status = 'paid'`, `paid_at = received_on` (regime de caixa), `competence_date` **intocada**.
- `bank_account_id` preenchido, `transaction_id` **NULL para sempre**.
- Evento da Agenda vai para `done` (mesmo comportamento do `mark_paid`) — a cobrança sai da régua.
- `bank_transaction` de `+amount_cents`, `source='charge'`, `origin_id=charge.id`,
  `status='matched'`, `counterparty_name` herdado de `Client.name` e `counterparty_document` de
  `Client.document` quando houver `client_id`.
- `FOR UPDATE` na `Charge`, como o `mark_paid`.

### 5.3 Como o código impede que os dois se confundam — e como isso é testável

Cinco defesas, e nenhuma delas é "tomar cuidado":

1. **Estrutural — a invariante do §3.4.** `test_invariante_do_trilho` varre um cenário com cobranças
   dos dois tipos e exige exatamente-um-ponteiro por cobrança paga. Falha em qualquer linha que
   preencha os dois ou nenhum.
2. **Comportamental — espião no split.** `test_recebimento_fora_do_trilho_nao_aciona_split` monkey-
   patcha `wallet_service.build_transaction` para levantar exceção, e chama `settle_off_rail`. Se o
   caminho tocar a carteira, o teste explode. Mesmo padrão do teste que já protege
   `register_yield` (IV1 da Story 5.6).
3. **Contábil — nada aparece para a plataforma.**
   `test_recebimento_fora_do_trilho_nao_cria_platform_earning`: contagem de `PlatformEarning` antes e
   depois, idêntica.
4. **`mark_paid` recusa cobrança já liquidada fora do trilho.** Na prática a guarda de idempotência
   existente (`if status == PAID: return charge`) já faz isso — um webhook atrasado do gateway sobre
   uma cobrança que o dono já registrou vira **no-op silencioso**, que é o comportamento certo (o
   dinheiro já está contabilizado). Isso precisa de teste **explícito** justamente porque hoje o
   silêncio vem por acidente: `test_webhook_apos_recebimento_fora_do_trilho_e_noop`.
5. **`settle_off_rail` recusa (409) cobrança com `transaction_id` preenchido** — a direção inversa,
   que não é coberta pela idempotência de status.

### 5.4 Corrigir e desfazer

`PATCH /receivables/charges/{id}/payment {bank_account_id?, received_on?}` — simétrica à de payables
(§4.4), restrita a cobranças **fora do trilho** (`transaction_id IS NULL AND bank_account_id IS NOT
NULL`). Mesma idempotência, mesmo sincronizador.

**E uma capacidade que cai do desenho e merece ser nomeada:** o estorno de `Charge` está bloqueado
pela dívida `platform_earnings → transaction`. Mas o recebimento fora do trilho **não cria
`Transaction` nem `PlatformEarning`** — logo **a dívida não o alcança**. Desfazer um recebimento fora
do trilho (apagar o movimento, limpar `bank_account_id`, status de volta para `open`, evento da
Agenda de volta para `scheduled`) é seguro, e a condição que garante isso é uma só:
`transaction_id IS NULL AND bank_account_id IS NOT NULL`.

Isto **não** desbloqueia a Onda 6 (baixa de receber a partir do extrato), que é sobre cobranças do
trilho e sobre baixa automática. É uma porta pequena e verificável. **Não a coloco em escopo por
conta própria** — vai como decisão do fundador (§12, F-D4), porque a rota de correção da §5.4 já
cobre o erro provável (conta errada) e o "desfazer" cobre um caso mais raro.

---

## 6. O sinal de recebimento fora do trilho — onde, para quem, com que tom

O estudo do @analyst aponta recebimento fora do trilho como **vazamento de receita da e1p**. A
decisão G-D7 (design-mãe §10, epic §9 D7) mandou: *"informação neutra ao dono, nunca reportada ao
Master"*. Ela foi tomada sobre a **conferência inferindo** o caso a partir de um crédito órfão. Agora
o dono **está dizendo** explicitamente. O dado fica limpo; **para quem ele é não muda**.

**Onde:** `/financeiro/diagnostico`, uma regra nova no `engine.py` (que continua **puro**, sem I/O —
o dado chega montado de fora, como a completude).

**Cardinalidade e nível:** 🟡, **um sinal por relatório**, só quando houve recebimento fora do trilho
na janela. Não 🔴 porque nada está quebrado. Não um aviso por cobrança, pela mesma disciplina
anti-ruído da banda de tolerância — *"uma tela que grita por R$ 3 destrói a confiança no sinal"*.

**Tom — operacional, sobre o interesse DELE, e nada sobre o nosso:**

> 🟡 *3 dos 11 recebimentos deste mês (R$ 4.200,00) entraram direto na sua conta, fora da cobrança
> do e1p. Eles contam na sua DRE e no seu saldo, mas não geram boleto, lembrete automático nem baixa
> sozinha.*

Verdadeiro, útil, acionável, e **não diz uma palavra sobre split**. O que o dono ganha em saber é
concreto: aquele cliente não recebe régua de cobrança e aquela cobrança não fecha sozinha.

**A proibição, e ela precisa ser normativa porque a "melhoria" natural é óbvia:**

> **Nenhuma superfície da plataforma pode ser construída sobre `charges.bank_account_id`.** Nem
> painel do Master, nem agregado em `/admin/*`, nem e-mail, nem cobrança de taxa. `platform_earnings`
> não é tocado. Teste: `test_admin_nao_expoe_recebimento_fora_do_trilho` — varre os schemas de saída
> de `/admin` procurando qualquer agregado sobre a coluna.
>
> Se um dia a e1p quiser cobrar sobre recebimento fora do trilho, isso é **decisão comercial com
> consentimento contratual**, não consequência técnica de uma coluna. Escrever isto agora custa um
> parágrafo; descobrir depois que o dado virou base de cobrança sem ninguém decidir custa a relação
> com o usuário.

---

## 7. Manual reduzido ao que só existe no banco

Fundador: *"o que vamos fazer manual é apenas coisas diretas lá, como taxas e transferência para
aplicações"*.

**Não é validação por categoria, não é só documentação: é curadoria de UI + uma validação estreita.**

**Por que não whitelist rígida:** o extrato está cheio de coisas que não imaginamos (estorno de
tarifa, crédito de convênio, débito de seguro, cashback). Recusar um fato bancário legítimo porque
ele não está na lista recria a incompletude que a onda combate.

**Por que não só documentação:** hoje o formulário manual é a porta **primária** e parece o jeito de
registrar qualquer coisa — inclusive um pagamento. Um pagamento registrado nos dois lugares derruba o
saldo **duas vezes**, e a divergência resultante parece um achado real. É o pior modo de falha desta
onda.

**(a) Curadoria de UI, reusando campo que já existe.** O formulário deixa de ser "Novo movimento" e
passa a perguntar **para que serve**, com uma lista curta: `Tarifa / juros`, `IOF / imposto`,
`Transferência entre minhas contas`, `Rendimento`, `Outro (descreva)`. Isso alimenta
`bank_transactions.operation_nature` — coluna que **já existe**, nullable, com vocabulário
declaradamente *"sugerido, não enum fechado"* (design-mãe §7.2). **Zero migration.** Um valor novo no
vocabulário (`tarifa_bancaria`); o resto mapeia no que já está lá (`tributo`,
`transferencia_propria`, `receita_financeira`).

Sistema integrado aplicado ao próprio módulo: o campo estava lá, nasceu nulo, e ninguém o usava.

**(b) Uma validação estreita — a que impede a contagem dupla.** Em `create_transaction` com
`source='manual'` e `amount_cents < 0`, procurar `Payable` em aberto ou paga recentemente com o
**mesmo valor absoluto** dentro de **±3 dias**. Se achar, **409 com escolha** (não bloqueio mudo):

> *"Existe uma conta a pagar de R$ 380,00 vencendo em 12/07 (Enel). Quer dar baixa nela — o movimento
> nasce sozinho — ou este é outro pagamento?"*
> `{"acao": "baixar_payable", "payable_id": "..."}`

O usuário repete a requisição com `confirmar_avulso=true` para insistir. Falso positivo (pagou outra
coisa de exatamente R$ 380 em 3 dias): um clique, raro. Verdadeiro positivo: evita a divergência
dobrada que *parece* um achado. Vale a troca.

**Como isso convive com o gate `bank ↛ payables` da §3.5 — normativo.**

> ⚠️ **ACRESCENTADO EM 2026-07-30 (ratificação, C-5).** Esta seção pedia que `create_transaction`
> (módulo `bank`) consultasse `Payable`, e a §3.5 da mesma peça institui o gate estrutural que
> proíbe `bank` de importar `payables`. As duas não cabem juntas por import direto. Achado do @sm da
> Story 8.17, com a forma proposta por ele — **ratificada, com dois ajustes**.

**Primeiro, a regra que decide todas as alternativas:**

> **Evadir um gate é pior do que quebrá-lo às claras.** Quebrado às claras, alguém vê no diff.
> Evadido, o gate fica verde e a proibição está morta — que é literalmente o achado **TEST-001** do
> gate das Ondas 0–1. **Import lazy** dentro da função e **SQL cru** sobre a tabela `payables`
> passariam no gate de AST e violariam exatamente o que ele protege: os dois estão **reprovados por
> definição** nesta onda, e não por estilo.

**A forma: porta de saída registrada na composição.** `bank` declara um `Protocol` que ele próprio
possui e um registrador; a implementação concreta vive em `payables` (que **pode** importar `bank`);
a ligação é feita em `app/main.py`. Direção final: `main → bank`, `main → payables`,
`payables → bank`. **`bank` não sabe que `payables` existe** — o gate fica verde porque a dependência
sumiu, não porque foi escondida.

**Ajuste 1 — a porta devolve um DTO de `bank`, nunca uma entidade de `payables`.**

```python
# bank/service.py — CONTRATO
@dataclass(frozen=True)
class DuplicataCandidato:
    referencia_id: str      # id opaco; `bank` não sabe de que entidade é id
    descricao: str
    valor_cents: int
    data: date
```

Um `Protocol` cuja assinatura devolvesse `Payable | None` obrigaria `bank` a **importar o tipo** —
e um `if TYPE_CHECKING: from app.modules.payables.models import Payable` continua sendo um import de
`payables` dentro de `bank`, que a varredura de **texto cru** do gate pega, com razão. O campo se
chama `referencia_id` e não `payable_id` de propósito: `bank` não pode nomear um conceito de
`payables` nem no nome de um campo. O vocabulário de `payables` aparece só no payload HTTP
(`{"acao": "baixar_payable", "payable_id": ...}`), montado com o valor opaco.

**Ajuste 2 — fail-closed no BOOT, não no request.** Se o probe não estiver registrado, a alternativa
"silenciosamente não valida" é a guarda desligada em produção sem ninguém saber, e a consequência é o
pior modo de falha desta onda. Mas **um erro de fiação é condição de startup, não de request**: um
500 numa ação legítima do dono (lançar uma tarifa de R$ 2,90) é o pior lugar para descobrir que o
`main.py` não ligou um `Protocol`.

> **A aplicação não sobe sem o probe registrado.** Precedente do próprio projeto: a guarda de boot
> contra `JWT_SECRET` fraco em produção. A verificação de request-time **fica**, como segunda guarda
> — inalcançável se a de boot funcionar. É a mesma disciplina dupla que o `update_transaction` do
> módulo `bank` documenta *"de propósito"*.

**O que NÃO muda:** a guarda vale só em `create_transaction`, nunca em `update_transaction` (editar é
correção, não criação — ampliar é Art. IV); o probe **recebe** o `db` do request e nunca abre sessão
própria (abrir sessão própria é escapar da GUC do tenant); a janela de ±3 dias e o valor exato
continuam os mesmos do enriquecimento.

⚠️ A janela de **±3 dias** e o valor **exato** são deliberadamente **os mesmos** do enriquecimento da
§4.5 do design-mãe — um número, não dois. `[SUPOSIÇÃO minha, parametrizável]`.

**(c) O que acontece com `source='manual'` já existente?** **Nada automático. Nenhuma migration,
nenhuma reclassificação.** Uma linha manual é a afirmação do usuário; reescrevê-la seria a "tradução
silenciosa entre dois vocabulários" que a lição D-3 proíbe. O que se faz é **anotar**: a conferência
(a partir da Onda 4, junto com os outros blocos) marca *"este movimento pode ser a mesma despesa da
conta X"* quando encontrar um `manual` sem `origin_id` casando com um `payable` pago. Informativo,
nunca corretivo.

**Movimento manual negativo continua legal.** Tarifa, IOF e taxa de TED são saídas que não têm — e
nunca terão — `payable`: criar uma conta a pagar de R$ 2,90 para uma tarifa é a ERP-ificação que o
produto recusa. A guarda (b) é a granularidade certa; proibir saída manual seria a errada.

---

## 8. Transferência entre contas próprias — entra, mas a aplicação não

**Decisão: partir a Onda 2 original em duas e trazer só a metade barata para cá.**

- **Onda 2 (esta):** `bank_transfers` genérica — duas pernas, `kind ∈ {own_transfer, investment_in,
  investment_out}`, resultado zero na DRE por construção. **Zero acoplamento com `investments`.**
- **Onda 2b:** `investment_accounts.bank_account_id`, `principal_cents` derivado, **o backfill**,
  `register_yield` gerando movimento, extrato da aplicação no `InvestimentosPage`.

**Por que puxar a transferência para cá:** o fundador a citou no mesmo recorte do manual (*"taxas e
transferência para aplicações"*); ela é a **segunda porta manual legítima** e o item (c) da lista
curada da §7 aponta para ela; e ela usa o mesmo `sync_origin_movement` (`source='transfer'`), **duas
chamadas, uma por perna**.

**A forma canônica das duas pernas (normativa).**

> ⚠️ **CORRIGIDO EM 2026-07-30 (ratificação, C-3).** Esta seção dizia *"duas linhas com o mesmo
> `origin_id`"*, o que **viola** o índice único `(tenant_id, source, origin_id)` da §3.2 — e
> `sync_origin_movement` recebe **uma** conta e devolve **um** movimento, então nem sabe criar duas
> pernas. Achado do @sm da Story 8.18, com a forma proposta por ele — **ratificada**. A §3.2 agora
> define `origin_id` como **chave de origem**, e com isso o sufixo deixa de ser gambiarra: é a chave
> dizendo a verdade sobre o que ela identifica.

| Perna | Conta | `amount_cents` | `origin_id` | `transfer_id` |
|---|---|---|---|---|
| saída | `from_account_id` | **−** valor | `f"{transfer.id}:out"` | `transfer.id` |
| entrada | `to_account_id` | **+** valor | `f"{transfer.id}:in"` | `transfer.id` |

- **duas chamadas** a `sync_origin_movement`, na mesma transação do `bank_transfer`;
- o pareamento é o `transfer_id`, coluna que **já existe** (`bank/models.py:278`) e existe para isso;
- `dedup_hash = sha256(f"{source}|{origin_id}")` dá hashes distintos por perna **de graça**;
- `origin_id` é `VARCHAR(64)` (§3.2) — a chave sufixada tem 40 caracteres, e a folga é deliberada.

> ⚠️ **O 422 de `posted_at` futuro da transferência é validado em `create_transfer`, NUNCA em
> `_validate_posted_at`.** A partir da §4.2.0, a guarda do módulo `bank` **aceita** futuro para
> `source ∈ SOURCES_SISTEMA`, e `transfer` está lá dentro. Uma guarda posta no lugar errado seria
> silenciosamente inócua.
>
> **Transferência agendada está fora de escopo, e é decisão, não lacuna:** não existe estado de
> promoção, nem superfície, nem teste para uma quarta semântica de agendamento — `scheduled` é estado
> de `Payable`/`Charge`, não de movimento bancário. Inventá-la aqui é Art. IV.

**Desfazer uma transferência: as duas pernas somem juntas.** `DELETE` do `bank_transfer` **e** das
duas pernas, na mesma transação, com a **mesma guarda de linha puramente sintética** do estorno
(§4.5). Isto **não é escopo novo** — é a §4.5 aplicada onde ela já valia: sem o DELETE, a única
correção de uma transferência errada seria lançar a transferência inversa, ou seja, exatamente a
**contrapartida que a §4.5 rejeita nominalmente** (*"o extrato do dono tem uma linha; criar duas
inventa um crédito que nunca existiu"*). Corrigir (editar conta/data/valor) fica fora: apagar e
recriar aqui é barato — duas linhas sintéticas, nenhum evento de Agenda envolvido.

**Por que deixar a aplicação fora:** a Onda 2 original carrega **o único backfill sobre dado
existente de todo o épico**, exposto à armadilha do `FORCE RLS` (a lição da 0046, que o SQLite dos
testes não pega). Esse é o item de maior risco do épico inteiro — e ele é sobre **investimentos**,
não sobre o fluxo de pagamento que resolve o problema imediato do fundador (45 contas, saldo derivado
R$ 0,00). Acoplar os dois adia o urgente pelo arriscado.

O corte é o mesmo que a §3.2 do design-mãe já fez no modelo: **a transferência é o dinheiro; a
aplicação é o produto financeiro.** Cortar as ondas na mesma linha é coerência, não fatiamento.

A costura fica limpa: uma `bank_account` com `kind='investment'` **já existe** desde a Onda 1, então
transferir para ela funciona corretamente na Onda 2 — o dinheiro se move e o saldo bate. A Onda 2b só
liga a faceta de produto e passa a derivar `principal_cents`.

**A Regra da Neutralidade (design-mãe §3.5) permanece intacta:** `dre.py` agrega exatamente
`charges` + `payables` + `transactions`; `bank_transfers` e `bank_transactions` não são nenhuma das
três e nunca serão. Teste: `test_transferencia_nao_altera_dre` (snapshot idêntico campo a campo).

---

## 9. O que isso faz com a conferência — e com o gate

### 9.1 A descoberta desconfortável: a Onda 1 não conseguia medir o que o épico diz que ela mede

Hoje, no tenant do fundador: 45 `payables` pagas, 0 `charges`, `saldo_sistema = opening_balance + 0`.
Declarar o saldo real produz uma divergência do tamanho de tudo o que aconteceu desde a abertura.

**Esse número diz "você não digitou nada". Ele não diz "faltam estes lançamentos".** Ele mede a
**ausência de uma porta**, não a incompletude da disciplina do dono.

E aí está o custo real do erro de escopo, que é maior do que uma feature faltando:

> O epic §3.1 define a divergência da Onda 1 como **o instrumento do gate** que libera ou mata as
> Ondas 3 e 4 (4,5 ondas de trabalho e um custo de manutenção perpétuo). Medida **antes** da Onda 2,
> essa divergência seria enorme por construção — e teria argumentado, com número na mão, para
> **liberar a onda cara**. **A feature que faltava teria pedido a construção da feature mais cara.**

Não é hipótese: é o que aconteceria no primeiro ciclo de conferência do fundador, e nada no desenho
da Onda 1 avisaria.

### 9.2 Depois da Onda 2, a divergência decompõe em quatro termos — e só um é o alvo

1. **Movimentos que só existem no banco** — tarifa, IOF, débito automático não cadastrado. *Resíduo
   estrutural; nunca vai a zero.*
2. **Recebimentos que o dono não registrou de nenhuma forma.** *Fecha com a porta da §5.*
3. **Erro de data** — pagou em 12, o banco compensou em 13. *Resíduo estrutural.*
4. **Contas pagas fora do e1p e nunca cadastradas.** ← **é este o furo que o épico existe para
   achar.**
5. **Agendamento que não saiu** — novo, e é o termo mais interessante (§9.2.1).

#### 9.2.1 O agendamento que falha vira divergência — a leitura do coordenador se sustenta

No dia seguinte à data agendada, o movimento **já conta** no saldo derivado — sem worker nenhum,
porque o saldo é função da data (`posted_at <= hoje`). Se o débito não saiu (saldo insuficiente, banco
recusou, o dono cancelou no app e esqueceu de avisar o e1p), o próximo checkpoint declara um saldo
**maior** que o derivado → `divergencia > 0` → *"você tem dinheiro que o sistema não conhece"*.

Isso é o bloco 1 da conferência funcionando exatamente como projetado, sobre uma classe de furo que
**hoje ninguém pegaria**: um agendamento que falha é invisível para o dono até a conta vencer de novo
ou o fornecedor cobrar.

⚠️ **Mas o sinal é AMBÍGUO, e isso precisa ser dito:** `divergencia > 0` é também o sintoma de
*"recebi algo e não registrei"*. Entregar só o número faz o dono caçar a coisa errada — o mesmo modo
de falha do BANK-001, com outra causa.

> ⚠️ **CORRIGIDA EM 2026-07-30 (ratificação, C-2).** A população original desta regra —
> *"payables em `scheduled` cuja data já passou"* — é **código morto**: o worker da §4.2.3 (F-D11)
> promove `scheduled → paid` assim que o dia chega, então essa população existe entre a meia-noite e
> a varredura e é quase sempre vazia. Achado do @sm da Story 8.16. **O efeito continua existindo; o
> adjetivo "agendamento" não sobrevive ao worker** — ver a §9.2.2 e a ratificação §C-2.

**Desambiguação barata, e ela é determinística:** o Diagnóstico **nomeia o débito suspeito** em vez
de só apresentar o número.

> 🟡 *O débito de R$ 5.000,00 de 15/08 (Aluguel) **pode não ter saído** da conta: o saldo que você
> declarou está R$ 5.000,00 acima do que o e1p calculou.*

**A população (normativa), montada com dado que já existe, sem coluna nova e sem reabrir F-D11:**

1. `Payable` com `status == 'scheduled'` **e** `paid_at::date <= hoje` — a janela entre a data e a
   varredura. Rara, e é a mais precisa quando existe;
2. **união com** `Payable` com `status == 'paid'`, `bank_account_id IS NOT NULL` e `paid_at::date`
   dentro da janela conferida e `<= reference_date` do checkpoint — ou seja, débitos que **já contam**
   no `saldo_sistema` daquela data e que, portanto, **podem** explicar o saldo declarado estar acima.

**O critério de casamento (normativo), que é o que evita a segunda população virar ruído:**

> `|valor_cents − divergencia_cents| <= max(5000, divergencia_cents // 10)` — **R$ 50 ou 10%, o que
> for maior**. Constante nomeada, ao lado de `_COMPLETENESS_STALE_DAYS`.
>
> É a **mesma forma** da banda de tolerância (`max(R$ 50, 0,5%)`) e um **percentual diferente de
> propósito**: a banda absorve resíduo estrutural; este critério responde *"este débito explica esta
> divergência?"*, que é pergunta mais estrita. Uma forma, dois usos, e a diferença escrita.
>
> Um intervalo largo (o `[0,5×, 2×]` proposto na Story 8.16) nomearia um débito de R$ 5.000 diante de
> uma divergência de R$ 2.500. **Nomear um débito inocente é pior do que ficar calado:** *"pode não
> ter saído"* sobre um débito que obviamente saiu treina o dono a ignorar a tela, e o silêncio apenas
> devolve o número que ele já tem hoje.

Cardinalidade e silêncio: **1 sinal por conta**, o suspeito de maior valor; **zero sinal** quando
nada casa; **zero sinal** quando a divergência é **negativa** (banco abaixo do sistema é o sintoma
oposto — falta lançamento de saída — e nomear um débito ali manda o dono para o lado errado).

Uma regra no `engine.py` — que continua **puro**, porque o dado chega montado de fora, igual à
completude. **Incluir na onda:** sem ela, o "efeito feature" vira só mais um número de divergência, e
números sem pista treinam o dono a ignorar a tela.

Nota de precisão: a regra diz *"pode não ter saído"*, nunca *"não saiu"* — o e1p continua sem ver o
extrato. É a mesma disciplina de afirmação do resto do épico.

#### 9.2.2 O que sobrou do "efeito agendamento", dito sem eufemismo

**O efeito existe. O adjetivo não.** A distinção importa porque eu vendi o adjetivo.

O que continua existindo, exatamente como prometido: um débito que o e1p registrou e que o banco
**não executou** entra no saldo derivado na data (sem worker nenhum — o saldo é função da data), o
checkpoint declara um saldo **maior**, e `divergencia > 0` no ciclo seguinte. É uma classe de furo que
hoje ninguém pegaria, e ela é pega.

O que **não** existe é o e1p saber dizer *"o **agendamento** de 15/08"*. Depois da varredura o
`Payable` está `paid`, e nada no dado distingue *"eu agendei e o banco não executou"* de *"eu paguei
no caixa e o banco não compensou"*. Escrevi "agendamento" porque estava com o `scheduled` na cabeça e
não perguntei o que sobra dele depois do worker que eu mesma especifiquei duas seções antes.

**Isso não custa valor ao sinal**, e a razão é a que o épico inteiro já usa: o valor está em apontar
**qual débito** casa com a divergência, não no adjetivo. O dono que vai conferir um débito de
R$ 5.000 de 15/08 no app do banco não precisa que a gente lhe diga que ele o agendou — ele sabe.
E *"suprima a afirmação, nunca o número"* decide o resto: não posso afirmar "agendado"; posso
apontar o débito e a divergência.

**Consequência de nomenclatura (normativa), porque um nome que diz uma coisa carregando outra é o
defeito D-3, e eu já o cometi duas vezes neste épico:**

| De | Para |
|---|---|
| `AgendamentoSuspeitoInput` | `DebitoSuspeitoInput` |
| `source="agendamento"` | `source="debito_nao_confirmado"` |
| rótulo de tela "Agendamentos" | **"Saídas"** |

Consequência para a banda de tolerância: ela deixa de ser "ignore ruído" e passa a ter um trabalho
nomeado — **absorver as classes (1) e (3)**. `max(R$ 50, 0,5%)` continua parecendo a ordem de
grandeza certa, e agora com **razão** em vez de suposição. A justificativa da banda sobe de
`[SUPOSIÇÃO minha]` para *"absorve o resíduo estrutural conhecido"*, e os três primeiros ciclos devem
ser lidos com essa decomposição na mão.

### 9.3 A nova pré-condição do gate — e a linha que eu não cruzo

> ⚠️ **REESCRITA EM 2026-07-30 (ratificação, C-1).** A redação anterior — *"toda `Payable` paga e
> toda `Charge` recebida precisam ter conta bancária informada"* — era **insatisfazível**: pela
> Invariante do Trilho (§3.4), uma `Charge` paga pelo trilho tem `transaction_id` e **nunca** terá
> `bank_account_id`, e o trilho é o caminho normal do produto. Lida ao pé da letra, a pré-condição
> fechava o gate para sempre. O achado é do @sm da Story 8.16; a correção e o que faltava nela estão
> em [`controle-bancario-onda2-ratificacao.md`](controle-bancario-onda2-ratificacao.md) §C-1.
> A redação antiga fica registrada aqui **como o erro, não como instrução**.

> **PRÉ-CONDIÇÃO DO GATE (normativa).**
>
> A leitura do gate do epic §3.1 é válida num ciclo de conferência **se e somente se**, na janela
> conferida, **não existe evento conhecido pelo e1p que moveu dinheiro numa conta real do dono sem
> ter gerado o `bank_transaction` correspondente.**
>
> Operacionalmente, quatro termos. Cada um tem o predicado que o decide e a onda que o zera:
>
> | # | População | Predicado | Zera na |
> |---|---|---|---|
> | **P1** | Baixa de Contas a Pagar sem conta informada | `Payable`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `bank_account_id IS NULL` | **Onda 2** — vai a zero **por construção** assim que o legado for corrigido, porque a coluna passa a ser obrigatória em `apply_paid` (§4.1) |
> | **P2** | Recebimento fora do trilho sem conta informada | `Charge`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `transaction_id IS NULL`, `bank_account_id IS NULL`, **e** `_not_investment_yield()` | **Onda 2** (§5) |
> | **P3** | Rendimento de aplicação sem perna bancária | `Charge` com `external_ref LIKE 'investment:%'`, `paid_at::date` na janela | **Onda 2b** (`register_yield` → `source='yield'`) |
> | **P4** | Payout da Carteira liquidado sem perna bancária | payout com liquidação real na janela | **Onda 3**. ⚠️ **Hoje é vazio por construção**: `request_payout` só marca `withdrawn` (`wallet/service.py:227`) — nenhum dinheiro sai de conta real |
>
> **Fora da população, por construção e não por omissão:** `Charge` do trilho
> (`transaction_id IS NOT NULL`). O dinheiro dela está na **Carteira**, não numa conta do dono, e ela
> **não deve** gerar `bank_transaction` até o payout. Incluí-la é a leitura que torna a pré-condição
> insatisfazível — e a exclusão é a **Regra dos Planos**, não uma lacuna de preenchimento.
>
> **Membro** (para que o conjunto não seja só descrito — §1.1(5)): um `Payable` pago em 12/07 com
> `bank_account_id IS NULL`, uma das 45 legadas → **P1, conta**.
> **Não-membro:** uma `Charge` paga pelo webhook do Asaas em 12/07 → tem `transaction_id` → **não
> conta**.

**Consequência de roadmap, dita em voz alta porque muda a leitura do épico:** o gate **não** abre
"depois da Onda 2" em geral. Ele abre depois da Onda 2 **para um tenant cujos únicos eventos que
movem conta real na janela sejam baixa de Contas a Pagar e recebimento fora do trilho**. Um tenant
que registra rendimento precisa da **Onda 2b**; quando o payout virar real, precisa da **Onda 3**.
P3 e P4 sempre foram termos da divergência — o que estava errado é que eu escrevia a pré-condição
como se a Onda 2 a satisfizesse sozinha. → **F-D12** (§12).

`_not_investment_yield()` **não é reescrito** em lugar nenhum: é importado de
`receivables/service.py:82-90`, onde já existe. Duas cópias divergem — e já divergiram uma vez, entre
dois @sm que não conversam (a Story 8.15 lembrou dele na Invariante do Trilho; a 8.16 esqueceu dele
na pré-condição, e o efeito era o gate nunca abrir para quem usa Investimentos).

Como isso aparece: o relatório de conferência ganha **uma nota por termo não-zero** no bloco 4 (*"o
sistema declara o que não sabe"*, que já existe exatamente para isto), cada uma nomeando a onda que
a fecha:

> *"7 lançamentos deste período não informam de qual conta saíram (R$ 3.120,00). A divergência
> abaixo inclui esse valor."*
> *"3 rendimentos de aplicação deste período (R$ 480,00) ainda não geram movimento bancário. A
> divergência abaixo inclui esse valor."*

⚠️ **A nota ANOTA; ela NUNCA SUBTRAI.** Descontar o termo conhecido da divergência seria o checkpoint
corrigindo o derivado com outra roupa: a divergência iria a zero por construção sempre que o sistema
soubesse explicar a diferença, e a métrica primária do épico morreria. Essa é a **Regra 5 do
`CLAUDE.md`**, e este design chega perto dela aqui — por isso a linha está escrita em vez de
implícita. **Anotar, nunca subtrair.**

### 9.4 Efeito colateral: SIG-001 fica mais barato de fechar

O achado SIG-001 do gate (a virada de mês apaga uma conferência recente e bem-sucedida) é a regra de
completude usando *"checkpoint dentro da janela"* — e a janela é o mês da DRE. O motor **já recebe**
`dias_desde_ultima_conferencia`, que é absoluto e não depende de janela, e **não o usa**. Resolver é
trocar o predicado de "há checkpoint na janela" por "`dias <= _COMPLETENESS_STALE_DAYS`".

**Decisão de arquitetura (fecha o item 2 da lista "o que precisa de decisão" do re-gate):** a
completude deve usar `dias_desde_ultima_conferencia`, **não** a janela da DRE. Uma conferência que
bateu em 28/06 continua sendo verdade em 01/07; a janela da DRE é uma escolha de relatório, não uma
propriedade do saldo. **Story própria, fora do escopo desta onda** — registro aqui porque a Onda 2
multiplica os movimentos e, com isso, a frequência com que o dono olha esse sinal.

---

## 10. Reordenação do roadmap

| Nova | Era | Entrega | Dependência **externa** |
|---|---|---|---|
| 0 ✅ | 0 | Saldo inicial honesto | — |
| 1 ✅ | 1 | Contas, saldo derivado, checkpoint, conferência | — |
| **2** | *(nova)* | **A origem do movimento**: `payable→banco`, recebimento fora do trilho, data de baixa editável **+ estado `scheduled` (agendamento)**, corte de data nas superfícies de saldo, manual curado, transferência entre contas próprias | **nenhuma** |
| **2b** | 2 | Aplicação como conta, `principal_cents` derivado, `register_yield`→movimento | nenhuma (mas **backfill** sob FORCE RLS) |
| **3** | 6 | Payout da Carteira fecha o circuito | nenhuma |
| **4** | 3 | Importação OFX/CSV | **@analyst D6** (OFX existe em 2026?) + gate §3.1 + manutenção perpétua |
| **5** | 4 | Sugestão de vínculo + baixa de `Payable` pelo extrato | Onda 4 |
| **6** | 5 | Baixa de Receber pelo extrato | dívida `platform_earnings → transaction` |

**A justificativa, e ela é a mesma coisa dita de três ângulos:**

**(1) Dependência externa crescente é a regra de ordenação, e a ordem antiga a violava.** As Ondas 2,
2b e 3 não dependem de **nada fora do repositório**. A importação depende de três coisas que não
controlamos: o formato ainda existir nos bancos do público-alvo em 2026 (D6, **pendente com o
@analyst** — e o ADR 0003 registra que, se não existir, *"o caminho de arquivo morre"*), o número do
gate §3.1, e um custo de manutenção que o próprio ADR chama de *"perpétuo, reativo e imprevisível"*.
**Colocar a onda de maior dependência externa antes das de dependência zero foi o erro de ordem.**

**(2) A Onda 2 é pré-requisito da métrica primária do épico, não um incremento dela** (§9.1).

**(3) O custo de ter feito na ordem antiga, se tivéssemos chegado lá.** A importação traria as 45
linhas reais de débito, todas sem contrapartida no sistema, e a Onda 4 (matcher determinístico + IA)
seria gasta **casando à mão o que a Onda 2 gera de graça e sem erro** — porque o e1p originou os dois
lados. Teríamos construído um matcher probabilístico para resolver um problema que a origem do
movimento elimina por construção. E o matcher **erra**: cada erro dele numa conta a pagar exige um
estorno.

**Efeito colateral bom:** o payout (era Onda 6) sobe para 3 porque é o **mesmo mecanismo** — mais um
evento do sistema virando movimento pelo mesmo `sync_origin_movement`, `source='payout'`. Depois da
Onda 2 ele custa quase nada; antes dela seria um caso especial. Isso é o teste de que a Regra da
Origem é a modelagem certa: ela transforma três ondas separadas em três entradas de uma tupla.

**A Onda 4 continua sujeita ao gate.** A reordenação **não** a antecipa nem a garante — ao contrário:
com a divergência medindo o furo real em vez da ausência de porta, é bastante possível que o gate
diga *"pare"*. O ADR 0003 já chama esse desfecho de **bom, não de fracasso**, e a Onda 2 é o que
torna essa leitura confiável.

---

## 11. Riscos

| Risco | Prob. | Impacto | Mitigação neste design |
|---|---|---|---|
| **Tenant sem conta bancária não consegue pagar conta** | **Alta** (é certeza no primeiro tenant novo) | Alto — bloqueia fluxo central | 409 acionável + cadastro embutido; onboarding avisa antes. **É o custo direto da decisão do fundador e está declarado** (§4.1) |
| **Backfill esbarrar em `opening_date`** | **Alta** (provável no 1º ciclo do fundador) | Médio | 422 nomeando as duas saídas; recuo de data permitido; aviso pró-ativo no cadastro (§4.3) |
| **Recuar `opening_date` sem redeclarar o saldo** → divergência inventada (gêmeo do BANK-001) | **Alta** depois desta onda | Alto | Guarda nova: recuo exige `opening_balance_cents` no mesmo PATCH (§4.3) |
| **Contagem dupla** (pagamento lançado como baixa **e** como movimento manual) | **Alta** sem a guarda | **Alto — a divergência dobrada parece um achado real** | Validação (b) da §7 com escolha explícita |
| **Dinheiro de plataforma parecendo dinheiro de banco** | Média | Alto (é o bug de origem) | Invariante do Trilho + 5 defesas testáveis (§5.3) |
| **Saldo corrente incluindo movimento agendado** (o "Total em contas" mostra dinheiro que ainda não saiu) | **Alta** — é o estado atual do código em 6 chamadas | Alto — o dono conta com dinheiro que já tem destino | `until=None` passa a significar **hoje** em `derived_balance` (§4.2.1). Fail-closed: quem quiser o futuro pede explicitamente |
| **Agendamento sumindo da Projeção** (não é `open`, e o movimento é futuro) | **Alta** se `_window_sums` não for tocado | **Alto — é a máquina de falso negativo da Onda 0 ressuscitada** | Estado `scheduled` + `status IN ('open','scheduled')` no `_window_sums`, com a data do débito (§4.2.2) |
| **`divergencia > 0` ambígua** (agendamento que falhou × recebimento não registrado) | Alta assim que houver agendamento | Médio — manda o dono caçar a coisa errada | Regra determinística no `engine.py` nomeando o agendamento vencido suspeito (§9.2.1) |
| **`paid` com data futura entrando primeiro e `scheduled` depois** | Média (é a tentação de fasear) | Alto — exigiria migration com backfill sob FORCE RLS | Entregar `scheduled` junto; custo medido em ~1/3 de onda (§4.2.4) |
| **O sinal da §6 virar produto de plataforma** | Média ao longo do tempo | Alto (relação com o usuário) | Proibição normativa + teste varrendo `/admin` (§6) |
| **Estorno apagando linha real já importada** | Baixa hoje, alta a partir da Onda 4 | Alto (perda de dado bancário) | Guarda de linha puramente sintética; enriquecida vira órfã em vez de sumir (§4.5) |
| **45 estornos agitando a Agenda** | Alta se o fundador seguir o plano | Baixo | Recomendar a rota `PATCH .../payment`; se estornar mesmo assim, nada quebra (§4.4) |
| **`source` com dois eixos degradar com o tempo** | Média | Médio | Toda regra escrita contra `SOURCES_SISTEMA`/`SOURCES_EXTERNA`, nunca contra valor solto (§3.1) |
| **`bank` importando `payables`/`receivables` (ciclo)** | Média | Médio | Gate estrutural novo em `test_money_planes.py` (§3.5) |
| **Seletor de conta fora da área visível em ~360px** | Média | **Alto — já aconteceu duas vezes** (PRs #56, #58) | Seletor dentro da mesma barra fixa do botão; validação em 360px é aceite obrigatório desta onda (§4.6) |

---

## 12. Pontos que precisam de decisão do fundador

> **Resolvidas em 2026-07-30:** **F-D1** — o fundador manteve `due_date` **e liberou data futura**
> (agendamento). Minha recomendação de `min(due_date, hoje)` está **revogada** por este documento
> (§4.2): ela desenhava o produto em volta de uma limitação do meu modelo. **F-D3** — ele escolheu
> **estornar e repagar** as 45, com o motivo declarado de conferir valores conta a conta. Aceito e
> registrado (§4.4).

| # | Pergunta | Recomendação minha | Impacto se ele discordar |
|---|---|---|---|
| **F-D12** | **NOVA (ratificação, C-1) — você registra rendimento de aplicação no e1p hoje?** A pré-condição do gate (§9.3) tem 4 termos; a Onda 2 zera dois. O rendimento (P3) só zera na **Onda 2b** | **Perguntar antes de planejar** — é uma consulta ao banco, não uma decisão de produto. **Se não registra:** o gate abre no primeiro ciclo pós-Onda 2, como planejado. **Se registra:** a leitura do gate espera a Onda 2b, e o F-D7 (2b logo depois da 2) ganha razão mais forte do que "é barata": **ela vira pré-requisito da métrica primária do épico** | Se ele planejar a leitura do gate para logo depois da Onda 2 sem responder isto, a conferência vai dizer corretamente que o número ainda não decide, e o ciclo é perdido |
| **F-D2** | **Conta obrigatória bloqueia quem não tem conta cadastrada.** Aceita que `bank_accounts` vire pré-requisito de Contas a Pagar? | **Sim, aceitar.** É a consequência direta de "obrigatória", e a alternativa é o "opcional" que ele já recusou | Se não, volta o opcional e o razão volta a nascer incompleto |
| **F-D4** | **Desfazer recebimento fora do trilho entra nesta onda?** | **Não agora.** A rota de correção (§5.4) cobre o erro provável (conta/data). O desfazer é seguro (a dívida `platform_earnings` não o alcança) e pode entrar depois | Se sim: +1 rota, +2 testes, escopo pequeno |
| **F-D9** | **NOVA — estado `scheduled` próprio, ou `paid` com data futura?** | **Estado próprio, e entra JUNTO.** `paid` com data futura afirma o que não aconteceu, exige um predicado autocontraditório (*"pago no futuro"*) replicado em 5 lugares, e **faz o dinheiro agendado sumir da Projeção** (§4.2.2 — verificado no código). Custo medido: ~1/3 de onda, **sem migration de tipo**, **zero impacto na DRE** | Se for `paid`+futuro: é preciso consertar `_window_sums` do mesmo jeito, e separar depois exige migration com backfill sob FORCE RLS |
| **F-D10** | **NOVA — a rota `PATCH .../payment` fica, agora que o retroativo saiu?** | **Fica.** O argumento mudou de "mutirão pontual" para **"reagendar é evento normal"** — sem ela, reagendar = estornar + repagar, com delete+recreate do movimento e a Agenda piscando, todo mês | Sem ela: funciona, só é a operação pesada para um evento leve |
| **F-D11** | **NOVA — quem promove `scheduled → paid` na data?** | **O worker que já existe** (`app.worker.run_sweep`, itera tenants sob `tenant_session`, idempotente, réplica única): +1 varredura de ~20 linhas. ⚠️ O **saldo** não precisa disso — ele anda sozinho porque é função da data; o worker só move o `status` para a Fila e o resumo pararem de mostrar como agendado | Sem worker: `scheduled` vira estado permanente e todo `status == 'paid'` do repo precisa virar `IN ('paid','scheduled')` — o predicado espalhado de novo |
| **F-D5** | **O sinal da §6 pode ser desligado pelo dono?** | **Não.** Mesma lógica do 🟡 "nenhuma conta cadastrada" da Onda 1: o sinal é verdadeiro e é sobre o interesse dele | Se puder desligar, o dono que mais precisa é o que desliga |
| **F-D6** | **A lista curada do manual (§7a) está completa?** Tarifa, IOF, transferência, rendimento, outro | Adotar como está; `Outro (descreva)` é a válvula | Se faltar categoria comum, é uma entrada numa lista — custo zero |
| **F-D7** | **Onda 2b (aplicação) entra logo depois da 2, ou espera?** | Logo depois. Mas ela carrega **o único backfill** do épico, sob a armadilha do FORCE RLS — merece story própria e atenção de gate | — |
| **F-D8** | **G-4 do gate:** validação em ~360px continua **aberta** desde a Onda 1, e esta onda acrescenta um seletor de conta na barra fixa do celular | **Bloquear o release** desta onda no aceite em 360px. Dois PRs de fix de campo já foram pagos por essa lacuna | — |

---

## 13. Rastreabilidade (Constitution Artigo IV — No Invention)

| Afirmação | Fonte |
|---|---|
| `payables` não tem nenhuma referência a `bank` | grep do repo, `apps/api/app/modules/payables/` |
| `bank_transactions.SOURCES` não tem `payable` nem `charge` | `bank/models.py:129-136` |
| `paid_at` é cravado em `now()` | `payables/service.py:258` |
| 409 em conta paga só cobre 6 campos; `competence_date`/`chart_account_id` **já** são editáveis em conta paga | `payables/service.py:160-173` |
| `apply_paid`/`build_payable` sem commit; `reverse_payable` existe | `payables/service.py:241,74,285` |
| A bandeja de comprovantes chama `apply_paid` | `payables/receipts.py:180-181` |
| Não existe caminho para marcar cobrança paga fora do webhook (botão removido de propósito) | `CLAUDE.md` §Financeiro; `receivables/router.py:117` (`/pay` só para teste interno) |
| `mark_paid` chama `wallet.build_transaction` (split + `PlatformEarning`) | `receivables/service.py:394-399` |
| `request_payout` só marca `withdrawn` | `wallet/service.py:227` |
| Movimento futuro é recusado; movimento ≤ `opening_date` é recusado | `bank/service.py:605-628` |
| Projeção já usa `active_balance_total(db, until=today)` — **imune a movimento futuro** | `financial_intelligence/projection.py:16,32,329` |
| Conferência já usa `derived_balance(until=<reference_date do checkpoint>)` — imune por construção | `bank/reconciliation.py:358`; `CLAUDE.md` regra 6 |
| Checkpoint recusa `reference_date` futura | `bank/service.py:909-914` |
| DRE filtra `status != canceled` nas 4 agregações ⇒ status novo passa direto | `financial_intelligence/dre.py:124,290,437,634` |
| `GET /bank/accounts` chama `derived_balances_as_of` **sem `as_of`** (inclui futuro) | `bank/router.py:128` |
| As 4 respostas de CRUD e `GET /accounts/{id}/balance` usam `until=None` (inclui futuro) | `bank/router.py:140,153,169,184,202` |
| "Total em contas" / "Disponível como caixa" somam `saldo_derivado_cents` da lista | `apps/web/src/features/financeiro/contas.ts:219,240,248` |
| Testes de colisão de rótulo instituídos pelo UX-001 | `apps/web/src/features/financeiro/contas.test.ts:157-168` |
| `_window_sums` filtra `status == 'open'` ⇒ agendada sumiria da Projeção | `financial_intelligence/projection.py:370-373` |
| `payables.status` é `String(12)` ⇒ `"scheduled"` (9) cabe sem migration de tipo | `payables/models.py:43` |
| Baldes da Fila são calculados **na leitura**, *"sem precisar de job/cron"* (precedente do worker dispensável) | `payables/service.py:361-363` |
| `reverse_payable` hoje exige `status == PAID` | `payables/service.py:291` |
| Worker existente: itera tenants sob `tenant_session`, idempotente, réplica única | `apps/api/app/worker.py` (docstring + `run_sweep`) |
| Fundador cadastrou o C6 em 2026-07-30 | **[COORDENADOR, 2026-07-30]** |
| Saldo derivado só soma `posted_at > opening_date` | `bank/service.py:287-306` |
| Recuar `opening_date` é permitido e é "o caminho de reparo" | `bank/service.py:124-127` |
| BANK-001: mover `opening_date` produz divergência inventada | `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` §BANK-001 |
| SIG-001 aberto; `days_since_last_declared_balance` sem consumidor | mesmo gate, §Placar; `CLAUDE.md` |
| `operation_nature` já existe, nullable, vocabulário aberto | `bank/models.py:268-270`; design-mãe §7.2 |
| Regra dos Planos, dois eixos, saldo derivado, checkpoint não corrige, conferência por conta | design-mãe §1.3, §1.3.1, §3.1, §2.4, §5.1; `CLAUDE.md` (as 7 regras) |
| §2.3 rejeitou a coluna por causa de N:N e sugestão/confirmação | design-mãe §2.3 |
| `payables.bank_account_id` estava na §6.7 como "opcional, onda posterior, melhora o match" | design-mãe §6.7 |
| C2 (`register_yield`) e C3 (porta do arquivo) pendentes | epic §11.4 |
| REQ-12: reusar a porta de entrada de arquivo existente | pesquisa `2026-07-29-controle-bancario-requisitos-e-viabilidade.md`, REQ-12 |
| G-D7: sinalizar ao dono, nunca ao Master | design-mãe §10 D7; epic §9 D7 |
| Estorno de `Charge` bloqueado por `platform_earnings → transaction` | `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md`; ADR 0003 Consequência 6 |
| Dois PRs de fix de campo por elemento fora da área visível em ~360px | `CLAUDE.md` (PRs #56, #58) |
| Armadilha do backfill sob FORCE RLS | `migrations/versions/0046_ledger_classification.py` |
| 45 payables, 0 charges, saldo derivado R$ 0,00 em produção | **[FUNDADOR / coordenador, 2026-07-30]** — não verificado por mim contra o banco de produção |
| *"é um sistema integrado, não tem o motivo de tudo começar do zero"*; conta obrigatória nos dois lados; manual só para taxas e transferência; backfill à mão | **falas do fundador, 2026-07-29/30** |
| *"deixar habilitado no vencimento, pois se estiver fazendo retroativo, pq não deu certo no dia — e no futuro também permitir, pq posso estar agendando"* | **fala do fundador, 2026-07-30** (F-D1) — origem do estado `scheduled` |
| Escolha de estornar e repagar as 45, para conferir valores conta a conta | **decisão do fundador, 2026-07-30** (F-D3) |
| Agendamento de pagamento pelo app do banco como fluxo real do usuário | **fala do fundador, 2026-07-30** — **não estava em lugar nenhum do Epic 8** |
| Janela de ±3 dias e valor exato na guarda de contagem dupla | **[SUPOSIÇÃO minha, parametrizável]** — mesmo número do enriquecimento (design-mãe §4.5), de propósito |
| Decomposição da divergência em 4 termos | **[ANÁLISE minha]** — derivada dos eventos que o sistema conhece (§1.2) |
