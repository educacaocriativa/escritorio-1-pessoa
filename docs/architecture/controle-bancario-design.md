# Controle Bancário e Conferência de Saldo — Design Arquitetural

> **Autor:** Aria (@architect)
> **Data:** 2026-07-29 · **Revisado:** 2026-07-29 (ratificação dos desvios do Epic 8 — ver abaixo)
> **Status:** Ratificado. Onda 0 + Onda 1 liberadas pelo fundador (epic §9 F2); §10 traz as pendências
> que **não** bloqueiam essas duas ondas.
> **Tipo:** Design de arquitetura. **NÃO é** implementação, story nem migration. Os blocos de schema
> são **ilustrativos** (documentam intenção, não são código para colar) — **exceto** os que estão
> marcados `CONTRATO`: §1.3.1 (vocabulários de procedência), §3.1.1 (assinaturas de saldo derivado),
> §5.3 (`CompletenessInput`) e §6.1 (`CashProjection`/`Runway`/`ProjectionWindow`), que foram fixados
> na ratificação porque duas stories em paralelo precisam concordar sobre eles.
> **Parecer de ratificação (2026-07-29):**
> [`controle-bancario-design-ratificacao.md`](controle-bancario-design-ratificacao.md) — julga sete
> desvios levantados pelo @sm e registra o que mudou neste documento e por quê.
>
> ---
>
> ⚠️ **SUPERSEDE PARCIAL (2026-07-30) — leia antes de usar a §8 (faseamento).**
> [`controle-bancario-onda2-design.md`](controle-bancario-onda2-design.md) corrige uma **falha de
> escopo deste documento**: aqui só foi modelado o fluxo **extrato → sistema** (importar e casar).
> A direção **sistema → banco** — a baixa de Contas a Pagar, o recebimento fora do trilho, o
> rendimento e o payout gerando o movimento bancário — **não foi modelada**, embora seja a que já
> tem os dados. Consequência: a §6.7 rebaixou `payables.bank_account_id` a "otimização de match,
> onda posterior" quando ele é a **origem do movimento**, e o razão bancário nasce vazio.
> **O que continua valendo integralmente:** §1 (Regra dos Planos e os dois eixos), §2 (modelo), §3
> (saldo derivado), §5 (conferência), §7 (rastreabilidade tributária).
> **O que está SUPERSEDIDO:** a §6.7 (a coluna é obrigatória, não opcional), a §3.4(b) e a §6.6
> (mudam de onda) e **a ordem das ondas da §8** — ver a §10 do documento novo.
>
> ---
>
> **ADR associado:** [`docs/decisions/0003-controle-bancario-nativo.md`](../decisions/0003-controle-bancario-nativo.md)
> **Estudo antecedente:** [`docs/research/2026-07-29-conta-bancaria-conciliacao-brainstorm.md`](../research/2026-07-29-conta-bancaria-conciliacao-brainstorm.md)

---

## 0. Enquadramento — o que está decidido e o que este documento decide

**Decidido pelo fundador (não reabrir):** o e1p vai ter controle nativo de conta bancária com
conferência de saldo, **sem depender de agregador Open Finance** (Pluggy/Belvo/Klavi/Celcoin estão
fora por decisão, não por preço). Arquivo (OFX/CSV) não é "serviço de terceiro" e é aceitável.

**Falas do fundador que são requisitos deste design** (verbatim, rastreabilidade Art. IV):

| # | Fala | Onde este design responde |
|---|---|---|
| R1 | *"a questão é o contas a pagar e o controle bancário; de saldo batendo é uma conferência para achar possível furos"* | §5 (a conferência), §2 (movimento bancário), §4 (pipeline) |
| R2 | *"com a entrada da nova legislação tributária, teremos que ter os dados cada vez mais fiéis de onde vem e para onde vai o dinheiro"* | §7 (rastreabilidade tributária) |
| R3 | *"e depois com a conta de aplicação entrando neste processo, não apenas o lançamento do quanto rendeu"* | §3.4 (conta de investimento), §3.5 (transferência), §6.2 (migração do `principal_cents`) |
| R4 | *"não podemos ficar contando com serviços de terceiros"* | ADR 0003, §4 (parser plugável, zero dependência de rede) |

**O que este documento decide (o COMO):** a separação conceitual entre dinheiro da plataforma e
dinheiro do usuário, o modelo de dados, o pipeline de importação sem terceiros, o relatório de
conferência, os impactos no que já existe, os campos de rastreabilidade tributária e o faseamento.

**Restrições herdadas que o design respeita como lei:**

- **Regra de Ouro nº 1** — toda tabela de negócio carrega `tenant_id` + RLS `FORCE`, nenhuma query
  filtra tenant manualmente.
- **Regra de Ouro nº 2** — anonimizador antes da IA. Extrato bancário carrega nome e documento de
  contraparte: é PII de primeira classe.
- **Regra de Ouro nº 4** — custo importa. Este design tem **R$ 0 de custo recorrente novo**.
- **Dinheiro em centavos `BigInteger`.** Nunca float.
- **Caixa vs. competência** (docstrings de `payables/models.py` e `receivables/models.py`): fluxo de
  caixa usa `paid_at`; DRE/lucratividade usam `competence_date`. **Nunca inverter.**
- **Teto de simplicidade** (§6.3 do estudo, que continua válido): *"o e1p pode pedir ao usuário que
  ele CONFIRME um número. Não pode pedir que ele CONSTRUA um número."* Toda tela deste design é
  avaliada contra esse critério na §9.

**O que este design deliberadamente NÃO faz** (herdado do estudo, §8 "o que não fazer"):

- Não cria item de menu chamado "Conciliação bancária" (§5.4 — o rótulo é o problema).
- Não soma saldo de plataforma com saldo bancário sem rótulo (§1.3 — regra testável).
- Não entrega, como caminho principal, uma tela de 43 linhas de extrato com checkbox. A tela
  principal é a **divergência em uma frase**; o extrato linha a linha é a tela de investigação,
  alcançada a partir do sinal, não a partir do menu.

---

## 1. A distinção conceitual — dois universos de dinheiro

### 1.1 Os planos

O estudo já nomeou três planos de dinheiro; este design os fixa como vocabulário do código.

| Plano | O que é | Tabela canônica | Quem é o dono do dinheiro |
|---|---|---|---|
| **1 — Plataforma** | Dinheiro que passou pelo trilho e1p, com split 40/30/20 aplicado. Estados `pending`/`available`/`withdrawn`/`refunded` | `transactions` (+ `platform_earnings`, global) | Está **na e1p**; é passivo da plataforma com o usuário |
| **2 — Negócio** | Direitos e obrigações: o que vou receber, o que devo pagar, classificado por plano de contas, em competência e em caixa | `charges` + `payables` + `chart_accounts` | Nem um nem outro — é promessa, não dinheiro |
| **3 — Bancário** | O extrato real da conta do usuário. A única verdade sobre quanto dinheiro existe | **`bank_accounts` + `bank_transactions` (NOVO)** | Está **no banco do usuário** |

**O bug de hoje é exatamente uma confusão de plano.** `financial_intelligence/projection.py:177`:

```python
saldo_inicial = int(wallet_service.wallet_summary(db)["available_cents"])
```

`available_cents` é a soma de `net_cents` das `Transaction` com `status='available'` — um número do
**plano 1**, usado como se fosse do **plano 3**. Não existe configuração de uso em que ele esteja
certo: se o usuário nunca saca, ele acumula todo o faturamento líquido histórico e nunca diminui
quando uma conta é paga (porque `payables` **não toca a Carteira** por design — `payables/models.py:4`);
se o usuário saca tudo, ele vai a zero enquanto o dinheiro está na conta do banco dele.

### 1.2 Onde os planos se tocam LEGITIMAMENTE

Existe **exatamente um** ponto de contato real, e ele é uma transferência física de dinheiro:

```
  wallet.request_payout()          →  o dinheiro sai da e1p e entra na conta do usuário
  Transaction.status = withdrawn      (plano 1 → plano 3)
```

Hoje `wallet/service.py:227` só marca `withdrawn` — não existe integração bancária nem KYC. Mesmo
assim, o **evento contábil** existe: a partir do momento em que o payout é registrado, aquele
dinheiro deixou de ser "na plataforma" e passou a ser "no banco" (mesmo que o TED/Pix real ainda
esteja a caminho). Este design modela esse evento como um `bank_transfer` de `kind='wallet_payout'`
(§3.5) — o único write que atravessa a fronteira.

Consequência de produto: enquanto o payout real não existir, o dinheiro `available` fica **preso no
plano 1** e o "caixa total do usuário" é a soma rotulada dos dois planos:

```
Na plataforma (a liberar/sacar):  pending_cents + available_cents      [plano 1]
Na sua conta (banco):             Σ saldo derivado das bank_accounts   [plano 3]
Caixa total:                      os dois somados, SEMPRE com os rótulos visíveis
```

### 1.3 A regra que impede os planos de se misturarem de novo

> **REGRA DOS PLANOS (normativa, testável).**
> **(a)** Nenhum cálculo de saldo bancário pode ler `transactions`, e nenhum cálculo de saldo de
> carteira pode ler `bank_transactions`. As duas somas nunca aparecem no mesmo campo numérico.
> **(b)** A dependência entre os módulos é **unidirecional**: `app.modules.bank` **pode** importar
> `app.modules.wallet`; `app.modules.wallet` **nunca** importa `app.modules.bank`. O ponto de
> contato (§1.2) vive no lado `bank`.
> **(c)** Todo campo de API que carrega um valor monetário de saldo declara **de qual plano de
> dinheiro** ele vem, num campo irmão `*_origem` com valor em
> `{"plataforma", "banco", "misto", "indisponivel"}`. Nenhum número de saldo trafega sem procedência.

#### 1.3.1 Os DOIS eixos de procedência — correção de incoerência do próprio design

> **Ratificado em 2026-07-29** (ver `controle-bancario-design-ratificacao.md`, D-3). A primeira versão
> deste documento listava três vocabulários **incompatíveis** para `*_origem` em três seções: §1.3c
> (`{plataforma, banco, declarado, indisponivel}`), §6.1 (`{plataforma, banco, misto, indisponivel}`)
> e §5.1 (`{declarado, extrato, indisponivel}`) — mais um quarto, `manual|ofx`, já cravado na coluna
> `bank_balance_checkpoints.origin` da §2.4. Não era descuido de redação: eram **dois conceitos
> distintos achatados num só campo**. Cinco valores num único campo escondiam a confusão; dois campos
> a resolvem.

| | **Eixo A — plano** | **Eixo B — porta de entrada** |
|---|---|---|
| **Pergunta que responde** | *"De qual plano de dinheiro (§1.1) este número vem?"* | *"Por qual porta este saldo **externo** entrou no e1p?"* |
| **Sufixo canônico do campo** | `*_origem` | `*_fonte` |
| **Vocabulário** | `plataforma` \| `banco` \| `misto` \| `indisponivel` | os valores da coluna `bank_balance_checkpoints.origin`: `manual` \| `ofx` |
| **Onde vive o vocabulário** | `app/core/money_planes.py` (`ORIGEM_*`, `ORIGENS`) | `app/modules/bank/models.py` (`ORIGIN_MANUAL`, `ORIGIN_OFX`, `ORIGINS`) — ao lado da coluna que ele descreve |
| **Por que em `core/`** | é consumido por `financial_intelligence` **e** por `bank`, e nenhum dos dois pode importar o outro nessa direção | não precisa: só `bank` (e quem lê o relatório dele) conhece checkpoint |
| **Obrigatório em** | todo campo de saldo, sem exceção (§1.3c) | só em saldo **atestado por terceiro** (hoje: o checkpoint) |

**`declarado` e `extrato` estão REVOGADOS como valores de `*_origem`.** Eles eram os valores do eixo B
vestidos de eixo A: `declarado` ≡ `manual`, `extrato` ≡ `ofx`. Manter as duas grafias para a mesma
coisa obrigaria uma camada de tradução (`origin='manual'` → `origem='declarado'`) que existe apenas
para satisfazer um documento incoerente — e toda tradução silenciosa entre dois vocabulários do mesmo
conceito é uma fábrica de bug de manutenção. **`ORIGENS` tem quatro valores, não cinco.**

**Consequência para a conferência (§5.1):** `saldo_banco` e `saldo_sistema` são **ambos** do plano 3 —
o eixo A é degenerado (`banco` nos dois) e não informa nada ali. O que distingue os dois números é o
**método de estabelecimento** (atestado pelo banco × derivado pelo e1p), e isso já está nos **nomes**
dos campos. O eixo B é que carrega informação nova, e por isso ganha campo próprio.

**Como isso vira teste** (não é convenção, é gate):

1. `tests/test_money_planes.py::test_wallet_nao_importa_bank` — varre `apps/api/app/modules/wallet/`
   procurando `from app.modules.bank` / `import app.modules.bank`. Falha se achar. É o mesmo estilo
   de teste estrutural já usado em `tests/test_tenancy_guard.py` (allowlist de acesso fora da RLS).
2. `test_bank_balance_ignora_wallet` — cria transações na Carteira e verifica que o saldo bancário
   derivado não muda em 1 centavo.
3. `test_wallet_summary_ignora_bank` — o recíproco.
4. `test_projecao_declara_origem_do_saldo_inicial` — `CashProjection` sempre traz
   `saldo_inicial_origem` preenchido (Onda 0, §6.1).
5. `test_todo_saldo_declara_origem` — teste de **contrato**, não de cenário: varre os schemas de saída
   que expõem saldo e exige, para cada campo de saldo, o irmão `*_origem` com valor em `ORIGENS`.
   É este teste que torna o item (c) auditável **sem exceções** — e é por isso que o `*_origem` da
   conferência é mantido mesmo sendo degenerado ali (§1.3.1): uma exceção "porque não informa nada
   neste caso" transforma um invariante mecânico num julgamento caso a caso, e aí ele para de valer.

Sem (1) o resto degrada por acidente: basta uma story futura importar o módulo errado para
recriar o §1.1 numa forma nova.

---

## 2. Modelo de dados

Convenções aplicadas em todas as tabelas abaixo, sem exceção:

- `Base, TenantMixin, TimestampMixin` (`app/db/base.py`), `id: String(36)` UUID gerado por `_uuid`.
- Migration **estritamente aditiva**, `ENABLE` + `FORCE ROW LEVEL SECURITY`, policy
  `tenant_isolation` com `USING` e `WITH CHECK` (padrão do `_enable_rls` da migration 0049).
- **Sem FK dura** entre tabelas de negócio — referência solta, integridade por RLS + validação no
  service (padrão do projeto: `charges.client_id`, `payables.contract_id`, `cost_center_id`).
- Dinheiro em `BigInteger` (centavos).
- **Numeração de migration: este design NÃO fixa número de revision.** Head na data do design:
  `0057_device_tokens.py` (reconfirmado 2026-07-29). A única lei é **encadear linearmente após o head
  REAL no momento da implementação** — a lição já escrita na docstring da `0049_investments.py`:
  encadear num revision antigo cria múltiplos heads e `alembic upgrade head` falha.
  > **Ratificado em 2026-07-29** (D-6): a versão anterior deste documento prescrevia *"uma migration
  > por onda"* e a §8 mapeava `Onda 1 → 0058`, `Onda 2 → 0059`, etc. **Errado nos dois pontos.** A
  > granularidade real é **uma migration por story que cria tabela** — a Onda 1 sozinha cria três
  > tabelas em três stories (`bank_accounts`, `bank_transactions`, `bank_balance_checkpoints`) e
  > portanto consome **três** revisions. A coluna "Migration" da §8 vale como **ordem de dependência**,
  > nunca como identificador. Um design que carimba número de revision fica desatualizado no primeiro
  > merge de qualquer outra frente de trabalho, e o custo de acreditar nele é um `multiple heads` em
  > produção.

> ⚠️ **Armadilha conhecida do backfill sob FORCE RLS** (documentada em `migrations/versions/0046_ledger_classification.py`):
> a migration roda como o papel dono non-superuser `e1p_app` **sem** a GUC `app.current_tenant_id`,
> então qualquer `UPDATE` direto numa tabela com FORCE RLS é filtrado a **zero linhas**, em silêncio.
> Toda migration deste design que faça backfill (§6.2) precisa desabilitar a RLS na janela do
> backfill e reabilitar depois, como a 0046 faz. Isso não aparece no SQLite dos testes unitários.

### 2.1 `bank_accounts` — a conta do usuário

```sql
-- ILUSTRATIVO
CREATE TABLE bank_accounts (
    id                     VARCHAR(36)  PRIMARY KEY,
    tenant_id              VARCHAR(36)  NOT NULL,
    name                   VARCHAR(120) NOT NULL,          -- "Itaú PJ", "Aplicação CDB"
    kind                   VARCHAR(16)  NOT NULL,          -- checking|savings|investment|cash|platform_wallet
    institution            VARCHAR(120) NOT NULL DEFAULT '',   -- nome do banco (livre)
    institution_code       VARCHAR(8)   NOT NULL DEFAULT '',   -- COMPE/ISPB quando o OFX trouxer (<BANKID>)
    branch                 VARCHAR(16)  NOT NULL DEFAULT '',   -- agência
    number                 VARCHAR(32)  NOT NULL DEFAULT '',   -- conta (<ACCTID> do OFX)
    holder_document        VARCHAR(20)  NOT NULL DEFAULT '',   -- CPF/CNPJ do titular (§7)
    pix_key                VARCHAR(140) NOT NULL DEFAULT '',
    opening_balance_cents  BIGINT       NOT NULL DEFAULT 0,    -- saldo na data de abertura no e1p
    opening_date           DATE         NOT NULL,              -- a partir de quando o e1p conhece esta conta
    is_primary             BOOLEAN      NOT NULL DEFAULT FALSE,-- conta padrão de débito/crédito
    archived_at            TIMESTAMPTZ  NULL,                  -- arquivar, nunca deletar (padrão chart_accounts)
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_bank_accounts_tenant_id ON bank_accounts (tenant_id);
CREATE UNIQUE INDEX uq_bank_accounts_tenant_ident
    ON bank_accounts (tenant_id, institution_code, branch, number)
    WHERE number <> '';   -- identidade bancária única quando informada; conta "caixa" sem número não colide
```

**Decisões e trade-offs:**

- **`opening_balance_cents` + `opening_date` são o coração da usabilidade.** Os bancos brasileiros
  entregam tipicamente só os **últimos 60 dias** de extrato (`[CONFIRMADO]` no estudo §4.5). Sem
  saldo de abertura, o saldo derivado começaria errado para sempre. Com ele, o usuário **confirma um
  número** que está a 5 segundos do polegar dele (app do banco) e o sistema anda a partir dali —
  dentro do teto de simplicidade.
- **`archived_at` em vez de delete** — mesmo padrão de `chart_accounts`. Conta encerrada não pode
  levar o histórico de movimentos junto; a auditoria é o produto.
- **`kind='platform_wallet'`**: *permitido, mas não criado automaticamente.* Modelar a Carteira Asaas
  como uma `bank_account` é tentador (unificaria a visão de "onde está meu dinheiro"), e
  **este design rejeita fazer isso agora**: o saldo da carteira é derivado de `transactions` com
  regras de split e estado próprio, e materializá-lo como conta bancária violaria a Regra dos Planos
  (§1.3a) — passaria a existir um caminho em que somar as duas coisas é fácil. O `kind` fica
  reservado no vocabulário para o dia em que houver payout real e a carteira virar de fato um saldo
  fungível; até lá, ninguém escreve nele. **[SUPOSIÇÃO minha, marcada:** o custo de reservar o valor
  no vocabulário é zero; o custo de descobrir depois que o enum era fechado é uma migration.**]**
- **`uq` parcial em `(tenant_id, institution_code, branch, number)`** evita a mesma conta cadastrada
  duas vezes (que produziria divergência crônica na conferência). O `WHERE number <> ''` deixa passar
  contas informais ("Caixinha") sem número.
- **Índice único e RLS:** um índice único é global, não respeita RLS — por isso `tenant_id` **é** a
  primeira coluna da constraint. Sem ela, o tenant B não conseguiria cadastrar uma conta com o mesmo
  número que o tenant A e receberia um 409 inexplicável (vazamento de existência, além de bug).

### 2.2 `bank_transactions` — a linha de extrato

```sql
-- ILUSTRATIVO
CREATE TABLE bank_transactions (
    id                    VARCHAR(36)  PRIMARY KEY,
    tenant_id             VARCHAR(36)  NOT NULL,
    bank_account_id       VARCHAR(36)  NOT NULL,      -- ref. solta (sem FK dura)
    posted_at             DATE         NOT NULL,      -- data do movimento no banco (<DTPOSTED>)
    amount_cents          BIGINT       NOT NULL,      -- COM SINAL: + crédito, − débito
    raw_description       TEXT         NOT NULL DEFAULT '',   -- <MEMO>/<NAME> cru, NUNCA editado
    user_description      TEXT         NOT NULL DEFAULT '',   -- rótulo do usuário/IA (editável)
    fitid                 VARCHAR(255) NULL,          -- <FITID>: id único do banco, quando existir
    dedup_hash            VARCHAR(64)  NOT NULL,      -- sha256, ver §4.4
    balance_after_cents   BIGINT       NULL,          -- saldo após o movimento, se o arquivo trouxer
    -- contraparte (§7 rastreabilidade tributária) — TODOS opcionais
    counterparty_name     VARCHAR(160) NOT NULL DEFAULT '',
    counterparty_document VARCHAR(20)  NOT NULL DEFAULT '',   -- CPF/CNPJ só dígitos
    pix_end_to_end_id     VARCHAR(40)  NULL,
    operation_nature      VARCHAR(24)  NULL,          -- ver §7.2
    fiscal_document_ref   VARCHAR(64)  NULL,          -- nº/chave da NFS-e etc.
    -- origem e estado
    source                VARCHAR(16)  NOT NULL,      -- ofx|csv|manual|transfer|yield|payout
    import_batch_id       VARCHAR(36)  NULL,
    transfer_id           VARCHAR(36)  NULL,          -- preenchido quando source in (transfer,yield,payout)
    status                VARCHAR(16)  NOT NULL DEFAULT 'unmatched',  -- unmatched|partial|matched|ignored
    ignored_reason        VARCHAR(120) NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_bank_transactions_tenant_id ON bank_transactions (tenant_id);
CREATE INDEX ix_bank_transactions_account_date
    ON bank_transactions (tenant_id, bank_account_id, posted_at);
CREATE INDEX ix_bank_transactions_status
    ON bank_transactions (tenant_id, status) WHERE status <> 'matched';   -- a conferência só olha o que não bateu
CREATE UNIQUE INDEX uq_bank_transactions_dedup
    ON bank_transactions (tenant_id, bank_account_id, dedup_hash);
```

**Decisões e trade-offs:**

- **`amount_cents` com sinal, não um par (`kind`, valor absoluto).** Um extrato é uma sequência
  assinada; somar para obter saldo é `SUM(amount_cents)` puro, sem `CASE`. O custo é lembrar que o
  sinal aqui **não** segue a convenção canônica da DRE ("o sinal vem da tabela de origem" —
  `dre.py`), porque aqui *uma mesma tabela* carrega entradas e saídas. Isso precisa estar na
  docstring do modelo, do mesmo jeito que a regra caixa/competência está nas de `payables`/`charges`.
- **`raw_description` é imutável.** É a prova documental do que o banco disse. Qualquer
  reclassificação (do usuário ou da IA) vai em `user_description`. Sem isso, a auditoria — que é o
  ponto do produto — perde a fonte.
- **`fitid` nullable + `dedup_hash` NOT NULL.** O FITID é o mecanismo canônico de idempotência do
  OFX, mas CSV não tem, lançamento manual não tem, e há relatos de bancos que reciclam FITID entre
  arquivos. `dedup_hash` é o mecanismo **universal** (§4.4) e é ele que carrega a constraint única.
  O `fitid` fica guardado para diagnóstico e para o dia em que quisermos detectar reciclagem.
- **`status` é derivável de `bank_reconciliations`, e mesmo assim é materializado.** É a única
  materialização deste design, e é deliberada: a conferência (§5) precisa varrer "tudo que não
  bateu" num índice parcial. Recalcular por `NOT EXISTS` a cada leitura é correto mas transforma o
  índice em inútil. Mitigação de consistência: `status` **só** é escrito pela função
  `_refresh_status(bank_transaction_id)` do service de conciliação, chamada em toda mutação de
  vínculo, na mesma transação — e existe um comando de auditoria (`python -m app.scripts.bank_audit`)
  que recalcula e reporta divergência sem corrigir em silêncio.
- **`transfer_id` sem FK dura**, coerente com o resto do projeto.

### 2.3 `bank_reconciliations` — o vínculo (tabela de ligação, não coluna)

```sql
-- ILUSTRATIVO
CREATE TABLE bank_reconciliations (
    id                   VARCHAR(36) PRIMARY KEY,
    tenant_id            VARCHAR(36) NOT NULL,
    bank_transaction_id  VARCHAR(36) NOT NULL,
    target_type          VARCHAR(16) NOT NULL,   -- payable|charge|transfer|wallet_payout
    target_id            VARCHAR(36) NOT NULL,
    amount_cents         BIGINT      NOT NULL,   -- parcela ALOCADA, mesmo sinal do movimento
    confidence           SMALLINT    NULL,       -- 0..100, quando veio de regra/IA
    suggested_by         VARCHAR(8)  NOT NULL DEFAULT 'user',  -- user|rule|ai
    confirmed_at         TIMESTAMPTZ NULL,       -- NULL = SUGESTÃO, não vínculo
    confirmed_by         VARCHAR(36) NULL,       -- user_id de quem confirmou
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_bank_reconciliations_tenant_id ON bank_reconciliations (tenant_id);
CREATE INDEX ix_bank_recon_movement ON bank_reconciliations (tenant_id, bank_transaction_id);
CREATE INDEX ix_bank_recon_target   ON bank_reconciliations (tenant_id, target_type, target_id);
CREATE UNIQUE INDEX uq_bank_recon_pair
    ON bank_reconciliations (tenant_id, bank_transaction_id, target_type, target_id);
```

**Decisão: tabela de ligação, não coluna no movimento. Por quê:**

| Critério | Coluna (`payable_id` no movimento) | **Tabela de ligação (escolhida)** |
|---|---|---|
| 1 movimento quita 2 contas (Pix único para 2 boletos) | Impossível | Duas linhas, `amount_cents` somando ao total |
| 1 conta paga em 2 movimentos (entrada + parcela) | Impossível | Duas linhas apontando ao mesmo `target` |
| Sugestão sem confirmação | Precisaria de uma 2ª coluna de estado | `confirmed_at IS NULL` |
| Quem confirmou, quando, com que confiança | Precisaria de 4 colunas no movimento | Nativo |
| Custo | — | 1 join a mais; 1 tabela a mais |

O caso "um pagamento que quita duas contas" **não é hipotético** neste produto: a Fila de Pagamentos
(`FilaPagamentosPage`) existe justamente para agrupar o que vence no dia, e o comportamento natural
do usuário é pagar tudo junto. Uma coluna condenaria esse caso a ficar eternamente "sem
contrapartida" na conferência — ou seja, o furo falso mais comum seria criado pelo próprio design.

**Invariante de alocação** (validado no service, não no banco):

```
Σ |amount_cents| dos vínculos CONFIRMADOS de um movimento  ≤  |bank_transaction.amount_cents|
```

Não vira `CHECK` porque depende de agregação sobre outra tabela. Vira: guarda no service +
teste + o `bank_audit` da §2.2. Igual à decisão do projeto de não usar FK dura: **a integridade
mora no service, sob RLS.** Se a soma for menor que o total, o movimento fica `partial` — e
`partial` é um estado legítimo e visível (o furo é o resto).

**Guardas de segurança do vínculo:**

- Movimento com `source in ('transfer','yield','payout')` **não pode** ter `target_type in
  ('payable','charge')`. Isso é o que impede um resgate de aplicação de virar receita fantasma por
  vínculo acidental (§3.5).
- Sinal: vínculo com `target_type='payable'` exige `amount_cents < 0`; com `'charge'` exige
  `> 0`. Um crédito no extrato nunca pode quitar uma despesa.

### 2.4 `bank_balance_checkpoints` — a verdade externa

```sql
-- ILUSTRATIVO
CREATE TABLE bank_balance_checkpoints (
    id               VARCHAR(36) PRIMARY KEY,
    tenant_id        VARCHAR(36) NOT NULL,
    bank_account_id  VARCHAR(36) NOT NULL,
    reference_date   DATE        NOT NULL,   -- "o saldo era este NO FIM deste dia"
    balance_cents    BIGINT      NOT NULL,
    origin           VARCHAR(12) NOT NULL,   -- manual|ofx  (LEDGERBAL do arquivo)
    import_batch_id  VARCHAR(36) NULL,
    created_by       VARCHAR(36) NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_bank_checkpoints_tenant_id ON bank_balance_checkpoints (tenant_id);
CREATE UNIQUE INDEX uq_bank_checkpoint_day
    ON bank_balance_checkpoints (tenant_id, bank_account_id, reference_date, origin);
```

Esta é a tabela que **torna a conferência possível sem importação nenhuma**. É a Opção B do estudo
(saldo declarado) preservada dentro do desenho maior — e é o motivo de a Onda 1 (§8) entregar valor
sozinha, antes de qualquer parser existir. `origin='ofx'` guarda o `<LEDGERBAL>` do arquivo
importado, que é o mesmo conceito vindo de outra porta.

### 2.5 `bank_import_batches` — o lote de importação

```sql
-- ILUSTRATIVO
CREATE TABLE bank_import_batches (
    id               VARCHAR(36) PRIMARY KEY,
    tenant_id        VARCHAR(36) NOT NULL,
    bank_account_id  VARCHAR(36) NOT NULL,
    filename         VARCHAR(255) NOT NULL,
    file_sha256      VARCHAR(64)  NOT NULL,   -- reimportar o MESMO arquivo é detectado na hora
    parser_id        VARCHAR(32)  NOT NULL,   -- ofx-sgml|ofx-xml|csv:<layout_id>
    encoding         VARCHAR(24)  NOT NULL DEFAULT '',
    period_start     DATE         NULL,
    period_end       DATE         NULL,
    lines_total      INTEGER      NOT NULL DEFAULT 0,
    lines_new        INTEGER      NOT NULL DEFAULT 0,
    lines_duplicate  INTEGER      NOT NULL DEFAULT 0,
    lines_enriched   INTEGER      NOT NULL DEFAULT 0,   -- casaram com movimento já existente (§4.5)
    status           VARCHAR(12)  NOT NULL,   -- parsed|applied|failed
    error_message    TEXT         NOT NULL DEFAULT '',
    created_by       VARCHAR(36)  NULL,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX ix_bank_import_batches_tenant_id ON bank_import_batches (tenant_id);
```

O arquivo em si vai para `attachments` com `owner_type='bank_import'`, `owner_id=<batch_id>` —
reusa `core/storage.py` (S3 com fallback Postgres) sem inventar caminho novo, e mantém a prova
documental da importação.

### 2.6 `bank_transfers` — transferência entre contas próprias

```sql
-- ILUSTRATIVO
CREATE TABLE bank_transfers (
    id               VARCHAR(36) PRIMARY KEY,
    tenant_id        VARCHAR(36) NOT NULL,
    from_account_id  VARCHAR(36) NULL,   -- NULL = origem fora do e1p (ex.: payout da carteira)
    to_account_id    VARCHAR(36) NULL,   -- NULL = destino fora do e1p (ex.: saque para conta não cadastrada)
    amount_cents     BIGINT      NOT NULL,   -- SEMPRE positivo; o sinal vive nos movimentos gerados
    transfer_date    DATE        NOT NULL,
    kind             VARCHAR(20) NOT NULL,   -- own_transfer|investment_in|investment_out|wallet_payout
    description      TEXT        NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_bank_transfers_tenant_id ON bank_transfers (tenant_id);
CREATE INDEX ix_bank_transfers_date ON bank_transfers (tenant_id, transfer_date);
```

Ver §3.5 para a semântica completa (é o coração do requisito R3).

### 2.7 Diagrama de entidades

```
                        ┌──────────────────────────┐
                        │      bank_accounts       │  RLS
                        │  kind: checking|savings| │
                        │        investment|cash   │
                        │  opening_balance/date    │
                        └──────────┬───────────────┘
                                   │ 1                          ┌─────────────────────────┐
                     ┌─────────────┼──────────────┬─────────────│  investment_accounts    │ RLS
                     │ N           │ N            │ N        1:1│  (FACETA de produto)    │
        ┌────────────▼─────┐  ┌────▼───────────┐  │             │  index_rate_label       │
        │ bank_transactions│  │bank_balance_   │  │             │  accrued_yield_cents    │
        │ RLS              │  │  checkpoints   │  │             │  bank_account_id  ◄─────┘
        │ posted_at        │  │ RLS            │  │             └─────────────────────────┘
        │ amount_cents (±) │  │ reference_date │  │                (principal vira DERIVADO)
        │ raw_description  │  │ balance_cents  │  │
        │ fitid/dedup_hash │  │ origin         │  │
        │ counterparty_*   │  └────────────────┘  │
        │ source/status    │                      │
        └───┬──────────┬───┘                      │
            │ 1        │ N                        │ N
            │          └──────────────┐   ┌───────▼──────────────┐
            │ N                       │   │   bank_transfers     │ RLS
   ┌────────▼──────────────┐          │   │ from/to_account_id   │
   │ bank_reconciliations  │ RLS      │   │ kind: own_transfer|  │
   │ target_type/target_id │          │   │  investment_in|out|  │
   │ amount_cents          │          └───┤  wallet_payout       │
   │ confirmed_at (NULL=   │   gera 2     └──────────────────────┘
   │   sugestão)           │   movimentos
   └───┬───────┬───────┬───┘
       │       │       │                 ┌──────────────────────┐
       │       │       └────────────────►│  bank_import_batches │ RLS
       │       │        (import_batch)   │  file_sha256/parser  │
       │       │                         └──────────────────────┘
       ▼       ▼
  ┌─────────┐ ┌─────────┐        ══════════ FRONTEIRA DOS PLANOS ══════════
  │payables │ │ charges │  ◄── plano 2 (negócio), JÁ EXISTEM, intocados
  └─────────┘ └────┬────┘
                   │ mark_paid
                   ▼
             ┌──────────────┐  plano 1 (plataforma) — JÁ EXISTE
             │ transactions │  split 40/30/20 → platform_earnings (global)
             └──────┬───────┘
                    │ request_payout  ── ÚNICO ponto de contato legítimo (§1.2)
                    └──────────────────► bank_transfers(kind='wallet_payout')
```

---

## 3. Semântica das entidades — as decisões que importam

### 3.1 Saldo: derivado, não materializado

**Decisão: o saldo é DERIVADO.**

```
saldo(conta, até_data) = opening_balance_cents
                       + SUM(bank_transactions.amount_cents
                             WHERE bank_account_id = conta
                               AND posted_at > opening_date
                               AND posted_at <= até_data
                               AND status <> 'ignored')
```

| Eixo | Derivado (escolhido) | Materializado (rejeitado) |
|---|---|---|
| **Consistência** | Impossível divergir dos próprios movimentos | Pode divergir; aí existem dois números e nenhuma forma de saber qual está certo |
| **Auditoria** | "de onde vem esse número" = a própria lista | Precisa de um ledger paralelo para explicar o saldo |
| **Precisão** | Exata — centavo inteiro, `SUM` de `BIGINT`, sem arredondamento | Igual, mas com risco de write perdido |
| **Performance** | `SUM` sob índice `(tenant_id, bank_account_id, posted_at)` | `O(1)` |
| **Custo de correção** | Nenhum — corrigir um movimento corrige o saldo | Recalcular tudo, e decidir se o saldo antigo estava errado ou o movimento |

**Por que a performance não é argumento aqui:** o usuário-alvo é uma empresa de 1 pessoa. O estudo
estimou 8–20 saídas/mês `[ESTIMATIVA]`; some entradas e chegue a ~40 movimentos/mês = ~500/ano =
~5.000 em dez anos, por conta, por tenant. `SUM` sobre 5.000 linhas indexadas é ruído. **Materializar
saldo aqui seria otimizar o eixo errado e pagar com a única propriedade que o produto está vendendo:
que o número é conferível.**

#### 3.1.1 Assinaturas canônicas do saldo derivado — e a que a conferência NÃO pode usar

> **Ratificado em 2026-07-29** (D-4). Existem **duas** funções de saldo derivado, com propósitos
> distintos, e confundi-las reintroduz exatamente o erro que a §5.1 manda recusar.

```python
# app/modules/bank/service.py — CANÔNICO
def derived_balance(db, *, bank_account_id: str, until: date | None = None) -> int: ...
#   UMA conta, UMA data. `until` é DATE (nunca datetime) e é INCLUSIVO. É a única implementação
#   da fórmula da §3.1 no repositório inteiro — uma segunda torna a Regra dos Planos §1.3a
#   inauditável (o `dedup-checker` deve reprovar).

def derived_balances_as_of(
    db, *, as_of: date | None = None, include_archived: bool = False
) -> dict[str, int]: ...
#   TODAS as contas, UMA data comum — para TELA DE LISTA ("Contas & Saldos", §5.4), onde o usuário
#   quer o saldo de hoje de tudo. PROIBIDO na conferência (ver abaixo).
```

**A conferência (§5.1) usa laço de `derived_balance` por conta, com o `until` de cada conta.** Não é
concessão de performance: é correção. A conferência tem **uma data de referência por conta** — o
`reference_date` do checkpoint daquela conta —, e um `as_of` comum compararia o saldo do banco de uma
data com o saldo do sistema de outra, que é *o* erro clássico desta classe de relatório e que a §5.1
manda o service **recusar**. Escala real: uma empresa de 1 pessoa com um punhado de contas; N queries
sob índice `(tenant_id, bank_account_id, posted_at)` é ruído (mesmo argumento do saldo derivado acima).

**Por que não trocar a assinatura por um mapa `{conta: data}`:** porque o ganho da versão em lote é
fazer **uma** passada no banco, e com uma data por conta isso degenera em N queries (ou num `CASE`
por conta que é menos legível que o laço). O mapa custaria complexidade para entregar zero — e
convidaria o chamador a construí-lo a partir de uma data única, que é o bug de novo. **A função em
lote existe para o caso em que a data É uma só; a conferência não é esse caso.**

⚠️ **Nome, não só assinatura:** a função em lote **não** se chama `derived_balances` (diferença de um
`s` final em relação à correta, para um erro cujo sintoma é uma divergência falsa e silenciosa). O
`as_of` no nome e no parâmetro declara que há **uma** data para todas as contas.

Mitigação do único caso que dói (extrato de 10 anos, tela de saldo diário): `opening_balance_cents`
já funciona como ponto de corte, e se um dia doer, a resposta é um **checkpoint de corte** (mover o
`opening_date` para frente consolidando o passado), não um saldo materializado — a diferença é que o
checkpoint é auditável e explícito.

### 3.2 Conta de investimento: `kind` de conta bancária **com faceta de produto preservada**

**A decisão:** `investment_accounts` **não some** e **não vira** a fonte do dinheiro. Ela se torna a
**faceta de produto** (1:1) de uma `bank_accounts` com `kind='investment'`.

```
bank_accounts (kind='investment')   ── o DINHEIRO: saldo derivado, movimentos, conciliação
        ▲ 1:1
investment_accounts                 ── o PRODUTO: index_rate_label, accrued_yield_cents,
   + bank_account_id (NOVO)                        rentabilidade, tipo de aplicação
   - principal_cents (vira DERIVADO)
```

**Alternativas consideradas:**

| Alternativa | Prós | Contras | Veredito |
|---|---|---|---|
| **A. Absorver:** matar `investment_accounts`, tudo vira `bank_accounts` | Um conceito só | Perde `index_rate_label`/`accrued_yield_cents`/rentabilidade (Story 5.6 inteira: service, router, `InvestimentosPage.tsx`, testes, `diagnostics._investment_returns`). Poluiria `bank_accounts` com colunas que só uma minoria usa | **Rejeitada** — destrói capacidade entregue (regra "nunca perder capacidade") |
| **B. Manter separadas, sem vínculo** | Custo zero hoje | `principal_cents` continua digitado; aporte/resgate seguem invisíveis; o requisito R3 do fundador não é atendido | **Rejeitada** — é o status quo que motivou a missão |
| **C. Faceta 1:1 (escolhida)** | Semântica de dinheiro **uniforme** (transferência funciona igual para toda conta); `principal_cents` derivado; Story 5.6 continua viva; rentabilidade ganha denominador confiável | Duas tabelas para um conceito que o usuário vê como um; migração de dados necessária (§6.2) | **Escolhida** |

**Por que C e não A, dito sem diplomacia:** a diferença entre uma aplicação e uma conta corrente,
para o e1p, é **só um rótulo e um indexador** — o dinheiro se comporta igual (entra, sai, rende).
Modelar isso como duas hierarquias separadas foi o que criou o ponto cego. Mas a Story 5.6 entregou
rentabilidade real, com tela e testes, e a rentabilidade não é uma propriedade de conta bancária —
é de produto financeiro. Separar o *dinheiro* do *produto* é a única fatia que não perde nada.

Consequência: `investment_accounts.principal_cents` deixa de ser digitado e passa a ser
`SUM(investment_in) − SUM(investment_out)` — ou seja, o saldo derivado da conta bancária vinculada
**menos** o rendimento acumulado. Isso é a resposta direta ao R3: *"não apenas o lançamento do
quanto rendeu"*. Migração em §6.2.

### 3.3 O movimento bancário

Já especificado em §2.2. Três pontos que costumam ser subestimados:

1. **`balance_after_cents` é ouro quando existe.** Alguns arquivos trazem saldo corrente por linha.
   Quando trazem, a conferência ganha um segundo mecanismo de detecção: se
   `balance_after(linha_n) − balance_after(linha_{n−1}) ≠ amount(linha_n)`, **falta uma linha no
   arquivo** — furo detectado sem precisar de nada do sistema. Vale implementar como verificação
   barata, e degradar em silêncio quando o campo vier vazio.
2. **A contraparte só existe se o arquivo trouxer.** OFX tem `<NAME>` e `<MEMO>`; o CPF/CNPJ da
   contraparte de um Pix **pode ou não** vir no `<MEMO>`, dependendo do banco. **[DEPENDE DE
   @analyst]** — o design guarda os campos; o parser preenche o que houver; a IA pode *sugerir* a
   extração a partir do `raw_description` (§4.6), sempre com confirmação.
3. **`posted_at` é `DATE`, não `TIMESTAMP`.** O extrato bancário brasileiro é por dia. Guardar hora
   convidaria o bug de fuso que já mordeu a Agenda (`CLAUDE.md` §6.0: *"toda data de negócio que
   vira evento all-day deve ser comparada por data de calendário, nunca por horário local"*). Aqui a
   lição é aplicada na origem: o tipo não permite o erro.

### 3.4 Charge de rendimento — a pendência reservada, resolvida

`investments/service.py:27-37` reservou explicitamente ao fundador + @architect a decisão de
visibilidade/reconciliação da `Charge` sintética de rendimento. **Decidido:**

**(a) Ratifico o filtro que já está no código.** `receivables/service.py:82-89` (`_not_investment_yield`,
aplicado em `list_charges:270` e `summary:698`) exclui `external_ref LIKE 'investment:%'` das
superfícies de Contas a Receber. Isso está **correto e permanece**: "Recebido" na tela de Cobranças
é uma superfície de reconciliação de recebíveis **de cliente**; rendimento de aplicação não é
cobrança de ninguém. A DRE continua incluindo o lançamento (agrega `charges` por
`chart_account_id` + competência, sem passar por `list_charges`) — que é o comportamento certo,
porque rendimento **é** receita financeira do grupo FINANCEIRO.

**(b) O que faltava, e este design adiciona:** o rendimento hoje é **invisível como dinheiro**. Ele
aumenta `accrued_yield_cents` e cria uma `Charge`, mas nenhum saldo se move. A partir da Onda 2,
`register_yield` passa a criar **também** um `bank_transaction` na conta bancária da aplicação:

```
register_yield(conta, valor, data):
    acc.accrued_yield_cents += valor                       # já existe
    Charge(status=paid, external_ref='investment:<id>')    # já existe — DRE, competência
    bank_transaction(+valor, source='yield',               # NOVO — o dinheiro existe
                     bank_account_id=<conta bancária da aplicação>,
                     posted_at=data)
    bank_reconciliation(movimento ↔ charge,                # NOVO — nasce conciliado
                        confidence=100, suggested_by='rule',
                        confirmed_at=now)                  # é o sistema que originou os dois lados
```

Isso não move a Carteira, não aciona split, não cria `PlatformEarning` — a garantia IV1 da Story 5.6
(*"nunca chamar `mark_paid`/`build_transaction`"*) permanece intacta e continua coberta pelo teste
existente. O vínculo nasce confirmado porque **o e1p originou os dois lados**; não há
julgamento a fazer.

**(c) A duplicação deliberada da string `'investment:'`** entre `investments/models.py:31` e
`receivables/service.py:53` (para evitar dependência circular) **fica como está**. O módulo `bank`
vai precisar do mesmo prefixo; ele deve importar de `investments.EXTERNAL_REF_PREFIX` (pode — `bank`
depende de `investments`, não o contrário), **não** duplicar uma terceira vez.

### 3.5 Transferência entre contas próprias — resultado zero na DRE

Este é o requisito R3 e o ponto de maior risco de erro conceitual do design inteiro.

**Semântica:**

```
bank_transfer(from=Itaú, to=Aplicação, amount=10.000, kind='investment_in', date=D)
   ├── bank_transaction(Itaú,      −10.000, source='transfer', transfer_id=T, posted_at=D)
   └── bank_transaction(Aplicação, +10.000, source='transfer', transfer_id=T, posted_at=D)
```

**Por que a DRE fica zerada — por construção, não por regra:**

`financial_intelligence/dre.py` agrega exatamente **três** origens: `charges`, `payables` e
`transactions` (Carteira). `bank_transactions` e `bank_transfers` **não são nenhuma delas** e nunca
serão adicionadas. Logo:

> **REGRA DA NEUTRALIDADE (normativa, testável).** Uma transferência entre contas próprias é
> **exclusivamente** um evento do plano 3. Ela nunca cria, altera ou baixa um `Charge`, um `Payable`
> ou uma `Transaction`. Consequentemente não aparece na DRE, na Lucratividade nem na Projeção como
> entrada/saída — só move saldo entre contas.
>
> **Teste:** `test_transferencia_nao_altera_dre` — snapshot da `dre_report` antes e depois de criar
> uma transferência de valor arbitrário; os dois resultados devem ser **idênticos campo a campo**.

**Por que o resgate não vira receita fantasma:** porque não existe caminho de código que transforme
um `bank_transfer` em `Charge`. Além disso, a guarda da §2.3 bloqueia o vínculo:
`source='transfer'` não pode ter `target_type in ('payable','charge')`. Duas defesas independentes.

**O caso desagradável — o resgate que passa pelo extrato do banco.** Quando o usuário importar o OFX
da conta corrente, a linha de crédito do resgate **vai** aparecer no arquivo. Se ela virar um
movimento novo, o saldo dobra. Resolução em §4.5 (passo de *enriquecimento antes de inserir*).

**Rendimento ≠ transferência.** O rendimento é receita financeira (grupo FINANCEIRO na DRE, via
`Charge` — §3.4) **e** um movimento bancário. O resgate é **só** movimento. Aporte é **só**
movimento. Essa é a distinção que o R3 pede e que hoje não existe.

**Payout da Carteira** (`kind='wallet_payout'`): `from_account_id = NULL` (a origem é o plano 1, que
não é uma `bank_account`), `to_account_id` = a conta bancária do usuário. Gera **um** movimento
(+valor na conta destino). Também é DRE-neutro — a receita já foi reconhecida quando a `Charge` foi
paga; o payout só transporta o dinheiro. Detalhe em §6.6.

---

## 4. Pipeline de importação — sem terceiros

```
 [1] upload         POST /bank/accounts/{id}/imports  (multipart)
       │            grava Attachment(owner_type='bank_import') via core/storage
       ▼
 [2] detecção       sniff dos primeiros bytes → parser_id + encoding
       │            (OFXHEADER: → sgml | <?xml/<?OFX → xml | resto → csv:<layout>)
       ▼
 [3] parse          StatementParser.parse(bytes) → ParsedStatement (PURO, sem banco, sem rede)
       │
       ▼
 [4] normalização   valor → centavos int; data → date; descrição → strip/collapse;
       │            contraparte → extração determinística (regex) do MEMO
       ▼
 [5] dedup          dedup_hash por linha; colisão com o que já existe → PULA (idempotente)
       │
       ▼
 [6] enriquecimento linha nova que casa com movimento 'transfer'/'payout' pendente → ENRIQUECE
       │            o existente em vez de inserir (§4.5)
       ▼
 [7] persistência   INSERT das linhas realmente novas + batch + checkpoint (LEDGERBAL)
       │            TUDO num commit só
       ▼
 [8] sugestão       regra determinística primeiro (valor+data+janela) → depois IA (classificação,
       │            contraparte, ranking) → grava bank_reconciliations com confirmed_at=NULL
       ▼
 [9] confirmação    USUÁRIO confirma → confirmed_at=now → e SÓ AQUI pode haver baixa
       ▼
[10] baixa          payable → payables.apply_paid (seguro, tem estorno)
                    charge  → BLOQUEADO até a dívida platform_earnings ser resolvida (§4.7)
```

### 4.1 Parser como strategy plugável (protege contra a pesquisa do @analyst)

O @analyst está apurando **quais bancos ainda exportam OFX em 2026** e o estado das libs Python.
O design não pode depender dessa resposta. Portanto:

```python
# app/modules/bank/parsers/base.py — ILUSTRATIVO
class ParsedLine(NamedTuple):
    posted_at: date
    amount_cents: int          # com sinal
    raw_description: str
    fitid: str | None
    balance_after_cents: int | None
    counterparty_name: str
    counterparty_document: str
    pix_end_to_end_id: str | None

class ParsedStatement(NamedTuple):
    account_hint: AccountHint      # bankid/branch/acctid quando o formato trouxer
    lines: list[ParsedLine]
    ledger_balance_cents: int | None
    ledger_balance_date: date | None
    encoding: str

class StatementParser(Protocol):
    id: str
    def sniff(self, filename: str, head: bytes) -> int: ...   # 0 = não sei; 1..100 = confiança
    def parse(self, raw: bytes) -> ParsedStatement: ...
```

- **Registro ordenado** em `parsers/__init__.py`; a detecção escolhe o de maior `sniff`.
- **Layouts CSV em YAML**, não em código: `app/modules/bank/layouts/*.yaml` com
  `{id, label, delimiter, encoding, date_format, columns:{date,amount,description,...},
  amount_style: signed|debit_credit_columns, skip_rows, decimal_separator}`. Adicionar um banco novo
  vira **um arquivo de dados**, não um deploy de lógica. (Princípio "config > hardcoding".)
- **Os parsers são PUROS** — nenhum acesso a `Session`, nenhum I/O. Mesma disciplina do
  `financial_intelligence/engine.py`, e pela mesma razão: testável com um `bytes` fixture, sem banco.
- **Zero dependência de rede em runtime.** Se uma lib de OFX for adotada, ela é parsing local; se
  nenhuma servir, o parser SGML é escrito à mão (OFX 1.x é SGML tolerante: tags sem fechamento,
  hierarquia rasa — é um parser de ~150 linhas, não um projeto).

### 4.2 OFX 1.x (SGML) vs 2.x (XML)

| | OFX 1.x | OFX 2.x |
|---|---|---|
| Cabeçalho | `OFXHEADER:100` ... linhas `CHAVE:VALOR` até linha em branco | `<?xml version...?>` + `<?OFX OFXHEADER="200" ...?>` |
| Corpo | SGML: **tags de fechamento opcionais**, valor até a próxima tag | XML bem-formado |
| Encoding | Declarado em `CHARSET:` (`1252`, `NONE`) + `ENCODING:` (`USASCII`, `UTF-8`) | Atributo `encoding` do XML |
| Estratégia | Parser tolerante próprio (`OfxSgmlParser`): separa header, tokeniza `<TAG>valor`, monta pilha ignorando fechamentos ausentes | `xml.etree` com resolução de entidade **desligada** (defesa XXE) |

Ambos entregam o mesmo `ParsedStatement`. Campos lidos: `<STMTTRN>` → `<DTPOSTED>`, `<TRNAMT>`,
`<FITID>`, `<MEMO>`, `<NAME>`, `<TRNTYPE>`; `<LEDGERBAL>` → `<BALAMT>`, `<DTASOF>`;
`<BANKACCTFROM>` → `<BANKID>`, `<BRANCHID>`, `<ACCTID>`.

**Encoding — regra fail-loud, nunca mojibake silencioso:** cadeia `CHARSET/ENCODING declarado →
cp1252 → latin-1 → utf-8-sig`. O encoding efetivamente usado é **gravado no batch**. Se a
decodificação produzir caractere de substituição (`�`) em mais de 1% do texto, o import falha
com mensagem acionável ("o arquivo parece estar em outra codificação") em vez de gravar lixo
permanente em `raw_description` — que, por ser imutável (§2.2), seria lixo para sempre.

**Fuso:** `<DTPOSTED>` vem como `YYYYMMDDHHMMSS[±h:TZ]`. Usamos **só os 8 primeiros dígitos** (a data
de calendário como o banco a publicou) e ignoramos hora/offset. Converter para UTC e depois voltar é
exatamente o bug que derrubou a Agenda; aqui não fazemos a conversão.

### 4.3 CSV com layout por banco

Encoding declarado no YAML do layout, mesmo fallback. `amount_style` cobre os dois padrões reais:
coluna única assinada, ou colunas separadas de débito/crédito. Separador decimal `,` (padrão BR)
tratado no layout, nunca por heurística global. **Sem FITID** → `dedup_hash` cai na variante
composta (§4.4). Um layout desconhecido → o e1p mostra as 5 primeiras linhas e pede o mapeamento
uma vez; o mapeamento vira um YAML de layout **por tenant** (`bank_csv_layouts`, se necessário) —
**[marcado como escopo de onda posterior; não é da Onda 3]**.

### 4.4 Deduplicação e idempotência

```
se fitid presente:   dedup_hash = sha256(f"{bank_account_id}|fitid|{fitid}")
senão:               dedup_hash = sha256(f"{bank_account_id}|c|{posted_at}|{amount_cents}"
                                         f"|{normaliza(raw_description)}|{ordinal_no_dia}")
```

- `normaliza` = upper, colapsa espaços, remove pontuação — porque o mesmo lançamento reexportado
  pode variar em espaçamento.
- `ordinal_no_dia` = índice (0,1,2…) da linha entre as **idênticas** (mesma data, mesmo valor, mesma
  descrição normalizada) **dentro do arquivo**. Sem ele, dois Pix de R$ 50 para a mesma pessoa no
  mesmo dia colidiriam e o segundo sumiria — um furo **criado pelo sistema**. Com ele, ao reimportar
  um arquivo sobreposto, os ordinais se reproduzem de forma estável e a dedup continua correta.
  ⚠️ O ordinal é calculado **contra o que já existe no banco naquele dia**, não só contra o arquivo —
  senão um extrato parcialmente sobreposto reinseriria duplicatas.
- A **constraint única** `(tenant_id, bank_account_id, dedup_hash)` é a garantia final: mesmo que a
  lógica falhe, o banco recusa. Fail-closed, no espírito da RLS.

**Reimportar o mesmo arquivo:** `file_sha256` já existente → resposta `200` com
`{lines_new: 0, lines_duplicate: N}` e a mensagem *"este extrato já foi importado em DD/MM"*. **Não é
erro** — é o comportamento esperado de quem não lembra se importou.

**Períodos sobrepostos** (importar 01–31/jul depois de 15/jun–15/jul): só as linhas de 16–31/jul são
novas; o resto colide no `dedup_hash` e é contado em `lines_duplicate`. É o caminho normal, não o
excepcional — o usuário **vai** fazer isso.

### 4.5 Enriquecimento antes de inserir (o caso da transferência)

Antes de inserir uma linha nova, o importador procura um movimento **já existente** na mesma conta
com `source in ('transfer','yield','payout')`, `status <> 'ignored'`, `fitid IS NULL`, mesmo
`amount_cents` e `posted_at` dentro de **± 3 dias**. Se achar exatamente um:

- **enriquece** o existente (`fitid`, `raw_description`, `balance_after_cents`, `import_batch_id`,
  `source` → `'ofx'`), e **não insere**;
- conta em `lines_enriched`.

Se achar mais de um candidato, **não adivinha**: insere a linha e marca ambas com
`user_description` sinalizando "possível duplicata" — o usuário resolve na conferência (é
exatamente o tipo de decisão que a §4.6 diz que a máquina não toma sozinha). A janela de ±3 dias é
**[SUPOSIÇÃO minha, parametrizável]**: cobre TED/Pix agendado que compensa em dia útil seguinte.

### 4.6 Onde a IA entra — e onde ela é proibida

| Etapa | IA pode? | Justificativa |
|---|---|---|
| Escolher o parser / decodificar | **Não** | Determinístico; IA aqui só adiciona não-determinismo e custo |
| Extrair contraparte do `raw_description` | **Sim, sugerindo** | Regex determinística primeiro; IA só no que sobrou. Grava em `counterparty_*` com `suggested_by='ai'` até confirmação |
| Classificar (`chart_account_id`, `cost_center_id`) | **Sim, sugerindo** | Não move dinheiro; erro é visível e reversível numa edição |
| Ranquear candidatos de vínculo | **Sim, sugerindo** | Grava `bank_reconciliations` com `confirmed_at=NULL`, `confidence` |
| **Confirmar** um vínculo | **NÃO** | `confirmed_at` só é escrito por ação de usuário autenticado |
| **Dar baixa** em `Payable` | **NÃO** | Reversível (`POST /payables/bills/{id}/reverse` existe), mas é ato de dono |
| **Dar baixa** em `Charge` | **NÃO — e nem o usuário, por ora** | §4.7 |
| Narrar a conferência | **Sim** | Padrão da casa: *regra determinística primeiro, IA narrando depois* (FR8/NFR3 do PRD) |

**Anonimizador obrigatório (Regra de Ouro nº 2 / NFR2).** `raw_description` de extrato bancário
carrega nome e frequentemente documento de contraparte. Nenhuma dessas strings vai para o Claude sem
passar por `core/anonymizer`. Isso vale inclusive na classificação — a tentação de mandar a descrição
crua "porque é só uma categoria" é exatamente o caminho pelo qual PII vaza.

**Rastro da IA (Regra de Ouro nº 3):** toda sugestão gerada por IA grava `audit.record(...,
is_ai=True)` e é visível na UI como sugestão, nunca como fato.

### 4.7 O bloqueio duro: baixa de `Charge` a partir do extrato

Documentado em `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md` e no `CLAUDE.md`:
o estorno de Contas a Receber foi **implementado, revisado duas vezes e removido antes do merge**,
porque `platform_earnings` (ledger global de GMV do Master) não guarda vínculo de volta à
`Transaction`/`Charge` de origem — pagar → estornar → pagar de novo reportaria GMV duplicado.

Consequência inescapável para este design:

> **Hoje não existe caminho seguro de DESFAZER uma baixa de cobrança.** Um match de extrato
> **vai** produzir baixas indevidas (é estatística, não pessimismo). Portanto **a baixa automática
> ou semiautomática de `Charge` a partir de um movimento bancário está BLOQUEADA** até que o
> vínculo `platform_earnings → transaction` exista.

O que **é** permitido antes disso, e entrega quase todo o valor:

- **Vínculo informativo** movimento ↔ `charge` já paga (confirma que o dinheiro entrou de fato) — não
  muda status, não move dinheiro, é seguro.
- **Sinalizar** na conferência: *"esta cobrança está em aberto há 47 dias e existe um crédito de
  mesmo valor no extrato — o cliente pagou por fora?"*. O usuário decide o que fazer com a
  informação. Isso ataca o fantasma do §2.3 do estudo **sem** tocar no split.
- Baixa de `Payable` a partir do extrato: **liberada** (Contas a Pagar nunca move a Carteira e tem
  estorno).

---

## 5. A conferência — o entregável que o fundador pediu

> *"de saldo batendo é uma conferência para achar possível furos"* (R1)

### 5.1 O relatório

`GET /bank/reconciliation-report?account_id=&start=&end=` — **somente leitura**, mesmo padrão dos
serviços do `financial_intelligence` (nenhuma escrita, nenhum efeito colateral).

```python
@dataclass
class ConferenciaConta:
    bank_account_id: str
    periodo: tuple[date, date]

    # ── bloco 1: o saldo bate? ────────────────────────────────────────────
    # ⚠️ Vocabulário corrigido em 2026-07-29 (§1.3.1 — dois eixos, dois campos).
    saldo_banco_cents: int | None       # checkpoint utilizável na janela; None = não sei
    saldo_banco_origem: str            # EIXO A (plano): ORIGEM_BANCO | ORIGEM_INDISPONIVEL
    saldo_banco_fonte: str | None      # EIXO B (porta): ORIGIN_MANUAL | ORIGIN_OFX; None se indisp.
    saldo_banco_data: date | None
    saldo_sistema_cents: int | None    # derivado (§3.1) na MESMA data; None quando não há o que comparar
    saldo_sistema_origem: str          # EIXO A: sempre ORIGEM_BANCO (derivado dos movimentos)
    divergencia_cents: int | None      # banco − sistema  (+ = tem dinheiro que o sistema não conhece)
    dentro_da_tolerancia: bool | None
    tolerancia_cents: int

    # ── bloco 2: extrato SEM contrapartida no sistema (o furo clássico) ───
    movimentos_sem_contrapartida: list[MovimentoOrfao]   # unmatched/partial, com o resto pendente
    total_sem_contrapartida_cents: int

    # ── bloco 3: sistema SEM contrapartida no extrato ─────────────────────
    lancamentos_sem_extrato: list[LancamentoOrfao]       # paid_at no período, zero vínculo
    total_sem_extrato_cents: int

    # ── bloco 4: transparência ────────────────────────────────────────────
    dias_desde_ultima_conferencia: int | None
    movimentos_ignorados: int
    notes: list[str]
```

**Bloco 1 — saldo do banco vs. saldo do sistema.** `saldo_banco` vem do checkpoint (§2.4): declarado
pelo usuário **ou** lido do `<LEDGERBAL>` do último arquivo. `saldo_sistema` é o derivado (§3.1) na
mesma data de referência — comparar em datas diferentes é o erro clássico e o service **recusa**
fazê-lo (se não há checkpoint na janela, `saldo_banco_origem='indisponivel'` e o bloco 1 diz isso
em vez de mostrar um número falso).

**Banda de tolerância:** `max(R$ 50,00, 0,5% do saldo)` — **[SUPOSIÇÃO minha, parametrizável por
tenant]**, herdada da ideia I-15 do estudo. Dentro da banda → verde e **silêncio**. O e1p não é
ferramenta contábil; não precisa fechar em zero, e alertar sobre R$ 3,50 num mês de R$ 25.000 treina
o usuário a ignorar o alerta.

#### 5.1.1 Onde a banda MORA, se for persistida (REQ-16)

> **Resposta arquitetural dada em 2026-07-29** (D-7). A decisão de **escopo** (persistir na Onda 1 ou
> não) é do @po/fundador; a de **lugar** é minha, e é esta.

**Forma na Onda 1 (recomendada): função pura parametrizada, sem persistir.**
`tolerance_cents(saldo_cents, *, floor_cents=TOLERANCE_FLOOR_CENTS, pct=TOLERANCE_PCT) -> int`.
Razão que não é preguiça de escopo: **a Onda 1 é um instrumento de medição** (epic §3.1 — o número
dela é o gate que libera ou mata as Ondas 3 e 4, 4,5 ondas de trabalho). Se cada tenant pode mover a
banda, a régua muda junto com o que ela mede e a leitura do gate perde sentido. Uma banda **fixa e
conhecida** é uma propriedade do experimento, não uma limitação dele.

**Quando persistir: `tenant_profiles`, duas colunas, por tenant — não por conta.**

| Opção | Veredito |
|---|---|
| **`tenant_profiles` (`app/modules/settings/models.py`)** — 1 linha por tenant, RLS, criada sob demanda com defaults, e **já carrega configuração operacional** (`timezone`, `default_entry_funnel_id`, credenciais de WhatsApp), não só brand kit | **ESCOLHIDA.** Reusa a tabela de configuração que existe, com o padrão de default-on-demand já testado. Custo: 2 colunas numa migration aditiva, zero backfill |
| Tabela `bank_settings` nova, 1:1 com tenant | **Rejeitada.** É `tenant_profiles` com outro nome, para dois escalares. Uma tabela por conjunto de preferências é como se chega a quinze tabelas de uma linha |
| Coluna em `bank_accounts` (banda **por conta**) | **Rejeitada agora, não descartada.** O componente percentual da fórmula **já** adapta a banda ao tamanho de cada conta — que é justamente o que faz um único ajuste servir para a corrente de R$ 80k e para a "Caixinha" de R$ 300. Uma banda por conta só se justifica quando aparecer evidência de uma conta com regime de ruído próprio; então entra como coluna **nullable** de override em `bank_accounts`, lida com fallback no default do tenant. Fazer isso antes é inventar requisito (Art. IV) |
| Arquivo YAML / env var | **Rejeitada.** É configuração de **negócio por tenant**, não de infraestrutura; um SaaS multi-tenant não configura tenant por deploy |

**Forma das colunas — sem float no banco:**
`bank_tolerance_floor_cents BIGINT NOT NULL DEFAULT 5000` e
`bank_tolerance_bps INTEGER NOT NULL DEFAULT 50` (basis points: 50 bps = 0,5%). O percentual entra como
**inteiro em pontos-base**, não como `float`/`NUMERIC`: mantém a disciplina "dinheiro e taxas de
dinheiro em inteiro" do projeto, e o cálculo fica `round(abs(saldo) * bps / 10_000)` — determinístico,
sem arredondamento de binário flutuante persistido. A função pura continua sendo o único lugar da
fórmula; o que muda é de onde vêm os dois parâmetros (uma linha em `diagnostics`/`reconciliation`).

**Dono da migration:** **não** a story do `bank_accounts`. `tenant_profiles` não é tabela do módulo
`bank`, e enfiar `ALTER TABLE tenant_profiles` na migration que cria `bank_accounts` mistura dois
domínios num revision e torna o `downgrade` mais arriscado do que precisa. Se o REQ-16 exigir
persistência, ela é **story própria** com revision própria (§2 — revisions encadeiam após o head real;
não há "vaga de 0058" a disputar).

**Bloco 2 — o furo clássico (despesa esquecida).** Movimentos com `status in ('unmatched','partial')`
no período, ordenados por valor absoluto decrescente (o que dói primeiro). Cada item traz ações
diretas: *criar conta a pagar já baixada* (reusa `payables.build_payable` + `apply_paid` num commit
só, o mesmo par extraído para a bandeja de comprovantes), *vincular a uma conta existente*,
*marcar como transferência*, *ignorar com motivo*.

**Bloco 3 — lançou mas não pagou (ou pagou por fora).** `Payable`/`Charge` com `paid_at` dentro do
período e **zero** `bank_reconciliations` confirmado. Dois diagnósticos opostos que o produto
precisa separar:
- despesa marcada paga que nunca saiu do banco → **baixa errada** (existe `reverse`, é corrigível);
- cobrança marcada paga sem crédito correspondente → investigar (e, se o crédito existe em outra
  conta não cadastrada, o remédio é cadastrar a conta).

**Bloco 4 — o sistema declara o que não sabe.** `dias_desde_ultima_conferencia` é o que permite a
frase honesta *"saldo não confirmado há 47 dias"* em vez de exibir um número com falsa precisão.

### 5.2 A frase, antes da tabela

A tela **abre** com uma linha, não com uma lista:

> ⚠️ *Seu saldo no banco está **R$ 2.340 abaixo** do que eu calculei. Provavelmente faltam
> lançamentos de saída. Encontrei **3 movimentos** no extrato que não têm conta correspondente.*

E só então, abaixo, os blocos 2 e 3. Isso é o teto de simplicidade aplicado: quem quiser só o
veredito, para na primeira linha; quem quiser investigar, desce. **O caminho principal não é a
tabela de 43 linhas.**

### 5.3 Integração com o motor de diagnóstico existente

`financial_intelligence/engine.py` é puro, sem I/O, e recebe um `EngineInput` de dataclasses. A
conferência entra ali como **regra determinística de primeira classe** — não como uma tela paralela:

> ⚠️ **Forma CANÔNICA, fixada em 2026-07-29 (D-4 do parecer de ratificação).** A versão anterior deste
> bloco mostrava um `CompletenessInput` **plano**, que **não consegue nomear qual conta está fora da
> banda** — e nomear a conta é exigência da decisão do fundador F3 (várias contas PJ) e do epic §3.2.
> Um plano com decomposição por conta não é refinamento cosmético: sem ele, três contas divergindo
> +R$ 1.200, −R$ 900 e +R$ 40 produzem o diagnóstico "+R$ 340, parece saudável" e o produto perde
> exatamente a capacidade que está vendendo. **O bloco abaixo não é mais ilustrativo — é o contrato.**

```python
# engine.py — CONTRATO (não colar cegamente: respeitar o estilo do arquivo)
@dataclass(frozen=True)
class CompletenessAccountInput:
    """UMA conta bancária, já conferida (ou não) pelo serviço de conferência (§5.1).

    `account_name` pode conter PII → anonimizado pelo narrador na SAÍDA para o Claude, NUNCA aqui
      (exatamente o caminho que `MarginTrend.project_name` já percorre).
    `divergencia_cents = None` significa NÃO AVALIÁVEL (sem saldo declarado utilizável na janela) —
      jamais "zero". Confundir os dois faz o motor afirmar que está batendo o que não foi conferido.
    `dias_desde_ultima_conferencia = None` = nunca confirmado.
    """
    account_name: str
    divergencia_cents: int | None
    tolerancia_cents: int
    dias_desde_ultima_conferencia: int | None


@dataclass(frozen=True)
class CompletenessInput:
    """Completude POR CONTA. `contas == []` = nenhuma conta bancária cadastrada (estado de todos os
    tenants hoje). `movimentos_sem_contrapartida` nasce 0 por construção na Onda 1 (não existe
    conciliação) e a regra só acorda na Onda 3 — PROIBIDO aproximar por "movimentos unmatched":
    esse número alimenta o gate de decisão do epic §3.1, e um número inventado ali custa ~4,5 ondas.
    """
    contas: list[CompletenessAccountInput]
    movimentos_sem_contrapartida: int = 0

# EngineInput ganha `completeness: CompletenessInput | None = None` — ÚLTIMO campo, COM default, para
# que as chamadas e os testes da Story 5.8 continuem válidos sem edição (None → zero sinais).
```

**A `dias_desde_ultima_conferencia` mora na CONTA, não no relatório.** Colapsar para o máximo entre as
contas ("a mais desatualizada manda") é honesto mas **perde qual conta é** — e cai na mesma armadilha
do consolidado que o F3 proíbe. Uma conta conferida ontem e outra nunca conferida não são "45 dias":
são duas afirmações diferentes sobre duas contas.

**Regra de completude — forma canônica** (`source="completude"`, limiar
`_COMPLETENESS_STALE_DAYS = 45` ao lado de `_RUNWAY_RED_DAYS`/`_MARGIN_DROP_*`):

| Condição | Nível | Cardinalidade | Explicação |
|---|---|---|---|
| `data is None` | — | — | nenhum sinal (compatibilidade retroativa com a 5.8) |
| `contas == []` | 🟡 | 1 por relatório | *"Nenhuma conta bancária cadastrada — não sei se os seus lançamentos estão completos"* |
| conta com `divergencia is None` **ou** `dias is None` **ou** `dias > 45` | 🟡 | **1 por conta** | nomeia a conta e **qual** dos casos: *"nunca confirmado"* / *"confirmado há N dias"* / *"sem saldo declarado na janela"* |
| conta com `divergencia is not None` e `abs(divergencia) > tolerancia` | 🔴 | **1 por conta** | nomeia a conta, o valor e a tolerância aplicada. Quando `divergencia < 0`, diz que **provavelmente faltam lançamentos de saída** (REQ-14 — o achado de maior valor) |
| `movimentos_sem_contrapartida > 0` | 🟡 | 1 por relatório | *"N movimentos sem conta correspondente"* — **dormente até a Onda 3** |
| todas as contas avaliáveis **e** dentro da banda **e** frescas (`dias <= 45`) | 🟢 | 1 por relatório | *"Está tudo batendo"* + a maior divergência absoluta e sua tolerância |

Duas notas que evitam retrabalho:
1. **As duas regras 🟡 de "não sei" foram fundidas numa só, por conta.** Ter uma regra para "sem
   checkpoint" e outra para "checkpoint velho" produz, num tenant com 3 contas nenhuma conferida, seis
   sinais 🟡 dizendo a mesma coisa — ruído que treina o usuário a ignorar a tela, o mesmo vício que a
   banda de tolerância existe para evitar. **Uma conta gera no máximo um 🟡 de "não sei".** (Um 🔴 de
   fora-da-banda **pode** coexistir com um 🟡 de desatualização na mesma conta: são afirmações
   diferentes — *"está fora da banda em R$ X"* e *"e essa medição é de 60 dias atrás"*.)
2. **Um 🟢 exige que TODAS as contas sejam avaliáveis.** Qualquer conta não conferida impede o verde: o
   sistema não afirma que está batendo aquilo que não conferiu.

**O motor decide por `abs(divergencia) > tolerancia`, não pelo `dentro_da_tolerancia` da §5.1** —
não porque o booleano esteja errado, mas para não haver **duas verdades** sobre a mesma comparação
(o booleano é para a UI; o motor é auto-suficiente e o teste unitário fica trivial). A borda
`abs(divergencia) == tolerancia` é **dentro** (silêncio) nos dois lugares, e isso precisa de teste
para ninguém invertê-lo em manutenção.

`diagnostics.py` (a camada fina de I/O) ganha a chamada ao serviço de conferência e adapta para
`CompletenessInput` — **uma `CompletenessAccountInput` por `ConferenciaConta`**, `movimentos_sem_contrapartida=0`
literal. **Nada muda na arquitetura** — é exatamente o ponto de extensão que a Story 5.8 projetou, e
`engine.py` continua **estritamente puro** (sem `Session`, sem query, sem `core.ai`, sem tocar `bank`):
a decomposição por conta chega **já montada** de fora, o que é precisamente o que a pureza permite.

**Por que 🔴 e não um aviso lateral:** se a completude estiver quebrada, os outros sinais (margem,
runway, rentabilidade) estão calculados sobre dados incompletos. O sinal de completude tem
precedência semântica: *"não confio nos outros sinais até você fechar isto"*. Esse era o valor da
provocação PO-3 do estudo, na versão fraca — e é barato: uma regra num arquivo puro.

### 5.4 Estender ou criar tela nova? **Estender o diagnóstico; a tela de detalhe não vai no menu.**

| Superfície | Decisão |
|---|---|
| `/financeiro/diagnostico` (`DiagnosticoPage.tsx`) | **Estender.** Ganha o sinal de completude no topo, com o número da divergência |
| Tela de detalhe da conferência | **Nova rota `/financeiro/conferencia`**, alcançada **a partir do sinal** e da tela de contas — **não** entra na sidebar |
| Item de menu "Conciliação bancária" | **NÃO EXISTE.** Ideia I-23 do estudo: o rótulo comunica "software de contabilidade" para todo usuário, inclusive quem nunca abre a tela |
| Item de menu novo | **"Contas & Saldos"** (`/financeiro/contas`) — cadastro, saldo por conta, importar extrato. É um rótulo de *onde está meu dinheiro*, não de *tarefa contábil* |

O nome importa mais do que parece: a mesma capacidade, com o rótulo errado, muda o posicionamento
do produto para quem sequer clica.

---

## 6. Impactos no que já existe

### 6.1 Onda 0 — corrigir o `saldo_inicial` da Projeção (bug independente)

`projection.py:177` hoje usa `available_cents` (plano 1) como saldo de caixa (plano 3). **É bug, não
lacuna de feature**, e a correção **não depende de nada** deste design.

**Onda 0 (zero tabelas novas, zero migration):**

```python
# CONTRATO — projection.py  (ratificado 2026-07-29: D-1 e D-5)
@dataclass
class CashProjection:
    ...
    saldo_inicial_cents: int
    saldo_inicial_origem: str        # "plataforma" | "banco" | "misto" | "indisponivel" (§1.3.1, eixo A)

@dataclass
class Runway:
    days: int | None
    days_suprimido: bool             # True ⇒ days IS None, sempre (invariante testável)
    burn_rate_cents_per_day: int     # NÃO é suprimido — deriva de contas em aberto, não do saldo

@dataclass
class ProjectionWindow:
    days: int
    saldo_projetado_cents: int       # continua exposto — o número é mostrado, a AFIRMAÇÃO é calada
    alert: bool
    alert_suprimido: bool            # True ⇒ alert IS False, sempre (invariante testável)
```

- `saldo_inicial_origem = "plataforma"` e uma `note` nova, explícita:
  *"O saldo inicial vem do disponível na Carteira e1p, não da sua conta bancária. Enquanto você não
  cadastrar sua conta, a projeção e o runway são aproximações."*
- O campo `notes: list[str]` já existe **exatamente para isso** (`_NOTE_CAIXA`, `_NOTE_OVERDUE`) —
  é o padrão da casa, não invenção.

#### 6.1.1 A supressão é NA ORIGEM (backend), porque há DUAS superfícies — não uma

> **Ratificado em 2026-07-29 (D-1).** A versão anterior desta seção dizia que *"o runway deixa de ser
> **exibido** em dias"*, e a leitura natural era "na tela". **Isso era lacuna do design, não licença
> para suprimir só na tela.** Existem duas superfícies que hoje afirmam runway em dias sobre o
> `saldo_inicial` contaminado:
>
> 1. `ProjecaoCaixaPage.tsx` → `runwayLabel(runway.days)`;
> 2. `/financeiro/diagnostico` → `diagnostics.collect_engine_input` (`diagnostics.py:90`) repassa
>    `proj.runway.days` ao motor, e `engine._runway_signal` (`engine.py:128-137`) emite
>    *"Runway de N dias"* / *"Runway < 60 dias"*.
>
> Eu só havia mapeado a (1). O critério de pronto desta seção, porém, é **surface-agnostic** — *"nenhum
> usuário vê um runway em dias derivado de um saldo inicial cuja origem não está declarada na própria
> tela"* —, e um critério surface-agnostic exige supressão surface-agnostic.

**A regra normativa, então:**

> **Quando `saldo_inicial_origem == "plataforma"` e há queima (`burn_rate > 0`), `projection.py` devolve
> `runway.days = None` + `days_suprimido = True`.** A supressão acontece **na origem do dado**, não em
> cada consumidor.

Três razões, em ordem de peso:

1. **Fail-closed.** Qualquer superfície criada depois (uma API pública, um resumo por e-mail, o
   Cockpit) herda a supressão **sem precisar saber que ela existe**. Suprimir por consumidor é
   fail-open: cada novo consumidor é uma nova chance de vazar, e N regras precisam ficar em sincronia.
2. **`engine.py` e `diagnostics.py` ficam intocados.** `engine._runway_signal(None)` já devolve `[]` —
   silêncio, não um 🟢 falso. O comportamento correto sai **por construção**, sem segunda regra. E
   isso elimina colisão de merge com a story que adiciona a regra de completude (§5.3) exatamente
   nesses dois arquivos.
3. **É o mesmo dado, não duas verdades.** Um runway suprimido na tela e presente na API é um convite a
   alguém "consertar" a tela de volta.

**Custos aceitos, ditos sem eufemismo:**

- Os testes de runway da Story 5.7 que hoje afirmam *"queima positiva → N dias"* **mudam de
  expectativa**. Isso é a correção, não uma regressão: eles afirmavam um número derivado de premissa
  errada. A cobertura do cálculo **não** se perde — ela se desloca para `burn_rate_cents_per_day`, que
  continua exposto e continua correto (deriva de contas em aberto, não do saldo inicial).
- Durante a Onda 0, `runway.days` é `None` em **todo** cenário com queima. Aceitável — e o preço de
  não aceitar seria continuar afirmando dias que não sabemos.
- **A armadilha que anula o benefício, e por isso é invariante e não recomendação:**
  `_NOTE_RUNWAY_SEM_RISCO` **não pode** ser emitida no caso suprimido. Hoje a condição é
  `if runway_days is None`; ela precisa passar a ser `if runway_days is None and not days_suprimido`.
  Trocar *"faltam 43 dias"* (falso preciso) por *"sem risco"* (falso tranquilizador) é **pior** que o
  bug original: o primeiro erra um número, o segundo dá permissão para gastar. **"Sem risco"** e
  **"não sei"** nunca compartilham mensagem, nota ou rótulo de tela.
- **Invariante de contrato:** `days_suprimido is True ⇒ days is None`. Nenhum consumidor deve precisar
  tratar "suprimido, mas com número".

#### 6.1.2 O `alert` de janela negativa TAMBÉM é suprimido na Onda 0

> **Ratificado em 2026-07-29 (D-5), REVERTENDO a proposta de deixá-lo passar.** O 🔴 *"Projeção de caixa
> negativa em N dias"* (`engine.py:140-148`, alimentado por `ProjectionWindow.alert`) deriva do **mesmo**
> `saldo_inicial` contaminado. Deixá-lo passar enquanto o runway é suprimido é uma assimetria que não
> se sustenta.

O argumento a favor de deixá-lo passar era que `alert` é uma afirmação **direcional** ("vai ficar
negativo"), não de **precisão numérica**, e que o vício de "precisão espúria" não se aplicaria. **O
argumento não sobrevive ao código:** `saldo_projetado = saldo_inicial + entradas − saídas` e
`alert = saldo_projetado < 0`. O termo contaminado é **aditivo** e o `alert` é um **cruzamento de
limiar** sobre essa soma. Logo o erro no saldo inicial se traduz diretamente em erro de veredito, nas
duas direções:

| Perfil de uso | Efeito em `available_cents` | Efeito em `alert` |
|---|---|---|
| Nunca saca (**o caso real hoje**) | acumula todo o faturamento líquido histórico e **nunca diminui quando uma conta é paga** (`payables` não toca a Carteira) | `saldo_inicial` inflado, monotonicamente → **falso negativo**: silêncio sobre um aperto de caixa que existe |
| Saca tudo | vai a zero enquanto o dinheiro está no banco | `saldo_inicial ≈ 0` → **falso positivo**: 🔴 "caixa negativo em 30 dias" para quem tem R$ 80k na conta |

E o perfil de uso não é uma incógnita: **`request_payout` (`wallet/service.py:227`) só marca
`withdrawn`** — não existe transferência real, ninguém "saca" de fato. Portanto, para todo tenant real,
`available_cents` é a figura que só cresce, e o `alert` é sistematicamente uma **máquina de falso
negativo**. Um sinal que se cala justamente quando deveria falar não é "direcionalmente aproximado":
é ruído com selo de vermelho.

**A regra, então — suprimir a AFIRMAÇÃO, nunca o NÚMERO:**

> Quando `saldo_inicial_origem == "plataforma"`: `ProjectionWindow.alert = False` +
> `alert_suprimido = True`, com nota própria. **`saldo_projetado_cents` continua exposto e continua
> sendo exibido**, com o rótulo de origem ao lado.

Por que isso não é "deixar a Projeção sem sinal nenhum", que era a objeção legítima:

- O dono **continua vendo os três saldos projetados** (30/60/90) e a trajetória. O que desaparece é o
  e1p **afirmando** *"seu caixa fica negativo"* — afirmação para a qual ele não tem lastro. Mostrar o
  número com a premissa rotulada respeita o teto de simplicidade (§0: confirmar, não construir); gritar
  vermelho sobre premissa falsa não.
- No perfil real (nunca saca), o dono **já** não recebia esse 🔴 — o falso negativo é o estado atual.
  Suprimir não remove informação que ele tinha; remove um alarme que só disparava quando estava errado.
- O vazio é preenchido de propósito pelo sinal de completude (§5.3): 🟡 *"Nenhuma conta bancária
  cadastrada — não sei se os seus lançamentos estão completos"*. **Essa é a mensagem certa para este
  estado**, e ela é acionável (cadastre a conta) — o que *"caixa negativo em 30 dias"* derivado de um
  número errado não é.

**Mecanismo (idêntico ao do runway, e pela mesma razão):** com `alert=False`,
`engine._projection_window_signals` não emite nada — o 🔴 desaparece do `/financeiro/diagnostico`
**por construção**, sem editar `engine.py` nem `diagnostics.py`, preservando a ausência de colisão da
§6.1.1. Na UI, `WindowCard` deixa de pintar vermelho e `TrajectoryChart` deixa de traçar em vermelho
(`anyAlert`), mantendo os valores. **Invariante:** `alert_suprimido is True ⇒ alert is False`.

**Restauração:** a partir da Onda 1 (saldo inicial `misto`/`banco`), `days_suprimido` e
`alert_suprimido` voltam a `False` e os dois sinais voltam — agora sobre um número com lastro.

**A partir da Onda 1** (com `bank_accounts` existindo), a precedência do saldo inicial passa a ser:

```
1. Se há conta bancária ativa:
     saldo_inicial = Σ saldo derivado das bank_accounts ativas (kind <> 'investment')
                   + available_cents da Carteira        ← dinheiro do usuário ainda retido na e1p
     origem = "misto"        ← e a UI mostra as DUAS parcelas rotuladas (§1.2), nunca só o total
2. Senão: comportamento da Onda 0, origem = "plataforma", com a note.
```

⚠️ Somar `available_cents` **é correto** (é dinheiro do usuário, só não está no banco ainda) **e é
perigoso** — é exatamente a soma que o §1.1 proíbe fazer sem rótulo. Por isso a Regra dos Planos
(§1.3c) exige o campo `_origem` e a UI exige as duas parcelas visíveis. **Somar sim; esconder a
composição, nunca.**

**Critério de pronto da Onda 0:** nenhum usuário vê um runway em dias derivado de um saldo inicial
cuja origem não está declarada na própria tela.

### 6.2 `investment_accounts.principal_cents` vira derivado — migração de dados

Estado atual: `principal_cents` é **digitado** (`create_account`/`update_account`), sem nenhum evento
de aporte ou resgate. É o ponto cego total que o R3 aponta.

**Migração (Onda 2), passo a passo:**

1. `ALTER TABLE investment_accounts ADD COLUMN bank_account_id VARCHAR(36) NULL;`
2. Para **cada** `investment_accounts` existente, criar uma `bank_accounts` com
   `kind='investment'`, `name` = o nome da aplicação, `opening_date` = `opened_at`,
   `opening_balance_cents = 0`, e ligar `bank_account_id`.
3. Criar um `bank_transfer` **sintético** `kind='investment_in'`, `from_account_id=NULL`
   (origem desconhecida — honesto, não inventado), `amount_cents = principal_cents`,
   `transfer_date = opened_at`, `description = 'Aporte inicial (migrado do principal informado)'`,
   gerando **um** `bank_transaction` de `+principal_cents` na conta de investimento.
4. Criar um `bank_transaction` de `+accrued_yield_cents` só se o rendimento acumulado **não**
   estiver coberto pelas `Charge` de rendimento — **na prática ele está** (cada `register_yield`
   criou uma `Charge`), então o correto é gerar **um movimento por `Charge` de rendimento** daquela
   conta (`external_ref = 'investment:<id>'`), com `posted_at = charge.competence_date`, já
   conciliado ao respectivo `Charge`. Isso reconstrói o histórico real em vez de um número achatado.
5. **Não dropar `principal_cents` nesta migration.** Ela passa a ser recalculada e mantida como
   espelho por 1 ciclo (mesma estratégia da coluna `attachments.data` na Story 3.5: dual antes de
   remover). O drop é uma migration posterior, depois de o derivado estar validado em produção.
6. `update_account` **rejeita** (409) alteração de `principal_cents` a partir da Onda 2, com
   mensagem apontando para "registrar aporte/resgate".

**Invariante verificável pós-migração:** para toda conta,
`saldo_derivado(bank_account) == principal_cents + accrued_yield_cents` **antes** de qualquer resgate.
Um script `python -m app.scripts.bank_audit --investments` reporta divergências sem corrigir em
silêncio.

⚠️ Este é o **único** backfill deste design que toca dado existente — logo é o único exposto à
armadilha do FORCE RLS (§2). Ele roda sob a mesma disciplina da migration 0046.

### 6.3 Charge de rendimento — resolvido em §3.4

Ratificado o filtro existente + o rendimento passa a gerar movimento bancário conciliado.
`InvestimentosPage.tsx` ganha um **extrato da aplicação** (aportes, resgates, rendimentos) — que é
literalmente o *"não apenas o lançamento do quanto rendeu"* do R3.

### 6.4 DRE e Lucratividade

**Impacto zero, por construção** (§3.5). `dre.py` agrega `charges` + `payables` + `transactions`;
nenhuma das novas tabelas entra. `profitability.py` deriva da DRE. Garantido por
`test_transferencia_nao_altera_dre` e `test_movimento_bancario_nao_altera_dre`.

O que **melhora indiretamente**: a linha de extrato sem contrapartida vira conta a pagar lançada
(com `chart_account_id` sugerido pela IA), e **aí sim** entra na DRE — pelo caminho normal, com
competência. A completude sobe; a mecânica não muda.

### 6.5 Cockpit

`cockpit/service.py:130` calcula `net_revenue = available + pending + withdrawn` como **faturamento
líquido** — isso está **correto** (é faturamento, não saldo) e não muda. O que muda:

- Novo card **"Em conta"** (saldo bancário derivado), ao lado de **"Na plataforma"**.
- **Proibido** um card único somando os dois sem decomposição visível (Regra dos Planos §1.3c).

### 6.6 Carteira e payout

`request_payout` (`wallet/service.py:227`) hoje só marca `withdrawn`. A partir da Onda 6, ele emite
um evento (via `core/events`, já existente — mantendo `wallet` sem importar `bank`, §1.3b) que o
módulo `bank` consome para criar `bank_transfer(kind='wallet_payout')` + um `bank_transaction` de
crédito na conta primária. Se **não houver** conta bancária cadastrada, o consumidor não faz nada —
graceful degradation, padrão da casa.

Quando o extrato for importado, o crédito real casa com o movimento sintético pelo passo de
enriquecimento (§4.5). **É o fechamento do circuito:** o dinheiro sai da e1p e aparece no banco, e o
sistema sabe que é o mesmo dinheiro.

### 6.7 Fila de Pagamentos

- Após baixa via conferência, o item sai da fila naturalmente (usa `Payable.status`).
- **Opcional (onda posterior):** `payables.bank_account_id` nullable = "de qual conta pretendo
  pagar". Melhora a sugestão de match (restringe candidatos à conta certa) e a projeção por conta.
  Fica **fora** das ondas 0–6 para não inflar escopo; registrado como extensão natural.

### 6.8 Bandeja de comprovantes ↔ movimento bancário

> *Um comprovante e uma linha de extrato são a mesma despesa vista de dois ângulos.*

A bandeja (`payables/receipts.py`, `attachments` com `owner_type='receipt_inbox'`) já move a captura
para onde o usuário está (share sheet do Android, Atalho do iOS). A conexão desenhada:

1. **Do extrato para o comprovante:** cada `movimento_sem_contrapartida` da conferência consulta a
   bandeja por valor/data compatíveis (±3 dias, valor exato) e oferece *"há um comprovante na
   bandeja que parece ser este movimento"*. É a `receipts.list_candidates` **invertida** — hoje ela
   procura contas para um comprovante; aqui procura comprovantes para um movimento.
2. **Do comprovante para o extrato:** ao vincular um comprovante a uma conta a pagar e dar baixa
   (`POST /payables/receipts/{id}/link`), se existir um movimento bancário não conciliado compatível,
   o vínculo de conciliação é **sugerido** (não confirmado — §4.6).
3. **Criar conta a partir da linha do extrato** reusa exatamente o par `build_payable` + `apply_paid`
   já extraído para `receipts.new_bill_from_receipt` — mesmo commit único, sem duplicar lógica.

**Dívida herdada que este design NÃO resolve e precisa ser dita:** o `CLAUDE.md` registra que a
bandeja é isolada por usuário **só por convenção nas rotas de `receipts`** — as rotas genéricas de
`/attachments` permitem que um colega do mesmo tenant liste/baixe o comprovante em staging de outro.
O arquivo de extrato bancário (`owner_type='bank_import'`) nasce com **o mesmo problema**: é
documento financeiro completo do tenant acessível por qualquer usuário dele. Para uma empresa de 1
pessoa isso é aceitável hoje; quando `/attachments` for endurecido (checar dono, não só tenant),
`bank_import` deve entrar na mesma varredura.

---

## 7. Rastreabilidade tributária

> *"com a entrada da nova legislação tributária, teremos que ter os dados cada vez mais fiéis de
> onde vem e para onde vai o dinheiro"* (R2)

### 7.1 O que "de onde vem e para onde vai" exige, decomposto

| Pergunta | Campo | Onde | Status |
|---|---|---|---|
| **Quem** pagou/recebeu | `counterparty_name` | `bank_transactions` | Do arquivo, quando houver |
| **Quem**, de forma inequívoca | `counterparty_document` (CPF/CNPJ, só dígitos) | `bank_transactions` | Do arquivo **ou** herdado do vínculo (`charge.client_id → Client.document`) |
| **Qual conta** de origem/destino | `bank_account_id`, `holder_document` | `bank_accounts` | Cadastro |
| **Quanto e quando** | `amount_cents`, `posted_at` | `bank_transactions` | Sempre |
| **Natureza** da operação | `operation_nature` | `bank_transactions` | §7.2 — vocabulário |
| **Qual documento fiscal** lastreia | `fiscal_document_ref`, `fiscal_document_type` | `bank_transactions` | **[DEPENDE DE @analyst]** |
| **Classificação contábil** | `chart_account_id`, `cost_center_id` | via vínculo ao `payable`/`charge` | Já existe |
| **Identificador da transação Pix** | `pix_end_to_end_id` | `bank_transactions` | Do `<MEMO>` quando houver |

### 7.2 `operation_nature` — vocabulário sugerido, não enum fechado

Mesmo padrão deliberado de `investment_accounts.kind` e `cost_centers.kind`: **texto curto validado
por tamanho, com vocabulário sugerido na UI**, não enum de banco. Tributação muda; enum de banco
exige migration.

Vocabulário inicial: `receita_servico`, `receita_produto`, `receita_financeira`, `despesa_operacional`,
`tributo`, `pro_labore`, `transferencia_propria`, `aporte_socio`, `distribuicao_lucro`, `emprestimo`,
`estorno`. **[SUPOSIÇÃO minha — a lista é derivada dos `grupo_dre` existentes + dos eventos que este
design cria; NÃO é derivada de nenhuma obrigação legal confirmada.]**

### 7.3 O que depende do @analyst — marcado explicitamente

| Item | Por quê depende | Se a resposta for X, o que muda |
|---|---|---|
| **A obrigação legal em si** (qual norma, quais campos, qual prazo) | Ninguém confirmou a norma; a fala do fundador é uma antecipação | Se exigir campo que não temos, é migration aditiva num campo nullable — **custo baixo por design** |
| **Se o OFX brasileiro carrega CPF/CNPJ da contraparte** | Varia por banco; o padrão OFX não tem campo dedicado (viria no `<MEMO>`) | Se **não** carregar: o campo fica alimentado por herança do vínculo + extração por IA sugerida. Se carregar: parser preenche direto |
| **Se o `endToEndId` do Pix aparece no extrato exportado** | Não confirmado | Se não aparecer, o campo fica reservado, sem custo |
| **Se há obrigação de reter o arquivo original** | Não confirmado | Já retemos (`attachments`, `owner_type='bank_import'`) — cobertos por acidente feliz |

**Postura de design:** todos os campos nascem **nullable e opcionais**, sem validação obrigatória,
sem tela nova. Custo hoje ≈ zero; custo de adicioná-los depois = migration + backfill impossível
(o dado histórico não volta). **É barato guardar cedo e caro descobrir tarde.**

### 7.4 LGPD — a advertência que precisa estar escrita

`counterparty_document` é CPF de terceiro que **nunca contratou com a e1p**. Isso é dado pessoal de
não-usuário, coletado por via indireta. Consequências operacionais:

- **Anonimizador obrigatório** antes de qualquer chamada de IA que toque `raw_description`,
  `counterparty_name` ou `counterparty_document` (Regra de Ouro nº 2 / NFR2). Não é opcional nem
  "só na narrativa".
- O extrato importado, tanto o arquivo quanto as linhas, entra no escopo de **exclusão de conta**
  (`delete_account` já purga dinamicamente subclasses de `TenantMixin` — as tabelas novas são
  cobertas automaticamente, o que é uma virtude do padrão existente).
- Minimização: **não** extrair documento de contraparte "porque dá"; extrair quando houver finalidade
  (vínculo fiscal). Marcar isso na docstring do parser evita que uma story futura ligue extração
  agressiva sem pensar.

---

## 8. Faseamento — ondas com valor próprio

> ⚠️ **A ORDEM DESTA SEÇÃO ESTÁ SUPERSEDIDA (2026-07-30).** A ordem corrente está em
> [`controle-bancario-onda2-design.md`](controle-bancario-onda2-design.md) §10. Resumo do que mudou:
> uma **Onda 2 nova** (a origem do movimento: `payable`→banco, recebimento fora do trilho, data de
> baixa editável, manual curado, transferência entre contas próprias) entra logo após a Onda 1; a
> Onda 2 antiga vira **2b** (só a parte de aplicação/`principal_cents`, que carrega o único
> backfill); o payout (era 6) sobe para **3**, porque passa a ser o mesmo mecanismo; a importação
> (era 3) desce para **4**. Critério de ordenação: **dependência externa crescente** — 2, 2b e 3 não
> dependem de nada fora do repositório; a importação depende da verificação de OFX real (D6) e do
> gate §3.1. E a Onda 2 é **pré-requisito da métrica do gate**: medida antes dela, a divergência
> mede a ausência da porta, não o furo. As **estimativas e o conteúdo** de cada onda abaixo
> continuam válidos; só a ordem e o corte da 2 mudaram.
>
> Cada onda entrega valor sozinha e pode parar ali sem deixar o produto pela metade.
> Estimativa em **ondas de trabalho**, calibrada contra módulos já entregues (não em horas — não há
> velocity confiável). **Migrations: ver §2 — este design não fixa número de revision; a coluna
> "Migration" das tabelas abaixo é ORDEM de dependência, não identificador.**

### Onda 0 — Saldo inicial honesto *(bug, independente de tudo)*

- **Escopo:** `projection.py` ganha `saldo_inicial_origem` + note explícita; **na origem do dado
  (backend)**, suprime o **runway em dias** (`days=None` + `days_suprimido`) **e** o **`alert` de janela
  negativa** (`alert=False` + `alert_suprimido`) enquanto a origem for `"plataforma"` — as duas
  supressões fecham, por construção, tanto a tela quanto o sinal do `/financeiro/diagnostico`
  (§6.1.1, §6.1.2). `engine.py` e `diagnostics.py` **não são tocados**. Zero tabela, zero migration.
- **Critério de aceite:**
  1. `GET /financial-intelligence/projection` devolve `saldo_inicial_origem="plataforma"` e a note.
  2. `ProjecaoCaixaPage.tsx` exibe a origem junto ao número; não exibe runway em dias nem pinta
     janela/trajetória de vermelho enquanto a origem for `"plataforma"` — **mas continua exibindo**
     `saldo_projetado_cents` de cada janela e `burn_rate_cents_per_day`.
  3. Teste: `test_projecao_declara_origem_do_saldo_inicial`.
  4. Teste: nenhum `Signal` de `source="projecao"` sai de `diagnostics.compute_signals` enquanto a
     origem for `"plataforma"` — nem o de runway, nem o de janela negativa. É o critério de pronto
     desta onda, e ele é sobre o **usuário**, não sobre um endpoint.
  5. Teste: caso suprimido **não** produz a nota/mensagem de "sem risco" (`days_suprimido` ⇒ sem
     `_NOTE_RUNWAY_SEM_RISCO`). É o teste de maior valor da onda inteira.
  6. Invariantes: `days_suprimido ⇒ days is None`; `alert_suprimido ⇒ alert is False`.
- **Esforço:** ~0,25 onda.

### Onda 1 — Contas, saldo e a conferência de um número

- **Escopo:** `bank_accounts`, `bank_transactions` (só `source='manual'`), `bank_balance_checkpoints`;
  saldo derivado; CRUD de conta; lançamento manual; **conferência bloco 1** (banco vs. sistema, com
  banda de tolerância); regra de completude no `engine.py`; sinal no `/financeiro/diagnostico`; menu
  **"Contas & Saldos"**. `projection.saldo_inicial` passa a usar o saldo bancário quando existir
  (`origem="misto"`, com as duas parcelas rotuladas). Testes da Regra dos Planos (§1.3).
- **Critério de aceite:**
  1. Usuário cadastra conta com saldo de abertura e vê o saldo derivado bater com o extrato dele.
  2. Declara o saldo de hoje e recebe **uma frase** com a divergência (ou "está tudo batendo").
  3. Divergência dentro da tolerância → 🟢 e nenhum alerta.
  4. `/financeiro/diagnostico` mostra o sinal de completude com o número.
  5. Projeção declara `origem="misto"` e a UI mostra "na plataforma" e "no banco" separados.
  6. `test_wallet_nao_importa_bank` passa; RLS e2e cross-tenant no Postgres real passa.
- **Esforço:** ~1,5 onda. **Já entrega o pedido literal do fundador (R1) sem parser nenhum.**

### Onda 2 — Transferências, aplicação como conta, `principal_cents` derivado

- **Escopo:** `bank_transfers`; UI de aporte/resgate/transferência; `investment_accounts.bank_account_id`;
  migração de dados (§6.2); `register_yield` passa a gerar movimento conciliado (§3.4);
  extrato da aplicação no `InvestimentosPage`; `update_account` rejeita editar `principal_cents`.
- **Critério de aceite:**
  1. Aporte de R$ 10.000 da conta corrente para a aplicação: saldo da corrente cai 10k, o da
     aplicação sobe 10k, **DRE idêntica antes e depois** (teste de snapshot).
  2. Resgate: mesmo, invertido, e **nenhuma receita** aparece em lugar nenhum.
  3. Rendimento lançado: aparece na DRE (grupo FINANCEIRO) **e** aumenta o saldo da aplicação.
  4. Contas de investimento pré-existentes migradas: `saldo_derivado == principal + accrued_yield`.
  5. `bank_audit --investments` reporta zero divergência.
- **Esforço:** ~1,5 onda. **Atende integralmente o R3.**

### Onda 3 — Importação de extrato (parser plugável, sem match automático)

- **Escopo:** `bank_import_batches`; `StatementParser` + `OfxSgmlParser` + `OfxXmlParser` + `CsvParser`
  com 1–2 layouts YAML; dedup (§4.4); enriquecimento (§4.5); checkpoint a partir do `<LEDGERBAL>`;
  **conferência bloco 2 e 3** (movimentos e lançamentos órfãos); ações manuais por linha
  (criar conta a pagar já baixada, vincular, marcar transferência, ignorar).
- **Critério de aceite:**
  1. OFX 1.x e 2.x reais importam; encoding registrado; arquivo ilegível falha com mensagem
     acionável (não grava lixo).
  2. Reimportar o mesmo arquivo → `lines_new = 0`, sem erro.
  3. Importar período sobreposto → só o incremento entra.
  4. Dois lançamentos idênticos no mesmo dia → **dois** movimentos, não um.
  5. Transferência lançada antes do import não duplica após o import (`lines_enriched ≥ 1`).
  6. A conferência lista os órfãos dos dois lados com os totais.
  7. Zero chamada de rede em todo o pipeline.
- **Esforço:** ~2,5 ondas. É a onda cara — e o custo é permanente (ADR 0003, §"Consequências").

### Onda 4 — Sugestão de vínculo (regra → IA) e baixa de Contas a Pagar

- **Escopo:** matcher determinístico (valor exato + janela de data + conta); IA classificando e
  ranqueando **sob anonimizador**; `bank_reconciliations` com `confirmed_at=NULL`; confirmação do
  usuário; baixa de `Payable` a partir da confirmação; alocação parcial (N:N).
- **Critério de aceite:**
  1. Um Pix que quita **duas** contas: dois vínculos, soma = valor do movimento, movimento vira
     `matched`.
  2. Uma conta paga em **dois** movimentos: dois vínculos, conta baixada só quando a soma fecha.
  3. Nenhuma baixa acontece sem `confirmed_at` preenchido por usuário (teste).
  4. Nenhuma string crua de `raw_description` chega ao Claude (teste com espião no `core/ai`).
  5. Vínculo `source='transfer'` → `target_type='payable'` é rejeitado (409).
- **Esforço:** ~2 ondas.

### Onda 5 — Baixa de Contas a Receber a partir do extrato — **BLOQUEADA**

- **Pré-requisito absoluto:** vínculo `platform_earnings → transaction` (migration + ajuste do ledger
  global), reabilitando o estorno de `Charge`. **Enquanto isso não existir, esta onda não começa.**
- **Escopo (quando desbloqueada):** baixa de `Charge` via conciliação; detecção de "cliente pagou por
  fora" (crédito no extrato + cobrança em aberto de mesmo valor).
- **Esforço:** ~1 onda de pré-requisito + ~1 onda de escopo.

### Onda 6 — Payout da Carteira fecha o circuito

- **Escopo:** evento de payout → `bank_transfer(kind='wallet_payout')` + crédito na conta primária;
  card do Cockpit com as duas parcelas rotuladas; graceful degradation sem conta cadastrada.
- **Critério de aceite:**
  1. Payout com conta cadastrada gera o crédito bancário; sem conta cadastrada, nada acontece e nada
     quebra.
  2. `grep -r "from app.modules.bank" apps/api/app/modules/wallet/` → vazio (Regra dos Planos §1.3b).
  3. Ao importar o extrato, o crédito real enriquece o movimento sintético (não duplica).
- **Esforço:** ~0,5 onda.

### Resumo

> **A coluna "Migrations" conta QUANTAS revisions a onda consome, não QUAIS.** Ver §2: o número é
> definido pelo head real no momento da implementação, uma migration por story que cria tabela.

| Onda | Entrega | Migrations | Esforço `[EST.]` | Depende de |
|---|---|---|---|---|
| 0 | Saldo inicial honesto (runway **e** alert suprimidos) | — | 0,25 | nada |
| 1 | Contas + saldo + conferência (1 número), por conta | **3** (`bank_accounts`, `bank_transactions`, `bank_balance_checkpoints`) | 1,5 | 0 (recomendado) |
| 2 | Transferências + aplicação + derivado | 1–2 (`bank_transfers`; `investment_accounts.bank_account_id` + backfill) | 1,5 | 1 |
| 3 | Importação OFX/CSV + órfãos | 1 (`bank_import_batches`) | 2,5 | 1 |
| 4 | Sugestão + baixa de Pagar | 1 (`bank_reconciliations`) | 2,0 | 3 |
| 5 | Baixa de Receber | 1+ (`platform_earnings → transaction`) | 1,0 + 1,0 | **dívida `platform_earnings`** |
| 6 | Payout fecha o circuito | 0–1 (pode não precisar de DDL) | 0,5 | 1 |
| — | Banda de tolerância persistida por tenant (§5.1.1), **se** o @po/fundador exigir | 1 (`tenant_profiles` +2 colunas) | ~0,25 | 1 |

**Ordem recomendada:** 0 → 1 → 2 → 3 → 4 → 6, com 5 fora da fila até a dívida ser paga.
**Ponto de parada legítimo:** depois da Onda 2. Se a divergência medida na Onda 1 for pequena e
estável na maioria dos tenants, as Ondas 3–4 são over-engineering e devem ser adiadas. **A Onda 1 é
o experimento mais barato para medir o tamanho real do problema — e hoje ninguém sabe o tamanho.**

---

## 9. Custo de esforço do usuário — justificando cada pedido

Contra o teto de simplicidade (*confirmar, nunca construir*):

| Onda | O que o e1p pede | Confirma ou constrói? | Frequência | Justificativa |
|---|---|---|---|---|
| 1 | Cadastrar a conta + saldo de abertura | **Confirma** (lê no app do banco) | 1× por conta | Sem isso não existe plano 3. 5 campos, uma vez na vida |
| 1 | Declarar o saldo atual | **Confirma** | ~1×/mês | É o insumo da conferência inteira. 5 segundos |
| 2 | Registrar aporte/resgate | **Confirma** (valor que ele acabou de mover) | Por evento | Alternativa é `principal_cents` digitado, que é o ponto cego atual |
| 3 | Baixar o OFX e subir | **Constrói levemente** (5 min, fora do e1p) | ~1×/mês | ⚠️ **É o pedido mais caro do design.** Vale porque *localiza* o furo em vez de só quantificá-lo — e o fundador pediu explicitamente "achar possível furos" |
| 4 | Confirmar sugestões | **Confirma** | Por linha órfã | O trabalho caro (achar o par) é da máquina; a decisão é do dono |
| — | Conciliar 43 linhas manualmente | **Constrói** | — | **Nunca pedido.** É o que a conferência de um número (Onda 1) existe para evitar |

**Onde eu discordaria do design se fosse o revisor:** a Onda 3 (import) é o ponto em que o produto
mais se aproxima da fronteira "ERP contábil" do §6.1 do estudo. A mitigação desenhada é o rótulo
(§5.4) e o fato de a conferência funcionar **sem** o import (Onda 1). Se o import virar o caminho
principal em vez do complementar, o teto foi rompido — e o sintoma será a tela de linhas virando a
tela mais acessada do financeiro. **Isso é observável e deve ser observado.**

---

## 10. Pontos que precisam de decisão do fundador

Nada aqui bloqueia a Onda 0 ou a Onda 1.

| # | Pergunta | Onda afetada | Default se ele não responder |
|---|---|---|---|
| **D1** | **Banda de tolerância:** `max(R$ 50, 0,5%)` é aceitável, ou ele quer fechar em zero? | 1 | Adotar o default como **função pura parametrizada, sem persistir** na Onda 1 (a banda fixa é propriedade do experimento de medição do epic §3.1). Se a persistência por tenant for exigida, o lugar está decidido: `tenant_profiles`, duas colunas inteiras — **§5.1.1** |
| **D2** | **Quantas contas bancárias, na prática?** Uma (corrente) ou várias (corrente + poupança + aplicação + PF)? | 1, 5 | Suportar N contas desde a Onda 1 (o modelo já suporta; é custo zero) |
| **D3** | **Conta PF misturada com PJ:** o advogado usa a mesma conta para pessoal e escritório? Se sim, a divergência será ruído crônico | 1 | Perguntar na tela ("saldo da conta que você usa para o escritório") e tolerar divergência estável |
| **D4** | **Pagar a dívida `platform_earnings → transaction` agora?** É pré-requisito absoluto da Onda 5 e destrava também o estorno de cobranças (capacidade já construída e descartada) | 5 | Não fazer; Onda 5 fica fora da fila |
| **D5** | **Payout real (`request_payout` hoje só marca `withdrawn`)** entra no roadmap? Se sim, dados bancários + KYC vêm por esse caminho e a Onda 6 muda de natureza | 6 | Onda 6 permanece como registro contábil, sem transferência real |
| **D6** | **Carteira Asaas como `bank_account`** (`kind='platform_wallet'`)? Unificaria "onde está meu dinheiro", ao custo de enfraquecer a Regra dos Planos | — | **Não** criar; valor fica reservado no vocabulário |
| **D7** | **Recebimento fora do trilho:** ele quer que a conferência *sinalize* crédito no extrato sem cobrança correspondente (o que tem leitura de fiscalização do split)? | 3, 5 | Sinalizar como informação neutra ao **dono**, nunca reportar ao Master |
| **D8** | **`operation_nature`:** o vocabulário da §7.2 é suposição minha. Ele tem uma lista vinda do contador? | 3+ | Usar o vocabulário sugerido, texto livre |

---

## 11. Riscos e o que reverteria a decisão

| Risco | Probabilidade | Impacto | Mitigação no design |
|---|---|---|---|
| **Parser por banco vira manutenção perpétua** | **Alta** (é certeza, não risco) | Médio | Strategy + layouts em YAML; falha de parse **nunca** corrompe dado (fail-loud); começar com 1–2 formatos, não 10 |
| **Baixa indevida de `Charge` sem caminho de desfazer** | Alta se permitida | **Crítico** (GMV duplicado no Master) | Onda 5 bloqueada até a dívida ser paga. Defesa dupla: guarda de `target_type` + ausência do endpoint |
| **Resgate virando receita fantasma** | Média sem cuidado | Alto | Transferência não toca `charges`/`payables`/`transactions`; guarda de vínculo; teste de snapshot da DRE |
| **Dupla contagem transferência × extrato** | **Alta** | Alto | Passo de enriquecimento (§4.5) + constraint única + "possível duplicata" quando ambíguo |
| **Planos voltarem a se misturar** | Média ao longo do tempo | Alto (é o bug original) | Regra dos Planos com teste estrutural de import; campo `_origem` obrigatório |
| **Abandono da conferência** ("última conferência há 94 dias") | Média | Médio | O sistema **declara que não sabe** em vez de culpar; o gancho é utilidade, não obrigação |
| **PII de contraparte vazando para a IA** | Média sem disciplina | Alto (LGPD) | Anonimizador obrigatório; teste com espião no `core/ai` |
| **Produto virar ERP contábil e perder o público** | Média | **Existencial para a tese** | Rótulo "Contas & Saldos"; conferência funciona sem import; a frase antes da tabela |
| **Backfill silencioso a zero linhas sob FORCE RLS** | **Alta** se esquecido | Alto | §2 + §6.2 documentam; só uma migration faz backfill |

### O que me faria recomendar reverter

1. **A Onda 1 mostrar divergência tipicamente dentro da tolerância** na maioria dos tenants → o
   problema era menor do que se supunha; **pare na Onda 2** e não construa import. Este é o
   desfecho que eu consideraria *bom*, não frustrante.
2. **Nenhum banco relevante do público-alvo exportar OFX em 2026** (pesquisa do @analyst) → o
   caminho de arquivo morre; a resposta passa a ser captura na origem (comprovante + IA) e a
   conferência de um número. O design **sobrevive** porque as Ondas 0–2 não dependem de arquivo.
3. **A tela de conciliação virar a mais acessada do financeiro** → sinal de que o teto de
   simplicidade foi rompido e o produto virou contábil. Ação: rebaixar a tela, reforçar a frase.
4. **O custo de manutenção dos parsers passar de ~1 correção por trimestre** → o custo permanente
   superou o valor; congelar em 1 formato canônico e aceitar cobertura parcial.
5. **Aparecer obrigação legal que exija conciliação formal fechando em zero** → o design continua
   servindo, mas o teto de simplicidade muda por força externa e a decisão vira "atender obrigação",
   não "dar clareza" — o que exige reabrir a conversa de posicionamento, não só de escopo.

---

## 12. Rastreabilidade (Artigo IV — No Invention)

| Afirmação deste design | Fonte |
|---|---|
| Não existe entidade de conta bancária | Grep total do repo (fato confirmado no briefing) |
| `saldo_inicial` usa `available_cents` | `financial_intelligence/projection.py:177` |
| `payables` não toca a Carteira | `payables/models.py:4` |
| Regra caixa vs. competência | `payables/models.py:6-9`, `receivables/models.py:6-9` |
| Sinal vem da tabela de origem | `financial_intelligence/dre.py` (docstring) |
| DRE agrega `charges` + `payables` + `transactions` | `dre.py:51,135-156` |
| `principal_cents` é digitado; não há aporte/resgate | `investments/models.py:49`, `investments/service.py:96-113` |
| Visibilidade da Charge de rendimento reservada ao @architect | `investments/service.py:27-37` |
| Filtro `investment:` em `list_charges`/`summary` | `receivables/service.py:53,82-89,270,698` |
| Estorno de `Charge` descartado por `platform_earnings` | `docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md` (Adendo), `CLAUDE.md` |
| Adapter com `is_configured()` + degradação | `core/payment_gateway.py`, ADR 0002 |
| Referências soltas sem FK dura | `charges.client_id`, `payables.contract_id`/`cost_center_id` |
| Padrão de RLS em migration | `migrations/versions/0049_investments.py::_enable_rls` |
| Armadilha do backfill sob FORCE RLS | `migrations/versions/0046_ledger_classification.py` |
| Head das migrations na data do design = 0057 (reconfirmado 2026-07-29) | `apps/api/migrations/versions/` |
| `engine._runway_signal` emite "Runway de N dias"; `diagnostics` repassa `proj.runway.days` | `engine.py:128-137`, `diagnostics.py:90` |
| O 🔴 de janela negativa nasce de `ProjectionWindow.alert` | `engine.py:140-148`, `projection.py:83,189` |
| `available_cents` nunca diminui ao pagar conta; `request_payout` só marca `withdrawn` (⇒ o `alert` é máquina de falso negativo) | `payables/models.py:4`, `wallet/service.py:227` |
| `WindowCard`/`TrajectoryChart` pintam vermelho a partir de `alert`/`anyAlert` | `ProjecaoCaixaPage.tsx:112-137,153-154` |
| `bank_balance_checkpoints.origin` já tem vocabulário `manual`\|`ofx` (⇒ `declarado`/`extrato` eram tradução redundante) | §2.4 deste design; Story 8.4 (constantes `ORIGIN_MANUAL`/`ORIGIN_OFX`) |
| `tenant_profiles` é a tabela de configuração por tenant e já carrega config operacional (`timezone`, `default_entry_funnel_id`) | `apps/api/app/modules/settings/models.py` |
| Conferência e sinal **por conta** (não consolidada) | decisão do fundador **F3** (2026-07-29), epic §3.2 |
| Vocabulário de origem em dois eixos; supressão do `alert`; revisions não fixadas; forma de `CompletenessInput`; assinatura de saldo em lote; casa da banda de tolerância | `docs/architecture/controle-bancario-design-ratificacao.md` (2026-07-29) |
| Bandeja de comprovantes e suas rotas | `payables/receipts_router.py`, `payables/receipts.py` |
| Dívida de isolamento por usuário em `/attachments` | `CLAUDE.md` (seção do comprovante mobile) |
| Motor de diagnóstico é puro, sem I/O | `financial_intelligence/engine.py` (docstring), PRD NFR3 |
| Anonimizador obrigatório antes da IA | `CLAUDE.md` Regra de Ouro nº 2, PRD NFR2 |
| Bancos entregam ~60 dias de extrato; OFX tem dialetos | Estudo §4.5 `[CONFIRMADO 2026-07-29]` |
| Teto de simplicidade (confirmar × construir) | Estudo §6.3 |
| Banda de tolerância; frase antes da tabela | Estudo I-15, I-14, §3.5 |
| Rótulo do menu muda a percepção do produto | Estudo I-23 |
| Vocabulário de `operation_nature` | **[SUPOSIÇÃO minha]** — derivado dos `grupo_dre` + eventos deste design |
| Janela de ±3 dias no enriquecimento | **[SUPOSIÇÃO minha, parametrizável]** |
| `max(R$ 50, 0,5%)` de tolerância | **[SUPOSIÇÃO minha, parametrizável]** — ordem de grandeza do estudo I-15 |
| Volume de ~40 movimentos/mês | **[ESTIMATIVA do estudo §2.5]** — base do argumento de saldo derivado |
| Se o OFX carrega CPF/CNPJ e Pix E2E | **[DEPENDE DE @analyst]** |
| Qual é a obrigação tributária concreta | **[DEPENDE DE @analyst]** |
