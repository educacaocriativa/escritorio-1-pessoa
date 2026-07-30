# Quality Gate — Epic 8 (Controle Bancário e Conferência), Onda 0 + Onda 1

> **Revisor:** Quinn (@qa) · **Data:** 2026-07-30
> **Branch:** `feat/controle-bancario-conferencia` @ `4da2a2e` (12 commits à frente de `origin/main`)
> **Escopo:** Stories 8.1 a 8.8 · 66 arquivos · +22.774/−90
> **Nada foi commitado nem enviado por este gate.** Foram alterados **três arquivos de teste**
> (correção de gate furado, ver TEST-001) e as seções `QA Results` das oito stories.

---

## Veredito

# ❌ FAIL

**Um** achado de severidade **alta**, em código novo, que produz exatamente o modo de falha que
este épico inteiro existe para impedir: **uma divergência que não existe, relatada com aparência de
fato**. É alcançável pela UI em dois cliques e está reproduzido abaixo com saída real.

Tudo o mais está em nível CONCERNS. A onda é, no restante, de qualidade alta e incomum: os gates
estruturais foram submetidos a **teste de mutação** e **todos os 10 mutantes morreram**; o
isolamento cross-tenant da conferência tem teste e2e em Postgres real que cobre inclusive o caminho
sem GUC; as três migrations encadeiam serialmente com `FORCE ROW LEVEL SECURITY` e policy
`tenant_isolation`. O FAIL é estreito e barato de limpar — uma guarda de ~10 linhas e um teste.

**Recomendação:** `@dev` corrige **BANK-001**; o gate reabre só sobre esse item.

---

## Os 7 quality checks

| # | Check | Resultado | Evidência |
|---|---|---|---|
| 1 | **Testes passando** | ✅ PASS | backend `1045 passed, 1 skipped, 22 deselected` (315,57s); `rls_e2e` `22 passed` (101,82s); frontend `288 tests / 50 files` |
| 2 | **Lint / typecheck** | ✅ PASS | `ruff check .` → *All checks passed!*; `tsc --noEmit` exit 0; `eslint . --max-warnings 0` exit 0 |
| 3 | **ACs implementados** | ⚠️ CONCERNS | Todos os ACs verificados em código. **AC8 da 8.7 (responsividade ~360px) não foi validado** — declarado pelo @dev, não simulado (G-4) |
| 4 | **Segurança / isolamento** | ✅ PASS | 3 migrations com `ENABLE` + `FORCE` + policy `tenant_isolation` (`USING` + `WITH CHECK`); `alembic heads` → **`0060 (head)`**, head único, `alembic branches` vazio; `test_conferencia_isolamento_cross_tenant` cobre o vazamento **e** o fail-closed sem GUC |
| 5 | **Regressão** | ✅ PASS | `dre.py` e `profitability.py` **não foram tocados** (`git diff --stat`); baseline `origin/main` 826 → 1045 testes, zero regressão; o módulo `bank` não referencia `paid_at`/`competence_date`/`due_date` em lugar nenhum — caixa × competência não se invertem porque o plano 3 não participa da DRE |
| 6 | **Qualidade dos testes (não-vácuo)** | ⚠️ CONCERNS | **10/10 mutantes mortos** (tabela abaixo). Mas o gate mais importante do épico tinha **evasão trivial** — corrigido neste gate (TEST-001) |
| 7 | **Documentação / rastreabilidade** | ⚠️ CONCERNS | Rastreio Art. IV excelente no código. Epic PRD e stories **dessincronizados** da ratificação em ~15 pontos (CodeRabbit); `shared-types/generated.ts` com **0** menções a `bank` |

---

## Achados por severidade

### 🔴 HIGH

#### BANK-001 — Editar `opening_date` para frente produz **divergência inventada**

**Arquivos:** `apps/api/app/modules/bank/service.py:367-368` (`update_account`) →
`apps/api/app/modules/bank/service.py:186-192` (`_movements_sums`, filtro `posted_at > opening_date`).
Superfície: `apps/web/src/features/financeiro/ContasSaldosPage.tsx:699,715` (o formulário de edição
envia `opening_date`); schema `apps/api/app/modules/bank/schemas.py:110`.

`_movements_sums` só soma movimentos com `posted_at > opening_date`. `update_account` aceita mover
`opening_date` para frente **sem nenhuma guarda**, e os movimentos anteriores à nova data param de
contar no saldo derivado — continuando **visíveis na lista**. A conferência então compara o
checkpoint (correto) contra um saldo derivado inflado e **relata um furo que não existe**.

O próprio service já articula por que isso é errado — mas só no caminho de criação
(`_validate_posted_at`, `service.py:496-499`): *"Aceitar a data e não somar o movimento seria pior
do que recusar: a linha existiria, o saldo não mudaria, e ninguém entenderia por quê."* A guarda
existe no `create` e falta no `update`.

**Reprodução (saída real, probe descartado após a execução):**

```
=== ANTES — abertura 01/06
    saldo_derivado=20000  movimentos_visiveis=1
    conferencia: banco=20000 sistema=20000 divergencia=0 dentro=True
=== PATCH opening_date -> 15/06 : 200 {"id":"ce5aff86-...","name":"Itau PJ",...}
=== DEPOIS — abertura 15/06
    saldo_derivado=100000  movimentos_visiveis=1
    conferencia: banco=20000 sistema=100000 divergencia=-80000 dentro=False
```

Cenário: conta aberta 01/06 com R$ 1.000; um débito de R$ 800 em 10/06; saldo declarado R$ 200 em
20/06 — **batendo exatamente**. Um `PATCH {"opening_date": "2026-06-15"}` responde **200**, sem
aviso, e a conferência passa a dizer *"seu saldo no banco está R$ 800,00 abaixo do que eu calculei —
provavelmente faltam lançamentos de saída"*. O lançamento de saída **existe** e está na tela.

**Por que é HIGH e não MEDIUM.** É a falha nº 1 da priorização deste gate: o dono vai caçar um
lançamento que já está lá, na frente dele. Depois da segunda caçada frustrada ele para de confiar no
sinal, e o sinal é o produto. Não é dívida herdada — `update_account` é código novo da Story 8.2.

**Recomendação (`@dev`, Story 8.2).** Espelhar no `update_account` a guarda que o `create` já tem:
recusar (422) mover `opening_date` para frente quando existir movimento com
`posted_at <= nova_data`, nomeando a data do movimento mais antigo. Mensagem no estilo da casa
(diz o que aconteceria, não só que é inválido). **+1 teste**, e um segundo confirmando que mover a
data **para trás** continua permitido. A guarda por si só não é suficiente sem o teste — este gate
mostrou que gate sem mutante é gate que não avisa.

---

### 🟠 MEDIUM

#### TEST-001 — Evasão trivial no gate da Regra dos Planos · **CORRIGIDO NESTE GATE**

**Arquivos:** `apps/api/tests/test_money_planes.py:59-75` (`_imported_modules`),
`apps/api/tests/test_financial_intelligence_completeness.py:358-369`,
`apps/api/tests/test_bank_reconciliation_report.py:776-782`.

Os três coletores de import por AST montavam o caminho como `f"{prefix}{node.module}"`, **sem
apensar o alias**. Consequência: `from app.modules import bank` produzia só `"app.modules"`, que não
casa com `startswith("app.modules.bank")` nem com `lstrip(".").startswith("bank")`. E o teste
redundante por texto cru (`test_wallet_nao_importa_bank_tambem_por_texto_cru`) procura a string
literal `"app.modules.bank"`, que essa forma de import **não contém**. Os dois furavam juntos.

Isto atinge `test_wallet_nao_importa_bank`, descrito na própria docstring como *"o teste de maior
valor da Story 8.2"* e *"a única defesa **permanente** contra a reintrodução do bug original numa
forma nova"* — e é a mitigação nomeada do risco nº 1 da tabela do epic §7.

**Evidência (antes da correção):** com `from app.modules import bank` dentro de
`app/modules/wallet/service.py`, a suíte ficou **verde**:

```
### EVASAO DO GATE: 'from app.modules import bank' dentro de wallet/
MUTADO
6 passed, 8 warnings in 1.30s
```

Mesma classe de furo em mais dois gates: `from app.core import ai` dentro de `engine.py` (a lista
`_IMPORTS_PROIBIDOS` tem `app.core.ai`, mas o coletor devolvia `"app.core"`) e
`from app.modules import wallet` dentro de `reconciliation.py`.

**Correção aplicada** (só teste, autorizado): o `ImportFrom` passa a devolver o módulo **e** o
caminho com cada alias apenso. Verificação pós-correção — os três mutantes agora morrem, e a
baseline segue verde (`65 passed` nos três arquivos; `1045 passed` na suíte completa):

```
### 2) evasao wallet -> 'from app.modules import bank' agora DEVE reprovar
FAILED tests/test_money_planes.py::test_wallet_nao_importa_bank
### 3) evasao engine -> 'from app.core import ai' agora DEVE reprovar
FAILED tests/test_financial_intelligence_completeness.py::test_iv1_engine_permanece_estritamente_puro
### 4) evasao conferencia -> 'from app.modules import wallet' agora DEVE reprovar
FAILED tests/test_bank_reconciliation_report.py::test_conferencia_nao_importa_wallet_nem_le_transactions
```

> ⚠️ **Para quem for copiar o padrão:** `tests/test_tenancy_guard.py` é a origem deste estilo. Vale
> conferir se ele carrega o mesmo furo — não foi auditado neste gate (fora do escopo do épico).

#### UX-001 — G-3 residual: **"no banco" nomeia dois números opostos**, em duas telas

**Arquivos:** `apps/web/src/features/financeiro/projecao.ts:131`
(`ROTULO_BANCO = "no banco"`, alimentado por `saldo_inicial_banco_cents` =
`bank.service.active_balance_total`, ou seja **o saldo que o e1p calculou**) ×
`apps/web/src/features/financeiro/ConferenciaPage.tsx:239`
(`<th>Saldo no banco</th>`, alimentado por `saldo_banco_cents` = o checkpoint, ou seja **o saldo que
o banco atestou**). A frase da conferência repete a colisão:
`apps/web/src/features/financeiro/conferencia.ts:153` — *"Seu saldo no banco está X abaixo do que eu
calculei"*.

A resolução do D-6 (`contas.ts:180-254`) está **correta e testada** para o par que ela endereçou —
*Contas & Saldos* × *Projeção*: dois rótulos distintos (`"Total em contas"` / `"Disponível como
caixa"`), um só cálculo, cada um com a sua `explicacao`, e testes que afirmam que nenhum deles é
`ROTULO_BANCO` (`contas.test.ts:153-161`, `ContasSaldosPage.test.tsx:92-107`). O par que ela **não**
endereçou é o mais perigoso: na Conferência, *"Saldo no banco"* é a coluna do banco e *"Saldo no
e1p"* é a do sistema; na Projeção, *"no banco"* é **a do sistema**. São as duas pontas exatas da
comparação cujo produto é a diferença entre elas, com a mesma palavra apontando para lados opostos.

**Recomendação (`@architect` decide o vocabulário, `@dev` aplica).** Duas saídas viáveis: (a) a
Projeção passa a rotular a parcela como *"nas suas contas"* / *"saldo calculado"*, liberando
*"no banco"* para significar só o que o banco atesta; ou (b) a Conferência renomeia a coluna para
*"O que o banco diz"* × *"O que o e1p calculou"* — que já é como a tela se explica em prosa.
Preferência do gate: **(b)**, porque a tela da conferência é onde o usuário está prestes a errar, e
porque o par "diz/calculou" carrega a diferença conceitual, não só nomes diferentes. O teste que
existe (`not.toContain(ROTULO_BANCO)`) deve ser estendido à `ConferenciaPage`.

#### SIG-001 — A virada de mês apaga uma conferência recente e bem-sucedida

**Arquivos:** `apps/api/app/modules/financial_intelligence/diagnostics.py:111` (passa a janela do
diagnóstico direto para `reconciliation_report`) × `apps/web/src/features/financeiro/DiagnosticoPage.tsx:30,38`
(`monthRange(currentMonth)` — a janela é o **mês corrente**).

O bloco 1 da conferência (por desenho correto, `reconciliation.py:328-330`) só compara com
checkpoint **dentro** da janela. Como o consumidor amarra a janela ao mês do calendário, um saldo
declarado em 28/06 que **bateu exatamente** deixa de valer em 01/07.

**Reprodução (saída real, probe descartado):**

```
=== JUNHO (mes da declaracao)
    [verde] Lançamentos batendo com o banco :: Está tudo batendo: maior divergência de R$ 0,00 na conta Itau PJ, dentro da tolerância de R$ 50,00
=== JULHO (mes seguinte, 3 dias depois)
    [amarelo] Não sei se os lançamentos estão completos :: Conta Itau PJ: sem saldo declarado na janela — não sei se os lançamentos dela estão completos
```

Nada mudou entre as duas leituras exceto o mês pedido. Pior: o motor **tem** o dado
(`dias_desde_ultima_conferencia = 3`, entregue pelo bloco 4 da 8.5 justamente para isso) e **não o
usa** na mensagem, porque `3 <= _COMPLETENESS_STALE_DAYS` e o motivo só é acrescentado acima do
limiar (`engine.py:249-252`). O usuário é informado de "não sei" sem menção de que conferiu há três
dias e bateu.

Não é número falso — é honesto sobre a janela. Mas dispara de forma **determinística no início de
todo mês, para toda conta**, o que torna o 🟢 inalcançável nos primeiros dias e treina o usuário a
ignorar o amarelo — exatamente o vício que a banda de tolerância e o Ajuste 2 da ratificação D-2
existem para evitar, e o risco *"Abandono da conferência"* do epic §7.

**Recomendação (`@architect`).** O design §5.1 não previu que o consumidor amarraria a janela da
conferência ao mês da DRE. Menor mudança que resolve: quando `divergencia_cents is None` **e**
`dias_desde_ultima_conferencia` for pequeno, o 🟡 dizer *"confirmado há N dias, fora desta janela"*
em vez de *"sem saldo declarado na janela"* — o dado já chega ao motor. Alternativa mais estrutural:
`_completeness` usar janela deslizante própria, desacoplada do período do diagnóstico.

#### REL-001 — Ações de movimento falham em silêncio na tela

**Arquivo:** `apps/web/src/features/financeiro/ContasSaldosPage.tsx:445-470` — `ignorar`,
`desfazerIgnorar` e `removerDeclaracao` chamam a API sem `try/catch`. Numa falha (422/409/rede) a
promise rejeita, `load()`/`onChanged()` não rodam e **nada aparece na tela**: o usuário conclui que
o clique não pegou, ou pior, que pegou. As demais mutações da página tratam erro; estas três não.
Achado do CodeRabbit, confirmado por leitura. **Recomendação:** `catch` → `setError(...)`, mesmo
padrão do resto do arquivo.

#### MNT-001 — (pré-existente, 17 call sites) `audit.record` grava `target=''`

O `id` tem default *Python-side* (`app/db/base.py:15`, `_uuid`), aplicado só no INSERT. Onde
`audit.record(..., target=obj.id)` roda **antes** de `db.flush()`/`db.commit()`, o rastro nasce
apontando para nada. O módulo `bank` faz o `flush` antes e está **correto** — e documenta o achado
em `service.py:339-343`.

**Confirmado empiricamente** (probe descartado; `repr()` do `target` gravado):

```
=== bank         201 ["'4556abfa-1017-49df-93a3-334cf114265d'"]
=== chart        201 ["''"]
=== cost_center  201 ["''"]
=== crm          201 ["''"]
```

**Varredura AST completa — 17 ocorrências do padrão:**

| Módulo | Função | Linha do `audit.record` |
|---|---|---|
| `agenda/service.py` | `create_event` | 115 |
| `attachments/service.py` | `create_attachment` | 74 |
| `attachments/service.py` | `create_public_image` | 138 |
| `chart_of_accounts/service.py` | `create_account` | 65 |
| `contracts/service.py` | `create_template` | 112 |
| `cost_centers/service.py` | `create_cost_center` | 47 |
| `crm/service.py` | `create_stage` | 81 |
| `crm/service.py` | `create_client` | 167 |
| `funnels/service.py` | `create_funnel` | 269 |
| `integrations/service.py` | `create_key` | 68 |
| `investments/service.py` | `create_account` | 90 |
| `juridico/service.py` | `generate` | 156 |
| `marketing/service.py` | `create_carousel` | 140 |
| `pages/service.py` | `create_page` | 120 |
| `products/service.py` | `create_product` | 47 |
| `products/service.py` | `create_coupon` | 100 |
| `whatsapp_templates/service.py` | `create_template` | 97 |

**Severidade: MEDIUM, não HIGH** — não corrompe dado de negócio e nenhuma funcionalidade depende do
`target`. Mas é a Regra de Ouro nº 3 (*rastro da IA*) e o log de auditoria de **todas** as criações
do produto: hoje eles registram que algo foi criado sem dizer o quê. **Fora do escopo desta onda.**

**Recomendação:** story de follow-up própria, `@dev`. O `fix` é `db.flush()` antes do `audit.record`
em cada um (o `bank` é o modelo), + um teste estrutural no estilo desta varredura para não voltar —
a varredura AST usada aqui está pronta e vale ser convertida em gate permanente.

---

### 🟢 LOW

| ID | Achado | Arquivo:linha |
|---|---|---|
| MNT-002 | `days_since_last_declared_balance` entregue pelo AC7 da 8.4 e **sem nenhum consumidor** (só testes). A docstring já alerta que a semântica difere do campo homônimo da 8.5 — API pública não exercitada, com armadilha documentada | `apps/api/app/modules/bank/service.py:914` |
| MNT-003 | `scripts/check.sh` mascara falha do vitest com `\|\| true` e resolve `ruff`/`python` do PATH (não do venv) — um verde do `check.sh` **não** é evidência de suíte verde | `scripts/check.sh:14,20,26` |
| REL-002 | Conta **arquivada** sai do laço da conferência (`list_accounts` esconde arquivadas) sem nenhuma nota. Arquivar uma conta com furo em aberto o remove do relatório, do `contas_fora_da_banda` e do 🔴 do diagnóstico. É decisão deliberada e documentada, mas nada avisa o usuário | `apps/api/app/modules/bank/reconciliation.py:440-444` |
| DOC-001 | `packages/shared-types/src/generated.ts` tem **0** menções a `bank`. As telas usam tipos locais (padrão vigente), então nada quebra — mas o contrato compartilhado ficou mais defasado, e não há check de drift no CI | `packages/shared-types/src/generated.ts` |
| DOC-002 | `CLAUDE.md` §6.1 ainda diz que CPF/CNPJ *"só valida tamanho"*; `core/validators.py` já valida dígito verificador | `CLAUDE.md` §6.1 |
| DOC-003 | Epic PRD e stories dessincronizados da ratificação em ~15 pontos (números de migration fixos, `declarado` em `*_origem`, `max()` do AC7 da 8.6, assinaturas de contrato). Não afeta código; afeta quem ler o epic depois | ver seção CodeRabbit |

---

## Teste de mutação — os gates não são vácuo

Dez mutações aplicadas ao código de produção, cada uma restaurada com `git restore` logo após a
execução (árvore verificada limpa a cada passo). **Todos os 10 mutantes foram mortos.**

| # | Mutação | Gate que deveria pegar | Resultado |
|---|---|---|---|
| M1 | `engine.py` importa `sqlalchemy.orm.Session` | pureza IV1 (8.6) | ✅ `FAILED test_iv1_engine_permanece_estritamente_puro` — `assert not ['sqlalchemy.orm']` |
| M2 | Conferência chama `derived_balances_as_of(as_of=end)` | proibição AC4b (8.5) | ✅ `FAILED test_conferencia_nao_usa_derived_balances_as_of` |
| M3 | `wallet/service.py` importa `app.modules.bank` | Regra dos Planos §1.3b | ✅ 2 testes falharam (AST + texto cru) |
| M4 | `declare_balance` grava `opening_balance_cents = balance_cents` | *"o checkpoint não corrige o derivado"* (8.4) | ✅ 4 testes falharam, incl. `test_checkpoint_nao_altera_saldo_derivado` e `test_checkpoint_nao_altera_projecao_de_caixa` |
| M5 | `_movements_sums` perde o filtro `status <> 'ignored'` | AC5 da 8.3 | ✅ 4 testes falharam |
| M6 | `total_divergencia_cents` colapsa `None` em `0` | *"None ≠ zero"* | ✅ 3 testes falharam, incl. `test_conta_sem_checkpoint_nenhum_e_indisponivel` |
| M7 | `_fora_da_banda` usa `not c.dentro_da_tolerancia` | divergência **inventada** em conta não avaliada | ✅ 5 testes falharam |
| M8 | Borda da banda vira `<` em vez de `<=` | silêncio na borda `==` | ✅ 2 testes de borda falharam (regime do piso **e** do percentual) |
| M9 | Conferência compara com `until=end` em vez da data do checkpoint | comparação em datas diferentes | ✅ `test_movimento_posterior_a_referencia_nao_muda_a_divergencia` + `test_cada_conta_usa_a_SUA_data_de_referencia` |
| M10 | Checkpoint **fora** da janela aceito no bloco 1 | divergência inflada | ✅ `test_checkpoint_fora_da_janela_segue_indisponivel_mas_conta_os_dias` |

**A exceção é o TEST-001**: o gate da Regra dos Planos morria para `import app.modules.bank` (M3) e
**sobrevivia** a `from app.modules import bank`. Corrigido, e a correção foi verificada por mutação.

---

## Decisões G-1 a G-4

### G-1 — O gate global `test_todo_saldo_declara_origem`

> **Decisão: ADIAR COM REGISTRO FORMAL.** Não criar agora; não deixar morrer em silêncio. A
> cobertura por instância **é suficiente para esta onda** e **não é suficiente como resposta
> permanente**. Duas perguntas de desenho, ambas da `@architect`, bloqueiam a criação.

Não é decisão de opinião — é o que o inventário mostra. Varredura AST de **todo** campo
`saldo_*_cents` anotado em classe (dataclasses + schemas Pydantic) do `apps/api/app`:

| Campo | Classe | Irmão `*_origem`? |
|---|---|---|
| `saldo_banco_cents` | `reconciliation.ConferenciaConta` | sim |
| `saldo_sistema_cents` | `reconciliation.ConferenciaConta` | sim |
| `saldo_derivado_cents` | `bank.schemas.BankAccountOut` | sim |
| `saldo_derivado_cents` | `bank.schemas.BankBalanceOut` | sim |
| `saldo_banco_cents` | `bank.schemas.ConferenciaContaOut` | sim |
| `saldo_sistema_cents` | `bank.schemas.ConferenciaContaOut` | sim |
| `saldo_inicial_cents` | `projection.CashProjection` | sim |
| `saldo_inicial_cents` | `fi.schemas.ProjectionOut` | sim |
| **`saldo_projetado_cents`** | `projection.ProjectionWindow` | **NÃO** |
| **`saldo_projetado_cents`** | `fi.schemas.ProjectionWindowOut` | **NÃO** |
| **`saldo_inicial_banco_cents`** | `projection.CashProjection` | **NÃO** (G-2) |
| **`saldo_inicial_plataforma_cents`** | `projection.CashProjection` | **NÃO** (G-2) |
| **`saldo_inicial_banco_cents`** | `fi.schemas.ProjectionOut` | **NÃO** (G-2) |
| **`saldo_inicial_plataforma_cents`** | `fi.schemas.ProjectionOut` | **NÃO** (G-2) |

**14 campos, 6 sem irmão** — e mais **8 campos que carregam saldo e o regex `saldo_*_cents` nem
alcança**: `BankAccount.opening_balance_cents`, `BankTransaction.balance_after_cents`,
`BankBalanceCheckpoint.balance_cents`, `BankAccountCreate/Update/Out.opening_balance_cents`,
`CheckpointCreate/Out.balance_cents`.

Escrever o gate hoje, ao pé da letra da ratificação, exigiria **eu** decidir duas coisas que não são
de teste:

1. **`saldo_projetado_cents` precisa de `saldo_projetado_origem`?** O @dev da 8.1 nomeou exatamente
   isto ao não implementar o gate; o D-5 da ratificação **não lista** esse campo. A resposta importa:
   é o número que o D-5 mandou continuar exibindo *com a premissa rotulada ao lado* — logo a
   procedência dele é a discussão inteira da Onda 0.
2. **A regra é sobre o prefixo `saldo_` ou sobre saldo?** `CheckpointOut.balance_cents` é a verdade
   externa atestada pelo banco e viaja **sem** procedência; ela só ganha `saldo_banco_origem` quando
   a conferência a re-expõe. Um gate que não alcança o campo onde o vocabulário do épico nasceu é um
   gate que confere a ortografia, não a regra.

**Por que a cobertura por instância não encerra o item.** Existem hoje **três** varredores
independentes (`test_bank_reconciliation_report`, `test_projection_saldo_misto`,
`test_bank_accounts`), **duas** allowlists com justificativa escrita e **zero** auditor global. Um
schema novo numa story futura não é coberto por nenhum deles — e é precisamente o cenário que o
argumento *"sem o teste, o resto degrada por acidente"* descreve. A `@architect` manteve o
`*_origem` degenerado da conferência (que não informa nada) **em nome desse gate**; sem ele, aquele
campo é custo sem contrapartida.

**Encaminhamento:** item nomeado para `@architect` responder as duas perguntas; depois é uma story de
teste de ~0,25 onda. O inventário acima é o artefato — o item não pode mais morrer por esquecimento.

### G-2 — A allowlist da 8.8

> **Decisão: ACEITA.** O argumento do @dev está correto e é mais forte do que a alternativa.

`saldo_inicial_banco_cents` e `saldo_inicial_plataforma_cents` não são dois saldos independentes que
precisam se identificar — são a **decomposição declarada** de `saldo_inicial_cents`, cuja origem é
`saldo_inicial_origem = "misto"`, e `misto` é definido em `money_planes.py:67-69` como *"a soma
rotulada dos planos 3 + 1"*. O **nome de cada parcela é o valor de `ORIGENS` a que ela pertence**.
Um `saldo_inicial_banco_origem = "banco"` constante não carregaria informação — carregaria a
aparência de verificação. O que precisa ser aferido no lugar dele é que a decomposição usa o
vocabulário canônico e que **a soma fecha**, e é o que
`test_todo_saldo_da_projecao_declara_origem` faz (`test_projection_saldo_misto.py:613-635`), nos
dois estados da story.

Duas ressalvas registradas, nenhuma bloqueante:

- a justificativa está escrita e é auditável — o padrão certo (mesmo de `test_tenancy_guard.py`);
- é a **segunda** allowlist do épico sem auditor global. Não é problema desta story; é mais um voto a
  favor de resolver o G-1. Se a `@architect` preferir os irmãos redundantes, a mudança é **aditiva** e
  cabe em duas linhas do schema, como a própria story registra.

### G-3 — Os dois totais (D-6)

> **Decisão: PARCIALMENTE RESOLVIDO.** O par que o D-6 endereçou está certo e testado. O par que ele
> não viu é o mais perigoso e continua aberto → **UX-001** (MEDIUM).

Resposta direta à pergunta *"um usuário real consegue ver dois números que parecem a mesma coisa e não
são?"* — **sim, ainda consegue**, mas não onde se procurou:

| Onde | Rótulo | O que o número é |
|---|---|---|
| Contas & Saldos | *"Total em contas"* | Σ derivado de **todas** as contas ativas |
| Contas & Saldos | *"Disponível como caixa"* | Σ derivado **excluindo aplicação** |
| Projeção de Caixa | **"no banco"** | Σ derivado excluindo aplicação — **o que o e1p calculou** |
| Conferência | **"Saldo no banco"** | o checkpoint — **o que o banco atestou** |
| Conferência | *"Saldo no e1p"* | o derivado daquela conta |

A disciplina aplicada em `contas.ts` é exemplar: um cálculo, dois rótulos, cada um com a sua
`explicacao`, a segunda linha só aparece quando existe aplicação ativa (senão seria ruído), e há
teste afirmando que nenhum dos dois é `ROTULO_BANCO` e que a página não contém a string. O que
escapou é que *"no banco"* **já estava tomado** pela Conferência, com o sentido oposto.

### G-4 — Validação visual em ~360px

> **Decisão: ITEM DE ACEITE MANUAL PENDENTE.** Não foi feita, não simulo que foi, e **não bloqueia
> o merge** — bloqueia o *release*, e a decisão de soltar sem ela é do fundador.

O @dev da 8.7 declarou explicitamente que não validou. O código está preparado
(`ConferenciaPage.tsx:234` com `overflow-x-auto` + `min-w-[56rem]`; 13 marcadores responsivos em
`ContasSaldosPage.tsx`, 7 em `ConferenciaPage.tsx`), e a suíte de componente cobre comportamento,
não layout. **Nada disto é evidência de que um aparelho de ~360px mostra o que precisa mostrar.**

O repositório já pagou **duas vezes** por pular exatamente esta verificação, no mesmo mês: PR #56
(sidebar de 256px fixos escondendo o checkbox *"marcar como paga"* — uma conta real foi baixada sem
o usuário conseguir ver) e PR #58 (checkbox separado do botão Anexar; `overflow-hidden` cortando os
botões Estornar/Editar). `docs/CHECKLIST-COMPROVANTE-MOBILE.md` existe por causa desses dois
incidentes.

**O que precisa ser olhado em aparelho real, em ~360px:**

1. `/financeiro/contas` — a **frase** e os totais rotulados aparecem antes de qualquer rolagem?
2. `/financeiro/contas` — os botões *Declarar saldo* / *Lançar movimento* / *Arquivar* estão todos
   alcançáveis, e **Arquivar não fica adjacente** a um botão de uso frequente?
3. `/financeiro/conferencia` — a tabela rola de fato (`overflow-x-auto`), e as colunas **Divergência**
   e **Tolerância** são alcançáveis? São elas que dizem se há furo.
4. `/financeiro/conferencia` — a frase da conta (o produto da tela) é legível **sem** rolagem
   horizontal?
5. `/financeiro/projecao` — as **duas parcelas** do saldo inicial aparecem juntas, sem que uma
   quebre para fora da vista (a composição visível é o preço que o design cobra para autorizar a soma).

---

## CodeRabbit

Executado com sucesso — **sem** o artefato CRLF de 500+ arquivos conhecido deste ambiente. Os 66
arquivos corretos foram revisados.

```
coderabbit review --agent --committed --base main
{"type":"complete","status":"review_completed","findings":27,"reviewedFiles":[... 66 arquivos ...]}
```

Aviso registrado: *"educacaocriativa/escritorio-1-pessoa is not connected to a CodeRabbit
organization you can access, so this review will use the free CLI allowance."*

| Severidade | Qtd | Destino |
|---|---|---|
| critical | 1 | Design da Onda 3 (dedup sem FITID reimportando o mesmo arquivo) — **fora do escopo liberado**, registrado para o gate da Onda 3 |
| major | 17 | **2 de código**, ambos adotados: BANK-001 e REL-001. Os outros 15 são dessincronização epic/story × ratificação (DOC-003) |
| minor | 9 | Documentação e Change Log |

O achado do TEST-001 partiu do CodeRabbit (`test_money_planes.py:70-74`) e foi confirmado por
mutação antes de ser corrigido.

---

## Comandos executados (saída real)

```
$ alembic heads
0060 (head)
$ alembic branches
(vazio — nenhum branch point)

$ ruff check .
All checks passed!

$ python -m pytest -q -m "not rls_e2e"
1045 passed, 1 skipped, 22 deselected, 2147 warnings in 315.57s (0:05:15)

$ python -m pytest -q -m "rls_e2e"
22 passed, 1046 deselected in 101.82s (0:01:41)

$ pnpm --filter @e1p/web typecheck     # tsc --noEmit
=== TSC EXIT: 0 ===
$ pnpm --filter @e1p/web lint          # eslint . --max-warnings 0
=== LINT EXIT: 0 ===
$ pnpm --filter @e1p/web test
 Test Files  50 passed (50)
      Tests  288 passed (288)
```

> ⚠️ `scripts/check.sh` **não** foi usado como evidência (MNT-003): ele resolve `ruff`/`python` do
> PATH, que aqui não aponta para `apps/api/.venv`, e mascara falha do vitest com `|| true`. As etapas
> acima foram rodadas individualmente com `apps/api/.venv/Scripts/`.

---

## O que precisa de decisão antes do PR

| # | Item | Quem decide | Bloqueia o PR? |
|---|---|---|---|
| 1 | **BANK-001** — guarda de `opening_date` no `update_account` + 2 testes | `@dev` (Story 8.2) — é correção, não decisão | **SIM** |
| 2 | **UX-001** — qual das duas telas cede a palavra *"no banco"* | `@architect` | Não, mas é barato agora e caro depois de o usuário aprender o rótulo errado |
| 3 | **SIG-001** — a janela da conferência deve seguir o mês do diagnóstico? | `@architect` | Não |
| 4 | **G-1** — `saldo_projetado_cents` precisa de irmão? A regra é sobre o prefixo ou sobre saldo? | `@architect` | Não |
| 5 | **G-4** — soltar para produção sem a validação em ~360px | **fundador** | Não bloqueia merge; bloqueia release |
| 6 | **MNT-001** — 17 call sites com `target=''` viram story de follow-up? | `@po` / fundador | Não |
| 7 | **DOC-003** — reconciliar epic/stories com a ratificação | `@pm` / `@po` | Não |

---

## Alterações feitas por este gate

| Arquivo | O que mudou | Autorização |
|---|---|---|
| `apps/api/tests/test_money_planes.py` | `_imported_modules` passa a apensar o alias do `ImportFrom` (TEST-001) | teste, correção de gate furado |
| `apps/api/tests/test_financial_intelligence_completeness.py` | idem | teste |
| `apps/api/tests/test_bank_reconciliation_report.py` | idem, no coletor inline | teste |
| `docs/stories/8.1` … `8.8` | seção `QA Results` preenchida | seção do @qa |
| `docs/stories/8.2.story.md` | **Status: InReview → InProgress** (dono do BANK-001) | veredito FAIL |
| `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` | este arquivo | artefato do gate |

**Nenhum código de produção foi alterado.** As dez mutações do teste de mutação foram revertidas com
`git restore` imediatamente após cada execução, e a árvore foi verificada limpa a cada passo.

---
---

# RE-GATE — 2026-07-30 (2ª passagem)

> **Revisor:** Quinn (@qa) · **HEAD:** `63a5a52` · **Base do re-gate:** `4da2a2e` (o HEAD do 1º gate)
> **Seção acrescentada, não substitui nada acima.** O gate original permanece como registro do que
> foi encontrado; esta seção registra o que foi verificado depois das correções.

## Veredito do re-gate

# ✅ CONCERNS

**O FAIL está levantado.** BANK-001 e REL-001 foram fechados, e eu os verifiquei reproduzindo o
cenário original e aplicando **9 mutações novas** — não pela palavra de ninguém. Sobram apenas itens
que não bloqueiam o merge: dois que precisam de decisão da `@architect` (UX-001, SIG-001), um item
de aceite manual do fundador (G-4) e dívidas pré-existentes ao épico.

**Por que CONCERNS e não PASS:** UX-001 continua aberto e é um defeito de confiança real (*"no
banco"* nomeando os dois lados opostos da comparação), e a validação em ~360px segue sem ter sido
feita por ninguém. Nenhum dos dois é blocker de PR — são decisão de dono, não correção de @dev.

---

## Evidência executada (foreground, interpretador do venv)

```
$ ruff check .
All checks passed!

$ python -m pytest -q -m "not rls_e2e"
1051 passed, 1 skipped, 22 deselected, 2173 warnings in 316.65s (0:05:16)

$ python -m pytest -q -m "rls_e2e"
22 passed, 1052 deselected in 103.31s (0:01:43)

$ pnpm --filter @e1p/web typecheck     # tsc --noEmit
=== TSC OK ===
$ pnpm --filter @e1p/web lint          # eslint . --max-warnings 0
=== LINT OK ===
$ pnpm --filter @e1p/web test
 Test Files  50 passed (50)
      Tests  294 passed (294)
```

Backend `1051` = os `1050` declarados pelo coordenador **+1** teste que acrescentei (ver RG-1).
Frontend `294` = os `293` declarados **+1** (ver RG-3).

---

## 1 · BANK-001 — **FECHADO**

### O cenário original do gate, reproduzido

Mesmo caso que devolvia `200` e `divergencia=-80000`:

```
=== [1] CENARIO ORIGINAL DO GATE
    ANTES : derivado=20000 banco=20000 sistema=20000 div=0 dentro=True
    PATCH opening_date -> 15/06 : 422
    MSG: Esta conta tem 1 movimento lançado em 2026-06-10. Mover a data de abertura para
         2026-06-15 tiraria esse lançamento do saldo desta conta, mas ele continuaria aparecendo
         na lista de movimentos: o saldo mudaria sozinho e a conferência acusaria uma diferença
         que não existe. Se quem está com a data errada é o movimento, corrija a data dele
         primeiro. Se a conta recomeçou do zero, arquive-a e cadastre-a [...]
    DEPOIS: derivado=20000 banco=20000 sistema=20000 div=0 dentro=True
```

A divergência inventada não acontece mais, e a mensagem faz o que uma boa recusa faz: diz **o que
aconteceria**, não só que é inválido, e oferece saída.

### As três decisões de borda — **as três estão certas**

| Borda | Comportamento verificado | Julgamento |
|---|---|---|
| Mover **para trás** é livre | `200`; e o teste `..._para_tras_continua_permitido_e_pode_reparar` fabrica o órfão por escrita direta e prova que o movimento **volta a somar** | ✅ **Certa.** Recuar só pode *acrescentar* ao conjunto que soma (`posted_at > opening_date`) — não existe órfão a criar. E é o único caminho de reparo para o dado que já ficou torto antes da guarda existir. Bloquear seria proibir o conserto |
| `posted_at == nova_data` é **recusado** | `422` na data exata; `200` em `nova_data = posted_at − 1d` | ✅ **Certa, e é a borda que mais importa.** `_movements_sums` soma com `>` estrito, então o movimento *na* data de abertura ficaria órfão igual. É a mesma assimetria que a 8.4 fixou em `_validate_reference_date` (movimento `>`, checkpoint `>=`) — coerência, não coincidência |
| Movimento `ignored` **conta** | `422` mesmo com o saldo já sem ele (`saldo=100000`, o mov já fora), com nota própria na mensagem | ✅ **Certa, e é a mais sutil das três.** Hoje não muda número nenhum — o argumento é sobre o **futuro**: `unignore_transaction` promete *"devolve o movimento ao saldo"*, e depois da data movida ela não teria como cumprir. Seria o BANK-001 de novo, com o gatilho adiado para um clique. Escolher o inverso (deixar passar) seria otimizar por permissividade contra uma promessa escrita no próprio service |

### Mutação — 4 mutantes, 4 mortos

Os 3 do @dev conferem, e apliquei um 4º que ele não fez:

| # | Mutação | Resultado |
|---|---|---|
| MG1 | Guarda inteira removida de `update_account` | ✅ `3 failed` — os três testes de borda |
| MG2 | `posted_at <= nova` vira `<` | ✅ `1 failed` — `test_patch_opening_date_na_data_exata_do_movimento_422` |
| MG3 | `status != STATUS_IGNORED` acrescentado à guarda (exclui ignorados) | ✅ `1 failed` — `..._conta_movimento_ignorado` |
| **MG4** | **Filtro `bank_account_id == account.id` removido** | ❌ **SOBREVIVEU** (`51 passed`) → ver RG-1 |

### RG-1 (LOW) — o filtro mais importante da guarda não era testado · **FECHADO por mim**

Removendo `BankTransaction.bank_account_id == account.id` de `_validate_opening_date_move`, a suíte
inteira ficava **verde**. Nada exercitava "movimento da conta A não pode bloquear a edição da conta B".

O que a ausência causaria é o **espelho exato do BANK-001**: em vez de divergência fantasma, um
**bloqueio fantasma** — `422` numa edição legítima, com uma mensagem nomeando *"1 movimento lançado
em ..."* que o usuário não acha em lugar nenhum daquela conta, porque está em outra. Mesmo tipo de
dano: o sistema afirmando com precisão algo que não é verdade sobre a conta que ele está olhando.

**Acrescentado** `test_patch_opening_date_ignora_movimento_de_OUTRA_conta_do_mesmo_tenant`
(`apps/api/tests/test_bank_accounts.py`), com as duas contas no **mesmo tenant** de propósito — a RLS
não protege aqui, ela esconde tenant vizinho, não conta vizinha. Verificado: com o teste, MG4 morre
(`1 failed, 51 passed`). Código de produção **não** foi tocado — está correto hoje.

### RG-2 (LOW, cosmético) — concordância quebrada na mensagem do caso `ignored`

Em `_validate_opening_date_move`, o @dev montou a concordância em pedaços (`"Ele está ignorado"` vs
`"Eles estão ignorados"`) e depois concatena um sufixo fixo no **plural**:

> "Ele está ignorado: hoje isso já **os** deixa fora do saldo, mas depois da mudança desfazer o
> 'ignorar' deixaria de **devolvê-los** a ele, sem avisar."

Singular + plural na mesma frase. Só aparece com **exatamente 1** movimento ignorado — que é o caso
mais comum. Não corrigido (código de produção). Custo: duas variantes do sufixo, ~4 linhas.

---

## 2 · REL-001 — **FECHADO**

### A preocupação do @dev sobre vácuo: **confirmada como resolvida**

Ele reportou que a 1ª versão do teste de sucesso contava `api.get` no total e não matava o mutante
"sucesso sem `load()`", porque `onChanged()` é o `load()` da **página** e sobe o contador sozinho.
A versão final conta só `/bank/transactions`. **Verificado por mutação — não é vácuo:**

| # | Mutação em `ContasSaldosPage.tsx` | Resultado |
|---|---|---|
| MR1 | `catch` removido de `ignorar` (volta ao bug original) | ✅ `1 failed` — o teste de falha |
| MR2 | `catch { }` engolindo em silêncio (o anti-padrão clássico) | ✅ `1 failed` — o teste de falha |
| **MR3** | **`load()` removido do sucesso de `ignorar`, `onChanged()` mantido** — *o mutante exato que enganou a 1ª versão* | ✅ **`1 failed`** — `"ignorar: no sucesso recarrega a lista"` |
| MR4 | `load()` removido do sucesso de `removerDeclaracao` | ✅ `1 failed` |
| MR5 | `load()` removido do sucesso de `desfazerIgnorar` | ❌ **SOBREVIVEU** (`16 passed`) → ver RG-3 |

O par falha+sucesso é a forma certa, e o @dev acertou ao desconfiar do próprio teste: um `catch` que
engolisse tudo passaria no teste de falha sozinho. **A autocorreção dele se sustenta sob mutação.**

### RG-3 (LOW) — a terceira ação não tinha par de sucesso · **FECHADO por mim**

`desfazerIgnorar` ficou só com o teste de falha (o @dev declarou: *"par de sucesso de **dois**"*), e
removendo o `load()` do caminho feliz dela a suíte ficava verde. O dano é menor que o das irmãs, mas
é da mesma família: `unignore` **devolve** dinheiro ao saldo, e sem o `load()` do detalhe o movimento
segue desenhado como ignorado enquanto o saldo da página (recarregado por `onChanged()`) já mudou —
dois números na mesma tela contando histórias diferentes sobre a mesma ação.

**Acrescentado** o par de sucesso em `ContasSaldosPage.test.tsx`. Verificado: MR5 agora morre
(`1 failed, 16 passed`). Código de produção **não** foi tocado.

### Decisão de UX do @dev, julgada

Fechar o modal **antes** de saber o desfecho, deixando a mensagem na seção atrás do overlay: ✅
**certa**. A alternativa (manter aberto) mostraria exatamente o nada de antes, já que o elemento de
erro vive na seção. Perder o motivo digitado é o preço menor — ele é opcional e curto; a informação
de que a ação não aconteceu, não.

---

## 3 · Auditoria do `test_tenancy_guard.py` — **a leitura do coordenador está certa, e o furo é maior**

**Confirmado ponto a ponto:**

- ✅ Não usa AST — é substring (`if "get_db" in source`), então **não** tem a evasão de alias.
- ✅ **Nenhuma violação hoje.** Os dois hits fora de router são menções em docstring
  (`platform/service.py:269`, `whatsapp_inbox/service.py:86`) e os dois módulos estão na ALLOWLIST.
- ✅ `bank` **não** está na ALLOWLIST e usa `get_tenant_db` em todas as rotas
  (`bank/router.py:24,117,136,...`).
- ✅ Varredura completa: **nenhum** módulo fora da ALLOWLIST cita `get_db` — nem em `router.py`, nem
  em qualquer `.py` de `app/modules/`.

**O que o coordenador descreveu como hipótese é, na verdade, concreto.** O ponto cego não é só
*"um `service.py` poderia"* — **existe hoje um arquivo de rota real, montado, fora da varredura**:

```
glob atual: 29 arquivos | glob amplo: 30 arquivos
arquivos que ENTRARIAM na varredura: ['app\modules\payables\receipts_router.py']
```

`app/modules/payables/receipts_router.py` é incluído no app (`app/modules/__init__.py:31,56`) e o
glob `*/router.py` não casa com ele — o nome do arquivo não é `router.py`. **A própria docstring do
teste sempre disse `**/router.py`**; era a implementação que discordava dela.

E é justamente o módulo da bandeja de comprovantes, onde o `CLAUDE.md` já registra uma ressalva de
isolamento por usuário.

**Provado por mutação:** com `from app.db.session import get_db` dentro de `receipts_router.py`, a
guarda passava (`2 passed`).

### RG-4 — **FECHADO por mim** (era grátis, e eu medi antes)

Antes de mexer, medi o custo de ampliar:

```
violacoes sob o glob AMPLO: NENHUMA
se varresse TODO .py de modules (fora da allowlist): NENHUMA
```

Zero violação pré-existente — ampliar não arrasta nada para dentro deste PR. `_module_routers()`
passou a varrer qualquer arquivo com `router` no nome (`rglob`), que é a intenção já documentada.
Verificado: o mutante agora reprova (`1 failed`), baseline verde.

**Resposta à pergunta do coordenador — follow-up ou bloqueante?** Nem um nem outro:
**a parte que era barata e provadamente grátis eu fechei agora**, porque um router real invisível a
uma guarda de isolamento não é dívida de arquitetura, é um bug de uma linha no glob.

**O que fica como follow-up (LOW, fora deste PR):** a guarda só olha arquivos de **rota**. Um
`service.py` que abrisse sessão global continua passando. Não ampliei para todo `.py` de propósito —
a guarda é substring e não distingue código de prosa, então varrer tudo transformaria qualquer
docstring que cite `get_db` em falso positivo (exatamente o caso de `platform/service.py:269` e
`whatsapp_inbox/service.py:86`, que hoje só escapam por estarem na ALLOWLIST). Fazer isso direito
pede AST — e aí a lição do TEST-001 se aplica: **com o alias apenso desde o primeiro dia.**

---

## 4 · `test_projection_saldo_misto.py` — **tinha a mesma evasão. Miss meu no 1º gate.**

O coordenador estava certo em desconfiar. O arquivo tem **dois** coletores de import diferentes:

- `test_a_projecao_nao_reimplementa_o_saldo_bancario` usa `ast.alias`
  (`node.name.split(".")[-1]`) e **nunca teve o furo** — foi o que eu vi na primeira passagem e me
  fez marcar o arquivo como limpo;
- `test_dre_e_lucratividade_nao_importam_o_modulo_bank` tinha `importados.append(node.module or "")`
  — **a evasão exata**, no gate que protege a DRE.

**Provado por mutação:** `from app.modules import bank` dentro de `dre.py` → `1 passed`, gate verde
com a DRE importando o plano 3. É o gate cuja própria mensagem diz *"saldo de conta não é receita nem
despesa de competência — se entrou na DRE, entrou como número inventado"*.

**FECHADO por mim** (mesma correção dos outros três). Verificado: o mutante agora mata
(`FAILED test_dre_e_lucratividade_nao_importam_o_modulo_bank`), baseline `25 passed`.

**Correção do 1º gate:** onde a seção TEST-001 diz "três arquivos", são **quatro**. Aprendizado
registrado: *contar coletores, não arquivos* — um arquivo pode ter um coletor certo e outro errado, e
foi exatamente o que aconteceu aqui.

---

## CodeRabbit (re-gate)

Escopo reduzido aos 3 commits (`--committed --base-commit 4da2a2e`) — o combo sem `--committed`
disparou o falso positivo de 610 arquivos e o CLI recusou.

```
{"type":"complete","status":"review_completed","findings":3,"reviewedFiles":[17 arquivos]}
```

**Zero achados nos dois arquivos de código corrigidos** (`bank/service.py`,
`ContasSaldosPage.tsx`). Os 3 achados:

| Severidade | Onde | Destino |
|---|---|---|
| major | `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` — *"rode `scripts/check.sh` e os 3 agentes de QA"* | ❌ **Rejeitado, com motivo.** É leitura literal do `CLAUDE.md` §5 sem saber que a ferramenta está quebrada: `check.sh` mascara falha do vitest e resolve `ruff`/`python` do PATH (MNT-003). Rodar as etapas individualmente é evidência **estritamente mais forte**, não mais fraca. Trocar por um verde de `check.sh` seria rebaixar o gate |
| minor | `docs/stories/8.5.story.md` — *"sem achados atribuídos"* seguido de dois achados | ✅ **Aceito e corrigido** (texto meu, do 1º gate): passou a *"nenhum achado **bloqueante**"*, nomeando REL-002 e SIG-001 |
| minor | `CLAUDE.md` §6.1 — CPF/CNPJ | ✅ Confirma o DOC-002 que eu já havia levantado. Segue como follow-up; `CLAUDE.md` não é artefato do @qa |

> ⚠️ Os 4 arquivos de teste que **eu** alterei estavam sem commit e ficaram fora deste `--committed`.
> Nenhum foi revisado por máquina — mas cada um foi verificado por mutação, que é o critério que este
> gate usa e o mais forte dos dois para um arquivo de teste.

---

## Placar dos achados do 1º gate

| ID | Severidade | Estado |
|---|---|---|
| **BANK-001** | 🔴 HIGH | ✅ **FECHADO** — reproduzido, 3 bordas julgadas certas, 4 mutantes mortos |
| **TEST-001** | 🟠 MEDIUM | ✅ **FECHADO** — 4 coletores corrigidos (3 no 1º gate + 1 no re-gate) |
| **REL-001** | 🟠 MEDIUM | ✅ **FECHADO** — 5 mutantes, incluindo o par de sucesso que faltava |
| **UX-001** | 🟠 MEDIUM | 🔴 **ABERTO** — verificado: `projecao.ts:131` e `ConferenciaPage.tsx:239` inalterados. Decisão da `@architect` |
| **SIG-001** | 🟠 MEDIUM | 🔴 **ABERTO** — não tocado. Decisão da `@architect` |
| **MNT-001** | 🟠 MEDIUM | 🔴 **ABERTO** — 17 call sites com `target=''`. Pré-existente, follow-up |
| **G-4** (~360px) | ⚠️ aceite manual | 🔴 **ABERTO** — nenhuma evidência nova. Decisão do fundador |
| **MNT-002/003, REL-002, DOC-001/002/003** | 🟢 LOW | 🔴 Abertos, follow-up |
| **RG-1** | 🟢 LOW | ✅ **FECHADO** — teste do filtro de conta |
| **RG-2** | 🟢 LOW | 🔴 **ABERTO** — concordância singular/plural, cosmético |
| **RG-3** | 🟢 LOW | ✅ **FECHADO** — par de sucesso de `desfazerIgnorar` |
| **RG-4** | 🟢 LOW | ✅ **FECHADO** — glob do tenancy guard |

---

## O que ainda precisa de decisão antes do PR

| # | Item | Quem decide | Bloqueia o PR? |
|---|---|---|---|
| 1 | **UX-001** — qual tela cede a palavra *"no banco"*. Preferência do gate: renomear as colunas da Conferência para *"O que o banco diz"* × *"O que o e1p calculou"* | `@architect` | **Não** — mas fica mais caro depois que o usuário aprender o rótulo errado |
| 2 | **SIG-001** — a janela da conferência deve seguir o mês da DRE? | `@architect` | Não |
| 3 | **G-1** — `saldo_projetado_cents` precisa de irmão `*_origem`? A regra é sobre o prefixo `saldo_` ou sobre saldo? | `@architect` | Não |
| 4 | **G-4** — soltar para produção sem validar ~360px | **fundador** | Não bloqueia merge; **bloqueia release** |
| 5 | **MNT-001** (17 call sites) e **RG-2** (concordância) viram story de follow-up? | `@po` / fundador | Não |
| 6 | **RG-4 follow-up** — endurecer o tenancy guard para além de arquivos de rota (pede AST) | `@po` | Não |
| 7 | **DOC-003** — reconciliar epic/stories com a ratificação | `@pm` / `@po` | Não |

---

## Alterações feitas por este re-gate

| Arquivo | O que mudou | Autorização |
|---|---|---|
| `apps/api/tests/test_bank_accounts.py` | +1 teste: a guarda é **por conta** (mata MG4) | teste |
| `apps/api/tests/test_projection_saldo_misto.py` | coletor de import do gate da DRE passa a apensar o alias | teste |
| `apps/api/tests/test_tenancy_guard.py` | `_module_routers()` varre qualquer arquivo com `router` no nome | teste |
| `apps/web/src/features/financeiro/ContasSaldosPage.test.tsx` | +1 par de sucesso para `desfazerIgnorar` (mata MR5) | teste |
| `docs/stories/8.5.story.md` | *"sem achados"* → *"nenhum achado **bloqueante**"* (achado do CodeRabbit sobre texto meu) | seção do @qa |
| `docs/qa/epic-8-onda-0-1-gate-2026-07-30.md` | esta seção | artefato do gate |

**Nenhum código de produção foi alterado.** As 9 mutações desta passagem foram revertidas com
`git restore` imediatamente após cada execução, com a árvore verificada limpa a cada passo.

### Status das stories

Mantidos como estão — a transição é decisão do coordenador, não deste re-gate. A 8.2 segue em
`InProgress` (foi para lá pelo BANK-001, que está fechado) e as outras sete em `InReview`. Com o
veredito em **CONCERNS**, a transição natural das oito é `→ Done`; não a apliquei porque a 8.2 exige
o passo `InProgress → InReview → Done` e porque UX-001/G-4 podem mudar o desfecho conforme a decisão
do fundador.
