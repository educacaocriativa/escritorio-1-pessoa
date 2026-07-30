# Epic 8: Controle Bancário e Conferência

> **Classificação:** FEATURE NOVA (pós-go-live) — plano 3 do dinheiro (o extrato real do usuário) +
> conferência de completude. **Contém também um bug de dados em produção** (Onda 0), que é corrigível
> isoladamente.
> **Escopo liberado agora:** **Onda 0 + Onda 1** (decisão do fundador, 2026-07-29). Ondas 2, 3, 4 e 6
> entram como escopo **planejado, não liberado**; Onda 5 entra **bloqueada** com pré-requisito nomeado.
> **Sequenciamento:** depende do Epic 5 (Inteligência Financeira) **já entregue** — estende
> `financial_intelligence` (`projection.py`, `engine.py`, `diagnostics.py`) e `investments`. Independente
> dos Epics 6 e 7 (podem correr em paralelo). Internamente: Onda 0 → Onda 1.
> **Fonte:** design [`../architecture/controle-bancario-design.md`](../architecture/controle-bancario-design.md)
> (ratificado); ADR [`../decisions/0003-controle-bancario-nativo.md`](../decisions/0003-controle-bancario-nativo.md)
> (Aceito); pesquisa [`../research/2026-07-29-controle-bancario-requisitos-e-viabilidade.md`](../research/2026-07-29-controle-bancario-requisitos-e-viabilidade.md)
> (REQ-1..32); `CLAUDE.md` (sistema existente).
> **Este epic NÃO reabre o "o quê" nem o "como".** Ele organiza a execução do que já foi decidido.

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

**Head de migrations no momento deste epic: 0057** (`device_tokens`). O design encadeia a partir de
**0058**, uma migration por onda. O @sm/@dev deve **confirmar o head** no momento da implementação.

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
| **Baixa automática de Contas a Receber** | Bloqueada até a dívida `platform_earnings → transaction` existir (REQ-17; ver Onda 5) |
| **CNAB 240/400** | Fora do escopo até aparecer banco concreto que ofereça CNAB e não OFX (REQ-11) |
| **Uma tela de 43 linhas de extrato com checkbox como caminho principal** | O caminho principal é **a divergência em uma frase**; o extrato linha a linha é tela de investigação, alcançada a partir do sinal (design §5.2, §5.4) |

---

## 3. Business value e critério de sucesso mensurável

**Valor:** os três relatórios analíticos que o Epic 5 entregou (DRE, Lucratividade, Projeção/Runway)
**só valem o que vale a completude dos lançamentos que os alimentam**. Hoje ninguém sabe qual é essa
completude — nem o produto, nem o dono. A Onda 1 transforma "não sei se meus números estão completos"
num **número em reais**, por conta, medido contra a verdade externa (o saldo que o banco mostra). E a
Onda 0 remove, já, a pior combinação possível: precisão espúria (runway "faltam 43 dias") sobre
premissa falsa (saldo de plano errado).

### 3.1 O mecanismo do epic: a Onda 1 é o instrumento de decisão sobre as ondas seguintes

Isto é **mecanismo do epic, não aspiração**. Hoje **ninguém sabe o tamanho real do problema** — a
Onda 1 é o experimento mais barato para medi-lo (design §8; ADR 0003, Revisão futura (a)).

**Métrica primária (disponível a partir da Onda 1):** `|divergencia_cents|` **por conta**, por ciclo
de conferência, comparada à banda de tolerância — e `dias_desde_ultima_conferencia` como métrica de
uso. **A medição é por conta, nunca só consolidada** (ver §3.2).

**Métrica secundária (só a partir da Onda 3):** contagem de `movimentos_sem_contrapartida`. É esta que
responde literalmente ao REQ-13 ("quantos lançamentos faltantes foram encontrados") — a Onda 1 mede o
**tamanho em R$** do furo, não a contagem dos lançamentos que faltam. Dizer o contrário seria
prometer o que a Onda 1 não entrega.

**Regra de decisão (o gate deste epic):**

| Leitura da Onda 1 | Decisão |
|---|---|
| Divergência tipicamente **dentro** da banda de tolerância e estável | **Parar na Onda 2.** Ondas 3 e 4 são over-engineering e **não** são liberadas. Este é um desfecho **bom**, não um fracasso (ADR 0003, Revisão futura (a)) |
| Divergência **fora** da banda, recorrente, e o dono não consegue explicar de onde vem | Liberar Onda 3 (importação) — o furo precisa ser **localizado**, não só quantificado |
| Divergência fora da banda mas explicada por causa conhecida e pontual | Corrigir a causa; **não** liberar Onda 3 |

**Janela de observação sugerida:** 3 ciclos mensais de conferência no tenant do fundador antes de
decidir — `[SUPOSIÇÃO DO @PM]`, não vem do design nem da pesquisa; ajustar quando houver mais tenants
usando. A **decisão** de liberar ou não as ondas seguintes é do fundador, com o número na mão.

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
   `{plataforma, banco, misto, declarado, indisponivel}`.
   Isto entra como **teste estrutural** (`tests/test_money_planes.py`), no mesmo estilo do
   `tests/test_tenancy_guard.py` já existente. Sem o teste, o resto degrada por acidente.
2. **Regra da Neutralidade (design §3.5, a partir da Onda 2):** transferência entre contas próprias é
   exclusivamente evento do plano 3 — nunca cria/altera/baixa `Charge`, `Payable` ou `Transaction`, e
   por isso não aparece na DRE, na Lucratividade nem na Projeção como entrada/saída (REQ-20, REQ-21).
3. **Caixa vs. competência nunca se invertem:** fluxo de caixa usa `paid_at`; DRE/lucratividade usam
   `competence_date` (`payables/models.py:6-9`, `receivables/models.py:6-9`).
4. **Anonimizador obrigatório** antes de qualquer chamada de IA que toque `raw_description`,
   `counterparty_name` ou `counterparty_document` — extrato carrega PII de terceiro que nunca
   contratou com a e1p (Regra de Ouro nº 2 / REQ-18 / design §7.4). Aplicável a partir da Onda 3/4.
5. **IA sugere, usuário confirma.** A IA nunca escreve `confirmed_at` e nunca dá baixa (REQ-15,
   design §4.6).
6. **Zero custo recorrente novo** (Regra de Ouro nº 4) e **zero chamada de rede** no pipeline de
   importação.
7. **Não quebrar o que funciona** (Regra de Ouro nº 5): cada story roda `scripts/check.sh` + os 3
   agentes de QA, traz testes novos e validação e2e de isolamento cross-tenant no **Postgres real**
   (`pytest.mark.rls_e2e`, testcontainers, job `cross-tenant-rls`).

---

## 5. Escopo por ondas

> Cada onda entrega valor sozinha e pode parar ali sem deixar o produto pela metade (design §8).
> Esforço em **ondas de trabalho** `[ESTIMATIVA do design]`, não em horas — não há velocity confiável.

| Onda | Entrega | Status | Migration | Esforço `[EST.]` | Depende de |
|---|---|---|---|---|---|
| **0** | Saldo inicial honesto (bug) | ✅ **APROVADA** | — | 0,25 | nada |
| **1** | Contas + saldo derivado + conferência de um número, por conta | ✅ **APROVADA** | 0058 | 1,5 | Onda 0 (recomendado) |
| **2** | Transferências + aplicação como conta + `principal_cents` derivado | 📋 **PLANEJADA** (não liberada) | 0059 | 1,5 | Onda 1 |
| **3** | Importação OFX/CSV + órfãos dos dois lados | 📋 **PLANEJADA** (não liberada; sujeita ao gate §3.1) | 0060 | 2,5 | Onda 1 + verificação empírica de OFX real |
| **4** | Sugestão de vínculo (regra → IA) + baixa de Contas a **Pagar** | 📋 **PLANEJADA** (não liberada; sujeita ao gate §3.1) | 0061 | 2,0 | Onda 3 |
| **5** | Baixa de Contas a **Receber** a partir do extrato | 🚫 **BLOQUEADA** | 0062+ | 1,0 (pré-req.) + 1,0 | **dívida `platform_earnings → transaction`** |
| **6** | Payout da Carteira fecha o circuito | 📋 **PLANEJADA** (não liberada) | 0063 | 0,5 | Onda 1 |

**Ordem recomendada:** 0 → 1 → 2 → 3 → 4 → 6, com a 5 **fora da fila**.

### Onda 0 — Saldo inicial honesto ✅ APROVADA

Bug independente de tudo. Zero tabela, zero migration.

- `CashProjection` ganha `saldo_inicial_origem` ∈ `{plataforma, banco, misto, indisponivel}` e uma
  `note` explícita — o campo `notes: list[str]` já existe exatamente para isso (`_NOTE_CAIXA`,
  `_NOTE_OVERDUE`), é padrão da casa, não invenção. → design §6.1, REQ-3
- **O runway deixa de ser exibido em dias** quando `origem == "plataforma"`; vira faixa qualitativa ou
  desaparece. → design §6.1
- **Critério de pronto:** nenhum usuário vê runway em dias derivado de saldo cuja origem não está
  declarada na própria tela. → design §6.1

### Onda 1 — Contas, saldo e a conferência de um número ✅ APROVADA

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

### Onda 2 — Transferências, aplicação como conta, `principal_cents` derivado 📋 PLANEJADA

`bank_transfers` (duas pernas, DRE-neutro por construção); UI de aporte/resgate/transferência;
`investment_accounts.bank_account_id` (faceta de produto 1:1, `investment_accounts` **não** é
absorvida); migração de dados de `principal_cents` → derivado; `register_yield` passa a gerar também
um `bank_transaction` **nascido conciliado**; extrato da aplicação no `InvestimentosPage`;
`update_account` rejeita (409) editar `principal_cents`.
→ design §2.6, §3.2, §3.4, §3.5, §6.2, §6.3; REQ-20..REQ-26; **R3 do fundador atendido integralmente**.
⚠️ Contém o **único backfill sobre dado existente** deste epic — exposto à armadilha do FORCE RLS.

### Onda 3 — Importação de extrato (parser plugável, sem match automático) 📋 PLANEJADA

`bank_import_batches`; `StatementParser` como strategy + `OfxSgmlParser` + `OfxXmlParser` +
`CsvParser`; dedup por `dedup_hash` com constraint única (fail-closed); enriquecimento antes de
inserir (evita dupla contagem transferência × extrato); checkpoint a partir do `<LEDGERBAL>`;
**conferência blocos 2 e 3** (movimentos órfãos e lançamentos sem extrato); ações manuais por linha.
→ design §2.5, §4.1–§4.5, §5.1; REQ-5..REQ-12.
**É a onda cara, e o custo é permanente** (parser por banco é manutenção perpétua — ADR 0003,
Consequência 1). **Sujeita ao gate do §3.1** e a uma verificação empírica prévia (§8, dependência D3).

### Onda 4 — Sugestão de vínculo (regra → IA) e baixa de Contas a Pagar 📋 PLANEJADA

`bank_reconciliations` como **tabela de ligação** (suporta N:N: um Pix quitando duas contas; uma conta
paga em dois movimentos); matcher determinístico primeiro, IA classificando/ranqueando depois **sob
anonimizador**; `confirmed_at=NULL` = sugestão; baixa de `Payable` só após confirmação do usuário.
→ design §2.3, §4.6, §4.7; REQ-14, REQ-15, REQ-18, REQ-19. **Sujeita ao gate do §3.1.**

### Onda 5 — Baixa de Contas a Receber a partir do extrato 🚫 BLOQUEADA

> **Pré-requisito absoluto e nomeado:** existir o vínculo **`platform_earnings → transaction`**
> (migration + ajuste do ledger global do Master), reabilitando o estorno de `Charge`.
> **Enquanto isso não existir, esta onda não começa.**

**Decisão do fundador (2026-07-29): a dívida NÃO será paga agora.** Logo a Onda 5 fica **fora da
fila** deste epic (responde D4 do design com "não").

**Por que o bloqueio é duro:** o estorno de Contas a Receber foi implementado, revisado em duas
rodadas e **removido antes do merge** porque `platform_earnings` não guarda vínculo de volta à
`Transaction`/`Charge` de origem — pagar → estornar → pagar de novo duplicaria o GMV no painel do
Master (`docs/superpowers/specs/2026-07-27-estornar-conta-paga-design.md`, Adendo; `CLAUDE.md`). Um
matcher **vai** produzir baixas indevidas (é estatística, não pessimismo) e hoje **não existe caminho
seguro de desfazer**. → REQ-17; design §4.7; ADR 0003, Consequência 6.

**Isto não bloqueia o lado do pagar**, que é o objetivo declarado: `Payable` nunca move a Carteira e
já tem `POST /payables/bills/{id}/reverse` (REQ-14, REQ-17 nota). E o que entrega quase todo o valor
**é permitido antes**, dentro da Onda 4: vínculo **informativo** movimento ↔ cobrança já paga (não
muda status, não move dinheiro) e **sinalização** do tipo *"esta cobrança está em aberto há 47 dias e
existe um crédito de mesmo valor no extrato"* — o dono decide o que fazer (design §4.7).

### Onda 6 — Payout da Carteira fecha o circuito 📋 PLANEJADA

`request_payout` emite evento via `core/events` (mantendo `wallet` sem importar `bank`) → o módulo
`bank` cria `bank_transfer(kind='wallet_payout')` + crédito na conta primária; card do Cockpit com as
duas parcelas rotuladas; **graceful degradation** sem conta cadastrada (nada acontece, nada quebra).
→ design §1.2, §6.5, §6.6.

### 5.1 Ponto de parada legítimo — decisão consciente, não escopo automático

> **As Ondas 3 e 4 NÃO são escopo automático deste epic.** O design registra explicitamente que, se a
> divergência medida na Onda 1 for **pequena e estável**, elas são **over-engineering e devem ser
> adiadas** (design §8; ADR 0003, Revisão futura (a) — *"este é um desfecho bom, não um fracasso"*).

O ponto de parada natural é **depois da Onda 2**: nesse estado o e1p tem conta bancária de primeira
classe, saldo derivado confiável, projeção/runway verdadeiros, aporte/resgate visíveis e a conferência
de um número por conta. Isso é um produto completo, não um produto pela metade — é exatamente a
Alternativa A do ADR 0003, absorvida em vez de descartada.

**Este epic proíbe tratar 3 e 4 como consequência inevitável de 1 e 2.** Só o número da §3.1, com o
fundador decidindo, libera a Onda 3. Registrar isto aqui é o mecanismo que impede o escopo de crescer
por inércia.

---

## 6. Stories previstas — Onda 0 e Onda 1

> **Só nomeadas e delimitadas.** Escrever a story completa (As a / I want / so that, Acceptance
> Criteria, Integration Verification, tasks) é do **@sm** via `create-next-story.md`.
> A decomposição em stories é `[DECOMPOSIÇÃO DO @PM]` — os **itens de escopo** vêm do design §8; o
> corte entre stories não. O @sm/@po pode reagrupar, desde que nenhum item da §5 caia fora.
> Ordem = ordem de dependência.

### Onda 0

**Story 8.1 — Saldo inicial honesto na Projeção de Caixa (origem declarada + runway suprimido)**
`CashProjection` passa a expor `saldo_inicial_origem` + `note` explícita, e a UI deixa de exibir
runway **em dias** enquanto a origem for `"plataforma"`.
*Não inclui:* nenhuma tabela nova, nenhuma migration, nenhuma mudança na fórmula da projeção além do
rótulo de origem e da supressão do runway. → design §6.1; REQ-3

### Onda 1

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
*Não inclui:* `origin='ofx'` (vem com a Onda 3); histórico/gráfico de saldo. → design §2.4

**Story 8.5 — Conferência bloco 1: a divergência em uma frase, por conta**
Serviço **read-only** que compara `saldo_banco` (checkpoint) × `saldo_sistema` (derivado) **na mesma
data de referência**, aplica a banda de tolerância `max(R$ 50, 0,5%)` configurável e devolve a
divergência **por conta** — recusando-se a comparar datas diferentes e declarando
`origem='indisponivel'` quando não há checkpoint na janela.
*Não inclui:* blocos 2 e 3 (órfãos dos dois lados, que dependem de conciliação — Onda 3); consolidado
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

**Total previsto: 8 stories** (1 na Onda 0, 7 na Onda 1).

---

## 7. Riscos

| Risco | Prob. | Impacto | Mitigação já desenhada | Fonte |
|---|---|---|---|---|
| **Planos de dinheiro voltarem a se misturar** (é o bug original, numa forma nova) | Média ao longo do tempo | Alto | Regra dos Planos com **teste estrutural de import** + campo `*_origem` obrigatório. Sem o teste, degrada por acidente: basta uma story futura importar o módulo errado | design §1.3, §11 |
| **Divergência agregada esconder problemas** (várias contas PJ em bancos diferentes) | **Alta** se a conferência for consolidada | Alto — mata o poder de diagnóstico, que é o produto | Conferência **por conta** obrigatória; consolidado só com decomposição visível | **fundador D2 (2026-07-29)**; §3.2 deste epic |
| **Abandono da conferência** ("última conferência há 94 dias") | Média | Médio | O sistema **declara que não sabe** em vez de culpar; `dias_desde_ultima_conferencia` permite a frase honesta; o gancho é utilidade, não obrigação | design §5.1, §11 |
| **Produto virar ERP contábil e perder o público** | Média | **Existencial para a tese** | Rótulo "Contas & Saldos"; a frase antes da tabela; conferência funciona **sem** import. **Sintoma observável:** a tela de linhas virar a mais acessada do financeiro | design §9, §11; ADR 0003 Consequência 2 |
| **Escopo crescer por inércia até a Onda 3/4** sem o número justificar | Média | Alto (2,5 + 2,0 ondas de custo permanente) | §5.1 + gate do §3.1: liberar 3 exige o número na mão e decisão do fundador | design §8; ADR 0003 Revisão futura (a) |
| **Parser por banco vira manutenção perpétua** (Onda 3+) | **Alta — é certeza, não risco** | Médio, recorrente e imprevisível | Strategy plugável; falha de parse **fail-loud**, nunca grava lixo em campo imutável; começar com 1–2 formatos. **É o preço direto de "não contar com terceiros"** e foi aceito de olhos abertos | ADR 0003 Consequência 1; design §11 |
| **Janela de ~60 dias de extrato reintroduz dependência de disciplina** | Alta (Onda 3+) | Alto — dado perdido é irrecuperável | `opening_balance_cents` como âncora; lembrete de cadência; a conferência da Onda 1 não depende de arquivo | REQ-9; pesquisa R4; design §2.1 |
| **`MEMO` do OFX não verificado** — toda promessa de match por contraparte repousa nele | Média/Alta | Médio — o match cai para valor+data, mais fraco | **Verificar empiricamente com arquivos reais de 3–4 bancos ANTES de comprometer escopo da Onda 3** | REQ-19; pesquisa R5 |
| **Dupla contagem transferência × extrato** | **Alta** (Onda 2+3 juntas) | Alto | Passo de enriquecimento antes de inserir + constraint única + marcação "possível duplicata" quando ambíguo (não adivinha) | design §4.5, §11 |
| **Resgate de aplicação virando receita fantasma** | Média sem cuidado | Alto | Regra da Neutralidade + guarda de `target_type` no vínculo + teste de snapshot da DRE. Duas defesas independentes | design §3.5, §11; REQ-25 |
| **Baixa indevida de `Charge` sem caminho de desfazer** | Alta **se permitida** | **Crítico** (GMV duplicado no painel do Master) | Onda 5 bloqueada; ausência do endpoint + guarda de `target_type` | design §4.7; REQ-17 |
| **PII de contraparte vazando para a IA** (CPF de quem nunca contratou com a e1p) | Média sem disciplina | Alto (LGPD) | Anonimizador obrigatório inclusive na classificação; minimização na extração; teste com espião no `core/ai` | design §4.6, §7.4; REQ-18 |
| **Backfill silencioso a zero linhas sob FORCE RLS** (Onda 2) | **Alta se esquecido** | Alto | Documentado no design; disciplina da migration 0046; SQLite dos testes **não pega** | design §2, §6.2 |
| **Vender a feature como "conformidade com a reforma tributária"** | — (evitável por decisão) | Médio — envelhece mal e expõe a contestação por qualquer contador | **Vetado** por decisão do fundador (§2.1) | REQ-28; pesquisa R1, §1.6 |
| **Arquivo de extrato acessível por outro usuário do mesmo tenant** | Média | Médio (documento financeiro completo) | Dívida **herdada e não resolvida** por este epic: `owner_type='bank_import'` nasce com o mesmo problema da bandeja de comprovantes. Quando `/attachments` for endurecido (checar dono, não só tenant), `bank_import` entra na mesma varredura | design §6.8; `CLAUDE.md` |

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

| # | Dependência | Onda | Situação |
|---|---|---|---|
| D5 | **Vínculo `platform_earnings → transaction`** | 5 | 🚫 **Não será feito agora** (decisão do fundador). Onda 5 fora da fila |
| D6 | **Verificação empírica de OFX real** (3–4 bancos do público-alvo): o formato ainda é exportado? o `MEMO` carrega contraparte/CPF? o `endToEndId` do Pix aparece? | 3 | ⏳ Pendente — **@analyst**. Se nenhum banco relevante exportar OFX em 2026, o caminho de arquivo morre e as Ondas 0–2 sobrevivem intactas (ADR 0003, Revisão futura (b)) |
| D7 | **Payout real** (`request_payout` hoje só marca `withdrawn`; exige dados bancários + KYC) | 6 | ⏳ Não decidido (D5 do design). Default: Onda 6 permanece registro contábil, sem transferência real |
| D8 | **O número da Onda 1** (o gate do §3.1) | 3, 4 | ⏳ Só existe depois de a Onda 1 rodar em produção por alguns ciclos |

**Externas:** nenhuma. Zero serviço de terceiro no caminho crítico, zero custo recorrente novo
(ADR 0003, Consequência positiva 10).

---

## 9. Decisões do fundador registradas (2026-07-29) e pendências

**Decididas — não reabrir:**

| # | Decisão | Onde reverbera |
|---|---|---|
| F1 | **Controle bancário nativo, sem agregador de Open Finance.** Pluggy, Belvo, Klavi (e correlatos) **vetados por decisão de dependência**, não por preço. Arquivo (OFX/CSV) é aceitável | ADR 0003; §2.1 |
| F2 | **Escopo imediato aprovado: Onda 0 + Onda 1.** Ondas 2–6 são escopo planejado, não liberado | §5 |
| F3 | **Topologia: várias contas PJ** (corrente + poupança + aplicação, possivelmente em bancos diferentes). Não é conta PF misturada. Suportar N contas desde a Onda 1; **conferência por conta**, não só consolidada | §3.2; Story 8.2, 8.5 (responde **D2** e, por consequência, **D3** do design) |
| F4 | **A dívida `platform_earnings → transaction` não será paga agora** | Onda 5 bloqueada (responde **D4** do design com "não") |
| F5 | **Não posicionar como conformidade com a reforma tributária.** A justificativa é conferência e controle interno; a e-Financeira é **contexto de risco de divergência**, não obrigação | §2.1 (responde REQ-28) |

**Pendentes — com default do design adotado até haver resposta:**

| # | Pergunta | Default adotado | Onda |
|---|---|---|---|
| D1 | Banda de tolerância `max(R$ 50, 0,5%)` serve, ou quer fechar em zero? | Adotar o default e torná-lo configurável por tenant | 1 |
| D5 | Payout real entra no roadmap? | Não; Onda 6 fica como registro contábil | 6 |
| D6 | Carteira Asaas como `bank_account` (`kind='platform_wallet'`)? | **Não** criar; o valor fica reservado no vocabulário | — |
| D7 | A conferência deve sinalizar crédito no extrato sem cobrança correspondente? | Sinalizar como informação neutra **ao dono**, nunca reportar ao Master | 3, 5 |
| D8 | O vocabulário de `operation_nature` vem do contador? | Usar o vocabulário sugerido pelo design, como texto livre | 3+ |

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

---

## 11. Conflitos com épicos existentes — o que este epic supersede

> Registrado aqui para que o @sm não escreva story contra um AC que este epic revogou.

**11.1 Epic 5, Story 5.7, AC1** diz que a projeção parte *"do saldo disponível atual da Carteira"*.
**A Onda 0 deste epic (Story 8.1) declara isso incorreto e a Onda 1 (Story 8.8) o substitui** por
saldo bancário derivado + `available_cents`, com origem rotulada. O AC1 da 5.7 fica **superado** a
partir da Story 8.8 — não é regressão, é correção de bug (design §6.1; ADR 0003, alternativa F).

**11.2 Epic 5, Story 5.6, AC1** trata *"principal aplicado"* como campo da entidade de investimento.
**A Onda 2 torna `principal_cents` derivado** (Σ aportes − Σ resgates) e faz `update_account`
rejeitar sua edição. O AC1 da 5.6 fica superado **quando a Onda 2 for liberada** — enquanto a Onda 2
não for liberada, o comportamento atual permanece válido (design §3.2, §6.2; REQ-23).

**11.3 Nada em Epics 1–4, 6 e 7 conflita** com este epic. Epic 7 (cobertura de testes) é
**complementar**: os testes estruturais da Regra dos Planos seguem o mesmo estilo do
`test_tenancy_guard.py` que a Story 7.1 endurece no CI.

### 11.4 Divergências entre o design e a pesquisa — não resolvidas aqui

> Ambos os documentos estão ratificados, e nestes três pontos eles **não dizem a mesma coisa**. Nenhuma
> afeta a Onda 0 ou a Onda 1 (o escopo liberado). Registradas para serem **resolvidas por @architect +
> fundador antes de a onda correspondente ser liberada** — não por quem estiver escrevendo a story.

| # | Divergência | Onda | Encaminhamento |
|---|---|---|---|
| **C1** | **Layout de CSV.** REQ-10: CSV é fallback, exige **mapeamento explícito de colunas pelo usuário**, e é *"proibido manter tabela de layouts conhecidos por banco"*. Design §4.1/§4.3: layouts de CSV **em YAML por banco** (`app/modules/bank/layouts/*.yaml`), com mapeamento por tenant marcado como onda posterior. É contradição direta, não nuance | 3 | Decidir **antes** de a Onda 3 começar. A tensão real é custo de manutenção perpétua (REQ-10 protege contra isso) × fricção para o usuário (o design protege contra isso). Prioridade baixa hoje: a Onda 3 não está liberada |
| **C2** | **`register_yield`.** REQ-24: *"`register_yield` **não muda**"*. Design §3.4(b): passa a criar **também** um `bank_transaction` de `source='yield'` já conciliado. **Leitura do @pm:** compatíveis no que importa — o caminho `Charge`/DRE/competência fica **idêntico** (a garantia IV1 da Story 5.6, "nunca chamar `mark_paid`/`build_transaction`", permanece), e o que se adiciona é o movimento no plano 3. Ainda assim, a letra do REQ-24 é mais restritiva que o design | 2 | Tratar como **resolvida em favor do design**, com a garantia IV1 da Story 5.6 explicitamente reafirmada no AC da story da Onda 2 |
| **C3** | **Porta de entrada do arquivo.** REQ-12: reaproveitar a entrada de arquivo que já existe (share sheet / bandeja de comprovantes), **não criar fluxo de upload paralelo**. Design §4 passo [1]: `POST /bank/accounts/{id}/imports` (rota nova), reusando `attachments` + `core/storage` por baixo | 3 | O reuso do design é de **persistência**, não de **porta de entrada** — que é justamente o ponto do REQ-12 (reduzir fricção da ação do usuário, pesquisa §3.4). Decidir se o extrato também entra pelo share sheet **antes** da Onda 3 |
