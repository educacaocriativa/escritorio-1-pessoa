# ADR 0003 — Controle bancário nativo, sem agregador Open Finance

- **Status:** Aceito · **Adendo 4 em 2026-07-30** (a origem do movimento + reordenação das ondas)
- **Data:** 2026-07-29
- **Autor:** Aria (@architect) — formalização da decisão de produto tomada pelo fundador
- **Relacionado:** [ADR 0001](0001-stack-e-infra.md), [ADR 0002](0002-gateway-pagamento.md),
  [`docs/architecture/controle-bancario-design.md`](../architecture/controle-bancario-design.md),
  [`docs/architecture/controle-bancario-onda2-design.md`](../architecture/controle-bancario-onda2-design.md) (Adendo 4),
  [`docs/research/2026-07-29-conta-bancaria-conciliacao-brainstorm.md`](../research/2026-07-29-conta-bancaria-conciliacao-brainstorm.md)

## Contexto

O e1p conhece hoje **três planos de dinheiro**, e só implementa dois:

| Plano | Tabela | Situação |
|---|---|---|
| 1 — Plataforma (split 40/30/20) | `transactions`, `platform_earnings` | Implementado |
| 2 — Negócio (direitos e obrigações) | `charges`, `payables`, `chart_accounts` | Implementado |
| 3 — Bancário (o extrato real do usuário) | — | **Não existe** |

A ausência do plano 3 produz dois danos já verificados no código, não hipóteses:

1. **A Projeção de Caixa e o Runway estão errados hoje, com zero lançamentos esquecidos.**
   `financial_intelligence/projection.py:177` usa `wallet_summary()["available_cents"]` — um número
   do plano 1 — como saldo inicial de caixa. Se o usuário nunca saca, o número acumula todo o
   faturamento líquido histórico e nunca diminui quando uma conta é paga (`payables` não toca a
   Carteira por design — `payables/models.py:4`). Se ele saca tudo, o número vai a zero enquanto o
   dinheiro está na conta dele. Não há configuração de uso em que esteja certo.
2. **Transferência entre contas próprias é ponto cego total.** `investment_accounts.principal_cents`
   é um campo **digitado** (`investments/models.py:49`); não existe modelo de aporte nem de resgate.
   O único evento de investimento é `register_yield`, que cria uma `Charge status=paid` sintética.
   Ou seja: o e1p sabe *quanto rendeu* e não sabe *quanto foi aplicado nem quanto foi resgatado*.

Um estudo de brainstorm (rodada 1, `docs/research/2026-07-29-...`) recomendou **não** construir
controle bancário agora, propondo em vez disso uma "posição de caixa declarada" (um número, uma
divergência, sem cadastro de conta). O fundador **avaliou e superou** essa recomendação, com três
razões declaradas:

- *"a questão é o contas a pagar e o controle bancário; de saldo batendo é uma conferência para
  achar possível furos"* — quer **localizar** o furo, não só quantificá-lo.
- *"com a entrada da nova legislação tributária, teremos que ter os dados cada vez mais fiéis de
  onde vem e para onde vai o dinheiro"* — precisa de contraparte identificada por movimento, o que
  um saldo agregado não carrega.
- *"e depois com a conta de aplicação entrando neste processo, não apenas o lançamento do quanto
  rendeu"* — o requisito de aporte/resgate exige a noção de conta e de movimento; um saldo declarado
  único não modela transferência entre contas próprias.

E uma restrição dura: *"não podemos ficar contando com serviços de terceiros"* — agregadores de Open
Finance estão fora **por decisão de dependência**, não por preço. (O preço também não ajudava:
Pluggy a partir de R$ 2.500/mês `[CONFIRMADO 2026-07-29]`, antes do primeiro usuário conectar — o
oposto literal da Regra de Ouro nº 4.)

## Decisão

**Construir controle bancário nativo no e1p**, com:

1. **`bank_accounts` + `bank_transactions` como plano 3 de primeira classe**, tabelas de negócio com
   `tenant_id` + RLS `FORCE`, dinheiro em centavos `BigInteger`.
2. **Saldo DERIVADO dos movimentos**, nunca materializado (`opening_balance_cents` +
   `SUM(amount_cents)`). Consistência e auditabilidade acima de performance — o volume do
   usuário-alvo (~500 movimentos/ano/conta) torna a performance um não-problema.
3. **Conta de investimento como `kind` de conta bancária**, com `investment_accounts` preservada
   como faceta de produto (indexador, rendimento acumulado, rentabilidade) ligada 1:1. Aporte e
   resgate viram **transferências entre contas próprias**, e `principal_cents` passa a ser derivado.
4. **Transferência entre contas próprias é DRE-neutra por construção** — não cria `Charge`,
   `Payable` nem `Transaction`, e a DRE agrega exatamente essas três origens. Resgate nunca vira
   receita.
5. **Vínculo de conciliação em tabela de ligação** (`bank_reconciliations`), suportando alocação
   parcial N:N (um pagamento quitando duas contas; uma conta paga em dois movimentos).
6. **Importação por arquivo (OFX 1.x SGML, OFX 2.x XML, CSV por layout), com parser em strategy
   plugável** e layouts de CSV descritos em YAML. Zero chamada de rede no pipeline. Idempotência por
   `dedup_hash` com constraint única no banco (fail-closed, no espírito da RLS).
7. **IA sugere, usuário confirma.** A IA classifica, extrai contraparte e ranqueia candidatos, sempre
   sob o anonimizador (Regra de Ouro nº 2). Ela **nunca** confirma vínculo nem dá baixa.
8. **Baixa de `Charge` a partir do extrato fica BLOQUEADA** até a dívida `platform_earnings →
   transaction` ser resolvida (ver Consequências).
9. **A entrega é faseada em ondas com valor próprio** (§8 do design), sendo a Onda 0 a correção
   isolada do `saldo_inicial` e a Onda 1 a conferência de um número — que funciona **sem parser
   nenhum**.

**Regra dos Planos (normativa e testável):** nenhum cálculo de saldo bancário lê `transactions` e
vice-versa; `app.modules.bank` pode importar `app.modules.wallet`, nunca o contrário; todo campo de
saldo trafega com um campo irmão `*_origem` declarando **de qual plano de dinheiro** ele vem
(`plataforma` | `banco` | `misto` | `indisponivel`). A procedência da **evidência externa** de um
saldo atestado por terceiro é um **segundo eixo**, com campo e vocabulário próprios (`*_fonte`) —
ver Adendo 1 e design §1.3.1.

## Alternativas consideradas e rejeitadas

### A. Saldo declarado agregado, sem entidade de conta (recomendação do estudo, rodada 1)

Uma "posição de caixa" por tenant, sem `bank_accounts`, sem movimentos, sem OFX: o usuário declara o
saldo, o sistema compara com o calculado e mostra a divergência.

- **A favor:** ~1 onda de esforço, zero manutenção perpétua, complexidade percebida mínima, e
  conserta o `saldo_inicial` de quebra.
- **Rejeitada porque:** não localiza o furo (R1), não carrega contraparte por movimento (R2) e não
  modela transferência entre contas próprias (R3) — falha nos três requisitos declarados do fundador.
- **Não foi descartada, foi absorvida:** `bank_balance_checkpoints` (§2.4 do design) é exatamente
  essa capacidade, e a Onda 1 a entrega antes de qualquer parser existir. Se as ondas seguintes
  nunca forem feitas, o e1p fica com a Opção A — e isso é um desfecho aceitável, não um fracasso.

### B. Open Finance via agregador (Pluggy / Belvo / Klavi / Tecnospeed)

- **A favor:** completude quase perfeita **sem depender de disciplina** do usuário — o único caminho
  que elimina de fato a causa-raiz ("o e1p só vê o dinheiro que ele mesmo originou").
- **Rejeitada porque:** viola a restrição declarada do fundador (*"não podemos ficar contando com
  serviços de terceiros"*). Subsidiariamente: custo fixo a partir de R$ 2.500/mês `[CONFIRMADO —
  pluggy.ai/precos, 2026-07-29]` incorrido antes do primeiro usuário, colidindo frontalmente com a
  Regra de Ouro nº 4 e com a filosofia "sem custo parado" do ADR 0001; e dependência de terceiro no
  caminho crítico de um dado que o produto apresenta como verdade.
- **Nota honesta:** o obstáculo **regulatório** é menor do que se costuma dizer (a e1p seria cliente
  de uma instituição autorizada, não participante do ecossistema) e o limite de 12 meses para
  consentimento **acabou** (Resolução Conjunta CMN/BCB nº 7). O bloqueio é de dependência e custo,
  não de regulação. Se a restrição do fundador mudar **e** houver receita dedicada, reavaliar.

### C. Só reforçar o motor de diagnóstico (detectar sintomas indiretos)

Regras no `engine.py` do tipo "mês sem despesa em categoria recorrente", "margem > 85% é implausível".

- **A favor:** ~0,5 onda, risco quase nulo, encaixa no motor puro existente.
- **Rejeitada como solução:** **infere** em vez de **medir**; quem esquece a mesma despesa todo mês
  tem um padrão consistente e passa despercebido. E não conserta o `saldo_inicial`.
- **Absorvida:** a regra de completude da §5.3 do design **é** essa ideia, agora alimentada por uma
  medição real em vez de uma heurística.

### D. Coluna de conciliação no movimento (em vez de tabela de ligação)

- **A favor:** um join a menos, uma tabela a menos.
- **Rejeitada porque:** torna **impossível** o caso "um Pix quita duas contas" — que não é edge case
  neste produto (a Fila de Pagamentos existe justamente para agrupar o que vence no dia, e o
  comportamento natural é pagar tudo junto). Uma coluna condenaria esse caso a aparecer
  eternamente como "furo" na conferência: o design criaria o falso positivo mais comum.

### E. Absorver `investment_accounts` dentro de `bank_accounts`

- **A favor:** um conceito só.
- **Rejeitada porque:** destruiria capacidade já entregue e testada (Story 5.6: `index_rate_label`,
  `accrued_yield_cents`, rentabilidade, `InvestimentosPage.tsx`, `diagnostics._investment_returns`)
  e poluiria `bank_accounts` com colunas que a maioria das contas nunca usa. A separação
  *dinheiro* (conta) × *produto financeiro* (aplicação) é a única fatia que não perde nada.

### F. Não fazer nada (manter o status quo)

- **Rejeitada porque:** o status quo **já está errado** — a Projeção e o Runway mentem hoje, sem
  nenhum lançamento esquecido. Mesmo que todo o resto deste ADR fosse descartado, a Onda 0 teria de
  ser feita.

## Consequências

### Aceitas conscientemente

**1. Parser por banco é manutenção perpétua. Sem eufemismo:**

OFX 1.x é SGML pré-XML com dialetos por instituição; encoding varia (CP1252 vs UTF-8 vs Latin-1);
formato de data varia; CSV não tem padrão nenhum. Cada banco novo suportado é trabalho novo, **para
sempre**, e o trabalho é reativo — o banco muda o layout e a e1p descobre pelo relato de um usuário,
depois que o import quebrou. `[ESTIMATIVA — 2 a 3 rodadas de correção por banco novo, base: o
precedente do próprio projeto, PRs #56 e #58, duas rodadas de fix de campo no comprovante mobile]`.

Isto é o preço direto de *"não podemos ficar contando com serviços de terceiros"*: a e1p troca um
custo **monetário e previsível** (R$ 2.500/mês) por um custo **de engenharia, recorrente e
imprevisível**. É uma troca legítima e foi feita de olhos abertos — mas não é "de graça", e chamar
de graça seria desonesto.

Mitigações no design: strategy plugável (formato novo = classe nova, não `if` num parser gigante);
layouts de CSV em YAML (banco novo = arquivo de dados); falha de parse é **fail-loud** e nunca grava
lixo em `raw_description` (que é imutável); começar com 1–2 formatos, não 10.

**2. Complexidade percebida sobe, e o posicionamento fica sob tensão.** O e1p se aproxima da
fronteira "software de gestão → software de contabilidade". Mitigações: o menu se chama **"Contas &
Saldos"**, nunca "Conciliação bancária"; a conferência abre com **uma frase**, não com uma tabela; o
extrato linha a linha é alcançado a partir do sinal de diagnóstico, não da sidebar; e a conferência
funciona **sem** import (Onda 1).

**3. O e1p passa a guardar dado bancário e PII de terceiros.** `raw_description`,
`counterparty_name` e `counterparty_document` são dado financeiro sensível, incluindo CPF de pessoas
que nunca contrataram com a e1p. Consequências: anonimizador **obrigatório** antes de qualquer
chamada de IA que toque esses campos (Regra de Ouro nº 2 / NFR2), minimização na extração, e o
arquivo original retido em `attachments` sob `core/storage`. A purga dinâmica de `delete_account`
(que descobre subclasses de `TenantMixin`) cobre as tabelas novas automaticamente.

**4. Um `status` materializado em `bank_transactions`.** É a única materialização do design e existe
para que a conferência varra "o que não bateu" por índice parcial. Escrito por um único ponto
(`_refresh_status`, na mesma transação da mutação do vínculo) e auditável por
`python -m app.scripts.bank_audit`.

**5. Uma migration com backfill sobre dado existente** (a de `investment_accounts`). É a única, e
está exposta à armadilha documentada na migration 0046: sob `FORCE ROW LEVEL SECURITY`, um `UPDATE`
sem GUC de tenant é filtrado a zero linhas **em silêncio**, e o SQLite dos testes não pega.

### Bloqueios e pré-requisitos

**6. Baixa de `Charge` a partir do extrato está BLOQUEADA.** O estorno de Contas a Receber foi
implementado, revisado em duas rodadas e **removido antes do merge** porque `platform_earnings` não
guarda vínculo de volta à `Transaction`/`Charge` de origem — pagar → estornar → pagar de novo
duplicaria o GMV no painel do Master (`docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md`,
Adendo). Como um matcher **vai** produzir baixas indevidas, e como não existe caminho de desfazer,
a onda que dá baixa em cobrança só começa depois de a dívida ser paga. Baixa de `Payable` é
liberada (nunca move a Carteira e tem `POST /payables/bills/{id}/reverse`).

### Positivas

**7. A Projeção de Caixa e o Runway passam a ser verdadeiros** — o dano mais imediato do sistema
atual desaparece já na Onda 0/1.

**8. Aporte e resgate deixam de ser invisíveis** e `principal_cents` deixa de ser um número digitado
sem lastro (R3 atendido integralmente na Onda 2).

**9. Rastreabilidade tributária fica preparada a custo ~zero** — os campos de contraparte, natureza
da operação e documento fiscal nascem nullable. É barato guardar cedo e impossível reconstruir tarde:
o dado histórico não volta.

**10. Zero custo recorrente novo.** Coerente com a Regra de Ouro nº 4 e com os ADRs 0001 e 0002.

## Adendos de ratificação (2026-07-29)

> Origem: dois @sm expandiram o Epic 8 em 8 stories e escalaram sete desvios do design para
> ratificação. Parecer completo:
> [`docs/architecture/controle-bancario-design-ratificacao.md`](../architecture/controle-bancario-design-ratificacao.md).
> Nenhum desvio alterou uma decisão deste ADR; três alteraram o **grão** de como ela é implementada, e
> por isso ficam registrados aqui — um ADR que descreve um design que mudou é pior do que nenhum.

**Adendo 1 — A procedência de um saldo tem DOIS eixos, não um.** O texto original da Regra dos Planos
tratava `*_origem` como um campo único, e o design listava três vocabulários incompatíveis para ele em
três seções. A causa era conceitual: *"de qual plano de dinheiro este número vem"* (`plataforma` |
`banco` | `misto` | `indisponivel`) e *"por qual porta este saldo externo entrou no e1p"* (`manual` |
`ofx`, os valores da coluna `bank_balance_checkpoints.origin`) são perguntas diferentes. Dois campos
(`*_origem` e `*_fonte`), dois vocabulários, em dois lugares (`core/money_planes.py` e
`bank/models.py`). Os valores `declarado` e `extrato` ficam **revogados** como `*_origem`: eram o eixo
B disfarçado, e mantê-los obrigava uma tradução silenciosa (`origin='manual'` → `origem='declarado'`)
que só existia para satisfazer um documento incoerente. **Sem impacto na decisão**; impacto no
contrato de API, resolvido antes de qualquer implementação.

**Adendo 2 — A Onda 0 suprime também o `alert` de janela negativa, não só o runway em dias.** A
Consequência positiva 7 deste ADR (*"a Projeção e o Runway passam a ser verdadeiros já na Onda 0/1"*)
era otimista: a Onda 0 **não** conserta o número (isso é a Onda 1), ela cala as afirmações que
dependiam dele. E eram **duas** afirmações, não uma — o 🔴 *"projeção de caixa negativa em N dias"*
nasce do mesmo `saldo_inicial` contaminado. Como `request_payout` só marca `withdrawn` (não existe
saque real) e `payables` não toca a Carteira, `available_cents` só cresce para todo tenant real, o que
faz desse `alert` uma **máquina de falso negativo**: silêncio exatamente quando deveria alertar. Fica
suprimido na Onda 0 (`alert=False` + `alert_suprimido`), com `saldo_projetado_cents` **ainda exposto e
exibido** — suprime-se a afirmação, nunca o número. Restaurado na Onda 1, sobre saldo com lastro.
Design §6.1.2.

**Adendo 3 — Nenhum número de revision de migration é fixado por design.** O design prescrevia "uma
migration por onda" e mapeava `Onda 1 → 0058`. Errado em ambos: a granularidade real é **uma migration
por story que cria tabela** (a Onda 1 cria três tabelas em três stories, logo três revisions), e o
número depende do head real no momento da implementação — encadear num revision antigo produz
`multiple heads` e quebra `alembic upgrade head`. A coluna "Migration" do faseamento vale como
**ordem**, não como identificador. Design §2.

**Custo aceito e adicionado à conta desta decisão:** a Onda 0 obriga a **atualizar os testes de runway
da Story 5.7** (que hoje afirmam um número de dias) e faz `runway.days` ser `None` em todo cenário com
queima até a Onda 1. Isso é correção de bug, não regressão (alternativa F acima), e a cobertura do
cálculo se desloca para `burn_rate_cents_per_day`, que continua exposto e continua correto.

## Adendo 4 (2026-07-30) — A origem do movimento, e a reordenação das ondas

> Origem: o fundador identificou, com as Ondas 0 e 1 já em produção (`7dba286`), uma **falha de
> escopo do design**. Documento completo:
> [`docs/architecture/controle-bancario-onda2-design.md`](../architecture/controle-bancario-onda2-design.md).
> **Nenhuma decisão deste ADR é revertida.** A restrição "sem agregador" (F1/alternativa B) continua
> intacta, o bloqueio da baixa de `Charge` continua intacto, o saldo derivado continua derivado, a
> Regra dos Planos continua normativa. O que muda é **a fonte do movimento** e **a ordem das ondas**.

**O que estava errado.** O design modelou **uma** direção do fluxo — *extrato → sistema* (importar
OFX e casar linhas contra `payables`/`charges`) — e nunca modelou a direção oposta, *sistema →
banco*. Quando o dono dá baixa numa conta a pagar, o e1p **já sabe** valor, data e fornecedor; falta
só de qual conta o dinheiro saiu, e virar aquilo um `bank_transaction`. Isso não depende de OFX nem
de banco nenhum. Confirmado por grep: `payables` não tem **nenhuma** referência a `bank`, e
`bank_transactions.SOURCES` não tem `payable`.

Consequência medida em produção: o tenant tem **45 `payables` pagas, 0 `charges` e saldo derivado
R$ 0,00**. Declarar o saldo produziria uma divergência gigante que diz *"você não digitou nada"* —
não *"faltam estes lançamentos"* —, e o único conserto disponível seria redigitar 45 contas como
movimento bancário: digitação dupla, exatamente o peso que o produto promete não impor.

**Decisão acrescentada (item 11 da Decisão):**

> **REGRA DA ORIGEM.** Todo evento do e1p que significa *"dinheiro entrou ou saiu de uma conta real
> do dono"* gera **exatamente um** `bank_transaction`, na mesma transação, **nascido conciliado**,
> com `origin_id` apontando para o lançamento de origem (1:1, garantido por índice único parcial).
> Corrigir a conta ou a data **move** o movimento; estornar o lançamento **apaga** o movimento.
> **Lançamento manual e importação existem para o resíduo** — o que nenhum evento do sistema
> conhece.
>
> A Regra da Origem alimenta `saldo_sistema`, **nunca** `saldo_banco`. O checkpoint continua sendo a
> única fonte do lado externo e continua não sendo corrigido por nada (Consequência: a divergência
> diminuir porque o sistema passou a **saber mais** é o objetivo; diminuir porque um lado foi
> ajustado contra o outro continua proibido).

**Decisões do fundador que este adendo formaliza:** conta bancária **obrigatória** na baixa de Contas
a Pagar e no recebimento; lançamento manual reduzido ao que só existe no banco (tarifa, IOF,
transferência para aplicação); **data da baixa editável, com default no vencimento e futuro
permitido** (`paid_at` hoje é cravado em `now()`, `payables/service.py:258`); backfill das 45 contas
feito à mão pelo fundador, por estorno e repagamento conta a conta, sem migração automática de dado.

**Requisito novo, que o Epic 8 não conhecia: agendamento de pagamento.** *"no futuro também permitir,
pq posso estar agendando"* — o dono agenda o débito no app do banco e quer marcar a conta como
resolvida hoje, com a data em que o dinheiro vai sair. Duas consequências arquiteturais:

1. **`payables` ganha o estado `scheduled`**, distinto de `open` e de `paid`. `paid` com data futura
   **afirma o que não aconteceu** — o oposto do princípio da Onda 0 (*"suprima a afirmação, nunca o
   número"*) — e exige o predicado autocontraditório `status='paid' AND paid_at > today` replicado em
   cinco lugares. Verificado: a coluna é `String(12)` (sem migration de tipo) e a DRE filtra
   `status != canceled` nas 4 agregações (impacto zero). O estado é **derivado da data**, não
   escolhido: `paid_on` futuro ⇒ `scheduled`; hoje ou passado ⇒ `paid`.
2. **A guarda contra data futura muda de lugar, não desaparece.** De *"recuse `posted_at` futuro"*
   para **"nenhuma superfície de saldo corrente inclui o futuro"**: `until=None` passa a significar
   **hoje** (fail-closed) nas funções de saldo derivado. A varredura encontrou o defeito concentrado
   em `bank/router.py` (6 chamadas); a Projeção (`projection.py:329`, já com `until=today`) e a
   Conferência (`reconciliation.py:358`, `until` = `reference_date` do checkpoint) **já estavam
   corretas**.

**Efeito colateral positivo:** um agendamento que **falha** (saldo insuficiente, banco recusou) vira
divergência no ciclo seguinte — o movimento entra no saldo derivado quando a data chega, o banco diz
outra coisa, e a conferência acusa. É uma classe de furo que hoje ninguém pegaria. Como
`divergencia > 0` também é o sintoma de *"recebi e não registrei"*, o Diagnóstico ganha uma regra
determinística que **nomeia o agendamento vencido suspeito** em vez de só apresentar o número.

**A assimetria do recebimento, resolvida sem violar a Regra dos Planos.** Cobrança paga **pelo
trilho** (Asaas) cai na carteira da e1p com split retido e **não** encosta na conta do dono; cobrança
paga **fora do trilho** (Pix direto) cai na conta do dono e a e1p **não** retém split. Os dois viram
caminhos separados, amarrados por uma invariante estrutural: **para toda `Charge` paga, exatamente um
de `transaction_id` e `bank_account_id` é não-nulo** — nunca os dois, nunca nenhum. Não existe coluna
de rótulo da rota: a rota é derivada dos dois ponteiros, para não haver uma terceira fonte de verdade
(lição do Adendo 1). O caminho fora do trilho **nunca** cria `Transaction` nem `PlatformEarning`, e
isso é verificado por espião no `core` da carteira, no mesmo padrão da garantia IV1 da Story 5.6.

**Reordenação das ondas — o critério é dependência externa crescente.**

| Nova | Era | Entrega | Dependência externa |
|---|---|---|---|
| 2 | *(nova)* | A origem do movimento (`payable`→banco, recebimento fora do trilho, data de baixa, manual curado, transferência entre contas próprias) | **nenhuma** |
| 2b | 2 | Aplicação como conta, `principal_cents` derivado, `register_yield`→movimento | nenhuma (mas o **único backfill** do épico) |
| 3 | 6 | Payout da Carteira fecha o circuito | nenhuma |
| 4 | 3 | Importação OFX/CSV | **@analyst D6** + gate §3.1 + manutenção perpétua |
| 5 | 4 | Sugestão de vínculo + baixa de `Payable` pelo extrato | Onda 4 |
| 6 | 5 | Baixa de Receber pelo extrato | dívida `platform_earnings → transaction` (inalterada) |

**Por que a ordem antiga estava errada, e é o achado mais grave deste adendo:** o epic §3.1 define a
divergência da Onda 1 como **o instrumento do gate** que libera ou mata as ondas caras. Medida
**antes** da Onda 2, essa divergência é enorme por construção — porque mede a **ausência de uma
porta**, não a incompletude da disciplina do dono. Ela teria argumentado, com número na mão, para
**liberar a onda mais cara do épico**. A feature que faltava teria pedido a construção da feature
mais cara. Formalmente, portanto: **a leitura do gate do epic §3.1 só é válida a partir do primeiro
ciclo completo posterior à Onda 2.**

**Dois conflitos do epic §11.4 ficam resolvidos:** **C2** (`register_yield`) em favor do design, agora
por princípio (é a Regra da Origem, não um caso julgado à parte), viajando com a Onda 2b; **C3**
(porta de entrada do arquivo) em favor do **REQ-12** — `POST /bank/accounts/{id}/imports` fica
revogado como porta primária; se a importação for liberada, o arquivo entra pela bandeja/anexo que já
existe.

**Custo acrescentado à conta desta decisão, sem eufemismo:** `bank_accounts` passa a ser
**pré-requisito** de um fluxo central que hoje funciona sozinho — um tenant sem conta cadastrada não
consegue dar baixa em conta a pagar (409 acionável, com cadastro embutido). É a consequência direta
de *"obrigatória"*, e a alternativa é o "opcional com default" que o fundador recusou porque
*"opcional significa que alguém pula, e a conferência volta a medir o que você esqueceu de
preencher"*.

## Revisão futura

Reabrir este ADR se:

- **(a)** A Onda 1 medir divergência tipicamente **dentro** da banda de tolerância na maioria dos
  tenants → o problema era menor do que se supunha; parar na Onda 2 e não construir import. **Este é
  um desfecho bom, não um fracasso.**
- **(b)** A pesquisa do @analyst apontar que **nenhum banco relevante do público-alvo exporta OFX em
  2026** → o caminho de arquivo morre. As Ondas 0–2 sobrevivem (não dependem de arquivo) e a resposta
  para completude passa a ser captura na origem (comprovante + IA).
- **(c)** O custo de manutenção dos parsers passar de ~1 correção por trimestre → congelar em um
  formato canônico e aceitar cobertura parcial.
- **(d)** A tela de extrato virar a mais acessada do financeiro → o teto de simplicidade foi rompido;
  rebaixar a tela e reforçar a conferência de um número.
- **(e)** A restrição *"não podemos contar com serviços de terceiros"* mudar **e** existir receita
  recorrente dedicada que absorva o piso do Open Finance → reavaliar a alternativa B, que hoje é
  tecnicamente superior e economicamente inviável.
- **(f)** Surgir obrigação legal exigindo conciliação formal fechando em zero → o design serve, mas
  o teto de simplicidade muda por força externa, e isso é conversa de posicionamento, não de escopo.
