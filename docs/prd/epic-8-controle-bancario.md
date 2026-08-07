# Epic 8: Controle Bancário e Conferência

> **Classificação:** FEATURE NOVA (pós-go-live) — plano 3 do dinheiro (o extrato real do usuário) +
> conferência de completude. **Contém também um bug de dados em produção** (Onda 0), que é corrigível
> isoladamente.
> **Estado (2026-07-30):** **Ondas 0 e 1 ✅ EM PRODUÇÃO** (PR #61, `7dba286`, migrations 0058/0059/0060).
> **Onda 2 — "a origem do movimento" — LIBERADA** por decisão do fundador (2026-07-30, §9.1).
> **Onda 2b** entra como escopo planejado, não liberado; **Ondas 3, 4 e 5** planejadas, não liberadas
> (4 e 5 sujeitas ao gate §3.1); **Onda 6 bloqueada** com pré-requisito nomeado.
> ⚠️ **As ondas foram RENUMERADAS em 2026-07-30.** Ver §5 e §11.5 antes de citar qualquer "Onda N"
> escrita antes desta data — os números 2 a 6 **mudaram de significado**.
> **Sequenciamento:** depende do Epic 5 (Inteligência Financeira) **já entregue** — estende
> `financial_intelligence` (`projection.py`, `engine.py`, `diagnostics.py`), `payables`, `receivables` e
> `investments`. Independente dos Epics 6 e 7 (podem correr em paralelo).
> Internamente: Onda 0 ✅ → Onda 1 ✅ → **Onda 2** → 2b → 3 → 4 → 5 → 6.
> **Fonte:** design-mãe [`../architecture/controle-bancario-design.md`](../architecture/controle-bancario-design.md)
> (ratificado, **parcialmente supersedido**) + [`../architecture/controle-bancario-design-ratificacao.md`](../architecture/controle-bancario-design-ratificacao.md);
> design da Onda 2 [`../architecture/controle-bancario-onda2-design.md`](../architecture/controle-bancario-onda2-design.md)
> (**fonte de escopo da Onda 2 e da nova ordem**); ADR
> [`../decisions/0003-controle-bancario-nativo.md`](../decisions/0003-controle-bancario-nativo.md)
> (Aceito, **Adendo 4**); pesquisa [`../research/2026-07-29-controle-bancario-requisitos-e-viabilidade.md`](../research/2026-07-29-controle-bancario-requisitos-e-viabilidade.md)
> (REQ-1..32); gate [`../qa/epic-8-onda-0-1-gate-2026-07-30.md`](../qa/epic-8-onda-0-1-gate-2026-07-30.md);
> `CLAUDE.md` §"Financeiro: Controle Bancário e Conferência" (as 7 regras invariantes);
> **ratificação dos 7 conflitos da Onda 2** [`../architecture/controle-bancario-onda2-ratificacao.md`](../architecture/controle-bancario-onda2-ratificacao.md)
> (@architect, 2026-07-30 — **normativa onde diverge do design**); **validação das 11 stories**
> [`../stories/8.8-validacao-po-onda2.md`](../stories/8.8-validacao-po-onda2.md) (@po, 2026-07-30).
> **Este epic NÃO reabre o "o quê" nem o "como".** Ele organiza a execução do que já foi decidido.
>
> ⚠️ **Atualizado em 2026-07-30 (2ª rodada) com as 4 correções escaladas ao @pm** — E-1 (`bank_audit`
> não existe, §"Contexto"), E-2 (pré-condição do gate P1..P4 + F-D12 fechada, §3.1.2), E-3 (forma
> canônica das pernas de transferência, item 2.24 e Story 8.18), E-4 (Stories **8.19** e **8.20** na §6
> e na ordem de merge). Todas são **transcrição** da ratificação e da validação; nenhuma decisão de
> escopo da Onda 2 foi reaberta.

---

## Contexto do sistema existente (para o @sm)

O e1p é um SaaS multi-tenant white-label (FastAPI + PostgreSQL 16 com **Row-Level Security**; React +
Vite; design "Portal", cor `#5D44F8`). Isolamento entre tenants é garantido **apenas** por RLS, com a
app conectando como papel non-superuser `e1p_app`. Dinheiro sempre em **centavos** (`BigInteger`).

O e1p conhece **três planos de dinheiro** e implementa só dois (ADR 0003, Contexto):

| Plano | O que é | Tabelas | Situação |
|---|---|---|---|
| 1 — Plataforma | Dinheiro no trilho e1p, com split 40/30/20 | `transactions`, `platform_earnings` (global) | Implementado |
| 2 — Negócio | Direitos e obrigações, em competência e em caixa | `charges`, `payables`, `chart_accounts`, `cost_centers` | Implementado (Epic 5) |
| 3 — Bancário | O extrato real da conta do usuário | — | **Não existe** |

**Ativos a reusar (não recriar):**
- `financial_intelligence/engine.py` — motor de diagnóstico **puro, sem I/O** (Story 5.8). O ponto de
  extensão da conferência é uma regra nova nesse motor, não uma tela paralela (design §5.3).
- `financial_intelligence/projection.py` + `diagnostics.py` — projeção/runway e a camada fina de I/O.
- `investments/` — `investment_accounts` com `index_rate_label`, `accrued_yield_cents`, rentabilidade
  (Story 5.6) e `register_yield` criando `Charge status=paid` com `external_ref='investment:<id>'`.
- `payables/` — `build_payable` + `apply_paid` (versões sem commit, já extraídas para a bandeja de
  comprovantes) e `POST /payables/bills/{id}/reverse` (estorno seguro).
- `payables/receipts.py` + `attachments` + `core/storage.py` (S3 com fallback Postgres).
- `core/anonymizer` (obrigatório antes de qualquer chamada à IA — Regra de Ouro nº 2), `core/ai`,
  `core/events` (barramento pós-commit que isola exceções de assinantes).
- Padrão de migration com RLS: `migrations/versions/0049_investments.py::_enable_rls`.
- ⚠️ Armadilha de backfill sob `FORCE ROW LEVEL SECURITY`, documentada em
  `migrations/versions/0046_ledger_classification.py`: `UPDATE` sem a GUC `app.current_tenant_id` é
  filtrado a **zero linhas, em silêncio** — e o SQLite dos testes unitários não pega.

**Ativos NOVOS a reusar, entregues pelas Ondas 0 e 1 (não recriar):**
- `app/modules/bank/` — `bank_accounts`, `bank_transactions`, `bank_balance_checkpoints`,
  `derived_balance`/`derived_balances_as_of`, `reconciliation.py` (read-only).
- `app/core/money_planes.py` — o eixo de **plano** (`plataforma｜banco｜misto｜indisponivel`).
- `tests/test_money_planes.py` — gates estruturais da Regra dos Planos, **com varredura AST** e teste
  de mutação já aplicado (4 mutantes mortos no re-gate).
- Telas `/financeiro/contas` e `/financeiro/conferencia`, com os **testes de colisão de rótulo** que o
  UX-001 instituiu (`contas.test.ts:157-168`) — qualquer rótulo novo passa por eles.
- `app/worker.py::run_sweep` — itera tenants sob `tenant_session`, idempotente, réplica única.

> 🔴 **CORREÇÃO 2026-07-30 — `app/scripts/bank_audit.py` NÃO EXISTE e nunca existiu.** Esta lista
> chegou a citá-lo como ativo entregue pelas Ondas 0 e 1, sob a instrução *"não recriar"*. Verificado
> pela @architect e pelo @po de forma independente: `grep -rn "bank_audit" apps/` → **zero**;
> `apps/api/app/scripts/` tem `__init__.py`, `migrate_attachments_to_s3.py` e `scan_orphan_storage.py`.
> A Story 8.9 obedeceu ao epic e mandou o @dev **editar um arquivo inexistente** — que é o modo de
> falha exato desta entrada. A story já foi corrigida pelo @po; esta é a correção da **fonte**.
>
> **O que fica no lugar, e quando o script volta a ser assunto:**
>
> | Trabalho que o script prometia | Onde ele mora agora |
> |---|---|
> | Auditar `payables.bank_transaction_id` (cache) × `origin_id` (verdade) — **obrigação da Onda 2** | **Teste, não script:** `test_cache_de_movimento_nunca_diverge_do_origin_id`, cobrindo os cinco caminhos de mutação (baixar, trocar conta, trocar data, estornar, repagar). A divergência só é alcançável **por bug** — `sync_origin_movement` é o escritor único, devolve a linha na mesma chamada e na mesma transação. Condição alcançável só por bug se prova com teste; um script que ninguém tem gatilho para rodar não é garantia, é intenção documentada |
> | Auditar o `status` materializado (`partial`/`matched`) | **Pré-requisito da Onda 5**, junto com `_refresh_status` (que também não existe — `bank/service.py:826` o descreve como trabalho da Onda 4). É lá que a divergência passa a ser alcançável **sem** bug: matcher concorrente, vínculo parcial |
>
> **Regra de método que fica** (é a segunda vez que uma lista de ativos induz uma story a especificar
> errado — a primeira foi a entrada de CPF/CNPJ do `CLAUDE.md` §6.1, que levou a Story 8.2 a
> especificar validação fraca): **uma lista de ativos é um conjunto de afirmações verificáveis sobre o
> repositório.** Quem acrescenta um item aqui roda o `ls`/`grep` antes. Custo: 2 segundos por item.
> → ratificação §C-4; validação do @po §3 e §7.1 (E-1)

**Head de migrations no momento desta atualização: 0060** (`bank_balance_checkpoints`). ⚠️ O epic **não
fixa número de revision**; o @sm/@dev **confirma o head real** no momento da implementação e encadeia a
partir dele. (A tabela da §5 na versão anterior fixava 0059/0060/0061 por onda e **estava errada** — a
Onda 1 sozinha consumiu 0058, 0059 e 0060.)

---

## 1. O problema — a assimetria estrutural entre receber e pagar

**Receber tem três testemunhas independentes.** Uma cobrança quitada é confirmada pelo gateway
(Asaas), pelo webhook (`POST /receivables/webhook`) e pelo dinheiro entrando na Carteira com split.
Se o dono não fizer nada, o sistema ainda sabe.

**Pagar não tem nenhuma.** Se o dono paga um boleto pelo app do banco e não lança em Contas a Pagar,
**nada protesta**. E o pior não é a ausência do dado: é que **o silêncio de uma despesa não lançada é
indistinguível do silêncio de um mês sem despesa**. O sistema não tem como saber a diferença.

Consequência direta, nos relatórios que o Epic 5 acabou de entregar:

| Relatório | O que acontece com despesa não lançada |
|---|---|
| **DRE** (`dre.py`) | Infla o lucro — a receita está completa (3 testemunhas), o custo não |
| **Lucratividade por contrato** (`profitability.py`) | Distorce — deriva da DRE; margem aparente maior que a real |
| **Projeção de Caixa / Runway** (`projection.py`) | Mente — projeta saída que nunca é debitada |

**Evidência de mercado que sustenta o diagnóstico (pesquisa §3.1):** o **QuickBooks Solopreneur**
(US$ 20/mês, líder mundial da categoria "dono solo") **não tem contas a pagar** — nem cadastro de
fornecedor, nem agendamento, nem relatório de pendências. Ele sabe que a despesa aconteceu **pelo
extrato** (bank feed automático + categorização). A assimetria não é peculiaridade do e1p: é a
assimetria estrutural da categoria, e o líder a resolve exatamente por observar o dinheiro sair.
Diferença que joga a favor do e1p: aqui contas a pagar, plano de contas, centro de custo e
lucratividade **já existem** — o extrato entra como **conferência** sobre um modelo que existe, não
como substituto dele.

### 1.1 O bug já confirmado por leitura de código — independente de qualquer esquecimento

`apps/api/app/modules/financial_intelligence/projection.py:177` semeia o saldo inicial da projeção com:

```python
saldo_inicial = int(wallet_service.wallet_summary(db)["available_cents"])
```

`available_cents` é saldo da **carteira da plataforma** (plano 1), usado como se fosse saldo da
**conta bancária do usuário** (plano 3). **Não existe configuração de uso em que esteja certo:**

- se o usuário nunca saca, o número acumula todo o faturamento líquido histórico e **nunca diminui
  quando uma conta é paga** — porque `payables` não toca a Carteira por design (`payables/models.py:4`);
- se o usuário saca tudo, o número vai a zero enquanto o dinheiro está na conta dele.

**Isto é bug, não lacuna de feature**, e a correção (Onda 0) não depende de nada mais deste epic.
Mesmo que todo o resto fosse descartado, a Onda 0 teria de ser feita (ADR 0003, alternativa F).

### 1.2 A falha de escopo achada com as Ondas 0 e 1 já em produção (2026-07-30)

> **Registrada aqui, e não numa nota de rodapé, porque ela mudou a ordem do épico inteiro e porque a
> lição vale para as ondas que ainda não foram desenhadas.** Fonte:
> [`controle-bancario-onda2-design.md`](../architecture/controle-bancario-onda2-design.md) §1;
> ADR 0003 Adendo 4.

O design modelou **uma** direção do fluxo — **extrato → sistema** (importar OFX e casar linhas contra
`payables`/`charges`) — e **nunca modelou a direção oposta, sistema → banco**. Quando o dono marca uma
conta a pagar como paga, o e1p **já sabe** valor, data, fornecedor, plano de contas e centro de custo;
falta só **de qual conta o dinheiro saiu**, e virar aquilo um movimento bancário. Isso não depende de
OFX, de arquivo nem de banco nenhum.

**Diagnóstico do fundador, e é a moldura de método, não um pedido de feature:**

> *"o que vc tem que entender, que é um sistema integrado, não tem o motivo de tudo começar do zero."*

**O estado que isso produziu em produção:** 45 `payables` pagas, 0 `charges`, saldo derivado
**R$ 0,00** — e o único caminho disponível para encher o razão bancário seria **redigitar 45 contas**
como movimento manual. Digitação dupla é exatamente o peso que este produto promete não impor.

O inventário que deveria ter sido feito antes de desenhar a porta de entrada (design da Onda 2 §1.2):
**cinco eventos que o sistema já conhece e significam "dinheiro se moveu numa conta real"** — baixa de
Contas a Pagar, comprovante vinculado com baixa, recebimento fora do trilho (que sequer tinha caminho),
rendimento de aplicação, payout da Carteira — e **zero ligados**. A Onda 1 entregou o plano 3 **sem
nenhum afluente**.

**A regra de método que este epic passa a adotar, para as ondas ainda não desenhadas:**

> **Antes de desenhar a porta de entrada de um plano de dados novo, enumere TODOS os eventos que o
> sistema já emite e que significam um fato desse plano. Ligue-os primeiro. A porta manual e a
> importação existem para o resíduo — o que ninguém no sistema sabe — e só o resíduo justifica o custo
> delas.**

**Regra irmã, sobre coluna nullable** (o design-mãe §6.7 tinha `payables.bank_account_id` como
*"opcional, onda posterior, melhora a sugestão de match"*):

> **Quando um design cria uma coluna nullable e a justifica com "melhora X", pergunte se o que ela
> guarda é um FATO ou uma PREFERÊNCIA. Preferência é otimização e pode esperar. Fato tem hora marcada:
> o instante em que ele acontece. Perdido esse instante, ele não volta.**

**O que NÃO muda por causa desta falha:** nada do que foi construído nas Ondas 0 e 1 é removido,
reescrito ou migrado. As três tabelas, o saldo derivado, o checkpoint, a conferência, os gates da Regra
dos Planos e as duas telas são o substrato **correto** e são reusados inteiros. O que muda é **quem
escreve** `bank_transactions`.

---

## 2. Epic Goal

Dar ao e1p o **plano 3 do dinheiro** — conta financeira própria do usuário como entidade de primeira
classe, com saldo **derivado** dos movimentos — e, sobre ele, uma **conferência que localiza furos**:
comparar o saldo que o banco mostra com o saldo que o sistema calcula, **por conta**, e dizer em uma
frase quanto está faltando. Sem agregador de Open Finance, sem custo recorrente novo, e sem que os
planos de dinheiro voltem a se misturar (Regra dos Planos, design §1.3).

O epic começa consertando o dano que já existe hoje (Onda 0: nenhum runway em dias sobre saldo de
origem errada) e entrega, na Onda 1, o pedido literal do fundador — *"de saldo batendo é uma
conferência para achar possível furos"* — **sem parser de arquivo nenhum**.

### 2.1 O que este epic explicitamente NÃO é

| Não é | Por quê / fonte |
|---|---|
| **Escrituração contábil** | O critério de sucesso é *"quantos lançamentos faltantes foram encontrados"*, nunca *"fechou em zero"* (REQ-13). Existe **banda de tolerância** e, dentro dela, o sistema fica em silêncio (REQ-16) |
| **Concorrente do contador** | Sociedade de advogados já tem escrituração formal obrigatória por força do Código Civil (pesquisa §1.5) — isso é do contador. O e1p entrega **conferência e controle interno para o dono** |
| **Conformidade com a reforma tributária** | **Decisão do fundador (2026-07-29)** + REQ-28. A obrigação da LC 214/2025 é **documental** (NFS-e com CBS/IBS destacados), não bancária; o split payment não alcança o Simples com DAS unificado — que é o regime da sociedade unipessoal de advocacia (pesquisa §1.2, §1.6). A e-Financeira (IN RFB 2.278/2025) entra como **contexto de risco de divergência**, não como obrigação: o Fisco **já recebe** a movimentação pelas instituições; o risco do contribuinte é a divergência entre extrato e declaração |
| **Conciliação bancária como item de menu** | O rótulo comunica "software de contabilidade" para todo usuário, inclusive quem nunca abre a tela. O menu é **"Contas & Saldos"** (design §5.4) |
| **Integração com agregador de Open Finance** | Pluggy, Belvo, Klavi, Tecnospeed, Celcoin **vetados** por decisão do fundador (ADR 0003, alternativa B; REQ-29) |
| **Baixa automática de Contas a Receber** | Bloqueada até a dívida `platform_earnings → transaction` existir (REQ-17; ver **Onda 6** na numeração nova). ⚠️ **Não confundir com o `settle-externally` da Onda 2** (§5, Onda 2): aquele é o **dono declarando** que recebeu direto no banco, nunca cria `Transaction` nem `PlatformEarning`, e por isso **a dívida não o alcança** (design Onda 2 §5.4) |
| **CNAB 240/400** | Fora do escopo até aparecer banco concreto que ofereça CNAB e não OFX (REQ-11) |
| **Uma tela de 43 linhas de extrato com checkbox como caminho principal** | O caminho principal é **a divergência em uma frase**; o extrato linha a linha é tela de investigação, alcançada a partir do sinal (design §5.2, §5.4) |
| **Base de cobrança da plataforma sobre recebimento fora do trilho** | **Proibição normativa** (design Onda 2 §6): nenhuma superfície da plataforma pode ser construída sobre `charges.bank_account_id` — nem painel do Master, nem agregado em `/admin/*`, nem e-mail, nem taxa. Se a e1p um dia quiser cobrar por isso, é **decisão comercial com consentimento contratual**, nunca consequência técnica de uma coluna. Teste varrendo `/admin` (§5, Onda 2) |
| **Digitação dupla do que o sistema já sabe** | A Regra da Origem (§4.8) torna manual/importação o caminho do **resíduo**. Uma porta manual para algo que já tem porta própria é digitação dupla — e a contagem dupla resultante **parece um achado real** na conferência (§7) |

---

## 3. Business value e critério de sucesso mensurável

**Valor:** os três relatórios analíticos que o Epic 5 entregou (DRE, Lucratividade, Projeção/Runway)
**só valem o que vale a completude dos lançamentos que os alimentam**. Hoje ninguém sabe qual é essa
completude — nem o produto, nem o dono. A Onda 1 transforma "não sei se meus números estão completos"
num **número em reais**, por conta, medido contra a verdade externa (o saldo que o banco mostra). E a
Onda 0 remove, já, a pior combinação possível: precisão espúria (runway "faltam 43 dias") sobre
premissa falsa (saldo de plano errado).

### 3.1 O mecanismo do epic: a divergência é o instrumento de decisão sobre as ondas caras

> ⚠️ **ESTA SEÇÃO FOI CORRIGIDA EM 2026-07-30. A versão anterior estava errada de um jeito que teria
> custado caro.** A correção é a §3.1.1; a regra de decisão corrigida é a §3.1.2. A redação anterior
> — *"a Onda 1 é o instrumento de decisão"* — continua registrada na §3.1.1 como o achado, não como
> instrução.

Isto é **mecanismo do epic, não aspiração**. Hoje **ninguém sabe o tamanho real do problema** — a
conferência é o experimento mais barato para medi-lo (design §8; ADR 0003, Revisão futura (a)).

**Métrica primária:** `|divergencia_cents|` **por conta**, por ciclo de conferência, comparada à banda
de tolerância — e `dias_desde_ultima_conferencia` como métrica de uso. **A medição é por conta, nunca
só consolidada** (ver §3.2).

**Métrica secundária (só a partir da onda de importação — Onda 4 na numeração nova):** contagem de
`movimentos_sem_contrapartida`. É esta que responde literalmente ao REQ-13 ("quantos lançamentos
faltantes foram encontrados") — a conferência mede o **tamanho em R$** do furo, não a contagem dos
lançamentos que faltam. Dizer o contrário seria prometer o que ela não entrega.

#### 3.1.1 O erro: a divergência da Onda 1 mede a ausência de uma porta, não o furo

Este epic definiu a divergência da **Onda 1** como o instrumento do gate que libera ou mata as ondas
caras — **4,5 ondas de trabalho e um custo de manutenção que o ADR 0003 chama de "perpétuo, reativo e
imprevisível"**. Com a falha de escopo da §1.2 exposta, essa definição é insustentável:

> Em produção, o tenant tem **45 `payables` pagas, 0 `charges` e saldo derivado R$ 0,00**. Declarar o
> saldo real produziria uma divergência do tamanho de **tudo o que aconteceu desde a abertura da
> conta**. Esse número diz *"você não digitou nada"*. Ele **não** diz *"faltam estes lançamentos"*.
> **Ele mede a ausência de uma porta, não a incompletude da disciplina do dono.**

E o custo do erro é maior do que uma feature faltando:

> Medida **antes** da Onda 2, a divergência é **enorme por construção** — e teria caído exatamente na
> segunda linha da tabela de decisão antiga (*"fora da banda, recorrente, e o dono não consegue
> explicar de onde vem"*), argumentando **com número na mão** para liberar a onda mais cara do épico.
> **A feature que faltava teria pedido a construção da feature mais cara.**

Não é hipótese: é o que aconteceria no primeiro ciclo de conferência do fundador, e nada no desenho da
Onda 1 avisaria. → design da Onda 2 §9.1; ADR 0003 Adendo 4.

#### 3.1.2 A pré-condição do gate, e a regra de decisão corrigida

> ⚠️ **REESCRITA EM 2026-07-30 (ratificação §C-1). A redação anterior era INSATISFAZÍVEL.** Ela dizia
> *"toda `Payable` paga e toda `Charge` recebida precisam ter conta bancária informada"* — e uma
> `Charge` paga pelo trilho (gateway → webhook → Carteira) tem `transaction_id` e, pela **Invariante do
> Trilho**, **nunca** terá `bank_account_id`. O trilho é o caminho normal do produto: qualquer janela
> com uma cobrança normal fechava o gate **para sempre**. A frase era razoável **e** insatisfazível, e
> nada entre as duas disparava — é o caso que originou a **Regra da Instanciação Obrigatória** do
> `CLAUDE.md`. A redação abaixo é a da @architect, verbatim em substância.

> **PRÉ-CONDIÇÃO DO GATE (normativa).**
>
> A leitura do gate é válida num ciclo de conferência **se e somente se**, na janela conferida, **não
> existe evento conhecido pelo e1p que moveu dinheiro numa conta real do dono sem ter gerado o
> `bank_transaction` correspondente.**
>
> Operacionalmente, **quatro termos**. Cada um tem o predicado que o decide e a onda que o zera:
>
> | # | População | Predicado | Zera na |
> |---|---|---|---|
> | **P1** | Baixa de Contas a Pagar sem conta informada | `Payable`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `bank_account_id IS NULL` | **Onda 2** — a 8.12 torna a coluna obrigatória, então P1 vai a zero **por construção** assim que o legado (as 45, §7.2) for corrigido |
> | **P2** | Recebimento fora do trilho sem conta informada | `Charge`, `status ∈ {paid, scheduled}`, `paid_at::date` na janela, `transaction_id IS NULL`, `bank_account_id IS NULL`, **e** `_not_investment_yield()` | **Onda 2** (8.15) |
> | **P3** | Rendimento de aplicação sem perna bancária | `Charge` com `external_ref LIKE 'investment:%'`, `paid_at::date` na janela | **Onda 2b** |
> | **P4** | Payout da Carteira liquidado sem perna bancária | payout com liquidação real na janela | **Onda 3**. ⚠️ **Hoje é vazio por construção**: `request_payout` só marca `withdrawn` (`wallet/service.py:227`) — nenhum dinheiro sai de conta real. Passa a ser contado quando o payout for real |
>
> **Fora da população, por construção e não por omissão:** `Charge` do trilho
> (`transaction_id IS NOT NULL`). O dinheiro dela está na **Carteira**, não numa conta do dono, e ela
> **não deve** gerar `bank_transaction` até o payout. Incluí-la é exatamente a leitura que tornava a
> pré-condição insatisfazível — e a exclusão é a **Regra dos Planos**, não uma lacuna de preenchimento.
>
> **Membro:** um `Payable` pago em 12/07 com `bank_account_id IS NULL` (uma das 45 legadas) → P1,
> conta.
> **Não-membro:** uma `Charge` paga pelo webhook do Asaas em 12/07 → tem `transaction_id`, **não**
> conta.
>
> ⚠️ **O `_not_investment_yield()` do P2 é IMPORTADO de `receivables/service.py:82-90`, nunca
> reescrito.** Duas cópias divergem — e a ratificação é a prova de que já divergiram uma vez entre dois
> @sm (a Story 8.15 lembrou o predicado; a 8.16 o esqueceu). Sem ele no P2, a `Charge` sintética de
> rendimento cai inteira na população e **o gate não abre para nenhum tenant que registre rendimento**,
> nunca, até a Onda 2b. → ratificação §C-1.2 (achado A-1)

**Consequência de roadmap, escrita sem eufemismo porque muda a leitura do épico:**

> **O gate não abre "depois da Onda 2" em geral.** Ele abre depois da Onda 2 **para um tenant cujos
> únicos eventos que movem conta real na janela sejam baixa de Contas a Pagar e recebimento fora do
> trilho.** Um tenant que registra rendimento precisa da **Onda 2b**; quando o payout virar real,
> precisa da **Onda 3**. Isto **não é escopo novo** — P3 e P4 sempre foram termos da divergência. O que
> muda é que o epic escrevia a pré-condição como se a Onda 2 a satisfizesse sozinha. → ratificação §C-1.4

**F-D12 — RESPONDIDA E FECHADA (2026-07-30): o gate abre no primeiro ciclo completo pós-Onda 2, como
planejado.**

> **Pergunta:** o fundador registra rendimento de aplicação no e1p hoje? (Se sim, P3 é não-vazio e a
> leitura do gate esperaria a Onda 2b.)
>
> **Resposta: NÃO.** Apurada por **consulta ao banco de produção**, não por pergunta ao fundador — que
> é o que a @architect recomendou e o tipo de coisa que ela registra como *"deveria ter instanciado em
> vez de descrito"*. Estado medido: **1 conta de investimento cadastrada, 0 rendimentos lançados**
> (`charges` com `external_ref LIKE 'investment:%'` = **0**).
>
> **Decisão:** **a Onda 2b NÃO é pré-requisito da leitura do gate.** A ordem do §5 fica como está
> (2 → 2b → 3 → …) e nada no roadmap muda por causa disto.
>
> ⚠️ **A decisão é frágil, e a fragilidade é o registro:** ela depende de um contador em zero, não de
> uma propriedade estrutural. **No dia em que o fundador lançar o primeiro rendimento, P3 deixa de ser
> vazio e a leitura do gate passa a depender da Onda 2b** — sem aviso, porque nada no produto liga um
> alarme para isso. O que protege: a **nota do bloco 4 nomeia a própria onda** (item 2.20, Story 8.16
> AC7), então a conferência vai dizer *"este termo fecha na Onda 2b"* na tela, no ciclo em que
> acontecer. É degradação honesta, não silêncio. → ratificação §3.3; validação do @po §7.4

Como isso aparece para o dono: o relatório de conferência ganha **até três notas** no bloco 4 (*"o
sistema declara o que não sabe"*, que já existe exatamente para isto) — **uma por termo não-zero, cada
uma nomeando a onda que a fecha**:

> *"7 lançamentos deste período não informam de qual conta saíram (R$ 3.120,00). A divergência abaixo
> inclui esse valor."* (P1/P2 — **some** quando o mutirão das 45 terminar)
> *"2 rendimentos de aplicação deste período ainda não geram movimento bancário (R$ 340,00). A
> divergência abaixo inclui esse valor."* (P3 — **não some nesta onda**; fecha na Onda 2b)

Nomear a onda em cada nota é o que impede o dono de tentar corrigir à mão um termo que **software
nenhum** consegue fechar ainda — e é o que torna a fragilidade do F-D12 visível na tela, no ciclo em
que ela aparecer. → ratificação §C-1.5; Story 8.16 AC7

⚠️ **A nota ANOTA; ela NUNCA SUBTRAI.** Descontar o termo conhecido da divergência seria o checkpoint
corrigindo o derivado com outra roupa — a divergência iria a zero por construção sempre que o sistema
soubesse explicar a diferença, e a métrica primária do épico morreria. É a **Regra 5 do `CLAUDE.md`**,
e o desenho chega perto dela aqui, por isso a linha está escrita em vez de implícita.
→ design da Onda 2 §9.3.

**Depois da Onda 2, a divergência decompõe em cinco termos, e só um é o alvo** (design da Onda 2 §9.2):

| # | Termo | Natureza |
|---|---|---|
| 1 | Movimentos que só existem no banco (tarifa, IOF, débito automático não cadastrado) | Resíduo estrutural; nunca vai a zero |
| 2 | Recebimentos que o dono não registrou de forma nenhuma | Fecha com a porta de recebimento fora do trilho (Onda 2) |
| 3 | Erro de data (pagou dia 12, o banco compensou dia 13) | Resíduo estrutural |
| 4 | **Contas pagas fora do e1p e nunca cadastradas** | ← **é este o furo que o épico existe para achar** |
| 5 | Agendamento que não saiu (saldo insuficiente, banco recusou, cancelado no app) | Novo com a Onda 2; classe de furo que hoje ninguém pegaria |

Consequência para a **banda de tolerância**: ela deixa de ser "ignore ruído" e passa a ter um trabalho
nomeado — **absorver as classes (1) e (3)**. `max(R$ 50, 0,5%)` continua parecendo a ordem de grandeza
certa, agora com **razão** em vez de suposição.

**Regra de decisão corrigida (o gate deste epic):**

| Leitura da conferência, **no primeiro ciclo completo pós-Onda 2** | Decisão |
|---|---|
| Pré-condição **não** satisfeita — **qualquer** de P1..P4 não-vazio na janela | **O gate não abre.** Nenhuma onda é liberada nem morta com base neste ciclo. **P1/P2 se corrigem com trabalho do dono** (informar a conta) e o ciclo seguinte já vale; **P3 e P4 não se corrigem com trabalho nenhum** — dependem, respectivamente, das Ondas 2b e 3. A nota do bloco 4 diz qual é o caso |
| Divergência tipicamente **dentro** da banda e estável, por 3 ciclos | **Parar depois da Onda 3 (payout).** A **importação (Onda 4)** e a **sugestão de vínculo (Onda 5)** são over-engineering e **não** são liberadas. Desfecho **bom**, não fracasso (ADR 0003, Revisão futura (a)) |
| Divergência **fora** da banda, recorrente, e o dono não consegue explicar de onde vem | Liberar a **importação (Onda 4)** — o furo precisa ser **localizado**, não só quantificado. ⚠️ Sujeita também à dependência D6 (OFX real existe em 2026?) |
| Divergência fora da banda **explicada** por causa conhecida e pontual — inclusive por agendamento que não saiu (termo 5) | Corrigir a causa; **não** liberar a importação |

**Janela de observação sugerida:** 3 ciclos mensais de conferência no tenant do fundador **contados a
partir do primeiro ciclo que satisfaz a pré-condição** — `[SUPOSIÇÃO DO @PM]`, não vem do design nem da
pesquisa; ajustar quando houver mais tenants usando. A **decisão** de liberar ou não as ondas seguintes
é do fundador, com o número na mão.

⚠️ **Onde os números das ondas mudaram, a regra é a mesma; os rótulos é que se moveram.** Toda leitura
antiga deste epic que diga *"liberar a Onda 3"* significa **importação**, que agora é a **Onda 4**. Ver
§11.5.

### 3.2 A conferência é por conta, não só consolidada

**Decisão do fundador (2026-07-29), respondendo D2 do design:** a topologia real é **várias contas
PJ** — corrente + poupança + aplicação, possivelmente em **bancos diferentes**. Não é conta PF
misturada com PJ (D3), então a divergência é sinal **relativamente limpo**.

Consequência que este epic registra como restrição de produto: **divergência agregada entre várias
contas perde poder de diagnóstico.** Se três contas divergem +R$ 1.200, −R$ 900 e +R$ 40, o
consolidado (+R$ 340) parece saudável e esconde dois problemas. Portanto:

> **A conferência é calculada e apresentada POR CONTA.** Um total consolidado pode existir, mas
> **sempre acompanhado da decomposição por conta**, nunca sozinho — mesma disciplina que a Regra dos
> Planos §1.3c impõe aos saldos de origem diferente. O sinal de diagnóstico agrega, mas aponta **qual
> conta** está fora da banda.

---

## 4. Integration Requirements

Camada **majoritariamente aditiva**. Todas as tabelas novas carregam `tenant_id` + `ENABLE` +
`FORCE ROW LEVEL SECURITY` com policy `tenant_isolation` (`USING` + `WITH CHECK`), sem FK dura entre
tabelas de negócio (padrão do projeto: integridade no service, sob RLS), dinheiro em centavos
`BigInteger`. A purga dinâmica de `delete_account` (que descobre subclasses de `TenantMixin`) cobre as
tabelas novas automaticamente.

Restrições que valem para **toda** story deste epic:

1. **Regra dos Planos (design §1.3, normativa e testável):**
   **(a)** nenhum cálculo de saldo bancário lê `transactions`, e nenhum cálculo de saldo de carteira
   lê `bank_transactions`; as duas somas nunca ocupam o mesmo campo numérico.
   **(b)** `app.modules.bank` **pode** importar `app.modules.wallet`; `app.modules.wallet` **nunca**
   importa `app.modules.bank`. O ponto de contato vive no lado `bank`.
   **(c)** todo campo de API que carrega saldo declara a procedência num campo irmão `*_origem` ∈
   `{plataforma, banco, misto, indisponivel}`.
   ⚠️ **Correção (2026-07-30):** os valores `declarado` e `extrato`, que constavam aqui, foram
   **revogados** pela ratificação do design — eram o eixo de **porta de entrada** (`*_fonte` ∈
   `manual｜ofx`) disfarçado de eixo de **plano**. São dois eixos, nunca achatados num campo
   (`CLAUDE.md`, regra 2). O epic estava desatualizado; o código em produção já está certo.
   Isto entra como **teste estrutural** (`tests/test_money_planes.py`), no mesmo estilo do
   `tests/test_tenancy_guard.py` já existente. Sem o teste, o resto degrada por acidente.
   **(d) (a partir da Onda 2):** a dependência é **de negócio para banco, nunca a volta** —
   `payables`/`receivables` **podem** importar `app.modules.bank`; `app.modules.bank` **nunca** importa
   `payables`/`receivables`. Asserção positiva nova em `test_money_planes.py`; sem ela, o primeiro
   atalho de conveniência recria um ciclo (design da Onda 2 §3.5).
2. **Regra da Neutralidade (design §3.5, a partir da Onda 2):** transferência entre contas próprias é
   exclusivamente evento do plano 3 — nunca cria/altera/baixa `Charge`, `Payable` ou `Transaction`, e
   por isso não aparece na DRE, na Lucratividade nem na Projeção como entrada/saída (REQ-20, REQ-21).
   Teste: `test_transferencia_nao_altera_dre` (snapshot idêntico campo a campo).
3. **Caixa vs. competência nunca se invertem:** fluxo de caixa usa `paid_at`; DRE/lucratividade usam
   `competence_date` (`payables/models.py:6-9`, `receivables/models.py:6-9`).
4. **Anonimizador obrigatório** antes de qualquer chamada de IA que toque `raw_description`,
   `counterparty_name` ou `counterparty_document` — extrato carrega PII de terceiro que nunca
   contratou com a e1p (Regra de Ouro nº 2 / REQ-18 / design §7.4). Aplicável a partir das Ondas **4 e
   5** (importação e match). ⚠️ **A Onda 2 não chama IA em lugar nenhum** — as regras novas do
   Diagnóstico são determinísticas, no motor puro.
5. **IA sugere, usuário confirma.** A IA nunca escreve `confirmed_at` e nunca dá baixa (REQ-15,
   design §4.6).
6. **Zero custo recorrente novo** (Regra de Ouro nº 4) e **zero chamada de rede** no pipeline de
   importação.
7. **Não quebrar o que funciona** (Regra de Ouro nº 5): cada story roda `scripts/check.sh` + os 3
   agentes de QA, traz testes novos e validação e2e de isolamento cross-tenant no **Postgres real**
   (`pytest.mark.rls_e2e`, testcontainers, job `cross-tenant-rls`).

### 4.8 A Regra da Origem (normativa e testável, a partir da Onda 2)

> Fonte: design da Onda 2 §2; ADR 0003 Adendo 4, item 11 da Decisão. **Vale para toda story da Onda 2
> em diante.**

> **(a)** Todo evento do e1p que significa *"dinheiro entrou ou saiu de uma conta real do dono"* gera
> **exatamente um** `bank_transaction`, **na mesma transação** do evento, e esse movimento **nasce
> conciliado** (`status='matched'`) — o e1p originou os dois lados, não há julgamento a fazer.
> **(b)** O movimento carrega `origin_id` apontando para o lançamento que o gerou, relação **1:1**,
> garantida por **índice único parcial** `(tenant_id, source, origin_id) WHERE origin_id IS NOT NULL`.
> É **este índice**, e não o `dedup_hash`, a garantia de idempotência.
> **(c)** O ciclo de vida do movimento é **espelho** do lançamento: corrigir conta ou data **move** o
> movimento; estornar o lançamento **apaga** o movimento. Nunca duplica, nunca deixa órfão.
> **(d)** Movimento de origem do sistema **não é editável nem ignorável** pela tela de movimentos —
> quem quer mudá-lo mexe no lançamento de origem. Única exceção: `user_description`, que é rótulo, não
> fato.
> **(e)** Lançamento manual e importação existem para o **resíduo**.

**A regra irmã, que preserva a Regra 5 do `CLAUDE.md`:**

> **A Regra da Origem alimenta `saldo_sistema`, NUNCA `saldo_banco`.** O checkpoint continua sendo a
> única fonte do lado externo e continua não sendo corrigido por nada. **A divergência diminuir porque
> o sistema passou a saber mais é o objetivo; diminuir porque um lado foi ajustado contra o outro
> continua proibido.**

**Invariante da Origem (testável):** `source ∈ SOURCES_SISTEMA` ⟺ `origin_id IS NOT NULL`, nas duas
direções. **Toda regra deste epic é escrita contra os conjuntos `SOURCES_SISTEMA` /
`SOURCES_EXTERNA`, nunca contra um valor solto de `source`** — porque `source` mistura dois eixos
(portas de entrada `manual|ofx|csv` × origens de lançamento `payable|charge|transfer|yield|payout`) e
essa mistura já está em produção na migration 0059. Consertá-la exigiria reescrever coluna com dado sob
`FORCE RLS` para benefício estético; a mitigação escolhida é escrever as regras contra os conjuntos
(design da Onda 2 §3.1).

**Ponto único de escrita:** `app/modules/bank/origin.py::sync_origin_movement` é a **única** função do
repositório que escreve `source ∈ SOURCES_SISTEMA`. Qualquer segundo caminho torna a Regra da Origem
inauditável. Ela **não commita** — o movimento e o lançamento entram na mesma transação, pelo mesmo
motivo de `build_payable`/`apply_paid`/`build_charge`.

### 4.9 A Invariante do Trilho (normativa e testável, a partir da Onda 2)

> **Para toda `Charge` com `status='paid'`, exatamente um de `transaction_id` e `bank_account_id` é
> não-nulo.** Nunca os dois, nunca nenhum.
>
> - `transaction_id IS NOT NULL` → entrou pelo **trilho**: plano 1, split aplicado, `PlatformEarning`
>   criado, **nenhum** `bank_transaction`.
> - `bank_account_id IS NOT NULL` → entrou **fora do trilho**: plano 3, **nenhuma** `Transaction`,
>   **nenhum** `PlatformEarning`, um `bank_transaction` de crédito.

**Não existe coluna `payment_route`.** A rota é **derivada** dos dois ponteiros — um rótulo separado
pode divergir do fato e vira a terceira fonte de verdade (lição do Adendo 1, aplicada preventivamente).
→ design da Onda 2 §3.4, §5.3.

---

## 5. Escopo por ondas

> Cada onda entrega valor sozinha e pode parar ali sem deixar o produto pela metade (design §8).
> Esforço em **ondas de trabalho** `[ESTIMATIVA do design]`, não em horas — não há velocity confiável.

> ⚠️ **RENUMERAÇÃO (2026-07-30).** Uma **Onda 2 nova** — a origem do movimento — entra logo após a
> Onda 1; a Onda 2 antiga (aplicação) vira **2b**; o payout (era 6) sobe para **3**; a importação (era
> 3) desce para **4**; a sugestão de vínculo (era 4) vira **5**; a baixa de Receber (era 5, bloqueada)
> vira **6**. **Critério de ordenação: dependência externa crescente.** Tabela de-para em §11.5.

| Onda | Era | Entrega | Status | Migration | Esforço `[EST.]` | Dependência **externa** |
|---|---|---|---|---|---|---|
| **0** | 0 | Saldo inicial honesto (bug) | ✅ **EM PRODUÇÃO** | — | 0,25 | — |
| **1** | 1 | Contas + saldo derivado + checkpoint + conferência de um número, por conta | ✅ **EM PRODUÇÃO** | 0058, 0059, 0060 | 1,5 | — |
| **2** | *(nova)* | **A origem do movimento**: `payable`→banco, recebimento fora do trilho, data de baixa editável + estado `scheduled`, corte de data nas superfícies de saldo, manual curado, transferência entre contas próprias | 🟢 **LIBERADA** (fundador, 2026-07-30) | +2 aditivas (a partir do head real) | **2,5** `[EST. @PM]` | **nenhuma** |
| **2b** | 2 | Aplicação como conta, `principal_cents` derivado, `register_yield`→movimento | 📋 **PLANEJADA** (não liberada) | +1 | 1,0 | nenhuma — mas carrega **o único backfill** do épico, sob `FORCE RLS` |
| **3** | 6 | Payout da Carteira fecha o circuito | 📋 **PLANEJADA** (não liberada) | +0/1 | 0,5 | nenhuma |
| **4** | 3 | Importação OFX/CSV + órfãos dos dois lados | 📋 **PLANEJADA**; **sujeita ao gate §3.1** | +1 | 2,5 | **D6** (OFX real existe em 2026?) + gate + **manutenção perpétua** |
| **5** | 4 | Sugestão de vínculo (regra → IA) + baixa de Contas a **Pagar** pelo extrato | 📋 **PLANEJADA**; **sujeita ao gate §3.1** | +1 | 2,0 | Onda 4 |
| **6** | 5 | Baixa de Contas a **Receber** a partir do extrato | 🚫 **BLOQUEADA** | +1 | 1,0 (pré-req.) + 1,0 | **dívida `platform_earnings → transaction`** |

**Ordem recomendada:** 0 ✅ → 1 ✅ → **2** → 2b → 3 → 4 → 5, com a **6 fora da fila**.

**Por que a ordem antiga estava errada — o mesmo argumento por três ângulos** (design da Onda 2 §10):

1. **Dependência externa crescente é a regra de ordenação, e a ordem antiga a violava.** As Ondas 2, 2b
   e 3 não dependem de **nada fora do repositório**. A importação depende de três coisas que não
   controlamos: o formato ainda existir nos bancos do público-alvo em 2026 (D6), o número do gate §3.1,
   e um custo de manutenção que o ADR chama de *"perpétuo, reativo e imprevisível"*. **Pôr a onda de
   maior dependência externa antes das de dependência zero foi o erro de ordem.**
2. **A Onda 2 é pré-requisito da métrica primária do épico, não um incremento dela** (§3.1.1).
3. **O custo, se tivéssemos chegado lá na ordem antiga:** a importação traria as 45 linhas reais de
   débito, todas sem contrapartida, e a onda de match seria gasta **casando à mão o que a Onda 2 gera
   de graça e sem erro** — porque o e1p originou os dois lados. Teríamos construído um matcher
   probabilístico para um problema que a origem do movimento elimina por construção. E o matcher
   **erra**: cada erro numa conta a pagar exige um estorno.

**Efeito colateral bom:** o payout sobe de 6 para 3 porque passa a ser o **mesmo mecanismo** — mais um
evento do sistema virando movimento pelo mesmo `sync_origin_movement`, `source='payout'`. Depois da
Onda 2 ele custa quase nada; antes dela seria um caso especial. Isso é o teste de que a Regra da Origem
é a modelagem certa: transforma três ondas separadas em três entradas de uma tupla.

**A onda de importação continua sujeita ao gate.** A reordenação **não** a antecipa nem a garante — ao
contrário: com a divergência medindo o furo real em vez da ausência de porta, é bastante possível que o
gate diga *"pare"*. O ADR 0003 já chama esse desfecho de **bom, não de fracasso**.

⚠️ **Migrations: o epic NÃO fixa número.** Head no momento desta atualização: **0060**
(`bank_balance_checkpoints`). O @sm/@dev **confirma o head real** no momento da implementação e
encadeia a partir dele.

### Onda 0 — Saldo inicial honesto ✅ EM PRODUÇÃO

Bug independente de tudo. Zero tabela, zero migration.

- `CashProjection` ganha `saldo_inicial_origem` ∈ `{plataforma, banco, misto, indisponivel}` e uma
  `note` explícita — o campo `notes: list[str]` já existe exatamente para isso (`_NOTE_CAIXA`,
  `_NOTE_OVERDUE`), é padrão da casa, não invenção. → design §6.1, REQ-3
- **O runway deixa de ser exibido em dias** quando `origem == "plataforma"`; vira faixa qualitativa ou
  desaparece. → design §6.1
- **Critério de pronto:** nenhum usuário vê runway em dias derivado de saldo cuja origem não está
  declarada na própria tela. → design §6.1

### Onda 1 — Contas, saldo e a conferência de um número ✅ EM PRODUÇÃO

| Item de escopo | Rastreio |
|---|---|
| `bank_accounts` (N contas desde já: `checking`/`savings`/`investment`/`cash`), com `opening_balance_cents` + `opening_date`, `archived_at` em vez de delete, unicidade parcial `(tenant_id, institution_code, branch, number)` | design §2.1; REQ-1; **fundador D2 (várias contas PJ)** |
| `bank_transactions` **só com `source='manual'`** (sem parser nesta onda), `amount_cents` **com sinal**, `posted_at` como `DATE` (não `TIMESTAMP` — evita na origem o bug de fuso que mordeu a Agenda), `raw_description` imutável | design §2.2, §3.3; REQ-1 |
| `bank_balance_checkpoints` — a verdade externa (saldo declarado pelo usuário) | design §2.4; é a "Opção A" da pesquisa absorvida dentro do desenho maior (ADR 0003, alt. A) |
| **Saldo derivado, nunca materializado**: `opening_balance_cents + SUM(amount_cents)` | design §3.1; REQ-2 |
| **Conferência bloco 1**, **por conta** (§3.2): saldo do banco vs. saldo do sistema **na mesma data de referência** — se não há checkpoint na janela, `saldo_banco_origem='indisponivel'` e o relatório **diz isso** em vez de mostrar número falso | design §5.1; R1 do fundador |
| **Banda de tolerância** `max(R$ 50,00, 0,5% do saldo)`, configurável por tenant; dentro da banda → verde e **silêncio** | design §5.1 `[SUPOSIÇÃO do design — D1 não respondida]`; REQ-16 |
| **A frase antes da tabela** — a tela abre com uma linha ("seu saldo no banco está R$ X abaixo do que eu calculei"), não com uma lista | design §5.2 |
| Regra de **completude** no `engine.py` (motor puro) + sinal no `/financeiro/diagnostico`, com precedência semântica sobre margem/runway/rentabilidade | design §5.3 |
| Menu **"Contas & Saldos"** (`/financeiro/contas`). Rota de detalhe `/financeiro/conferencia` **não entra na sidebar** | design §5.4 |
| `projection.saldo_inicial` passa a usar saldo bancário quando existir → `origem="misto"`, com as **duas parcelas rotuladas** ("na plataforma" / "no banco"), nunca só o total | design §6.1; REQ-3, REQ-4 |
| Testes da **Regra dos Planos** (§4.1 deste epic) | design §1.3 |

**Critérios de aceite da onda** (o @sm detalha por story): o usuário cadastra conta com saldo de
abertura e vê o saldo derivado bater com o extrato dele; declara o saldo de hoje e recebe **uma
frase** com a divergência **daquela conta** (ou "está tudo batendo"); divergência dentro da tolerância
→ 🟢 e nenhum alerta; o diagnóstico mostra o sinal de completude com o número e aponta qual conta;
a projeção declara `origem="misto"` com as parcelas separadas; `test_wallet_nao_importa_bank` passa;
RLS e2e cross-tenant no Postgres real passa.

### Onda 2 — A origem do movimento bancário 🟢 LIBERADA (2026-07-30)

> **Fonte de escopo: [`controle-bancario-onda2-design.md`](../architecture/controle-bancario-onda2-design.md)
> inteiro.** Nada aqui é invenção do @pm; o corte em stories (§6) é.
> **Camada aditiva:** colunas nullable, zero backfill sobre dado existente, `source='manual'` continua
> legal, o formulário manual é **curado, não removido**.

| # | Item de escopo | Rastreio |
|---|---|---|
| 2.1 | `bank_transactions.origin_id` + **índice único parcial** `(tenant_id, source, origin_id) WHERE origin_id IS NOT NULL`; `SOURCES` ganha `payable` e `charge`; conjuntos `SOURCES_SISTEMA`/`SOURCES_EXTERNA`; `dedup_hash` de origem de sistema = `sha256(f"{source}|{origin_id}")`, **sem** `bank_account_id` (trocar a conta não reidrata o hash) | design Onda 2 §3.1, §3.2 |
| 2.2 | `payables.bank_account_id` (**a decisão do usuário, autoritativa**) + `payables.bank_transaction_id` (**cache de leitura**) + índice `(tenant_id, bank_account_id)`. `bank_transactions.bank_account_id` é **derivada** e escrita só pelo sincronizador. Divergência entre o cache e o `origin_id` → **quem manda é o `origin_id`**, e a regra de autoridade fica escrita na docstring das duas colunas. ⚠️ **A garantia é TESTE, não script** (`test_cache_de_movimento_nunca_diverge_do_origin_id`, os cinco caminhos de mutação) — `bank_audit` **não existe**, ver a correção no "Contexto do sistema existente" | design Onda 2 §3.3; ratificação §C-4.2 |
| 2.3 | `charges.bank_account_id` + `charges.bank_transaction_id`, sob a **Invariante do Trilho** (§4.9). **Sem** coluna `payment_route` | design Onda 2 §3.4 |
| 2.4 | `bank/origin.py::sync_origin_movement` — **ponto único de escrita**, idempotente, **não commita**; ausente→cria, presente→atualiza, origem desliquidada→apaga. Gate estrutural: `bank` **não** importa `payables`/`receivables` | design Onda 2 §3.5; §4.8 deste epic |
| 2.5 | **`until=None` passa a significar HOJE** em `derived_balance`/`derived_balances_as_of` (fail-closed). `date.max` para histórico completo — feio de propósito. **6 chamadas em `bank/router.py`** a corrigir (`:128,140,153,169,184,202`). `BankBalanceOut.until` para de vir `null` e a tela ganha *"saldo em DD/MM"* de graça | design Onda 2 §4.2.1 |
| 2.6 | **Conta bancária OBRIGATÓRIA em `apply_paid`** (sem default). 3 chamadores mudam: `payables/router.py:108`, `receipts.link_receipt:191`, `receipts.new_bill_from_receipt:218`. Tenant sem conta → **409 acionável** `{"acao": "cadastrar_conta"}` + cadastro embutido na UI | **fundador 2026-07-30**; design Onda 2 §4.1 |
| 2.7 | **`paid_on` editável, default = `due_date`**, sempre visível. Piso: `> opening_date` da conta (422 nomeando as duas saídas). **Sem teto superior** a partir do item 2.8. `competence_date` **não** muda junto — teste `test_alterar_data_de_baixa_nao_altera_dre` | **fundador 2026-07-30** (F-D1); design Onda 2 §4.2, §4.3 |
| 2.8 | **Estado `scheduled` em `payables`**, **derivado da data, nunca escolhido** (`paid_on` futuro ⇒ `scheduled`; hoje/passado ⇒ `paid`). Toca: `ALL_STATUSES` (cabe em `String(12)`, **sem migration de tipo**), `payment_queue` (+balde "Agendadas"), `summary` (+`scheduled_cents`), `reverse_payable` (aceita `scheduled`), `apply_paid` (transição `scheduled→paid`), `receipts.list_candidates`, e **`projection._window_sums`: `status IN ('open','scheduled')` com a data do débito** | **fundador 2026-07-30** (F-D9); design Onda 2 §4.2.2–§4.2.4 |
| 2.9 | **Promoção `scheduled → paid` no worker que já existe** (`app.worker.run_sweep`): +1 varredura. ⚠️ **O saldo não precisa do worker** — o movimento nasce com `posted_at` na data agendada e entra sozinho quando o dia chega, porque saldo é função da data. O worker só move o `status`, para a Fila e o resumo pararem de mostrar como agendado | design Onda 2 §4.2.3 (F-D11) |
| 2.10 | **`PATCH /payables/bills/{id}/payment {bank_account_id?, paid_on?}`** — rota de correção **e de reagendamento** (evento normal, não excepcional). Aceita `paid`e `scheduled`; 409 em conta aberta. **`PayableUpdate` não é tocado** (guarda dupla, mesma disciplina do `update_transaction` do `bank`). Chama o mesmo `sync_origin_movement` | design Onda 2 §4.4 (F-D10) |
| 2.11 | **Estorno apaga o movimento** (DELETE, mesma transação) — não contrapartida (fabricaria crédito que nunca existiu), não `ignored` (é julgamento do dono, e colide com o índice único ao repagar). ⚠️ **Guarda:** o DELETE só vale enquanto a linha for **puramente sintética** (`fitid IS NULL AND import_batch_id IS NULL`); enriquecida, ela **desliga a origem** e vira órfã do extrato — degradação honesta. Trilha de auditoria continua em `audit_entries` | design Onda 2 §4.5 |
| 2.12 | **Guarda do `opening_date`:** recuar a data passa a **exigir `opening_balance_cents` no mesmo PATCH** (422 se ausente). É o gêmeo do BANK-001 pela porta oposta, e fica **muito mais provável** a partir desta onda. +2 testes (recuo com saldo → 200; sem saldo → 422) | design Onda 2 §4.3 |
| 2.13 | **Aviso pró-ativo no cadastro da conta:** *"você tem N contas pagas entre DD/MM e ontem; se esta conta abrir hoje, elas não entram no extrato do e1p"*. O e1p **não inventa** o saldo — ele diz **qual número ir buscar** no app do banco. É "sistema integrado" aplicado a um dado externo sem violar a Regra 5 | design Onda 2 §1.2(c) |
| 2.14 | **A bandeja de comprovantes vira o afluente principal, de graça.** `link_receipt`/`new_bill_from_receipt` ganham `bank_account_id` (obrigatório quando `mark_paid=True`) e `paid_on`. Share sheet do Android + Atalho do iOS passam a alimentar o razão bancário **sem uma linha de tela nova**. ⚠️ O seletor de conta fica **dentro da mesma barra fixa** do botão (lição dos PRs #56 e #58) | design Onda 2 §4.6; REQ-12 |
| 2.15 | **Porta de recebimento fora do trilho:** `POST /receivables/charges/{id}/settle-externally {bank_account_id, received_on?}` → `receivables/service.py::settle_off_rail`. **Nunca** chama wallet, **nunca** cria `Transaction` nem `PlatformEarning`; gera `bank_transaction` de **crédito**. Hoje **não existe caminho nenhum** para isso (o botão "Marcar paga" foi removido de propósito), e a cobrança paga por fora fica em aberto para sempre com a régua mandando lembrete a quem já pagou | design Onda 2 §5.1, §5.2 |
| 2.16 | **As 5 defesas testáveis** contra os planos se confundirem: invariante do trilho; **espião** em `wallet_service.build_transaction`; contagem de `PlatformEarning` antes/depois; `mark_paid` pós-`settle_off_rail` é **no-op** (hoje o silêncio vem por acidente — precisa de teste explícito); `settle_off_rail` **409** em cobrança com `transaction_id` | design Onda 2 §5.3 |
| 2.17 | `PATCH /receivables/charges/{id}/payment` — simétrica à 2.10, restrita a cobranças fora do trilho | design Onda 2 §5.4 |
| 2.18 | **Sinal 🟡 de recebimento fora do trilho** no `/financeiro/diagnostico`: **um por relatório**, só quando houve na janela, tom operacional sobre o interesse **do dono** (*"não geram boleto, lembrete automático nem baixa sozinha"*), **nada sobre split**. `engine.py` continua **puro** (o dado chega montado de fora). **Neutro ao dono, nunca reportado ao Master** — com a **proibição normativa** da §2.1 e o teste `test_admin_nao_expoe_recebimento_fora_do_trilho` | design Onda 2 §6; G-D7 |
| 2.19 | **Desambiguação do `divergencia > 0`:** se há `payables` em `scheduled` com data já vencida, o Diagnóstico **nomeia o suspeito** (*"o débito de R$ X agendado para DD/MM pode não ter saído"*) em vez de só apresentar o número. Compara **ordem de grandeza**, não igualdade; diz *"pode não ter saído"*, nunca *"não saiu"*. Sem ela, vira mais um número — e número sem pista treina o dono a ignorar a tela | design Onda 2 §9.2.1 |
| 2.20 | **Nota do gate no bloco 4 da conferência** (*"N lançamentos não informam de qual conta saíram (R$ X). A divergência abaixo inclui esse valor."*). ⚠️ **ANOTA, NUNCA SUBTRAI** (§3.1.2) | design Onda 2 §9.3 |
| 2.21 | **Manual curado:** o formulário deixa de ser "Novo movimento" e pergunta **para que serve** — `Tarifa / juros`, `IOF / imposto`, `Transferência entre minhas contas`, `Rendimento`, `Outro (descreva)` — alimentando `operation_nature`, coluna que **já existe**, nullable, vocabulário aberto. **Zero migration.** Não é whitelist rígida: recusar um fato bancário legítimo recriaria a incompletude que a onda combate | **fundador 2026-07-30**; design Onda 2 §7(a) |
| 2.22 | **Guarda de contagem dupla:** `create_transaction` com `source='manual'` e `amount_cents < 0` procura `Payable` de **mesmo valor absoluto** em **±3 dias** → **409 com escolha** (`{"acao": "baixar_payable", "payable_id": ...}`), não bloqueio mudo; `confirmar_avulso=true` insiste. **É o pior modo de falha desta onda**: o pagamento lançado nos dois lugares derruba o saldo duas vezes e a divergência dobrada **parece um achado real**. Movimento manual negativo **continua legal** (tarifa, IOF, TED — criar `payable` de R$ 2,90 é a ERP-ificação que o produto recusa). Janela ±3 dias e valor exato: `[SUPOSIÇÃO do design, parametrizável]`, deliberadamente o **mesmo número** do enriquecimento (design-mãe §4.5) | design Onda 2 §7(b) |
| 2.23 | **`source='manual'` já existente:** **nada automático, nenhuma migration, nenhuma reclassificação.** Uma linha manual é a afirmação do usuário; reescrevê-la é a tradução silenciosa que a lição D-3 proíbe. A conferência **anota** ("pode ser a mesma despesa da conta X") a partir da Onda 4. Informativo, nunca corretivo | design Onda 2 §7(c) |
| 2.24 | **`bank_transfers` genérica** — duas pernas, `kind ∈ {own_transfer, investment_in, investment_out}`, **zero acoplamento com `investments`**, DRE-neutro por construção (§4.2). Usa o mesmo `sync_origin_movement` (`source='transfer'`). ⚠️ **Forma canônica das pernas (ratificada, §C-3.1):** `origin_id = f"{transfer.id}:out"` e `f"{transfer.id}:in"`, **pareadas por `transfer_id`** (coluna que **já existe**, `bank/models.py:278`), `dedup_hash = sha256(f"{source}\|{origin_id}")` distinto por perna de graça, coluna **`VARCHAR(64)`**. **NÃO é "duas linhas com o mesmo `origin_id`"** — essa forma foi **rejeitada**: destrói a idempotência na origem onde ela mais importa (um retry de transferência move o dinheiro duas vezes). `origin_id` é a **chave de origem**, não "o id do lançamento": para origem de perna única (`payable`, `charge`, `yield`, `payout`) ela **é** o id; para origem de múltiplas pernas é `f"{id}:{perna}"`. A unidade de sincronização de uma transferência é **a perna**. O 422 de `posted_at` futuro mora em `create_transfer`, **antes** das duas chamadas ao sincronizador — nunca dentro de `_validate_posted_at`, que a partir da 8.14 **aceita** futuro para `SOURCES_SISTEMA` (achado A-3). Transferir para uma `bank_account` com `kind='investment'` **já funciona** desde a Onda 1 | design Onda 2 §8; ratificação §C-3 |
| 2.25 | **Tela 8.7 ganha um terceiro número: "Agendado para sair"** (e "Agendado para entrar", quando houver). Sem ele o dono agenda um pagamento e não o vê em lugar nenhum. ⚠️ Passa pelos **mesmos testes de colisão de rótulo** que o UX-001 instituiu: não pode ser, nem conter, `ROTULO_BANCO`, `TOTAL_EM_CONTAS_LABEL` nem `DISPONIVEL_CAIXA_LABEL` | design Onda 2 §4.2.1 |

**O que a Onda 2 explicitamente NÃO faz:** nenhum parser de arquivo; nenhum matcher; nenhuma tabela
`bank_reconciliations`; nenhum toque em `investments` (é a 2b); nenhum backfill automático das 45
contas — **o backfill é manual, por decisão do fundador** (§9.1, F8); nenhuma remoção do formulário
manual; nenhuma superfície de plataforma sobre recebimento fora do trilho.

**Critérios de aceite da onda** (o @sm detalha por story): o dono dá baixa numa conta a pagar, informa
a conta, e o movimento aparece no razão **na mesma transação**; estorna, e o movimento **some**; troca
a conta, e o movimento **move** (não duplica); agenda para o dia 15 e o valor aparece em "Agendado para
sair" **sem** entrar no "Total em contas" e **sem** sumir da Projeção; registra um recebimento fora do
trilho e **nenhum** `PlatformEarning` é criado; tenta lançar manualmente um pagamento que já tem conta
a pagar e recebe **409 com escolha**; recua o `opening_date` sem informar o saldo e recebe **422**;
`test_bank_nao_importa_payables` passa; RLS e2e cross-tenant no Postgres real passa; **aceite manual em
~360px** (G-4, §9.2).

### Onda 2b — Aplicação como conta, `principal_cents` derivado 📋 PLANEJADA (não liberada)

`investment_accounts.bank_account_id` (faceta de produto 1:1, `investment_accounts` **não** é
absorvida); migração de dados de `principal_cents` → derivado; `update_account` rejeita (409) editar
`principal_cents`; `register_yield` passa a gerar também um `bank_transaction` `source='yield'`
**nascido conciliado**, pelo **mesmo** `sync_origin_movement` — reafirmando a garantia IV1 da Story 5.6
(nunca chama `mark_paid`/`build_transaction`); extrato da aplicação no `InvestimentosPage`.
→ design-mãe §2.6, §3.2, §3.4, §6.2, §6.3; design Onda 2 §8; REQ-20..REQ-26; **R3 do fundador**.

⚠️ **Contém o único backfill sobre dado existente de todo o épico** — exposto à armadilha do
`FORCE ROW LEVEL SECURITY` da migration 0046 (`UPDATE` sem a GUC é filtrado a zero linhas, **em
silêncio**, e o SQLite dos testes **não pega**). É o item de maior risco do épico inteiro. Por isso foi
**separado da Onda 2**: acoplar os dois adiaria o urgente (45 contas, saldo R$ 0,00) pelo arriscado.

### Onda 3 — Payout da Carteira fecha o circuito 📋 PLANEJADA (não liberada)

> **Era a Onda 6.** Subiu porque, depois da Onda 2, é **o mesmo mecanismo**: mais um evento do sistema
> virando movimento pelo mesmo `sync_origin_movement`, `source='payout'`.

`request_payout` emite evento via `core/events` (mantendo `wallet` sem importar `bank`) → o módulo
`bank` cria o crédito na conta primária; card do Cockpit com as duas parcelas rotuladas; **graceful
degradation** sem conta cadastrada (nada acontece, nada quebra).
→ design-mãe §1.2, §6.5, §6.6. **Dependência D7** (payout real exige dados bancários + KYC) permanece:
o default continua sendo **registro contábil, sem transferência real**.

### Onda 4 — Importação de extrato (parser plugável, sem match automático) 📋 PLANEJADA

`bank_import_batches`; `StatementParser` como strategy + `OfxSgmlParser` + `OfxXmlParser` +
`CsvParser`; dedup por `dedup_hash` com constraint única (fail-closed); enriquecimento antes de
inserir (evita dupla contagem transferência × extrato); checkpoint a partir do `<LEDGERBAL>`;
**conferência blocos 2 e 3** (movimentos órfãos e lançamentos sem extrato); ações manuais por linha.
→ design-mãe §2.5, §4.1–§4.5, §5.1; REQ-5..REQ-12.
**É a onda cara, e o custo é permanente** (parser por banco é manutenção perpétua — ADR 0003,
Consequência 1). **Sujeita ao gate do §3.1** e a uma verificação empírica prévia (§8, dependência
**D6**).

⚠️ **`POST /bank/accounts/{id}/imports` fica REVOGADO como porta primária** (fecha o conflito C3 em
favor do REQ-12, §11.4). Se esta onda for liberada, o arquivo entra pela **infraestrutura de
anexo/bandeja que já existe** (`owner_type='bank_import'`), com a conta escolhida **depois** do upload.
A rota dedicada sobrevive como caminho de desktop, não como **o** caminho. → design Onda 2 §1.2(a).

### Onda 5 — Sugestão de vínculo (regra → IA) e baixa de Contas a Pagar 📋 PLANEJADA

> **Era a Onda 4.**

`bank_reconciliations` como **tabela de ligação** (suporta N:N: um Pix quitando duas contas; uma conta
paga em dois movimentos); matcher determinístico primeiro, IA classificando/ranqueando depois **sob
anonimizador**; `confirmed_at=NULL` = sugestão; baixa de `Payable` só após confirmação do usuário.
→ design-mãe §2.3, §4.6, §4.7; REQ-14, REQ-15, REQ-18, REQ-19. **Sujeita ao gate do §3.1.**

⚠️ **A Onda 2 reduz o trabalho desta onda, e isso é deliberado:** todo movimento originado pelo sistema
**nasce conciliado** e não passa pelo matcher. O que sobra para o matcher é o **resíduo** — exatamente o
que o §4.8(e) diz que manual e importação existem para cobrir.

### Onda 6 — Baixa de Contas a Receber a partir do extrato 🚫 BLOQUEADA

> **Pré-requisito absoluto e nomeado:** existir o vínculo **`platform_earnings → transaction`**
> (migration + ajuste do ledger global do Master), reabilitando o estorno de `Charge`.
> **Enquanto isso não existir, esta onda não começa.**

**Decisão do fundador (2026-07-29): a dívida NÃO será paga agora.** Logo a Onda 6 fica **fora da
fila** deste epic (responde D4 do design com "não").

**Por que o bloqueio é duro:** o estorno de Contas a Receber foi implementado, revisado em duas
rodadas e **removido antes do merge** porque `platform_earnings` não guarda vínculo de volta à
`Transaction`/`Charge` de origem — pagar → estornar → pagar de novo duplicaria o GMV no painel do
Master (`docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md`, Adendo; `CLAUDE.md`). Um
matcher **vai** produzir baixas indevidas (é estatística, não pessimismo) e hoje **não existe caminho
seguro de desfazer**. → REQ-17; design §4.7; ADR 0003, Consequência 6.

**Isto não bloqueia o lado do pagar**, que é o objetivo declarado: `Payable` nunca move a Carteira e
já tem `POST /payables/bills/{id}/reverse` (REQ-14, REQ-17 nota). E o que entrega quase todo o valor
**é permitido antes**, dentro da Onda 5: vínculo **informativo** movimento ↔ cobrança já paga (não
muda status, não move dinheiro) e **sinalização** do tipo *"esta cobrança está em aberto há 47 dias e
existe um crédito de mesmo valor no extrato"* — o dono decide o que fazer (design-mãe §4.7).

⚠️ **A Onda 2 NÃO fura este bloqueio, e a distinção precisa ficar escrita.** O
`settle-externally` (item 2.15) é o **dono declarando** que recebeu direto na conta dele; ele **nunca**
cria `Transaction` nem `PlatformEarning`, logo a dívida `platform_earnings → transaction` **não o
alcança**. A Onda 6 é sobre **baixa automática a partir do extrato**, de cobranças **do trilho** — outra
coisa. Desfazer um recebimento fora do trilho também seria seguro pela mesma razão (design Onda 2 §5.4,
F-D4) — **e mesmo assim não está em escopo da Onda 2** (§9.2).

### 5.1 Ponto de parada legítimo — decisão consciente, não escopo automático

> **As Ondas 4 e 5 (importação e match) NÃO são escopo automático deste epic.** O design registra
> explicitamente que, se a divergência medida for **pequena e estável**, elas são **over-engineering e
> devem ser adiadas** (design-mãe §8; ADR 0003, Revisão futura (a) — *"este é um desfecho bom, não um
> fracasso"*).

⚠️ **O ponto de parada mudou de lugar com a renumeração — e o texto anterior desta seção viraria uma
armadilha se ficasse.** Ele dizia *"o ponto de parada natural é depois da Onda 2"*, e "Onda 2"
significava **aplicação/`principal_cents`**. Com a nova numeração, a mesma frase apontaria para um
estado do produto completamente diferente.

**Ponto de parada legítimo, na numeração nova:** `[DECISÃO DO @PM — a confirmar com o fundador, §9.2]`
**depois da Onda 3 (payout)** — que é o fim das ondas de **dependência externa zero**. Nesse estado o
e1p tem: conta bancária de primeira classe, saldo derivado confiável e **cheio** (a Regra da Origem
alimentando o razão a partir de todos os eventos que o sistema conhece), projeção/runway verdadeiros,
agendamento visível, aporte/resgate, recebimento fora do trilho registrável e a conferência de um número
por conta com a **pré-condição do gate satisfeita**. Isso é um produto completo, não um produto pela
metade — é a Alternativa A do ADR 0003, absorvida em vez de descartada, e agora **com afluentes**.

**Este epic proíbe tratar 4 e 5 como consequência inevitável de 1, 2 e 3.** Só o número da §3.1, lido
sob a pré-condição da §3.1.2 e com o fundador decidindo, libera a importação. Registrar isto aqui é o
mecanismo que impede o escopo de crescer por inércia — e a §3.1.1 é a prova de que o mecanismo **quase
falhou** por medir a coisa errada.

---

## 6. Stories previstas

> **Só nomeadas e delimitadas.** Escrever a story completa (As a / I want / so that, Acceptance
> Criteria, Integration Verification, tasks) é do **@sm** via `create-next-story.md`.
> A decomposição em stories é `[DECOMPOSIÇÃO DO @PM]` — os **itens de escopo** vêm do design §8; o
> corte entre stories não. O @sm/@po pode reagrupar, desde que nenhum item da §5 caia fora.
> Ordem = ordem de dependência.

### Onda 0 ✅ EM PRODUÇÃO

**Story 8.1 — Saldo inicial honesto na Projeção de Caixa (origem declarada + runway suprimido)**
`CashProjection` passa a expor `saldo_inicial_origem` + `note` explícita, e a UI deixa de exibir
runway **em dias** enquanto a origem for `"plataforma"`.
*Não inclui:* nenhuma tabela nova, nenhuma migration, nenhuma mudança na fórmula da projeção além do
rótulo de origem e da supressão do runway. → design §6.1; REQ-3

### Onda 1 ✅ EM PRODUÇÃO

**Story 8.2 — Fundação `bank_accounts` + saldo derivado + Regra dos Planos como teste estrutural**
Tabela `bank_accounts` com RLS `FORCE` (migration 0058), CRUD por tenant (N contas, `archived_at` em
vez de delete, saldo de abertura + data), função de saldo derivado, e os testes estruturais que
impedem os planos de se misturarem de novo (`wallet` não importa `bank`, saldo bancário ignora
`transactions` e vice-versa).
*Não inclui:* movimentos, checkpoints, conferência, tela. → design §1.3, §2.1, §3.1; REQ-1, REQ-2

**Story 8.3 — Movimento bancário manual (`bank_transactions` com `source='manual'`)**
Lançar/editar/ignorar movimento à mão na conta, com `amount_cents` **assinado**, `posted_at` como
`DATE`, `raw_description` imutável e `user_description` editável — o saldo derivado se move a partir
disso.
*Não inclui:* importação de arquivo, dedup por `fitid`/`dedup_hash`, vínculo de conciliação,
enriquecimento, contraparte extraída por IA. → design §2.2, §3.3

**Story 8.4 — Checkpoint de saldo declarado (`bank_balance_checkpoints`)**
O usuário informa "o saldo desta conta no fim deste dia era X" (`origin='manual'`), que é a verdade
externa contra a qual a conferência compara.
*Não inclui:* `origin='ofx'` (vem com a onda de importação — **Onda 4** na numeração nova); histórico/
gráfico de saldo. → design §2.4

**Story 8.5 — Conferência bloco 1: a divergência em uma frase, por conta**
Serviço **read-only** que compara `saldo_banco` (checkpoint) × `saldo_sistema` (derivado) **na mesma
data de referência**, aplica a banda de tolerância `max(R$ 50, 0,5%)` configurável e devolve a
divergência **por conta** — recusando-se a comparar datas diferentes e declarando
`origem='indisponivel'` quando não há checkpoint na janela.
*Não inclui:* blocos 2 e 3 (órfãos dos dois lados, que dependem de conciliação — **Onda 4/5** na
numeração nova); a **nota do bloco 4** sobre lançamentos sem conta informada (Onda 2, Story 8.16); consolidado
sem decomposição por conta é **proibido** (§3.2). → design §5.1, §5.2; §3.2 deste epic; REQ-16

**Story 8.6 — Regra de completude no motor de diagnóstico + sinal no `/financeiro/diagnostico`**
`CompletenessInput` e a regra 🟢🟡🔴 no `engine.py` (puro, sem I/O), alimentada pelo serviço da 8.5 via
`diagnostics.py`, com **precedência semântica** sobre os demais sinais e indicação de **qual conta**
está fora da banda.
*Não inclui:* narrativa nova por IA além do padrão já existente da Story 5.8; nenhuma escrita.
→ design §5.3

**Story 8.7 — Tela "Contas & Saldos" + rota de conferência fora da sidebar**
Menu novo `/financeiro/contas` (cadastro de conta, saldo por conta, declarar saldo, lançar movimento)
e a rota de detalhe `/financeiro/conferencia`, alcançada **a partir do sinal de diagnóstico e da tela
de contas** — a frase antes da tabela.
*Não inclui:* item de menu "Conciliação bancária" (proibido); upload de extrato; tela de match linha a
linha. → design §5.2, §5.4

**Story 8.8 — Projeção de Caixa passa a usar o saldo bancário (`origem="misto"`, parcelas rotuladas)**
Com conta bancária ativa, o saldo inicial da projeção passa a ser saldo bancário derivado +
`available_cents` da Carteira, com `origem="misto"` e a UI exibindo **as duas parcelas separadas** —
somar sim, esconder a composição nunca.
*Não inclui:* remover o comportamento da 8.1 (permanece como fallback quando não há conta cadastrada).
→ design §6.1, §1.2; REQ-3, REQ-4

**Onda 0 + Onda 1: 8 stories (8.1–8.8), todas ✅ em produção** (PR #61, `7dba286`).

### Onda 2 — a origem do movimento (12 stories, 8.9–8.20)

> **Só nomeadas e delimitadas.** A story completa é do **@sm**.
> O corte é `[DECOMPOSIÇÃO DO @PM]`; os **itens de escopo** vêm do design da Onda 2 e estão numerados
> na §5 (2.1–2.25). **Nenhum item da §5 pode cair fora do conjunto de stories** — se o @sm/@po
> reagrupar, precisa recontar os 25 itens.
>
> ⚠️ **8.19 e 8.20 são de natureza diferente das 10 primeiras, e por isso NÃO consomem item da §5.**
> As 8.9–8.18 constroem a Onda 2; as 8.19 e 8.20 **corrigem comportamento das Ondas 0/1 que já está em
> produção** e que foi achado durante a expansão da onda em stories. Os **25 itens seguem cobertos
> pelas 8.9–8.18** — a recontagem continua batendo. Elas entram aqui, e não numa onda futura, porque
> as duas tocam a **leitura da conferência**, que é a métrica primária do épico.
> **Critério de corte usado:** (i) cada story cabe numa sessão de implementação; (ii) a ordem de merge
> é a ordem de dependência, sem "story que precisa da seguinte para não deixar dado ruim no banco";
> (iii) migration e backend de contrato vêm **antes** de qualquer chamador; (iv) frontend de superfície
> crítica em ~360px vira story própria, porque **dois PRs de fix de campo já foram pagos** por elemento
> fora da área visível (PRs #56 e #58).

**Story 8.9 — Fundação da Regra da Origem (`sync_origin_movement` + migration aditiva)**
Migration aditiva com `bank_transactions.origin_id` + índice único parcial, `payables.bank_account_id`
/ `bank_transaction_id` + índice, `charges.bank_account_id` / `bank_transaction_id`; `SOURCES` ganha
`payable` e `charge`; conjuntos `SOURCES_SISTEMA`/`SOURCES_EXTERNA`; `bank/origin.py::sync_origin_movement`
(idempotente, não commita); Invariante da Origem testada nas duas direções; gate estrutural novo
(`bank` não importa `payables`/`receivables`). **Nenhum chamador ainda** — a story entrega o contrato,
não o comportamento. → itens 2.1–2.4
*Não inclui:* qualquer mudança em `apply_paid`, em `charges` ou em tela.

**Story 8.10 — Corte de data: `until=None` passa a significar hoje nas superfícies de saldo**
`derived_balance` e `derived_balances_as_of` mudam o **significado do default** (não a assinatura),
fail-closed; as 6 chamadas de `bank/router.py` passam a receber "hoje"; `date.max` explícito para
histórico completo; `BankBalanceOut.until` para de vir `null`. **Pré-requisito de qualquer coisa com
data futura** — sem ela, um agendamento entra no "Total em contas". → item 2.5
*Não inclui:* estado `scheduled`, data de baixa editável, nenhum rótulo novo de tela.

**Story 8.11 — Guarda do `opening_date` + aviso pró-ativo no cadastro da conta**
Recuar `opening_date` passa a exigir `opening_balance_cents` no mesmo PATCH (422 com mensagem nomeando
as duas datas); aviso no cadastro contando as contas pagas anteriores à abertura e dizendo **qual
número ir buscar** no app do banco. **É o passo 1 do alerta operacional (§7.1)** — precisa estar em
produção antes de o fundador começar o mutirão das 45. → itens 2.12, 2.13
*Não inclui:* derivar o saldo de abertura (proibido — é a Regra 5); mexer em `_validate_posted_at`.

**Story 8.12 — Baixa de Contas a Pagar gera o movimento (conta obrigatória, data editável, estorno apaga)**
`apply_paid` ganha `bank_account_id` **obrigatório** e `paid_on` com default `due_date`; os 3
chamadores mudam; 409 acionável `{"acao":"cadastrar_conta"}`; 422 contra `opening_date`; estorno
**apaga** o movimento com a guarda de linha puramente sintética; `PATCH /payables/bills/{id}/payment`.
⚠️ **Nesta story `paid_on` tem teto em hoje** — o teto sai na 8.14, junto com `scheduled`. `[CORTE DO
@PM]`: é o que garante que **nunca exista `paid` com data futura no banco**, que é a armadilha nomeada
no design (§4.2.4). Não contradiz o design; implementa a mecânica dele. → itens 2.6, 2.7 (parcial),
2.10, 2.11
*Não inclui:* `scheduled`; a bandeja de comprovantes (8.13); cobranças (8.15).

**Story 8.13 — As telas da baixa: seletor de conta e data, do desktop ao 360px**
`PagarPage` (seletor de conta + campo de data com default no vencimento + fluxo do 409 com cadastro
embutido) e a **bandeja de comprovantes** (`link_receipt`/`new_bill_from_receipt` ganham
`bank_account_id`/`paid_on`; conta primária **pré-selecionada e visível no próprio botão**, com troca a
um toque). ⚠️ **O seletor fica DENTRO da mesma barra fixa do botão** — fisicamente inseparável da ação
que o torna efetivo. **Aceite manual em ~360px é bloqueante desta story.** → item 2.14, superfície de
2.6/2.7
*Não inclui:* backend novo (veio na 8.12); "Agendado para sair" (8.14).

**Story 8.14 — Estado `scheduled`: agendar pagamento sem mentir na Projeção**
`ALL_STATUSES` +1 (cabe em `String(12)`); estado **derivado da data**, invariante
`scheduled ⟺ paid_at.date() > hoje` no momento da escrita; teto de `paid_on` removido; `payment_queue`
ganha o balde "Agendadas"; `summary.scheduled_cents`; `reverse_payable` aceita `scheduled`;
`receipts.list_candidates`; **`projection._window_sums`: `status IN ('open','scheduled')` com a data do
débito**; promoção `scheduled → paid` no `app.worker.run_sweep`; **"Agendado para sair" como terceiro
número** na tela de Contas & Saldos, sob os testes de colisão de rótulo do UX-001.
⚠️ É a story mais delicada da onda: sem `_window_sums`, o dinheiro agendado **some da Projeção** — a
máquina de falso negativo da Onda 0 ressuscitada. → itens 2.7 (teto), 2.8, 2.9, 2.25
*Não inclui:* agendamento de recebimento fora do trilho (herda a regra na 8.15); DRE (impacto zero,
verificado).

**Story 8.15 — Recebimento fora do trilho (`settle_off_rail`) e a Invariante do Trilho**
`POST /receivables/charges/{id}/settle-externally` + `settle_off_rail` (nunca toca wallet, nunca cria
`Transaction`/`PlatformEarning`, `FOR UPDATE`, evento da Agenda para `done`); Invariante do Trilho
como teste que varre todas as charges pagas; as **5 defesas testáveis**; `PATCH /receivables/charges/{id}/payment`;
a porta na UI de Cobranças e na Ficha 360°. `received_on` futuro ⇒ `scheduled`, pela regra da 8.14; o
caminho do **gateway** mantém `paid_at = now()` e **não é editável** (fato externo atestado por
terceiro). → itens 2.15, 2.16, 2.17
*Não inclui:* o sinal do Diagnóstico (8.16); **desfazer** recebimento fora do trilho (F-D4, §9.2);
qualquer superfície de plataforma sobre a coluna (proibido, §2.1).

**Story 8.16 — Diagnóstico e conferência aprendem a Onda 2**
Três regras, todas no motor **puro** (o dado chega montado de fora, como a completude): (a) sinal 🟡 de
recebimento fora do trilho, **um por relatório**, com o tom operacional e a **proibição normativa** +
`test_admin_nao_expoe_recebimento_fora_do_trilho`; (b) desambiguação do `divergencia > 0` nomeando o
agendamento vencido suspeito, por ordem de grandeza e com *"pode não ter saído"*; (c) **nota do gate**
no bloco 4 da conferência — *anota, nunca subtrai*. → itens 2.18, 2.19, 2.20
*Não inclui:* SIG-001 (a virada de mês apagando conferência recente) — **story própria, fora desta
onda**, com decisão de arquitetura já registrada (§9.2, item 5).

**Story 8.17 — Manual curado + a guarda que impede a contagem dupla**
Formulário manual deixa de ser "Novo movimento" e passa a perguntar **para que serve** (lista curta →
`operation_nature`, coluna que já existe, **zero migration**); validação estreita em `create_transaction`
(`source='manual'`, `amount_cents < 0`, mesmo valor absoluto em ±3 dias) → **409 com escolha**, com
`confirmar_avulso=true` para insistir. Movimento manual negativo **continua legal**. → itens 2.21, 2.22,
2.23
*Não inclui:* whitelist rígida de categorias (rejeitada); reclassificar `source='manual'` já existente
(proibido).

**Story 8.18 — Transferência entre contas próprias (`bank_transfers`)**
Migration própria; **duas pernas com `origin_id` `:out`/`:in`, pareadas por `transfer_id`** (a forma
canônica ratificada — **não** "o mesmo `origin_id` nas duas", que quebra a idempotência num retry);
`kind ∈ {own_transfer, investment_in, investment_out}`; **zero acoplamento com `investments`**;
`test_transferencia_nao_altera_dre` (snapshot idêntico campo a campo); 422 de `posted_at` futuro **em
`create_transfer`**, não em `_validate_posted_at` (A-3); UI de transferência. Transferir para conta
`kind='investment'` já funciona — a faceta de produto é a 2b. → item 2.24; ratificação §C-3
*Não inclui:* `investment_accounts.bank_account_id`, `principal_cents` derivado, `register_yield` (tudo
Onda 2b — é lá que mora o backfill).

**Story 8.19 — O saldo de abertura é uma declaração (âncora quando não há checkpoint)**
A Conferência para de dizer *"esta conta nunca teve saldo informado"* a quem informou o saldo **no
cadastro da conta**: `dias_desde_ultima_conferencia` cai para `opening_date` quando
`latest_checkpoint(on_or_before=end)` devolve `None`, e a nota do bloco 4 passa a dizer as duas coisas
separadas — (a) existe um saldo de partida, informado por você em `{opening_date}`; (b) **dentro deste
período** não houve saldo novo informado, então não há verdade externa para comparar. Como
`opening_date` é `NOT NULL`, o campo **nunca mais volta `None`** — é mudança de contrato, e a story a
declara. Read-only, **sem migration**.
⚠️ **Escopo reduzido na v0.2 (@po):** a v0.1 dizia que a Projeção estava afirmando sem lastro em
produção — **premissa refutada pelo fundador** (o saldo R$ 0,00 da C6 é real e consciente). Esta story
**não toca `projection.py`**, e a Projeção **não** é regressão a corrigir.
*Não inclui:* a comparação degenerada (saiu para a 8.20); o modo *"tenho a conta e NÃO sei o saldo"*
(exige migration — escalado, fora da onda). → **não consome item da §5**; corrige comportamento das
Ondas 0/1

**Story 8.20 — A comparação degenerada: checkpoint na data de abertura não é conferência**
`derived_balance(until=opening_date) ≡ opening_balance_cents` por construção (`_movements_sums` só soma
`posted_at > opening_date`) e `_validate_reference_date` **aceita** `reference_date == opening_date` —
então declarar o saldo no dia da abertura produz `divergencia_cents == 0` **por construção matemática**,
satisfaz `todas_batendo` e pode emitir o 🟢 *"Está tudo batendo"* para um tenant com 45 contas pagas e
razão bancário vazio. **É um 🟢 falso**, da mesma família do erro da §3.1.1: um número que mede a
própria incompletude com aparência de fato.
Tratamento (recomendação do @po, decisão final da @architect como co-requisito): **marcar
não-avaliável no bloco 1, mantendo a contagem no bloco 4** — a declaração é legítima (*"o saldo da
conta no dia em que ela abriu"* é verdade), **o que é degenerado é a comparação**; recusá-la com 422
apagaria uma afirmação verdadeira, que é o inverso do princípio da Onda 0. Junto, no mesmo commit: a
**docstring invertida** de `_validate_reference_date` (ela é o motivo de o defeito ter sobrevivido a 36
testes — quem foi escrever o teste leu que o caso era *"o mais sadio que existe"*) e o **primeiro teste
do cenário**. Read-only, **sem migration**.
*Não inclui:* 422 na criação do checkpoint (rejeitado); "aceitar e apenas anotar" (rejeitado — mantém o
🟢 possível). → **não consome item da §5**; especificação preservada no AC3 da 8.19

**Story 8.21 — "Tenho a conta e NÃO sei o saldo": o modelo registra o ATO, não só o VALOR**
`opening_balance_cents` é `NOT NULL DEFAULT 0` e o formulário pré-preenchia `"0,00"` — então
*"informei zero"* e *"não informei nada"* eram **a mesma linha**, e a Projeção afirmava runway sobre um
saldo que ninguém informou. Coluna irmã `opening_balance_is_known` (migration `0074`, **sem backfill**:
`ADD COLUMN` é DDL e a RLS não o alcança). **`ORIGEM_INDISPONIVEL` existia desde a Onda 0 sem gatilho —
esta story é o gatilho.** Basta **uma** conta elegível desconhecida para calar runway e alerta, porque
`opening_balance_cents` pode ser **negativo** (cheque especial) e somar só as conhecidas erraria nas
duas direções sem nada dizer em qual. O número continua visível e a nota **nomeia quais contas faltam**.
*Não inclui:* materializar o saldo de abertura como checkpoint (rejeitado pela 8.19); tornar
`opening_balance_cents` anulável (rejeitado pela @architect — quebraria a guarda da 8.11, cujo
mecanismo é *"`None` = campo ausente"*). → **não consome item da §5**; fecha o §Escalado 2 da 8.19

**Total da Onda 2: 13 stories (8.9–8.21)** — 10 que constroem a onda (8.9–8.18, cobrindo os 25 itens da
§5) + 3 que corrigem comportamento das Ondas 0/1 achado durante a expansão (8.19, 8.20, 8.21).

#### 6.1 Ordem de merge da Onda 2

```
8.9 ──► 8.12 ──► 8.13 ──► 8.14 ──► 8.15 ──► [8.20] ──► 8.16
 │                          ▲
8.10 ─────────────────────┘        8.17 (independente, após 8.9)
8.11 (independente — merge cedo)   8.18 (independente, após 8.9)
8.19 (independente de tudo — não entra na frente de ninguém)
8.21 (independente — depende só da 8.19 ter fechado o escalado dela)
```

| Ordem | Story | Por quê nesta posição |
|---|---|---|
| 1 | **8.11** | Não depende de nada e **destrava o passo 1 do mutirão** (§7.1). Pode ir primeiro, inclusive antes da 8.9 |
| 2 | **8.9** | Contrato antes de chamador. Sem ela, nada da onda existe |
| 3 | **8.10** | Independe da 8.9, mas **tem de estar antes da 8.14** — senão o agendamento entra no saldo corrente |
| 4 | **8.12** | Primeiro chamador do `sync_origin_movement`. **Já entrega valor sozinha:** o mutirão das 45 funciona só com ela |
| 5 | **8.13** | Superfície da 8.12. Separada porque o aceite em 360px é bloqueante e merece atenção isolada |
| 6 | **8.14** | Precisa de 8.10 (corte de data) e de 8.12 (baixa com data). Remove o teto que a 8.12 pôs |
| 7 | **8.15** | Precisa da 8.9; herda `scheduled` da 8.14 para `received_on` futuro |
| 8 | **8.20** | **Não depende de nenhuma das 8.9–8.18** (corrige comportamento das Ondas 0/1), mas **tem de mergear ANTES da 8.16**. Razão: a 8.16 consome o **bloco 1** para o sinal de completude; com a comparação degenerada de pé, o épico ganha um caminho para se **auto-aprovar** — emitir 🟢 no mesmo ciclo em que a nota do bloco 4 diria que o gate ainda não pode ser lido. **Também bloqueia o passo 1 do mutirão** (§7.2): o fundador foi instruído a não declarar saldo até isto resolver |
| 9 | **8.16** | Precisa de 8.14 (débito não confirmado), 8.15 (recebimento fora do trilho) **e 8.20** (bloco 1 confiável) — é a leitura das três |
| 10 | **8.17** | Só precisa da 8.9. Pode correr em paralelo a partir daí. ⚠️ **Quanto mais tarde, mais tempo a janela de contagem dupla fica aberta** |
| 11 | **8.18** | Só precisa da 8.9. Tem migration própria — merge por último evita conflito de head com a 8.9 |
| — | **8.19** | **Não entra na frente de ninguém, e ninguém a espera.** Independe das 8.9–8.18 e não é pré-requisito de nenhuma delas. Entra quando houver folga. ⚠️ Seis stories chegaram a dizer que ela vinha primeiro — premissa da v0.1, **corrigida pelo @po nas seis** |

**Paralelizável com segurança:** {8.11}, {8.10}, {8.17, 8.18 após 8.9}, {8.19, a qualquer momento},
{8.20, a qualquer momento **antes da 8.16**}. **Serial obrigatório:** 8.9 → 8.12 → 8.13, e
8.10+8.12 → 8.14 → 8.16, e **8.20 → 8.16**.

⚠️ **A 8.19 e a 8.20 são independentes ENTRE SI**, apesar de a especificação da 8.20 ter nascido dentro
da 8.19 (AC3). Foram separadas porque são **classes de risco diferentes**: a 8.19 é leitura e texto com
o bloco 1 **inalterado**; a 8.20 **muda o comportamento do bloco 1 de um relatório em produção**. Fundir
as duas num diff só tira do gate a capacidade de julgar qual mudança quebrou o quê — é o mesmo argumento
que mantém o SIG-001 fora da 8.16. → validação do @po §5

### Onda 2b em diante — stories não delimitadas

**Deliberado.** A Onda 2b e as seguintes só ganham corte em stories **quando forem liberadas** — e a 4
e a 5 dependem do gate §3.1 lido sob a pré-condição da §3.1.2. Delimitar agora seria produzir
decomposição que envelhece antes de ser usada, que é o defeito que a §3.1.1 acabou de custar caro.

---

## 7. Riscos

> ⚠️ Nesta tabela, os números de onda foram **atualizados para a numeração nova** (§11.5). Onde a
> mitigação original citava "Onda 3" (importação), leia **Onda 4**; "Onda 4" (match) → **Onda 5**;
> "Onda 5" (baixa de Receber) → **Onda 6**; o backfill de aplicação → **Onda 2b**.

| Risco | Prob. | Impacto | Mitigação já desenhada | Fonte |
|---|---|---|---|---|
| **Planos de dinheiro voltarem a se misturar** (é o bug original, numa forma nova) | Média ao longo do tempo | Alto | Regra dos Planos com **teste estrutural de import** + campo `*_origem` obrigatório. Sem o teste, degrada por acidente: basta uma story futura importar o módulo errado | design §1.3, §11 |
| **Divergência agregada esconder problemas** (várias contas PJ em bancos diferentes) | **Alta** se a conferência for consolidada | Alto — mata o poder de diagnóstico, que é o produto | Conferência **por conta** obrigatória; consolidado só com decomposição visível | **fundador D2 (2026-07-29)**; §3.2 deste epic |
| **Abandono da conferência** ("última conferência há 94 dias") | Média | Médio | O sistema **declara que não sabe** em vez de culpar; `dias_desde_ultima_conferencia` permite a frase honesta; o gancho é utilidade, não obrigação | design §5.1, §11 |
| **Produto virar ERP contábil e perder o público** | Média | **Existencial para a tese** | Rótulo "Contas & Saldos"; a frase antes da tabela; conferência funciona **sem** import. **Sintoma observável:** a tela de linhas virar a mais acessada do financeiro | design §9, §11; ADR 0003 Consequência 2 |
| **Escopo crescer por inércia até a importação e o match** (Ondas **4 e 5**) sem o número justificar | Média | Alto (2,5 + 2,0 ondas de custo permanente) | §5.1 + gate do §3.1, **agora sob a pré-condição da §3.1.2**: liberar a importação exige o número na mão, lido depois da Onda 2, e decisão do fundador | design §8; ADR 0003 Revisão futura (a); §3.1.1 |
| **Parser por banco vira manutenção perpétua** (Onda **4**+) | **Alta — é certeza, não risco** | Médio, recorrente e imprevisível | Strategy plugável; falha de parse **fail-loud**, nunca grava lixo em campo imutável; começar com 1–2 formatos. **É o preço direto de "não contar com terceiros"** e foi aceito de olhos abertos | ADR 0003 Consequência 1; design §11 |
| **Janela de ~60 dias de extrato reintroduz dependência de disciplina** | Alta (Onda **4**+) | Alto — dado perdido é irrecuperável | `opening_balance_cents` como âncora; lembrete de cadência; **a conferência não depende de arquivo, e a partir da Onda 2 nem depende de digitação** | REQ-9; pesquisa R4; design §2.1 |
| **`MEMO` do OFX não verificado** — toda promessa de match por contraparte repousa nele | Média/Alta | Médio — o match cai para valor+data, mais fraco | **Verificar empiricamente com arquivos reais de 3–4 bancos ANTES de comprometer escopo da Onda 4** (dependência D6) | REQ-19; pesquisa R5 |
| **Dupla contagem transferência × extrato** | **Alta** se a importação (Onda 4) for liberada | Alto | Passo de enriquecimento antes de inserir + constraint única + marcação "possível duplicata" quando ambíguo (não adivinha). ⚠️ **A Onda 2 acrescenta um segundo eixo dessa dupla contagem — baixa × movimento manual** — mitigado pela guarda da §7.1 | design §4.5, §11 |
| **Resgate de aplicação virando receita fantasma** (Onda **2b**) | Média sem cuidado | Alto | Regra da Neutralidade + guarda de `target_type` no vínculo + teste de snapshot da DRE. Duas defesas independentes. A `bank_transfers` genérica da Onda 2 já nasce DRE-neutra por construção | design §3.5, §11; REQ-25 |
| **Baixa indevida de `Charge` sem caminho de desfazer** | Alta **se permitida** | **Crítico** (GMV duplicado no painel do Master) | Onda **6** bloqueada; ausência do endpoint + guarda de `target_type`. ⚠️ **Não confundir com o `settle-externally` da Onda 2**, que é declaração do dono e não cria `PlatformEarning` | design §4.7; REQ-17 |
| **PII de contraparte vazando para a IA** (CPF de quem nunca contratou com a e1p) | Média sem disciplina | Alto (LGPD) | Anonimizador obrigatório inclusive na classificação; minimização na extração; teste com espião no `core/ai` | design §4.6, §7.4; REQ-18 |
| **Backfill silencioso a zero linhas sob FORCE RLS** (Onda **2b**) | **Alta se esquecido** | Alto | Documentado no design; disciplina da migration 0046; SQLite dos testes **não pega**. ⚠️ **A Onda 2 nova NÃO tem backfill** — é migration puramente aditiva; o único backfill do épico ficou na 2b, de propósito | design §2, §6.2 |
| **Vender a feature como "conformidade com a reforma tributária"** | — (evitável por decisão) | Médio — envelhece mal e expõe a contestação por qualquer contador | **Vetado** por decisão do fundador (§2.1) | REQ-28; pesquisa R1, §1.6 |
| **Arquivo de extrato acessível por outro usuário do mesmo tenant** | Média | Médio (documento financeiro completo) | Dívida **herdada e não resolvida** por este epic: `owner_type='bank_import'` nasce com o mesmo problema da bandeja de comprovantes. Quando `/attachments` for endurecido (checar dono, não só tenant), `bank_import` entra na mesma varredura | design §6.8; `CLAUDE.md` |

### 7.1 Riscos acrescentados pela Onda 2

| Risco | Prob. | Impacto | Mitigação | Story |
|---|---|---|---|---|
| **Tenant sem conta bancária não consegue dar baixa em conta a pagar** | **Alta** — é certeza no primeiro tenant novo | Alto — bloqueia um fluxo central que hoje funciona sozinho | 409 acionável + cadastro embutido; aviso no onboarding. **É o custo direto da decisão do fundador e está declarado**, não descoberto depois (design Onda 2 §4.1) | 8.12, 8.13 |
| **Contagem dupla** — o mesmo pagamento lançado como baixa **e** como movimento manual | **Alta** sem a guarda | **Alto — a divergência dobrada PARECE um achado real**, e é o pior modo de falha da onda | Validação estreita ±3 dias com **409 de escolha** (não bloqueio mudo) + curadoria de UI do formulário manual | 8.17 |
| **Agendamento sumindo da Projeção** (não é `open`, e o movimento é futuro) | **Alta** se `_window_sums` não for tocado | **Alto — é a máquina de falso negativo da Onda 0 ressuscitada, na mesma tela que a Onda 0 consertou** | Estado `scheduled` + `status IN ('open','scheduled')` com a data do débito | 8.14 |
| **Saldo corrente incluindo movimento agendado** ("Total em contas" mostra dinheiro que já tem destino) | **Alta** — é o estado atual do código, em 6 chamadas | Alto | `until=None` = **hoje**, fail-closed; quem quiser o futuro pede `date.max` explicitamente | 8.10 |
| **`paid` com data futura entrando primeiro e `scheduled` depois** | Média — é a tentação de fasear | Alto — exigiria **migration com backfill sob FORCE RLS** para separar os dois depois | `scheduled` entra **junto** (F-D9); e o corte 8.12/8.14 põe **teto em hoje** enquanto `scheduled` não existe, para que o dado ruim nunca chegue ao banco | 8.12, 8.14 |
| **Recuar `opening_date` sem redeclarar o saldo** → divergência inventada (gêmeo do BANK-001, pela porta oposta) | **Alta depois desta onda** | Alto | Recuo passa a exigir `opening_balance_cents` no mesmo PATCH (422) | 8.11 |
| **Backfill esbarrar em `opening_date`** — as 45 baixas retroativas levam 422 | **Alta** — é **certeza** com a C6 aberta em 30/07 | Médio, mas **operacionalmente travante** | Ordem obrigatória do mutirão (§7.2) + aviso pró-ativo no cadastro | 8.11 |
| **`divergencia > 0` ambígua** — agendamento que falhou × recebimento não registrado | Alta assim que houver agendamento | Médio — manda o dono caçar a coisa errada (o modo de falha do BANK-001, com outra causa) | Regra determinística nomeando o suspeito, por ordem de grandeza, com *"pode não ter saído"* | 8.16 |
| **Dinheiro de plataforma parecendo dinheiro de banco** (é o bug de origem, numa forma nova) | Média | Alto | Invariante do Trilho (§4.9) + 5 defesas testáveis, incluindo **espião** em `build_transaction` | 8.15 |
| **O sinal de recebimento fora do trilho virar produto de plataforma** | Média **ao longo do tempo** — a "melhoria" é óbvia para quem chegar depois | Alto — relação com o usuário | Proibição normativa (§2.1) + `test_admin_nao_expoe_recebimento_fora_do_trilho`. **Escrever isto agora custa um parágrafo; descobrir depois custa a relação** | 8.16 |
| **Estorno apagando linha real já importada** | Baixa hoje, **alta a partir da Onda 4** | Alto — perda de dado bancário | DELETE só em linha **puramente sintética**; linha enriquecida **desliga a origem** e vira órfã do extrato (degradação honesta) | 8.12 |
| **`bank` importando `payables`/`receivables` (ciclo)** | Média | Médio | Asserção positiva nova em `test_money_planes.py` (§4.1d). Sem ela, o primeiro atalho de conveniência recria o ciclo | 8.9 |
| **`source` com dois eixos degradar com o tempo** | Média | Médio | **Toda regra escrita contra `SOURCES_SISTEMA`/`SOURCES_EXTERNA`**, nunca contra valor solto. A mistura está em produção (0059) e **não** será consertada: exigiria reescrever coluna sob FORCE RLS por benefício estético | 8.9 |
| **Seletor de conta fora da área visível em ~360px** | Média | **Alto — já aconteceu DUAS vezes** (PRs #56 e #58; uma conta real foi marcada paga sem o dono ver o checkbox) | Seletor **dentro da mesma barra fixa** do botão; aceite manual em 360px **bloqueia a story** | 8.13 |
| **`payables.bank_transaction_id` (cache) divergir do `origin_id` (verdade)** | Baixa — **só alcançável por bug** (escritor único, mesma chamada, mesma transação) | Médio | Regra de autoridade escrita na docstring das duas colunas: quem manda é o `origin_id`. ⚠️ **A garantia é `test_cache_de_movimento_nunca_diverge_do_origin_id`** (baixar / trocar conta / trocar data / estornar / repagar), **não** um script de auditoria — `bank_audit` não existe (ratificação §C-4.2) | 8.9, 8.12 |
| **45 estornos agitando a Agenda** (90 escritas de status; janela com 45 contas aparecendo vencidas) | Alta — é o plano escolhido | Baixo | Custo **conhecido e aceito** pelo fundador (F8). Nada quebra; contas com comprovante mantêm o anexo | — |

### 7.2 Alerta operacional — a ordem do mutirão das 45 não é negociável

> **Situação verificada:** o fundador cadastrou a conta **C6 em 2026-07-30**, com `opening_date` = hoje.
> `_movements_sums` só soma `posted_at > opening_date` e `_validate_posted_at` recusa
> `posted_at <= opening_date` com **422** — as duas guardas estão **certas** (o que aconteceu até a
> abertura já está dentro de `opening_balance_cents`; contar de novo dobraria o valor).

**Consequência CERTA, não provável:** com `opening_date = 30/07`, **as 45 baixas retroativas levam 422,
todas**.

**Ordem obrigatória:**

| Passo | Ação | Se pular |
|---|---|---|
| **1** | **Recuar o `opening_date` da C6** para antes da conta mais antiga que ele quiser trazer, **declarando o saldo daquele dia** (número que só existe no app do banco dele — o e1p diz qual buscar, não inventa) | Todo repagamento leva 422 |
| **2** | **Só então estornar** as 45 | — |
| **3** | **Repagar** informando conta e data | — |

> ⚠️ **Invertendo a ordem, ele fica com 45 contas estornadas e nenhuma repagável.**

**Pré-requisito de software:** a **Story 8.11** (guarda do recuo + aviso pró-ativo) precisa estar em
produção antes do passo 1 — senão recuar a data sem redeclarar o saldo produz uma **divergência
inventada**, que é o BANK-001 pela porta oposta.

**E antes de tudo:** a **Story 8.12** precisa estar em produção para que o passo 3 exista. Sem ela, não
há onde informar a conta na baixa. → design Onda 2 §4.3, §4.4; ADR 0003 Adendo 4.

---

## 8. Dependências

**Internas (código já existente — pré-requisitos satisfeitos):**

| # | Dependência | Situação |
|---|---|---|
| D1 | **Epic 5 entregue** — `engine.py` puro (5.8), `projection.py` (5.7), `investments` (5.6), plano de contas (5.1/5.2) | ✅ Satisfeita — este epic **estende**, não recria |
| D2 | `payables.build_payable` + `apply_paid` sem commit; `POST /payables/bills/{id}/reverse` | ✅ Satisfeita (extraídos na bandeja de comprovantes) |
| D3 | `core/events`, `core/anonymizer`, `core/ai`, `core/storage`, `attachments` | ✅ Satisfeita |
| D4 | Job `cross-tenant-rls` no CI (testcontainers + Postgres real) | ✅ Satisfeita — é o gate de RLS de toda story deste epic |

**Bloqueios e pré-requisitos de ondas não liberadas:**

| # | Dependência | Onda (numeração nova) | Situação |
|---|---|---|---|
| D5 | **Vínculo `platform_earnings → transaction`** | **6** | 🚫 **Não será feito agora** (decisão do fundador). Onda 6 fora da fila. ⚠️ **Não alcança** o `settle-externally` da Onda 2 (§5, Onda 6) |
| D6 | **Verificação empírica de OFX real** (3–4 bancos do público-alvo): o formato ainda é exportado? o `MEMO` carrega contraparte/CPF? o `endToEndId` do Pix aparece? | **4** | ⏳ Pendente — **@analyst**. Se nenhum banco relevante exportar OFX em 2026, o caminho de arquivo morre e as Ondas 0–3 sobrevivem intactas (ADR 0003, Revisão futura (b)) |
| D7 | **Payout real** (`request_payout` hoje só marca `withdrawn`; exige dados bancários + KYC) | **3** | ⏳ Não decidido (D5 do design). Default: a Onda 3 permanece **registro contábil**, sem transferência real |
| D8 | **O número da conferência** (o gate do §3.1) | **4, 5** | ⏳ ⚠️ **Corrigido em 2026-07-30:** o número **não** é o da Onda 1 — só é legível **depois da Onda 2**, no primeiro ciclo que satisfaz a pré-condição da §3.1.2 |
| D9 | **A Onda 2 em produção** — pré-condição do gate (zera **P1 e P2**) | **4, 5** | ⏳ Nova. Sem ela, a divergência mede a **ausência de uma porta** (§3.1.1). ⚠️ **A Onda 2 sozinha não satisfaz a pré-condição em geral**: P3 (rendimento) só zera na **2b** e P4 (payout) na **3**. Hoje ambos são vazios no tenant do fundador — P4 por construção, P3 por medição (F12) —, então a Onda 2 basta. **Isso é estado, não garantia** |
| D10 | **Mutirão do fundador na ordem da §7.2** (recuar `opening_date` → estornar → repagar), com as Stories 8.11 e 8.12 em produção | — | ⏳ Operacional, do fundador. **Bloqueia a leitura do gate**, não o desenvolvimento |

**Externas:** nenhuma. Zero serviço de terceiro no caminho crítico, zero custo recorrente novo
(ADR 0003, Consequência positiva 10).

---

## 9. Decisões do fundador registradas e pendências

**Decididas em 2026-07-29 — não reabrir:**

| # | Decisão | Onde reverbera |
|---|---|---|
| F1 | **Controle bancário nativo, sem agregador de Open Finance.** Pluggy, Belvo, Klavi (e correlatos) **vetados por decisão de dependência**, não por preço. Arquivo (OFX/CSV) é aceitável | ADR 0003; §2.1 |
| F2 | **Escopo imediato aprovado: Onda 0 + Onda 1.** ✅ **Concluídas e em produção** (PR #61) | §5 |
| F3 | **Topologia: várias contas PJ** (corrente + poupança + aplicação, possivelmente em bancos diferentes). Não é conta PF misturada. Suportar N contas desde a Onda 1; **conferência por conta**, não só consolidada | §3.2; Story 8.2, 8.5 (responde **D2** e, por consequência, **D3** do design) |
| F4 | **A dívida `platform_earnings → transaction` não será paga agora** | Onda **6** bloqueada (responde **D4** do design com "não") |
| F5 | **Não posicionar como conformidade com a reforma tributária.** A justificativa é conferência e controle interno; a e-Financeira é **contexto de risco de divergência**, não obrigação | §2.1 (responde REQ-28) |

### 9.1 Decididas em 2026-07-30 (Onda 2) — não reabrir

> Origem: o fundador achou a falha de escopo da §1.2 com as Ondas 0 e 1 já em produção. Formalizadas no
> **ADR 0003 Adendo 4** e no design da Onda 2.

| # | Decisão | Fala / fonte | Onde reverbera |
|---|---|---|---|
| **F6** | **Onda 2 LIBERADA** — a origem do movimento entra agora, antes de qualquer coisa que dependa de arquivo | falha de escopo achada por ele; ADR Adendo 4 | §5; stories 8.9–8.18 (+ 8.19 e 8.20, corretivas) |
| **F7** | **Conta bancária OBRIGATÓRIA** na baixa de Contas a Pagar e no recebimento de Cobranças | *"opcional significa que alguém pula, e a conferência volta a medir o que você esqueceu de preencher"* | itens 2.6, 2.15; stories 8.12, 8.15 |
| **F8** | **Backfill das 45 contas à mão: estornar e repagar**, conta a conta — **não** rota de correção em massa, **não** migration | motivo declarado: *"rever conta a conta pode ser desejável para conferir valores"*. Custo (90 escritas de status na Agenda) **conhecido e aceito** | §7.2; nenhuma story — é operação |
| **F9** | **Lançamento manual reduzido ao que só existe no banco** | *"o que vamos fazer manual é apenas coisas diretas lá, como taxas e transferência para aplicações"* | itens 2.21, 2.22, 2.24; stories 8.17, 8.18 |
| **F10** | **Data da baixa: default no vencimento (`due_date`), e data futura PERMITIDA** | *"deixar habilitado no vencimento, pois se estiver fazendo retroativo, pq não deu certo no dia — e no futuro também permitir, pq posso estar agendando"*. ⚠️ A recomendação anterior da @architect (`min(due_date, hoje)`) foi **revogada por ela mesma**: desenhava o produto em volta de uma limitação do modelo | item 2.7; story 8.12 |
| **F11** | **Estado próprio `scheduled`, entrando JUNTO nesta onda** — não `paid` com data futura | Motivo decisivo, verificado no código: com `paid`+futuro a conta agendada **sai dos fluxos de saída** (`_window_sums` filtra `status=='open'`) **e** não entra no saldo inicial (`until=today`) — **o dinheiro some da Projeção**. É a máquina de falso negativo da Onda 0 ressuscitada na mesma tela que a Onda 0 consertou | itens 2.8, 2.9; story 8.14 |

| **F12** | **F-D12 fechada: o gate abre no primeiro ciclo completo pós-Onda 2** — a Onda 2b **não** é pré-requisito da leitura do gate | ⚠️ **Não é fala do fundador: é consulta ao banco de produção** (2026-07-30) — 1 conta de investimento cadastrada, **0 rendimentos lançados**, então o termo P3 é vazio. Era o que a @architect recomendava ("perguntar antes de planejar… é uma consulta ao banco de dados dele, não uma decisão de produto") | §3.1.2; §5 (ordem inalterada); item 2.20; Story 8.16 AC7 |

**⚠️ F12 é a única decisão desta lista que pode se desfazer sozinha.** As outras onze são escolhas de
produto: só mudam se alguém as mudar. F12 depende de um **contador em zero** — no dia em que o fundador
lançar o primeiro rendimento de aplicação, P3 deixa de ser vazio e a leitura do gate passa a depender da
**Onda 2b**, sem que ninguém tenha decidido nada. Não há alarme para isso; o que há é a **nota do bloco
4 nomeando a onda que fecha cada termo** (Story 8.16 AC7), que faz a mudança aparecer na tela no ciclo
em que acontecer.

**Requisito que o Epic 8 não conhecia, e que veio de F10:** **agendamento de pagamento no app do
banco**. Não estava em lugar nenhum deste epic nem do design-mãe. Não é o fundador ignorando o
argumento; é o desenho não conhecendo o fluxo real.

### 9.2 Pendentes — com default adotado até haver resposta

| # | Pergunta | Default adotado / recomendação | Quem decide | Onda |
|---|---|---|---|---|
| D1 | Banda de tolerância `max(R$ 50, 0,5%)` serve, ou quer fechar em zero? | Adotar o default, configurável por tenant. **A justificativa subiu de `[SUPOSIÇÃO]` para *"absorve o resíduo estrutural conhecido"*** — as classes (1) e (3) da decomposição da §3.1.2 | fundador | 1 ✅ |
| D6 | Carteira Asaas como `bank_account` (`kind='platform_wallet'`)? | **Não** criar; o valor fica reservado no vocabulário e é **rejeitado como `kind`** (Regra dos Planos em forma de validação) | fundador | — |
| D7 | Sinalizar recebimento que não veio pelo trilho? | ✅ **Resolvida e antecipada:** sinalizar como informação **neutra ao dono, nunca ao Master**. Antes seria a conferência **inferindo** de um crédito órfão; agora o dono **declara**. O dado fica limpo; **para quem ele é não muda** | — | **2** |
| D8 | O vocabulário de `operation_nature` vem do contador? | Usar o vocabulário sugerido pelo design, como **texto livre** — não enum fechado | fundador | **2**+ |
| **F-D2** | **Aceita que `bank_accounts` vire pré-requisito de Contas a Pagar?** (tenant sem conta não dá baixa) | **Sim, aceitar.** É a consequência direta de F7, e a alternativa é o "opcional" que ele já recusou. Recomendação: 409 acionável + cadastro embutido | fundador — **confirmação, não reabertura** | 2 |
| **F-D4** | **"Desfazer" recebimento fora do trilho entra na Onda 2?** | **Não agora.** A rota de correção (2.17) cobre o erro provável (conta/data). O desfazer é **seguro** (a dívida `platform_earnings` não o alcança) e cabe depois. Se sim: +1 rota, +2 testes | fundador | 2 |
| **F-D5** | **O sinal de recebimento fora do trilho pode ser desligado pelo dono?** | **Não.** Mesma lógica do 🟡 "nenhuma conta cadastrada" da Onda 1: o sinal é verdadeiro e é sobre o interesse dele. *"O dono que mais precisa é o que desliga"* | fundador | 2 |
| **F-D6** | **A lista curada do manual está completa?** (tarifa/juros, IOF/imposto, transferência entre minhas contas, rendimento, outro) | Adotar como está; `Outro (descreva)` é a válvula. Se faltar categoria comum, é **uma entrada numa lista** — custo zero | fundador | 2 |
| **F-D10** | **A rota `PATCH .../payment` fica, agora que o retroativo saiu (F8)?** | **Fica.** O argumento mudou de "mutirão pontual" para **"reagendar é evento normal"** — sem ela, reagendar = estornar + repagar, com delete+recreate do movimento e a Agenda piscando, **todo mês** | fundador | 2 |
| **F-D11** | **Quem promove `scheduled → paid` na data?** | **O worker que já existe** (`app.worker.run_sweep`): +1 varredura. ⚠️ O **saldo** não precisa dele — anda sozinho porque é função da data | @architect / fundador | 2 |
| **F-D7** | **Onda 2b (aplicação) entra logo depois da 2, ou espera?** | Logo depois — mas ela carrega **o único backfill** do épico, sob a armadilha do FORCE RLS. Merece story própria e atenção de gate | fundador | 2b |
| **F-D8 / G-4** | **Soltar release sem a validação em ~360px?** | **Bloquear o release.** Aberta desde a Onda 1, e esta onda **acrescenta um seletor de conta na barra fixa do celular**. Dois PRs de fix de campo já foram pagos por essa lacuna | **fundador** | 1, 2 |
| **@PM-1** | **NOVA — o "ponto de parada legítimo" agora é depois da Onda 3 (payout)?** | **Sim** `[DECISÃO DO @PM, a confirmar]`. É o fim das ondas de dependência externa zero. O design da Onda 2 **não** reescreveu a §5.1 do epic; esta leitura é minha | fundador | 3 |
| **@PM-2** | **NOVA — a Onda 2 (12 stories, ~2,5 ondas) entra inteira, ou em duas liberações?** | **Inteira.** Fatiar reabre o risco do `paid`+futuro e deixa a pré-condição do gate insatisfeita por mais tempo. Mas o corte da §6.1 permite parar **depois da 8.14** com o produto coerente, se ele quiser reavaliar. ⚠️ A **8.20 não é fatiável para fora**: sem ela a conferência pode emitir 🟢 falso, que é pior do que não ter a onda | fundador | 2 |

**Herdadas do gate das Ondas 0–1 (`docs/qa/epic-8-onda-0-1-gate-2026-07-30.md`), ainda abertas:**

| # | Item | Quem decide | Bloqueia a Onda 2? |
|---|---|---|---|
| 1 | **SIG-001** — a virada de mês apaga uma conferência recente e bem-sucedida (a janela é o mês da DRE). **A @architect já decidiu a arquitetura** no design da Onda 2 §9.4: usar `dias_desde_ultima_conferencia`, **não** a janela da DRE — uma conferência que bateu em 28/06 continua verdade em 01/07. Falta virar **story própria** | @po (agendar) | Não — mas a Onda 2 **multiplica os movimentos** e, com isso, a frequência com que o dono olha esse sinal |
| 2 | **G-1** — o gate global `test_todo_saldo_declara_origem` foi adiado; hoje a cobertura é por instância (14 campos `saldo_*_cents`, 6 sem irmão, +8 fora do regex) | @architect | Não |
| 3 | **MNT-001** — `audit.record(target='')` em **17 call sites** (`chart_of_accounts`, `cost_centers`, `crm`). O módulo `bank` está correto (faz `flush()` antes) | @po / fundador | Não |
| 4 | **RG-2** — concordância singular/plural na mensagem do caso `ignored` (cosmético) | @po | Não |
| 5 | **RG-4 follow-up** — endurecer o tenancy guard além de arquivos de rota (pede AST) | @po | Não |
| 6 | **G-4 (~360px)** | fundador | **Bloqueia release**, não merge — ver F-D8 |

---

## 10. Rastreabilidade (Constitution Artigo IV — No Invention)

| Afirmação deste epic | Fonte |
|---|---|
| Plano 3 não existe; planos 1 e 2 implementados | ADR 0003, Contexto |
| `saldo_inicial` usa `available_cents` (plano 1 como plano 3) | `financial_intelligence/projection.py:177` |
| `payables` não toca a Carteira | `payables/models.py:4` |
| Caixa usa `paid_at`; DRE/lucratividade usam `competence_date` | `payables/models.py:6-9`, `receivables/models.py:6-9` |
| DRE agrega exatamente `charges` + `payables` + `transactions` | `dre.py:51,135-156` |
| `principal_cents` é digitado, sem aporte/resgate | `investments/models.py:49`, `investments/service.py:96-113` |
| Estorno de `Charge` descartado por causa de `platform_earnings` | `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md` (Adendo); `CLAUDE.md` |
| Motor de diagnóstico é puro, sem I/O | `financial_intelligence/engine.py`; PRD NFR3 |
| Padrão de RLS em migration; armadilha de backfill sob FORCE RLS | `0049_investments.py::_enable_rls`; `0046_ledger_classification.py` |
| Head de migrations = 0057 | `apps/api/migrations/versions/` |
| Modelo de dados, saldo derivado, Regra dos Planos, Regra da Neutralidade, pipeline, conferência, faseamento em ondas, ponto de parada | `docs/architecture/controle-bancario-design.md` §1–§12 |
| Decisão de construir nativo; alternativas rejeitadas; bloqueio da baixa de `Charge`; consequências aceitas | `docs/decisions/0003-controle-bancario-nativo.md` |
| REQ-1..REQ-32 (fundação, import, conferência, transferência, posicionamento) | `docs/research/2026-07-29-controle-bancario-requisitos-e-viabilidade.md` §"Requisitos Consolidados" |
| QuickBooks Solopreneur não tem contas a pagar e depende do extrato | pesquisa §3.1 (TechRepublic, Intuit, Mission Accounting) |
| Reforma exige documento fiscal, não extrato; split payment não alcança Simples com DAS unificado | pesquisa §1.2, §1.3, §1.6 |
| e-Financeira estendida a fintechs/IPs pela IN RFB 2.278/2025; obrigação é da instituição | pesquisa §1.4 |
| Sociedade de advogados já tem escrituração formal obrigatória (Código Civil) | pesquisa §1.5 |
| Bancos entregam tipicamente ~60 dias de extrato | pesquisa §2.2; design §2.1 `[CONFIRMADO 2026-07-29]` |
| Várias contas PJ; conferência por conta; Onda 0+1 aprovadas; dívida não paga; não posicionar como tributário | **falas do fundador, 2026-07-29** (§9, F1–F5) |
| Banda `max(R$ 50, 0,5%)`; janela de ±3 dias no enriquecimento; vocabulário de `operation_nature` | `[SUPOSIÇÃO do design]`, parametrizáveis — design §12 |
| Janela de 3 ciclos mensais para o gate de decisão | **`[SUPOSIÇÃO DO @PM]`** — não vem do design nem da pesquisa |
| Corte das 8 stories (8.1–8.8) | **`[DECOMPOSIÇÃO DO @PM]`** — os itens de escopo vêm do design §8; o corte entre stories, não |

**Acrescentado em 2026-07-30 (Onda 2):**

| Afirmação deste epic | Fonte |
|---|---|
| A falha de escopo: só a direção `extrato → sistema` foi modelada; `payables` não tem **nenhuma** referência a `bank` | `controle-bancario-onda2-design.md` §1.1; grep de `apps/api/app/modules/payables/` |
| 45 `payables` pagas, 0 `charges`, saldo derivado R$ 0,00 em produção | **[FUNDADOR / coordenador, 2026-07-30]** — a @architect registra que **não** verificou contra o banco de produção |
| *"é um sistema integrado, não tem o motivo de tudo começar do zero"* | **fala do fundador, 2026-07-29/30** |
| Cinco eventos que o sistema conhece; zero ligados | design Onda 2 §1.2 (inventário sobre `payables.apply_paid:241`, `receipts.link_receipt:191`, `receivables.mark_paid:380`, `investments.register_yield`, `wallet.request_payout:227`) |
| A divergência da Onda 1 mede a **ausência de uma porta**; o gate teria pedido a onda mais cara | design Onda 2 §9.1; ADR 0003 Adendo 4 |
| Pré-condição do gate: **P1..P4**, com a `Charge` do trilho fora **por construção** | `controle-bancario-onda2-ratificacao.md` §C-1.3 (normativa) + design Onda 2 §9.3 reescrita. ⚠️ **A redação anterior deste epic** (*"toda `Payable` paga e toda `Charge` recebida"*) era **insatisfazível** e foi revogada |
| A nota do bloco 4 **anota, nunca subtrai** (é a Regra 5 do `CLAUDE.md`) | design Onda 2 §9.3 |
| Decomposição da divergência em 5 termos | **[ANÁLISE da @architect]** — derivada dos eventos que o sistema conhece (design Onda 2 §9.2) |
| Regra da Origem, índice único parcial, `sync_origin_movement` não commita | design Onda 2 §2, §3.2, §3.5; ADR 0003 Adendo 4, item 11 |
| Invariante do Trilho; **não existe** coluna `payment_route` | design Onda 2 §3.4 |
| `paid_at` é cravado em `now()` | `payables/service.py:258` |
| 409 de conta paga cobre só 6 campos; `competence_date`/`chart_account_id` **já** são editáveis em conta paga | `payables/service.py:160-173` |
| `_window_sums` filtra `status == 'open'` ⇒ agendada sumiria da Projeção | `financial_intelligence/projection.py:370-373` |
| `payables.status` é `String(12)` ⇒ `"scheduled"` (9) cabe **sem migration de tipo** | `payables/models.py:43` |
| DRE filtra `status != canceled` nas 4 agregações ⇒ status novo passa direto (impacto zero) | `financial_intelligence/dre.py:124,290,437,634` |
| `GET /bank/accounts` e as 4 respostas de CRUD + `/accounts/{id}/balance` incluem o futuro | `bank/router.py:128,140,153,169,184,202` |
| Projeção (`until=today`) e Conferência (`until=reference_date`) **já estavam seguras** | `projection.py:329`; `reconciliation.py:358`; `CLAUDE.md` regra 6 |
| `operation_nature` já existe, nullable, vocabulário aberto ⇒ **zero migration** | `bank/models.py:268-270`; design-mãe §7.2 |
| Recuar `opening_date` é permitido e é *"o caminho de reparo"*; `update_account` **não** exige redeclarar o saldo | `bank/service.py:124-127` |
| Saldo derivado só soma `posted_at > opening_date`; `posted_at <= opening_date` → 422 | `bank/service.py:287-306, 605-628` |
| Worker existente itera tenants sob `tenant_session`, idempotente, réplica única | `apps/api/app/worker.py` |
| Baldes da Fila são calculados **na leitura**, *"sem precisar de job/cron"* | `payables/service.py:361-363` |
| Fundador cadastrou a C6 em 2026-07-30 | **[COORDENADOR, 2026-07-30]** |
| Dois PRs de fix de campo por elemento fora da área visível em ~360px | `CLAUDE.md` (PRs #56, #58) |
| Conta obrigatória; manual só para taxas e transferência; backfill à mão; default no vencimento com futuro permitido; `scheduled` junto | **falas e decisões do fundador, 2026-07-29/30** (§9.1, F6–F11) |
| Janela de ±3 dias e valor exato na guarda de contagem dupla | **`[SUPOSIÇÃO do design, parametrizável]`** — mesmo número do enriquecimento (design-mãe §4.5), de propósito |
| Esforço da Onda 2 = 2,5 ondas de trabalho | **`[ESTIMATIVA DO @PM]`** — o design da Onda 2 **não** estima; derivada do número de stories e do escopo tocado |
| Corte das 10 stories construtivas da Onda 2 (8.9–8.18) e a ordem de merge da §6.1 | **`[DECOMPOSIÇÃO DO @PM]`** — os 25 itens de escopo vêm do design; o corte, não |
| Teto de `paid_on` em "hoje" na Story 8.12, removido na 8.14 | **`[CORTE DO @PM]`** — implementa a mecânica do design §4.2.4 (nunca deixar `paid`+futuro no banco), não a contradiz |
| Ponto de parada legítimo agora é depois da Onda 3 (payout) | **`[DECISÃO DO @PM, a confirmar]`** (§9.2, @PM-1) — o design da Onda 2 não reescreveu a §5.1 |
| `declarado`/`extrato` revogados do vocabulário de `*_origem` | ratificação do design; `CLAUDE.md` regra 2 — **o epic estava desatualizado** |

**Acrescentado em 2026-07-30, 2ª rodada** — correções do @pm a partir da ratificação da @architect
(`controle-bancario-onda2-ratificacao.md`) e da validação do @po (`docs/stories/8.8-validacao-po-onda2.md`).
**Nada aqui é análise nova do @pm: é transcrição do que já foi decidido por elas.**

| Afirmação deste epic | Fonte |
|---|---|
| `app/scripts/bank_audit.py` **não existe**; `app/scripts/` tem 3 arquivos (`__init__`, `migrate_attachments_to_s3`, `scan_orphan_storage`) | ratificação §C-4.1 (`grep -rn "bank_audit" apps/api` → 0); validação do @po §3 (`grep -rn "bank_audit" apps/` → 0), **verificado duas vezes, independentemente** |
| A obrigação da Onda 2 vira **teste** (`test_cache_de_movimento_nunca_diverge_do_origin_id`, 5 caminhos); o script fica como pré-requisito da **Onda 5** | ratificação §C-4.2 |
| `_refresh_status` também não existe; é descrito como trabalho da Onda 4 | `bank/service.py:826`; ratificação §4 |
| Pré-condição P1..P4, com o par membro/não-membro **dentro** do bloco normativo | ratificação §C-1.3 |
| `_not_investment_yield()` existe e é **importado**, nunca reescrito | `receivables/service.py:82-90`; ratificação §C-1.5 |
| A `Charge` de rendimento nasce `paid`, `paid_at=now()`, sem `transaction_id` e sem `bank_account_id` — cairia inteira no P2 sem o predicado | `investments/service.py:163-177`; ratificação §C-1.2 (achado A-1) |
| `request_payout` só marca `withdrawn` ⇒ P4 é **vazio por construção** hoje | `wallet/service.py:227`; ratificação §C-1.3 |
| **F-D12 respondida: 1 conta de investimento cadastrada, 0 rendimentos lançados** (`charges` com `external_ref LIKE 'investment:%'` = 0) ⇒ P3 vazio ⇒ o gate abre no primeiro ciclo completo pós-Onda 2 | **consulta ao banco de produção, 2026-07-30** (não é fala do fundador); pergunta em ratificação §3.3 e validação do @po §7.4 |
| Forma canônica das pernas: `:out`/`:in`, pareadas por `transfer_id`, `VARCHAR(64)`; *"mesmo `origin_id` nas duas"* **rejeitada** (retry moveria o dinheiro duas vezes) | ratificação §C-3.1, §C-3.3 |
| `origin_id` é **chave de origem**, não "o id do lançamento"; a unidade de sincronização de uma transferência é **a perna** | ratificação §C-3.2 (normativa) |
| O 422 de `posted_at` futuro da transferência mora em `create_transfer`, não em `_validate_posted_at` | ratificação §C-3.4 (achado A-3) |
| `transfer_id` já existe em `bank_transactions` | `bank/models.py:278` |
| Story **8.19** existe, é da Onda 2, com escopo reduzido (não toca `projection.py`; a premissa da v0.1 foi refutada pelo fundador) | `docs/stories/8.19.story.md` v0.2; validação do @po §6 |
| Story **8.20** existe (comparação degenerada), merge **antes da 8.16**, tratamento = não-avaliável no bloco 1 | validação do @po §5 (veredito) — especificação preservada no AC3 da 8.19 |
| `derived_balance(until=opening_date) ≡ opening_balance_cents`; `reference_date == opening_date` é aceito; o cenário **não tem teste** (36 testes, zero o exercitam) | `bank/service.py::_movements_sums`, `::_validate_reference_date`; `test_bank_reconciliation_report.py`; validação do @po §5 |
| 8.19 e 8.20 **não consomem item da §5** — corrigem comportamento das Ondas 0/1 | **`[DECOMPOSIÇÃO DO @PM]`**, derivada do veredito do @po (§5) e do escopo reduzido da 8.19; os 25 itens seguem cobertos pelas 8.9–8.18 |

---

## 11. Conflitos com épicos existentes — o que este epic supersede

> Registrado aqui para que o @sm não escreva story contra um AC que este epic revogou.

**11.1 Epic 5, Story 5.7, AC1** diz que a projeção parte *"do saldo disponível atual da Carteira"*.
**A Onda 0 deste epic (Story 8.1) declara isso incorreto e a Onda 1 (Story 8.8) o substitui** por
saldo bancário derivado + `available_cents`, com origem rotulada. O AC1 da 5.7 fica **superado** a
partir da Story 8.8 — não é regressão, é correção de bug (design §6.1; ADR 0003, alternativa F).

**11.2 Epic 5, Story 5.6, AC1** trata *"principal aplicado"* como campo da entidade de investimento.
**A Onda 2b torna `principal_cents` derivado** (Σ aportes − Σ resgates) e faz `update_account` rejeitar
sua edição. O AC1 da 5.6 fica superado **quando a Onda 2b for liberada** — enquanto isso, o
comportamento atual permanece válido (design-mãe §3.2, §6.2; REQ-23).
⚠️ **Corrigido em 2026-07-30:** este parágrafo dizia "Onda 2". Com a renumeração, isso passaria a
significar a **Onda 2 nova** (a origem do movimento), que **não toca `investments`** — e o AC1 da 5.6
teria sido lido como superado cedo demais.

**11.3 Nada em Epics 1–4, 6 e 7 conflita** com este epic. Epic 7 (cobertura de testes) é
**complementar**: os testes estruturais da Regra dos Planos seguem o mesmo estilo do
`test_tenancy_guard.py` que a Story 7.1 endurece no CI.

### 11.4 Divergências entre o design e a pesquisa

> Registradas para serem **resolvidas por @architect + fundador antes de a onda correspondente ser
> liberada** — não por quem estiver escrevendo a story.

| # | Divergência | Onda | Situação |
|---|---|---|---|
| **C1** | **Layout de CSV.** REQ-10: CSV é fallback, exige **mapeamento explícito de colunas pelo usuário**, e é *"proibido manter tabela de layouts conhecidos por banco"*. Design-mãe §4.1/§4.3: layouts de CSV **em YAML por banco**, com mapeamento por tenant marcado como onda posterior. Contradição direta, não nuance | **4** | 🔴 **ABERTA.** Decidir **antes** de a onda de importação começar. Tensão real: manutenção perpétua (REQ-10 protege) × fricção para o usuário (o design protege). Prioridade baixa: a onda não está liberada |
| **C2** | **`register_yield`.** REQ-24: *"`register_yield` **não muda**"*. Design-mãe §3.4(b): passa a criar **também** um `bank_transaction` `source='yield'` já conciliado | **2b** *(era 2)* | ✅ **RESOLVIDA em favor do design (2026-07-30), e agora por princípio em vez de por julgamento:** sob a **Regra da Origem** (§4.8), rendimento é um evento que o sistema originou, logo gera movimento — pela mesma regra e pelo mesmo helper que a baixa de `payable`. Não há um caso a julgar à parte. A garantia IV1 da Story 5.6 (nunca chamar `mark_paid`/`build_transaction`) **permanece intacta** e deve ser reafirmada no AC da story da 2b. ⚠️ **Depende de `investment_accounts.bank_account_id`, então viaja com a 2b, não com a Onda 2** |
| **C3** | **Porta de entrada do arquivo.** REQ-12: reaproveitar a entrada que já existe (share sheet / bandeja de comprovantes), **não criar fluxo paralelo**. Design-mãe §4 passo [1]: `POST /bank/accounts/{id}/imports` (rota nova) | **4** *(era 3)* | ✅ **RESOLVIDA em favor do REQ-12 (2026-07-30).** A relação **inverteu**: com a Onda 2, `link_receipt(mark_paid=True)` → `apply_paid` → movimento, e a bandeja deixa de ser porta paralela para virar **a porta que já carrega o evento de pagamento**. `POST /bank/accounts/{id}/imports` fica **revogado como porta primária**; se a importação for liberada, o arquivo entra por `owner_type='bank_import'` com a conta escolhida **depois** do upload. A rota dedicada sobrevive como caminho de desktop, não como **o** caminho |

### 11.5 Renumeração das ondas (2026-07-30) — tabela de-para

> **Leia isto antes de interpretar qualquer "Onda N" escrita antes de 2026-07-30**, inclusive em
> stories já mergeadas, no gate de QA, no `CLAUDE.md` e no design-mãe. **Os números 2 a 6 mudaram de
> significado.**

| Número antigo | Conteúdo | Número novo |
|---|---|---|
| 0 | Saldo inicial honesto | **0** (igual) |
| 1 | Contas, saldo derivado, checkpoint, conferência | **1** (igual) |
| — | *(não existia)* — a origem do movimento | **2** |
| 2 | Transferências + aplicação + `principal_cents` | partida: transferência vai para a **2**; aplicação vira **2b** |
| 3 | Importação OFX/CSV | **4** |
| 4 | Sugestão de vínculo + baixa de Pagar | **5** |
| 5 | Baixa de Receber (bloqueada) | **6** |
| 6 | Payout da Carteira | **3** |

**Armadilhas conhecidas desta renumeração** (todas corrigidas neste arquivo):

| Onde | O que dizia | Por que era armadilha |
|---|---|---|
| §3.1 (gate) | *"Parar na Onda 2. Ondas 3 e 4 são over-engineering"* | Na numeração nova, "3 e 4" seriam **payout e importação**. Corrigido nomeando o **conteúdo**, não o número (§3.1.2) |
| §5.1 (ponto de parada) | *"o ponto de parada natural é depois da Onda 2"* | "Onda 2" significava **aplicação**. A mesma frase apontaria hoje para um estado do produto totalmente diferente |
| §11.2 | *"o AC1 da 5.6 fica superado quando a Onda 2 for liberada"* | A Onda 2 nova **não toca `investments`**. Corrigido para **2b** |
| §4.2 | *"Regra da Neutralidade, a partir da Onda 2"* | Continua correto **por acaso** — `bank_transfers` ficou na Onda 2. Verificado, não presumido |
| `CLAUDE.md` | *"Onda 5 (baixa automática de Contas a Receber) está bloqueada"* | Passou a ser **Onda 6**. ⚠️ **O `CLAUDE.md` ainda não foi atualizado** — ver §11.6 |

### 11.6 Conflitos encontrados nesta atualização e ainda NÃO resolvidos

> Achados ao cruzar o design da Onda 2, o design-mãe, o epic e o código em produção. **Nenhum bloqueia
> o início da Onda 2**; todos precisam de dono.

| # | Conflito | Quem resolve |
|---|---|---|
| **X1** | **`CLAUDE.md` §Financeiro está defasado**: fala de "Ondas 0 e 1" com a numeração antiga, diz *"Onda 5 bloqueada"* (agora 6), *"Ondas 3 e 4 são over-engineering"* (agora 4 e 5), e registra *"ponto de parada legítimo: se a divergência medida na Onda 1 for pequena e estável"* — que é exatamente a leitura que a §3.1.1 acabou de invalidar | @dev na primeira story da Onda 2 (é memória viva do projeto, não documento de PM) |
| **X2** | **Coluna "Migration" do epic estava errada de fato**: dizia Onda 1 = 0058, Onda 2 = 0059, Onda 3 = 0060. A Onda 1 consumiu **0058, 0059 e 0060**. Corrigido para "+N aditivas a partir do head real" | ✅ Corrigido aqui |
| **X3** | **Vocabulário de `*_origem` no §4.1(c)** listava `declarado`, revogado pela ratificação. O código em produção já está certo; **o epic é que estava errado**, e uma story escrita contra o epic teria reintroduzido o valor | ✅ Corrigido aqui |
| **X4** | **Design-mãe §2.3 × design da Onda 2 §3.3.** A §2.3 **rejeitou** a coluna direta em favor de `bank_reconciliations`, por causa de N:N (um Pix quitando duas contas) e do estado sugestão/confirmação. A Onda 2 usa **coluna direta**. A @architect argumenta que não é contradição — aqueles dois motivos são propriedades de **casar linha externa**, e movimento originado pelo sistema é 1:1 por construção, nasce confirmado, sem ambiguidade. **Julgo o argumento sólido e o registro como tensão resolvida por argumento, não como conflito aberto** — mas quem construir a Onda 5 (match) precisa saber que as duas formas coexistem no mesmo módulo | @architect (ciência); @sm (não reabrir) |
| **X5** | **Design-mãe §6.7 supersedido**: `payables.bank_account_id` como *"opcional, onda posterior, melhora a sugestão de match"*. A marca de supersede já está no design-mãe. **Nenhuma story pode citar a §6.7 como fonte** | ✅ Marcado no design-mãe |
| **X6** | **REQ-24 (letra) continua mais restritivo que o resolvido em C2.** A pesquisa está ratificada e não foi editada. Fica o registro de que **o design vence**, com a garantia IV1 reafirmada | @architect (já decidido, falta a story da 2b citar) |
| **X7** | **O design da Onda 2 não dá estimativa de esforço.** A minha (2,5 ondas) é `[ESTIMATIVA DO @PM]` derivada do número de stories — não há velocity confiável, e a Onda 1 (estimada em 1,5) consumiu 3 migrations e 8 stories | @pm / fundador |
| **X8** | **`packages/shared-types/src/generated.ts` continua defasado** e sem check de drift no CI — **zero menções a `bank`** desde o PR #45. A Onda 2 acrescenta campos a `payables`, `charges` e `bank_transactions`, ou seja, **aumenta a dívida**. Não bloqueia, mas cresce | @devops / Epic 6 |
| **X9** | **`scripts/check.sh` mascara falha de frontend** com `|| true` no vitest e resolve `ruff`/`python` do PATH. A Onda 2 tem 3 stories com frontend (8.13, 8.14, 8.17/8.18) — **rodar as etapas individualmente** até isso ser corrigido | @devops |
| **X10** | **A `Charge` sintética de rendimento é lembrada num lugar e esquecida no outro.** O mesmo predicado (`_not_investment_yield()`) foi aplicado pela Story 8.15 e omitido pela 8.16, escritas por @sm diferentes que não conversam. Corrigido nas duas, e a regra que fica é *"importar, nunca reescrever"* — mas **o padrão vai se repetir** em qualquer predicado compartilhado entre módulos. Não há gate mecânico para isso | @architect / @po (vigilância); ratificação §C-1.2 |

### 11.7 As quatro escalações ao @pm — RESOLVIDAS nesta rodada (2026-07-30)

> Registrado para que ninguém reabra o que já foi corrigido, e para que a **próxima** story leia o epic
> corrigido em vez de reproduzir o defeito. As quatro vinham da ratificação da @architect (§3.1) e da
> validação do @po (§7.1).

| # | O quê | Onde ficou | Estado |
|---|---|---|---|
| **E-1 / B-1** | `bank_audit` listado como ativo entregue, sob a instrução *"não recriar"* | §"Contexto do sistema existente" (removido da lista + bloco de correção com o que fica no lugar); item **2.2**; risco correspondente na **§7.1** | ✅ **Corrigido** — era 🔴 **bloqueio da 8.9** |
| **E-2** | §3.1.2 com pré-condição **insatisfazível** (`Charge` do trilho nunca terá `bank_account_id`) | §3.1.2 reescrita com **P1..P4**, membro/não-membro dentro do bloco normativo, `Charge` do trilho fora **por construção**, consequência de roadmap e **F-D12 fechada**; 1ª linha da tabela de decisão; nota do bloco 4 vira **até três notas** | ✅ **Corrigido** |
| **E-3** | Forma velha das pernas de transferência (*"mesmo `origin_id`"*) | Item **2.24** e **Story 8.18** na §6 — `:out`/`:in`, `transfer_id`, `VARCHAR(64)`, 422 em `create_transfer` | ✅ **Corrigido** |
| **E-4** | 8.19 e 8.20 fora da §6 | §6 (as duas delimitadas), **§6.1** (ordem de merge, com **8.20 antes da 8.16**), total 10 → **12 stories**, e a nota de que **não consomem item da §5** | ✅ **Corrigido** |

**O que continua aberto e NÃO é do @pm** (transcrito da validação do @po, para não se perder):

- **B-2 — a Story 8.20 precisa ser escrita** (@sm) e o **tratamento** confirmado (@architect). Bloqueia
  a **8.16** e o passo 1 do mutirão; **não** bloqueia 8.9–8.15, 8.17, 8.18.
- **SIG-001** — a virada de mês apagando conferência recente: arquitetura já decidida, falta virar
  story própria (@po). **Fora da 8.16**, de propósito.
- **"Tenho a conta e NÃO sei o saldo"** — não existe forma de o dono declarar isso; exige migration.
  Escalado pela 8.19, fora da Onda 2.
- **`TRANSFER_KINDS` sem não-membro escrito** (8.18 AC5) — risco baixo (validação por lista fechada, com
  o precedente `platform_wallet`), registrado pelo @po e não corrigido.
